"""Faults that find you.

`PlatformComponent` has recorded every task's outcome since the day it was
written and nothing has ever sent that anywhere. Every fault found on
2026-08-28 was already in that table and was discovered by a human opening
a page: the calendar had said `not configured: no_api_key` for months, the
OANDA streamer had never started, and `FINNHUB_API_KEY` was set to the
empty string.

The digest's difficulty is not finding faults — they are sitting in a
column. It is being worth reading on the two hundredth morning. These tests
mostly hold the things it must NOT say.

Run with:  python manage.py test tests.test_component_digest
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone


class _ComponentsOnly(TestCase):
    """Silences the FEED half of the digest.

    On a bare test database no feed has ever written a quote, so every
    keyless one is legitimately `never` — five extra faults that are the
    right answer for a fresh deployment and pure noise in a test about
    component rows. The feed half has its own class below.
    """

    def setUp(self):
        p = patch("core.component_digest._feed_faults", return_value=[])
        p.start()
        self.addCleanup(p.stop)


def _component(key, **kw):
    from core.platform_control import PlatformComponent
    defaults = dict(name=key.replace("_", " ").title(), category="scraper",
                    is_enabled=True, last_run_at=timezone.now(),
                    last_status="success", last_message="")
    defaults.update(kw)
    return PlatformComponent.objects.update_or_create(
        key=key, defaults=defaults)[0]


class ItReportsWhatAnOperatorCanActOnTests(_ComponentsOnly):

    def test_a_failing_component_is_reported(self):
        from core.component_digest import collect_faults
        _component("scraper_x", last_status="error",
                   last_message="HTTP 403 from the vendor")
        out = collect_faults()
        self.assertEqual([f["key"] for f in out["errors"]], ["scraper_x"])
        self.assertIn("403", out["errors"][0]["message"])

    def test_a_warning_is_reported_separately_from_an_error(self):
        """`warning` is the state that hid the calendar for months: the task
        ran, raised nothing, and did not do its job."""
        from core.component_digest import collect_faults
        _component("scraper_calendar", last_status="warning",
                   last_message="not configured: no_api_key")
        out = collect_faults()
        self.assertEqual(out["errors"], [])
        self.assertEqual([f["key"] for f in out["warnings"]],
                         ["scraper_calendar"])

    def test_a_component_that_stopped_is_reported_however_green_it_looks(self):
        """A beat that stops firing leaves last_status frozen at whatever it
        was the last time it worked, so a healthy-looking green row can be
        three weeks stale. That is the failure a status column cannot
        express by itself."""
        from core.component_digest import collect_faults
        _component("scraper_frozen", last_status="success",
                   last_run_at=timezone.now() - timedelta(days=8))
        out = collect_faults()
        self.assertEqual([f["key"] for f in out["silent"]],
                         ["scraper_frozen"])
        self.assertIn("8d", out["silent"][0]["message"])

    def test_silence_is_reported_INSTEAD_of_the_stale_status(self):
        """Printing "success — last run 8 days ago" under a heading that
        says FAILING is how a digest teaches its reader to distrust it."""
        from core.component_digest import collect_faults
        _component("scraper_both", last_status="error",
                   last_message="old failure",
                   last_run_at=timezone.now() - timedelta(days=8))
        out = collect_faults()
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["silent"]), 1)

    def test_a_component_that_never_ran_says_so(self):
        from core.component_digest import collect_faults
        _component("scraper_never", last_run_at=None, last_status="")
        out = collect_faults()
        self.assertIn("never run", out["silent"][0]["message"])


class WhatItDeliberatelyStaysQuietAboutTests(_ComponentsOnly):
    """A digest that reports everything is a digest nobody reads by week
    three — and then the one that matters is skipped with the rest."""

    def test_a_switched_off_component_is_not_nagged_about(self):
        """An operator who disabled something meant it."""
        from core.component_digest import collect_faults
        _component("scraper_off", is_enabled=False, last_status="error",
                   last_message="boom")
        self.assertEqual(collect_faults()["errors"], [])

    def test_a_healthy_component_is_not_mentioned(self):
        from core.component_digest import collect_faults
        _component("scraper_fine")
        out = collect_faults()
        self.assertEqual(out["errors"] + out["warnings"] + out["silent"], [])

    def test_a_long_cadence_task_is_not_reported_daily(self):
        """A weekly task is not silent for six days; it is weekly."""
        from core.component_digest import collect_faults
        _component("scraper_cot", last_run_at=timezone.now() - timedelta(days=5))
        self.assertEqual(collect_faults()["silent"], [])

    def test_a_healthy_platform_sends_nothing_at_all(self):
        """A daily message that is usually empty gets filtered, and the one
        that matters is filtered with it."""
        from core.component_digest import collect_faults, render_digest
        _component("scraper_fine")
        title, body = render_digest(collect_faults())
        self.assertIsNone(title)
        self.assertIsNone(body)


class TheFeedsRideTheSameDigestTests(TestCase):

    def test_a_configured_feed_that_never_delivered_is_reported(self):
        import os

        from core.component_digest import collect_faults
        saved = os.environ.get("FINNHUB_API_KEY")
        os.environ["FINNHUB_API_KEY"] = "present"
        try:
            keys = [f["key"] for f in collect_faults()["feeds"]]
        finally:
            if saved is None:
                os.environ.pop("FINNHUB_API_KEY", None)
            else:
                os.environ["FINNHUB_API_KEY"] = saved
        self.assertIn("finnhub_ws", keys)

    def test_an_unconfigured_feed_is_not(self):
        """`off` is the system working. A digest that nags about a feed
        nobody wants trains its reader to skip it."""
        import os

        from core.component_digest import collect_faults
        saved = {k: os.environ.pop(k, None)
                 for k in ("OANDA_API_KEY", "OANDA_ACCOUNT_ID")}
        try:
            keys = [f["key"] for f in collect_faults()["feeds"]]
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        self.assertNotIn("oanda_stream", keys)


class TheMessageItselfTests(_ComponentsOnly):

    def test_it_names_the_count_in_the_title(self):
        from core.component_digest import collect_faults, render_digest
        _component("scraper_a", last_status="error", last_message="boom")
        _component("scraper_b", last_status="warning", last_message="nothing stored")
        title, body = render_digest(collect_faults())
        self.assertIn("need you", title)
        self.assertIn("FAILING", body)
        self.assertIn("RAN BUT DID NOTHING", body)

    def test_it_never_raises_on_an_unreadable_table(self):
        """A digest that can break a beat is worse than no digest."""
        from unittest.mock import patch

        from core.component_digest import collect_faults
        with patch("core.platform_control.PlatformComponent.objects.filter",
                   side_effect=RuntimeError("db gone")):
            out = collect_faults()
        self.assertEqual(out["checked"], 0)

    def test_the_send_path_reports_what_it_found_even_if_nobody_heard(self):
        """A run that found problems but could not deliver them must be
        distinguishable from a quiet day."""
        from unittest.mock import patch

        from core.component_digest import send_component_digest
        _component("scraper_a", last_status="error", last_message="boom")
        with patch("alerts.models.Notification.create_for_user",
                   side_effect=RuntimeError("no channel")):
            out = send_component_digest()
        self.assertEqual(out["faults"], 1)
        self.assertEqual(out["sent"], 0)


class TheDigestCannotBeSilencedByWhatItWatchesTests(TestCase):

    def test_it_is_not_gated_by_a_component_row(self):
        """Every other periodic task is gated by its own PlatformComponent,
        which is right. This one's job is to report the state of those rows,
        and a health check that the same switch can silence goes quiet
        exactly when the platform does."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "core" / "tasks.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("guarded_task", src.split('"""')[2]
                         if src.count('"""') > 2 else src.replace(
                             "guarded_task", "", 0))
        # The decorator itself must be absent from the task definition.
        after_docstring = src.split('"""')[-1]
        self.assertNotIn("@guarded_task", after_docstring)

    def test_the_beat_actually_schedules_it(self):
        from config.celery import app
        self.assertIn("component-digest", app.conf.beat_schedule)
        self.assertEqual(
            app.conf.beat_schedule["component-digest"]["task"],
            "core.tasks.send_component_digest_task")
