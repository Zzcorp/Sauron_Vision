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

    # The FLEET is what this page is about, and the config TAKE TRADE books
    # hand-taken positions against is not part of it — it carries an empty
    # symbol list and can never open anything on its own. The headband's BOT
    # cell already carves it out; this page did not, so an account whose only
    # config was that one showed "NONE — no bot is configured" in the cell
    # and "1 enabled paper bot, 1 open position" on the page the cell links
    # to. Two surfaces one click apart, opposite answers.
    #
    # It is separated, not hidden: the hand-taken book gets its own row below
    # so the positions stay visible and stay attributable to the operator.
    from core.context_processors import _is_manual_config

    all_configs = list(
        AssetBotConfig.objects.filter(user=request.user)
        .order_by("asset_class", "name")
    )
    configs = [c for c in all_configs if not _is_manual_config(c)]
    manual_configs = [c for c in all_configs if _is_manual_config(c)]

    rows = []
    for cfg in configs:
        open_count = AssetBotTrade.objects.filter(config=cfg, status__in=("OPEN", "CLOSE_PENDING")).count()
        since_24h = timezone.now() - timedelta(hours=24)
        closed_24h = AssetBotTrade.objects.filter(
            config=cfg, status="CLOSED", closed_at__gte=since_24h)
        pnl_24h = closed_24h.aggregate(s=Sum("pnl"))["s"] or Decimal("0")
        rows.append({
            "config": cfg,
            "open_positions": open_count,
            "trades_24h": closed_24h.count(),
            "pnl_24h": pnl_24h,
            # The ceiling this config enforces and where it came from. The
            # settings form writes it and cannot show it back (it is a blank
            # create/update form), so this list is where an operator reads a
            # saved value — and where "blank" stops being invisible.
            "time_stop": cfg.time_stop_setting(),
        })

    from bot_program.asset_engine.base import time_stop_status

    open_trades = list(
        AssetBotTrade.objects
        .filter(config__user=request.user, status__in=("OPEN", "CLOSE_PENDING"))
        .select_related("config")
        .order_by("-opened_at")[:30]
    )
    # How much of its ceiling each position has spent. A time stop the
    # operator only learns about when the position is already gone is a
    # surprise; this is the same reading the pre-close warning uses.
    for t in open_trades:
        t.time_stop = time_stop_status(t, config=t.config)
    recent_closed = list(
        AssetBotTrade.objects
        .filter(config__user=request.user, status="CLOSED")
        .select_related("config")
        .order_by("-closed_at")[:30]
    )

    # Phase 63 — top-line aggregates
    n_enabled = sum(1 for c in configs if c.enabled)
    classes = sorted(set(c.asset_class for c in configs))
    pnl_24h_total = sum(float(r["pnl_24h"] or 0) for r in rows)
    n_open_total = sum(r["open_positions"] for r in rows)
    n_trades_24h = sum(r["trades_24h"] for r in rows)

    # The hand-taken book, counted separately so the carve-out above cannot
    # become a hiding place. `open_trades` below is deliberately NOT filtered
    # — a position is a position, and the operator needs to see every one
    # they hold on the page that lists positions.
    manual_open = AssetBotTrade.objects.filter(
        config__in=manual_configs,
        status__in=("OPEN", "CLOSE_PENDING")).count() if manual_configs else 0

    context = {
        "page_id": "asset_bots",
        "rows": rows, "configs": configs,
        "manual_configs": manual_configs,
        "manual_open": manual_open,
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
