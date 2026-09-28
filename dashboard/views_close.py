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


@login_required
def position_levels(request, trade_id):
    """POST {stop, target, clear_target, pin} — move a position's levels.

    Beside the close flow because it is the same shape of decision: a
    money action on one row, taken from a dialog, refused with a reason
    the operator can act on rather than a status code.

    The PIN is required for LIVE positions only, matching the close. A
    paper row is a simulation and gating it teaches the operator to type
    the PIN reflexively, which is the opposite of what a PIN is for.
    """
    from bot_program.adjust_levels import adjust_levels

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    trade = _trade_for(request, trade_id)
    body, err = _body(request)
    if err:
        return JsonResponse({"error": err}, status=400)

    if not trade.paper and not _pin_ok(request, body):
        return JsonResponse(
            {"error": "This is a LIVE position — the trading PIN is "
                      "required to move its stop or target. Nothing was "
                      "changed.", "pin_required": True}, status=403)

    result = adjust_levels(
        request.user, trade,
        stop=body.get("stop"), target=body.get("target"),
        clear_target=bool(body.get("clear_target")))
    if result.get("gone"):
        return JsonResponse({"error": result["error"]}, status=404)
    if not result.get("ok"):
        return JsonResponse({"error": result.get("error", "Refused.")},
                            status=400)
    return JsonResponse(result)


# ── Close what was TICKED, and ask first whether to ──────────────────────
# Between one row and the whole book there was nothing: an operator who
# wanted out of the three crypto longs had three dialogs and three PINs, or
# the button that also closed the forex. These act on the ids the page
# sends and on nothing else — re-read owner-scoped at every step, so a row
# that vanished between the tick and the confirm is REPORTED, never
# replaced by whatever else happens to be open.

#: At most this many rows per request. Past it the question is the whole
#: book, which already has its own button and its own dialog.
MAX_SELECTED = 50


def _ids_from(body):
    """(ids, error) — the ticked trade ids, in the order sent.

    Strict for the same reason `_body` is: this list decides which real
    positions close. Anything that is not a positive whole number is a
    malformed request, not something to guess about; duplicates are
    folded so a row can never be closed "twice" in one loop.
    """
    raw = (body or {}).get("ids")
    if not isinstance(raw, list) or not raw:
        return None, "ids must be a non-empty list of position ids"
    if len(raw) > MAX_SELECTED:
        return None, "At most %d positions at a time" % MAX_SELECTED
    ids = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return None, "ids must be whole numbers"
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None, "ids must be whole numbers"
        if n <= 0:
            return None, "ids must be whole numbers"
        if n not in ids:
            ids.append(n)
    return ids, None


def _ccy(trade) -> str:
    """The currency a row's money is booked in — its config's."""
    return (getattr(trade.config, "base_currency", "") or "USD").strip()


def _selected_closable(user, ids):
    """(trades in the order asked, missing ids).

    The same ownership and status filter as `_open_closable` — the user's
    own rows, OPEN or CLOSE_PENDING — narrowed to the ids. A missing id is
    another user's row, a closed one, or one that never existed; the
    answer does not say which, for the reason `_trade_for` answers 404.
    """
    from bot_program.models import AssetBotTrade
    found = {t.pk: t for t in (
        AssetBotTrade.objects
        .select_related("config", "config__user")
        .filter(pk__in=ids, config__user=user,
                status__in=("OPEN", "CLOSE_PENDING")))}
    return ([found[i] for i in ids if i in found],
            [i for i in ids if i not in found])


@login_required
def close_advice(request):
    """POST {ids, model} — is closing these a good idea? Advice only.

    Nothing here closes, claims or sends anything: brain.close_advice has
    no path to the engine, and a source test pins that. `model: true` asks
    for the one AI call too; the answer says in words when it could not be
    had (no key, no budget, an error) and stands on the rules alone.
    """
    from brain.close_advice import advise

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body, err = _body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    ids, err = _ids_from(body)
    if err:
        return JsonResponse({"error": err}, status=400)
    model = body.get("model", False)
    if not isinstance(model, bool):
        return JsonResponse({"error": "model must be true or false"},
                            status=400)
    return JsonResponse(advise(request.user, ids, use_model=model))


