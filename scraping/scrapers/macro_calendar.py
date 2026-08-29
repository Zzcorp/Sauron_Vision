"""The macro calendar — the source that never existed.

`brain.position_review._imminent_events` derives {EUR, USD} from EURUSD and
queries `currency_affected`, with a comment noting that "the currency
carries the macro print that moves an FX leg". A repo-wide search found
exactly ONE non-test writer of `EconomicEvent`: the earnings scraper, which
stores the equity TICKER in that column. The field held "AAPL", never
"USD", so the forex branch could not match a row — ever — and every forex
position's event-risk read rendered a confident empty list through NFP, CPI
and FOMC.

The blind marker in position_review names that absence. This fills it.

WHAT IS DIFFERENT FROM THE EARNINGS SCRAPER
`currency_affected` gets the CURRENCY, which is the entire point. The two
scrapers write the same table under different `source` values so neither
can overwrite the other, and `_imminent_events` reads both: a title match
finds single-name earnings, a currency match finds the macro print.

Impact is normalised down to the platform's vocabulary. FMP grades
Low/Medium/High; the position review only reacts to `high`, and quietly
mapping "Medium" up to it would put a permanent event flag on every FX
position and train the operator to ignore the one that matters.

Run with:
    python manage.py fetch_macro_calendar
"""
import logging
import os
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Same shape as the earnings endpoints, and for the same reason: FMP
#: retired the v3 paths, a key on a current plan gets 403 there, and a key
#: on a legacy plan may be entitled to v3 and nothing else. Tried in order;
#: the first that returns a LIST wins, because FMP answers a plan violation
#: with HTTP 200 and an object carrying "Error Message".
FMP_MACRO_ENDPOINTS = (
    ("stable", "https://financialmodelingprep.com/stable/economic-calendar"),
    ("v3", "https://financialmodelingprep.com/api/v3/economic_calendar"),
)

#: The currencies the fleet actually trades. A calendar row for a currency
#: no bot holds is noise in a table the position review scans per position.
TRADED_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}

SOURCE = "fmp_macro"


def _event_datetime(raw):
    """FMP sends "2026-09-05 12:30:00" — naive, and documented as UTC."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(str(raw)[:19], fmt)
        except (TypeError, ValueError):
            continue
        # `django.utils.timezone.utc` was removed in Django 5; the
        # sibling scraper already uses the stdlib one.
        return naive.replace(tzinfo=dt_timezone.utc)
    return None


def _impact(raw) -> str:
    """FMP's Low/Medium/High down to what this platform reacts to.

    Only `high` triggers the position review's event flag. Promoting
    "Medium" would flag every FX position permanently, which teaches an
    operator to ignore the flag — the failure mode a risk marker cannot
    afford.
    """
    return "high" if str(raw or "").strip().lower() == "high" else "low"


def _persist(rows) -> int:
    from market_data.models import EconomicEvent

    stored = 0
    for row in rows:
        when = _event_datetime(row.get("date"))
        currency = str(row.get("currency") or "").strip().upper()[:10]
        title = str(row.get("event") or "").strip()[:300]
        if when is None or not title or currency not in TRADED_CURRENCIES:
            continue

        defaults = {
            "datetime": when,
            "country": str(row.get("country") or "")[:50],
            "impact": _impact(row.get("impact")),
            "currency_affected": currency,
            "forecast": "" if row.get("estimate") is None
                        else str(row["estimate"])[:50],
            "previous": "" if row.get("previous") is None
                        else str(row["previous"])[:50],
            "actual": "" if row.get("actual") is None
                      else str(row["actual"])[:50],
        }
        # Keyed on source+title+day so a re-run updates rather than
        # duplicates, and so this scraper can never touch an earnings row.
        existing = EconomicEvent.objects.filter(
            source=SOURCE, title=title, currency_affected=currency,
            datetime__date=when.date()).first()
        try:
            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save(update_fields=list(defaults.keys()))
            else:
                EconomicEvent.objects.create(
                    source=SOURCE, title=title, **defaults)
            stored += 1
        except Exception as exc:  # noqa: BLE001 — loud, and keep going
            logger.error("macro persist failed for %s %s: %s",
                         currency, title, exc)
    return stored


def fetch_macro_calendar_fmp(days_ahead: int = 14) -> dict:
    """Fetch the macro calendar from FMP and store it.

    Returns {"parsed", "stored"} plus, on failure, "skipped" or "error" —
    so the caller can tell "no high-impact prints this fortnight" from "we
    stored nothing", which is the distinction the whole module exists for.
    """
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        logger.warning(
            "Macro calendar skipped: FMP_API_KEY is not set. Every forex "
            "position's event-risk read stays UNCHECKED until it is.")
        return {"parsed": 0, "stored": 0, "skipped": "no_api_key"}

    today = timezone.now().date()
    future = today + timedelta(days=days_ahead)

    data, used, failures = None, "", []
    for label, url in FMP_MACRO_ENDPOINTS:
        try:
            resp = requests.get(
                url,
                params={"from": today.isoformat(), "to": future.isoformat(),
                        "apikey": api_key},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:  # noqa: BLE001 — try the next one
            failures.append(f"{label}: {e}")
            continue
        if isinstance(payload, list):
            data, used = payload, label
            break
        note = ""
        if isinstance(payload, dict):
            note = str(payload.get("Error Message")
                       or payload.get("message") or "")[:200]
        failures.append(f"{label}: {note or 'unexpected payload'}")

    if data is None:
        # Scrubbed AT THE SOURCE as well as in the log filter. This
        # string is returned to the caller, stored on the component row and
        # rendered on the health page; defence in depth is cheap here and
        # the cost of missing one surface is a published credential.
        from core.secret_scrub import scrub
        detail = scrub(" | ".join(failures) or "no endpoint answered")
        # ERROR, not warning. A macro calendar that cannot be read leaves
        # the FX event check blind, and the blind marker in position_review
        # only knows to fire because this table stays empty — so the reason
        # has to be somewhere an operator can find it.
        logger.error("FMP macro calendar error: %s", detail)
        return {"parsed": 0, "stored": 0, "error": detail}
    if used != FMP_MACRO_ENDPOINTS[0][0]:
        logger.warning("FMP macro calendar answered on %s after %s refused "
                       "— this key is on a legacy plan", used,
                       "; ".join(failures) or "nothing")

    rows = [{
        "date": item.get("date"),
        "country": item.get("country"),
        "event": item.get("event"),
        # `stable` and v3 disagree on the currency field name, and reading
        # both spellings is what lets one parser serve either plan.
        "currency": item.get("currency", item.get("currencyCode")),
        "impact": item.get("impact"),
        "estimate": item.get("estimate", item.get("consensus")),
        "previous": item.get("previous"),
        "actual": item.get("actual"),
    } for item in data]

    stored = _persist(rows)
    logger.info("FMP macro: parsed=%s stored=%s (source=%s)",
                len(rows), stored, used)
    return {"parsed": len(rows), "stored": stored}
