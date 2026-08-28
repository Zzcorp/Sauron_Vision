"""Per-bot equity curve and R-distribution.

Every closed trade already carries `pnl` and `realized_r`; nothing plotted
them, so judging a bot meant reading a table of numbers. An equity curve
answers "is this working" in one glance, and the R-distribution answers
the more useful question — whether the edge comes from many small wins or
one lucky outlier.

Rendered as inline SVG: no chart library, no CDN (the CSP on this app
blocks external scripts anyway), and it works with JavaScript disabled.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

# Buckets for the R histogram, in R multiples.
R_BUCKETS = [
    (float("-inf"), -2.0, "≤ -2R"),
    (-2.0, -1.0, "-2 to -1R"),
    (-1.0, -0.5, "-1 to -0.5R"),
    (-0.5, 0.0, "-0.5 to 0R"),
    (0.0, 0.5, "0 to 0.5R"),
    (0.5, 1.0, "0.5 to 1R"),
    (1.0, 2.0, "1 to 2R"),
    (2.0, float("inf"), "≥ 2R"),
]


def _equity_series(trades, starting_capital: float) -> list:
    """Cumulative equity after each closed trade.

    A trade whose exit could not be priced carries pnl NULL, and it is
    skipped rather than stepped by zero: a flat step draws a line where the
    truth is a gap, and — because this is a CUMULATIVE series — every point
    after it inherits the error. The curve is then short by that trade
    rather than wrong from it onward, and `unmeasured_count` lets the page
    say so.
    """
    equity = starting_capital
    points = [{"i": 0, "equity": round(equity, 2), "at": None}]
    for i, t in enumerate(trades, start=1):
        if t.pnl is None:
            continue
        equity += float(t.pnl)
        points.append({"i": i, "equity": round(equity, 2), "at": t.closed_at})
    return points


def unmeasured_count(trades) -> int:
    """How many closed trades have no price behind their P&L."""
    return sum(1 for t in trades if t.pnl is None)


def _sparkline_path(points, width=720, height=200, pad=8) -> dict:
    """SVG path for the equity curve plus its drawdown shading bounds."""
    if len(points) < 2:
        return {"path": "", "min": 0, "max": 0, "last": 0, "first": 0}
    values = [p["equity"] for p in points]
    lo, hi = min(values), max(values)
    # A flat curve has NO span. Substituting 1.0 mapped every point to
    # (v - lo)/1 = 0, i.e. the floor of the box — so an account that never
    # moved was drawn sitting at its low. A flat series is drawn through the
    # middle, which is the only honest place for a line with no range.
    span = hi - lo
    flat = span <= 0
    step = (width - 2 * pad) / (len(values) - 1)

    coords = []
    for i, v in enumerate(values):
        x = pad + i * step
        frac = 0.5 if flat else (v - lo) / span
        y = pad + (height - 2 * pad) * (1 - frac)
        coords.append(f"{x:.1f},{y:.1f}")
    return {"path": "M " + " L ".join(coords),
            "min": round(lo, 2), "max": round(hi, 2),
            "flat": flat,
            "first": round(values[0], 2), "last": round(values[-1], 2),
            "up": values[-1] >= values[0]}


def _r_histogram(trades) -> list:
    rs = [float(t.realized_r) for t in trades if t.realized_r is not None]
    if not rs:
        return []
    counts = []
    for low, high, label in R_BUCKETS:
        n = sum(1 for r in rs if low < r <= high or (low == float("-inf") and r <= high))
        counts.append({"label": label, "n": n, "win": high > 0})
    peak = max((c["n"] for c in counts), default=0) or 1
    for c in counts:
        c["pct"] = round(c["n"] / peak * 100, 1)
    return counts


def _stats(trades, points) -> dict:
    rs = [float(t.realized_r) for t in trades if t.realized_r is not None]
    pnls = [float(t.pnl) for t in trades if t.pnl is not None]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    # Max drawdown from the running peak of the equity curve.
    peak, max_dd = None, 0.0
    for p in points:
        peak = p["equity"] if peak is None else max(peak, p["equity"])
        if peak > 0:
            max_dd = max(max_dd, (peak - p["equity"]) / peak * 100)

    gross_win = sum(r for r in wins)
    gross_loss = abs(sum(r for r in losses))
    return {
        "n": len(trades),
        "graded": len(rs),
        "win_rate": round(len(wins) / len(rs), 3) if rs else None,
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(rs) / len(rs), 3) if rs else None,
        "profit_factor": (round(gross_win / gross_loss, 2)
                          if gross_loss > 0 else None),
        "max_drawdown_pct": round(max_dd, 2),
        "best_r": round(max(rs), 2) if rs else None,
        "worst_r": round(min(rs), 2) if rs else None,
        # If the best trade carries most of the edge, the "edge" is one
        # lucky outlier rather than a repeatable process.
        "top_trade_share": (round(max(rs) / sum(rs), 3)
                            if rs and sum(rs) > 0 else None),
    }


@login_required
def bot_charts(request):
    from bot_program.models import AssetBotConfig, AssetBotTrade

    days = int(request.GET.get("days", 180) or 180)
    since = timezone.now() - timedelta(days=days)

    configs = list(AssetBotConfig.objects.filter(user=request.user)
                   .order_by("asset_class", "name"))
    selected_id = request.GET.get("config")
    selected = None
    if selected_id:
        selected = next((c for c in configs if str(c.id) == str(selected_id)), None)

    qs = (AssetBotTrade.objects
          .filter(config__user=request.user, status="CLOSED",
                  closed_at__gte=since)
          .select_related("config")
          .order_by("closed_at"))
    if selected:
        qs = qs.filter(config=selected)
    trades = list(qs)

    capital = float(selected.capital) if selected else sum(
        float(c.capital or 0) for c in configs) or 10000.0
    points = _equity_series(trades, capital)

    return render(request, "dashboard/bot_charts.html", {
        "page_id": "bot_charts",
        "configs": configs,
        "selected": selected,
        "days": days,
        "curve": _sparkline_path(points),
        "histogram": _r_histogram(trades),
        "stats": _stats(trades, points),
        "recent": list(reversed(trades[-15:])),
    })
