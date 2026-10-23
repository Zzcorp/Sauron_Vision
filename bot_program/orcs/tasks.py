"""The Orcs' Celery tasks (spec §10.3). O1a: the census, every 5 minutes
on the fast queue (config/celery.py), behind the `orcs` switch. O1b: the
arms after the row (track_ghosts, every 15 minutes), the grades (hourly)
and the faithfulness audit (weekly), on the SLOW queue until O2's worker
and its `orcs` queue exist (routed by exact name, never a glob: a glob to
`orcs` would strand them unconsumed). O1c (§5.2a, §7.5.3, §10.7): the day
roll (MK0 per model family, the day's weather, the calendar's actuals),
the session close (each closed session's MK block per model family) and
the hourly read (IN-slow, the class's hourly terms, the level-break and
sweep drums), on the slow queue by exact name, on UTC crontabs that cover
both sides of the clock change: every pass is idempotent. Each is behind the switch; a
pass with nothing to do returns `idle`, so the census keeps the
component's row."""
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


# ── O1c: the dossier's beats ─────────────────────────────────────────────

DAY_ROLL_LOCK = "orcs:day_roll"
SESSION_LOCK = "orcs:session_close"
HOURLY_LOCK = "orcs:hourly"
O1C_LOCK_TTL_S = 1500


def _living_classes():
    """[(user, class)] with a living Orc."""
    from bot_program.orcs.constants import STATE_DEAD
    from bot_program.orcs.models import Orc
    seen, out = set(), []
    for orc in (Orc.objects.exclude(state=STATE_DEAD)
                .select_related("user").order_by("pk")):
        key = (orc.user_id, orc.asset_class)
        if key not in seen:
            seen.add(key)
            out.append((orc.user, orc.asset_class, orc))
    return out


@shared_task
@guarded_task("orcs")
def orc_day_roll():
    """At the trading-day roll (17:00 New York, both clocks): MK0 for every
    model family the ladder routes to, the day's weather per (user, class)
    with a living Orc, and the calendar's actuals measured once a day."""
    if not cache.add(DAY_ROLL_LOCK, 1, O1C_LOCK_TTL_S):
        return {"idle": "another day roll is running"}
    try:
        from django.utils import timezone

        from bot_program.orcs import dossier_market, sources, weather
        from bot_program.orcs.constants import MK_FAMILIES
        from bot_program.orcs.models import OrcDayBaseline, OrcSetting
        from bot_program.orcs.sessions import trading_day
        now = timezone.now()
        td = trading_day(now)
        built = 0
        for model in MK_FAMILIES:
            try:
                if dossier_market.mk0(td, model, now=now, build=False) \
                        is None:
                    dossier_market.mk0(td, model, now=now)
                    built += 1
            except Exception as e:  # noqa: BLE001 — one model never stops
                logger.warning("[orcs] MK0 %s (%s) not built: %s", td,
                               model, e)
        days = 0
        for user, cls, _orc in _living_classes():
            try:
                had = OrcDayBaseline.objects.filter(
                    user=user, asset_class=cls, trading_day=td).exists()
                weather.current(user, cls, now)
                days += 0 if had else 1
            except Exception as e:  # noqa: BLE001
                logger.warning("[orcs] weather %s/%s not read: %s",
                               user.pk, cls, e)
        stored = OrcSetting.get("calendar_actuals") or {}
        recorded = False
        if stored.get("trading_day") != td.isoformat():
            m = sources.actuals_measurement(14, now)
            m["trading_day"] = td.isoformat()
            OrcSetting.objects.update_or_create(
                key="calendar_actuals", defaults={"value": m,
                                                  "updated_by": "day_roll"})
            recorded = True
        if not built and not days and not recorded:
            return {"idle": f"the day {td.isoformat()} is already rolled"}
        return {"status": "success", "mk0": built, "weather": days,
                "actuals": recorded}
    finally:
        cache.delete(DAY_ROLL_LOCK)


@shared_task
@guarded_task("orcs")
def orc_session_close():
    """After each session's close: its MK block per model family, once (a
    closed session never changes). Catch-up safe: every closed session of
    the trading day still missing is built."""
    if not cache.add(SESSION_LOCK, 1, O1C_LOCK_TTL_S):
        return {"idle": "another session close is running"}
    try:
        from django.utils import timezone

        from bot_program.orcs import dossier_market
        from bot_program.orcs.constants import MK_FAMILIES
        from bot_program.orcs.sessions import closed_sessions, trading_day
        now = timezone.now()
        td = trading_day(now)
        built = 0
        for model in MK_FAMILIES:
            for name in closed_sessions(now):
                try:
                    if dossier_market.mk_session(td, name, model, now=now,
                                                 build=False) is None:
                        dossier_market.mk_session(td, name, model, now=now)
                        built += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("[orcs] MK %s %s (%s) not built: %s", td,
                                   name, model, e)
        if not built:
            return {"idle": "every closed session is written"}
        return {"status": "success", "built": built}
    finally:
        cache.delete(SESSION_LOCK)


@shared_task
@guarded_task("orcs")
def orc_hourly():
    """Hourly: IN-slow for every held symbol and model (so a wake finds it
    built), the class's hourly complexity terms and the upward re-run of
    the day's weather, and the market's level-break and sweep drums."""
    if not cache.add(HOURLY_LOCK, 1, O1C_LOCK_TTL_S):
        return {"idle": "another hourly read is running"}
    try:
        from django.utils import timezone

        from bot_program.orcs import dossier_instrument, drum_bus, weather
        from bot_program.orcs.constants import MK_FAMILIES
        now = timezone.now()
        pairs = _living_classes()
        if not pairs:
            return {"idle": "no living Orc"}
        from bot_program.orcs.constants import STATE_DEAD
        from bot_program.orcs.models import Orc
        symbols = sorted(set(Orc.objects.exclude(state=STATE_DEAD)
                             .values_list("symbol", "asset_class")))
        blocks = 0
        cache_ = {}
        for symbol, cls in symbols:
            for model in MK_FAMILIES:
                try:
                    dossier_instrument.in_slow(symbol, cls, model, now=now,
                                               cache=cache_)
                    blocks += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("[orcs] IN-slow %s (%s) not built: %s",
                                   symbol, model, e)
        hours = 0
        for user, cls, _orc in pairs:
            try:
                weather.hourly(user, cls, now)
                hours += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("[orcs] the hourly read %s/%s failed: %s",
                               user.pk, cls, e)
        drums = 0
        try:
            drums = drum_bus.hourly_market(now)
        except Exception as e:  # noqa: BLE001
            logger.warning("[orcs] the hourly drums failed: %s", e)
        return {"status": "success", "in_slow": blocks, "classes": hours,
                "drums": drums}
    finally:
        cache.delete(HOURLY_LOCK)
