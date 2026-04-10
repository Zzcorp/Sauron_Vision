"""Commodities-API.com adapter."""
import os
import logging
import requests
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("COMMODITIES_API_KEY", "")
BASE_URL = "https://commodities-api.com/api"

_DEFAULT_SYMBOLS = ["BRENTOIL", "WTIOIL", "XAU", "XAG", "COPPER"]


def fetch_latest(symbols: list = None) -> dict:
    """Fetch latest commodity prices.

    The Commodities-API returns rates relative to a base currency (usually USD),
    meaning the rates represent how many units of the commodity equal 1 USD.
    To obtain USD prices per unit we invert each rate: price = 1 / rate.

    Returns a dict of {symbol: usd_price}, or an empty dict on failure.
    """
    rate_limiter.wait_if_needed("commodities_api", 10)

    if symbols is None or len(symbols) == 0:
        symbols = _DEFAULT_SYMBOLS

    if not API_KEY:
        logger.warning("COMMODITIES_API_KEY is not set — skipping fetch_latest")
        return {}

    url = f"{BASE_URL}/latest"
    params = {
        "access_key": API_KEY,
        "symbols": ",".join(symbols),
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("success", False):
            error_info = data.get("error", {})
            logger.error(
                "Commodities API returned failure: code=%s info=%s",
                error_info.get("code"),
                error_info.get("info"),
            )
            return {}

        rates = data.get("data", {}).get("rates", {})
        if not rates:
            logger.warning("Commodities API returned no rates in response")
            return {}

        # Invert rates: API gives units-of-commodity per 1 base-unit (USD),
        # so 1/rate gives USD price per commodity unit.
        prices = {}
        for symbol, rate in rates.items():
            try:
                rate_float = float(rate)
                prices[symbol] = 1.0 / rate_float if rate_float != 0 else 0.0
            except (TypeError, ValueError) as exc:
                logger.warning("Commodities API could not parse rate for %s: %s", symbol, exc)

        return prices

    except requests.exceptions.HTTPError as exc:
        logger.error("Commodities API HTTP error: %s", exc)
    except requests.exceptions.RequestException as exc:
        logger.error("Commodities API request error: %s", exc)
    except (ValueError, KeyError) as exc:
        logger.error("Commodities API JSON parse error: %s", exc)

    return {}
