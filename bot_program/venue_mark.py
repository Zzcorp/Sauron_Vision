"""THE VENUE MARK (2026-10-05): a real row is valued at its venue's own rate.

The operator bought WTI and silver at eToro and the positions page showed a
gain at the open. The row's entry was eToro's fill (the CFD's rate, off the
order's answer); the page marked it at the platform's own quote — for a
commodity Yahoo's front-month future or the spot, minutes old — and the basis
between the two rendered as P&L. The engine never had the problem: the
manage tick marks a REAL row at the venue's ticker (client_for_symbol ->
eToro's rates), so every stop and every care decision read the venue's
price. Only the pages and the book value read the LiveQuote.

Now the manage tick STAMPS the venue's mark on a real row each time it reads
one (metadata["venue_mark"]: price, at, source — the adapter's key), and
portfolio.services._trade_to_position prefers a stamp younger than MAX_AGE_S
over the LiveQuote for a real row (mark_source "venue"), falling back to the
quote ("quote") when the stamp is stale or absent. A paper row's quote IS its
venue, so it is never stamped. The positions page says which mark it shows.
The same print is not rewritten within REWRITE_AFTER_S. Never raises.

THE BIRTH GAP (2026-10-08). The operator opened Gold Spot at eToro (TAKE
TRADE) and the portfolio read about +18 while eToro read about -0.25: the
new row had no stamp yet (only the manage tick wrote one, up to a beat
later, never for a config nothing ticks), so the page fell back to the
platform's quote — for XAUUSD Yahoo's GC=F, the gold FUTURE, above spot —
and the basis rendered as P&L again. All through here:

  * the fill IS a venue print: both lanes book a real row with its fill
    stamped (`at_fill`), so a new row reads about zero at once;
  * `resolve` is the ONE answer to "what price values this row", read by
    the book (portfolio.services._trade_to_position) and by the two exit
    paths that fell back to the LiveQuote (the reconcile's orphan close,
    the kill switch). A REAL row is never valued against a quote of a
    DIFFERENT instrument (`quote_stand_in`, off public_feed.YF_SYMBOL_MAP):
    with no fresh stamp it is valued at its last stamp, said stale with
    its age, up to STALE_MAX_AGE_S; past that or with none it is not
    valued at all ("awaiting_venue": the cells print an em dash and say
    they wait for the venue's price). Where the quote IS the venue's
    instrument (forex, crypto, stocks) the quote fallback stays;
  * the bar refresh, which already reads the venue's own candles for
    every symbol a live config trades and for every real row no enabled
    live config covers (market_data.bot_bars), stamps the newest candle's
    close on the open real rows of that symbol (`stamp_rows`): no new
    request, and a row nothing ticks is still marked every ten minutes;
  * the close dialog's own venue read stamps the row it priced
    (manual_close.preview_close), so the dialog and the page agree;
  * a stamp never replaces a NEWER one (`stamp(at=...)`).

THE CLOSING SIDE (2026-10-08, review). eToro values an open long at its
bid and a short at its ask; a mark at the last trade or the mid reads half
a spread kinder, a mark at the fill (the opening side) reads exactly zero.
A stamp may carry the venue's bid and ask (`at_fill`, `stamp`), and
`resolve` values a long at the bid and a short at the ask when the stamp
has them, so a new row reads what eToro reads: minus the spread.

BOOKING IS STRICTER THAN SHOWING (2026-10-08, review). A page may show a
stale venue price with its age; a CLOSE booked at one turns that age into
realized P&L. `bookable` is the one rule the two exit paths that fall back
to the platform (the reconcile's orphan close, the kill switch) ask: a
fresh venue print or the venue's own instrument's quote; a stale venue
print only while the market is shut (then it IS the venue's last price)
or within BOOK_STALE_MAX_S. Anything else is an unpriced exit, flagged.

THE RE-CHECK (2026-10-15). Two adversarial re-reads of the rule above:
  * a SHUT market is the venue's own clock (`market_shut`: core
    .exchange_status.market_clock, never the paper venue's settle window,
    which is an OPEN market whose first quotes may still be the close's),
    and a stale print books over it only when it was taken within
    BOOK_BEFORE_SHUT_S of the close (`at_the_close`) — the venue's price
    AT the close, not Friday noon's on a Sunday; that bound is the open
    market's own (BOOK_STALE_MAX_S), so a shut market books exactly what
    the open market accepted a moment before it shut. An index CFD is
    timed by its venue's week (the FX week's edges), never by its cash
    index's session (NYSE for SPX500): eToro's CFD trades through the
    cash market's nights and shuts only for the weekend;
  * a QUOTE books only while fresh (MAX_AGE_S, the bound a venue stamp has
    to meet to be VENUE), or at the close of a shut market like a stale
    print; and a stale quote never hides a bookable venue print
    (`for_booking`: the one call the two exit paths make);
  * a SIDELESS newer print (a candle's close) carries the last MEASURED
    half-spread forward while that measurement is younger than
    SPREAD_CARRY_MAX_S (`stamp`: bid/ask derived, `spread_from` and
    `spread_age_s` recorded), so a long keeps reading at a bid; `fill_sides`
    anchors the venue's spread at the fill for the lanes that book a row at
    one (TAKE TRADE, the bot entry, the working fill — the last with the
    time its spread was read, `at_fill(spread_from=...)`);
  * the readers that DECIDE on a mark (the position review's thesis stop,
    the level editor) take a VENUE_STALE print only when it is the venue's
    price at the close of a market now shut (`at_the_close`, the booking's
    own rule); the pages keep showing it with its age.

A display and valuation change only: no engine decision (stops, care,
sizing, mark sanity) reads metadata["venue_mark"].
"""
import logging
from datetime import timedelta
from typing import NamedTuple, Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

