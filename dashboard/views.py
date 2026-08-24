"""Sauron Vision — Dashboard Views (enriched)."""
import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.db import models
from django.db.models import Avg, Sum, Count

# The one parser for the `{parent}_evolved_v{N}` fork-name scheme. This module
# used to carry a private `_fork_parent` with its own copy of the regex, as
# did dashboard/views_evolution.py and signals/promotion_evidence.py — three
# copies whose docstrings each asserted that the other two agreed with them.
# `core.fork_names` imports nothing but `re`, so the import is free here.
from core.fork_names import FORK_INFIX, fork_parent

# The mover buckets the quotes page understands. Anything else arriving in
# ?movers= — a typo, a truncated link, an old bookmark — is not an error the
# operator can act on, so the view falls back to "all" rather than 500ing.
MOVER_BUCKETS = ("all", "winners", "losers")

# A view that swallows a failure has to say so somewhere. This module had no
# logger at all, so the only alternative to a 500 was silence.
logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    """Legacy redirect — the old 'COMMAND CENTER' home page was superseded by
    the Operations Center (/command/, Phase 62+). The URL is kept as a 302 so
    old bookmarks, the intro hand-off, and LOGIN_REDIRECT_URL all land on the
    current home. The full legacy page remains at legacy_dashboard below.
    """
    return redirect("command_center")


@login_required
def legacy_dashboard(request):
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from ai_agents.models import AgentTask
    from market_data.models import EconomicEvent
    from portfolio.services import (get_or_create_default_portfolio,
                                    live_book_value)
    from portfolio.models import Position, PortfolioSnapshot
    from core.market_calendar import is_forex_open, is_us_market_open, is_eu_market_open, is_weekend

    portfolio = get_or_create_default_portfolio()
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Portfolio metrics
    open_positions = Position.objects.filter(portfolio=portfolio, closed_at__isnull=True)
    total_unrealized = sum(float(p.unrealized_pnl) for p in open_positions)
    # The denominator for every share below is the LIVE book — cash plus both
    # position books at their marks — and no longer `Portfolio.current_value`.
    # That column is written by an hourly task that valued the legacy half
    # alone, so dividing by it reported "100% cash · 0% deployed" on an
    # account carrying bot trades, and a delta of 0.00 next to it.
    book = live_book_value(request.user, portfolio)
    # LIVE_DASH and not None: this template guards its shares with
    # `|default:"100"`, and Django's `default` fires on ANY falsy value — so a
    # None here would print "100% of portfolio" over a fully deployed book,
    # which is the exact fiction the em-dash exists to prevent.
    cash_pct = (LIVE_DASH if book.cash_pct is None else round(book.cash_pct))

    latest_snapshot = PortfolioSnapshot.objects.filter(portfolio=portfolio).first()

    # Trading performance metrics
    closed_positions = Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=False
    ).select_related("instrument", "strategy")
    total_closed = closed_positions.count()
    winning_trades = [p for p in closed_positions if float(p.unrealized_pnl) > 0]
    losing_trades = [p for p in closed_positions if float(p.unrealized_pnl) <= 0]
    win_rate = round(len(winning_trades) / total_closed * 100, 1) if total_closed > 0 else 0
    all_returns = [float(p.unrealized_pnl_pct) for p in closed_positions]
    avg_return = sum(all_returns) / len(all_returns) if all_returns else 0
    portfolio_alpha = round(avg_return, 2)
    # Deployed notional over book value — both from the live union, so the
    # ratio divides two figures that counted the same positions. It used to
    # put the legacy book's notional over the stored column, which counts a
    # different set of rows in the numerator than in the denominator.
    portfolio_delta = (LIVE_DASH if book.exposure_pct is None
                       else round(book.exposure_pct / 100, 2))
    best_trades = sorted(closed_positions, key=lambda p: float(p.unrealized_pnl), reverse=True)[:5]
    avg_win = round(sum(float(p.unrealized_pnl) for p in winning_trades) / len(winning_trades), 2) if winning_trades else 0
    avg_loss = round(sum(float(p.unrealized_pnl) for p in losing_trades) / len(losing_trades), 2) if losing_trades else 0
    profit_factor = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0

    # Signal metrics
    active_signals = Signal.objects.filter(is_active=True)
    avg_score = active_signals.aggregate(avg=Avg("score"))["avg"]

    # Strategy metrics
    active_strats = Strategy.objects.filter(status__in=["active", "approved"])
    proposed_strats = Strategy.objects.filter(status="proposed")

    # News metrics
    news_24h_qs = NewsArticle.objects.filter(published_at__gte=day_ago)
    avg_sentiment = news_24h_qs.filter(ai_sentiment_score__isnull=False).aggregate(avg=Avg("ai_sentiment_score"))["avg"]

    # Economic calendar
    upcoming = EconomicEvent.objects.filter(datetime__gte=now)
    high_impact = upcoming.filter(impact="high")

    # AI metrics
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    ai_mtd = AgentTask.objects.filter(created_at__gte=month_start)
    ai_total = ai_24h.count()
    ai_success = ai_24h.filter(success=True).count()
    ai_tokens = sum(t.input_tokens + t.output_tokens for t in ai_24h)
    last_task = AgentTask.objects.order_by("-created_at").first()

    context = {
        "page_id": "dashboard",
        "portfolio": portfolio,

        # Portfolio
        # The raw number, not a pre-signed string. "+{:.2f}" glued a plus in
        # front of whatever came back, so a down day rendered "+-2.34%" — and
        # the fallback "+0.00" reported a flat day on a book that had simply
        # never been snapshotted. The template signs it and colours it from
        # `sign_class`, and prints an em-dash when there is nothing to sign.
        "daily_pnl_pct": (latest_snapshot.daily_pnl_pct
                          if latest_snapshot is not None else None),
        "cash_pct": cash_pct,
        # The LIVE union, already computed above. The Command Center printed
        # `portfolio.current_value` behind a hardcoded "10,000" default — the
        # stored column AND a literal, which is why that cell read 10,000 on
        # an account that had been trading for days.
        "book_value_text": book.value_text or LIVE_DASH,
        "book_coverage": book.coverage,
        "total_unrealized_pnl": "{:.2f}".format(total_unrealized),
        "open_positions_count": open_positions.count(),
        # Measured, not 100 minus the cash share: with positions open and none
        # of them priced the complement reads 0% deployed, which is a claim of
        # no exposure on a book that is carrying some.
        "total_exposure_pct": (LIVE_DASH if book.exposure_pct is None
                               else round(book.exposure_pct)),
        "max_drawdown": "{:.2f}".format(latest_snapshot.max_drawdown) if latest_snapshot else "0.00",
        "sharpe_ratio": "{:.2f}".format(latest_snapshot.sharpe_ratio) if latest_snapshot and latest_snapshot.sharpe_ratio else "—",

        # Markets
        "instruments_count": Instrument.objects.filter(is_active=True).count(),
        "watchlist_count": Instrument.objects.filter(is_watchlist=True).count(),
        "active_signals_count": active_signals.count(),
        "bullish_count": active_signals.filter(direction="bullish").count(),
        "bearish_count": active_signals.filter(direction="bearish").count(),
        "avg_signal_score": "{:.2f}".format(avg_score) if avg_score else "—",
        "active_strategies_count": active_strats.count(),
        "proposed_strategies": proposed_strats.count(),

        # News
        "news_24h": news_24h_qs.count(),
        "avg_news_sentiment": "{:.2f}".format(avg_sentiment) if avg_sentiment else "—",

        # Economic calendar
        "upcoming_events": upcoming.count(),
        "high_impact_events": high_impact.count(),

        # AI
        "ai_tasks_24h": ai_total,
        "ai_success_rate": round(ai_success / ai_total * 100) if ai_total > 0 else 0,
        "ai_cost_24h": "${:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
        "ai_cost_mtd": "${:.2f}".format(sum(float(t.cost_usd) for t in ai_mtd)),
        "ai_avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in ai_24h) / ai_total if ai_total > 0 else 0),
        "ai_tokens_24h": "{:,}".format(ai_tokens),
        "last_agent_name": last_task.agent if last_task else "—",
        "last_agent_time": "{} ago".format(last_task.created_at.strftime("%H:%M")) if last_task else "—",

        # Trading performance
        "win_rate": win_rate,
        "total_trades": total_closed,
        "portfolio_alpha": portfolio_alpha,
        "portfolio_delta": portfolio_delta,
        "profit_factor": profit_factor,
        "avg_win": "{:.2f}".format(avg_win),
        "avg_loss": "{:.2f}".format(avg_loss),
        "best_trades": best_trades,

        # Exposure
        "exposure": {"stock": 0, "forex": 0, "commodity": 0, "cash": cash_pct},

        # Market sessions
        "forex_open": is_forex_open(),
        "us_open": is_us_market_open(),
        "eu_open": is_eu_market_open(),
        "is_weekend": is_weekend(),

        # Feed data
        "recent_signals": active_signals.select_related("instrument").order_by("-created_at")[:8],
        "active_strategies": active_strats.order_by("-created_at")[:5],
        "recent_news": NewsArticle.objects.order_by("-published_at")[:6],
        "recent_ai_tasks": AgentTask.objects.order_by("-created_at")[:8],
    }
    return render(request, "dashboard/dashboard.html", context)


@login_required
def instruments_list(request):
    import json
    from instruments.models import Instrument
    from market_data.models import LiveQuote

    qs = Instrument.objects.filter(is_active=True)
    filter_type = request.GET.get("filter", "")
    search_q = request.GET.get("q", "").strip()
    sort_by = request.GET.get("sort", "symbol")
    exchange_filter = request.GET.get("exchange", "")
    country_filter = request.GET.get("country", "")
    movers = request.GET.get("movers", "all").strip().lower()
    if movers not in MOVER_BUCKETS:
        movers = "all"

    if filter_type == "watchlist":
        qs = qs.filter(is_watchlist=True)
    elif filter_type in ("stock", "forex", "commodity", "index", "etf", "crypto", "bond"):
        qs = qs.filter(asset_class=filter_type)
    if search_q:
        qs = qs.filter(
            models.Q(symbol__icontains=search_q) |
            models.Q(name__icontains=search_q) |
            models.Q(sector__icontains=search_q)
        )
    if exchange_filter:
        qs = qs.filter(exchange__iexact=exchange_filter)
    if country_filter:
        qs = qs.filter(country__iexact=country_filter)

    instruments = list(qs.order_by("asset_class", "symbol"))

    # Attach live quotes
    quotes_map = {}
    try:
        for lq in LiveQuote.objects.select_related("instrument").all():
            quotes_map[lq.instrument_id] = lq
    except Exception:
        pass

    # Whether each row's MARKET is open right now — fourteen timezones
    # computed once for the whole table, then a dict lookup per row. A
    # price table with no market state on it reads every frozen Friday
    # close as a live print; this is the row-level answer, kept live by
    # sv-market-status.js repainting every [data-market-session] element.
    try:
        from core.exchange_status import get_exchange_status, market_status_for
        _ex_status = get_exchange_status()
    except Exception:
        _ex_status, market_status_for = None, None

    items = []
    for inst in instruments:
        q = quotes_map.get(inst.id)
        market = None
        if _ex_status is not None:
            try:
                market = market_status_for(inst.asset_class, inst.exchange,
                                           _status=_ex_status)
            except Exception:
                market = None
        items.append({
            "market": market,
            "id": inst.id,
            "symbol": inst.symbol,
            "name": inst.name,
            "asset_class": inst.asset_class,
            # Em-dash for unknown, like every other cell in the row — the
            # price columns were converted and these were left, so an
            # unpriced instrument rendered five em-dashes and two hyphens.
            "exchange": inst.exchange or "—",
            "currency": inst.currency,
            "sector": inst.sector or "—",
            "country": inst.country or "—",
            "is_watchlist": inst.is_watchlist,
            "last": float(q.last) if q else None,
            "change_pct": float(q.change_pct) if q else None,
            "bid": float(q.bid) if q and q.bid else None,
            "ask": float(q.ask) if q and q.ask else None,
            "volume": q.volume if q else None,
            "source": q.source if q else "—",
            "updated_at": q.updated_at.isoformat() if q else None,
        })

    # Summary stats — counted over the whole selection, before the mover
    # bucket narrows it, so the strip keeps reporting the full split while
    # WINNERS or LOSERS is showing one end of it. change_pct is None only
    # when the instrument has no LiveQuote row at all: unknown is its own
    # bucket and is never rolled in with the losers.
    total = len(items)
    with_quotes = sum(1 for i in items if i["last"] is not None)
    gainers = sum(1 for i in items if i["change_pct"] is not None and i["change_pct"] > 0)
    losers = sum(1 for i in items if i["change_pct"] is not None and i["change_pct"] < 0)
    unpriced = sum(1 for i in items if i["change_pct"] is None)

    if movers == "winners":
        items = [i for i in items if i["change_pct"] is not None and i["change_pct"] > 0]
    elif movers == "losers":
        items = [i for i in items if i["change_pct"] is not None and i["change_pct"] < 0]

    # Sort
    if movers != "all" and request.GET.get("sort", "symbol") == "symbol":
        # A bucket carries its own order — biggest gain / worst loss first —
        # because the operator arriving from a market-anomaly alert wants the
        # interesting end, not the alphabet. An explicit ?sort= is the
        # operator overruling that, so it still wins below.
        #
        # Tested for the DEFAULT value rather than for the key's absence:
        # the Search form's Sort By select is always a successful control,
        # so every search submitted sort=symbol whether or not the operator
        # touched it — which silently cancelled the bucket's ordering and
        # put the alphabet back.
        items.sort(key=lambda x: x["change_pct"], reverse=(movers == "winners"))
    elif sort_by == "change":
        # Unknown is not a rank: an instrument with no quote sank to the
        # middle of the board as if it were flat at 0.00%. It sits out the
        # ranking at the bottom instead, in both directions.
        items.sort(key=lambda x: (x["change_pct"] is None, -(x["change_pct"] or 0)))
    elif sort_by == "change_asc":
        items.sort(key=lambda x: (x["change_pct"] is None, x["change_pct"] or 0))
    elif sort_by == "volume":
        items.sort(key=lambda x: x["volume"] or 0, reverse=True)
    elif sort_by == "name":
        items.sort(key=lambda x: x["name"].lower())

    shown = len(items)

    # Unique exchanges and countries for filter dropdowns. The explicit
    # order_by is load-bearing: Instrument.Meta.ordering is
    # ["asset_class", "symbol"], and those columns ride into the GROUP BY of
    # a values_list().distinct(), which would hand back one row per
    # (exchange, asset_class, symbol) — the same exchange over and over.
    active = Instrument.objects.filter(is_active=True)
    exchanges = sorted(
        active.exclude(exchange="").order_by("exchange")
        .values_list("exchange", flat=True).distinct()
    )
    countries = sorted(
        active.exclude(country="").order_by("country")
        .values_list("country", flat=True).distinct()
    )

    return render(request, "dashboard/instruments_list.html", {
        "page_id": "instruments",
        "items": items,
        "items_json": json.dumps(items, default=str),
        "filter": filter_type,
        "search_q": search_q,
        "sort_by": sort_by,
        "exchange_filter": exchange_filter,
        "country_filter": country_filter,
        "movers": movers,
        "total": total,
        "shown": shown,
        "with_quotes": with_quotes,
        "gainers": gainers,
        "losers": losers,
        "unpriced": unpriced,
        "exchanges": exchanges,
        "countries": countries,
    })


@login_required
def market_quotes(request):
    """Redirect to unified instruments & quotes page."""
    # The query string rides along so a shared or alert-borne deep link like
    # /quotes/?movers=losers still opens on the bucket it names — the bounce
    # used to drop it and land everyone on the unfiltered board.
    target = reverse("instruments_list")
    # Re-encoded from the parsed QueryDict rather than echoed from
    # QUERY_STRING, so nothing hand-crafted reaches the Location header raw.
    query = request.GET.urlencode()
    return redirect(f"{target}?{query}" if query else target)


@login_required
def economic_calendar(request):
    from market_data.models import EconomicEvent
    from datetime import timedelta
    from django.utils import timezone
    from collections import defaultdict
    import json

    now = timezone.now()
    month_ahead = now + timedelta(days=30)
    week_ahead = now + timedelta(days=7)

    all_events = list(
        EconomicEvent.objects.filter(datetime__gte=now - timedelta(days=7))
        .order_by("datetime")[:200]
    )
    upcoming = [e for e in all_events if e.datetime >= now]
    past_week = [e for e in all_events if e.datetime < now]

    # Group events by date for calendar view
    events_by_date = defaultdict(list)
    for ev in all_events:
        events_by_date[ev.datetime.date().isoformat()].append({
            "time": ev.datetime.strftime("%H:%M"),
            "title": ev.title,
            "country": ev.country,
            "impact": ev.impact,
            "forecast": ev.forecast or "-",
            "previous": ev.previous or "-",
            "actual": ev.actual or "-",
            "currency": ev.currency_affected or "-",
        })

    # Outlook summary cards
    high_impact_week = len([e for e in upcoming if e.impact in ("high", "HIGH") and e.datetime <= week_ahead])
    high_impact_month = len([e for e in upcoming if e.impact in ("high", "HIGH") and e.datetime <= month_ahead])
    total_week = len([e for e in upcoming if e.datetime <= week_ahead])
    total_month = len(upcoming)

    # Countries with most events
    country_counts = defaultdict(int)
    for e in upcoming:
        country_counts[e.country] += 1
    top_countries = sorted(country_counts.items(), key=lambda x: -x[1])[:5]

    ctx = {
        "page_id": "calendar",
        "events": all_events,
        "events_by_date_json": json.dumps(events_by_date),
        "high_impact_week": high_impact_week,
        "high_impact_month": high_impact_month,
        "total_week": total_week,
        "total_month": total_month,
        "top_countries": top_countries,
        "today": now.date().isoformat(),
    }
    return render(request, "dashboard/economic_calendar.html", ctx)


@login_required
def signals_list(request):
    """Phase 63 — enriched signals dashboard.

    Adds: 24h fresh count · direction donut · score-distribution histogram ·
    asset-class breakdown · win-rate by signal_type (Phase 1 grading) ·
    urgency mix.
    """
    from collections import defaultdict
    from datetime import timedelta
    from django.utils import timezone as _tz
    from signals.models import Signal

    active_only = request.GET.get("active") == "1"
    qs = Signal.objects.select_related("instrument").order_by("-created_at")
    if active_only:
        qs = qs.filter(is_active=True)
    active_qs = Signal.objects.filter(is_active=True)

    n_active = active_qs.count()
    n_bull = active_qs.filter(direction="bullish").count()
    n_bear = active_qs.filter(direction="bearish").count()
    avg_score = active_qs.aggregate(avg=Avg("score"))["avg"] or 0

    # 24h freshness.
    cutoff_24h = _tz.now() - timedelta(hours=24)
    n_24h = Signal.objects.filter(created_at__gte=cutoff_24h).count()
    n_high_urg = active_qs.filter(urgency__in=["high", "critical"]).count()

    # Score-distribution histogram (active signals, bucketed by 0.1).
    score_buckets = [0] * 10  # 0.0-0.1, 0.1-0.2, ..., 0.9-1.0
    for s in active_qs.only("score"):
        idx = min(9, max(0, int(float(s.score or 0) * 10)))
        score_buckets[idx] += 1
    score_max = max(score_buckets) if score_buckets else 0
    # Bars for _partials/chart_bars.html. The tone carries the conviction
    # band, which is the reason this histogram is on the page at all — the
    # template used to re-derive it from the loop index.
    score_bars = [
        {
            "label": "{:.1f}".format(i / 10),
            "value": n,
            "display": "{} signal{}".format(n, "" if n == 1 else "s"),
            "note": "score {:.1f}–{:.1f}".format(i / 10, (i + 1) / 10),
            "tone": "red" if i < 4 else ("gold" if i < 7 else "accent"),
        }
        for i, n in enumerate(score_buckets)
    ]

    # Direction donut.
    n_neutral = max(0, n_active - n_bull - n_bear)
    direction_donut = []
    if n_bull > 0:
        direction_donut.append({"key": "bullish", "n": n_bull,
                                 "pct": round(n_bull / max(n_active, 1) * 100, 1)})
    if n_bear > 0:
        direction_donut.append({"key": "bearish", "n": n_bear,
                                 "pct": round(n_bear / max(n_active, 1) * 100, 1)})
    if n_neutral > 0:
        direction_donut.append({"key": "neutral", "n": n_neutral,
                                 "pct": round(n_neutral / max(n_active, 1) * 100, 1)})

    # Asset-class breakdown of active signals.
    by_class = (active_qs.values("instrument__asset_class")
                .annotate(n=Count("id")).order_by("-n"))
    asset_breakdown = [
        {"asset_class": r["instrument__asset_class"] or "other", "n": r["n"]}
        for r in by_class
    ]

    # Urgency mix.
    urgency_mix = list(active_qs.values("urgency")
                        .annotate(n=Count("id")).order_by("-n"))

    # Win rate by signal_type — uses Phase-1 self-grading on closed signals.
    closed = (Signal.objects
              .filter(is_active=False, realized_r__isnull=False)
              .exclude(signal_type=""))
    type_stats: dict = defaultdict(lambda: {"n": 0, "wins": 0, "total_r": 0.0})
    for s in closed.only("signal_type", "realized_r"):
        d = type_stats[s.signal_type]
        d["n"] += 1
        if float(s.realized_r) > 0:
            d["wins"] += 1
        d["total_r"] += float(s.realized_r)
    perf_by_type = []
    for t, d in type_stats.items():
        if d["n"] < 3:  # noise floor
            continue
        perf_by_type.append({
            "signal_type": t, "n": d["n"],
            "win_rate": round(d["wins"] / d["n"] * 100, 1),
            "avg_r": round(d["total_r"] / d["n"], 3),
            "total_r": round(d["total_r"], 2),
        })
    perf_by_type.sort(key=lambda r: r["avg_r"], reverse=True)

    return render(request, "dashboard/signals_list.html", {
        "page_id": "signals", "signals": qs[:100], "active_only": active_only,
        "active_count": n_active,
        "bullish_count": n_bull,
        "bearish_count": n_bear,
        "avg_score": "{:.2f}".format(avg_score),
        "n_24h": n_24h,
        "n_high_urg": n_high_urg,
        "score_buckets": score_buckets,
        "score_bars": score_bars,
        "score_max": score_max,
        "direction_donut": direction_donut,
        "asset_breakdown": asset_breakdown,
        "urgency_mix": urgency_mix,
        "perf_by_type": perf_by_type[:8],
    })


# ══ Strategies page ═══════════════════════════════════════════════════════
#
# "Why still 0 strategies?" — asked while twelve rules were running. This page
# led with `strategies.Strategy`: a multi-leg trade plan the wizard writes and
# NOTHING executes, of which a fresh install has none. Meanwhile the public
# landing page counts `RuleControl` as "strategies"
# (core/wall_facts._count_strategies), so the platform gave two different
# answers to one question, one on each side of the login. The promotion ladder
# leads now; the wizard's plans keep their own section, labelled as what they
# are.
#
# Every join between Signal / RuleControl / OpportunitySetup / AssetBotTrade is
# a STRING (`rule_name`), not a foreign key. There is no select_related to lean
# on, so each helper below does ONE grouped query for ALL rules and hands back
# a dict keyed by rule_name. The alternative — calling the pipeline's own
# per-rule helpers from inside the card loop — is a query per card.

# A stage is a VENUE, not a size. `signals.rule_actuator.stage_policy` spells
# this out: reading it as a size is what once let a PAPER rule size to zero,
# take no paper trade, and so never produce the evidence needed to leave paper.
# The page says it out loud because the word "small" invites the wrong reading.
_STAGE_VENUE = {
    "research": "signals only — no order is ever placed",
    "paper": "full nominal size, forced onto the paper venue",
    "live_small": "live venue, quarter size",
    "live_full": "live venue, full size",
}

# n=0 is a measured zero; a rate or an expectancy with no sample behind it is
# not measured at all, and renders as an em-dash rather than as 0.
_NO_RECORD = {"n": 0, "hits": 0, "expectancy": None, "hit_rate": None}


# ── Why a freshly seeded strategy does nothing ──────────────────────────────
#
# Two switches decide whether anything at all happens, and BOTH seed off:
# `OpportunitySetup.is_active` at False, `RuleControl.promotion_stage` at
# "research". That is the right default — nothing should reach an order because
# somebody ran a seeder — but it appeared on no page, so the sequence was:
# seed the pack, arm a strategy, watch nothing happen, and have no way to learn
# which of the two was holding it. `_trade_gates` below is what puts both on
# the card, with what each one stops and what clears it.


def _stage_verdict(stage):
    """`rule_actuator.stage_policy`, for a stage whose row this page already holds.

    Restated rather than called, and the restatement is deliberate:
    `stage_policy` takes a rule NAME and re-reads RuleControl, so calling it
    per card would add a query per rule to a function whose whole design is a
    fixed query budget. It is asserted equal to `stage_policy` for every stage
    — the unrecognised one included — in tests/test_pead_and_promotion.py, the
    same contract `RuleControl.running_q` keeps with the method it mirrors.

    The last branch is the one worth reading twice. A row carrying a stage the
    pipeline does not recognise is NOT blocked: `stage_policy` falls back to
    paper — may_trade True, forced to the paper venue — because failing all the
    way closed would wall off the paper evidence the ladder needs to promote
    anything. A page that drew it as "unrecognised, so nothing happens" would
    describe the opposite of what runs.
    """
    from signals.promotion_pipeline import STAGE_ORDER

    if stage not in STAGE_ORDER:
        return {"stage": stage, "known": False, "may_trade": True,
                "force_paper": True}
    if stage == "research":
        return {"stage": stage, "known": True, "may_trade": False,
                "force_paper": True}
    return {"stage": stage, "known": True, "may_trade": True,
            "force_paper": stage == "paper"}


