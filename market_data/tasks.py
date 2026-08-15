"""Celery tasks for market data — REAL implementations."""
import os
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)

# ── daily API budgets ───────────────────────────────────────────────────
# Free tiers are per-day, not per-minute; a per-minute limiter happily
# burns a 25/day allowance before breakfast.
AV_DAILY_LIMIT = int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", "20"))


def _budget_key(provider: str) -> str:
    from django.utils import timezone
    return f"apibudget:{provider}:{timezone.now():%Y%m%d}"


def _daily_budget_remaining(provider: str, *, limit: int) -> int:
    from django.core.cache import cache
    used = cache.get(_budget_key(provider), 0)
    return max(0, limit - int(used))


def _record_api_call(provider: str, n: int = 1) -> None:
    from django.core.cache import cache
    key = _budget_key(provider)
    cache.set(key, int(cache.get(key, 0)) + n, 60 * 60 * 26)



@shared_task(bind=True, max_retries=3)
@guarded_task("scraper_live_quotes")
def fetch_live_quotes(self, watchlist_only=True):
    """Tier 1: Fetch live quotes using yfinance (free, no key needed)."""
    from instruments.models import Instrument
    from core.market_calendar import is_any_market_open
    from market_data.adapters.yfinance_adapter import save_quote_to_db

    if not is_any_market_open():
        return {"status": "skipped", "reason": "markets_closed"}

    from signals.universe import quote_targets

    if watchlist_only:
        # "watchlist_only" now means "the scan universe" — the watchlist plus
        # every enabled bot's symbols. A quote is what the mark and the paper
        # fill path read, so a traded symbol without one is a bot that can
        # decide but never act.
        targets = quote_targets("stock", limit=20)
    else:
        targets = list(Instrument.objects.filter(
            is_active=True, asset_class="stock")[:20])

    fetched = 0
    for inst in targets:
        try:
            result = save_quote_to_db(inst.symbol)
            if result:
                fetched += 1
                # Push WebSocket update
                from dashboard.consumers import push_quote_update
                push_quote_update(inst.symbol, result.last, result.change_pct)
        except Exception as e:
            logger.warning(f"Quote fetch failed for {inst.symbol}: {e}")

    return {"status": "success", "fetched": fetched}


@shared_task
@guarded_task("scraper_forex")
def fetch_forex_quotes():
    """Tier 1: Fetch forex rates via Alpha Vantage."""
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    from market_data.adapters.alpha_vantage import fetch_forex_rate
    from core.market_calendar import is_forex_open

    if not is_forex_open():
        return {"status": "skipped", "reason": "forex_closed"}

    from signals.universe import quote_targets
    fetched = 0

    # Alpha Vantage's free tier allows 25 requests A DAY. At the old 120s
    # cadence x 10 pairs this ran ~288x over the cap, so every call after
    # the first few returned a throttle notice and forex quotes silently
    # stopped updating. Budget the day's calls and spend them evenly.
    from market_data.quotes import write_quote
    from market_data.adapters.alpha_vantage import API_KEY as AV_KEY

    # Without a key, fetch_forex_rate returns None before making a request.
    # The loop below still charged the day's budget for every one of those
    # non-requests, so ~20 no-op calls a day exhausted a quota belonging to a
    # key that does not exist — and the task then reported "budget spent",
    # which reads as "we used our allowance" rather than "we are not
    # configured". Two very different problems wearing the same message.
    if not AV_KEY:
        return {"status": "success", "fetched": 0, "attempted": 0,
                "skipped": "no_api_key",
                "hint": "ALPHA_VANTAGE_API_KEY is not set. OANDA practice "
                        "streaming is free and broker-grade."}

    budget = _daily_budget_remaining("alpha_vantage", limit=AV_DAILY_LIMIT)
    if budget <= 0:
        return {"status": "skipped", "reason": "alpha_vantage daily budget spent",
                "hint": "OANDA practice streaming is free and broker-grade"}

    attempted = 0
    for inst in quote_targets("forex", limit=budget):
        from_cur = inst.symbol[:3]
        to_cur = inst.symbol[3:]
        rate = fetch_forex_rate(from_cur, to_cur)
        # Charge the budget for a request that actually went out. A None here
        # can still mean a spent call (throttled, bad symbol), but it can no
        # longer mean a call that was never attempted.
        _record_api_call("alpha_vantage")
        attempted += 1
        if rate and write_quote(inst.symbol, last=rate["rate"],
                                 source="alpha_vantage",
                                 bid=rate.get("bid"), ask=rate.get("ask"),
                                 instrument=inst):
            fetched += 1

    return {"status": "success", "fetched": fetched, "attempted": attempted}


