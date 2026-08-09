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

    qs = Instrument.objects.filter(is_active=True, asset_class="stock")
    if watchlist_only:
        qs = qs.filter(is_watchlist=True)

    fetched = 0
    for inst in qs[:20]:  # Limit to 20 per run to avoid rate limits
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

    forex_instruments = Instrument.objects.filter(asset_class="forex", is_active=True, is_watchlist=True)
    fetched = 0

    # Alpha Vantage's free tier allows 25 requests A DAY. At the old 120s
    # cadence x 10 pairs this ran ~288x over the cap, so every call after
    # the first few returned a throttle notice and forex quotes silently
    # stopped updating. Budget the day's calls and spend them evenly.
    from market_data.quotes import write_quote

    budget = _daily_budget_remaining("alpha_vantage", limit=AV_DAILY_LIMIT)
    if budget <= 0:
        return {"status": "skipped", "reason": "alpha_vantage daily budget spent",
                "hint": "OANDA practice streaming is free and broker-grade"}

    for inst in forex_instruments[:budget]:
        from_cur = inst.symbol[:3]
        to_cur = inst.symbol[3:]
        rate = fetch_forex_rate(from_cur, to_cur)
        _record_api_call("alpha_vantage")
        if rate and write_quote(inst.symbol, last=rate["rate"],
                                 source="alpha_vantage",
                                 bid=rate.get("bid"), ask=rate.get("ask"),
                                 instrument=inst):
            fetched += 1

    return {"status": "success", "fetched": fetched}


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

    fetched = 0
    for sauron_sym, yf_sym in commodities.items():
        try:
            # Fetch via yfinance using the futures symbol
            import yfinance as yf
            from instruments.models import Instrument
            from market_data.models import LiveQuote
            from decimal import Decimal

            ticker = yf.Ticker(yf_sym)
            info = ticker.info
            price = info.get("regularMarketPrice", info.get("previousClose", 0))

            if price:
                try:
                    inst = Instrument.objects.get(symbol=sauron_sym)
                    LiveQuote.objects.update_or_create(
                        instrument=inst,
                        defaults={
                            "last": Decimal(str(price)),
                            "change_pct": Decimal(str(round(info.get("regularMarketChangePercent", 0), 4))),
                            "volume": int(info.get("volume", 0)),
                            "source": "yfinance",
                        }
                    )
                    fetched += 1
                except Instrument.DoesNotExist:
                    pass
        except Exception as e:
            logger.warning(f"Commodity fetch failed for {sauron_sym}: {e}")

    return {"status": "success", "fetched": fetched}


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
    """Fetch crypto prices from CoinGecko."""
    from market_data.adapters.crypto_adapter import save_crypto_quotes_to_db
    count = save_crypto_quotes_to_db()
    return {"status": "success", "fetched": count}


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
