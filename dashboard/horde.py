# -*- coding: utf-8 -*-
"""THE HORDE (2026-10-08): a seat for every open position.

The operator: a new bottom band at the level of the cockpit strip, that can
be enlarged or shrunk, with the mission, the activity and the deployment of
every seat per portfolio, every metric, the allocation, the voices and the
comments, commands to talk to Sauron about the data, and the underlying and
correlated instruments. This module builds what /api/horde/ answers
(dashboard/views_horde.py); templates/_partials/the_horde.html is the shell
and static/js/sv-horde.js paints it.

What a seat is: one open position of the viewer, the set /positions/ shows
(dashboard/views.py _render_positions over portfolio.services.
unified_open_positions): the viewer's AssetBotTrade rows OPEN or
CLOSE_PENDING, and the open portfolio.Position rows of their own
`<username>_main` book. Closes Sauron gave up on (ERROR with no closed_at)
are a band of their own, never seats; broker positions no row claims are a
display band; the shared Main book is a footnote.

The truth contract, in four lines:
  * a real row is valued by bot_program.venue_mark.resolve, through the
    positions page's own row (dashboard.views._live_row), so the Horde and
    /positions/ print the same digits;
  * unmeasured is None here and an em dash on the page, never 0;
  * worlds (real, demo, paper, no venue) and currencies are never summed;
  * the seat slot for the coming trader agents is None today and the
    group slot for their class leaders is None today: the seams are
    _orc_slots and _captain_slots below. No sentence here says one of them
    did anything; the holder line says who really holds the seat.

The reads (rule 5): Block A, every board and tab compute, a constant number
of queries whatever the seat count (dashboard.horde.board, pinned by
tests/test_the_horde.py; hand-kept forex rows add their quote currencies'
USD rates, one read per currency and never per row, and the broker band
reads the seats closed since its snapshot only when a broker row is left
unmatched); Block B, the book limits, pools and broker view,
cached 20 s on the book fingerprint; Block C, one seat's detail, on demand
only. Nothing here calls build_summary, preview_close, close_advice,
compute_correlation, correlation_state or is_component_enabled.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone as dt_tz

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.context_processors import PANEL_TTL_SECONDS
from core.templatetags.sauron_tags import _WORLD_TITLES

logger = logging.getLogger(__name__)

V = 1
DASH = "—"
#: The open band's clock: the strip's own (templates/_partials/
#: live_region.html TICK_MS / UP_EVERY).
TICK_S = 20
UP_EVERY = 3
#: Block B and the tab answer are kept this long: the cockpit's own TTL.
KEPT_S = PANEL_TTL_SECONDS
SEAT_STATUSES = ("OPEN", "CLOSE_PENDING")
SWITCH_KEYS = ("platform_master", "pipeline_asset_bots", "aragorn",
               "agent_position_review")
FACTS_MAX = 900
PEERS_MAX = 12                      # dashboard/views_desk.py HEAT_MAX
NEAR_STOP_R = 0.25
TIME_STOP_SOON_S = 2 * 3600
THESIS_FRESH_H = 24
TIMELINE_MAX = 50
REASONING_MAX = 600
REASONING_KEPT = 6000
QUOTE_MAX_AGE_S = 900               # bot_program/venue_mark.py MAX_AGE_S

WORLD_ORDER = ("live", "demo", "paper", "")
TONE_ORDER = ("alarm", "order", "watch", "unheld", "calm")
TONE_WORDS = {"alarm": "ALARM", "order": "ORDER", "watch": "WATCH",
              "unheld": "UNHELD", "calm": "CALM"}

# ── the words (every server sentence lives here) ─────────────────────────

NO_VENUE = "NO VENUE"
NO_VENUE_TITLE = ("Recorded by hand or imported: this row does not say "
                  "whether it is real or simulated money. The book limits "
                  "treat rows like it as real money.")
#: The world pill's hover, the money_world tag's own words
#: (core/templatetags/sauron_tags.py), and the NO VENUE chip's.
WORLD_TITLES = {**_WORLD_TITLES, "": NO_VENUE_TITLE}
SIDE_WORDS = {"BUY": "LONG", "SELL": "SHORT"}

MISSION_SIGNAL = "Your ticket · signal #{id}"
MISSION_PAGE = "Your ticket · from its instrument page"
MISSION_WORKING = "Working order at the broker · since {at}"
MISSION_LEGACY = "Recorded by hand · no keeper"
NOT_FILLED = "no P&L: not filled"
MARK_WAIT = "waiting for the venue's price"

# The holder (who holds the seat today), first match wins.
H_NOTHING_SHORT = "Nothing holds it"
H_LEGACY = ("Nothing on the platform manages, trails or closes this "
            "position: it is a row of your hand-kept book.")
H_TICK_OFF = ("Nothing is ticking: the 5-minute tick is switched off. Only "
              "what rests at the broker acts on it.")
H_BOT_OFF = ("Its bot is off ({record}): it is not ticked. Only what rests "
             "at the broker acts on it.")
H_ENGINE_SHORT = "Engine only · care off"
H_ENGINE = ("The care is switched off. The engine still checks the stop, the "
            "target and the time stop on every tick.")
H_LOCKS_SHORT = "Care · profit locks"
H_LOCKS = ("Held by the care: profit locks only (break-even, trail, weekend "
           "and event locks). Your ticket is never cut by a rule.")
H_BRAKED_SHORT = "Care · braked bot"
H_BRAKED = ("Held by the care; its bot is braked ({record}): exits run, "
            "entries do not.")
H_FULL_SHORT = "Care · full"
H_FULL = ("Held by the care: locks, posture floors, weekend and event cuts, "
          "the no-progress close and the structure stop.")
S_PROTECTED = ("The broker holds these levels, so they work even when Sauron "
               "is offline.")
#: A protected row whose stop the broker does not hold (eToro rewrote it
#: to "none" at the fill and nothing has moved it since: bot_program/
#: venue_exit.py venue_levels): what rests there is said, never more.
S_PROTECTED_TARGET_ONLY = "The broker holds the target only; no stop rests there."
S_PROTECTED_NOTHING = "The broker holds neither a stop nor a target for it."
S_PROTECTED_UNREAD = ("The broker holds its levels, but the stop it holds could "
                      "not be read.")
S_ENGINE_HELD = ("Sauron closes it as long as Sauron itself is running; the "
                 "broker does not hold these levels.")
#: Nothing ticks the row (the tick or its bot is off, holder() rows 2-3):
#: the runner skips it (bot_program/asset_engine/runner.py
#: run_asset_bot_tick), so no sentence may say Sauron closes it.
S_NOTHING_REAL = ("Nothing on the platform closes it, and the broker holds no "
                  "levels for it.")
S_PAPER = "A paper row: only the platform's simulator acts on it."
S_PAPER_NOTHING = ("A paper row: nothing on the platform acts on it while it "
                   "is not ticked.")
#: The holder, as the Ask facts say it.
HOLDER_FACTS = {"nothing": "held by nothing on the platform",
                "engine": "held by the engine alone (the care is off)",
                "care_locks": "held by the care: profit locks only",
                "care_braked": "held by the care, its bot braked",
                "care": "held by the care"}

# The light's reasons, in the table's order (the `why` list keeps it).
L_CLOSE_PENDING = ("Closing: the broker refused the close, so it is still "
                   "open there; Sauron retries it.")
L_CLOSE_IN_DOUBT = "A close is in doubt: the broker's answer was lost."
L_VANISHED = "The protective orders vanished at the broker."
L_LEGS = "The broker has not confirmed the stop and target orders."
L_STOP_UNREAD = "The stop the broker holds could not be read."
L_INERT = "Stop moves keep failing at the broker: {reason}."
L_THROUGH = "The price is through the stop ({stop})."
L_NO_STOP_REAL = "No stop on a {world} position: the whole notional is at risk."
L_NO_STOP_VENUE = "No stop rests at eToro."
L_THESIS = "The thesis check reads {verdict}."
L_REVIEWER = "The position reviewer advises {verdict}."
L_UNHELD_REAL = ("Nothing manages this {world} position and no stop rests at "
                 "the broker.")
L_WORKING = ("A working order at the broker, not a position yet: it has no "
             "P&L.")
L_STALE = "Priced at the venue's last rate, {age} old."
L_STALE_NOAGE = "Priced at the venue's last rate."
L_WAITING = "No price: waiting for the venue."
L_NEAR = "Within {r}R of the stop."
L_EVENT = "A high-impact print is near: {title} at {at} UTC."
L_NO_CARE = "The care has no record of this row yet."
L_REFUSED = "eToro refused the care's stop: {refusal}."
L_TIME_STOP = "Time stop in {left}."
L_NO_STAMP = "No USD conversion stamp: its money is left out of the totals."
L_NO_STOP = "No stop."
L_TICK = "Its bot last ticked {age} ago."
L_CALM = "Held; nothing flagged."
INERT_WORDS = {
    "broker_protected": "the stop rests at the broker, which no client can "
                        "modify yet",
    "legs_unmovable": "every recorded leg handle was refused",
}

# The head.
SIDE_LABELS = {"live": "REAL ACCOUNT", "paper": "PAPER BOOK"}
RISK_TEXT = "{risk} of {limit} at the stops of {rows} positions"
RISK_UNSTOPPED = " ({n} without a stop, counted at their whole notional)"
RISK_PAST = ("PAST THE CEILING: no entry opens until a position closes or "
             "trails its stop.")
DEMO_NOTE = "Demo rows are counted here, as the entry gate counts them."
GATE_EXTRA = ("The gate counts {k} more row(s): open rows of the shared Main "
              "book, which are not seats here.")
DAILY_OPEN = "OPEN · {realized} realized in 24 h, floor {floor} ({pct}%)"
DAILY_ELITE = ("ELITE ONLY · past the {pct}% stop: bots may open elite "
               "entries at half size, {used} of {max} used in 24 h; absolute "
               "stop {hard}%")
DAILY_SHUT = ("SHUT · past the absolute stop ({hard}%): no bot opens "
              "anything")
ALLOC_UNKNOWN = "Book size unknown: allocation cannot be measured."
ALLOC_OVER = "over the book by {x}%"
ALLOC_UNMEASURED = "{n} seats not measured"
ALLOC_UNMEASURED_ONE = "1 seat not measured"
FAILED_OPEN = ("THE BOOK LIMITS COULD NOT BE READ: entries are not gated by "
               "them right now. ({reason})")
HEAD_UNREADABLE = "The book limits could not be read. The seats below are live."
POOLS_LINE = "{world} {used} of {pool} used · {free} free"
POOLS_TITLE = ("Pools are what the bots may draw on; they are not the book. "
               "Per class: {classes}")
SWITCH_TICK_OFF = ("The 5-minute tick is off: the platform enforces no stop "
                   "or target.")
SWITCH_CARE_OFF = "The care is switched off: no soft stops, trails or locks run."
SWITCH_REVIEW_OFF = "The position reviewer is switched off."

# The bands.
STRAGGLER_WORDS = ("Sauron stopped trying to close this position after the "
                   "broker refused several times. It may still be open at "
                   "the broker: check it there.")
#: A broker row no open seat matched, one seat per row by (symbol, side).
#: It says what was measured and when, never where the position came from:
#: the snapshot is up to a sync old and a seat may have closed since.
UNSEATED_WORDS = "Not matched to an open seat as of this read ({age} ago)."
UNSEATED_WORDS_NOAGE = "Not matched to an open seat as of this read."
#: A row whose instrument the broker's client could not name ("ETORO:<id>",
#: bot_program/engine/etoro_client.py _symbol_for): it cannot be matched
#: by name, so it may well be one of the seats.
UNSEATED_UNNAMED = ("{broker} could not name this instrument; it may be one of "
                    "your seats.")
SHARE_LINE = "This class: {x} of the {y} at the stops on the {side}."
EMPTY_NO_SEATS = ("No seats. Every open position takes a seat here; you hold "
                  "none right now.")
EMPTY_NO_BOOK = ("You have no bots and no positions yet. The Horde fills as "
                 "soon as a position opens.")

# The reserved sentences: the only strings that name the coming trader
# agents or their class leaders. Nothing else in this file may.
NO_ORC = "No Orc"
NO_ORC_SEATED = "No Orc seated."
NOT_DECIDED = "Nothing on this seat was decided by an Orc."
ORC_ARRIVES = ("When the Orcs arrive, this seat's Orc writes its thesis, plan "
               "and notes here.")
TODAY = "Today: {holder}"
NO_CAPTAIN = "No Captain seated yet."
CAPTAINS_NOT_BUILT = ("Captains are not built yet. Today this class answers "
                      "to the book limits: open risk at the stops, theme "
                      "legs and the correlation taper.")
NO_THESIS_YET = "No thesis is written for this seat yet."
RESERVED_ORC_SENTENCES = frozenset({
    NO_ORC, NO_ORC_SEATED, NOT_DECIDED, ORC_ARRIVES, NO_CAPTAIN,
    CAPTAINS_NOT_BUILT, NO_THESIS_YET})

# The dossier.
WHO_YOU = "Opened by you (TAKE TRADE)"
WHO_BOT = "Opened by the bot {name} #{id}"
NO_SIGNAL = "No signal is recorded on this position."
DEBATE_NONE = {
    "manual": "No debate: hand trades are never debated.",
    "paper": "No debate: paper entries are never debated.",
    "demo": "No debate: demo entries are never debated.",
    "": "No debate on record for this entry.",
}
REVIEW_QUIET = ("Nothing flagged in the last 24 hours. The reviewer writes "
                "only when something triggers; this is not a clean bill.")
REVIEW_OFF = "The position reviewer is switched off."
THESIS_APPLIED = "Applied by the care: tighten only, for 24 hours."
THESIS_ADVICE = "Advice only on your own ticket: the care does not apply it."
THESIS_LEGACY = "Not run on rows of your hand-kept book."
THESIS_NONE = "Not checked yet."
CARE_NONE = "No care record: the care has not ticked this row."
NOTES_NONE = "No notes are stored on positions yet."
TIMELINE_NOTE = ("The care records its closes, scale-outs and broker mirrors; "
                 "its soft-stop changes show as the current state only.")
TIMELINE_EMPTY = "No moves recorded yet."
TIMELINE_LEGACY = "Rows of your hand-kept book keep no history on the platform."
CORR_NOTE = ("Measured on the platform's 4h bars; a bar can come from "
             "different sources, so read it as a guide.")
CORR_EMPTY = "No peer could be measured for this instrument."
CORR_UNMEASURED = "not enough shared 4h bars"
STAND_IN = ("The platform's quote for this symbol is {quote} ({kind}), not "
            "the instrument held.")
STAND_IN_KIND = {"future": "a futures contract", "cash index": "a cash index"}
PHONE_LINES = (
    ("/positions", "Every open position, with the stop eToro holds."),
    ("/why {symbol}", "Why there is or is not a trade on {symbol}."),
    ("/q {question}", "Ask Sauron from your phone (30 a day)."),
)
PHONE_STOP = ("/stop {id}", "Brakes the bot {name} #{id}: no new entries. It "
                            "never closes this position.")
#: A seat that is still a working order: the Eye's /stop withdraws the
#: braked config's working entries (bot_program/telegram_eye.py
#: apply_brake, withdraw=True), so the sentence says so.
PHONE_STOP_WORKING = ("Brakes the bot {name} #{id}: no new entries, and its "
                      "working orders are withdrawn, this one included.")
#: The stop a protected real row can actually be stopped at is the one the
#: venue holds (venue_exit.venue_levels; notifications._open_levels says
#: it the same way). The risk figure stays the gate's (at the stop sent,
#: the 15% ceiling's own number) and these say what rests at the venue.
VENUE_NO_STOP = "{venue} holds no stop: the whole notional is at risk."
VENUE_WIDER = "{venue} holds a wider stop: {x} at it."
VENUE_TIGHTER = "{venue} holds a tighter stop: {x} at it."
VENUE_PAST_ENTRY = "{venue} holds the stop past the entry: no loss at it."
VENUE_OTHER = "{venue} holds another stop ({stop})."
RISK_GATE_SUB = "The book limits count {x} at the stop sent."
STOP_FILL_REPLACED = "{venue}'s stop at the fill (since replaced)"


# ── the seams the trader agents will fill ────────────────────────────────

def _orc_slots(trade_ids) -> dict:
    """{seat key: slot} for the seats a trader agent sits in. Empty today:
    none is built. The agents' own PR replaces this with their notes read
    (one bulk read over trade_ids), keyed bot:<id>."""
    return {}


def _captain_slots(user, classes) -> dict:
    """{asset class: slot} for the class leaders. Empty today."""
    return {}


# ── small formatting helpers ─────────────────────────────────────────────

def _f(value):
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _money(value, signed=False):
    v = _f(value)
    if v is None:
        return None
    return ("{:+,.2f}" if signed else "{:,.2f}").format(v)


def _pct(value, places=1):
    v = _f(value)
    if v is None:
        return None
    return "{:.{p}f}%".format(v, p=places)


def _g(value):
    v = _f(value)
    return DASH if v is None else "{:g}".format(v)


def _tone(value):
    v = _f(value)
    if v is None or v == 0:
        return ""
    return "up" if v > 0 else "down"


def _price(value, cls="", symbol=""):
    from core.price_format import format_price
    return format_price(value, cls, symbol)


def _iso(moment):
    if moment is None:
        return None
    if isinstance(moment, str):
        parsed = parse_datetime(moment)
        if parsed is None:
            return None
        moment = parsed
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, dt_tz.utc)
    return moment.astimezone(dt_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(value):
    """A datetime from a datetime or an ISO string, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if not timezone.is_naive(value) else timezone.make_aware(value, dt_tz.utc)
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    return parsed if not timezone.is_naive(parsed) else timezone.make_aware(parsed, dt_tz.utc)


