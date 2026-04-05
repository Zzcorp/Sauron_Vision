"""Celery tasks for technical indicators — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_indicators")
def recalculate_watchlist_indicators():
    """Tier 2: Recalculate indicators for watchlist."""
    logger.info("Recalculating technical indicators for watchlist")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_indicators")
def recalculate_all_indicators():
    """Tier 5: Daily full recalculation."""
    logger.info("Recalculating all technical indicators")
    return {"status": "pending_implementation"}
