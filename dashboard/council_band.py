"""THE COUNCIL BAND (task #104, 2026-10-22): what Sauron thinks now, who
disagrees and who has been right, on the right edge of every staff page.

The council of ten (ai_agents/agents/council.py) sits on live trades and
is graded on what the market did next (ai_agents/council_grading.py).
This module reads what it recorded and says it in plain English for the
band (templates/_partials/council_band.html, static/js/sv-council-band.js,
served by dashboard/views_council_band.py). It reads; it never writes,
never sends, never asks a model.

THE TRUTH CONTRACT, which every sentence below keeps:
  - Only recorded figures. The band grades nothing and computes no weight:
    a weight is the one the Emperor READ at a sitting (CouncilSession
    .weights, CouncilVoice.weight_seen) or the one the council's own record
    matrix states (council_grading.record_matrix). The council's reader of
    live weights is pinned to three modules (tests/test_council_shadow.py)
    and is neither called nor named here.
  - A dash, "not measured" or "unmeasured" is said where nothing was
    measured; absent is never zero, and an unread mood is never calm.
  - Every number says which book it covers (the live record, 180 days; your
    book as the gates read it; the real-money book, world live).
  - No money: R and percent only. AI spend is a percent of the day's
    core-line allowance; no dollar figure leaves this module, and a line a
    voice wrote that names an amount is withheld whole.
  - No exception text and no raw `why`: each stored reason is mapped to a
    fixed sentence, and anything unmatched maps to nothing.
  - Live sittings only: a debate argued on a rehearsal client (venue
    "demo") is not read at all, and a live sitting whose order filled in a
    rehearsal world, or a repeat, is said as such, never as "no order sent".

THE COST: panels are read once and cached, each with its own TTL and its
own fence (a panel that fails says its sentence; the others render). A
cold room is about 66 queries (record_matrix 20 and the mood 17 of them,
measured); a warm one costs none. A shut band, a hidden tab and a phone
read nothing at all: only the open band's script asks.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import timedelta, timezone as dt_tz
from types import SimpleNamespace

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

V = 2
DASH = "—"
CACHE_PREFIX = "council_band:v2"
#: An event read rebuilds the panels it wakes only when their cached copy
#: is at least this old: a burst of fills is one read.
EV_MIN_AGE_S = 5
EVENTS = ("fill_open", "fill_close", "council_sitting")
SITTINGS_DAYS = 7
SITTINGS_MAX = 20
BATTLE_DAYS = 30
SNAPSHOT_DAYS = 30
SNAPSHOT_ROWS = 60
FACTS_MAX = 900
LINE_MAX = 300
REASONS_MAX = 5
RULINGS_MAX = 3
HISTORY_MAX = 20
BEST_MAX = 3
DISSENT_SHOWN = 2

#: Seconds each data panel is kept.
TTL = {"switches": 60, "phase": 300, "regime": 300, "sittings": 60,
       "snapshot": 300, "record": 600, "battles": 300, "war": 120,
       "ai": 120, "mood": 300, "horizon": 3600, "traders": 600}
#: The panels read for the viewer's own book; the rest are the platform's.
USER_SCOPED = frozenset({"war", "mood", "traders"})
#: What each event wakes.
WAKE = {"fill_open": {"sittings", "war"},
        "fill_close": {"phase", "sittings", "battles", "war", "mood",
                       "traders"},
        "council_sitting": {"sittings", "snapshot", "record"}}

SWITCH_KEYS = ("platform_master", "trade_debate", "council_bots",
               "council_ticket")

# ── the seats and the voices ──────────────────────────────────────────────

#: The round table: two benches facing each other (the right argues for,
#: the left tests and doubts), opposite temperaments mirrored across it;
#: the Emperor in the centre. (voice, angle clockwise from the top.)
SEATS = (("awakened", 0), ("champion", 40), ("opportunist", 80),
         ("gambler", 120), ("striker", 160), ("theorist", 200),
         ("fixer", 240), ("skeptic", 280), ("executioner", 320))
MONO = {"executioner": "EX", "champion": "CH", "skeptic": "SK",
        "awakened": "AW", "theorist": "TH", "opportunist": "OP",
        "striker": "ST", "fixer": "FI", "gambler": "GA", "emperor": "EM"}
TRIADS = (
    {"key": "trial", "title": "THE TRIAL",
     "sub": "against, for, and the evidence",
     "voices": ("executioner", "champion", "skeptic")},
    {"key": "sight", "title": "THE SIGHT", "sub": "what the market hides",
     "voices": ("awakened", "theorist", "opportunist")},
    {"key": "move", "title": "THE MOVE", "sub": "what to do now",
     "voices": ("striker", "fixer", "gambler")},
)
#: What each voice is for, as its own prompt says it (council.py).
ROLE = {
    "executioner": "Why the trade fails.",
    "champion": "Why it works.",
    "skeptic": "Attacks the evidence of the other voices, never the trade.",
    "awakened": "The trap, the hunter and the prey, from cited footprints only.",
    "theorist": "Falsifiable theories, graded in the hypothesis market.",
    "opportunist": "What the crowd misses, or a better trade elsewhere.",
    "striker": "One decision now: take it, wait for a touch, or skip it.",
    "fixer": "The one flaw that matters, and its repair.",
    "gambler": "How hard to press, never past the limits.",
    "emperor": ("The chair: the war over the battle. He weighs every voice "
                "by its record."),
}
#: The short chip for a verdict, keyed by (voice, verdict): "pass" is the
#: Executioner letting a trade through and the Opportunist finding nothing.
VERDICT_TOKENS = {
    ("executioner", "pass"): "PASS", ("executioner", "cut"): "CUT",
    ("executioner", "veto"): "VETO",
    ("champion", "back"): "BACK", ("champion", "neutral"): "NEUTRAL",
    ("opportunist", "seize"): "SEIZE",
    ("opportunist", "elsewhere"): "ELSEWHERE",
    ("opportunist", "pass"): "PASS",
    ("striker", "take"): "TAKE", ("striker", "wait"): "WAIT",
    ("striker", "skip"): "SKIP",
    ("fixer", "fix"): "FIX", ("fixer", "no_fix"): "NO FIX",
    ("gambler", "all_in"): "ALL IN", ("gambler", "press"): "PRESS",
    ("gambler", "normal"): "NORMAL", ("gambler", "small"): "SMALL",
    ("skeptic", "sound"): "SOUND", ("skeptic", "shaky"): "SHAKY",
    ("skeptic", "unfounded"): "UNFOUNDED",
    ("awakened", "trap"): "TRAP", ("awakened", "clean"): "CLEAN",
    ("awakened", "unread"): "UNREAD",
    ("theorist", "serves"): "SERVES",
    ("theorist", "contradicts"): "CONTRADICTS",
    ("theorist", "none"): "NO THEORY",
    ("emperor", "fight"): "FIGHT", ("emperor", "fight_smaller"): "SMALLER",
    ("emperor", "refuse"): "REFUSE",
}
#: A side, as the council measures it (council.claim_side), and its mark.
SIDE_GLYPH = {"for": "▲", "against": "▼", "none": "●", "silent": "○",
              "waiting": "…", "absent": "—"}
CHAIR_GLYPH = {"fight": "●", "fight_smaller": "◐", "refuse": "✕"}
SPOKEN = ("spoke", "copied", "late")

GRADE_WORDS = {"right": "right", "wrong": "wrong",
               "unresolvable": "not resolvable",
               "ungraded": "not graded, by rule",
               "refused": "refused at the door", "pending": "pending"}
#: What each claim of a transcript is graded on, in words.
CLAIM_WORDS = {"work": "works or not", "stance": "for or against",
               "battle": "the battle", "attack": "the attack",
               "fix": "the fix", "trigger": "the wait", "touch": "the level",
               "direction": "the direction", "theory": "the theory",
               "boldness": "the size"}

# ── the static labels the script prints (one <span> each in the partial) ──

WORDS = {
    "tab": "COUNCIL",
    "tab_title": "The council: what Sauron thinks, who disagrees, who has been right (c)",
    "badge_label": "{n} new sittings since you last looked",
    "tab_label": "The council",
    "title": "THE COUNCIL",
    "title_chamber": "THE COUNCIL CHAMBER",
    "widen": "Widen the council (Shift+C)",
    "narrow": "Narrow the council (Shift+C)",
    "no_room": "Not enough room to widen: close the rail or fold the sidebar.",
    "no_room_horde": "Close the Horde to widen the council.",
    "close": "Close the council (Esc)",
    "read_ago": "read {t}",
    "not_live": "read {t} UTC · not live",
    "calling": "Calling the council",
    "locked": "Locked. The council carries on once the PIN is entered.",
    "signed_out": "Signed out. Sign in again to see the council.",
    "staff_only": "Staff only. This account cannot see the council.",
    "cannot_reach": "Cannot reach Sauron. Retrying; the figures below are from {t}.",
    "narrowed_room": "Council narrowed: not enough room.",
    "narrowed_horde": "Council narrowed: the Horde is open.",
    "sat_on": "The council sat on {s}.",
    "not_sat": "The council did not sit on {s}.",
    "thinks": "SAURON THINKS",
    "disagrees": "WHO DISAGREES",
    "right": "WHO HAS BEEN RIGHT",
    "throne": "THE THRONE",
    "nine": "THE NINE",
    "traders": "THE TRADERS",
    "campaign": "THE CAMPAIGN",
    "hand": "THE EMPEROR'S HAND",
    "hand_now": "THE SEAT PER CELL, NOW",
    "hand_last": "AT THE LAST SITTING",
    "hand_against": "THE EMPEROR AGAINST HIS HAND",
    "mood": "THE PEOPLE'S MOOD",
    "war": "THE WAR, AS THE GATES READ IT",
    "posture": "POSTURE",
    "horizon": "HORIZON",
    "battles": "BATTLES · 30 DAYS",
    "chair_record": "THE CHAIR'S RECORD",
    "rulings": "LAST RULINGS",
    "orcs": "THE ORCS",
    "emperor": "The Emperor",
    "open_dossier": "Open the dossier of {name}",
    "fold": "Fold or unfold {name}",
    "sittings_link": "The sittings ›",
    "record_link": "The record ›",
    "tab_sittings": "The sittings",
    "tab_record": "The record",
    "back_council": "‹ Back to the council",
    "back_sittings": "‹ Back to the sittings",
    "back_sitting": "‹ Back to the sitting",
    "chamber_tabs": "Chamber",
    "filter_all": "All",
    "filter_bot": "Bot orders",
    "filter_ticket": "Tickets",
    "filter_dissent": "Dissent only",
    "show_older": "Show older",
    "no_sitting_7": "No sitting in the last 7 days.",
    "nothing_kind": "No sitting of this kind among those shown.",
    "loading": "Reading…",
    "t_emperor": "THE EMPEROR",
    "t_dissent": "DISSENT",
    "t_others": "THE OTHERS",
    "reasons": "Reasons ({n})",
    "open_trade": "Open trade #{id} ›",
    "ask_sitting": "Ask Sauron about this sitting",
    "ask_voice": "Ask Sauron about {name}",
    "r_hand": "THE HAND, CELL BY CELL",
    "r_against": "THE EMPEROR AGAINST HIS HAND",
    "r_skeptic": "THE SKEPTIC TOLD",
    "r_mood": "THE MOOD, GRADED",
    "r_weights": "WEIGHTS BY REGIME",
    "r_weights_note": "Live record, 180 days, every class. A cell is measured at 10 graded calls; below that it reads —.",
    "r_bench": "DOES WEIGHTING HELP?",
    "d_weight": "WEIGHT AS THE EMPEROR LAST READ IT",
    "d_regimes": "RECORD BY REGIME",
    "d_regimes_note": "A cell is measured at 10 graded calls; below that it reads —. Live record, 180 days, every class.",
    "d_table": "THE TABLE",
    "d_hand": "THE EMPEROR'S HAND",
    "d_best": "BEST CALLS",
    "d_worst": "WORST CALLS",
    "d_history": "HISTORY",
    "d_today": "CALLS TODAY",
    "d_loading": "Reading this voice…",
    "d_failed": "This voice could not be read. The rest of the council is current.",
    "s_loading": "Reading this sitting…",
    "s_failed": "This sitting could not be read. The rest of the council is current.",
    "side_for": "for",
    "side_against": "against",
    "side_none": "no side",
    "side_silent": "silent",
    "side_waiting": "waiting",
    "side_absent": "not asked",
    "seat_label": "{name}: {side}",
    "chair_none": "no chair",
    "matrix_label": "{label} in {regime}: ×{f} {lane}",
    "regime_now": "now",
}

# ── the server's sentences ────────────────────────────────────────────────

NO_SESSION = ("The council has not sat yet. Every live entry the debate "
              "argues is recorded here; the eight sit once a live bot order "
              "has left (council_bots on), or when someone asks on a live "
              "ticket (council_ticket on).")
NO_SITTING_7 = "No sitting in the last 7 days."
WITHHELD = "Withheld: this line may name an amount of money."
#: A panel that could not be read says this; its exception stays in the log.
SENTENCE = {
    "switches": "The switches could not be read.",
    "phase": "The debate's phase could not be read.",
    "regime": "The regime and the posture could not be read.",
    "sittings": ("The sittings could not be read. The rest of the council "
                 "is current."),
    "snapshot": "The weights the Emperor read could not be read.",
    "record": ("The council's record could not be read. The sittings below "
               "are current."),
    "battles": "The battles could not be read.",
    "war": "The book's limits could not be read.",
    "ai": "Today's AI spend could not be read.",
    "mood": "The people's mood could not be read: unmeasured, never calm.",
    "horizon": "The Horizon view could not be read.",
    "traders": "The regime mix could not be read. The presets are unaffected.",
    "head": "The head could not be read. The rest of the council is current.",
    "direction": ("The direction could not be read. The rest of the council "
                  "is current."),
    "throne": "The throne could not be read. The rest of the council is current.",
    "nine": "The nine could not be read. The rest of the council is current.",
}
SEATS_UNREAD = "The seats could not be read."
CAMPAIGN = ("No campaign plan is recorded. The Emperor reads the limits, the "
            "posture and the Horizon view below. No season objective is set.")
#: The long line he last stated in a live ruling (the last 7 days).
CAMPAIGN_LINE = ("No season objective is set. The last long line he stated "
                 "({on}, {at}): {plan}")
STATUS_SHADOW = ("Seated in shadow: his ruling is recorded and graded, and no "
                 "order waits for it.")
STATUS_OFF = ("Not sitting: both council switches are off. The debate's own "
              "rule decides, and a veto binds only after 30 graded trades.")
STATUS_MASTER = "Not sitting: the platform's master switch is off."
NOTE_DEBATE_OFF = ("The debate is switched off. No voice argues a live entry "
                   "until it is switched on in Platform Control. The record "
                   "below stays.")
NOTE_COUNCIL_OFF = ("The council is switched off: council_bots and "
                    "council_ticket are off on /ops/. The debate's two voices "
                    "are still recorded when the debate runs.")
NOTE_MASTER_OFF = ("The platform's master switch is off: every sitting is "
                   "silenced until it is on.")
NOTE_BUDGET_SPENT = ("Today's AI budget is spent. The voices are silent until "
                     "00:00 UTC. Entries go on without a debate, and once the "
                     "debate binds, no elite entry opens without the Champion.")
#: Two books, named apart (round 2: "your book" twice read as a
#: contradiction): the gates read every row not marked paper; the mood
#: reads the real money only.
WAR_LABEL = ("The book the gates read (a demo world included): every row "
             "of yours not marked paper.")
MOOD_BOOK = ("Now, the real-money book (yours, world live: no demo, no SIM, "
             "no paper): {level}, {n} of {of} inputs measured.")
MOOD_GRADED_TITLE = ("What the argued trades returned under each mood (live, "
                     "graded, 180 days)")
MOOD_GRADED_NOTE = "If the mood predicts nothing, these rows will not differ."
ORCS = "The Orcs are not in the field yet."
TRADERS_FOOT = "The mix moves shares only, never the risk per trade."
TRADERS_UNKNOWN = "No regime recorded: every factor is neutral."
TRADERS_KEY = ("Filled gold: measured on live fills · dashed: a prior, "
               "unproven · plain: neutral · outlined: the regime now.")
#: Under WEIGHTS BY REGIME, after each monogram's voice.
WEIGHTS_KEY_TAIL = ("Gold: measured. A dash: not measured yet, its graded "
                    "calls so far in brackets. Shaded: the regime now.")
#: Said once under THE NINE: the sitting whose weights the rows show.
NINE_WEIGHTS = ("Weights as the Emperor read them at the {at} sitting "
                "({regime} on {cls}). Brier a vs b: the voice's score against "
                "always saying the base rate; lower is better.")
HORIZON_NONE = "No Horizon view: it is switched off, or older than 45 days."
OUTCOME_NOT_SENT = ("Argued, no order sent: refused after the debate, or by a "
                    "later gate.")
#: A bot sitting the council never sat (a budget refusal, a switch): only
#: the debate's two voices argued, and no order is linked to it.
OUTCOME_ONLY_DEBATE = "Only the debate's two voices argued; no order was sent."
OUTCOME_REHEARSAL = "Filled in a rehearsal world: not real money."
OUTCOME_YOUNG = "Not linked yet: the order row is linked within the hour."
OUTCOME_TICKET_NONE = "The ticket · no trade linked"
NO_CALL = "No call in the last 7 days."
NO_WEIGHT_READ = "No sitting has read its weight yet."
EMPEROR_LATE = ("The Emperor answered late: his ruling is recorded and "
                "graded, but the sitting closed without him.")
ONLY_DEBATE = "Only the debate's two voices sat."

# session why/status -> the sitting's sentence (first match wins)
S_SITTING = "The council is sitting."
S_REHEARSAL = ("The order filled in a rehearsal world: not real money, "
               "closed ungraded.")
S_SPENT = "Only the debate's two voices sat: the day's {n} bot sittings were spent."
S_LATE = "Too late to sit: the order's moment had passed."
S_MASTER = "Did not sit: the platform's master switch was off."
S_LANE = "Did not sit: its lane's switch was off."
S_QUEUE = "Did not sit: the queue did not take it."
S_UNFINISHED = "The sitting did not finish."
S_FAILED = "The sitting failed."
S_BUDGET_SILENT = "Did not sit: today's AI budget refused it."
S_BUDGET_PARTIAL = "Some voices were silent: today's AI budget refused them."
S_PARTIAL = "Some voices did not answer."
S_SILENT = "No voice answered."

# grade notes -> the grading's sentence
G_REHEARSAL = "Filled in a rehearsal world: not real money, not graded."
G_REPEAT = ("Argued again within the hold window: a repeat of sitting #{n}, "
            "not graded.")
G_REPLAYED = "Replayed: {reason}."
G_NO_BARS = "Not measured: no bars to replay."
G_NO_LEVELS = "Not measured: no levels to replay."
G_NO_RISK = "Not measured: no risk to measure."

# ── the scrub ─────────────────────────────────────────────────────────────

#: The currency half of the alarm tripwire (tests/test_alarm_bot.py MONEY):
#: a currency sign or code beside a digit.
CURRENCY = re.compile(
    r"[$€£¥]\s?\d"
    r"|\d\s?[$€£¥]"
    r"|\d\s?(?:USD|EUR|GBP|CHF|JPY|CAD|AUD|USDT)\b"
    r"|\b(?:USD|EUR|GBP|CHF|JPY|CAD|AUD|USDT)\s?\d",
    re.IGNORECASE)
#: Its money-word clause, less "price" (a level is not money) and less a
#: figure in R or in percent ("a loss of 1R", "drawdown 4%" pass), and
#: the words a voice uses when it echoes the brief's own amount ("size N
#: units, risk at the stop 1,234.56", trade_debate.candidate_brief).
MONEY_WORD = re.compile(
    r"\b(?:P&L|PnL|equity|margin|balance|cash|capital|profit|loss|drawdown"
    r"|risk(?:ing|ed)?(?: at the stop)?|stake|notional|exposure|book value"
    r"|dollars?)\b"
    r"\s*(?:[:=]|of|at|is|was|used|left)?\s*[-+−]?\d(?![\d.,]*\s?(?:R\b|%))",
    re.IGNORECASE)
#: The brief's amount shape (`:,.2f`: thousands grouped, two decimals),
#: whatever word stands beside it ("one stop costs 1,234.56"). It also
#: withholds a quoted index level of that shape: on the safe side.
MONEY_FIGURE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+\.\d{2}(?![\d%R])")
#: An amount said in words after its figure ("500 dollars").
MONEY_AFTER = re.compile(r"\d\s?(?:dollars?|euros?|bucks)\b", re.IGNORECASE)
_EXC = r"(?:[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+|Exception|Error)"
#: An exception's class name the council wrote into its own sentence ("the
#: seat could not be read (KeyError)", "posture unreadable: KeyError"), with
#: its message when one follows it inside the brackets.
EXC_NAME = re.compile(r"\s*\(" + _EXC + r"(?::[^()]*)?\)|:\s*" + _EXC + r"\b")
_CLASS_NAME = re.compile(r"[A-Za-z_][\w.]*")


def no_exc(text) -> str:
    return EXC_NAME.sub("", str(text or "")).strip()


def scrub(text, n: int = LINE_MAX, marks=None) -> str:
    """A stored line as the band may show it: one line, no exception name,
    and withheld whole when it may name an amount of money. `marks` is a
    sitting's own amount (money_marks): a line that repeats it, in any
    words, is withheld too."""
    t = no_exc(" ".join(str(text or "").split()))
    if (CURRENCY.search(t) or MONEY_WORD.search(t) or MONEY_FIGURE.search(t)
            or MONEY_AFTER.search(t) or (marks is not None and marks.search(t))):
        return WITHHELD
    return t[:n]


def money_marks(s):
    """The amount a sitting's brief put before every voice ("risk at the
    stop 1,234.56": qty × |entry − stop| × value per unit, as
    trade_debate.candidate_brief prints it), as a pattern of the shapes a
    voice may echo it in: 1,234.56, 1234.56, 1,235 and 1235. Read here,
    from the stored levels; neither the levels nor the amount is ever
    serialized. None when the sitting stored no levels or no size."""
    entry, stop, qty = (_num(s.get("entry")), _num(s.get("stop")),
                        _num(s.get("qty")))
    if entry is None or stop is None or qty is None:
        return None
    risk = abs(qty * abs(entry - stop) * float(_num(s.get("value_per_unit"))
                                                 or 1.0))
    if not risk or not math.isfinite(risk):
        return None
    shapes = {f"{risk:,.2f}", f"{risk:.2f}"}
    if risk >= 100:
        # a whole figure of three digits or more; a short one ("12") is a
        # count as often as an amount
        shapes |= {f"{risk:,.0f}", f"{risk:.0f}"}
    alts = "|".join(re.escape(x) for x in sorted(shapes, key=len, reverse=True))
    return re.compile(r"(?<![\d.,])(?:" + alts + r")(?![\d,]|\.\d)")


# ── small words ───────────────────────────────────────────────────────────

def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _C():
    from ai_agents.agents import council
    return council


def name_of(voice: str) -> str:
    return _C().VOICE_NAMES.get(voice, voice)


def mid(name: str) -> str:
    """'The Champion' inside a sentence: 'the Champion'."""
    return "the" + name[3:] if name.startswith("The ") else name


def _names(keys) -> str:
    keys = [k for k in keys if k]
    return ", ".join(mid(name_of(k)) for k in keys) if keys else "no one"


def _utc(dt):
    return dt.astimezone(dt_tz.utc) if dt is not None else None


def _iso(dt):
    return _utc(dt).isoformat() if dt is not None else None


def _at(dt, now) -> str:
    """When a sitting was, in UTC: '18:36 UTC' today, '2026-10-20 18:36
    UTC' on any other day (a bare hour on a days-old sitting reads as
    today's)."""
    if dt is None:
        return DASH
    u = _utc(dt)
    if now is not None and u.date() == _utc(now).date():
        return f"{u:%H:%M} UTC"
    return f"{u:%Y-%m-%d %H:%M} UTC"


