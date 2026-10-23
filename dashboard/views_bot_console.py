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
    """Toggle the user's bot enabled flag (the big PAUSE/RESUME button).

    RESUME on a LIVE bot arms real money: it takes the trading PIN
    (2026-10-23), through the one counted check (core/trading_pin.py, an
    ACT door). PAUSE never asks, and paper is unchanged. `want` (on|off)
    is the direction the page meant: a stale click writes nothing."""
    from bot_program.models import BotConfig
    cfg = BotConfig.objects.filter(user=request.user).first()
    if cfg is None:
        return JsonResponse({"ok": False, "error": "No bot is configured."})
    want = request.POST.get("want", "")
    if want in ("on", "off") and (want == "on") == bool(cfg.enabled):
        return JsonResponse({"ok": True, "enabled": cfg.enabled,
                             "unchanged": True})
    if not cfg.enabled and cfg.mode == "live":
        from core.trading_pin import ACT, gate, json_refusal, refusal_of
        pin_ok = gate(request, request.POST.get("pin", ""), door=ACT,
                      act="resume a live crypto bot")
        if not pin_ok:
            return JsonResponse(json_refusal(
                refusal_of(pin_ok), subject="Resuming the bot LIVE",
                nothing="it stays paused", extra={"ok": False}))
    cfg.enabled = not cfg.enabled
    cfg.save(update_fields=["enabled"])
    if cfg.mode == "live":
        from bot_program.audit import record_legacy_bot
        record_legacy_bot(cfg, on=cfg.enabled, via="bot_console",
                          who=request.user.username, user=request.user)
    return JsonResponse({"ok": True, "enabled": cfg.enabled})