#: A venue mark older than this is not preferred over the platform's quote.
MAX_AGE_S = 900
#: The same price is rewritten no more often than this (the tick's cadence
#: keeps the stamp fresh; a changed price is always written).
REWRITE_AFTER_S = 240
#: How old a venue mark may be and still value a REAL row whose platform
#: quote is a stand-in (said stale, with its age). Four days: the longest
#: routine shut of the instruments this guards is a holiday weekend (the
#: metals and the US index CFDs: Thursday's close to Sunday's reopen, about
#: 73 h), and over a shut market the last venue print IS the venue's price —
#: eToro shows the same close. Past it the stamp is not a shut market's
#: last print but a stamping path that has been broken for days, and a dash
#: says so where a four-day-old price would not.
STALE_MAX_AGE_S = 4 * 86400
#: How old a venue print may be and still BOOK a close (realized P&L) while
#: the market is open: an hour. Over a shut market the last print is the
#: venue's own price when it was taken at the close (BOOK_BEFORE_SHUT_S).
BOOK_STALE_MAX_S = 3600
#: Over a SHUT market a stale print (or a stale quote) books only when it
#: was taken within this long BEFORE the shut began: the venue's price at
#: the close. The open market's own bound, so a shut market never books a
#: print the same market refused a moment before it shut (an hour); a
#: print from Friday noon, or one four days old, is not the close's price
#: however shut the market is now (2026-10-15, re-check).
BOOK_BEFORE_SHUT_S = BOOK_STALE_MAX_S
#: A SIDELESS print (a candle's close, a bare ticker last) carries the
#: half-spread the previous stamp MEASURED forward while that measurement
#: is younger than this, so a long keeps reading at a derived bid instead
#: of snapping to the mid on every bar refresh. Six hours: the same
#: session's spread; past it the print is read as it is (2026-10-15).
SPREAD_CARRY_MAX_S = 6 * 3600

