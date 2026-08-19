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
def cleanup_news_bodies():
    """Blank `raw_content` on SUMMARISED articles past RETAIN_NEWS_RAW_DAYS
    (default 90).

    News was the one high-volume writer with no retention at all, and
    `raw_content` is nearly all of its weight — the full scraped body, kept
    forever for a sentiment score computed on the day it arrived. Stripping
    it keeps the ROW: title, summary, sentiment, affected instruments, and
    the /news/<pk>/ link a notification may still point at.

    Only where a summary exists, and that condition is load-bearing rather
    than tidy. TWO readers fall back to the body: the news analyst uses
    `content_summary or raw_content[:2000]` (ai_agents/tasks.py), and the
    detail page renders the body when it differs from the summary. An
    article with no summary would therefore be left with nothing to read
    and nothing to analyse. With one, the analyst is unaffected and the
    page loses only the full text of an article a quarter old.
    """
    from scraping.models import NewsArticle
    cutoff = timezone.now() - timedelta(days=_days("RETAIN_NEWS_RAW_DAYS", 90))
    stripped = (NewsArticle.objects
                .filter(published_at__lt=cutoff)
                .exclude(raw_content="")
                .exclude(content_summary="")
                .update(raw_content=""))
    log.info("cleanup_news_bodies: stripped %d summarised article bodies "
             "older than %s", stripped, cutoff)
    return stripped


@shared_task
def cleanup_news():
    """Delete articles past RETAIN_NEWS_DAYS (default 365) that nothing
    still points at.

    A notification deep-links to /news/<pk>/, and this platform spent a day
    repairing links that led nowhere — so an article a notification names
    is kept no matter how old it is. Anything else past the window is a row
    nobody can reach: it is off every feed, out of every lookback, and its
    sentiment was consumed the day it landed.
    """
    from alerts.models import Notification
    from scraping.models import NewsArticle

    cutoff = timezone.now() - timedelta(days=_days("RETAIN_NEWS_DAYS", 365))
    stale = NewsArticle.objects.filter(published_at__lt=cutoff)
    if not stale.exists():
        return 0

    # The ids any notification still links to. Parsed from the stored url
    # rather than a join, because the link is free text by design.
    linked = set()
    for url in (Notification.objects
                .filter(url__startswith="/news/")
                .values_list("url", flat=True).distinct()):
        part = url.strip("/").split("/")[-1]
        if part.isdigit():
            linked.add(int(part))

    deleted, _ = stale.exclude(id__in=linked).delete()
    log.info("cleanup_news: removed %d articles older than %s (%d kept for "
             "notifications that still link to them)", deleted, cutoff,
             len(linked))
    return deleted


@shared_task
def nightly_cleanup_all():
    """One-shot wrapper run from beat."""
    return {
        "liquidations": cleanup_liquidations(),
        "orderbook":    cleanup_orderbook(),
        "funding":      cleanup_funding(),
        "price_data":   cleanup_price_data(),
        "news_bodies":  cleanup_news_bodies(),
        "news":         cleanup_news(),
    }
