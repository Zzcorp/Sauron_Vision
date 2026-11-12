"""ONE PRICE EVERYWHERE (2026-11-12): the rule every screen prints a price by.

The operator, 2026-11-12: "all the prices dont seem to be the same at the
same time at all between the different rendering sources, bottom
headband, the horde (most accurate and recent it seems...)... they need to
be similar alltogether", and a minute later "between charts and numbers
also mostly". Measured on one synthetic fixture (scratchpad
onequote/measure_before.md): one held EURUSD printed 1.08447 on the Horde,
1.0845 on /positions/, 1.08452 on the hero's venue line and 1.08390 on the
headband, the rails, the hero, the quote card, the ticket and the hover
preview — four numbers, four ages, five spellings, at one moment. Every
surface read its own row by its own rule: the headband the instrument's
LiveQuote (whichever feed won it, a Yahoo future's previous close
included), the Horde and /positions/ the row's venue stamp at its closing
side, the hero's venue line the stamp's print.

ONE FUNCTION NOW DECIDES, for an instrument at a moment, the price every
screen shows (`shown`, `shown_many`), and every surface that prints an
instrument's price calls it, through the template tags
(core.templatetags.quote_tags), a context builder or a JSON API. It
returns one `Shown`: the number a compact cell prints, the reading's own
two sides, whose it is and in what words, when it is from, and the state
of its market. The browser keeps the newest of these per symbol
(static/js/sv-venue.js) and paints every cell of a symbol from it in one
frame; `words` below is mirrored there, and one shared case table pins the
two (tests/one_quote_words.json).

THE RULE.

  HELD AT eTORO (the viewer's own open eToro rows, real money or eToro's
  demo world: market data carries no world). The NEWEST of the eToro
  readings Sauron already holds, by Sauron's read time:
    * every open row's venue stamp (bot_program.venue_mark.last: the
      manage tick's read, eToro's latest candle, the fill, the close
      dialog), kept while younger than STALE_MAX_AGE_S;
    * the instrument's LiveQuote row when eToro's own 30-second quote
      read wrote it (market_data.venue_source.is_venue_source, EXACT: the
      one venue-source rule of F1) and it is younger than STALE_MAX_AGE_S.
  A tie goes to the stamp (it says who read it). Every row of a symbol
  shows that ONE reading. The side a compact cell prints is the side eToro
  values the holding at (venue_mark's CLOSING SIDE): every row a BUY, the
  bid; every row a SELL, the ask; both ways, the mid (computed for the
  cell, never stored); a reading without sides (an eToro candle's close
  with no carried spread), its print ("last"). A position's own cell
  prints the same reading at ITS closing side (`closing_side`).
  No eToro reading at all: the LiveQuote row when it is the same
  instrument (resolve's QUOTE branch), labelled with its own source; a
  stand-in (a Yahoo future, a cash index) or nothing: "awaiting eToro",
  the stand-in only in the outside slot (resolve's AWAITING_VENUE).

  ANY OTHER INSTRUMENT. Its one LiveQuote row, as the rank rule
  (market_data.quotes.write_quote) left it, labelled with its source and,
  for a stand-in, what it stands in as. A row Yahoo wrote from its
  PREVIOUS CLOSE (F1's poller_previous_close harm event, at or after the
  row's write) says so, with that close's day, never as a current price.

  THE OUTSIDE SLOT. Beside an eToro price, the instrument's LiveQuote row
  when another feed wrote it (F1's venue_quotes.reference_quote, stand-in
  words included), with its gap to the price shown. The screen never
  substitutes it (I10).

  ONE CLOCK. `at` is when the price is from as Sauron knows it: a stamp's
  `at`, the polled row's write, an outside row's write CLAMPED to the
  start of its own market's shut (a cash index the poller re-stamps
  overnight reads its true age), a previous close's day. The age is
  worked out from `at` where it is printed, never stored, so a payload
  changes only when a value does.

  ONE MARKET CLOCK. "shut" is signals.market_hold.market_state's, the
  clock and the words the signal rail prints ("market shut · opens Sun
  22:00 UTC"). An eToro reading is never "live" before the eToro stream
  (F3): F1 rules that a REST record is never LIVE until C_rest is
  measured. An outside real-time stream (venue_quotes.REFERENCE_SOURCES)
  is "live" within its class's L.

  ONE DAY CHANGE. Only the price's own source's (`change_source ==
  source`); another feed's day change beside a price is a disagreement,
  so it is None and prints a dash.

DISPLAY ONLY. Nothing here writes, opens a network connection or calls a
model, and no money path calls it: entries, sizing, the manage tick, the
marks stops are measured on, closes, the kill switch, bookings, valuation
(venue_mark.resolve) and every P&L figure read exactly what they read
before (tests/test_one_quote_pins.py: no money module names this module).
Three queries answer any number of symbols (the open eToro rows, the
instruments with their LiveQuote rows, the previous-close harm events),
plus one for a previous close's day when one is shown.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

#: How old an eToro reading may be and still be the price shown: the
#: valuation's own bound for a stale stamp (venue_mark.STALE_MAX_AGE_S),
#: four days, the longest routine shut of a market eToro trades.
STALE_MAX_AGE_S = 4 * 86400
#: A previous-close harm event this long before a row's write still names
#: that write (the counter is queued after the write commits).
PREVIOUS_CLOSE_SLACK_S = 5
#: F1's harm event for a poller that wrote Yahoo's previous close as a
#: fresh last (bot_program.feed_harms.POLLER_PREVIOUS_CLOSE; spelled here:
#: only the fence imports the counters, tests/feed/test_feed_harms).
POLLER_PREVIOUS_CLOSE = "poller_previous_close"

#: The carrier whose prices the screens put first.
ETORO = "etoro"
#: auth: held at eToro by the viewer, or anything else.
AUTH_ETORO, AUTH_REFERENCE = ETORO, "reference"

#: The states a price is shown in.
LIVE, DELAYED, SHUT, NONE = "live", "delayed", "shut", "none"
STATES = (LIVE, DELAYED, SHUT, NONE)

#: basis: which reading the price is.
BASIS_POLL = "etoro_poll"
BASIS_QUOTE = "quote"
BASIS_PREVIOUS_CLOSE = "previous_close"
BASIS_STAMP = "stamp:"              # + the stamp's reader ("tick", ...)

#: The sides a cell can name.
SIDES = ("bid", "ask", "mid", "last")

#: Who read a stamp, in the words the hover says (dashboard.views
#: _MARK_VIA_WORDS, the Horde's and /positions/' own), plus the beat.
VIA_WORDS = {"fill": "at the fill", "tick": "read by the manage tick",
             "candle": "from eToro's latest candle",
             "close dialog": "read by the close dialog",
             "poll": "read by the 30-second eToro quote read"}

DASH = "—"

#: The weekday and month from fixed tables: no locale changes the words
#: (the mirror in static/js/sv-venue.js uses the same tables).
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
           "Oct", "Nov", "Dec")


def now() -> datetime:
    """The module's one clock: every Shown of one response is read at one
    instant (tests hold it)."""
    return timezone.now()


def _clock() -> datetime:
    """`now()`, looked up at call time (a test that holds the clock
    patches `now`)."""
    return now()


class _All:
    """`user=ALL`: every user's open eToro rows (the display relay)."""

    def __repr__(self):
        return "ALL"


