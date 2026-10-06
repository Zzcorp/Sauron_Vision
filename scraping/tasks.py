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
# A publisher's NO is remembered (2026-10-06). "No article tried more than a
# handful of times", above, was true only while new stories kept pushing
# the old ones out of the batch: newest first, with the twenty-five newest
# behind paywalls, the SAME twenty-five were asked again every ten minutes
# for seventy-two hours — four hundred times each — and the row read
# "handled 25 rows and stored none" at every pass. A refusal that is the
# publisher's (robots.txt, a 4xx, a paywall stub, a PDF) is kept in the
# cache, one key per row, for the fetch window, and that row is not asked
# again; a failure that is the ROAD's (unreachable, timed out, a 5xx) is
# not remembered, so a host that was down is asked again next pass.
BODY_REFUSED_KEY = "news_body_refused:{pk}"
# How many newest rows are read to fill one batch past the remembered
# refusals. Four batches deep: beyond that the stories are old enough that
# the feed's own summary will have to do.
BODY_CANDIDATE_FACTOR = 4
# The reasons fetch_article_body gives that are the road's, not the
# publisher's. Anything else — "robots", "http 403", "too short (12 chars)
# — paywall or wall", "content-type application/pdf", "private address" —
# is a refusal no retry will change.
BODY_TRANSPORT_PREFIXES = ("fetch failed", "deadline", "read failed",
                           "error:", "requests unavailable", "http 5")
# The road is called broken when at least this many hosts never answered
# AND they are half the batch or more: one dead link in a batch of two is
# a dead link, not the box's network, and it is asked again next pass
# either way (a transport failure is never remembered).
BODY_ROAD_MIN = 3


def _body_reason_kind(reason) -> str:
    """"ok", "transport" or "refusal" for one of fetch_article_body's reasons."""
    r = str(reason or "").strip().lower()
    if r == "ok":
        return "ok"
    if r.startswith(BODY_TRANSPORT_PREFIXES):
        return "transport"
    return "refusal"


def _body_reason_words(reasons: dict) -> str:
    """"paywall or wall 14, http 403 8, robots 3": the batch's reasons
    folded onto their kind — a `too short (312 chars)` and a `too short
    (40 chars)` are one reason — largest first."""
    folded = {}
    for reason, n in (reasons or {}).items():
        r = str(reason or "?").strip()
        if r.startswith("too short"):
            r = "paywall or wall"
        elif r.startswith("deadline"):
            r = "timed out"
        elif r.startswith("fetch failed"):
            r = "unreachable"
        elif r.startswith("error:"):
            r = "fetch raised"
        folded[r] = folded.get(r, 0) + int(n or 0)
    return ", ".join(f"{k} {v}" for k, v in
                     sorted(folded.items(), key=lambda kv: (-kv[1], kv[0])))


def _bodies_refused(pks) -> set:
    """The rows among `pks` whose publisher already said no. Never raises:
    a cache that cannot be read remembers nothing, and the batch asks."""
    from django.core.cache import cache
    pks = [pk for pk in pks if pk is not None]
    if not pks:
        return set()
    try:
        found = cache.get_many([BODY_REFUSED_KEY.format(pk=pk) for pk in pks])
    except Exception as e:  # noqa: BLE001
        logger.debug("news body refusals unreadable: %s", e)
        return set()
    prefix = BODY_REFUSED_KEY.format(pk="")
    out = set()
    for key in found:
        try:
            out.add(int(str(key)[len(prefix):]))
        except (TypeError, ValueError):
            continue
    return out


def _remember_refusal(pk, reason: str, hours) -> None:
    from django.core.cache import cache
    try:
        cache.set(BODY_REFUSED_KEY.format(pk=pk), str(reason or "")[:80],
                  int(max(1, float(hours or 1)) * 3600))
    except Exception as e:  # noqa: BLE001
        logger.debug("news body refusal not remembered: %s", e)


