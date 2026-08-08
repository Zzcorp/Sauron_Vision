"""Trade forensics — the full causal chain behind one fill.

Every fill already records why it happened: the rule that fired, the
signals that voted, the orchestrator's gate decision, the brain's
advisory, the sizing multipliers that were in force, and an immutable
audit trail. Until now that story was spread across five pages, so
"why did the bot do that?" was an archaeology exercise.

This assembles it into one timeline per trade.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render


# Signals within this window of the entry are treated as "what it saw".
SIGNAL_WINDOW_MINUTES = 90


@login_required
def forensics_list(request):
    """Recent fills, newest first — the entry point to a trade's story."""
    from bot_program.models import AssetBotTrade

    qs = (AssetBotTrade.objects
          .filter(config__user=request.user)
          .select_related("config")
          .order_by("-opened_at"))

    symbol = (request.GET.get("symbol") or "").strip().upper()
    if symbol:
        qs = qs.filter(symbol__iexact=symbol)
    rule = (request.GET.get("rule") or "").strip()
    if rule:
        qs = qs.filter(rule_name__icontains=rule)

    page = Paginator(qs, 40).get_page(request.GET.get("page", 1))
    return render(request, "dashboard/forensics_list.html", {
        "page_id": "forensics",
        "page": page, "symbol": symbol, "rule": rule,
        "total": qs.count(),
    })


def _signals_around(trade):
    """Active signals on this instrument near the entry — the bot's inputs."""
    from instruments.models import Instrument
    from signals.models import Signal

    inst = Instrument.objects.filter(symbol=trade.symbol).first()
    if inst is None or trade.opened_at is None:
        return []
    window = timedelta(minutes=SIGNAL_WINDOW_MINUTES)
    return list(
        Signal.objects.filter(
            instrument=inst,
            created_at__gte=trade.opened_at - window,
            created_at__lte=trade.opened_at + timedelta(minutes=5),
        ).order_by("-score")[:12]
    )


def _gate_events(trade):
    """Orchestrator decisions for this symbol around the entry."""
    from bot_program.orchestrator_models import OrchestratorEvent

    if trade.opened_at is None:
        return []
    window = timedelta(minutes=10)
    return list(
        OrchestratorEvent.objects.filter(
            user=trade.config.user, symbol=trade.symbol,
            created_at__gte=trade.opened_at - window,
            created_at__lte=trade.opened_at + window,
        ).order_by("-created_at")[:10]
    )


def _audit_entries(trade):
    """Immutable audit rows that mention this trade."""
    from bot_program.audit_models import AuditLogEntry

    rows = (AuditLogEntry.objects
            .filter(user=trade.config.user,
                    kind__in=("trade_open", "trade_close", "gate_reject"))
            .order_by("-created_at")[:400])
    out = []
    for row in rows:
        data = row.data or {}
        if str(data.get("trade_id")) == str(trade.id) or (
                data.get("symbol") == trade.symbol
                and data.get("asset_class") == trade.asset_class):
            out.append(row)
        if len(out) >= 12:
            break
    return out


def _rule_state(trade):
    """Sizing multipliers and promotion stage in force for the rule."""
    if not trade.rule_name:
        return None
    try:
        from signals.models_control import RuleControl
        ctl = RuleControl.objects.filter(rule_name=trade.rule_name).first()
    except Exception:
        return None
    if ctl is None:
        return None
    weight = float(getattr(ctl, "weight_multiplier", 1) or 1)
    alloc = float(getattr(ctl, "allocator_weight", 1) or 1)
    return {
        "control": ctl,
        "weight_multiplier": weight,
        "allocator_weight": alloc,
        "effective": round(weight * alloc, 4),
        "stage": getattr(ctl, "promotion_stage", ""),
    }


def _rule_track_record(trade):
    """How this rule has actually performed on this asset class."""
    from bot_program.models import AssetBotTrade

    if not trade.rule_name:
        return None
    qs = AssetBotTrade.objects.filter(
        config__user=trade.config.user, rule_name=trade.rule_name,
        asset_class=trade.asset_class, status="CLOSED",
        realized_r__isnull=False)
    n = qs.count()
    if not n:
        return None
    rs = list(qs.values_list("realized_r", flat=True))
    wins = sum(1 for r in rs if r and r > 0)
    return {
        "n": n, "wins": wins, "losses": n - wins,
        "win_rate": round(wins / n, 3),
        "avg_r": round(sum(float(r or 0) for r in rs) / n, 3),
    }


def _lifecycle(trade):
    """A plain-language timeline of what happened to this trade."""
    meta = trade.metadata or {}
    events = []
    if trade.opened_at:
        source = meta.get("fill_source", "ticker")
        events.append({
            "at": trade.opened_at, "label": "Entry filled",
            "detail": (f"{trade.side} {trade.qty} @ {trade.entry_price} "
                       f"({'broker fill' if source == 'broker' else 'ticker price'}"
                       f"{', paper' if trade.paper else ', live'})"),
        })
        if meta.get("protected"):
            events.append({
                "at": trade.opened_at, "label": "Broker-side protection",
                "detail": (f"SL {trade.stop_loss} / TP {trade.take_profit} held "
                           f"at the broker "
                           f"({len(meta.get('protective_order_ids') or [])} legs)"),
            })
    if trade.status == "CLOSE_PENDING":
        events.append({
            "at": None, "label": "Close failed",
            "detail": (f"broker rejected the close "
                       f"({meta.get('close_retry_attempts', 0)} retries); "
                       f"position still open at the broker. "
                       f"{meta.get('close_retry_last_error', '')}"),
        })
    if trade.closed_at:
        events.append({
            "at": trade.closed_at, "label": "Closed",
            "detail": (f"@ {trade.exit_price} · P&L {trade.pnl} · "
                       f"{trade.outcome or 'n/a'}"
                       + (f" · {trade.realized_r}R" if trade.realized_r is not None else "")),
        })
    return events


@login_required
def forensics_detail(request, trade_id: int):
    from bot_program.models import AssetBotTrade

    trade = get_object_or_404(
        AssetBotTrade.objects.select_related("config"),
        id=trade_id, config__user=request.user)

    signals = _signals_around(trade)
    return render(request, "dashboard/forensics_detail.html", {
        "page_id": "forensics",
        "trade": trade,
        "reasons": [r.strip() for r in (trade.reason or "").split("·") if r.strip()],
        "signals": signals,
        "signal_agree": [s for s in signals
                         if (s.direction == "bullish") == (trade.side == "BUY")],
        "gate_events": _gate_events(trade),
        "audit_entries": _audit_entries(trade),
        "rule_state": _rule_state(trade),
        "track_record": _rule_track_record(trade),
        "lifecycle": _lifecycle(trade),
        "metadata_items": sorted((trade.metadata or {}).items()),
    })