#: What `resolve` answers in `source` (and _trade_to_position copies into
#: UnifiedPosition.mark_source).
VENUE = "venue"                      # a stamp younger than MAX_AGE_S
VENUE_STALE = "venue_stale"          # an older stamp, within STALE_MAX_AGE_S
QUOTE = "quote"                      # the platform's LiveQuote
AWAITING_VENUE = "awaiting_venue"    # a real row whose quote is a stand-in
                                     # and whose venue price is unknown


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _when(s):
    if not s:
        return None
    if hasattr(s, "tzinfo"):
        return s
    try:
        return parse_datetime(str(s))
    except (TypeError, ValueError):
        return None


def _sides(bid, ask) -> dict:
    """{"bid", "ask"} for a stamp — only a usable, uncrossed pair."""
    b, a = _f(bid), _f(ask)
    if b is None or a is None or b <= 0 or a <= 0 or b > a:
        return {}
    return {"bid": b, "ask": a}


def fill_sides(price, side, bid=None, ask=None) -> dict:
    """{"bid", "ask"} anchored AT a fill (2026-10-15): the venue's spread
    (ask - bid, as read a moment before the order) laid against the fill
    price on the side it filled on — a BUY fills at the ask, a SELL at the
    bid — so a new row reads what the venue shows it: a long at the bid,
    minus the spread. {} without a usable pair or price. The one rule the
    three lanes that book a row at a fill share (TAKE TRADE, the bot entry,
    the working fill)."""
    p = _f(price)
    pair = _sides(bid, ask)
    if p is None or p <= 0 or not pair:
        return {}
    spread = pair["ask"] - pair["bid"]
    if str(side or "").upper() == "BUY":
        return {"bid": round(p - spread, 10), "ask": p}
    return {"bid": p, "ask": round(p + spread, 10)}


def _carried_sides(prev, price, at) -> dict:
    """bid/ask for a SIDELESS print at `price`, derived from the half-spread
    the previous stamp carried (its own measured pair, or one it carried in
    turn), while that measurement is younger than SPREAD_CARRY_MAX_S at
    `at`. `spread_from` is when the spread was MEASURED and `spread_age_s`
    its age at this print. {} when there is nothing to carry."""
    pair = _sides((prev or {}).get("bid"), (prev or {}).get("ask"))
    p = _f(price)
    if not pair or p is None or p <= 0:
        return {}
    measured_at = _when(prev.get("spread_from")) or _when(prev.get("at"))
    if measured_at is None:
        return {}
    age = (at - measured_at).total_seconds()
    if age < 0 or age > SPREAD_CARRY_MAX_S:
        return {}
    half = (pair["ask"] - pair["bid"]) / 2.0
    out = _sides(round(p - half, 10), round(p + half, 10))
    if not out:
        return {}
    out["spread_from"] = measured_at.isoformat()
    out["spread_age_s"] = int(round(age))
    return out


def at_fill(price, *, source="", now=None, bid=None, ask=None,
            spread_from=None) -> Optional[dict]:
    """The metadata["venue_mark"] value for a REAL row booked at a venue
    fill — written WITH the row (both lanes put it in the create's
    metadata), so the row is never seen without it. None for a price that
    is not one. The caller decides it is a venue print: eToro's avgPrice,
    or, with none, the venue's own ticker read moments before. `bid` and
    `ask`, when the caller read them, let `resolve` value the row on its
    closing side (a new long reads minus the spread, as eToro shows it).

    `spread_from` (2026-10-15, re-check): when the spread was READ, for a
    fill that lands long after the order (a working entry: up to a day).
    Recorded with its age at the fill, so the carry dates the measurement
    from the read, never from the fill; a read older than
    SPREAD_CARRY_MAX_S at the fill anchors nothing (the row is stamped
    sideless and the next tick measures)."""
    p = _f(price)
    if p is None or p <= 0:
        return None
    now = now or timezone.now()
    out = {"price": p, "at": now.isoformat(), "source": str(source or ""),
           "via": "fill"}
    pair = _sides(bid, ask)
    if pair and spread_from is not None:
        read_at = _when(spread_from)
        try:
            age = (now - read_at).total_seconds()
        except (TypeError, ValueError):
            return out           # an unreadable read time anchors nothing
        if age > SPREAD_CARRY_MAX_S:
            return out
        read_at = min(read_at, now)
        pair["spread_from"] = read_at.isoformat()
        pair["spread_age_s"] = int(round(max(0.0, age)))
    out.update(pair)
    return out


