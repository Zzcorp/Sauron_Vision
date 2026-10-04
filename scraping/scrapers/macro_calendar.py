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

TWO SOURCES, ONE TABLE (2026-10-03). FMP's economic calendar is a paid
endpoint: this account's key answered 402 Payment Required every thirty
minutes for a month, and every forex position read "NO MACRO CALENDAR
COVERS THE NEXT 24H" through NFP, CPI and FOMC. The operator chose the
free source: Forex Factory publishes its calendar for the week in progress
as a keyless JSON file (nfs.faireconomy.media, the feed most home-built
systems read). `fetch_macro_calendar` asks Forex Factory first and FMP
only when Forex Factory failed, so a working free feed never pays for a
402 it does not need. The two write under different `source` values
(`forexfactory`, `fmp_macro`); every reader of the macro half lists both
(`MACRO_SOURCES`). Forex Factory's "Holiday" rows are not stored: a bank
holiday is not a print, and the review only reacts to `high` anyway.

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

#: Forex Factory's weekly calendar, one keyless JSON file. Each row:
#: {"title", "country" (a currency code), "date" (ISO 8601 with the New
#: York offset), "impact" (High/Medium/Low/Holiday), "forecast",
#: "previous", "url"}. Read every thirty minutes by the beat; the feed's
#: owner asks for no more than one read a minute.
#:
#: THE CURRENT WEEK ONLY (measured on the VPS, 2026-10-04 03:20 UTC: this
#: week answered 139 rows, 135 stored; a "nextweek" file answered 404).
#: Forex Factory publishes the week in progress, Sunday to Saturday, and
#: rolls it over on Sunday — so late on a Friday the horizon ahead is a day
#: or two, and the position review's blind marker can honestly read
#: UNCHECKED over a weekend, when nothing trades. The tuple stays a tuple:
#: a second file, should one appear, is one line here.
FF_FEEDS = (
    ("thisweek", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"),
)
#: The feed sits behind a CDN that has refused the default python
#: user-agent; a browser's is what every other reader sends.
FF_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}
FF_TIMEOUT_S = 15

#: The currencies the fleet actually trades. A calendar row for a currency
#: no bot holds is noise in a table the position review scans per position.
TRADED_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}

SOURCE = "fmp_macro"
FF_SOURCE = "forexfactory"
#: Every writer of the MACRO half, for the readers (position review's
#: blind marker, news risk's leg C, the calendar page). `source="fmp"` is
#: the earnings half and stores a ticker, never a currency.
MACRO_SOURCES = (FF_SOURCE, SOURCE)


def _event_datetime(raw):
    """An event's instant in UTC, from what either source sends.

    FMP sends "2026-09-05 12:30:00" — naive, and documented as UTC. Forex
    Factory sends "2026-10-05T08:30:00-04:00" — New York wall time with
    its offset, so the offset is applied, never dropped: dropping it would
    file NFP four hours early and clear the window the print lands in.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return (raw.astimezone(dt_timezone.utc) if raw.tzinfo
                else raw.replace(tzinfo=dt_timezone.utc))
    text = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        return (parsed.astimezone(dt_timezone.utc) if parsed.tzinfo
                else parsed.replace(tzinfo=dt_timezone.utc))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(text[:19], fmt)
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


def _persist(rows, source: str = SOURCE) -> int:
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
            source=source, title=title, currency_affected=currency,
            datetime__date=when.date()).first()
        try:
            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save(update_fields=list(defaults.keys()))
            else:
                EconomicEvent.objects.create(
                    source=source, title=title, **defaults)
            stored += 1
        except Exception as exc:  # noqa: BLE001 — loud, and keep going
            logger.error("macro persist failed for %s %s: %s",
                         currency, title, exc)
    return stored


# ── Forex Factory ────────────────────────────────────────────────────────

def _ff_rows(payload) -> list:
    """Forex Factory's rows in the shape `_persist` reads. The currency IS
    the country here (the feed carries no country name), and a Holiday is
    not a print."""
    rows = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("impact") or "").strip().lower() == "holiday":
            continue
        currency = str(item.get("country") or "").strip().upper()
        rows.append({
            "date": item.get("date"),
            "country": currency,
            "event": item.get("title"),
            "currency": currency,
            "impact": item.get("impact"),
            "estimate": item.get("forecast"),
            "previous": item.get("previous"),
            "actual": item.get("actual"),
        })
    return rows


def fetch_macro_calendar_ff() -> dict:
    """This week's prints from Forex Factory (every file in FF_FEEDS),
    stored under `forexfactory`. Returns {"parsed", "stored", "source",
    "weeks"} plus "failures" when a file failed and "error" when none
    answered. Keyless: there is no `skipped`."""
    rows, weeks, failures = [], [], []
    for label, url in FF_FEEDS:
        try:
            resp = requests.get(url, headers=FF_HEADERS, timeout=FF_TIMEOUT_S)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:  # noqa: BLE001 — the other file still counts
            failures.append(f"{label}: {e}")
            continue
        if not isinstance(payload, list):
            failures.append(f"{label}: unexpected payload")
            continue
        rows.extend(_ff_rows(payload))
        weeks.append(label)
    if not weeks:
        from core.secret_scrub import scrub
        detail = scrub(" | ".join(failures) or "no feed answered")
        logger.error("Forex Factory calendar error: %s", detail)
        return {"parsed": 0, "stored": 0, "source": FF_SOURCE,
                "error": detail}
    stored = _persist(rows, source=FF_SOURCE)
    out = {"parsed": len(rows), "stored": stored, "source": FF_SOURCE,
           "weeks": weeks}
    if failures:
        out["failures"] = failures
        logger.warning("Forex Factory calendar: %s answered, %s did not (%s)",
                       ", ".join(weeks), "; ".join(failures), "partial week")
    logger.info("Forex Factory macro: parsed=%s stored=%s (%s)",
                len(rows), stored, ", ".join(weeks))
    return out


def fetch_macro_calendar(days_ahead: int = 14) -> dict:
    """The macro half: Forex Factory, then FMP only when it failed.

    Returns the winning source's dict. When both fail the error names both,
    so an operator reading the component row sees "forexfactory: … |
    fmp: …" and not one source's excuse for the other's silence. A missing
    FMP key is not a `skipped` here: with a free primary source, the paid
    fallback being unconfigured is a detail of the error, not the verdict.
    """
    ff = fetch_macro_calendar_ff()
    if not ff.get("error"):
        return ff
    fmp = fetch_macro_calendar_fmp(days_ahead=days_ahead)
    if not fmp.get("error") and not fmp.get("skipped"):
        fmp["source"] = SOURCE
        fmp["fallback_after"] = ff["error"]
        logger.warning("macro calendar: Forex Factory failed (%s); FMP "
                       "answered instead", ff["error"])
        return fmp
    detail = f"forexfactory: {ff['error']}"
    if fmp.get("error"):
        detail += f" | fmp: {fmp['error']}"
    elif fmp.get("skipped"):
        detail += f" | fmp: skipped ({fmp['skipped']})"
    return {"parsed": 0, "stored": 0, "source": "", "error": detail}


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
