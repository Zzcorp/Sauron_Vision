"""Task gate — check if a component is enabled before executing."""
import logging
from functools import wraps
from core.platform_control import is_component_enabled, get_component

logger = logging.getLogger(__name__)


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
                    msg = str(result.get("status", "ok")) if isinstance(result, dict) else "ok"
                    comp.mark_run(success=True, message=msg)
                return result
            except Exception as e:
                if comp:
                    comp.mark_run(success=False, message=str(e)[:500])
                raise

        return wrapper
    return decorator
