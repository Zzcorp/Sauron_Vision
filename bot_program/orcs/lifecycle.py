"""DEATH (spec §1.2): an idea ends when its last leg closes, whatever path
closed it. A row reaches CLOSED through the tick's _close_trade, the
reconcile (every eToro venue stop or target, and a hand close in the app),
the CLOSE_PENDING drain and the kill switch, so the hook is tied to none:

  1. a post_save receiver on AssetBotTrade: a stamped row (no query for an
     unstamped one) saved CANCELED, or CLOSED with its outcome set — after
     the grade, so the fact carries the booked R — runs on_leg_closed once
     the save commits;
  2. the census sweep (every 5 min): any live Orc whose legs are all
     closed, which catches a queryset update (no signal);
  3. the kill switch calls kill_all: every idea in scope dead, no window.

In O1 every idea ends dead: a re-entry window needs an L3 seat and the
re-entry path, which arrive with O5. Only Orc tables are written.
"""
import logging
from functools import partial

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from bot_program.orcs.constants import (LEG_DONE_STATUSES, MAX_REENTRIES,
                                        STATE_DEAD, STATE_REENTRY)

logger = logging.getLogger(__name__)

#: The seat level from which an idea may re-enter (§3.1, I7).
REENTRY_MIN_LEVEL = 3


@receiver(post_save, sender="bot_program.AssetBotTrade",
          dispatch_uid="orcs_leg_closed")
def _leg_saved(sender, instance, created=False, **kwargs):
    """Never raises; no query for a row without the stamp."""
    try:
        meta = instance.metadata
        if not isinstance(meta, dict):
            return
        stamp = meta.get("orc")
        if not isinstance(stamp, dict) or not stamp.get("idea"):
            return
        status = instance.status
        if not (status == "CANCELED"
                or (status == "CLOSED" and instance.outcome)):
            return
        from bot_program.orcs.switches import orcs_on
        if not orcs_on():
            return
        transaction.on_commit(partial(_closed_quietly, instance.pk),
                              robust=True)
    except Exception as e:  # noqa: BLE001 — the Orcs never stop a save
        logger.warning("[orcs] close of #%s not registered: %s",
                       getattr(instance, "pk", "?"), e)