@shared_task
# Gated on scraper_news rather than a component of its own, deliberately.
# A new PlatformComponent is created with is_enabled=False (the model default,
# and DEFAULT_COMPONENTS does not override it), so shipping one here would
# have added a task that silently never runs until somebody found a checkbox
# nobody mentioned — the exact failure mode this platform has already been
# bitten by. Fetching an article body IS news scraping; it belongs behind the
# switch the operator already turned on for news.
# The flip side: this task is the SECOND WRITER of the scraper_news row, every
# 10 minutes to the feed's 15, so what it returns is what the row says. See
# the return values below and `core.task_gate.guarded_task` on `idle`.
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

    WHAT THE SHARED ROW SAYS AFTER A BATCH (2026-10-06). The row is the
    news's — the feed task writes it every fifteen minutes — and this task
    writes it only when it has something true to say about the news:

      filled some    success, with the counts: the bodies landed.
      none, the ROAD half the batch or more never answered (unreachable,
                     timed out, a 5xx; at least BODY_ROAD_MIN of them): a
                     warning IN THIS TASK'S WORDS — "25 article bodies
                     tried, none kept: 18 hosts unreachable… the headlines
                     still arrive" — which is the operator's to look at
                     (the box's network, DNS).
      none,          idle: the row keeps the feed's verdict. A publisher's
      otherwise      no (robots.txt, a 4xx, a paywall stub) is the
                     designed outcome for most of the wire, it changes
                     nothing about the news, and it is remembered so the
                     same rows are not asked again (BODY_REFUSED_KEY); a
                     dead link or two is asked again next pass.

    Before this the counts' sentence, "handled 25 rows and stored none",
    went on the row every ten minutes and the digest read it under the
    name BREAKING NEWS — the operator read that the news had stopped,
    when the headlines were arriving and only the bodies were missing.
    """
    from datetime import timedelta

    from django.utils import timezone

    from scraping.article_body import fetch_article_body
    from scraping.models import NewsArticle

    cutoff = timezone.now() - timedelta(hours=int(max_age_hours))
    want = max(1, int(limit))
    candidates = list(NewsArticle.objects
                      .filter(published_at__gte=cutoff, raw_content="")
                      .order_by("-published_at")[:want * BODY_CANDIDATE_FACTOR])
    refused = _bodies_refused([a.pk for a in candidates])
    due = [a for a in candidates if a.pk not in refused][:want]

    if not due:
        # `idle`, not a verdict. A pass with nothing due is not a run of news
        # scraping, and the gate must not grade it: this used to return
        # {"considered": 0, "filled": 0}, keys judge_result cannot read, so
        # it kept the benefit of the doubt — "success" — and mark_run wrote
        # that over the feed task's real verdict on the shared row within
        # ten minutes of it landing. A dead RSS host showed green. The
        # convention for a second writer is the gate's own (the war story in
        # core.task_gate.guarded_task): say idle, and the row keeps the last
        # verdict of a pass that was a run.
        why = "no article is due for a body"
        if candidates:
            why += (f" ({len(candidates)} refused by their publishers, not "
                    f"asked again)")
        return {"status": "success", "idle": why,
                "considered": 0, "filled": 0, "reasons": {},
                "refused_remembered": len(refused)}

    filled, reasons = 0, {}
    for article in due:
        try:
            text, reason = fetch_article_body(article.url)
        except Exception as e:  # noqa: BLE001 — one bad host is not a failed run
            text, reason = "", f"error: {type(e).__name__}"
            logger.debug("body fetch raised for %s: %s", article.url, e)
        reasons[reason] = reasons.get(reason, 0) + 1
        if not text:
            if _body_reason_kind(reason) == "refusal":
                _remember_refusal(article.pk, reason, max_age_hours)
            continue
        # raw_content ONLY. content_summary is the feed's own words and the
        # retention task uses the pair to decide what is safe to strip: it
        # blanks raw_content only on rows that still carry a summary, so
        # overwriting the summary with our extraction would eventually leave
        # the row with neither.
        NewsArticle.objects.filter(pk=article.pk).update(raw_content=text)
        filled += 1

    tried = len(due)
    words = _body_reason_words(reasons)
    out = {"status": "success", "considered": tried, "filled": filled,
           "reasons": reasons, "refused_remembered": len(refused)}
    if filled:
        logger.info("fetch_news_bodies: %d/%d filled (%s)", filled, tried, words)
        # attempted/stored are the gate's words (task_gate.WORK_KEYS/
        # DONE_KEYS): a batch that filled some earns its success on the
        # row. considered/filled stay: they are this task's own words, for
        # the log and the operator.
        out.update(attempted=tried, stored=filled)
        return out

    transport = sum(n for r, n in reasons.items()
                    if _body_reason_kind(r) == "transport")
    remembered = sum(n for r, n in reasons.items()
                     if _body_reason_kind(r) == "refusal")
    if transport >= BODY_ROAD_MIN and transport * 2 >= tried:
        # The road, not the publishers: said in this task's words (the
        # gate believes a declared warning's reason, task_gate.judge_result),
        # never as the counts' "handled N rows and stored none".
        logger.warning("fetch_news_bodies: 0/%d filled — %d host(s) "
                       "unreachable or timed out (%s)", tried, transport, words)
        out["status"] = "warning"
        out["reason"] = (f"{tried} article bodies tried, none kept: "
                         f"{transport} host(s) unreachable or timed out "
                         f"({words}) — the headlines still arrive; only the "
                         f"bodies are missing")
        return out

    # The publishers refused (the designed outcome for most of the wire,
    # remembered above so those rows are not asked again), or a dead link
    # or two that is asked again next pass. Nothing about the NEWS
    # changed, so the row keeps the feed's verdict (idle).
    logger.warning("fetch_news_bodies: 0/%d filled (%s); %d refused by their "
                   "publishers and not asked again for %sh",
                   tried, words, remembered, max_age_hours)
    out["idle"] = (f"{tried} article bodies tried, none kept ({words}); the "
                   f"headlines still arrive"
                   + (f", and the {remembered} refused are not asked again"
                      if remembered else ""))
    return out


@shared_task
@guarded_task("scraper_sentiment")
def fetch_social_sentiment():
    """Tier 2: Fetch sentiment from StockTwits, and Reddit when its keys
    exist (Reddit off is the normal state since 2026-10-04)."""
    from scraping.scrapers.reddit_sentiment import (fetch_reddit_sentiment,
                                                    reddit_unavailable_reason)
    from scraping.scrapers.stocktwits import (fetch_trending, refusals,
                                              reset_refusals)

    from scraping.models import SentimentSnapshot

    # Counting rows written is the only honest measure here. Both sources
    # previously reported len() of what they fetched, which is a count of
    # HTTP results rather than of anything that reached the database — and
    # SentimentSnapshot had zero rows the whole time.
    before = SentimentSnapshot.objects.count()
    reset_refusals()
    results = {"reddit": 0, "stocktwits": 0}

    # An unconfigured Reddit returned [] exactly like a quiet hour on
    # r/wallstreetbets, so a source that has never once run looked like a
    # source with nothing to say. Naming the reason used to put the task
    # in judge_result's not-configured branch, "the only verdict that
    # tells the operator there is something to DO about it" — and there
    # was, until Reddit closed self-service app creation (November 2025;
    # the operator hit the wall on 2026-10-04 and chose to run without).
    # No keys is now Reddit OFF: said on the result, never graded as a
    # warning. A missing library with keys present is still the fault it
    # always was (`skipped`).
    reddit_reason = reddit_unavailable_reason()
    reddit_skipped = ""
    if reddit_reason == "reddit_no_credentials":
        results["reddit_off"] = ("no credentials — Reddit closed self-service "
                                 "app creation; StockTwits runs alone")
    elif reddit_reason:
        reddit_skipped = reddit_reason
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
    # A BLOCKED HOST IS NOT A QUIET MARKET (2026-10-06). StockTwits answers
    # a 403 or a 429 to this box and every call comes back None; the pass
    # then stores nothing, and the counts' verdict for that is "ran and
    # produced nothing" — a quiet market's words, which the digest sent
    # under SOCIAL SENTIMENT and the operator read as one. The scraper
    # counts its refusals (stocktwits.refusals); half the calls refused or
    # more, and nothing stored, is the fault it is, in words that say
    # which host to look at.
    asked = refusals()
    out["stocktwits_calls"] = asked["calls"]
    out["stocktwits_refused"] = asked["refused"]
    if (stored == 0 and asked["refused"]
            and asked["refused"] * 2 >= asked["calls"]):
        out["status"] = "error"
        out["error"] = (f"StockTwits refused {asked['refused']} of "
                        f"{asked['calls']} calls (last: {asked['last']}) — "
                        f"blocked or rate-limited from this host; nothing "
                        f"stored")
    if reddit_skipped:
        out["skipped"] = reddit_skipped
    return out


@shared_task
@guarded_task("scraper_calendar")
def check_economic_calendar():
    """Tier 2: Fetch the earnings calendar (FMP) AND the macro calendar
    (Forex Factory, FMP as the fallback — see macro_calendar).

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
    from scraping.scrapers.macro_calendar import fetch_macro_calendar

    result = fetch_earnings_calendar_fmp(days_ahead=14)
    macro = fetch_macro_calendar(days_ahead=14)
    result = {
        **result,
        "macro_parsed": macro.get("parsed", 0),
        "macro_stored": macro.get("stored", 0),
        "macro_source": macro.get("source", ""),
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
    calls = answered = 0

    # `parsed` counts the symbols TradingView ANSWERED, not the requests
    # made (2026-10-03). The scraper returns a neutral placeholder on every
    # failure — blocked, timed out, a symbol it does not know — and this
    # loop counted each placeholder as a row handled, so a scanner that
    # answered nothing for all twenty symbols read "handled 20 rows and
    # stored none", a dedupe's verdict, instead of the fault it was.
    for inst in _scan_universe(limit=20):
        calls += 1
        try:
            # The exchange travels with the symbol (2026-10-06): a NYSE
            # name asked for as NASDAQ:<symbol> is a symbol the scanner
            # does not know, and half the seeded book is on the NYSE.
            res = fetch_technical_analysis(
                inst.symbol, asset_class=getattr(inst, "asset_class", ""),
                exchange=getattr(inst, "exchange", "") or "")
        except Exception as e:
            logger.warning("TradingView technicals failed for %s: %s", inst.symbol, e)
            continue
        if (res or {}).get("recommendation_value") is not None:
            answered += 1

    stored = SentimentSnapshot.objects.count() - before
    if calls and not answered:
        return {"status": "error", "symbols": calls, "parsed": 0,
                "stored": stored,
                "error": (f"TradingView's scanner answered no data for "
                          f"{calls}/{calls} symbols — blocked from this host, "
                          f"or none of them in its spelling (see the log)")}
    return {"status": "success", "symbols": calls, "answered": answered,
            "parsed": answered, "stored": stored}


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
