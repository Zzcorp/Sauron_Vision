"""Notification creation helpers — call these when events happen."""
import logging
from alerts.models import Notification

logger = logging.getLogger(__name__)


def notify_new_signal(signal):
    """Create in-app notification for a new signal."""
    try:
        Notification.create_for_all(
            notification_type="signal",
            title=f"{signal.direction.upper()} {signal.instrument.symbol}",
            body=f"{signal.title} — Score: {signal.score:.2f}",
            url="/signals/",
        )
    except Exception as e:
        logger.warning(f"Failed to create signal notification: {e}")


def notify_strategy_proposed(strategy):
    """Create notification for a new strategy proposal."""
    try:
        Notification.create_for_all(
            notification_type="strategy",
            title=f"New Strategy: {strategy.name}",
            body=f"Horizon: {strategy.time_horizon} — {strategy.description[:100]}",
            url=f"/strategies/{strategy.id}/",
        )
    except Exception as e:
        logger.warning(f"Failed to create strategy notification: {e}")


def notify_critical_news(article):
    """Create notification for critical news."""
    if article.ai_urgency not in ["critical", "high"]:
        return
    try:
        Notification.create_for_all(
            notification_type="news",
            title=f"Breaking: {article.title[:80]}",
            body=f"Source: {article.source} — Urgency: {article.ai_urgency}",
            url="/news/",
        )
    except Exception as e:
        logger.warning(f"Failed to create news notification: {e}")


def notify_portfolio_alert(user, title, body):
    """Create portfolio alert for a specific user."""
    try:
        Notification.create_for_user(
            user=user,
            notification_type="portfolio",
            title=title,
            body=body,
            url="/portfolio/",
        )
    except Exception as e:
        logger.warning(f"Failed to create portfolio notification: {e}")


def notify_system(title, body, url=""):
    """System-wide notification to all users."""
    try:
        Notification.create_for_all(
            notification_type="system",
            title=title,
            body=body,
            url=url,
        )
    except Exception as e:
        logger.warning(f"Failed to create system notification: {e}")