@shared_task
@guarded_task("scraper_commodities")
def fetch_commodity_quotes():
    """Tier 1: Fetch commodity prices via yfinance."""
    from market_data.adapters.yfinance_adapter import save_quote_to_db

    # yfinance commodity symbols
    commodities = {
        "XAUUSD": "GC=F",    # Gold
        "XAGUSD": "SI=F",    # Silver
        "WTIUSD": "CL=F",    # WTI Oil
        "BRNUSD": "BZ=F",    # Brent
        "NGUSD": "NG=F",     # Natural Gas
        "HGUSD": "HG=F",     # Copper
    }

    # Through write_quote, not straight into LiveQuote. This was the only
    # market poller writing the row directly, which meant it skipped the
    # source-precedence rule that every other feed obeys — and yfinance is the
    # lowest-priority source on the platform because it is fifteen minutes
    # delayed for most listings. A five-minute poll could therefore overwrite
    # a live broker tick on XAUUSD with a stale print, which is precisely the
    # defect market_data/quotes.py was written to stop.
    from market_data.quotes import write_quote

    fetched = attempted = 0
    for sauron_sym, yf_sym in commodities.items():
        try:
            import yfinance as yf

            ticker = yf.Ticker(yf_sym)
            info = ticker.info
            price = info.get("regularMarketPrice", info.get("previousClose", 0))
            if not price:
                continue

            attempted += 1
            if write_quote(sauron_sym, last=price, source="yfinance",
                           change_pct=info.get("regularMarketChangePercent"),
                           volume=info.get("volume")):
                fetched += 1
        except Exception as e:
            logger.warning(f"Commodity fetch failed for {sauron_sym}: {e}")

    return {"status": "success", "fetched": fetched, "attempted": attempted}


@shared_task
@guarded_task("scraper_fred")
def fetch_fred_updates():
    """Tier 4: Fetch latest FRED macro data."""
    from core.constants import FRED_SERIES
    from market_data.adapters.fred_adapter import save_series_to_db

    total = 0
    for series_id in FRED_SERIES:
        try:
            count = save_series_to_db(series_id)
            total += count
        except Exception as e:
            logger.warning(f"FRED fetch failed for {series_id}: {e}")

    return {"status": "success", "observations_saved": total}


@shared_task
@guarded_task("scraper_eod")
def fetch_eod_all_instruments():
    """Tier 5: End-of-day data for all stock instruments via yfinance."""
    from instruments.models import Instrument
    from market_data.adapters.yfinance_adapter import save_history_to_db

    instruments = Instrument.objects.filter(is_active=True, asset_class="stock")
    total = 0

    for inst in instruments:
        try:
            count = save_history_to_db(inst.symbol, period="5d")
            total += count
        except Exception as e:
            logger.warning(f"EOD fetch failed for {inst.symbol}: {e}")

    return {"status": "success", "bars_saved": total}


@shared_task
@guarded_task("scraper_crypto")
def fetch_crypto_quotes():
    """Mark crypto from the venue the orders fill on.

    This used to read CoinGecko's cross-exchange aggregate, which had two
    problems. The smaller one is that a blended price never printed on the
    book you actually trade against, so a stop could be evaluated against a
    level that did not exist at your venue. The larger one, measured: the
    call returned ZERO symbols — CoinGecko's free tier now rate-limits it —
    so `LiveQuote` was never written for any crypto pair at all, and a paper
    crypto bot had no mark price, which means its positions could never
    reach a stop or a target.

    Binance's public ticker is free, keyless, and is the venue. CoinGecko
    stays as a fallback for pairs Binance does not list.
    """
    from instruments.models import Instrument
    from market_data.public_feed import public_feed_for
    from market_data.quotes import write_quote

    feed = public_feed_for("crypto")
    fetched, failed = 0, []
    if feed is not None:
        from market_data.management.commands.backfill_bars import venue_symbol
        for inst in Instrument.objects.filter(asset_class="crypto",
                                              is_active=True):
            try:
                tk = feed.ticker(venue_symbol(inst.symbol)) or {}
                last = float(tk.get("lastPrice", 0) or 0)
            except Exception:
                last = 0
            if last <= 0:
                failed.append(inst.symbol)
                continue
            change = 0.0
            try:
                change = float(tk.get("priceChangePercent", 0) or 0)
            except (TypeError, ValueError):
                pass
            if write_quote(inst.symbol, last=last, source="binance_public",
                            change_pct=change, instrument=inst):
                fetched += 1

    # Anything Binance does not list falls back to the aggregate.
    if failed:
        try:
            from market_data.adapters.crypto_adapter import save_crypto_quotes_to_db
            fetched += save_crypto_quotes_to_db(symbols=failed) or 0
        except Exception as e:
            logger.warning("[crypto quotes] CoinGecko fallback failed: %s", e)

    return {"status": "success", "fetched": fetched,
            "not_on_binance": len(failed)}


@shared_task
@guarded_task("scraper_crypto_news")
def fetch_crypto_news_task():
    """Fetch crypto news from RSS feeds."""
    from market_data.adapters.crypto_news import fetch_crypto_news
    count = fetch_crypto_news()
    return {"status": "success", "articles": count}


@shared_task
def refresh_bot_bars_task():
    """Write 1h/4h OHLCV bars for every symbol an enabled bot trades.

    The rule layer reads 4h bars; without this task nothing produces them,
    every rule returns None, and the bots can only ever HOLD. Bars come
    from each bot's own broker so there is no feed/execution basis.
    """
    from market_data.bot_bars import refresh_bot_bars
    return refresh_bot_bars()
