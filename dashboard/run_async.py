"""The async branch every "Run now" endpoint shares.

An XHR click enqueues the REAL beat task and answers 202 immediately —
the button flips to a running state, and completion arrives on the
operator's live socket (banner + bell + in-page refresh) via the
callbacks in dashboard.tasks. A plain form POST — old browsers, no JS —
falls through to the endpoint's original synchronous path, and so does
a dead broker: degrading to today's behavior beats a dead button.

Dispatching through the NAMED shared tasks also restores the
@spend_guard budget checks that the synchronous views quietly bypassed
— a "Generate now" click was un-budgeted AI spend until this existed.
"""
import logging

from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Matches sv-run.js's client-side safety timer: if the announce callbacks
# never clear the lock (worker died mid-run), it frees itself when the
# operator's button does.
LOCK_TTL_SECONDS = 15 * 60


def lock_key(job):
    return "runnow:lock:" + job


def maybe_dispatch_async(request, task, job, page_url, kwargs=None):
    """Return a 202 JsonResponse when the click was XHR and the task got
    enqueued, a 409 when that job is already in flight; None means "run
    the synchronous path instead"."""
    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or ""))
    if not wants_json:
        return None
    if not hasattr(task, "apply_async"):
        # A plain callable (no Celery twin) has no async lane.
        return None
    # One in-flight run per job, platform-wide. The button's disabled
    # state lives per page load — a reload or a second tab re-arms it,
    # and the expensive LLM jobs must not run twice concurrently. The
    # announce callbacks clear the lock the moment the run settles.
    if not cache.add(lock_key(job), "1", timeout=LOCK_TTL_SECONDS):
        return JsonResponse(
            {"ok": False, "job": job, "error": "already running"},
            status=409)
    try:
        from dashboard.tasks import (announce_run_complete,
                                     announce_run_failed)
        async_result = task.apply_async(
            kwargs=kwargs or {},
            link=announce_run_complete.s(request.user.pk, job, page_url),
            link_error=announce_run_failed.s(request.user.pk, job,
                                             page_url),
        )
        return JsonResponse(
            {"ok": True, "job": job, "task_id": async_result.id},
            status=202)
    except Exception as e:  # noqa: BLE001 — broker down: degrade to sync
        cache.delete(lock_key(job))
        logger.warning("[run-now] async dispatch failed for %s: %s — "
                       "falling back to the synchronous path", job, e)
        return None
