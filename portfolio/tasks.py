"""Celery tasks for portfolio — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_exposure")
def recalculate_exposure():
    """Tier 3: Recalculate portfolio exposure."""
    logger.info("Recalculating portfolio exposure")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_snapshot")
def create_daily_snapshot():
    """Tier 5: Create end-of-day snapshot."""
    logger.info("Creating daily portfolio snapshot")
    return {"status": "pending_implementation"}
