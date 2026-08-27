"""Celery tasks for web scraping — REAL implementations."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


def _scan_universe(limit=20):
    """The instruments a per-symbol scraper should walk.

    Every per-symbol loop in this package filtered on is_watchlist=True. Not
    one of the 179 active instruments has that flag set, so each of those
    loops iterated zero times and returned success — which is also why
    TechnicalIndicator held zero rows despite 5,600 price bars being present.

    An empty watchlist is a configuration the operator has not got round to,
    not an instruction to do nothing. So fall back to the instruments we
    actually have prices for, which is the set any of this can say something
    useful about, and say out loud that we are doing it.
    """
    from instruments.models import Instrument

    watchlist = Instrument.objects.filter(is_watchlist=True, is_active=True)
    if watchlist.exists():
        return list(watchlist[:limit])

    fallback = list(Instrument.objects.filter(
        is_active=True, prices__isnull=False).distinct()[:limit])
    if fallback:
        logger.info("No instruments are flagged is_watchlist; falling back to "
                    "%d active instruments that have price history. Run "
                    "`manage.py seed_watchlist` to set a real watchlist.",
                    len(fallback))
    else:
        logger.warning("No watchlist and no instruments with price history — "
                       "per-symbol scrapers have nothing to walk.")
    return fallback


@shared_task
@guarded_task("scraper_news")
def fetch_breaking_news():
    # After AI processes news, notify on critical items:
    # from alerts.notify import notify_critical_news
    # for article in critical_articles:
    #     notify_critical_news(article)
    """Tier 1: Fetch news from RSS feeds and APIs."""
    from scraping.scrapers.news_aggregator import fetch_rss_news, fetch_marketaux_news

    rss = fetch_rss_news(max_per_feed=5)
    api = fetch_marketaux_news(limit=20)
    stored = rss["stored"] + api["stored"]

    # Push WebSocket notification for new news
    if stored > 0:
        from dashboard.consumers import push_news_notification
        push_news_notification({"count": stored, "message": f"{stored} new articles"})

    return {"status": "success", "rss": rss, "api": api,
            "parsed": rss["parsed"] + api["parsed"], "stored": stored}


@shared_task
@guarded_task("scraper_sentiment")
def fetch_social_sentiment():
    """Tier 2: Fetch sentiment from Reddit + StockTwits."""
    from scraping.scrapers.reddit_sentiment import (fetch_reddit_sentiment,
                                                    reddit_unavailable_reason)
    from scraping.scrapers.stocktwits import fetch_trending

    from scraping.models import SentimentSnapshot

    # Counting rows written is the only honest measure here. Both sources
    # previously reported len() of what they fetched, which is a count of
    # HTTP results rather than of anything that reached the database — and
    # SentimentSnapshot had zero rows the whole time.
    before = SentimentSnapshot.objects.count()
    results = {"reddit": 0, "stocktwits": 0}

    # An unconfigured Reddit returned [] exactly like a quiet hour on
    # r/wallstreetbets, so a source that has never once run looked like a
    # source with nothing to say. Naming the reason puts the task in
    # judge_result's not-configured branch, which is the only verdict that
    # tells the operator there is something to DO about it.
    reddit_skipped = reddit_unavailable_reason()
    if reddit_skipped:
        results["reddit_skipped"] = reddit_skipped
    else:
        try:
            results["reddit"] = len(fetch_reddit_sentiment(limit=50))
        except Exception as e:
            logger.error(f"Reddit sentiment failed: {e}")

    try:
        results["stocktwits"] = len(fetch_trending())
    except Exception as e:
        logger.error(f"StockTwits trending failed: {e}")

    # The operator's OWN starred equities — trending alone samples
    # StockTwits' universe (mostly off-catalogue small caps), which is how
    # this task used to run green while storing nothing.
    try:
        from scraping.scrapers.stocktwits import fetch_watchlist_sentiment
        results["stocktwits_watchlist"] = fetch_watchlist_sentiment()
    except Exception as e:
        logger.error(f"StockTwits watchlist sentiment failed: {e}")
        results["stocktwits_watchlist"] = 0

    stored = SentimentSnapshot.objects.count() - before
    out = {"status": "success", **results,
           "parsed": (results["reddit"] + results["stocktwits"]
                      + results["stocktwits_watchlist"]),
           "stored": stored}
    if reddit_skipped:
        out["skipped"] = reddit_skipped
    return out


@shared_task
@guarded_task("scraper_calendar")
def check_economic_calendar():
    """Tier 2: Fetch earnings calendar from FMP."""
    from scraping.scrapers.earnings_calendar import fetch_earnings_calendar_fmp
    result = fetch_earnings_calendar_fmp(days_ahead=14)
    # The scraper's word goes LAST. This used to read {"status": "success",
    # **result}: the scraper's failure paths return an `error` key and no
    # status, so a 403, a timeout or a DNS failure kept the hardcoded
    # "success" and graded as a mere warning ("ran and produced nothing") —
    # the same verdict a quiet calendar earns. An error the source reported
    # has to reach task_gate as an error.
    # A run that SKIPPED is not a run that succeeded. The no-credential
    # path returns {"skipped": "no_api_key"} and no status, so the default
    # below graded it "success" — while `task_gate`, reading the same dict,
    # wrote "warning" to the component row. One run, two verdicts, and the
    # return value was the dishonest one: anything reading the task's own
    # result saw a healthy calendar that had never fetched anything.
    if result.get("error"):
        status = "error"
    elif result.get("skipped"):
        status = "warning"
    else:
        status = result.get("status", "success")
    return {**result, "status": status}


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
    """Tier 4: TradingView aggregate ratings for the watchlist.

    The ideas half of this task was removed. It scraped tradingview.com/ideas
    with a `per_page` parameter that the site answers with a 404, there is no
    model anywhere that could hold an idea, and no page would have shown one —
    so it was three failure modes deep and still reported success every six
    hours.
    """
    from scraping.scrapers.tradingview import fetch_technical_analysis
    from scraping.models import SentimentSnapshot

    before = SentimentSnapshot.objects.count()
    parsed = 0

    for inst in _scan_universe(limit=20):
        try:
            fetch_technical_analysis(inst.symbol)
            parsed += 1
        except Exception as e:
            logger.warning("TradingView technicals failed for %s: %s", inst.symbol, e)

    return {"status": "success", "symbols": parsed, "parsed": parsed,
            "stored": SentimentSnapshot.objects.count() - before}


@shared_task
@guarded_task("scraper_sec")
def fetch_sec_filings():
    """Tier 5: Fetch SEC filings (13F + insider trades)."""
    from scraping.scrapers.sec_edgar import fetch_recent_13f_filings, fetch_insider_trades

    from scraping.models import InstitutionalFiling

    before = InstitutionalFiling.objects.count()
    results = {"filings_13f": 0, "insider_trades": 0}

    try:
        results["filings_13f"] = len(fetch_recent_13f_filings(limit=20))
    except Exception as e:
        logger.error(f"SEC 13F fetch failed: {e}")

    try:
        results["insider_trades"] = len(fetch_insider_trades(limit=20))
    except Exception as e:
        logger.error(f"SEC insider trades failed: {e}")

    stored = InstitutionalFiling.objects.count() - before
    return {"status": "success", **results,
            "parsed": results["filings_13f"] + results["insider_trades"],
            "stored": stored}


@shared_task
@guarded_task("scraper_cot")
def fetch_cot_reports():
    """Tier 6: Fetch CFTC Commitments of Traders reports."""
    from scraping.scrapers.cot_reports import fetch_latest_cot_report

    try:
        outcome = fetch_latest_cot_report()
    except Exception as e:
        logger.exception("COT reports failed")
        return {"status": "error", "error": str(e)}

    # Counts come back FROM the call. They used to be read off a function
    # attribute the scraper set only when it succeeded, and a Celery prefork
    # child outlives many beats — so a failed week reported the previous
    # week's stored count and the gate graded a dead scraper green.
    #
    # 'stored' counts UPSERTS, not a row-count delta: the Saturday beat can
    # fire before the CFTC posts the new week, and re-asserting last week's
    # rows is a healthy run, not "handled N rows and stored none".
    parsed = int(outcome.get("parsed") or 0)
    stored = int(outcome.get("stored") or 0)
    result = {"status": "success", "reports_processed": parsed,
              "parsed": parsed, "stored": stored}
    # Not under a 'skipped' key: that word is the gate's own, and it grades a
    # missing credential. A mapped market with no catalogue row is a seeding
    # gap, so it rides along named while the counts stay the verdict.
    missing = outcome.get("missing_instruments") or []
    if missing:
        result["missing_instruments"] = list(missing)[:25]
    return result
