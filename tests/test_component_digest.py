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


def _seeded_long_ago(row, days=90):
    """A row seeded long before today. Since 2026-09-26 a component that
    has never run is judged from the day its row was created, and
    `created_at` is auto_now_add, so a test moves it with update()."""
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(days=days))
    row.refresh_from_db()
    return row


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
        # A key a beat entry writes (daily, 22:30 UTC): since 2026-09-26
        # only a component with a rhythm can fall behind it.
        _component("scraper_eod", last_status="success",
                   last_run_at=timezone.now() - timedelta(days=8))
        out = collect_faults()
        self.assertEqual([f["key"] for f in out["silent"]],
                         ["scraper_eod"])
        self.assertIn("8d", out["silent"][0]["message"])

    def test_silence_is_reported_INSTEAD_of_the_stale_status(self):
        """Printing "success — last run 8 days ago" under a heading that
        says FAILING is how a digest teaches its reader to distrust it."""
        from core.component_digest import collect_faults
        _component("scraper_sec", last_status="error",  # daily beat
                   last_message="old failure",
                   last_run_at=timezone.now() - timedelta(days=8))
        out = collect_faults()
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["silent"]), 1)

    def test_a_component_that_never_ran_says_so(self):
        from core.component_digest import collect_faults
        # A key the beat writes every four hours, seeded long enough ago
        # to have missed its first run: a row younger than its window is
        # judged from the day it was seeded (2026-09-26).
        _seeded_long_ago(_component("scraper_fred", last_run_at=None,
                                    last_status=""))
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
        # The words moved to the English house style on 2026-09-26.
        self.assertEqual(title, "⊙ Sauron — 2 things need attention")
        self.assertIn("Failing (1)", body)
        self.assertIn("Ran but did nothing (1)", body)

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


# ── 2026-09-26: the digest stops crying wolf ─────────────────────────────
#
# The 2026-09-26 digest sent nineteen items and one of them was a fault.
# Every test below holds a false alarm down or keeps a real fault up, and
# its docstring says which.

#: The five weekly beats the daily window called "stopped" five or six
#: mornings out of seven (config/celery.py: Sat 10:00, Sat 14:00, Sun 18:00, Sun 04:00
#: and Sun 06:00 UTC).
WEEKLY_KEYS = ("agent_weekly_review", "agent_optimization",
               "agent_monday_plan", "pipeline_meta_allocator",
               "pipeline_pattern_miner")

#: A switch, per-event gates and a step no beat entry writes. Each read
#: "has never run" on 2026-09-26, which is true of a switch forever.
UNSCHEDULED_KEYS = ("platform_master", "feature_ai_pretrade_gate",
                    "generator_auto_research", "pipeline_event_engine",
                    "pipeline_ai_journal")


def _days_ago(days):
    return timezone.now() - timedelta(days=days)