def _trade_gates(ctrl, setup, now):
    """Can this rule place an order right now — and if not, what has to change.

    Returns {can_trade, venue, blockers, caveats, armed, stage_known}. Each
    blocker names the FIELD, what it stops, and the action that clears it;
    every blocker is listed rather than just the first, because clearing one
    switch on a rule the other also blocks changes nothing an operator can see.
    """
    verdict = _stage_verdict(ctrl.promotion_stage)
    # `setup is None` is not `is_active=False`. A rule whose conditions live in
    # engine code has no arming flag at all, and printing DISARMED for it would
    # invent a switch its operator cannot go and find.
    armed = None if setup is None else bool(setup.is_active)
    running = ctrl.is_effectively_active(now)

    # The chips name the CONSEQUENCE, not the flag, and deliberately so: the
    # card already carries a state chip reading PAUSED for a disarmed setup and
    # another reading Paused for an actuator pause, which are different things.
    # A third chip repeating either word would make the vocabulary worse; what
    # an operator needs from a glance is what STOPS, not which column holds it.
    blockers, caveats = [], []
    if armed is False:
        blockers.append({
            "chip": "NOT SCANNED",
            "field": "OpportunitySetup.is_active = False",
            "what": ("the scanner never evaluates this setup — scan_all_setups "
                     "reads is_active=True and consults nothing else — so it "
                     "writes no signal, and with no signal the gate above can "
                     "never fill either"),
            "fix": ("arm it on the opportunity setups page, or re-seed the "
                    "pack with --activate"),
        })
    if not verdict["may_trade"]:
        blockers.append({
            "chip": "NO ORDERS",
            "field": "RuleControl.promotion_stage = research",
            "what": ("stage_policy resolves research to may_trade=False and "
                     "the bot honours it twice: the entry is skipped as "
                     "stage-blocked, and this rule's signals are dropped from "
                     "the consensus before any headcount is taken"),
            "fix": ("clear the gate above and it promotes on the next ladder "
                    "pass, or promote it by hand from the promotion pipeline"),
        })
    if not running:
        if setup is None:
            blockers.append({
                "chip": "SIGNALS DROPPED",
                "field": "RuleControl.status = paused",
                "what": ("is_rule_active() is False, so the rule-engine lanes "
                         "drop every new signal this rule produces"),
                "fix": ("roll the pause back from rule controls, or wait for "
                        "paused_until to elapse"),
            })
        else:
            # A pause is NOT a blocker on a setup-backed rule, and the
            # asymmetry is real rather than an oversight: `is_rule_active` is
            # read where the rule engine writes signals and nowhere else.
            # `scan_all_setups` never consults it, `stage_policy` never
            # consults it, and `admin_allocator_multiplier` honours
            # weight_multiplier only when status == "reduced" — so this setup
            # keeps scanning, keeps publishing, and is sized at full. Drawing
            # the pause as a stop would be the page lying in the one direction
            # an operator cannot check.
            caveats.append(
                "paused by the actuator, which stops the rule-engine lanes — "
                "not this setup: the opportunity scanner does not read that "
                "flag, so it keeps scanning and publishing")
    if verdict["force_paper"] and verdict["may_trade"]:
        caveats.append("orders are forced onto the paper venue whatever the "
                       "bot config's own mode says")

    # No `venue` key here on purpose: the card already carries one, and two
    # places computing the same sentence is how they come to disagree.
    return {"can_trade": not blockers, "armed": armed,
            "stage_known": verdict["known"],
            "blockers": blockers, "caveats": caveats}


# Evolution forks the RuleControl row ONLY — the OpportunitySetup holding the
# conditions still belongs to the parent — so this page resolves a fork's name
# to that parent with `core.fork_names.fork_parent`, the same parser
# `promotion_evidence` resolves evaluators with. A fork and its evidence gate
# therefore cannot disagree about who its parent is.


def _rule_stats_map(rule_names, since_by_rule=None):
    """Closed-signal stats per rule, in ONE grouped query.

    Mirrors `promotion_pipeline._stats_since` filter for filter — same
    is_active / outcome / realized_r exclusions, same "hit" definition, same
    rounding — because a card that shows different numbers from the ones the
    ladder judges on is worse than a card that shows nothing.

    `since_by_rule` reproduces the per-rule `expired_at >= stage_entered_at`
    window the PAPER and LIVE_SMALL gates read, as one OR'd filter rather than
    one query per rule.
    """
    import operator
    from functools import reduce
    from django.db.models import Q
    from signals.models import Signal

    qs = (Signal.objects
          .filter(rule_name__in=rule_names, is_active=False)
          .exclude(outcome="").exclude(realized_r__isnull=True))
    if since_by_rule:
        qs = qs.filter(reduce(operator.or_, [
            Q(rule_name=name, expired_at__gte=since)
            for name, since in since_by_rule.items()
        ]))
    # Signal.Meta.ordering is ["-created_at"], and a default ordering rides
    # into the GROUP BY of a values().annotate() — which would return one row
    # per signal instead of one per rule. Clearing it on the selected column
    # first is the fix.
    rows = (qs.values("rule_name").order_by("rule_name")
              .annotate(n=Count("id"),
                        hits=Count("id", filter=Q(outcome="hit_target")),
                        expectancy=Avg("realized_r")))
    out = {}
    for r in rows:
        n = r["n"]
        out[r["rule_name"]] = {
            "n": n,
            "hits": r["hits"],
            "expectancy": (float(r["expectancy"])
                           if r["expectancy"] is not None else None),
            "hit_rate": round(r["hits"] / n, 4) if n else None,
        }
    return out


def _n_gates(conditions):
    """How many of a setup's conditions are gates (preconditions)."""
    return sum(1 for c in (conditions or [])
               if isinstance(c, dict) and c.get("gate"))


def _n_scoring(conditions):
    """How many actually vote — the population the composite averages over."""
    return sum(1 for c in (conditions or [])
               if isinstance(c, dict) and not c.get("gate"))


def _cond_weight(cond):
    """A condition's weight, in the type `scan_setup` reads it as.

    The scanner does `float(cond.get("weight", 1.0))` and does NOT catch a
    failure there, so a hand-authored `"1,5"` or `null` is not a weight of 1.0
    — it is a condition the scanner raises on. The page reports that as
    unknown rather than printing a number nothing will ever multiply by.
    """
    try:
        w = float(cond.get("weight", 1.0))
    except (TypeError, ValueError):
        return {"weight": None, "weight_display": "—"}
    return {"weight": w, "weight_display": "{:g}".format(w)}


def _fmt_gate(value, unit):
    """A criterion value in the unit the ladder states it in."""
    if value is None:
        return "—"
    if unit == "rate":
        return "{:.0f}%".format(value * 100)
    if unit == "R":
        return "{:+.2f}R".format(value)
    if unit == "d":
        return "{:d}d".format(int(value))
    return "{:d}".format(int(value))


def _gate_check(label, value, need, unit=""):
    """One promotion criterion, plus what fraction of it is satisfied.

    `ratio` is what the stage bar fills to, so it has to respect the two
    shapes of criterion the ladder uses. A count creeps toward its gate and
    fills proportionally. "Expectancy ≥ 0R" does not: a rule losing money is
    not 90% of the way to being trusted with capital, it is at zero.
    """
    if value is None:
        return {"label": label, "unit": unit, "met": False, "ratio": 0.0,
                "known": False, "value": None, "need": need,
                "value_display": "—", "need_display": _fmt_gate(need, unit)}
    met = value >= need
    ratio = max(0.0, min(1.0, value / need)) if need > 0 else (1.0 if met else 0.0)
    return {"label": label, "unit": unit, "met": met, "ratio": ratio,
            "known": True, "value": value, "need": need,
            "value_display": _fmt_gate(value, unit),
            "need_display": _fmt_gate(need, unit)}


def _next_gate(ctrl, record, stage_record, days_in_stage):
    """What this rule is waiting for before it moves up a venue.

    Thresholds are imported from the pipeline rather than restated, so
    retuning a gate moves the page with it instead of leaving the page lying.
    """
    from signals import promotion_pipeline as pp
    from signals.promotion_evidence import LIVE_STAGES

    stage = ctrl.promotion_stage
    target = pp._next_stage(stage) if stage in pp.STAGE_ORDER else None
    if target is None:
        return {
            "target": None, "checks": [], "progress": None,
            "summary": ("top of the ladder — nothing above live_full"
                        if stage == pp.STAGE_ORDER[-1]
                        else "not on the ladder — no recognised stage"),
        }

    if stage == "research":
        checks = [
            _gate_check("closed trades", record["n"],
                        pp.PROMO_RESEARCH_TO_PAPER_MIN_N),
            _gate_check("hit rate", record["hit_rate"],
                        pp.PROMO_RESEARCH_TO_PAPER_MIN_HIT_RATE, unit="rate"),
            _gate_check("expectancy", record["expectancy"],
                        pp.PROMO_RESEARCH_TO_PAPER_MIN_EXPECTANCY, unit="R"),
        ]
    elif stage == "paper":
        # No usable baseline means the pipeline falls back to "just be
        # positive" — show the fallback, not a threshold that isn't applied.
        base = ctrl.stage_baseline_expectancy
        need = (base * pp.PROMO_PAPER_TO_LIVE_SMALL_RETENTION
                if base and base > 0 else 0.0)
        checks = [
            _gate_check("days in paper", days_in_stage,
                        pp.PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS, unit="d"),
            _gate_check("closed since entry", stage_record["n"],
                        pp.PROMO_PAPER_TO_LIVE_SMALL_MIN_N),
            _gate_check("expectancy", stage_record["expectancy"], need, unit="R"),
        ]
    elif stage == "live_small":
        base = ctrl.stage_baseline_expectancy
        need = (base * pp.PROMO_LIVE_SMALL_TO_FULL_RETENTION
                if base and base > 0 else 0.0)
        checks = [
            _gate_check("days at small", days_in_stage,
                        pp.PROMO_LIVE_SMALL_TO_FULL_MIN_DAYS, unit="d"),
            _gate_check("closed since entry", stage_record["n"],
                        pp.PROMO_LIVE_SMALL_TO_FULL_MIN_N),
            _gate_check("expectancy", stage_record["expectancy"], need, unit="R"),
        ]
    else:
        checks = []

    progress = int(round(min(c["ratio"] for c in checks) * 100)) if checks else None
    unmet = [c for c in checks if not c["met"]]
    if unmet:
        blocker = min(unmet, key=lambda c: c["ratio"])
        summary = "{} of {} {}".format(
            blocker["value_display"], blocker["need_display"], blocker["label"])
    elif target in LIVE_STAGES:
        # Meeting the ladder's criteria is not the last gate before real
        # money: promotion_evidence requires out-of-sample walk-forward
        # evidence too. Saying "ready" here would be a promise the pipeline
        # has not made.
        summary = "criteria met — awaiting out-of-sample (walk-forward) evidence"
    else:
        summary = "criteria met — promotes on the next ladder pass"

    return {"target": target, "target_label": target.replace("_", " "),
            "target_venue": _STAGE_VENUE.get(target, ""),
            "checks": checks, "progress": progress, "summary": summary}


def _promotion_ladder(now=None):
    """Every RuleControl row as a card, grouped by promotion stage.

    Query budget is FIXED at 7 (2 when no rule exists), whatever the rule
    count: rules, setups, all-time stats, in-stage stats, signal recency, bot
    trades, mutations. Nothing in the per-card loop below touches the database.
    The setup query runs even with no rules, because an armed setup with no
    RuleControl row still scans — see the comment on it below.
    """
    from collections import defaultdict
    from django.db.models import Max, Q
    from bot_program.asset_models import AssetBotTrade
    from signals import promotion_pipeline as pp
    from signals.models import Signal
    from signals.models_control import RuleControl, RuleMutation
    from signals.models_opportunity import OpportunitySetup

    now = now or timezone.now()
    empty = {"stage_groups": [], "n_rules": 0, "n_running": 0, "n_by_stage": {},
             "n_live_venue": 0, "n_can_trade": 0,
             "n_setups": 0, "n_armed": 0, "unbacked_setups": [], "ladder_n": 0,
             "ladder_hit_rate": None, "ladder_expectancy": None,
             "stage_venues": [{"key": s, "label": s.replace("_", " "),
                               "venue": _STAGE_VENUE[s]}
                              for s in pp.STAGE_ORDER]}

    rules = list(RuleControl.objects.order_by("rule_name"))          # 1
    names = [r.rule_name for r in rules]

    # A fork inherits its parent's conditions, so pull the parents' setups
    # too — bounded, because a fork of a fork of a fork is still a name.
    wanted = set(names)
    for name in names:
        cur = name
        for _ in range(4):
            parent = fork_parent(cur)
            if not parent:
                break
            wanted.add(parent)
            cur = parent

    # `| Q(is_active=True)` is what keeps an armed setup that no rule backs on
    # this page. `scan_all_setups` iterates OpportunitySetup.objects.filter(
    # is_active=True) and never consults RuleControl, and `stage_policy` reads
    # a missing RuleControl row as PAPER / may_trade=True — so such a setup
    # scans every pass, writes signals, and can place paper orders at full
    # nominal size. Fetching only rule-backed names hid it from the one page
    # that claims to show what is running and dropped it from the "n of m
    # setups armed" denominator too. Both creation paths that arm a setup
    # (hq_create_opportunity_setup, hq_toggle_opportunity_setup on a mined
    # candidate) write no companion RuleControl, and no post_save does either,
    # so the omission is permanent rather than a startup race.
    setups = {                                                       # 2
        s.name: s for s in OpportunitySetup.objects
        .filter(Q(name__in=wanted) | Q(is_active=True)).order_by("name")
        .annotate(n_flags=Count("flags"))
    }
    # `n not in wanted` implies is_active — an inactive setup only reaches
    # this dict through the name branch.
    # Gates are counted apart here for the same reason as on the cards: a gate
    # is a universe check the scanner skips the setup on, not a leg that votes.
    unbacked = [{"name": s.name,
                 "direction": s.direction,
                 "asset_classes": ", ".join(s.asset_classes or []) or "any",
                 "min_match_score": s.min_match_score,
                 "horizon_days": s.suggested_horizon_days,
                 "n_scoring": _n_scoring(s.conditions),
                 "n_gates": _n_gates(s.conditions),
                 "n_flags": s.n_flags}
                for name, s in setups.items() if name not in wanted]

    if not rules:
        return {**empty, "unbacked_setups": unbacked,
                "n_setups": len(unbacked), "n_armed": len(unbacked)}

    # The RESEARCH gate reads all-time; the PAPER and LIVE_SMALL gates read
    # only what closed since the rule entered its current stage.
    record_by_rule = _rule_stats_map(names)                          # 3
    stage_record_by_rule = _rule_stats_map(names, since_by_rule={    # 4
        r.rule_name: (r.stage_entered_at or r.created_at) for r in rules})

    recency = {r["rule_name"]: r for r in                            # 5
               Signal.objects.filter(rule_name__in=names)
               .values("rule_name").order_by("rule_name")
               .annotate(last_at=Max("created_at"),
                         n_live=Count("id", filter=Q(is_active=True)))}

    # What the bot actually executed under this rule — the stage claim and
    # the trade log disagreeing is the failure this column exists to expose.
    trades = {r["rule_name"]: r for r in                              # 6
              AssetBotTrade.objects
              .filter(rule_name__in=names, status="CLOSED",
                      realized_r__isnull=False)
              .values("rule_name").order_by("rule_name")
              .annotate(n=Count("id"), expectancy=Avg("realized_r"),
                        n_real=Count("id", filter=Q(paper=False)))}

    forks_open, forks_applied = defaultdict(list), defaultdict(list)  # 7
    for parent, forked, state, score, method, changed in (
            RuleMutation.objects.filter(parent_rule__in=names)
            .order_by("parent_rule", "-proposed_at")
            .values_list("parent_rule", "forked_rule", "state",
                         "proposed_score", "score_method",
                         "parameters_changed")):
        row = {"forked": forked, "method": method,
               "changed": ", ".join(changed or []) or "—",
               "score": ("{:+.3f}".format(score) if score is not None else "—")}
        if state == "proposed":
            forks_open[parent].append(row)
        elif state == "applied":
            forks_applied[parent].append(row)

    by_stage = defaultdict(list)
    ladder_n = ladder_hits = n_can_trade = 0
    ladder_r_sum = 0.0
    for ctrl in rules:
        name = ctrl.rule_name
        record = record_by_rule.get(name, _NO_RECORD)
        stage_record = stage_record_by_rule.get(name, _NO_RECORD)
        entered = ctrl.stage_entered_at or ctrl.created_at
        days_in_stage = (now - entered).days

        ladder_n += record["n"]
        ladder_hits += record["hits"]
        if record["expectancy"] is not None:
            ladder_r_sum += record["expectancy"] * record["n"]

        # A fork with no setup of its own borrows the definition it was
        # forked from — the card says so rather than claiming the fork
        # authored it.
        setup, source, cur = setups.get(name), name, name
        for _ in range(4):
            if setup is not None:
                break
            parent = fork_parent(cur)
            if not parent:
                break
            setup, source, cur = setups.get(parent), parent, parent

        setup_ctx = None
        if setup is not None:
            conditions = []
            for cond in (setup.conditions or []):
                if not isinstance(cond, dict):
                    continue
                params = cond.get("params") or {}
                conditions.append({
                    "kind": cond.get("kind", "?"),
                    "detail": " · ".join(
                        "{}={}".format(k, v) for k, v in params.items()),
                    # A gate is a PRECONDITION, not a leg. `scan_setup` returns
                    # {"skipped": True, "reason": "gate_failed"} before it
                    # touches either accumulator, so a gate adds nothing to the
                    # score AND nothing to the denominator, and no amount of
                    # evidence can outvote it. Rendering one as "×1.0" told the
                    # operator two false things about the only gated setup the
                    # platform ships: that the universe check was ~29% of a
                    # vote, and that the composite divides by 3.5 when the
                    # scanner divides by 2.5.
                    "gate": bool(cond.get("gate")),
                    **_cond_weight(cond),
                })
            scoring = [c for c in conditions if not c["gate"]]
            # A weight the scanner cannot float() is a weight this page must
            # not invent one for: `float(cond.get("weight", 1.0))` raises in
            # scan_setup, so the honest total is unknown, not a partial sum.
            known = all(c["weight"] is not None for c in scoring)
            weight_sum = sum(c["weight"] for c in scoring) if known else None
            setup_ctx = {
                "name": setup.name,
                "inherited": source != name,
                "is_active": setup.is_active,
                "direction": setup.direction,
                "asset_classes": ", ".join(setup.asset_classes or []) or "any",
                "min_match_score": setup.min_match_score,
                "horizon_days": setup.suggested_horizon_days,
                "n_flags": setup.n_flags,
                "conditions": conditions,
                # Counted apart, because "3 conditions" over two legs and a
                # gate describes a setup that does not exist.
                "n_scoring": len(scoring),
                "n_gates": len(conditions) - len(scoring),
                # The denominator `scan_setup` actually divides by, so the
                # operator can reproduce the threshold instead of deriving a
                # different one from the same card.
                "weight_sum": weight_sum,
                "weight_sum_display": ("—" if weight_sum is None
                                       else "{:g}".format(weight_sum)),
            }

        trade = trades.get(name)
        seen = recency.get(name)
        # `setup`, not `setup_ctx`: the arming flag belongs to the row, and a
        # fork reading its parent's definition is armed by the parent's switch
        # — which is the switch an operator would have to go and flip.
        gates = _trade_gates(ctrl, setup, now)
        if gates["can_trade"]:
            n_can_trade += 1
        by_stage[ctrl.promotion_stage].append({
            "rule": name,
            "stage": ctrl.promotion_stage,
            "stage_display": ctrl.get_promotion_stage_display(),
            # The fallback used to be "", which drew an empty line on the one
            # card that most needs a sentence. `stage_policy` reads a stage it
            # does not recognise as PAPER — may_trade, forced to the paper
            # venue — so the honest fallback says that rather than nothing.
            "venue": _STAGE_VENUE.get(
                ctrl.promotion_stage,
                "unrecognised stage — stage_policy falls back to the paper "
                "venue, so it trades on paper at full nominal size"),
            "status": ctrl.status,
            "status_display": ctrl.get_status_display(),
            "paused_until": ctrl.paused_until,
            "weight": ctrl.weight_multiplier,
            "allocator_weight": ctrl.allocator_weight,
            "entered_at": entered,
            "days_in_stage": days_in_stage,
            "baseline": ctrl.stage_baseline_expectancy,
            "parent": fork_parent(name),
            "record": record,
            "hit_rate_display": ("{:.0f}%".format(record["hit_rate"] * 100)
                                 if record["hit_rate"] is not None else None),
            "expectancy_display": ("{:+.2f}R".format(record["expectancy"])
                                   if record["expectancy"] is not None else None),
            "stage_record": stage_record,
            "setup": setup_ctx,
            "last_signal_at": seen["last_at"] if seen else None,
            "n_live_signals": seen["n_live"] if seen else 0,
            "n_trades": trade["n"] if trade else 0,
            "n_trades_real": trade["n_real"] if trade else 0,
            "trade_expectancy": ("{:+.2f}R".format(trade["expectancy"])
                                 if trade and trade["expectancy"] is not None
                                 else None),
            "forks_open": forks_open.get(name, []),
            "forks_applied": forks_applied.get(name, []),
            "gate": _next_gate(ctrl, record, stage_record, days_in_stage),
            # Both seeded-off switches, resolved the way the engine resolves
            # them, with the action that clears each — see `_trade_gates`.
            "trade": gates,
        })

    # STAGE_ORDER, not the dict's insertion order: the page reads bottom of
    # the ladder to top, the same direction risk to capital increases in.
    stage_groups = [{"key": stage,
                     "label": stage.replace("_", " "),
                     "venue": _STAGE_VENUE[stage],
                     "cards": by_stage.get(stage, [])}
                    for stage in pp.STAGE_ORDER]
    # A rule carrying a stage the pipeline does not recognise is a data fault,
    # not a rule to hide.
    for stage in sorted(set(by_stage) - set(pp.STAGE_ORDER)):
        stage_groups.append({"key": stage, "label": stage.replace("_", " "),
                             "venue": "unrecognised stage — not on the ladder",
                             "cards": by_stage[stage]})

    # `wanted`, not a one-level parent set: it is the same reachability walk
    # the card loop uses to inherit a fork's definition, so every setup that
    # renders on a card is a setup this denominator counts. A fork of a fork
    # used to fall between the two.
    backed = {n: s for n, s in setups.items() if n in wanted}
    n_by_stage = {g["key"]: len(g["cards"]) for g in stage_groups}
    return {
        "stage_groups": stage_groups,
        "n_rules": len(rules),
        # The population the headband cell means by "STRATEGIES n active",
        # printed on the page that cell deep-links to so the two numbers can be
        # seen to reconcile instead of reading as a contradiction. This is the
        # model's own `is_effectively_active()` and not `status == "active"`:
        # a reduced rule still signals, and a paused rule whose paused_until
        # has elapsed is running again even though nothing writes the column
        # back.
        "n_running": sum(1 for r in rules if r.is_effectively_active(now)),
        "n_by_stage": n_by_stage,
        # Summed here rather than with |add: in the template — the filter
        # returns "" on a missing key, so a fresh install printed a blank
        # where a 0 belongs.
        "n_live_venue": (n_by_stage.get("live_small", 0)
                         + n_by_stage.get("live_full", 0)),
        # Ladder rules only, and the strip cell says so. The unbacked setups
        # below can also trade — `stage_policy` reads a missing row as paper —
        # but they are not on the ladder, and folding them in would make this
        # number irreconcilable with the stage counts beside it.
        "n_can_trade": n_can_trade,
        # The unbacked ones are armed by construction (an inactive setup never
        # enters `unbacked`), so they raise numerator and denominator alike —
        # the counter stops hiding them without claiming they are on the ladder.
        "n_setups": len(backed) + len(unbacked),
        "n_armed": (len([s for s in backed.values() if s.is_active])
                    + len(unbacked)),
        "unbacked_setups": unbacked,
        "ladder_n": ladder_n,
        "ladder_hit_rate": (round(ladder_hits / ladder_n * 100, 1)
                            if ladder_n else None),
        "ladder_expectancy": (round(ladder_r_sum / ladder_n, 3)
                              if ladder_n else None),
        "stage_venues": empty["stage_venues"],
    }


def _hand_built_plans(status_filter=""):
    """`strategies.Strategy` — the wizard's multi-leg trade plans.

    Kept, and kept honest: nothing in the platform executes one. They are a
    record of a plan the operator wrote. Deleting the section would lose that
    record; leading with it is what made an install with twelve running rules
    report zero strategies.
    """
    from strategies.models import Strategy

    # Strategy.Meta.ordering is ["-created_at"], which rides into the GROUP BY
    # of a values().annotate() and returns one row per plan — order on the
    # selected column first.
    counts = {r["status"]: r["n"] for r in
              Strategy.objects.values("status").order_by("status")
              .annotate(n=Count("id"))}
    qs = Strategy.objects.order_by("-created_at").prefetch_related("legs")
    if status_filter:
        qs = qs.filter(status=status_filter)
    return {"plans": list(qs[:50]), "n_plans": sum(counts.values())}


@login_required
def strategies_list(request):
    """What is running, at what stage, and how it is doing.

    Two models answer to the word "strategy" and they are not the same animal.
    `signals.RuleControl` rows are what the engine runs and the Phase-8 ladder
    promotes. `strategies.Strategy` rows are trade plans the wizard writes and
    nothing executes. This page leads with the first and labels the second.
    """
    status_filter = request.GET.get("status") or ""
    ctx = {"page_id": "strategies", "status_filter": status_filter}
    ctx.update(_promotion_ladder())
    ctx.update(_hand_built_plans(status_filter))
    return render(request, "dashboard/strategies_list.html", ctx)


@login_required
def strategy_detail(request, pk):
    from strategies.models import Strategy
    strategy = get_object_or_404(Strategy.objects.prefetch_related("legs__instrument", "adjustments"), pk=pk)
    return render(request, "dashboard/strategy_detail.html", {"page_id": "strategies", "strategy": strategy})


