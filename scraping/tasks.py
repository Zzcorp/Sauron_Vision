"""Celery tasks for web scraping — REAL implementations."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("scraper_news")
def fetch_breaking_news():
    # After AI processes news, notify on critical items:
    # from alerts.notify import notify_critical_news
    # for article in critical_articles:
    #     notify_critical_news(article)
    """Tier 1: Fetch news from RSS feeds and APIs."""
    from scraping.scrapers.news_aggregator import fetch_rss_news, fetch_marketaux_news

    rss_count = fetch_rss_news(max_per_feed=5)
    api_count = fetch_marketaux_news(limit=20)

    # Push WebSocket notification for new news
    if rss_count + api_count > 0:
        from dashboard.consumers import push_news_notification
        push_news_notification({"count": rss_count + api_count, "message": f"{rss_count + api_count} new articles"})

    return {"status": "success", "rss": rss_count, "api": api_count}


@shared_task
@guarded_task("scraper_sentiment")
def fetch_social_sentiment():
    """Tier 2: Fetch sentiment from Reddit + StockTwits."""
    from scraping.scrapers.reddit_sentiment import fetch_reddit_sentiment
    from scraping.scrapers.stocktwits import fetch_trending

    results = {"reddit": 0, "stocktwits": 0}
    try:
        reddit_data = fetch_reddit_sentiment(limit=50)
        results["reddit"] = len(reddit_data)
    except Exception as e:
        logger.error(f"Reddit sentiment failed: {e}")

    try:
        trending = fetch_trending()
        results["stocktwits"] = len(trending)
    except Exception as e:
        logger.error(f"StockTwits trending failed: {e}")

    return {"status": "success", **results}


@shared_task
@guarded_task("scraper_calendar")
def check_economic_calendar():
    """Tier 2: Fetch earnings calendar from FMP."""
    from scraping.scrapers.earnings_calendar import fetch_earnings_calendar_fmp
    data = fetch_earnings_calendar_fmp(days_ahead=14)
    return {"status": "success", "events": len(data)}


@shared_task
@guarded_task("scraper_finviz")
def fetch_finviz_screener():
    """Tier 3: Fetch FinViz screener data."""
    from scraping.scrapers.finviz import fetch_screener_results

    try:
        results = fetch_screener_results()
        return {"status": "success", "stocks_found": len(results)}
    except Exception as e:
        logger.error(f"FinViz screener failed: {e}")
        return {"status": "error", "error": str(e)}


@shared_task
@guarded_task("pipeline_sentiment_agg")
def aggregate_sentiment():
    """Tier 3: Aggregate sentiment scores across all sources."""
    from scraping.models import SentimentSnapshot
    from instruments.models import Instrument
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Avg, Sum

    cutoff = timezone.now() - timedelta(hours=24)
    instruments = Instrument.objects.filter(is_active=True, is_watchlist=True)
    aggregated = 0

    for inst in instruments:
        snapshots = SentimentSnapshot.objects.filter(
            instrument=inst, timestamp__gte=cutoff
        )
        if not snapshots.exists():
            continue

        agg = snapshots.aggregate(
            avg_score=Avg("composite_score"),
            total_volume=Sum("volume"),
            total_bullish=Sum("bullish_count"),
            total_bearish=Sum("bearish_count"),
        )
        SentimentSnapshot.objects.create(
            instrument=inst,
            source="aggregated",
            timestamp=timezone.now(),
            composite_score=agg["avg_score"] or 0,
            volume=agg["total_volume"] or 0,
            bullish_count=agg["total_bullish"] or 0,
            bearish_count=agg["total_bearish"] or 0,
            trending=bool(agg["total_volume"] and agg["total_volume"] > 100),
        )
        aggregated += 1

    return {"status": "success", "instruments_aggregated": aggregated}


@shared_task
@guarded_task("scraper_tradingview")
def fetch_tradingview_ideas():
    """Tier 4: Fetch TradingView ideas + technicals for watchlist."""
    from scraping.scrapers.tradingview import fetch_trending_ideas, fetch_technical_analysis
    from instruments.models import Instrument

    results = {"ideas": 0, "technicals": 0}
    try:
        ideas = fetch_trending_ideas(limit=20)
        results["ideas"] = len(ideas)
    except Exception as e:
        logger.error(f"TradingView ideas failed: {e}")

    try:
        watchlist = Instrument.objects.filter(is_watchlist=True, is_active=True)[:20]
        for inst in watchlist:
            try:
                fetch_technical_analysis(inst.symbol)
                results["technicals"] += 1
            except Exception:
                pass
    except Exception as e:
        logger.error(f"TradingView technicals failed: {e}")

    return {"status": "success", **results}


@shared_task
@guarded_task("scraper_sec")
def fetch_sec_filings():
    """Tier 5: Fetch SEC filings (13F + insider trades)."""
    from scraping.scrapers.sec_edgar import fetch_recent_13f_filings, fetch_insider_trades

    results = {"filings_13f": 0, "insider_trades": 0}
    try:
        filings = fetch_recent_13f_filings(limit=20)
        results["filings_13f"] = len(filings)
    except Exception as e:
        logger.error(f"SEC 13F fetch failed: {e}")

    try:
        trades = fetch_insider_trades(limit=20)
        results["insider_trades"] = len(trades)
    except Exception as e:
        logger.error(f"SEC insider trades failed: {e}")

    return {"status": "success", **results}


@shared_task
@guarded_task("scraper_cot")
def fetch_cot_reports():
    """Tier 6: Fetch CFTC Commitments of Traders reports."""
    from scraping.scrapers.cot_reports import fetch_latest_cot_report

    try:
        reports = fetch_latest_cot_report()
        return {"status": "success", "reports_processed": len(reports)}
    except Exception as e:
        logger.error(f"COT reports failed: {e}")
        return {"status": "error", "error": str(e)}
