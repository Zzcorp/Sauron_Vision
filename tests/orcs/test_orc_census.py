"""THE CENSUS (spec §1.2, §10.3, O1a): every 5 minutes on the fast queue,
behind the `orcs` switch, one pass at a time — births the hooks missed
(adoptions), deaths no receiver saw (the sweep), stamps another writer
dropped, the reviews and the pending closes as facts. One bad row never
stops the pass.

Run with:  python manage.py test tests.orcs.test_orc_census
"""
import os
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.orcs.helpers import _config, _on, _row, _user, born, headlines

NOTIFY = "bot_program.notifications.dispatch_notification"


class TheScheduleTests(SimpleTestCase):

    def test_the_beat_entry_route_and_import(self):
        from config.celery import app
        self.assertEqual(app.conf.beat_schedule["orc-census"], {
            "task": "bot_program.orcs.tasks.orc_census", "schedule": 300.0,
            "options": {"expires": 280, "expire_seconds": 280}})
        routes = dict(app.conf.task_routes)
        self.assertEqual(routes["bot_program.orcs.tasks.orc_census"],
                         {"queue": "fast"})
        self.assertFalse([k for k in routes if k.startswith(
            "bot_program.orcs") and "*" in k], "no orcs glob before O2")
        self.assertIn("bot_program.orcs.tasks", app.conf.imports)
        from bot_program.orcs.tasks import orc_census
        self.assertEqual(orc_census.name, "bot_program.orcs.tasks.orc_census")
        self.assertEqual(orc_census.run.component_key, "orcs")

    def test_the_census_has_a_stage_in_the_day_scheme(self):
        from core import day_of_sauron as day
        self.assertEqual(day.STAGE_OF["orc-census"][0], "watch")
        self.assertEqual([t["key"] for t in day.day_scheme()["unplaced"]], [])

    def test_the_orcs_command_is_registered(self):
        from core import ops_commands
        e = ops_commands.get("orcs")
        self.assertIsNotNone(e)
        self.assertEqual((e["category"], e["read_only"]), ("decide", False))
        self.assertIn("python manage.py orcs adopt --open --yes", " ".join(
            e["usage"]))

    def test_the_runbook_says_how_to_switch_it_on(self):
        from django.conf import settings
        text = open(os.path.join(settings.BASE_DIR, "deploy", "RUNBOOK.md"),
                    encoding="utf-8").read()
        head = "## The Orcs (O1: journals, no model)"
        self.assertIn(head, text)
        self.assertLess(text.index(head), text.index("## Operating notes"))
        section = text[text.index(head):text.index("## Operating notes")]
        for words in ("manage.py component on orcs",
                      "manage.py orcs adopt --open",
                      "--yes", "kill switch", "OFF"):
            self.assertIn(words, section)