def stamp(trade, price, *, source="", now=None, at=None, via="",
          bid=None, ask=None) -> bool:
    """Write the venue's mark on a REAL row (metadata["venue_mark"]), read
    fresh under a row lock so no other writer's keys are lost. True when
    written. A paper row, a bad price, the same price written within
    REWRITE_AFTER_S, or a stamp NEWER than `at` already on the row:
    nothing. `at` is when the price was the venue's (a candle's close
    time); default now. `via` says who read it ("tick", "candle", "close
    dialog"; "fill" is at_fill's). `bid`/`ask`: the venue's two sides at
    that print, when the reader has them (the closing side, `resolve`). A
    print WITHOUT sides carries the previous stamp's measured half-spread
    forward while it is younger than SPREAD_CARRY_MAX_S (`_carried_sides`),
    so a bar refresh never undoes the bid/ask valuation (2026-10-15)."""
    try:
        if getattr(trade, "paper", True):
            return False
        p = _f(price)
        if p is None or p <= 0:
            return False
        now = now or timezone.now()
        at = _when(at) or now
        if at > now:
            at = now
        from django.db import transaction

        from bot_program.asset_models import AssetBotTrade
        value = {"price": p, "at": at.isoformat(), "source": str(source or "")}
        if via:
            value["via"] = str(via)
        value.update(_sides(bid, ask))
        with transaction.atomic():
            row = AssetBotTrade.objects.select_for_update().get(pk=trade.pk)
            meta = dict(row.metadata or {})
            prev = meta.get("venue_mark") or {}
            prev_at = _when(prev.get("at"))
            if prev_at is not None and prev_at > at:
                # a newer venue print is already on the row
                return False
            if "bid" not in value:
                value.update(_carried_sides(prev, p, at))
            if (_f(prev.get("price")) == p and prev_at is not None
                    and _f(prev.get("bid")) == value.get("bid")
                    and _f(prev.get("ask")) == value.get("ask")
                    and 0 <= (at - prev_at).total_seconds() < REWRITE_AFTER_S):
                return False
            meta["venue_mark"] = value
            row.metadata = meta
            row.save(update_fields=["metadata"])
        trade.metadata = meta
        return True
    except Exception as e:  # noqa: BLE001 — a mark not stamped is the quote
        logger.info("[venue mark] %s #%s not stamped: %s",
                    getattr(trade, "symbol", "?"), getattr(trade, "id", "?"), e)
        return False


def last(trade, *, now=None):
    """The venue's mark on `trade` whatever its age: {price, at, source,
    via, age_s} — or None (absent, unreadable, or a paper row)."""
    try:
        if getattr(trade, "paper", True):
            return None
        vm = (getattr(trade, "metadata", None) or {}).get("venue_mark") or {}
        p = _f(vm.get("price"))
        at = _when(vm.get("at"))
        if p is None or p <= 0 or at is None:
            return None
        now = now or timezone.now()
        age = max(0.0, (now - at).total_seconds())
        out = {"price": p, "at": at, "source": str(vm.get("source") or ""),
               "via": str(vm.get("via") or ""), "age_s": age}
        out.update(_sides(vm.get("bid"), vm.get("ask")))
        if "bid" in out and vm.get("spread_from"):
            # the sides were DERIVED from a spread measured earlier
            out["spread_from"] = _when(vm.get("spread_from"))
            out["spread_age_s"] = _f(vm.get("spread_age_s"))
        return out
    except Exception:  # noqa: BLE001
        return None


