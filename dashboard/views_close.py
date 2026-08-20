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
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)


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


# ── Close everything, in one decision ────────────────────────────────────
# Position by position is the safe default and a bad answer when the reason
# to be flat is the market rather than the trade: five dialogs and five PIN
# entries, while the thing that made the operator want out keeps moving.
#
# This is NOT the kill switch. `flatten_all_positions` also disables every
# bot and is the emergency stop; this closes the book and leaves the
# platform running, which means an armed bot can open something new on its
# next beat. The dialog says so, because an operator who believes they are
# flat and is not is worse off than one who never pressed the button.

def _open_closable(user):
    """The user's open trades, newest first — the ones a close path exists
    for at all.

    Legacy portfolio.Position rows are deliberately absent: nothing on this
    platform can close one (the headband labels them "manual" for exactly
    that reason), so counting them here would promise something this
    endpoint cannot do.
    """
    from bot_program.models import AssetBotTrade
    return list(
        AssetBotTrade.objects
        .select_related("config", "config__user")
        .filter(config__user=user, status__in=("OPEN", "CLOSE_PENDING"))
        .order_by("-opened_at"))


def _abandoned_count(user):
    """Closes this platform GAVE UP on, which are still live at the broker.

    `pending_closes._give_up` flips a row to ERROR after MAX_RETRY_ATTEMPTS
    failed closes and never sets `closed_at`: the position is still open at
    the broker, the platform has merely stopped firing orders at it. ERROR
    is outside the ("OPEN", "CLOSE_PENDING") filter every open-book read
    uses, so such a row is invisible to `_open_closable`, to the positions
    page, to reconciliation and to the stranded-close health card.

    It must not be invisible HERE, because "flat" is the one word an
    operator acts on without reading further, and a row nothing is watching
    is the last one that should be allowed to satisfy it.
    """
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.filter(
        config__user=user, status="ERROR", closed_at__isnull=True).count()


def _unclosable_count(user):
    """Open legacy rows, which this cannot touch. Reported, never hidden."""
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    book = get_or_create_default_portfolio(user=user)
    return Position.objects.filter(portfolio=book, closed_at__isnull=True).count()


@login_required
def close_all_preview(request):
    """POST — what closing everything would do, before it is done."""
    from bot_program.manual_close import preview_close, requires_pin

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    trades = _open_closable(request.user)
    rows, live_n, pending_n = [], 0, 0
    pnl_total, pnl_measured = 0.0, True
    for trade in trades:
        try:
            p = preview_close(request.user, trade)
        except Exception:  # noqa: BLE001 — one bad row must not hide the rest
            logger.exception("[close-all] preview failed for trade %s", trade.pk)
            p = {}
        venue = str(p.get("venue") or ("paper" if trade.paper else "live"))
        if venue == "live":
            live_n += 1
        if p.get("pending") or trade.status == "CLOSE_PENDING":
            pending_n += 1
        pnl = p.get("pnl")
        if pnl is None:
            # One unmeasured row makes the TOTAL unmeasured. Summing the
            # rest and printing it as the whole would understate what the
            # operator is about to realise.
            pnl_measured = False
        else:
            try:
                pnl_total += float(pnl)
            except (TypeError, ValueError):
                pnl_measured = False
        rows.append({
            "id": trade.pk, "symbol": trade.symbol, "side": trade.side,
            "qty": str(trade.qty), "venue": venue,
            "pending": bool(p.get("pending")),
        })

    return JsonResponse({
        "count": len(rows),
        "live": live_n,
        "paper": len(rows) - live_n,
        "pending": pending_n,
        # requires_pin is per-trade and this is one decision, so ANY live
        # position in the set arms the gate for the whole set. Splitting it
        # into a PIN-less paper pass and a gated live one would close half
        # the book and then stop to ask a question.
        "needs_pin": any(requires_pin(t) for t in trades),
        "pnl": round(pnl_total, 2) if pnl_measured else None,
        "unclosable": _unclosable_count(request.user),
        "rows": rows[:12],
        "more": max(0, len(rows) - 12),
    })


@login_required
def close_all_execute(request):
    """POST {pin} — close every open position this user can close.

    Sequential on purpose. These submit real orders, and firing them
    concurrently would race the same broker session and the same claim locks
    the single-close path takes. Each result is reported individually: a
    partial flatten is the outcome that MUST be visible, because believing
    the book is flat when three rows are still live is how a hedge becomes a
    naked position.
    """
    from bot_program.manual_close import execute_close

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body, err = _body(request)
    if err:
        return JsonResponse({"error": err}, status=400)

    pin_ok = _pin_ok(request, body)
    closed, failed = [], []
    for trade in _open_closable(request.user):
        try:
            result = execute_close(request.user, trade, pin_ok=pin_ok)
        except Exception as e:  # noqa: BLE001
            logger.exception("[close-all] close failed for trade %s", trade.pk)
            failed.append({"symbol": trade.symbol, "error": str(e)[:160]})
            continue
        if result.get("error") or result.get("not_found"):
            failed.append({
                "symbol": trade.symbol,
                "error": str(result.get("error") or "no longer open")[:160],
            })
            continue
        closed.append({
            "symbol": result.get("symbol", trade.symbol),
            "side": result.get("side", trade.side),
            "qty": str(result.get("qty", trade.qty)),
            "exit": result.get("exit"),
            "pnl": result.get("pnl"),
        })

    # RE-READ the book rather than inferring. "Every close returned ok" is
    # not the same claim as "nothing is open": a row can leave the loop in a
    # state that is neither closed nor an error the loop saw — abandoned
    # after its retries, or reopened by a bot on its beat while this ran.
    # `flat` is the one field an operator acts on without reading further,
    # so it is measured, not deduced. Both counts come from ONE read, or
    # `flat` and `unclosable` would describe two different instants.
    still_open = len(_open_closable(request.user))
    unclosable = _unclosable_count(request.user)
    abandoned = _abandoned_count(request.user)
    return JsonResponse({
        "closed": closed,
        "failed": failed,
        "n_closed": len(closed),
        "n_failed": len(failed),
        "still_open": still_open,
        "unclosable": unclosable,
        "abandoned": abandoned,
        # The operator asked to be flat. Whether they ARE is the only
        # question worth answering at the top of the result — and an
        # abandoned close denies it exactly as loudly as an open row does.
        "flat": not still_open and not unclosable and not abandoned,
    })
