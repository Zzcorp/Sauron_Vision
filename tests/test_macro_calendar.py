"""The macro calendar source that never existed.

`_imminent_events` derives {EUR, USD} from EURUSD and queries
`currency_affected`. A repo-wide search found exactly one non-test writer
of `EconomicEvent` — the earnings scraper — and it stores the equity TICKER
there. The column held "AAPL", never "USD", so the forex branch could not
match a row and every forex position's event-risk read rendered a confident
empty list through NFP, CPI and FOMC.

These tests assert the PARSE against payload shapes, not against dicts the
platform wrote for itself — the same lesson as the vendor-payload work:
a mapping verified only against its own output is a mapping that has never
run.

Run with:  python manage.py test tests.test_macro_calendar
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase


STABLE_ROW = {
    "date": "2026-09-04 12:30:00",
    "country": "US",
    "event": "Non-Farm Payrolls",
    "currency": "USD",
    "impact": "High",
    "estimate": 165000,
    "previous": 142000,
    "actual": None,
}

V3_ROW = {
    "date": "2026-09-11 12:15:00",
    "country": "EU",
    "event": "ECB Interest Rate Decision",
    "currencyCode": "EUR",          # v3's spelling
    "impact": "High",
    "consensus": 2.15,              # v3's spelling
    "previous": 2.15,
    "actual": None,
}


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


class TheParseHandlesBothPlanShapesTests(TestCase):

    def _run(self, payload, key="k"):
        from scraping.scrapers import macro_calendar
        with patch.dict("os.environ", {"FMP_API_KEY": key}), \
             patch.object(macro_calendar.requests, "get",
                          return_value=_resp(payload)):
            return macro_calendar.fetch_macro_calendar_fmp()

    def test_a_stable_payload_stores_the_currency_not_a_ticker(self):
        """The whole point. `currency_affected` is what the forex branch
        matches on, and nothing had ever written a currency into it."""
        from market_data.models import EconomicEvent
        out = self._run([STABLE_ROW])
        self.assertEqual(out["stored"], 1)
        row = EconomicEvent.objects.get(source="fmp_macro")
        self.assertEqual(row.currency_affected, "USD")
        self.assertEqual(row.title, "Non-Farm Payrolls")
        self.assertEqual(row.impact, "high")

    def test_the_v3_field_spellings_are_read_too(self):
        """A key on a legacy plan gets v3 and nothing else; one parser has
        to serve either, or the fallback endpoint is decoration."""
        from market_data.models import EconomicEvent
        self._run([V3_ROW])
        row = EconomicEvent.objects.get(source="fmp_macro")
        self.assertEqual(row.currency_affected, "EUR")
        self.assertEqual(row.forecast, "2.15")

    def test_a_medium_impact_print_is_not_promoted_to_high(self):
        """Only `high` triggers the position review's flag. Promoting
        Medium would flag every FX position permanently, which teaches an
        operator to ignore the flag."""
        from market_data.models import EconomicEvent
        self._run([{**STABLE_ROW, "impact": "Medium"}])
        self.assertEqual(
            EconomicEvent.objects.get(source="fmp_macro").impact, "low")

    def test_a_currency_no_bot_trades_is_dropped(self):
        self._run([{**STABLE_ROW, "currency": "SEK"}])
        from market_data.models import EconomicEvent
        self.assertFalse(EconomicEvent.objects.filter(
            source="fmp_macro").exists())

    def test_an_unparseable_date_is_skipped_not_stored_at_now(self):
        """A macro print filed at the wrong time is worse than a missing
        one: the position review would clear the real window and flag an
        empty one."""
        self._run([{**STABLE_ROW, "date": "not a date"}])
        from market_data.models import EconomicEvent
        self.assertFalse(EconomicEvent.objects.filter(
            source="fmp_macro").exists())

    def test_a_rerun_updates_rather_than_duplicates(self):
        from market_data.models import EconomicEvent
        self._run([STABLE_ROW])
        self._run([{**STABLE_ROW, "actual": 170000}])
        rows = EconomicEvent.objects.filter(source="fmp_macro")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().actual, "170000")

    def test_it_never_touches_an_earnings_row(self):
        """Two scrapers, one table. A key collision would have the macro
        run overwrite AAPL's earnings entry."""
        from market_data.models import EconomicEvent
        from django.utils import timezone
        EconomicEvent.objects.create(
            source="fmp", title="AAPL Earnings", country="US",
            datetime=timezone.now(), impact="high",
            currency_affected="AAPL")
        self._run([STABLE_ROW])
        self.assertTrue(EconomicEvent.objects.filter(
            source="fmp", currency_affected="AAPL").exists())
        self.assertEqual(EconomicEvent.objects.count(), 2)


