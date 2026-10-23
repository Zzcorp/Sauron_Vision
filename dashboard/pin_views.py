"""Change PIN — the old form endpoint (no page posts here any more; the
profile's modal is the UI). It delegates to the modal's own change
(views_profile_modals.change_pin_answer): the same 4-to-8-digit rule, the
new PIN judged before the current one, and the current one through the
one counted check (core/trading_pin.py)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST


@login_required
@require_POST
def change_pin(request):
    from dashboard.views_profile_modals import change_pin_answer
    ok, message, _logged_out = change_pin_answer(
        request, request.POST.get("current_pin", ""),
        request.POST.get("new_pin", ""), request.POST.get("confirm_pin", ""))
    if not ok:
        messages.error(request, message)
    # A success already said PIN_CHANGED (messages.info).
    return redirect("profile")
