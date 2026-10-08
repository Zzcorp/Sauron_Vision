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

A display and valuation change only: no engine decision (stops, care,
sizing, mark sanity) reads metadata["venue_mark"].
"""
import logging
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
#: venue's own price at any age within STALE_MAX_AGE_S.
BOOK_STALE_MAX_S = 3600

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


def at_fill(price, *, source="", now=None, bid=None, ask=None) -> Optional[dict]:
    """The metadata["venue_mark"] value for a REAL row booked at a venue
    fill — written WITH the row (both lanes put it in the create's
    metadata), so the row is never seen without it. None for a price that
    is not one. The caller decides it is a venue print: eToro's avgPrice,
    or, with none, the venue's own ticker read moments before. `bid` and
    `ask`, when the caller read them, let `resolve` value the row on its
    closing side (a new long reads minus the spread, as eToro shows it)."""
    p = _f(price)
    if p is None or p <= 0:
        return None
    now = now or timezone.now()
    out = {"price": p, "at": now.isoformat(), "source": str(source or ""),
           "via": "fill"}
    out.update(_sides(bid, ask))
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
    that print, when the reader has them (the closing side, `resolve`)."""
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


def bookable(mk, trade, *, now=None) -> bool:
    """May `mk` (a `resolve` answer) BOOK a close of `trade` as realized
    P&L? A fresh venue print or a QUOTE (the venue's own instrument; a
    paper row's venue): yes. A VENUE_STALE print: only while the row's
    market is shut (its last print IS the venue's price) or within
    BOOK_STALE_MAX_S. Anything else: no — the caller books the exit
    unpriced and says so, never an old price passed off as the venue's."""
    if mk is None or mk.price is None:
        return False
    if mk.source in (VENUE, QUOTE):
        return True
    if mk.source != VENUE_STALE:
        return False
    if mk.age_s is not None and mk.age_s <= BOOK_STALE_MAX_S:
        return True
    try:
        from bot_program.engine.paper_trader import paper_market_shut
        return bool(paper_market_shut(getattr(trade, "symbol", ""),
                                      getattr(trade, "asset_class", ""),
                                      now=now))
    except Exception:  # noqa: BLE001 — unknown clock: not bookable
        return False


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
