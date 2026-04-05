"""Celery tasks for signal detection — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_signals")
def run_signal_scan():
    # Note: when signals are created, call these to notify users:
    # from alerts.notify import notify_new_signal
    # from alerts.dispatch import dispatch_signal_alert
    # notify_new_signal(signal)  # in-app bell
    # dispatch_signal_alert(signal)  # telegram/email/whatsapp
    """Tier 2: Run signal scan on watchlist."""
    logger.info("Running signal scan on watchlist")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_signals")
def run_full_universe_scan():
    """Tier 5: Daily full universe signal scan."""
    logger.info("Running full universe signal scan")
    return {"status": "pending_implementation"}