def fresh(trade, *, now=None, max_age_s=MAX_AGE_S):
    """The venue's mark on `trade` while it is younger than `max_age_s`:
    {price, at, source, via, age_s} — or None (absent, unreadable, stale,
    or a paper row)."""
    vm = last(trade, now=now)
    if vm is None or vm["age_s"] > max_age_s:
        return None
    return vm


def quote_stand_in(symbol, quote=None, *, carrier="") -> str:
    """Why the platform's quote for `symbol` is NOT the instrument a CFD
    venue trades — "future" or "cash index" (public_feed.yf_stand_in, off
    YF_SYMBOL_MAP, the one record of what Yahoo quotes for each symbol) —
    or "" when it is the same instrument. A quote the row's own venue wrote
    (its source is the carrier's key) is the venue's rate, whatever the
    symbol."""
    try:
        if quote is not None and carrier and \
                str(getattr(quote, "source", "") or "").lower() == \
                str(carrier).lower():
            return ""
        from market_data.public_feed import yf_stand_in
        return yf_stand_in(symbol)
    except Exception:  # noqa: BLE001 — a dict read; kept total
        return ""


class Mark(NamedTuple):
    """What values an open row now, and why. `price` None: nothing does."""
    price: Optional[float]
    source: Optional[str]            # VENUE, VENUE_STALE, QUOTE,
                                     # AWAITING_VENUE or None
    at: object = None                # when the price was read (datetime)
    age_s: Optional[float] = None    # its age at `now`
    via: str = ""                    # the stamp's reader: fill, tick, ...
    stand_in: str = ""               # quote_stand_in for a real row


def closing_side(trade, vm) -> float:
    """The price a venue print values `trade` at: its BID for a long and its
    ASK for a short when the stamp carries them (what eToro shows an open
    row: a new long at minus the spread), else the print's price."""
    side = str(getattr(trade, "side", "") or "").upper()
    if side == "BUY" and vm.get("bid") is not None:
        return vm["bid"]
    if side == "SELL" and vm.get("ask") is not None:
        return vm["ask"]
    return vm["price"]


def resolve(trade, quote, *, now=None) -> Mark:
    """THE one answer to "what price values this OPEN row now" (2026-10-08).

    A PAPER row: its quote (its venue), or nothing. A REAL row:
      1. a venue stamp younger than MAX_AGE_S — VENUE, on the row's
         closing side when the stamp has it (`closing_side`);
      2. else, where the platform quote IS the venue's instrument, exists
         and is not older than the row's last venue print — QUOTE (PR40's
         fallback);
      3. else a stamp younger than STALE_MAX_AGE_S — VENUE_STALE, its age
         said;
      4. else, where the quote is a stand-in (another instrument) —
         AWAITING_VENUE, no price: the basis is never a P&L;
      5. else nothing (no quote, no stamp)."""
    now = now or timezone.now()
    q_last = None
    q_at = None
    if quote is not None:
        q_last = _f(getattr(quote, "last", None))
        if q_last is not None and q_last <= 0:
            q_last = None
        q_at = getattr(quote, "updated_at", None)
    q_age = (max(0.0, (now - q_at).total_seconds())
             if q_last is not None and q_at is not None else None)
    if getattr(trade, "paper", True):
        if q_last is None:
            return Mark(None, None)
        return Mark(q_last, QUOTE, q_at, q_age)
    meta = getattr(trade, "metadata", None) or {}
    stand_in = quote_stand_in(getattr(trade, "symbol", ""), quote,
                              carrier=str(meta.get("broker") or ""))
    vm = last(trade, now=now)
    if vm is not None and vm["age_s"] <= MAX_AGE_S:
        return Mark(closing_side(trade, vm), VENUE, vm["at"], vm["age_s"],
                    vm["via"], stand_in)
    # The venue's own instrument's quote — but never one OLDER than the
    # venue's last print on the row (2026-10-08, review: a dead feed's
    # three-hour-old quote outranked a twenty-minute-old venue print).
    if not stand_in and q_last is not None and (
            vm is None or q_at is None or q_at >= vm["at"]):
        return Mark(q_last, QUOTE, q_at, q_age, "", stand_in)
    if vm is not None and vm["age_s"] <= STALE_MAX_AGE_S:
        return Mark(closing_side(trade, vm), VENUE_STALE, vm["at"],
                    vm["age_s"], vm["via"], stand_in)
    if stand_in:
        return Mark(None, AWAITING_VENUE,
                    vm["at"] if vm else None, vm["age_s"] if vm else None,
                    vm["via"] if vm else "", stand_in)
    return Mark(None, None)