def _rg(regime) -> str:
    """A regime key in words: 'mean_reverting' is 'mean reverting'."""
    return str(regime or "unknown").replace("_", " ")


def reason_words(text) -> str:
    """A reason the council wrote, scrubbed, with its regime keys in words
    ("measured in mean_reverting on crypto" reads "in mean reverting")."""
    from bot_program.persona_mix import REGIMES
    t = scrub(text, 200)
    for key in REGIMES:
        if "_" in key:
            t = re.sub(rf"\b{re.escape(key)}\b", _rg(key), t)
    return t


_W_NEUTRAL = re.compile(r"neutral: (\d+) graded calls in this cell, (\d+) needed")
_W_MEASURED = re.compile(r"measured ([^,]+), (\d+) graded calls, (.+)")
_W_SKILL = re.compile(r"Brier ([\d.]+) against ([\d.]+) for always saying the "
                      r"base rate")
_W_NOSKILL = re.compile(r"Brier ([\d.]+); every outcome alike \(base rate "
                        r"([\d.]+%)\), so no skill can show")


def weight_words(reason, cell: str = "") -> str:
    """A weight's reason as the council wrote it (council_grading._ladder),
    said short: 'measured · 34 graded · Brier 0.08 vs 0.16' (vs always
    saying the base rate), 'neutral: 0 of 10 graded'. Its scope ('in
    trending on forex') is left out when it is `cell`, said once above
    the rows. Any other shape is said as written."""
    r = str(reason or "")
    m = _W_NEUTRAL.fullmatch(r)
    if m:
        return f"neutral: {m.group(1)} of {m.group(2)} graded"
    m = _W_MEASURED.fullmatch(r)
    if not m:
        return r
    scope, n, rest = m.group(1).strip(), m.group(2), m.group(3)
    k = _W_SKILL.fullmatch(rest)
    if k:
        tail = f"Brier {k.group(1)} vs {k.group(2)}"
    else:
        k = _W_NOSKILL.fullmatch(rest)
        tail = (f"Brier {k.group(1)}, no skill can show (every outcome "
                f"alike)" if k else rest)
    return ("measured" + ("" if scope == cell else f" {scope}")
            + f" · {n} graded · {tail}")


def _day_start(now):
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _ago(minutes) -> str:
    if minutes is None:
        return DASH
    m = max(0.0, float(minutes))
    if m < 1:
        return "just now"
    if m < 60:
        return f"{int(m)} min ago"
    if m < 48 * 60:
        return f"{int(m // 60)} h ago"
    return f"{int(m // 1440)} d ago"


def plural(n, word: str, many: str = "") -> str:
    """'1 ticket', '3 tickets'."""
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _were(n) -> str:
    """'1 of 1 was wrong', '2 of 3 were wrong'."""
    return "was" if n == 1 else "were"


def _worth(v) -> str:
    """What a commitment or a call was worth, in R, with a verb that
    matches its sign: 'saved +0.50R', 'cost 0.40R', never 'saved -0.40R'."""
    return (f"saved {v:+.2f}R" if v > 0 else f"cost {-v:.2f}R" if v < 0
            else "changed nothing")


def regime_title(regime: str) -> str:
    return str(regime or "unknown").replace("_", " ").capitalize()


def token(voice: str, verdict: str, answer=None) -> str:
    """The short chip for a verdict: CUT ×0.50, FIGHT ×0.50 for a smaller
    commitment, a dash for a verdict the band does not know."""
    base = VERDICT_TOKENS.get((voice, str(verdict or "")))
    if not base:
        return DASH
    a = answer or {}
    if voice == "executioner" and verdict == "cut":
        s = _num(a.get("size_scale"))
        return f"CUT ×{s:.2f}" if s is not None else base
    if voice == "emperor" and verdict == "fight_smaller":
        c = _num(a.get("commit"))
        return f"FIGHT ×{c:.2f}" if c is not None else base
    return base


def _p_line(voice: str, row) -> str:
    """'says it works 62%', or the Skeptic's conviction about his target."""
    if voice == "skeptic":
        c = _num(row.get("conviction"))
        target = (row.get("answer") or {}).get("target") or ""
        if c is None or not target or row.get("verdict") == "sound":
            return ""
        return f"sure {mid(name_of(target))} is wrong {c:.0%}"
    p = _num(row.get("p_work"))
    return f"says it works {p:.0%}" if p is not None else ""


# ── the mappings: a stored reason is said, never forwarded ────────────────

def session_sentence(status: str, why: str, debate: bool = False) -> str:
    """The sitting's sentence. When the debate's two voices argued
    (`debate`: copied into the sitting), a council that did not sit is
    "the other eight", never the whole table (round 2: "Argued" beside
    "Did not sit" read as a contradiction)."""
    t = _session_sentence(status, why)
    if debate and t.startswith("Did not sit: "):
        t = "The other eight did not sit: " + t[len("Did not sit: "):]
    return t


def _session_sentence(status: str, why: str) -> str:
    C = _C()
    status, why = str(status or ""), str(why or "")
    if status in ("queued", "sitting"):
        return S_SITTING
    if why == "the order filled in a rehearsal world":
        return S_REHEARSAL
    if why.startswith("argued on a rehearsal client"):
        return ""
    if "bot sittings are spent" in why:
        return S_SPENT.format(n=C.COUNCIL_BOT_SITTINGS_PER_DAY)
    if status == "record" and not why:
        return ONLY_DEBATE
    if why.startswith("too late to sit"):
        return S_LATE
    if why == "the platform master switch is OFF":
        return S_MASTER
    if why.endswith(" is OFF"):
        return S_LANE
    if "queue did not take it" in why:
        return S_QUEUE
    if why == "the sitting did not finish":
        return S_UNFINISHED
    if why.startswith("the sitting failed"):
        return S_FAILED
    if why.startswith("AI budget") and status == "silent":
        return S_BUDGET_SILENT
    if why.startswith("AI budget") and status == "partial":
        return S_BUDGET_PARTIAL
    if status == "partial":
        return S_PARTIAL
    if status == "silent":
        return S_SILENT
    return ""


def voice_silence(status: str, why: str, wave, session_status: str) -> str:
    """Why a voice did not speak, in words; its stored `why` (an exception's
    class name, a budget refusal in dollars, the debate's own note) never
    leaves."""
    status, why = str(status or ""), str(why or "")
    if status == "asked" and session_status in ("queued", "sitting"):
        return "not answered yet"
    if status == "late":
        return "late: not heard by the chair"
    if why == "timeout":
        return "no answer in time"
    if why.startswith("AI budget"):
        return "the AI budget refused it"
    if wave == 0:
        return "the debate did not hear it"
    if _CLASS_NAME.fullmatch(why):
        return "the call failed"
    if status == "asked":
        return "no answer recorded"
    return "the call failed"


def _replay_reasons():
    C = _C()
    return ("not sent", "not taken", "levels moved", "levels not checked",
            f"still open after {C.COUNCIL_MAX_WAIT_DAYS} days",
            "realized R unpriced", "never filled")


def grade_notes_sentence(notes: str) -> str:
    from ai_agents.council_grading import (REHEARSAL_ARGUED_NOTES,
                                           REHEARSAL_NOTES)
    notes = str(notes or "")
    if notes.startswith(REHEARSAL_NOTES[:60]) \
            or notes.startswith(REHEARSAL_ARGUED_NOTES[:60]):
        return G_REHEARSAL
    m = re.fullmatch(r"a repeat of session #(\d+)", notes)
    if m:
        return G_REPEAT.format(n=int(m.group(1)))
    if notes == "realized":
        return ""
    m = re.fullmatch(r"replayed: (.+)", notes)
    if m and m.group(1) in _replay_reasons():
        return G_REPLAYED.format(reason=m.group(1))
    if notes.endswith("; no bars"):
        return G_NO_BARS
    if notes.endswith("; no levels"):
        return G_NO_LEVELS
    if notes.endswith("; no risk to measure"):
        return G_NO_RISK
    return ""


# ── sides, dissent and the outcome of a sitting ───────────────────────────

def _claim(c):
    payload = c.get("payload") if isinstance(c.get("payload"), dict) else {}
    return SimpleNamespace(kind=c.get("kind"), stance=c.get("stance") or "",
                           p=_num(c.get("p")), grade=c.get("grade") or "",
                           payload={"target": str(payload.get("target") or "")})


def sides_of(voices, claims, session_status: str) -> dict:
    """{voice: side} for the ten, one sitting: for, against, none (spoke and
    took no side), silent, waiting (asked while the sitting sits) or absent
    (never asked). Read as council.claim_side reads it: a voice's stance,
    else (the Skeptic) the opposite of the side of the voice his attack
    names, else its work claim; the chair's side is council.emperor_side.
    A late voice keeps its side."""
    C = _C()
    open_ = session_status in ("queued", "sitting")
    rows = {r["voice"]: r for r in voices}
    by_voice = {}
    for c in claims:
        by_voice.setdefault(c.get("voice_key"), []).append(_claim(c))
    out, attacks = {}, {}
    for v in C.ALL_VOICES:
        r = rows.get(v)
        if r is None:
            out[v] = "absent"
            continue
        st = r.get("status")
        if st == "asked":
            out[v] = "waiting" if open_ else "silent"
            continue
        if st not in SPOKEN:
            out[v] = "silent"
            continue
        if v == "emperor":
            out[v] = C.emperor_side(r.get("verdict")) or "none"
            continue
        c = C.deciding_claim(by_voice.get(v, []), v)
        if c is None:
            out[v] = "none"
        elif c.kind == "stance":
            out[v] = c.stance
        elif c.kind == "attack":
            attacks[v] = c.payload.get("target") or ""
        else:
            out[v] = ("for" if c.p > 0.5 else "against" if c.p < 0.5
                      else "none")
    for v, target in attacks.items():
        if not target or target == v:
            out[v] = "none"
        else:
            out[v] = {"for": "against", "against": "for"}.get(
                out.get(target), "none")
    return out


