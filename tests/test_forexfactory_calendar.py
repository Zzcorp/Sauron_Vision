"""The macro calendar from Forex Factory (scraping/scrapers/macro_calendar.py,
2026-10-03): the free source the operator chose after FMP's economic
calendar answered 402 Payment Required for a month.

Pinned: the parse of Forex Factory's row shape (title, country-as-currency,
a New York offset on the date, High/Medium/Low/Holiday), the UTC
conversion, the Holiday and foreign-currency drops, re-runs that update,
one week failing while the other answers, the orchestrator asking Forex
Factory first and FMP only after it failed, the task carrying the source,
and every reader of the macro half seeing both sources.

Run with:  python manage.py test tests.test_forexfactory_calendar
"""
from datetime import datetime, timedelta, timezone as dt_tz
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

#: Two rows Forex Factory serves on a CPI week, one bank holiday, one
#: currency the fleet does not trade.
THIS_WEEK = [
    {"title": "CPI m/m", "country": "USD",
     "date": "2026-10-14T08:30:00-04:00", "impact": "High",
     "forecast": "0.3%", "previous": "0.4%",
     "url": "https://www.forexfactory.com/calendar?day=oct14.2026"},
    {"title": "German ZEW Economic Sentiment", "country": "EUR",
     "date": "2026-10-13T05:00:00-04:00", "impact": "Medium",
     "forecast": "38.2", "previous": "37.3", "url": ""},
    {"title": "Bank Holiday", "country": "JPY",
     "date": "2026-10-12T00:00:00-04:00", "impact": "Holiday",
     "forecast": "", "previous": "", "url": ""},
    {"title": "GDP q/y", "country": "CNY",
     "date": "2026-10-17T22:00:00-04:00", "impact": "High",
     "forecast": "4.8%", "previous": "5.0%", "url": ""},
]
NEXT_WEEK = [
    {"title": "BOC Rate Statement", "country": "CAD",
     "date": "2026-10-21T09:45:00-04:00", "impact": "High",
     "forecast": "", "previous": "", "url": ""},
]


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def _get_by_url(answers):
    """A requests.get stand-in answering each feed by its label."""
    def get(url, **kw):
        for label, payload in answers.items():
            if label in url:
                if isinstance(payload, Exception):
                    raise payload
                return _resp(payload)
        raise AssertionError(f"unexpected url {url}")
    return get


#: Two files, to pin the machinery that reads several and survives one
#: failing. Production reads one: Forex Factory publishes the current week
#: only (its "nextweek" answered 404 on the VPS, 2026-10-04).
TWO_FEEDS = (("thisweek", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"),
             ("nextweek", "https://nfs.faireconomy.media/ff_calendar_nextweek.json"))


class TheParseTests(TestCase):

    def _run(self, this=THIS_WEEK, nxt=NEXT_WEEK):
        from scraping.scrapers import macro_calendar as M
        with patch.object(M, "FF_FEEDS", TWO_FEEDS), \
             patch.object(M.requests, "get",
                          side_effect=_get_by_url({"thisweek": this,
                                                   "nextweek": nxt})) as g:
            out = M.fetch_macro_calendar_ff()
        return out, g

    def test_production_reads_the_current_week_only(self):
        """Measured 2026-10-04 03:20 UTC on the VPS: thisweek 139 rows,
        nextweek 404. A file that does not exist must not be asked every
        thirty minutes and logged as a failure every time."""
        from scraping.scrapers.macro_calendar import FF_FEEDS
        self.assertEqual([label for label, _url in FF_FEEDS], ["thisweek"])

    def test_the_currency_is_the_country_and_the_offset_is_applied(self):
        from market_data.models import EconomicEvent
        out, _ = self._run()
        self.assertEqual((out["parsed"], out["stored"], out["source"]),
                         (4, 3, "forexfactory"))
        self.assertEqual(out["weeks"], ["thisweek", "nextweek"])
        cpi = EconomicEvent.objects.get(source="forexfactory", title="CPI m/m")
        self.assertEqual(cpi.currency_affected, "USD")
        self.assertEqual(cpi.country, "USD")
        # 08:30 New York on daylight time is 12:30 UTC — four hours later,
        # never the same digits.
        self.assertEqual(cpi.datetime,
                         datetime(2026, 10, 14, 12, 30, tzinfo=dt_tz.utc))
        self.assertEqual((cpi.impact, cpi.forecast, cpi.previous, cpi.actual),
                         ("high", "0.3%", "0.4%", ""))

    def test_medium_is_low_holidays_and_foreign_currencies_are_dropped(self):
        from market_data.models import EconomicEvent
        self._run()
        zew = EconomicEvent.objects.get(source="forexfactory",
                                        title__startswith="German ZEW")
        self.assertEqual(zew.impact, "low")
        self.assertFalse(EconomicEvent.objects.filter(
            title="Bank Holiday").exists())
        self.assertFalse(EconomicEvent.objects.filter(
            currency_affected="CNY").exists())
        self.assertTrue(EconomicEvent.objects.filter(
            source="forexfactory", currency_affected="CAD").exists())

    def test_a_rerun_updates_rather_than_duplicates(self):
        from market_data.models import EconomicEvent
        self._run()
        revised = [{**THIS_WEEK[0], "forecast": "0.2%"}]
        self._run(this=revised, nxt=[])
        rows = EconomicEvent.objects.filter(source="forexfactory",
                                            title="CPI m/m")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().forecast, "0.2%")

    def test_the_feed_is_asked_as_a_browser(self):
        _, g = self._run()
        for call in g.call_args_list:
            self.assertIn("Mozilla", call.kwargs["headers"]["User-Agent"])
            self.assertEqual(call.kwargs["timeout"], 15)

    def test_one_week_failing_still_stores_the_other_and_says_so(self):
        out, _ = self._run(nxt=OSError("connection reset"))
        self.assertEqual((out["stored"], out["weeks"]), (2, ["thisweek"]))
        self.assertEqual(len(out["failures"]), 1)
        self.assertIn("nextweek", out["failures"][0])
        self.assertNotIn("error", out)

    def test_both_weeks_failing_is_an_error_never_an_empty_fortnight(self):
        out, _ = self._run(this=OSError("dns"), nxt=OSError("dns"))
        self.assertIn("error", out)
        self.assertEqual(out["stored"], 0)
        self.assertIn("thisweek: dns", out["error"])

    def test_a_payload_that_is_not_a_list_is_a_failure(self):
        out, _ = self._run(this={"error": "Access denied"},
                           nxt={"error": "Access denied"})
        self.assertIn("unexpected payload", out["error"])


