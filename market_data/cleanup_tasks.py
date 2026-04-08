"""Nightly retention cleanup tasks. Registered in celery beat."""
import logging
import os
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)

# Defaults configurable via env
def _days(env_key: str, default: int) -> int:
    try: return max(1, int(os.environ.get(env_key, default)))
    except Exception: return default

@shared_task
def cleanup_liquidations():
    from market_data.models import LiquidationEvent
    cutoff = timezone.now() - timedelta(days=_days("RETAIN_LIQUIDATIONS_DAYS", 30))
    deleted, _ = LiquidationEvent.objects.filter(timestamp__lt=cutoff).delete()
    log.info("cleanup_liquidations: removed %d rows older than %s", deleted, cutoff)
    return deleted

@shared_task
def cleanup_orderbook():
    from market_data.models import OrderBookSnapshot
    # Keep only the last 2000 per symbol (matches the streamer's opportunistic prune).
    syms = OrderBookSnapshot.objects.values_list("symbol", flat=True).distinct()
    total = 0
    for sym in syms:
        keep = list(OrderBookSnapshot.objects.filter(symbol=sym)
                    .order_by("-timestamp").values_list("id", flat=True)[:2000])
        n, _ = OrderBookSnapshot.objects.filter(symbol=sym).exclude(id__in=keep).delete()
        total += n
    log.info("cleanup_orderbook: removed %d stale snapshots", total)
    return total

@shared_task
def cleanup_funding():
    from market_data.models import FundingRate
    cutoff = timezone.now() - timedelta(days=_days("RETAIN_FUNDING_DAYS", 60))
    deleted, _ = FundingRate.objects.filter(timestamp__lt=cutoff).delete()
    log.info("cleanup_funding: removed %d rows", deleted)
    return deleted

@shared_task
def cleanup_price_data():
    """Prune intraday PriceData older than RETAIN_INTRADAY_DAYS (default 90).
    Daily/weekly bars are preserved regardless."""
    from market_data.models import PriceData
    cutoff = timezone.now() - timedelta(days=_days("RETAIN_INTRADAY_DAYS", 90))
    deleted, _ = PriceData.objects.filter(
        timeframe__in=["1m","5m","15m","1h","4h"],
        timestamp__lt=cutoff).delete()
    log.info("cleanup_price_data: removed %d intraday bars", deleted)
    return deleted

@shared_task
def nightly_cleanup_all():
    """One-shot wrapper run from beat."""
    return {
        "liquidations": cleanup_liquidations(),
        "orderbook":    cleanup_orderbook(),
        "funding":      cleanup_funding(),
        "price_data":   cleanup_price_data(),
    }
