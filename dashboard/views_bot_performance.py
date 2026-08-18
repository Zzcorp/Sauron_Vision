"""Phase-17 bot-trade performance dashboard.

Surfaces the reinforcement loop:
  - Per-rule × asset_class performance over the last N days
  - Per-asset-class roll-ups
  - Recently graded trades

The user can use this to spot rules that grade well at the signal level
(Phase-1 /performance/) but underperform once their bot acts on them.
"""
from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def bot_performance_dashboard(request):
    from bot_program.bot_grading import bot_performance_summary
    from bot_program.models import AssetBotTrade

    try:
        days = max(7, min(int(request.GET.get("days", 90)), 365))
    except (TypeError, ValueError):
        days = 90

    rows = bot_performance_summary(days=days, min_n=1)

    # Filter to this user's configs only. The bare .order_by() clears the model's
    # -opened_at Meta ordering, which would otherwise join the DISTINCT projection
    # and make the DB ship one row per trade instead of one per value.
    user_configs = set(
        AssetBotTrade.objects.filter(config__user=request.user)
        .order_by().values_list("config__id", flat=True).distinct()
    )
    user_rules = set(
        AssetBotTrade.objects.filter(config__user=request.user, status="CLOSED")
        .order_by().values_list("rule_name", flat=True).distinct()
    )
    rows = [r for r in rows if r["rule_name"] in user_rules]

    # Asset-class roll-up.
    by_class: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "n_wins": 0, "sum_r": 0.0})
    for r in rows:
        b = by_class[r["asset_class"]]
        b["n"] += r["n"]
        b["n_wins"] += r["n_wins"]
        b["sum_r"] += r["avg_r"] * r["n"]
    class_rows = []
    for ac, b in sorted(by_class.items()):
        n = b["n"]
        if n == 0:
            continue
        class_rows.append({
            "asset_class": ac,
            "n": n,
            "win_rate": round(b["n_wins"] / n, 4) if n else 0,
            "avg_r": round(b["sum_r"] / n, 4) if n else 0,
        })

    # Recently graded trades.
    recent = list(
        AssetBotTrade.objects
        .filter(config__user=request.user, status="CLOSED")
        .exclude(outcome="")
        .order_by("-closed_at")[:30]
    )

    # Phase 63 — top-line aggregates for the strip
    n_total = sum(r["n"] for r in rows)
    n_wins = sum(r["n_wins"] for r in rows)
    n_losses = n_total - n_wins
    win_rate_total = round(n_wins / n_total, 4) if n_total else 0
    sum_r = sum(r["avg_r"] * r["n"] for r in rows)
    avg_r_overall = round(sum_r / n_total, 4) if n_total else 0
    n_rules = len(rows)
    n_classes = len(class_rows)
    best_rule = max(rows, key=lambda r: r["avg_r"], default=None) if rows else None
    worst_rule = min(rows, key=lambda r: r["avg_r"], default=None) if rows else None

    context = {
        "page_id": "bot_performance",
        "days": days,
        "rows": rows,
        "class_rows": class_rows,
        "recent": recent,
        "n_total": n_total,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate_total": win_rate_total,
        "avg_r_overall": avg_r_overall,
        "sum_r": round(sum_r, 2),
        "n_rules": n_rules,
        "n_classes": n_classes,
        "best_rule": best_rule,
        "worst_rule": worst_rule,
    }
    return render(request, "dashboard/bot_performance.html", context)