def dissent_of(voices, sides) -> dict:
    """{chair, dissent, split}. With a chair that spoke: the voices he
    named as overruled, else the voices on the side opposite his; the Hand
    joins when code found he went against it (council.py decides that from
    the two sides, never from his list). Without one (a debate's record, a
    late or silent Emperor): no dissent, and SPLIT when one voice that
    spoke stood for the trade and one against."""
    C = _C()
    emp = next((r for r in voices if r.get("voice") == "emperor"
                and r.get("status") == "spoke"), None)
    if emp is not None:
        a = emp.get("answer") or {}
        chair = C.emperor_side(emp.get("verdict") or a.get("verdict")) or "none"
        named = []
        for o in a.get("overruled") or []:
            k = C.voice_key(o.get("voice") if isinstance(o, dict) else o)
            if k and k != "emperor" and k not in named:
                named.append(k)
        if named:
            dissent = named
        elif chair in ("for", "against"):
            other = "against" if chair == "for" else "for"
            dissent = [v for v in C.ALL_VOICES
                       if v != "emperor" and sides.get(v) == other]
        else:
            dissent = []
        hand = C.voice_key(a.get("hand"))
        if a.get("hand_overruled") and hand and hand not in dissent:
            dissent.append(hand)
        return {"chair": chair, "dissent": dissent, "split": False}
    spoken = [s for v, s in sides.items() if v != "emperor"]
    return {"chair": "", "dissent": [],
            "split": "for" in spoken and "against" in spoken}


def _world(s) -> str:
    from dashboard.position_summary import world_of
    if not s.get("trade_id"):
        return ""
    return world_of({"paper": s.get("trade__paper"),
                     "metadata": s.get("trade_meta") or {}})


def outcome_of(s, now, debate: bool = False) -> str:
    """What became of the order a sitting argued, in words. A rehearsal
    fill and a repeat are said as such, never as "no order sent". A bot
    sitting the council never sat (`debate`: only the debate's two voices
    argued) says so instead of guessing which gate refused the order."""
    from ai_agents.council_grading import NOT_SENT_AFTER, REHEARSAL_NOTES
    tid = s.get("trade_id")
    if s.get("origin") == "ticket":
        if tid:
            t = f"The ticket · taken as trade #{tid}"
            if s.get("levels_match") is False:
                t += " · levels moved, replayed"
            return t
        return OUTCOME_TICKET_NONE
    if tid and _world(s) == "live":
        st, r = s.get("trade__status"), _num(s.get("trade__realized_r"))
        if st in ("OPEN", "CLOSE_PENDING"):
            return f"Sent · trade #{tid} · open"
        if st == "CLOSED" and r is not None:
            return f"Sent · trade #{tid} · {r:+.1f}R"
        if st == "CLOSED":
            return f"Sent · trade #{tid} · closed, R not priced"
        return f"Sent · trade #{tid}"
    notes = str(s.get("grade_notes") or "")
    if (tid or notes.startswith(REHEARSAL_NOTES[:60])
            or s.get("why") == "the order filled in a rehearsal world"):
        return OUTCOME_REHEARSAL
    m = re.fullmatch(r"a repeat of session #(\d+)", notes)
    if m:
        return f"Argued again: a repeat of sitting #{int(m.group(1))}."
    created = s.get("created_at")
    if created is not None and now - created < NOT_SENT_AFTER:
        return OUTCOME_YOUNG
    if debate and s.get("origin") == "bot" and s.get("status") == "silent":
        return OUTCOME_ONLY_DEBATE
    return OUTCOME_NOT_SENT


def _outcome_kind(text: str) -> str:
    if text == OUTCOME_REHEARSAL:
        return "rehearsal"
    if text.startswith("Argued again"):
        return "repeat"
    if text == OUTCOME_YOUNG:
        return "young"
    if text in (OUTCOME_NOT_SENT, OUTCOME_ONLY_DEBATE):
        return "not_sent"
    if text.startswith("Sent"):
        return "sent"
    return "ticket"


def said_once(outcome: str, sentence: str, graded: str) -> tuple:
    """The sitting's and the grading's sentences, less what the outcome
    already said: a rehearsal fill or a repeat is said once."""
    kind = _outcome_kind(outcome)
    if kind == "rehearsal":
        sentence = "" if sentence == S_REHEARSAL else sentence
        graded = "" if graded == G_REHEARSAL else graded
    elif kind == "repeat" and graded.startswith("Argued again"):
        graded = ""
    return sentence, graded


# ── the panels: read once, cached, fenced ─────────────────────────────────

class _Panels:
    """The data panels of one request: each read at most once, from the
    cache when warm. A panel the event `wake`s is rebuilt when its cached
    copy is EV_MIN_AGE_S old. A failure is logged with its traceback,
    never cached, and answers None; the room says the panel's sentence."""

    def __init__(self, user, now, wake=()):
        self.user, self.now, self.wake = user, now, set(wake or ())
        self.got, self.errors = {}, set()

    def key(self, name):
        scope = getattr(self.user, "pk", None) if name in USER_SCOPED else "all"
        return f"{CACHE_PREFIX}:{name}:{scope}"

    def get(self, name):
        if name in self.got:
            return self.got[name]
        key = self.key(name)
        hit = cache.get(key)
        if hit is not None and name in self.wake:
            age = (self.now - hit["built_at"]).total_seconds()
            if age >= EV_MIN_AGE_S:
                hit = None
        if hit is None:
            try:
                data = READERS[name](self.user, self.now)
            except Exception:  # noqa: BLE001 — said by the panel, logged here
                logger.error("[council band] panel %s unreadable", name,
                             exc_info=True)
                self.errors.add(name)
                self.got[name] = None
                return None
            hit = {"built_at": self.now, "data": data}
            cache.set(key, hit, TTL[name])
        self.got[name] = hit["data"]
        return hit["data"]


def _read_switches(user, now):
    from core.platform_control import PlatformComponent
    on = dict(PlatformComponent.objects.filter(key__in=SWITCH_KEYS)
              .values_list("key", "is_enabled"))
    return {k: bool(on.get(k, False)) for k in SWITCH_KEYS}


def _read_phase(user, now):
    from ai_agents.agents import trade_debate as D
    return {"graded": int(D.graded_count()), "shadow_n": D.DEBATE_SHADOW_N}


def _read_regime(user, now):
    from bot_program.persona_mix import latest_report
    from brain import strategist
    from brain.briefing_models import StrategistBriefing
    rep = latest_report(now)
    b = (StrategistBriefing.objects.filter(created_at__gte=_day_start(now))
         .order_by("-created_at")
         .values("posture", "measured_posture", "posture_rationale", "error",
                 "created_at").first())
    briefing = None
    if b is not None:
        briefing = {"error": bool(b["error"]),
                    "title": scrub(strategist.posture_title(SimpleNamespace(**b)),
                                   120),
                    "rationale": scrub(b["posture_rationale"], 160)}
    m = strategist.measured_posture(now)
    return {"regime": rep.get("regime") or "unknown",
            "confidence": _num(rep.get("confidence")) or 0.0,
            "age_min": _num(rep.get("age_minutes")),
            "report": rep.get("report_id") is not None,
            "briefing": briefing,
            "measured": {"title_word": scrub(m.get("title_word"), 80),
                         "note": scrub(m.get("note"), 300)}}


SESSION_FIELDS = ("id", "created_at", "origin", "venue", "status", "why",
                  "user_id", "trade_id", "trade__status", "trade__realized_r",
                  "trade__paper", "trade__metadata", "symbol", "asset_class",
                  "side", "regime", "truth", "truth_r", "graded_at",
                  "grade_notes", "finished_at", "levels_match", "hand",
                  "mood",
                  # read for money_marks only: never serialized
                  "entry", "stop", "qty", "value_per_unit")
VOICE_FIELDS = ("session_id", "voice", "agent", "wave", "status", "why",
                "verdict", "p_work", "conviction", "answer", "model",
                "weight_seen", "weight_reason", "answered_at")
CLAIM_FIELDS = ("session_id", "voice_key", "kind", "stance", "p", "grade",
                "r", "value_r", "payload")
SIDE_KINDS = ("stance", "attack", "work", "battle")


def _trade_meta(meta) -> dict:
    """Only what the band reads of a trade's metadata: its world and the
    debate's phase stamped on it. The rest (the debate's own `why`, which
    can carry an exception's text) is dropped at the door."""
    meta = meta if isinstance(meta, dict) else {}
    debate = meta.get("debate") if isinstance(meta.get("debate"), dict) else {}
    return {"broker": str(meta.get("broker") or ""),
            "broker_env": str(meta.get("broker_env") or ""),
            "binding": bool(debate.get("binding")),
            "graded": _num(debate.get("graded"))}


def _read_sittings_rows(now, before=None) -> dict:
    """The newest SITTINGS_MAX live sessions of any status (the list), and
    with them the newest SITTINGS_MAX that SAT (any status but the
    debate's bare "record"). The debate opens a record for every live
    entry it argues, every tick, so twenty records can push a ruling of a
    few hours ago out of the newest twenty: the rulings, the last sitting,
    the campaign, the mood and each voice's last call read the merged
    set, newest first; the list shows its first SITTINGS_MAX, which are
    the newest twenty."""
    from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                          CouncilVoice)
    qs = CouncilSession.objects.filter(venue="live")
    if before is None:
        qs = qs.filter(created_at__gte=now - timedelta(days=SITTINGS_DAYS))
    else:
        qs = qs.filter(id__lt=int(before))
    rows = list(qs.order_by("-created_at", "-id")
                .values(*SESSION_FIELDS)[:SITTINGS_MAX])
    if before is None and len(rows) >= SITTINGS_MAX:
        # short of SITTINGS_MAX, every session of the window is already in
        seen = {r["id"] for r in rows}
        sat = [r for r in qs.exclude(status="record")
               .order_by("-created_at", "-id")
               .values(*SESSION_FIELDS)[:SITTINGS_MAX] if r["id"] not in seen]
        if sat:
            rows = sorted(rows + sat, key=lambda r: (r["created_at"], r["id"]),
                          reverse=True)
    for r in rows:
        r["trade_meta"] = _trade_meta(r.pop("trade__metadata", None))
    ids = [r["id"] for r in rows]
    voices, claims = {}, {}
    if ids:
        for v in CouncilVoice.objects.filter(session_id__in=ids).values(
                *VOICE_FIELDS):
            voices.setdefault(v["session_id"], []).append(v)
        for c in CouncilClaim.objects.filter(
                session_id__in=ids, kind__in=SIDE_KINDS).values(*CLAIM_FIELDS):
            payload = c.get("payload") if isinstance(c.get("payload"), dict) else {}
            c["payload"] = {"target": str(payload.get("target") or "")}
            claims.setdefault(c["session_id"], []).append(c)
    ever = bool(rows) or (before is None and CouncilSession.objects.filter(
        venue="live").exists())
    return {"sessions": rows, "voices": voices, "claims": claims,
            "ever": ever}


def _read_sittings(user, now):
    return _read_sittings_rows(now)


def _weight_entry(w) -> dict:
    w = w if isinstance(w, dict) else {}
    return {"factor": _num(w.get("factor")), "lane": str(w.get("lane") or ""),
            "n": int(_num(w.get("n")) or 0),
            "reason": reason_words(w.get("reason"))}


def _read_snapshot(user, now):
    """The weights the chair read: per class, the newest live sitting in
    the last SNAPSHOT_DAYS that stored them (a sitting refused before the
    chair stores none)."""
    from ai_agents.council_models import CouncilSession
    C = _C()
    out = {}
    # weights are stored before wave 3: a sitting whose chair never ran
    # (the AI budget refused wave 3) stored weights no Emperor read. One
    # Emperor row per sitting (a unique constraint): the join adds none.
    for r in (CouncilSession.objects
              .filter(venue="live", weights__has_key="emperor",
                      voices__voice="emperor",
                      voices__status__in=("spoke", "late"),
                      created_at__gte=now - timedelta(days=SNAPSHOT_DAYS))
              .order_by("-created_at")
              .values("id", "created_at", "regime", "asset_class",
                      "weights")[:SNAPSHOT_ROWS]):
        cls = r["asset_class"] or ""
        if cls in out:
            continue
        w = r["weights"] if isinstance(r["weights"], dict) else {}
        out[cls] = {"sitting": r["id"], "at": r["created_at"],
                    "regime": r["regime"] or "unknown", "class": cls,
                    "weights": {v: _weight_entry(w.get(v))
                                for v in C.ALL_VOICES if v in w}}
    return out


def _read_record(user, now):
    """The council's own record (council_grading.record_matrix), cut to
    what the band shows: no dollar figure (cost_30d stays home), every
    sentence scrubbed."""
    from ai_agents import council_grading as G
    rm = G.record_matrix()
    voices = [{"voice": v.get("voice"), "factor": _num(v.get("factor")),
               "lane": str(v.get("lane") or ""), "n": int(v.get("n") or 0),
               "brier": _num(v.get("brier")),
               "base_rate": _num(v.get("base_rate")),
               "reason": reason_words(v.get("reason")),
               "right": int(v.get("right") or 0),
               "wrong": int(v.get("wrong") or 0),
               "bot_n": int(v.get("bot_n") or 0),
               "hand_n": int(v.get("hand_n") or 0),
               "specialty": scrub(v.get("specialty"), 200)}
              for v in rm.get("voices") or []]
    matrix = [{"voice": row.get("voice"),
               "cells": [{"regime": c.get("regime"),
                          "factor": _num(c.get("factor")),
                          "n": int(c.get("n") or 0),
                          "lane": str(c.get("lane") or "")}
                         for c in row.get("cells") or []]}
              for row in rm.get("matrix") or []]
    hands = [{"regime": h.get("regime"), "asset_class": h.get("asset_class"),
              "voice": str(h.get("voice") or ""), "factor": _num(h.get("factor")),
              "n": int(h.get("n") or 0), "brier": _num(h.get("brier")),
              "why_empty": no_exc(h.get("why_empty"))}
             for h in rm.get("hands") or []]
    ag = rm.get("against_hand") or {}
    against = {k: int(ag.get(k) or 0) for k in (
        "overruled", "graded", "emperor_right", "hand_right", "unresolved",
        "pending", "no_reason")}
    against["agreed"] = {k: int((ag.get("agreed") or {}).get(k) or 0)
                         for k in ("n", "right")}
    against["by_voice"] = {str(v): {k: int(d.get(k) or 0) for k in (
        "graded", "emperor_right", "hand_right")}
        for v, d in (ag.get("by_voice") or {}).items() if isinstance(d, dict)}
    sf = rm.get("skeptic_first") or {}
    return {"voices": voices, "matrix": matrix, "hands": hands,
            "regimes": list(rm.get("regimes") or []),
            "benchmarks": [{"name": str(b.get("name") or ""),
                            "brier": _num(b.get("brier")),
                            "n": int(b.get("n") or 0)}
                           for b in rm.get("benchmarks") or []],
            "unpaired": int(rm.get("benchmarks_unpaired") or 0),
            "replay": {k: int((rm.get("replay") or {}).get(k) or 0)
                       for k in ("n", "agree")},
            "chair": {k: int((rm.get("chair") or {}).get(k) or 0) for k in (
                "over_wrong", "over_n", "follow_right", "follow_n")},
            "against": against,
            "skeptic": {k: int(sf.get(k) or 0) for k in (
                "named", "attacked", "first", "right", "graded")},
            "moods": [{"level": str(m.get("level") or ""),
                       "n": int(m.get("n") or 0), "thin": bool(m.get("thin")),
                       "avg": scrub(m.get("avg_r_text"), 20),
                       "won": scrub(m.get("won_text"), 20),
                       "commit": scrub(m.get("commit_text"), 20)}
                      for m in rm.get("moods") or []]}


