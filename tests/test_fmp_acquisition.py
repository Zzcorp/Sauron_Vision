"""The vendor's own payload, parsed.

The roadmap's Tier-1 item, on the case that proved it. Before this file the
FMP mapping — `item["epsEstimated"]`, `item["eps"]`, `item["time"]` — had
ZERO coverage: all 25 test call sites passed dicts already in the
platform's normalised internal shape, so the acquisition path had never
executed under test and the suite was green because of it.

Then the operator supplied a key and the page said:

    403 Client Error: Forbidden for url:
    .../api/v3/earning_calendar?from=2026-08-28&to=2026-09-11&apikey=***

FMP retired that path. Every current plan answers on `stable`, which also
RENAMED the actuals — `eps` became `epsActual`, `revenue` became
`revenueActual` — so switching endpoints without reading the payload would
have traded a loud 403 for a silent column of Nones.

That is the whole argument for fixture tests: a status code is not a parse.

Run with:  python manage.py test tests.test_fmp_acquisition
"""
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from django.test import TestCase


@contextmanager
def _key(value="test-key"):
    saved = os.environ.get("FMP_API_KEY")
    os.environ["FMP_API_KEY"] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("FMP_API_KEY", None)
        else:
            os.environ["FMP_API_KEY"] = saved


def _resp(status=200, payload=None, url=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    if status >= 400:
        import requests
        r.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: Forbidden for url: {url}")
    else:
        r.raise_for_status.return_value = None
    return r


#: A real `stable` row, field-for-field. Actuals are null for a future date,
#: which is the normal case for a forward-looking calendar.
STABLE_ROW = {
    "symbol": "AAPL", "date": "2026-09-04",
    "epsActual": None, "epsEstimated": 1.54,
    "revenueActual": None, "revenueEstimated": 94_500_000_000,
    "lastUpdated": "2026-08-27",
}

#: The same earnings date as legacy v3 spelled it.
V3_ROW = {
    "symbol": "AAPL", "date": "2026-09-04",
    "eps": None, "epsEstimated": 1.54,
    "revenue": None, "revenueEstimated": 94_500_000_000,
    "time": "amc", "updatedFromDate": "2026-08-27",
}


class ItAsksTheEndpointThatStillExistsTests(TestCase):

    def test_stable_is_tried_first(self):
        from scraping.scrapers.earnings_calendar import (
            FMP_CALENDAR_ENDPOINTS, fetch_earnings_calendar_fmp,
        )
        self.assertEqual(FMP_CALENDAR_ENDPOINTS[0][0], "stable")
        with _key(), patch("scraping.scrapers.earnings_calendar.requests.get",
                           return_value=_resp(payload=[STABLE_ROW])) as g:
            out = fetch_earnings_calendar_fmp(days_ahead=14)
        self.assertEqual(out["parsed"], 1)
        self.assertIn("/stable/earnings-calendar", g.call_args_list[0][0][0])

    def test_a_403_on_stable_falls_back_to_v3(self):
        """A key issued on an older plan may be entitled to v3 and nothing
        else. Dropping it would break a working deployment to fix a broken
        one."""
        from scraping.scrapers.earnings_calendar import (
            fetch_earnings_calendar_fmp,
        )
        responses = [_resp(403, url="stable"), _resp(payload=[V3_ROW])]
        with _key(), patch("scraping.scrapers.earnings_calendar.requests.get",
                           side_effect=responses):
            out = fetch_earnings_calendar_fmp(days_ahead=14)
        self.assertEqual(out["parsed"], 1)
        self.assertNotIn("error", out)

    def test_both_refusing_reports_both_reasons(self):
        """The operator's next move differs depending on whether it is a
        plan limit or a bad key, and only the messages say which."""
        from scraping.scrapers.earnings_calendar import (
            fetch_earnings_calendar_fmp,
        )
        with _key(), patch("scraping.scrapers.earnings_calendar.requests.get",
                           side_effect=[_resp(403, url="stable"),
                                        _resp(403, url="v3")]):
            out = fetch_earnings_calendar_fmp(days_ahead=14)
        self.assertIn("error", out)
        self.assertIn("stable", out["error"])
        self.assertIn("v3", out["error"])
        self.assertEqual(out["stored"], 0)

    def test_a_200_carrying_an_error_message_is_not_a_success(self):
        """FMP answers a plan violation with HTTP 200 and an object. A
        status check alone calls that a success, and the parse then finds
        no rows — a refusal that reads as an empty week."""
        from scraping.scrapers.earnings_calendar import (
            fetch_earnings_calendar_fmp,
        )
        refusal = {"Error Message": "Exclusive Endpoint: This endpoint is "
                                    "not available under your current "
                                    "subscription."}
        with _key(), patch("scraping.scrapers.earnings_calendar.requests.get",
                           return_value=_resp(payload=refusal)):
            out = fetch_earnings_calendar_fmp(days_ahead=14)
        self.assertIn("error", out)
        self.assertIn("Exclusive Endpoint", out["error"])


class TheMappingSurvivesEitherSpellingTests(TestCase):
    """`stable` renamed the ACTUALS and kept the estimates. Switching
    endpoints without reading the payload would have traded a loud 403 for
    a silent column of Nones."""

    def _rows_from(self, payload):
        from scraping.scrapers.earnings_calendar import (
            fetch_earnings_calendar_fmp,
        )
        seen = {}
        with _key(), \
                patch("scraping.scrapers.earnings_calendar.requests.get",
                      return_value=_resp(payload=payload)), \
                patch("scraping.scrapers.earnings_calendar._persist_earnings",
                      side_effect=lambda rows: seen.setdefault("rows", rows)
                      and 0):
            fetch_earnings_calendar_fmp(days_ahead=14)
        return seen.get("rows", [])

    def test_a_stable_row_maps(self):
        rows = self._rows_from([dict(STABLE_ROW, epsActual=1.61,
                                     revenueActual=95_000_000_000)])
        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["eps_actual"], 1.61)
        self.assertEqual(rows[0]["eps_estimated"], 1.54)
        self.assertEqual(rows[0]["revenue_actual"], 95_000_000_000)

    def test_a_v3_row_maps_to_the_same_shape(self):
        rows = self._rows_from([dict(V3_ROW, eps=1.61,
                                     revenue=95_000_000_000)])
        self.assertEqual(rows[0]["eps_actual"], 1.61)
        self.assertEqual(rows[0]["revenue_actual"], 95_000_000_000)

    def test_a_future_date_with_no_actuals_is_not_an_error(self):
        """The normal case for a forward-looking calendar."""
        rows = self._rows_from([STABLE_ROW])
        self.assertIsNone(rows[0]["eps_actual"])
        self.assertEqual(rows[0]["eps_estimated"], 1.54)

    def test_an_unexpected_field_set_does_not_crash_the_parse(self):
        """A vendor adding or dropping a key must cost this row, not the
        run."""
        rows = self._rows_from([{"symbol": "MSFT", "date": "2026-09-05"}])
        self.assertEqual(rows[0]["symbol"], "MSFT")
        self.assertIsNone(rows[0]["eps_estimated"])


class TheKeyNeverReachesTheRecordTests(TestCase):
    """The 403 message FMP builds contains the full query string, apikey
    included. It lands in `last_message`, on the health page, and in every
    log line that echoes it."""

    def test_the_error_the_operator_sees_is_scrubbed(self):
        from core.secret_scrub import scrub
        raw = ("403 Client Error: Forbidden for url: "
               "https://financialmodelingprep.com/api/v3/earning_calendar"
               "?from=2026-08-28&to=2026-09-11&apikey=jiXVeSMzuDSQuMzDRVoM")
        cleaned = scrub(raw)
        self.assertNotIn("jiXVeSMzuDSQuMzDRVoM", cleaned)
        self.assertIn("403", cleaned)