def _hhmm(value):
    at = _when(value)
    return at.astimezone(dt_tz.utc).strftime("%H:%M") if at else ""


def _age_words(seconds):
    from bot_program.venue_mark import age_words
    return age_words(seconds)


def _digest(text):
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()[:16]


def _side_word(side):
    return SIDE_WORDS.get(str(side or "").upper(), DASH)


def _side_key(side):
    """"BUY", "SELL" or "" from either spelling of a side."""
    s = str(side or "").upper()
    return "BUY" if s in ("BUY", "LONG") else "SELL" if s in ("SELL", "SHORT") else ""


def _a_stop(value):
    """A stop level, or None: 0 (and anything under it) is eToro's own
    spelling of "no stop", never a level 100% away and never a 1R."""
    v = _f(value)
    return v if (v is not None and v > 0) else None


def _venue_word(meta):
    """The carrier's name as a sentence starts with it ("eToro"), or "The
    broker" when the row never named one."""
    from .position_summary import BROKER_NAMES
    carrier = str((meta or {}).get("broker") or "").strip().lower()
    return BROKER_NAMES.get(carrier) or "The broker"


def _class_label(key):
    from core.constants import AssetClass
    words = dict(AssetClass.CHOICES)
    word = words.get(key)
    return (word or key or "other").upper()


# ── the reads ────────────────────────────────────────────────────────────

def _fingerprint(user, pf):
    """(stamp, configs n, trades n): the cockpit's own book fingerprint
    (core.context_processors._book_fingerprint), with the positions
    aggregate skipped when the viewer has no book row yet. It moves on every
    open, close and bot heartbeat; marks are the 20 s TTL's job."""
    from django.db.models import Count, Max

    from bot_program.models import AssetBotConfig, AssetBotTrade
    trades = AssetBotTrade.objects.filter(config__user=user).aggregate(
        n=Count("id"), opened=Max("opened_at"), closed=Max("closed_at"))
    positions = ({"n": 0} if pf is None else pf.positions.aggregate(
        n=Count("id"), opened=Max("opened_at"), closed=Max("closed_at")))
    configs = AssetBotConfig.objects.filter(user=user).aggregate(
        n=Count("id"), on=Count("id", filter=Q(enabled=True)),
        touched=Max("updated_at"))
    stamp = "|".join(str(block[k]) for block in (trades, positions, configs)
                     for k in sorted(block))
    return stamp, int(configs["n"] or 0), int(trades["n"] or 0)


def _own_book(user):
    """The viewer's own legacy book row, READ ONLY: never created here (the
    cockpit's context processor creates it on every render)."""
    from portfolio.models import Portfolio
    return Portfolio.objects.filter(name=f"{user.username}_main").first()


def _switches():
    """{key: on?} for the four switches the holder and the head read, in one
    query. A missing row reads as off, as is_component_enabled answers it
    (core/platform_control.py)."""
    from core.platform_control import PlatformComponent
    found = dict(PlatformComponent.objects.filter(key__in=SWITCH_KEYS)
                 .values_list("key", "is_enabled"))
    return {k: bool(found.get(k, False)) for k in SWITCH_KEYS}


class _Book:
    """Block A, read once: the seats' raw rows, already marked."""
    __slots__ = ("pf", "fp", "n_configs", "n_trades", "trades", "ups",
                 "rows", "legacy", "stragglers", "reviews", "switches",
                 "now")


def _read_book(user, pf, fp, now):
    """The seats, read with a constant number of queries:
    open legacy rows (skipped without a book), every OPEN / CLOSE_PENDING /
    abandoned bot row with its config, the marks (Instrument and LiveQuote
    by symbol), the legacy re-price (only with legacy rows), the reviewer's
    latest verdicts (only with seats) and the switch batch."""
    from bot_program.manual_close import _initial_stop
    from bot_program.models import AssetBotTrade
    from portfolio.services import _normalize_trades

    from .views import _live_row, _pos_leverage, _trade_leverage
    from .views_command import _reprice_legacy

    book = _Book()
    book.pf = pf
    book.fp, book.n_configs, book.n_trades = fp
    book.now = now
    book.legacy = (list(pf.positions.filter(closed_at__isnull=True)
                        .select_related("instrument", "strategy"))
                   if pf is not None else [])
    every = list(AssetBotTrade.objects.filter(config__user=user).filter(
        Q(status__in=SEAT_STATUSES) | Q(status="ERROR", closed_at__isnull=True))
        .select_related("config").order_by("-opened_at"))
    book.trades = [t for t in every if t.status in SEAT_STATUSES]
    book.stragglers = [t for t in every if t.status == "ERROR"]
    book.ups = _normalize_trades(book.trades) if book.trades else []
    if book.legacy:
        _reprice_legacy(book.legacy)

    # An opening stop of 0 is eToro's "no stop": no R, no 1R, no rail.
    stops = {f"bot-{t.id}": _a_stop(_initial_stop(t)) for t in book.trades}
    levs = {f"bot-{t.id}": _trade_leverage(t) for t in book.trades}
    for p in book.legacy:
        cls = getattr(p.instrument, "asset_class", "") or ""
        levs[f"pos-{p.pk}"] = _pos_leverage(cls)
    book.rows = {}
    for up in book.ups:
        book.rows[f"bot:{up.trade_id}"] = _live_row(up, stops, levs)
    for p in book.legacy:
        book.rows[f"pf:{p.pk}"] = _live_row(p, stops, levs)

    keys = list(book.rows)
    book.reviews = {}
    if keys:
        # Never with an empty list: `if keys:` is false there and every
        # user's reviews come back (brain/position_review.py latest_verdicts).
        from brain import position_review
        book.reviews = position_review.latest_verdicts(keys=keys)
    book.switches = _switches()
    return book


def _head_key(user, fp):
    return f"sv:horde:head:{user.pk}:{_digest(fp)}"


def _head_raw(user, fp, now):
    """Block B: the gate's two sides, the elite allowance, the pools and the
    broker view, cached KEPT_S on the fingerprint. Raises what it raises:
    the caller says the limits could not be read and serves the seats."""
    key = _head_key(user, fp)
    hit = cache.get(key)
    if hit is not None:
        return hit
    from bot_program import capital_truth
    from portfolio import risk_gate
    from portfolio.services import capital_summary
    raw = {
        "live": risk_gate.preflight(user, venue="live"),
        "paper": risk_gate.preflight(user, venue="paper"),
        "elite_live": risk_gate.elite_entries_since(user, paper=False),
        "elite_paper": risk_gate.elite_entries_since(user, paper=True),
        "capital": capital_summary(user),
        "broker": capital_truth.broker_view(user),
        "at": _iso(now),
    }
    cache.set(key, raw, KEPT_S)
    # The dossier reads the book sizes off the last head, never recomputes it.
    cache.set(f"sv:horde:headlast:{user.pk}", raw, 10 * 60)
    return raw


# ── the holder and the light: pure ───────────────────────────────────────

def _venue_stop_state(trade):
    """What stop rests at the venue for a protected row: "held", "none"
    (venue_exit.venue_levels has no stop: eToro rewrote it to none at the
    fill and nothing moved it since) or "unread" (the venue's stop could
    not be read); and whether a target rests there. ("", False) for a row
    the venue does not protect."""
    meta = trade.metadata or {}
    if not meta.get("protected"):
        return "", False
    from bot_program.venue_exit import venue_levels
    vl = venue_levels(trade)
    if meta.get("venue_stop_unread"):
        return "unread", "target" in vl
    return ("held" if vl.get("stop") else "none"), "target" in vl


def _holder_facts(trade, world):
    """What holder() reads off one bot row and its config."""
    from bot_program.asset_engine import disarm
    from core.context_processors import _is_manual_config
    cfg = trade.config
    enabled = bool(getattr(cfg, "enabled", False))
    venue_stop, venue_target = _venue_stop_state(trade)
    return {
        "legacy": False,
        "config_enabled": enabled,
        "keeps_managing": disarm.keeps_managing(cfg),
        "record_short": "" if enabled else disarm.record_words(cfg, short=True),
        "manual_lane": _is_manual_config(cfg),
        "protected": bool((trade.metadata or {}).get("protected")),
        "venue_stop": venue_stop, "venue_target": venue_target,
        "world": world,
    }


def holder(facts, switches) -> dict:
    """Who holds the seat TODAY: {"by", "short", "words", "suffix"}. Pure;
    the first matching row wins (the build spec's §6.4 table). A switch
    missing from `switches` reads as off."""
    def on(key):
        return bool((switches or {}).get(key))

    record = facts.get("record_short") or ""
    if facts.get("legacy"):
        return {"by": "nothing", "short": H_NOTHING_SHORT, "words": H_LEGACY,
                "suffix": ""}
    if not (on("platform_master") and on("pipeline_asset_bots")):
        by, short, words = "nothing", H_NOTHING_SHORT, H_TICK_OFF
    elif not facts.get("config_enabled") and not facts.get("keeps_managing"):
        by, short, words = ("nothing", H_NOTHING_SHORT,
                            H_BOT_OFF.format(record=record or "off"))
    elif not on("aragorn"):
        by, short, words = "engine", H_ENGINE_SHORT, H_ENGINE
    elif facts.get("manual_lane"):
        by, short, words = "care_locks", H_LOCKS_SHORT, H_LOCKS
    elif not facts.get("config_enabled"):
        by, short, words = ("care_braked", H_BRAKED_SHORT,
                            H_BRAKED.format(record=record or "braked"))
    else:
        by, short, words = "care", H_FULL_SHORT, H_FULL
    world = facts.get("world") or ""
    if facts.get("protected"):
        # What the venue holds, as venue_levels reads it (a fact missing
        # here is the old contract: the levels rest there).
        held = facts.get("venue_stop") or "held"
        if held == "none":
            suffix = (S_PROTECTED_TARGET_ONLY if facts.get("venue_target")
                      else S_PROTECTED_NOTHING)
        elif held == "unread":
            suffix = S_PROTECTED_UNREAD
        else:
            suffix = S_PROTECTED
    elif world in ("live", "demo"):
        # Only something that ticks the row closes it: rows 2-3 tick
        # nothing (the runner skips the config), so no "Sauron closes it".
        suffix = S_NOTHING_REAL if by == "nothing" else S_ENGINE_HELD
    elif world == "paper":
        suffix = S_PAPER_NOTHING if by == "nothing" else S_PAPER
    else:
        suffix = ""
    return {"by": by, "short": short, "words": words, "suffix": suffix}


def _end(text):
    text = str(text or "").strip()
    return text[:-1] if text.endswith(".") else text