ALL = _All()


# ── small helpers ─────────────────────────────────────────────────────────

def _dec(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not d.is_finite() or d <= 0:
        return None
    return d


def _ms(at) -> Optional[int]:
    if at is None:
        return None
    try:
        return int(round(at.timestamp() * 1000))
    except (AttributeError, OverflowError, ValueError):
        return None


def _utc(ms) -> Optional[datetime]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=dt_tz.utc)


def closing_side(direction) -> str:
    """The side eToro values an open position at: "bid" for a long (BUY,
    LONG), "ask" for a short (SELL, SHORT); "" for anything else."""
    d = str(direction or "").strip().upper()
    if d in ("BUY", "LONG"):
        return "bid"
    if d in ("SELL", "SHORT"):
        return "ask"
    return ""


def _decimals(value, asset_class, symbol) -> int:
    from core.price_format import price_decimals
    return price_decimals(value, asset_class, symbol)


def _px(value, dp) -> str:
    d = _dec(value)
    if d is None:
        return DASH
    return f"{d:.{dp}f}"


def age_words(seconds) -> str:
    """"40 s", "12 min", "3 h", "2 days": the age the Horde and /positions/
    print (bot_program.venue_mark.age_words), the one age grammar."""
    from bot_program.venue_mark import age_words as _venue_age_words
    return _venue_age_words(seconds)


def when_words(at: datetime, now_at: datetime) -> str:
    """"21:58" on `now_at`'s own UTC day, else "Fri 13 Nov 21:58" (F1's
    venue_quotes._when_words, from fixed tables)."""
    a = at.astimezone(dt_tz.utc)
    n = now_at.astimezone(dt_tz.utc)
    hm = f"{a.hour:02d}:{a.minute:02d}"
    if a.date() == n.date():
        return hm
    return f"{_DAYS[a.weekday()]} {a.day:02d} {_MONTHS[a.month - 1]} {hm}"


def day_words(at: datetime) -> str:
    """"Thu 12 Nov": a session's day (a previous close)."""
    a = at.astimezone(dt_tz.utc)
    return f"{_DAYS[a.weekday()]} {a.day:02d} {_MONTHS[a.month - 1]}"


# ── the one grammar (mirrored in static/js/sv-venue.js) ───────────────────

def _head(payload: dict, side=None) -> str:
    who = str(payload.get("who") or "")
    if payload.get("src") == ETORO:
        s = side or payload.get("side") or ""
        if s in ("bid", "ask", "mid") and (payload.get("b") is None
                                           or payload.get("a") is None):
            s = "last"         # a reading without sides prints its print
        return f"{who} {s}" if s in SIDES else who
    return who


