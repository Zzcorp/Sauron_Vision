"""THE TRUTH CORE OF eTORO'S PRICES (the eToro feed spec, F1; 2026-11-07).

The operator's two orders: Sauron prices like eToro ("same grade"), and
the juggling between price sources is harmless by construction. This
module is the vocabulary every later phase speaks, and in F1 it changes
nothing: no money path calls it, it reads no network, no cache and no
database, and the one money door it holds is shut.

  * THE TYPES (I3). A VenueQuote is one coherent tuple — eToro's bid and
    ask, eToro's own Date, the rate id, the channel it came by, when it
    arrived and when it was last confirmed — and its constructor refuses
    a missing side, a value <= 0, a non-finite or unparsable value, a
    crossed quote and a spread above 10% of the mid (W1). No mid is
    stored. A ReferenceQuote is an outside quote (OANDA, Binance,
    Finnhub, Yahoo): it may label a screen slot or refuse an entry, and
    every money function refuses it by type. A VenuePrice is what the
    money door answers when it is open; a Refusal (falsy) when it is not.
  * THE MONEY DOOR (I7, I14). money_price(instrument, purpose) answers
    Refusal("switch_off") while the feed's money switch for the purpose
    is OFF. FEED_MONEY_SWITCHES is empty in F1 — no switch exists to turn
    ON — so every purpose is refused, record or none, and today's eToro
    wire path decides exactly as before.
  * ONE GRADE (I5, I6). grade() reads the confirmation age (the last
    evidence that a price was still eToro's current one), never Sauron's
    write time: LIVE, RECENT, STALE, CLOSED or NONE, by class (§5.4).
  * AUTHORITY (I1) is a pure function of where the instrument is held,
    routed, ticketed or watched, never of any quote's state; leaving it
    takes AUTHORITY_LEAVE_S of absence.
  * THE SCREEN NEVER SUBSTITUTES (I10). display_quote's main cell is
    eToro's numbers or "awaiting eToro"; an outside quote only ever sits
    in its labelled slot.
  * ONE VENUE-SOURCE RULE (§3.2 item 3, harm 27). is_venue_source() is
    the one answer to "did eToro write this quote?". Three tests answered
    it before F1 and they disagree on names no code writes; the readings
    keep each caller's answer to the letter (tests/feed/
    test_venue_source_one_rule.py runs the old and the new side by side).

Constants are the spec's starting values; each later change is measured
first (M1, M2) and logged.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional

#: The venue whose prices this core carries, and the LiveQuote source its
#: readers write today (the legacy Sync button, the interim quotes beat).
VENUE = "etoro"

# ── grades, channels, flags ───────────────────────────────────────────────

LIVE, RECENT, STALE, CLOSED, NONE = "LIVE", "RECENT", "STALE", "CLOSED", "NONE"
GRADES = (LIVE, RECENT, STALE, CLOSED, NONE)

#: eToro's channels: the stream, the feed's own REST reads, and the
#: engine's rates cache (etoro_rates:r:*), read-only to the feed until F9.
WS, REST, ENGINE = "ws", "rest", "engine"
CHANNELS = (WS, REST, ENGINE)

QUIET = "quiet"                     # print older than EQ[class] while LIVE
UNCONFIRMED_JUMP = "unconfirmed_jump"
SKEW = "skew"                       # eToro's Date ahead of the host clock
BEHIND = "behind"                   # REST showed a newer print than the topic
UNTIMED = "untimed"                 # no eToro Date: display only (W7)

# ── the money door's answers ──────────────────────────────────────────────

SWITCH_OFF = "switch_off"
NOT_LIVE = "not_live"
SESSION = "session"
NO_RECORD = "no_record"
STALE_CONVERSION = "stale_conversion"
REFUSAL_REASONS = (SWITCH_OFF, NOT_LIVE, UNCONFIRMED_JUMP, SESSION, QUIET,
                   NO_RECORD, STALE_CONVERSION)

CLOSING, EXECUTABLE, CONVERSION = "closing", "executable", "conversion"
PURPOSES = (CLOSING, EXECUTABLE, CONVERSION)

#: The feed's money switches by purpose: a key of core.platform_control's
#: LIVE_MONEY_SWITCHES, seeded OFF, one pull request each (F9, F10a,
#: F10b). EMPTY IN F1: no purpose has a switch, so the door is shut.
FEED_MONEY_SWITCHES: dict = {}

# ── thresholds by class (§5.4; starting values until M2) ──────────────────


class ClassThresholds(NamedTuple):
    quiet_s: int        # Q: a topic this quiet pulls the watchdog forward
    live_s: int         # L: LIVE while confirm_age <= L
    stale_s: int        # S: STALE after
    entry_s: int        # E: entries need confirm_age <= E
    entry_quiet_s: int  # EQ: entries refuse once unchanged for longer
    settle_s: int       # entries wait this long after a reopen


THRESHOLDS = {
    "forex": ClassThresholds(10, 15, 60, 2, 60, 300),
    "crypto": ClassThresholds(10, 15, 60, 2, 60, 0),
    "index": ClassThresholds(10, 15, 60, 3, 60, 300),
    "commodity": ClassThresholds(15, 20, 60, 3, 120, 300),
    "stock": ClassThresholds(60, 65, 120, 5, 300, 300),
}
THRESHOLDS["etf"] = THRESHOLDS["stock"]
#: A class with no row takes the strictest of every column: the shortest
#: freshness and the longest settle.
STRICTEST = ClassThresholds(
    *(min(t[i] for t in THRESHOLDS.values()) for i in range(5)),
    max(t.settle_s for t in THRESHOLDS.values()))

#: The REST server-cache bound until M1/M2 measure it (§5.4): a REST
#: confirmation is dated its arrival less C_rest.
C_REST_UNMEASURED_S = 60
#: M1/M2 measured C_rest. UNTIL THEN A REST OR ENGINE RECORD IS NEVER LIVE
#: (2026-11-07, F1): the spec's "C_rest = 60 s, so REST alone never makes
#: a price LIVE" holds for every class but stocks and ETFs, whose L (65 s)
#: is above 60 s — a REST answer would read LIVE for its first 5 s. The
#: guarantee is kept by this rule rather than by the arithmetic.
C_REST_MEASURED = False
#: No feed REST GET more often than max(C_rest, this) per batch (§4.5.6).
REST_FLOOR_S = 30
#: A Date this far ahead of the host clock flags `skew`.
SKEW_TOLERANCE_S = 2
#: A record older than this is gone (the stores' expiry).
RECORD_KEEP_S = 4 * 86400
#: A spread wider than this share of the mid is not a quote (W1).
MAX_SPREAD_FRACTION = Decimal("0.10")

# ── hysteresis (§5.6; no money decision ever waits on it) ─────────────────

TRUST_PUSHES = 2                # distinct priced pushes to trust a topic
TRUST_DWELL_S = 5
REST_FALLBACK_AFTER_S = 3       # REST carries this long after the stream sickens
REST_FALLBACK_HOLD_S = 30       # ...and until the stream is LIVE this long
BADGE_MIN_S = 5                 # a degraded badge stays at least this long
SLOT_SHOW_AFTER_STALE_S = 30    # the outside-quote slot appears...
SLOT_HIDE_AFTER_LIVE_S = 10     # ...and goes
UNWANTED_LEAVE_S = 60           # a topic leaves after this long unwanted
AUTHORITY_EVERY_S = 10
AUTHORITY_LEAVE_S = 60

# ── jumps (§5.3) and references (§5.7) ────────────────────────────────────

JUMP_WINDOW_S = 15 * 60
JUMP_CONFIRM_GAP_S = 0.2        # a second print at least this much later
JUMP_CONFIRM_READS = 2          # or a P0 read, at most this many tries

#: The only outside sources that may ever be a second opinion: real-time
#: streams of the same instrument, written within REFERENCE_MAX_AGE_S.
REFERENCE_SOURCES = ("oanda_stream", "binance_ws", "finnhub_ws")
REFERENCE_MAX_AGE_S = 120

_SIDES = {"BUY": "BUY", "LONG": "BUY", "SELL": "SELL", "SHORT": "SELL"}


class InvalidQuote(ValueError):
    """W1: what eToro sent is not a quote. `reason` names why."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _side(side) -> str:
    s = _SIDES.get(str(side or "").strip().upper())
    if s is None:
        raise ValueError(f"not a side: {side!r}")
    return s


