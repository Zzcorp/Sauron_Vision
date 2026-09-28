"""Paper trading engine — simulates fills without real orders."""
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)

#: THE PAPER VENUE KEEPS ITS MARKETS' HOURS (2026-09-26). On Saturday
#: 2026-09-26 13:53:54 UTC the CLOSE button booked two paper forex rows —
#: #108 EURCAD and #109 GBPCAD — at Friday's last OANDA price: the stream
#: had re-written it under a fresh timestamp on a reconnect, so the quote
#: read younger than MAX_QUOTE_AGE_SECONDS, and nothing on the paper path
#: asked whether the market was open. While an instrument's market is shut
#: (core.exchange_status.market_clock) the paper venue fills nothing and
#: exits nothing: ticker reports no price, market_order refuses, and every
#: paper booking site asks paper_market_shut first. LIVE rows never pass
#: through here — the venue decides whether it fills. Read at call time;
#: tests/__init__.py turns it off for a suite whose paper trades run at
#: whatever hour the wall clock says, and tests/test_paper_market_hours.py
#: turns it back on at a fixed clock.
MARKET_HOURS_GATE = True

#: THE FIRST QUARTER HOUR AFTER AN OPEN IS NOT A PAPER PRICE YET
#: (2026-09-26). A poller writes whatever its source still shows on its
#: first run after an open: the 10-minute forex poll and the 5-minute
#: commodity poll re-stamp the last pre-shut price under a fresh
#: timestamp, and yfinance runs 15 minutes behind on most US listings, so
#: at 13:31 UTC its "price" is the previous close. For this long after an
#: open the paper venue fills and exits nothing (the refusal names the
#: minute it resumes); after it, a LiveQuote counts only when it was
#: WRITTEN after the window, and a bar only when it ENDS after the open.
REOPEN_SETTLE_SECONDS = 900
#: A paper exit that would book the ENTRY price because nothing prices the
#: position (the time stop's dead-feed rule, the kill switch's flatten)
#: waits this long after its market opened for the new session's first
#: price: in those hours "nothing priced it" means the first price has not
#: arrived yet, not that the feed is dead. Past it the dead-feed rule
#: stands, so a position nothing will ever price still ends.
REOPEN_PRICE_GRACE_SECONDS = 6 * 3600

_CLASS_WORDS = {"etf": "ETF"}


class PaperMarketShut(RuntimeError):
    """PaperTrader.market_order while the instrument's market is shut:
    nothing filled, nothing to book."""


def _class_words(asset_class) -> str:
    cls = str(asset_class or "").strip().lower()
    return _CLASS_WORDS.get(cls, cls)


def _paper_clock(asset_class, exchange="", symbol="", now=None):
    """(words, opened). `words` is "" while a paper fill or exit may go
    ahead; otherwise the clause every paper refusal carries — "the forex
    market is shut (reopens Sunday 21:00 UTC)", or the settling window's
    after an open. `opened` is the aware UTC instant the running session
    opened: None while shut, for crypto and unmodelled classes, with the
    gate off, or when the clock cannot be read."""
    if not MARKET_HOURS_GATE:
        return "", None
    now = now or timezone.now()
    try:
        from core.exchange_status import market_clock, utc_words
        clock = market_clock(asset_class or "", exchange or "",
                             symbol=symbol or "", now_utc=now)
    except Exception as e:  # noqa: BLE001 — an unreadable clock refuses nothing
        logger.warning("[PAPER] market clock unreadable for %s: %s",
                       symbol, e)
        return "", None
    cls = _class_words(asset_class)
    if not clock.get("is_open", True):
        words = f"the {cls} market is shut"
        if clock.get("reopens_words"):
            words += f" (reopens {clock['reopens_words']})"
        return words, None
    opened = clock.get("opened")
    if opened is not None:
        settled = opened + timedelta(seconds=REOPEN_SETTLE_SECONDS)
        if now < settled:
            return (f"the {cls} market reopened at {utc_words(opened)} and "
                    f"its first quotes may still carry the price from "
                    f"before it shut (paper fills resume "
                    f"{utc_words(settled)})", opened)
    return "", opened