def words(payload: dict, now_ms: int, side=None) -> str:
    """The words beside a price, from its payload (Shown.payload) at
    `now_ms` (epoch milliseconds), for a cell printing `side` (a
    position's closing side) or the payload's own. Pure.

      eToro, delayed     eToro bid · 25 s
      outside, live      OANDA stream · live
      outside, delayed   Yahoo GBPUSD=X · 4 min
      previous close     Yahoo EURUSD=X previous close · Thu 12 Nov
      shut               closed · eToro bid Fri 13 Nov 21:58 · opens Sun 22:00 UTC
      none               awaiting eToro (held) / no price
    """
    p = payload or {}
    state = p.get("state") or NONE
    if state == NONE or p.get("v") is None:
        return "awaiting eToro" if p.get("auth") == AUTH_ETORO else "no price"
    head = _head(p, side)
    at = p.get("at")
    now_at = _utc(now_ms)
    prev = p.get("basis") == BASIS_PREVIOUS_CLOSE
    if state == SHUT:
        shut = p.get("shut") or {}
        if prev:
            core = f"{p.get('who') or ''} previous close"
            if at is not None:
                core += f" {day_words(_utc(at))}"
        else:
            core = head
            if at is not None:
                core += f" {when_words(_utc(at), now_at)}"
        out = f"closed · {core}"
        if shut.get("opens"):
            out += f" · {shut['opens']}"
        return out
    if prev:
        out = f"{p.get('who') or ''} previous close"
        if at is not None:
            out += f" · {day_words(_utc(at))}"
        return out
    if at is None:
        return head
    age = max(0.0, (now_ms - at) / 1000.0)
    ls = p.get("ls")
    if ls is not None and age <= ls:
        return f"{head} · live"
    return f"{head} · {age_words(age)}"


def slot_words(payload: dict, now_ms: int) -> str:
    """The outside quote beside an eToro price: "Yahoo GC=F, the
    front-month future 2671.30 · 3 min · +0.87% vs eToro"."""
    slot = (payload or {}).get("slot") or None
    if not slot:
        return ""
    parts = [f"{slot.get('who') or ''} {slot.get('p') or DASH}".strip()]
    if slot.get("at") is not None:
        parts.append(age_words(max(0.0, (now_ms - slot["at"]) / 1000.0)))
    if slot.get("gap") is not None:
        parts.append(f"{slot['gap']}% vs eToro")
    return " · ".join(parts)


