"""THE OCULUS — /oculus/, every cycle on one screen.

Every other page answers its own question. This one answers the
question none of them could: *is the machine turning, and which of its
wheels is actually engaged?*

It owns no data and adds no arithmetic of its own. Eleven cycles and the
book: the viewer's own book on top — REAL money, the broker's DEMO and
PAPER, side by side and never summed, with the desk's two venues beside
them — then one panel per cycle: the forge, the switches, the scan, the
ladder, the signals, the evolution, the personalities, the allocation,
the horizon, the backtests, the confidence. Each panel carries three
things the other pages never had to carry together:

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

Read-only: it places no orders, writes no rows and flips no switch. It
carries no form and no POST; an action is a link to the page that holds
it. No broker and no model is called to draw it. Every count names its
window, and every stored reading (the forge's scan and plan, the probe,
three ten-minute aggregates) prints its age.
Fenced like /shares/ and /personas/ — a page that 500s because one table
is mid-migration hides the nine panels that were healthy.

Staff's, in part (2026-09-28): the switches and the forge follow
/health/'s rule as the cockpit applies it. oculus() reads the viewer and
withholds those two cycles, and every panel's gate chips, from a login
that is not staff — nothing here decides it.
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
        # The viewer, for THE BOOK — the one per-user panel on an otherwise
        # platform-wide page. Capital belongs to a user; pooling it across
        # the platform would produce a number nobody could act on.
        data = oculus(user=request.user)
    except Exception as exc:  # noqa: BLE001 — oculus() is fenced, this is the belt
        logger.warning("[oculus] unreadable: %s", exc)
        error = (f"The Oculus could not be assembled ({exc}). No number is "
                 f"shown rather than a wrong one.")
        data = {"generated_at": None, "window_days": 0,
                "cycles": [], "degraded": []}

    return render(request, "dashboard/oculus.html", {
        "page_id": "oculus",
        "oculus": data,
        "oculus_error": error,
    })
