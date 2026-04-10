"""Twelve Data API adapter — multi-asset time series."""
import os
import logging
import requests
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
BASE_URL = "https://api.twelvedata.com"
CALLS_PER_MINUTE = 8  # Free tier


def fetch_time_series(symbol: str, interval: str = "1day", outputsize: int = 30) -> list:
    """Fetch time series data for any asset class.

    Returns a list of dicts with keys: datetime, open, high, low, close, volume.
    Returns an empty list on failure.
    """
    rate_limiter.wait_if_needed("twelve_data", CALLS_PER_MINUTE)

    if not API_KEY:
        logger.warning(
            "TWELVE_DATA_API_KEY is not set — skipping fetch_time_series for %s", symbol
        )
        return []

    url = f"{BASE_URL}/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Twelve Data signals errors in the JSON body with a "status" or "code" field
        if data.get("status") == "error" or "code" in data:
            logger.error(
                "Twelve Data API error for time_series %s: %s",
                symbol,
                data.get("message", data),
            )
            return []

        values = data.get("values", [])
        if not isinstance(values, list):
            logger.warning(
                "Twelve Data unexpected 'values' format for %s: %s", symbol, type(values)
            )
            return []

        return values

    except requests.exceptions.HTTPError as exc:
        logger.error("Twelve Data HTTP error for time_series %s: %s", symbol, exc)
    except requests.exceptions.RequestException as exc:
        logger.error("Twelve Data request error for time_series %s: %s", symbol, exc)
    except (ValueError, KeyError) as exc:
        logger.error("Twelve Data JSON parse error for time_series %s: %s", symbol, exc)

    return []


def fetch_quote(symbol: str) -> dict:
    """Fetch real-time quote.

    Returns a dict with keys: symbol, name, exchange, currency, datetime,
    open, high, low, close, volume, previous_close, change, percent_change.
    Returns an empty dict on failure.
    """
    rate_limiter.wait_if_needed("twelve_data", CALLS_PER_MINUTE)

    if not API_KEY:
        logger.warning(
            "TWELVE_DATA_API_KEY is not set — skipping fetch_quote for %s", symbol
        )
        return {}

    url = f"{BASE_URL}/quote"
    params = {"symbol": symbol, "apikey": API_KEY}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "error" or "code" in data:
            logger.error(
                "Twelve Data API error for quote %s: %s",
                symbol,
                data.get("message", data),
            )
            return {}

        return data

    except requests.exceptions.HTTPError as exc:
        logger.error("Twelve Data HTTP error for quote %s: %s", symbol, exc)
    except requests.exceptions.RequestException as exc:
        logger.error("Twelve Data request error for quote %s: %s", symbol, exc)
    except (ValueError, KeyError) as exc:
        logger.error("Twelve Data JSON parse error for quote %s: %s", symbol, exc)

    return {}
