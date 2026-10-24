"""Admin bot control panel — surfaces money-protection state for all users."""
import logging

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _is_staff(u):
    return u.is_authenticated and u.is_staff


@login_required
@user_passes_test(_is_staff)
def admin_bots_panel(request):
    """Render the admin bot control panel."""
    rows = []
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.heartbeat import heartbeat_age_seconds
        from bot_program.engine.shadow import is_shadow_mode

        # BotConfig has no Meta ordering — pin the panel to username order.
        configs = BotConfig.objects.select_related("user").order_by("user__username")
        for cfg in configs:
            try:
                circuit = cfg.circuit_state.halt_reason or ""
            except Exception:
                circuit = ""
            try:
                hb_age = heartbeat_age_seconds(cfg)
            except Exception:
                hb_age = None
            rows.append({
                "config": cfg,
                "user": cfg.user,
                "enabled": cfg.enabled,
                "mode": cfg.mode,
                "market": cfg.market_type,
                "shadow": is_shadow_mode(cfg),
                "heartbeat_age": hb_age,
                "circuit": circuit,
                "open_trades": cfg.trades.filter(status="OPEN").count() if hasattr(cfg, "trades") else 0,
            })
    except Exception as e:
        return render(request, "dashboard/_admin_bots.html", {"error": str(e), "rows": []})

    return render(request, "dashboard/_admin_bots.html", {"rows": rows})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_toggle(request, config_id):
    """Toggle a bot's enabled flag — any user's legacy crypto bot.

    Arming one in LIVE mode takes the ACTING staff user's trading PIN
    (D2, 2026-10-23), through the one counted check (core/trading_pin.py,
    an ACT door). Turning one off never asks, and paper is unchanged.
    `want` (on|off) is the direction the panel meant: a stale click on a
    bot already in that state writes nothing. Every live flip is recorded.
    Always HTTP 200: the panel reads the body's `ok`."""
    from bot_program.models import BotConfig
    cfg = BotConfig.objects.select_related("user").filter(id=config_id).first()
    if cfg is None:
        return JsonResponse({"ok": False, "error": "No such bot."})
    want = request.POST.get("want", "")
    if want in ("on", "off") and (want == "on") == bool(cfg.enabled):
        return JsonResponse({"ok": True, "enabled": cfg.enabled,
                             "unchanged": True})
    if not cfg.enabled and cfg.mode == "live":
        from core.trading_pin import ACT, gate, json_refusal, refusal_of
        pin_ok = gate(request, request.POST.get("pin", ""), door=ACT,
                      act="arm a live crypto bot (admin panel)")
        if not pin_ok:
            owner = cfg.user.username
            return JsonResponse(json_refusal(
                refusal_of(pin_ok),
                subject=f"Arming {owner}'s crypto bot LIVE",
                nothing="it stays OFF", extra={"ok": False}))
    try:
        cfg.enabled = not cfg.enabled
        cfg.save(update_fields=["enabled"])
    except Exception:  # noqa: BLE001 — never the exception's text
        logger.exception("[admin bots] toggle of config %s failed", config_id)
        return JsonResponse({"ok": False,
                             "error": "The bot could not be changed; the "
                                      "reason is in the server log."})
    if cfg.mode == "live":
        from bot_program.audit import record_legacy_bot
        record_legacy_bot(cfg, on=cfg.enabled, via="admin_bots",
                          who=request.user.username, user=request.user)
    return JsonResponse({"ok": True, "enabled": cfg.enabled})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_shadow(request, config_id):
    """Enable shadow mode for N hours."""
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.shadow import enable_shadow
        cfg = BotConfig.objects.get(id=config_id)
        hours = int(request.POST.get("hours", 24))
        until = enable_shadow(cfg, hours=hours)
        return JsonResponse({"ok": True, "shadow_until": str(until)})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_reset_circuit(request, config_id):
    """Clear the circuit breaker state for a config."""
    try:
        from bot_program.models import BotConfig
        from bot_program.models_v2 import BotCircuitState
        cfg = BotConfig.objects.get(id=config_id)
        BotCircuitState.objects.filter(config=cfg).update(
            error_count_in_burst=0,
            last_error_burst_started=None,
            halted_until=None,
            halt_reason="",
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_reconcile(request, config_id):
    """Force a reconciliation pass for a config."""
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.reconcile import reconcile_user
        cfg = BotConfig.objects.get(id=config_id)
        result = reconcile_user(cfg.user_id)
        return JsonResponse({"ok": True, "result": result})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
