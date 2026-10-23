"""O1c'S BEATS, SWITCHES AND REGISTRIES (bot_program/orcs/tasks.py,
config/celery.py, core/platform_control.py, core/day_of_sauron.py,
core/ops_commands.py; spec §10.3, §10.7): the day roll, the session close
and the hourly read on the SLOW queue by exact name, the Mercenaries' tape
on the fast queue by its glob; each behind its switch, idempotent, catch-up
safe; `orcs_drums` and `orcs_tape` are System keys OFF on arrival; the
census gains the book, the clock and the drums.

Run with:  python manage.py test tests.orcs.test_orc_beats_o1c
"""
import io
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _config, _on, _row, _switch, _user, born

TASKS = ("bot_program.orcs.tasks.orc_day_roll",
         "bot_program.orcs.tasks.orc_session_close",
         "bot_program.orcs.tasks.orc_hourly")
BEATS = {"orc-day-roll": TASKS[0], "orc-session-close": TASKS[1],
         "orc-hourly": TASKS[2],
         "orc-tape-mercenary": "market_data.tasks.refresh_orc_tape_task"}
UTC = dt_tz.utc


class TheWiringTests(SimpleTestCase):

    def test_routes_by_exact_name_and_the_tape_by_its_glob(self):
        from celery.app.routes import MapRoute

        from config.celery import app
        routes = dict(app.conf.task_routes)
        route = MapRoute(routes)
        for name in TASKS:
            self.assertIn(name, routes)
            self.assertEqual(route(name), {"queue": "slow"}, name)
        self.assertNotIn("market_data.tasks.refresh_orc_tape_task", routes)
        self.assertEqual(route("market_data.tasks.refresh_orc_tape_task"),
                         {"queue": "fast"})

    def test_the_schedules(self):
        from config.celery import app
        beat = app.conf.beat_schedule
        for key, task in BEATS.items():
            self.assertEqual(beat[key]["task"], task)
        roll = beat["orc-day-roll"]["schedule"]
        self.assertEqual((str(roll._orig_minute), str(roll._orig_hour)),
                         ("3", "21,22"))
        close = beat["orc-session-close"]["schedule"]
        self.assertEqual(str(close._orig_minute), "4")
        self.assertEqual(str(close._orig_hour),
                         "4,5,9,10,15,16,17,18,20,21")
        self.assertEqual(str(beat["orc-hourly"]["schedule"]._orig_minute),
                         "6")
        self.assertEqual(beat["orc-tape-mercenary"]["schedule"], 300.0)
        self.assertEqual(beat["orc-tape-mercenary"]["options"]["expires"],
                         280)

    def test_the_session_close_hours_are_every_session_end_on_both_clocks(
            self):
        from datetime import date

        from bot_program.orcs.sessions import session_windows
        from config.celery import app
        hours = {int(h) for h in str(app.conf.beat_schedule[
            "orc-session-close"]["schedule"]._orig_hour).split(",")}
        for td in (date(2026, 10, 22), date(2026, 12, 3)):
            for _name, _start, end in session_windows(td):
                self.assertIn(end.hour, hours, (td, end))
                self.assertEqual(end.minute, 0)

    def test_day_scheme_words(self):
        from core.day_of_sauron import STAGE_OF
        for key in BEATS:
            stage, words = STAGE_OF[key]
            self.assertNotIn("/", words)
            self.assertNotIn("Orc", words)

    def test_the_switches(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES)
        for key in ("orcs_drums", "orcs_tape"):
            entry = next(c for c in DEFAULT_COMPONENTS if c["key"] == key)
            with self.subTest(key=key):
                self.assertEqual(entry["category"], "system")
                self.assertLess(len(entry["description"]), 300)
                self.assertTrue(entry["description"].startswith(
                    "Off (default)."))
                self.assertNotIn(key, LIVE_MONEY_SWITCHES)
                self.assertNotIn(key, BULK_ENABLE_EXEMPT)

    def test_the_ops_registry(self):
        from core.ops_commands import COMMANDS
        by = {c["name"]: c for c in COMMANDS}
        usage = "\n".join(by["orcs"]["usage"])
        self.assertIn("orcs actuals", usage)
        self.assertIn("orcs dossier", usage)
        self.assertIn("etoro_candle_headroom", by)
        self.assertFalse(by["etoro_candle_headroom"]["run_args"])


