"""User-facing bot console: live positions + pause + decisions log."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


@login_required
def bot_console(request):
    """Render the user's bot console page."""
    ctx = {
        "config": None, "open_trades": [], "recent_trades": [],
        "heartbeat": None, "shadow": False, "circuit": "",
    }
    try:
        cfg = request.user.bot_config
    except Exception:
        cfg = None
    if cfg:
        ctx["config"] = cfg
        try:
            ctx["open_trades"] = list(cfg.trades.filter(status="OPEN")[:20])
            ctx["recent_trades"] = list(cfg.trades.filter(status="CLOSED").order_by("-closed_at")[:10])
        except Exception:
            pass
        try:
            from bot_program.engine.heartbeat import heartbeat_age_seconds
            ctx["heartbeat"] = heartbeat_age_seconds(cfg)
        except Exception:
            pass
        try:
            from bot_program.engine.shadow import is_shadow_mode
            ctx["shadow"] = is_shadow_mode(cfg)
        except Exception:
            pass
        try:
            ctx["circuit"] = cfg.circuit_state.halt_reason or ""
        except Exception:
            pass
    return render(request, "dashboard/bot_console.html", ctx)


@login_required
@require_POST
def bot_pause(request):
    """Toggle the user's bot enabled flag (the big PAUSE/RESUME button)."""
    try:
        cfg = request.user.bot_config
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"no config: {e}"})
    cfg.enabled = not cfg.enabled
    cfg.save(update_fields=["enabled"])
    return JsonResponse({"ok": True, "enabled": cfg.enabled})
