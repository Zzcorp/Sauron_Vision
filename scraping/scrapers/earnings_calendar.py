"""Earnings calendar and transcript scraper."""
import logging
import requests
from datetime import datetime, timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def fetch_earnings_calendar_fmp(days_ahead=14):
    """Fetch upcoming earnings from Financial Modeling Prep."""
    import os
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/earning_calendar",
            params={"from": today, "to": future, "apikey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data:
            results.append({
                "symbol": item.get("symbol", ""),
                "date": item.get("date", ""),
                "eps_estimated": item.get("epsEstimated"),
                "eps_actual": item.get("eps"),
                "revenue_estimated": item.get("revenueEstimated"),
                "revenue_actual": item.get("revenue"),
                "time": item.get("time", ""),  # "bmo" (before market open) or "amc" (after market close)
            })
        return results

    except Exception as e:
        logger.error(f"FMP earnings calendar error: {e}")
        return []


def fetch_sec_earnings_transcript(symbol, year=None, quarter=None):
    """Fetch earnings call transcript from FMP."""
    import os
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return None

    if not year:
        year = datetime.now().year
    if not quarter:
        quarter = (datetime.now().month - 1) // 3 + 1

    try:
        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{symbol}",
            params={"year": year, "quarter": quarter, "apikey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        logger.error(f"FMP transcript error: {e}")
        return None
