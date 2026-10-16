"""THE HORDE's one door (2026-10-08): GET /api/horde/.

    (nothing) or ?part=board   the open band (dashboard.horde.board)
    ?part=tab                  the collapsed tab, cached 20 s (horde.tab)
    ?seat=bot:<id> | pf:<id>   one seat's dossier, on demand (horde.seat_detail)

Under /api/ on purpose: a locked session's poll gets the idle lock's 423
JSON instead of a redirect, and these polls never count as a human's
activity (core/idle_lock.py). An investor session never reaches it
(core/investor_gate.py). Every read is scoped to request.user in the
queryset itself: another viewer's seat is not hidden, it is not fetched,
and the 404 says nothing about whose it was. GET only; nothing here
writes, and nothing here sends an order.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import horde

logger = logging.getLogger(__name__)

BAD = {"ok": False, "error": "bad_request", "t": "Unknown part or seat key."}
NOT_FOUND = {"ok": False, "error": "not_found",
             "t": "This position is not open in your book."}
UNAVAILABLE = {"ok": False, "error": "unavailable",
               "t": "The Horde could not read your book. Nothing was changed."}


@login_required
@never_cache
@require_GET
def horde_feed(request):
    part = request.GET.get("part")
    seat = request.GET.get("seat")
    if seat is not None:
        if part is not None or horde.parse_seat_key(seat) is None:
            return JsonResponse(BAD, status=400)
        try:
            out = horde.seat_detail(request.user, seat)
        except Exception:  # noqa: BLE001 — said, logged, never a 500 page
            logger.error("[horde] seat %s unreadable", seat, exc_info=True)
            return JsonResponse(UNAVAILABLE, status=503)
        if out is None:
            return JsonResponse(NOT_FOUND, status=404)
        return JsonResponse(out)
    if part in (None, "", "board"):
        build = horde.board
    elif part == "tab":
        build = horde.tab
    else:
        return JsonResponse(BAD, status=400)
    try:
        return JsonResponse(build(request.user))
    except Exception:  # noqa: BLE001
        logger.error("[horde] %s unreadable", part or "board", exc_info=True)
        return JsonResponse(UNAVAILABLE, status=503)