def light(facts) -> dict:
    """The seat's state light: {"tone", "word", "why"}. Pure. Every reason
    that fired is listed, in the table's order; the tone is the highest that
    fired (ALARM > ORDER > WATCH > UNHELD > CALM)."""
    world = facts.get("world") or ""
    real = world in ("live", "demo")
    real_word = "real-money" if world == "live" else "demo"
    why = []

    def add(code, tone, text):
        why.append({"code": code, "tone": tone, "t": text})

    # ALARM
    if facts.get("status") == "CLOSE_PENDING":
        add("close_pending", "alarm", L_CLOSE_PENDING)
    if facts.get("close_in_doubt"):
        add("close_in_doubt", "alarm", L_CLOSE_IN_DOUBT)
    if facts.get("protection_vanished"):
        add("protection_vanished", "alarm", L_VANISHED)
    if facts.get("legs_unconfirmed"):
        add("legs_unconfirmed", "alarm", L_LEGS)
    if facts.get("venue_stop_unread"):
        add("venue_stop_unread", "alarm", L_STOP_UNREAD)
    inert = facts.get("stop_rules_inert") or ""
    if inert:
        reason = INERT_WORDS.get(inert, str(inert).replace("_", " "))
        detail = _end(facts.get("stop_rules_inert_detail"))
        if detail:
            reason = f"{reason} ({detail})"
        add("stop_rules_inert", "alarm", L_INERT.format(reason=reason))
    if facts.get("through_stop"):
        add("through_stop", "alarm", L_THROUGH.format(stop=facts.get("stop_t") or DASH))
    if real and not facts.get("has_stop"):
        add("no_stop_real", "alarm", L_NO_STOP_REAL.format(world=real_word))
    if real and facts.get("held_stop") == 0.0:
        add("no_stop_at_venue", "alarm", L_NO_STOP_VENUE)
    thesis = facts.get("thesis_verdict") or ""
    if thesis == "exit" and facts.get("thesis_fresh"):
        add("thesis_exit", "alarm", L_THESIS.format(verdict="EXIT"))
    reviewer = facts.get("reviewer_verdict") or ""
    if reviewer == "exit":
        add("reviewer_exit", "alarm", L_REVIEWER.format(verdict="EXIT"))
    if real and facts.get("holder_by") == "nothing" and not facts.get("protected"):
        add("unheld_real", "alarm", L_UNHELD_REAL.format(world=real_word))
    # ORDER
    if facts.get("working"):
        add("working", "order", L_WORKING)
    # WATCH
    if real and facts.get("mark_source") == "venue_stale":
        age = facts.get("mark_age_t") or ""
        add("mark_stale", "watch", L_STALE.format(age=age) if age else L_STALE_NOAGE)
    if real and not facts.get("priced"):
        add("mark_waiting", "watch", L_WAITING)
    near = _f(facts.get("near_stop_r"))
    if near is not None and 0 <= near <= NEAR_STOP_R:
        add("near_stop", "watch", L_NEAR.format(r="{:.2f}".format(near)))
    if thesis in ("adjust", "watch") and facts.get("thesis_fresh"):
        add("thesis_" + thesis, "watch", L_THESIS.format(verdict=thesis.upper()))
    if reviewer in ("tighten", "take_part"):
        add("reviewer_" + reviewer, "watch",
            L_REVIEWER.format(verdict=reviewer.replace("_", " ").upper()))
    event = facts.get("event")
    if event:
        add("event_near", "watch", L_EVENT.format(
            title=_end(event.get("title") or "an event"),
            at=event.get("at_t") or DASH))
    if str(facts.get("holder_by") or "").startswith("care") \
            and not facts.get("care_present"):
        add("no_care_record", "watch", L_NO_CARE)
    if facts.get("refusal"):
        add("mirror_refused", "watch", L_REFUSED.format(refusal=_end(facts["refusal"])))
    left = _f(facts.get("time_stop_left_s"))
    if left is not None and left <= TIME_STOP_SOON_S:
        from .position_summary import duration_words
        add("time_stop_soon", "watch", L_TIME_STOP.format(left=duration_words(left)))
    if facts.get("asset_class") == "forex" and not facts.get("vpu_stamped") \
            and not facts.get("legacy"):
        add("no_usd_stamp", "watch", L_NO_STAMP)
    if world == "paper" and not facts.get("has_stop"):
        add("no_stop_paper", "watch", L_NO_STOP)
    if facts.get("tick_overdue"):
        add("tick_stale", "watch", L_TICK.format(age=facts.get("tick_age_t") or DASH))
    # UNHELD
    if facts.get("holder_by") == "nothing" and (world == "paper" or facts.get("legacy")):
        add("unheld", "unheld", facts.get("holder_words") or (H_NOTHING_SHORT + "."))
    if not why:
        add("calm", "calm", L_CALM)
    tone = min((w["tone"] for w in why), key=TONE_ORDER.index)
    return {"tone": tone, "word": TONE_WORDS[tone], "why": why}


# ── one seat ─────────────────────────────────────────────────────────────

def _thesis_of(meta, now):
    t = meta.get("thesis") if isinstance(meta.get("thesis"), dict) else None
    if not t:
        return None
    at = _when(t.get("at"))
    age = (now - at).total_seconds() if at else None
    return {"verdict": str(t.get("verdict") or ""),
            "word": str(t.get("verdict") or "").upper() or DASH,
            "age_t": _age_words(age) if age is not None else "",
            "fresh": age is not None and age <= THESIS_FRESH_H * 3600,
            "words": str(t.get("words") or ""), "stop": t.get("stop"),
            "at": t.get("at")}


#: The reviewer's four verdicts (brain/position_review_models.py). Its two
#: other words, "none" (no model pass was made) and "no_quote" (no usable
#: mark), are deliberately not verdicts: they never colour a seat.
REVIEW_VERDICTS = ("hold", "tighten", "take_part", "exit")
REVIEW_NO_VERDICT = "NO VERDICT"


def _review_word(verdict):
    verdict = str(verdict or "")
    if verdict not in REVIEW_VERDICTS:
        return REVIEW_NO_VERDICT
    return verdict.replace("_", " ").upper()


def _reviewer_of(card, now):
    """The card's reviewer voice from latest_verdicts' payload, or None
    when there is none within 24 h or the latest one is not a verdict."""
    if not card:
        return None
    verdict = str(card.get("verdict") or "")
    if verdict not in REVIEW_VERDICTS:
        return None
    at = _when(card.get("as_of_iso"))
    age = (now - at).total_seconds() if at else None
    return {"verdict": verdict, "word": _review_word(verdict),
            "age_t": _age_words(age) if age is not None else "",
            "id": card.get("review_id")}


def _rev(status, stop, target, qty, meta, review_id):
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    thesis = meta.get("thesis") if isinstance(meta.get("thesis"), dict) else {}
    parts = [status, str(stop), str(target), str(qty),
             len(meta.get("stop_moves") or []), len(meta.get("level_edits") or []),
             care.get("soft_stop"), care.get("venue_stop"), thesis.get("at"),
             review_id, bool(meta.get("scale_out"))]
    return hashlib.sha1(json.dumps(parts, default=str).encode("utf-8")).hexdigest()[:8]


def _venue_held_stop(trade):
    """The stop eToro holds NOW when it rewrote the one sent at the fill:
    notifications._held_stop (0.0 for its "no stop", None when it kept the
    stop sent) — but only while nothing has moved the levels since. A
    later broker move, a level edit or the post-fill re-anchor replaces
    the level the fill left there, exactly as the platform's own reader
    of venue levels says (bot_program/venue_exit.py venue_levels), and a
    care mirror copies a stop onto the venue. None then: the fill's word
    is history, not the level resting at the broker."""
    from bot_program.notifications import _held_stop
    meta = trade.metadata or {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    if (meta.get("stop_moves") or meta.get("level_edits")
            or meta.get("stop_reanchored_to_fill")
            or care.get("venue_stop") is not None):
        return None
    return _held_stop(trade)


def _is_hand(trade):
    from core.context_processors import _is_manual_config
    meta = trade.metadata or {}
    return (bool(meta.get("manual"))
            or (trade.rule_name or "").lower() in ("manual_take", "manual")
            or _is_manual_config(trade.config))


def _facts_line(seat, extra):
    """The facts the Ask panel sends beside a seat question: the numbers the
    seat shows, "unknown" for every one it cannot show, at most FACTS_MAX
    characters (the research agent sees no positions of its own)."""
    def k(v):
        return v if v not in (None, "", DASH) else "unknown"
    lv = seat["levels"]
    mark = seat["mark"]
    parts = [seat["commands"]["ask"]["subject"], seat["world_word"],
             "entry " + k(lv.get("entry_t")),
             "opening stop " + (k(lv.get("istop_t")) if lv.get("istop_t") is not None
                                else "none"),
             "stop " + (lv.get("stop_t") or "none")]
    if lv.get("sent_stop_t"):
        parts.append("stop sent " + lv["sent_stop_t"])
    if extra.get("held_t") is not None:
        parts.append("held at eToro " + k(extra["held_t"]))
    parts.append("target " + (lv.get("target_t") if lv.get("target_t") not in (None, DASH)
                              else "none"))
    if mark.get("v") is None:
        parts.append("mark unknown")
    else:
        parts.append(f"mark {mark['t']}" + (f" ({mark['word']})" if mark.get("word") else ""))
    r = seat["money"].get("r_v")
    parts.append("R now " + ("{:+.2f}".format(r) if r is not None else "unknown"))
    care = seat.get("care") or {}
    parts.append("best " + k(care.get("mfe_t")))
    parts.append("worst " + k(care.get("mae_t")))
    parts.append("held " + k(seat["held"]["t"]))
    parts.append(HOLDER_FACTS.get(seat["holder"]["by"], "held by nothing"))
    rv = seat["voice"].get("reviewer")
    parts.append("reviewer: " + (f"{rv['word']} ({rv['age_t']} ago)" if rv
                                 else "nothing flagged in 24 h"))
    th = seat["voice"].get("thesis")
    parts.append("thesis check: " + (f"{th['word']} ({th['age_t']} ago)" if th
                                     else "not checked"))
    text = " · ".join(parts)
    return text if len(text) <= FACTS_MAX else text[:FACTS_MAX - 1] + "…"


def _bot_seat(book, trade, up, row, sides_book, now):
    """One bot row as a seat (the SEAT shape of the build spec §10.2)."""
    from bot_program.asset_engine.base import is_entry_working, time_stop_status
    from bot_program.asset_engine.safety import heartbeat_age_seconds
    from core.context_processors import (BOT_TICK_OVERDUE_FACTOR,
                                         _bot_tick_cadence_seconds)
    from portfolio.risk_gate import _row_risk
    from portfolio.services import instrument_has_page, value_per_unit

    from .position_summary import (WORLD_WORDS, duration_words, rule_words,
                                   venue_of, world_of)
    from .views import _pos_committed, _pos_distance

    meta = trade.metadata or {}
    cfg = trade.config
    key = f"bot:{trade.id}"
    world = world_of(trade)
    sym = trade.symbol
    inst = up.instrument
    inst_cls = getattr(inst, "asset_class", "") or ""
    cls = trade.asset_class or inst_cls or "other"
    pcls = inst_cls or cls
    side = str(trade.side or "").upper()
    is_long = side in ("BUY", "LONG")
    working = is_entry_working(trade)
    mark_v = _f(row["current_price"])
    entry = _f(trade.entry_price)
    sent = _f(trade.stop_loss)
    target = _f(trade.take_profit)
    # An opening stop of 0 is eToro's "no stop": no R, no rail, no 1R.
    istop = _a_stop(row.get("initial_stop"))
    qty = _f(trade.qty) or 0.0
    # THE STOP THAT CAN BE HIT. A real row the venue protects skips every
    # bot-side stop check (notifications._held_stop), so the stop resting
    # at the venue is the only one: venue_exit.venue_levels reads it (the
    # stop eToro rewrote at the fill until something moved it). The row's
    # stop_loss stays the stop SENT, which the gate's risk is measured at.
    # A venue stop that could not be read keeps the stop sent (the light
    # says it could not be read).
    stop = sent
    venue_state, _vt = ("", False)
    if world in ("live", "demo") and meta.get("protected"):
        venue_state, _vt = _venue_stop_state(trade)
        if venue_state in ("held", "none"):
            from bot_program.venue_exit import venue_levels
            stop = venue_levels(trade).get("stop")
    venue_moved = venue_state in ("held", "none") and not (
        (stop is None and not _a_stop(sent))
        or (stop is not None and sent is not None and abs(stop - sent) <= 1e-12))
    vpu = value_per_unit(trade)
    stamped = meta.get("value_per_unit") is not None
    hand = _is_hand(trade)
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}

    # the mission (no query: why_words is the dossier's)
    if working:
        mission = MISSION_WORKING.format(at=_hhmm(meta.get("entry_working_since")
                                                  or trade.opened_at) or DASH)
    elif hand:
        sid = meta.get("signal_id")
        mission = MISSION_SIGNAL.format(id=sid) if sid else MISSION_PAGE
    else:
        rule = rule_words(trade.rule_name)
        mission = f"{rule} · {cfg.name}" if rule else cfg.name

    # the money, the positions page's own digits
    pnl_v, r_v = _f(row["unrealized_pnl"]), _f(row["r_multiple"])
    money = {"pnl_t": row["pnl_text"], "pnl_v": pnl_v, "pnl_tone": row["pnl_tone"],
             "pct_t": row["pct_text"], "cap_pct_t": row["cap_pct_text"] or None,
             # No currency word on a forex row with no USD stamp: its money
             # is in the quote currency and is left out of every total.
             "ccy": "" if (cls == "forex" and not stamped) else (cfg.base_currency or "USD"),
             "r_t": row["r_text"], "r_v": r_v,
             "r_tone": row["r_tone"], "r_title": row["r_title"], "note": ""}
    if working:
        money.update(pnl_t=DASH, pnl_v=None, pnl_tone="", pct_t=DASH,
                     cap_pct_t=None, r_t=DASH, r_v=None, r_tone="", note=NOT_FILLED)
    mark = {"t": row["last_text"], "v": mark_v, "word": row["mark_word"],
            "title": row["mark_title"], "wait": row["mark_wait"],
            "source": row["mark_source"] or ""}

    # the levels
    # A level of 0 is "none" (eToro's own spelling of no stop), never a
    # level 100% away.
    stop_pct, through = _pos_distance(mark_v, stop or None, is_long)
    target_pct, _t = _pos_distance(mark_v, target or None, not is_long)
    progress = None
    if None not in (mark_v, istop, target) and target != istop:
        progress = round((mark_v - istop) / (target - istop), 4)
    levels = {"entry_t": _price(entry, pcls, sym),
              "istop_t": _price(istop, pcls, sym) if istop is not None else None,
              "stop_t": _price(stop, pcls, sym) if stop else None,
              # The stop sent, beside the venue's when the venue holds
              # another (or none): the gate still measures the risk at it.
              "sent_stop_t": (_price(sent, pcls, sym) if (venue_moved and sent)
                              else None),
              "target_t": _price(target, pcls, sym) if target else None,
              "stop_pct_t": stop_pct or None, "stop_through": bool(through),
              "target_pct_t": target_pct or None, "progress_v": progress}

    # the risk at the stop and the capital at work: the GATE's figure, at
    # the stop sent (portfolio.risk_gate._row_risk, the 15% ceiling's own)
    risk, stopped = _row_risk(qty, entry or 0.0, sent, side, vpu)
    side_book = sides_book.get("paper" if world == "paper" else "live")
    locked = None
    if stopped and risk == 0 and sent and entry:
        locked = abs(qty) * abs(sent - entry) * vpu
    risk_d = {"t": _money(risk), "v": round(risk, 2), "stopped": bool(stopped),
              "locked": locked is not None and locked > 0,
              "locked_t": _money(locked) if locked else None,
              "pct_t": _pct(risk / side_book * 100) if side_book else None,
              "venue_note": None}
    if cls == "forex" and not stamped:
        # Its money is in the quote currency: left out of every total,
        # and a dash here rather than yen printed as dollars (§6.3).
        risk_d.update(t=None, v=None, locked=False, locked_t=None, pct_t=None)
    if venue_moved:
        venue = _venue_word(meta)
        if stop is None:
            risk_d["venue_note"] = VENUE_NO_STOP.format(venue=venue)
        elif entry:
            loss = (entry - stop) if is_long else (stop - entry)
            if loss <= 0:
                risk_d["venue_note"] = VENUE_PAST_ENTRY.format(venue=venue)
            elif cls == "forex" and not stamped:
                risk_d["venue_note"] = VENUE_OTHER.format(
                    venue=venue, stop=_price(stop, pcls, sym))
            else:
                at_venue = _money(abs(qty) * loss * vpu)
                wider = sent is None or loss > abs(entry - sent)
                risk_d["venue_note"] = (VENUE_WIDER if wider else VENUE_TIGHTER).format(
                    venue=venue, x=at_venue)
    notional = abs(qty) * (entry or 0.0) * vpu if entry else None
    at_work = {"t": None, "v": None, "kind": ""}
    if notional and not (cls == "forex" and not stamped):
        committed, levered = _pos_committed(trade.asset_class or "", notional, meta)
        if committed is not None:
            at_work = {"t": _money(committed), "v": round(float(committed), 2),
                       "kind": "margin" if levered else "cost"}

    hfacts = _holder_facts(trade, world)
    hold = holder(hfacts, book.switches)
    reviewer = _reviewer_of(book.reviews.get(key), now)
    thesis = _thesis_of(meta, now)

    # the light's facts
    near = None
    if not working and mark_v is not None and stop and entry and istop is not None \
            and abs(entry - istop) > 1e-12:
        near = (mark_v - stop) * (1 if is_long else -1) / abs(entry - istop)
    tleft = None
    ts = time_stop_status(trade, config=cfg, now=now)
    if ts.get("enabled") and ts.get("hours_left") is not None:
        tleft = float(ts["hours_left"]) * 3600
    tick_overdue, tick_age_t = False, ""
    if book.switches.get("platform_master") and book.switches.get("pipeline_asset_bots") \
            and (cfg.enabled or hfacts["keeps_managing"]):
        age = heartbeat_age_seconds(cfg)
        if age is not None and age > _bot_tick_cadence_seconds() * BOT_TICK_OVERDUE_FACTOR:
            tick_overdue, tick_age_t = True, _age_words(age)
    event = care.get("event") if isinstance(care.get("event"), dict) else None
    lf = {
        "status": trade.status, "close_in_doubt": bool(meta.get("close_in_doubt")),
        "protection_vanished": bool(meta.get("protection_vanished_at")),
        "legs_unconfirmed": bool(meta.get("protective_legs_unconfirmed")),
        "venue_stop_unread": bool(meta.get("venue_stop_unread")),
        "stop_rules_inert": meta.get("stop_rules_inert") or "",
        "stop_rules_inert_detail": meta.get("stop_rules_inert_detail") or "",
        "through_stop": bool(through) and not working,
        "stop_t": levels["stop_t"], "world": world,
        # The row's own stop (no stop at all is its own alarm); the
        # venue's "none" is the held_stop's alarm, said once.
        "has_stop": bool(sent and sent > 0), "held_stop": _venue_held_stop(trade),
        "thesis_verdict": thesis["verdict"] if thesis else "",
        "thesis_fresh": bool(thesis and thesis["fresh"]),
        "reviewer_verdict": reviewer["verdict"] if reviewer else "",
        "holder_by": hold["by"], "holder_words": hold["words"],
        "protected": bool(meta.get("protected")), "working": working,
        "mark_source": mark["source"], "mark_age_t": _age_words(up.mark_age_s),
        "priced": mark_v is not None or working, "near_stop_r": near,
        "event": ({"title": event.get("title"), "at_t": _hhmm(event.get("at"))}
                  if event else None),
        "care_present": bool(care), "refusal": care.get("venue_stop_refusal") or "",
        "time_stop_left_s": tleft, "asset_class": cls, "vpu_stamped": stamped,
        "tick_overdue": tick_overdue, "tick_age_t": tick_age_t, "legacy": False,
    }
    lt = light(lf)

    page = f"/instruments/{sym}/" if instrument_has_page(inst) else None
    levels_cmd = None
    if trade.status == "OPEN":
        from core.price_format import price_decimals
        # A stop of 0 is no stop: the editor opens empty, as /positions/
        # hands it (positions_list.html, stop_loss|default:''), and its
        # precision is the entry's rather than a zero's.
        levels_cmd = {"trade": str(trade.id), "symbol": sym,
                      "side": "LONG" if is_long else "SHORT",
                      "stop": str(trade.stop_loss) if _a_stop(sent) else "",
                      "target": "" if trade.take_profit is None else str(trade.take_profit),
                      "decimals": price_decimals(trade.stop_loss if _a_stop(sent)
                                                 else trade.entry_price, pcls, sym),
                      "live": "0" if trade.paper else "1",
                      "protected": "1" if meta.get("protected") else "0"}
    subject = f"{sym} {'long' if is_long else 'short'} #{trade.id}"
    held_at = trade.opened_at
    seat = {
        "key": key, "kind": "bot", "trade_id": trade.id, "position_id": None,
        "rev": _rev(trade.status, trade.stop_loss, trade.take_profit, trade.qty,
                    meta, reviewer["id"] if reviewer else None),
        "symbol": sym, "side": side, "side_word": _side_word(side),
        "status": trade.status, "working": working,
        "world": world, "world_word": WORLD_WORDS.get(world, NO_VENUE),
        "world_title": WORLD_TITLES.get(world, ""),
        "venue": venue_of(trade)[2], "class": cls, "class_label": _class_label(cls),
        "instrument_class": inst_cls or cls,
        "lane": "hand" if hand else "bot",
        "config": {"id": cfg.id, "label": f"{cfg.name} #{cfg.id}", "mode": cfg.mode,
                   "ccy": cfg.base_currency or "USD"},
        "mission": mission, "light": lt, "mark": mark, "money": money,
        "levels": levels, "risk": risk_d, "at_work": at_work,
        "care": {"present": bool(care),
                 "mfe_t": ("{:+.2f}R".format(_f(care["mfe_r"]))
                           if _f(care.get("mfe_r")) is not None else None),
                 "mae_t": ("{:+.2f}R".format(_f(care["mae_r"]))
                           if _f(care.get("mae_r")) is not None else None),
                 "soft_t": _price(care.get("soft_stop"), pcls, sym)
                 if care.get("soft_stop") is not None else None,
                 "soft_why": str(care.get("soft_why") or "")},
        "holder": hold,
        "voice": {"reviewer": ({k: reviewer[k] for k in ("verdict", "word", "age_t")}
                               if reviewer else None),
                  "thesis": ({k: thesis[k] for k in ("verdict", "word", "age_t")}
                             if thesis else None)},
        "held": {"t": duration_words((now - held_at).total_seconds()) if held_at else DASH,
                 "since": _iso(held_at)},
        "same_bet": [],
        "orc": None,
        "links": {"story": f"/forensics/{trade.id}/", "page": page,
                  "chart": (page + "#instrument-main-chart-container") if page else None},
        "commands": {"close": True,
                     "close_label": "Retry close…" if trade.status == "CLOSE_PENDING"
                     else "Close…",
                     "advice": True, "levels": levels_cmd,
                     "ask": {"subject": subject, "facts": ""}},
        "_sort": (TONE_ORDER.index(lt["tone"]), WORLD_ORDER.index(world),
                  -(risk_d["v"] or 0.0), trade.id),
        "_theme": (sym, side, cls),
        "_ccy": cfg.base_currency or "USD",
        "_unstamped": cls == "forex" and not stamped,
    }
    held = _venue_held_stop(trade)
    seat["commands"]["ask"]["facts"] = _facts_line(seat, {
        "held_t": None if held is None else ("none" if held == 0.0
                                             else _price(held, pcls, sym))})
    return seat