def _parse(value) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InvalidQuote("missing_side")
    if isinstance(value, bool):
        raise InvalidQuote("unparsed", repr(value))
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise InvalidQuote("unparsed", repr(value)) from None
    if not d.is_finite():
        raise InvalidQuote("not_finite", repr(value))
    if d <= 0:
        raise InvalidQuote("not_positive", repr(value))
    return d


def _aware(when, name) -> datetime:
    if not isinstance(when, datetime) or when.tzinfo is None:
        raise InvalidQuote("bad_time", name)
    return when


@dataclass(frozen=True)
class VenueQuote:
    """One eToro quote, whole: never a carried spread, never a stored mid,
    never a foreign conversion (I3). `vt` is eToro's own Date (None for an
    untimed answer, display only); `confirmed_at` the last evidence that
    this was still eToro's current price (default: its arrival)."""
    iid: int                         # eToro's instrument id
    bid: Decimal
    ask: Decimal
    vt: Optional[datetime]
    channel: str
    arrival: datetime
    rate_id: str = ""
    confirmed_at: Optional[datetime] = None

    def __post_init__(self):
        if self.bid is None or self.ask is None:
            raise InvalidQuote("missing_side")
        bid, ask = _parse(self.bid), _parse(self.ask)
        if bid > ask:
            raise InvalidQuote("crossed", f"bid {bid} over ask {ask}")
        mid = (bid + ask) / 2
        if (ask - bid) > MAX_SPREAD_FRACTION * mid:
            raise InvalidQuote("wide_spread")
        if self.channel not in CHANNELS:
            raise InvalidQuote("bad_channel", repr(self.channel))
        arrival = _aware(self.arrival, "arrival")
        if self.vt is not None:
            _aware(self.vt, "vt")
        conf = (arrival if self.confirmed_at is None
                else _aware(self.confirmed_at, "confirmed_at"))
        object.__setattr__(self, "bid", bid)
        object.__setattr__(self, "ask", ask)
        object.__setattr__(self, "rate_id", str(self.rate_id or ""))
        object.__setattr__(self, "confirmed_at", conf)
        object.__setattr__(self, "iid", int(self.iid))

    @property
    def mid(self) -> Decimal:
        """Computed for a compact cell, never stored, never a money price."""
        return (self.bid + self.ask) / 2

    def closing_side(self, position_side):
        """(price, "bid" | "ask"): what eToro values an open position at —
        the bid for a long, the ask for a short."""
        return ((self.bid, "bid") if _side(position_side) == "BUY"
                else (self.ask, "ask"))

    def executable_side(self, order_side):
        """(price, "ask" | "bid"): where an order fills — a BUY at the
        ask, a SELL at the bid."""
        return ((self.ask, "ask") if _side(order_side) == "BUY"
                else (self.bid, "bid"))

    def confirmed(self, at) -> "VenueQuote":
        """This quote confirmed at `at`; a confirmation never moves back."""
        at = _aware(at, "confirmed_at")
        return replace(self, confirmed_at=max(self.confirmed_at, at))


