"""Phase-21 Eye drill-down panels.

Three filterable detail views off the Sauron's-Eye dashboard:
  /eye/gate-events/ — full orchestrator decision history with filters
  /eye/fills/       — full AssetBotTrade history (open + closed) with filters
  /eye/exposure/    — theme exposure breakdown showing which open positions
                      contribute to each USD/equity/vol/currency/sector dimension

Per-user scoped — each user only sees their own events / trades.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.shortcuts import render
from django.utils import timezone


def _parse_days(request, *, default=7, max_days=365) -> int:
    try:
        return max(1, min(int(request.GET.get("days", default)), max_days))
    except (TypeError, ValueError):
        return default


# ── Gate events ──────────────────────────────────────────────────────────

@login_required
def eye_gate_events(request):
    from bot_program.models import OrchestratorEvent

    days = _parse_days(request)
    since = timezone.now() - timedelta(days=days)
    decision = (request.GET.get("decision") or "").strip().lower()
    asset_class = (request.GET.get("asset_class") or "").strip().lower()
    symbol = (request.GET.get("symbol") or "").strip().upper()
    q = (request.GET.get("q") or "").strip()

    qs = (OrchestratorEvent.objects
          .filter(user=request.user, created_at__gte=since)
          .order_by("-created_at"))
    if decision in ("allow", "reject"):
        qs = qs.filter(decision=decision)
    if asset_class:
        qs = qs.filter(asset_class=asset_class)
    if symbol:
        qs = qs.filter(symbol__iexact=symbol)
    if q:
        qs = qs.filter(Q(reason__icontains=q) | Q(symbol__icontains=q))

    # Stats over the filtered window.
    total = qs.count()
    rejects = qs.filter(decision="reject").count()
    allows = total - rejects
    rejection_rate = (rejects / total) if total else 0.0

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page", 1))

    asset_classes = sorted(set(
        OrchestratorEvent.objects
        .filter(user=request.user, created_at__gte=since)
        .values_list("asset_class", flat=True).distinct()
    ))

    context = {
        "page_id": "eye",
        "days": days, "decision": decision, "asset_class": asset_class,
        "symbol": symbol, "q": q,
        "total": total, "rejects": rejects, "allows": allows,
        "rejection_rate": round(rejection_rate, 4),
        "asset_classes": asset_classes,
        "page": page,
    }
    return render(request, "dashboard/eye_gate_events.html", context)


# ── Fills ────────────────────────────────────────────────────────────────

@login_required
def eye_fills(request):
    from bot_program.models import AssetBotTrade

    days = _parse_days(request, default=14)
    since = timezone.now() - timedelta(days=days)
    asset_class = (request.GET.get("asset_class") or "").strip().lower()
    symbol = (request.GET.get("symbol") or "").strip().upper()
    side = (request.GET.get("side") or "").strip().upper()
    outcome = (request.GET.get("outcome") or "").strip().lower()
    mode = (request.GET.get("mode") or "").strip().lower()  # paper|live

    qs = (AssetBotTrade.objects
          .filter(config__user=request.user, opened_at__gte=since)
          .select_related("config")
          .order_by("-opened_at"))
    if asset_class:
        qs = qs.filter(asset_class=asset_class)
    if symbol:
        qs = qs.filter(symbol__iexact=symbol)
    if side in ("BUY", "SELL"):
        qs = qs.filter(side=side)
    if outcome:
        qs = qs.filter(outcome=outcome)
    if mode == "paper":
        qs = qs.filter(paper=True)
    elif mode == "live":
        qs = qs.filter(paper=False)

    # Aggregate stats over the filtered window.
    closed = qs.filter(status="CLOSED")
    n_closed = closed.count()
    n_wins = closed.filter(realized_r__gt=0).count()
    win_rate = (n_wins / n_closed) if n_closed else 0.0
    pnl_total = closed.aggregate(s=Sum("pnl"))["s"] or Decimal("0")
    total_r_sum = closed.aggregate(s=Sum("realized_r"))["s"]
    total_r = float(total_r_sum) if total_r_sum is not None else 0.0

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page", 1))

    asset_classes = sorted(set(
        AssetBotTrade.objects
        .filter(config__user=request.user, opened_at__gte=since)
        .values_list("asset_class", flat=True).distinct()
    ))

    context = {
        "page_id": "eye",
        "days": days, "asset_class": asset_class, "symbol": symbol,
        "side": side, "outcome": outcome, "mode": mode,
        "total": qs.count(),
        "n_closed": n_closed, "n_wins": n_wins,
        "win_rate": round(win_rate, 4),
        "pnl_total": pnl_total,
        "total_r": round(total_r, 4),
        "asset_classes": asset_classes,
        "page": page,
    }
    return render(request, "dashboard/eye_fills.html", context)


# ── Exposure breakdown ───────────────────────────────────────────────────

@login_required
def eye_exposure(request):
    """For each open position, show how it contributes to every theme/currency
    dimension. Lets the user see *why* the gate sees what it sees."""
    from bot_program.models import AssetBotTrade
    from bot_program.orchestrator import (
        classify_full, current_exposures, trade_size_weight,
    )
    from portfolio.trader_profile import TraderProfile

    profile = TraderProfile.objects.filter(user=request.user).first()
    weighted = bool(profile and getattr(profile, "size_weighted_orchestrator", False))
    full = current_exposures(request.user)

    # Per-trade contribution table.
    rows = []
    qs = (AssetBotTrade.objects
          .filter(config__user=request.user, status="OPEN")
          .select_related("config")
          .order_by("asset_class", "symbol"))
    for t in qs:
        right = (t.metadata or {}).get("right", "") if t.asset_class == "options" else ""
        c = classify_full(t.asset_class, t.symbol, t.side, right=right)
        weight = trade_size_weight(t) if weighted else 1.0
        rows.append({
            "trade": t,
            "asset_class": t.asset_class,
            "symbol": t.symbol,
            "side": t.side,
            "right": right,
            "weight": round(weight, 3),
            "themes": {k: round(v * weight, 3) for k, v in c["themes"].items()},
            "currencies": {k: round(v * weight, 3) for k, v in c["currencies"].items()},
            "sector": c["sector"],
        })

    context = {
        "page_id": "eye",
        "weighted": weighted,
        "exposures": full,
        "rows": rows,
        "n_open": len(rows),
    }
    return render(request, "dashboard/eye_exposure.html", context)
