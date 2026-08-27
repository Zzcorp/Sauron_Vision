"""Move the stop or the target on an open position.

The validation here is the feature. Writing a number onto a row is
trivial; refusing the numbers that would hurt is the part worth having,
and every refusal below came from asking what the operator would have
meant and what the platform would then do:

  * A STOP ON THE WRONG SIDE of the mark closes the position at market
    on the next tick and books it as a stop-out — a loss the thesis
    never took. Same for a target on the wrong side, which fills
    instantly at a worse price than the operator was aiming for.

  * A stop that MOVES AGAINST the position is the one edit that can
    turn a defined loss into an open-ended one. It is allowed, because
    an operator who has read the news and wants more room is making a
    real decision — but it is named in the audit trail as a widening,
    not filed silently beside the tightenings.

  * `initial_stop_loss` IS NOT TOUCHED. Grading measures R against the
    stop the trade opened with, and rewriting that would make risk and
    reward the same quantity: every managed winner would score 1R and
    the track record would stop meaning anything. `bot_grading` freezes
    it for exactly this reason and so does the trailing rule.

  * A BROKER-PROTECTED position's stop rests AT THE BROKER. Moving only
    our copy would leave the database claiming a level the broker has
    never heard of, which is worse than not moving it — the operator
    would believe the position was protected where it is not. So the
    broker leg moves first, and the row follows only if it worked.
"""
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# Statuses whose levels may still be edited. A CLOSE_PENDING row has a
# close working at the broker; moving its stop is an instruction about a
# position that is on its way out, and the two would race.
EDITABLE_STATUSES = ("OPEN",)


def _dec(v):
    if v in (None, "", "null"):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d > 0 else None


def _mark_for(trade):
    """The live mark, or None. Never raises."""
    try:
        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol=trade.symbol).first()
        quote = getattr(inst, "live_quote", None) if inst else None
        return Decimal(str(quote.last)) if quote and quote.last else None
    except Exception:  # noqa: BLE001
        return None


def validate_levels(trade, stop, target, mark=None):
    """Everything wrong with this pair, as a list of reasons.

    Empty means the edit is allowed. Reasons are phrased for the person
    who typed the number, not for a log.
    """
    reasons = []
    long_side = str(getattr(trade, "side", "")).upper() == "BUY"
    mark = mark if mark is not None else _mark_for(trade)

    if stop is not None and mark is not None:
        if long_side and stop >= mark:
            reasons.append(
                f"A stop at {stop} is at or above the current price "
                f"({mark}). On a long it would close the position at "
                f"market on the next tick.")
        if not long_side and stop <= mark:
            reasons.append(
                f"A stop at {stop} is at or below the current price "
                f"({mark}). On a short it would close the position at "
                f"market on the next tick.")

    if target is not None and mark is not None:
        if long_side and target <= mark:
            reasons.append(
                f"A target at {target} is at or below the current price "
                f"({mark}) — it would fill immediately.")
        if not long_side and target >= mark:
            reasons.append(
                f"A target at {target} is at or above the current price "
                f"({mark}) — it would fill immediately.")

    if stop is not None and target is not None:
        if long_side and stop >= target:
            reasons.append("The stop is above the target.")
        if not long_side and stop <= target:
            reasons.append("The stop is below the target.")

    return reasons


def widens_risk(trade, stop):
    """True when this stop gives the position MORE room to lose.

    Not a refusal — an operator who has read the news and wants room is
    making a real decision. But it is the one edit that turns a defined
    loss into a larger one, so it is named rather than filed quietly
    beside the tightenings.
    """
    current = _dec(getattr(trade, "stop_loss", None))
    if stop is None or current is None:
        return False
    return (stop < current if str(trade.side).upper() == "BUY"
            else stop > current)