@login_required
def news_feed(request):
    """Phase 63 — enriched news & sentiment dashboard.

    Adds: 24h volume · sentiment distribution donut · top mentioned tickers ·
    sentiment trend (24h hourly buckets) · urgency mix · top sources.
    """
    from collections import Counter, defaultdict
    from datetime import timedelta
    from django.utils import timezone as _tz
    from scraping.models import NewsArticle

    qs = NewsArticle.objects.prefetch_related("ai_affected_instruments")
    articles = list(qs.order_by("-published_at")[:100])
    now = _tz.now()
    cutoff_24h = now - timedelta(hours=24)

    # prefetch_related(None): the clone inherits the instruments prefetch
    # from `qs`, and this branch never reads them — on a busy news day
    # that was thousands of m2m rows fetched and instantly discarded.
    recent_24h = list(qs.filter(published_at__gte=cutoff_24h)
                        .prefetch_related(None)
                        .only("ai_sentiment_score", "ai_urgency", "source",
                              "published_at"))
    n_24h = len(recent_24h)

    bull = sum(1 for a in recent_24h if a.ai_sentiment_score is not None
               and a.ai_sentiment_score > 0.2)
    bear = sum(1 for a in recent_24h if a.ai_sentiment_score is not None
               and a.ai_sentiment_score < -0.2)
    neut = sum(1 for a in recent_24h if a.ai_sentiment_score is not None
               and -0.2 <= a.ai_sentiment_score <= 0.2)
    unscored = n_24h - bull - bear - neut

    sentiment_donut = []
    for k, v in [("bullish", bull), ("neutral", neut), ("bearish", bear),
                  ("unscored", unscored)]:
        if v > 0:
            sentiment_donut.append({
                "key": k, "n": v,
                "pct": round(v / max(n_24h, 1) * 100, 1),
            })

    scored = [a for a in recent_24h if a.ai_sentiment_score is not None]
    avg_sent = sum(a.ai_sentiment_score for a in scored) / len(scored) if scored else 0

    # Sentiment trend — 24 hourly buckets, mean sentiment per bucket.
    hourly_sum: dict = defaultdict(float)
    hourly_n: dict = defaultdict(int)
    for a in scored:
        h = int((now - a.published_at).total_seconds() // 3600)
        if 0 <= h < 24:
            hourly_sum[h] += a.ai_sentiment_score
            hourly_n[h] += 1
    sent_trend = []
    for h in range(23, -1, -1):  # oldest first → newest
        if hourly_n[h]:
            avg = round(hourly_sum[h] / hourly_n[h], 3)
            sent_trend.append({
                "hour": h,
                "avg": avg,
                "n": hourly_n[h],
                "label": "-{}h".format(h),
                "value": avg,
                "display": "{:+.2f}".format(avg),
                "note": "{} article{}".format(hourly_n[h],
                                              "" if hourly_n[h] == 1 else "s"),
            })
        else:
            # An hour with nothing scored is UNKNOWN, not neutral. It used to
            # be stored as avg 0, which the chart drew as a measured zero on
            # the mid-line — a flat reading the platform never took.
            sent_trend.append({
                "hour": h, "avg": None, "n": 0,
                "label": "-{}h".format(h),
                "value": None,
                "display": "—",
                "note": "nothing scored this hour",
            })
    sent_max = max((abs(r["avg"]) for r in sent_trend if r["avg"] is not None),
                   default=0)

    # Urgency mix.
    urg_counter: Counter = Counter()
    for a in recent_24h:
        if a.ai_urgency:
            urg_counter[a.ai_urgency] += 1
    urgency_mix = [{"urgency": u, "n": n}
                    for u, n in urg_counter.most_common()]

    # Top mentioned tickers (uses prefetched affected instruments on the head).
    ticker_counter: Counter = Counter()
    for a in articles[:60]:  # head of feed only
        for inst in a.ai_affected_instruments.all():
            ticker_counter[inst.symbol] += 1
    top_tickers = [{"symbol": s, "n": n}
                    for s, n in ticker_counter.most_common(8)]

    # Top sources (24h).
    src_counter: Counter = Counter(a.source for a in recent_24h if a.source)
    top_sources = [{"source": s, "n": n}
                    for s, n in src_counter.most_common(6)]

    n_critical = sum(1 for a in recent_24h if a.ai_urgency in ("critical", "high"))

    return render(request, "dashboard/news_feed.html", {
        "page_id": "news",
        "articles": articles,
        "n_24h": n_24h,
        "n_critical": n_critical,
        "bull_24h": bull,
        "bear_24h": bear,
        "avg_sent_24h": round(avg_sent, 3),
        "sentiment_donut": sentiment_donut,
        "sent_trend": sent_trend,
        "sent_max": sent_max,
        "urgency_mix": urgency_mix,
        "top_tickers": top_tickers,
        "top_sources": top_sources,
    })


# ═════════════════════════════════════════════════════════════════════════
# THE NUMBERS THAT MOVE — /portfolio/ and /positions/
# ─────────────────────────────────────────────────────────────────────────
# Both pages computed everything once, at render, and nothing recomputed it.
# An operator watching a position work read whatever the page said at load,
# however many fills and quotes ago that was — on the two screens that hold
# their money.
#
# Everything below feeds BOTH the first render and the live refresh, because
# the refresh endpoints re-enter the SAME view body and re-render the SAME
# template through a bare shell. Two formatters for one number is how a page
# ends up disagreeing with itself after the first push, and a refresh that
# renders its own markup is how an em-dash becomes a zero on the second read.
# ═════════════════════════════════════════════════════════════════════════

# An em-dash means NOT MEASURED. Never 0: a confident "+0.00" under
# UNREALIZED P&L is a claim that the book is flat, which is a completely
# different statement from "no quote arrived for anything in it".
LIVE_DASH = "—"

# The wrapper the refresh endpoints render the page through: it emits the
# content block and nothing else, so a fragment carries the live regions in
# exactly the markup the full page rendered.
LIVE_SHELL = "dashboard/_live_shell.html"


def _as_float(value):
    """Decimal | float | str | None → float | None. None survives as None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _live_tone(value):
    """Colour class for a signed reading; blank for zero and for unknown."""
    if value is None:
        return ""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return ""


def _live_num(value, spec="{:+,.2f}"):
    """A measurement, or the em-dash when there was nothing to measure."""
    number = _as_float(value)
    if number is None:
        return LIVE_DASH
    return spec.format(number)


def _live_cell(text, sub="", tone="", title=""):
    """One stat-strip cell, already formatted for display.

    Pre-formatted on purpose: the em-dash rule then lives in ONE place
    instead of in eight template `{% if x is not None %}` branches, each of
    which is another chance for a cell to quietly print a zero.
    """
    return {"text": text, "sub": sub, "tone": tone, "title": title}


def _initial_stop_map(rows):
    """{row key: the stop each open position OPENED with}.

    R is measured against the risk the trade was actually taken with. The
    CURRENT stop is the wrong denominator — a trailing stop rewrites it, so
    risk and P&L become the same quantity and every trailed winner scores
    ~1.0R. bot_program.manual_close._initial_stop is the platform's one
    reader of metadata["initial_stop_loss"] (bot_grading applies the same
    rule), so the R this page prints is the R the close dialog promises and
    the R the ledger eventually books.

    One extra query over a trade set unified_open_positions has already
    fetched: the normalised bot row carries no metadata at all, and the
    alternative was a second copy of the union in this module.
    """
    out = {}
    ids = [r.trade_id for r in rows
           if getattr(r, "source", "") == "bot"
           and getattr(r, "trade_id", None)]
    if not ids:
        return out
    try:
        from bot_program.manual_close import _initial_stop
        from bot_program.models import AssetBotTrade
        for trade in AssetBotTrade.objects.filter(id__in=ids).only(
                "id", "stop_loss", "metadata"):
            out[f"bot-{trade.id}"] = _initial_stop(trade)
    except Exception as e:
        # Every R then renders an em-dash, which is the honest reading of "we
        # could not find the risk". Silence here would have been a column of
        # dashes with no explanation anywhere.
        logger.warning("Initial stops unavailable, R reads as unmeasured: %s",
                       e, exc_info=True)
    return out


def _live_row(row, stops):
    """One open position, shaped the way the tables already read it, plus R.

    A dict and not the model instance: UnifiedPosition declares __slots__, so
    an R multiple cannot be hung on a bot row at all, and half a book
    carrying the field would be worse than none of it. The keys mirror the
    attribute names the templates use, so the row markup did not have to
    move to gain a live column.

    P&L arrives already marked by _open_book and is never read off
    Position.unrealized_pnl: that column defaults to 0 and its only writer is
    an hourly task on one book, so on a row this page renders it is a
    permanent, confident +0.00.
    """
    source = getattr(row, "source", "") or "position"
    ident = getattr(row, "trade_id", None) or getattr(row, "pk", None)
    key = f"{'bot' if source == 'bot' else 'pos'}-{ident}"

    entry = _as_float(row.entry_price)
    mark = _as_float(row.current_price)
    stop = stops.get(key)
    if stop is None:
        stop = _as_float(getattr(row, "stop_loss", None))
    sign = -1 if (row.direction or "").lower() in ("short", "sell") else 1

    # Every term has to be there. An R with no stop behind it is not 0.0R —
    # it is a position whose risk was never recorded, and 0.0R reads as a
    # scratch trade sitting exactly at entry.
    r_mult = None
    if (mark is not None and entry
            and stop is not None and abs(entry - stop) > 1e-12):
        r_mult = round((mark - entry) * sign / abs(entry - stop), 2)

    pnl = _as_float(row.unrealized_pnl)
    pct = _as_float(row.unrealized_pnl_pct)
    # The SECOND percentage: the same P&L against the capital the row
    # actually ties up — "+0.42%" on a forex leg is true about the
    # notional and silent about the operator's cash, which moved 30x
    # that. The suppression for cash-funded classes lives at the SOURCE
    # (services.pnl_on_capital_pct returns None when capital == notional
    # by construction) — a numeric comparison here only ever matched on
    # exact equality of two independently rounded values.
    cap_pct = _as_float(getattr(row, "pnl_on_capital_pct", None))
    instrument = getattr(row, "instrument", None)
    return {
        "key": key,
        "instrument": instrument,
        "symbol": getattr(instrument, "symbol", "") or "",
        "asset_class": getattr(instrument, "asset_class", "") or "other",
        "direction": row.direction,
        "quantity": row.quantity,
        "entry_price": row.entry_price,
        "current_price": row.current_price,
        "stop_loss": row.stop_loss,
        "initial_stop": stop,
        "take_profit": row.take_profit,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pct,
        "last_text": _live_num(mark, "{:,.4f}"),
        "pnl_text": _live_num(pnl),
        "pnl_tone": _live_tone(pnl),
        "pct_text": _live_num(pct, "{:+.2f}%"),
        "pct_tone": _live_tone(pct),
        "cap_pct": cap_pct,
        "cap_pct_text": (_live_num(cap_pct, "{:+.2f}%")
                         if cap_pct is not None else ""),
        "r_multiple": r_mult,
        "r_text": _live_num(r_mult, "{:+.2f}R"),
        "r_tone": _live_tone(r_mult),
        "r_title": (
            f"Marked at {mark:,.4f} against an entry of {entry:,.4f} and the "
            f"stop this position opened with ({stop:,.4f})."
            if r_mult is not None else
            "No R: this position has no live mark, or no entry stop was ever "
            "recorded, so there is no risk to divide the move by."),
        "strategy": getattr(row, "strategy", None),
        "opened_at": row.opened_at,
        "trade_id": getattr(row, "trade_id", None),
        "status": getattr(row, "status", ""),
        "paper": getattr(row, "paper", True),
        "source": source,
    }


def _live_open_book(user, portfolio):
    """Every open position, both books, marked to live quotes, with R.

    views_command._open_book is the platform's one union-and-mark: it reads
    portfolio.Position AND bot_program.AssetBotTrade — exposure genuinely
    lives in both, and reading one of them showed an empty book to an
    operator holding trades — and it re-prices the legacy half in memory.
    Reusing it is what stops this page and the Operations Center quoting two
    different P&Ls for the same position.

    Returns (rows, n_priced, unrealized, deployed). unrealized and deployed
    are None when nothing could be priced: an unpriced book is unknown, not
    flat.
    """
    from .views_command import _open_book
    objects, n_priced, unrealized, deployed = _open_book(user, portfolio)
    stops = _initial_stop_map(objects)
    return (objects, [_live_row(r, stops) for r in objects],
            n_priced, unrealized, deployed)


def _closed_stats(closed_positions):
    """Win rate / profit factor over the closed book, honestly.

    A close nothing could price is held OUT of the split rather than booked
    as a loss, which is what `float(p.unrealized_pnl or 0) <= 0` did to every
    one of them — each unmeasurable row silently dragging the win rate down.
    Where there is nothing to measure the answer is None, and None renders as
    an em-dash: a 0.0% win rate over zero trades is a claim that every trade
    lost, and a 0.00 profit factor reads as a broken system rather than an
    unmeasured one.
    """
    graded = [p for p in closed_positions if p.unrealized_pnl is not None]
    winning = [p for p in graded if float(p.unrealized_pnl) > 0]
    losing = [p for p in graded if float(p.unrealized_pnl) < 0]
    n_graded = len(graded)
    gross_win = sum(float(p.unrealized_pnl) for p in winning)
    gross_loss = abs(sum(float(p.unrealized_pnl) for p in losing))
    return {
        "graded": graded,
        "n_closed": len(closed_positions),
        "n_graded": n_graded,
        "n_ungraded": len(closed_positions) - n_graded,
        "n_winning": len(winning),
        "n_losing": len(losing),
        "win_rate": (round(len(winning) / n_graded * 100, 1)
                     if n_graded else None),
        "realized": (round(sum(float(p.unrealized_pnl) for p in graded), 2)
                     if n_graded else None),
        "avg_win": round(gross_win / len(winning), 2) if winning else None,
        "avg_loss": round(-gross_loss / len(losing), 2) if losing else None,
        # With one side of the ratio empty the ratio does not exist yet —
        # it is neither 0 nor 99.99.
        "profit_factor": (round(gross_win / gross_loss, 2)
                          if gross_loss > 0 and winning else None),
    }


def _exposure_split(deployed, cash, n_open):
    """(deployed value, cash %, deployed %) — None where unknown.

    With positions open and none of them priced the split is NOT "100% cash":
    that is a claim of no exposure at all, on a book that is carrying some.
    """
    if n_open == 0:
        return 0.0, 100.0, 0.0
    if deployed is None:
        return None, None, None
    total = deployed + cash
    if total <= 0:
        return deployed, None, None
    return (deployed, round(cash / total * 100, 1),
            round(deployed / total * 100, 1))


def _live_page(request, template, context, live_only):
    """Render a page — or only its live regions — from one template."""
    context["live_only"] = live_only
    context["base_template"] = LIVE_SHELL if live_only else "base.html"
    return render(request, template, context)


def _capital_or_none(user):
    """capital_summary, fenced: a page must render even when the pools
    cannot be read — None keys already render as em-dashes."""
    from portfolio.services import capital_summary
    try:
        return capital_summary(user)
    except Exception:  # noqa: BLE001
        logger.debug("capital summary unavailable", exc_info=True)
        return None


def _render_portfolio(request, live_only):
    """Phase 63 — enriched portfolio dashboard, now live.

    Equity sparkline · allocation donut · win/loss/profit-factor stats ·
    Sharpe 30d · top contributors/detractors — and a strip whose numbers move
    with the market instead of with the page load.
    """
    from collections import defaultdict
    from datetime import timedelta
    from django.utils import timezone as _tz
    from portfolio.services import (get_or_create_default_portfolio,
                                    live_book_value,
                                    unified_closed_positions)
    from portfolio.models import PortfolioSnapshot
    # THE USER'S OWN BOOK. This read the shared "Main" one, for a reason
    # that has since stopped being true: Main was the only book the
    # pipeline maintained, so a per-user book here drew an empty equity
    # curve over never-marked rows. `recalculate_exposure` and
    # `create_daily_snapshot` now walk EVERY portfolio, so a per-user book
    # is marked and snapshotted like any other.
    #
    # Leaving it on Main had become the page contradicting itself: the
    # headline value folded in the user's AssetBotTrades while the equity
    # curve, the drawdown and the snapshot table underneath came from
    # Main's bot-free series — one screen describing two books. And Main
    # is not anybody's portfolio: it is fed by a single global eToro API
    # key with no user attached, so on an install with more than one
    # operator it was showing both of them the same account and calling it
    # theirs.
    portfolio = get_or_create_default_portfolio(user=request.user)

    # BOTH books, marked to live quotes: legacy Position rows plus the
    # AssetBotTrades that every interactive path (bots, TAKE TRADE,
    # LONG/SHORT) actually writes — the taken trade used to be invisible on
    # this page by construction.
    _objects, open_rows, n_priced, unrealized, deployed = _live_open_book(
        request.user, portfolio)
    closed_positions = unified_closed_positions(request.user, portfolio)
    stats = _closed_stats(closed_positions)

    n_open = len(open_rows)
    cash = float(portfolio.cash_available or 0)
    deployed_value, cash_pct, exposure_pct = _exposure_split(
        deployed, cash, n_open)
    # TOTAL VALUE, measured on this read. The union `_live_open_book` already
    # performed is handed straight over, so the strip's headline and the table
    # under it are two readings of ONE re-pricing rather than two of their own.
    book = live_book_value(request.user, portfolio,
                           book=(_objects, n_priced, unrealized, deployed))

    # 30d Sharpe / Sortino approximation, from the snapshot series.
    cutoff_30d = _tz.now().date() - timedelta(days=30)
    snaps_30d = list(PortfolioSnapshot.objects.filter(
        portfolio=portfolio, date__gte=cutoff_30d).order_by("date"))
    sharpe_30d = sortino_30d = None
    rets = [float(s.daily_pnl_pct or 0) for s in snaps_30d]
    if len(rets) >= 5:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        std = var ** 0.5
        if std > 0:
            sharpe_30d = round((mean / std) * (252 ** 0.5), 2)
        downside = [r for r in rets if r < 0]
        if downside:
            d_var = sum(r ** 2 for r in downside) / len(downside)
            d_std = d_var ** 0.5
            if d_std > 0:
                sortino_30d = round((mean / d_std) * (252 ** 0.5), 2)

    latest_snapshot = (PortfolioSnapshot.objects.filter(portfolio=portfolio)
                        .order_by("-date").first())
    # A book with no snapshot has no measured drawdown. "0.00%" under a MAX
    # DRAWDOWN label reads as "this book never lost money".
    max_drawdown = (float(latest_snapshot.max_drawdown)
                    if latest_snapshot is not None
                    and latest_snapshot.max_drawdown is not None else None)

    priced_note = (f"{n_priced} of {n_open} open positions carry a live quote."
                   if n_open else "No open positions in either book.")
    strip = {
        "value": _live_cell(
            _live_num(book.value, "{:,.2f}"),
            # The sub-label carries the currency AND, when the total left rows
            # out, that it is short of the whole book — the one place on this
            # page where a partial sum could otherwise pass for a complete one.
            sub=(f"{portfolio.currency} · partial" if book.partial
                 else portfolio.currency),
            title=(f"Cash plus everything open across both books, marked to "
                   f"live quotes on this read — not the stored "
                   f"current_value column, which only an hourly task on the "
                   f"legacy book ever wrote. {book.coverage}")),
        "cash": _live_cell(
            _live_num(portfolio.cash_available, "{:,.2f}"),
            sub=(f"{cash_pct:.1f}% of the book" if cash_pct is not None
                 else "share unknown — nothing could be priced"),
            title="Cash available to deploy, and its share of cash plus "
                  "marked exposure."),
        # ALLOCATED and FREE — the two halves of "can I take another
        # trade", which the page could not answer. It showed a total, a
        # cash column and a notional exposure, and none of those is the
        # capital actually locked: an FX position carries thirty times the
        # money it ties up, so reading the exposure as the allocation says
        # an operator is fully committed when most of the book is idle.
        "allocated": _live_cell(
            _live_num(book.allocated, "{:,.2f}"),
            sub=(f"{book.allocated_pct:.1f}% of the book"
                 if book.allocated_pct is not None
                 else "share unknown — the book could not be valued"),
            title="Capital the open positions actually tie up, margin-aware "
                  "— the same number the risk gates size against, not the "
                  "notional they carry."),
        "free": _live_cell(
            _live_num(book.free, "{:,.2f}"),
            tone=("down" if (book.free_pct is not None and book.free_pct < 10)
                  else ""),
            sub=(f"{book.free_pct:.1f}% left to deploy"
                 if book.free_pct is not None
                 else "share unknown — the book could not be valued"),
            title="What is left after the open book. Never negative: more "
                  "margin than the book is worth is a margin call, not a "
                  "negative pile of cash."),
        "exposure": _live_cell(
            _live_num(deployed_value, "{:,.2f}"),
            sub=(f"{exposure_pct:.1f}% deployed" if exposure_pct is not None
                 else "share unknown — nothing could be priced"),
            title=f"Notional at live marks across both books. {priced_note}"),
        "open": _live_cell(
            str(n_open), sub="positions",
            title="Open positions across the legacy book and the bot book."),
        "unrealized": _live_cell(
            _live_num(unrealized), tone=_live_tone(unrealized),
            sub="across open positions",
            title=(f"Marked to live quotes, never read off the stored "
                   f"column. {priced_note}")),
        "win_rate": _live_cell(
            _live_num(stats["win_rate"], "{:.1f}%"),
            sub=(f"{stats['n_winning']}W / {stats['n_losing']}L · "
                 f"{stats['n_graded']} closed"),
            title=(f"Over the {stats['n_graded']} closed positions that could "
                   f"be priced; {stats['n_ungraded']} could not and are held "
                   f"out rather than counted as losses.")),
        "profit_factor": _live_cell(
            _live_num(stats["profit_factor"], "{:.2f}"),
            tone=("up" if stats["profit_factor"] is not None
                  and stats["profit_factor"] >= 1 else ""),
            sub=(f"avg win {_live_num(stats['avg_win'])} · avg loss "
                 f"{_live_num(stats['avg_loss'])}"),
            title="Gross win divided by gross loss over the closed book."),
        "sharpe": _live_cell(
            _live_num(sharpe_30d, "{:.2f}"), tone=_live_tone(sharpe_30d),
            sub=(f"sortino {sortino_30d:.2f}" if sortino_30d is not None
                 else f"{len(rets)} daily snapshots · 5 needed"),
            title="Annualised from daily snapshot returns over 30 days."),
        "max_dd": _live_cell(
            _live_num(max_drawdown, "{:.2f}%"),
            tone="down" if max_drawdown else "",
            sub="all-time low watermark",
            title=("From the most recent portfolio snapshot."
                   if latest_snapshot is not None
                   else "No snapshot has ever been taken for this book, so "
                        "drawdown is not measured.")),
    }

    # Allocation donut — by asset class from current open positions + cash.
    # Marked value where a mark exists, entry cost otherwise: a slice sized
    # at zero because no quote arrived would silently shrink the book.
    alloc_by_class = defaultdict(float)
    for p in open_rows:
        price = (p["current_price"] if p["current_price"] is not None
                 else p["entry_price"])
        alloc_by_class[p["asset_class"]] += abs(
            float(p["quantity"] or 0) * float(price or 0))
    alloc_by_class["cash"] = cash
    alloc_total = sum(alloc_by_class.values()) or 1.0
    allocation = sorted(
        # "key" is the donut partial's contract; asset_class stays for the
        # table that reads the same rows.
        ({"asset_class": k, "key": k, "value": v,
          "pct": round(v / alloc_total * 100, 1)}
         for k, v in alloc_by_class.items() if v > 0),
        key=lambda r: r["value"], reverse=True,
    )

    context = {
        "page_id": "portfolio", "portfolio": portfolio,
        # Pools / used / free / cash — the money question, answered by ONE
        # service so this page, the positions page and the headband popups
        # can never quote three different answers. See
        # portfolio.services.capital_summary for what the two economies are.
        "capital": _capital_or_none(request.user),
        "strip": strip,
        "open_positions_count": n_open,
        "open_positions": open_rows[:8],
        "n_priced": n_priced,
        # What the strip's TOTAL VALUE actually covered. The number itself is
        # in strip.value; these two say whether it is the whole book, so the
        # page can print the shortfall instead of leaving it in a tooltip.
        "book_coverage": book.coverage,
        "book_partial": book.partial,
        "book_unpriced": book.n_unpriced,
        "allocation": allocation,
        # Some rows could not be priced, so the donut is drawn from entry
        # cost for those slices — the card says so rather than implying the
        # ring is marked to market throughout.
        "allocation_partial": n_open > 0 and n_priced < n_open,
    }

    if not live_only:
        # The slow half: daily snapshots and the closed book. It does not
        # move between two fills, so the refresh does not pay for it.
        equity_points = [float(s.total_value) for s in snaps_30d]
        ranked = sorted(stats["graded"],
                        key=lambda p: float(p.unrealized_pnl), reverse=True)
        context.update({
            "snapshots": PortfolioSnapshot.objects.filter(
                portfolio=portfolio).order_by("-date")[:30],
            "equity_points": equity_points,
            "equity_min": min(equity_points) if equity_points else 0,
            "equity_max": max(equity_points) if equity_points else 0,
            # Only actual winners and actual losers. The old slices took the
            # top and bottom three whatever their sign, so a book of three
            # losses listed all three as "top contributors".
            "top_contributors": [p for p in ranked[:3]
                                 if float(p.unrealized_pnl) > 0],
            "top_detractors": [p for p in reversed(ranked[-3:])
                               if float(p.unrealized_pnl) < 0],
        })

    return _live_page(request, "dashboard/portfolio_overview.html",
                      context, live_only)


@login_required
def portfolio_overview(request):
    return _render_portfolio(request, live_only=False)


@login_required
def portfolio_live(request):
    """The moving regions of /portfolio/, re-rendered.

    Same view body, same template, a bare shell instead of base.html — so a
    refreshed cell can never say something the first render would not have
    said, and a position nothing can price stays an em-dash on the second
    read as well as the first.

    The page asks for this on the /ws/eye/ fill events the shell already
    re-dispatches, plus a slow sweep for the marks those events say nothing
    about. It is never on a fast unconditional timer.
    """
    return _render_portfolio(request, live_only=True)


def _pos_distance(mark, level, resolves_below):
    """(percent of the mark, already-through) for one price level.

    `resolves_below` says which side of the mark resolves that level — a
    long's stop and a short's target both sit below it. Without that the
    card cannot tell a stop about to fill from one comfortably clear, and
    the two most opposite states a position can be in would both read as
    "0.4% away".
    """
    if level is None or not mark:
        return "", False
    through = (mark <= level) if resolves_below else (mark >= level)
    return "{:.2f}".format(abs(level - mark) / abs(mark) * 100), through


def _pos_num(value):
    """A float, or None. Decimal, str and None all arrive here."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pos_fmt(value, digits=None):
    """A number as the card should print it, or "" for one we do not have.

    Empty string, never "0" and never "None": the row's data attributes are
    read by sv-position-card.js, which renders an absent attribute as an
    em-dash. A zero here would be indistinguishable from a measured zero,
    and "None" is the string that used to be painted loss-red in the table.

    digits=None means "pick the precision from the magnitude", which is what
    prices need: this book holds instruments quoted at 60000 and instruments
    quoted at 0.000012 in the same table, and a fixed four decimals prints
    the second one as a flat 0 — a price of zero on a position that is very
    much alive.
    """
    f = _pos_num(value)
    if f is None:
        return ""
    if digits is None:
        a = abs(f)
        digits = 2 if a >= 100 else (4 if a >= 1 else 8)
    text = "{:.{}f}".format(f, digits)
    # Strip trailing zeros only AFTER a decimal point. Unconditional
    # rstrip("0") eats the zeros of an INTEGER: at digits=0 a leverage of
    # 30 printed as "3", 100 as "1", 20 as "2". Harmless on a price, which
    # always has a fractional part, and silently wrong on anything whole.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _pos_money(value):
    """A currency amount as the card prints it, or "" for one we do not have.

    Separate from _pos_fmt because money is not a price: it is always two
    places and always grouped. _pos_fmt strips trailing zeros — right for a
    stop at 0.00001, wrong for a committed capital of "1540" where the eye
    needs "1,540.00" to read it as money rather than as a quantity.
    """
    f = _pos_num(value)
    return "" if f is None else "{:,.2f}".format(f)


# Asset classes whose qty x entry is a LEVERED notional rather than capital
# the account actually put up. sizing.MAX_NOTIONAL_FRACTION allows forex to
# run to 400% of equity precisely because the leverage sits at the broker,
# so printing qty x entry as "committed" would overstate what this position
# cost by up to 4x. What was actually committed is margin, and margin is a
# broker-side number this platform never records — so it renders as the
# em-dash and the levered notional is labelled as the exposure it is.
_POS_LEVERED_CLASSES = {"forex"}


def _pos_value_per_unit(trade):
    """Base-currency money per price point per unit, for one trade.

    The SAME derivation portfolio.services uses to mark the row — by calling
    it, not by reproducing it. The two copies drifted within a day: the
    correction that taught the options test to match the platform's plural
    spelling landed in one of them, so a multiplier-less options row would
    have been denominated 100x apart in two numbers printed on the same
    card. The card's percentage has to divide the card's own currency
    figures, which it can only do if one function answers this.
    """
    from portfolio.services import value_per_unit
    return value_per_unit(trade)


def _pos_exit_cost(trade, mark, qty_abs, vpu):
    """The paper round trip this close is already modelled to pay, in money.

    bot_program.manual_close._exit_fill is the one place that decides the
    price a close actually books at — a paper exit is charged half the round
    trip adversely by _close_trade, so the confirm dialog quotes the P&L at
    that FILL and not at the raw mark. The card has to charge the operator
    the same number or "what will this make me" gets a third answer: the
    table's, the card's, and the dialog's.

    None for a live trade: the cost there is the broker's and is not
    modelled anywhere, which is a gap and renders as one.
    """
    if trade is None or not trade.paper or not mark or not qty_abs:
        return None
    try:
        from bot_program.manual_close import _exit_fill
        fill = _exit_fill(trade, float(mark))
    except Exception as e:  # noqa: BLE001
        # A hand-edited extras['cost_bps'] must cost one line on one card,
        # not the positions page.
        logger.warning("Paper exit cost unavailable for trade #%s: %s",
                       getattr(trade, "id", "?"), e)
        return None
    return abs(float(mark) - float(fill)) * qty_abs * vpu





def _pos_modelled_margin(asset_class: str, notional):
    """Capital a levered position ties up, per the platform's own table.

    None when there is no notional to scale — an unpriced row has no
    margin to state, and inventing one would put a number under a
    position nobody could value.
    """
    if notional is None:
        return None
    try:
        from bot_program.manual_trade import CAPITAL_USE_FRACTION
    except Exception:  # noqa: BLE001
        return None
    frac = CAPITAL_USE_FRACTION.get(asset_class)
    return None if not frac else float(notional) * frac


def _pos_leverage(asset_class: str) -> str:
    """How many times its own capital a position of this class carries.

    Read off `manual_trade.CAPITAL_USE_FRACTION`, the platform's single
    record of margin — the same table the risk gates size against — so the
    card cannot drift from the gate. "1" is a real answer and not a
    missing one: a spot position settles in full and carries exactly its
    own money.

    "" only when the class is unknown, because a leverage nobody can
    establish must not be printed as 1.
    """
    if not asset_class:
        return ""
    try:
        from bot_program.manual_trade import CAPITAL_USE_FRACTION
    except Exception:  # noqa: BLE001
        return ""
    frac = CAPITAL_USE_FRACTION.get(asset_class, 1.0)
    if not frac or frac <= 0:
        return ""
    return _pos_fmt(1.0 / frac, 0)


def _pos_committed_pct(committed, trade):
    """This position's capital as a share of the pool it came out of.

    "4,800" means nothing on its own. "48% of the pool" is the sentence an
    operator sizes by, and it is the one number that says whether a book is
    concentrated without them having to divide anything in their head.

    "" when there is no pool to divide by — a legacy Position row belongs to
    no bot config and has no capital pool, and inventing one would put a
    confident percentage under a number nobody set.
    """
    cfg = getattr(trade, "config", None) if trade is not None else None
    try:
        capital = float(getattr(cfg, "capital", 0) or 0)
    except (TypeError, ValueError):
        return ""
    if not committed or capital <= 0:
        return ""
    return _pos_fmt(float(committed) / capital * 100, 1)


def _position_card_details(user, positions):
    """One dict per position with everything the hover card shows that the
    ROW cannot carry — aligned with `positions`, same order.

    The positions table renders portfolio.services.UnifiedPosition, a
    __slots__-bound shape that deliberately exposes only the columns the
    table prints. Every fact the card exists to answer "why is this position
    on, and what is it doing" with lives elsewhere: the reason the engine
    wrote at the decision, the composite score, the stop the trade OPENED
    with (the only correct R denominator once a trail has rewritten
    stop_loss), the venue, the broker order, the originating Signal and its
    sub-scores, the tax lot's cost basis. Gathered here in four bounded
    queries plus a cached spark lookup rather than per row in the template,
    which would be an N+1 that grows with the book.

    A row this cannot enrich — a portfolio.Position from the shared book,
    with no AssetBotTrade behind it — gets the same dict with empty values.
    The card then degrades to em-dashes and drops its two actions, which is
    the honest rendering: that row has no forensics page and nothing in the
    platform can flatten it.
    """
    from django.core.cache import cache
    from django.utils.timesince import timesince
    from bot_program.models import AssetBotTrade
    # The R denominator rule is not restated here. bot_grading, the close
    # dialog and this card must agree on what 1R was, and the one place
    # that decides it is manual_close — a fourth copy is how the card ends
    # up promising an R the ledger never books.
    from bot_program.manual_close import _initial_stop, _risk_dollars
    from bot_program.tax_lot_models import TaxLot
    from core.context_ui import _recent_closes
    from instruments.models import Instrument
    from signals.models import Signal

    trade_ids = [tid for tid in
                 (getattr(p, "trade_id", None) for p in positions) if tid]
    # Scoped by config__user, not filtered after the fetch: another user's
    # trade is not "hidden" from the card, it is not fetched at all.
    trades = {t.id: t for t in AssetBotTrade.objects.filter(
        id__in=trade_ids, config__user=user).select_related("config")} \
        if trade_ids else {}

    # ── The signal behind each trade ───────────────────────────────────
    # metadata["signal_id"] is authoritative (manual TAKE TRADE records it).
    # A bot entry has none, so the fallback is the newest signal on the same
    # symbol from the same rule at or before the entry — the same join the
    # forensics page makes, bounded so a large book cannot walk the table.
    def _signal_id(trade):
        raw = (trade.metadata or {}).get("signal_id")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    wanted = {sid for sid in (_signal_id(t) for t in trades.values()) if sid}
    by_id = {s.id: s for s in Signal.objects.filter(id__in=wanted)
             .select_related("instrument")} if wanted else {}
    unresolved = [t for t in trades.values() if _signal_id(t) not in by_id]
    pool = []
    if unresolved:
        pool = list(Signal.objects.filter(
            instrument__symbol__in={t.symbol for t in unresolved})
            .select_related("instrument").order_by("-created_at")[:200])

    def _signal_for(trade):
        hit = by_id.get(_signal_id(trade))
        if hit is not None:
            return hit
        # No rule to match on — a hand-taken entry, or a row from before
        # rule_name existed. The newest signal on the symbol is NOT evidence
        # this trade saw, and attributing it would fabricate the provenance
        # the card exists to show. metadata["signal_id"] is the only path in
        # for those, and its absence is an honest blank.
        if not trade.rule_name:
            return None
        for s in pool:
            if s.instrument.symbol != trade.symbol:
                continue
            if trade.rule_name and s.rule_name != trade.rule_name:
                continue
            if trade.opened_at and s.created_at > trade.opened_at:
                continue
            return s
        return None

    # ── Cost basis: the lot this trade opened, if the ledger tracked one ──
    lots = {}
    if trade_ids:
        for lot in TaxLot.objects.filter(
                source_trade_id__in=trade_ids, user=user).order_by("-opened_at"):
            lots.setdefault(lot.source_trade_id, lot)

    # ── 12-bar sparks, cached 300s per symbol ─────────────────────────
    # Same renderer and the same cache window the headband popups use: the
    # shape moves daily and is not worth a bar query per position per load.
    symbols = {getattr(p.instrument, "symbol", "") for p in positions
               if getattr(p, "instrument", None)}
    symbols.discard("")
    sparks, missing = {}, []
    for sym in symbols:
        hit = cache.get("pos:spark:" + sym)
        if hit is None:
            missing.append(sym)
        else:
            sparks[sym] = hit
    if missing:
        inst_ids = dict(Instrument.objects.filter(symbol__in=missing)
                        .values_list("symbol", "id"))
        for sym in missing:
            closes = _recent_closes(inst_ids[sym]) if sym in inst_ids else []
            sparks[sym] = closes
            cache.set("pos:spark:" + sym, closes, 300)

    details = []
    for p in positions:
        trade = trades.get(getattr(p, "trade_id", None))
        is_long = p.direction == "long"
        entry = _pos_num(p.entry_price)
        mark = _pos_num(p.current_price)
        stop = _pos_num(p.stop_loss)
        target = _pos_num(p.take_profit)
        istop = _pos_num(_initial_stop(trade)) if trade else None
        pnl = _pos_num(p.unrealized_pnl)

        stop_pct, stop_through = _pos_distance(mark, stop, is_long)
        target_pct, target_through = _pos_distance(mark, target, not is_long)

        # Where the mark stands between the ENTRY stop and the target. The
        # formula is direction-agnostic: for a short both differences are
        # negative and the ratio comes out the same way up.
        progress = ""
        if None not in (mark, istop, target) and target != istop:
            progress = "{:.1f}".format((mark - istop) / (target - istop) * 100)

        # What 1R is worth in the config's base currency — the SIZE of the
        # risk, which no column prints. The R MULTIPLE itself is deliberately
        # not computed here: _live_row already puts one in the row's own
        # cell, the card floats directly over that cell, and two R's on one
        # row is the one disagreement an operator cannot resolve. The
        # template hands the row's r_multiple straight to the card.
        risk = _risk_dollars(trade) if trade else 0.0

        signal = _signal_for(trade) if trade else None
        subs = ""
        if signal and isinstance(signal.sub_scores, dict):
            ranked = sorted(
                ((k, v) for k, v in signal.sub_scores.items()
                 if isinstance(v, (int, float))),
                key=lambda kv: -kv[1])[:4]
            subs = " · ".join("{} {:.2f}".format(k, v) for k, v in ranked)

        lot = lots.get(getattr(p, "trade_id", None))
        sym = getattr(p.instrument, "symbol", "") if getattr(p, "instrument", None) else ""
        spark = sparks.get(sym) or []
        paper = getattr(p, "paper", None)
        opened = p.opened_at

        # ── The money ────────────────────────────────────────────────────
        # The card had the R multiple and the P&L but never the two figures
        # every operator actually asks first: what did this cost me, and
        # what is it worth now. Both are denominated with the SAME
        # value_per_unit the row's P&L was marked with, so the percentage
        # the card prints divides the currency figures it prints.
        vpu = _pos_value_per_unit(trade)
        qty_abs = abs(_pos_num(p.quantity) or 0.0)
        asset_class = (getattr(trade, "asset_class", "") if trade else
                       getattr(getattr(p, "instrument", None), "asset_class", "")) or ""
        notional = qty_abs * entry * vpu if (entry and qty_abs) else None
        value_now = qty_abs * mark * vpu if (mark and qty_abs) else None
        # On a levered class qty x entry is exposure, not capital committed
        # — see _POS_LEVERED_CLASSES. The margin is the broker's number and
        # nothing here records it, so the card dashes it and names the
        # notional separately rather than passing one off as the other.
        levered = asset_class in _POS_LEVERED_CLASSES
        # The MODELLED margin on a levered row, not a dash.
        #
        # This used to be None on the grounds that the margin is the
        # broker's number and nothing records it. The platform does model
        # it — `manual_trade.CAPITAL_USE_FRACTION` is what the risk gates
        # and the book's own ALLOCATED figure size against — so dashing it
        # here left the one class where capital and exposure differ by 30x
        # as the one class whose capital the card would not name. It is
        # labelled `committed_kind = "margin"` so it is never read as cash
        # spent, and it is the same number the gate used.
        committed = (_pos_modelled_margin(asset_class, notional) if levered
                     else notional)
        exit_cost = _pos_exit_cost(trade, mark, qty_abs, vpu)
        if pnl is None:
            net_now = None
        elif exit_cost is not None:
            net_now = pnl - exit_cost
        elif trade is not None and not trade.paper:
            # A live close books at the mark; the broker's costs are the
            # broker's and are modelled nowhere, so this is the same number
            # the confirm dialog will quote.
            net_now = pnl
        else:
            net_now = None

        details.append({
            "symbol": sym,
            "side": "LONG" if is_long else "SHORT",
            "qty": _pos_fmt(p.quantity, 8),
            "status": getattr(p, "status", "") or "",
            "venue": "" if paper is None else ("PAPER" if paper else "LIVE"),
            "entry": _pos_fmt(entry),
            "mark": _pos_fmt(mark),
            "stop": _pos_fmt(stop),
            "target": _pos_fmt(target),
            "initial_stop": _pos_fmt(istop),
            "stop_pct": stop_pct,
            "stop_through": "1" if stop_through else "",
            "target_pct": target_pct,
            "target_through": "1" if target_through else "",
            "progress": progress,
            # How far the PRICE has travelled since entry, signed by the
            # price and not by the P&L. On a long the two agree; on a SHORT
            # they are opposites, and a mark 4% BELOW entry on a short is a
            # 4% fall that made money. Printing the P&L sign against a price
            # would have the card claim the market moved up when it moved
            # down.
            "mark_pct": (_pos_fmt((mark - entry) / entry * 100, 2)
                         if mark is not None and entry else ""),
            # LEVERAGE, as a fact rather than a control. Nothing on this
            # platform sets it — the broker does — but the platform models
            # it: `manual_trade.CAPITAL_USE_FRACTION` is the fraction of a
            # position's notional that its class actually ties up, and the
            # risk gates size against exactly that. An operator reading a
            # 4,800 exposure on a 160 margin is owed the number that
            # explains the gap.
            "leverage": _pos_leverage(asset_class),
            # What this one position ties up, as a share of the book it is
            # tying it up FROM. 4,800 means nothing without the pool it came
            # out of; "48% of the pool" is the sentence an operator sizes by.
            "committed_pct": _pos_committed_pct(committed, trade),
            "pnl": _pos_fmt(pnl, 2),
            "pnl_pct": _pos_fmt(p.unrealized_pnl_pct, 2),
            "risk": _pos_fmt(risk, 2) if risk else "",
            # ── The money block. Every one of these is "" when the platform
            # does not have it — the card renders "" as an em-dash, and a
            # fabricated 0 on a committed capital reads as a free position.
            "asset_class": asset_class,
            "committed": _pos_money(committed),
            # Which of the two questions the line above answers. "margin"
            # means the card must NOT print the notional as the cost.
            "committed_kind": "margin" if levered else "cost",
            # Only carried when it is a different quantity from the committed
            # capital — otherwise the card would print the same number twice
            # under two names, which is how a notional becomes a cost.
            "notional": _pos_money(notional) if levered else "",
            "value_now": _pos_money(value_now),
            "exit_cost": _pos_money(exit_cost),
            "net_now": _pos_money(net_now),
            "ccy": (trade.config.base_currency if trade and trade.config
                    else ""),
            # The BOOKED R off the ledger, not the live one the row computes
            # from the mark. Present only on a graded close; while the trade
            # is open the card shows live R and says so.
            "realized_r": ("{:+.2f}".format(trade.realized_r)
                           if trade and trade.realized_r is not None else ""),
            "age": timesince(opened).split(",")[0] if opened else "",
            "opened": (timezone.localtime(opened).strftime("%b %d %H:%M")
                       if opened else ""),
            "rule": (trade.rule_name if trade else
                     (p.strategy.name if p.strategy else "")) or "",
            # composite_score defaults to 0 and a hand-taken trade never
            # sets it, so 0 here means "never scored", not "scored zero" —
            # it renders as the em-dash rather than as a damning 0.00.
            "score": ("{:.2f}".format(trade.composite_score)
                      if trade and trade.composite_score else ""),
            "reason": (trade.reason or "") if trade else "",
            "order": (trade.broker_order_id or "") if trade else "",
            "basis": _pos_fmt(lot.cost_basis_per_unit) if lot else "",
            "lot_left": _pos_fmt(lot.qty_remaining, 8) if lot else "",
            "signal": (signal.title if signal else ""),
            "signal_dir": (signal.direction if signal else ""),
            "signal_score": ("{:.2f}".format(signal.score)
                             if signal and signal.score is not None else ""),
            "signal_sub": subs,
            # Eight places, matching PriceData's own — six flattens the
            # spark of anything quoted below a cent into a straight line.
            "spark": ",".join("{:.8f}".format(c) for c in spark),
            "spark_min": _pos_fmt(min(spark), 8) if spark else "",
            "spark_max": _pos_fmt(max(spark), 8) if spark else "",
            "spark_up": "1" if len(spark) > 1 and spark[-1] >= spark[0] else "",
            # The click destination. Only a bot trade has a timeline; a row
            # from the shared book has no page to open, and the card says so
            # rather than offering a link that 404s.
            "href": reverse("forensics_detail", args=[trade.id]) if trade else "",
        })
    return details


def _render_positions(request, live_only):
    """Phase 63 — enriched positions dashboard, now live.

    Open exposure totals, direction donut, asset-class breakdown, monthly
    P&L bars, profit factor, avg W/L — and an open book marked to live
    quotes, each row carrying the R multiple it is currently running at.
    """
    from collections import defaultdict
    from portfolio.services import (get_or_create_default_portfolio,
                                    unified_closed_positions)
    tab = request.GET.get("tab", "open")
    if tab not in ("open", "history"):
        tab = "open"
    # The user's own book, the same one /portfolio/ and the headband read.
    # Two position pages disagreeing about which book they are counting is
    # the bug this whole pass keeps finding in new places.
    portfolio = get_or_create_default_portfolio(user=request.user)
    # BOTH books: that shared Position book plus the user's AssetBotTrades —
    # a trade taken from a signal used to show in fills, the Op Center and
    # forensics but never here.
    open_objects, open_rows, n_priced, unrealized, deployed = _live_open_book(
        request.user, portfolio)
    closed_positions = unified_closed_positions(request.user, portfolio)
    stats = _closed_stats(closed_positions)

    n_open = len(open_rows)
    best_trade = (max(stats["graded"], key=lambda p: float(p.unrealized_pnl))
                  if stats["graded"] else None)
    worst_trade = (min(stats["graded"], key=lambda p: float(p.unrealized_pnl))
                   if stats["graded"] else None)
    # Whether the pair says anything is not a question about HOW MANY closes
    # were graded — it is whether these two are the same row. Counting was
    # the first fix and it was not enough: max() and min() both return the
    # FIRST extremum, so any tie hands back one object twice, and ties are
    # ordinary here because portfolio.Position.unrealized_pnl defaults to
    # 0.00 and nothing marks a closed legacy row. Two unmarked closes and
    # the page crowned one trade as both the best and the worst again, from
    # a different direction.
    have_pair = (best_trade is not None and worst_trade is not None
                 and best_trade is not worst_trade)

    priced_note = (f"{n_priced} of {n_open} open positions carry a live quote."
                   if n_open else "No open positions in either book.")
    strip = {
        "open": _live_cell(
            str(n_open), sub="currently active",
            title="Across the legacy Position book and the bot book."),
        "unrealized": _live_cell(
            _live_num(unrealized), tone=_live_tone(unrealized),
            sub="mark-to-market",
            title=(f"Marked to live quotes, never read off the stored "
                   f"column. {priced_note}")),
        "exposure": _live_cell(
            _live_num(deployed, "{:,.2f}"), sub="notional capital deployed",
            title=f"At live marks. {priced_note}"),
        "closed": _live_cell(
            str(stats["n_closed"]),
            sub=f"{stats['n_winning']}W / {stats['n_losing']}L",
            title=(f"{stats['n_ungraded']} of them could not be priced and "
                   f"are held out of the split rather than booked as "
                   f"losses.")),
        "win_rate": _live_cell(
            _live_num(stats["win_rate"], "{:.1f}%"),
            tone=("" if stats["win_rate"] is None else
                  "up" if stats["win_rate"] >= 50 else
                  "down" if stats["win_rate"] < 40 else ""),
            sub="closed history",
            title=f"Over {stats['n_graded']} priced closes."),
        "realized": _live_cell(
            _live_num(stats["realized"]), tone=_live_tone(stats["realized"]),
            sub="all-time",
            title="Booked P&L across every closed position that carries one."),
        "profit_factor": _live_cell(
            _live_num(stats["profit_factor"], "{:.2f}"),
            tone=("" if stats["profit_factor"] is None else
                  "up" if stats["profit_factor"] >= 1 else "down"),
            sub="gross win / gross loss",
            title="Undefined until the closed book holds both a win and a "
                  "loss."),
        "avg_wl": _live_cell(
            f"{_live_num(stats['avg_win'])} / {_live_num(stats['avg_loss'])}",
            sub="per closed trade",
            title="Average winner and average loser, each over its own side "
                  "of the book."),
    }

    # Direction donut over open positions.
    n_long = sum(1 for p in open_rows if p["direction"] == "long")
    n_short = n_open - n_long
    direction_donut = []
    if n_long:
        direction_donut.append({"key": "long", "n": n_long,
                                "pct": round(n_long / n_open * 100, 1)})
    if n_short:
        direction_donut.append({"key": "short", "n": n_short,
                                "pct": round(n_short / n_open * 100, 1)})

    # Asset-class breakdown. Exposure at the mark where there is one and at
    # entry cost otherwise — a row sized at zero because no quote arrived
    # reads as a position that is not there. Unrealized stays None for a
    # class nothing in it could be priced.
    by_class: dict = defaultdict(
        lambda: {"n": 0, "exposure": 0.0, "unrealized": None, "n_priced": 0})
    for p in open_rows:
        d = by_class[p["asset_class"]]
        d["n"] += 1
        price = (p["current_price"] if p["current_price"] is not None
                 else p["entry_price"])
        d["exposure"] += abs(float(p["quantity"] or 0) * float(price or 0))
        if p["unrealized_pnl"] is not None:
            d["unrealized"] = (d["unrealized"] or 0.0) + p["unrealized_pnl"]
            d["n_priced"] += 1
    total_exposure = sum(d["exposure"] for d in by_class.values())
    asset_breakdown = sorted(
        [{"asset_class": k, **v,
          "unrealized_text": _live_num(v["unrealized"]),
          "unrealized_tone": _live_tone(v["unrealized"]),
          "exposure_pct": (round(v["exposure"] / total_exposure * 100, 1)
                           if total_exposure > 0 else None)}
         for k, v in by_class.items()],
        key=lambda r: -r["exposure"])

    context = {
        "page_id": "positions",
        # Pools / used / free / cash — the money question, answered by ONE
        # service so this page, the positions page and the headband popups
        # can never quote three different answers. See
        # portfolio.services.capital_summary for what the two economies are.
        "capital": _capital_or_none(request.user),
        "tab": tab,
        "strip": strip,
        "positions": open_rows,
        # The row loop iterates this. The card details are built from the
        # ORIGINAL model rows — _position_card_details reads attributes off
        # them — while the row's own cells read the live dict, so the two
        # halves of a row cannot quote different marks. Zipped rather than
        # keyed because a portfolio.Position row has no id to join on.
        "positions_detailed": list(zip(
            open_rows, _position_card_details(request.user, open_objects))),
        # CLOSED rows get the same treatment. They used to carry eight
        # cells and nothing else — no capital, no leverage, no venue, no
        # rule, not even the R the trade was graded on — so a trade the
        # operator wanted to LEARN from was the thinnest row on the page,
        # which is exactly backwards: an open position can be watched, a
        # closed one is only ever what was written down about it.
        "closed_detailed": list(zip(
            closed_positions,
            _position_card_details(request.user, closed_positions))),
        "n_priced": n_priced,
        "direction_donut": direction_donut,
        "asset_breakdown": asset_breakdown,
    }

    if not live_only:
        # The closed book and its 12-month bars. They only move when a trade
        # closes — and a close reloads the whole page's live regions anyway —
        # but the history list is long, so the refresh does not carry it.
        from datetime import timedelta as _td
        now = timezone.now()
        monthly_pnl: dict = defaultdict(float)
        for p in stats["graded"]:
            if p.closed_at:
                monthly_pnl[p.closed_at.strftime("%Y-%m")] += float(
                    p.unrealized_pnl)
        monthly_rows = []
        for i in range(11, -1, -1):
            month = (now - _td(days=i * 30)).replace(day=1)
            pnl = round(monthly_pnl.get(month.strftime("%Y-%m"), 0), 2)
            monthly_rows.append({
                "month": month.strftime("%b"),
                "pnl": pnl,
                # chart_bars contract. A month with no closes really did
                # realize nothing, so it is a zero on the axis, not unknown.
                "label": month.strftime("%b"),
                "value": pnl,
                "display": "{}{:.2f}".format("+" if pnl > 0 else "", pnl),
            })
        monthly_max = max((abs(r["pnl"]) for r in monthly_rows), default=0)

        # The mini bar in each history row. It used to be two lies side by
        # side: a LONG drew `width: {{ pct }}%`, so a losing long produced a
        # negative width that CSS discards — every loss, from -0.4% to -40%,
        # collapsed to the same 4px stub — while a SHORT was hardcoded to
        # `width: 50%` and said nothing at all about the trade it belonged
        # to. Magnitude scaled against the biggest move on the page, sign
        # carried by the colour, direction by the marker; None where there
        # is nothing to draw, which renders as no bar rather than a full one.
        pcts = [abs(float(p.unrealized_pnl_pct)) for p in closed_positions
                if p.unrealized_pnl_pct is not None]
        peak = max(pcts) if pcts else 0.0
        for p in closed_positions:
            pct = p.unrealized_pnl_pct
            p.bar_pct = (round(abs(float(pct)) / peak * 100, 1)
                         if pct is not None and peak > 0 else None)

        context.update({
            "closed_positions": closed_positions,
            "total_closed": stats["n_closed"],
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            # With ONE graded close, best and worst are the same row, and the
            # page showed it twice — once in a green "Best Trade" card that
            # hardcoded a + in front of the number. A single losing short read
            # as the platform's best trade AND its worst.
            "n_graded": stats["n_graded"],
            "have_pair": have_pair,
            "monthly_rows": monthly_rows,
            "monthly_max": monthly_max,
            "monthly_max_display": "{:.2f}".format(monthly_max),
        })

    return _live_page(request, "dashboard/positions_list.html",
                      context, live_only)


@login_required
def positions_list(request):
    return _render_positions(request, live_only=False)


@login_required
def positions_live(request):
    """The moving regions of /positions/, re-rendered — see portfolio_live.

    ?tab= rides along, so the open tab refreshes its book and the history tab
    refreshes only the regions it actually shows.
    """
    return _render_positions(request, live_only=True)


@login_required
def ai_insights(request):
    """Phase 63 — enriched AI intelligence dashboard.

    Adds: per-agent breakdown · provider mix donut · 7d cost trend ·
    failure rate · top error agents · model-tier distribution.
    """
    from collections import Counter, defaultdict
    from ai_agents.models import AgentTask

    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    tasks_24h = list(AgentTask.objects.filter(created_at__gte=day_ago)
                      .only("agent", "provider", "model", "success",
                            "cost_usd", "duration_seconds", "created_at",
                            "input_tokens", "output_tokens"))
    total_24h = len(tasks_24h)
    success_24h = sum(1 for t in tasks_24h if t.success)
    fail_24h = total_24h - success_24h

    cost_24h = sum(float(t.cost_usd) for t in tasks_24h)
    in_tok_24h = sum(t.input_tokens for t in tasks_24h)
    out_tok_24h = sum(t.output_tokens for t in tasks_24h)
    avg_dur = (sum(t.duration_seconds for t in tasks_24h) / total_24h) if total_24h else 0

    # Per-agent breakdown (24h).
    agent_rows: dict = defaultdict(
        lambda: {"n": 0, "ok": 0, "cost": 0.0, "tokens": 0})
    for t in tasks_24h:
        d = agent_rows[t.agent or "—"]
        d["n"] += 1
        if t.success:
            d["ok"] += 1
        d["cost"] += float(t.cost_usd)
        d["tokens"] += t.input_tokens + t.output_tokens
    by_agent = sorted(
        [{"agent": k, **v,
          "success_rate": round(v["ok"] / max(v["n"], 1) * 100, 1),
          "cost": round(v["cost"], 4)}
         for k, v in agent_rows.items()],
        key=lambda r: -r["n"]
    )

    # Provider mix donut (24h).
    prov_counter: Counter = Counter(t.provider or "—" for t in tasks_24h)
    provider_donut = []
    for p, n in prov_counter.most_common():
        provider_donut.append({
            "key": p, "n": n,
            "pct": round(n / max(total_24h, 1) * 100, 1),
        })

    # Cost trend — last 7 days bucketed by date.
    cost_per_day: dict = defaultdict(float)
    n_per_day: dict = defaultdict(int)
    week_qs = AgentTask.objects.filter(created_at__gte=week_ago).only(
        "created_at", "cost_usd")
    for t in week_qs:
        d = t.created_at.date()
        cost_per_day[d] += float(t.cost_usd)
        n_per_day[d] += 1
    # `label`/`value` is the contract of _partials/chart_bars.html — the one
    # column chart on the platform. A day with no tasks spent nothing, which
    # is a MEASUREMENT of zero, not a missing reading: it keeps value 0 and
    # sits on the baseline. A missing reading would carry value None instead
    # and draw no bar at all.
    cost_trend = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        n = n_per_day.get(d, 0)
        cost = round(cost_per_day.get(d, 0), 4)
        cost_trend.append({
            "label": d.strftime("%m-%d"),
            "value": cost,
            "display": "${:.4f}".format(cost),
            "note": "{} task{}".format(n, "" if n == 1 else "s"),
            "date": d.strftime("%m-%d"),
            "cost": cost,
            "n": n,
        })
    max_day_cost = max((r["value"] for r in cost_trend), default=0)
    max_day_cost_display = "${:.4f}".format(max_day_cost)

    # Top failing agents (24h).
    fail_counter: Counter = Counter(
        t.agent for t in tasks_24h if not t.success and t.agent)
    top_failures = [{"agent": a, "n": n}
                     for a, n in fail_counter.most_common(5)]

    # Recent latest briefing (Strategist/Reviewer).
    latest_briefing = AgentTask.objects.filter(
        agent__in=["strategy_advisor", "weekly_reviewer"],
        success=True
    ).first()

    return render(request, "dashboard/ai_insights.html", {
        "page_id": "ai",
        "tasks_24h": total_24h,
        "success_24h": success_24h,
        "fail_24h": fail_24h,
        "success_rate": round(success_24h / total_24h * 100) if total_24h > 0 else 0,
        "cost_24h": "{:.2f}".format(cost_24h),
        "in_tok_24h": in_tok_24h,
        "out_tok_24h": out_tok_24h,
        "avg_duration": "{:.1f}".format(avg_dur),
        "by_agent": by_agent,
        "provider_donut": provider_donut,
        "cost_trend": cost_trend,
        "max_day_cost": max_day_cost,
        "max_day_cost_display": max_day_cost_display,
        "top_failures": top_failures,
        "latest_briefing": latest_briefing,
        "recent_tasks": AgentTask.objects.order_by("-created_at")[:20],
    })


@login_required
def ai_tasks_list(request):
    """Phase 63 — enriched agent task log.

    Adds: 24h/7d aggregates, per-agent breakdown, success/cost trend,
    longest tasks, latest failures.
    """
    from collections import defaultdict
    from ai_agents.models import AgentTask

    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    qs_24h = list(AgentTask.objects.filter(created_at__gte=day_ago)
                   .only("agent", "provider", "model", "success",
                         "cost_usd", "duration_seconds", "created_at",
                         "input_tokens", "output_tokens"))
    qs_7d = list(AgentTask.objects.filter(created_at__gte=week_ago)
                  .only("agent", "success", "cost_usd",
                        "duration_seconds", "created_at"))

    # 24h aggregates
    n_24h = len(qs_24h)
    n_ok_24h = sum(1 for t in qs_24h if t.success)
    n_fail_24h = n_24h - n_ok_24h
    cost_24h = sum(float(t.cost_usd) for t in qs_24h)
    in_tok_24h = sum(t.input_tokens for t in qs_24h)
    out_tok_24h = sum(t.output_tokens for t in qs_24h)

    # 7d aggregates
    n_7d = len(qs_7d)
    cost_7d = sum(float(t.cost_usd) for t in qs_7d)
    success_rate_7d = round(
        sum(1 for t in qs_7d if t.success) / max(n_7d, 1) * 100, 1)
    avg_dur_7d = (sum(t.duration_seconds for t in qs_7d) / max(n_7d, 1))

    # Per-agent breakdown (last 7d).
    agent_rows: dict = defaultdict(
        lambda: {"n": 0, "ok": 0, "cost": 0.0, "dur": 0.0})
    for t in qs_7d:
        d = agent_rows[t.agent or "—"]
        d["n"] += 1
        if t.success:
            d["ok"] += 1
        d["cost"] += float(t.cost_usd)
        d["dur"] += t.duration_seconds
    by_agent = sorted(
        [{"agent": k, **v,
          "success_rate": round(v["ok"] / max(v["n"], 1) * 100, 1),
          "avg_dur": round(v["dur"] / max(v["n"], 1), 1),
          "cost": round(v["cost"], 4)}
         for k, v in agent_rows.items()],
        key=lambda r: -r["n"]
    )

    # Recent failures (last 5).
    recent_failures = list(
        AgentTask.objects.filter(success=False)
        .order_by("-created_at")[:5]
    )

    # Top-5 longest tasks (last 7d).
    longest = sorted(qs_7d, key=lambda t: -t.duration_seconds)[:5]
    longest_rows = [{
        "agent": t.agent, "duration": round(t.duration_seconds, 1),
        "created_at": t.created_at, "success": t.success,
    } for t in longest]

    # 7d cost trend by date.
    cost_per_day: dict = defaultdict(float)
    n_per_day: dict = defaultdict(int)
    for t in qs_7d:
        d = t.created_at.date()
        cost_per_day[d] += float(t.cost_usd)
        n_per_day[d] += 1
    # Same bar contract as /ai/ — see the note there on zero vs unknown.
    cost_trend = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        n = n_per_day.get(d, 0)
        cost = round(cost_per_day.get(d, 0), 4)
        cost_trend.append({
            "label": d.strftime("%m-%d"),
            "value": cost,
            "display": "${:.4f}".format(cost),
            "note": "{} task{}".format(n, "" if n == 1 else "s"),
            "date": d.strftime("%m-%d"),
            "cost": cost,
            "n": n,
        })
    max_day_cost = max((r["value"] for r in cost_trend), default=0)
    max_day_cost_display = "${:.4f}".format(max_day_cost)

    return render(request, "dashboard/ai_tasks_list.html", {
        "page_id": "ai_tasks",
        "tasks": AgentTask.objects.order_by("-created_at")[:200],
        "n_24h": n_24h,
        "n_ok_24h": n_ok_24h,
        "n_fail_24h": n_fail_24h,
        "cost_24h": "{:.2f}".format(cost_24h),
        "in_tok_24h": in_tok_24h,
        "out_tok_24h": out_tok_24h,
        "n_7d": n_7d,
        "cost_7d": "{:.2f}".format(cost_7d),
        "success_rate_7d": success_rate_7d,
        "avg_dur_7d": "{:.1f}".format(avg_dur_7d),
        "by_agent": by_agent,
        "recent_failures": recent_failures,
        "longest_rows": longest_rows,
        "cost_trend": cost_trend,
        "max_day_cost": max_day_cost,
        "max_day_cost_display": max_day_cost_display,
    })


@login_required
def profile(request):
    """User profile: personal info + trading preferences."""
    from django.contrib import messages
    from portfolio.trader_profile import TraderProfile

    profile_obj, _ = TraderProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # Personal info (on User model)
        request.user.email = request.POST.get("email", request.user.email)
        request.user.first_name = request.POST.get("first_name", "")
        request.user.last_name = request.POST.get("last_name", "")
        request.user.save()

        # Profile fields
        profile_obj.display_name = request.POST.get("display_name", "")
        profile_obj.bio = request.POST.get("bio", "")
        profile_obj.location = request.POST.get("location", "")
        profile_obj.phone = request.POST.get("phone", "")
        profile_obj.timezone_preference = request.POST.get("timezone_preference", "UTC")

        # Trading profile
        profile_obj.experience_level = request.POST.get("experience_level", "intermediate")
        profile_obj.trading_style = request.POST.get("trading_style", "swing_trader")
        profile_obj.risk_appetite = request.POST.get("risk_appetite", "moderate")
        profile_obj.analysis_approach = request.POST.get("analysis_approach", "mixed")
        profile_obj.preferred_session = request.POST.get("preferred_session", "european")
        profile_obj.available_hours_per_day = float(request.POST.get("available_hours_per_day", 2))

        # Markets
        profile_obj.trade_stocks = "trade_stocks" in request.POST
        profile_obj.trade_forex = "trade_forex" in request.POST
        profile_obj.trade_commodities = "trade_commodities" in request.POST
        profile_obj.trade_crypto = "trade_crypto" in request.POST
        profile_obj.trade_indices = "trade_indices" in request.POST
        profile_obj.trade_bonds = "trade_bonds" in request.POST

        # Goals
        profile_obj.monthly_return_target_pct = float(request.POST.get("monthly_return_target_pct", 3))
        profile_obj.max_acceptable_drawdown_pct = float(request.POST.get("max_acceptable_drawdown_pct", 10))
        profile_obj.annual_income_target = request.POST.get("annual_income_target", 0) or 0

        # AI
        profile_obj.theme_mode = request.POST.get("theme_mode", profile_obj.theme_mode)
        profile_obj.ai_autonomy = request.POST.get("ai_autonomy", "suggest")
        profile_obj.ai_commentary_detail = request.POST.get("ai_commentary_detail", "detailed")

        # Notifications
        profile_obj.notify_channel = request.POST.get("notify_channel", "telegram")
        profile_obj.notify_signals = "notify_signals" in request.POST
        profile_obj.notify_strategies = "notify_strategies" in request.POST
        profile_obj.notify_news_critical = "notify_news_critical" in request.POST
        profile_obj.notify_portfolio = "notify_portfolio" in request.POST
        profile_obj.notify_weekly_review = "notify_weekly_review" in request.POST

        # Phase-15 cross-asset orchestrator
        profile_obj.cross_asset_orchestrator_enabled = (
            "cross_asset_orchestrator_enabled" in request.POST)
        try:
            profile_obj.max_usd_theme_exposure = float(
                request.POST.get("max_usd_theme_exposure", 3.0) or 3.0)
            profile_obj.max_equity_theme_exposure = float(
                request.POST.get("max_equity_theme_exposure", 3.0) or 3.0)
            # Phase-24 additions (0 = disabled).
            profile_obj.max_vol_theme_exposure = float(
                request.POST.get("max_vol_theme_exposure", 0) or 0)
            profile_obj.max_currency_exposure = float(
                request.POST.get("max_currency_exposure", 0) or 0)
            profile_obj.max_sector_exposure = int(
                request.POST.get("max_sector_exposure", 0) or 0)
        except ValueError:
            pass  # keep current values on parse failure
        # Phase-25 — size-weighted exposure toggle.
        profile_obj.size_weighted_orchestrator = (
            "size_weighted_orchestrator" in request.POST)

        # Phase-27 — tax-lot consumption method.
        method = request.POST.get("tax_lot_method", "").strip().upper()
        if method in ("FIFO", "LIFO", "HIFO"):
            profile_obj.tax_lot_method = method

        # Idle PIN lock (enforced by core.idle_lock). Only values from
        # the choice list are accepted — a tampered POST must not be able
        # to set a 0-minute or 9999-minute window.
        profile_obj.idle_lock_enabled = "idle_lock_enabled" in request.POST
        try:
            minutes = int(request.POST.get(
                "idle_lock_minutes", profile_obj.idle_lock_minutes))
            if minutes in dict(TraderProfile.IDLE_LOCK_MINUTES_CHOICES):
                profile_obj.idle_lock_minutes = minutes
        except (TypeError, ValueError):
            pass  # keep current value on parse failure

        profile_obj.save()
        messages.success(request, "Profile updated successfully.")

        from django.shortcuts import redirect
        return redirect("profile")

    # Common timezones
    timezones = [
        "UTC", "Europe/Paris", "Europe/London", "Europe/Berlin", "Europe/Zurich",
        "US/Eastern", "US/Central", "US/Pacific",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Asia/Dubai",
        "Australia/Sydney", "Pacific/Auckland",
    ]

    return render(request, "dashboard/profile.html", {
        "page_id": "profile",
        "profile": profile_obj,
        "timezones": timezones,
        "experience_choices": TraderProfile.EXPERIENCE_CHOICES,
        "style_choices": TraderProfile.STYLE_CHOICES,
        "risk_choices": TraderProfile.RISK_CHOICES,
        "analysis_choices": TraderProfile.ANALYSIS_CHOICES,
        "session_choices": TraderProfile.SESSION_CHOICES,
    })


# What the /setup/ Risk Limits card may write, and why each bound is there.
#
# These four numbers stopped being decorative: `portfolio.risk_gate.preflight`
# reads them before every bot entry and every manual trade. They also live on
# the SHARED "Main" portfolio, which has no user column, so anyone who can
# reach this page moves them for everyone — which makes an out-of-range value
# a fleet-wide outage rather than one operator's mistake.
#
#   field: (minimum, maximum, label)
#
# The minimums are the point, and they are there for two opposite reasons.
#
# In three of the four fields a 0 — accepted without complaint until this
# existed — now means "halt": 0% daily loss stops the fleet at the first cent
# lost, and 0% exposure or 0% single position refuses every entry there will
# ever be. Those floors are the smallest values that still describe a book
# someone could trade — 0.1% of a €10,000 book is €10, below which the limit is
# indistinguishable from off.
#
# The correlation threshold fails the other way, which is why it carries its
# own floor. `risk_gate.correlation_state` reads a 0 exactly as it reads an
# unset value — the taper is OFF — so a 0 typed into the tightest-looking field
# on the card would bind nothing whatsoever. 0.01 is the tightest setting that
# is still a setting; switching the taper off is 1.00, which is what the card
# tells the operator to use.
#
# The maximums are looser on purpose, because a high limit is a decision and a
# legible one: 1000% exposure is what a margined FX book genuinely runs at, and
# 100% single position is "one trade may be the whole book", which is
# reckless but honest. Correlation caps at 1.0 because nothing correlates
# higher than perfectly.
RISK_LIMIT_BOUNDS = {
    "max_total_exposure_pct": (0.1, 1000.0, "Max total exposure"),
    "max_single_position_pct": (0.1, 100.0, "Max single position"),
    "max_daily_loss_pct": (0.1, 100.0, "Max daily loss"),
    "max_correlation_threshold": (0.01, 1.0, "Max correlation threshold"),
    # A COUNT, not a percentage, and 0 is a legal value here — it turns the
    # theme gate off, where a 0 on the sibling limits would mean "refuse
    # everything" and is therefore out of their bounds.
    "max_theme_legs": (0, 20, "Max theme legs"),
}

# POST field -> Portfolio field. The form names are short and the model names
# are not; the mapping is here so a renamed input fails loudly at the one place
# that knows both.
RISK_LIMIT_FIELDS = {
    "max_exposure": "max_total_exposure_pct",
    "max_position": "max_single_position_pct",
    "max_daily_loss": "max_daily_loss_pct",
    "max_correlation": "max_correlation_threshold",
    "max_theme_legs": "max_theme_legs",
}


def _apply_risk_limits(portfolio, post) -> tuple[bool, list[str]]:
    """Validate and save the four risk limits. Returns (saved, rejections).

    ALL FOUR OR NONE. A partial save is the worst outcome available here: the
    operator asked for one policy and would get a mixture of the new one and
    the old, with a green message on top. Nothing is written until every field
    parses and sits inside its bound.

    The old handler was `float(request.POST.get(...))` four times over. A blank
    field or a typo raised ValueError straight out of the view — a 500 on a
    settings page — and any number at all was accepted, including the zeros
    that now mean "stop trading".
    """
    rejected: list[str] = []
    pending: dict[str, float] = {}

    for form_name, field in RISK_LIMIT_FIELDS.items():
        low, high, label = RISK_LIMIT_BOUNDS[field]
        raw = post.get(form_name)
        if raw is None or str(raw).strip() == "":
            rejected.append(f"{label} was left blank")
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            rejected.append(f"{label} must be a number, got {raw!r}")
            continue
        if not (low <= value <= high):
            # The tail is per-field truth: a 0 on the percentage limits
            # means "refuse everything", while on the theme count 0 is the
            # legal off switch and the bound exists to catch typos like 200.
            if field == "max_theme_legs":
                rejected.append(
                    f"{label} must be between {low:g} and {high:g} — it is "
                    f"a count of concurrent same-currency tickets, and 0 "
                    f"turns the theme gate off")
            else:
                rejected.append(
                    f"{label} must be between {low:g} and {high:g} — "
                    f"{value:g} would gate every trade on this platform")
            continue
        if field == "max_theme_legs":
            # A count of tickets. int() would quietly turn 2.5 into 2 and
            # save a limit nobody typed; a count that is not whole is a
            # typo, and typos are rejected, not rounded.
            if value != int(value):
                rejected.append(f"{label} is a count of tickets — "
                                f"{value:g} is not a whole number")
                continue
            value = int(value)
        pending[field] = value

    if rejected:
        return False, rejected

    for field, value in pending.items():
        setattr(portfolio, field, value)
    portfolio.save(update_fields=[*pending, "updated_at"])
    return True, []


@login_required
def setup(request):
    """Account setup: capital, risk, eToro, manual positions."""
    import os
    from django.contrib import messages
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    from instruments.models import Instrument
    from django.utils import timezone

    # The user's own book — a position somebody adds by hand is theirs, and
    # it has to land where the pages that display it are looking. This wrote
    # to the shared "Main" book to match the eToro sync this same page
    # triggers, but that sync is the odd one out: it runs off a single
    # global API key with no user attached, so it has no book of its own to
    # write to. A hand-added position does.
    portfolio = get_or_create_default_portfolio(user=request.user)

    # ...but the four RISK LIMITS are a different object with a different
    # owner. `portfolio.risk_gate.limits_book()` is the shared "Main" row,
    # and every gate on every trading path reads its percentages from there.
    # Writing them onto the per-user book would put an operator's MAX DAILY
    # LOSS 3% somewhere no gate looks, leaving the factory defaults enforcing
    # in its place — the exact "the card protects nothing" failure the gates
    # were wired to end. Card and gate therefore read and write ONE row.
    from portfolio.risk_gate import limits_book
    limits = limits_book()

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "update_capital":
            portfolio.initial_capital = request.POST.get("initial_capital", portfolio.initial_capital)
            portfolio.current_value = request.POST.get("current_value", portfolio.current_value)
            portfolio.cash_available = request.POST.get("cash_available", portfolio.cash_available)
            portfolio.currency = request.POST.get("currency", portfolio.currency)
            portfolio.save()
            messages.success(request, "Portfolio capital updated successfully.")

        elif action == "update_risk":
            saved, rejected = _apply_risk_limits(limits, request.POST)
            if rejected:
                messages.error(request, "Risk limits NOT saved: "
                                        + "; ".join(rejected))
            elif saved:
                messages.success(
                    request,
                    "Risk limits updated — these now gate every bot entry "
                    "and every manual trade on the shared book.")

        elif action == "connect_etoro":
            etoro_key = request.POST.get("etoro_api_key", "").strip()
            if etoro_key:
                # Store in env or DB (for simplicity, write to .env-like storage)
                os.environ["ETORO_API_KEY"] = etoro_key
                messages.success(request, "eToro API key saved. Use Sync to pull positions.")
            else:
                messages.error(request, "Please provide an eToro API key.")

        elif action == "sync_etoro":
            from market_data.adapters.etoro_adapter import sync_etoro_positions
            result = sync_etoro_positions()
            if result.get("status") == "success":
                messages.success(request, f"Synced {result['synced']} positions from eToro.")
            elif result.get("status") == "not_configured":
                messages.error(request, "eToro API key not configured.")
            else:
                messages.error(request, "Failed to sync eToro positions. Check your API key.")

        elif action == "add_position":
            symbol = request.POST.get("symbol", "").upper().strip()
            if symbol:
                instrument, _ = Instrument.objects.get_or_create(
                    symbol=symbol,
                    defaults={
                        "name": symbol,
                        "asset_class": request.POST.get("asset_class", "stock"),
                        "is_active": True,
                    }
                )
                Position.objects.create(
                    portfolio=portfolio,
                    instrument=instrument,
                    direction=request.POST.get("direction", "long"),
                    quantity=request.POST.get("quantity", 0),
                    entry_price=request.POST.get("entry_price", 0),
                    current_price=request.POST.get("entry_price", 0),
                    stop_loss=request.POST.get("stop_loss") or None,
                    take_profit=request.POST.get("take_profit") or None,
                    opened_at=timezone.now(),
                )
                messages.success(request, f"Position {symbol} added successfully.")
            else:
                messages.error(request, "Symbol is required.")

        from django.shortcuts import redirect
        return redirect("setup")

    # API keys status
    api_keys = [
        {"name": "Anthropic (Claude AI)", "configured": bool(os.getenv("ANTHROPIC_API_KEY")), "url": "https://console.anthropic.com", "url_label": "console.anthropic.com"},
        {"name": "Alpha Vantage", "configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY")), "url": "https://www.alphavantage.co/support/#api-key", "url_label": "alphavantage.co"},
        {"name": "Twelve Data", "configured": bool(os.getenv("TWELVE_DATA_API_KEY")), "url": "https://twelvedata.com", "url_label": "twelvedata.com"},
        {"name": "Finnhub", "configured": bool(os.getenv("FINNHUB_API_KEY")), "url": "https://finnhub.io", "url_label": "finnhub.io"},
        {"name": "FMP", "configured": bool(os.getenv("FMP_API_KEY")), "url": "https://financialmodelingprep.com", "url_label": "financialmodelingprep.com"},
        {"name": "FRED", "configured": bool(os.getenv("FRED_API_KEY")), "url": "https://fred.stlouisfed.org/docs/api/api_key.html", "url_label": "fred.stlouisfed.org"},
        {"name": "eToro", "configured": bool(os.getenv("ETORO_API_KEY")), "url": "https://api-portal.etoro.com", "url_label": "api-portal.etoro.com"},
        {"name": "Telegram", "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")), "url": "https://core.telegram.org/bots#botfather", "url_label": "BotFather"},
    ]

    etoro_key = os.getenv("ETORO_API_KEY", "")
    etoro_masked = ("●" * 20 + etoro_key[-4:]) if len(etoro_key) > 4 else ""

    # Where the book stands against the limits right now. The card used to
    # show four inputs and no consequence, which is how a limit that enforced
    # nothing went unnoticed for so long — there was never a number next to it
    # that would have moved. `preflight` is the same read the entry gates make,
    # so what the card shows is what a bot would decide this second.
    from portfolio.risk_gate import (
        DAILY_LOSS_WINDOW_HOURS, book_value, preflight, single_position_state,
    )
    risk_state = preflight(request.user, portfolio=limits)
    # The single-position ceiling in money, so the operator can compare it with
    # the pool capital they armed a bot with. The two are configured on
    # different pages and nothing reconciles them: a 10% ceiling on a 10,000
    # book refuses a position a 10,000 pool is entitled to open at 20% of
    # itself, and before this the collision only ever surfaced as a refusal at
    # the moment of trading. Notional 0 asks for the ceiling alone.
    risk_single = single_position_state(limits, asset_class="stock",
                                        notional=0.0)

    return render(request, "dashboard/setup.html", {
        "page_id": "setup",
        "portfolio": portfolio,
        # The Risk Limits card renders ITS values from this row, not from
        # `portfolio` — otherwise the card shows one book's numbers while
        # the gates enforce another's.
        "limits": limits,
        "api_keys": api_keys,
        "etoro_connected": bool(etoro_key),
        "etoro_key_masked": etoro_masked,
        "risk_state": risk_state,
        "risk_daily_loss": risk_state["checks"].get("daily_loss"),
        "risk_exposure": risk_state["checks"].get("exposure"),
        "risk_single": risk_single,
        "risk_book_value": book_value(limits),
        "risk_window_hours": DAILY_LOSS_WINDOW_HOURS,
    })


