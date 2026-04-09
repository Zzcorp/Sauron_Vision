"""Metrics endpoints for the enriched dashboard pages.

Each view returns a small HTML partial (cards + JSON for charts) that the
parent page polls via HTMX. Charts are rendered client-side by Chart.js.
"""
import json
from collections import Counter
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone


# ── Signals page metrics ────────────────────────────────────────────────
@login_required
def signals_metrics(request):
    """Active signal counts, hit-rate per setup, distribution by direction."""
    ctx = {"setups": [], "totals": {}, "chart_data": "{}"}
    try:
        from signals.models_smc import SmcSignal
        from signals.performance import setup_performance_summary

        active = SmcSignal.objects.filter(status__in=["ACTIVE", "TRIGGERED"])
        ctx["totals"] = {
            "active": active.count(),
            "long": active.filter(direction="LONG").count(),
            "short": active.filter(direction="SHORT").count(),
            "avg_conviction": round(
                sum(s.conviction or 0 for s in active) / max(active.count(), 1), 1
            ),
        }
        perf = setup_performance_summary(days=30)
        ctx["setups"] = [
            {
                "name": k,
                "hit_rate": v["hit_rate"],
                "expectancy": v["expectancy_r"],
                "n_closed": v["n_closed"],
                "is_empirical": v["is_empirical"],
            }
            for k, v in perf.items()
        ]

        # Chart data: signal counts per day for the last 14 days
        since = timezone.now() - timedelta(days=14)
        recent = SmcSignal.objects.filter(created_at__gte=since)
        per_day = {}
        for s in recent:
            day = s.created_at.date().isoformat()
            per_day.setdefault(day, {"long": 0, "short": 0})
            per_day[day]["long" if s.direction == "LONG" else "short"] += 1

        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "long": [per_day[d]["long"] for d in days_sorted],
            "short": [per_day[d]["short"] for d in days_sorted],
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_signals_metrics.html", ctx)


# ── Strategies page metrics ─────────────────────────────────────────────
@login_required
def strategies_metrics(request):
    """Strategy outcomes, R-distribution, status mix."""
    ctx = {"by_status": [], "chart_data": "{}", "totals": {}}
    try:
        from strategies.models import Strategy
        all_strats = Strategy.objects.all()
        status_counts = Counter(s.status for s in all_strats)
        ctx["by_status"] = [{"status": k, "count": v} for k, v in status_counts.items()]
        ctx["totals"] = {
            "total": all_strats.count(),
            "active": status_counts.get("active", 0),
            "proposed": status_counts.get("proposed", 0),
            "completed": status_counts.get("completed", 0),
        }
        ctx["chart_data"] = json.dumps({
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_strategies_metrics.html", ctx)


# ── News & sentiment metrics ────────────────────────────────────────────
@login_required
def news_metrics(request):
    """News volume per day, sentiment trend."""
    ctx = {"totals": {}, "chart_data": "{}"}
    try:
        from scraping.models import NewsItem
        since = timezone.now() - timedelta(days=14)
        items = NewsItem.objects.filter(published_at__gte=since) if hasattr(NewsItem, "published_at") else []
        ctx["totals"]["count_14d"] = len(list(items)) if items else 0

        per_day = {}
        for n in items:
            day = (n.published_at or timezone.now()).date().isoformat()
            per_day[day] = per_day.get(day, 0) + 1
        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "values": [per_day[d] for d in days_sorted],
        })
    except Exception as e:
        ctx["error"] = str(e)
        ctx["totals"]["count_14d"] = 0
    return render(request, "dashboard/_news_metrics.html", ctx)


# ── Backtest metrics ────────────────────────────────────────────────────
@login_required
def backtest_metrics(request):
    """Latest backtest summary + equity curve."""
    ctx = {"runs": [], "chart_data": "{}"}
    try:
        from backtester.models_v2 import BacktestRunV2
        recent = BacktestRunV2.objects.all()[:10]
        ctx["runs"] = list(recent)
        if recent:
            latest = recent[0]
            curve = latest.equity_curve or []
            ctx["chart_data"] = json.dumps({
                "labels": [str(p.get("ts", i)) for i, p in enumerate(curve)],
                "equity": [p.get("equity", 0) for p in curve],
                "name": latest.name,
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_backtest_metrics.html", ctx)


# ── Portfolio metrics ───────────────────────────────────────────────────
@login_required
def portfolio_metrics(request):
    """Portfolio composition + exposure breakdown."""
    ctx = {"exposure": {}, "chart_data": "{}"}
    try:
        from portfolio.models import Portfolio
        from strategies.portfolio_analyzer import analyze_exposure

        portfolio = Portfolio.objects.filter(user=request.user).first()
        if portfolio:
            exposure = analyze_exposure(portfolio)
            ctx["exposure"] = exposure
            asset_break = exposure.get("by_asset_class", {})
            ctx["chart_data"] = json.dumps({
                "labels": list(asset_break.keys()),
                "values": [round(v * 100, 2) for v in asset_break.values()],
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_portfolio_metrics.html", ctx)


# ── Positions metrics ───────────────────────────────────────────────────
@login_required
def positions_metrics(request):
    """Open positions table with PnL distribution."""
    ctx = {"positions": [], "chart_data": "{}"}
    try:
        from portfolio.models import Position, Portfolio
        portfolio = Portfolio.objects.filter(user=request.user).first()
        if portfolio:
            positions = Position.objects.filter(
                portfolio=portfolio, is_open=True
            ).select_related("instrument")[:50]
            ctx["positions"] = list(positions)
            symbols = []
            pnls = []
            for p in positions:
                symbols.append(getattr(p.instrument, "symbol", "?"))
                pnls.append(float(getattr(p, "unrealized_pnl", 0) or 0))
            ctx["chart_data"] = json.dumps({
                "labels": symbols,
                "values": pnls,
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_positions_metrics.html", ctx)