# ── the answer ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Shown:
    """The price every screen prints for one instrument at one moment.

    `price` is what a compact cell prints (at `side`); `bid`/`ask` are the
    chosen reading's own sides (None when it has none); `last` its own
    print. `at` is when the price is from (see the module docstring)."""
    symbol: str
    asset_class: str = ""
    price: Optional[Decimal] = None
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    last: Optional[Decimal] = None
    side: str = ""                 # "bid" | "ask" | "mid" | "last" | ""
    source: str = ""               # "etoro", "yfinance", "oanda_stream", ...
    who: str = ""                  # "eToro", "Yahoo GBPUSD=X", ...
    auth: str = AUTH_REFERENCE     # "etoro" | "reference"
    basis: str = ""
    at: Optional[datetime] = None
    state: str = NONE
    shut: Optional[dict] = None    # {"since", "label", "opens"}
    chg: Optional[Decimal] = None  # the day change, its own source's only
    dp: int = 2
    sides_from: Optional[datetime] = None   # a carried spread's measurement
    slot: Optional[dict] = None    # {"who", "p", "at", "gap", "si"}
    live_s: Optional[int] = None   # an outside stream's L (live while <=)
    via: str = ""                  # who read it: tick, candle, fill, poll
    volume: Optional[int] = None
    family: str = ""               # the source's feed (chart_source.family)

    # ── values ──
    def value(self, side=None) -> Optional[Decimal]:
        """The price at `side` (a position's closing side), or the compact
        cell's own. A side the reading does not carry is its price."""
        if self.price is None:
            return None
        s = side or ""
        if s == "bid" and self.bid is not None:
            return self.bid
        if s == "ask" and self.ask is not None:
            return self.ask
        if s == "mid" and self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        if s == "last" and self.last is not None:
            return self.last
        return self.price

    def text(self, side=None) -> str:
        """The px text of `value(side)`; "—" when there is no price."""
        return _px(self.value(side), self.dp)

    def side_text(self, which) -> str:
        if which == "bid":
            return _px(self.bid, self.dp)
        if which == "ask":
            return _px(self.ask, self.dp)
        if which == "spread":
            if self.bid is None or self.ask is None:
                return DASH
            return f"{self.ask - self.bid:.{self.dp}f}"
        if which == "sides":
            if self.bid is None or self.ask is None:
                return DASH
            return f"{_px(self.bid, self.dp)} / {_px(self.ask, self.dp)}"
        raise ValueError(which)

    def chg_text(self) -> str:
        if self.chg is None or self.price is None:
            return DASH
        return f"{'+' if self.chg >= 0 else ''}{self.chg:.2f}%"

    def at_ms(self) -> Optional[int]:
        return _ms(self.at)

    # ── words ──
    def words(self, now_at=None, side=None) -> str:
        n = now_at or _clock()
        return words(self.payload(), _ms(n), side=side)

    def age_text(self, now_at=None) -> str:
        if self.at is None or self.price is None:
            return ""
        n = now_at or _clock()
        return age_words(max(0.0, (n - self.at).total_seconds()))

    def asof_text(self) -> str:
        """The headband card's "As of": the UTC clock face of `at`."""
        if self.at is None:
            return DASH
        a = self.at.astimezone(dt_tz.utc)
        return f"{a:%H:%M:%S} UTC ·"

    def slot_text(self, now_at=None) -> str:
        n = now_at or _clock()
        return slot_words(self.payload(), _ms(n))

    def title(self, now_at=None, side=None) -> str:
        """The hover: the words, who read it, a carried spread, the
        outside quote beside it."""
        n = now_at or _clock()
        parts = [self.words(n, side=side)]
        via = VIA_WORDS.get(self.via, "")
        if via and self.price is not None:
            parts.append(via)
        if self.sides_from is not None and (side or self.side) in (
                "bid", "ask", "mid"):
            parts.append("its bid and ask from the spread measured "
                         + when_words(self.sides_from, n))
        if self.basis == BASIS_PREVIOUS_CLOSE:
            parts.append("Yahoo's previous close, standing in for a "
                         "market price")
        slot = self.slot_text(n)
        if slot:
            parts.append(f"outside quote: {slot}")
        return "; ".join(p for p in parts if p)

    def field_text(self, field="price", *, side=None, now_at=None) -> str:
        """One cell's text, by its field (the `data-q-f` grammar)."""
        f = field or "price"
        if f == "price":
            return self.text(side)
        if f in ("bid", "ask", "spread", "sides"):
            return self.side_text(f)
        if f == "chg":
            return self.chg_text()
        if f == "who":
            return self.who or DASH
        if f == "words":
            return self.words(now_at, side=side)
        if f == "age":
            return self.age_text(now_at)
        if f == "asof":
            return self.asof_text()
        if f == "slot":
            return self.slot_text(now_at)
        if f == "title":
            return self.title(now_at, side=side)
        raise ValueError(f"not a quote field: {field!r}")

    # ── the browser's value ──
    def payload(self) -> dict:
        """What the browser keeps per symbol (static/js/sv-venue.js): short
        keys, no age (the browser derives it from `at`)."""
        def txt(v):
            return None if v is None else _px(v, self.dp)
        shut = None
        if self.shut:
            shut = {"since": _ms(self.shut.get("since")),
                    "label": self.shut.get("label") or "",
                    "opens": self.shut.get("opens") or ""}
        return {"s": self.symbol, "p": txt(self.price),
                "v": None if self.price is None else float(self.price),
                "l": txt(self.last), "b": txt(self.bid), "a": txt(self.ask),
                "side": self.side, "src": self.source, "fam": self.family,
                "who": self.who, "auth": self.auth, "basis": self.basis,
                "at": _ms(self.at), "state": self.state, "dp": self.dp,
                "cls": self.asset_class,
                "chg": None if self.chg is None else float(self.chg),
                "ls": self.live_s, "shut": shut, "sf": _ms(self.sides_from),
                "slot": self.slot, "via": self.via}

    def as_quote(self):
        """A LiveQuote-shaped view of this answer, for the code that reads
        a quote's attributes (the instrument page's hero, card and
        ticket; chart_source.quote_facts): last, bid, ask, spread,
        change_pct, change_source, volume, updated_at, source."""
        return QuoteView(self)


class QuoteView:
    """LiveQuote's attributes, answered by the rule (Shown.as_quote)."""

    def __init__(self, shown: Shown):
        self.shown = shown
        self.symbol = shown.symbol
        self.last = shown.price
        self.bid = shown.bid
        self.ask = shown.ask
        self.source = shown.source
        self.updated_at = shown.at
        self.volume = shown.volume or 0
        self.change_pct = shown.chg if shown.chg is not None else Decimal("0")
        # the day change is the price's own feed's, or none at all
        self.change_source = shown.source if shown.chg is not None else ""

    @property
    def spread(self):
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def __bool__(self):
        """A quote worth a hero: a price, or a held instrument waiting for
        eToro's (its words and the outside slot are said)."""
        return (self.last is not None or self.shown.auth == AUTH_ETORO
                or bool(self.shown.slot))


# ── the rule ─────────────────────────────────────────────────────────────

def _held_rows(symbols, user):
    """{SYMBOL: [open eToro rows]} for `user` (ALL: every user's; None or
    an anonymous user: nobody's). One query."""
    out: dict = {}
    if user is None:
        return out
    if user is not ALL and not getattr(user, "is_authenticated", False):
        return out
    try:
        from bot_program.models import AssetBotTrade
        qs = AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING"), paper=False,
            metadata__broker=ETORO)
        if symbols is not None:
            qs = qs.filter(symbol__in=list(symbols))
        if user is not ALL:
            qs = qs.filter(config__user=user)
        for t in qs.only("id", "symbol", "side", "paper", "metadata",
                         "asset_class"):
            out.setdefault((t.symbol or "").upper(), []).append(t)
    except Exception as e:  # noqa: BLE001 — a word beside a price
        logger.info("[one quote] held rows unread: %s", e)
    return out


def held_symbols(user=ALL) -> list:
    """Every symbol `user` (ALL: anyone) holds open at eToro. One query."""
    return sorted(_held_rows(None, user))