class TheGateTests(TestCase):

    def test_every_beat_skips_while_off(self):
        from bot_program.orcs import tasks
        from market_data.tasks import refresh_orc_tape_task
        _switch("platform_master", True)
        for task in (tasks.orc_day_roll, tasks.orc_session_close,
                     tasks.orc_hourly):
            self.assertEqual(task()["status"], "skipped")
        self.assertEqual(refresh_orc_tape_task()["status"], "skipped")


class TheTaskTests(TestCase):

    def setUp(self):
        _switch("aragorn")
        _on()
        self.user = _user("orc_beats")
        self.cfg = _config(self.user)
        self.now = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)
        with patch("django.utils.timezone.now", return_value=self.now):
            self.orc = born(self, _row(self.cfg), at=self.now)

    def _at(self, task, at=None):
        with patch("django.utils.timezone.now", return_value=at or self.now):
            return task()

    def test_the_day_roll_builds_mk0_per_family_weather_and_the_actuals(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.constants import MK_FAMILIES
        from bot_program.orcs.models import (OrcDayBaseline, OrcDossierBlock,
                                             OrcSetting)
        out = self._at(tasks.orc_day_roll)
        self.assertEqual(out["status"], "success")
        self.assertEqual(OrcDossierBlock.objects.filter(kind="mk0").count(),
                         len(MK_FAMILIES))
        self.assertEqual(OrcDayBaseline.objects.filter(
            user=self.user, asset_class="crypto").count(), 1)
        self.assertIsNotNone(OrcSetting.get("calendar_actuals"))
        again = self._at(tasks.orc_day_roll,
                         self.now + timedelta(minutes=5))
        self.assertIn("idle", again)
        self.assertEqual(OrcDossierBlock.objects.filter(kind="mk0").count(),
                         len(MK_FAMILIES))

    def test_the_session_close_builds_what_is_missing_once(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.constants import MK_FAMILIES
        from bot_program.orcs.models import OrcDossierBlock
        out = self._at(tasks.orc_session_close)
        self.assertEqual(out["built"], 2 * len(MK_FAMILIES), "asia, london")
        self.assertIn("idle", self._at(tasks.orc_session_close))
        later = datetime(2026, 10, 22, 15, 4, tzinfo=UTC)
        out = self._at(tasks.orc_session_close, later)
        self.assertEqual(out["built"], len(MK_FAMILIES), "New York AM")
        self.assertEqual(OrcDossierBlock.objects.filter(
            kind="mk_session").count(), 3 * len(MK_FAMILIES))

    def test_the_hourly_read_is_idempotent(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.models import (OrcDayBaseline, OrcDossierBlock,
                                             OrcDrum)
        out = self._at(tasks.orc_hourly)
        self.assertEqual(out["status"], "success")
        n = (OrcDossierBlock.objects.count(), OrcDrum.objects.count())
        self._at(tasks.orc_hourly, self.now + timedelta(minutes=10))
        self.assertEqual((OrcDossierBlock.objects.count(),
                          OrcDrum.objects.count()), n)
        base = OrcDayBaseline.objects.get(user=self.user,
                                          asset_class="crypto")
        self.assertIn("hour", base.components)

    def test_the_census_reads_the_book_the_clock_and_the_drums(self):
        from bot_program.orcs import census
        with patch("django.utils.timezone.now", return_value=self.now):
            out = census.run(self.now)
        for key in ("book", "clock", "pending_w10", "drums_published",
                    "drums_routed"):
            self.assertIn(key, out)
        for key in ("skipped", "parsed", "attempted"):
            self.assertNotIn(key, out)

    def test_the_dossier_command_replays_a_wake(self):
        from django.core.management import call_command

        from bot_program.orcs import dossier, observe
        from types import SimpleNamespace
        row = self.orc.root_trade
        row.refresh_from_db()
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks={})
        with patch("django.utils.timezone.now", return_value=self.now), \
                self.captureOnCommitCallbacks(execute=True):
            observe.after_care(bot, row, "100.5", "")
        from bot_program.orcs.models import OrcWake
        w = OrcWake.objects.get(orc=self.orc)
        out = io.StringIO()
        call_command("orcs", "dossier", str(row.pk), stdout=out)
        self.assertIn(dossier.text_of(w.block_hashes), out.getvalue())
        out = io.StringIO()
        call_command("orcs", "dossier", str(row.pk), "--wake", "9",
                     stdout=out)
        self.assertIn("no wake", out.getvalue())
