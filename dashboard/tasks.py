"""Dashboard-side Celery glue for the async "Run now" buttons.

Every manually initiated task used to run SYNCHRONOUSLY inside the
click's request — an LLM generation held the page (and a worker) for
minutes, then answered with a full reload. The buttons now enqueue the
real beat task and return immediately; these callbacks announce the
outcome on the operator's live socket when the work actually finishes.

The announcement is a Notification row: the post_save hook in
alerts.models already pushes it to the user's /ws/eye/ socket, raising
the 4s banner and moving the bell badge with zero extra plumbing. A
second push carries kind "run_complete" so the page that launched the
job can refresh its result region in place.
"""
from celery import shared_task


def _summarize(result) -> str:
    """One honest line from a task's returned dict."""
    if not isinstance(result, dict):
        return "done"
    if result.get("status") == "skipped":
        return f"skipped — {result.get('reason', 'gated')}"
    if result.get("error"):
        return f"failed — {str(result['error'])[:120]}"
    interesting = {k: v for k, v in result.items()
                   if k not in ("status",) and isinstance(v, (int, float, str))
                   and str(v)}
    if not interesting:
        return "ok"
    parts = [f"{k}={v}" for k, v in list(interesting.items())[:4]]
    return " · ".join(parts)[:180]


def _clear_inflight_lock(job):
    """Free the one-run-per-job dispatch lock, whatever else fails."""
    try:
        from django.core.cache import cache

        from dashboard.run_async import lock_key
        cache.delete(lock_key(job))
    except Exception:  # noqa: BLE001
        pass


@shared_task
def announce_run_complete(result, user_id, job, page_url):
    """Callback (Celery `link=`) — the job finished; tell its operator."""
    from django.contrib.auth.models import User

    _clear_inflight_lock(job)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return {"status": "no_user"}
    summary = _summarize(result)
    ok = not (isinstance(result, dict)
              and (result.get("error") or result.get("ok") is False))

    try:
        from alerts.models import Notification
        n = Notification(
            user=user, notification_type="system",
            title=f"{job} finished" if ok else f"{job} failed",
            body=summary, url=Notification.safe_url(page_url))
        # The run_complete push below draws the visible card — this row
        # is the durable inbox record and the badge mover, not a second
        # banner for the same completion.
        n._banner_silent = True
        n.save()
    except Exception:  # noqa: BLE001 — announcing must never fail the chain
        pass

    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(user, "run_complete", {
            "job": job, "ok": ok, "summary": summary, "url": page_url,
        })
    except Exception:  # noqa: BLE001
        pass
    return {"status": "announced", "job": job}


@shared_task
def announce_run_failed(request, exc, traceback, user_id, job, page_url):
    """Callback (Celery `link_error=`) — the job blew up; say so plainly.

    Signature contract: an errback whose header takes more than one
    argument is invoked INLINE by the worker as errback(request, exc,
    traceback), and those three call args are merged BEFORE the partial
    args stored by .s(user_id, job, page_url) in run_async. A
    (task_id, ...) signature therefore raises TypeError inside the
    worker's own failure handling and no announcement ever fires.
    """
    from django.contrib.auth.models import User

    _clear_inflight_lock(job)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return {"status": "no_user"}
    detail = str(exc)[:140] if exc else "check the worker logs"
    try:
        from alerts.models import Notification
        n = Notification(
            user=user, notification_type="system", title=f"{job} failed",
            body=f"The background run raised an error — {detail}",
            url=Notification.safe_url(page_url))
        n._banner_silent = True   # the run_complete push draws the card
        n.save()
    except Exception:  # noqa: BLE001
        pass
    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(user, "run_complete", {
            "job": job, "ok": False,
            "summary": f"failed — {detail}", "url": page_url,
        })
    except Exception:  # noqa: BLE001
        pass
    return {"status": "announced_failure", "job": job}