@login_required
def getting_started(request):
    return render(request, "dashboard/getting_started.html", {"page_id": "getting_started"})


@login_required
def toggle_theme(request):
    """Toggle light/dark theme via AJAX or form POST."""
    from portfolio.trader_profile import TraderProfile
    from django.http import JsonResponse
    from django.shortcuts import redirect

    profile, _ = TraderProfile.objects.get_or_create(user=request.user)
    profile.theme_mode = "light" if profile.theme_mode == "dark" else "dark"
    profile.save()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"theme": profile.theme_mode})
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
def admin_dashboard(request):
    """Superuser admin dashboard — system overview."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Superuser access required.")

    import os
    from django.contrib.auth.models import User
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle, SentimentSnapshot, COTReport, InstitutionalFiling
    from market_data.models import PriceData, LiveQuote, EconomicEvent, MacroIndicator
    from ai_agents.models import AgentTask
    from django.utils import timezone as tz
    from datetime import timedelta
    from django.db.models import Count, Avg

    now = tz.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # AI stats by agent
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    ai_mtd = AgentTask.objects.filter(created_at__gte=month_start)
    ai_total_24 = ai_24h.count()
    ai_success_24 = ai_24h.filter(success=True).count()
    ai_tokens = sum(t.input_tokens + t.output_tokens for t in ai_24h)

    agent_stats = []
    # order_by("agent") clears AgentTask's -created_at Meta ordering, which would
    # otherwise sneak created_at into the DISTINCT projection and yield dupes.
    for agent_name in ai_24h.order_by("agent").values_list("agent", flat=True).distinct():
        agent_qs = ai_24h.filter(agent=agent_name)
        agent_stats.append({
            "agent": agent_name,
            "total": agent_qs.count(),
            "success": agent_qs.filter(success=True).count(),
            "fails": agent_qs.filter(success=False).count(),
            "avg_time": "{:.1f}".format(sum(t.duration_seconds for t in agent_qs) / max(agent_qs.count(), 1)),
            "cost": "{:.4f}".format(sum(float(t.cost_usd) for t in agent_qs)),
        })

    # Asset class breakdown
    asset_classes = Instrument.objects.values("asset_class").annotate(count=Count("id")).order_by("asset_class")

    # API keys
    api_keys_status = [
        {"name": "Anthropic", "ok": bool(os.getenv("ANTHROPIC_API_KEY"))},
        {"name": "Alpha Vantage", "ok": bool(os.getenv("ALPHA_VANTAGE_API_KEY"))},
        {"name": "Twelve Data", "ok": bool(os.getenv("TWELVE_DATA_API_KEY"))},
        {"name": "Finnhub", "ok": bool(os.getenv("FINNHUB_API_KEY"))},
        {"name": "FMP", "ok": bool(os.getenv("FMP_API_KEY"))},
        {"name": "FRED", "ok": bool(os.getenv("FRED_API_KEY"))},
        {"name": "eToro Public", "ok": bool(os.getenv("ETORO_PUBLIC_KEY"))},
        {"name": "eToro User", "ok": bool(os.getenv("ETORO_USER_KEY"))},
        {"name": "Telegram", "ok": bool(os.getenv("TELEGRAM_BOT_TOKEN"))},
        {"name": "ScraperAPI (proxy)", "ok": bool(os.getenv("SCRAPER_API_KEY"))},
        {"name": "SERP API", "ok": bool(os.getenv("SERP_API_KEY"))},
    ]

    # Data sources health
    data_sources = [
        {"name": "Price Data (OHLCV)", "count": PriceData.objects.count(), "last_updated": PriceData.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()},
        {"name": "Live Quotes", "count": LiveQuote.objects.count(), "last_updated": LiveQuote.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()},
        {"name": "News Articles", "count": NewsArticle.objects.count(), "last_updated": NewsArticle.objects.order_by("-scraped_at").values_list("scraped_at", flat=True).first()},
        {"name": "Sentiment Snapshots", "count": SentimentSnapshot.objects.count(), "last_updated": SentimentSnapshot.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()},
        {"name": "Economic Events", "count": EconomicEvent.objects.count(), "last_updated": None},
        {"name": "COT Reports", "count": COTReport.objects.count(), "last_updated": COTReport.objects.order_by("-report_date").values_list("report_date", flat=True).first()},
        {"name": "Institutional Filings", "count": InstitutionalFiling.objects.count(), "last_updated": InstitutionalFiling.objects.order_by("-filing_date").values_list("filing_date", flat=True).first()},
        {"name": "Macro Indicators", "count": MacroIndicator.objects.count(), "last_updated": None},
        {"name": "AI Agent Tasks", "count": AgentTask.objects.count(), "last_updated": AgentTask.objects.order_by("-created_at").values_list("created_at", flat=True).first()},
    ]

    context = {
        "page_id": "admin_dashboard",
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "users": User.objects.order_by("-date_joined"),
        "total_instruments": Instrument.objects.count(),
        "watchlist_instruments": Instrument.objects.filter(is_watchlist=True).count(),
        "asset_class_counts": [{"class": ac["asset_class"], "count": ac["count"]} for ac in asset_classes],
        "active_signals": Signal.objects.filter(is_active=True).count(),
        "total_signals": Signal.objects.count(),
        "total_strategies": Strategy.objects.count(),
        "active_strategies": Strategy.objects.filter(status__in=["active", "approved"]).count(),
        "total_news": NewsArticle.objects.count(),
        "unprocessed_news": NewsArticle.objects.filter(ai_processed_at__isnull=True).count(),
        "ai_tasks_24h": ai_total_24,
        "ai_success_rate": round(ai_success_24 / max(ai_total_24, 1) * 100),
        "ai_cost_24h": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
        "ai_cost_mtd": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_mtd)),
        "ai_tokens_24h": "{:,}".format(ai_tokens),
        "ai_avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in ai_24h) / max(ai_total_24, 1)),
        "agent_stats": agent_stats,
        "api_keys_status": api_keys_status,
        "data_sources": data_sources,
    }
    # Platform components
    from core.platform_control import PlatformComponent, is_component_enabled
    from collections import OrderedDict

    master_enabled = is_component_enabled("platform_master")
    all_components = PlatformComponent.objects.exclude(key="platform_master").order_by("category", "name")
    components_by_category = OrderedDict()
    cat_labels = {"scraper": "Data Scrapers", "pipeline": "Data Pipeline", "agent": "AI Agents", "system": "System"}
    for comp in all_components:
        label = cat_labels.get(comp.category, comp.category)
        if label not in components_by_category:
            components_by_category[label] = []
        components_by_category[label].append(comp)

    # Market configs
    from core.market_config import MarketConfig
    market_configs = MarketConfig.objects.all()
    context["market_configs"] = market_configs

    context["master_enabled"] = master_enabled
    context["components_by_category"] = components_by_category

    # What STOP ALL does NOT do. Toggling platform_master stops the scheduler
    # from running tasks; it does not close a single position. So an operator
    # who presses the big red button while holding open trades is left in the
    # worst state available: positions still live at the broker, and the bot
    # that would have honoured their stops now switched off. The page has to
    # say so, and it needs the real flatten within reach.
    from bot_program.models import AssetBotTrade, BotTrade
    context["open_trade_count"] = (
        AssetBotTrade.objects.filter(config__user=request.user,
                                     status__in=("OPEN", "CLOSE_PENDING")).count()
        + BotTrade.objects.filter(config__user=request.user,
                                  status="OPEN").count()
    )
    context["has_pin"] = bool(
        getattr(getattr(request.user, "trader_profile", None),
                "access_pin_hash", ""))

    # Phase-3/4 HQ additions: surface broker accounts + AI-related components
    # so the template can render dedicated sections without re-querying.
    from bot_program.models import (BinanceAccount, OANDAAccount,
                                    AlpacaAccount, IBKRAccount)
    broker_rows = []
    for u in User.objects.order_by("username"):
        binance = getattr(u, "binance_account", None)
        oanda = getattr(u, "oanda_account", None)
        alpaca = getattr(u, "alpaca_account", None)
        # IBKR was absent from this table entirely, so a user whose ONLY
        # broker is the one meant to carry the real book did not appear in
        # it at all — the page said "no broker accounts configured yet"
        # over a configured account.
        ibkr = getattr(u, "ibkr_account", None)
        if not (binance or oanda or alpaca or ibkr):
            continue
        broker_rows.append({
            "username": u.username,
            "binance": {
                "connected": bool(binance and binance.api_key_enc),
                "testnet": bool(binance and binance.testnet),
            } if binance else None,
            "oanda": {
                "connected": bool(oanda and oanda.api_key_enc),
                "practice": bool(oanda and oanda.practice),
            } if oanda else None,
            "alpaca": {
                "connected": bool(alpaca and alpaca.api_key_enc),
                "paper": bool(alpaca and alpaca.paper),
            } if alpaca else None,
            # `env` comes from the PORT, which is what actually selects the
            # account — never from the `paper` checkbox, which the model
            # itself documents as informational. `env` is None for a port
            # that is none of IBKR's four, and that renders as UNKNOWN
            # rather than as paper: "we could not tell" and "it is
            # simulated" are different answers.
            "ibkr": {
                "connected": bool(ibkr and ibkr.account_id_enc),
                "env": ibkr.env,
                "env_label": ibkr.env_label,
                "host": ibkr.host,
                "port": ibkr.port,
                "disagrees": ibkr.paper_flag_disagrees,
            } if ibkr else None,
        })
    context["broker_rows"] = broker_rows

    # Pull the AI-gate component out separately so the template can render a
    # prominent toggle (rather than buried inside the agent table).
    context["ai_gate_component"] = PlatformComponent.objects.filter(
        key="feature_ai_pretrade_gate"
    ).first()
    context["ai_journal_component"] = PlatformComponent.objects.filter(
        key="pipeline_ai_journal"
    ).first()
    context["ai_decay_component"] = PlatformComponent.objects.filter(
        key="pipeline_ai_decay"
    ).first()

    # Phase-5 actuator panel: pending proposals, applied (rollback-able) actions,
    # and the live-mode toggle.
    from signals.models import RuleAction, MetaAllocation
    context["actuator_live_component"] = PlatformComponent.objects.filter(
        key="actuator_mode_live"
    ).first()
    context["actuator_proposed"] = list(
        RuleAction.objects.filter(state=RuleAction.STATE_PROPOSED)
        .order_by("-proposed_at")[:10]
    )
    context["actuator_applied"] = list(
        RuleAction.objects.filter(state=RuleAction.STATE_APPLIED)
        .order_by("-applied_at")[:10]
    )

    # Phase-7 meta-allocator panel.
    context["allocator_live_component"] = PlatformComponent.objects.filter(
        key="meta_allocator_mode_live"
    ).first()
    context["allocator_shadows"] = list(
        MetaAllocation.objects.filter(state=MetaAllocation.STATE_SHADOW)
        .order_by("-proposed_at")[:5]
    )
    context["allocator_applied"] = list(
        MetaAllocation.objects.filter(state=MetaAllocation.STATE_APPLIED)
        .order_by("-applied_at")[:5]
    )

    # Strategy Evolution — the constant view: pending queue inline, so the
    # operator decides from Control without leaving for /evolution/.
    from signals.models_control import RuleControl, RuleMutation
    context["evo_pending"] = RuleMutation.objects.filter(
        state=RuleMutation.STATE_PROPOSED).count()
    context["evo_pending_rows"] = list(
        RuleMutation.objects.filter(state=RuleMutation.STATE_PROPOSED)
        .order_by("-proposed_score")[:5])
    context["evo_applied_30d"] = RuleMutation.objects.filter(
        state=RuleMutation.STATE_APPLIED,
        applied_at__gte=now - timedelta(days=30)).count()
    # The infix comes from `core.fork_names`, the module that owns the naming
    # scheme, so this LIKE cannot outlive a rename of it. It is the loose form
    # of the parser on purpose — a LIKE the DB can index, over a name shape
    # nothing but `apply_evolution` writes.
    context["evo_forks_alive"] = RuleControl.objects.filter(
        rule_name__contains=FORK_INFIX).count()

    return render(request, "dashboard/admin_dashboard.html", context)


@login_required
def admin_toggle_component(request):
    """Toggle a single platform component on/off."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.platform_control import PlatformComponent
        from django.contrib import messages
        key = request.POST.get("key", "")
        try:
            comp = PlatformComponent.objects.get(key=key)
            comp.is_enabled = not comp.is_enabled
            comp.save()
            action = "started" if comp.is_enabled else "stopped"
            messages.success(request, f"{comp.name} {action}.")
        except PlatformComponent.DoesNotExist:
            messages.error(request, f"Component '{key}' not found.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_bulk_toggle(request):
    """Enable or disable all components in a category."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.platform_control import PlatformComponent
        from django.contrib import messages
        category = request.POST.get("category", "")
        action = request.POST.get("action", "")
        enable = action == "enable"
        count = PlatformComponent.objects.filter(category=category).update(is_enabled=enable)
        verb = "started" if enable else "stopped"
        messages.success(request, f"{count} {category} components {verb}.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def instrument_detail(request, symbol):
    """Instrument detail page with chart, indicators, signals, news."""
    import json
    from instruments.models import Instrument
    from market_data.models import PriceData, LiveQuote
    from indicators.models import TechnicalIndicator
    from signals.models import Signal
    from scraping.models import NewsArticle

    instrument = get_object_or_404(Instrument, symbol=symbol)

    # Chart data — daily candles, synthesized from intraday bars when no
    # real 1d rows exist yet (see _daily_chart_bars).
    price_data = [
        {k: v for k, v in bar.items() if k != "volume"}
        for bar in _daily_chart_bars(instrument, limit=200)
    ]

    # Get quote
    quote = None
    try:
        quote = instrument.live_quote
    except Exception:
        pass

    # Get latest technicals
    technicals = TechnicalIndicator.objects.filter(instrument=instrument).first()

    # Get signals
    signals = Signal.objects.filter(instrument=instrument).order_by("-created_at")[:10]

    # Get related news
    news = instrument.news_articles.order_by("-published_at")[:5]

    # Which market this instrument answers to, and whether that market is
    # open RIGHT NOW — rendered server-side so the badge is true at first
    # paint, kept true by sv-market-status.js polling the same computation.
    from core.exchange_status import market_status_for
    try:
        market = market_status_for(instrument.asset_class, instrument.exchange)
    except Exception:
        market = None

    return render(request, "dashboard/instrument_detail.html", {
        "page_id": "instruments",
        "instrument": instrument,
        "quote": quote,
        "technicals": technicals,
        "signals": signals,
        "news": news,
        "market": market,
        "price_data_json": json.dumps(price_data),
    })


@login_required
def take_trade_preview(request, signal_id):
    """POST — the facts the TAKE TRADE confirm popup shows: sized quantity,
    levels, dollar risk, capital position and (when capital is short) the
    proposed funding closes. Nothing is executed here."""
    from django.http import HttpResponseNotAllowed, JsonResponse
    from bot_program.manual_trade import preview_take_trade
    from signals.models import Signal

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    signal = get_object_or_404(Signal, pk=signal_id, is_active=True)
    return JsonResponse(preview_take_trade(request.user, signal))


@login_required
def take_trade_execute(request, signal_id):
    """POST — execute the trade previewed above, at the operator's terms:
    the positions THEY chose to close for capital (close_ids), the size,
    the stop and the target they chose instead of the platform's. Paper
    venue only in this wave; the live path adds the PIN and the
    pending-close machinery.

    Every one of those arrives as a number in a request body, so every one
    of them is a claim rather than a fact. manual_trade re-derives the size
    against the real fill and the post-close pool, re-judges the levels
    against the same fill and the same caps the bots obey, and re-reads the
    pool after the closes; this view only proves the numbers are finite
    before handing them over.
    """
    from django.http import HttpResponseNotAllowed, JsonResponse
    from bot_program.manual_trade import execute_take_trade
    from signals.models import Signal

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    signal = get_object_or_404(Signal, pk=signal_id, is_active=True)
    body, err = _parse_trade_body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    return JsonResponse(execute_take_trade(request.user, signal,
                                           body["close_ids"],
                                           qty=body["qty"],
                                           stop=body["stop"],
                                           target=body["target"]))


def _parse_trade_body(request):
    """Parse an execute body into
    {"close_ids": [...], "side": ..., "qty": ..., "stop": ..., "target": ...}.

    Strict on shape: a non-object body 500'd (AttributeError on .get), and
    a string close_ids like "12" iterated per character into [1, 2] —
    closing trades nobody named.

    `close_ids` is the operator's chosen funding closes. It is a SELECTION,
    not an acknowledgement of what the preview proposed: the popup used to
    copy close_proposal into it wholesale, so the list arriving here was
    always the server's own recommendation coming home. Which positions are
    liquidated is the operator's decision, and this is the field that
    carries it.

    `qty`, `stop` and `target` are the operator's overrides, each None for
    "use the platform's answer". Only their SHAPE is settled here — a
    finite number, and not a bool, because float(True) is 1.0 and a JSON
    `true` would otherwise become a one-unit position or a stop at $1.
    Whether any of them is permissible is a money question, answered under
    the execution lock against the real fill, the real pool and the real
    caps — never here against a preview the browser could have edited.
    """
    import json as _json
    import math as _math
    try:
        body = _json.loads(request.body.decode() or "{}")
    except ValueError:
        return None, "Body must be JSON"
    if not isinstance(body, dict):
        return None, "Body must be a JSON object"
    raw_ids = body.get("close_ids") or []
    if not isinstance(raw_ids, list):
        return None, "close_ids must be a list"
    close_ids = [int(i) for i in raw_ids if str(i).isdigit()]

    def _number(field):
        """(value, None) or (None, reason) — absent and empty both mean
        'the platform's answer', which is not the same as zero."""
        raw = body.get(field)
        if raw is None or raw == "":
            return None, None
        if isinstance(raw, bool):
            return None, f"{field} must be a number"
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None, f"{field} must be a number"
        if not _math.isfinite(val):
            return None, f"{field} must be a finite number"
        return val, None

    parsed = {}
    for field in ("qty", "stop", "target"):
        val, err = _number(field)
        if err:
            return None, err
        parsed[field] = val

    return {"close_ids": close_ids,
            "side": str(body.get("side", "")).upper(),
            **parsed}, None


@login_required
def toggle_watchlist(request, symbol):
    """POST — star or unstar an instrument.

    The star is not cosmetic: scan_universe and the quote pollers read
    is_watchlist, so this is how an operator widens what the platform
    watches — bars, quotes and signal scans follow — without creating a
    bot for it.
    """
    from django.contrib import messages
    from django.http import HttpResponseNotAllowed
    from django.utils.http import url_has_allowed_host_and_scheme
    from instruments.models import Instrument

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    instrument = get_object_or_404(Instrument, symbol=symbol)
    instrument.is_watchlist = not instrument.is_watchlist
    instrument.save(update_fields=["is_watchlist"])
    verb = "added to" if instrument.is_watchlist else "removed from"
    messages.success(request, f"{instrument.symbol} {verb} the watchlist.")
    # Every OTHER open tab learns the new count live — best-effort, a
    # broken socket must never break the toggle itself.
    try:
        from dashboard.consumers import push_watchlist_update
        push_watchlist_update(instrument.symbol, instrument.is_watchlist)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).debug("watchlist push failed: %s", e)
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("instrument_detail", symbol=instrument.symbol)


