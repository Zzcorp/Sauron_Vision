"""The calendar says what it is and why it is empty.

"calendar still not working" — the third such report, and the first two
fixes touched reporting and ordering. Neither made a source answer, because
there are two separate problems and only one of them is a bug.

(1) The ingest is credential-gated. `fetch_earnings_calendar_fmp` reads
    FMP_API_KEY, and with none returns {"parsed":0,"stored":0,
    "skipped":"no_api_key"} before its first HTTP call. The component row
    records exactly that. Nothing on the page read it, so the empty state
    printed "Scraper will populate this automatically" — a promise the
    platform cannot keep — for that case, for a provider refusing the
    request, and for a genuinely quiet fortnight alike. One sentence for
    three different failures.

(2) The page is not an economic calendar. The ONLY writer of EconomicEvent
    anywhere in this codebase is the earnings scraper, which stamps
    title="<SYMBOL> Earnings", country="US", impact="high", source="fmp".
    No FOMC, CPI, NFP or rate-decision ingestion exists — no module produces
    one. A page headed ECONOMIC CALENDAR with Forecast/Previous/Actual
    columns promises a macro feed that structurally cannot arrive, and an
    operator reading an empty table concludes the platform is broken rather
    than that it never covered macro at all.

Run with:  python manage.py test tests.test_calendar_truth
"""
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase


@contextmanager
def _env(**pairs):
    """Set or unset environment variables, and put every one of them back.

    The suite runs SERIALLY IN ONE PROCESS. A test that pops FMP_API_KEY and
    restores it only `if saved is not None` leaves it DELETED for every test
    that follows — including the ones asserting a configured calendar, which
    then pass or fail on test ordering rather than on the code.
    """
    saved = {k: os.environ.get(k) for k in pairs}
    try:
        for k, v in pairs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def page_source():
    return (Path(settings.BASE_DIR) / "templates" / "dashboard"
            / "economic_calendar.html").read_text(encoding="utf-8")


class TheEmptyStateNamesItsCauseTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("cal_u", password="x")
        self.client.force_login(self.user)

    def test_the_old_promise_is_gone(self):
        """It is the single most misleading string in this failure.

        Asserted against the RENDERED page, not the template source: the
        comment explaining why the sentence was removed quotes it, and a
        test that cannot tell a comment from a promise is reading the wrong
        artefact."""
        body = self.client.get("/calendar/").content.decode()
        self.assertNotIn("Scraper will populate this automatically", body)

    def test_an_unconfigured_source_says_so_by_name(self):
        with _env(FMP_API_KEY=None):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn("NOT CONFIGURED", body)
        self.assertIn("FMP_API_KEY", body)

    def test_a_configured_source_that_never_ran_says_that_instead(self):
        with _env(FMP_API_KEY="present"):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn("HAS NOT RUN YET", body)

    def test_a_provider_refusal_is_reported_as_one(self):
        """A 403 from FMP and a quiet fortnight are not the same news."""
        from django.utils import timezone
        with _env(FMP_API_KEY="present"), patch(
                "dashboard.views.calendar_source_state",
                return_value={"configured": True, "enabled": True,
                              "status": "error",
                              "message": "HTTP 403 from FMP",
                              "last_run": timezone.now()}):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn("REFUSED", body)
        self.assertIn("403", body)

    def test_a_switched_off_scraper_says_so(self):
        """PlatformComponent.is_enabled defaults to False and the seeder
        does not set it, so on a fresh install the beat fires, the gate
        refuses, and the page said "scheduled every 30 minutes" about a task
        that had never once been allowed to run."""
        with _env(FMP_API_KEY="present"), patch(
                "dashboard.views.calendar_source_state",
                return_value={"configured": True, "enabled": False,
                              "status": "", "message": "",
                              "last_run": None}):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn("SWITCHED OFF", body)

    def test_a_warning_run_reports_its_own_message(self):
        """`judge_result` writes "warning" for the two outcomes that
        actually explain an empty table — "not configured: no_api_key" (the
        WORKER lacks the key even though the web container has it) and
        "handled N rows and stored none". Branching only on "error" printed
        "the fetch succeeded" over both."""
        from django.utils import timezone
        with _env(FMP_API_KEY="present"), patch(
                "dashboard.views.calendar_source_state",
                return_value={"configured": True, "enabled": True,
                              "status": "warning",
                              "message": "not configured: no_api_key",
                              "last_run": timezone.now()}):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn("DID NOT DELIVER", body)
        self.assertIn("no_api_key", body)

    def test_a_successful_run_with_nothing_to_report_says_that(self):
        from django.utils import timezone
        with patch("dashboard.views.calendar_source_state",
                   return_value={"configured": True, "enabled": True,
                                 "status": "success",
                                 "message": "", "last_run": timezone.now()}):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn("NO EARNINGS IN THE WINDOW", body)

    def test_the_state_never_raises_on_a_missing_component_row(self):
        """A deployment where the ingest has not run yet is its own honest
        answer, not a 500."""
        from dashboard.views import calendar_source_state
        from core.models import PlatformComponent
        PlatformComponent.objects.filter(key="scraper_calendar").delete()
        state = calendar_source_state()
        self.assertIn("configured", state)
        self.assertIsNone(state["last_run"])


class ThePageIsHonestAboutItsScopeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("cal_scope_u", password="x")
        self.client.force_login(self.user)

    def test_the_writers_are_the_two_calendar_scrapers(self):
        """This fired exactly as designed.

        It used to assert `earnings_calendar.py` was the ONLY writer, with
        a docstring saying that if a macro ingest were ever added the test
        should fail and the page title change back. A macro ingest was
        added, it failed, and the title changed — the page now reads
        ECONOMIC CALENDAR and its scope note follows the DATA rather than
        the code, because a scraper that exists is not a scraper that has
        delivered.

        The tripwire is kept, widened to exactly two: a THIRD writer would
        mean some other module is stamping rows into this table under its
        own conventions, and the page's claim about its own scope would go
        stale again without anyone noticing."""
        import subprocess
        root = Path(settings.BASE_DIR)
        hits = []
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if "tests" in parts or "migrations" in parts:
                continue
            if ".venv" in parts or "SV_V" in parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "EconomicEvent.objects.create" in text or \
               "EconomicEvent.objects.update_or_create" in text:
                hits.append(path.name)
        self.assertEqual(sorted(hits),
                         ["earnings_calendar.py", "macro_calendar.py"], hits)

    def test_the_title_says_what_the_pipeline_delivers(self):
        self.assertIn("ECONOMIC CALENDAR", page_source())

    def test_the_page_says_what_it_does_not_cover(self):
        """With no macro row written, the page must still say macro does
        not appear — a scraper that EXISTS is not a scraper that has
        DELIVERED, and promising coverage on the strength of the code
        would replace one false claim with another."""
        # Whitespace-normalised: the sentence wraps in the template, so a
        # raw substring check would be asserting the line breaks rather
        # than the claim.
        body = " ".join(
            self.client.get("/calendar/").content.decode().lower().split())
        self.assertIn("fomc", body)
        self.assertIn("never delivered", body)

    def test_and_stops_saying_so_once_macro_actually_arrives(self):
        """The claim follows the data in both directions, or the note
        becomes the next stale thing on the page."""
        from django.utils import timezone
        from market_data.models import EconomicEvent
        EconomicEvent.objects.create(
            source="fmp_macro", title="Non-Farm Payrolls", country="US",
            datetime=timezone.now(), impact="high",
            currency_affected="USD")
        body = " ".join(
            self.client.get("/calendar/").content.decode().lower().split())
        self.assertNotIn("never delivered", body)
        self.assertIn("macro releases", body)

    def test_the_refresh_cell_states_the_real_cadence(self):
        """It said DAILY / 'fetched 06:00 UTC'. The beat runs it every 30
        minutes, so an operator waited until tomorrow for a fix that would
        have landed in half an hour."""
        body = self.client.get("/calendar/").content.decode()
        self.assertNotIn("fetched 06:00 UTC", body)
        self.assertNotIn(">DAILY<", body)


class OneRunOneVerdictTests(TestCase):
    """`task_gate` wrote 'warning' to the component row while the task's own
    return value said 'success'. Anything reading the task result saw a
    healthy calendar that had never fetched anything."""

    def setUp(self):
        # The gate short-circuits to {"status": "skipped"} unless both the
        # master switch and this component are on, so the task body — the
        # thing under test — would never run.
        from core.models import PlatformComponent
        for key in ("platform_master", "scraper_calendar"):
            PlatformComponent.objects.update_or_create(
                key=key, defaults={"name": key, "category": "system",
                                   "is_enabled": True})

    def test_a_skipped_run_does_not_report_success(self):
        from scraping.tasks import check_economic_calendar
        with patch("scraping.scrapers.earnings_calendar.fetch_earnings_calendar_fmp",
                   return_value={"parsed": 0, "stored": 0,
                                 "skipped": "no_api_key"}):
            out = check_economic_calendar()
        self.assertEqual(out["status"], "warning")

    def test_an_error_still_reports_error(self):
        from scraping.tasks import check_economic_calendar
        with patch("scraping.scrapers.earnings_calendar.fetch_earnings_calendar_fmp",
                   return_value={"parsed": 0, "stored": 0,
                                 "error": "HTTP 403"}):
            out = check_economic_calendar()
        self.assertEqual(out["status"], "error")

    def test_a_real_fetch_still_reports_success(self):
        from scraping.tasks import check_economic_calendar
        with patch("scraping.scrapers.earnings_calendar."
                   "fetch_earnings_calendar_fmp",
                   return_value={"parsed": 12, "stored": 12}), \
                patch("scraping.scrapers.macro_calendar."
                      "fetch_macro_calendar_fmp",
                      return_value={"parsed": 3, "stored": 3}):
            out = check_economic_calendar()
        self.assertEqual(out["status"], "success")


class TheScraperStillRefusesToInventTests(TestCase):

    def test_no_key_means_no_http_call_and_a_named_skip(self):
        from scraping.scrapers.earnings_calendar import (
            fetch_earnings_calendar_fmp,
        )
        with _env(FMP_API_KEY=None):
            with patch("scraping.scrapers.earnings_calendar.requests.get") as g:
                out = fetch_earnings_calendar_fmp(days_ahead=14)
            g.assert_not_called()
        self.assertEqual(out["skipped"], "no_api_key")
        self.assertEqual(out["stored"], 0)