def _read_battles(user, now):
    """Thirty days of live sittings: what they argued, what left, and what
    the chair's commitment did. Three queries."""
    from django.db.models import Count, Sum

    from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                          CouncilVoice)
    since = now - timedelta(days=BATTLE_DAYS)
    rows = list(CouncilSession.objects.filter(venue="live",
                                              created_at__gte=since)
                .values("id", "origin", "trade_id", "trade__status",
                        "trade__realized_r", "trade__paper", "trade__metadata",
                        "grade_notes", "why", "created_at", "levels_match"))
    out = {"sat": len(rows), "bots": 0, "tickets": 0, "left": 0, "won": 0,
           "lost": 0, "even": 0, "open": 0, "unpriced": 0, "net_r": 0.0,
           "no_order": 0, "rehearsal": 0, "repeat": 0, "young": 0}
    for r in rows:
        r["trade_meta"] = _trade_meta(r.pop("trade__metadata", None))
        if r["origin"] == "ticket":
            out["tickets"] += 1
            continue
        out["bots"] += 1
        kind = _outcome_kind(outcome_of(r, now))
        if kind == "sent":
            out["left"] += 1
            st, rr = r["trade__status"], _num(r["trade__realized_r"])
            if st in ("OPEN", "CLOSE_PENDING"):
                out["open"] += 1
            elif rr is None:
                out["unpriced"] += 1
            else:
                out["net_r"] += rr
                # a priced 0.0R is a measured break-even, never unpriced
                out["won" if rr > 0 else "lost" if rr < 0 else "even"] += 1
        elif kind == "not_sent":
            out["no_order"] += 1
        elif kind in ("rehearsal", "repeat", "young"):
            out[kind] += 1
    verdicts = {"fight": 0, "fight_smaller": 0, "refuse": 0}
    if rows:
        for v in CouncilVoice.objects.filter(
                session_id__in=[r["id"] for r in rows], voice="emperor",
                status="spoke").values_list("verdict", flat=True):
            if v in verdicts:
                verdicts[v] += 1
    agg = CouncilClaim.objects.filter(
        voice_key="emperor", kind="battle", venue="live",
        grade__in=("right", "wrong"), graded_at__gte=since).aggregate(
        n=Count("id"), nv=Count("value_r"), v=Sum("value_r"))
    # A claim graded without a value is unmeasured, never zero: only the
    # claims that carry one are summed, and their count is said.
    out["emperor"] = {**verdicts, "graded": int(agg["n"] or 0),
                      "valued": int(agg["nv"] or 0),
                      "saved_r": _num(agg["v"]) if agg["nv"] else None}
    return out


def _read_war(user, now):
    """The book's limits as the gates read them (risk_gate, venue live),
    in percent and mode words: every reason string stays home (it carries
    money)."""
    from portfolio import risk_gate as RG
    out = {"daily": None, "open": None, "elite": None}
    book = RG.limits_book()
    try:
        d = RG.daily_loss_state(user, portfolio=book, venue="live")
        limit, money = _num(d.get("limit_pct")), _num(d.get("limit_money"))
        realized = _num(d.get("realized"))
        if limit is None:
            out["daily"] = {"state": "no_limit"}
        elif _num(d.get("book_value")) is None or not money:
            out["daily"] = {"state": "no_book"}
        elif realized is None:
            out["daily"] = {"state": "unpriced",
                            "n": int(d.get("unmeasured") or 0)}
        else:
            # the closes the gate could not price are not in `realized`:
            # their count is said beside the figure, never taken as zero
            out["daily"] = {"state": "ok", "mode": str(d.get("mode") or "open"),
                            "limit_pct": limit,
                            "used_pct": 100.0 * min(0.0, realized) / money,
                            "unpriced": int(d.get("unmeasured") or 0)}
    except Exception:  # noqa: BLE001 — that line says it
        logger.error("[council band] daily stop unreadable", exc_info=True)
    try:
        o = RG.open_risk_state(user, portfolio=book, venue="live")
        limit, money = _num(o.get("limit_pct")), _num(o.get("limit_money"))
        if limit is None:
            out["open"] = {"state": "no_limit"}
        elif not money:
            out["open"] = {"state": "no_book"}
        else:
            out["open"] = {"state": "ok", "limit_pct": limit,
                           "used_pct": 100.0 * (_num(o.get("open_risk")) or 0.0)
                           / money,
                           "rows": int(o.get("rows") or 0),
                           "unstopped": int(o.get("unstopped") or 0)}
    except Exception:  # noqa: BLE001
        logger.error("[council band] open risk unreadable", exc_info=True)
    try:
        out["elite"] = {"used": int(RG.elite_entries_since(user, paper=False)),
                        "max": int(RG.ELITE_MAX_PER_WINDOW)}
    except Exception:  # noqa: BLE001
        logger.error("[council band] elite count unreadable", exc_info=True)
    return out


def _read_ai(user, now):
    """Today's AI on the core line, in percent of the day's allowance and
    in calls: the sums are turned into shares here, and no dollar figure is
    kept, cached or sent."""
    from django.db.models import Count, Sum

    from ai_agents import spend as S
    from ai_agents.models import AgentTask
    C = _C()
    budget = _num(S.daily_budget("core")) or 0.0
    spent = _num(S.spent_today("core")) or 0.0
    rows = list(AgentTask.objects.filter(created_at__gte=_day_start(now))
                .order_by().values("agent", "model")
                .annotate(n=Count("id"), c=Sum("cost_usd")))
    council_names = set(C.COUNCIL_AGENT_NAMES) | set(C.COUNCIL_DEBATER_NAMES)
    council = sum(float(r["c"] or 0) for r in rows
                  if r["agent"] in council_names)
    agents = {}
    for r in rows:
        a = agents.setdefault(r["agent"], {"n": 0, "pct": 0.0, "models": []})
        a["n"] += int(r["n"] or 0)
        if budget > 0:
            a["pct"] += 100.0 * float(r["c"] or 0) / budget
        if r["model"] and r["model"] not in a["models"]:
            a["models"].append(str(r["model"])[:50])
    if budget <= 0:
        for a in agents.values():
            a["pct"] = None
    return {"budget_set": budget > 0,
            "used_pct": int(round(100.0 * spent / budget)) if budget > 0 else None,
            "council_pct": int(round(100.0 * council / spent)) if spent > 0 else 0,
            "deep_refused": budget > 0 and spent > budget * S.DEEP_TIER_SHARE,
            "spent_out": budget > 0 and spent >= budget,
            "agents": agents}


def _read_mood(user, now):
    """THE PEOPLE'S MOOD of the viewer's own real-money book: pure code
    (council_mood), never a model call. A gauge that cannot be read is
    unmeasured, said, never calm."""
    from ai_agents import council_mood as M
    unread = False
    try:
        mood = M.people_mood(user)
    except Exception:  # noqa: BLE001 — said as unmeasured
        logger.error("[council band] the mood unreadable", exc_info=True)
        mood, unread = M.unmeasured_mood("the gauge could not be read"), True
    mood = mood if isinstance(mood, dict) else {}
    level = str(mood.get("level") or "")
    if level not in M.MOOD_LEVELS + (M.UNMEASURED,):
        level = M.UNMEASURED
    inputs = {}
    for k in M.INPUTS:
        e = (mood.get("inputs") or {}).get(k)
        if isinstance(e, dict):
            inputs[k] = {"measured": bool(e.get("measured")),
                         "words": scrub(e.get("words"), 200) or "not read"}
    return {"level": level, "measured_n": int(mood.get("measured_n") or 0),
            "of": int(mood.get("of") or len(M.INPUTS)), "inputs": inputs,
            "why": scrub(mood.get("why"), 200), "unread": unread}


def _read_horizon(user, now):
    from brain.horizon_models import latest_view
    view = latest_view()
    if view is None:
        return None
    chips = []
    for cls, t in sorted((view.asset_class_tilts or {}).items()):
        tilt = _num((t or {}).get("tilt")) if isinstance(t, dict) else None
        if tilt is not None:
            chips.append(f"{cls} {tilt:+g}")
    return {"chips": chips,
            "age_days": (now - view.created_at).total_seconds() / 86400.0}


def _share(band) -> str:
    """A share band as the personas page writes it ('17.925–52.925%'),
    to a tenth of a percent ('17.9–52.9%'); a dash when it is unread."""
    ends = re.findall(r"-?\d+(?:\.\d+)?", str(band or ""))
    if len(ends) != 2:
        return DASH
    lo, hi = (round(float(x), 1) for x in ends)
    return f"{lo:g}–{hi:g}%"


def _read_traders(user, now):
    """The three personalities under the regime, from the /personas/
    page's own reader (one definition of the learned count); never the
    per-config record reader, which is one query per config."""
    from bot_program.persona_mix import _wearing
    from bot_program.personas import PERSONA_KEYS, PERSONAS
    from dashboard import views_personas as VP
    from bot_program.asset_models import AssetBotConfig
    rows, mix, err = VP._mix_matrix(user)
    if err or not rows:
        return {"unread": True}
    wearing = _wearing()
    # _wearing counts every config, paper and switched off included: each
    # card names its book (one query for the three personas)
    pks = {pk for ks in wearing.values() for pk in ks}
    books = {pk: (mode, bool(on)) for pk, mode, on in
             AssetBotConfig.objects.filter(pk__in=pks)
             .values_list("pk", "mode", "enabled")} if pks else {}
    cards, matrix = [], []
    for row in rows:
        key = row["key"]
        p = PERSONAS.get(key)
        cur = next((c for c in row["cells"] if c.get("current")), None)
        lo, hi = (float(p.share_floor_pct), float(p.share_ceiling_pct)) \
            if p is not None else (0.0, 0.0)
        cards.append({
            "key": key, "label": row.get("label") or key,
            "holding": (str(getattr(p, "holding", "")).split(" ")[0]
                        if p is not None else ""),
            "factor": _num(cur.get("factor")) if cur else 1.0,
            "lane": str(cur.get("lane")) if cur else "neutral",
            "n": int(cur.get("n") or 0) if cur else 0,
            "band": f"{lo:g}–{hi:g}%",
            "band_now": _share(cur.get("band")) if cur else f"{lo:g}–{hi:g}%",
            "worn_by": len(wearing.get(key) or []),
            "worn_live": sum(1 for pk in wearing.get(key) or []
                             if books.get(pk, ("", False))[0] == "live"),
            "worn_live_on": sum(1 for pk in wearing.get(key) or []
                                if books.get(pk) == ("live", True)),
            "worn_paper": sum(1 for pk in wearing.get(key) or []
                              if books.get(pk, ("", False))[0] == "paper")})
        matrix.append({"key": key, "label": row.get("label") or key,
                       "cells": [{"regime": c["regime"],
                                  "factor": _num(c.get("factor")),
                                  "lane": str(c.get("lane") or ""),
                                  "current": bool(c.get("current"))}
                                 for c in row["cells"]]})
    order = {k: i for i, k in enumerate(PERSONA_KEYS)}
    cards.sort(key=lambda c: order.get(c["key"], 99))
    matrix.sort(key=lambda c: order.get(c["key"], 99))
    return {"unread": False, "cards": cards, "matrix": matrix,
            "regime": str(mix.get("regime") or "unknown"),
            "confidence": _num(mix.get("confidence")) or 0.0,
            "age_min": _num(mix.get("age_minutes")),
            "measured": int(mix.get("measured") or 0),
            "n_measured": int(mix.get("n_measured") or 0),
            "n_cells": int(mix.get("n_cells") or 0)}


READERS = {"switches": _read_switches, "phase": _read_phase,
           "regime": _read_regime, "sittings": _read_sittings,
           "snapshot": _read_snapshot, "record": _read_record,
           "battles": _read_battles, "war": _read_war, "ai": _read_ai,
           "mood": _read_mood, "horizon": _read_horizon,
           "traders": _read_traders}


# ── one sitting, as the band draws it ─────────────────────────────────────

def _sitting_view(s, voices, claims, now) -> dict:
    """The derived reading of one sitting, shared by the card, the
    transcript, the direction strip and the voice rows."""
    sides = sides_of(voices, claims, s.get("status"))
    dis = dissent_of(voices, sides)
    if s.get("status") in ("queued", "sitting"):
        # SPLIT is a closed record's word: while the council sits, the
        # chair has not ruled yet and the voices are not all in
        dis["split"] = False
    emp = next((r for r in voices if r.get("voice") == "emperor"), None)
    debate = any(r.get("status") == "copied" for r in voices)
    return {"sides": sides, "dissent": dis, "emperor": emp, "debate": debate,
            "outcome": outcome_of(s, now, debate=debate)}


def _table(s, voices, view) -> dict:
    """The round table: seats by temperament, each in its side's colour,
    a ring for each dissenting voice, the chair in the centre."""
    sides, dis, emp = view["sides"], view["dissent"], view["emperor"]
    marks = money_marks(s)
    chair_spoke = emp is not None and emp.get("status") == "spoke"
    verdict = (emp or {}).get("verdict") if chair_spoke else ""
    seats = [{"voice": v, "mono": MONO[v], "a": a, "side": sides.get(v, "absent"),
              "dissent": v in dis["dissent"], "name": name_of(v)}
             for v, a in SEATS]
    tally = _tally(sides)
    on = f"{s['symbol']} {s.get('side') or ''}".strip()
    status = (emp or {}).get("status")
    glyph = CHAIR_GLYPH.get(verdict, "·")
    if chair_spoke:
        label = (f"Council on {on}: the Emperor "
                 f"{scrub(_C().verdict_words('emperor', emp.get('answer')), 80, marks)}; "
                 f"{tally}; dissent: {_names(dis['dissent'])}.")
        word = VERDICT_TOKENS.get(("emperor", verdict), "NO CHAIR")
    elif status == "late":
        # he ruled, after the sitting closed: recorded and graded, heard by
        # no one (round 2: "NO CHAIR" over his recorded ruling)
        words = scrub(_C().verdict_words("emperor", emp.get("answer")), 80,
                      marks)
        label = (f"Council on {on}: the Emperor ruled late"
                 + (f" ({words})" if words else "") + f"; {tally}.")
        word, glyph = "LATE", "…"
    elif s.get("status") in ("queued", "sitting"):
        label = (f"Council sitting on {on}: {tally} so far; the Emperor has "
                 f"not ruled yet.")
        word, glyph = "SITTING", "…"
    elif emp is not None and s.get("status") != "record":
        label = f"Council on {on}: {tally}; the Emperor did not rule."
        word = "NO CHAIR"
    else:
        label = f"Debate on {on}: {tally}; no chair."
        word = "NO CHAIR"
    return {"sitting": f"c{s['id']}", "seats": seats,
            "chair": dis["chair"] if chair_spoke else "",
            "chair_glyph": glyph,
            "chair_token": word,
            # a smaller commitment is drawn apart from a refusal (◐, not ✕):
            # the order went out, smaller; its side stays the council's
            "smaller": chair_spoke and verdict == "fight_smaller",
            "split": dis["split"], "label": label}


def _tally(sides) -> str:
    counts = {}
    for v, side in sides.items():
        if v == "emperor" or side == "absent":
            continue
        counts[side] = counts.get(side, 0) + 1
    words = [f"{counts[k]} {w}" for k, w in (
        ("for", "for"), ("against", "against"), ("none", "no side"),
        ("silent", "silent"), ("waiting", "waiting")) if counts.get(k)]
    return " · ".join(words) if words else "no voice heard"


def _so_far(sides, voices) -> str:
    """WHO DISAGREES while the council sits: the voices standing apart
    from the rest so far, by name, then who has not answered yet. 'so far
    the Executioner (VETO) stands against it, 5 for; 3 waiting'."""
    C = _C()
    order = [v for v in C.ALL_VOICES if v != "emperor"]
    fors = [v for v in order if sides.get(v) == "for"]
    against = [v for v in order if sides.get(v) == "against"]
    if fors and against:
        if len(against) <= len(fors):
            few, side, many, other = against, "against", len(fors), "for"
        else:
            few, side, many, other = fors, "for", len(against), "against"
        shown = []
        for v in few[:DISSENT_SHOWN]:
            r = _row_of(voices, v) or {}
            tok = token(v, r.get("verdict"), r.get("answer"))
            shown.append(mid(name_of(v)) + (f" ({tok})" if tok != DASH else ""))
        more = len(few) - DISSENT_SHOWN
        who = " and ".join(shown) if more <= 0 and len(shown) == 2 \
            else ", ".join(shown) + (f" and {more} more" if more > 0 else "")
        t = (f"so far {who} {'stands' if len(few) == 1 else 'stand'} "
             f"{side} it, {many} {other}")
    elif fors or against:
        t = (f"so far {len(fors)} for, none against" if fors else
             f"so far {len(against)} against, none for")
    else:
        t = "so far no voice has taken a side"
    rest = [f"{n} {w}" for n, w in (
        (sum(1 for v in order if sides.get(v) == "waiting"), "waiting"),
        (sum(1 for v in order if sides.get(v) == "silent"), "silent")) if n]
    return t + ("; " + ", ".join(rest) if rest else "")


def _row_of(voices, voice):
    return next((r for r in voices if r.get("voice") == voice), None)


