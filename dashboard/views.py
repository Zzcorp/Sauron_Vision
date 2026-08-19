"""Sauron Vision — Dashboard Views (enriched)."""
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
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position, PortfolioSnapshot
    from core.market_calendar import is_forex_open, is_us_market_open, is_eu_market_open, is_weekend

    portfolio = get_or_create_default_portfolio()
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Portfolio metrics
    open_positions = Position.objects.filter(portfolio=portfolio, closed_at__isnull=True)
    total_unrealized = sum(float(p.unrealized_pnl) for p in open_positions)
    cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)

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
    portfolio_delta = round(
        sum(float(p.quantity) * float(p.current_price) for p in open_positions)
        / max(float(portfolio.current_value), 1), 2
    )
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
        "daily_pnl_pct": "+{:.2f}".format(latest_snapshot.daily_pnl_pct) if latest_snapshot else "+0.00",
        "cash_pct": cash_pct,
        "total_unrealized_pnl": "{:.2f}".format(total_unrealized),
        "open_positions_count": open_positions.count(),
        "total_exposure_pct": 100 - cash_pct,
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

    items = []
    for inst in instruments:
        q = quotes_map.get(inst.id)
        items.append({
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
             "n_live_venue": 0,
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
    ladder_n = ladder_hits = 0
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
        by_stage[ctrl.promotion_stage].append({
            "rule": name,
            "stage": ctrl.promotion_stage,
            "stage_display": ctrl.get_promotion_stage_display(),
            "venue": _STAGE_VENUE.get(ctrl.promotion_stage, ""),
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
            sent_trend.append({
                "hour": h,
                "avg": round(hourly_sum[h] / hourly_n[h], 3),
                "n": hourly_n[h],
            })
        else:
            sent_trend.append({"hour": h, "avg": 0, "n": 0})

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
        "urgency_mix": urgency_mix,
        "top_tickers": top_tickers,
        "top_sources": top_sources,
    })


@login_required
def portfolio_overview(request):
    """Phase 63 — enriched portfolio dashboard.

    Adds: equity sparkline · allocation donut · win/loss/profit-factor stats ·
    Sharpe 30d · top contributors/detractors. Reuses the same rendering
    patterns as the Operations Center PORTFOLIO tab.
    """
    from collections import defaultdict
    from datetime import timedelta
    from django.utils import timezone as _tz
    from portfolio.services import (get_or_create_default_portfolio,
                                    unified_closed_positions,
                                    unified_open_positions)
    from portfolio.models import PortfolioSnapshot
    # The SHARED "Main" book, deliberately: it is the only Position book
    # the background pipeline maintains — snapshots, mark-to-market, the
    # eToro sync, the REST API and the Telegram digest all operate on it.
    # A per-user book here rendered empty equity curves and never-marked
    # rows, and silently hid all pre-existing history.
    portfolio = get_or_create_default_portfolio()

    # BOTH books: legacy Position rows plus the AssetBotTrades that every
    # interactive path (bots, TAKE TRADE, LONG/SHORT) actually writes —
    # the taken trade used to be invisible on this page by construction.
    open_positions = unified_open_positions(request.user, portfolio)
    closed_positions = unified_closed_positions(request.user, portfolio)

    # Win/loss / profit factor / unrealized stats.
    n_closed = len(closed_positions)
    winning = [p for p in closed_positions if float(p.unrealized_pnl or 0) > 0]
    losing = [p for p in closed_positions if float(p.unrealized_pnl or 0) <= 0]
    win_rate = round(len(winning) / n_closed * 100, 1) if n_closed else 0
    avg_win = (sum(float(p.unrealized_pnl) for p in winning) / len(winning)) if winning else 0
    avg_loss = (sum(float(p.unrealized_pnl) for p in losing) / len(losing)) if losing else 0
    profit_factor = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0
    total_unrealized = sum(float(p.unrealized_pnl or 0) for p in open_positions)

    latest_snapshot = (PortfolioSnapshot.objects.filter(portfolio=portfolio)
                        .order_by("-date").first())
    max_drawdown = float(latest_snapshot.max_drawdown) if latest_snapshot else 0.0

    # Equity curve sparkline — last 30 days.
    cutoff_30d = _tz.now().date() - timedelta(days=30)
    equity_rows = list(
        PortfolioSnapshot.objects.filter(
            portfolio=portfolio, date__gte=cutoff_30d)
        .order_by("date")
        .values_list("date", "total_value")
    )
    equity_points = [float(v) for _, v in equity_rows]

    # 30d Sharpe / Sortino approximation.
    sharpe_30d = sortino_30d = None
    rets = [float(s.daily_pnl_pct or 0) for s in
            PortfolioSnapshot.objects.filter(
                portfolio=portfolio, date__gte=cutoff_30d)]
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

    # Allocation donut — by asset class from current open positions + cash.
    alloc_by_class = defaultdict(float)
    for p in open_positions:
        ac = getattr(p.instrument, "asset_class", "") or "other"
        alloc_by_class[ac] += abs(float(p.quantity or 0) * float(p.current_price or 0))
    alloc_by_class["cash"] = float(portfolio.cash_available or 0)
    alloc_total = sum(alloc_by_class.values()) or 1.0
    allocation = sorted(
        ({"asset_class": k, "value": v, "pct": round(v / alloc_total * 100, 1)}
         for k, v in alloc_by_class.items() if v > 0),
        key=lambda r: r["value"], reverse=True,
    )

    # Top 3 contributors / detractors among CLOSED positions.
    closed_sorted = sorted(closed_positions,
                            key=lambda p: float(p.unrealized_pnl or 0),
                            reverse=True)
    top_contributors = closed_sorted[:3]
    top_detractors = list(reversed(closed_sorted[-3:])) if len(closed_sorted) >= 3 else []

    return render(request, "dashboard/portfolio_overview.html", {
        "page_id": "portfolio", "portfolio": portfolio,
        "snapshots": PortfolioSnapshot.objects.filter(portfolio=portfolio).order_by("-date")[:30],
        "open_positions_count": len(open_positions),
        "open_positions": list(open_positions[:8]),
        "total_unrealized": total_unrealized,
        "n_closed": n_closed,
        "n_winning": len(winning),
        "n_losing": len(losing),
        "win_rate": win_rate,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_30d": sharpe_30d,
        "sortino_30d": sortino_30d,
        "equity_points": equity_points,
        "equity_min": min(equity_points) if equity_points else 0,
        "equity_max": max(equity_points) if equity_points else 0,
        "allocation": allocation,
        "top_contributors": top_contributors,
        "top_detractors": top_detractors,
    })


@login_required
def positions_list(request):
    """Phase 63 — enriched positions dashboard.

    Adds: open exposure totals, direction donut, asset-class breakdown,
    monthly P&L bars, profit factor, avg W/L, current open P&L sum.
    """
    from collections import defaultdict
    from portfolio.services import (unified_closed_positions,
                                    unified_open_positions)
    tab = request.GET.get("tab", "open")
    # BOTH books: the maintained shared Position book plus the user's
    # AssetBotTrades — a trade taken from a signal used to show in fills,
    # the Op Center and forensics but never here.
    open_positions = unified_open_positions(request.user)
    closed_positions = unified_closed_positions(request.user)

    total_closed = len(closed_positions)
    winning = [p for p in closed_positions if float(p.unrealized_pnl or 0) > 0]
    losing = [p for p in closed_positions if float(p.unrealized_pnl or 0) < 0]
    n_winning = len(winning)
    n_losing = len(losing)
    win_rate = round(n_winning / total_closed * 100, 1) if total_closed > 0 else 0
    total_realized = sum(float(p.unrealized_pnl or 0) for p in closed_positions)
    best_trade = max(closed_positions, key=lambda p: float(p.unrealized_pnl or 0)) if total_closed else None
    worst_trade = min(closed_positions, key=lambda p: float(p.unrealized_pnl or 0)) if total_closed else None

    # Profit factor + avg win/loss
    gross_win = sum(float(p.unrealized_pnl or 0) for p in winning)
    gross_loss = abs(sum(float(p.unrealized_pnl or 0) for p in losing))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (0 if gross_win == 0 else 99.99)
    avg_win = round(gross_win / max(n_winning, 1), 2)
    avg_loss = round(-gross_loss / max(n_losing, 1), 2)

    # Open P&L + exposure
    open_unrealized = sum(float(p.unrealized_pnl or 0) for p in open_positions)
    open_exposure = sum(
        abs(float(p.quantity or 0) * float(p.current_price or 0))
        for p in open_positions)

    # Direction donut over open positions
    n_long = sum(1 for p in open_positions if p.direction == "long")
    n_short = sum(1 for p in open_positions if p.direction == "short")
    n_open_total = n_long + n_short
    direction_donut = []
    if n_long:
        direction_donut.append({"key": "long", "n": n_long,
                                  "pct": round(n_long / max(n_open_total, 1) * 100, 1)})
    if n_short:
        direction_donut.append({"key": "short", "n": n_short,
                                  "pct": round(n_short / max(n_open_total, 1) * 100, 1)})

    # Asset-class breakdown over open positions
    by_class: dict = defaultdict(
        lambda: {"n": 0, "exposure": 0.0, "unrealized": 0.0})
    for p in open_positions:
        cls = (p.instrument.asset_class
               if p.instrument else None) or "other"
        d = by_class[cls]
        d["n"] += 1
        d["exposure"] += abs(float(p.quantity or 0) * float(p.current_price or 0))
        d["unrealized"] += float(p.unrealized_pnl or 0)
    asset_breakdown = sorted(
        [{"asset_class": k, **v,
          "exposure_pct": round(v["exposure"] / max(open_exposure, 1) * 100, 1)}
         for k, v in by_class.items()],
        key=lambda r: -r["exposure"]
    )

    # Monthly P&L (last 12 months) — bucket closed by month
    from datetime import timedelta as _td
    now = timezone.now()
    monthly_pnl: dict = defaultdict(float)
    for p in closed_positions:
        if p.closed_at:
            key = p.closed_at.strftime("%Y-%m")
            monthly_pnl[key] += float(p.unrealized_pnl or 0)
    monthly_rows = []
    for i in range(11, -1, -1):
        month = (now - _td(days=i * 30)).replace(day=1)
        key = month.strftime("%Y-%m")
        monthly_rows.append({
            "month": month.strftime("%b"),
            "pnl": round(monthly_pnl.get(key, 0), 2),
        })
    monthly_max = max((abs(r["pnl"]) for r in monthly_rows), default=0)

    return render(request, "dashboard/positions_list.html", {
        "page_id": "positions",
        "tab": tab,
        "positions": open_positions,
        "closed_positions": closed_positions,
        "total_closed": total_closed,
        "n_winning": n_winning,
        "n_losing": n_losing,
        "win_rate": win_rate,
        "total_realized": "{:.2f}".format(total_realized),
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "open_unrealized": round(open_unrealized, 2),
        "open_exposure": round(open_exposure, 2),
        "direction_donut": direction_donut,
        "asset_breakdown": asset_breakdown,
        "monthly_rows": monthly_rows,
        "monthly_max": monthly_max,
    })


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
    cost_trend = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        cost_trend.append({
            "date": d.strftime("%m-%d"),
            "cost": round(cost_per_day.get(d, 0), 3),
            "n": n_per_day.get(d, 0),
        })
    max_day_cost = max((r["cost"] for r in cost_trend), default=0)

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
    cost_trend = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        cost_trend.append({
            "date": d.strftime("%m-%d"),
            "cost": round(cost_per_day.get(d, 0), 3),
            "n": n_per_day.get(d, 0),
        })
    max_day_cost = max((r["cost"] for r in cost_trend), default=0)

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


@login_required
def setup(request):
    """Account setup: capital, risk, eToro, manual positions."""
    import os
    from django.contrib import messages
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    from instruments.models import Instrument
    from django.utils import timezone

    # The shared "Main" book, matching the eToro sync this same page
    # triggers and the pipeline that marks/snapshots positions — the
    # positions pages read this book (plus the user's bot trades).
    portfolio = get_or_create_default_portfolio()

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
            portfolio.max_total_exposure_pct = float(request.POST.get("max_exposure", 100))
            portfolio.max_single_position_pct = float(request.POST.get("max_position", 10))
            portfolio.max_daily_loss_pct = float(request.POST.get("max_daily_loss", 3))
            portfolio.max_correlation_threshold = float(request.POST.get("max_correlation", 0.7))
            portfolio.save()
            messages.success(request, "Risk limits updated successfully.")

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

    return render(request, "dashboard/setup.html", {
        "page_id": "setup",
        "portfolio": portfolio,
        "api_keys": api_keys,
        "etoro_connected": bool(etoro_key),
        "etoro_key_masked": etoro_masked,
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
    from bot_program.models import BinanceAccount, OANDAAccount, AlpacaAccount
    broker_rows = []
    for u in User.objects.order_by("username"):
        binance = getattr(u, "binance_account", None)
        oanda = getattr(u, "oanda_account", None)
        alpaca = getattr(u, "alpaca_account", None)
        if not (binance or oanda or alpaca):
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

    return render(request, "dashboard/instrument_detail.html", {
        "page_id": "instruments",
        "instrument": instrument,
        "quote": quote,
        "technicals": technicals,
        "signals": signals,
        "news": news,
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
    """POST — execute the trade previewed above, optionally closing the
    listed manual positions first to free capital. Paper venue only in this
    wave; the live path adds the PIN and the pending-close machinery."""
    import json as _json
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
                                           body["close_ids"]))


def _parse_trade_body(request):
    """Parse an execute body into {"close_ids": [...], "side": ...}.

    Strict on shape: a non-object body 500'd (AttributeError on .get), and
    a string close_ids like "12" iterated per character into [1, 2] —
    closing trades nobody named.
    """
    import json as _json
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
    return {"close_ids": close_ids,
            "side": str(body.get("side", "")).upper()}, None


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
def panel_counts_json(request):
    """The bottom headband's live numbers, as JSON. Fetched (debounced) by
    the /ws/eye/ listener on fill events, so the POSITIONS and BOT cells
    move the moment a trade opens or closes — they used to be render-time
    constants that froze until the next full reload."""
    from django.http import JsonResponse
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    from portfolio.services import get_or_create_default_portfolio

    bot_open = AssetBotTrade.objects.filter(
        config__user=request.user,
        status__in=("OPEN", "CLOSE_PENDING")).count()
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
        "positions": pos_open + bot_open,
        "bot_open": bot_open,
        "watchlist": watchlist,
        "notifications": unread,
    })


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
    """POST {side, close_ids} — execute the signal-less trade previewed
    above. Same paper venue, same funding-close chain."""
    from django.http import HttpResponseNotAllowed, JsonResponse
    from bot_program.manual_trade import execute_asset_trade
    from instruments.models import Instrument

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    inst = get_object_or_404(Instrument, symbol=symbol, is_active=True)
    body, err = _parse_trade_body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    return JsonResponse(execute_asset_trade(request.user, inst,
                                            body["side"], body["close_ids"]))


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