def _instruments(symbols) -> dict:
    """{SYMBOL: Instrument with its live_quote joined}. One query."""
    out: dict = {}
    try:
        from instruments.models import Instrument
        wanted = set(symbols) | {s.upper() for s in symbols}
        for inst in (Instrument.objects.filter(symbol__in=list(wanted))
                     .select_related("live_quote")):
            out.setdefault((inst.symbol or "").upper(), inst)
    except Exception as e:  # noqa: BLE001
        logger.info("[one quote] instruments unread: %s", e)
    return out


def _quote_of(inst):
    try:
        return inst.live_quote
    except Exception:  # noqa: BLE001 — no row is no quote
        return None


def _previous_closes(rows: dict) -> dict:
    """{SYMBOL: newest poller_previous_close event time} for the rows a
    poller wrote. One query, none when no row is a poller's."""
    syms = [s for s, q in rows.items()
            if q is not None and str(q.source or "").lower() == "yfinance"]
    if not syms:
        return {}
    try:
        from django.db.models import Max

        from bot_program.feed_harm_models import FeedHarmEvent
        return {r["symbol"].upper(): r["last"] for r in (
            FeedHarmEvent.objects.filter(kind=POLLER_PREVIOUS_CLOSE,
                                         symbol__in=syms)
            .values("symbol").annotate(last=Max("at")))}
    except Exception as e:  # noqa: BLE001
        logger.info("[one quote] previous closes unread: %s", e)
        return {}


def _close_days(inst_ids) -> dict:
    """{instrument id: newest stored daily bar's time}: a previous
    close's session day. One query, only when a previous close is shown."""
    if not inst_ids:
        return {}
    try:
        from django.db.models import Max

        from market_data.models import PriceData
        return {r["instrument_id"]: r["day"] for r in (
            PriceData.objects.filter(instrument_id__in=list(inst_ids),
                                     timeframe="1d")
            .values("instrument_id").annotate(day=Max("timestamp")))}
    except Exception as e:  # noqa: BLE001
        logger.info("[one quote] close days unread: %s", e)
        return {}


class _Clocks:
    """market_state and market_clock, memoised per instrument for one
    answer (both are pure: no query)."""

    def __init__(self, now_at):
        self.now = now_at
        self._state: dict = {}
        self._clock: dict = {}

    def state(self, inst) -> dict:
        key = (getattr(inst, "asset_class", ""), getattr(inst, "exchange", ""),
               getattr(inst, "symbol", ""))
        if key not in self._state:
            try:
                from signals.market_hold import market_state
                self._state[key] = market_state(inst, now=self.now)
            except Exception as e:  # noqa: BLE001 — an unread clock is open
                logger.info("[one quote] market state unread: %s", e)
                self._state[key] = {"state": "unmodelled"}
        return self._state[key]

    def source_closed(self, inst):
        """When the outside source's own market shut, while it is shut
        (core.exchange_status.market_clock: the cash index's venue for an
        index, CME for a commodity's future, the FX week, the listing
        exchange); None while it is open or unmodelled."""
        key = (getattr(inst, "asset_class", ""), getattr(inst, "exchange", ""),
               getattr(inst, "symbol", ""))
        if key not in self._clock:
            try:
                from core.exchange_status import market_clock
                c = market_clock(key[0], key[1], symbol=key[2],
                                 now_utc=self.now)
                self._clock[key] = (None if c.get("is_open", True)
                                    or not c.get("modelled")
                                    else c.get("closed"))
            except Exception as e:  # noqa: BLE001
                logger.info("[one quote] market clock unread: %s", e)
                self._clock[key] = None
        return self._clock[key]

    def shut(self, inst):
        """{"since", "label", "opens"} while the instrument's market is
        shut by the signal rail's clock, else None."""
        st = self.state(inst)
        if st.get("state") != "shut":
            return None
        since = None
        try:
            from core.exchange_status import market_clock
            c = market_clock(getattr(inst, "asset_class", ""),
                             getattr(inst, "exchange", ""),
                             symbol=getattr(inst, "symbol", ""),
                             now_utc=self.now)
            since = c.get("closed")
        except Exception:  # noqa: BLE001
            since = None
        return {"since": since, "label": st.get("label") or "market shut",
                "opens": st.get("opens") or ""}


def _who(tag, inst) -> str:
    """"eToro", "Yahoo GBPUSD=X", "Yahoo GC=F, the front-month future",
    "OANDA stream" (dashboard.chart_source's own words)."""
    try:
        from dashboard import chart_source as cs
        lab = cs.quote_label(tag, inst)
        si = cs.stand_in(cs.family(tag), getattr(inst, "symbol", ""))
        return lab + (f", {cs.STAND_IN_WORDS[si]}" if si else "")
    except Exception:  # noqa: BLE001
        return str(tag or "")


def _family(tag) -> str:
    try:
        from dashboard.chart_source import family
        return family(tag)
    except Exception:  # noqa: BLE001
        return str(tag or "").lower()


