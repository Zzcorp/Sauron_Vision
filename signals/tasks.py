"""Celery tasks for signal detection — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_signals")
def run_signal_scan():
    """Tier 2: Run signal scan on watchlist."""
    logger.info("Running signal scan on watchlist")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_signals")
def run_full_universe_scan():
    """Tier 5: Daily full universe signal scan."""
    logger.info("Running full universe signal scan")
    return {"status": "pending_implementation"}
