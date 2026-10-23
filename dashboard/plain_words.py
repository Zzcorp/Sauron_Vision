# -*- coding: utf-8 -*-
"""What a stored reason may say on a page (2026-10-23).

Some of what a page prints was not written for it: a voice's own words
(the trade debate's Executioner and Champion, the position reviewer), a
reason a producer stored beside an order (the debate's `why`, a venue's
answer to a stop move, a check that could not read), an exception's text
caught on the way. Two rules hold for every one of them:

  * no exception text: a stored reason is said in fixed words keyed on
    its cause, never forwarded; a voice's line that names an exception,
    or repeats a stored failure's text, is withheld whole;
  * no amount of money a voice wrote: R and percent only. A voice's line
    that may name an amount is withheld whole, never cut to fit, so no
    half of a figure survives.

Nothing is ever cut out of a voice's line: it shows as the voice wrote
it, or a fixed sentence says it is withheld and why.

Neutral on purpose: the Horde (dashboard/horde.py) reads it today, and any
surface that prints the same stored reasons (the council band, the
positions page) can read the same words. The money and exception patterns
began as the council band's (task #104) and are widened here, so one line
is judged alike wherever it is printed. Pure: no I/O, no model, no
settings.
"""
from __future__ import annotations

import math
import re

#: The longest one line a voice may keep (the debate parses each side's
#: killer or edge to 300 characters, ai_agents/agents/trade_debate.py).
LINE_MAX = 300
WITHHELD = "Withheld: this line may name an amount of money."
WITHHELD_ERROR = "Withheld: this line quotes an error."

# ── the scrub: a voice's words ───────────────────────────────────────────

_CODES = r"US\$|USD|EUR|GBP|CHF|JPY|CAD|AUD|USDT|USDC"
#: The currency half of the alarm tripwire (tests/test_alarm_bot.py MONEY):
#: a currency sign or code beside a figure, a sign or a magnitude between
#: them allowed ("USD -850.00", "$-412.50", "1.2k USD", "1250 USDC").
CURRENCY = re.compile(
    r"[$€£¥]\s?[-+−]?\d"
    r"|\b(?:" + _CODES + r")\s?[-+−]?\d"
    r"|\d(?:[.,]\d+)?\s?[kmb]?\s?(?:[$€£¥]|(?:" + _CODES + r")\b)",
    re.IGNORECASE)
#: What a figure may be counted in when it is not money: R and percent
#: first (the platform's own units), then a multiple, a distance or a
#: count. "R:R" is a ratio's name, not a figure in R.
_NOT_MONEY = (r"\s?(?:R(?![\w:/])|%|x\b|ATRs?\b|pips?\b|points?\b|pts\b"
              r"|ticks?\b|bars?\b|candles?\b|days?\b|hours?\b|units?\b"
              r"|lots?\b|shares?\b|trades?\b|times\b|bps\b)")
#: A figure from its first digit, unless the whole figure (its own digits,
#: thousands groups and decimals: a comma or a full stop after it ends it)
#: is counted in one of the units above.
_FIGURE = (r"[-+−]?\d(?!\d*(?:,\d{3})*(?:\.\d+)?" + _NOT_MONEY + r")")
#: The words a voice puts between a money word and its figure ("a loss of
#: about 850.00", "risk ≈ 850.00", "risk of roughly 1,250").
_FILLER = (r"(?:\s*(?:[:=~≈]|\b(?:of|at|is|was|about|around|roughly"
           r"|approximately|near|nearly|almost|some|only|just|over|under"
           r"|used|left)\b))*\s*")
#: Its money-word clause, less "price" (a level is not money), less a
#: figure in R or percent ("a loss of 1R", "drawdown 4%" pass), less the
#: ratio and the level that share a money word ("net reward:risk 2.85",
#: "reward-to-risk of 2.85", "the stop loss at 1950", "take profit at
#: 2150"), and less "exposure" (the reviewer's concentration trigger counts
#: it in theme units, "net USD exposure +1.2"; an exposure in money is a
#: currency above). It covers the words a voice uses when it echoes the
#: brief's own amount ("size N units, risk at the stop 1,234.56",
#: trade_debate.candidate_brief).
MONEY_WORD = re.compile(
    r"\b(?:P&L|PnL|equity|margin|balance|cash|capital"
    r"|(?<!stop[ -])(?<!take[ -])(?:profit|loss)(?:es)?|drawdown"
    r"|(?<!reward[:/ -])(?<!reward-to-)(?<!reward to )risk(?:ing|ed|s)?"
    r"(?: at the stop)?"
    r"|stake|notional|book value|dollars?)\b" + _FILLER + _FIGURE,
    re.IGNORECASE)