def _card(s, voices, claims, now) -> dict:
    view = _sitting_view(s, voices, claims, now)
    dis = view["dissent"]
    emp = view["emperor"]
    chips = []
    meta = s.get("trade_meta") or {}
    if s.get("trade_id") and _world(s) == "live":
        if meta.get("binding"):
            chips.append("BINDING")
        elif meta.get("graded") is not None:
            # the count stamped on the trade when it opened, not today's
            # (the head says today's)
            from ai_agents.agents.trade_debate import DEBATE_SHADOW_N
            chips.append(f"SHADOW AT ENTRY {int(meta['graded'])}/"
                         f"{DEBATE_SHADOW_N}")
    if dis["dissent"]:
        chips.append(f"{len(dis['dissent'])} DISSENT")
    if dis["split"]:
        chips.append("SPLIT")
    grade = _grade_chip(s)
    chips.append(grade)
    shown = []
    for v in dis["dissent"][:DISSENT_SHOWN]:
        r = _row_of(voices, v) or {}
        bits = [token(v, r.get("verdict"), r.get("answer"))]
        p = _p_line(v, r)
        if p:
            bits.append(p)
        shown.append(f"{mid(name_of(v))} ({', '.join(bits)})")
    more = len(dis["dissent"]) - DISSENT_SHOWN
    dissent = ("Dissent: " + ", ".join(shown)
               + (f" +{more} more" if more > 0 else "")) if shown else ""
    chair = ""
    if emp is not None and emp.get("status") == "spoke":
        chair = "THE EMPEROR " + token("emperor", emp.get("verdict"),
                                       emp.get("answer"))
    elif emp is not None and emp.get("status") == "late":
        chair = "THE EMPEROR · late"
    sentence, graded = said_once(
        view["outcome"], session_sentence(s.get("status"), s.get("why"),
                                          view["debate"]),
        grade_notes_sentence(s.get("grade_notes")))
    return {"id": f"c{s['id']}", "origin": s["origin"],
            "kind": "BOT ORDER" if s["origin"] == "bot" else "TICKET",
            "symbol": s["symbol"], "class": s.get("asset_class") or "",
            "side": s.get("side") or "", "at": _iso(s["created_at"]),
            "table": _table(s, voices, view), "chair": chair,
            "tally": _tally(view["sides"]), "dissent": dissent,
            "has_dissent": bool(dis["dissent"]), "split": dis["split"],
            "chips": chips, "outcome": outcome_shown(view["outcome"], grade),
            "sentence": sentence, "graded": graded}


def outcome_shown(outcome: str, grade: str) -> str:
    """The outcome beside its grade chip: a sent order's R is said once,
    by the chip ("Sent · trade #5 · closed" beside "GRADED +0.8R")."""
    m = re.fullmatch(r"(Sent · trade #\d+) · ([+-]\d+\.\dR)", outcome or "")
    if m and grade == f"GRADED {m.group(2)}":
        return f"{m.group(1)} · closed"
    return outcome


def _grade_chip(s) -> str:
    """GRADED/REPLAYED with its R; NOT GRADED (BY RULE) for a rehearsal
    fill or a repeat; NOT MEASURED when graded without an R; GRADE
    PENDING while the nightly grading has not reached it (a sitting in
    progress included)."""
    from ai_agents.council_grading import (REHEARSAL_ARGUED_NOTES,
                                           REHEARSAL_NOTES)
    r = _num(s.get("truth_r"))
    if s.get("truth") == "realized" and r is not None:
        return f"GRADED {r:+.1f}R"
    if s.get("truth") == "replay" and r is not None:
        return f"REPLAYED {r:+.1f}R"
    notes = str(s.get("grade_notes") or "")
    if (notes.startswith(REHEARSAL_NOTES[:60])
            or notes.startswith(REHEARSAL_ARGUED_NOTES[:60])
            or re.fullmatch(r"a repeat of session #\d+", notes)):
        return "NOT GRADED (BY RULE)"
    if s.get("graded_at") is not None:
        return "NOT MEASURED"
    return "GRADE PENDING"


# ── the room ──────────────────────────────────────────────────────────────

def _rev(data) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str)
                        .encode("utf-8")).hexdigest()[:8]


def _fenced(name, fn) -> dict:
    try:
        data = fn()
    except Exception:  # noqa: BLE001 — the panel says its sentence
        logger.error("[council band] %s unreadable", name, exc_info=True)
        return {"error": SENTENCE.get(name, "This part could not be read.")}
    data["rev"] = _rev(data)
    return data


def _sessions(P):
    data = P.get("sittings")
    if data is None:
        return None
    out = []
    for s in data["sessions"]:
        sid = s["id"]
        out.append((s, data["voices"].get(sid, []), data["claims"].get(sid, [])))
    return out


def _latest_sat(sess):
    """The newest live sitting that sat (not a debate's bare record)."""
    for s, voices, claims in sess or []:
        if s.get("status") != "record":
            return s, voices, claims
    return None


def _room_head(P, now) -> dict:
    sw, phase, ai = P.get("switches"), P.get("phase"), P.get("ai")
    if sw is None:
        debate = council = "SWITCHES UNREAD"
    else:
        if not sw["trade_debate"]:
            debate = "DEBATE OFF"
        elif phase is None:
            debate = "DEBATE · PHASE UNREAD"
        elif phase["graded"] >= phase["shadow_n"]:
            debate = "DEBATE · BINDING"
        else:
            debate = f"DEBATE · SHADOW {phase['graded']}/{phase['shadow_n']}"
        bots, tickets = sw["council_bots"], sw["council_ticket"]
        if not sw["platform_master"]:
            council = "COUNCIL · MASTER OFF"
        elif bots and tickets:
            council = "COUNCIL · BOTS + TICKETS"
        elif bots:
            council = "COUNCIL · BOTS"
        elif tickets:
            council = "COUNCIL · TICKETS"
        else:
            council = "COUNCIL OFF"
    return {"debate": {"t": debate,
                       "title": "The debate's phase: a veto binds once 30 "
                                "live trades it argued are graded."},
            "council": {"t": council,
                        "title": "The council's two lanes: bot orders that "
                                 "left, and live tickets on request."},
            "budget_spent": bool(ai and ai.get("spent_out"))}


def _thinks(P, now) -> dict:
    reg, mood = P.get("regime"), P.get("mood")
    if reg is None:
        return {"t": SENTENCE["regime"]}
    if not reg["report"]:
        head = "No regime recorded: Sauron's Mind has not written a report."
    else:
        head = (f"{regime_title(reg['regime'])} (confidence "
                f"{reg['confidence']:.2f})")
    b = reg["briefing"]
    posture = ("no briefing today" if b is None else
               "today's briefing failed" if b["error"] else b["title"])
    level = mood["level"] if mood else "unmeasured"
    parts = [head, posture, f"the people: {level}"]
    if reg["report"]:
        age = reg["age_min"]
        # Overdue past the Mind's own freshness window (brain/context.py),
        # the span every reader still takes its last report as its word.
        from brain.context import mind_fresh_minutes
        parts.append(f"Mind read {_ago(age)}"
                     + (" (overdue)" if age is not None
                        and age > mind_fresh_minutes() else ""))
    return {"t": " · ".join(parts)}


def _disagrees(P, now) -> dict:
    sess = _sessions(P)
    if sess is None:
        return {"t": SENTENCE["sittings"], "sitting": None}
    if not sess:
        data = P.get("sittings") or {}
        return {"t": NO_SESSION if not data.get("ever") else NO_SITTING_7,
                "sitting": None}
    s, voices, claims = sess[0]
    view = _sitting_view(s, voices, claims, now)
    dis, emp = view["dissent"], view["emperor"]
    when = f" ({_at(s['created_at'], now)})"
    on = f"{s['symbol']} {s.get('side') or ''}".strip()
    if emp is not None and emp.get("status") == "spoke":
        a = emp.get("answer") or {}
        words = scrub(_C().verdict_words("emperor", a), 80, money_marks(s))
        named = [_C().voice_key(o.get("voice") if isinstance(o, dict) else o)
                 for o in a.get("overruled") or []]
        named = [k for k in named if k and k != "emperor"]
        t = (f"The Emperor: {words} on {on} · "
             + (f"overruled {_names(named)}" if named else "no one overruled"))
        hand = _C().voice_key(a.get("hand"))
        if a.get("hand_overruled") and hand:
            t += f" · against his Hand, {mid(name_of(hand))}"
        return {"t": t + when, "sitting": f"c{s['id']}"}
    sides = view["sides"]
    if s.get("status") in ("queued", "sitting"):
        return {"t": f"The council is sitting on {on}: "
                     f"{_so_far(sides, voices)}" + when + ".",
                "sitting": f"c{s['id']}"}
    ex, ch = sides.get("executioner"), sides.get("champion")
    spoke = {v: x for v, x in sides.items() if x in ("for", "against", "none")}
    if dis["split"]:
        if set(spoke) <= {"executioner", "champion"}:
            against = "executioner" if ex == "against" else "champion"
            for_ = "champion" if against == "executioner" else "executioner"
            ra, rf = _row_of(voices, against), _row_of(voices, for_)
            t = (f"SPLIT: {mid(name_of(against))} "
                 f"({token(against, ra.get('verdict'), ra.get('answer'))}) "
                 f"against {mid(name_of(for_))} "
                 f"({token(for_, rf.get('verdict'), rf.get('answer'))}) on {on}")
        else:
            k = sum(1 for x in spoke.values() if x == "against")
            m = sum(1 for x in spoke.values() if x == "for")
            t = f"SPLIT: {k} against, {m} for, and no chair, on {on}"
    elif any(x in ("for", "against") for x in spoke.values()):
        t = f"No split: the voices that spoke leaned the same way on {on}"
    else:
        t = f"No voice took a side on {on}"
    t += when + "."
    if emp is not None and emp.get("status") == "late":
        t += " The Emperor answered late."
    return {"t": t, "sitting": f"c{s['id']}"}


def _who_right(P, now) -> dict:
    C = _C()
    rec, reg = P.get("record"), P.get("regime")
    if rec is None:
        return {"t": "Not read: the council's record could not be read.",
                "voice": None}
    regime = (reg or {}).get("regime") or "unknown"
    if not (reg or {}).get("report") or regime == "unknown":
        return {"t": "No one in an unknown regime: the Mind has recorded none.",
                "voice": None}
    cells = []
    for row in rec["matrix"]:
        for c in row["cells"]:
            if c["regime"] == regime:
                cells.append((row["voice"], c))
    measured = [(v, c) for v, c in cells
                if c["lane"] == "measured" and c["n"] >= C.COUNCIL_MIN_N
                and c["factor"] is not None]
    # a weight of 1.00 is no skill and one under it a record worse than
    # always saying the base rate (calibration.trust_from_brier): neither
    # is "right" (council_grading.most_trusted says the same)
    above = [(v, c) for v, c in measured if c["factor"] > 1.0]
    days = C.COUNCIL_RECORD_DAYS
    if measured and not above:
        k = len(measured)
        return {"t": ("No one: the one measured voice in "
                      f"{_rg(regime)} weighs ×1.00 or less" if k == 1 else
                      f"No one: the {k} measured voices in {_rg(regime)} "
                      f"weigh ×1.00 or less")
                     + f" (live, {days} days).", "voice": None}
    if above:
        v, c = max(above, key=lambda vc: (vc[1]["factor"], vc[1]["n"]))
        return {"t": f"{name_of(v)}: weight ×{c['factor']:.2f} in {_rg(regime)}, "
                     f"{c['n']} graded calls (live, {days} days, every class).",
                "voice": v}
    top = sorted([(v, c) for v, c in cells if c["n"] > 0],
                 key=lambda vc: -vc[1]["n"])[:3]
    if not top:
        return {"t": f"No one yet: no voice has a graded call in {_rg(regime)} "
                     f"(live, {days} days).", "voice": None}
    names = ", ".join(f"{mid(name_of(v))} {c['n']}" for v, c in top)
    return {"t": f"No one yet: no voice has {C.COUNCIL_MIN_N} graded calls in "
                 f"{_rg(regime)} ({names}; live, {days} days).", "voice": None}


def _room_direction(P, now) -> dict:
    sess = _sessions(P)
    table = None
    if sess:
        s, voices, claims = sess[0]
        table = _table(s, voices, _sitting_view(s, voices, claims, now))
    return {"table": table, "thinks": _thinks(P, now),
            "disagrees": _disagrees(P, now), "right": _who_right(P, now)}


# ── the throne ────────────────────────────────────────────────────────────

def _hand_now(P) -> list:
    C = _C()
    from ai_agents.council_grading import HAND_EMPTY
    rec, reg = P.get("record"), P.get("regime")
    if rec is None:
        return [SEATS_UNREAD]
    regime = (reg or {}).get("regime") or "unknown"
    if not (reg or {}).get("report") or regime == "unknown":
        return ["No seat: the regime is unknown, so no cell is measured."]
    rows = [h for h in rec["hands"] if h["regime"] == regime]
    if not rows:
        return [f"No cell in {_rg(regime)} has a graded call yet: no voice "
                f"holds the Hand here."]
    out = []
    for h in rows:
        cls = h["asset_class"] or "every class"
        if h["voice"]:
            b = h["brier"]
            out.append(f"{cls}: {mid(name_of(h['voice']))} · "
                       f"×{h['factor']:.2f} · {h['n']} graded calls in this "
                       f"cell (live, {C.COUNCIL_RECORD_DAYS} days) · Brier "
                       + (f"{b:.2f}" if b is not None else DASH))
        else:
            out.append(f"{cls}: {h['why_empty'] or HAND_EMPTY} (the seat needs "
                       f"{C.COUNCIL_HAND_MIN_N} graded calls in this regime and "
                       f"class and a weight of at least "
                       f"{C.COUNCIL_HAND_MIN_FACTOR:.2f})")
    return out


def _hand_at(s, voices) -> list:
    """The Hand at one sitting: who held it, its side, and whether the
    chair went with it."""
    C = _C()
    h = s.get("hand") if isinstance(s.get("hand"), dict) else {}
    if not h:
        return ["The Hand was not read at this sitting."]
    if not h.get("voice"):
        if str(h.get("why_empty") or "").startswith(C.SEAT_UNREAD):
            return ["The seat could not be read at this sitting."]
        return ["No voice had earned the Hand in this cell."]
    # The Hand's side is written once wave 2 has answered (council.py): no
    # "side" key yet, or a wave-2 voice still asked, is not read, never
    # "no side taken".
    sitting = s.get("status") in ("queued", "sitting")
    wave2_out = any(r.get("wave") == 2 and r.get("status") == "asked"
                    for r in voices)
    read = "side" in h and not (sitting and wave2_out)
    side = h.get("side") or ""
    name = name_of(h["voice"])
    if side in ("for", "against"):
        first = f"{name} held the Hand, {side} the trade."
    elif not read and sitting:
        first = f"{name} holds the Hand; its side is read once wave 2 has answered."
    elif not read:
        first = f"{name} held the Hand; its side was not read."
    else:
        first = f"{name} held the Hand, with no side taken."
    lines = [first]
    emp = _row_of(voices, "emperor")
    if sitting and (emp is None or emp.get("status") == "asked"):
        lines.append("The Emperor has not ruled yet: the council is sitting.")
        return lines
    if emp is not None and emp.get("status") == "late":
        # he ruled, after the sitting closed: recorded and graded, and an
        # overruling the sitting never heard is not counted as one
        a = emp.get("answer") or {}
        lines.append("The Emperor ruled late, after the sitting closed"
                     + (": against it, not counted as an overruling."
                        if a.get("hand_overruled") else "."))
        return lines
    if emp is None or emp.get("status") != "spoke":
        lines.append("The Emperor did not rule.")
        return lines
    a = emp.get("answer") or {}
    if a.get("hand_overruled"):
        why = scrub(a.get("hand_why"), 200, money_marks(s)).rstrip(".")
        lines.append(f'The Emperor went against it: "{why}".' if why else
                     "The Emperor went against it without saying why.")
    elif side in ("for", "against"):
        lines.append("The Emperor went with it.")
    elif read:
        lines.append("Its side was none: there was nothing to overrule.")
    else:
        lines.append("Whether he went with it is not measured: its side was "
                     "not read.")
    return lines


def _hand_last(P) -> list:
    sess = _sessions(P)
    if sess is None:
        return [SENTENCE["sittings"]]
    got = _latest_sat(sess)
    if got is None:
        return ["No sitting in the last 7 days."]
    s, voices, _claims = got
    # under its label, AT THE LAST SITTING: the sitting, said once
    head = (f"{s['symbol']} {s.get('side') or ''}".strip()
            + f", {_at(s['created_at'], P.now)}:")
    return [head] + _hand_at(s, voices)


def _against_lines(rec) -> list:
    C = _C()
    if rec is None:
        return ["The record could not be read."]
    a = rec["against"]
    days = C.COUNCIL_RECORD_DAYS
    if not a["overruled"]:
        return [f"He has not gone against his Hand yet (live sittings, "
                f"{days} days)."]
    t = (f"Went against it {plural(a['overruled'], 'time')} (live sittings, "
         f"{days} days). Graded {a['graded']}: the "
         f"Emperor right {a['emperor_right']}, the Hand right {a['hand_right']}; "
         f"{a['unresolved']} inside a quarter R; {a['pending']} not graded yet. "
         f"Without a reason: {a['no_reason']}. When they agreed: right "
         f"{a['agreed']['right']} of {a['agreed']['n']}.")
    if a["graded"] < C.COUNCIL_MIN_N:
        t += f" Under {C.COUNCIL_MIN_N} graded: not measured."
    return [t]