@dataclass(frozen=True)
class ReferenceQuote:
    """An outside quote. Never a money price: every money function refuses
    it by type. `stand_in` is "future" or "cash index" when the quote is
    another instrument than the one eToro trades (public_feed.yf_stand_in),
    "" when it is the same."""
    symbol: str
    source: str
    last: Decimal
    written_at: Optional[datetime]
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    stand_in: str = ""

    @property
    def mid(self) -> Decimal:
        """Mid against mid, each from its own coherent quote (§5.7)."""
        if self.bid is not None and self.ask is not None \
                and self.bid > 0 and self.ask >= self.bid:
            return (Decimal(self.bid) + Decimal(self.ask)) / 2
        return Decimal(self.last)

    def age_s(self, now) -> Optional[float]:
        if self.written_at is None:
            return None
        return max(0.0, (now - self.written_at).total_seconds())

    def qualifies(self, now) -> bool:
        """A second opinion only when the same instrument, a real-time
        stream and written within REFERENCE_MAX_AGE_S. Pollers never."""
        age = self.age_s(now)
        return (not self.stand_in
                and str(self.source or "").lower() in REFERENCE_SOURCES
                and age is not None and age <= REFERENCE_MAX_AGE_S)


@dataclass(frozen=True)
class VenuePrice:
    """What the money door answers when open: eToro's side at LIVE."""
    price: Decimal
    side: str
    vt: Optional[datetime]
    confirmed_at: datetime
    channel: str
    grade: str


