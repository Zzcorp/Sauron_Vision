"""Celery tasks for strategies — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("agent_strategy")
def suggest_rebalancing():
    """Tier 6: Weekly portfolio rebalancing suggestions."""
    logger.info("Generating rebalancing suggestions")
    return {"status": "pending_implementation"}
