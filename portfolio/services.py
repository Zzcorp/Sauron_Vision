"""Portfolio services — user-aware."""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def get_or_create_default_portfolio(user=None):
    """Get or create portfolio for a specific user."""
    from .models import Portfolio

    config = settings.PORTFOLIO_CONFIG

    if user and user.is_authenticated:
        portfolio, created = Portfolio.objects.get_or_create(
            name=f"{user.username}_main",
            defaults={
                "initial_capital": config["initial_capital"],
                "current_value": config["initial_capital"],
                "cash_available": config["initial_capital"],
                "currency": config["base_currency"],
            },
        )
    else:
        portfolio, created = Portfolio.objects.get_or_create(
            name="Main",
            defaults={
                "initial_capital": config["initial_capital"],
                "current_value": config["initial_capital"],
                "cash_available": config["initial_capital"],
                "currency": config["base_currency"],
            },
        )

    if created:
        logger.info(f"Created portfolio: {portfolio.name}")
    return portfolio