@dataclass(frozen=True)
class Refusal:
    """The money door's no. Falsy, so `if money_price(...)` reads right;
    the caller then takes today's eToro wire path, or holds, or refuses."""
    reason: str

    def __post_init__(self):
        if self.reason not in REFUSAL_REASONS:
            raise ValueError(f"not a refusal reason: {self.reason!r}")

    def __bool__(self):
        return False


@dataclass(frozen=True)
class Purpose:
    """What money wants a price for: CLOSING a position (its side),
    EXECUTABLE for an order (its side), or a CONVERSION (a currency)."""
    kind: str
    side: str = ""
    currency: str = ""


def closing(position_side) -> Purpose:
    return Purpose(CLOSING, side=_side(position_side))


def executable(order_side) -> Purpose:
    return Purpose(EXECUTABLE, side=_side(order_side))


def conversion(currency) -> Purpose:
    ccy = str(currency or "").strip().upper()
    if not ccy:
        raise ValueError("a conversion names its currency")
    return Purpose(CONVERSION, currency=ccy)


def money_switch_on(purpose: Purpose) -> bool:
    """The feed's money switch for `purpose`. None exists in F1, so OFF —
    without reading anything."""
    key = FEED_MONEY_SWITCHES.get(purpose.kind)
    if not key:
        return False
    from core.platform_control import is_component_enabled  # F9 onwards
    return bool(is_component_enabled(key))


def money_price(instrument, purpose, *, record=None, now=None):
    """THE ONE DOOR money reads a price through (I7): a VenuePrice — eToro's
    closing or executable side at LIVE — or a Refusal. While the purpose's
    switch is OFF (always, in F1) the answer is Refusal("switch_off") and
    the caller decides on today's eToro wire path. An outside quote is
    refused by type, whatever the switches say."""
    if isinstance(record, ReferenceQuote):
        raise TypeError("an outside quote never prices money (I7, I9)")
    if not isinstance(purpose, Purpose) or purpose.kind not in PURPOSES:
        raise TypeError("money_price takes a Purpose: closing(side), "
                        "executable(side) or conversion(currency)")
    if not money_switch_on(purpose):
        return Refusal(SWITCH_OFF)
    # F9/F10 open this door; until then nothing below is reachable.
    return Refusal(NOT_LIVE)  # pragma: no cover


# ── the one grade function (§5.4) ─────────────────────────────────────────

class Grade(NamedTuple):
    grade: str
    flags: frozenset
    confirm_age_s: Optional[int]
    print_age_s: Optional[int]


def thresholds(asset_class) -> ClassThresholds:
    return THRESHOLDS.get(str(asset_class or "").strip().lower(), STRICTEST)


def _secs(delta) -> int:
    return int(delta.total_seconds())


def grade(record, *, now, asset_class, session_open=True, ws_healthy=True,
          ws_trusted=True, unconfirmed_jump=False, behind=False) -> Grade:
    """How far `record` (a VenueQuote, or None) may be trusted at `now`.

    LIVE: the session is open for the purpose, the quote is timed, not an
    unconfirmed jump, confirmed within L[class], and — for a stream
    record — the connection healthy, the topic trusted and not behind;
    for a REST or engine record, C_rest measured (C_REST_MEASURED).
    RECENT: not LIVE, confirmed within S. STALE: beyond S, kept for display
    up to RECORD_KEEP_S. CLOSED: the session is shut. NONE: no record.
    Print ages are raw (now - eToro's Date, floored at 0); confirmation
    ages are Sauron's clock, so skew never reaches them."""
    if record is None:
        return Grade(NONE, frozenset(), None, None)
    flags = set()
    confirm_age = max(0, _secs(now - record.confirmed_at))
    if confirm_age > RECORD_KEEP_S:
        return Grade(NONE, frozenset(), None, None)
    print_age = None
    if record.vt is None:
        flags.add(UNTIMED)
    else:
        raw = (now - record.vt).total_seconds()
        if raw < -SKEW_TOLERANCE_S:
            flags.add(SKEW)
        print_age = max(0, int(raw))
    if unconfirmed_jump:
        flags.add(UNCONFIRMED_JUMP)
    if behind and record.channel == WS:
        flags.add(BEHIND)
    if not session_open:
        return Grade(CLOSED, frozenset(flags), confirm_age, print_age)
    t = thresholds(asset_class)
    if record.channel == WS:
        channel_ok = ws_healthy and ws_trusted and not behind
    else:
        channel_ok = C_REST_MEASURED
    if (confirm_age <= t.live_s and record.vt is not None
            and not unconfirmed_jump and channel_ok):
        if print_age is not None and print_age > t.entry_quiet_s:
            flags.add(QUIET)
        return Grade(LIVE, frozenset(flags), confirm_age, print_age)
    g = RECENT if confirm_age <= t.stale_s else STALE
    return Grade(g, frozenset(flags), confirm_age, print_age)


