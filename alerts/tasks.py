"""Celery tasks for alerts and newsletters."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def auto_generate_newsletter(frequency="weekly"):
    """Auto-generate a newsletter with AI."""
    from alerts.models import Newsletter
    from alerts.newsletter_service import generate_newsletter_with_ai

    title = f"{'Weekly' if frequency == 'weekly' else 'Monthly'} Market Report"
    nl = Newsletter.objects.create(
        title=title,
        frequency=frequency,
        send_telegram=True,
        send_email=True,
        status="draft",
    )
    success = generate_newsletter_with_ai(nl, frequency)
    if success:
        logger.info(f"Newsletter '{title}' generated — awaiting admin review")
    return {"status": "generated" if success else "failed", "id": nl.id}


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

    for user in User.objects.filter(is_active=True):
        try:
            digest = generate_morning_digest(user=user)
            send_digest(digest, user=user)
        except Exception as e:
            logger.error(f"Morning digest failed for {user.username}: {e}")

    return {"status": "ok"}


@shared_task
@guarded_task("pipeline_digest")
def send_eod_digest():
    """Scheduled: send end-of-day summary to all active users."""
    from alerts.scheduled_digests import generate_eod_digest, send_digest
    from django.contrib.auth.models import User

    for user in User.objects.filter(is_active=True):
        try:
            digest = generate_eod_digest(user=user)
            send_digest(digest, user=user)
        except Exception as e:
            logger.error(f"EOD digest failed for {user.username}: {e}")

    return {"status": "ok"}