def _legacy_seat(book, p, row, sides_book, now):
    """One open row of the viewer's hand-kept book as a seat."""
    from portfolio.risk_gate import _row_risk
    from portfolio.services import instrument_has_page

    from .position_summary import duration_words
    from .views import _pos_committed, _pos_distance

    key = f"pf:{p.pk}"
    inst = p.instrument
    sym = getattr(inst, "symbol", "") or ""
    cls = getattr(inst, "asset_class", "") or "other"
    is_long = str(p.direction or "").lower() not in ("short", "sell")
    side = "BUY" if is_long else "SELL"
    mark_v = _f(row["current_price"])
    entry = _f(p.entry_price)
    # A level of 0 is "none" (eToro's own spelling of no stop), never a
    # level 100% away, an opening stop or a 1R.
    stop = _a_stop(p.stop_loss)
    target = _f(p.take_profit)
    qty = _f(p.quantity) or 0.0
    vpu = getattr(p, "value_per_unit", None) or (1.0 if cls != "forex" else None)
    stop_pct, through = _pos_distance(mark_v, stop or None, is_long)
    target_pct, _t = _pos_distance(mark_v, target or None, not is_long)
    progress = None
    if None not in (mark_v, stop, target) and target != stop:
        progress = round((mark_v - stop) / (target - stop), 4)
    risk, stopped = _row_risk(qty, entry or 0.0, stop, side, vpu or 1.0)
    if vpu is None:
        # A forex row of the hand-kept book whose quote currency has no
        # readable USD rate (views_command._reprice_legacy): unmeasured.
        risk = None
    side_book = sides_book.get("live")
    at_work = {"t": None, "v": None, "kind": ""}
    if entry and vpu:
        committed, levered = _pos_committed(cls, abs(qty) * entry * vpu, {})
        if committed is not None:
            at_work = {"t": _money(committed), "v": round(float(committed), 2),
                       "kind": "margin" if levered else "cost"}
    hold = holder({"legacy": True}, book.switches)
    reviewer = _reviewer_of(book.reviews.get(key), now)
    levels = {"entry_t": _price(entry, cls, sym),
              "istop_t": _price(stop, cls, sym) if stop else None,
              "stop_t": _price(stop, cls, sym) if stop else None,
              "sent_stop_t": None,
              "target_t": _price(target, cls, sym) if target else None,
              "stop_pct_t": stop_pct or None, "stop_through": bool(through),
              "target_pct_t": target_pct or None, "progress_v": progress}
    near = None
    lf = {"status": "OPEN", "through_stop": bool(through), "stop_t": levels["stop_t"],
          "world": "", "has_stop": bool(stop and stop > 0), "held_stop": None,
          "reviewer_verdict": reviewer["verdict"] if reviewer else "",
          "holder_by": hold["by"], "holder_words": hold["words"],
          "priced": mark_v is not None, "near_stop_r": near, "care_present": False,
          "asset_class": cls, "vpu_stamped": True, "legacy": True,
          "mark_source": row["mark_source"] or ""}
    lt = light(lf)
    page = f"/instruments/{sym}/" if instrument_has_page(inst) else None
    subject = f"{sym} {'long' if is_long else 'short'} pos #{p.pk}"
    seat = {
        "key": key, "kind": "pf", "trade_id": None, "position_id": p.pk,
        "rev": _rev("OPEN", p.stop_loss, p.take_profit, p.quantity, {},
                    reviewer["id"] if reviewer else None),
        "symbol": sym, "side": side, "side_word": _side_word(side),
        "status": "OPEN", "working": False,
        "world": "", "world_word": NO_VENUE, "world_title": NO_VENUE_TITLE,
        "venue": "", "class": cls, "class_label": _class_label(cls),
        "instrument_class": cls, "lane": "legacy", "config": None,
        "mission": MISSION_LEGACY, "light": lt,
        "mark": {"t": row["last_text"], "v": mark_v, "word": row["mark_word"],
                 "title": row["mark_title"], "wait": row["mark_wait"],
                 "source": row["mark_source"] or ""},
        "money": {"pnl_t": row["pnl_text"], "pnl_v": _f(row["unrealized_pnl"]),
                  "pnl_tone": row["pnl_tone"], "pct_t": row["pct_text"],
                  "cap_pct_t": row["cap_pct_text"] or None,
                  "ccy": getattr(inst, "currency", "") or "USD",
                  "r_t": row["r_text"], "r_v": _f(row["r_multiple"]),
                  "r_tone": row["r_tone"], "r_title": row["r_title"], "note": ""},
        "levels": levels,
        "risk": {"t": _money(risk), "v": round(risk, 2) if risk is not None else None,
                 "stopped": bool(stopped), "locked": False, "locked_t": None,
                 "pct_t": (_pct(risk / side_book * 100)
                           if (side_book and risk is not None) else None),
                 "venue_note": None},
        "at_work": at_work,
        "care": {"present": False, "mfe_t": None, "mae_t": None, "soft_t": None,
                 "soft_why": ""},
        "holder": hold,
        "voice": {"reviewer": ({k: reviewer[k] for k in ("verdict", "word", "age_t")}
                               if reviewer else None), "thesis": None},
        "held": {"t": duration_words((now - p.opened_at).total_seconds())
                 if p.opened_at else DASH, "since": _iso(p.opened_at)},
        "same_bet": [], "orc": None,
        "links": {"story": None, "page": page,
                  "chart": (page + "#instrument-main-chart-container") if page else None},
        "commands": {"close": False, "close_label": "", "advice": False,
                     "levels": None, "ask": {"subject": subject, "facts": ""}},
        "_sort": (TONE_ORDER.index(lt["tone"]), WORLD_ORDER.index(""),
                  -(risk or 0.0), p.pk),
        "_theme": (sym, side, cls),
        "_ccy": getattr(inst, "currency", "") or "USD",
        "_unstamped": False,
    }
    seat["commands"]["ask"]["facts"] = _facts_line(seat, {})
    return seat


def _book_sizes(raw):
    """{"live": value | None, "paper": value | None} from a head's gates."""
    out = {"live": None, "paper": None}
    for side in out:
        checks = ((raw or {}).get(side) or {}).get("checks") or {}
        for name in ("open_risk", "daily_loss", "exposure"):
            value = _f((checks.get(name) or {}).get("book_value"))
            if value:
                out[side] = value
                break
    return out


def _seats(book, raw):
    sizes = _book_sizes(raw)
    seats = []
    by_trade = {t.id: t for t in book.trades}
    for up in book.ups:
        trade = by_trade.get(up.trade_id)
        if trade is None:
            continue
        try:
            seats.append(_bot_seat(book, trade, up, book.rows[f"bot:{trade.id}"],
                                   sizes, book.now))
        except Exception:  # noqa: BLE001 — one bad row must not blank the band
            logger.warning("[horde] seat bot:%s not shaped", trade.id, exc_info=True)
    for p in book.legacy:
        try:
            seats.append(_legacy_seat(book, p, book.rows[f"pf:{p.pk}"], sizes,
                                      book.now))
        except Exception:  # noqa: BLE001
            logger.warning("[horde] seat pf:%s not shaped", p.pk, exc_info=True)
    slots = _orc_slots([s["trade_id"] for s in seats if s["trade_id"]])
    for s in seats:
        s["orc"] = slots.get(s["key"])
    return seats, sizes


# ── bands ────────────────────────────────────────────────────────────────

def _legs_of(symbol, side, cls):
    from portfolio.risk_gate import _theme_legs
    try:
        return _theme_legs(symbol, side, cls)
    except Exception:  # noqa: BLE001
        return {}


def _same_bets(seats):
    """[{"world", "t"}] for every theme two or more seats of one world express
    in the same direction (risk_gate._theme_legs; stocks have none)."""
    out = []
    by = {}
    for s in seats:
        sym, side, cls = s["_theme"]
        for theme, d in _legs_of(sym, side, cls).items():
            by.setdefault((s["world"], theme, d), []).append(s)
    for (world, theme, d), members in sorted(by.items(), key=lambda kv: (
            WORLD_ORDER.index(kv[0][0]), kv[0][1], -kv[0][2])):
        if len(members) < 2:
            continue
        word = theme.replace("_", " ")
        forex = all(m["class"] == "forex" for m in members)
        names = ", ".join(
            (f"{m['symbol']} {m['side_word'].lower()}" if forex else m["symbol"])
            for m in members)
        text = (f"{'Long' if d > 0 else 'Short'} {word} through {len(members)} "
                f"seats ({names})")
        out.append({"world": world, "t": text, "keys": [m["key"] for m in members]})
    return out


