"""OilPriceAPI adapter — energy commodities."""
import os
import logging
import requests
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("OIL_PRICE_API_KEY", "")
BASE_URL = "https://api.oilpriceapi.com/v1"


def fetch_latest(code: str = "WTI_USD") -> dict:
    """Fetch latest oil/energy price by code.

    Common codes: WTI_USD, BRENT_USD, NATURAL_GAS_USD.

    Returns a dict with keys: price, code, created_at, currency.
    Returns an empty dict on failure.
    """
    rate_limiter.wait_if_needed("oil_price_api", 10)

    if not API_KEY:
        logger.warning("OIL_PRICE_API_KEY is not set — skipping fetch_latest for code=%s", code)
        return {}

    url = f"{BASE_URL}/prices/latest"
    params = {"by_code": code}
    headers = {"Authorization": f"Token {API_KEY}"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # The API wraps the result in a "data" key
        price_data = data.get("data", data)

        if not price_data:
            logger.warning("OilPriceAPI returned empty data for code=%s", code)
            return {}

        return price_data

    except requests.exceptions.HTTPError as exc:
        logger.error("OilPriceAPI HTTP error for code=%s: %s", code, exc)
    except requests.exceptions.RequestException as exc:
        logger.error("OilPriceAPI request error for code=%s: %s", code, exc)
    except (ValueError, KeyError) as exc:
        logger.error("OilPriceAPI JSON parse error for code=%s: %s", code, exc)

    return {}
