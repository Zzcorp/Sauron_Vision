"""The Orcs' place in the tick (spec §1.3, O1): right after the position
care (AssetBot.manage_positions, after `_care(self, trade, price,
client)`), each Orc reads what the care just did and journals it as code
facts. It never moves a stop, sends an order or calls a model, and it
never raises: a failure here leaves the row to the rest of the tick
exactly as before.

A row with no stamp (no Orc) costs no query at all; the switch is read
once per pass (the tick's per-pass cache). A row with an Orc costs a
bounded handful on a quiet tick: the Orc, the bars its predicates read
(once per symbol and pass), its arms and their one bulk update. Later
commits append their steps to TICK_STEPS (O1b: the thesis predicates, then
the arms' step; O1c: wake detection).
"""
import logging

from bot_program.orcs import facts
from bot_program.orcs.constants import STATE_DEAD
from bot_program.orcs.switches import orcs_on

logger = logging.getLogger(__name__)


def _observe_tick(bot, trade, price, cared, orc):
    return facts.observe_tick(bot, trade, price, cared, orc)


def _now_of(trade):
    from django.utils import timezone
    tick = getattr(trade, "_care_tick", None)
    return (tick.get("now") if isinstance(tick, dict) else None) \
        or timezone.now()


def _check_predicates(bot, trade, price, cared, orc):
    """O1b: the thesis's predicates, facts on their transitions only."""
    orc._orc_results = None
    if orc.state == STATE_DEAD:
        return None
    from bot_program.orcs import predicates
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    orc._orc_results = predicates.check(
        orc, trade, now=_now_of(trade), mfe_r=care.get("mfe_r"), mark=price,
        cache=getattr(bot, "_tick_broker_cache", None))
    return orc._orc_results


def _step_ghosts(bot, trade, price, cared, orc):
    """O1b: every arm of the idea, one tick, on its own state."""
    from bot_program.orcs import ghost
    return ghost.step_tick(orc, trade, bot=bot, price=price, cared=cared,
                           results=getattr(orc, "_orc_results", None))


#: Each step is fenced on its own: one failing never stops the next.
TICK_STEPS = (_observe_tick, _check_predicates, _step_ghosts)


def after_care(bot, trade, price, cared="") -> None:
    try:
        meta = trade.metadata
        if not isinstance(meta, dict):
            return None
        stamp = meta.get("orc")
        if not isinstance(stamp, dict) or not stamp.get("idea"):
            return None
        if not orcs_on(getattr(bot, "_tick_broker_cache", None)):
            return None
        from bot_program.orcs.models import Orc
        orc = Orc.objects.filter(pk=stamp["idea"]).first()
        if orc is None:
            return None
        if orc.state == STATE_DEAD and not cared:
            return None
        for step in TICK_STEPS:
            try:
                step(bot, trade, price, cared, orc)
            except Exception as e:  # noqa: BLE001 — one step never stops one
                logger.warning("[orcs] Orc %s: %s failed: %s", orc.pk,
                               getattr(step, "__name__", "a step"), e)
    except Exception as e:  # noqa: BLE001 — the Orcs never stop the tick
        logger.warning("[orcs] #%s: not observed: %s",
                       getattr(trade, "pk", "?"), e)
    return None