_WORLD_SUFFIX = {"live": "real", "demo": "demo", "paper": "paper", "": "no venue"}


def _line(world, members, sizes):
    from .position_summary import WORLD_WORDS
    longs = sum(1 for m in members if m["side"] == "BUY")
    shorts = sum(1 for m in members if m["side"] == "SELL")
    book = sizes.get("paper" if world == "paper" else "live")
    at_work = [m["at_work"]["v"] for m in members if m["at_work"]["v"] is not None]
    pnl, priced = {}, 0
    for m in members:
        v = m["money"]["pnl_v"]
        if v is None or m["_unstamped"]:
            continue
        priced += 1
        pnl[m["_ccy"]] = pnl.get(m["_ccy"], 0.0) + v
    rs = [m["money"]["r_v"] for m in members if m["money"]["r_v"] is not None]
    risks = [m["risk"]["v"] for m in members if m["risk"]["v"] is not None]
    risk = sum(risks)
    return {
        "world": world, "world_word": WORLD_WORDS.get(world, NO_VENUE),
        "seats": len(members), "long": longs, "short": shorts,
        "sides_known": longs + shorts == len(members),
        "at_work_t": _pct(sum(at_work) / book * 100) if (book and at_work) else None,
        "at_work_n": len(at_work),
        "pnl": [{"ccy": c, "t": _money(v, signed=True), "tone": _tone(v)}
                for c, v in sorted(pnl.items())],
        "priced": priced,
        "r_t": "{:+.2f}R".format(sum(rs)) if rs else None, "r_n": len(rs),
        "risk_t": _money(risk) if risks else None, "risk_n": len(risks),
        "risk_pct_t": _pct(risk / book * 100) if (book and risks) else None,
    }


def _groups(seats, sizes, gate_risk, user):
    classes = sorted({s["class"] for s in seats})
    captains = _captain_slots(user, classes)
    groups = []
    for cls in classes:
        members = sorted([s for s in seats if s["class"] == cls],
                         key=lambda s: s["_sort"])
        worlds = [w for w in WORLD_ORDER if any(m["world"] == w for m in members)]
        lines = [_line(w, [m for m in members if m["world"] == w], sizes)
                 for w in worlds]
        bets = _same_bets(members)
        for b in bets:
            for m in members:
                if m["key"] in b["keys"]:
                    m["same_bet"].append(b["t"])
        # The gate's own populations: the real account counts the live and
        # demo rows, the paper book the paper rows; a row of the hand-kept
        # book is not in either (the gate reads the shared Main book).
        real = [m for m in members if m["world"] in ("live", "demo")]
        paper = [m for m in members if m["world"] == "paper"]
        side = "live" if real else "paper" if paper else ""
        share = ""
        if side:
            mine = sum(m["risk"]["v"] or 0.0 for m in (real if real else paper))
            total = gate_risk.get(side)
            share = SHARE_LINE.format(
                x=_money(mine), y=_money(total) if total is not None else DASH,
                side="real account" if side == "live" else "paper book")
        groups.append({
            "key": cls, "label": _class_label(cls), "worlds": worlds,
            "lines": lines,
            "same_bet": [{"world": b["world"], "t": b["t"]} for b in bets],
            "today": {"share_t": share,
                      "legs_t": [f"{b['t']} · {_WORLD_SUFFIX.get(b['world'], '')}"
                                 for b in bets]},
            "captain": captains.get(cls),
            "seats": members,
            "_alarm": any(m["light"]["tone"] == "alarm" for m in members),
            "_real": any(m["world"] == "live" for m in members),
            "_live_risk": sum(m["risk"]["v"] or 0.0 for m in members
                              if m["world"] in ("live", "demo")),
        })
    groups.sort(key=lambda g: (not g["_alarm"], not g["_real"], -g["_live_risk"],
                               g["label"]))
    for g in groups:
        for k in ("_alarm", "_real", "_live_risk"):
            g.pop(k)
        for m in g["seats"]:
            for k in ("_sort", "_theme", "_ccy", "_unstamped"):
                m.pop(k, None)
    return groups


def _stragglers(book):
    from .position_summary import WORLD_WORDS, world_of
    out = []
    for t in book.stragglers:
        world = world_of(t)
        out.append({"key": f"bot:{t.id}", "id": t.id, "symbol": t.symbol,
                    "side_word": _side_word(t.side), "world": world,
                    "world_word": WORLD_WORDS.get(world, NO_VENUE),
                    "tone": "alarm", "word": TONE_WORDS["alarm"],
                    "t": STRAGGLER_WORDS, "story": f"/forensics/{t.id}/"})
    return out


def _claim(seats, sym, side):
    """Take one seat for a broker row keyed (symbol, side); a row that
    states no side takes a seat of either side. True when one was free."""
    for key in ([(sym, side)] if side else [(sym, "BUY"), (sym, "SELL")]) + [(sym, "")]:
        if seats.get(key, 0) > 0:
            seats[key] -= 1
            return True
    return False


def _unseated(raw, book, user=None):
    """The broker's own rows that no seat accounts for (a display band:
    the snapshot is the last sync's, up to its age old).

    One broker row per seat, by (symbol, side) and COUNT, never by symbol
    alone: a second XAUUSD the operator opened at the broker beside a
    seated one is exactly what this band is for. A seat claims a row when
    it is open or closing, or a close Sauron gave up on (it may still be
    open there), of the money world this account holds; a working order is
    not a position yet and claims nothing. Rows still unmatched are read
    against the seats that closed since the snapshot was taken (one read,
    only then): the snapshot cannot know about them yet."""
    from collections import Counter

    from bot_program.asset_engine.base import is_entry_working

    from .position_summary import WORLD_WORDS, world_of

    broker = (raw or {}).get("broker") or None
    if not broker:
        return None
    positions = broker.get("positions") or None
    if not positions or not positions.get("rows"):
        return None
    env = str(broker.get("env") or "").upper()
    world = "live" if env.startswith("LIVE") else "demo" if env.startswith("DEMO") else ""

    def held_here(paper, meta):
        if paper:
            return False
        w = world_of({"paper": paper, "metadata": meta})
        return w == world if world else w in ("live", "demo")

    seats = Counter()
    for t in list(book.trades) + list(book.stragglers):
        if held_here(t.paper, t.metadata) and not is_entry_working(t):
            seats[(str(t.symbol or "").upper(), _side_key(t.side))] += 1
    left = []
    for row in positions.get("rows") or []:
        sym = str(row.get("symbol", "") or "")
        if not sym:
            continue
        if not _claim(seats, sym.upper(), _side_key(row.get("side"))):
            left.append(row)
    at = _when(positions.get("at"))
    if left and user is not None and at is not None:
        from bot_program.models import AssetBotTrade
        closed = Counter()
        for sym, side, paper, meta in (AssetBotTrade.objects
                                       .filter(config__user=user, paper=False,
                                               closed_at__gte=at)
                                       .values_list("symbol", "side", "paper",
                                                    "metadata")):
            if held_here(paper, meta):
                closed[(str(sym or "").upper(), _side_key(side))] += 1
        left = [row for row in left
                if not _claim(closed, str(row.get("symbol")).upper(),
                              _side_key(row.get("side")))]
    age = _age_words(positions.get("age_seconds"))
    name = broker.get("name") or ""
    rows = []
    for row in left:
        sym = str(row.get("symbol", "") or "")
        units = _f(row.get("qty") if row.get("qty") is not None else row.get("units"))
        value = _f(row.get("market_value") if row.get("market_value") is not None
                   else row.get("value"))
        if not value:
            # eToro's /portfolio row carries no mark, so its adapter leaves
            # market_value at 0.0 rather than inventing one (bot_program/
            # engine/etoro_client.py broker_portfolio): unmeasured, a dash,
            # never a holding worth nothing.
            value = None
        if sym.upper().startswith("ETORO:"):
            words = UNSEATED_UNNAMED.format(broker=name or "The broker")
        else:
            words = UNSEATED_WORDS.format(age=age) if age else UNSEATED_WORDS_NOAGE
        side = _side_key(row.get("side"))
        rows.append({"symbol": sym, "side_word": SIDE_WORDS.get(side, ""),
                     "units_t": ("{:,.4f}".format(units).rstrip("0").rstrip(".")
                                 if units is not None else DASH),
                     "value_t": _money(value) or DASH,
                     "t": words})
    if not rows:
        return None
    return {"broker": name, "env": broker.get("env") or "",
            "world": world, "world_word": WORLD_WORDS.get(world, ""),
            "age_t": age, "rows": rows}


# ── the head ─────────────────────────────────────────────────────────────

def _open_risk(check, failed):
    reason = check.get("reason") or ""
    limit_money = _f(check.get("limit_money"))
    limit_pct = _f(check.get("limit_pct"))
    book = _f(check.get("book_value"))
    risk = _f(check.get("open_risk")) or 0.0
    out = {"pct_t": None, "pct_v": None,
           "limit_pct_t": f"{limit_pct:g}%" if limit_pct else None,
           "money_t": _money(risk) if limit_money is not None else None,
           "limit_money_t": _money(limit_money),
           "rows": int(check.get("rows") or 0),
           "unstopped": int(check.get("unstopped") or 0),
           "tone": "unmeasured", "t": reason, "past_t": "", "reason": reason}
    if failed or limit_money is None or not book:
        return out
    pct = risk / book * 100
    ratio = risk / limit_money if limit_money else 0.0
    tone = "ok" if ratio < 0.8 else "near" if ratio < 1.0 else "past"
    text = RISK_TEXT.format(risk=_money(risk), limit=_money(limit_money),
                            rows=out["rows"])
    if out["unstopped"]:
        text += RISK_UNSTOPPED.format(n=out["unstopped"])
    out.update(pct_t="{:.1f}%".format(pct), pct_v=round(pct, 2), tone=tone, t=text,
               past_t=RISK_PAST if tone == "past" else "")
    return out


def _daily(check, used):
    from portfolio.risk_gate import ELITE_MAX_PER_WINDOW
    reason = check.get("reason") or ""
    mode = check.get("mode") or "open"
    out = {"mode": mode, "t": reason, "reason": reason, "elite_used": int(used or 0),
           "measured": False}
    limit_money = _f(check.get("limit_money"))
    if limit_money is None or check.get("realized") is None:
        # No limit, no book to measure it against, or a day whose closes
        # carry no price (risk_gate.daily_loss_state): the gate cannot
        # apply the stop, so the band says so in the gate's own words.
        out["mode"] = "unmeasured"
        return out
    out["measured"] = True
    pct, hard = _g(check.get("limit_pct")), _g(check.get("hard_pct"))
    if mode == "shut":
        out["t"] = DAILY_SHUT.format(hard=hard)
    elif mode == "elite":
        out["t"] = DAILY_ELITE.format(pct=pct, used=int(used or 0),
                                      max=ELITE_MAX_PER_WINDOW, hard=hard)
    else:
        out["t"] = DAILY_OPEN.format(
            realized=_money(check.get("realized"), signed=True) or DASH,
            floor=_money(limit_money), pct=pct)
    return out


def _alloc(members, book):
    segs, total, unmeasured = {}, 0.0, 0
    for m in members:
        v = m["at_work"]["v"]
        if v is None:
            unmeasured += 1
            continue
        kind = "demo" if m["world"] == "demo" else "none" if m["world"] == "" else ""
        k = (m["class"], kind)
        segs[k] = segs.get(k, 0.0) + v
        total += v
    if not book:
        return [], None, unmeasured, "", ALLOC_UNKNOWN
    out = []
    for (cls, kind), v in sorted(segs.items(), key=lambda kv: -kv[1]):
        pct = v / book * 100
        out.append({"class": cls, "label": _class_label(cls), "pct_v": round(pct, 2),
                    "t": f"{_class_label(cls)} {pct:.1f}%", "demo": kind == "demo",
                    "legacy": kind == "none"})
    used = total / book * 100
    free = {"pct_v": round(max(0.0, 100 - used), 2),
            "t": "free {:.1f}%".format(max(0.0, 100 - used))}
    over = ALLOC_OVER.format(x="{:.1f}".format(used - 100)) if used > 100 else ""
    return out, free, unmeasured, over, ""


def _head(raw, seats, book):
    sides = {}
    gate_risk = {}
    elite = {"live": (raw or {}).get("elite_live"), "paper": (raw or {}).get("elite_paper")}
    for side in ("live", "paper"):
        pre = (raw or {}).get(side) or {}
        failed = bool(pre.get("failed_open"))
        checks = pre.get("checks") or {}
        orisk = checks.get("open_risk") or {}
        daily = checks.get("daily_loss") or {}
        expo = checks.get("exposure") or {}
        notl = checks.get("notional") or {}
        size = _f(orisk.get("book_value")) or _f(daily.get("book_value"))
        source = orisk.get("book_source") or daily.get("book_source") or ""
        mine = [s for s in seats if (s["world"] == "paper") == (side == "paper")]
        if side == "live":
            real_seats = [s for s in mine if s["world"] in ("live", "demo")]
        else:
            real_seats = mine
        orisk_out = _open_risk(orisk, failed)
        gate_risk[side] = (_f(orisk.get("open_risk"))
                           if orisk_out["tone"] != "unmeasured" else None)
        alloc, free, unmeasured, over, alloc_t = _alloc(mine, size)
        extra = 0
        if side == "live" and orisk_out["tone"] != "unmeasured":
            extra = max(0, orisk_out["rows"] - len(real_seats))
        from portfolio.risk_gate import _book_words
        sides[side] = {
            "present": bool(mine) or orisk_out["rows"] > 0,
            "label": SIDE_LABELS[side],
            "venue_class": "sv-venue--live" if side == "live" else "sv-venue--paper",
            # No book value, no words to say it in: a dash here, and the
            # allocation line says why (ALLOC_UNKNOWN), once.
            "book_t": _book_words(size, source) if size else DASH,
            "open_risk": orisk_out,
            "daily": _daily(daily, elite[side]),
            "alloc": alloc, "alloc_free": free, "alloc_unmeasured": unmeasured,
            "alloc_unmeasured_t": (ALLOC_UNMEASURED_ONE if unmeasured == 1
                                   else ALLOC_UNMEASURED.format(n=unmeasured)
                                   if unmeasured else ""),
            "alloc_over_t": over, "alloc_t": alloc_t,
            # None when the gate could not say (it failed open, or the check
            # is missing): a dash, never an OK the gate did not give.
            "exposure": {"ok": bool(expo["ok"]) if "ok" in expo else None,
                         "reason": expo.get("reason") or ""},
            "notional": {"ok": bool(notl["ok"]) if "ok" in notl else None,
                         "reason": notl.get("reason") or ""},
            "failed_open": failed,
            "failed_reason": pre.get("reason", "") if failed else "",
            "failed_t": FAILED_OPEN.format(reason=pre.get("reason", "")) if failed else "",
            "demo_note": side == "live" and any(s["world"] == "demo" for s in seats),
            "demo_note_t": DEMO_NOTE if (side == "live" and any(
                s["world"] == "demo" for s in seats)) else "",
            "gate_extra_rows": extra,
            "extra_t": GATE_EXTRA.format(k=extra) if extra else "",
        }
    cap = (raw or {}).get("capital") or {}

    def pool_line(world, w):
        used, pool, free = cap.get(f"used_{w}"), cap.get(f"pool_{w}"), cap.get(f"free_{w}")
        text = POOLS_LINE.format(world=world, used=_money(used) or DASH,
                                 pool=_money(pool) or DASH, free=_money(free) or DASH)
        neg = (_f(free) or 0.0) < 0
        return text + (" (oversubscribed)" if neg else ""), neg

    live_t, live_neg = pool_line("real", "live")
    paper_t, paper_neg = pool_line("paper", "paper")
    classes = "; ".join(
        f"{c.get('asset_class')} {c.get('mode')}: pool {_money(c.get('pool')) or DASH}, "
        f"used {_money(c.get('used')) or DASH}, free {_money(c.get('free')) or DASH}"
        for c in cap.get("classes") or []) or DASH
    real = [s for s in seats if s["world"] in ("live", "demo")]
    marks = {"venue": sum(1 for s in real if s["mark"]["source"] == "venue"),
             "venue_stale": sum(1 for s in real if s["mark"]["source"] == "venue_stale"),
             "quote": sum(1 for s in real if s["mark"]["source"] == "quote"),
             "waiting": sum(1 for s in real if s["mark"]["v"] is None)}
    sw = book.switches
    lines = []
    if not (sw.get("platform_master") and sw.get("pipeline_asset_bots")):
        lines.append(SWITCH_TICK_OFF)
    if not sw.get("aragorn"):
        lines.append(SWITCH_CARE_OFF)
    if not sw.get("agent_position_review"):
        lines.append(SWITCH_REVIEW_OFF)
    tones = {t: sum(1 for s in seats if s["light"]["tone"] == t) for t in TONE_ORDER}
    tones["alarm"] += len(book.stragglers)
    return {
        "as_of": (raw or {}).get("at"), "kept_s": KEPT_S, "readable": True, "t": "",
        "sides": sides,
        "pools": {"live_t": live_t, "live_neg": live_neg, "paper_t": paper_t,
                  "paper_neg": paper_neg, "classes_t": POOLS_TITLE.format(classes=classes)},
        "marks": marks, "switch_lines": lines, "tones": tones,
    }, gate_risk


