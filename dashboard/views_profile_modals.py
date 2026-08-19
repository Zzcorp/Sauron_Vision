"""Profile credential modals: PIN + password change with auto-save semantics."""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.contrib.auth import update_session_auth_hash


@login_required
def pin_modal(request):
    """Render the PIN-change modal body for HTMX injection.

    Someone arriving from the forgot-PIN gate must not be asked for the
    very value they just declared lost — change_pin_modal waives the
    check, and the form has to say so.
    """
    return render(request, "dashboard/_profile_pin_modal.html", {
        "force_pin_reset": bool(request.session.get("force_pin_reset")),
    })


@login_required
def password_modal(request):
    """Render the password-change modal body for HTMX injection."""
    return render(request, "dashboard/_profile_password_modal.html", {})


@login_required
@require_POST
def change_password(request):
    """Validate + persist new password. Returns JSON for the modal JS."""
    user = request.user
    current = request.POST.get("current_password", "")
    new = request.POST.get("new_password", "")
    confirm = request.POST.get("confirm_password", "")

    if not user.check_password(current):
        return JsonResponse({"ok": False, "error": "Current password is incorrect."})
    if not new or len(new) < 8:
        return JsonResponse({"ok": False, "error": "New password must be at least 8 characters."})
    if new != confirm:
        return JsonResponse({"ok": False, "error": "New password and confirmation do not match."})

    user.set_password(new)
    user.save()
    update_session_auth_hash(request, user)
    return JsonResponse({"ok": True, "message": "Password updated."})


@login_required
@require_POST
def change_pin_modal(request):
    """JSON-returning version of the PIN change endpoint for the modal."""
    # No bare `except` here. This import used to fail — get_or_create_profile
    # did not exist — and the handler reported "profile module unavailable",
    # which reads like a transient hiccup rather than "this feature has never
    # worked". Setting a PIN is a prerequisite for arming any bot live, so a
    # failure here has to be a 500 someone can see, not a polite string.
    from portfolio.trader_profile import get_or_create_profile
    profile = get_or_create_profile(request.user)
    current_pin = request.POST.get("current_pin", "")
    new_pin = request.POST.get("new_pin", "")
    confirm_pin = request.POST.get("confirm_pin", "")

    # The forgot-PIN flow (login_pin_forgot) re-verified the password at the
    # gate and set this flag — the whole point is that the current PIN is
    # unknown, so waive it here. Popped only when the reset succeeds: a typo
    # in the new PIN must not burn the one-shot waiver and dead-end the user.
    force_pin_reset = bool(request.session.get("force_pin_reset"))

    if profile.access_pin_hash and not force_pin_reset:
        if not profile.check_pin(current_pin):
            return JsonResponse({"ok": False, "error": "Current PIN is incorrect."})
    if not new_pin or not new_pin.isdigit() or not (4 <= len(new_pin) <= 8):
        return JsonResponse({"ok": False, "error": "PIN must be 4-8 digits."})
    if new_pin != confirm_pin:
        return JsonResponse({"ok": False, "error": "New PIN and confirmation do not match."})

    profile.set_pin(new_pin)
    profile.save()
    if force_pin_reset:
        request.session.pop("force_pin_reset", None)
        from core.audit import AuditLog
        AuditLog.log(
            user=request.user,
            action="config_change",
            description="PIN reset via forgot-PIN flow (password re-verified at the gate)",
            target_type="TraderProfile",
            target_id=profile.id,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    return JsonResponse({"ok": True, "message": "PIN updated."})