class TheOrchestratorTests(TestCase):

    def test_forex_factory_first_and_fmp_never_asked_when_it_answers(self):
        from scraping.scrapers import macro_calendar as M
        with patch.object(M, "fetch_macro_calendar_ff",
                          return_value={"parsed": 4, "stored": 3,
                                        "source": "forexfactory",
                                        "weeks": ["thisweek", "nextweek"]}), \
             patch.object(M, "fetch_macro_calendar_fmp") as fmp:
            out = M.fetch_macro_calendar()
        self.assertEqual(out["source"], "forexfactory")
        fmp.assert_not_called()

    def test_fmp_stands_in_when_forex_factory_failed(self):
        from scraping.scrapers import macro_calendar as M
        with patch.object(M, "fetch_macro_calendar_ff",
                          return_value={"parsed": 0, "stored": 0,
                                        "source": "forexfactory",
                                        "error": "thisweek: 503"}), \
             patch.object(M, "fetch_macro_calendar_fmp",
                          return_value={"parsed": 9, "stored": 7}) as fmp:
            out = M.fetch_macro_calendar(days_ahead=10)
        fmp.assert_called_once_with(days_ahead=10)
        self.assertEqual((out["source"], out["stored"]), ("fmp_macro", 7))
        self.assertEqual(out["fallback_after"], "thisweek: 503")

    def test_both_failing_names_both(self):
        from scraping.scrapers import macro_calendar as M
        with patch.object(M, "fetch_macro_calendar_ff",
                          return_value={"parsed": 0, "stored": 0,
                                        "error": "thisweek: 503"}), \
             patch.object(M, "fetch_macro_calendar_fmp",
                          return_value={"parsed": 0, "stored": 0,
                                        "error": "stable: 402 Payment Required"}):
            out = M.fetch_macro_calendar()
        self.assertEqual(out["error"],
                         "forexfactory: thisweek: 503 | fmp: stable: 402 "
                         "Payment Required")

    def test_a_missing_fmp_key_is_a_detail_of_the_error_not_a_skip(self):
        """With a free primary source, "not configured" would be the wrong
        verdict for a feed that is down."""
        from scraping.scrapers import macro_calendar as M
        with patch.object(M, "fetch_macro_calendar_ff",
                          return_value={"parsed": 0, "stored": 0,
                                        "error": "thisweek: 503"}), \
             patch.object(M, "fetch_macro_calendar_fmp",
                          return_value={"parsed": 0, "stored": 0,
                                        "skipped": "no_api_key"}):
            out = M.fetch_macro_calendar()
        self.assertNotIn("skipped", out)
        self.assertEqual(out["error"],
                         "forexfactory: thisweek: 503 | fmp: skipped (no_api_key)")


