"""The handover letter (core/passation.py): /passation/, after the hour."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core import passation


@login_required
def passation_letter(request):
    """Before OPENS_AT the reader is sent to the dashboard — not a teaser,
    not a countdown, not a 404 either: probe_routes counts a 404 as a page
    wired to nothing, and this page is wired to a clock. After the hour,
    the letter, for as long as the platform runs."""
    if not passation.is_open():
        return redirect("dashboard")
    return render(request, "dashboard/passation.html",
                  {"opened_at": passation.OPENS_AT,
                   "card_until": passation.CARD_UNTIL})
