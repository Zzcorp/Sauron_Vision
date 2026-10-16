"""The Orcs' Celery tasks (spec §10.3). O1a: the census, every 5 minutes
on the fast queue (config/celery.py), behind the `orcs` switch. O1b adds
the ghost and grade tasks on the slow queue until O2's worker exists."""
from celery import shared_task
from django.core.cache import cache

from core.task_gate import guarded_task

from bot_program.orcs.constants import CENSUS_LOCK_TTL_S

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
