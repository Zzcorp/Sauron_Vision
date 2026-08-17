"""Portfolio services — user-aware."""
import logging
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)


def get_or_create_default_portfolio(user=None):
    """Get or create portfolio for a specific user.

    The capital is coerced to Decimal BEFORE creation: settings hands it
    over as a float, and a freshly created instance keeps whatever types
    it was given until reloaded from the database — so the first task to
    both create and use the portfolio in one run crashed on
    float + Decimal, which on a fresh deploy is the very first exposure
    run.
    """
    from .models import Portfolio

    config = settings.PORTFOLIO_CONFIG
    capital = Decimal(str(config["initial_capital"]))

    if user and user.is_authenticated:
        portfolio, created = Portfolio.objects.get_or_create(
            name=f"{user.username}_main",
            defaults={
                "initial_capital": capital,
                "current_value": capital,
                "cash_available": capital,
                "currency": config["base_currency"],
            },
        )
    else:
        portfolio, created = Portfolio.objects.get_or_create(
            name="Main",
            defaults={
                "initial_capital": capital,
                "current_value": capital,
                "cash_available": capital,
                "currency": config["base_currency"],
            },
        )

    if created:
        logger.info(f"Created portfolio: {portfolio.name}")
    return portfolio