def _mood_panel(P) -> dict:
    from ai_agents import council_mood as M
    m = P.get("mood")
    unread = m is None or m.get("unread")
    m = m or {"level": M.UNMEASURED, "measured_n": 0, "of": len(M.INPUTS),
              "inputs": {}, "why": ""}
    level = m["level"] if m["level"] in M.MOOD_LEVELS + (M.UNMEASURED,) \
        else M.UNMEASURED
    inputs = [{"key": k, "label": M.LABELS[k],
               "words": (m["inputs"].get(k) or {}).get("words") or "not read",
               "measured": bool((m["inputs"].get(k) or {}).get("measured"))}
              for k in M.INPUTS]
    sess = _sessions(P)
    got = _latest_sat(sess) if sess else None
    last = (f"At the last sitting: {got[0].get('mood') or M.NOT_READ}."
            if got else "No sitting in the last 7 days.")
    rec = P.get("record")
    if rec is None:
        graded = ["The record could not be read."]
    else:
        graded = []
        for row in rec["moods"]:
            if not row["n"]:
                graded.append(f"{row['level']}: none graded")
            elif row["thin"]:
                graded.append(f"{row['level']}: {row['n']} graded, too few to read")
            else:
                # commit_text is his MEAN commitment (council_mood
                # .mood_outcomes), never a share of the sittings
                graded.append(f"{row['level']}: {row['n']} graded · average "
                              f"{row['avg']} · won {row['won']} · the "
                              f"Emperor's average commitment {row['commit']}")
    return {"level": level, "level_words": M.LEVEL_WORDS[level],
            "head": MOOD_BOOK.format(level=level, n=m["measured_n"], of=m["of"]),
            "why": m.get("why") or "",
            "note": SENTENCE["mood"] if unread else "",
            "inputs": inputs, "caution": M.CAUTION_ONLY, "last": last,
            "graded_title": MOOD_GRADED_TITLE, "graded": graded,
            "graded_note": MOOD_GRADED_NOTE}


def _war_lines(P) -> list:
    w = P.get("war")
    if w is None:
        return [SENTENCE["war"]]
    out = []
    d = w.get("daily")
    if d is None:
        out.append("Daily stop: could not be read.")
    elif d["state"] == "no_limit":
        out.append("Daily stop: no limit is set on the book.")
    elif d["state"] == "no_book":
        out.append("Daily stop: unmeasured, the book has no value set.")
    elif d["state"] == "unpriced":
        out.append(f"Daily stop: unmeasured, {d['n']} closes carry no price.")
    else:
        mode = {"open": "OPEN", "elite": "ELITE ONLY", "shut": "SHUT"}.get(
            d["mode"], d["mode"].upper())
        line = (f"Daily stop: {mode} · {d['used_pct']:.0f}% of it used "
                f"(the stop: {d['limit_pct']:g}% of the book)")
        if d.get("unpriced"):
            line += (f" · {plural(d['unpriced'], 'close')} without a price, "
                     f"not counted")
        out.append(line)
    o = w.get("open")
    if o is None:
        out.append("Open risk: could not be read.")
    elif o["state"] == "no_limit":
        out.append("Open risk: no ceiling is set on the book.")
    elif o["state"] == "no_book":
        out.append("Open risk: unmeasured, the book has no value set.")
    else:
        line = (f"Open risk: {o['used_pct']:.0f}% of the ceiling used (the "
                f"ceiling: {o['limit_pct']:g}% of the book), at the stops of "
                f"{plural(o['rows'], 'position')}")
        if o["unstopped"]:
            line += f" · {o['unstopped']} without a stop, counted whole"
        out.append(line)
    e = w.get("elite")
    out.append("Elite entries: could not be read." if e is None else
               f"Elite entries: {e['used']} of {e['max']} in 24 h")
    return out


def _ai_line(P) -> dict:
    ai = P.get("ai")
    if ai is None:
        return {"t": SENTENCE["ai"], "used_pct": None, "council_pct": None,
                "deep_refused": False}
    if not ai["budget_set"]:
        return {"t": "AI today: no daily budget is set.", "used_pct": None,
                "council_pct": ai["council_pct"], "deep_refused": False}
    t = (f"AI today (core line): {ai['used_pct']}% of the day's allowance · "
         f"the council's share of that spend: {ai['council_pct']}%")
    if ai["deep_refused"]:
        t += " · deep calls refused, so the bot lane's council is silent"
    return {"t": t, "used_pct": ai["used_pct"],
            "council_pct": ai["council_pct"],
            "deep_refused": ai["deep_refused"]}


def _posture(P) -> dict:
    reg = P.get("regime")
    if reg is None:
        return {"t": SENTENCE["regime"], "rationale": ""}
    m = reg["measured"]
    t = f"{m['title_word'] or 'unmeasured'} · {m['note']}" if m["note"] \
        else (m["title_word"] or "unmeasured")
    b = reg["briefing"]
    if b is None:
        rationale = "No briefing today: the strategist runs at 06:00 UTC."
    elif b["error"]:
        rationale = "Today's briefing failed: its posture is unknown."
    else:
        rationale = (f"Today's briefing: {b['title']}"
                     + (f" · {b['rationale']}" if b["rationale"] else ""))
    return {"t": t, "rationale": rationale}


def _horizon(P) -> dict:
    h = P.get("horizon")
    if h is None:
        return {"chips": [], "t": (SENTENCE["horizon"] if "horizon" in P.errors
                                   else HORIZON_NONE)}
    return {"chips": h["chips"],
            "t": f"The newest Horizon view, {h['age_days']:.0f} days old: "
                 f"each class's tilt, from -2 to +2."}


def _battle_lines(P) -> list:
    b = P.get("battles")
    if b is None:
        return [SENTENCE["battles"]]
    lines = [f"Sat {plural(b['sat'], 'time')} on the live book: "
             f"{plural(b['bots'], 'bot order')}, {plural(b['tickets'], 'ticket')}."]
    parts = [f"won {b['won']}", f"lost {b['lost']}"]
    if b.get("even"):
        parts.append(f"even {b['even']}")
    parts.append(f"open {b['open']}")
    if b["unpriced"]:
        parts.append(f"unpriced {b['unpriced']}")
    lines.append(f"Orders that left: {b['left']} ({', '.join(parts)}) · net "
                 f"{b['net_r']:+.1f}R")
    lines.append(f"Argued, no order sent: {b['no_order']}.")
    apart = []
    if b["rehearsal"]:
        apart.append(f"{b['rehearsal']} filled in a rehearsal world")
    if b["repeat"]:
        apart.append(f"{b['repeat']} repeat" + ("s" if b["repeat"] > 1 else ""))
    if b["young"]:
        apart.append(f"{b['young']} not linked yet")
    if apart:
        lines.append("Counted apart: " + ", ".join(apart) + ".")
    e = b["emperor"]
    head = (f"The Emperor: fight {e['fight']} · smaller {e['fight_smaller']} · "
            f"refuse {e['refuse']}; ")
    if not e["graded"]:
        tail = "none graded yet."
    elif e["saved_r"] is None:
        tail = (f"on {e['graded']} graded, what his commitment saved is not "
                f"measured.")
    else:
        valued = ("" if e["valued"] == e["graded"]
                  else f" ({e['valued']} with a value)")
        tail = (f"on {e['graded']} graded{valued}, his commitment "
                f"{_worth(e['saved_r'])}.")
    lines.append(head + tail)
    return lines


def _chair_lines(P) -> list:
    C = _C()
    rec = P.get("record")
    if rec is None:
        return [SENTENCE["record"]]
    bench = rec["benchmarks"]
    n = bench[0]["n"] if bench else 0
    book = f"live, {C.COUNCIL_RECORD_DAYS} days"
    lines = []
    if n < C.COUNCIL_MIN_N or len(bench) < 3 \
            or any(b["brier"] is None for b in bench):
        lines.append(f"Not measured: {plural(n, 'graded sitting')} ({book}), "
                     f"{C.COUNCIL_MIN_N} needed.")
    else:
        best = min(range(3), key=lambda i: bench[i]["brier"])
        words = ("the Emperor", "the council weighted by record",
                 "the plain average")
        parts = [f"{words[i]} Brier {bench[i]['brier']:.3f}"
                 + (" (best)" if i == best else "") for i in range(3)]
        lines.append(f"Over {n} graded sittings ({book}): "
                     + " · ".join(parts) + ".")
    if rec["unpaired"]:
        lines.append(f"{plural(rec['unpaired'], 'graded sitting')} without the "
                     f"Emperor's call or the weights "
                     + ("is" if rec["unpaired"] == 1 else "are")
                     + " left out of all three.")
    ch = rec["chair"]
    if ch["over_n"] or ch["follow_n"]:
        lines.append(f"Of the voices he overruled ({book}), {ch['over_wrong']} "
                     f"of {ch['over_n']} {_were(ch['over_wrong'])} wrong; of "
                     f"those he followed, {ch['follow_right']} of "
                     f"{ch['follow_n']} {_were(ch['follow_right'])} right.")
    return lines


def _rulings(P, now) -> list:
    sess = _sessions(P) or []
    out = []
    for s, voices, claims in sess:
        emp = _row_of(voices, "emperor")
        if emp is None or emp.get("status") != "spoke":
            continue
        a = emp.get("answer") or {}
        followed = [_C().voice_key(v) for v in a.get("followed") or []]
        overruled = [_C().voice_key(o.get("voice") if isinstance(o, dict) else o)
                     for o in a.get("overruled") or []]
        t = (f"{_at(s['created_at'], now)} · {s['symbol']} "
             f"{s.get('side') or ''} · "
             f"{token('emperor', emp.get('verdict'), a)} · followed "
             f"{_names(followed)} · overruled {_names(overruled)} · "
             f"{outcome_of(s, now)}")
        out.append({"sitting": f"c{s['id']}", "t": t})
        if len(out) >= RULINGS_MAX:
            break
    return out


def _campaign(P, now) -> str:
    """No season objective is set; the long line he last stated in a live
    ruling of the last 7 days is quoted, scrubbed, when there is one."""
    for s, voices, _claims in _sessions(P) or []:
        emp = _row_of(voices, "emperor")
        if emp is None or emp.get("status") not in ("spoke", "late"):
            continue
        plan = (emp.get("answer") or {}).get("plan")
        if not plan:
            continue
        line = scrub(plan, 240, money_marks(s))
        on = f"{s['symbol']} {s.get('side') or ''}".strip()
        return CAMPAIGN_LINE.format(
            on=on, at=_at(s["created_at"], now),
            plan=WITHHELD if line == WITHHELD else f'"{line}"')
    return CAMPAIGN


def _room_throne(P, now) -> dict:
    sw = P.get("switches")
    if sw is None:
        status = SENTENCE["switches"]
    elif not sw["platform_master"]:
        status = STATUS_MASTER
    elif sw["council_bots"] or sw["council_ticket"]:
        status = STATUS_SHADOW
    else:
        status = STATUS_OFF
    rec = P.get("record")
    rulings = _rulings(P, now)
    return {"name": name_of("emperor"), "mono": MONO["emperor"],
            "role": ROLE["emperor"], "status": {"t": status},
            "campaign": {"t": _campaign(P, now)},
            "hand": {"now": _hand_now(P), "last": _hand_last(P),
                     "against": _against_lines(rec)},
            "mood": _mood_panel(P),
            "war": {"label": WAR_LABEL, "lines": _war_lines(P)},
            "ai": _ai_line(P), "posture": _posture(P), "horizon": _horizon(P),
            "battles": {"lines": _battle_lines(P)},
            "chair": {"lines": _chair_lines(P)},
            "rulings": rulings,
            "rulings_none": "" if rulings else "The Emperor has not ruled in the "
                                               "last 7 days."}


# ── the nine ──────────────────────────────────────────────────────────────

def _snap_entry(snap, cls_hint, voice):
    if not snap:
        return None
    entry = snap.get(cls_hint) if cls_hint in snap else None
    if entry is None or voice not in entry["weights"]:
        entry = max((e for e in snap.values() if voice in e["weights"]),
                    key=lambda e: e["at"], default=None)
    return entry


def _entry_cell(entry) -> str:
    return f"in {_rg(entry['regime'])} on {entry['class'] or 'every class'}"


def _weight_line(snap, cls_hint, voice, now=None, shared=None) -> dict:
    """One row's weight, short ('×1.15 measured · 34 graded · Brier 0.08
    vs 0.16'). The sitting it was read at is said once under THE NINE
    (`shared`, the entry most rows read); a row read at another sitting
    says its own. The full reason is the dossier's (round 2: every row
    repeated the same sitting after the council's whole sentence)."""
    entry = _snap_entry(snap, cls_hint, voice)
    if entry is None:
        return {"t": NO_WEIGHT_READ, "factor": None, "lane": "",
                "sitting": None}
    w = entry["weights"][voice]
    f = w["factor"]
    words = weight_words(w["reason"], _entry_cell(entry))
    # the council's own reason opens with its lane ("measured in trending
    # on forex, ...", "neutral: 7 graded calls ..."): said once
    lane = "" if words.startswith(w["lane"]) else f" {w['lane']}"
    t = ((f"×{f:.2f}" if f is not None else DASH) + lane
         + (f" {words}" if words.startswith(("measured", "neutral"))
            else f" · {words}" if words else ""))
    if shared is None or entry["sitting"] != shared["sitting"]:
        t += (f" · read at the {_at(entry['at'], now)} sitting "
              f"({_rg(entry['regime'])} on {entry['class'] or 'every class'})")
    return {"t": t, "factor": f, "lane": w["lane"], "sitting": entry["sitting"]}


def _record_line(rec, voice) -> str:
    C = _C()
    if rec is None:
        return DASH
    v = next((x for x in rec["voices"] if x["voice"] == voice), None)
    if v is None or not v["n"]:
        return "Not graded yet."
    if v["n"] < C.COUNCIL_MIN_N:
        return f"{v['n']} graded · under {C.COUNCIL_MIN_N}, not measured"
    b = v["brier"]
    return (f"{v['right']} of {v['right'] + v['wrong']} graded weight calls "
            f"right · Brier " + (f"{b:.2f}" if b is not None else DASH)
            + (f" · {v['specialty']}" if v["specialty"] else "")
            + f" (live, {C.COUNCIL_RECORD_DAYS} days)")


def _hand_chips(P, voice) -> list:
    rec, reg = P.get("record"), P.get("regime")
    if rec is None or not (reg or {}).get("report"):
        return []
    regime = reg["regime"]
    return [f"THE HAND · {h['asset_class'] or 'every class'}"
            for h in rec["hands"] if h["regime"] == regime
            and h["voice"] == voice]


def _rule_line(P, voice) -> str:
    phase = P.get("phase")
    g = phase["graded"] if phase else None
    n = phase["shadow_n"] if phase else 30
    if voice == "executioner":
        return (f"By rule, once {n} trades are graded ("
                + (f"{g} so far" if g is not None else "not read")
                + "): a veto refuses the entry and a cut scales it.")
    if voice == "champion":
        return ("By rule, once binding: past the daily stop, an elite entry "
                "needs the Champion to back it with more conviction than the "
                "Executioner.")
    return ""


def _nine_row(P, voice, now) -> dict:
    sess = _sessions(P) or []
    latest = None
    today = {"for": 0, "against": 0, "none": 0, "silent": 0}
    start = _day_start(now)
    for s, voices, claims in sess:
        r = _row_of(voices, voice)
        if r is None:
            continue
        view = None
        if latest is None or s["created_at"] >= start:
            view = _sitting_view(s, voices, claims, now)
        if latest is None:
            side = view["sides"].get(voice, "absent")
            st = r.get("status")
            words = ""
            # its time, as a call's: a silence of six days ago never reads
            # as today's
            at = _at(s["created_at"], now)
            if st == "late":
                words = f"Late at the last sitting ({at}): not heard by the chair."
            elif st not in SPOKEN:
                words = ((f"Waiting at the last sitting ({at}): " if side == "waiting"
                          else f"Silent at the last sitting ({at}): ")
                         + voice_silence(st, r.get("why"), r.get("wave"),
                                         s.get("status")) + ".")
            latest = {"sitting": f"c{s['id']}", "status": st,
                      "token": token(voice, r.get("verdict"), r.get("answer"))
                      if st in SPOKEN else "",
                      "side": side, "glyph": SIDE_GLYPH.get(side, "·"),
                      "p": _p_line(voice, r) if st in SPOKEN else "",
                      "p_work": _num(r.get("p_work")) if voice != "skeptic"
                      else None,
                      "symbol": s["symbol"], "trade_side": s.get("side") or "",
                      "at": _iso(s["created_at"]),
                      # a call up to 7 days old says its day, never reads
                      # as the voice's stance now
                      "when": _at(s["created_at"], now), "words": words,
                      "cls": s.get("asset_class") or ""}
        if s["created_at"] >= start and view is not None:
            side = view["sides"].get(voice)
            if side in today:
                today[side] += 1
            elif side == "waiting":
                pass
    tally = " · ".join(f"{today[k]} {w}" for k, w in (
        ("for", "for"), ("against", "against"), ("none", "no side"),
        ("silent", "silent")) if today[k])
    snap = P.get("snapshot")
    return {"key": voice, "name": name_of(voice), "mono": MONO[voice],
            "a": dict(SEATS).get(voice), "role": ROLE[voice],
            "latest": latest, "none": "" if latest else NO_CALL,
            "today": {"t": f"Today: {tally}" if tally else "No sitting today."},
            "weight": (_weight_line(snap, (latest or {}).get("cls", ""), voice,
                                    now)
                       if snap is not None else
                       {"t": SENTENCE["snapshot"], "factor": None, "lane": ""}),
            "record": {"t": _record_line(P.get("record"), voice)},
            "rule": _rule_line(P, voice),
            "hand": _hand_chips(P, voice)}