#: A figure that reads as money: grouped in thousands, with decimals, or
#: whole from 100 up, all of its digits read ("lost 3 of 5" is a count).
_MONEYISH = (r"[-+−]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|[1-9]\d{2,})"
             r"(?![\d,]*\d)(?!" + _NOT_MONEY + r")")
#: The verbs a voice uses for an amount ("a stop-out costs 850.00", "would
#: lose 1250.00 on the stop", "gives back 412.50 of open profit").
MONEY_VERB = re.compile(
    r"\b(?:cost(?:s|ing)?|lose|loses|losing|lost|gain(?:s|ed|ing)?|worth"
    r"|give(?:s|n)? back|gave back|giving back)\b" + _FILLER + _MONEYISH,
    re.IGNORECASE)
#: The brief's amount shape (`:,.2f`: thousands grouped, two decimals),
#: whatever word stands beside it ("one stop costs 1,234.56"). It also
#: withholds a quoted index level of that shape: on the safe side.
MONEY_FIGURE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+\.\d{2}(?![\d%R])")
#: An amount said in words after its figure ("500 dollars", "850.00 at
#: risk", "1,250 on the line").
MONEY_AFTER = re.compile(
    r"\d\s?(?:dollars?|euros?|bucks)\b"
    r"|\d[\d,.]*\s+(?:at risk|on the line|in loss(?:es)?)\b",
    re.IGNORECASE)
#: An exception's class name, keyed on the suffixes Python and its
#: libraries give them (KeyError, OSError, HTTPError, JSONDecodeError,
#: BudgetRefused, ReadTimeout, StopIteration), dotted or not
#: (requests.exceptions.ConnectionError); the bare "Exception" or "Error"
#: only after a colon or inside a bracket. A word that merely looks like
#: one (PayPal, TradingView, PowerOfThree) is not one.
EXC_NAME = re.compile(
    r"(?<![\w.])(?:[A-Za-z_]\w*\.)*[A-Z]\w*?(?:Error|Exception|Refused"
    r"|Timeout|Warning|Interrupt|Exit|Iteration)\b"
    r"|\bsocket\.timeout\b"
    r"|[:(]\s*(?:Exception|Error)\b")
#: The shortest piece of a stored failure's text a voice may not repeat.
FAILURE_FRAGMENT = 12


def may_name_exception(text) -> bool:
    """True when the text names an exception: a line that names one
    carries its message with it, so it is withheld whole, never cut."""
    return bool(EXC_NAME.search(str(text or "")))


def may_name_money(text, marks=None) -> bool:
    """True when the text may name an amount of money: a currency beside a
    figure, a money word or verb before one, the brief's own amount shape,
    an amount said in words, or one of `marks` (money_marks)."""
    t = str(text or "")
    return bool(CURRENCY.search(t) or MONEY_WORD.search(t)
                or MONEY_VERB.search(t) or MONEY_FIGURE.search(t)
                or MONEY_AFTER.search(t)
                or (marks is not None and marks.search(t)))


def failure_texts(*texts) -> list:
    """The message part of each stored failure ("positioning unread: <e>",
    "thesis check failed: <e>", "structure unread: <e>"): what follows
    the first "unread: " or "failed: ", normalised. Short ones are kept
    out (FAILURE_FRAGMENT)."""
    out = []
    for raw in texts:
        t = " ".join(str(raw or "").split())
        for cut in ("unread: ", "failed: "):
            if cut in t:
                t = t.split(cut, 1)[1]
                break
        else:
            continue
        if len(t) >= FAILURE_FRAGMENT and t not in out:
            out.append(t)
    return out


def quotes_failure(text, failures) -> bool:
    """True when the text repeats any FAILURE_FRAGMENT-character piece of
    one of `failures` (failure_texts), case and spacing aside."""
    t = " ".join(str(text or "").split()).lower()
    if not t:
        return False
    n = FAILURE_FRAGMENT
    for f in failures or ():
        f = " ".join(str(f).split()).lower()
        if any(f[i:i + n] in t for i in range(len(f) - n + 1)):
            return True
    return False


def scrub(text, n: int = LINE_MAX, marks=None, *, withheld: str = WITHHELD,
          withheld_error: str = WITHHELD_ERROR, failures=(),
          keep_lines: bool = False) -> str:
    """A voice's stored words as a page may show them, or the voice's
    words withheld whole: `withheld_error` when they name an exception or
    repeat a stored failure's text (`failures`), `withheld` when they may
    name an amount of money. Nothing is cut out of them, so what shows is
    what the voice wrote. One line, at most `n` characters; `keep_lines`
    keeps the line breaks of a longer answer (the reviewer's reasoning is
    shown pre-wrapped)."""
    raw = str(text or "")
    if keep_lines:
        t = "\n".join(" ".join(line.split()) for line in raw.splitlines()).strip()
    else:
        t = " ".join(raw.split())
    if not t:
        return ""
    if may_name_exception(t) or quotes_failure(t, failures):
        return withheld_error
    if may_name_money(t, marks):
        return withheld
    return t[:n]


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


