"""Earnings calendar and transcript scraper.

This module fetched an earnings calendar and threw it away. There was no
persist helper at all — the Celery task called it, took len() of the result and
returned {"status": "success", "events": N}.

That is not a cosmetic gap. bot_program/asset_engine/stock_bot.py decides its
earnings blackout by querying market_data.EconomicEvent for an upcoming event
whose title contains the symbol and the word "earnings". The table has never
had a row in it, so the query has always returned None, so the blackout has
never once fired. The bot has been free to open a position the day before a
print, which is precisely the scenario the guard exists to prevent — and
nothing anywhere reported that the safety was inert.

The wording written below is therefore load-bearing: `{SYMBOL} Earnings` is
what stock_bot.py:44-53 and brain/earnings_reviewer.py:344 match against.
"""
import logging
import os
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# FMP reports the session an issuer prints in rather than a clock time.
# Mapped to the US cash session in UTC. These are wall-clock approximations —
# they shift an hour across DST — which is accurate enough for a guard that
# operates in whole days and errs toward blacking out too early.
_SESSION_UTC = {
    "bmo": (13, 30),   # before market open
    "amc": (21, 0),    # after market close
}
_DEFAULT_UTC = (13, 30)   # unknown session: assume the earliest, so the
                          # blackout starts sooner rather than later


def _event_datetime(date_str, session):
    """Aware UTC datetime for an earnings print, or None if the date is junk."""
    try:
        day = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    hh, mm = _SESSION_UTC.get((session or "").strip().lower(), _DEFAULT_UTC)
    return day.replace(hour=hh, minute=mm, tzinfo=dt_timezone.utc)


def _persist_earnings(rows):
    """Write the calendar to market_data.EconomicEvent. Returns rows UPSERTED.

    Keyed on (source, title, day) rather than on title alone: the same issuer
    prints four times a year, and keying on title would make each quarter
    overwrite the last.

    A re-asserted row counts, exactly as fetch_cot_reports counts its upserts.
    This used to count creates only, and FMP serves the whole rolling
    fortnight on every call: after the first beat of the day the remaining 47
    reported parsed=hundreds / stored=0, which task_gate.judge_result grades
    "handled N rows and stored none" — its loudest warning, and reserved for
    the case where the source answered and we kept nothing. Keeping a row that
    is already correct is a healthy run, not a dropped batch.
    """
    from market_data.models import EconomicEvent

    stored = 0
    created = 0
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        when = _event_datetime(row.get("date"), row.get("time"))
        if not symbol or when is None:
            continue

        title = f"{symbol} Earnings"
        defaults = {
            "datetime": when,
            "country": "US",
            "impact": "high",
            "currency_affected": symbol[:10],
            "forecast": "" if row.get("eps_estimated") is None else str(row["eps_estimated"]),
            "actual": "" if row.get("eps_actual") is None else str(row["eps_actual"]),
        }

        existing = EconomicEvent.objects.filter(
            source="fmp", title=title, datetime__date=when.date()).first()
        try:
            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save(update_fields=list(defaults.keys()))
                stored += 1
            else:
                EconomicEvent.objects.create(source="fmp", title=title, **defaults)
                stored += 1
                created += 1
        except Exception as exc:
            # Loud on purpose. The previous generation of persist helpers in
            # this package logged failures at DEBUG, so a mid-batch database
            # error dropped every remaining row with no trace at default level.
            logger.error("earnings persist failed for %s: %s", title, exc)

    # `created` is logged rather than returned: the caller's contract is a
    # single stored count, and the new-vs-re-asserted split is only ever
    # wanted when reading the log after a run looks odd.
    logger.debug("earnings upserts: %s (%s new)", stored, created)
    return stored


#: Where to ask, in order. FMP retired the v3 path: a key issued on any
#: of their current plans gets a flat 403 there, which is exactly what this
#: deployment saw —
#:
#:   403 Client Error: Forbidden for url:
#:   .../api/v3/earning_calendar?from=...&to=...&apikey=***
#:
#: `stable` is the current one. v3 stays as a fallback because a key issued
#: on an older plan may still be entitled to it and nothing else, and
#: dropping it would break a working deployment to fix a broken one.
#:
#: Tried in order, and the first that returns a LIST wins — status alone is
#: not enough, because FMP answers a plan violation with HTTP 200 and an
#: object carrying "Error Message".
FMP_CALENDAR_ENDPOINTS = (
    ("stable", "https://financialmodelingprep.com/stable/earnings-calendar"),
    ("v3", "https://financialmodelingprep.com/api/v3/earning_calendar"),
)


def fetch_earnings_calendar_fmp(days_ahead=14):
    """Fetch upcoming earnings from Financial Modeling Prep and store them.

    Returns {"parsed", "stored"} so the caller can tell the difference between
    "no earnings this fortnight" and "we stored nothing".
    """
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        # This used to be a bare `return []`, with no log line anywhere. The
        # task then reported success with zero events, which is exactly what a
        # quiet calendar looks like — so an unconfigured integration and a
        # working one were indistinguishable from the outside.
        logger.warning(
            "Earnings calendar skipped: FMP_API_KEY is not set. The earnings "
            "blackout in stock_bot cannot fire without this data.")
        return {"parsed": 0, "stored": 0, "skipped": "no_api_key"}

    today = timezone.now().date()
    future = today + timedelta(days=days_ahead)

    data, used, failures = None, "", []
    for label, url in FMP_CALENDAR_ENDPOINTS:
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
        # FMP answers a plan violation with 200 and an object carrying
        # "Error Message", so a status check alone calls it a success and
        # the parse below then finds no rows — a refusal that reads as an
        # empty week.
        note = ""
        if isinstance(payload, dict):
            note = str(payload.get("Error Message")
                       or payload.get("message") or "")[:200]
        failures.append(f"{label}: {note or 'unexpected payload'}")

    if data is None:
        # Same reasoning as macro_calendar: this detail is returned and
        # rendered, and it is built from raise_for_status() messages.
        from core.secret_scrub import scrub
        detail = scrub(" | ".join(failures) or "no endpoint answered")
        logger.error("FMP earnings calendar error: %s", detail)
        return {"parsed": 0, "stored": 0, "error": detail}
    if used != FMP_CALENDAR_ENDPOINTS[0][0]:
        logger.warning("FMP earnings calendar answered on %s after %s "
                       "refused — this key is on a legacy plan",
                       used, "; ".join(failures) or "nothing")

    rows = [{
        "symbol": item.get("symbol", ""),
        "date": item.get("date", ""),
        "eps_estimated": item.get("epsEstimated"),
        # `stable` renamed the ACTUALS: eps -> epsActual, revenue ->
        # revenueActual. The estimates kept their names. Reading both
        # spellings is what lets one parser serve either plan, and it is
        # cheaper than a second parser that drifts from this one.
        "eps_actual": item.get("epsActual", item.get("eps")),
        "revenue_estimated": item.get("revenueEstimated"),
        "revenue_actual": item.get("revenueActual", item.get("revenue")),
        "time": item.get("time", ""),
    } for item in data]

    stored = _persist_earnings(rows)
    logger.info("FMP earnings: parsed=%s stored=%s", len(rows), stored)
    return {"parsed": len(rows), "stored": stored}


def fetch_sec_earnings_transcript(symbol, year=None, quarter=None):
    """Fetch earnings call transcript from FMP."""
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return None

    now = timezone.now()
    if not year:
        year = now.year
    if not quarter:
        quarter = (now.month - 1) // 3 + 1

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
        logger.error("FMP transcript error: %s", e)
        return None