def _live_s(source, asset_class) -> Optional[int]:
    """An outside real-time stream's L for the class (F1's thresholds);
    None for every other source: it is never live."""
    from market_data.venue_quotes import REFERENCE_SOURCES, thresholds
    if str(source or "").lower() not in REFERENCE_SOURCES:
        return None
    return thresholds(asset_class).live_s


def _side_for(rows) -> str:
    sides = {closing_side(getattr(t, "side", "")) for t in rows} - {""}
    if sides == {"bid"}:
        return "bid"
    if sides == {"ask"}:
        return "ask"
    if sides:
        return "mid"
    return "last"


def _at_side(price, bid, ask, side) -> Optional[Decimal]:
    if side == "bid" and bid is not None:
        return bid
    if side == "ask" and ask is not None:
        return ask
    if side == "mid" and bid is not None and ask is not None:
        return (bid + ask) / 2
    return price


def _slot(q, inst, shown_price, now_at, clocks) -> Optional[dict]:
    """The outside quote beside an eToro price, or None."""
    if q is None:
        return None
    try:
        from market_data.venue_quotes import reference_quote
        ref = reference_quote(q, symbol=getattr(inst, "symbol", ""))
    except Exception:  # noqa: BLE001
        ref = None
    if ref is None:
        return None
    cls = getattr(inst, "asset_class", "") or ""
    dp = _decimals(ref.last, cls, getattr(inst, "symbol", ""))
    at = _outside_at(ref.written_at, inst, clocks)
    gap = None
    if shown_price is not None and shown_price > 0:
        g = (ref.last / shown_price - 1) * 100
        from dashboard.chart_source import GAP_WORDS_PCT
        if abs(g) >= Decimal(str(GAP_WORDS_PCT)) or ref.stand_in:
            gap = f"{g:+.2f}"
    return {"who": _who(ref.source, inst), "p": _px(ref.last, dp),
            "at": _ms(at), "gap": gap, "si": ref.stand_in or "",
            "src": ref.source}


def _outside_at(written_at, inst, clocks):
    """An outside row's write, clamped to the start of its own market's
    shut: a fossil re-stamped overnight reads its true age."""
    if written_at is None:
        return None
    closed = clocks.source_closed(inst)
    if closed is not None and written_at > closed:
        return closed
    return written_at


def _state_for(inst, at, live_s, clocks, now_at) -> tuple:
    shut = clocks.shut(inst)
    if shut is not None:
        return SHUT, shut
    if live_s is not None and at is not None and \
            (now_at - at).total_seconds() <= live_s:
        return LIVE, None
    return DELAYED, None


def _held(symbol, inst, rows, q, now_at, clocks) -> Shown:
    """THE RULE for an instrument the viewer holds at eToro."""
    from bot_program import venue_mark
    from market_data.venue_source import EXACT, is_venue_source

    cls = (getattr(inst, "asset_class", "") or
           getattr(rows[0], "asset_class", "") or "")
    best = None                     # (at, kind, record)
    for t in rows:
        vm = venue_mark.last(t, now=now_at)
        if vm is None or vm["age_s"] > STALE_MAX_AGE_S:
            continue
        if best is None or vm["at"] > best[0]:
            best = (vm["at"], "stamp", vm)
    polled = None
    if q is not None and is_venue_source(getattr(q, "source", ""), ETORO,
                                         reading=EXACT):
        q_at = getattr(q, "updated_at", None)
        if q_at is not None and _dec(q.last) is not None and \
                (now_at - q_at).total_seconds() <= STALE_MAX_AGE_S:
            polled = (q_at, "poll", q)
    if polled is not None and (best is None or polled[0] > best[0]):
        best = polled
    if best is None:
        return _held_without_etoro(symbol, inst, cls, rows, q, now_at, clocks)
    at, kind, rec = best
    if kind == "stamp":
        last = _dec(rec["price"])
        bid, ask = _dec(rec.get("bid")), _dec(rec.get("ask"))
        sides_from = rec.get("spread_from")
        via = rec.get("via") or ""
        basis = BASIS_STAMP + (via or "mark")
    else:
        last = _dec(rec.last)
        bid, ask = _dec(rec.bid), _dec(rec.ask)
        sides_from = None
        via = "poll"
        basis = BASIS_POLL
    if bid is None or ask is None or bid > ask:
        bid = ask = None
        side = "last"
    else:
        side = _side_for(rows)
        if side == "last":
            side = "bid"           # rows without a side: never in practice
    price = _at_side(last, bid, ask, side)
    state, shut = _state_for(inst, at, None, clocks, now_at)
    chg = None
    if kind == "poll":
        cs = str(getattr(rec, "change_source", "") or "").lower()
        if cs and cs == str(rec.source or "").lower():
            chg = _dec_any(getattr(rec, "change_pct", None))
    slot_q = q if (q is not None and not is_venue_source(
        getattr(q, "source", ""), ETORO, reading=EXACT)) else None
    return Shown(
        symbol=symbol, asset_class=cls, price=price, bid=bid, ask=ask,
        last=last, side=side, source=ETORO, who="eToro", auth=AUTH_ETORO,
        basis=basis, at=at, state=state, shut=shut, chg=chg,
        dp=_decimals(price, cls, symbol), sides_from=sides_from,
        slot=_slot(slot_q, inst, price, now_at, clocks), via=via,
        volume=_volume(q), family=_family(ETORO))