def market_shut(trade, *, now=None):
    """Is the row's market SHUT by the venue's own clock (core
    .exchange_status.market_clock, keyed as the paper venue keys it: the
    instrument's class and venue)? None while it is OPEN — the settle
    window after an open included: that is an open market whose first
    quotes may still carry the close's price, not a shut one — for a clock
    nothing models, and for an unreadable clock. Else {"closed": the aware
    UTC instant the running shut began (None when the clock cannot say),
    "reopens": when it next opens (None when unknowable)}.
    2026-10-15 (re-check): the one clock `bookable` and the deciding
    readers ask; the paper venue's `paper_market_shut` counted the settle
    window as shut and let a four-day-old print book after a weekend.

    AN INDEX CFD keeps its VENUE's week, never its cash index's session:
    the platform times an index by NYSE (SPX500) or its home exchange
    (GER40), while eToro's index CFD trades through the cash market's
    nights and shuts for the weekend. Its week is the FX week's edges
    (core.exchange_status._forex_week: Sunday's open to Friday's close),
    so it reads OPEN through the week and SHUT from Friday's close — a
    Saturday is not an open market, and the readers are not blind for
    it."""
    try:
        symbol = str(getattr(trade, "symbol", "") or "")
        cls = str(getattr(trade, "asset_class", "") or "")
        now = now or timezone.now()
        from bot_program.engine.paper_trader import _instrument_key
        icls, exchange = _instrument_key(symbol, cls)
        if quote_stand_in(symbol) == "cash index" \
                or str(icls or "").lower() == "index":
            from core.exchange_status import _forex_prev_close, _forex_week
            is_open, reopens, _opened = _forex_week(now)
            if is_open:
                return None
            return {"closed": _forex_prev_close(now), "reopens": reopens}
        from core.exchange_status import market_clock
        clock = market_clock(icls, exchange, symbol=symbol, now_utc=now)
        if not clock.get("modelled") or clock.get("is_open", True):
            return None
        return {"closed": clock.get("closed"), "reopens": clock.get("reopens")}
    except Exception as e:  # noqa: BLE001 — an unreadable clock is not shut
        logger.info("[venue mark] %s: market clock unread: %s",
                    getattr(trade, "symbol", "?"), e)
        return None


def bookable(mk, trade, *, now=None) -> bool:
    """May `mk` (a `resolve` answer) BOOK a close of `trade` as realized
    P&L? A fresh venue print: yes. A QUOTE (the venue's own instrument; a
    paper row's venue): while it is as fresh as a venue stamp must be
    (MAX_AGE_S). A VENUE_STALE print: within BOOK_STALE_MAX_S. Either of
    the last two, older: only while the row's market is SHUT by the
    venue's own clock (`market_shut`) AND the print was taken within
    BOOK_BEFORE_SHUT_S before that shut began (`at_the_close`) — then it
    IS the venue's price at the close. Anything else: no — the caller
    books the exit unpriced and says so, never an old price passed off as
    the venue's."""
    if mk is None or mk.price is None:
        return False
    if mk.source == VENUE:
        return True
    if mk.source == QUOTE and mk.age_s is not None and mk.age_s <= MAX_AGE_S:
        return True
    if mk.source == VENUE_STALE and mk.age_s is not None \
            and mk.age_s <= BOOK_STALE_MAX_S:
        return True
    if mk.source not in (QUOTE, VENUE_STALE):
        return False
    return at_the_close(mk, trade, now=now)


