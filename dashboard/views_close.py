"""CLOSE POSITION — the HTTP half of bot_program/manual_close.

Two POST endpoints shaped exactly like the TAKE TRADE pair, because the
front end runs the same preview → confirm → execute flow: fetch the facts,
show them in the house dialog, then act on what the operator saw.

Ownership is enforced by the QUERYSET, not by a check after the fetch:
another user's trade is not "forbidden", it is not found, and answering 404
is the only answer that does not confirm the row exists.
"""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404


def _trade_for(request, trade_id):
    """The user's own trade, or 404."""
    from bot_program.models import AssetBotTrade
    return get_object_or_404(
        AssetBotTrade.objects.select_related("config", "config__user"),
        pk=trade_id, config__user=request.user)


def _pin_ok(request, body) -> bool:
    """True iff the acting user supplied their correct trading PIN.

    Same check the kill switch and live-arming use — the PIN arrives in the
    JSON body here rather than a form field, because the close flow is an
    XHR from a dialog. A user with no PIN set can never satisfy it, which
    is the intended outcome: the platform already tells them to set one
    before anything live is reachable.
    """
    from django.contrib.auth.hashers import check_password
    pin = str((body or {}).get("pin", ""))
    prof = getattr(request.user, "trader_profile", None)
    return bool(prof and prof.access_pin_hash
                and check_password(pin, prof.access_pin_hash))


def _body(request):
    """Parse the JSON body into a dict, or (None, error).

    Strict on shape for the same reason the take-trade parser is: a
    non-object body used to 500 on .get, and this one carries a PIN.
    """
    try:
        parsed = json.loads(request.body.decode() or "{}")
    except ValueError:
        return None, "Body must be JSON"
    if not isinstance(parsed, dict):
        return None, "Body must be a JSON object"
    return parsed, None


@login_required
def close_position_preview(request, trade_id):
    """POST — the facts the CLOSE confirm popup shows: what closes, at what
    mark, the P&L and the R it realises against the ENTRY stop. Nothing is
    executed and nothing is claimed here."""
    from bot_program.manual_close import preview_close

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    trade = _trade_for(request, trade_id)
    return JsonResponse(preview_close(request.user, trade))


@login_required
def close_position_execute(request, trade_id):
    """POST {pin} — close the position previewed above.

    The PIN is required for LIVE positions only; manual_close.requires_pin
    owns that rule, and this view only supplies the verdict. A refusal here
    closes nothing, which is why the message says so explicitly.
    """
    from bot_program.manual_close import execute_close

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    trade = _trade_for(request, trade_id)
    body, err = _body(request)
    if err:
        return JsonResponse({"error": err}, status=400)

    result = execute_close(request.user, trade, pin_ok=_pin_ok(request, body))
    # The row vanished between the fetch and the locked re-read — deleted,
    # or reassigned. 404 is the same answer the fetch would have given.
    if result.get("not_found"):
        return JsonResponse({"error": "No such position"}, status=404)
    return JsonResponse(result)
