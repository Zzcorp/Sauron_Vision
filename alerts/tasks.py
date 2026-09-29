"""Celery tasks for alerts and newsletters."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


# ── The weekly letter (2026-09-29; alerts/newsletter_service.py) ─────────
# auto_generate_newsletter (a "Monthly Market Report" nobody scheduled)
# is gone: the Saturday weekly review is the week's edition, and an
# ad-hoc one is written by generate_newsletter_task, queued by the admin
# page instead of run inside its POST.

@shared_task
def generate_newsletter_task(newsletter_id):
    """Write an ad-hoc edition with the model. The row is "generating"
    until this lands: READY with its content, or "failed" with the
    reason on the admin page. Routed to the ai queue (config/celery.py)."""
    from alerts.models import Newsletter
    from alerts.newsletter_service import generate_newsletter_with_ai

    nl = Newsletter.objects.filter(pk=newsletter_id).first()
    if nl is None or nl.status != "generating":
        return {"status": "skipped",
                "reason": "gone" if nl is None else f"status {nl.status}"}
    ok = generate_newsletter_with_ai(nl)
    return {"status": "generated" if ok else "failed", "id": nl.pk}


@shared_task
def send_newsletter_task(newsletter_id, scheduled=False, requested=None):
    """Send one edition (newsletter_service.send_newsletter): the ledger,
    the batches, the retries. `scheduled`: queued by send_due_newsletters,
    so it sends only an edition still due. `requested`: queued by the
    admin's "Send now", the request it carries (review, 2026-09-29): it
    sends only while the edition still holds that request, so a Cancel or
    a Reschedule made while it waited in the queue stops it. Routed to the
    slow queue (config/celery.py): a thousand SMTP round trips must not
    sit in front of the quote poller. Not behind the newsletter_send
    switch: "Send now" is the operator's own decision; the switch governs
    what goes out on a schedule."""
    from alerts.models import Newsletter
    from alerts.newsletter_service import send_newsletter

    nl = Newsletter.objects.filter(pk=newsletter_id).first()
    if nl is None:
        return {"status": "skipped", "reason": "gone"}
    return send_newsletter(nl, scheduled=scheduled, requested=requested)


@shared_task
@guarded_task("newsletter_send")
def send_due_newsletters():
    """Every 15 min: queue the send of every edition whose time has come
    (READY or APPROVED with scheduled_for passed) and the retries due
    ("sending" with a released or abandoned lease). Light: it queues
    send_newsletter_task on the slow queue and returns. Behind the
    newsletter_send switch, OFF on arrival like everything that sends to
    people: after the deploy, `manage.py component on newsletter_send`."""
    from alerts.newsletter_service import due_newsletter_ids

    due = due_newsletter_ids()
    queued = 0
    for pk in due:
        try:
            send_newsletter_task.delay(pk, scheduled=True)
            queued += 1
        except Exception as e:  # noqa: BLE001 — the next pass tries again
            logger.warning("[newsletter] the send of %s could not be "
                           "queued: %s", pk, e)
    if due and queued < len(due):
        return {"status": "error",
                "error": f"{len(due) - queued} of {len(due)} due editions "
                         f"could not be queued"}
    return {"status": "ok", "due": len(due), "queued": queued}


@shared_task
def dispatch_signal_notifications(signal_id):
    """Dispatch signal notifications to all matching users."""
    from signals.models import Signal
    from alerts.dispatch import dispatch_signal_alert

    try:
        signal = Signal.objects.select_related("instrument").get(id=signal_id)
        dispatch_signal_alert(signal)
        return {"status": "dispatched", "signal": signal.instrument.symbol}
    except Signal.DoesNotExist:
        return {"status": "signal_not_found"}


@shared_task
def check_telegram_commands():
    """Check for incoming Telegram bot commands."""
    from alerts.channels.telegram_alert import process_commands
    processed = process_commands()
    return {"status": "ok", "processed": processed}


@shared_task
@guarded_task("pipeline_alerts")
def check_all_price_alerts():
    """Check all active price alerts against current market prices."""
    from alerts.models import check_price_alerts
    count = check_price_alerts()
    return {"status": "ok", "triggered": count}


@shared_task
@guarded_task("pipeline_digest")
def send_morning_digest():
    """Scheduled: send morning market brief to all active users."""
    from alerts.scheduled_digests import generate_morning_digest, send_digest
    from django.contrib.auth.models import User

    told = set()  # a chat several users share gets one brief (2026-09-26)
    for user in User.objects.filter(is_active=True):
        try:
            digest = generate_morning_digest(user=user)
            send_digest(digest, user=user, chats_done=told)
        except Exception as e:
            logger.error(f"Morning digest failed for {user.username}: {e}")

    return {"status": "ok"}


@shared_task
@guarded_task("pipeline_digest")
def send_eod_digest():
    """Scheduled: send end-of-day summary to all active users."""
    from alerts.scheduled_digests import generate_eod_digest, send_digest
    from django.contrib.auth.models import User

    told = set()  # a chat several users share gets one summary (2026-09-26)
    for user in User.objects.filter(is_active=True):
        try:
            digest = generate_eod_digest(user=user)
            send_digest(digest, user=user, chats_done=told)
        except Exception as e:
            logger.error(f"EOD digest failed for {user.username}: {e}")

    return {"status": "ok"}