def _unreadable_head(book, seats):
    tones = {t: sum(1 for s in seats if s["light"]["tone"] == t) for t in TONE_ORDER}
    tones["alarm"] += len(book.stragglers)
    return {"as_of": None, "kept_s": KEPT_S, "readable": False, "t": HEAD_UNREADABLE,
            "sides": {}, "pools": None, "marks": None, "switch_lines": [],
            "tones": tones}


# ── the answers ──────────────────────────────────────────────────────────

def _tab_of(book, seats, head, raw, now):
    by_world = {"live": 0, "demo": 0, "paper": 0, "none": 0}
    for s in seats:
        by_world[s["world"] or "none"] += 1
    alarms = sum(1 for s in seats if s["light"]["tone"] == "alarm") + len(book.stragglers)
    alarm_real = any(s["light"]["tone"] == "alarm" and s["world"] == "live" for s in seats)
    lead = ("live" if by_world["live"] else "demo" if by_world["demo"] else "paper")
    sides = {}
    for world in ("live", "demo", "paper"):
        rs = [s["money"]["r_v"] for s in seats if s["world"] == world
              and s["money"]["r_v"] is not None]
        n = by_world[world]
        gate = ((head.get("sides") or {}).get("paper" if world == "paper" else "live")
                or {}).get("open_risk") or {}
        sides[world] = {"n": n,
                        "r_t": "{:+.2f}R".format(sum(rs)) if rs else None,
                        "r_v": round(sum(rs), 2) if rs else None,
                        "r_n": len(rs), "r_of": n,
                        "risk_pct_t": gate.get("pct_t"),
                        "limit_pct_t": gate.get("limit_pct_t"),
                        "risk_tone": gate.get("tone") or "unmeasured",
                        "risk_why": gate.get("reason") or ""}
    flag = None
    lead_side = (head.get("sides") or {}).get("paper" if lead == "paper" else "live") or {}
    if not head.get("readable") or lead_side.get("failed_open"):
        flag = "unreadable"
    elif (lead_side.get("daily") or {}).get("mode") == "shut":
        flag = "shut"
    elif (lead_side.get("daily") or {}).get("mode") == "elite":
        flag = "elite"
    hhmmss = _when(now).astimezone(dt_tz.utc).strftime("%H:%M:%S")

    def side_words(world, label):
        s = sides[world]
        if not s["n"]:
            return ""
        risk = (f"open risk {s['risk_pct_t']} of {s['limit_pct_t']}"
                if s["risk_pct_t"] else "open risk —")
        return (f" {label}: {s['n']} seat{'s' if s['n'] != 1 else ''}, open R "
                f"{s['r_t'] or DASH}, {risk}.")
    title = ("The Horde: a seat for every open position."
             + side_words("live", "Real money") + side_words("demo", "Demo")
             + side_words("paper", "Paper")
             + (" Demo rows count on the real-money side, as the entry gate "
                "counts them." if by_world["demo"] else "")
             + (f" {alarms} seat{'s' if alarms != 1 else ''} need"
                f"{'' if alarms != 1 else 's'} attention." if alarms else "")
             + f" As of {hhmmss}. Click to open, or press h; drag the top edge "
               f"to resize.")
    lead_s = sides[lead]
    aria = (f"The Horde: {len(seats)} seat{'s' if len(seats) != 1 else ''}, "
            f"{alarms} alarm{'s' if alarms != 1 else ''}, {by_world['live']} real "
            f"money, open R {lead_s['r_t'] or DASH}, open risk "
            f"{lead_s['risk_pct_t'] or DASH} of {lead_s['limit_pct_t'] or DASH}.")
    return {"ok": True, "v": V, "part": "tab", "as_of": _iso(now),
            "seats": len(seats), "by_world": by_world, "alarms": alarms,
            "alarm_real": alarm_real, "stragglers": len(book.stragglers),
            "lead": lead, "sides": sides, "flag": flag,
            "title_t": title, "aria_t": aria,
            "attention_t": (f"{alarms} seat{'s' if alarms != 1 else ''} need"
                            f"{'' if alarms != 1 else 's'} attention." if alarms else "")}


def _compute(user, pf, fp, now):
    book = _read_book(user, pf, fp, now)
    try:
        raw = _head_raw(user, fp[0], now)
    except Exception:  # noqa: BLE001 — the seats are still served
        logger.warning("[horde] the book limits could not be read", exc_info=True)
        raw = None
    seats, sizes = _seats(book, raw)
    if raw is not None:
        head, gate_risk = _head(raw, seats, book)
    else:
        head, gate_risk = _unreadable_head(book, seats), {}
    tab = _tab_of(book, seats, head, raw, now)
    groups = _groups(seats, sizes, gate_risk, user)
    return book, raw, head, groups, tab


def board(user, *, now=None) -> dict:
    """The open band's answer (part=board). Not cached: marks move inside
    the fingerprint's blind spot, and covering that is the poll's job."""
    now = now or timezone.now()
    pf = _own_book(user)
    fp = _fingerprint(user, pf)
    book, raw, head, groups, tab = _compute(user, pf, fp, now)
    empty = None
    if not groups:
        if not book.stragglers:
            empty = ({"code": "no_book", "t": EMPTY_NO_BOOK}
                     if not (book.n_configs or book.n_trades or book.legacy)
                     else {"code": "no_seats", "t": EMPTY_NO_SEATS})
    cache.set(_tab_key(user, fp[0]), tab, KEPT_S)
    return {
        "ok": True, "v": V, "part": "board", "as_of": _iso(now),
        "cadence": {"tick_s": TICK_S, "up_every": UP_EVERY},
        "book": {"label": "Your book", "legacy_book": f"{user.username}_main",
                 "readable": head["readable"]},
        "head": head, "groups": groups, "stragglers": _stragglers(book),
        "unseated": _unseated(raw, book, user), "empty": empty, "tab": tab,
    }


def _tab_key(user, fp):
    return f"sv:horde:tab:{user.pk}:{_digest(fp)}"


def tab(user, *, now=None) -> dict:
    """The collapsed tab's answer (part=tab), cached KEPT_S on the
    fingerprint: a hit costs the book read and the fingerprint only."""
    now = now or timezone.now()
    pf = _own_book(user)
    fp = _fingerprint(user, pf)
    key = _tab_key(user, fp[0])
    hit = cache.get(key)
    if hit is not None:
        return hit
    _book, _raw, _head_, _groups_, out = _compute(user, pf, fp, now)
    cache.set(key, out, KEPT_S)
    return out


# ── one seat's dossier (Block C, on demand) ──────────────────────────────

def parse_seat_key(raw):
    """("bot" | "pf", id) from "bot:142" / "pf:7", or None."""
    text = str(raw or "")
    if ":" not in text:
        return None
    kind, _sep, ident = text.partition(":")
    if kind not in ("bot", "pf") or not ident.isdigit():
        return None
    return kind, int(ident)


def _line_t(label, text, **extra):
    out = {"label": label, "t": text if text not in (None, "") else DASH}
    out.update(extra)
    return out


def _debate_words(debate, cut=None):
    """The debate recorded on the row (bot_program/asset_engine/base.py
    entry_meta["debate"]: each side is the agent's own parse, ai_agents/
    agents/trade_debate.py — the Executioner's verdict and killer, the
    Champion's verdict and edge), in one line."""
    def side(name, why_key):
        said = debate.get(name)
        if not isinstance(said, dict):
            return DASH
        verdict = str(said.get("verdict") or "").upper() or DASH
        why = _end(said.get(why_key))
        return f"{verdict}: {why}" if why else verdict
    text = (f"Executioner: {side('executioner', 'killer')} · "
            f"Champion: {side('champion', 'edge')} · "
            f"{'binding' if debate.get('binding') else 'shadow'}")
    if not debate.get("ran") and debate.get("why"):
        text += f" · {_end(debate['why'])}"
    if isinstance(cut, dict) and _f(cut.get("scale")) is not None:
        text += f" · Size cut: {_g(cut.get('scale'))}x"
    return text


def _entry_tags(meta):
    """The entry's own stamps (bot_program/asset_engine/base.py: the
    promotion stage label, the proof, the attack tier, the elite flag, the
    crisis posture), in words; dicts are read, never printed raw."""
    from portfolio.risk_gate import ELITE_META_KEY
    tags = []
    if meta.get("promotion_stage"):
        tags.append(f"promotion stage {meta['promotion_stage']}")
    proof = meta.get("proof")
    if isinstance(proof, dict) and (proof.get("tier") or proof.get("words")):
        tags.append(f"proof {proof.get('tier') or _end(proof.get('words'))}")
    if meta.get("attack"):
        tags.append("attack mode at entry")
    if meta.get(ELITE_META_KEY):
        tags.append("elite entry past the daily stop")
    posture = meta.get("posture")
    if isinstance(posture, dict) and posture.get("level"):
        kind = str(posture.get("kind") or "").replace("_", " ")
        tags.append(f"posture at entry: {posture['level']}"
                    + (f" ({kind})" if kind else ""))
    return tags


def _mission(trade, hand, signal, pcls, now):
    from .position_summary import why_words
    meta = trade.metadata or {}
    sym = trade.symbol
    out = {"why": why_words(trade),
           "who": WHO_YOU if hand else WHO_BOT.format(name=trade.config.name,
                                                       id=trade.config.id),
           "reason": "", "score_t": None, "signal": None, "signal_t": NO_SIGNAL,
           "at_entry": [], "debate": None, "tags": [], "rule_stage_t": None,
           "plan": None, "thesis": NO_THESIS_YET}
    if signal is not None:
        direction = str(signal.direction or "").upper()
        rr = _f(signal.risk_reward_ratio)
        out["signal_t"] = " · ".join([
            f"#{signal.id}", signal.title, direction,
            "score {:.2f}".format(_f(signal.score) or 0.0),
            "suggested entry " + _price(signal.suggested_entry, pcls, sym),
            "stop " + _price(signal.suggested_stop, pcls, sym),
            "target " + _price(signal.suggested_target, pcls, sym),
            "R:R " + ("{:.2f}".format(rr) if rr is not None else DASH)])
        out["signal"] = {"id": signal.id, "page": None}
    if not hand:
        out["reason"] = str(trade.reason or "")
        score = _f(trade.composite_score)
        if score:
            out["score_t"] = "score {:.2f}".format(score)
    if hand:
        lines = []
        for key, label in (("book_limit_at_entry", "Book limits"),
                           ("concentration_at_entry", "Concentration"),
                           ("theme_at_entry", "Theme")):
            rec = meta.get(key)
            if isinstance(rec, dict):
                ok = bool(rec.get("ok", True))
                lines.append({"label": label, "ok": ok,
                              "t": "clear" if ok else "past at entry: "
                              + str(rec.get("reason") or DASH)})
        cost = meta.get("cost_at_entry")
        if isinstance(cost, dict):
            ok = bool(cost.get("ok", True))
            lines.append({"label": "Cost", "ok": ok,
                          "t": "clear" if ok else str(cost.get("reason") or DASH)})
        rr = meta.get("reward_risk_at_entry")
        if isinstance(rr, dict) and _f(rr.get("ratio")) is not None:
            lines.append({"label": "Reward:risk", "ok": bool(rr.get("ok", True)),
                          "t": "{:.2f}".format(_f(rr["ratio"]))})
        sb = meta.get("signal_backing_at_entry")
        if isinstance(sb, dict):
            n = len(sb.get("signals") or [])
            lines.append({"label": "Signal backing", "ok": n > 0,
                          "t": f"{n} signal(s)" if n else "none"})
        if meta.get("size_source"):
            lines.append({"label": "Size", "ok": True,
                          "t": "yours" if meta["size_source"] == "operator"
                          else "the risk budget"})
        out["at_entry"] = lines
    debate = meta.get("debate") if isinstance(meta.get("debate"), dict) else None
    if debate:
        out["debate"] = {"present": True, "t": _debate_words(debate, meta.get("debate_cut"))}
    else:
        from .position_summary import world_of
        world = world_of(trade)
        reason = ("manual" if hand else "paper" if world == "paper"
                  else "demo" if world == "demo" else "")
        out["debate"] = {"present": False, "t": DEBATE_NONE[reason]}
    out["tags"] = _entry_tags(meta)
    if not hand and trade.rule_name:
        # The stage alone, in one read: views_forensics._rule_state also
        # pays for the provenance note (up to four reads on a live rule).
        try:
            from signals.models_control import RuleControl
            stage = (RuleControl.objects.filter(rule_name=trade.rule_name)
                     .values_list("promotion_stage", flat=True).first())
        except Exception:  # noqa: BLE001 — no stage is no line
            stage = None
        if stage:
            out["rule_stage_t"] = f"rule stage {stage}"
    return out


