"""THE COUNCIL BAND's one door (task #104, 2026-10-22): GET /api/council/band/.

    (nothing) or ?part=room          the open band: head, direction, throne,
                                     the nine, the traders
    ?part=sittings[&before=<id>]     the sittings, 20 at a time
    ?part=record                     the record tab (the room's panels)
    ?sitting=c<id>                   one live sitting's transcript
    ?voice=<key>                     one voice's dossier
    &ev=fill_open|fill_close|council_sitting
                                     an event read: only the panels that
                                     event wakes are read again

Staff only, as the activity drawer's feed is: the band prints verdicts on
real-money entries and the book's limits. Under /api/ on purpose: a
locked session's read gets the idle lock's 423 JSON instead of a redirect,
and these reads never count as a human's activity (core/idle_lock.py); an
investor session never reaches it (core/investor_gate.py). GET only;
nothing here writes, sends an order or calls a model.
"""
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import council_band as band

logger = logging.getLogger(__name__)

BAD = {"ok": False, "error": "bad_request",
       "t": "Unknown part, voice or sitting."}
NOT_FOUND = {"ok": False, "error": "not_found",
             "t": "This sitting is not on record."}
UNAVAILABLE = {"ok": False, "error": "unavailable",
               "t": "The council could not be read. Nothing was changed."}
PARTS = (None, "", "room", "sittings", "record")
SITTING_KEY = re.compile(r"c(\d{1,12})")
BEFORE_KEY = re.compile(r"\d{1,12}")


@login_required
@never_cache
@require_GET
def council_band(request):
    if not request.user.is_staff:
        return JsonResponse({"staff_only": True}, status=403)
    from ai_agents.agents.council import ALL_VOICES
    q = request.GET
    part, sitting, voice = q.get("part"), q.get("sitting"), q.get("voice")
    before, ev = q.get("before"), q.get("ev")
    asked = [x for x in (part, sitting, voice) if x is not None]
    if len(asked) > 1 or part not in PARTS:
        return JsonResponse(BAD, status=400)
    if ev is not None and (ev not in band.EVENTS
                           or part not in (None, "", "room", "sittings")
                           or sitting is not None or voice is not None):
        return JsonResponse(BAD, status=400)
    if before is not None and (part != "sittings"
                               or not BEFORE_KEY.fullmatch(before)):
        return JsonResponse(BAD, status=400)
    if voice is not None and voice not in ALL_VOICES:
        return JsonResponse(BAD, status=400)
    m = SITTING_KEY.fullmatch(sitting) if sitting is not None else None
    if sitting is not None and m is None:
        return JsonResponse(BAD, status=400)
    now = timezone.now().isoformat()
    try:
        if m is not None:
            out = band.build_sitting(request.user, int(m.group(1)))
            if out is None:
                return JsonResponse(NOT_FOUND, status=404)
            return JsonResponse({"ok": True, "now": now, "sitting": out})
        if voice is not None:
            return JsonResponse({"ok": True, "now": now,
                                 "voice": band.build_voice(request.user, voice)})
        if part == "sittings":
            return JsonResponse({"ok": True, "now": now,
                                 "sittings": band.build_sittings(
                                     request.user,
                                     before=int(before) if before else None,
                                     ev=ev)})
        if part == "record":
            return JsonResponse({"ok": True, "now": now,
                                 "record": band.build_record(request.user)})
        return JsonResponse({"ok": True, "now": now,
                             "panels": band.build_room(request.user, ev=ev)})
    except Exception:  # noqa: BLE001 — said, logged, never a 500 page
        logger.error("[council band] unreadable", exc_info=True)
        return JsonResponse(UNAVAILABLE, status=503)
