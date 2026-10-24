"""THE ARMS' AND GRADES' TASKS (bot_program/orcs/tasks.py, spec §10.3): on
the slow queue by exact name (no worker serves `orcs` before O2), behind
the switch, idle passes keep the census's component row, idempotent and
catch-up safe; their beats sit in the day scheme in plain words.

Run with:  python manage.py test tests.orcs.test_orc_tasks_o1b
"""
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.orcs.helpers import (_config, _on, _row, _switch, _user, born,
                                tracks_of)

TASKS = ("bot_program.orcs.tasks.track_ghosts",
         "bot_program.orcs.tasks.grade_closed",
         "bot_program.orcs.tasks.shadow_audit")
BEATS = ("orc-track-ghosts", "orc-grade-closed", "orc-shadow-audit")


class TheWiringTests(SimpleTestCase):

    def test_routes_to_slow_and_queues_consumed(self):
        from celery.app.routes import MapRoute

        from config.celery import app
        from core import day_of_sauron as day
        routes = dict(app.conf.task_routes)
        route = MapRoute(routes)
        for name in TASKS:
            self.assertEqual(route(name), {"queue": "slow"}, name)
            self.assertEqual(day.queue_of(name, routes), "slow")
        self.assertNotIn("bot_program.orcs.tasks.*", routes,
                         "no glob: a queue no worker serves strands them")
        compose = open("deploy/docker-compose.yml").read()
        self.assertIn("-Q slow,ai", compose, "worker-slow consumes slow")
        self.assertIn("bot_program.orcs.tasks", app.conf.imports)
        beat = app.conf.beat_schedule
        self.assertEqual(beat["orc-track-ghosts"]["schedule"], 900.0)
        self.assertEqual(beat["orc-track-ghosts"]["options"]["expires"], 840)
        self.assertEqual(str(beat["orc-grade-closed"]["schedule"]._orig_minute),
                         "40")
        for key in BEATS:
            self.assertIn(beat[key]["task"], TASKS)

    def test_day_scheme_places_beats_plain_labels(self):
        from core.day_of_sauron import STAGE_OF
        for key in BEATS:
            stage, words = STAGE_OF[key]
            self.assertNotIn("/", words)
            self.assertNotIn("Orc", words, "the public scheme says it plainly")
        self.assertEqual(STAGE_OF["orc-shadow-audit"][0], "learn")


class TheTaskTests(TestCase):

    def setUp(self):
        _switch("aragorn")
        self.user = _user("orc_tasks")
        self.cfg = _config(self.user)

    def test_noop_while_off_zero_writes(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.models import OrcGrade, OrcJournal, OrcTrack
        _on()
        orc = born(self, _row(self.cfg))
        _on(False)
        before = (list(OrcTrack.objects.values()), OrcJournal.objects.count())
        for task in (tasks.track_ghosts, tasks.grade_closed,
                     tasks.shadow_audit):
            out = task()
            self.assertEqual(out["status"], "skipped")
        self.assertEqual((list(OrcTrack.objects.values()),
                          OrcJournal.objects.count()), before)
        self.assertEqual(OrcGrade.objects.count(), 0)
        self.assertTrue(orc.pk)

    def test_idle_keeps_component_row(self):
        from core.platform_control import PlatformComponent

        from bot_program.orcs import tasks
        _on()
        comp = PlatformComponent.objects.get(key="orcs")
        comp.mark_run(success=True, message="the census ran", status="success")
        for task in (tasks.track_ghosts, tasks.grade_closed,
                     tasks.shadow_audit):
            out = task()
            self.assertIn("idle", out)
        comp.refresh_from_db()
        self.assertEqual((comp.last_message, comp.run_count),
                         ("the census ran", 1))

    def test_track_ghosts_catch_up_safe(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import tasks
        _on()
        row = _row(self.cfg)
        orc = born(self, row)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", outcome="manual_close", closed_at=timezone.now(),
            exit_price=Decimal("101"),
            reason="t | closed:MANUAL")
        row.refresh_from_db()
        from bot_program.orcs.lifecycle import on_leg_closed
        on_leg_closed(row.pk)
        first = tasks.track_ghosts()
        self.assertEqual(first["status"], "success")
        state = {a: t.state for a, t in tracks_of(orc).items()}
        tasks.track_ghosts()
        self.assertEqual({a: t.state for a, t in tracks_of(orc).items()},
                         state, "a second pass with no new bar moves nothing")

    def test_grade_closed_only_resolved_dead_orcs(self):
        from bot_program.orcs import tasks
        from bot_program.orcs.models import Orc, OrcGrade, OrcTrack
        _on()
        live = born(self, _row(self.cfg))
        dead_open = born(self, _row(self.cfg, symbol="ETHUSD"))
        dead_done = born(self, _row(self.cfg, symbol="SOLUSD"))
        Orc.objects.filter(pk__in=[dead_open.pk, dead_done.pk]).update(
            state="dead", died_at=timezone.now() - timedelta(minutes=5))
        OrcTrack.objects.filter(orc=dead_done).update(
            open=False, exit_r=0.5, exit_price=Decimal("101"))
        out = tasks.grade_closed()
        self.assertEqual((out["graded"], out["waiting"]), (1, 1))
        self.assertEqual(list(OrcGrade.objects.values_list("orc_id",
                                                           flat=True)),
                         [dead_done.pk])
        again = tasks.grade_closed()
        self.assertIn("idle", again)
        self.assertTrue(live.pk)
