"""The dead man's switch: a heartbeat an OUTSIDE watcher expects (2026-09-30).

Everything that raises an alarm on this platform lives on the box: the
alarm bot, the Eye, Morgul, the digest. When the box itself stops (the
hosting month ran out, the disk filled, Docker or beat died), they stop
with it, and their silence reads exactly like "nothing is wrong". That is
how the VPS went dark on 2026-09-30 with nobody told: a dead box cannot
say it is dead.

So the box says it is ALIVE, every five minutes, to a service that is not
on the box (healthchecks.io, or anything speaking its protocol). The
service expects the ping; when none arrives within the period plus the
grace, the SERVICE raises the alarm: e-mail, Telegram, SMS, its phone app.

  - One ping after each bot tick (bot_program.tasks.tick_all_asset_bots),
    OUTSIDE the task gate. So a ping proves the box, beat, the default
    worker and the database all answered, and a paused platform still
    pings: the pause is the alarm bot's to report, not a dead box.
  - A tick that raises pings /fail with the exception's TYPE only, never
    its text (a message can carry an amount or a symbol), and the
    exception goes on to Celery as before.
  - No DEAD_MAN_SWITCH_URL, no ping: off until the operator sets it.
  - https only; five seconds at most; every failure is logged and
    swallowed. The watcher sits beside the tick, never in it.
  - The URL is never logged: anyone holding it can ping in the box's name.

Setup: deploy/RUNBOOK.md, "When the box itself goes silent".
"""
from __future__ import annotations

import logging
from functools import wraps
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

#: The setting (and .env key) that holds the ping URL.
SETTING = "DEAD_MAN_SWITCH_URL"
#: Seconds. A ping that cannot land in five never delays a tick for longer.
TIMEOUT_S = 5
#: The body carries a status word, never a figure; bounded all the same.
MAX_BODY = 200


def ping_url() -> str:
    """The configured URL, read at call time, trailing slash dropped; "" off."""
    from django.conf import settings
    return str(getattr(settings, SETTING, "") or "").strip().rstrip("/")


def where() -> str:
    """The URL's host alone, for a line an operator reads: never the path,
    which is the secret."""
    url = ping_url()
    return urlsplit(url).hostname or "" if url else ""


def ping(ok: bool = True, detail: str = "") -> bool:
    """One heartbeat. True when the watcher accepted it; False when the
    switch is off, the URL is refused, or the ping did not land. Never
    raises."""
    url = ping_url()
    if not url:
        return False
    if urlsplit(url).scheme != "https":
        logger.warning("[dead man's switch] %s is not an https URL; no ping "
                       "sent (fix it in .env)", SETTING)
        return False
    target = url if ok else f"{url}/fail"
    try:
        r = requests.post(target, data=(detail or "")[:MAX_BODY].encode(),
                          timeout=TIMEOUT_S,
                          headers={"User-Agent": "SauronVision dead-man-switch"})
    except Exception as e:  # noqa: BLE001 — the watcher never breaks the tick
        logger.warning("[dead man's switch] ping to %s did not land (%s)",
                       where(), type(e).__name__)
        return False
    if not 200 <= r.status_code < 300:
        logger.warning("[dead man's switch] %s answered HTTP %s", where(),
                       r.status_code)
        return False
    return True


def _status_word(result) -> str:
    """What the tick's result says, in a word or two and no figure."""
    if isinstance(result, dict) and result.get("status") == "skipped":
        return f"tick skipped ({str(result.get('reason') or '')[:60]})"
    return "tick ran"


def heartbeat(func):
    """Wrap a beat task: ping after it returns, ping /fail if it raises.

    Goes OUTSIDE @guarded_task, so a gate skip still pings. functools.wraps
    carries the gate's `component_key` up to the Celery task, where
    core.component_digest reads it."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            ping(ok=False, detail=f"tick raised {type(e).__name__}")
            raise
        ping(ok=True, detail=_status_word(result))
        return result
    return wrapper