class ItSaysWhyItStoredNothingTests(TestCase):
    """Three states used to look identical from outside: no key, a plan
    that refuses the endpoint, and a genuinely quiet fortnight."""

    def test_a_missing_key_is_named(self):
        from scraping.scrapers import macro_calendar
        with patch.dict("os.environ", {"FMP_API_KEY": ""}):
            out = macro_calendar.fetch_macro_calendar_fmp()
        self.assertEqual(out["skipped"], "no_api_key")

    def test_a_plan_violation_answered_with_http_200_is_an_error(self):
        """FMP answers a plan violation with 200 and an object carrying
        "Error Message", so a status check alone calls it a success and
        the parse then finds no rows — a refusal that reads as a quiet
        fortnight."""
        from scraping.scrapers import macro_calendar
        with patch.dict("os.environ", {"FMP_API_KEY": "k"}), \
             patch.object(macro_calendar.requests, "get",
                          return_value=_resp(
                              {"Error Message": "Legacy plan"})):
            out = macro_calendar.fetch_macro_calendar_fmp()
        self.assertIn("error", out)
        self.assertIn("Legacy plan", out["error"])

    def test_a_transport_failure_is_an_error_not_an_empty_week(self):
        from scraping.scrapers import macro_calendar
        with patch.dict("os.environ", {"FMP_API_KEY": "k"}), \
             patch.object(macro_calendar.requests, "get",
                          side_effect=RuntimeError("dns")):
            out = macro_calendar.fetch_macro_calendar_fmp()
        self.assertIn("error", out)

    def test_a_genuinely_empty_calendar_is_a_success(self):
        from scraping.scrapers import macro_calendar
        with patch.dict("os.environ", {"FMP_API_KEY": "k"}), \
             patch.object(macro_calendar.requests, "get",
                          return_value=_resp([])):
            out = macro_calendar.fetch_macro_calendar_fmp()
        self.assertNotIn("error", out)
        self.assertEqual(out["stored"], 0)


class TheForexBlindMarkerClearsOnceASourceRunsTests(TestCase):
    """The marker exists to say UNCHECKED. Once a real source has written,
    it must get out of the way or it becomes the permanent flag it was
    added to prevent."""

    def test_a_forex_position_reads_blind_before_the_scraper_runs(self):
        from brain.position_review import _imminent_events
        rows = _imminent_events({"symbol": "EURUSD", "asset_class": "forex"})
        self.assertTrue(rows[0].get("blind"))

    def test_and_reads_the_real_calendar_after(self):
        from brain.position_review import _imminent_events
        from scraping.scrapers import macro_calendar
        from django.utils import timezone
        from datetime import timedelta

        soon = (timezone.now() + timedelta(hours=6)).strftime(
            "%Y-%m-%d %H:%M:%S")
        with patch.dict("os.environ", {"FMP_API_KEY": "k"}), \
             patch.object(macro_calendar.requests, "get",
                          return_value=_resp(
                              [{**STABLE_ROW, "date": soon}])):
            macro_calendar.fetch_macro_calendar_fmp()

        rows = _imminent_events({"symbol": "EURUSD", "asset_class": "forex"})
        self.assertFalse(any(r.get("blind") for r in rows))
        self.assertEqual(rows[0]["title"], "Non-Farm Payrolls")