@login_required
def signal_rail_partial(request):
    """The signal rail's cards alone. Fetched by the dashboard WebSocket
    listener when a new signal fires, so the card slides into the rail
    without a reload. Context processors supply panel_recent_signals."""
    return render(request, "_partials/signal_rail_items.html")


@login_required
def ticker_partial(request):
    """Both halves of the news ticker's marquee. Fetched by the dashboard
    WebSocket listener when a scraper stores news, so fresh headlines
    enter the band without a reload. Context processors supply
    ticker_items."""
    return render(request, "_partials/ticker_items.html")


@login_required
def notif_items_partial(request):
    """The bell panel's rows alone.

    The badge and the banner were already live; the LIST behind the bell was
    not, because it was rendered once with the page and never again. Opening
    the bell after an alert showed the rows as they were at page load — the
    operator saw the red count, clicked, and the alert it counted was not
    there. Fetched on a notification event and again whenever the panel is
    opened, so the click always lands on current rows.

    Context processors supply recent_notifications, so this and the first
    paint read the same source.
    """
    return render(request, "_partials/notif_items.html")


@login_required
def panel_counts_json(request):
    """The bottom headband's live numbers, as JSON. Fetched (debounced) by
    the /ws/eye/ listener on fill events, so the POSITIONS and BOT cells
    move the moment a trade opens or closes — they used to be render-time
    constants that froze until the next full reload."""
    from django.http import JsonResponse
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    from portfolio.services import get_or_create_default_portfolio

    # The BOT cell counts the FLEET, and a hand-taken position is not the
    # fleet. TAKE TRADE books against a per-user config named "manual" with
    # an empty symbol list — it can never open anything on its own — so
    # counting it reported the operator's own click back to them as
    # automation. `core.context_processors._is_manual_config` is the one
    # definition of that carve-out; the server-rendered cell already used
    # it, and this live path did not, so pressing TAKE TRADE flipped the
    # sub-line to "1 open" within a second while the dropdown underneath it
    # still said zero. Two surfaces, one book, opposite answers.
    #
    # POSITIONS still counts every open row, hand-taken included: that cell
    # is about exposure, and exposure does not care who opened it.
    from core.context_processors import _is_manual_config

    open_trades = list(AssetBotTrade.objects.filter(
        config__user=request.user,
        status__in=("OPEN", "CLOSE_PENDING")).select_related("config"))
    all_open = len(open_trades)
    bot_open = sum(1 for t in open_trades
                   if not _is_manual_config(t.config))
    manual_open = all_open - bot_open
    try:
        pf = get_or_create_default_portfolio(user=request.user)
        pos_open = pf.positions.filter(closed_at__isnull=True).count()
    except Exception:  # noqa: BLE001 — counts must never 500 the panel
        pos_open = 0
    watchlist = Instrument.objects.filter(
        is_watchlist=True, is_active=True).count()
    try:
        from alerts.models import Notification
        unread = Notification.unread_count(request.user)
    except Exception:  # noqa: BLE001 — counts must never 500 the panel
        unread = 0
    return JsonResponse({
        "positions": pos_open + all_open,
        "bot_open": bot_open,
        # Published so the hand-taken book stays visible rather than merely
        # uncounted — the carve-out above must not become a hiding place.
        "manual_open": manual_open,
        "watchlist": watchlist,
        "notifications": unread,
    })


