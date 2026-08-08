"""AssetBot dashboard — Phase 13."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone


@login_required
def asset_bots_dashboard(request):
    from bot_program.models import AssetBotConfig, AssetBotTrade

    configs = list(
        AssetBotConfig.objects.filter(user=request.user)
        .order_by("asset_class", "name")
    )

    rows = []
    for cfg in configs:
        open_count = AssetBotTrade.objects.filter(config=cfg, status="OPEN").count()
        since_24h = timezone.now() - timedelta(hours=24)
        closed_24h = AssetBotTrade.objects.filter(
            config=cfg, status="CLOSED", closed_at__gte=since_24h)
        pnl_24h = closed_24h.aggregate(s=Sum("pnl"))["s"] or Decimal("0")
        rows.append({
            "config": cfg,
            "open_positions": open_count,
            "trades_24h": closed_24h.count(),
            "pnl_24h": pnl_24h,
        })

    open_trades = list(
        AssetBotTrade.objects
        .filter(config__user=request.user, status="OPEN")
        .select_related("config")
        .order_by("-opened_at")[:30]
    )
    recent_closed = list(
        AssetBotTrade.objects
        .filter(config__user=request.user, status="CLOSED")
        .select_related("config")
        .order_by("-closed_at")[:30]
    )

    # Phase 63 — top-line aggregates
    n_enabled = sum(1 for c in configs if getattr(c, "is_enabled", False))
    classes = sorted(set(c.asset_class for c in configs))
    pnl_24h_total = sum(float(r["pnl_24h"] or 0) for r in rows)
    n_open_total = sum(r["open_positions"] for r in rows)
    n_trades_24h = sum(r["trades_24h"] for r in rows)

    context = {
        "page_id": "asset_bots",
        "rows": rows, "configs": configs,
        "open_trades": open_trades,
        "recent_closed": recent_closed,
        "n_enabled": n_enabled,
        "n_classes": len(classes),
        "classes_str": ", ".join(classes) if classes else "—",
        "pnl_24h_total": round(pnl_24h_total, 2),
        "n_open_total": n_open_total,
        "n_trades_24h": n_trades_24h,
    }
    return render(request, "dashboard/asset_bots.html", context)