#: How near a figure must be to a known amount to be read as it: a fill, a
#: rounded cut or a voice's own rounding moves the figure a little.
MARK_TOLERANCE = 0.03
#: A figure as a voice writes it: grouped or not, with decimals or not.
_TOKEN = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?!\d)")
_TOKEN_EXEMPT = re.compile(r"\s?(?:R(?![\w:/])|%)")


class Marks:
    """Known amounts a voice may echo, matched by value, not by spelling:
    every figure in a line is read (grouping commas dropped) and is a hit
    when it lies in one of the spans, widened by MARK_TOLERANCE. A span is
    one amount, or the range a rounded size leaves (money_marks). A whole
    figure counts only from 100 up (a short one is a count as often as an
    amount), and a figure in R or percent never counts. The amounts are
    never printed."""

    def __init__(self, spans):
        self.spans = tuple(sorted(spans))

    def search(self, text):
        t = str(text or "")
        for m in _TOKEN.finditer(t):
            whole, frac = m.group(1), m.group(2)
            v = float(whole.replace(",", "") + (frac or ""))
            if not frac and "," not in whole and v < 100:
                continue
            if _TOKEN_EXEMPT.match(t, m.end()):
                continue
            if any(lo * (1 - MARK_TOLERANCE) <= v <= hi * (1 + MARK_TOLERANCE)
                   for lo, hi in self.spans):
                return m
        return None


def money_marks(amounts):
    """The amounts a voice may echo (Marks), or None when none is known.
    Each amount is a figure or a (low, high) range."""
    spans = set()
    for a in amounts or ():
        if isinstance(a, (tuple, list)) and len(a) == 2:
            lo, hi = _num(a[0]), _num(a[1])
            if lo is None or hi is None:
                continue
            lo, hi = sorted((abs(lo), abs(hi)))
        else:
            lo = hi = _num(a)
            if lo is None:
                continue
            lo = hi = abs(lo)
        if hi:
            spans.add((lo, hi))
    return Marks(spans) if spans else None


def size_step(qty) -> float:
    """The widest rounding step a size written as `qty` may have been
    rounded to: every engine rounds to a power of ten (bot_program/
    asset_engine: six, eight or four decimals, a whole unit, a hundred
    units), so 1.65 was rounded to at most 0.01, 1.6 to at most 0.1, a
    whole size to one unit, and a whole size of thousands to a hundred."""
    v = _num(qty)
    if not v:
        return 0.0
    v = abs(v)
    text = f"{v:.8f}".rstrip("0")
    places = len(text.split(".", 1)[1]) if "." in text else 0
    if places:
        return 10.0 ** -places
    return 100.0 if v >= 1000 and v % 100 == 0 else 1.0


# ── the trade debate's `why` ─────────────────────────────────────────────
#
# Written by ai_agents/agents/trade_debate.py debate_candidate (and by the
# demo branch before it, bot_program/asset_engine/base.py) and recorded on
# the row as metadata["debate"]["why"]. It can carry an exception's text
# ("debate unavailable (OperationalError: ...)") and an amount of money
# (the AI budget's refusal, ai_agents/spend.py can_spend, is in dollars),
# so it is said by cause and never forwarded.

DEBATE_NOT_ARGUED = "Not argued: {cause}"
DEBATE_IN_PART = "Not argued in full: {causes}"
DEBATE_UNSAID = "Not argued in full"
DEBATE_CAUSES = {
    "switch_off": "the debate's switch was off",
    "held": "an earlier binding refusal still held",
    "budget": "today's AI budget refused it",
    "failed": "the debate failed before either side was asked",
    "rehearsal": "the venue's demo world is a rehearsal and is never argued",
}
DEBATE_SIDE_CAUSES = {
    "timeout": "the {side} did not answer in time",
    "budget": "today's AI budget refused the {side}",
    "failed": "the {side}'s call failed",
}
DEBATE_SIDES = {"executioner": "Executioner", "champion": "Champion"}
#: "<side> unavailable (<timeout or an exception's class name>)", joined
#: by "; " (trade_debate.debate_candidate, the deadline loop).
_DEBATE_SIDE = re.compile(r"\b(executioner|champion) unavailable \(([^()]*)\)")


