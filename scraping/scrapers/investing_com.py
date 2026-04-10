"""Investing.com scraper — economic calendar, news.

Fetches the economic calendar and market overview from Investing.com.
Uses browser-like headers to mimic a real user session; no Selenium needed
for most data as the calendar data is available via a form-POST endpoint.
"""
import logging
import json
from datetime import date, datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

INVESTING_BASE = "https://www.investing.com"
CALENDAR_API = f"{INVESTING_BASE}/economic-calendar/Service/getCalendarFilteredData"
MARKET_OVERVIEW_URL = f"{INVESTING_BASE}/markets/global-indices-overview"

# Impact level mapping
IMPACT_MAP = {
    "1": "low",
    "2": "medium",
    "3": "high",
    "": "unknown",
}

# Browser-like headers — Investing.com requires these or returns 403
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.investing.com/economic-calendar/",
    "Origin": "https://www.investing.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
    "Connection": "keep-alive",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
}


def _rate_limit():
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("investing_com", calls_per_minute=5)
    except Exception:
        pass


def _get_bs4():
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "BeautifulSoup4 is required for the Investing.com scraper. "
            "Install with: pip install beautifulsoup4 lxml"
        ) from exc


def fetch_economic_calendar(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Fetch the economic calendar from Investing.com.

    Args:
        date_from: Start date as "YYYY-MM-DD" string.  Defaults to today.
        date_to:   End date as "YYYY-MM-DD" string.  Defaults to 7 days ahead.

    Returns:
        List of dicts with keys: event_name, country, event_date, time,
        impact, actual, forecast, previous.  Returns empty list on any error.
    """
    _rate_limit()

    today = date.today()
    if date_from is None:
        date_from = today.strftime("%Y-%m-%d")
    if date_to is None:
        date_to = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    # The Investing.com calendar endpoint expects a POST with form-encoded data
    form_data = {
        "country[]": [],          # empty = all countries
        "importance[]": ["1", "2", "3"],   # all impact levels
        "dateFrom": date_from,
        "dateTo": date_to,
        "timeZone": "55",          # UTC
        "timeFilter": "timeRemain",
        "currentTab": "custom",
        "submitFilters": "1",
        "limit_from": "0",
    }

    # Build form-encoded body manually to support repeated keys
    body_parts = []
    for k, v in form_data.items():
        if isinstance(v, list):
            for item in v:
                body_parts.append(f"{requests.utils.quote(str(k))}={requests.utils.quote(str(item))}")
        else:
            body_parts.append(f"{requests.utils.quote(str(k))}={requests.utils.quote(str(v))}")
    body = "&".join(body_parts)

    results: list[dict] = []

    try:
        resp = requests.post(CALENDAR_API, data=body, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Investing.com calendar POST failed: %s", exc)
        return _fallback_calendar_scrape(date_from, date_to)

    # Response is JSON with a "data" key containing an HTML fragment
    try:
        payload = resp.json()
    except ValueError:
        logger.error("Investing.com: failed to parse calendar JSON response")
        return _fallback_calendar_scrape(date_from, date_to)

    html_fragment = payload.get("data", "")
    if not html_fragment:
        logger.warning("Investing.com: calendar response has no 'data' field")
        return []

    try:
        BeautifulSoup = _get_bs4()
    except ImportError as exc:
        logger.warning("Investing.com calendar disabled: %s", exc)
        return []

    try:
        soup = BeautifulSoup(html_fragment, "lxml")
        rows = soup.find_all("tr", {"class": lambda c: c and "js-event-item" in c})

        if not rows:
            rows = soup.find_all("tr", attrs={"data-event-datetime": True})

        for row in rows:
            try:
                # Time
                time_el = row.find("td", class_=lambda c: c and "time" in (c or ""))
                event_time = time_el.get_text(strip=True) if time_el else ""

                # Country
                country_el = row.find("td", class_=lambda c: c and "flag" in (c or "").lower())
                country = ""
                if country_el:
                    flag_span = country_el.find("span", attrs={"title": True})
                    if flag_span:
                        country = flag_span.get("title", "")
                    else:
                        country = country_el.get_text(strip=True)

                # Impact (bull icons)
                impact_td = row.find("td", class_=lambda c: c and "sentiment" in (c or "").lower())
                impact = "unknown"
                if impact_td:
                    bull_icons = impact_td.find_all("i", class_=lambda c: c and "bull" in (c or "").lower())
                    active = [i for i in bull_icons if "grayFullBullishIcon" not in (i.get("class", []))]
                    impact_level = len(active)
                    impact = {1: "low", 2: "medium", 3: "high"}.get(impact_level, "unknown")

                # Event name
                event_td = row.find("td", class_=lambda c: c and "event" in (c or "").lower())
                event_name = ""
                if event_td:
                    event_link = event_td.find("a")
                    event_name = event_link.get_text(strip=True) if event_link else event_td.get_text(strip=True)

                # Actual / Forecast / Previous
                actual_td = row.find("td", id=lambda i: i and i.startswith("eventActual"))
                forecast_td = row.find("td", id=lambda i: i and i.startswith("eventForecast"))
                previous_td = row.find("td", id=lambda i: i and i.startswith("eventPrevious"))

                actual = actual_td.get_text(strip=True) if actual_td else ""
                forecast = forecast_td.get_text(strip=True) if forecast_td else ""
                previous = previous_td.get_text(strip=True) if previous_td else ""

                # Date from row attribute
                event_date_str = row.get("data-event-datetime", "")
                event_date = event_date_str[:10] if event_date_str else date_from

                results.append({
                    "event_name": event_name,
                    "country": country,
                    "event_date": event_date,
                    "time": event_time,
                    "impact": impact,
                    "actual": actual,
                    "forecast": forecast,
                    "previous": previous,
                })

            except Exception as row_exc:
                logger.debug("Calendar row parse error: %s", row_exc)
                continue

    except Exception as exc:
        logger.error("Investing.com calendar HTML parse failed: %s", exc)
        return []

    logger.info("Investing.com calendar: parsed %d events (%s to %s)",
                len(results), date_from, date_to)

    _persist_economic_events(results)
    return results


def _fallback_calendar_scrape(date_from: str, date_to: str) -> list[dict]:
    """Secondary attempt: scrape the calendar page directly."""
    _rate_limit()

    html_headers = {**HEADERS, "Content-Type": "text/html"}
    html_headers.pop("X-Requested-With", None)
    html_headers.pop("Content-Type", None)

    try:
        resp = requests.get(
            f"{INVESTING_BASE}/economic-calendar/",
            headers={**HEADERS, "Accept": "text/html"},
            timeout=25,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Investing.com fallback calendar scrape failed: %s", exc)
        return []

    try:
        BeautifulSoup = _get_bs4()
    except ImportError:
        return []

    try:
        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.find_all("tr", {"class": lambda c: c and "js-event-item" in (c or "")})
        results = []
        for row in rows:
            event_td = row.find("td", class_=lambda c: "event" in (c or ""))
            if not event_td:
                continue
            event_name = event_td.get_text(strip=True)
            results.append({
                "event_name": event_name,
                "country": "",
                "event_date": date_from,
                "time": "",
                "impact": "unknown",
                "actual": "",
                "forecast": "",
                "previous": "",
            })
        return results
    except Exception as exc:
        logger.error("Investing.com fallback parse error: %s", exc)
        return []


def fetch_market_overview() -> dict:
    """Fetch a snapshot of global market indices from Investing.com.

    Returns:
        Dict with key "indices" mapping to a list of dicts, each with:
        name, last, change, change_pct, country.  Returns empty dict on error.
    """
    _rate_limit()

    try:
        BeautifulSoup = _get_bs4()
    except ImportError as exc:
        logger.warning("Investing.com market overview disabled: %s", exc)
        return {}

    page_headers = {**HEADERS}
    page_headers.pop("Content-Type", None)
    page_headers.pop("X-Requested-With", None)
    page_headers["Accept"] = "text/html,application/xhtml+xml"

    try:
        resp = requests.get(MARKET_OVERVIEW_URL, headers=page_headers, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Investing.com market overview request failed: %s", exc)
        return {}

    try:
        soup = BeautifulSoup(resp.text, "lxml")
        indices = []

        # Primary: look for the global indices table
        table = soup.find("table", {"id": "world_indices"})
        if table is None:
            table = soup.find("table", class_=lambda c: c and "datatable" in (c or "").lower())

        if table:
            for row in table.find_all("tr")[1:]:  # skip header
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue

                name_el = cells[0].find("a") or cells[0]
                name = name_el.get_text(strip=True)

                last = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                chg = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                chg_pct = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                country = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                indices.append({
                    "name": name,
                    "last": last,
                    "change": chg,
                    "change_pct": chg_pct,
                    "country": country,
                })
        else:
            # Generic fallback: grab any numeric table rows
            for table_candidate in soup.find_all("table")[:5]:
                rows = table_candidate.find_all("tr")
                if len(rows) > 3:
                    for row in rows[1:]:
                        cells = row.find_all("td")
                        if cells:
                            indices.append({
                                "name": cells[0].get_text(strip=True),
                                "last": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                                "change": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                                "change_pct": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                                "country": "",
                            })
                    if indices:
                        break

        logger.info("Investing.com market overview: %d indices", len(indices))
        return {"indices": indices, "fetched_at": datetime.utcnow().isoformat()}

    except Exception as exc:
        logger.error("Investing.com market overview parse error: %s", exc)
        return {}


def _persist_economic_events(events: list[dict]) -> None:
    """Attempt to save economic events to the database.

    The base EconomicEvent model is referenced here if it exists in the
    scraping app; silently skips if the model is not yet defined.
    """
    if not events:
        return
    try:
        # Try to import a hypothetical EconomicEvent model
        from scraping.models import EconomicEvent  # type: ignore
        from django.utils import timezone as dj_tz

        created = 0
        for ev in events:
            try:
                event_date = None
                if ev.get("event_date"):
                    try:
                        event_date = date.fromisoformat(ev["event_date"])
                    except ValueError:
                        event_date = date.today()

                _, was_created = EconomicEvent.objects.get_or_create(
                    event_name=ev["event_name"][:200],
                    event_date=event_date,
                    country=ev.get("country", "")[:50],
                    defaults={
                        "time": ev.get("time", "")[:10],
                        "impact": ev.get("impact", "unknown")[:10],
                        "actual": ev.get("actual", "")[:50],
                        "forecast": ev.get("forecast", "")[:50],
                        "previous": ev.get("previous", "")[:50],
                    },
                )
                if was_created:
                    created += 1
            except Exception:
                continue

        logger.debug("EconomicEvent persistence: %d new rows", created)

    except ImportError:
        pass  # Model doesn't exist yet — silently skip
    except Exception as exc:
        logger.debug("EconomicEvent persistence skipped: %s", exc)