def adjust_levels(user, trade, stop=None, target=None, clear_target=False):
    """Set the stop and/or target on one open position.

    Returns a dict the view can hand straight back to the browser.
    """
    from django.db import transaction

    stop = _dec(stop)
    target = None if clear_target else _dec(target)

    if stop is None and target is None and not clear_target:
        return {"ok": False, "error": "Nothing to change."}

    with transaction.atomic():
        # Locked and re-read: the tick loop can close this row between
        # the page render and this call, and moving the stop on a
        # position that is already gone writes a level onto history.
        try:
            fresh = (type(trade).objects.select_for_update()
                     .get(pk=trade.pk))
        except type(trade).DoesNotExist:
            return {"ok": False, "error": "No such position.", "gone": True}

        if fresh.status not in EDITABLE_STATUSES:
            return {"ok": False,
                    "error": f"This position is {fresh.status.lower()} — "
                             f"its levels can no longer be changed."}

        mark = _mark_for(fresh)
        problems = validate_levels(fresh, stop, target, mark)
        if problems:
            return {"ok": False, "error": " ".join(problems)}

        widened = widens_risk(fresh, stop)
        protected = bool((fresh.metadata or {}).get("protected"))
        broker_note = ""

        if protected and stop is not None:
            # The broker leg FIRST. Moving only our copy would leave the
            # row claiming a stop the broker never heard of — the
            # operator would believe they were protected at a level that
            # does not exist anywhere but this database.
            moved, broker_note = _move_broker_stop(user, fresh, stop)
            if not moved:
                return {"ok": False,
                        "error": f"The stop rests at the broker and could "
                                 f"not be moved ({broker_note}). Nothing "
                                 f"was changed — the position is still "
                                 f"protected at its old level."}

        fields = []
        if stop is not None:
            fresh.stop_loss = stop
            fields.append("stop_loss")
        if clear_target:
            fresh.take_profit = None
            fields.append("take_profit")
        elif target is not None:
            fresh.take_profit = target
            fields.append("take_profit")

        # The audit trail, on the row. `initial_stop_loss` is NOT touched:
        # grading measures R against the stop the trade opened with.
        meta = dict(fresh.metadata or {})
        moves = list(meta.get("level_edits") or [])
        moves.append({
            "at": _now_iso(),
            "by": getattr(user, "username", "") or "operator",
            "stop": str(stop) if stop is not None else None,
            "target": (None if clear_target
                       else (str(target) if target is not None else None)),
            "widened": bool(widened),
            "broker": broker_note or ("in-place" if protected else "bot"),
        })
        meta["level_edits"] = moves[-20:]
        fresh.metadata = meta
        fields.append("metadata")
        fresh.save(update_fields=fields)

    if widened:
        logger.warning("[levels] %s widened the stop on #%s to %s — the "
                       "position can now lose more than it could",
                       getattr(user, "username", "?"), fresh.pk, stop)
    else:
        logger.info("[levels] #%s stop=%s target=%s by %s", fresh.pk,
                    stop, target, getattr(user, "username", "?"))

    return {"ok": True, "widened": bool(widened), "protected": protected,
            "broker": broker_note,
            "stop": str(fresh.stop_loss) if fresh.stop_loss else None,
            "target": str(fresh.take_profit) if fresh.take_profit else None}


def _now_iso():
    from django.utils import timezone
    return timezone.now().isoformat()


def _move_broker_stop(user, trade, stop):
    """Move the resting stop leg. Returns (moved, note)."""
    try:
        from bot_program.engine.broker_router import client_for_symbol
        client = client_for_symbol(user, trade.symbol, trade.config)
    except Exception as e:  # noqa: BLE001
        return False, f"broker unreachable: {e}"

    mover = getattr(client, "modify_protective", None)
    if not callable(mover):
        # Named rather than silently falling back to a row-only write:
        # this broker cannot move a resting order, and pretending
        # otherwise is how a row starts disagreeing with the venue.
        return False, ("this broker cannot modify a resting order yet — "
                       "close and re-open to change a broker-held stop")

    ids = (trade.metadata or {}).get("protective_order_ids") or []
    if not ids:
        return False, "the row records no resting protective orders"

    last = "no leg matched"
    for oid in ids:
        try:
            res = mover(str(oid), float(stop))
        except Exception as e:  # noqa: BLE001
            last = str(e)
            continue
        if res and res.get("ok"):
            return True, f"leg {oid} moved to {res.get('price')}"
        last = (res or {}).get("reason") or last
    return False, last