def debate_why_cause(why) -> str:
    """The cause key of a debate's `why` (DEBATE_CAUSES), "sides" when one
    or both sides were silent, "" for an empty `why`, "unknown" else."""
    t = " ".join(str(why or "").split())
    if not t:
        return ""
    if t.startswith("AI budget"):
        return "budget"
    if t.startswith("debate unavailable"):
        return "failed"
    if t.startswith("refused at "):
        return "held"
    if t.endswith(" is OFF"):
        return "switch_off"
    if "demo world" in t:
        return "rehearsal"
    if _DEBATE_SIDE.search(t):
        return "sides"
    return "unknown"


def debate_why_words(why) -> str:
    """Why the debate did not run (in full), in the platform's words; ""
    for an empty `why`. Nothing of the stored text is forwarded."""
    cause = debate_why_cause(why)
    if not cause:
        return ""
    if cause in DEBATE_CAUSES:
        return DEBATE_NOT_ARGUED.format(cause=DEBATE_CAUSES[cause])
    if cause == "sides":
        parts = []
        for side, name in _DEBATE_SIDE.findall(" ".join(str(why).split())):
            key = ("timeout" if name == "timeout"
                   else "budget" if name == "BudgetRefused" else "failed")
            words = DEBATE_SIDE_CAUSES[key].format(side=DEBATE_SIDES[side])
            if words not in parts:
                parts.append(words)
        return DEBATE_IN_PART.format(causes="; ".join(parts))
    return DEBATE_UNSAID


# ── a stop move the venue did not take ───────────────────────────────────
#
# The care's refusal note (bot_program/position_care.py _mirror_to_venue)
# is its own "not sent" sentence, or the engine mover's last error
# (bot_program/asset_engine/base.py _move_broker_stop: "<handle>: <the
# venue's answer or an exception's text>"), or an exception's text; the
# inert stamp's detail is the same mover's notes. Said by cause.

VENUE_CAUSES = {
    "wrong_side": "not sent, the level is not on the right side of the mark",
    "timeout": "the venue did not answer in time",
    "unreachable": "the venue could not be reached",
    "no_leg": "no order the row records was found at the venue",
    "other": ("the move failed; the venue's answer is kept in the log, not "
              "shown here"),
}


def venue_cause(text) -> str:
    """The cause key of a stop move's refusal note (VENUE_CAUSES), or ""."""
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    low = t.lower()
    if "not on the right side of the mark" in low:
        return "wrong_side"
    if "walk budget" in low or "timed out" in low or "timeout" in low:
        return "timeout"
    # A transport error's own spelling (requests / urllib3: "Max retries
    # exceeded", "NewConnectionError", "Connection reset", "Failed to
    # resolve").
    if ("max retries" in low or "connection" in low or "resolve" in low
            or "unreachable" in low):
        return "unreachable"
    # "no leg matched", alone or as every handle's answer ("P1: no leg
    # matched; P2: no leg matched").
    parts = [p.split(":", 1)[-1].strip() for p in low.split(";") if p.strip()]
    if parts and all(p == "no leg matched" for p in parts):
        return "no_leg"
    return "other"


def venue_words(text) -> str:
    """A stop move's refusal note in the platform's words; "" for none."""
    cause = venue_cause(text)
    return VENUE_CAUSES[cause] if cause else ""


# ── the thesis check's words ─────────────────────────────────────────────
#
# brain/thesis_check.py writes "Thesis unread: <why>." when it could not
# read, and the why of a structure read that raised is the exception's
# text ("structure unread: <e>"). Its other words are its own sentences of
# levels and R, kept (scrubbed all the same).

THESIS_UNREAD = "Thesis unread."
THESIS_UNREAD_CAUSES = {
    "no usable mark": "Thesis unread: no usable mark.",
    "too few bars for a structure read":
        "Thesis unread: too few bars for a structure read.",
    "no ATR or no mark": "Thesis unread: no ATR or no mark.",
    "structure unread": "Thesis unread: the structure could not be read.",
}


def thesis_words(verdict, words) -> str:
    """The thesis check's stored words as a page may show them."""
    t = " ".join(str(words or "").split())
    if not t:
        return ""
    if str(verdict or "") == "unread" or t.startswith("Thesis unread"):
        body = t[len("Thesis unread"):].lstrip(":").strip().rstrip(".") \
            if t.startswith("Thesis unread") else ""
        if body in THESIS_UNREAD_CAUSES:
            return THESIS_UNREAD_CAUSES[body]
        if body.startswith("structure unread"):
            return THESIS_UNREAD_CAUSES["structure unread"]
        return THESIS_UNREAD
    return scrub(t, LINE_MAX)