class TheBeatDecidesWhoCanBeSilentTests(_ComponentsOnly):
    """Silence is judged against each component's own beat, read off
    config/celery.py, and only for a component a beat entry writes."""

    def test_a_weekly_beat_is_not_stopped_five_or_six_days_out(self):
        """False alarm, held down: five of the nineteen."""
        from core.component_digest import collect_faults
        for days in (5, 6):
            for key in WEEKLY_KEYS:
                _component(key, last_run_at=_days_ago(days))
            self.assertEqual(collect_faults()["silent"], [],
                             "%d days after a weekly run" % days)

    def test_a_weekly_beat_is_stopped_nine_days_out(self):
        """Real fault, kept up: a weekly beat that missed its week."""
        from core.component_digest import collect_faults
        for key in WEEKLY_KEYS:
            _component(key, last_run_at=_days_ago(9))
        silent = collect_faults()["silent"]
        self.assertEqual(sorted(f["key"] for f in silent),
                         sorted(WEEKLY_KEYS))
        for f in silent:
            self.assertIn("last ran 9d ago", f["message"])
            self.assertIn("weekly", f["message"])

    def test_the_master_switch_never_reads_has_never_run(self):
        """False alarm, held down: nothing schedules a switch, so nothing
        can find it late — and a digest of nothing is not sent."""
        from core.component_digest import collect_faults, render_digest
        _seeded_long_ago(_component("platform_master", category="system",
                                    last_run_at=None, last_status=""))
        out = collect_faults()
        self.assertEqual(out["silent"] + out["errors"] + out["warnings"], [])
        self.assertEqual(render_digest(out), (None, None))

    def test_no_switch_or_event_gate_is_judged_for_silence(self):
        """False alarm, held down: four more of the nineteen."""
        from core.component_digest import collect_faults
        for key in UNSCHEDULED_KEYS:
            _seeded_long_ago(_component(key, last_run_at=None,
                                        last_status=""))
        self.assertEqual(collect_faults()["silent"], [])

    def test_an_unscheduled_component_that_fails_is_still_reported(self):
        """Real fault, kept up: not judged for silence is not exempt."""
        from core.component_digest import collect_faults
        _component("pipeline_event_engine", last_status="error",
                   last_message="dispatch raised KeyError: 'payload'",
                   last_run_at=_days_ago(3))
        out = collect_faults()
        self.assertEqual([f["key"] for f in out["errors"]],
                         ["pipeline_event_engine"])
        self.assertIn("KeyError", out["errors"][0]["message"])

    def test_a_beat_scheduled_key_that_never_ran_still_appears(self):
        """Real fault, kept up: the calendar's beat fires every thirty
        minutes, so a row seeded long ago that has never run is a beat that
        never reached a worker."""
        from core.component_digest import collect_faults
        _seeded_long_ago(_component("scraper_calendar", last_run_at=None,
                                    last_status=""))
        silent = collect_faults()["silent"]
        self.assertEqual([f["key"] for f in silent], ["scraper_calendar"])
        self.assertIn("has never run", silent[0]["message"])
        self.assertIn("every 30 minutes", silent[0]["message"])

    def test_a_monthly_beat_seeded_mid_month_is_not_late_before_its_first_run(self):
        """False alarm, held down: agent_horizon fires on the 1st at 04:45
        UTC and its row was seeded after the 1st, so "has never run" was
        true and not a fault. Seeded forty days ago and still never run,
        it is late — and said so."""
        from core.component_digest import collect_faults
        row = _seeded_long_ago(_component("agent_horizon", category="agent",
                                          last_run_at=None, last_status=""),
                               days=14)
        self.assertEqual(collect_faults()["silent"], [])
        _seeded_long_ago(row, days=40)
        silent = collect_faults()["silent"]
        self.assertEqual([f["key"] for f in silent], ["agent_horizon"])
        self.assertIn("has never run (monthly)", silent[0]["message"])

    def test_a_monthly_beat_is_judged_monthly(self):
        """Both at once: twenty days after a monthly run is on time; forty
        is a month missed."""
        from core.component_digest import collect_faults
        row = _component("agent_horizon", category="agent",
                         last_run_at=_days_ago(20))
        self.assertEqual(collect_faults()["silent"], [])
        row.last_run_at = _days_ago(40)
        row.save(update_fields=["last_run_at"])
        self.assertEqual([f["key"] for f in collect_faults()["silent"]],
                         ["agent_horizon"])

    def test_a_daily_beat_quiet_for_two_days_is_reported(self):
        """Real fault, kept up."""
        from core.component_digest import collect_faults
        _component("scraper_sec", last_run_at=_days_ago(2))
        silent = collect_faults()["silent"]
        self.assertEqual([f["key"] for f in silent], ["scraper_sec"])
        self.assertIn("last ran 2d ago (daily)", silent[0]["message"])

    def test_the_fifteen_minute_sync_keeps_the_daily_floor(self):
        """Real fault, kept up, and no sooner: all three broker walks
        stopping is reported once the row has been quiet past the 26-hour
        floor, never on a single missed beat."""
        from core.component_digest import collect_faults
        row = _component("broker_account_sync", category="pipeline",
                         last_run_at=timezone.now() - timedelta(hours=20))
        self.assertEqual(collect_faults()["silent"], [])
        row.last_run_at = timezone.now() - timedelta(hours=27)
        row.save(update_fields=["last_run_at"])
        silent = collect_faults()["silent"]
        self.assertEqual([f["key"] for f in silent], ["broker_account_sync"])
        self.assertIn("every 15 minutes", silent[0]["message"])

    def test_a_night_task_that_missed_one_run_is_in_the_next_digest(self):
        """Real fault, kept up, and no later than before: the rule actuator
        beats at 03:00 UTC, so at the 07:00 digest after one missed run it
        has been quiet 28 hours. A beat of a day or less keeps the 26-hour
        floor; 1.2 days plus two hours would have waited another morning."""
        from core.component_digest import collect_faults
        row = _component("pipeline_actuator", category="pipeline",
                         last_run_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(collect_faults()["silent"], [])
        row.last_run_at = timezone.now() - timedelta(hours=28)
        row.save(update_fields=["last_run_at"])
        silent = collect_faults()["silent"]
        self.assertEqual([f["key"] for f in silent], ["pipeline_actuator"])
        self.assertIn("last ran 28h ago (daily)", silent[0]["message"])

    def test_a_four_hourly_crontab_is_judged_every_four_hours(self):
        """Real fault, kept up: the share allocator's crontab (minute 5,
        hour */4) fires six times a day. Twenty-eight quiet hours are past
        its 26-hour window, the health page already calls it failing, and
        the words must name its own beat, never "(daily)"."""
        from core.component_digest import collect_faults
        _component("pipeline_share_allocator", category="pipeline",
                   name="Share Allocator",
                   last_run_at=timezone.now() - timedelta(hours=28))
        silent = collect_faults()["silent"]
        self.assertEqual([f["key"] for f in silent],
                         ["pipeline_share_allocator"])
        self.assertIn("(every 4 hours)", silent[0]["message"])
        self.assertNotIn("daily", silent[0]["message"])

    def test_a_beat_entry_naming_no_task_is_reported_not_dropped(self):
        """Real fault, kept up: a function renamed with its old name left
        on the beat. The beat keeps sending the name, the worker discards
        it, and the row freezes at its last "success". The component falls
        out of the cadence map and can no longer be called stopped, so the
        entry itself is reported, and logged."""
        from config.celery import app
        from core.component_digest import collect_faults, render_digest
        _component("scraper_eod", name="EOD Prices",
                   last_run_at=_days_ago(10))
        entry = dict(app.conf.beat_schedule["fetch-eod-prices-full-universe"])
        entry["task"] = "market_data.tasks.fetch_eod_renamed_away"
        with patch.dict(app.conf.beat_schedule,
                        {"fetch-eod-prices-full-universe": entry}), \
                self.assertLogs("core.component_digest", "WARNING") as logs:
            out = collect_faults()
        self.assertEqual(out["silent"], [])
        warned = [f for f in out["warnings"] if f["key"] == "beat_schedule"]
        self.assertEqual(len(warned), 1)
        self.assertEqual(
            warned[0]["message"],
            "beat entry fetch-eod-prices-full-universe names a task no "
            "worker knows (market_data.tasks.fetch_eod_renamed_away)")
        self.assertTrue(any("fetch_eod_renamed_away" in m
                            for m in logs.output))
        title, body = render_digest(out)
        self.assertEqual(title, "⊙ Sauron — 1 thing needs attention")
        self.assertIn("• Digest cadence map — beat entry "
                      "fetch-eod-prices-full-universe names a task no "
                      "worker knows (market_data.tasks.fetch_eod_renamed_away)",
                      body.splitlines())

    def test_an_unreadable_beat_is_said_out_loud(self):
        """Real fault, kept up: a digest that lost its silence check must
        not read like a healthy platform."""
        from core.component_digest import collect_faults
        _component("scraper_eod", last_run_at=_days_ago(8))
        with patch("core.component_digest.beat_periods", return_value=None):
            out = collect_faults()
        self.assertEqual(out["silent"], [])
        self.assertEqual([f["key"] for f in out["warnings"]],
                         ["beat_schedule"])


class TheCadenceMapIsReadOffTheBeatTests(TestCase):
    """beat_periods reads the schedule the workers run, through the key
    core.task_gate.guarded_task stamps on each task's wrapper — no second
    list of cadences to drift out of step."""

    def test_each_component_gets_its_own_beat_s_period(self):
        from core.component_digest import beat_periods
        p = beat_periods()
        for key in WEEKLY_KEYS:
            self.assertEqual(p[key], 168.0, key)
        self.assertEqual(p["agent_horizon"], 744.0)
        self.assertEqual(p["scraper_eod"], 24.0)
        self.assertAlmostEqual(p["scraper_calendar"], 0.5)
        self.assertAlmostEqual(p["broker_account_sync"], 0.25)

    def test_the_most_frequent_beat_sets_a_shared_row_s_period(self):
        """The row moves whenever any of its tasks runs."""
        from core.component_digest import beat_periods
        p = beat_periods()
        # the 4-hourly strategy review, beside a weekly rebalance
        self.assertAlmostEqual(p["agent_strategy"], 4.0)
        # the 5-minute bot tick, beside the daily reconcile and chains
        self.assertAlmostEqual(p["pipeline_asset_bots"], 300 / 3600)

    def test_nothing_schedules_a_switch_or_an_event_gate(self):
        from core.component_digest import beat_periods
        p = beat_periods()
        for key in UNSCHEDULED_KEYS:
            self.assertNotIn(key, p)

    def test_a_crontab_s_period_is_its_widest_gap(self):
        """A crontab says when, not how often: the period is the widest gap
        between two of its fire times, round the week's end."""
        from celery.schedules import crontab

        from core.component_digest import _period_hours, beat_periods
        cases = (
            (crontab(minute=5, hour="*/4"), 4.0),
            (crontab(minute="*/15"), 0.25),
            (crontab(hour=3, minute=0), 24.0),
            (crontab(hour="13-20", minute=0), 17.0),
            (crontab(hour=10, minute=0, day_of_week="sat"), 168.0),
            (crontab(hour=22, minute=0, day_of_week="mon-fri"), 72.0),
            (crontab(hour=4, minute=45, day_of_month=1), 744.0),
        )
        for schedule, hours in cases:
            self.assertAlmostEqual(_period_hours(schedule), hours,
                                   msg=repr(schedule))
        self.assertAlmostEqual(beat_periods()["pipeline_share_allocator"],
                               4.0)

    def test_today_s_beat_places_every_entry(self):
        """False alarm, held down: on the schedule the workers run, every
        entry resolves, so the cadence-map line never shows on a healthy
        morning."""
        from core.component_digest import beat_periods
        unplaced = []
        self.assertTrue(beat_periods(unresolved=unplaced))
        self.assertEqual(unplaced, [])

    def test_the_gate_names_its_component_on_the_task_celery_runs(self):
        from bot_program.tasks import sync_etoro_accounts
        from brain.tasks import run_horizon
        self.assertEqual(sync_etoro_accounts.__wrapped__.component_key,
                         "broker_account_sync")
        self.assertEqual(sync_etoro_accounts.run.component_key,
                         "broker_account_sync")
        self.assertEqual(run_horizon.__wrapped__.component_key,
                         "agent_horizon")

    def test_every_gated_beat_entry_is_in_the_map(self):
        """Real faults, kept reachable. Read off the SOURCE, independently
        of the stamp: a beat entry whose function carries the gate must put
        the gate's key in the map, or that component could stop and never
        be called stopped. Every entry must name a task the workers
        register and a function its module defines — an entry this check
        cannot find fails here, it is never skipped and so never quietly
        uncounted. (No literal key in this docstring: the registry test
        reads every guarded_task call in the tree.)"""
        import importlib
        import inspect
        import re

        from config.celery import app
        from core.component_digest import beat_periods
        app.loader.import_default_modules()
        p = beat_periods()
        seen = 0
        for name, entry in app.conf.beat_schedule.items():
            task = entry["task"]
            self.assertIn(task, app.tasks, name)
            module, _, attr = task.rpartition(".")
            src = inspect.getsource(importlib.import_module(module))
            self.assertRegex(src, r"\ndef %s\(" % re.escape(attr), name)
            m = re.search(r'@guarded_task\("([^"]+)"\)\s*\n(?:@[^\n]*\n)*'
                          r'def %s\(' % re.escape(attr), src)
            if m:
                seen += 1
                self.assertIn(m.group(1), p, task)
        self.assertGreaterEqual(seen, 50)


class TheSharedBrokerRowTests(_ComponentsOnly):
    """broker_account_sync is the row of three walks — IBKR, Saxo, eToro —
    each every fifteen minutes. On 2026-09-26 the two with nothing to read
    wrote "ran and produced nothing" over eToro's verdict. The walks run
    here THROUGH the gate (a task's __wrapped__ is the gate's wrapper)."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        from django.core.cache import cache
        cache.clear()
        _component("platform_master", category="system")
        _component("broker_account_sync", category="pipeline",
                   last_run_at=None, last_status="")
        self.user = User.objects.create_user("dg_sync", password="x")

    def _row(self):
        from core.platform_control import PlatformComponent
        return PlatformComponent.objects.get(key="broker_account_sync")

    def _ibkr_pass(self, trader=None, available=True):
        from unittest.mock import MagicMock

        from bot_program.tasks import sync_broker_account
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=available), \
             patch("bot_program.engine.ibkr_client.IBKRTrader",
                   return_value=trader or MagicMock()):
            return sync_broker_account.__wrapped__()

    def _saxo_pass(self):
        from bot_program.tasks import sync_saxo_accounts
        return sync_saxo_accounts.__wrapped__()

    def _etoro_pass(self, client):
        from bot_program.tasks import sync_etoro_accounts
        with patch("bot_program.engine.etoro_client.EtoroTrader",
                   return_value=client):
            return sync_etoro_accounts.__wrapped__()

    def _keyed_ibkr(self):
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(user=self.user, label="ISA",
                                          host="ibgateway", port=4001,
                                          client_id=1)
        acct.set_credentials("U1234567")
        acct.save(update_fields=["account_id_enc"])
        return acct

    def test_an_etoro_error_survives_the_idle_ibkr_and_saxo_passes(self):
        """Real fault, kept up — the worse half of the 2026-09-26 finding:
        an eToro error used to be overwritten minutes later by a walk that
        had nothing to read."""
        from unittest.mock import MagicMock

        from bot_program.models import EtoroAccount
        from core.component_digest import collect_faults
        with patch.object(EtoroAccount.objects, "exclude",
                          side_effect=RuntimeError("eToro answered 500")):
            with self.assertRaises(RuntimeError):
                self._etoro_pass(MagicMock())
        self.assertEqual(self._row().last_status, "error")
        self.assertEqual(self._ibkr_pass()["idle"], "no IBKR account to read")
        self.assertEqual(self._saxo_pass()["idle"], "no keyed Saxo account")
        row = self._row()
        self.assertEqual(row.last_status, "error")
        self.assertIn("eToro answered 500", row.last_message)
        errors = collect_faults()["errors"]
        self.assertEqual([f["key"] for f in errors], ["broker_account_sync"])
        self.assertIn("eToro answered 500", errors[0]["message"])

    def test_an_idle_pass_leaves_etoro_s_success_standing(self):
        """False alarm, held down: a healthy eToro sync read "ran and
        produced nothing" in the digest because IBKR and Saxo ran after
        it."""
        from unittest.mock import MagicMock

        from bot_program.models import EtoroAccount
        from core.component_digest import collect_faults
        acct = EtoroAccount.objects.create(user=self.user, demo=True,
                                           label="Main")
        acct.set_credentials("k", "u")
        acct.save()
        client = MagicMock()
        client.net_liquidation.return_value = (2012.02, "EUR")
        client.broker_portfolio.return_value = []
        out = self._etoro_pass(client)
        self.assertEqual((out["attempted"], out["stored"]), (1, 1))
        self.assertEqual(self._row().last_status, "success")
        self._ibkr_pass()
        self._saxo_pass()
        self.assertEqual(self._row().last_status, "success")
        faults = collect_faults()
        self.assertEqual(
            faults["errors"] + faults["warnings"] + faults["silent"], [])

    def test_a_keyed_ibkr_account_that_answers_nothing_is_still_a_warning(self):
        """Real fault, kept up: idle means nothing to read, never could
        not read."""
        from unittest.mock import MagicMock
        self._keyed_ibkr()
        trader = MagicMock()
        trader.net_liquidation.return_value = None
        trader.broker_portfolio.return_value = None
        out = self._ibkr_pass(trader)
        self.assertNotIn("idle", out)
        self.assertEqual((out["attempted"], out["unreachable"]), (1, 1))
        row = self._row()
        self.assertEqual(row.last_status, "warning")
        self.assertIn("stored none", row.last_message)

    def test_no_keyed_ibkr_account_is_idle_even_without_the_library(self):
        """False alarm, held down: IBKR is being retired."""
        out = self._ibkr_pass(available=False)
        self.assertEqual(out.get("idle"), "no keyed IBKR account")
        self.assertNotIn("skipped", out)
        self.assertIsNone(self._row().last_run_at)

    def test_a_keyed_ibkr_account_without_the_library_is_still_reported(self):
        """Real fault, kept up."""
        self._keyed_ibkr()
        out = self._ibkr_pass(available=False)
        self.assertNotIn("idle", out)
        row = self._row()
        self.assertEqual(row.last_status, "warning")
        self.assertIn("ib_insync not installed", row.last_message)

    def test_a_saxo_row_without_a_live_session_is_idle(self):
        """False alarm, held down: the session keeper and /brokers/ own a
        dead Saxo session; the sync row does not."""
        from bot_program.models import SaxoAccount
        acct = SaxoAccount.objects.create(
            user=self.user, sim=True,
            redirect_uri="https://h.example.net/brokers/saxo/callback/")
        acct.set_credentials("app-key", "app-secret")
        acct.save()
        out = self._saxo_pass()
        self.assertEqual(out["idle"], "no live Saxo session")
        self.assertIsNone(self._row().last_run_at)


class TheDigestReadsInTheHouseStyleTests(_ComponentsOnly):
    """English, one fault per line, names not keys, at most twenty-five
    lines — the house style every message the platform sends now keeps."""

    def test_the_one_real_fault_of_the_nineteen_reads_whole(self):
        """Real fault, kept up: the calendar's macro half."""
        from core.component_digest import collect_faults, render_digest
        _component("scraper_calendar", name="Economic Calendar",
                   last_status="warning",
                   last_message="macro half: FMP answered 402 Payment "
                                "Required")
        title, body = render_digest(collect_faults())
        self.assertEqual(title, "⊙ Sauron — 1 thing needs attention")
        lines = body.splitlines()
        self.assertEqual(lines[0], "Ran but did nothing (1)")
        self.assertIn("• Economic Calendar — macro half: FMP answered 402 "
                      "Payment Required", lines)
        self.assertEqual(lines[-1],
                         "All other checks passed (1 enabled component).")

    def test_sections_come_in_the_order_an_operator_acts(self):
        from core.component_digest import collect_faults, render_digest
        _component("scraper_a", name="Scraper A", last_status="error",
                   last_message="boom")
        _component("scraper_b", name="Scraper B", last_status="warning",
                   last_message="handled 12 rows and stored none")
        _component("scraper_eod", name="EOD Prices",
                   last_run_at=_days_ago(3))
        title, body = render_digest(collect_faults())
        self.assertEqual(title, "⊙ Sauron — 3 things need attention")
        order = [body.index(h) for h in ("Failing (1)",
                                         "Ran but did nothing (1)",
                                         "Stopped running (1)")]
        self.assertEqual(order, sorted(order))
        self.assertIn("All other checks passed (3 enabled components).",
                      body)

    def test_a_stopped_component_shows_its_name_and_rhythm_not_its_key(self):
        from core.component_digest import collect_faults, render_digest
        _component("pipeline_meta_allocator",
                   name="Meta Allocator (proposer)",
                   last_run_at=_days_ago(9))
        _title, body = render_digest(collect_faults())
        self.assertIn("• Meta Allocator (proposer) — last ran 9d ago "
                      "(weekly)", body.splitlines())
        self.assertNotIn("pipeline_meta_allocator", body)

    def test_a_long_multi_line_message_is_one_line_of_140(self):
        from core.component_digest import collect_faults, render_digest
        _component("scraper_a", name="Scraper A", last_status="error",
                   last_message="Traceback (most recent call last):\n"
                                "  File \"x.py\", line 1\n" + "y" * 400)
        _title, body = render_digest(collect_faults())
        line = next(ln for ln in body.splitlines()
                    if ln.startswith("• Scraper A — "))
        words = line[len("• Scraper A — "):]
        self.assertLessEqual(len(words), 140)
        self.assertTrue(words.startswith(
            "Traceback (most recent call last): File"))
        self.assertTrue(words.endswith("…"))

    def test_forty_faults_stop_at_25_lines_and_count_the_rest(self):
        """Real faults, none dropped in silence: what does not fit is
        counted and pointed at."""
        from core.component_digest import collect_faults, render_digest
        for i in range(40):
            _component("scraper_%02d" % i, name="Scraper %02d" % i,
                       last_status="error", last_message="boom")
        title, body = render_digest(collect_faults())
        lines = body.splitlines()
        self.assertLessEqual(len(lines), 25)
        self.assertEqual(title, "⊙ Sauron — 40 things need attention")
        shown = sum(1 for ln in lines if ln.startswith("• "))
        self.assertGreater(shown, 15)
        self.assertIn("+%d more on /health/" % (40 - shown), lines)


class TheDigestReachesTheOperatorTests(_ComponentsOnly):
    """The same two places as before — every staff bell, and the chat in
    TELEGRAM_CHAT_ID — with no bot preference and no quiet hours between,
    as before. What changed is that the bell now actually receives it, and
    Telegram receives escaped HTML."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user("dg_staff", password="x",
                                              is_staff=True)

    def _send(self, env=None, ok=True, status=200, text=""):
        import os

        from core.component_digest import send_component_digest
        env = env if env is not None else {
            "TELEGRAM_BOT_TOKEN": "t0k", "TELEGRAM_CHAT_ID": "-100123"}
        with patch.dict(os.environ, env), patch("requests.post") as post:
            post.return_value.ok = ok
            post.return_value.status_code = status
            post.return_value.text = text
            out = send_component_digest()
        return out, post

    def test_the_bell_receives_it(self):
        """Real fault, finally delivered: page_url("system_health") was a
        TypeError, so no digest had ever reached the bell."""
        from alerts.models import Notification
        _component("scraper_a", name="Scraper A", last_status="error",
                   last_message="boom")
        out, _post = self._send()
        self.assertEqual(out["sent"], 1)
        n = Notification.objects.get(user=self.staff)
        self.assertEqual(n.url, "/health/")
        self.assertEqual(n.title, "⊙ Sauron — 1 thing needs attention")
        self.assertIn("• Scraper A — boom", n.body)

    def test_telegram_gets_escaped_html_under_one_emoji(self):
        """Real fault, kept deliverable: in legacy Markdown one underscore
        in a fault's words ("platform_disabled") was a 400 and the whole
        digest was dropped."""
        _component("scraper_a", name="Scraper <A> & co", last_status="error",
                   last_message="platform_disabled <b>x</b>")
        out, post = self._send()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["chat_id"], "-100123")
        text = payload["text"]
        self.assertTrue(text.startswith(
            "<b>⚠️ Sauron — 1 thing needs attention</b>\n\n"),
            text[:80])
        self.assertNotIn("⊙", text)
        self.assertIn("• Scraper &lt;A&gt; &amp; co — platform_disabled "
                      "&lt;b&gt;x&lt;/b&gt;", text)
        self.assertTrue(out["telegram"])

    def test_a_telegram_refusal_is_logged_in_telegram_s_words(self):
        _component("scraper_a", name="Scraper A", last_status="error",
                   last_message="boom")
        with self.assertLogs("core.component_digest", "WARNING") as logs:
            out, _post = self._send(ok=False, status=400,
                                    text="Bad Request: can't parse entities")
        self.assertFalse(out["telegram"])
        self.assertEqual((out["faults"], out["sent"]), (1, 1))
        self.assertTrue(any("can't parse entities" in m
                            for m in logs.output))

    def test_without_telegram_the_bell_still_gets_it(self):
        _component("scraper_a", name="Scraper A", last_status="error",
                   last_message="boom")
        out, post = self._send(env={"TELEGRAM_BOT_TOKEN": "",
                                    "TELEGRAM_CHAT_ID": ""})
        post.assert_not_called()
        self.assertEqual(out["sent"], 1)
        self.assertFalse(out["telegram"])

    def test_a_healthy_platform_sends_nothing_anywhere(self):
        """False alarm, held down: the quiet day stays quiet, master
        switch and all."""
        from alerts.models import Notification
        _component("scraper_fine")
        _seeded_long_ago(_component("platform_master", category="system",
                                    last_run_at=None, last_status=""))
        out, post = self._send()
        post.assert_not_called()
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual((out["faults"], out["sent"]), (0, 0))
