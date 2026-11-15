"""THE FENCE AROUND THE HARM COUNTERS (the eToro feed spec, F1, §6.2;
2026-11-07; the counters are bot_program/feed_harms.py).

A money path reaches a counter only through `count(where, hook, ...)`, in
one line: the counter's module is looked up and the hook called inside a
try that catches everything — the import included — so the path's answer,
its timing and its commit are the same whatever the counter does. A
failure is told once: one WARNING per (where, what, kind of failure) and
process, DEBUG after, with the failure's type only, never its message (a
message may carry a price or an id). The counters' own fences tell their
failures here too, so one rule and one logger say everything about them.

Standard library only at module level: the fence always loads, and
importing it imports nothing of Django or of the counters.
"""
import logging
import threading

#: The counters' logger: one name to read or silence for all of them.
logger = logging.getLogger("bot_program.feed_harms")

_TOLD: set = set()
_TOLD_LOCK = threading.Lock()


def told(where, what, error) -> None:
    """Say that `what` failed on `where`: WARNING the first time this
    (where, what, kind of failure) is seen in this process, DEBUG after.
    Never raises."""
    try:
        key = (str(where), str(what), type(error).__name__)
        with _TOLD_LOCK:
            first = key not in _TOLD
            _TOLD.add(key)
        logger.log(logging.WARNING if first else logging.DEBUG,
                   "[feed harms] %s: %s failed (%s); nothing counted, and "
                   "nothing else touched", *key)
    except Exception:  # noqa: BLE001 — the fence's own word, never the path
        pass


def count(where, hook, *args, **kwargs):
    """`feed_harms.<hook>(*args, **kwargs)`'s answer, or None when anything
    fails (told once). Never raises."""
    try:
        from bot_program import feed_harms
        return getattr(feed_harms, hook)(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 — a count, never the money path
        told(where, hook, e)
        return None


def forget() -> None:
    """Forget which failures were told (tests)."""
    with _TOLD_LOCK:
        _TOLD.clear()
