"""Commodities-API.com adapter."""
import os
import logging
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("COMMODITIES_API_KEY", "")
BASE_URL = "https://commodities-api.com/api"


def fetch_latest(symbols: list) -> dict:
    """Fetch latest commodity prices."""
    rate_limiter.wait_if_needed("commodities_api", 10)
    # TODO: Implement API call
    raise NotImplementedError("Commodities API adapter not yet implemented")
