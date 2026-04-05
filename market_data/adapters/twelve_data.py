"""Twelve Data API adapter — multi-asset time series."""
import os
import logging
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
BASE_URL = "https://api.twelvedata.com"
CALLS_PER_MINUTE = 8  # Free tier


def fetch_time_series(symbol: str, interval: str = "1day", outputsize: int = 30) -> list:
    """Fetch time series data for any asset class."""
    rate_limiter.wait_if_needed("twelve_data", CALLS_PER_MINUTE)
    # TODO: Implement API call
    raise NotImplementedError("Twelve Data adapter not yet implemented")


def fetch_quote(symbol: str) -> dict:
    """Fetch real-time quote."""
    rate_limiter.wait_if_needed("twelve_data", CALLS_PER_MINUTE)
    # TODO: Implement API call
    raise NotImplementedError("Twelve Data adapter not yet implemented")