def _timeline(trade, hand, actions, notices, reviews, pcls, now):
    from .position_summary import quantity
    meta = trade.metadata or {}
    sym = trade.symbol
    out = []

    def add(at, author, text):
        out.append({"at": _iso(at) if at else None, "author": author, "t": text})

    target = _f(trade.take_profit)
    istop = _a_stop(meta.get("initial_stop_loss") if meta.get("initial_stop_loss") is not None
                    else trade.stop_loss)
    add(trade.opened_at, "YOU" if hand else "BOT",
        f"Opened {_side_word(trade.side)} {quantity(trade.qty)} @ "
        f"{_price(trade.entry_price, pcls, sym)}, "
        f"stop {_price(istop, pcls, sym) if istop else 'none'}, "
        f"target {_price(target, pcls, sym) if target else 'none'}.")
    if meta.get("entry_filled_at"):
        add(_when(meta["entry_filled_at"]), "VENUE", "The working order filled.")
    for e in meta.get("level_edits") or []:
        if not isinstance(e, dict):
            continue
        # adjust_levels records stop None on a target-only edit.
        if e.get("stop") not in (None, ""):
            text = f"You set the stop to {_price(e.get('stop'), pcls, sym)}"
            if e.get("target"):
                text += f" and the target to {_price(e.get('target'), pcls, sym)}"
        elif e.get("target"):
            text = f"You set the target to {_price(e.get('target'), pcls, sym)}"
        else:
            text = "You cleared the target"
        if e.get("widened"):
            text += ", wider than before"
        moved = str(e.get("broker") or "") not in ("", "row-only", "bot")
        text += ". " + ("Moved at the broker." if moved else "On the platform only.")
        add(_when(e.get("at")), "YOU", text)
    for m in meta.get("stop_moves") or []:
        if not isinstance(m, dict):
            continue
        why = str(m.get("why") or "")
        broker = why.endswith(":broker")
        why = why[:-len(":broker")] if broker else why
        text = (f"Stop moved to {_price(m.get('to'), pcls, sym)} "
                f"({why.replace('_', ' ') or 'a rule'})"
                + (" at the broker" if broker else ""))
        if m.get("asked") not in (None, "") and str(m.get("asked")) != str(m.get("to")):
            text += f", asked {_price(m.get('asked'), pcls, sym)}"
        add(_when(m.get("when")), "ENGINE", text + ".")
    moved = meta.get("stop_rewritten_by_venue")
    if isinstance(moved, dict):
        held = _f(moved.get("held"))
        sent = _price(moved.get("sent"), pcls, sym)
        at = _when(meta.get("entry_filled_at")) or trade.opened_at
        if held is not None and held > 0.0001 \
                and abs(held - (_f(moved.get("sent")) or 0.0)) > 1e-9:
            add(at, "VENUE", f"eToro held the stop at {_price(held, pcls, sym)} "
                             f"instead of {sent}.")
        elif held is not None:
            # Past tense: what the fill left there, which a later move,
            # edit or re-anchor replaces (the stops list says what rests
            # there now).
            add(at, "VENUE", f"eToro held no stop at the fill: {sent} was sent.")
    for a in actions:
        detail = _end(a.detail)
        if a.kind == "care_mirror":
            add(a.at, "CARE", (a.detail or "").strip())
        elif a.kind == "care_close":
            add(a.at, "CARE", f"The care closed it: {detail}.")
        elif a.kind == "care_close_pending":
            add(a.at, "CARE", f"The care asked to close it: {detail}. The broker "
                              f"has not confirmed.")
        elif a.kind == "scale_out":
            add(a.at, "CARE", f"Scale-out: {detail}.")
    if meta.get("protection_vanished_at"):
        add(_when(meta["protection_vanished_at"]), "VENUE",
            "The protective orders vanished at the broker.")
    tries = int(_f(meta.get("close_retry_attempts")) or 0)
    if tries:
        add(None, "SAURON", f"Close refused by the broker; attempt {tries}.")
    for r in reviews:
        first = ""
        for t in r.triggers or []:
            if isinstance(t, dict) and t.get("text"):
                first = str(t["text"])
                break
        add(r.created_at, "REVIEWER", f"{_review_word(r.verdict)}: {_end(first) or DASH}.")
    thesis = meta.get("thesis") if isinstance(meta.get("thesis"), dict) else None
    if thesis:
        add(_when(thesis.get("at")), "THESIS CHECK",
            f"{str(thesis.get('verdict') or '').upper()}: {thesis.get('words') or DASH}")
    for n in notices:
        add(n.created_at, "NOTICE", n.title)
    timed = sorted([e for e in out if e["at"]], key=lambda e: e["at"], reverse=True)
    untimed = [e for e in out if not e["at"]]
    return (timed + untimed)[:TIMELINE_MAX]


def _peers(user, symbol, side, cls, world, others, now):
    """The underlying's peers: the viewer's other seats (same world first),
    the SMT partner, the commodity complex, the seats that share a currency
    leg — capped at PEERS_MAX; one correlation matrix (bot_program.
    capital_desk.correlation_matrix, 4h, 45 days, cached on the newest
    bar), one Instrument read and one LiveQuote read. A peer that is a
    seat prints its own mark (bot_program.venue_mark.resolve over that same
    quote read), never the platform's quote; any other peer prints the
    quote, dashed past QUOTE_MAX_AGE_S."""
    from bot_program import capital_desk
    from bot_program.venue_mark import QUOTE, resolve
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    from portfolio.risk_gate import COMMODITY_THEMES, _currency_legs
    from signals.rules.smc_rules import smt_partner_for

    sym = symbol.upper()
    seats_by_sym = {}
    for o in sorted(others, key=lambda o: (o["world"] != world, o["id"])):
        seats_by_sym.setdefault(o["symbol"].upper(), o)
    smt = smt_partner_for(sym)
    smt = str(smt).upper() if smt else None
    complex_name = COMMODITY_THEMES.get(sym) if cls == "commodity" else None
    complex_syms = [s for s, c in COMMODITY_THEMES.items()
                    if complex_name and c == complex_name and s != sym]
    my_legs = set(_currency_legs(sym, side)) if cls == "forex" else set()
    candidates = list(seats_by_sym) + ([smt] if smt else []) + complex_syms
    insts = {r["symbol"].upper(): r for r in Instrument.objects.filter(
        symbol__in=set(candidates) | {sym}).values("symbol", "is_active",
                                                    "asset_class")}

    order, seen = [], {sym}

    def push(s):
        if s and s not in seen:
            seen.add(s)
            order.append(s)
    for s in seats_by_sym:
        push(s)
    push(smt)
    for s in complex_syms:
        if (insts.get(s) or {}).get("is_active"):
            push(s)
    order = order[:PEERS_MAX]
    matrix = capital_desk.correlation_matrix(user, order + [sym]) if order else {}
    quotes = ({q.instrument.symbol.upper(): q for q in LiveQuote.objects
               .select_related("instrument").filter(instrument__symbol__in=order)}
              if order else {})

    rows = []
    measured = (matrix or {}).get("measured") or set()
    for s in order:
        pair = (sym, s) if sym < s else (s, sym)
        is_m = pair in measured
        rho = capital_desk.rho_of(matrix, sym, s) if is_m else None
        seat = seats_by_sym.get(s)
        legs = set(_currency_legs(s, (seat or {}).get("side", "BUY"))) \
            if cls == "forex" else set()
        if smt and s == smt:
            rel = "SMT PARTNER"
        elif s in complex_syms:
            rel = "SAME COMPLEX"
        elif my_legs and legs and (my_legs & legs):
            rel = "SHARES " + sorted(my_legs & legs)[0]
        else:
            # Every other peer is one of the viewer's seats (the universe
            # is seats, the SMT partner and the complex).
            rel = f"SEAT #{seat['id']}"
        q = quotes.get(s)
        last_t, change_t = None, None
        quoted = q is not None
        if seat:
            mark = resolve(seat["_trade"], q, now=now)
            if mark.price is not None:
                last_t = _price(mark.price, seat["class"], s)
            # The day's change is the quote's: printed only when the quote
            # IS what marks the seat, never a stand-in's.
            quoted = mark.source == QUOTE
        elif q is not None:
            at = q.updated_at
            if at is not None and (now - at).total_seconds() <= QUOTE_MAX_AGE_S:
                last_t = _price(q.last, (insts.get(s) or {}).get("asset_class", ""), s)
        chg = _f(q.change_pct) if (q is not None and quoted) else None
        if chg is not None and chg != 0:
            change_t = "{:+.1f}%".format(chg)
        bet = None
        if seat and is_m:
            b = capital_desk.bet_rho(matrix, sym, side, s, seat["side"])
            bet = "same bet" if b >= 0.7 else "a hedge" if b <= -0.7 else None
        has_page = s in insts
        rows.append({
            "symbol": s, "relation": rel, "measured": is_m,
            "rho_t": "{:+.2f}".format(rho) if rho is not None else None,
            "rho_v": round(rho, 3) if rho is not None else None,
            "strength": ("strong" if abs(rho) >= 0.7 else "moderate" if abs(rho) >= 0.4
                         else "weak") if rho is not None else None,
            "n_bars": int(((matrix or {}).get("n_bars") or {}).get(pair) or 0),
            "why_t": None if is_m else CORR_UNMEASURED,
            "bet_t": bet, "is_seat": bool(seat), "seat_key": seat["key"] if seat else None,
            "last_t": last_t, "change_t": change_t,
            "page": f"/instruments/{s}/" if has_page else None,
            "ticket": bool(has_page and (insts.get(s) or {}).get("is_active")
                           and not seat),
        })
    chips = [f"SMT partner: {smt}"] if smt else []
    return rows, chips


def _peer_seat(t):
    """A seat as the peer table reads it: the row itself (its own mark is
    resolved from it), its key, side, world and class."""
    from .position_summary import world_of
    return {"id": t.id, "key": f"bot:{t.id}", "symbol": t.symbol,
            "side": str(t.side or "").upper(), "world": world_of(t),
            "class": t.asset_class or "", "_trade": t}


def seat_detail(user, raw_key, *, now=None):
    """One seat's dossier (?seat=bot:<id> | pf:<id>), or None when the seat
    is not open in this viewer's book. Never on a timer.

    The seat and the viewer's other open bot rows (the peer table's first
    ring) are one read: the book is owner-scoped in the queryset, so a key
    from another book is simply not in it."""
    from alerts.models import Notification
    from bot_program.aragorn_models import AragornAction
    from bot_program.models import AssetBotTrade
    from brain.position_review_models import PositionReview
    from signals.models import Signal

    from .views import _live_row, _pos_leverage, _trade_leverage

    parsed = parse_seat_key(raw_key)
    if parsed is None:
        return None
    kind, ident = parsed
    now = now or timezone.now()
    head = cache.get(f"sv:horde:headlast:{user.pk}")
    sizes = _book_sizes(head)
    book = _Book()
    book.now = now
    book.pf = None
    book.stragglers = []

    if kind == "pf":
        from portfolio.models import Position

        from .views_command import _reprice_legacy
        p = (Position.objects.select_related("instrument", "strategy")
             .filter(pk=ident, portfolio__name=f"{user.username}_main",
                     closed_at__isnull=True).first())
        if p is None:
            return None
        _reprice_legacy([p])
        book.switches = _switches()
        reviews = list(PositionReview.objects.filter(
            book="pf", position_id=p.pk,
            created_at__gte=now - timedelta(days=7)).order_by("-created_at")[:10])
        latest = next((r for r in reviews
                       if r.created_at >= now - timedelta(hours=24)), None)
        book.reviews = {f"pf:{p.pk}": latest.card_payload()} if latest else {}
        row = _live_row(p, {}, {f"pos-{p.pk}": _pos_leverage(
            getattr(p.instrument, "asset_class", "") or "")})
        seat = _legacy_seat(book, p, row, sizes, now)
        for k in ("_sort", "_theme", "_ccy", "_unstamped"):
            seat.pop(k, None)
        others = [_peer_seat(t) for t in AssetBotTrade.objects.select_related("config")
                  .filter(config__user=user, status__in=SEAT_STATUSES)]
        peers, chips = _peers(user, seat["symbol"], seat["side"], seat["class"],
                              seat["world"], others, now)
        return _legacy_detail(seat, p, reviews, book, peers, chips, now)

    open_rows = list(AssetBotTrade.objects.select_related("config")
                     .filter(config__user=user, status__in=SEAT_STATUSES))
    trade = next((t for t in open_rows if t.pk == ident), None)
    if trade is None:
        return None
    meta = trade.metadata or {}
    # _normalize_trades' own two reads, kept by hand so the quote that
    # marked the row is in hand for the stand-in sentence.
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    from portfolio.services import _trade_to_position
    instruments = {i.symbol: i for i in Instrument.objects.filter(symbol=trade.symbol)}
    quotes = {q.instrument.symbol: q for q in LiveQuote.objects
              .select_related("instrument").filter(instrument__symbol=trade.symbol)}
    up = _trade_to_position(trade, instruments, quotes)
    quote = quotes.get(trade.symbol)
    from bot_program.manual_close import _initial_stop
    row = _live_row(up, {f"bot-{trade.id}": _a_stop(_initial_stop(trade))},
                    {f"bot-{trade.id}": _trade_leverage(trade)})
    hand = _is_hand(trade)
    signal = None
    sid = meta.get("signal_id")
    try:
        sid = int(sid) if sid not in (None, "") else None
    except (TypeError, ValueError):
        sid = None
    if sid:
        signal = Signal.objects.select_related("instrument").filter(pk=sid).first()
    actions = list(AragornAction.objects.filter(
        trade_id=trade.id, at__gte=now - timedelta(days=30)).order_by("-at")[:50])
    notices = list(Notification.objects.filter(
        user=user, url=f"/forensics/{trade.id}/").order_by("-created_at")[:20])
    reviews = list(PositionReview.objects.filter(
        book="bot", position_id=trade.id,
        created_at__gte=now - timedelta(days=7)).order_by("-created_at")[:10])
    book.switches = _switches()
    latest = next((r for r in reviews if r.created_at >= now - timedelta(hours=24)), None)
    book.reviews = {f"bot:{trade.id}": latest.card_payload()} if latest else {}
    seat = _bot_seat(book, trade, up, row, sizes, now)
    for k in ("_sort", "_theme", "_ccy", "_unstamped"):
        seat.pop(k, None)
    pcls = seat["instrument_class"]
    others = [_peer_seat(t) for t in open_rows if t.pk != trade.pk]
    peers, chips = _peers(user, trade.symbol, str(trade.side).upper(), seat["class"],
                          seat["world"], others, now)
    return _bot_detail(seat, trade, up, quote, row, hand, signal, actions, notices,
                       reviews, book, sizes, peers, chips, pcls, now)


def _voice_reviewer(reviews, switches, now):
    if not switches.get("agent_position_review"):
        return {"switch_on": False, "present": False, "t": REVIEW_OFF}
    latest = next((r for r in reviews if r.created_at >= now - timedelta(hours=24)), None)
    if latest is None:
        return {"switch_on": True, "present": False, "t": REVIEW_QUIET}
    card = latest.card_payload()
    age = (now - latest.created_at).total_seconds()
    reasoning = str(card.get("reasoning_md") or "")
    return {"switch_on": True, "present": True,
            "word": _review_word(card.get("verdict")),
            "age_t": _age_words(age),
            "confidence_t": ("{:.2f}".format(card["confidence"])
                             if card.get("confidence") is not None else None),
            "triggers": [{"t": t.get("text") or "", "severity": t.get("severity")}
                         for t in card.get("triggers") or []],
            # Whole (bounded): the page shows the first REASONING_MAX
            # characters and a "more" that unfolds the rest.
            "reasoning": reasoning[:REASONING_KEPT],
            "reasoning_cut": REASONING_MAX if len(reasoning) > REASONING_MAX else None,
            "suggested_stop_t": (_g(card["suggested_stop"])
                                 if card.get("suggested_stop") is not None else None),
            "take_part_t": (f"Take {card['take_part_pct']}%"
                            if card.get("take_part_pct") else None)}