# page_id -> "when did this section last produce something worth seeing".
# Each probe is the cheapest honest question its table can answer, and a
# probe that cannot be read reports None — no dot, never a lie. The dict
# is module-level so the test that walks it and the endpoint can never
# disagree about which sections exist.
def _nav_activity_probes():
    from django.db.models import Max

    def latest(qs_fn):
        def probe():
            try:
                return qs_fn()
            except Exception:  # noqa: BLE001 — a dead probe is no dot
                return None
        return probe

    from alerts.models import Notification  # noqa: F401 — locality
    return {
        "signals": latest(lambda: __import__("signals.models", fromlist=["Signal"])
                          .Signal.objects.filter(is_active=True)
                          .aggregate(m=Max("created_at"))["m"]),
        # BOTH books, like the page: the platform's own docstrings record
        # a single-book read of positions as a past bug, and the NL trader
        # and setup form open legacy Position rows no AssetBotTrade sees.
        "positions": latest(lambda: max(filter(None, (
            __import__("bot_program.models", fromlist=["AssetBotTrade"])
            .AssetBotTrade.objects.aggregate(m=Max("opened_at"))["m"],
            __import__("portfolio.models", fromlist=["Position"])
            .Position.objects.aggregate(m=Max("opened_at"))["m"],
        )), default=None)),
        "news": latest(lambda: __import__("scraping.models", fromlist=["NewsArticle"])
                       .NewsArticle.objects
                       .aggregate(m=Max("published_at"))["m"]),
        "briefing": latest(lambda: __import__("brain.briefing_models", fromlist=["StrategistBriefing"])
                           .StrategistBriefing.objects
                           .aggregate(m=Max("created_at"))["m"]),
        "hypotheses": latest(lambda: __import__("brain.knowledge_models", fromlist=["Hypothesis"])
                             .Hypothesis.objects
                             .aggregate(m=Max("resolved_at"))["m"]),
        # scanned_at, not created_at: OpportunityFlag has no created_at,
        # and the fenced FieldError made this dot permanently dark — the
        # exact silent death the "no dot, never a lie" fence can hide.
        "opportunities": latest(lambda: __import__("signals.models", fromlist=["OpportunityFlag"])
                                .OpportunityFlag.objects
                                .aggregate(m=Max("scanned_at"))["m"]),
        "generated": latest(lambda: __import__("brain.generator_models", fromlist=["GeneratedSetupProposal"])
                            .GeneratedSetupProposal.objects
                            .filter(status="pending")
                            .aggregate(m=Max("created_at"))["m"]),
    }


@login_required
def nav_activity_json(request):
    """The sidebar's unseen dots — nothing stays unseen.

    GET: {"pages": {page_id: bool}} — true when the section produced
    something newer than this operator's last visit to it. A page never
    visited counts as unseen the moment it has ANY activity: a dot that
    waited for a first visit would never light for the page most worth
    discovering.

    POST {"page_id": X}: stamps X seen now. Being on a page IS seeing it —
    the JS beacons this once per page load. Server truth on the profile,
    so two browsers agree and a phone read clears the desktop's dot.
    """
    import json as _json

    from django.http import JsonResponse
    from django.utils import timezone as _tz
    from django.utils.dateparse import parse_datetime

    from portfolio.trader_profile import TraderProfile

    profile, _ = TraderProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        try:
            body = _json.loads(request.body or b"{}")
        except ValueError:
            body = {}
        # Non-dict JSON ("null", a list) is just an empty payload, not a
        # 500 — the beacon fires from every page load and must be boring.
        page_id = (str(body.get("page_id") or "")[:40]
                   if isinstance(body, dict) else "")
        known = set(_nav_activity_probes())
        if page_id in known:
            # Rebuilt against the whitelist on every write: the map stays
            # bounded at the probe set forever and self-heals any key an
            # older client or a hand-edited row left behind.
            seen = {k: v for k, v in (profile.pages_seen or {}).items()
                    if k in known}
            seen[page_id] = _tz.now().isoformat()
            profile.pages_seen = seen
            profile.save(update_fields=["pages_seen"])
            return JsonResponse({"ok": True})
        return JsonResponse({"ok": False})

    seen = profile.pages_seen or {}
    pages = {}
    for page_id, probe in _nav_activity_probes().items():
        latest = probe()
        if latest is None:
            pages[page_id] = False
            continue
        stamp = parse_datetime(str(seen.get(page_id) or "")) if seen.get(
            page_id) else None
        pages[page_id] = stamp is None or latest > stamp
    return JsonResponse({"pages": pages})


@login_required
def exchange_status_json(request):
    """The topbar's N/14 SE indicator and its dropdown, as JSON.

    Those values were render-time constants: a tab left open across the
    New York close kept saying 5/14 with NYSE marked OPEN until somebody
    reloaded — on a platform whose every other cell moves on its own.
    sv-market-status.js polls this (clock arithmetic only, no queries
    beyond none at all) and re-paints the indicator, the dropdown rows,
    and the instrument page's market badge.
    """
    from django.http import JsonResponse
    from core.exchange_status import get_exchange_status

    try:
        return JsonResponse(get_exchange_status())
    except Exception as e:  # noqa: BLE001 — a clock bug must not 500
        logger.debug(f"exchange status unavailable: {e}")
        return JsonResponse({"open_count": 0, "total": 0, "exchanges": [],
                             "error": "unavailable"})


@login_required
def asset_trade_preview(request, symbol):
    """POST {side} — signal-less TAKE TRADE preview from an instrument
    popup (watchlist rail, price headband). Levels come from the engine's
    ATR machinery; everything else matches the signal path."""
    from django.http import HttpResponseNotAllowed, JsonResponse
    from bot_program.manual_trade import preview_asset_trade
    from instruments.models import Instrument

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    inst = get_object_or_404(Instrument, symbol=symbol, is_active=True)
    body, err = _parse_trade_body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    return JsonResponse(preview_asset_trade(request.user, inst, body["side"]))


@login_required
def asset_trade_execute(request, symbol):
    """POST {side, close_ids, qty, stop, target} — execute the signal-less
    trade previewed above. Same paper venue, same funding-close chain, same
    pre-trade controls and the same server-side re-derivation of all of
    them."""
    from django.http import HttpResponseNotAllowed, JsonResponse
    from bot_program.manual_trade import execute_asset_trade
    from instruments.models import Instrument

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    inst = get_object_or_404(Instrument, symbol=symbol, is_active=True)
    body, err = _parse_trade_body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    return JsonResponse(execute_asset_trade(request.user, inst, body["side"],
                                            body["close_ids"],
                                            qty=body["qty"],
                                            stop=body["stop"],
                                            target=body["target"]))


