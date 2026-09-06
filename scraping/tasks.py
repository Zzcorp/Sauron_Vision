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


# How far back to reach for a body. A story older than this either has one by
# now or never will (paywall, dead link, JS-only page), and this window is what
# replaces a retry counter: a permanently unfetchable article ages out of the
# queryset by itself instead of being retried until the end of time. No new
# column, no migration, and no article tried more than a handful of times.
BODY_FETCH_MAX_AGE_HOURS = 72
# One batch. Each item is a live HTTP request to somebody else's server, so
# this is a politeness limit as much as a runtime one.
BODY_FETCH_BATCH = 25


@shared_task
# Gated on scraper_news rather than a component of its own, deliberately.
# A new PlatformComponent is created with is_enabled=False (the model default,
# and DEFAULT_COMPONENTS does not override it), so shipping one here would
# have added a task that silently never runs until somebody found a checkbox
# nobody mentioned — the exact failure mode this platform has already been
# bitten by. Fetching an article body IS news scraping; it belongs behind the
# switch the operator already turned on for news.
@guarded_task("scraper_news")
def fetch_news_bodies(*, limit: int = BODY_FETCH_BATCH,
                      max_age_hours: int = BODY_FETCH_MAX_AGE_HOURS) -> dict:
    """Fill `NewsArticle.raw_content`, which no scraper has ever written.

    The field is described across this codebase as "the full scraped body",
    and `cleanup_news_bodies` exists only to blank it after 90 days because it
    "is nearly all of [news's] weight". Nothing filled it. So the article page
    showed empty content beside the AI's opinion, and the AI's opinion itself
    came from `content_summary or raw_content[:2000]` — an RSS teaser capped at
    1000 characters, frequently empty. Sentiment, urgency, the affected-symbol
    match and the brain's news context were all measured off a headline.

    Newest first: if the batch cannot keep up, the stories the platform is
    about to reason about are the ones that get bodies.
    """
    from datetime import timedelta

    from django.utils import timezone

    from scraping.article_body import fetch_article_body
    from scraping.models import NewsArticle

    cutoff = timezone.now() - timedelta(hours=int(max_age_hours))
    due = list(NewsArticle.objects
               .filter(published_at__gte=cutoff, raw_content="")
               .order_by("-published_at")[:max(1, int(limit))])

    filled, reasons = 0, {}
    for article in due:
        try:
            text, reason = fetch_article_body(article.url)
        except Exception as e:  # noqa: BLE001 — one bad host is not a failed run
            text, reason = "", f"error: {type(e).__name__}"
            logger.debug("body fetch raised for %s: %s", article.url, e)
        reasons[reason] = reasons.get(reason, 0) + 1
        if not text:
            continue
        # raw_content ONLY. content_summary is the feed's own words and the
        # retention task uses the pair to decide what is safe to strip: it
        # blanks raw_content only on rows that still carry a summary, so
        # overwriting the summary with our extraction would eventually leave
        # the row with neither.
        NewsArticle.objects.filter(pk=article.pk).update(raw_content=text)
        filled += 1

    logger.info("fetch_news_bodies: %d/%d filled (%s)", filled, len(due),
                ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    return {"status": "success", "considered": len(due), "filled": filled,
            "reasons": reasons}


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
    """Tier 2: Fetch the earnings AND macro calendars from FMP.

    Both, under one component, because both ARE the economic calendar and
    a second component would need its own registry entry, topology node,
    system-map edge and beat schedule to say the same thing.

    They were not both here before, and the macro half is why every forex
    position's event-risk read rendered a confident empty list through NFP,
    CPI and FOMC: the earnings scraper is the only thing that ever wrote
    `EconomicEvent`, and it stores the equity TICKER in
    `currency_affected`, so the currency branch could never match a row.

    The two write under different `source` values and cannot overwrite each
    other. A failure in either is reported: the macro half failing while
    earnings succeed still leaves the FX check blind, so it must not be
    averaged away into a green run.
    """
    from scraping.scrapers.earnings_calendar import fetch_earnings_calendar_fmp
    from scraping.scrapers.macro_calendar import fetch_macro_calendar_fmp

    result = fetch_earnings_calendar_fmp(days_ahead=14)
    macro = fetch_macro_calendar_fmp(days_ahead=14)
    result = {
        **result,
        "macro_parsed": macro.get("parsed", 0),
        "macro_stored": macro.get("stored", 0),
    }
    # The macro half's verdict is carried, not merged: an `error` from
    # either has to reach task_gate as an error, and a `skipped` from
    # either is a run that did not do its job.
    if macro.get("error"):
        result["error"] = " | ".join(
            x for x in (result.get("error"), f"macro: {macro['error']}") if x)
    if macro.get("skipped") and not result.get("error"):
        result["skipped"] = result.get("skipped") or macro["skipped"]
    # A macro half that PARSED rows and stored NONE has to reach the verdict
    # on its own. `task_gate.judge_result` sums the counts it finds across the
    # result and its sub-dicts, so its "handled N rows and stored none"
    # warning can only fire when BOTH halves are empty — an earnings half
    # storing normally masks a macro half that kept nothing. The keys
    # macro_parsed/macro_stored are in neither WORK_KEYS nor DONE_KEYS, so
    # today the macro half cannot lower the grade at all.
    macro_dropped = ((macro.get("parsed") or 0) > 0
                     and not (macro.get("stored") or 0))
    if macro_dropped and not result.get("error"):
        result["skipped"] = (
            result.get("skipped")
            or f"macro parsed {macro.get('parsed')} rows and stored none")
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