def market_shut_words(asset_class, exchange="", symbol="", now=None) -> str:
    """"" while a paper fill or exit may go ahead (or the gate is off, or the
    clock cannot be read); otherwise the clause every paper refusal carries:
    "the forex market is shut (reopens Sunday 21:00 UTC)" — or, for the
    first REOPEN_SETTLE_SECONDS after an open, the settling window's."""
    return _paper_clock(asset_class, exchange, symbol, now=now)[0]


def _instrument_key(symbol, asset_class=""):
    """(class, exchange) of `symbol`'s INSTRUMENT row — the router's own
    key; `asset_class` (the trade's or the config's) only when no
    Instrument row exists."""
    cls, exchange = asset_class or "", ""
    try:
        from instruments.models import Instrument
        row = (Instrument.objects.filter(symbol=symbol)
               .values_list("asset_class", "exchange").first())
        if row:
            cls, exchange = (row[0] or cls), (row[1] or "")
    except Exception as e:  # noqa: BLE001
        logger.warning("[PAPER] instrument read failed for %s: %s",
                       symbol, e)
    return cls, exchange


def paper_market_shut(symbol, asset_class="", now=None) -> str:
    """market_shut_words for `symbol`, keyed on its INSTRUMENT's class and
    venue — the router's own key; `asset_class` (the trade's or the
    config's) only when no Instrument row exists. Every paper booking site
    asks this before it fills or exits: "" means go on."""
    if not MARKET_HOURS_GATE:
        return ""
    cls, exchange = _instrument_key(symbol, asset_class)
    return market_shut_words(cls, exchange, symbol, now=now)


def paper_awaits_first_price(symbol, asset_class="", now=None) -> str:
    """Asked ONLY by a paper exit that has no price and would otherwise
    book the ENTRY price — the time stop's dead-feed fallback, the kill
    switch's flatten. "" when that fallback may go ahead; otherwise why the
    exit waits: the market is shut or settling, or it opened less than
    REOPEN_PRICE_GRACE_SECONDS ago and nothing has priced `symbol` since,
    which means the new session's first price has not arrived — not a
    dead feed. A time stop that fell due over the weekend otherwise books
    the entry price on the first tick after the reopen, before any price
    of the new week exists (2026-09-26)."""
    if not MARKET_HOURS_GATE:
        return ""
    now = now or timezone.now()
    cls, exchange = _instrument_key(symbol, asset_class)
    words, opened = _paper_clock(cls, exchange, symbol, now=now)
    if words:
        return words
    if opened is None:
        return ""
    until = opened + timedelta(seconds=REOPEN_PRICE_GRACE_SECONDS)
    if now >= until:
        return ""
    from core.exchange_status import utc_words
    return (f"the {_class_words(cls)} market reopened at "
            f"{utc_words(opened)} and nothing has priced {symbol} since — "
            f"the exit waits for the new session's first price (until "
            f"{utc_words(until)}; after that the entry price stands in, as "
            f"for a dead feed)")