def _orc_block(seat):
    return {"present": False, "t": [NO_ORC_SEATED, NOT_DECIDED, ORC_ARRIVES,
                                    TODAY.format(holder=seat["holder"]["words"])]}


def _phone(seat, trade=None):
    lines = [{"cmd": c.format(symbol=seat["symbol"], question="{question}"),
              "t": t.format(symbol=seat["symbol"])} for c, t in PHONE_LINES]
    if trade is not None and seat["lane"] == "bot":
        cfg = trade.config
        words = PHONE_STOP_WORKING if seat.get("working") else PHONE_STOP[1]
        lines.append({"cmd": PHONE_STOP[0].format(id=cfg.id),
                      "t": words.format(name=cfg.name, id=cfg.id)})
    return lines


def _bot_detail(seat, trade, up, quote, row, hand, signal, actions, notices,
                reviews, book, sizes, peers, chips, pcls, now):
    from bot_program.asset_engine.base import time_stop_status
    from bot_program.asset_engine.safety import heartbeat_age_seconds
    from bot_program.notifications import _held_stop
    from bot_program.venue_mark import quote_stand_in
    from core.exchange_status import get_exchange_status, market_status_for
    from market_data.public_feed import YF_SYMBOL_MAP
    from portfolio.services import notional_usd, value_per_unit

    from .position_summary import countdown_words, quantity
    from .views import _pos_committed_pct

    meta = trade.metadata or {}
    sym = trade.symbol
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    world = seat["world"]
    side_book = sizes.get("paper" if world == "paper" else "live")
    mission = _mission(trade, hand, signal, pcls, now)
    # An opening stop of 0 is eToro's "no stop": no 1R and no target in R.
    istop = _a_stop(row.get("initial_stop"))
    entry = _f(trade.entry_price)
    qty = abs(_f(trade.qty) or 0.0)
    vpu = value_per_unit(trade)
    one_r = None
    if istop is not None and entry and (trade.asset_class != "forex"
                                        or meta.get("value_per_unit") is not None):
        one_r = abs(entry - istop) * qty * vpu
    target = _f(trade.take_profit)
    tgt_r = None
    if istop is not None and entry and target and abs(entry - istop) > 1e-12:
        tgt_r = abs(target - entry) / abs(entry - istop)
    lv = seat["levels"]
    mission["plan"] = {"t": (
        f"entry {lv['entry_t']} · opening stop {lv['istop_t'] or 'none'} "
        f"(1R = {_money(one_r) or DASH}) · stop now {lv['stop_t'] or 'none'}"
        + (f" (sent {lv['sent_stop_t']})" if lv.get("sent_stop_t") else "")
        + f" · target {lv['target_t'] or 'none'}"
        + (f" · target is {tgt_r:.2f}R from entry at the opening stop" if tgt_r else ""))}

    # deployment
    notional = notional_usd(up)
    at_work = seat["at_work"]
    pool_pct = _pos_committed_pct(at_work["v"], trade) if at_work["v"] else ""
    risk_t = (None if seat["risk"]["t"] is None
              else f"+{seat['risk']['locked_t']} locked" if seat["risk"]["locked"]
              else "the whole notional" if not seat["risk"]["stopped"]
              else f"{seat['risk']['t']} ({seat['risk']['pct_t'] or DASH} of the book)")
    risk_sub = None if risk_t is not None else "No USD conversion stamp"
    if seat["risk"].get("venue_note"):
        # The venue holds another stop (or none): what can be lost there
        # first, and the gate's own figure at the stop sent under it.
        risk_sub = RISK_GATE_SUB.format(x=risk_t or DASH)
        risk_t = seat["risk"]["venue_note"]
    order = str(trade.broker_order_id or "")
    deployment = [
        _line_t("Quantity", quantity(trade.qty)),
        _line_t("Notional (USD)", _money(notional)),
        _line_t("Leverage", row.get("leverage") or None),
        _line_t("Capital at work", (f"{at_work['t']} ({at_work['kind']})"
                                    if at_work["t"] else None)),
        _line_t("of its pool", f"{pool_pct}%" if pool_pct else None),
        _line_t("of the book", _pct(at_work["v"] / side_book * 100)
                if (at_work["v"] and side_book) else None),
        _line_t("Risk at the stop", risk_t, sub=risk_sub),
        _line_t("1R", _money(one_r), sub=None if one_r is not None
                else "No USD conversion stamp"),
        _line_t("Who holds the levels", seat["holder"]["suffix"]),
        _line_t("Carrier", seat["venue"]),
        _line_t("Order", order[-8:] if order else None, title=order),
        _line_t("Pool of", f"{trade.config.name} #{trade.config.id} · {trade.config.mode}"),
    ]

    # metrics
    since = _when(care.get("since"))
    metrics = [
        _line_t("P&L", " · ".join(x for x in (
            seat["money"]["pnl_t"], (seat["money"]["pct_t"] + " of notional")
            if seat["money"]["pct_t"] not in (None, DASH) else "",
            (seat["money"]["cap_pct_t"] + " of capital")
            if seat["money"]["cap_pct_t"] else "") if x)),
        _line_t("R now", seat["money"]["r_t"], title=seat["money"]["r_title"]),
        _line_t("Best / worst",
                f"{seat['care']['mfe_t']} / {seat['care']['mae_t']}"
                if seat["care"]["mfe_t"] else f"{DASH} the care has no record of this row",
                sub=(f"the care's record since {since.strftime('%-d %b')}"
                     if since and seat["care"]["mfe_t"] else None)),
        _line_t("Progress", "stop → target", progress_v=seat["levels"]["progress_v"]),
        _line_t("Mark", " · ".join(x for x in (seat["mark"]["t"], seat["mark"]["word"])
                                   if x and x != DASH) or seat["mark"]["wait"] or None,
                title=seat["mark"]["title"]),
    ]
    stand = ""
    if not trade.paper:
        kind = quote_stand_in(sym, quote, carrier=str(meta.get("broker") or ""))
        if kind:
            stand = STAND_IN.format(quote=YF_SYMBOL_MAP.get(sym.upper(), DASH),
                                    kind=STAND_IN_KIND.get(kind, kind))
            metrics.append(_line_t("Stand-in", stand))
    metrics.append(_line_t("Held", f"Held for {seat['held']['t']}"))
    try:
        ms = market_status_for(pcls, getattr(up.instrument, "exchange", "") or "",
                               _status=get_exchange_status(), symbol=sym)
        when = countdown_words(ms.get("time_until_change"))
        if ms.get("code") == "CRYPTO":
            mtext = "Crypto: always open"
        elif ms.get("is_open"):
            mtext = f"{ms.get('name')} open" + (f" · shuts in {when}" if when else "")
        else:
            mtext = f"{ms.get('name')} shut" + (f" · opens in {when}" if when else "")
    except Exception:  # noqa: BLE001
        mtext = None
    metrics.append(_line_t("Market", mtext))
    # The engine's clock exit runs on every row a config manages, the
    # manual lane's included (asset_engine/base.py _time_stop_hit reads
    # the config's ceiling, the class default when blank).
    ts = time_stop_status(trade, config=trade.config, now=now)
    metrics.append(_line_t("Time stop", (
        f"Time stop: {_g(ts['max_hold_hours'])} h after entry ({ts.get('source')})"
        if ts.get("enabled") else "Time stop: off")))
    so = meta.get("scale_out") if isinstance(meta.get("scale_out"), dict) else None
    if so:
        metrics.append(_line_t("Scale-out", (
            f"Half banked at {_price(so.get('price'), pcls, sym)}, "
            f"{_g(so.get('r'))}R, {_hhmm(so.get('at')) or DASH}")))
    age = heartbeat_age_seconds(trade.config)
    metrics.append(_line_t("Last tick", f"The bot last ticked {_age_words(age)} ago."
                           if age is not None else None))

    stops = [{"label": "stop on the row",
              "t": _price(trade.stop_loss, pcls, sym) if trade.stop_loss else "none"}]
    # What eToro left at the fill rests there only until something moves
    # the levels (_venue_held_stop, venue_exit.venue_levels): after that it
    # is history, said as history.
    held = _venue_held_stop(trade)
    fill = _held_stop(trade)
    if held is not None:
        stops.append({"label": "stop held at eToro since the fill",
                      "t": "none" if held == 0.0 else _price(held, pcls, sym)})
    elif fill is not None:
        stops.append({"label": STOP_FILL_REPLACED.format(venue="eToro"),
                      "t": "none" if fill == 0.0 else _price(fill, pcls, sym)})
    if care.get("venue_stop") is not None:
        stops.append({"label": "stop copied to eToro by the care",
                      "t": _price(care.get("venue_stop"), pcls, sym)})
    if care.get("soft_stop") is not None:
        stops.append({"label": "platform soft stop",
                      "t": _price(care.get("soft_stop"), pcls, sym),
                      "why": str(care.get("soft_why") or "")})

    timeline = _timeline(trade, hand, actions, notices, reviews, pcls, now)
    timeline_now = (f"Now: the care's soft stop is {_price(care['soft_stop'], pcls, sym)} "
                    f"({care.get('soft_why') or DASH})."
                    if care.get("soft_stop") is not None else "")

    thesis = meta.get("thesis") if isinstance(meta.get("thesis"), dict) else None
    th = _thesis_of(meta, now)
    voice = {
        "reviewer": _voice_reviewer(reviews, book.switches, now),
        "thesis": ({"word": th["word"], "age_t": th["age_t"], "words": th["words"],
                    "stop_t": (_price(thesis.get("stop"), pcls, sym)
                               if thesis.get("stop") else None),
                    "applies": THESIS_ADVICE if hand else THESIS_APPLIED}
                   if th else {"word": None, "t": THESIS_NONE}),
        "care": {"words": seat["holder"]["words"], "suffix": seat["holder"]["suffix"],
                 "soft_t": (f"Soft stop {_price(care['soft_stop'], pcls, sym)} "
                            f"({care.get('soft_why') or DASH})"
                            if care.get("soft_stop") is not None else None),
                 "venue_t": (f"Copied to eToro: {_price(care['venue_stop'], pcls, sym)}"
                             if care.get("venue_stop") is not None else None),
                 "refusal": (f"eToro refused the care's stop: "
                             f"{care['venue_stop_refusal']}"
                             if care.get("venue_stop_refusal") else ""),
                 "event": (f"Event ahead: {care['event'].get('title')} at "
                           f"{_hhmm(care['event'].get('at'))} UTC"
                           if isinstance(care.get("event"), dict) else None),
                 "none_t": "" if care else CARE_NONE},
        "notes": {"stored": False, "t": NOTES_NONE},
        "orc": None,
        "orc_block": _orc_block(seat),
    }
    page = seat["links"]["page"]
    underlying = {
        "symbol": sym, "page": page, "chart": seat["links"]["chart"],
        "venue_id": _venue_pin(sym),
        "stand_in_t": stand or None, "market_t": mtext,
    }
    return {
        "ok": True, "v": V, "as_of": _iso(now), "seat": seat,
        "mission": mission, "deployment": deployment, "metrics": metrics,
        "stops": stops, "timeline": timeline, "timeline_now": timeline_now,
        "timeline_note": TIMELINE_NOTE, "timeline_empty": TIMELINE_EMPTY,
        "voice": voice,
        "instruments": {"underlying": underlying, "peers": peers, "chips": chips,
                        "note": CORR_NOTE, "empty_t": CORR_EMPTY},
        "phone": _phone(seat, trade),
    }


def _venue_pin(symbol):
    """eToro's own instrument id for this symbol when the client pins it
    (bot_program/engine/etoro_client.py VENUE_ID_PINS), else None: a fact
    about eToro's catalogue, printed whatever world the seat is in."""
    try:
        from bot_program.engine.etoro_client import VENUE_ID_PINS
    except Exception:  # noqa: BLE001 — no client, no line
        return None
    return VENUE_ID_PINS.get(str(symbol or "").upper())


def _legacy_detail(seat, p, reviews, book, peers, chips, now):
    from portfolio.services import notional_usd
    sym = seat["symbol"]
    mission = {"why": f"Recorded by hand on {sym}.", "who": "Recorded in your hand-kept book",
               "reason": "", "score_t": None, "signal": None, "signal_t": NO_SIGNAL,
               "at_entry": [], "debate": None, "tags": [], "rule_stage_t": None,
               "plan": {"t": (f"entry {seat['levels']['entry_t']} · stop "
                              f"{seat['levels']['stop_t'] or 'none'} · target "
                              f"{seat['levels']['target_t'] or 'none'}")},
               "thesis": NO_THESIS_YET}
    deployment = [
        _line_t("Quantity", str(p.quantity.normalize()) if p.quantity is not None else None),
        _line_t("Notional (USD)", _money(notional_usd(p))),
        _line_t("Capital at work", (f"{seat['at_work']['t']} ({seat['at_work']['kind']})"
                                    if seat["at_work"]["t"] else None)),
        _line_t("Risk at the stop", seat["risk"]["t"] if seat["risk"]["stopped"]
                else "the whole notional"),
        _line_t("Carrier", None),
    ]
    metrics = [
        _line_t("P&L", seat["money"]["pnl_t"]),
        _line_t("R now", seat["money"]["r_t"], title=seat["money"]["r_title"]),
        _line_t("Mark", seat["mark"]["t"] if seat["mark"]["v"] is not None
                else seat["mark"]["wait"] or None, title=seat["mark"]["title"]),
        _line_t("Held", f"Held for {seat['held']['t']}"),
    ]
    stops = [{"label": "stop on the row",
              "t": seat["levels"]["stop_t"] or "none"}]
    voice = {
        "reviewer": _voice_reviewer(reviews, book.switches, now),
        "thesis": {"word": None, "t": THESIS_LEGACY},
        "care": {"words": seat["holder"]["words"], "suffix": "", "soft_t": None,
                 "venue_t": None, "refusal": "", "event": None, "none_t": ""},
        "notes": {"stored": False, "t": NOTES_NONE},
        "orc": None, "orc_block": _orc_block(seat),
    }
    return {
        "ok": True, "v": V, "as_of": _iso(now), "seat": seat,
        "mission": mission, "deployment": deployment, "metrics": metrics,
        "stops": stops, "timeline": [], "timeline_now": "",
        "timeline_note": "", "timeline_empty": TIMELINE_LEGACY,
        "voice": voice,
        "instruments": {"underlying": {"symbol": sym, "page": seat["links"]["page"],
                                       "chart": seat["links"]["chart"],
                                       "venue_id": _venue_pin(sym), "stand_in_t": None,
                                       "market_t": None},
                        "peers": peers, "chips": chips, "note": CORR_NOTE,
                        "empty_t": CORR_EMPTY},
        "phone": _phone(seat),
    }
