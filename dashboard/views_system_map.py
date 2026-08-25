"""System Map — what Sauron is actually doing, stage by stage.

The admin panel already had a component registry (is it switched on?) and a
health page (do these assertions pass?). Neither answered the question that
actually matters when something is wrong: **is data moving through the
machine?**

That gap was not theoretical. Six scraper components sat at last_status
='success' with zero rows between them, because the gate marked any task that
returned without raising as a success. The earnings calendar was among them, so
the bot's earnings blackout had never once fired — and every surface in the
platform reported green.

So this page is built on throughput, not on status. Each node states how many
rows it produced in the last 24 hours, how old the newest one is, and — when
those two disagree with "the task ran fine" — says so in a sentence naming the
thing to go and fix.

Every node here is computed from a real query. Nothing on this page is a
placeholder, because a diagnostic surface that can itself be wrong is worse
than no diagnostic surface.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max
from django.shortcuts import render
from django.utils import timezone

# State vocabulary, worst first. The order is the ranking used for the problem
# list, so it is the single place that decides what an operator is shown first.
STATE_ORDER = ["broken", "stale", "unconfigured", "off", "idle", "live", "unknown"]

STATE_META = {
    "broken":       {"label": "BROKEN",   "glyph": "✕", "tone": "critical",
                     "hint": "Ran and failed, or produced something impossible."},
    "stale":        {"label": "STALE",    "glyph": "▲", "tone": "serious",
                     "hint": "Reported success but nothing arrived, or the newest row is too old."},
    "unconfigured": {"label": "NOT SET UP", "glyph": "◌", "tone": "warning",
                     "hint": "Needs a credential or a one-off setup step before it can work."},
    "off":          {"label": "OFF",      "glyph": "⏻", "tone": "muted",
                     "hint": "Switched off deliberately."},
    "idle":         {"label": "IDLE",     "glyph": "·", "tone": "muted",
                     "hint": "On, with nothing to do right now."},
    "live":         {"label": "LIVE",     "glyph": "●", "tone": "good",
                     "hint": "Data is arriving."},
    "unknown":      {"label": "UNKNOWN",  "glyph": "?", "tone": "muted",
                     "hint": "Could not be measured."},
}


def _age_s(dt):
    if dt is None:
        return None
    return max(0.0, (timezone.now() - dt).total_seconds())


def _fmt_age(seconds):
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds / 60)}m"
    if seconds < 172800:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _components():
    from core.platform_control import PlatformComponent
    return {c.key: c for c in PlatformComponent.objects.all()}


def node(key, label, purpose, *, state="unknown", why="", metric=None,
         metric_label="", rows_24h=None, newest=None, component=None,
         link=None, link_label="", fix="", reads=None):
    """One box on the map.

    `why` is the load-bearing field. A state with no explanation sends the
    operator hunting; the whole point of this page is that it says which query
    returned what, so the next step is obvious.
    """
    return {
        "key": key, "label": label, "purpose": purpose,
        "state": state, "why": why,
        "metric": metric, "metric_label": metric_label,
        "rows_24h": rows_24h,
        "newest_age": _age_s(newest),
        "newest_display": _fmt_age(_age_s(newest)),
        "component": component, "link": link, "link_label": link_label,
        "fix": fix, "reads": reads or [],
        "meta": STATE_META[state],
    }


def _store_state(total, rows_24h, newest, *, expect_daily=True,
                 stale_after_s=172800):
    """Shared verdict for anything that is fundamentally a growing table."""
    age = _age_s(newest)
    if total == 0:
        return "idle", "The table is empty — nothing has ever been written."
    if age is not None and age > stale_after_s:
        return "stale", (f"{total:,} rows, but the newest is {_fmt_age(age)} old — "
                         f"nothing new is arriving.")
    if expect_daily and not rows_24h:
        return "stale", f"{total:,} rows, none in the last 24 hours."
    return "live", f"{rows_24h:,} new in 24h, newest {_fmt_age(age)} old."


def collect_system_map(user):
    """Every stage of the pipeline, measured.

    Each probe is wrapped: a diagnostic page that 500s when one model is
    missing is a diagnostic page you cannot use on the day you need it.
    """
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    comps = _components()
    stages = []

    def comp_state(key):
        """Fold the component switch into a node's verdict.

        Returns (override_state, why) or (None, "") to leave the data verdict
        alone. Being switched off outranks having no data: 'OFF' is an answer,
        'STALE' would be a red herring.
        """
        c = comps.get(key)
        if c is None:
            return None, ""
        if not c.is_enabled:
            return "off", "Switched off in the component registry."
        if c.last_status == "error":
            return "broken", f"Last run failed: {(c.last_message or '')[:160]}"
        if c.last_status == "warning":
            return "stale", f"Last run warned: {(c.last_message or '')[:160]}"
        return None, ""

    def finish(n, comp_key=None):
        """Apply the component override and attach its run record."""
        c = comps.get(comp_key) if comp_key else None
        if c is not None:
            n["component"] = {
                "key": c.key, "name": c.name, "enabled": c.is_enabled,
                "last_status": c.last_status or "never run",
                "last_message": (c.last_message or "")[:200],
                "last_run": _fmt_age(_age_s(c.last_run_at)),
                "runs": c.run_count, "errors": c.error_count,
            }
            override, why = comp_state(comp_key)
            if override:
                n["state"], n["why"] = override, why
                n["meta"] = STATE_META[override]
        return n

    # ── 1. INGEST ────────────────────────────────────────────────────────
    ingest = []
    try:
        from market_data.models import PriceData
        total = PriceData.objects.count()
        newest = PriceData.objects.aggregate(m=Max("timestamp"))["m"]
        r24 = PriceData.objects.filter(timestamp__gte=day_ago).count()
        st, why = _store_state(total, r24, newest, expect_daily=False)
        ingest.append(finish(node(
            "bars", "Market bars", "OHLCV history every indicator, backtest and bot reads.",
            state=st, why=why, metric=total, metric_label="bars", rows_24h=r24,
            newest=newest, link="/instruments/", link_label="Instruments",
            fix="python manage.py backfill_bars" if total == 0 else "",
            reads=["Indicators", "Signal rules", "Backtests", "Bots"]), "scraper_eod"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("bars", "Market bars", "OHLCV history.",
                           why=f"probe failed: {e}"))

    try:
        from market_data.models import LiveQuote
        total = LiveQuote.objects.count()
        newest = LiveQuote.objects.aggregate(m=Max("updated_at"))["m"]
        age = _age_s(newest)
        if total == 0:
            st, why = "idle", "No quotes have ever been stored."
        elif age is not None and age > 3600:
            st, why = ("stale",
                       f"{total} symbols quoted, but the freshest is {_fmt_age(age)} "
                       f"old — every price on the platform is that stale.")
        else:
            st, why = "live", f"{total} symbols, freshest {_fmt_age(age)} old."
        ingest.append(finish(node(
            "quotes", "Live quotes", "The price every open position is marked against.",
            state=st, why=why, metric=total, metric_label="symbols",
            newest=newest, link="/market-quotes/", link_label="Quotes",
            reads=["Open position R", "Ticker", "Bot exits"]), "scraper_live_quotes"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("quotes", "Live quotes", "Marks.", why=f"probe failed: {e}"))

    try:
        from scraping.models import NewsArticle
        total = NewsArticle.objects.count()
        newest = NewsArticle.objects.aggregate(m=Max("published_at"))["m"]
        r24 = NewsArticle.objects.filter(scraped_at__gte=day_ago).count()
        st, why = _store_state(total, r24, newest)
        ingest.append(finish(node(
            "news", "News", "Headlines the sentiment index and the news analyst read.",
            state=st, why=why, metric=total, metric_label="articles", rows_24h=r24,
            newest=newest, link="/news/", link_label="News feed",
            reads=["Sentiment index", "News analyst", "Digests"]), "scraper_news"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("news", "News", "Headlines.", why=f"probe failed: {e}"))

    try:
        from scraping.models import SentimentSnapshot
        total = SentimentSnapshot.objects.count()
        newest = SentimentSnapshot.objects.aggregate(m=Max("timestamp"))["m"]
        r24 = SentimentSnapshot.objects.filter(timestamp__gte=day_ago).count()
        sources = sorted(set(SentimentSnapshot.objects.values_list("source", flat=True)))
        st, why = _store_state(total, r24, newest)
        if total == 0:
            why = ("No sentiment has ever been stored. Reddit needs "
                   "REDDIT_CLIENT_ID/SECRET; StockTwits and TradingView need no key.")
            st = "unconfigured"
        else:
            why += f" Sources: {', '.join(sources)}."
        ingest.append(finish(node(
            "sentiment", "Social sentiment", "Crowd positioning, per instrument.",
            state=st, why=why, metric=total, metric_label="snapshots", rows_24h=r24,
            newest=newest, link="/opportunities/", link_label="Opportunities",
            reads=["Sentiment index", "Opportunity scanner"]), "scraper_sentiment"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("sentiment", "Social sentiment", "Crowd.", why=f"probe failed: {e}"))

    try:
        from market_data.models import EconomicEvent
        total = EconomicEvent.objects.count()
        upcoming = EconomicEvent.objects.filter(datetime__gte=now).count()
        newest = EconomicEvent.objects.aggregate(m=Max("datetime"))["m"]
        if total == 0:
            st = "unconfigured"
            why = ("Empty. The bot decides its earnings blackout from this table, "
                   "so with no rows the blackout can never fire and it will open "
                   "into a print. Needs FMP_API_KEY.")
        elif upcoming == 0:
            st, why = "stale", f"{total:,} rows but none in the future — the calendar has run out."
        else:
            st, why = "live", f"{upcoming} upcoming event{'s' if upcoming != 1 else ''}."
        ingest.append(finish(node(
            "calendar", "Economic calendar", "Earnings dates the bot blacks out around.",
            state=st, why=why, metric=upcoming, metric_label="upcoming",
            newest=newest, link="/calendar/", link_label="Calendar",
            fix="Set FMP_API_KEY, then run the Economic Calendar scraper",
            reads=["Stock bot earnings blackout", "Earnings reviewer"]), "scraper_calendar"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("calendar", "Economic calendar", "Earnings dates.",
                           why=f"probe failed: {e}"))

    try:
        from scraping.models import InstitutionalFiling
        total = InstitutionalFiling.objects.count()
        newest_d = InstitutionalFiling.objects.aggregate(m=Max("filing_date"))["m"]
        st = "live" if total else "idle"
        why = (f"{total:,} filings stored." if total
               else "No filings stored. SEC rejects a generic user agent — "
                    "SEC_EDGAR_USER_AGENT must name a real contact.")
        ingest.append(finish(node(
            "sec", "SEC filings", "13F positions and Form 4 insider trades.",
            state=st, why=why, metric=total, metric_label="filings",
            link="/opportunities/", link_label="Opportunities",
            reads=["Opportunity scanner"]), "scraper_sec"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("sec", "SEC filings", "Filings.", why=f"probe failed: {e}"))

    try:
        # Measured, not remembered. This node used to state a diagnosis in
        # prose — that the parser read column names the CFTC release no longer
        # publishes — and it kept stating it after the parser was rewritten to
        # read by position and verified storing rows. A diagnostic page that
        # narrates a fixed bug sends the operator to repair working code, so
        # the verdict now comes from the rows and the newest report_date.
        #
        # CFTC publishes once a week, for Tuesday's positions, on the Friday.
        # Two missed publications (~14 days) is the schedule having stopped;
        # anything less is the normal gap between releases.
        from scraping.models import COTReport
        total = COTReport.objects.count()
        newest_date = COTReport.objects.aggregate(m=Max("report_date"))["m"]
        weeks = COTReport.objects.values("report_date").distinct().count()
        if total == 0:
            st = "idle"
            why = ("No CFTC rows have ever been stored. The fetch runs weekly, "
                   "Saturday 00:00 UTC.")
        else:
            days = (timezone.now().date() - newest_date).days
            if days > 14:
                st = "stale"
                why = (f"{total:,} rows across {weeks} report dates, newest "
                       f"{newest_date} — {days} days old, so two weekly "
                       f"releases have been missed.")
            else:
                st = "live"
                why = (f"{total:,} rows across {weeks} report dates, newest "
                       f"{newest_date} ({days}d old).")
        ingest.append(finish(node(
            "cot", "COT positioning", "CFTC commitments of traders, weekly.",
            state=st, why=why, metric=total, metric_label="rows",
            # report_date is a date; the card's freshness field measures
            # datetimes, and handing it None would print "never" beside a
            # sentence that just named the date.
            newest=(timezone.make_aware(datetime.combine(newest_date, time.min))
                    if newest_date else None),
            reads=["Opportunity scanner", "Advanced evaluators"]), "scraper_cot"))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("cot", "COT positioning", "CFTC.", why=f"probe failed: {e}"))

    try:
        from market_data.models import FundingRate, LiquidationEvent
        fr = FundingRate.objects.filter(timestamp__gte=day_ago).count()
        lq = LiquidationEvent.objects.filter(timestamp__gte=day_ago).count()
        newest = FundingRate.objects.aggregate(m=Max("timestamp"))["m"]
        st = "live" if (fr or lq) else "idle"
        why = (f"{fr} funding samples and {lq} liquidations in 24h." if (fr or lq)
               else "No funding or liquidation data in 24h — the crypto streamer "
                    "is not running.")
        ingest.append(node(
            "derivs", "Funding & liquidations", "Perp funding and forced closes.",
            state=st, why=why, metric=fr + lq, metric_label="events 24h",
            rows_24h=fr + lq, newest=newest,
            link="/liquidations/", link_label="Liquidations",
            reads=["Info panel", "Crypto bot context"]))
    except Exception as e:                                    # pragma: no cover
        ingest.append(node("derivs", "Funding & liquidations", "Perps.",
                           why=f"probe failed: {e}"))

    stages.append({"key": "ingest", "title": "Ingest",
                   "blurb": "Everything the platform knows starts here. "
                            "A stale node here makes every stage below it wrong.",
                   "nodes": ingest})

    # ── 2. ENRICH ────────────────────────────────────────────────────────
    enrich = []
    try:
        from indicators.models import TechnicalIndicator
        total = TechnicalIndicator.objects.count()
        newest = TechnicalIndicator.objects.aggregate(m=Max("timestamp"))["m"]
        r24 = TechnicalIndicator.objects.filter(timestamp__gte=day_ago).count()
        from instruments.models import Instrument
        watch = Instrument.objects.filter(is_watchlist=True, is_active=True).count()
        if total == 0 and watch == 0:
            st = "unconfigured"
            why = ("No indicators, and no instrument is flagged is_watchlist — "
                   "the recalculation job filters on that flag, so it walks an "
                   "empty set and reports success.")
        else:
            st, why = _store_state(total, r24, newest)
        enrich.append(finish(node(
            "indicators", "Technical indicators", "RSI, MACD, moving averages, ATR.",
            state=st, why=why, metric=total, metric_label="rows", rows_24h=r24,
            newest=newest, fix="python manage.py seed_watchlist" if watch == 0 else "",
            link="/instruments/", link_label="Instruments",
            reads=["Signal rules", "Instrument detail", "Risk levels"]), "pipeline_indicators"))
    except Exception as e:                                    # pragma: no cover
        enrich.append(node("indicators", "Technical indicators", "TA.", why=f"probe failed: {e}"))

    try:
        from scraping.models import NewsArticle
        total = NewsArticle.objects.count()
        done = NewsArticle.objects.filter(ai_processed_at__isnull=False).count()
        tagged = NewsArticle.objects.filter(
            ai_affected_instruments__isnull=False).distinct().count()
        if total == 0:
            st, why = "idle", "No articles to enrich."
        elif done == 0:
            st = "unconfigured"
            why = (f"0 of {total:,} articles carry AI sentiment. The news analyst "
                   f"needs ANTHROPIC_API_KEY; {tagged:,} are instrument-tagged by "
                   f"the keyless text matcher.")
        else:
            st, why = "live", f"{done:,} of {total:,} enriched, {tagged:,} instrument-tagged."
        enrich.append(finish(node(
            "news_ai", "News enrichment", "Sentiment score and affected instruments per article.",
            state=st, why=why, metric=done, metric_label="enriched",
            link="/news/", link_label="News feed",
            reads=["News & sentiment page", "Sentiment index", "Instrument detail"]),
            "agent_news_analyst"))
    except Exception as e:                                    # pragma: no cover
        enrich.append(node("news_ai", "News enrichment", "AI.", why=f"probe failed: {e}"))

    stages.append({"key": "enrich", "title": "Enrich",
                   "blurb": "Raw rows become features. Nothing here invents data — "
                            "each node is only as good as its ingest node.",
                   "nodes": enrich})

    # ── 3. DECIDE ────────────────────────────────────────────────────────
    decide = []
    try:
        from signals.models import Signal
        total = Signal.objects.count()
        active = Signal.objects.filter(is_active=True).count()
        r24 = Signal.objects.filter(created_at__gte=day_ago).count()
        newest = Signal.objects.aggregate(m=Max("created_at"))["m"]
        st, why = _store_state(total, r24, newest)
        if total:
            why = f"{active} active, {r24} raised in 24h, newest {_fmt_age(_age_s(newest))} old."
        decide.append(finish(node(
            "signals", "Signals", "Setups the rules found, with entry, stop and target.",
            state=st, why=why, metric=active, metric_label="active", rows_24h=r24,
            newest=newest, link="/signals/", link_label="Signals",
            reads=["Bots", "Signal rail", "Ticker"]), "pipeline_signals"))
    except Exception as e:                                    # pragma: no cover
        decide.append(node("signals", "Signals", "Setups.", why=f"probe failed: {e}"))

    try:
        from signals.models_control import RuleControl
        rows = list(RuleControl.objects.all())
        active = [r for r in rows if r.status == "active"]
        by_stage = {}
        for r in rows:
            by_stage[r.promotion_stage or "—"] = by_stage.get(r.promotion_stage or "—", 0) + 1
        st = "live" if active else ("idle" if rows else "unconfigured")
        why = (f"{len(active)} active of {len(rows)} rules. Stages: "
               + ", ".join(f"{k} {v}" for k, v in sorted(by_stage.items()))
               if rows else "No rules are registered.")
        decide.append(node(
            "rules", "Rule controls", "Which rules may fire, and at what venue.",
            state=st, why=why, metric=len(active), metric_label="active rules",
            link="/rule-control/", link_label="Rule control",
            reads=["Signal scan", "Bots", "Allocator"]))
    except Exception as e:                                    # pragma: no cover
        decide.append(node("rules", "Rule controls", "Rules.", why=f"probe failed: {e}"))

    try:
        from strategies.models import Strategy
        total = Strategy.objects.count()
        act = Strategy.objects.filter(status__in=["active", "approved"]).count()
        prop = Strategy.objects.filter(status="proposed").count()
        st = "live" if act else ("idle" if total else "idle")
        why = (f"{act} active, {prop} awaiting review, {total} total."
               if total else "No strategies yet.")
        decide.append(node(
            "strategies", "Strategies", "Named plans built from rules.",
            state=st, why=why, metric=act, metric_label="active",
            link="/strategies/", link_label="Strategies",
            reads=["Allocator", "Generated proposals"]))
    except Exception as e:                                    # pragma: no cover
        decide.append(node("strategies", "Strategies", "Plans.", why=f"probe failed: {e}"))

    stages.append({"key": "decide", "title": "Decide",
                   "blurb": "Where features become an opinion with a price attached.",
                   "nodes": decide})

    # ── 4. GATE ──────────────────────────────────────────────────────────
    gate = []
    try:
        from core.platform_control import is_component_enabled
        master = is_component_enabled("platform_master")
        gate.append(node(
            "master", "Master switch", "One flag that stops every automated task.",
            state="live" if master else "off",
            why=("Automation is armed — scheduled tasks will run."
                 if master else
                 "Every scheduled task is disabled. Nothing scrapes, scans or trades."),
            metric=None, link="/hq/", link_label="Admin panel"))
    except Exception as e:                                    # pragma: no cover
        gate.append(node("master", "Master switch", "Kill switch.", why=f"probe failed: {e}"))

    try:
        from bot_program.models import OrchestratorEvent
        r24 = OrchestratorEvent.objects.filter(created_at__gte=day_ago)
        n = r24.count()
        rejects = r24.filter(decision="reject").count()
        newest = OrchestratorEvent.objects.aggregate(m=Max("created_at"))["m"]
        if n == 0:
            st, why = "idle", "No gate decisions in 24h — nothing reached the gate."
        else:
            pct = round(rejects / n * 100)
            st = "stale" if pct >= 95 else "live"
            why = (f"{n} decisions in 24h, {rejects} rejected ({pct}%)."
                   + (" Almost everything is being blocked — check the gate reasons."
                      if pct >= 95 else ""))
        gate.append(node(
            "gate", "Risk gate", "The last check before an order is sent.",
            state=st, why=why, metric=n, metric_label="decisions 24h", rows_24h=n,
            newest=newest, link="/eye/gate-events/", link_label="Gate events",
            reads=["Every bot entry"]))
    except Exception as e:                                    # pragma: no cover
        gate.append(node("gate", "Risk gate", "Pre-trade checks.", why=f"probe failed: {e}"))

    stages.append({"key": "gate", "title": "Gate",
                   "blurb": "Everything below has already been decided. "
                            "This stage exists to stop it.",
                   "nodes": gate})

    # ── 5. EXECUTE ───────────────────────────────────────────────────────
    execute = []
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfgs = list(AssetBotConfig.objects.filter(user=user))
        on = [c for c in cfgs if c.enabled]
        live_mode = [c for c in on if c.mode != "paper"]
        if not cfgs:
            st, why = "unconfigured", "No bots are configured for this account."
        elif not on:
            st, why = "off", f"{len(cfgs)} bots configured, none enabled."
        else:
            st = "live"
            why = (f"{len(on)} of {len(cfgs)} enabled"
                   + (f", {len(live_mode)} trading live." if live_mode
                      else " — all on paper."))
        execute.append(node(
            "bots", "Bots", "The asset-class engines that place orders.",
            state=st, why=why, metric=len(on), metric_label="enabled",
            link="/asset-bots/", link_label="Asset bots",
            reads=["Broker", "Trades"]))

        open_t = AssetBotTrade.objects.filter(
            config__user=user, status="OPEN").count()
        pending = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSE_PENDING").count()
        closed24 = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED", closed_at__gte=day_ago).count()
        newest = AssetBotTrade.objects.filter(config__user=user).aggregate(
            m=Max("opened_at"))["m"]
        if pending:
            st = "broken"
            why = (f"{pending} position(s) failed to close and are still open at "
                   f"the broker. This needs a human.")
        elif open_t or closed24:
            st, why = "live", f"{open_t} open, {closed24} closed in 24h."
        else:
            st, why = "idle", "Nothing open and nothing closed in 24h."
        execute.append(node(
            "trades", "Trades", "Positions the bots hold and have closed.",
            state=st, why=why, metric=open_t, metric_label="open",
            rows_24h=closed24, newest=newest,
            link="/eye/fills/", link_label="Trade history",
            fix="Reconcile the stranded closes from the admin bot panel" if pending else "",
            reads=["Portfolio", "Grading", "Info panel"]))
    except Exception as e:                                    # pragma: no cover
        execute.append(node("bots", "Bots", "Engines.", why=f"probe failed: {e}"))

    stages.append({"key": "execute", "title": "Execute",
                   "blurb": "The only stage that spends money.",
                   "nodes": execute})

    # ── 6. LEARN ─────────────────────────────────────────────────────────
    learn = []
    try:
        from brain.models import BrainReport
        newest = BrainReport.objects.filter(error="").aggregate(m=Max("created_at"))["m"]
        total = BrainReport.objects.count()
        age = _age_s(newest)
        if total == 0:
            st, why = "idle", "The Mind has never produced a report."
        elif age is not None and age > 7200:
            st, why = "stale", f"Newest report is {_fmt_age(age)} old; it synthesises every 30 minutes."
        else:
            st, why = "live", f"{total} reports, newest {_fmt_age(age)} old."
        learn.append(node(
            "brain", "The Mind", "Regime read, portfolio health and standing concerns.",
            state=st, why=why, metric=total, metric_label="reports", newest=newest,
            link="/brain/", link_label="Brain",
            reads=["Ask Sauron", "Briefings", "Allocator"]))
    except Exception as e:                                    # pragma: no cover
        learn.append(node("brain", "The Mind", "Synthesis.", why=f"probe failed: {e}"))

    try:
        from portfolio.models import PortfolioSnapshot
        total = PortfolioSnapshot.objects.count()
        newest = PortfolioSnapshot.objects.aggregate(m=Max("date"))["m"]
        if total == 0:
            st = "idle"
            why = ("No snapshots. Drawdown and daily P&L are computed from these, "
                   "so both render as unknown everywhere until one is taken.")
        else:
            st, why = "live", f"{total} daily snapshots, newest {newest}."
        learn.append(finish(node(
            "snapshots", "Portfolio snapshots", "The daily record drawdown is measured from.",
            state=st, why=why, metric=total, metric_label="snapshots",
            link="/portfolio/", link_label="Portfolio",
            reads=["Drawdown", "Daily P&L", "Performance"]), "pipeline_snapshot"))
    except Exception as e:                                    # pragma: no cover
        learn.append(node("snapshots", "Portfolio snapshots", "Record.", why=f"probe failed: {e}"))

    try:
        from brain.models import GeneratedSetupProposal
        total = GeneratedSetupProposal.objects.count()
        st = "live" if total else "idle"
        why = f"{total} setup proposals generated." if total else "None generated yet."
        learn.append(finish(node(
            "proposals", "Generated setups", "Rules the platform wrote for itself.",
            state=st, why=why, metric=total, metric_label="proposals",
            link="/generated/", link_label="Generated",
            reads=["Review queue"]), "pipeline_evolution"))
    except Exception as e:                                    # pragma: no cover
        pass

    stages.append({"key": "learn", "title": "Learn",
                   "blurb": "What the platform does with the outcome of its own decisions.",
                   "nodes": learn})

    # ── Problems, ranked ─────────────────────────────────────────────────
    problems = []
    for st in stages:
        for n in st["nodes"]:
            if n["state"] in ("broken", "stale", "unconfigured"):
                problems.append({**n, "stage": st["title"]})
    problems.sort(key=lambda n: STATE_ORDER.index(n["state"]))

    counts = {k: 0 for k in STATE_ORDER}
    for st in stages:
        for n in st["nodes"]:
            counts[n["state"]] += 1
    total_nodes = sum(counts.values())

    # Throughput bars are drawn against the busiest stage, so the widest bar is
    # always full width and the rest are honestly proportional to it.
    stage_rows = []
    for st in stages:
        vol = sum((n["rows_24h"] or 0) for n in st["nodes"])
        stage_rows.append({"title": st["title"], "key": st["key"], "volume": vol,
                           "nodes": len(st["nodes"]),
                           "bad": sum(1 for n in st["nodes"]
                                      if n["state"] in ("broken", "stale", "unconfigured"))})
    peak = max([r["volume"] for r in stage_rows] + [1])
    for r in stage_rows:
        r["pct"] = round(r["volume"] / peak * 100)

    if counts["broken"]:
        verdict, headline = "critical", "Something is broken"
    elif counts["stale"]:
        verdict, headline = "serious", "Data has stopped moving somewhere"
    elif counts["unconfigured"]:
        verdict, headline = "warning", "Parts of the platform are not set up"
    elif counts["off"]:
        verdict, headline = "muted", "Running, with pieces switched off"
    else:
        verdict, headline = "good", "Everything is moving"

    return {
        "stages": stages, "problems": problems, "counts": counts,
        "total_nodes": total_nodes, "stage_rows": stage_rows,
        "verdict": verdict, "headline": headline,
        "generated_at": now,
        "state_meta": STATE_META,
        # The count rides with each state rather than being looked up in the
        # template: Django templates cannot index a dict by a variable key, and
        # the workaround is always a custom filter nobody remembers exists.
        "state_legend": [{"key": k, "count": counts[k], **STATE_META[k]}
                         for k in STATE_ORDER if k != "unknown"],
    }


@login_required
@user_passes_test(lambda u: u.is_staff)
def system_map(request):
    ctx = collect_system_map(request.user)
    ctx["page_id"] = "hq"
    return render(request, "dashboard/system_map.html", ctx)