@login_required
def backtest_list(request):
    """Phase 63 — enriched backtest engine dashboard.

    Adds: status mix · strategy-type breakdown · top performers · win-rate
    distribution · best/worst run callouts.
    """
    import json as _json
    from collections import Counter, defaultdict
    from backtester.models import BacktestRun
    from dashboard.run_async import LOCK_TTL_SECONDS
    from instruments.models import Instrument

    runs = list(BacktestRun.objects.filter(user=request.user)
                 .order_by("-created_at")[:50])
    total = len(runs)
    completed = [r for r in runs if r.status == "completed"]
    n_completed = len(completed)
    n_running = sum(1 for r in runs if r.status == "running")
    n_failed = sum(1 for r in runs if r.status == "failed")
    n_pending = sum(1 for r in runs if r.status == "pending")

    # A run that has been queued or running longer than the platform's own
    # in-flight lock TTL is not "still working" — the worker that owed it an
    # answer is gone. Showing it as a live spinner forever is the same lie
    # the permanently-pending rows told, so it gets its own state.
    stale_before = timezone.now() - timedelta(seconds=LOCK_TTL_SECONDS)
    for r in runs:
        r.is_stale = (r.status in ("pending", "running")
                      and r.created_at < stale_before)
        r.is_live = r.status in ("pending", "running") and not r.is_stale
    n_stale = sum(1 for r in runs if r.is_stale)

    # None, not 0, when there is nothing completed to average: a 0% average
    # return across zero runs is a measurement nobody made.
    def _avg(attr):
        if not completed:
            return None
        return sum(getattr(r, attr) or 0 for r in completed) / n_completed

    avg_return = None if not completed else round(_avg("total_return_pct"), 2)
    best = max((r.total_return_pct or 0 for r in completed), default=None)
    worst = min((r.total_return_pct or 0 for r in completed), default=None)
    avg_sharpe = None if not completed else round(_avg("sharpe_ratio"), 2)
    avg_win_rate = None if not completed else round(_avg("win_rate"), 1)
    avg_dd = None if not completed else round(_avg("max_drawdown_pct"), 2)

    # Status donut.
    status_donut = []
    for k, v in [("completed", n_completed), ("running", n_running),
                  ("failed", n_failed), ("pending", n_pending)]:
        if v > 0:
            status_donut.append({"key": k, "n": v,
                                  "pct": round(v / max(total, 1) * 100, 1)})

    # Strategy-type breakdown.
    strat_rows: dict = defaultdict(
        lambda: {"n": 0, "ret": 0.0, "wins": 0})
    for r in completed:
        d = strat_rows[r.strategy_type or "—"]
        d["n"] += 1
        d["ret"] += r.total_return_pct or 0
        if (r.total_return_pct or 0) > 0:
            d["wins"] += 1
    strategy_breakdown = sorted(
        [{"strategy_type": k, **v,
          "avg_ret": round(v["ret"] / max(v["n"], 1), 2),
          "win_rate": round(v["wins"] / max(v["n"], 1) * 100, 1)}
         for k, v in strat_rows.items()],
        key=lambda r: -r["n"]
    )

    # Top 5 + worst 5 by return.
    by_ret = sorted(completed, key=lambda r: r.total_return_pct or 0,
                    reverse=True)
    top_runs = by_ret[:5]
    worst_runs = list(reversed(by_ret[-5:])) if len(by_ret) > 5 else []

    instruments = list(Instrument.objects.filter(is_active=True)
                        .order_by("symbol")
                        .values("id", "symbol", "name", "asset_class"))
    strategies = []
    try:
        from strategies.models import Strategy
        strategies = list(Strategy.objects.all()
                           .values("id", "name", "time_horizon"))
    except Exception:
        pass

    return render(request, "dashboard/backtest_list.html", {
        "page_id": "backtest",
        "runs": runs,
        "total": total,
        "completed_count": n_completed,
        "n_running": n_running,
        "n_failed": n_failed,
        "n_pending": n_pending,
        "n_stale": n_stale,
        # True while anything is genuinely in flight — the page polls itself
        # only then, so a settled history is a static page again.
        "has_live_runs": any(r.is_live for r in runs),
        "stale_after_minutes": LOCK_TTL_SECONDS // 60,
        "avg_return": avg_return,
        "best_return": None if best is None else round(best, 2),
        "worst_return": None if worst is None else round(worst, 2),
        "avg_sharpe": avg_sharpe,
        "avg_win_rate": avg_win_rate,
        "avg_dd": avg_dd,
        "status_donut": status_donut,
        "strategy_breakdown": strategy_breakdown,
        "top_runs": top_runs,
        "worst_runs": worst_runs,
        "instruments_json": _json.dumps(instruments),
        "strategies_json": _json.dumps(strategies, default=str),
    })


@login_required
def backtest_create(request):
    """Create and launch a new backtest.

    "Launch" is the operative word. This endpoint used to create the row
    and return, with the three dispatch lines commented out and no
    backtester.tasks module to import — so every click filed a request
    that nothing ever picked up and the row sat on "pending" forever.

    The row is now handed to a worker before this function returns, and
    if it cannot be (no broker, or a plain non-XHR form POST) it is run
    HERE rather than filing another abandoned pending row. Either way the
    caller gets an answer that reflects what actually happened.
    """
    from django.http import JsonResponse
    from backtester.models import BacktestRun
    from backtester.tasks import (BacktestConfigError, resolve_strategy,
                                  run_backtest as run_backtest_task)
    from dashboard.run_async import maybe_dispatch_async

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    try:
        name = request.POST.get("name", "").strip() or "Untitled Backtest"
        # No default strategy: the old one was "smc_signals", which no engine
        # here can honestly run. A missing field is a caller error, not a
        # reason to silently pick a strategy the operator did not choose.
        strategy_type = request.POST.get("strategy_type", "")
        symbols_raw = request.POST.get("symbols", "")
        symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        initial_capital = float(request.POST.get("initial_capital", 10000))
        params = {}
        if request.POST.get("position_size_pct"):
            params["position_size_pct"] = float(request.POST["position_size_pct"])
        if request.POST.get("stop_loss_pct"):
            params["stop_loss_pct"] = float(request.POST["stop_loss_pct"])
        if request.POST.get("take_profit_pct"):
            params["take_profit_pct"] = float(request.POST["take_profit_pct"])
        if request.POST.get("timeframe"):
            params["timeframe"] = request.POST["timeframe"]

        # Checked BEFORE the row exists so an unrunnable strategy comes back
        # as an inline form error, instead of littering the history with a
        # failed run the operator has to go read to learn what went wrong.
        try:
            resolve_strategy(strategy_type, params)
        except BacktestConfigError as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        if not symbols:
            return JsonResponse(
                {"ok": False,
                 "error": "Select at least one symbol to backtest."},
                status=400)

        run = BacktestRun.objects.create(
            user=request.user,
            name=name,
            strategy_type=strategy_type,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            parameters=params,
            status="pending",
        )
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)

    # The lock inside maybe_dispatch_async is per-job. Keying it on the run
    # id rather than a constant is what lets two backtests be in flight at
    # once — a shared key would 409 the second launch for the whole 15-minute
    # lock TTL. Hyphenated because the string also becomes a cache key.
    job = f"backtest-run-{run.id}"
    resp = maybe_dispatch_async(request, run_backtest_task, job, "/backtest/",
                                kwargs={"run_id": run.id})
    if resp is not None:
        if resp.status_code != 202:
            # A 409 means the lock for this job is already held. Pass it
            # through rather than dressing it up as a successful launch —
            # reporting "ok" for a run nobody started is how the row got
            # stranded on pending in the first place.
            return resp
        # Enqueued. The row stays "pending" — meaning QUEUED — until a worker
        # claims it and marks it running. Completion arrives on the operator's
        # /ws/eye/ socket via the run_async link callbacks.
        return JsonResponse({"ok": True, "id": run.id, "queued": True,
                             "redirect": "/backtest/"}, status=202)

    # No async lane: broker down, or a plain form POST. Run it in the request
    # rather than leaving behind the pending row this endpoint was fixed for.
    # The task owns the status contract, so a failure here still settles the
    # row on "failed" with a readable error instead of raising into a 500.
    result = run_backtest_task(run_id=run.id)
    run.refresh_from_db()
    if run.status == "failed":
        return JsonResponse({"ok": False, "id": run.id, "error": run.error},
                            status=400)
    return JsonResponse({"ok": True, "id": run.id, "queued": False,
                         "trades": run.total_trades,
                         "note": result.get("note", ""),
                         "redirect": "/backtest/"})


@login_required
def instrument_preview_api(request, symbol):
    """API endpoint for instrument hover preview."""
    from django.http import JsonResponse
    from instruments.models import Instrument
    from signals.models import Signal

    try:
        inst = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return JsonResponse({"symbol": symbol, "error": "not_found"})

    # Get quote
    price = None
    change_pct = 0
    volume = None
    try:
        quote = inst.live_quote
        price = str(quote.last)
        change_pct = float(quote.change_pct)
        volume = str(quote.volume) if quote.volume else None
    except Exception:
        pass

    # Count signals
    active_signals = Signal.objects.filter(instrument=inst, is_active=True).count()

    return JsonResponse({
        "symbol": inst.symbol,
        "name": inst.name,
        "asset_class": inst.asset_class,
        "exchange": inst.exchange,
        "price": price,
        "change_pct": change_pct,
        "volume": volume,
        "active_signals": active_signals,
    })


