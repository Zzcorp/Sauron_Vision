"""The Orcs' Celery tasks (spec §10.3). O1a: the census, every 5 minutes
on the fast queue (config/celery.py), behind the `orcs` switch. O1b: the
arms after the row (track_ghosts, every 15 minutes), the grades (hourly)
and the faithfulness audit (weekly), on the SLOW queue until O2's worker
and its `orcs` queue exist (routed by exact name, never a glob: a glob to
`orcs` would strand them unconsumed). Each is behind the switch; a pass
with nothing to do returns `idle`, so the census keeps the component's
row."""
import logging

from celery import shared_task
from django.core.cache import cache

from core.task_gate import guarded_task

from bot_program.orcs.constants import CENSUS_LOCK_TTL_S

logger = logging.getLogger(__name__)

CENSUS_LOCK = "orcs:census"


@shared_task
@guarded_task("orcs")
def orc_census():
    """One census at a time: a pass still running holds the lock and the
    next beat stands aside (idle: the gate keeps the last verdict)."""
    if not cache.add(CENSUS_LOCK, 1, CENSUS_LOCK_TTL_S):
        return {"idle": "another census is running"}
    try:
        from bot_program.orcs import census
        return census.run()
    finally:
        cache.delete(CENSUS_LOCK)


TRACK_LOCK = "orcs:track_ghosts"
TRACK_LOCK_TTL_S = 840


@shared_task
@guarded_task("orcs")
def track_ghosts():
    """Every idea whose row has closed (or was cancelled) with an arm still
    open: the arms' tail on the venue's bars, the multi-ghost's 4h bars
    (ghost.step_bars). While the row is open the tick alone steps its arms
    (one writer per phase), so its idea is not even read here. Idempotent
    and catch-up safe."""
    if not cache.add(TRACK_LOCK, 1, TRACK_LOCK_TTL_S):
        return {"idle": "another pass is running"}
    try:
        from django.utils import timezone

        from bot_program.orcs import ghost
        from bot_program.orcs.constants import LEG_DONE_STATUSES
        from bot_program.orcs.models import Orc
        now = timezone.now()
        orcs = list(Orc.objects.filter(
            tracks__open=True, root_trade__status__in=LEG_DONE_STATUSES)
            .distinct().order_by("pk"))
        if not orcs:
            return {"idle": "no closed row has an open arm"}
        stepped = exited = 0
        for orc in orcs:
            try:
                out = ghost.step_bars(orc, now=now)
                stepped += 1
                exited += len(out.get("exited") or [])
            except Exception as e:  # noqa: BLE001 — one idea never stops it
                logger.warning("[orcs] Orc %s: the arms did not step: %s",
                               orc.pk, e)
        return {"status": "success", "ideas": stepped, "exits": exited}
    finally:
        cache.delete(TRACK_LOCK)


@shared_task
@guarded_task("orcs")
def grade_closed():
    """Every dead idea whose arms all resolved and that has no grade."""
    from django.utils import timezone

    from bot_program.orcs import grading
    from bot_program.orcs.constants import STATE_DEAD
    from bot_program.orcs.models import Orc
    todo = list(Orc.objects.filter(state=STATE_DEAD, grade__isnull=True)
                .select_related("seat").order_by("pk"))
    if not todo:
        return {"idle": "no dead idea waits for its grade"}
    now = timezone.now()
    graded = waiting = 0
    for orc in todo:
        try:
            if grading.grade(orc, now=now) is not None:
                graded += 1
            else:
                waiting += 1
        except Exception as e:  # noqa: BLE001 — one idea never stops it
            logger.warning("[orcs] Orc %s was not graded: %s", orc.pk, e)
    if not graded:
        return {"idle": f"{waiting} idea(s) wait for an arm to resolve"}
    return {"status": "success", "graded": graded, "waiting": waiting}


@shared_task
@guarded_task("orcs")
def shadow_audit(days=7, journal=True):
    """The care ghost against the care's own exits (spec §6.1), weekly."""
    from bot_program.orcs import grading
    lines = grading.shadow_audit(days=days, journal=journal)
    if len(lines) <= 1:
        return {"idle": "no idea died in the window"}
    return {"status": "success", "ideas": len(lines) - 1}