class TheTaskAndTheCommandTests(TestCase):

    def setUp(self):
        from core.models import PlatformComponent
        for key in ("platform_master", "scraper_calendar"):
            PlatformComponent.objects.update_or_create(
                key=key, defaults={"name": key, "category": "system",
                                   "is_enabled": True})

    def test_the_task_asks_the_orchestrator_and_carries_the_source(self):
        from scraping.tasks import check_economic_calendar
        with patch("scraping.scrapers.earnings_calendar."
                   "fetch_earnings_calendar_fmp",
                   return_value={"parsed": 12, "stored": 12}), \
             patch("scraping.scrapers.macro_calendar.fetch_macro_calendar",
                   return_value={"parsed": 40, "stored": 22,
                                 "source": "forexfactory"}) as orch, \
             patch("scraping.scrapers.macro_calendar.fetch_macro_calendar_fmp") as fmp:
            out = check_economic_calendar()
        orch.assert_called_once()
        fmp.assert_not_called()
        self.assertEqual((out["status"], out["macro_parsed"],
                          out["macro_stored"], out["macro_source"]),
                         ("success", 40, 22, "forexfactory"))

    def test_the_command_names_the_source_and_the_weeks(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        with patch("scraping.scrapers.macro_calendar.fetch_macro_calendar",
                   return_value={"parsed": 40, "stored": 22,
                                 "source": "forexfactory",
                                 "weeks": ["thisweek", "nextweek"]}):
            call_command("fetch_macro_calendar", stdout=out)
        self.assertIn("parsed 40, stored 22", out.getvalue())
        self.assertIn("forexfactory, thisweek + nextweek", out.getvalue())

    def test_the_command_says_when_fmp_stood_in(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        with patch("scraping.scrapers.macro_calendar.fetch_macro_calendar",
                   return_value={"parsed": 9, "stored": 7,
                                 "source": "fmp_macro",
                                 "fallback_after": "thisweek: 503"}):
            call_command("fetch_macro_calendar", stdout=out)
        self.assertIn("Forex Factory failed (thisweek: 503); FMP answered",
                      out.getvalue())


class EveryReaderSeesBothSourcesTests(TestCase):

    def _ff_row(self, hours_ahead, currency="USD", impact="high"):
        from market_data.models import EconomicEvent
        return EconomicEvent.objects.create(
            source="forexfactory", title="CPI m/m", country=currency,
            currency_affected=currency, impact=impact,
            datetime=timezone.now() + timedelta(hours=hours_ahead))

    def test_the_blind_marker_is_disarmed_by_a_forex_factory_row(self):
        from brain.position_review import _imminent_events
        self._ff_row(hours_ahead=24 * 5)
        rows = _imminent_events({"symbol": "EURUSD", "asset_class": "forex"})
        self.assertEqual(rows, [])
        self._ff_row(hours_ahead=6)
        rows = _imminent_events({"symbol": "EURUSD", "asset_class": "forex"})
        self.assertEqual(rows[0]["title"], "CPI m/m")

    def test_news_risk_leg_c_counts_forex_factory_prints(self):
        from bot_program.news_risk import MACRO_SOURCES
        self.assertEqual(MACRO_SOURCES, ("forexfactory", "fmp_macro"))
        from scraping.scrapers.macro_calendar import MACRO_SOURCES as M
        self.assertEqual(M, MACRO_SOURCES)
        from brain.position_review import MACRO_SOURCES as P
        self.assertEqual(P, MACRO_SOURCES)

    def test_the_calendar_page_says_macro_arrived_from_forex_factory(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user("ff_cal_u", password="x")
        self.client.force_login(user)
        body = " ".join(
            self.client.get("/calendar/").content.decode().lower().split())
        self.assertIn("never delivered", body)
        self._ff_row(hours_ahead=30)
        body = " ".join(
            self.client.get("/calendar/").content.decode().lower().split())
        self.assertNotIn("never delivered", body)
        self.assertIn("from forex factory", body)


class TheInstantTests(SimpleTestCase):

    def test_either_source_s_spelling_lands_in_utc(self):
        from scraping.scrapers.macro_calendar import _event_datetime as f
        utc = dt_tz.utc
        self.assertEqual(f("2026-10-14T08:30:00-04:00"),
                         datetime(2026, 10, 14, 12, 30, tzinfo=utc))
        self.assertEqual(f("2026-09-04 12:30:00"),
                         datetime(2026, 9, 4, 12, 30, tzinfo=utc))
        self.assertEqual(f("2026-09-04"), datetime(2026, 9, 4, tzinfo=utc))
        self.assertEqual(f("2026-09-04T12:30:00Z"),
                         datetime(2026, 9, 4, 12, 30, tzinfo=utc))
        self.assertEqual(f(datetime(2026, 9, 4, 12, 30, tzinfo=utc)),
                         datetime(2026, 9, 4, 12, 30, tzinfo=utc))
        self.assertIsNone(f("not a date"))
        self.assertIsNone(f(""))
        self.assertIsNone(f(None))