def is_jump(last_live, price, asset_class) -> bool:
    """Whether `price` moved past the class's jump bar from the last LIVE
    price (mark_sanity.JUMP_PCT, the engine's own bars). A class never
    judged (options) never jumps."""
    from bot_program.mark_sanity import bar_for
    bar = bar_for(asset_class)
    if not bar or last_live is None or price is None:
        return False
    last, p = Decimal(str(last_live)), Decimal(str(price))
    if last <= 0:
        return False
    return abs(p - last) / last > Decimal(str(bar))


# ── authority (§5.1) ──────────────────────────────────────────────────────

class AuthorityFacts(NamedTuple):
    """Where the instrument is held, routed, ticketed or watched at eToro.
    Nothing about any quote: a source can never flap the authority."""
    verified_id: bool = False       # an exact-spelling eToro id is known
    open_row: bool = False          # an open Sauron row routed to eToro
    broker_position: bool = False   # a position in EtoroAccount's holdings
    enabled_config: bool = False    # an enabled config routing it to eToro
    open_ticket: bool = False       # a TAKE TRADE or CLOSE dialog open
    watchlist: bool = False


class Authority(NamedTuple):
    authority: str                  # "etoro" | "reference"
    why: str
    last_reason_at: Optional[datetime]


_REASONS = ("open_row", "broker_position", "enabled_config", "open_ticket",
            "watchlist")


def authority(facts, *, now, last_reason_at=None) -> Authority:
    """eToro holds the authority for an instrument with a verified id and
    any reason; it keeps it AUTHORITY_LEAVE_S after the last reason went
    (`last_reason_at`, the caller's memory, recomputed every
    AUTHORITY_EVERY_S). Otherwise the authority is "reference": today's
    path."""
    if facts.verified_id:
        for reason in _REASONS:
            if getattr(facts, reason):
                return Authority(VENUE, reason, now)
        if last_reason_at is not None and \
                (now - last_reason_at).total_seconds() < AUTHORITY_LEAVE_S:
            return Authority(VENUE, "leaving", last_reason_at)
        return Authority("reference", "no reason at eToro", last_reason_at)
    return Authority("reference", "no verified eToro id", last_reason_at)


# ── the screen (§5.8 main cell; I10, A1, A4) ──────────────────────────────

def _age_words(seconds) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} days"


def _slot(reference, record, now) -> Optional[dict]:
    if reference is None:
        return None
    if not isinstance(reference, ReferenceQuote):
        raise TypeError("the slot holds a ReferenceQuote")
    age = reference.age_s(now)
    what = {"future": "future, different instrument",
            "cash index": "cash index, different instrument"}.get(
        reference.stand_in, "")
    label = " · ".join(x for x in (
        str(reference.source), what,
        _age_words(age) if age is not None else "") if x)
    gap = None
    if record is not None and record.mid > 0:
        gap = format(abs(reference.mid - record.mid) / record.mid * 100,
                     ".2f")
    return {"source": reference.source, "price": str(reference.last),
            "age_s": None if age is None else int(age), "label": label,
            "gap_pct": gap}


def display_quote(record, *, now, asset_class, session_open=True,
                  reference=None, slot_shown=False) -> dict:
    """The main price cell of an eToro instrument and its outside slot.

    The cell holds eToro's numbers only — bid, ask, the mid for a compact
    cell — labelled with the grade and age, or "awaiting eToro" with no
    price at all. `reference`, an outside quote, appears only in "slot",
    labelled with its source, age and gap, and only when `slot_shown`
    (the hysteresis of §5.6 decides it: after eToro has been STALE for
    SLOT_SHOW_AFTER_STALE_S) and eToro is not LIVE."""
    g = grade(record, now=now, asset_class=asset_class,
              session_open=session_open)
    cell = {"source": VENUE, "channel": None, "bid": None, "ask": None,
            "mid": None, "grade": g.grade, "age_s": g.confirm_age_s,
            "flags": sorted(g.flags), "degraded": g.grade != LIVE,
            "label": "awaiting eToro", "slot": None}
    if record is not None and g.grade != NONE:
        cell.update(channel=record.channel, bid=str(record.bid),
                    ask=str(record.ask), mid=str(record.mid))
        if g.grade == LIVE:
            cell["label"] = "eToro · live"
        elif g.grade == RECENT:
            cell["label"] = f"eToro · {_age_words(g.confirm_age_s)}"
        elif g.grade == STALE:
            cell["label"] = (f"eToro · {_age_words(g.confirm_age_s)} · "
                             f"feed down")
        else:
            at = record.vt or record.confirmed_at
            cell["label"] = f"closed · eToro close {at:%H:%M}"
    if slot_shown and g.grade != LIVE:
        cell["slot"] = _slot(reference, record if g.grade != NONE else None,
                             now)
    return cell


