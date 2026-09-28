"""The handover letter (core/passation.py): /passation/, after the hour."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from core import passation


@login_required
def passation_letter(request):
    """404 before OPENS_AT — not a teaser, not a countdown: nothing. After
    it, the letter, for as long as the platform runs."""
    if not passation.is_open():
        raise Http404("Nothing to read here yet.")
    return render(request, "dashboard/passation.html",
                  {"opened_at": passation.OPENS_AT,
                   "card_until": passation.CARD_UNTIL})
