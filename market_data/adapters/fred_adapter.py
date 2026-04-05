"""FRED API adapter — REAL implementation for macroeconomic data."""
import os
import logging
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)

API_KEY = os.getenv("FRED_API_KEY", "")
BASE_URL = "https://api.stlouisfed.org/fred"


def _request(endpoint, params):
    """Make a request to the FRED API."""
    import requests
    if not API_KEY:
        return None
    params["api_key"] = API_KEY
    params["file_type"] = "json"
    try:
        resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"FRED API error: {e}")
        return None


def fetch_series(series_id, limit=100):
    """Fetch observations for a FRED series."""
    data = _request("series/observations", {
        "series_id": series_id,
        "sort_order": "desc",
        "limit": limit,
    })
    if not data or "observations" not in data:
        return []
    results = []
    for obs in data["observations"]:
        if obs["value"] != ".":
            results.append({
                "date": obs["date"],
                "value": Decimal(obs["value"]),
            })
    return results


def fetch_latest(series_id):
    """Fetch the most recent observation."""
    data = fetch_series(series_id, limit=1)
    return data[0] if data else None


def fetch_series_info(series_id):
    """Fetch metadata about a series."""
    data = _request("series", {"series_id": series_id})
    if not data or "seriess" not in data:
        return None
    s = data["seriess"][0] if data["seriess"] else None
    if s:
        return {
            "id": s["id"],
            "title": s["title"],
            "frequency": s.get("frequency_short", ""),
            "units": s.get("units", ""),
            "last_updated": s.get("last_updated", ""),
        }
    return None


def save_series_to_db(series_id):
    """Fetch a FRED series and save to MacroIndicator + MacroObservation."""
    from market_data.models import MacroIndicator, MacroObservation

    # Get or create the indicator
    info = fetch_series_info(series_id)
    indicator, _ = MacroIndicator.objects.get_or_create(
        series_id=series_id,
        defaults={
            "name": info["title"] if info else series_id,
            "category": "macro",
            "frequency": info.get("frequency", "daily") if info else "daily",
        }
    )

    # Fetch observations
    observations = fetch_series(series_id, limit=500)
    created = 0
    for obs in observations:
        _, was_created = MacroObservation.objects.get_or_create(
            indicator=indicator,
            date=datetime.strptime(obs["date"], "%Y-%m-%d").date(),
            defaults={"value": obs["value"]}
        )
        if was_created:
            created += 1

    # Update latest
    if observations:
        indicator.last_value = observations[0]["value"]
        indicator.last_date = datetime.strptime(observations[0]["date"], "%Y-%m-%d").date()
        indicator.save()

    return created