def at_the_close(mk, trade, *, now=None) -> bool:
    """Is `mk` the venue's price AT THE CLOSE of a market now shut? True
    only when the row's market is SHUT by the venue's own clock
    (`market_shut`), the clock says when that shut began, and the print
    was taken no earlier than BOOK_BEFORE_SHUT_S before it (a print taken
    after it — the last candle ending at the close — is the close's too).
    The one rule booking (`bookable`) and the readers that DECIDE on a
    mark (the position review, the level editor) share (2026-10-15,
    re-check): a shut market's older print is shown with its age and
    decides nothing — a stop measured on Wednesday's price over a weekend
    is a stop measured on a price days older than the close."""
    if mk is None or mk.price is None or mk.at is None:
        return False
    shut = market_shut(trade, now=now)
    if not shut or shut.get("closed") is None:
        return False
    try:
        return mk.at >= shut["closed"] - timedelta(seconds=BOOK_BEFORE_SHUT_S)
    except TypeError:          # a naive time is not a measured one
        return False


def for_booking(trade, quote, *, now=None) -> Optional[Mark]:
    """The mark a CLOSE of `trade` may be BOOKED at, or None (2026-10-15):
    `resolve`'s answer when `bookable` allows it; else, when that answer
    was the platform's quote and the quote is too old to book, the row's
    own last venue print when THAT is bookable — a stale quote never hides
    a bookable venue print (`resolve` already refuses a quote older than
    the print, so the print here is the older of the two). The one call
    the kill switch and the reconcile's orphan close make."""
    now = now or timezone.now()
    mk = resolve(trade, quote, now=now)
    if bookable(mk, trade, now=now):
        return mk
    if mk.source == QUOTE and not getattr(trade, "paper", True):
        vm = last(trade, now=now)
        if vm is not None and vm["age_s"] <= STALE_MAX_AGE_S:
            alt = Mark(closing_side(trade, vm), VENUE_STALE, vm["at"],
                       vm["age_s"], vm["via"], mk.stand_in)
            if bookable(alt, trade, now=now):
                return alt
    return None


def stamp_rows(symbol, price, *, carrier, at=None, via="candle",
               now=None) -> int:
    """Stamp the venue's price on every OPEN or CLOSE_PENDING REAL row of
    `symbol` that `carrier` holds (metadata["broker"]) — the bar refresh's
    hook (market_data.bot_bars): it already reads the venue's own candles
    for these symbols, so this costs no request. A newer stamp on a row is
    kept (stamp). Returns how many rows were written. Never raises."""
    if not carrier or not symbol:
        return 0
    n = 0
    try:
        from bot_program.asset_models import AssetBotTrade
        rows = AssetBotTrade.objects.filter(
            symbol=symbol, paper=False,
            status__in=("OPEN", "CLOSE_PENDING"),
            metadata__broker=carrier)
        for t in rows:
            if stamp(t, price, source=carrier, now=now, at=at, via=via):
                n += 1
    except Exception as e:  # noqa: BLE001
        logger.info("[venue mark] %s rows not stamped from %s: %s",
                    symbol, via, e)
    return n


def age_words(age_s) -> str:
    """"40 s", "12 min", "3 h", "2 days" — the age a page prints beside a
    stale venue mark."""
    a = _f(age_s)
    if a is None:
        return ""
    if a < 90:
        return f"{int(a)} s"
    if a < 90 * 60:
        return f"{int(round(a / 60))} min"
    if a < 48 * 3600:
        return f"{int(round(a / 3600))} h"
    return f"{int(round(a / 86400))} days"
