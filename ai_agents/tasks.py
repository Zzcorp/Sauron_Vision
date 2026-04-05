"""Celery tasks for AI agents — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("agent_news_analyst")
def process_unanalyzed_news():
    """Tier 1: Process news with AI sentiment analysis."""
    from scraping.models import NewsArticle
    from ai_agents.agents.news_analyst import NewsAnalystAgent

    unprocessed = NewsArticle.objects.filter(ai_processed_at__isnull=True).order_by("-published_at")[:10]
    if not unprocessed:
        return {"status": "no_unprocessed_news"}

    agent = NewsAnalystAgent()
    processed = 0

    for article in unprocessed:
        try:
            result = agent.run(article={
                "title": article.title,
                "source": article.source,
                "published_at": str(article.published_at),
                "content": article.content_summary or article.raw_content[:2000],
            })
            from django.utils import timezone
            article.ai_sentiment_score = result.get("sentiment_score", 0)
            article.ai_urgency = result.get("urgency", "low")
            article.ai_summary = result.get("summary", "")
            article.ai_processed_at = timezone.now()
            article.save()
            processed += 1
        except Exception as e:
            logger.error(f"Failed to process article {article.id}: {e}")

    return {"status": "success", "processed": processed}


@shared_task
@guarded_task("agent_anomaly")
def run_anomaly_detection():
    """Tier 3: AI anomaly detection scan."""
    logger.info("Running AI anomaly detection")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_strategy")
def review_active_strategies():
    """Tier 4: AI review of active strategies."""
    logger.info("AI reviewing active strategies")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_daily_briefing")
def generate_daily_briefing():
    """Tier 5: Generate morning briefing."""
    logger.info("Generating AI daily briefing")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_weekly_review")
def generate_weekly_review():
    """Tier 6: Saturday deep weekly review."""
    logger.info("Generating AI weekly review")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_optimization")
def optimize_strategies():
    """Tier 6: Saturday strategy optimization."""
    logger.info("Running AI strategy optimization")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_monday_plan")
def generate_monday_plan():
    """Tier 6: Sunday evening Monday game plan."""
    logger.info("Generating Monday game plan")
    return {"status": "pending_implementation"}