def _room_nine(P, now) -> dict:
    sw, ai = P.get("switches"), P.get("ai")
    notes = []
    if sw is not None:
        if not sw["platform_master"]:
            notes.append(NOTE_MASTER_OFF)
        if not sw["trade_debate"]:
            notes.append(NOTE_DEBATE_OFF)
        if not sw["council_bots"] and not sw["council_ticket"]:
            notes.append(NOTE_COUNCIL_OFF)
    if ai and ai.get("spent_out"):
        notes.append(NOTE_BUDGET_SPENT)
    sess = _sessions(P)
    if sess is not None and not sess:
        data = P.get("sittings") or {}
        notes.append(NO_SESSION if not data.get("ever") else NO_SITTING_7)
    rows = {v: _nine_row(P, v, now) for t in TRIADS for v in t["voices"]}
    weights_note = ""
    snap = P.get("snapshot")
    if snap:
        entries = {v: _snap_entry(snap, (r["latest"] or {}).get("cls", ""), v)
                   for v, r in rows.items()}
        read = [e for e in entries.values() if e is not None]
        if read:
            # the sitting most rows were read at, said once (the newest
            # on a tie); a row read at another says its own
            ids = [e["sitting"] for e in read]
            shared = max(read, key=lambda e: (ids.count(e["sitting"]), e["at"]))
            weights_note = NINE_WEIGHTS.format(
                at=_at(shared["at"], now), regime=_rg(shared["regime"]),
                cls=shared["class"] or "every class")
            for v, r in rows.items():
                r["weight"] = _weight_line(
                    snap, (r["latest"] or {}).get("cls", ""), v, now, shared)
    triads = [{"key": t["key"], "title": t["title"], "sub": t["sub"],
               "voices": [rows[v] for v in t["voices"]]}
              for t in TRIADS]
    return {"notes": notes, "weights_note": weights_note, "triads": triads}


# ── the traders ───────────────────────────────────────────────────────────

def _room_traders(P, now) -> dict:
    t = P.get("traders")
    if t is None or t.get("unread"):
        return {"cards": [], "matrix": [], "line": "",
                "unread": SENTENCE["traders"], "foot": TRADERS_FOOT,
                "orcs": ORCS}
    cards = []
    for c in t["cards"]:
        f = c["factor"]
        lane = c["lane"]
        factor = (f"×{f:.2f}" if f is not None else DASH) + (
            f" measured n={c['n']}" if lane == "measured" else
            " prior (unproven)" if lane == "prior" else " neutral")
        cards.append({**c, "factor_t": factor,
                      "band_t": f"share of the book {c['band']}, now "
                                f"{c['band_now']}",
                      "worn_t": worn_words(c.get("worn_live", 0),
                                           c.get("worn_live_on", 0),
                                           c.get("worn_paper", 0))})
    if t["regime"] == "unknown":
        line = TRADERS_UNKNOWN
    else:
        line = (f"{regime_title(t['regime'])} (confidence "
                f"{t['confidence']:.2f}) · "
                f"{t['measured']} of 3 factors measured · {t['n_measured']} "
                f"of {t['n_cells']} cells learned on live fills · Mind read "
                f"{_ago(t['age_min'])}")
    return {"cards": cards, "matrix": t["matrix"], "line": line,
            "key": TRADERS_KEY if t["matrix"] else "",
            "unread": "", "foot": TRADERS_FOOT, "orcs": ORCS,
            "regime": t["regime"]}


def worn_words(live, live_on, paper) -> str:
    """Who wears a persona, by book, short for a card a third of the band
    wide: 'worn by 2 live configs (1 on) and 1 paper'. A paper config is
    never counted as a live one, nor a switched-off one as trading."""
    if not live and not paper:
        return "worn by no config"
    if not live:
        return f"worn by {plural(paper, 'paper config')}"
    on = ("on" if live_on else "off") if live == 1 else (
        "none on" if not live_on else "all on" if live_on == live
        else f"{live_on} on")
    return (f"worn by {plural(live, 'live config')} ({on})"
            + (f" and {paper} paper" if paper else ""))


# ── the public builders ───────────────────────────────────────────────────

ROOM = (("head", _room_head), ("direction", _room_direction),
        ("throne", _room_throne), ("nine", _room_nine),
        ("traders", _room_traders))


def build_room(user, ev=None) -> dict:
    """{head, direction, throne, nine, traders}: the open band. An event
    read (`ev`) rebuilds only the panels that event wakes."""
    now = timezone.now()
    P = _Panels(user, now, WAKE.get(ev, ()) if ev else ())
    return {name: _fenced(name, lambda fn=fn: fn(P, now)) for name, fn in ROOM}


def build_sittings(user, before=None, ev=None) -> dict:
    """{cards, more, empty}: the sittings, newest first (the cached 20 of
    the last 7 days, or 20 older than `before`)."""
    now = timezone.now()
    if before is None:
        P = _Panels(user, now, WAKE.get(ev, ()) if ev else ())
        data = P.get("sittings")
        if data is None:
            return {"cards": [], "more": False, "empty": SENTENCE["sittings"]}
    else:
        data = _read_sittings_rows(now, before=before)
    # the merged set's first SITTINGS_MAX are the newest twenty of any
    # status (_read_sittings_rows): the list shows those
    rows = data["sessions"][:SITTINGS_MAX]
    cards = [_card(s, data["voices"].get(s["id"], []),
                   data["claims"].get(s["id"], []), now) for s in rows]
    empty = ""
    if not cards:
        empty = (NO_SITTING_7 if before is None and data.get("ever") else
                 NO_SESSION if before is None else "No older sitting.")
    out = {"cards": cards, "more": len(rows) >= SITTINGS_MAX, "empty": empty}
    # the script repaints the list only when this changes
    out["rev"] = _rev(out)
    return out


def _skeptic_line(rec) -> str:
    """THE SKEPTIC TOLD: the record's own counts, with their book."""
    C = _C()
    sk = rec["skeptic"]
    return (f"Told {plural(sk['named'], 'time')} (live sittings, "
            f"{C.COUNCIL_RECORD_DAYS} days); his attack named the voice he "
            f"was told {sk['first']} of {sk['attacked']} times; right "
            f"{sk['right']} of {sk['graded']} graded."
            + (f" Under {C.COUNCIL_MIN_N} graded: not measured."
               if sk["graded"] < C.COUNCIL_MIN_N else ""))


def build_record(user) -> dict:
    """The record tab: drawn from the cached record matrix and the regime
    now, so a warm read costs no query."""
    C = _C()
    now = timezone.now()
    P = _Panels(user, now)
    rec, reg = P.get("record"), P.get("regime")
    if rec is None:
        return {"error": SENTENCE["record"]}
    regime = (reg or {}).get("regime") or "unknown"
    hands = {}
    for h in rec["hands"]:
        cls = h["asset_class"] or "every class"
        hands.setdefault(h["regime"], []).append(
            f"{cls}: {mid(name_of(h['voice']))} · ×{h['factor']:.2f} · "
            f"{h['n']} graded" if h["voice"] else
            f"{cls}: {h['why_empty'] or 'no voice has earned it yet'}")
    hand_rows = [{"regime": rg, "now": rg == regime, "lines": lines}
                 for rg, lines in sorted(hands.items())]
    against = _against_lines(rec)
    for hv, d in sorted(rec["against"]["by_voice"].items()):
        against.append(f"Against {mid(name_of(hv))}: graded {d['graded']}, the "
                       f"Emperor right {d['emperor_right']}, the Hand right "
                       f"{d['hand_right']}.")
    skeptic = _skeptic_line(rec)
    weights = []
    for row in rec["matrix"]:
        weights.append({"voice": row["voice"], "name": name_of(row["voice"]),
                        "mono": MONO.get(row["voice"], ""),
                        "cells": [{"regime": c["regime"],
                                   "now": c["regime"] == regime,
                                   "measured": c["lane"] == "measured",
                                   "t": (f"×{c['factor']:.2f}"
                                         if c["lane"] == "measured"
                                         and c["factor"] is not None
                                         else DASH),
                                   "n": c["n"]} for c in row["cells"]]})
    weights_key = " · ".join(f"{w['mono']} {mid(w['name'])}" for w in weights
                             if w["mono"])
    weights_key = (weights_key + ". " if weights_key else "") + WEIGHTS_KEY_TAIL
    bench = _chair_lines(P)
    rp = rec["replay"]
    if rp["n"]:
        # record_matrix reads every realized sitting with a replay, with
        # no window; only a live sitting is ever given a realized truth
        bench.append(f"On {rp['n']} sittings with both (live sittings, all "
                     f"time), the replay and the realized result agreed in "
                     f"sign on {rp['agree']}.")
    mood = _mood_panel(P)
    return {"hands": hand_rows or [{"regime": regime, "now": True, "lines": [
                "No cell has a graded call yet: no voice holds the Hand."]}],
            "hand_bar": (f"Live record, {C.COUNCIL_RECORD_DAYS} days. A seat "
                         f"needs {C.COUNCIL_HAND_MIN_N} graded calls in "
                         f"its regime and class and a weight of at least "
                         f"{C.COUNCIL_HAND_MIN_FACTOR:.2f}."),
            "against": against, "skeptic": skeptic,
            "moods": mood["graded"], "moods_title": mood["graded_title"],
            "moods_note": mood["graded_note"],
            "regimes": rec["regimes"], "weights": weights,
            "weights_key": weights_key, "bench": bench}


def _voice_block(s, r, view, claims, now) -> dict:
    """One voice in a transcript."""
    C = _C()
    v = r["voice"]
    st = r.get("status")
    a = r.get("answer") or {}
    marks = money_marks(s)
    side = view["sides"].get(v, "absent")
    block = {"voice": v, "name": name_of(v), "mono": MONO.get(v, v[:2].upper()),
             "side": side, "glyph": SIDE_GLYPH.get(side, "·"), "status": st,
             "token": "", "words": "", "p": "", "key": "", "reasons": [],
             "note": "", "weight": "", "model": "", "grades": "",
             "silence": "", "extra": []}
    if st in SPOKEN:
        block["token"] = token(v, r.get("verdict"), a)
        block["words"] = scrub(C.verdict_words(v, a), 200, marks)
        block["p"] = _p_line(v, r)
        block["key"] = _key_line(v, a, block["words"], marks)
        reasons = a.get("reasons") if isinstance(a.get("reasons"), list) else []
        block["reasons"] = [scrub(x, 200, marks) for x in reasons[:REASONS_MAX]]
        notes = [a.get("note"), a.get("fix_refused"), a.get("touch_note")]
        block["note"] = " · ".join(scrub(x, 200, marks) for x in notes if x)
        if r.get("model"):
            block["model"] = f"answered by {scrub(r['model'], 60)}"
        if v == "theorist" and a.get("posted_theory"):
            block["extra"].append(f"posted theory #{int(_num(a['posted_theory']) or 0)}")
        if v == "opportunist" and isinstance(a.get("alternative"), dict):
            alt = a["alternative"]
            conf = _num(alt.get("confidence"))
            block["extra"].append(
                f"The alternative: {scrub(alt.get('symbol'), 20)} "
                f"{scrub(alt.get('direction'), 8)} within "
                f"{_num(alt.get('horizon_hours')) or 0:g} hours"
                + (f", confidence {conf:.0%}" if conf is not None else ""))
            if alt.get("why"):
                block["extra"].append(scrub(alt.get("why"), 200, marks))
        if v == "fixer" and _num(a.get("p_work_fixed")) is not None:
            block["extra"].append(
                f"says it works {_num(a['p_work_fixed']):.0%} with the fix")
        if v == "awakened" and a.get("footprints"):
            block["extra"].append("cites " + ", ".join(
                scrub(x, 6) for x in list(a["footprints"])[:12]))
    else:
        block["silence"] = (("Waiting: " if side == "waiting" else "Silent: ")
                            + voice_silence(st, r.get("why"), r.get("wave"),
                                            s.get("status")) + ".")
    if st == "late" and v != "emperor":
        block["silence"] = "Late: not heard by the chair."
    # the chair answering late is said once, over his block (EMPEROR_LATE)
    if r.get("weight_seen") is not None:
        # short, and its cell (the sitting's own) left out: the same tail
        # on ten blocks was noise (round 2)
        cell = f"in {_rg(s.get('regime'))} on {s.get('asset_class') or 'every class'}"
        words = weight_words(reason_words(r.get("weight_reason")), cell) \
            if r.get("weight_reason") else ""
        block["weight"] = (f"Weight ×{float(r['weight_seen']):.2f}"
                           + (f" ({words})" if words else ""))
    else:
        block["weight"] = "Weight: none read at this sitting"
    grades = []
    for c in claims:
        if c.get("voice_key") == v:
            kind = str(c.get("kind") or "")
            grades.append(f"{CLAIM_WORDS.get(kind, kind.replace('_', ' '))}: "
                          f"{GRADE_WORDS.get(c.get('grade'), DASH)}")
    block["grades"] = " · ".join(grades)
    if v == "emperor":
        block["smaller"] = r.get("verdict") == "fight_smaller"
    return block


def _key_line(voice, answer, words: str = "", marks=None) -> str:
    """The line a voice is quoted by. The Skeptic's is rebuilt in words:
    the council's own joins his target's key and his flaw's code
    ('champion: "..." (thin_sample)'); the flaw is left out when his
    verdict's `words` already name it ("shaky: the Champion, a thin
    sample")."""
    C = _C()
    a = answer or {}
    if voice != "skeptic":
        return scrub(C.key_line(voice, a), 300, marks)
    claim = " ".join(str(a.get("claim") or "").split())
    if not claim:
        return ""
    target = C.voice_key(a.get("target")) or ""
    who = name_of(target) if target in C.ALL_VOICES else "A voice"
    flaw = C.FLAW_WORDS.get(str(a.get("flaw") or ""))
    if flaw and flaw in (words or ""):
        flaw = ""
    return scrub(f'{who}: "{claim}"' + (f" ({flaw})" if flaw else ""), 300,
                 marks)


def _skeptic_told(hand) -> str:
    h = hand if isinstance(hand, dict) else {}
    how, v = h.get("trusted_why") or "", h.get("trusted") or ""
    if how == "hand" and v:
        return f"Told to attack {mid(name_of(v))} first: the Emperor's Hand."
    if how == "highest" and v:
        return (f"Told to attack {mid(name_of(v))} first: the best measured "
                f"record in this cell.")
    if how == "none":
        return "No voice was named: none had earned trust in this cell."
    if how == "unread":
        return "Not told: the record could not be read."
    return ""


