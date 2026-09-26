"""Task gate — check if a component is enabled before executing."""
import logging
from functools import wraps
from core.platform_control import is_component_enabled, get_component

logger = logging.getLogger(__name__)


def judge_result(result):
    """Decide what a task's return value actually says about its health.

    The gate used to call mark_run(success=True) for any return that did not
    raise. Every scraper task returns a hardcoded {"status": "success"} and
    swallows its own exceptions, so no scraper could ever mark itself
    unhealthy. Measured on the live database: six scraper components at
    last_status='success' with zero rows between them — including the earnings
    calendar, whose empty table silently disabled the bot's earnings blackout.

    So the gate now reads the numbers rather than the adjective:

      parsed > 0 and stored == 0   the source answered and we kept none of it.
                                   This is the failure that used to be
                                   invisible, and it is the important one.
      skipped                      a credential or precondition is missing.
                                   Not a crash, but not a working integration.
      status error/failed          the task said so itself.

    Anything with no numbers to check keeps the benefit of the doubt, so this
    cannot turn unrelated healthy tasks red.
    """
    if not isinstance(result, dict):
        return "success", "ok"

    declared = str(result.get("status", "ok")).lower()
    if declared in ("error", "failed", "failure"):
        return "error", str(result.get("error") or result.get("message") or declared)[:500]
    if declared == "skipped":
        return "success", str(result.get("reason", "skipped"))[:500]

    if result.get("skipped"):
        return "warning", f"not configured: {result['skipped']}"

    # Sum across sub-results too, so a task reporting several sources
    # ({"rss": {...}, "api": {...}}) is judged on the whole run.
    #
    # WORK_KEYS is not just "parsed"/"stored": the market-data tasks predate
    # that convention and report a single "fetched" count, so for a while this
    # function looked at them, found neither key, and waved them through — a
    # quote poller that wrote zero rows stayed permanently green, which is the
    # exact failure the function was written to catch, one module over.
    WORK_KEYS = ("parsed", "attempted")
    DONE_KEYS = ("stored", "written", "saved", "fetched", "observations_saved",
                 "bars_saved", "articles")

    attempted = done = 0
    seen_counts = False
    for value in [result] + [v for v in result.values() if isinstance(v, dict)]:
        keys = set(value)
        if not (keys & set(WORK_KEYS) or keys & set(DONE_KEYS)):
            continue
        seen_counts = True
        attempted += sum(int(value.get(k) or 0) for k in WORK_KEYS)
        done += sum(int(value.get(k) or 0) for k in DONE_KEYS)

    if not seen_counts:
        return "success", declared

    if attempted > 0 and done == 0:
        return "warning", f"handled {attempted} rows and stored none"
    if done == 0:
        # Nothing attempted and nothing produced. For a poller whose whole job
        # is to produce rows every run, that is not a healthy result — it is
        # how six scrapers held a clean record while their tables stayed empty.
        return "warning", "ran and produced nothing"
    return "success", (f"handled {attempted}, stored {done}" if attempted
                       else f"stored {done}")


def guarded_task(component_key):
    """
    Decorator for Celery tasks. Checks two things:
    1. The master switch is ON
    2. The specific component is ON
    If either is off, the task returns early with a skip message.

    AN IDLE PASS WRITES NOTHING (2026-09-26). A result carrying a truthy
    `idle` — the reason in words: "no IBKR account to read", "no live Saxo
    session" — says this pass had nothing to do, and the gate does not
    call mark_run for it: the row keeps whatever the last real run wrote.
    One row can be written by several tasks. broker_account_sync is the
    switch of three walks (IBKR, Saxo, eToro), each every fifteen minutes,
    and the two with nothing to read returned attempted 0 / stored 0,
    which judge_result rightly calls "ran and produced nothing". On the
    shared row that verdict overwrote eToro's success — the daily digest
    reported a healthy sync as a warning — and, worse, it overwrote an
    eToro ERROR minutes after it landed, hiding a real fault behind a walk
    that had nothing to read. `idle` is for a pass that is not a run of
    the component at all. A task that is the only writer of its row must
    not return it: a pass that does no work there is exactly the "ran and
    produced nothing" this gate exists to report.

    The component key is stamped on the wrapper (`component_key`) — the
    function celery's task.run and task.__wrapped__ are — so the digest
    reads which component each beat entry writes, and so how often that
    row should move, off the schedule itself, with no second table to keep
    in step (core.component_digest.beat_periods).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check master switch
            if not is_component_enabled("platform_master"):
                logger.info(f"[GATE] Platform master switch OFF — skipping {component_key}")
                return {"status": "skipped", "reason": "platform_disabled"}

            # Check component switch
            if not is_component_enabled(component_key):
                logger.info(f"[GATE] Component {component_key} disabled — skipping")
                return {"status": "skipped", "reason": f"{component_key}_disabled"}

            # Execute
            comp = get_component(component_key)
            try:
                result = func(*args, **kwargs)
                if comp and isinstance(result, dict) and result.get("idle"):
                    # Not a run of this component (see the docstring): the
                    # row keeps the verdict of the last pass that was one.
                    logger.debug("[GATE] %s idle (%s): the row keeps its "
                                 "last verdict", component_key,
                                 result.get("idle"))
                elif comp:
                    status, msg = judge_result(result)
                    comp.mark_run(success=status == "success", message=msg,
                                  status=status)
                return result
            except Exception as e:
                if comp:
                    comp.mark_run(success=False, message=str(e)[:500])
                raise

        # Read by core.component_digest.beat_periods (see the docstring).
        wrapper.component_key = component_key
        return wrapper
    return decorator
