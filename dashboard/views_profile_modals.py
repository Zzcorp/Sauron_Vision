"""Profile credential modals: PIN + password change with auto-save semantics."""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.contrib.auth import update_session_auth_hash


@login_required
def pin_modal(request):
    """Render the PIN-change modal body for HTMX injection."""
    return render(request, "dashboard/_profile_pin_modal.html", {})


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

    if profile.access_pin_hash:
        if not profile.check_pin(current_pin):
            return JsonResponse({"ok": False, "error": "Current PIN is incorrect."})
    if not new_pin or not new_pin.isdigit() or not (4 <= len(new_pin) <= 8):
        return JsonResponse({"ok": False, "error": "PIN must be 4-8 digits."})
    if new_pin != confirm_pin:
        return JsonResponse({"ok": False, "error": "New PIN and confirmation do not match."})

    profile.set_pin(new_pin)
    profile.save()
    return JsonResponse({"ok": True, "message": "PIN updated."})
