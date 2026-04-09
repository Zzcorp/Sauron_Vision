"""Admin bot control panel — surfaces money-protection state for all users."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


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

        configs = BotConfig.objects.select_related("user").all()
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
    """Toggle a bot's enabled flag."""
    try:
        from bot_program.models import BotConfig
        cfg = BotConfig.objects.get(id=config_id)
        cfg.enabled = not cfg.enabled
        cfg.save(update_fields=["enabled"])
        return JsonResponse({"ok": True, "enabled": cfg.enabled})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


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