def _dec_any(v) -> Optional[Decimal]:
    """A signed Decimal (a day change), or None."""
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


def _volume(q):
    try:
        v = int(getattr(q, "volume", 0) or 0)
    except (TypeError, ValueError):
        return None
    return v or None


def _held_without_etoro(symbol, inst, cls, rows, q, now_at, clocks) -> Shown:
    """A held instrument with no eToro reading: the same instrument's
    LiveQuote, labelled with its own source; a stand-in or nothing:
    "awaiting eToro", the stand-in in the slot."""
    from bot_program.venue_mark import quote_stand_in
    if q is not None and _dec(q.last) is not None and \
            quote_stand_in(symbol, q, carrier=ETORO) == "" and \
            not getattr(q, "_sv_prev", False):
        out = _outside(symbol, inst, q, now_at, clocks)
        return _replace(out, auth=AUTH_ETORO)
    return Shown(symbol=symbol, asset_class=cls, auth=AUTH_ETORO,
                 state=NONE, source=ETORO, who="eToro",
                 dp=_decimals(getattr(q, "last", None), cls, symbol),
                 slot=_slot(q, inst, None, now_at, clocks),
                 family=_family(ETORO))


def _replace(shown: Shown, **changes) -> Shown:
    from dataclasses import replace
    return replace(shown, **changes)


def _outside(symbol, inst, q, now_at, clocks) -> Shown:
    """THE RULE for any other instrument: its one LiveQuote row."""
    cls = getattr(inst, "asset_class", "") or ""
    if q is None or _dec(q.last) is None:
        return Shown(symbol=symbol, asset_class=cls, state=NONE,
                     dp=_decimals(None, cls, symbol))
    tag = str(q.source or "")
    last = _dec(q.last)
    bid, ask = _dec(q.bid), _dec(q.ask)
    if bid is None or ask is None or bid > ask:
        bid = ask = None
    if getattr(q, "_sv_prev", False):
        at = getattr(q, "_sv_prev_day", None)   # the close's day, or None
        basis = BASIS_PREVIOUS_CLOSE
    else:
        at = _outside_at(getattr(q, "updated_at", None), inst, clocks)
        basis = BASIS_QUOTE
    live_s = _live_s(tag, cls) if basis == BASIS_QUOTE else None
    state, shut = _state_for(inst, at, live_s, clocks, now_at)
    chg = None
    cs = str(getattr(q, "change_source", "") or "").lower()
    if cs and cs == tag.lower():
        chg = _dec_any(getattr(q, "change_pct", None))
    return Shown(
        symbol=symbol, asset_class=cls, price=last, bid=bid, ask=ask,
        last=last, side="", source=tag, who=_who(tag, inst),
        auth=AUTH_REFERENCE, basis=basis, at=at, state=state, shut=shut,
        chg=chg, dp=_decimals(last, cls, symbol), live_s=live_s,
        via="", volume=_volume(q), family=_family(tag))


def shown_many(symbols, *, user=None, now=None) -> dict:
    """{symbol: Shown} for every symbol asked, at one instant (`now`,
    default the module's clock). `user`: the viewer (a User: their open
    eToro rows decide what they hold), ALL (every user's: the display
    relay) or None (nobody holds anything: an anonymous page). Three
    queries for any number of symbols (one more when a previous close's
    day is shown). Never raises: a symbol it cannot answer is "no price"."""
    asked = [str(s or "") for s in symbols if s]
    if not asked:
        return {}
    now_at = now if now is not None else _clock()
    upper = sorted({s.upper() for s in asked})
    return _answer(asked, _held_rows(upper, user), now_at)


def _held_of(rows) -> dict:
    """{SYMBOL: rows} of the open eToro rows among `rows` (the trades a
    caller already read): the same filter as _held_rows, no query."""
    out: dict = {}
    for t in rows or ():
        meta = getattr(t, "metadata", None) or {}
        if getattr(t, "paper", True) or getattr(t, "status", "") not in (
                "OPEN", "CLOSE_PENDING") or meta.get("broker") != ETORO:
            continue
        out.setdefault((getattr(t, "symbol", "") or "").upper(), []).append(t)
    return out


def shown_from(symbols, *, rows=(), quotes=None, instruments=None,
               now=None) -> dict:
    """The rule from what a caller already read (the Horde's book): `rows`
    the viewer's open trades (its eToro real and demo ones are what it
    holds), `quotes` {SYMBOL: LiveQuote} and `instruments` {SYMBOL: an
    object with asset_class, exchange, symbol}; without `quotes`, one read
    of the instruments with their quotes. The previous-close events are
    read only when a poller's row is shown."""
    asked = [str(s or "") for s in symbols if s]
    if not asked:
        return {}
    now_at = now if now is not None else _clock()
    insts = None
    if quotes is not None:
        insts = {k.upper(): v for k, v in (instruments or {}).items()}
        quotes = {k.upper(): v for k, v in quotes.items()}
    return _answer(asked, _held_of(rows), now_at, insts=insts, quotes=quotes)