class PaperTrader:
    """Simulates order execution with realistic fills."""

    # A quote older than this is not a market price any more. Paper fills
    # and paper SL/TP marks read LiveQuote, which several pollers can leave
    # frozen (a dead streamer, a rate-limited adapter); marking against a
    # fossil silently fabricates P&L and corrupts grading.
    MAX_QUOTE_AGE_SECONDS = 900
    # Bars arrive every 10 min from the bot bar feed; a 1h/4h bar up to 6h
    # old is still a real traded price, unlike a frozen tick.
    MAX_BAR_AGE_SECONDS = 6 * 3600

    def __init__(self, config):
        self.config = config
        self.slippage_bps = 5  # basis points

    def ping(self):
        """Always reachable in paper mode."""
        return True

    def market_order(self, symbol, side, quantity, current_price=None, **kwargs):
        """Simulate a market order fill — never while the instrument's
        market is shut: that raises PaperMarketShut and nothing fills."""
        from bot_program.models import BotTrade

        shut = paper_market_shut(symbol)
        if shut:
            logger.warning("[PAPER] %s %s %s refused: %s — no paper fill",
                           side, quantity, symbol, shut)
            raise PaperMarketShut(f"{symbol}: {shut} — no paper fill")

        if current_price is None:
            # Try to get latest price from market data
            try:
                from market_data.models import LiveQuote
                from instruments.models import Instrument
                instrument = Instrument.objects.filter(symbol=symbol).first()
                if instrument:
                    lq = LiveQuote.objects.get(instrument=instrument)
                    current_price = Decimal(str(lq.last))
                else:
                    current_price = Decimal("0")
            except Exception:
                current_price = Decimal("0")

        current_price = Decimal(str(current_price))

        # Apply slippage
        slip = Decimal(str(self.slippage_bps)) / Decimal("10000")
        if side == "BUY":
            fill_price = current_price * (1 + slip)
        else:
            fill_price = current_price * (1 - slip)

        order_id = f"PAPER-{uuid.uuid4().hex[:12]}"

        logger.info(
            "[PAPER] %s %s %s @ %.8f (slip from %s)",
            side, quantity, symbol, fill_price, current_price,
        )

        return {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "executedQty": str(quantity),
            "avgPrice": str(fill_price),
            "status": "FILLED",
            "paper": True,
        }

    def ticker(self, symbol, *, market_hours=True):
        """Return a simulated ticker using the latest live quote.

        A quote older than MAX_QUOTE_AGE_SECONDS is reported as 0 — callers
        already treat 0 as "no price" and skip, which is the safe outcome.
        Returning the fossil instead would let SL/TP fire on a price that no
        longer exists.

        While the instrument's market is shut the answer is no price at all,
        with "market_shut" and the reason (2026-09-26): a shut market's only
        price is the last one before it shut, whatever its timestamp says —
        OANDA's reconnect snapshot re-stamped Friday's close on a Saturday.
        The same answer for the first REOPEN_SETTLE_SECONDS after an open;
        after that a LiveQuote counts only when it was WRITTEN after the
        window, and a bar only when it ENDS after the open.

        market_hours=False is for READ-ONLY callers (brain/position_review
        marks every position, LIVE ones included): the quote and the bar
        are read exactly as before, with no clock. Nothing that books a
        fill or an exit may pass it.
        """
        try:
            from django.utils import timezone
            from market_data.models import LiveQuote
            from instruments.models import Instrument
            instrument = Instrument.objects.filter(symbol=symbol).first()
            if instrument:
                opened = None
                if market_hours:
                    shut, opened = _paper_clock(instrument.asset_class,
                                                instrument.exchange, symbol)
                    if shut:
                        logger.info("[PAPER] %s: %s — no price", symbol, shut)
                        return {"lastPrice": "0", "symbol": symbol,
                                "market_shut": True, "reason": shut}
                settled = (None if opened is None else
                           opened + timedelta(seconds=REOPEN_SETTLE_SECONDS))
                lq = LiveQuote.objects.filter(instrument=instrument).first()
                if lq is not None:
                    age = (timezone.now() - lq.updated_at).total_seconds()
                    if age <= self.MAX_QUOTE_AGE_SECONDS and (
                            settled is None or lq.updated_at >= settled):
                        return {"lastPrice": str(lq.last), "symbol": symbol}
                    if age <= self.MAX_QUOTE_AGE_SECONDS:
                        # Written inside the settling window after the open:
                        # possibly the pre-shut price under a fresh stamp.
                        logger.info(
                            "[PAPER] %s quote was written at %s, inside the "
                            "%ds after the %s open — trying the bar feed",
                            symbol, lq.updated_at, REOPEN_SETTLE_SECONDS,
                            opened)
                    else:
                        logger.info(
                            "[PAPER] %s quote is %.0fs old (max %ds) — trying "
                            "the bar feed before giving up",
                            symbol, age, self.MAX_QUOTE_AGE_SECONDS)
                # Quote missing or stale: fall back to the most recent bar.
                # LiveQuote pollers only cover watchlist instruments, while
                # the bar feed covers exactly the symbols bots trade — so
                # without this a paper bot on a non-watchlist symbol would
                # be permanently priceless.
                bar_price = self._recent_bar_close(instrument, opened=opened)
                if bar_price is not None:
                    return {"lastPrice": str(bar_price), "symbol": symbol,
                            "source": "bars"}
                logger.warning(
                    "[PAPER] no fresh quote or recent bar for %s — reporting "
                    "no price rather than marking against a stale value",
                    symbol)
                return {"lastPrice": "0", "symbol": symbol, "stale": True}
        except Exception:
            pass
        return {"lastPrice": "0", "symbol": symbol}

    #: How long each bar the fallback reads runs, from its timestamp (its
    #: open), so "did it END after the session opened?" can be asked.
    _BAR_SPAN_SECONDS = {"1h": 3600, "4h": 4 * 3600}

    def _recent_bar_close(self, instrument, opened=None):
        """Close of the newest bar within MAX_BAR_AGE_SECONDS, else None.

        With `opened` (the running session's open, from the paper clock), a
        bar that ENDED at or before it is None too (2026-09-26): its close
        is a price from before the market shut — after a daily break or a
        product's gap it can still be under six hours old."""
        from django.utils import timezone
        from market_data.models import PriceData

        cutoff = timezone.now() - timedelta(seconds=self.MAX_BAR_AGE_SECONDS)
        bar = (PriceData.objects
               .filter(instrument=instrument, timeframe__in=("1h", "4h"),
                       timestamp__gte=cutoff)
               .order_by("-timestamp").first())
        if bar is None:
            return None
        if opened is not None:
            span = self._BAR_SPAN_SECONDS.get(bar.timeframe, 3600)
            if bar.timestamp + timedelta(seconds=span) <= opened:
                logger.info("[PAPER] %s newest bar (%s %s) ended before the "
                            "%s open — not a price of this session",
                            instrument.symbol, bar.timeframe, bar.timestamp,
                            opened)
                return None
        return bar.close

    def klines(self, symbol, interval="1h", limit=200):
        """Return historical OHLCV data from local PriceData."""
        try:
            from market_data.models import PriceData
            from instruments.models import Instrument
            instrument = Instrument.objects.filter(symbol=symbol).first()
            if not instrument:
                return []
            rows = PriceData.objects.filter(
                instrument=instrument, timeframe=interval
            ).order_by("-timestamp")[:limit]
            # Return in ascending order matching Binance kline format
            result = []
            for r in reversed(list(rows)):
                result.append([
                    int(r.timestamp.timestamp() * 1000),  # openTime
                    str(r.open), str(r.high), str(r.low), str(r.close),
                    str(r.volume),
                    int(r.timestamp.timestamp() * 1000) + 3600000,  # closeTime
                    "0", 0, "0", "0", "0",
                ])
            return result
        except Exception:
            return []

    def order_book(self, symbol, limit=50):
        """Return a minimal simulated order book."""
        try:
            from market_data.models import LiveQuote
            from instruments.models import Instrument
            instrument = Instrument.objects.filter(symbol=symbol).first()
            if instrument:
                lq = LiveQuote.objects.get(instrument=instrument)
                price = float(lq.last)
                bids = [[str(round(price * (1 - i * 0.0001), 8)), "10"] for i in range(limit)]
                asks = [[str(round(price * (1 + i * 0.0001), 8)), "10"] for i in range(limit)]
                return {"bids": bids, "asks": asks}
        except Exception:
            pass
        return {"bids": [], "asks": []}

    def get_balance(self):
        """Get simulated balance from portfolio."""
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        return float(portfolio.cash_available)

    def get_positions(self):
        """Get open paper positions."""
        from bot_program.models import BotTrade
        return list(BotTrade.objects.filter(
            config=self.config,
            exit_price__isnull=True,
            binance_order_id__startswith="PAPER-",
        ).values("symbol", "side", "qty", "entry_price"))
