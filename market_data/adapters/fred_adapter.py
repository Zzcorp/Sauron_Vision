"""FRED API adapter — REAL implementation for macroeconomic data."""
import os
import logging
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stlouisfed.org/fred"

NOT_CONFIGURED = "no_api_key"


def _api_key():
    """The FRED key, read at call time.

    This was a module-level constant, which froze whatever the environment
    held when the worker first imported the module — a key added to the env
    afterwards never took effect, and no test could set one.
    """
    return os.getenv("FRED_API_KEY", "")


def _request(endpoint, params):
    """Make a request to the FRED API."""
    import requests
    api_key = _api_key()
    if not api_key:
        return None
    params["api_key"] = api_key
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
    """Fetch a FRED series into MacroIndicator + MacroObservation.

    Returns {"parsed", "observations_saved"}, plus {"skipped": NOT_CONFIGURED}
    when there is no key.

    Both halves matter to core/task_gate.judge_result. Without the skip marker
    a missing FRED_API_KEY returned exactly what a healthy quiet run returns,
    so nothing could say WHY the macro page was empty. And `observations_saved`
    counts UPSERTS the way fetch_cot_reports does, not a row-count delta:
    these series are monthly or daily, the beat runs every four hours, and on
    most runs every observation FRED serves is already stored. Counting
    creates alone made that ordinary outcome read as "handled 500 rows and
    stored none" — the verdict reserved for a source we answered and threw
    away.
    """
    from market_data.models import MacroIndicator, MacroObservation

    if not _api_key():
        logger.warning(
            "FRED skipped: FRED_API_KEY is not set. Yield-curve and VIX "
            "regime reads have no data without it.")
        return {"parsed": 0, "observations_saved": 0, "skipped": NOT_CONFIGURED}

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
    created = revised = 0
    for obs in observations:
        row, was_created = MacroObservation.objects.get_or_create(
            indicator=indicator,
            date=datetime.strptime(obs["date"], "%Y-%m-%d").date(),
            defaults={"value": obs["value"]}
        )
        if was_created:
            created += 1
        elif row.value != obs["value"]:
            # FRED revises. CPI, GDP and payrolls are restated for months
            # after first print, and a plain get_or_create keeps whichever
            # number we happened to see first — so the regime reads would
            # have been made against a figure the source itself had retracted.
            row.value = obs["value"]
            row.save(update_fields=["value"])
            revised += 1

    # Update latest
    if observations:
        indicator.last_value = observations[0]["value"]
        indicator.last_date = datetime.strptime(observations[0]["date"], "%Y-%m-%d").date()
        indicator.save()

    logger.debug("FRED %s: parsed=%s new=%s revised=%s",
                 series_id, len(observations), created, revised)
    # Every observation walked above is now stored and correct, so the upsert
    # count is the whole batch.
    return {"parsed": len(observations),
            "observations_saved": len(observations),
            "created": created, "revised": revised}