# ── outside quotes (§5.7) ─────────────────────────────────────────────────

def reference_quote(row, *, symbol, stand_in=None) -> Optional[ReferenceQuote]:
    """A LiveQuote-shaped row (source, last, bid, ask, updated_at) as an
    outside quote, or None: no row, no positive price, or a row eToro's
    own reader wrote — eToro's price is never an outside opinion of
    itself. `stand_in` defaults to Yahoo's word for a Yahoo row
    (public_feed.yf_stand_in): the future or the cash index Yahoo quotes
    in place of a CFD; "" for any other source."""
    if row is None:
        return None
    source = str(getattr(row, "source", "") or "")
    if is_venue_source(source):
        return None
    try:
        last = Decimal(str(getattr(row, "last", None)))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not last.is_finite() or last <= 0:
        return None
    if stand_in is None:
        stand_in = ""
        if source.strip().lower() == "yfinance":
            from market_data.public_feed import yf_stand_in
            stand_in = yf_stand_in(symbol) or ""

    def _opt(v):
        try:
            d = Decimal(str(v)) if v is not None else None
        except (InvalidOperation, ValueError, TypeError):
            return None
        return d if d is not None and d.is_finite() and d > 0 else None
    return ReferenceQuote(symbol, source, last,
                          getattr(row, "updated_at", None),
                          bid=_opt(getattr(row, "bid", None)),
                          ask=_opt(getattr(row, "ask", None)),
                          stand_in=stand_in)


# ── the one venue-source rule (§3.2 item 3; F1) ───────────────────────────

#: THE RULE (the spec's): the venue's own name or one of its channels —
#: "etoro", "etoro_ws", "etoro_rest", "etoro-..." — trimmed, in any case.
CHANNEL = "channel"
#: The venue's own name only, any case, untrimmed: the carrier's own write
#: (venue_mark.quote_stand_in, generic over carriers: an OANDA row's
#: "oanda_stream" quote is not "oanda"'s own write).
EXACT = "exact"
#: Anything that begins with the venue's name, any case, untrimmed: mark
#: sanity's second opinion (VENUE_SOURCES, 2026-10-05).
PREFIX = "prefix"
READINGS = (CHANNEL, EXACT, PREFIX)


def is_venue_source(source, venue=VENUE, *, reading=CHANNEL) -> bool:
    """Did `venue`'s own reader write a quote whose source is `source`?

    ONE FUNCTION FOR THE THREE TESTS THAT ANSWERED IT BEFORE F1. They
    agree on every source the code base writes ("etoro" from the legacy
    Sync and the interim quotes beat; every outside feed's name; any
    case). They differ only on names no code writes — "etoro_ws", a padded
    " etoro", "etorox" — and each caller keeps its own answer there by its
    `reading`, so no decision moves (tests/feed/test_venue_source_one_rule
    .py runs the three old tests beside these readings over every such
    name and lists each difference)."""
    if reading not in READINGS:
        raise ValueError(f"not a reading: {reading!r}")
    if not venue:
        return False
    if reading == EXACT:
        # venue_mark.quote_stand_in before F1, to the letter
        return str(source or "").lower() == str(venue).lower()
    if reading == PREFIX:
        # mark_sanity.second_opinion before F1, to the letter
        return str(source or "").lower().startswith(str(venue))
    # portfolio.services._is_etoro_source before F1, to the letter
    s = str(source or "").strip().lower()
    v = str(venue).strip().lower()
    return bool(v) and (s == v or s.startswith((v + "_", v + "-")))
