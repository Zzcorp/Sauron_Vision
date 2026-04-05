"""OilPriceAPI adapter — energy commodities."""
import os
import logging
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("OIL_PRICE_API_KEY", "")
BASE_URL = "https://api.oilpriceapi.com/v1"


def fetch_latest(code: str = "WTI_USD") -> dict:
    """Fetch latest oil/energy price."""
    rate_limiter.wait_if_needed("oil_price_api", 10)
    # TODO: Implement API call
    raise NotImplementedError("OilPriceAPI adapter not yet implemented")
