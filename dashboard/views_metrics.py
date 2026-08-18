"""Metrics endpoints — v2 with sentiment trend, R-distribution, P&L bars."""
import json
from collections import Counter
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone


# ── Signals ─────────────────────────────────────────────────────────────
@login_required
def signals_metrics(request):
    ctx = {"setups": [], "totals": {}, "chart_data": "{}",
           "setup_dist": "{}", "r_hist": "{}"}
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
            {"name": k, "hit_rate": v["hit_rate"], "expectancy": v["expectancy_r"],
             "n_closed": v["n_closed"], "is_empirical": v["is_empirical"]}
            for k, v in perf.items()
        ]
        # Dict order here is DB arrival order — sort so the busiest setups lead.
        ctx["setups"].sort(key=lambda r: -(r["n_closed"] or 0))

        # Chart 1: signals per day stacked long/short
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

        # Chart 2: setup distribution donut (active signals)
        # most_common() gives one aligned (label, value) sequence, largest first.
        setup_counts = Counter(s.setup for s in active)
        setup_pairs = setup_counts.most_common()
        ctx["setup_dist"] = json.dumps({
            "labels": [k for k, _ in setup_pairs],
            "values": [v for _, v in setup_pairs],
        })

        # Chart 3: R-multiple histogram from closed signals (90d)
        closed = SmcSignal.objects.filter(
            closed_at__gte=timezone.now() - timedelta(days=90),
            realized_r__isnull=False,
        )
        bins = [-3, -2, -1, 0, 1, 2, 3, 5]
        hist = [0] * (len(bins) - 1)
        for s in closed:
            r = float(s.realized_r)
            for i in range(len(bins) - 1):
                if bins[i] <= r < bins[i + 1]:
                    hist[i] += 1
                    break
        ctx["r_hist"] = json.dumps({
            "labels": [f"{bins[i]} to {bins[i+1]}R" for i in range(len(bins) - 1)],
            "values": hist,
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_signals_metrics.html", ctx)


# ── Strategies ──────────────────────────────────────────────────────────
@login_required
def strategies_metrics(request):
    ctx = {"by_status": [], "chart_data": "{}", "totals": {}, "pnl_data": "{}"}
    try:
        from strategies.models import Strategy
        all_strats = Strategy.objects.all()
        status_counts = Counter(s.status for s in all_strats)
        # Fixed lifecycle order — Counter order is arrival order, which shuffles
        # the table and chart between reloads. Zero-count statuses are skipped.
        status_order = ["active", "approved", "proposed", "completed", "paused", "rejected"]
        by_status = [
            {"status": k, "count": status_counts.get(k, 0)}
            for k in status_order if status_counts.get(k, 0)
        ]
        ctx["by_status"] = by_status
        ctx["totals"] = {
            "total": all_strats.count(),
            "active": status_counts.get("active", 0),
            "proposed": status_counts.get("proposed", 0),
            "completed": status_counts.get("completed", 0),
        }
        ctx["chart_data"] = json.dumps({
            "labels": [r["status"] for r in by_status],
            "values": [r["count"] for r in by_status],
        })
        # Per-strategy P&L bar (uses any 'realized_pnl' or 'pnl' field if present)
        labels = []
        values = []
        for s in all_strats[:20]:
            pnl = getattr(s, "realized_pnl", None) or getattr(s, "pnl", None) or 0
            try:
                pnl = float(pnl)
            except (ValueError, TypeError):
                pnl = 0
            if pnl != 0:
                labels.append((s.name or f"#{s.id}")[:24])
                values.append(round(pnl, 2))
        ctx["pnl_data"] = json.dumps({"labels": labels, "values": values})
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_strategies_metrics.html", ctx)


# ── News & sentiment ────────────────────────────────────────────────────
@login_required
def news_metrics(request):
    ctx = {"totals": {}, "chart_data": "{}", "sentiment_data": "{}",
           "current_sentiment": None}
    try:
        from scraping.models import NewsItem
        since = timezone.now() - timedelta(days=14)
        # NewsItem may not have published_at; tolerate both
        ts_field = None
        for f in ("published_at", "created_at", "scraped_at", "timestamp"):
            if hasattr(NewsItem, f):
                ts_field = f
                break
        if ts_field is None:
            ctx["totals"]["count_14d"] = 0
            return render(request, "dashboard/_news_metrics.html", ctx)

        items = list(NewsItem.objects.filter(**{f"{ts_field}__gte": since}).order_by(ts_field))
        ctx["totals"]["count_14d"] = len(items)

        per_day = {}
        sentiment_per_day = {}
        for n in items:
            ts = getattr(n, ts_field) or timezone.now()
            day = ts.date().isoformat()
            per_day[day] = per_day.get(day, 0) + 1
            score = getattr(n, "ai_sentiment_score", None)
            if score is not None:
                try:
                    score_f = float(score)
                except (ValueError, TypeError):
                    continue
                sentiment_per_day.setdefault(day, []).append(score_f)

        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "values": [per_day[d] for d in days_sorted],
        })

        # Sentiment trend: average per day, only days with data
        sent_days = [d for d in days_sorted if d in sentiment_per_day]
        sent_values = [
            round(sum(sentiment_per_day[d]) / len(sentiment_per_day[d]), 3)
            for d in sent_days
        ]
        ctx["sentiment_data"] = json.dumps({
            "labels": sent_days, "values": sent_values,
        })
        if sent_values:
            current = sent_values[-1]
            ctx["current_sentiment"] = current
            ctx["totals"]["sentiment_label"] = (
                "BULLISH" if current > 0.2
                else "BEARISH" if current < -0.2
                else "NEUTRAL"
            )
    except Exception as e:
        ctx["error"] = str(e)
        ctx["totals"]["count_14d"] = 0
    return render(request, "dashboard/_news_metrics.html", ctx)


# ── Backtest ────────────────────────────────────────────────────────────
@login_required
def backtest_metrics(request):
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


# ── Portfolio ───────────────────────────────────────────────────────────
@login_required
def portfolio_metrics(request):
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


# ── Positions ───────────────────────────────────────────────────────────
@login_required
def positions_metrics(request):
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
            ctx["chart_data"] = json.dumps({"labels": symbols, "values": pnls})
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_positions_metrics.html", ctx)
