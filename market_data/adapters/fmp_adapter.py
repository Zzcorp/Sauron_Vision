"""Financial Modeling Prep adapter — fundamentals & SEC data."""
import os
import logging
import requests
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("FMP_API_KEY", "")
BASE_URL = "https://financialmodelingprep.com/api/v3"


def fetch_company_profile(symbol: str) -> dict:
    """Fetch company fundamentals.

    Returns a dict with fields such as symbol, companyName, sector, industry,
    marketCap, price, beta, description and more, or an empty dict on failure.
    """
    rate_limiter.wait_if_needed("fmp", 5)

    if not API_KEY:
        logger.warning("FMP_API_KEY is not set — skipping fetch_company_profile for %s", symbol)
        return {}

    url = f"{BASE_URL}/profile/{symbol}"
    params = {"apikey": API_KEY}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data:
            logger.warning("FMP returned empty profile for symbol: %s", symbol)
            return {}

        # API returns a list with one element
        if isinstance(data, list):
            return data[0] if data else {}

        return data

    except requests.exceptions.HTTPError as exc:
        logger.error("FMP HTTP error fetching profile for %s: %s", symbol, exc)
    except requests.exceptions.RequestException as exc:
        logger.error("FMP request error fetching profile for %s: %s", symbol, exc)
    except (ValueError, KeyError) as exc:
        logger.error("FMP JSON parse error for profile %s: %s", symbol, exc)

    return {}


def fetch_financial_statements(symbol: str, statement_type: str = "income-statement") -> list:
    """Fetch financial statements (income, balance sheet, cash flow).

    Valid statement_type values:
        - "income-statement"
        - "balance-sheet-statement"
        - "cash-flow-statement"

    Returns the last 5 periods as a list of dicts, or an empty list on failure.
    """
    rate_limiter.wait_if_needed("fmp", 5)

    valid_types = {"income-statement", "balance-sheet-statement", "cash-flow-statement"}
    if statement_type not in valid_types:
        logger.warning(
            "Invalid statement_type '%s'. Must be one of %s", statement_type, valid_types
        )
        return []

    if not API_KEY:
        logger.warning(
            "FMP_API_KEY is not set — skipping fetch_financial_statements for %s", symbol
        )
        return []

    url = f"{BASE_URL}/{statement_type}/{symbol}"
    params = {"limit": 5, "apikey": API_KEY}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            logger.warning(
                "FMP unexpected response format for %s %s: %s", statement_type, symbol, type(data)
            )
            return []

        return data

    except requests.exceptions.HTTPError as exc:
        logger.error(
            "FMP HTTP error fetching %s for %s: %s", statement_type, symbol, exc
        )
    except requests.exceptions.RequestException as exc:
        logger.error(
            "FMP request error fetching %s for %s: %s", statement_type, symbol, exc
        )
    except (ValueError, KeyError) as exc:
        logger.error(
            "FMP JSON parse error for %s %s: %s", statement_type, symbol, exc
        )

    return []
