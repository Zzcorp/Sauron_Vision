"""THE OCULUS — /oculus/, every cycle on one screen.

Thirty dashboards answered thirty questions. This one answers the
question none of them could: *is the machine turning, and which of its
wheels is actually engaged?*

It owns no data and adds no arithmetic of its own. Each panel is one
cycle — the switches, the scan, the ladder, the signals, the evolution,
the personalities, the allocation, the horizon, the backtests, the
trust — and each panel carries three things the thirty pages never had
to carry together:

1. THE GATE. Every count is rendered beside the switch of the component
   that writes it. A number produced by a task nobody has turned on is a
   measurement of the switch, not of the market, and on 2026-09-13 three
   components turned out never to have had a row at all.

2. THE QUALIFIER. The recurring failure in this codebase is a right
   number that reads as its opposite — "26 rules registered" sounds like
   coverage while a research-stage rule cannot trade AND has its signals
   dropped from the vote. Every such count states what it means in the
   same breath, and the ones that cannot act are toned down rather than
   celebrated.

3. THE EM-DASH. A counter that could not be read renders "—", never 0.
   `core/wall_facts.py` collapses to 0 because it is the public login
   gateway and must never raise; behind auth the duty is the opposite,
   because "measured zero" and "not measurable" are different answers
   and an operator acts differently on each.

Read-only: it places no orders, writes no rows and flips no switch.
Fenced like /shares/ and /personas/ — a page that 500s because one table
is mid-migration hides the nine panels that were healthy.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

logger = logging.getLogger(__name__)


@login_required
def oculus_dashboard(request):
    from .oculus import oculus

    data, error = None, ""
    try:
        data = oculus()
    except Exception as exc:  # noqa: BLE001 — oculus() is fenced, this is the belt
        logger.warning("[oculus] unreadable: %s", exc)
        error = (f"L'Occulus n'a pas pu être assemblé ({exc}). Aucun chiffre "
                 f"n'est affiché plutôt qu'un chiffre faux.")
        data = {"generated_at": None, "window_days": 0,
                "cycles": [], "degraded": []}

    return render(request, "dashboard/oculus.html", {
        "page_id": "oculus",
        "oculus": data,
        "oculus_error": error,
    })