class TheCensusTests(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_census")
        self.cfg = _config(self.user)

    def test_one_pass_births_sweeps_restamps_and_reads_reviews(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import census
        from bot_program.orcs.models import Orc
        from brain.position_review_models import PositionReview
        unborn = _row(self.cfg, symbol="U1USD")
        closed = _row(self.cfg, symbol="D1USD")
        dying = born(self, closed)
        wiped = _row(self.cfg, symbol="W1USD")
        restamp = born(self, wiped)
        reviewed = _row(self.cfg, symbol="R1USD")
        read = born(self, reviewed)
        pending = _row(self.cfg, symbol="P1USD")
        waiting = born(self, pending)
        # the hooks' blind spots
        AssetBotTrade.objects.filter(pk=closed.pk).update(
            status="CLOSED", outcome="stopped_out", closed_at=timezone.now(),
            exit_price=Decimal("98"), realized_r=-1.0)
        AssetBotTrade.objects.filter(pk=wiped.pk).update(metadata={
            "initial_stop_loss": 98.0})
        AssetBotTrade.objects.filter(pk=pending.pk).update(
            status="CLOSE_PENDING")
        PositionReview.objects.create(
            book="bot", position_id=reviewed.pk, symbol="R1USD", side="BUY",
            verdict="hold", mark=101, unrealized_r=0.5)
        with patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            out = census.run()
        self.assertEqual(out["status"], "success")
        self.assertEqual((out["born"], out["adopted"], out["died"],
                          out["restamped"]), (1, 1, 1, 1))
        self.assertEqual(out["facts"], 2)
        for key in ("skipped", "parsed", "attempted"):
            self.assertNotIn(key, out, "the task gate reads these")
        self.assertTrue(Orc.objects.get(root_trade=unborn).adopted)
        dying.refresh_from_db()
        self.assertEqual(dying.state, "dead")
        wiped.refresh_from_db()
        self.assertEqual(wiped.metadata["orc"]["idea"], restamp.pk)
        self.assertIn("The reviewer reads hold at 101.00, +0.50R.",
                      headlines(read))
        self.assertIn("A close is pending at the venue for this position.",
                      headlines(waiting))
        again = census.run()
        self.assertEqual((again["born"], again["died"], again["restamped"],
                          again["facts"]), (0, 0, 0, 0))

    def test_a_stale_orc_frees_its_slot_in_the_same_pass(self):
        """The sweep runs before the births: a paper Orc whose row closed
        where no receiver saw it (a queryset update) gives its slot under
        the cap to a row waiting in this very pass."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import census
        from bot_program.orcs.models import Orc, OrcSetting
        OrcSetting.objects.create(key="max_paper_orcs", value=1)
        stale_row = _row(self.cfg, symbol="S1USD")
        stale = born(self, stale_row)
        waiting = _row(self.cfg, symbol="S2USD")
        AssetBotTrade.objects.filter(pk=stale_row.pk).update(
            status="CLOSED", outcome="stopped_out", closed_at=timezone.now(),
            exit_price=Decimal("98"), realized_r=-1.0)
        with patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            out = census.run()
        self.assertEqual((out["died"], out["born"]), (1, 1))
        stale.refresh_from_db()
        self.assertEqual(stale.state, "dead")
        self.assertTrue(Orc.objects.get(root_trade=waiting).adopted)

    def test_a_full_cap_costs_the_same_whatever_the_rows_it_holds_back(self):
        """With the cap full the rows outside real money are not even read:
        a pass costs the same queries with 2 or 40 of them waiting, and a
        real row is still adopted."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from bot_program.orcs import census
        from bot_program.orcs.models import Orc, OrcSetting
        OrcSetting.objects.create(key="max_paper_orcs", value=0)
        etoro = _config(self.user, mode="live", name="etoro")
        demo = {"broker": "etoro", "broker_env": "paper"}

        def one_pass():
            with CaptureQueriesContext(connection) as q, patch(NOTIFY), \
                    self.captureOnCommitCallbacks(execute=True):
                census.run()
            return len(q.captured_queries)

        for i in range(2):
            _row(self.cfg, symbol=f"Q{i}USD")
            _row(etoro, paper=False, symbol=f"E{i}USD", meta=demo)
        real = _row(etoro, paper=False, symbol="RQUSD")
        one_pass()
        self.assertEqual(list(Orc.objects.values_list("root_trade_id",
                                                      flat=True)),
                         [real.pk])
        few = one_pass()
        for i in range(2, 40):
            _row(self.cfg, symbol=f"Q{i}USD")
            _row(etoro, paper=False, symbol=f"E{i}USD", meta=demo)
        many = one_pass()
        self.assertEqual(many, few, "a capped row costs no query")
        self.assertEqual(Orc.objects.count(), 1)
        # with room, the rows are taken oldest first and the count stops
        # the pass at the cap
        OrcSetting.objects.filter(key="max_paper_orcs").update(value=3)
        one_pass()
        self.assertEqual(Orc.objects.exclude(seat__venue="live").count(), 3)
        self.assertEqual(sorted(Orc.objects.exclude(seat__venue="live")
                                .values_list("symbol", flat=True)),
                         ["E0USD", "Q0USD", "Q1USD"])

    def test_two_passes_never_overlap(self):
        from bot_program.orcs.tasks import orc_census
        cache.delete("orcs:census")
        cache.add("orcs:census", 1, 60)
        try:
            with patch("bot_program.orcs.census.run") as run:
                self.assertEqual(orc_census(),
                                 {"idle": "another census is running"})
            run.assert_not_called()
        finally:
            cache.delete("orcs:census")
        with patch("bot_program.orcs.census.run",
                   return_value={"status": "success"}) as run:
            self.assertEqual(orc_census(), {"status": "success"})
        run.assert_called_once()
        self.assertIsNone(cache.get("orcs:census"), "the lock is let go")

    def test_one_bad_row_never_stops_the_pass(self):
        from bot_program.orcs import birth, census
        from bot_program.orcs.models import Orc
        first = _row(self.cfg, symbol="B1USD")
        second = _row(self.cfg, symbol="B2USD")
        real = birth.ensure

        def flaky(trade, **kw):
            if trade.pk == first.pk:
                raise RuntimeError("one bad row")
            return real(trade, **kw)
        with patch("bot_program.orcs.birth.ensure", side_effect=flaky), \
                self.captureOnCommitCallbacks(execute=True):
            out = census.run()
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["born"], 1)
        self.assertEqual(list(Orc.objects.values_list("root_trade_id",
                                                      flat=True)),
                         [second.pk])


class TheLateSeedTests(TestCase):
    """AN ORC BORN BEFORE ITS ARMS (O1a's births). The census gives it
    the arms it lacks, marked "late" (graded, never counted for a seat),
    and brings O1a's care track up to the arms' format IN PLACE: the
    static keys the stepper needs come from the row and its config, every
    care-state key the track already holds stays, and nothing is reseeded
    from the row's care. Before, the old track lacked `cf` and never
    stepped again."""

    def setUp(self):
        from tests.orcs.helpers import _switch
        _on()
        _switch("aragorn")
        self.user = _user("orc_late")
        self.cfg = _config(self.user)

    def _o1a(self):
        """An Orc as O1a left it: one care track in O1a's own format."""
        from datetime import datetime, timezone as dt_tz

        from bot_program.models import AssetBotTrade
        from bot_program.orcs import tracks
        from bot_program.orcs.models import OrcTrack
        t0 = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)
        row = _row(self.cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=t0)
        row.refresh_from_db()
        orc = born(self, row, at=t0)
        OrcTrack.objects.filter(orc=orc).delete()
        old = tracks.seed_care(orc, row)
        old.update({"peak": 101.7, "worst": 99.4, "soft_stop": 100.1,
                    "soft_why": "breakeven"})
        OrcTrack.objects.create(orc=orc, arm="care", open=True, state=old)
        # the row's care moved on since: a reseed would read 103.0
        meta = dict(row.metadata)
        meta["care"] = {"peak": 103.0, "worst": 99.4, "soft_stop": 101.0,
                        "soft_why": "trail", "mfe_r": 1.5}
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata=meta)
        row.refresh_from_db()
        return t0, row, orc, old

    def test_seed_late_upgrades_an_o1a_care_track_in_place_never_reseeding_its_state(
            self):
        from datetime import timedelta

        from bot_program.orcs import census
        from bot_program.orcs.constants import GHOST_ARMS
        from tests.orcs.helpers import drive, tracks_of
        t0, row, orc, old = self._o1a()
        self.assertEqual(census._seed_late(t0 + timedelta(minutes=5)), 1)
        t = tracks_of(orc)
        self.assertEqual(set(t), set(GHOST_ARMS))
        care = t["care"].state
        for key in ("peak", "worst", "soft_stop", "soft_why", "venue_stop",
                    "entry", "initial_stop", "qty", "qty_open", "side"):
            self.assertEqual(care[key], old[key], key)
        self.assertEqual((care["cf"], care["rpu"], care["symbol"],
                          care["asset_class"], care["root"], care["paper"],
                          care["seed"], care["manual"]),
                         (t["playbook"].state["cf"], 2.0, "BTCUSD", "crypto",
                          row.pk, True, "late", False))
        for arm in ("playbook", "orc_shadow", "chandelier3", "staged"):
            self.assertEqual(t[arm].state["seed"], "late", arm)
        drive(self, self.cfg, row, [(t0 + timedelta(minutes=30), "100.6")])
        care = tracks_of(orc)["care"].state
        self.assertEqual(care["last_tick_at"],
                         (t0 + timedelta(minutes=30)).isoformat(),
                         "the old track steps")
        self.assertEqual(care["peak"], 101.7, "its own peak, never the row's")

    def test_census_seeds_missing_arms_once_marked_late(self):
        from datetime import timedelta

        from bot_program.orcs import census
        from bot_program.orcs.models import Orc, OrcTrack
        t0, row, orc, _old = self._o1a()
        dead = born(self, _row(self.cfg, symbol="ETHUSD"), at=t0)
        OrcTrack.objects.filter(orc=dead).exclude(arm="care").delete()
        Orc.objects.filter(pk=dead.pk).update(state="dead")
        with patch("django.utils.timezone.now",
                   return_value=t0 + timedelta(minutes=5)):
            out = census.run(now=t0 + timedelta(minutes=5))
        self.assertEqual(out["seeded"], 1, "the living Orc only")
        self.assertEqual(OrcTrack.objects.filter(orc=orc).count(), 5)
        self.assertEqual(OrcTrack.objects.filter(orc=dead).count(), 1)
        self.assertEqual(census._seed_late(t0 + timedelta(minutes=10)), 0,
                         "once")