@login_required
def admin_create_user(request):
    """Create a new user from admin popup."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from django.contrib.auth.models import User
        from django.contrib import messages
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        email = request.POST.get("email", "")
        first_name = request.POST.get("first_name", "")
        last_name = request.POST.get("last_name", "")
        is_staff = "is_staff" in request.POST
        is_superuser = "is_superuser" in request.POST

        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
        else:
            user = User.objects.create_user(
                username=username, password=password, email=email,
                first_name=first_name, last_name=last_name,
            )
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()
            messages.success(request, f"User '{username}' created successfully.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_toggle_market(request):
    """Toggle a market on/off from admin dashboard."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.market_config import MarketConfig
        from django.contrib import messages
        key = request.POST.get("market_key", "")
        try:
            market = MarketConfig.objects.get(market_key=key)
            market.is_enabled = not market.is_enabled
            market.save()
            action = "enabled" if market.is_enabled else "disabled"
            messages.success(request, f"{market.display_name} market {action}.")
        except MarketConfig.DoesNotExist:
            messages.error(request, f"Market '{key}' not found.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_newsletters(request):
    """Newsletter management page."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    from alerts.models import Newsletter
    from django.contrib import messages

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "create":
            nl = Newsletter.objects.create(
                title=request.POST.get("title", "Weekly Report"),
                frequency=request.POST.get("frequency", "weekly"),
                send_telegram="send_telegram" in request.POST,
                send_email="send_email" in request.POST,
                send_whatsapp="send_whatsapp" in request.POST,
                created_by=request.user,
            )
            # Auto-generate with AI
            from alerts.newsletter_service import generate_newsletter_with_ai
            generate_newsletter_with_ai(nl, nl.frequency)
            messages.success(request, f"Newsletter '{nl.title}' generated. Review before sending.")

        elif action == "approve":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            nl.status = "approved"
            nl.save()
            messages.success(request, f"Newsletter '{nl.title}' approved.")

        elif action == "send":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            from alerts.newsletter_service import send_newsletter
            result = send_newsletter(nl)
            if "error" in result:
                messages.error(request, result["error"])
            else:
                messages.success(request, f"Newsletter sent to {result['recipients']} recipients.")

        elif action == "edit":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            nl.content_markdown = request.POST.get("content", nl.content_markdown)
            nl.title = request.POST.get("title", nl.title)
            nl.save()
            messages.success(request, "Newsletter updated.")

        elif action == "delete":
            nl_id = request.POST.get("newsletter_id")
            Newsletter.objects.filter(id=nl_id).delete()
            messages.success(request, "Newsletter deleted.")

        from django.shortcuts import redirect
        return redirect("admin_newsletters")

    newsletters = Newsletter.objects.all()[:30]
    return render(request, "dashboard/admin_newsletters.html", {
        "page_id": "admin_newsletters",
        "newsletters": newsletters,
    })


@login_required
def user_notifications(request):
    """User notification preferences page."""
    from alerts.models import UserNotificationPrefs, AlertRule
    from django.contrib import messages

    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_prefs":
            prefs.telegram_chat_id = request.POST.get("telegram_chat_id", "")
            prefs.whatsapp_number = request.POST.get("whatsapp_number", "")
            prefs.email_notifications = "email_notifications" in request.POST
            prefs.sms_number = request.POST.get("sms_number", "")
            prefs.receive_signals = "receive_signals" in request.POST
            prefs.receive_strategies = "receive_strategies" in request.POST
            prefs.receive_news_alerts = "receive_news_alerts" in request.POST
            prefs.receive_portfolio_alerts = "receive_portfolio_alerts" in request.POST
            prefs.receive_weekly_newsletter = "receive_weekly_newsletter" in request.POST
            prefs.receive_monthly_newsletter = "receive_monthly_newsletter" in request.POST
            prefs.receive_bot_alerts = "receive_bot_alerts" in request.POST
            prefs.receive_strategist_briefing = "receive_strategist_briefing" in request.POST
            # Phase-44 — quiet hours (UTC). Empty string clears the window.
            qs = (request.POST.get("quiet_start") or "").strip()
            qe = (request.POST.get("quiet_end") or "").strip()
            from datetime import datetime as _dt
            try:
                prefs.quiet_start = _dt.strptime(qs, "%H:%M").time() if qs else None
            except ValueError:
                prefs.quiet_start = None
            try:
                prefs.quiet_end = _dt.strptime(qe, "%H:%M").time() if qe else None
            except ValueError:
                prefs.quiet_end = None
            prefs.save()
            messages.success(request, "Notification preferences saved.")

        elif action == "add_rule":
            AlertRule.objects.create(
                user=request.user,
                name=request.POST.get("rule_name", "Custom Alert"),
                instrument_symbol=request.POST.get("rule_symbol", ""),
                asset_class=request.POST.get("rule_asset_class", ""),
                min_score=float(request.POST.get("rule_min_score", 0.5)),
                direction=request.POST.get("rule_direction", ""),
                notify_telegram="rule_telegram" in request.POST,
                notify_email="rule_email" in request.POST,
                notify_whatsapp="rule_whatsapp" in request.POST,
            )
            messages.success(request, "Alert rule created.")

        elif action == "delete_rule":
            rule_id = request.POST.get("rule_id")
            AlertRule.objects.filter(id=rule_id, user=request.user).delete()
            messages.success(request, "Alert rule deleted.")

        from django.shortcuts import redirect
        return redirect("user_notifications")

    rules = AlertRule.objects.filter(user=request.user)
    return render(request, "dashboard/user_notifications.html", {
        "page_id": "notifications",
        "prefs": prefs,
        "rules": rules,
    })


@login_required
def tour_complete(request):
    """Stamp the guided tour finished (or skipped — same thing: the user
    decided). POST-only like every other state change; replay runs are
    purely client-side and never call this."""
    from django.http import HttpResponseNotAllowed, JsonResponse
    from django.utils import timezone as _tz
    from portfolio.trader_profile import get_or_create_profile
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    profile = get_or_create_profile(request.user)
    profile.tour_completed_at = _tz.now()
    profile.save(update_fields=["tour_completed_at", "updated_at"])
    return JsonResponse({"status": "ok"})


@login_required
def notifications_inbox(request):
    """Every notification, paginated — the bell shows ten, this shows all.

    Filters: ?type=<choice> and ?unread=1. Each row shows the FULL body
    (the bell truncates at 110 chars) plus an "open" link when the row
    carries a resolvable url — a notification click must always lead
    somewhere real.
    """
    from alerts.models import Notification
    from django.core.paginator import Paginator
    from django.db.models import Count, Q

    qs = Notification.objects.filter(user=request.user)
    type_filter = (request.GET.get("type") or "").strip()
    valid_types = {t[0] for t in Notification.TYPES}
    if type_filter in valid_types:
        qs = qs.filter(notification_type=type_filter)
    unread_only = request.GET.get("unread") == "1"
    if unread_only:
        qs = qs.filter(read=False)

    counts = dict(
        Notification.objects.filter(user=request.user)
        .values_list("notification_type")
        .annotate(n=Count("id")).order_by())
    type_tabs = [(key, label, counts.get(key, 0))
                 for key, label in Notification.TYPES]
    page = Paginator(qs, 25).get_page(request.GET.get("page"))

    return render(request, "dashboard/notifications_inbox.html", {
        "page_id": "notifications_inbox",
        "page_obj": page,
        "type_tabs": type_tabs,
        "type_filter": type_filter,
        "unread_only": unread_only,
        "unread_total": Notification.unread_count(request.user),
        "total": sum(counts.values()),
    })


@login_required
def mark_notification_read(request, notif_id):
    """Mark a single notification as read."""
    from alerts.models import Notification
    from django.http import JsonResponse
    Notification.objects.filter(id=notif_id, user=request.user).update(read=True)
    return JsonResponse({"status": "ok"})


@login_required
def mark_all_notifications_read(request):
    """Mark notifications as read. POST only — a state change on GET let
    any prefetching proxy silently clear the operator's inbox.

    Two callers, one endpoint. With no `ids` this is the "Mark all read"
    control and every unread row goes. With `ids` it is the bell's
    mark-on-view, which may only retire the rows the panel actually
    showed — opening the bell must not clear fifty older notifications
    nobody has laid eyes on.

    Both forms filter on request.user before anything is written, so an
    id lifted from another account matches nothing, and both are
    idempotent: the queryset is already narrowed to read=False, so a
    repeat POST updates zero rows.
    """
    from alerts.models import Notification
    from django.http import HttpResponseNotAllowed, JsonResponse
    from django.shortcuts import redirect
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    qs = Notification.objects.filter(user=request.user, read=False)
    raw = request.POST.getlist("ids")
    if raw:
        # One malformed id must not cost the other nine their update, so
        # junk is dropped rather than raised — and an all-junk list marks
        # nothing rather than falling through to "everything".
        ids = []
        for value in raw:
            for part in str(value).split(","):
                # isdigit() is NOT int()'s alphabet: it accepts superscripts
                # and circled digits ('²', '①') that int() then rejects with
                # ValueError — a 500 on this endpoint from a crafted body.
                part = part.strip()
                try:
                    ids.append(int(part))
                except ValueError:
                    continue
        qs = qs.filter(id__in=ids)

    marked = qs.update(read=True)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "status": "ok", "marked": marked,
            "unread": Notification.unread_count(request.user),
        })
    return redirect(request.META.get("HTTP_REFERER", "/notifications/"))


@login_required
def ai_chat_api(request):
    """AI chat endpoint — send question to Claude, get response with conversation memory."""
    from django.http import JsonResponse
    import json, os

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        message = data.get("message", "")
    except Exception:
        return JsonResponse({"error": "Invalid request"}, status=400)

    if not message:
        return JsonResponse({"error": "Empty message"}, status=400)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JsonResponse({"response": "Anthropic API key not configured. Add ANTHROPIC_API_KEY to your .env file."})

    # Build rich context
    context_parts = [f"User: {request.user.username}"]
    try:
        from signals.models import Signal
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import Position
        portfolio = get_or_create_default_portfolio(user=request.user)
        context_parts.append(f"Portfolio: {portfolio.currency} {portfolio.current_value}")

        open_positions = Position.objects.filter(
            portfolio=portfolio, closed_at__isnull=True
        ).select_related("instrument")[:10]
        if open_positions:
            pos_list = [f"{p.instrument.symbol} {p.direction} {p.quantity}@{p.entry_price} (P&L: {p.unrealized_pnl_pct:.1f}%)" for p in open_positions]
            context_parts.append(f"Open positions: {'; '.join(pos_list)}")

        active = Signal.objects.filter(is_active=True).order_by("-score")[:5]
        if active:
            sig_list = [f"{s.instrument.symbol} {s.direction} score={s.score:.2f}" for s in active.select_related("instrument")]
            context_parts.append(f"Top signals: {'; '.join(sig_list)}")
    except Exception:
        pass

    system_prompt = f"""You are Sauron Vision AI, a trading intelligence assistant.
You help traders analyze markets, review signals, and make informed decisions.
Current user context: {'; '.join(context_parts)}
Be concise, data-driven, and professional. Use markdown formatting."""

    # Conversation memory via session — keep last 20 messages
    SESSION_KEY = "ai_chat_history"
    MAX_HISTORY = 20
    history = request.session.get(SESSION_KEY, [])

    # Add user message to history
    history.append({"role": "user", "content": message})

    # Trim to keep within token budget (last MAX_HISTORY messages)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    try:
        import requests as req
        resp = req.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }, json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": history,
        }, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        ai_text = result.get("content", [{}])[0].get("text", "No response")

        # Add assistant response to history and save
        history.append({"role": "assistant", "content": ai_text})
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        request.session[SESSION_KEY] = history

        return JsonResponse({"response": ai_text})
    except Exception as e:
        return JsonResponse({"response": f"AI request failed: {str(e)}"})


@login_required
def ai_chat_stream(request):
    """SSE streaming AI chat endpoint."""
    import json, os
    from django.http import StreamingHttpResponse

    message = request.GET.get("message", "")
    if not message:
        return JsonResponse({"error": "Empty message"}, status=400)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JsonResponse({"error": "API key not configured"}, status=500)

    # Build same context as ai_chat_api
    context_parts = [f"User: {request.user.username}"]
    try:
        from signals.models import Signal
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=request.user)
        context_parts.append(f"Portfolio: {portfolio.currency} {portfolio.current_value}")
        active = Signal.objects.filter(is_active=True).count()
        context_parts.append(f"Active signals: {active}")
    except Exception:
        pass

    system_prompt = f"""You are Sauron Vision AI, a trading intelligence assistant.
You help traders analyze markets, review signals, and make informed decisions.
Current user context: {'; '.join(context_parts)}
Be concise, data-driven, and professional. Use markdown formatting."""

    # Get conversation history from session
    SESSION_KEY = "ai_chat_history"
    history = request.session.get(SESSION_KEY, [])
    history.append({"role": "user", "content": message})
    if len(history) > 20:
        history = history[-20:]

    def stream_response():
        import requests as req
        full_text = ""
        try:
            resp = req.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
            }, json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "stream": True,
                "system": system_prompt,
                "messages": history,
            }, stream=True, timeout=60)
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                        if event.get("type") == "content_block_delta":
                            text = event.get("delta", {}).get("text", "")
                            if text:
                                full_text += text
                                yield f"data: {json.dumps({'text': text})}\n\n"
                    except json.JSONDecodeError:
                        pass

            # Save to session after streaming completes
            history.append({"role": "assistant", "content": full_text})
            request.session[SESSION_KEY] = history[-20:]
            request.session.save()

            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    response = StreamingHttpResponse(stream_response(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def ai_chat_page(request):
    """Phase 64.5 — legacy redirect.

    The standalone "AI Chat" page was a generic Claude pass-through with no
    Sauron context. It's been merged into /research/ which now shows live
    Mind context next to the conversation. The URL is kept as a 302 redirect
    so old bookmarks continue to land somewhere useful.
    """
    return redirect("research_view")


@login_required
def intro_page(request):
    """Login intro animation — plays once per browser session, then hands off
    to the Operations Center. Repeat visits within the session skip straight
    through (a fresh login flushes the session and replays it); the page
    itself also carries a Skip button."""
    if request.session.get("sauron_intro_seen"):
        return redirect("command_center")
    request.session["sauron_intro_seen"] = True
    return render(request, "dashboard/intro.html")


# ── Chart Data API ──────────────────────────────────────────────────────────

def _daily_chart_bars(instrument, since=None, limit=None):
    """Daily OHLCV dicts for a chart, synthesized from intraday bars when
    no real daily rows exist.

    A fresh deployment has 1h/4h bars DAYS before its first daily row: the
    bot-bar feed writes intraday only, and the EOD scraper runs nightly and
    covered a subset of instruments — so every chart on a new box queried
    an empty table and rendered blank while the data to draw it sat one
    timeframe over. A daily candle IS the aggregate of its day's intraday
    bars, so the synthesis is exact for the hours the platform has.
    """
    from market_data.models import PriceData

    def _rows(tf):
        qs = PriceData.objects.filter(instrument=instrument, timeframe=tf)
        if since is not None:
            qs = qs.filter(timestamp__gte=since)
        return qs.order_by("timestamp")

    bars = [{
        "time":   p.timestamp.strftime("%Y-%m-%d"),
        "open":   float(p.open),
        "high":   float(p.high),
        "low":    float(p.low),
        "close":  float(p.close),
        "volume": float(p.volume) if p.volume else 0,
    } for p in _rows("1d")]

    if not bars:
        for intraday_tf in ("4h", "1h"):
            days = {}
            for p in _rows(intraday_tf):
                key = p.timestamp.strftime("%Y-%m-%d")
                d = days.get(key)
                if d is None:
                    days[key] = {
                        "time": key, "open": float(p.open),
                        "high": float(p.high), "low": float(p.low),
                        "close": float(p.close),
                        "volume": float(p.volume) if p.volume else 0,
                    }
                else:
                    d["high"] = max(d["high"], float(p.high))
                    d["low"] = min(d["low"], float(p.low))
                    d["close"] = float(p.close)
                    d["volume"] += float(p.volume) if p.volume else 0
            if days:
                bars = [days[k] for k in sorted(days)]
                break

    if limit:
        bars = bars[-int(limit):]
    return bars


def _intraday_chart_bars(instrument, interval, limit=240):
    """Intraday OHLCV dicts, freshest first source wins.

    1h/4h come from PriceData (the bot/watchlist passes keep them warm).
    Finer resolutions are not stored anywhere — persisting minute bars for
    every instrument would bloat the table for a chart click — so they are
    fetched LIVE from the keyless public feed and cached for a minute.
    `time` is epoch seconds: lightweight-charts needs numeric time for
    intraday resolution.
    """
    from django.core.cache import cache
    from market_data.models import PriceData

    if interval in ("1h", "4h"):
        rows = (PriceData.objects.filter(instrument=instrument,
                                         timeframe=interval)
                .order_by("-timestamp")[:limit])
        bars = [{
            "time":   int(p.timestamp.timestamp()),
            "open":   float(p.open), "high": float(p.high),
            "low":    float(p.low), "close": float(p.close),
            "volume": float(p.volume) if p.volume else 0,
        } for p in reversed(list(rows))]
        if bars:
            return bars
        # No stored rows (instrument outside the fleet/watchlist) — fall
        # through to the live fetch below.

    cache_key = f"chart:{instrument.symbol}:{interval}"
    try:
        cached = cache.get(cache_key)
    except Exception:  # noqa: BLE001
        cached = None
    if cached is not None:
        return cached

    from market_data.public_feed import public_feed_for
    client = public_feed_for(instrument.asset_class)
    if client is None:
        return []
    fetch_symbol = instrument.symbol
    if instrument.asset_class == "crypto":
        from market_data.management.commands.backfill_bars import venue_symbol
        fetch_symbol = venue_symbol(instrument.symbol)

    bars = []
    try:
        for row in client.klines(fetch_symbol, interval=interval,
                                 limit=limit) or []:
            if not row or len(row) < 6:
                continue
            bars.append({
                "time":   int(int(row[0]) / 1000),
                "open":   float(row[1]), "high": float(row[2]),
                "low":    float(row[3]), "close": float(row[4]),
                "volume": float(row[5] or 0),
            })
    except Exception:  # noqa: BLE001 — a dead feed is an empty chart, not a 500
        bars = []
    try:
        cache.set(cache_key, bars, 60)
    except Exception:  # noqa: BLE001
        pass
    return bars


# Live-fetched resolutions. 1h/4h are handled from stored bars first.
INTRADAY_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m",
                      "1h": "1h", "4h": "4h"}


@login_required
def chart_data_api(request):
    """
    Returns OHLCV bars for a symbol + timeframe.

    GET /api/chart-data/?symbol=AAPL&timeframe=1d
    Response: { "bars": [{"time": ..., "open": ..., "high": ..., "low": ...,
                          "close": ..., "volume": ...}, ...] }

    Two families of timeframe:
      * Ranges of DAILY candles ("1d", "1w", "1mo"/"1m", "3m", "1y") —
        `time` is a date string.
      * Intraday RESOLUTIONS ("1min", "5min", "15min", "1h", "4h") —
        `time` is epoch seconds; minute bars are fetched live from the
        keyless public feed and cached for a minute.
    """
    from django.http import JsonResponse
    from instruments.models import Instrument
    from django.utils import timezone
    from datetime import timedelta

    symbol    = request.GET.get("symbol", "").strip().upper()
    timeframe = request.GET.get("timeframe", "1d").strip().lower()

    if not symbol:
        return JsonResponse({"error": "symbol required", "bars": []})

    try:
        instrument = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return JsonResponse({"error": f"Symbol '{symbol}' not found", "bars": []})

    # The UI sends "1min"/"5min"/"15min" (never bare "1m", which has
    # always meant ONE MONTH here — the legacy range value keeps working).
    interval = {"1min": "1m", "5min": "5m", "15min": "15m",
                "1h": "1h", "4h": "4h"}.get(timeframe)
    if interval:
        bars = _intraday_chart_bars(instrument, interval)
        if not bars:
            return JsonResponse({
                "symbol": symbol, "timeframe": timeframe, "bars": [],
                "error": f"No intraday source for {symbol} at {timeframe}"})
        return JsonResponse({"symbol": symbol, "timeframe": timeframe,
                             "bars": bars})

    # UI timeframe -> how far back to look. These views draw daily candles.
    DAYS_BACK = {"1d": 90, "1w": 365, "1m": 30, "1mo": 30,
                 "3m": 90, "1y": 365}
    days_back = DAYS_BACK.get(timeframe, 90)
    since = timezone.now() - timedelta(days=days_back)

    bars = _daily_chart_bars(instrument, since=since)
    return JsonResponse({"symbol": symbol, "timeframe": timeframe, "bars": bars})


# ── Dashboard Preset APIs ───────────────────────────────────────────────────

@login_required
def dashboard_presets_api(request):
    """
    GET  — Returns list of user's dashboard presets (creates defaults if none exist).
    POST — Creates a new custom preset.
           Body: { "name": "My Layout", "config": { "sections": [...] } }
    """
    from django.http import JsonResponse
    import json
    from .models import DashboardPreset

    if request.method == "GET":
        # Ensure defaults exist
        DashboardPreset.get_or_create_defaults(request.user)
        presets = DashboardPreset.objects.filter(user=request.user).order_by("preset_type", "name")
        data = []
        for p in presets:
            data.append({
                "id":          p.id,
                "name":        p.name,
                "preset_type": p.preset_type,
                "config":      p.layout_config,
                "is_active":   p.is_active,
                "created_at":  p.created_at.isoformat(),
            })
        active = DashboardPreset.get_active_for_user(request.user)
        return JsonResponse({
            "presets":   data,
            "active_id": active.id if active else None,
        })

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        name   = body.get("name", "").strip()
        config = body.get("config", {})

        if not name:
            return JsonResponse({"ok": False, "error": "name is required"}, status=400)

        if DashboardPreset.objects.filter(user=request.user, name=name).exists():
            return JsonResponse({"ok": False, "error": f"A preset named '{name}' already exists"}, status=409)

        preset = DashboardPreset.objects.create(
            user=request.user,
            name=name,
            preset_type="custom",
            layout_config=config,
            is_active=False,
        )
        return JsonResponse({
            "ok":    True,
            "id":    preset.id,
            "name":  preset.name,
            "type":  preset.preset_type,
            "config": preset.layout_config,
        }, status=201)

    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


@login_required
def dashboard_preset_activate(request, preset_id):
    """
    POST — Activates a preset, deactivating all others for the user.
    """
    from django.http import JsonResponse
    from .models import DashboardPreset

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    try:
        preset = DashboardPreset.objects.get(id=preset_id, user=request.user)
    except DashboardPreset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Preset not found"}, status=404)

    # Deactivate all, then activate chosen one
    DashboardPreset.objects.filter(user=request.user).update(is_active=False)
    preset.is_active = True
    preset.save(update_fields=["is_active"])

    return JsonResponse({
        "ok":        True,
        "active_id": preset.id,
        "name":      preset.name,
        "config":    preset.layout_config,
    })


@login_required
def dashboard_preset_delete(request, preset_id):
    """
    DELETE — Removes a custom preset. Built-in presets (morning/active/eod) cannot be deleted.
    """
    from django.http import JsonResponse
    from .models import DashboardPreset

    if request.method != "DELETE":
        return JsonResponse({"ok": False, "error": "DELETE required"}, status=405)

    try:
        preset = DashboardPreset.objects.get(id=preset_id, user=request.user)
    except DashboardPreset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Preset not found"}, status=404)

    if preset.preset_type != "custom":
        return JsonResponse({"ok": False, "error": "Built-in presets cannot be deleted"}, status=403)

    preset.delete()
    return JsonResponse({"ok": True, "deleted_id": preset_id})


# ── Annotations API ─────────────────────────────────────────────────────────

@login_required
def annotations_api(request):
    """GET list of annotations (filtered by type/target), POST to create."""
    from django.http import JsonResponse
    import json
    from .models import UserAnnotation

    if request.method == "GET":
        qs = UserAnnotation.objects.filter(user=request.user)
        ann_type = request.GET.get("type", "")
        target_id = request.GET.get("target_id", "")
        target_symbol = request.GET.get("symbol", "")
        if ann_type:
            qs = qs.filter(annotation_type=ann_type)
        if target_id:
            qs = qs.filter(target_id=target_id)
        if target_symbol:
            qs = qs.filter(target_symbol__iexact=target_symbol)
        data = [
            {
                "id": a.id,
                "annotation_type": a.annotation_type,
                "target_id": a.target_id,
                "target_symbol": a.target_symbol,
                "content": a.content,
                "color": a.color,
                "pinned": a.pinned,
                "created_at": a.created_at.isoformat(),
                "updated_at": a.updated_at.isoformat(),
            }
            for a in qs[:100]
        ]
        return JsonResponse({"annotations": data})

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        content = body.get("content", "").strip()
        if not content:
            return JsonResponse({"ok": False, "error": "content is required"}, status=400)

        ann = UserAnnotation.objects.create(
            user=request.user,
            annotation_type=body.get("annotation_type", "general"),
            target_id=body.get("target_id") or None,
            target_symbol=body.get("target_symbol", ""),
            content=content,
            color=body.get("color", "#ffeb3b"),
            pinned=bool(body.get("pinned", False)),
        )
        return JsonResponse({
            "ok": True,
            "id": ann.id,
            "annotation_type": ann.annotation_type,
            "target_symbol": ann.target_symbol,
            "content": ann.content,
            "color": ann.color,
            "pinned": ann.pinned,
            "created_at": ann.created_at.isoformat(),
        }, status=201)

    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


@login_required
def annotation_delete(request, pk):
    """DELETE — Remove a user annotation by pk."""
    from django.http import JsonResponse
    from .models import UserAnnotation

    if request.method != "DELETE":
        return JsonResponse({"ok": False, "error": "DELETE required"}, status=405)

    try:
        ann = UserAnnotation.objects.get(id=pk, user=request.user)
    except UserAnnotation.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Annotation not found"}, status=404)

    ann.delete()
    return JsonResponse({"ok": True, "deleted_id": pk})


# ── Risk Dashboard API ───────────────────────────────────────────────────────

@login_required
def risk_dashboard_api(request):
    """API endpoint for risk metrics, VaR, and stress testing."""
    from django.http import JsonResponse
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.risk_engine import RiskEngine

    portfolio = get_or_create_default_portfolio(user=request.user)
    engine = RiskEngine(portfolio)

    action = request.GET.get("action", "all")

    if action == "var":
        method = request.GET.get("method", "historical")
        confidence = float(request.GET.get("confidence", 0.95))
        result = engine.calculate_var(confidence=confidence, method=method)
        return JsonResponse(result)
    elif action == "stress":
        result = engine.stress_test()
        return JsonResponse({"scenarios": result})
    elif action == "metrics":
        result = engine.calculate_risk_metrics()
        return JsonResponse(result)
    else:
        return JsonResponse({
            "var": engine.calculate_var(),
            "stress_test": engine.stress_test(),
            "risk_metrics": engine.calculate_risk_metrics(),
        })


# ── Monte Carlo / Regime / Position Sizing APIs ──────────────────────────────

@login_required
def monte_carlo_api(request):
    """Run Monte Carlo simulation on a strategy's trades."""
    from django.http import JsonResponse
    from backtester.monte_carlo import run_monte_carlo

    strategy_id = request.GET.get('strategy_id')
    if not strategy_id:
        return JsonResponse({'error': 'strategy_id required'}, status=400)

    from strategies.models import Strategy
    from portfolio.models import Position

    strategy = Strategy.objects.filter(id=strategy_id).first()
    if not strategy:
        return JsonResponse({'error': 'strategy not found'}, status=404)

    # Get closed positions for this strategy
    closed = Position.objects.filter(strategy=strategy, closed_at__isnull=False)
    trades = []
    for pos in closed:
        if pos.entry_price and pos.entry_price > 0:
            pnl_pct = float((pos.current_price - pos.entry_price) / pos.entry_price * 100)
            if pos.direction.lower() in ('short',):
                pnl_pct = -pnl_pct
            trades.append({'pnl_pct': pnl_pct})

    if not trades:
        # Fall back to backtest trades log
        from backtester.models import BacktestRun
        bt = BacktestRun.objects.filter(strategy_type=strategy.name).order_by('-created_at').first()
        if bt and bt.trades_log:
            trades = [{'pnl_pct': t.get('pnl_pct', t.get('pnl', 0))} for t in bt.trades_log]

    result = run_monte_carlo(trades)
    return JsonResponse(result)


@login_required
def regime_api(request):
    """Get current market regime detection."""
    from django.http import JsonResponse
    from signals.regime_detector import RegimeDetector

    symbol = request.GET.get('symbol')
    instrument = None
    if symbol:
        from instruments.models import Instrument
        instrument = Instrument.objects.filter(symbol=symbol).first()

    detector = RegimeDetector()
    result = detector.detect(instrument=instrument)
    return JsonResponse(result)


@login_required
def position_sizing_api(request):
    """Calculate position sizing recommendations."""
    from django.http import JsonResponse
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.position_sizing import PositionSizer

    portfolio = get_or_create_default_portfolio(user=request.user)
    sizer = PositionSizer(portfolio)

    method = request.GET.get('method', 'volatility')
    symbol = request.GET.get('symbol')

    if method == 'kelly':
        win_rate = float(request.GET.get('win_rate', 0.5))
        avg_win = float(request.GET.get('avg_win', 2.0))
        avg_loss = float(request.GET.get('avg_loss', 1.0))
        result = sizer.kelly_criterion(win_rate, avg_win, avg_loss)
    elif method == 'fixed_risk':
        entry = float(request.GET.get('entry_price', 0))
        stop = float(request.GET.get('stop_loss', 0))
        risk_pct = float(request.GET.get('risk_pct', 0.02))
        result = sizer.fixed_risk(entry, stop, risk_pct)
    else:
        if not symbol:
            return JsonResponse({'error': 'symbol required for volatility sizing'}, status=400)
        from instruments.models import Instrument
        instrument = Instrument.objects.filter(symbol=symbol).first()
        if not instrument:
            return JsonResponse({'error': 'instrument not found'}, status=404)
        risk_pct = float(request.GET.get('risk_pct', 0.02))
        result = sizer.volatility_based(instrument, risk_pct)

    return JsonResponse(result)


# ── Pop-Out Panel ────────────────────────────────────────────────────────────

@login_required
def popout_panel(request):
    """Render a panel in a minimal popup window."""
    panel = request.GET.get("panel", "")
    return render(request, "dashboard/_popout.html", {"panel": panel})


# ── Kill Switch ──────────────────────────────────────────────────────────────

@login_required
def kill_switch_api(request):
    """Emergency kill switch endpoint — flatten all positions instantly.

    PIN-gated, like the HQ button that reaches the same function
    (views_admin_hq.flatten_all_positions). This endpoint was login-only
    while its twin required the PIN, so a stolen session could disable
    every bot and flatten the book with no second factor at all.
    """
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    from bot_program.engine.kill_switch import execute_kill_switch
    from django.contrib.auth.hashers import check_password
    import json

    try:
        data = json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    pin = data.get('pin') or request.POST.get('pin', '')
    prof = getattr(request.user, 'trader_profile', None)
    if not (prof and prof.access_pin_hash
            and check_password(pin, prof.access_pin_hash)):
        return JsonResponse(
            {'error': 'PIN required to flatten the book.'}, status=403)

    reason = data.get('reason', 'manual activation')
    results = execute_kill_switch(user=request.user, reason=reason)
    return JsonResponse(results)


# ── Price Alerts ─────────────────────────────────────────────────────────────

@login_required
def price_alerts_api(request):
    """GET list of price alerts or POST to create a new one."""
    from django.http import JsonResponse
    from alerts.models import PriceAlert
    from instruments.models import Instrument
    import json

    if request.method == 'GET':
        alerts = PriceAlert.objects.filter(user=request.user).select_related('instrument')
        data = [
            {
                'id': a.id,
                'instrument': a.instrument.symbol,
                'condition': a.condition,
                'target_price': str(a.target_price),
                'triggered': a.triggered,
                'triggered_at': a.triggered_at.isoformat() if a.triggered_at else None,
                'notify_telegram': a.notify_telegram,
                'notify_email': a.notify_email,
                'note': a.note,
                'created_at': a.created_at.isoformat(),
            }
            for a in alerts
        ]
        return JsonResponse({'alerts': data})

    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        symbol = body.get('instrument', '').strip().upper()
        if not symbol:
            return JsonResponse({'error': 'instrument is required'}, status=400)

        try:
            instrument = Instrument.objects.get(symbol=symbol)
        except Instrument.DoesNotExist:
            return JsonResponse({'error': f'Instrument {symbol} not found'}, status=404)

        condition = body.get('condition', 'above')
        if condition not in ('above', 'below', 'cross'):
            return JsonResponse({'error': 'condition must be above, below, or cross'}, status=400)

        target_price = body.get('target_price')
        if target_price is None:
            return JsonResponse({'error': 'target_price is required'}, status=400)

        alert = PriceAlert.objects.create(
            user=request.user,
            instrument=instrument,
            condition=condition,
            target_price=target_price,
            notify_telegram=bool(body.get('notify_telegram', True)),
            notify_email=bool(body.get('notify_email', False)),
            note=body.get('note', ''),
        )
        return JsonResponse({'id': alert.id, 'status': 'created'}, status=201)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def price_alert_delete(request, pk):
    """DELETE a price alert by pk."""
    from django.http import JsonResponse
    from alerts.models import PriceAlert

    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE required'}, status=405)

    try:
        alert = PriceAlert.objects.get(id=pk, user=request.user)
    except PriceAlert.DoesNotExist:
        return JsonResponse({'error': 'Alert not found'}, status=404)

    alert.delete()
    return JsonResponse({'status': 'deleted', 'id': pk})


# ── Audit Log ────────────────────────────────────────────────────────────────

@login_required
def audit_log_api(request):
    """Return the most recent 100 audit log entries for the current user."""
    from core.audit import AuditLog
    from django.http import JsonResponse

    logs = AuditLog.objects.filter(user=request.user).order_by('-created_at')[:100]
    data = [
        {
            'action': l.action,
            'description': l.description,
            'target_type': l.target_type,
            'created_at': l.created_at.isoformat(),
            'metadata': l.metadata,
        }
        for l in logs
    ]
    return JsonResponse({'logs': data})


# ── Session Management ───────────────────────────────────────────────────────

@login_required
def active_sessions_api(request):
    """View and manage active sessions."""
    from django.contrib.sessions.models import Session
    from django.http import JsonResponse
    from django.utils import timezone
    import json

    if request.method == 'DELETE':
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        session_key = data.get('session_key')
        if session_key and session_key != request.session.session_key:
            Session.objects.filter(session_key=session_key).delete()
            return JsonResponse({'status': 'revoked'})
        return JsonResponse({'error': 'Cannot revoke current session'}, status=400)

    # List active sessions for this user
    sessions = Session.objects.filter(expire_date__gte=timezone.now()).order_by("-expire_date")
    user_sessions = []
    for session in sessions:
        session_data = session.get_decoded()
        if str(session_data.get('_auth_user_id')) == str(request.user.id):
            user_sessions.append({
                'session_key': session.session_key[:8] + '...',
                'full_key': session.session_key,
                'expires': session.expire_date.isoformat(),
                'is_current': session.session_key == request.session.session_key,
            })

    return JsonResponse({'sessions': user_sessions})


# ── AI/Data Enhancement APIs ─────────────────────────────────────────────────

@login_required
def sentiment_index_api(request):
    from django.http import JsonResponse
    from signals.sentiment_index import SentimentIndex

    symbol = request.GET.get('symbol')
    instrument = None
    if symbol:
        from instruments.models import Instrument
        instrument = Instrument.objects.filter(symbol=symbol).first()

    index = SentimentIndex()
    result = index.calculate(instrument=instrument)
    return JsonResponse(result)


@login_required
def agent_calibration_api(request):
    from django.http import JsonResponse
    from ai_agents.calibration import CalibrationTracker

    agent = request.GET.get('agent')
    tracker = CalibrationTracker()

    if agent:
        result = tracker.get_agent_accuracy(agent)
        result['adjustment'] = tracker.suggest_confidence_adjustment(agent)
    else:
        result = tracker.get_all_agents_accuracy()

    return JsonResponse(result, safe=False)


@login_required
def rag_search_api(request):
    from django.http import JsonResponse
    from ai_agents.rag import rag_store

    query = request.GET.get('q', '')
    doc_type = request.GET.get('type')
    top_k = int(request.GET.get('k', 5))

    types = [doc_type] if doc_type else None
    results = rag_store.retrieve(query, top_k=top_k, doc_types=types)
    return JsonResponse({'results': results, 'query': query})


# ── Sector Rotation API ──────────────────────────────────────────────────────

@login_required
def sector_rotation_api(request):
    from django.http import JsonResponse
    from signals.sector_rotation import SectorRotationModel

    lookback = int(request.GET.get('lookback_days', 30))
    model = SectorRotationModel()
    result = model.analyze(lookback_days=lookback)
    return JsonResponse(result)


# ── Earnings Predictor API ───────────────────────────────────────────────────

@login_required
def earnings_predictor_api(request):
    from django.http import JsonResponse
    from signals.earnings_predictor import EarningsPredictor

    symbol = request.GET.get('symbol')
    eps_actual = float(request.GET.get('eps_actual', 0))
    eps_estimate = float(request.GET.get('eps_estimate', 0))
    revenue_actual = request.GET.get('revenue_actual')
    revenue_estimate = request.GET.get('revenue_estimate')

    if not symbol:
        return JsonResponse({'error': 'symbol required'}, status=400)

    predictor = EarningsPredictor()
    result = predictor.predict_reaction(
        symbol, eps_actual, eps_estimate,
        float(revenue_actual) if revenue_actual else None,
        float(revenue_estimate) if revenue_estimate else None,
    )
    return JsonResponse(result)


# ── Trade Journal API ────────────────────────────────────────────────────────

@login_required
def trade_journal_api(request):
    from django.http import JsonResponse
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio

    portfolio = get_or_create_default_portfolio(user=request.user)

    if request.method == 'POST':
        # Generate journal for a specific position
        import json as json_mod
        data = json_mod.loads(request.body)
        position_id = data.get('position_id')
        position = Position.objects.filter(id=position_id, portfolio=portfolio).first()
        if not position or not position.closed_at:
            return JsonResponse({'error': 'closed position not found'}, status=404)

        from ai_agents.trade_journal import generate_journal_entry
        result = generate_journal_entry(position)
        return JsonResponse(result or {'error': 'generation failed'})

    # GET: return recent closed positions for journaling
    closed = Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=False
    ).select_related('instrument', 'strategy').order_by('-closed_at')[:20]

    positions = [{
        'id': p.id,
        'symbol': p.instrument.symbol,
        'direction': p.direction,
        'pnl_pct': p.unrealized_pnl_pct,
        'opened_at': p.opened_at.isoformat(),
        'closed_at': p.closed_at.isoformat(),
    } for p in closed]

    return JsonResponse({'positions': positions})


# ── Webhook API ──────────────────────────────────────────────────────────────

@login_required
def webhooks_api(request):
    """GET list of webhooks or POST to create a new one."""
    from django.http import JsonResponse
    from alerts.models import WebhookEndpoint
    import json

    if request.method == 'GET':
        hooks = WebhookEndpoint.objects.filter(user=request.user)
        data = [
            {
                'id': h.id,
                'name': h.name,
                'url': h.url,
                'is_active': h.is_active,
                'on_signal': h.on_signal,
                'on_trade': h.on_trade,
                'on_alert': h.on_alert,
                'on_portfolio': h.on_portfolio,
                'on_news': h.on_news,
                'total_sent': h.total_sent,
                'last_sent_at': h.last_sent_at.isoformat() if h.last_sent_at else None,
                'consecutive_failures': h.consecutive_failures,
                'last_error': h.last_error,
                'created_at': h.created_at.isoformat(),
            }
            for h in hooks
        ]
        return JsonResponse({'webhooks': data})

    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        name = body.get('name', '').strip()
        url = body.get('url', '').strip()
        if not name:
            return JsonResponse({'error': 'name is required'}, status=400)
        if not url:
            return JsonResponse({'error': 'url is required'}, status=400)

        hook = WebhookEndpoint.objects.create(
            user=request.user,
            name=name,
            url=url,
            secret=body.get('secret', ''),
            is_active=bool(body.get('is_active', True)),
            on_signal=bool(body.get('on_signal', True)),
            on_trade=bool(body.get('on_trade', True)),
            on_alert=bool(body.get('on_alert', True)),
            on_portfolio=bool(body.get('on_portfolio', False)),
            on_news=bool(body.get('on_news', False)),
        )
        return JsonResponse({'id': hook.id, 'status': 'created'}, status=201)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def webhook_delete(request, pk):
    """DELETE a webhook endpoint by pk."""
    from django.http import JsonResponse
    from alerts.models import WebhookEndpoint

    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE required'}, status=405)

    try:
        hook = WebhookEndpoint.objects.get(id=pk, user=request.user)
    except WebhookEndpoint.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)

    hook.delete()
    return JsonResponse({'status': 'deleted', 'id': pk})


@login_required
def webhook_test(request, pk):
    """POST to send a test event to a webhook endpoint."""
    from django.http import JsonResponse
    from alerts.models import WebhookEndpoint
    from alerts.webhook_manager import _deliver_webhook

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        hook = WebhookEndpoint.objects.get(id=pk, user=request.user)
    except WebhookEndpoint.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)

    try:
        _deliver_webhook(hook, 'test', {
            'message': 'This is a test event from Sauron Vision',
            'user': request.user.username,
        })
        return JsonResponse({'status': 'sent'})
    except Exception as e:
        return JsonResponse({'status': 'failed', 'error': str(e)}, status=500)


# ── On-Chain API ─────────────────────────────────────────────────────────────

@login_required
def onchain_api(request):
    """GET on-chain analytics data (whale tracking, exchange flows, DeFi TVL)."""
    from django.http import JsonResponse
    from market_data.adapters.onchain_adapter import OnChainAdapter

    adapter = OnChainAdapter()
    action = request.GET.get('action', 'flows')
    asset = request.GET.get('asset', 'BTC').upper()

    if action == 'flows':
        data = adapter.get_exchange_flows(asset=asset)
    elif action == 'whales':
        min_usd = int(request.GET.get('min_usd', 1000000))
        data = adapter.get_whale_transactions(asset=asset, min_value_usd=min_usd)
    elif action == 'network':
        data = adapter.get_network_metrics(asset=asset)
    elif action == 'defi':
        protocol = request.GET.get('protocol') or None
        data = adapter.get_defi_tvl(protocol=protocol)
    else:
        return JsonResponse({'error': f'Unknown action: {action}. Use flows, whales, network, or defi'}, status=400)

    return JsonResponse({'action': action, 'asset': asset, 'data': data})


# ── Natural Language Trade API ───────────────────────────────────────────────

@login_required
def nl_trade_api(request):
    """Natural language trade entry."""
    from django.http import JsonResponse
    import json as json_mod

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    data = json_mod.loads(request.body)
    command = data.get('command', '')

    if not command:
        return JsonResponse({'error': 'command required'}, status=400)

    from bot_program.nl_trader import NLTradeParser
    parser = NLTradeParser()
    parsed = parser.parse(command)

    # If just parsing (preview mode)
    if data.get('preview', False):
        return JsonResponse({'parsed': parsed})

    # Execute
    result = parser.execute(parsed, request.user)

    # Audit log
    try:
        from core.audit import AuditLog
        AuditLog.log(
            user=request.user,
            action='trade_open' if result.get('status') == 'executed' else 'config_change',
            description=f"NL trade: {command} → {result.get('status')}",
            metadata={'command': command, 'parsed': parsed, 'result': result},
        )
    except Exception:
        pass

    return JsonResponse(result)


# ── Compliance API ────────────────────────────────────────────────────────────

@login_required
def compliance_api(request):
    """Check compliance or list restrictions."""
    from django.http import JsonResponse
    from core.compliance import ComplianceChecker

    checker = ComplianceChecker()

    if request.method == 'POST':
        import json as json_mod
        data = json_mod.loads(request.body)
        allowed, reasons = checker.check_trade(
            request.user,
            data.get('symbol', ''),
            data.get('action', ''),
            quantity=data.get('quantity'),
            value=data.get('value'),
        )
        return JsonResponse({'allowed': allowed, 'violations': reasons})

    # GET: list restrictions
    restrictions = checker.get_active_restrictions(user=request.user)
    return JsonResponse({'restrictions': restrictions})


# ── Market Commentary API ─────────────────────────────────────────────────────

@login_required
def market_commentary_api(request):
    """Return latest daily market commentary from notifications."""
    from django.http import JsonResponse
    from alerts.models import Notification

    latest = (
        Notification.objects.filter(title__icontains='Market Commentary')
        .order_by('-created_at')
        .first()
    )

    if not latest:
        return JsonResponse({'commentary': None, 'message': 'No commentary available yet'})

    return JsonResponse({
        'commentary': latest.body,
        'title': latest.title,
        'created_at': latest.created_at.isoformat(),
    })