def _closed_quietly(trade_id):
    try:
        on_leg_closed(trade_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[orcs] close of #%s not journaled: %s", trade_id, e)


def _reentry_open(orc, trade) -> tuple:
    """(open, why). Closed in O1 for every idea, with its reason."""
    if orc.killed:
        return False, "the kill switch ended it"
    if orc.manual:
        return False, "a hand idea never re-enters on its own"
    if orc.reentries_used >= MAX_REENTRIES:
        return False, "its one re-entry is used"
    level = getattr(orc.seat, "level", 0) or 0
    if level < REENTRY_MIN_LEVEL:
        return False, f"its seat is at L{level}; a re-entry needs L3"
    return False, "the re-entry arrives with O5"


def on_leg_closed(trade_id, *, now=None):
    """Journal the close of one leg (once), and end the idea when its last
    leg is closed: `dead`, died_at the last leg's close time. A dead Orc
    still hears the close of its legs. Idempotent. The Orc, or None.

    O1c (§4.7): once the close is journaled and its block has committed, a
    leg its stop closed publishes a stop_hit drum
    (drum_bus.on_close_quietly, never raises), called here rather than
    through a second on_commit, so a closing save still queues one
    callback."""
    from bot_program.orcs.models import OrcLeg
    leg = OrcLeg.objects.filter(trade_id=trade_id).only("orc_id").first()
    if leg is None:
        return None
    orc, journaled = _close_leg(leg, trade_id, now)
    if journaled:
        from bot_program.orcs import drum_bus
        drum_bus.on_close_quietly(orc.pk, trade_id)
    return orc


def _close_leg(leg, trade_id, now) -> tuple:
    """(orc, journaled): the close fact (once) and the idea's end."""
    from bot_program.models import AssetBotTrade
    from bot_program.orcs import facts, journal
    from bot_program.orcs.models import Orc, OrcLeg
    journaled = False
    with transaction.atomic():
        # the Orc's row alone is locked (never its shared seat)
        orc = Orc.objects.select_for_update().get(pk=leg.orc_id)
        trade = AssetBotTrade.objects.get(pk=trade_id)
        if trade.status not in LEG_DONE_STATUSES:
            return orc, False
        closed = list((orc.seen or {}).get("closed_legs") or [])
        if trade.pk not in closed:
            hand = facts.is_hand_close(trade)
            fields = {"hand_touched": True} if hand and not orc.hand_touched \
                else None
            journal.append(orc, "fact", facts.close_line(orc, trade),
                           author="reconcile" if "reconciled-orphan" in (
                               trade.reason or "") else "code",
                           body={"leg": trade.pk, "status": trade.status,
                                 "outcome": trade.outcome or "",
                                 "exit": facts._f(trade.exit_price),
                                 "r": facts._f(trade.realized_r),
                                 "how": facts.close_how(orc, trade),
                                 "hand": hand},
                           fact=True, remember={"closed_legs": closed + [
                               trade.pk]}, fields=fields)
            journaled = True
        if orc.state == STATE_DEAD:
            return orc, journaled
        legs = list(OrcLeg.objects.select_related("trade").filter(orc=orc))
        if not legs or not all(lg.trade.status in LEG_DONE_STATUSES
                               for lg in legs):
            return orc, journaled
        ok, why = _reentry_open(orc, trade)
        if ok:
            journal.append(orc, "fact", "The last leg closed; the re-entry "
                           "window is open.", fact=True,
                           fields={"state": STATE_REENTRY})
            return orc, journaled
        died = max((lg.trade.closed_at for lg in legs
                    if lg.trade.closed_at is not None),
                   default=None) or now or timezone.now()
        journal.append(orc, "fact", f"This idea is over: its last leg "
                       f"closed. No re-entry window: {why}.",
                       body={"why": why}, fact=True,
                       fields={"state": STATE_DEAD, "died_at": died})
    return orc, journaled


def kill_all(user=None, *, reason="", now=None) -> int:
    """The kill switch ends every idea in scope: dead, killed, no re-entry
    window. It ignores the switch on purpose: an idea must never outlive a
    flatten. One SELECT when there is nothing to end. Returns the count."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import Orc
    now = now or timezone.now()
    qs = Orc.objects.exclude(state=STATE_DEAD)
    if user is not None:
        qs = qs.filter(user=user)
    n = 0
    for orc in list(qs):
        try:
            with transaction.atomic():
                locked = Orc.objects.select_for_update().get(pk=orc.pk)
                if locked.state == STATE_DEAD:
                    continue
                journal.append(locked, "fact", "The kill switch ended this "
                               "idea: no re-entry window.",
                               body={"reason": str(reason or "")[:120]},
                               fact=True,
                               fields={"state": STATE_DEAD, "killed": True,
                                       "died_at": now})
            n += 1
        except Exception as e:  # noqa: BLE001 — one idea never stops it
            logger.warning("[orcs] Orc %s was not ended by the kill "
                           "switch: %s", orc.pk, e)
    return n


def sweep(now=None) -> int:
    """Every live Orc whose legs are all closed goes through on_leg_closed
    (the closes no receiver saw: a queryset update, a switch that was
    OFF). Returns the ideas it ended."""
    from bot_program.orcs.models import Orc
    died = 0
    live = (Orc.objects.exclude(state=STATE_DEAD)
            .prefetch_related("legs__trade"))
    for orc in live:
        try:
            legs = list(orc.legs.all())
            if not legs or not all(lg.trade.status in LEG_DONE_STATUSES
                                   for lg in legs):
                continue
            said = set((orc.seen or {}).get("closed_legs") or [])
            order = sorted(legs, key=lambda lg: (lg.trade.closed_at is None,
                                                 lg.trade.closed_at, lg.seq))
            todo = [lg for lg in order if lg.trade_id not in said] or order[-1:]
            out = None
            for lg in todo:
                out = on_leg_closed(lg.trade_id, now=now)
            if out is not None and out.state == STATE_DEAD:
                died += 1
        except Exception as e:  # noqa: BLE001 — one idea never stops it
            logger.warning("[orcs] sweep of Orc %s failed: %s", orc.pk, e)
    return died
