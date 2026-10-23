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


#: Said after any PIN change: the session's login mark no longer matches,
#: so every live act waits for a fresh login; closing does not.
PIN_CHANGED = ("PIN updated: log out and log back in with it before your "
               "next live act; closing a position and the kill switch work "
               "as they are.")


def change_pin_answer(request, current_pin, new_pin, confirm_pin):
    """THE PIN change, for the modal and the old form alike:
    (ok, message, logged_out).

    The order is the fix for an oracle (2026-10-23, guidance g): the new
    PIN's shape and its confirmation are judged FIRST, with no secret
    involved; only then the current PIN, through the one counted check
    (core.trading_pin, an ACT door: the fifth wrong answer ends the
    session, and a session that did not log in under the current PIN must
    log in again). A right current PIN can no longer be told from a wrong
    one by a refusal about the new PIN.

    No PIN set yet: nothing to check, the first PIN is set, and the
    session's login mark no longer matches, so it opens and arms nothing
    until a fresh login. The forgot-PIN flow (login_pin_forgot) re-verified
    the password at the gate and set `force_pin_reset`: the current PIN is
    waived, and the flag is popped only when the reset succeeds, so a typo
    in the new PIN does not burn the one-shot waiver.
    """
    from portfolio.trader_profile import get_or_create_profile
    from core.trading_pin import ACT, check, sentence

    new_pin = new_pin or ""
    if not new_pin.isdigit() or not (4 <= len(new_pin) <= 8):
        return False, "PIN must be 4-8 digits.", False
    if new_pin != (confirm_pin or ""):
        return False, "New PIN and confirmation do not match.", False

    # No bare `except` here. This import used to fail — get_or_create_profile
    # did not exist — and the handler reported "profile module unavailable",
    # which reads like a transient hiccup rather than "this feature has never
    # worked". Setting a PIN is a prerequisite for arming any bot live, so a
    # failure here has to be a 500 someone can see, not a polite string.
    profile = get_or_create_profile(request.user)
    force_pin_reset = bool(request.session.get("force_pin_reset"))
    if profile.has_pin and not force_pin_reset:
        verdict = check(request, current_pin, door=ACT,
                        act="change the trading PIN")
        if not verdict.ok:
            return (False, sentence(verdict, subject="Changing your PIN",
                                    nothing="your PIN was not changed"),
                    verdict.logged_out)

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
    from django.contrib import messages
    messages.info(request, PIN_CHANGED)
    return True, "PIN updated.", False


@login_required
@require_POST
def change_pin_modal(request):
    """JSON-returning version of the PIN change endpoint for the modal."""
    ok, message, logged_out = change_pin_answer(
        request, request.POST.get("current_pin", ""),
        request.POST.get("new_pin", ""), request.POST.get("confirm_pin", ""))
    if ok:
        return JsonResponse({"ok": True, "message": message})
    return JsonResponse({"ok": False, "error": message,
                         "logged_out": logged_out})