@login_required
def close_selected_preview(request):
    """POST {ids} — what closing the ticked rows would do, before it is done.

    close_all_preview's shape, over the selection, plus the ids that are no
    longer there and the three worlds counted apart: the close-all dialog
    counts an eToro demo row as "live" because its preview venue is, and
    this dialog must not say real money about simulated money.
    """
    from bot_program.manual_close import preview_close, requires_pin
    from brain.close_advice import world_of
    from dashboard.position_summary import money

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body, err = _body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    ids, err = _ids_from(body)
    if err:
        return JsonResponse({"error": err}, status=400)

    trades, missing = _selected_closable(request.user, ids)
    rows, pending_n = [], 0
    worlds = {"live": 0, "demo": 0, "paper": 0}
    pnl_total, pnl_measured = 0.0, True
    for trade in trades:
        try:
            p = preview_close(request.user, trade)
        except Exception:  # noqa: BLE001 — one bad row must not hide the rest
            logger.exception("[close-selected] preview failed for trade %s",
                             trade.pk)
            p = {}
        # The world, never preview_close's "venue": that word is "live" for
        # every paper=False row, an eToro demo included, because it says
        # where the close is SENT (the broker) rather than whose money it is.
        world = world_of(trade)[0]
        worlds[world] = worlds.get(world, 0) + 1
        if p.get("pending") or trade.status == "CLOSE_PENDING":
            pending_n += 1
        pnl = p.get("pnl")
        if pnl is None:
            # Same rule as close-all: one unmeasured row makes the total
            # unmeasured rather than a flattering partial sum.
            pnl_measured = False
        else:
            try:
                pnl_total += float(pnl)
            except (TypeError, ValueError):
                pnl_measured = False
        rows.append({
            "id": trade.pk, "symbol": trade.symbol, "side": trade.side,
            "qty": str(trade.qty), "world": world,
            "pending": bool(p.get("pending")),
            "error": str(p.get("error") or "")[:160],
        })

    # Summed only inside one currency: 12 USD and 900 JPY is not a total,
    # and printing one would state a realised figure nobody will receive.
    ccys = {_ccy(t) for t in trades}
    pnl = (round(pnl_total, 2)
           if pnl_measured and trades and len(ccys) == 1 else None)
    return JsonResponse({
        "count": len(rows),
        # close_all_preview's keys, but counted by WORLD: `live` is real
        # money only, and a demo row is `demo`, never `live` and never
        # folded into `paper` — whoever reads this JSON (this page, Gandalf,
        # the next page) is told whose money each row is. The three add up
        # to `count`; `worlds` carries the same three for the page script.
        "live": worlds["live"],
        "demo": worlds["demo"],
        "paper": worlds["paper"],
        "pending": pending_n,
        "worlds": worlds,
        "pnl_text": money(pnl, ccys.pop() if len(ccys) == 1 else "",
                          signed=True),
        # All or nothing, as on the execute below: ANY row that needs the
        # PIN arms it for the whole selection.
        "needs_pin": any(requires_pin(t) for t in trades),
        "pnl": pnl,
        # Legacy rows have no trade id and can never be ticked; the key is
        # kept so this answer reads like close-all's.
        "unclosable": 0,
        "ids": [t.pk for t in trades],
        "missing": missing,
        "rows": rows[:12],
        "more": max(0, len(rows) - 12),
    })


@login_required
def close_selected_execute(request):
    """POST {ids, pin} — close exactly the ticked rows that are still open.

    Two differences from close_all_execute, both deliberate.

    ALL OR NOTHING ON THE PIN. Close-all lets a wrong PIN close the paper
    rows and refuse the live ones, which is a half-closed book the operator
    did not ask for. Here, if ANY selected row needs the PIN and it is
    missing or wrong, the whole batch is refused before a single close is
    attempted: one decision, one answer.

    ONLY THE IDS. The rows are re-read at execute time, owner-scoped and
    still open. One that vanished since the preview is reported in
    `missing`, and nothing takes its place — close-all re-reads the BOOK,
    which is right for "close everything" and wrong for "close these".

    Then sequential, exactly like close_all_execute, for the same reason:
    real orders, one broker session, one claim lock at a time. Same
    response shape; `still_open`, `abandoned` and `flat` describe the
    SELECTION, re-read after the loop rather than inferred from it.
    """
    from bot_program.manual_close import execute_close, requires_pin
    from dashboard.position_summary import money

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body, err = _body(request)
    if err:
        return JsonResponse({"error": err}, status=400)
    ids, err = _ids_from(body)
    if err:
        return JsonResponse({"error": err}, status=400)

    trades, missing = _selected_closable(request.user, ids)
    pin_ok = _pin_ok(request, body)
    if not pin_ok and any(requires_pin(t) for t in trades):
        return JsonResponse({
            "error": ("At least one of these positions is held at a broker, "
                      "so your trading PIN is needed — it was missing or "
                      "wrong. Nothing was closed."),
            "pin_required": True,
            "closed": [], "failed": [], "n_closed": 0, "n_failed": 0,
            "still_open": len(trades), "unclosable": 0, "abandoned": 0,
            "flat": False, "missing": missing,
        }, status=403)

    closed, failed = [], []
    for trade in trades:
        try:
            result = execute_close(request.user, trade, pin_ok=pin_ok)
        except Exception as e:  # noqa: BLE001
            logger.exception("[close-selected] close failed for trade %s",
                             trade.pk)
            failed.append({"id": trade.pk, "symbol": trade.symbol,
                           "error": str(e)[:160]})
            continue
        if result.get("error") or result.get("not_found"):
            failed.append({
                "id": trade.pk, "symbol": trade.symbol,
                "error": str(result.get("error") or "no longer open")[:160],
            })
            continue
        closed.append({
            "id": trade.pk,
            "symbol": result.get("symbol", trade.symbol),
            "side": result.get("side", trade.side),
            "qty": str(result.get("qty", trade.qty)),
            "exit": result.get("exit"),
            "pnl": result.get("pnl"),
            "pnl_text": money(result.get("pnl"), _ccy(trade), signed=True),
        })

    # RE-READ the selection, as close-all re-reads the book: "every close
    # returned ok" is not the claim "none of these is open".
    from bot_program.models import AssetBotTrade
    picked = [t.pk for t in trades]
    still_open = AssetBotTrade.objects.filter(
        pk__in=picked, config__user=request.user,
        status__in=("OPEN", "CLOSE_PENDING")).count()
    abandoned = AssetBotTrade.objects.filter(
        pk__in=picked, config__user=request.user, status="ERROR",
        closed_at__isnull=True).count()
    return JsonResponse({
        "closed": closed,
        "failed": failed,
        "n_closed": len(closed),
        "n_failed": len(failed),
        "still_open": still_open,
        "unclosable": 0,
        "abandoned": abandoned,
        "missing": missing,
        # Every selected row that was still there is no longer open. The
        # ids in `missing` were not open when this ran, so they cannot
        # deny it — but they are reported, never silently counted as done.
        "flat": not still_open and not abandoned,
    })