def build_sitting(user, session_id) -> dict | None:
    """One transcript: the Emperor, then the dissent, then the others in
    seat order. None when the sitting is not a live one on record."""
    from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                          CouncilVoice)
    C = _C()
    now = timezone.now()
    s = (CouncilSession.objects.filter(id=int(session_id), venue="live")
         .values(*SESSION_FIELDS).first())
    if s is None:
        return None
    s["trade_meta"] = _trade_meta(s.pop("trade__metadata", None))
    voices = list(CouncilVoice.objects.filter(session_id=s["id"])
                  .values(*VOICE_FIELDS))
    claims = []
    for c in CouncilClaim.objects.filter(session_id=s["id"]).values(*CLAIM_FIELDS):
        payload = c.get("payload") if isinstance(c.get("payload"), dict) else {}
        c["payload"] = {"target": str(payload.get("target") or "")}
        claims.append(c)
    side_claims = [c for c in claims if c["kind"] in SIDE_KINDS]
    view = _sitting_view(s, voices, side_claims, now)
    dis = view["dissent"]
    blocks = {r["voice"]: _voice_block(s, r, view, claims, now) for r in voices}
    emp = view["emperor"]
    emperor, late = None, ""
    if emp is not None and emp.get("status") == "spoke":
        a = emp.get("answer") or {}
        marks = money_marks(s)
        emperor = blocks.get("emperor")
        followed = [C.voice_key(v) for v in a.get("followed") or []]
        overruled = [o for o in a.get("overruled") or [] if isinstance(o, dict)]
        battle = scrub(a.get("battle"), 300, marks) if a.get("battle") else ""
        emperor["extra"] = (
            [f"Followed: {_names(followed)}.",
             "Overruled: " + ("; ".join(
                 f"{mid(name_of(C.voice_key(o.get('voice'))))}"
                 + (f": {scrub(o.get('why'), 200, marks)}" if o.get("why")
                    else "")
                 for o in overruled if C.voice_key(o.get("voice")))
                 if overruled else "no one") + "."]
            # his quoted key line is his battle: said once
            + [f"The battle: {battle}"
               if battle and battle != emperor["key"] else "",
               f"What it costs the war: {scrub(a.get('war_cost'), 300, marks)}"
               if a.get("war_cost") else "",
               f"The long line: {scrub(a.get('plan'), 300, marks)}"
               if a.get("plan") else ""]
            + _hand_at(s, voices)
            + [f"The people's mood at the sitting: {s.get('mood') or 'not read'}."])
        emperor["extra"] = [x for x in emperor["extra"] if x]
    elif emp is not None and emp.get("status") == "late":
        late = EMPEROR_LATE
    if "skeptic" in blocks:
        told = _skeptic_told(s.get("hand"))
        if told:
            blocks["skeptic"]["extra"].append(told)
    order = [v for v, _a in SEATS]
    dissent = [blocks[v] for v in dis["dissent"] if v in blocks and v != "emperor"]
    others = [blocks[v] for v in order if v in blocks
              and v not in dis["dissent"]]
    if late and "emperor" in blocks:
        others.append(blocks["emperor"])
    asked = [r for r in voices if r.get("wave", 1) >= 1]
    only_debate = not asked or s.get("status") == "record"
    trade_url = ""
    if s.get("trade_id") and _world(s) == "live":
        from django.urls import reverse
        trade_url = reverse("forensics_detail", args=[s["trade_id"]])
    kind = "BOT ORDER" if s["origin"] == "bot" else "TICKET"
    head = (f"{kind} · {s['symbol']} ({s.get('asset_class') or 'no class'}) "
            f"{s.get('side') or ''} · argued {_at(s['created_at'], now)} · "
            f"regime {_rg(s.get('regime'))}")
    sentence, graded = said_once(
        view["outcome"], session_sentence(s.get("status"), s.get("why"),
                                          view["debate"]),
        grade_notes_sentence(s.get("grade_notes")))
    grade = _grade_chip(s)
    # the model once in the head when every voice that answered shares it
    spoken = [r for r in voices if r.get("status") in SPOKEN]
    models = {str(r.get("model") or "") for r in spoken}
    model = ""
    if len(models) == 1 and "" not in models:
        model = f"Every answer came from {scrub(models.pop(), 60)}."
        for b in blocks.values():
            b["model"] = ""
    out = {"id": f"c{s['id']}", "head": head, "at": _iso(s["created_at"]),
           "table": _table(s, voices, view), "sides": view["sides"],
           "outcome": outcome_shown(view["outcome"], grade),
           "sentence": sentence, "graded": graded, "model": model,
           "grade": grade, "emperor": emperor, "emperor_late": late,
           "dissent": dissent, "others": others,
           "only_debate": ONLY_DEBATE if only_debate else "",
           # the Emperor's block already says it when he ruled
           "mood": "" if emperor is not None else
                   f"The people's mood at the sitting: {s.get('mood') or 'not read'}.",
           "trade_id": s.get("trade_id") if trade_url else None,
           "trade_url": trade_url}
    out["ask"] = {"subject": f"{s['symbol']} {s.get('side') or ''} sitting".strip(),
                  "kind": "sitting", "facts": facts_for_sitting(s, view, blocks)}
    return out


def facts_for_sitting(s, view, blocks) -> str:
    """The facts that travel with a question about one sitting: scrubbed
    lines only, no money, at most FACTS_MAX characters."""
    origin = "a bot's order" if s["origin"] == "bot" else "a live ticket"
    parts = [f"{s['symbol']} {s.get('side') or ''} · {origin} · regime "
             f"{_rg(s.get('regime'))}"]
    emp = blocks.get("emperor")
    if emp and emp.get("status") == "spoke":
        parts.append(f"the Emperor: {emp['words']}")
    for v, _a in SEATS:
        b = blocks.get(v)
        if not b or b["status"] not in SPOKEN:
            continue
        bit = f"{b['name']}: {b['token']}"
        if b["p"]:
            bit += f", {b['p']}"
        if b["key"] and b["key"] != WITHHELD:
            bit += f', "{b["key"][:80]}"'
        parts.append(bit)
    parts.append(view["outcome"])
    text = " · ".join(parts)
    return text[:FACTS_MAX]


#: A voice's status at a sitting, in words: "asked" and "copied" are the
#: council's own codes (round 2).
NOTHING_TO_GRADE = "nothing to grade"


def _history_status(status, session_status) -> str:
    if status == "asked":
        return ("waiting" if session_status in ("queued", "sitting")
                else "silent")
    return {"spoke": "spoke", "copied": "in the debate", "late": "late",
            "silent": "silent"}.get(str(status or ""), "silent")


def _debate_status(key, phase) -> str:
    """The debate's two voices: in the order's path only once the debate
    binds; in shadow until then (round 2: "In the order's path" under a
    head that said SHADOW 1/30)."""
    if phase is None:
        return ("Argues every live bot entry; the debate's phase could not "
                "be read.")
    g, n = phase["graded"], phase["shadow_n"]
    if g >= n:
        return "In the order's path, by rule (the debate's two voices)."
    if key == "executioner":
        return (f"Argues every live bot entry in shadow ({g} of {n} graded): "
                f"his veto binds once {n} are graded.")
    return (f"Argues every live bot entry in shadow ({g} of {n} graded): once "
            f"{n} are graded, past the daily stop an elite entry needs his "
            f"backing.")


def _calls(key, grade) -> list:
    """A voice's best (right) or worst (wrong) graded calls, ranked by
    what the call was worth. The Emperor's battle and the Executioner's
    stance carry it (value_r: what his size, his veto or cut saved); a
    work call is ranked by the trade's size. The Skeptic's attack carries
    no R of its own (council_grading._grade_attack): it is said by what
    became of the call he attacked, the newest first."""
    from django.db.models import F
    from django.db.models.functions import Abs

    from ai_agents.council_models import CouncilClaim
    if key == "skeptic":
        rows = []
        for c in (CouncilClaim.objects
                  .filter(voice_key=key, venue="live", kind="attack",
                          grade=grade)
                  .annotate(rr=F("session__truth_r"))
                  .order_by("-graded_at", "-id")
                  .values("session_id", "session__symbol", "session__side",
                          "session__created_at", "rr", "payload",
                          "voice__verdict", "voice__answer")[:BEST_MAX]):
            payload = c["payload"] if isinstance(c["payload"], dict) else {}
            target = _C().voice_key(payload.get("target")) or ""
            whose = (f"{mid(name_of(target))}'s call" if target else
                     "the call he attacked")
            rr = _num(c["rr"])
            rows.append({"sitting": f"c{c['session_id']}", "t": " · ".join((
                f"{c['session__symbol']} {c['session__side']}",
                token(key, c["voice__verdict"], c["voice__answer"]),
                f"{GRADE_WORDS[grade]}: {whose} was "
                f"{'wrong' if grade == 'right' else 'right'}",
                f"the trade {rr:+.2f}R" if rr is not None
                else "the trade unpriced",
                f"{_utc(c['session__created_at']):%Y-%m-%d}"))})
        return rows
    kind = {"emperor": "battle", "executioner": "stance"}.get(key, "work")
    q = CouncilClaim.objects.filter(voice_key=key, venue="live", kind=kind,
                                    r__isnull=False, grade=grade)
    if kind in ("battle", "stance"):
        v = F("value_r")
        q = q.order_by(v.desc(nulls_last=True) if grade == "right"
                       else v.asc(nulls_last=True), Abs("r").desc())
    else:
        q = q.order_by(Abs("r").desc())
    rows = []
    for c in q.values("session_id", "session__symbol", "session__side",
                      "session__created_at", "r", "value_r", "grade",
                      "voice__verdict", "voice__answer")[:BEST_MAX]:
        rows.append({"sitting": f"c{c['session_id']}",
                     "t": f"{c['session__symbol']} {c['session__side']} · "
                          f"{token(key, c['voice__verdict'], c['voice__answer'])}"
                          f" · {call_worth(key, c)} · "
                          f"{_utc(c['session__created_at']):%Y-%m-%d}"})
    return rows


def call_worth(key, c) -> str:
    """What one graded call was worth, never the trade's R alone: a
    smaller commitment on a losing trade is right, and the trade's -1R is
    not what it earned. 'right · the trade -1.00R · his size saved +0.50R'
    (council_grading: a battle's value is (commit - 1) x R; the
    Executioner's stance, what his veto or cut saved)."""
    r, v = _num(c.get("r")), _num(c.get("value_r"))
    bits = [GRADE_WORDS.get(c.get("grade"), DASH),
            f"the trade {r:+.2f}R" if r is not None else "the trade unpriced"]
    if v is not None:
        who = "his size" if key == "emperor" else "the call"
        bits.append(f"{who} {_worth(v)}")
    return " · ".join(bits)


#: Seconds a voice's dossier is kept: an open dossier is asked again
#: every minute, and an unchanged one costs no query and no repaint.
VOICE_TTL = 300


def build_voice(user, key) -> dict:
    """One voice's dossier: the weight the Emperor last read, its record by
    regime, the table's record, the Hand, its best and worst graded calls,
    its history and its calls today (in calls and percent, never dollars).
    Kept VOICE_TTL per voice, with its `rev`: it reads only the platform's
    panels (none of USER_SCOPED), so one copy serves every staff reader.
    A dossier built while a panel failed is never kept."""
    ck = f"{CACHE_PREFIX}:voice:{key}"
    hit = cache.get(ck)
    if hit is not None:
        return hit
    P = _Panels(user, timezone.now())
    out = _build_voice(P, key)
    out["rev"] = _rev(out)
    if not P.errors:
        cache.set(ck, out, VOICE_TTL)
    return out


def _build_voice(P, key) -> dict:
    from ai_agents.council_models import CouncilClaim, CouncilVoice
    C = _C()
    now = P.now
    rec, snap, reg, ai, sw = (P.get("record"), P.get("snapshot"),
                              P.get("regime"), P.get("ai"), P.get("switches"))
    regime = (reg or {}).get("regime") or "unknown"
    out = {"key": key, "name": name_of(key), "mono": MONO[key],
           "role": ROLE[key], "a": dict(SEATS).get(key)}
    if sw is None:
        status = SENTENCE["switches"]
    elif not sw["platform_master"]:
        # the master switch stops every automated task, the debate's too
        status = STATUS_MASTER
    elif key in ("executioner", "champion") and sw["trade_debate"]:
        status = _debate_status(key, P.get("phase"))
    elif sw["council_bots"] or sw["council_ticket"]:
        status = "Seated in shadow: recorded and graded, never in an order's path."
    else:
        status = "Not sitting: the council's switches are off."
    out["status"] = status
    out["hand_cells"] = [f"Holds the Hand in {_rg(h['regime'])} on "
                         f"{h['asset_class'] or 'every class'}"
                         for h in (rec or {}).get("hands", [])
                         if h["voice"] == key]
    weights = []
    if snap is None:
        weights.append(SENTENCE["snapshot"])
    else:
        for cls, e in sorted(snap.items()):
            w = e["weights"].get(key)
            if w is None:
                continue
            f = w["factor"]
            # the council's reason opens with its lane: said once
            lane = ("" if w["reason"].startswith(w["lane"])
                    else f" {w['lane']}")
            weights.append(f"{cls or 'every class'}, {_rg(e['regime'])}, "
                           f"{_at(e['at'], now)}: "
                           + (f"×{f:.2f}" if f is not None else DASH)
                           + lane
                           + (f" · {w['reason']}" if w["reason"] else ""))
        if not weights:
            weights.append(NO_WEIGHT_READ)
    out["weights"] = weights
    cells = []
    if rec is not None:
        row = next((r for r in rec["matrix"] if r["voice"] == key), None)
        for c in (row or {}).get("cells", []):
            measured = c["lane"] == "measured"
            cells.append({"regime": c["regime"], "now": c["regime"] == regime,
                          "measured": measured,
                          "t": (f"{_rg(c['regime'])}: ×{c['factor']:.2f} · "
                                f"{c['n']} graded"
                                if measured and c["factor"] is not None else
                                f"{_rg(c['regime'])}: {DASH} ({c['n']} graded)")})
    out["regimes"] = cells
    table, specialty = DASH, ""
    if rec is not None:
        v = next((x for x in rec["voices"] if x["voice"] == key), None)
        if v is not None:
            f, b, base = v["factor"], v["brier"], v["base_rate"]
            table = ((f"×{f:.2f}" if f is not None else DASH) + f" {v['lane']} · "
                     f"{v['n']} graded · Brier "
                     + (f"{b:.2f}" if b is not None else DASH)
                     + " · base rate " + (f"{base:.0%}" if base is not None else DASH)
                     + f" · {v['right']} of {v['right'] + v['wrong']} right · "
                       # hand_n counts the TICKET lane: "Hand" is only ever
                       # the Emperor's Hand
                       f"bot {v['bot_n']} / ticket {v['hand_n']} (live, "
                       f"{C.COUNCIL_RECORD_DAYS} days, every class)")
            specialty = v["specialty"]
    out["table"], out["specialty"] = table, specialty
    hand = []
    if rec is None:
        hand.append("The record could not be read.")
    elif key == "emperor":
        hand += _against_lines(rec)
        for hv, d in sorted(rec["against"]["by_voice"].items()):
            hand.append(f"Against {mid(name_of(hv))}: graded {d['graded']}, "
                        f"he was right {d['emperor_right']}, it was right "
                        f"{d['hand_right']}.")
    else:
        # The council counts per voice only the GRADED overrulings
        # (council_grading.against_hand): one pending, or inside a quarter
        # R, is not in by_voice, so its absence never means "never
        # overruled".
        d = rec["against"]["by_voice"].get(key)
        book = f"live sittings, {C.COUNCIL_RECORD_DAYS} days"
        if d:
            hand.append(f"When the Emperor went against it as his Hand ({book}): "
                        f"graded {d['graded']}, it was right {d['hand_right']}, "
                        f"he was right {d['emperor_right']}.")
        elif out["hand_cells"]:
            hand.append(f"No graded overruling of it as the Hand yet ({book}).")
        else:
            # never "no overruling of it as the Hand yet" for a voice that
            # holds no seat (round 2: said of the Skeptic, who never held it)
            hand.append("Holds the Hand in no cell now.")
        if key == "skeptic":
            hand.append(_skeptic_line(rec))
    out["hand"] = hand
    out["best"], out["worst"] = _calls(key, "right"), _calls(key, "wrong")
    out["calls_none"] = "No graded call yet."
    hist = list(CouncilVoice.objects.filter(voice=key, session__venue="live")
                .order_by("-session__created_at")
                .values("session_id", "session__symbol", "session__side",
                        "session__created_at", "session__status", "verdict",
                        "status", "answer")[:HISTORY_MAX])
    grades = {}
    if hist:
        dkinds = ("battle",) if key == "emperor" else ("stance", "attack", "work")
        by = {}
        for c in CouncilClaim.objects.filter(
                session_id__in=[h["session_id"] for h in hist], voice_key=key,
                kind__in=dkinds).values("session_id", "kind", "stance", "p",
                                        "grade", "payload"):
            by.setdefault(c["session_id"], []).append(_claim(c))
        for sid, cs in by.items():
            pick = (next((c for c in cs if c.kind == "battle"), None)
                    if key == "emperor" else C.deciding_claim(cs, key))
            if pick is not None:
                grades[sid] = pick.grade
    out["history"] = [{
        "sitting": f"c{h['session_id']}",
        "t": " · ".join(x for x in (
            f"{_utc(h['session__created_at']):%Y-%m-%d}",
            f"{h['session__symbol']} {h['session__side']}",
            token(key, h["verdict"], h["answer"]) if h["status"] in SPOKEN
            else "",
            _history_status(h["status"], h["session__status"]),
            GRADE_WORDS.get(grades.get(h["session_id"]), NOTHING_TO_GRADE))
            if x)}
        for h in hist]
    if ai is None:
        today = SENTENCE["ai"]
    else:
        from ai_agents.council_grading import _agents_for
        n, pct, models = 0, 0.0, []
        for agent in _agents_for(key):
            a = ai["agents"].get(agent)
            if not a:
                continue
            n += a["n"]
            pct += a["pct"] or 0.0
            models += [m for m in a["models"] if m not in models]
        if not n:
            today = "No call today."
        else:
            today = (f"Today: {plural(n, 'call')}"
                     + (f" · {pct:.0f}% of the day's AI allowance"
                        if ai["budget_set"] else "")
                     + (f" · answered by {', '.join(models)}" if models else ""))
    out["today"] = today
    facts = [f"{name_of(key)} · {table}"]
    if specialty:
        facts.append(specialty)
    facts += [h["t"] for h in out["history"][:5]]
    out["ask"] = {"subject": mid(name_of(key)), "kind": "voice",
                  "facts": " · ".join(facts)[:FACTS_MAX]}
    return out