def _answer(asked, held, now_at, *, insts=None, quotes=None) -> dict:
    """The rule for `asked` given the open eToro rows `held` ({SYMBOL:
    rows}): the instruments with their LiveQuote rows (one query, unless
    the caller hands them) and the previous-close events (one query, none
    without a poller's row)."""
    keys = {s: s.upper() for s in asked}
    upper = sorted(set(keys.values()))
    if quotes is None:
        insts = _instruments(upper)
        quotes = {k: (_quote_of(insts[k]) if k in insts else None)
                  for k in upper}
    else:
        insts = insts or {}
        quotes = {k: quotes.get(k) for k in upper}
    prev = _previous_closes(quotes)
    prev_rows = {}
    for k, q in quotes.items():
        hit = prev.get(k)
        if q is None or hit is None or getattr(q, "updated_at", None) is None:
            continue
        if hit >= q.updated_at - timedelta(seconds=PREVIOUS_CLOSE_SLACK_S):
            prev_rows[k] = q
    days = _close_days([insts[k].id for k in prev_rows if k in insts])
    for k, q in prev_rows.items():
        q._sv_prev = True
        q._sv_prev_day = days.get(insts[k].id) if k in insts else None
    clocks = _Clocks(now_at)
    out = {}
    for s in asked:
        k = keys[s]
        try:
            inst = insts.get(k)
            rows = held.get(k) or []
            if inst is None:
                first = rows[0] if rows else None
                inst = SimpleNamespace(
                    symbol=k, exchange="",
                    asset_class=getattr(first, "asset_class", "") or "")
            if rows:
                out[s] = _held(k, inst, rows, quotes.get(k), now_at, clocks)
            else:
                out[s] = _outside(k, inst, quotes.get(k), now_at, clocks)
        except Exception as e:  # noqa: BLE001 — a cell, never a 500
            logger.warning("[one quote] %s could not be answered: %s", s, e)
            out[s] = Shown(symbol=k)
    return out


def shown_held(*, user=ALL, now=None) -> dict:
    """{symbol: Shown} for every instrument `user` (ALL: anyone) holds open
    at eToro, at one instant: the display relay's read (three queries)."""
    held = _held_rows(None, user)
    if not held:
        return {}
    return _answer(sorted(held), held, now if now is not None else _clock())


def shown(symbol, *, user=None, now=None) -> Shown:
    """The one answer for one symbol (shown_many of one)."""
    return shown_many([symbol], user=user, now=now).get(
        str(symbol or ""), Shown(symbol=str(symbol or "").upper()))


# ── one answer per symbol per response ───────────────────────────────────

class Registry:
    """The answers of one response, at one instant, for one viewer: every
    cell of a symbol on a page prints the same Shown, and the page's JSON
    block (`json_block`) carries exactly what its cells used."""

    def __init__(self, user=None, now_at=None):
        self.user = user
        self.now = now_at or _clock()
        self._got: dict = {}
        self._used: list = []
        self._emitted: set = set()

    def many(self, symbols) -> dict:
        want = [str(s or "") for s in symbols if s]
        missing = [s for s in want if s.upper() not in self._got]
        if missing:
            for s, v in shown_many(missing, user=self.user,
                                   now=self.now).items():
                self._got[s.upper()] = v
        out = {}
        for s in want:
            k = s.upper()
            if k not in self._used:
                self._used.append(k)
            out[s] = self._got.get(k) or Shown(symbol=k)
        return out

    def get(self, symbol) -> Shown:
        return self.many([symbol]).get(str(symbol or ""), Shown(
            symbol=str(symbol or "").upper()))

    def used(self) -> list:
        return list(self._used)

    def payloads(self, symbols=None) -> dict:
        syms = self._used if symbols is None else [s.upper() for s in symbols]
        return {k: self._got[k].payload() for k in syms if k in self._got}

    def json_block(self, *, all_used=False) -> str:
        """`<script type="application/json" data-sv-quotes>` with the
        payloads of the symbols this response used and has not emitted
        yet (all of them with `all_used`), and the server's clock; "" when
        there is nothing to say."""
        syms = [k for k in self._used
                if all_used or k not in self._emitted]
        if not syms:
            return ""
        self._emitted |= set(syms)
        return json_script({"t": _ms(self.now),
                            "q": self.payloads(syms)})


def json_script(data: dict) -> str:
    """The quote block, safe inside HTML: no "<", ">" or "&" survives
    (a symbol's or a feed's words cannot close the script)."""
    body = (json.dumps(data, separators=(",", ":"), sort_keys=True)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))
    return f'<script type="application/json" data-sv-quotes>{body}</script>'


def for_request(request) -> Registry:
    """The response's Registry, memoised on the request: its viewer is the
    signed-in user (an anonymous page holds nothing)."""
    if request is None:
        return Registry(None)
    reg = getattr(request, "_sv_one_quote", None)
    if reg is not None:
        return reg
    user = getattr(request, "user", None)
    viewer = user if (user is not None and
                      getattr(user, "is_authenticated", False)) else None
    reg = Registry(viewer)
    try:
        request._sv_one_quote = reg
    except Exception:  # noqa: BLE001
        pass
    return reg
