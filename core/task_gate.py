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
    parsed = stored = 0
    seen_counts = False
    for value in [result] + [v for v in result.values() if isinstance(v, dict)]:
        if "parsed" in value or "stored" in value:
            seen_counts = True
            parsed += int(value.get("parsed") or 0)
            stored += int(value.get("stored") or 0)

    if seen_counts and parsed > 0 and stored == 0:
        return "warning", f"parsed {parsed} rows and stored none"
    if seen_counts:
        return "success", f"parsed {parsed}, stored {stored}"

    return "success", declared


def guarded_task(component_key):
    """
    Decorator for Celery tasks. Checks two things:
    1. The master switch is ON
    2. The specific component is ON
    If either is off, the task returns early with a skip message.
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
                if comp:
                    status, msg = judge_result(result)
                    comp.mark_run(success=status == "success", message=msg,
                                  status=status)
                return result
            except Exception as e:
                if comp:
                    comp.mark_run(success=False, message=str(e)[:500])
                raise

        return wrapper
    return decorator
