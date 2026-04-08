"""Change PIN — handled separately from the profile form so it has
its own POST endpoint with current-PIN verification."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect
from django.views.decorators.http import require_POST


@login_required
@require_POST
def change_pin(request):
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=request.user)

    current = request.POST.get("current_pin", "")
    new_pin = request.POST.get("new_pin", "")
    confirm = request.POST.get("confirm_pin", "")

    if not new_pin or len(new_pin) < 4:
        messages.error(request, "New PIN must be at least 4 digits.")
        return redirect("profile")
    if not new_pin.isdigit():
        messages.error(request, "PIN must be digits only.")
        return redirect("profile")
    if new_pin != confirm:
        messages.error(request, "New PIN and confirmation do not match.")
        return redirect("profile")

    # If a PIN exists, require the current one (unless it's the
    # default 0000 — we still verify it though).
    if prof.access_pin_hash:
        if not check_password(current, prof.access_pin_hash):
            messages.error(request, "Current PIN is incorrect.")
            return redirect("profile")

    prof.access_pin_hash = make_password(new_pin)
    prof.save(update_fields=["access_pin_hash"])
    messages.success(request, "PIN updated successfully.")
    return redirect("profile")
