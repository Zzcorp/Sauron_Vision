"""THE ARMS ON THEIR OWN STATE (bot_program/orcs/ghost.py, spec §3.3, §6.1,
§6.4): the care ghost is seeded once from the row and never reads the
row's care again; it replays plan() with the care's own inputs; the O arm
records the real row and, after a hand act, carries on as a shadow. One
writer per phase (the tick while the row is open, track_ghosts after);
the manual lane's care in the tail; the playbook arm's own code.

Run with:  python manage.py test tests.orcs.test_orc_ghost
"""
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import (_bars, _config, _on, _row, _switch, _user,
                                _wave, born, care_tick, drive, headlines,
                                tracks_of)

T0 = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)      # a Wednesday


def _at(minutes):
    return T0 + timedelta(minutes=minutes)


def _open_at(row, at=T0):
    from bot_program.models import AssetBotTrade
    AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=at)
    row.refresh_from_db()


class _Base(TestCase):

    def setUp(self):
        _on()
        _switch("aragorn")
        self.user = _user("orc_ghost")
        self.cfg = _config(self.user)

    def _born(self, **kw):
        row = _row(self.cfg, **kw)
        _open_at(row)
        return row, born(self, row)


class TheSeedTests(_Base):

    def test_seed_once_from_the_rows_care(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.constants import GHOST_ARMS
        care = {"peak": 103.0, "worst": 99.5, "soft_stop": 100.2,
                "soft_why": "breakeven", "mfe_r": 1.5,
                "since": "2026-10-14T10:00:00+00:00"}
        row, orc = self._born(meta={"care": care,
                                    "cost_fraction_charged": 0.002})
        tracks = tracks_of(orc)
        self.assertEqual(set(tracks), set(GHOST_ARMS))
        for arm in ("care", "playbook", "orc_shadow"):
            st = tracks[arm].state
            self.assertEqual((st["soft_stop"], st["peak"], st["seed"],
                              st["cf"], st["rpu"], st["venue_stop"]),
                             (100.2, 103.0, "birth", 0.002, 2.0, 98.0), arm)
        for arm in ("chandelier3", "staged"):
            st = tracks[arm].state
            self.assertEqual((st["soft"], st["mfe"], st["extreme"],
                              st["target"]), (98.0, 1.5, 103.0, 110.0))
        before = {a: t.state for a, t in tracks.items()}
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata={
            **row.metadata, "care": {**care, "soft_stop": 101.0}})
        born(self, AssetBotTrade.objects.get(pk=row.pk))
        self.assertEqual({a: t.state for a, t in tracks_of(orc).items()},
                         before, "never reseeded")

    def test_ghost_state_never_written_from_the_row_after_seed(self):
        """An Orc's tightening (O3) moves the row's care and stop; the care
        ghost keeps its own: the row closes on that stop, the ghost runs."""
        from bot_program.models import AssetBotTrade
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(30), "101.0")])
        meta = dict(row.metadata)
        meta["care"] = {**meta["care"], "soft_stop": 100.9,
                        "soft_why": "orc: a noise level"}
        AssetBotTrade.objects.filter(pk=row.pk).update(
            metadata=meta, stop_loss=Decimal("100.9"))
        row.refresh_from_db()
        drive(self, self.cfg, row, [(_at(45), "101.2")])
        self.assertEqual(
            tracks_of(orc)["orc_shadow"].state["first_divergence"],
            {"kind": "reduce", "at": _at(45).isoformat()},
            "the row's stop tighter than the ghost's: a reduction")
        drive(self, self.cfg, row, [(_at(60), "100.8")])
        self.assertEqual(row.status, "CLOSED", "the row met the tightened stop")
        ghost = tracks_of(orc)["care"]
        self.assertTrue(ghost.open)
        self.assertIsNone(ghost.state["soft_stop"])
        self.assertEqual(ghost.state["venue_stop"], 98.0)
        # graded: the grade carries the divergence to the council of war
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcTrack
        OrcTrack.objects.filter(orc=orc, open=True).update(
            open=False, exit_r=0.0, exit_price=Decimal("100"),
            exit_at=_at(90))
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead")
        self.assertEqual(grade(orc, now=_at(95)).first_divergence, "reduce")

    def test_a_wider_row_stop_is_a_hold(self):
        from bot_program.models import AssetBotTrade
        row, orc = self._born()
        AssetBotTrade.objects.filter(pk=row.pk).update(
            stop_loss=Decimal("97.0"))
        row.refresh_from_db()
        drive(self, self.cfg, row, [(_at(30), "100.5")])
        self.assertEqual(
            tracks_of(orc)["orc_shadow"].state["first_divergence"]["kind"],
            "hold")

    def test_shadow_row_cannot_save(self):
        from bot_program.orcs.ghost import ShadowRow, shadow_of
        row, orc = self._born()
        st = tracks_of(orc)["care"].state
        shadow = shadow_of(st, base_meta=row.metadata)
        self.assertIsInstance(shadow, ShadowRow)
        self.assertFalse(hasattr(shadow, "save"))
        self.assertFalse(hasattr(shadow, "refresh_from_db"))
        self.assertNotIn("orc", shadow.metadata)


class TheReplayTests(_Base):

    def test_replays_plan_with_the_cares_own_inputs(self):
        from bot_program import position_care
        row, orc = self._born()
        with patch.object(position_care, "plan",
                          wraps=position_care.plan) as spy:
            drive(self, self.cfg, row, [(_at(30), "102.2")])
        self.assertEqual(spy.call_count, 3,
                         "the care, then its ghost and the playbook arm")
        real, *arms = spy.call_args_list
        for arm in arms:
            self.assertEqual(real.kwargs, arm.kwargs)
            self.assertEqual(str(real.args[1]), str(arm.args[1]))
        st = tracks_of(orc)["care"].state
        row.refresh_from_db()
        self.assertEqual((st["soft_stop"], st["soft_why"], st["peak"]),
                         (row.metadata["care"]["soft_stop"],
                          row.metadata["care"]["soft_why"],
                          row.metadata["care"]["peak"]))

    def test_no_plan_step_when_care_did_not_run(self):
        from bot_program import position_care
        row, orc = self._born()
        _switch("aragorn", False)
        with patch.object(position_care, "plan",
                          wraps=position_care.plan) as spy:
            drive(self, self.cfg, row, [(_at(30), "102.2")])
        self.assertEqual(spy.call_count, 0)
        st = tracks_of(orc)["care"].state
        self.assertIsNone(st["soft_stop"])
        self.assertEqual(st["last_tick_at"], _at(30).isoformat(),
                         "the arm still saw the tick")

    def test_venue_stop_follows_soft_tighten_only_on_protected_live(self):
        from bot_program.orcs.ghost import _mirror
        st = {"side": "BUY", "soft_stop": 100.2, "venue_stop": 98.0,
              "asset_class": "crypto", "symbol": "BTCUSD",
              "init_in_meta": True}
        _mirror(st, 101.0)
        self.assertEqual(st["venue_stop"], 100.2)
        st["soft_stop"] = 99.5
        _mirror(st, 101.0)
        self.assertEqual(st["venue_stop"], 100.2, "tighten-only")
        st["soft_stop"] = 101.5
        _mirror(st, 101.2)
        self.assertEqual(st["venue_stop"], 100.2, "never past the mark")
        self.assertEqual(st["mirror_refused"], 1)
        st["soft_stop"] = 100.123456
        st["venue_stop"] = 99.0
        _mirror(st, 101.0)
        self.assertEqual(st["venue_stop"], 100.12, "printed precision")
        short = {"side": "SELL", "soft_stop": 99.8, "venue_stop": 102.0,
                 "asset_class": "crypto", "symbol": "BTCUSD",
                 "init_in_meta": False, "initial_stop": 102.0}
        _mirror(short, 99.0)
        self.assertEqual((short["venue_stop"], short["init_in_meta"],
                          short["initial_stop"]), (99.8, True, 102.0))

    def test_paper_scale_out_banked_like_the_care(self):
        from bot_program.orcs import pricing
        _switch("aragorn_scale_out")
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(30), "102.2")])
        row.refresh_from_db()
        self.assertEqual(row.qty, Decimal("0.5"), "the care banked half")
        tracks = tracks_of(orc)
        tick = pricing.Tick(at=_at(30), p=102.2)
        for arm in ("care", "orc_shadow"):
            st = tracks[arm].state
            self.assertEqual(st["qty_open"], 0.5, arm)
            self.assertEqual(len(st["banked"]), 1, arm)
            self.assertEqual(st["banked"][0]["qty"], 0.5)
            self.assertAlmostEqual(st["banked"][0]["px"],
                                   pricing.market_exit_px(tick, "BUY",
                                                          st["cf"]))

    def test_between_ticks_paper_replay_on_own_levels(self):
        from bot_program.orcs.models import OrcTrack
        from bot_program.orcs import pricing
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(10), "100.5")])
        ghost = tracks_of(orc)["care"]
        self.assertTrue(ghost.state["replay"], "the row's stamp, copied")
        self.assertFalse(ghost.state["replay_own"])
        st = dict(ghost.state)
        st["soft_stop"], st["soft_why"] = 101.0, "its own lock"
        OrcTrack.objects.filter(pk=ghost.pk).update(state=st)
        # a bar between the ticks dips to 100.6: under the ghost's 101.0,
        # far above the row's 98
        _bars("BTCUSD", "1h", [(101.3, 101.4, 100.6, 101.1)],
              start=T0 + timedelta(hours=1))
        drive(self, self.cfg, row, [(_at(130), "101.5")])
        self.assertEqual(row.status, "OPEN")
        ghost.refresh_from_db()
        self.assertFalse(ghost.open)
        self.assertEqual(ghost.state["exit"]["kind"], "resting")
        self.assertAlmostEqual(float(ghost.exit_price),
                               pricing.level_exit_px(101.0, "BUY",
                                                     st["cf"]))


class TheVenueEventTests(_Base):

    def _live(self):
        cfg = _config(self.user, mode="live", name="live")
        row = _row(cfg, paper=False, meta={
            "protected": True, "protective_trade_id": "P1",
            "broker": "etoro", "broker_env": "live"})
        _open_at(row)
        orc = born(self, row)
        from bot_program.asset_engine.base import make_bot
        bot = make_bot(cfg)
        client = MagicMock()
        client.close_needs_position_id.return_value = True
        client.get_positions.return_value = []
        client.modify_protective.return_value = {"ok": True, "price": None}
        return cfg, row, orc, bot, client

    def test_care_decided_close_venue_unlisted_ghost_waits_for_the_venue_event(self):
        from bot_program.orcs import ghost
        cfg, row, orc, bot, client = self._live()
        care_tick(self, bot, row, "102.5", client, _at(30))
        self.assertEqual(float(row.stop_loss), 100.2, "the mirror moved it")
        st = tracks_of(orc)["care"].state
        self.assertEqual((st["soft_stop"], st["venue_stop"]), (100.2, 100.2))
        cared = care_tick(self, bot, row, "100.0", client, _at(60))
        self.assertEqual(cared, "", "the venue does not list it: held")
        g = tracks_of(orc)["care"]
        self.assertTrue(g.open, "the ghost waits for the venue's event")
        self.assertTrue(g.state["waits_for_venue"])
        # the reconcile books the venue's stop fill
        row.status, row.outcome = "CLOSED", "stopped_out"
        row.exit_price = Decimal("100.2")
        row.closed_at = _at(70)
        row.metadata = {**row.metadata, "exit_fill_source": "venue_stop",
                        "exit_price_inferred": True}
        row.reason = (row.reason or "") + " | reconciled"
        with self.captureOnCommitCallbacks(execute=True):
            row.save()
        ghost.step_bars(orc, now=_at(90))
        tracks = tracks_of(orc)
        self.assertFalse(tracks["care"].open)
        self.assertFalse(tracks["orc_shadow"].open)
        self.assertEqual(tracks["care"].exit_price,
                         tracks["orc_shadow"].exit_price)
        self.assertEqual(tracks["care"].exit_r - tracks["orc_shadow"].exit_r,
                         0.0, "the same event, the same price")
        # the venue's fill is read from the reconcile: kept, and flagged
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcJournal, OrcTrack
        OrcTrack.objects.filter(orc=orc, open=True).update(
            open=False, exit_r=0.0, exit_price=Decimal("100"),
            exit_at=_at(90))
        orc.refresh_from_db()
        grade(orc, now=_at(95))
        body = OrcJournal.objects.get(orc=orc, kind="grade").body
        self.assertIs(body["flags"]["inferred_exit"], True)

    def test_app_close_is_a_hand_act_venue_stop_fill_is_not(self):
        from types import SimpleNamespace

        from bot_program.orcs.ghost import real_exit_of
        orc = SimpleNamespace(killed=False)
        app = SimpleNamespace(
            status="CLOSED", reason="x | reconciled-orphan",
            outcome="manual_close", metadata={}, closed_at=_at(5),
            paper=False, stop_loss=Decimal("98"), take_profit=None)
        self.assertEqual((real_exit_of(orc, app).kind,
                          real_exit_of(orc, app).hand), ("hand", "app_close"))
        fill = SimpleNamespace(
            status="CLOSED", reason="x | reconciled-orphan",
            outcome="stopped_out", closed_at=_at(5), paper=False,
            metadata={"exit_fill_source": "venue_stop", "protected": True},
            stop_loss=Decimal("100.2"), take_profit=None)
        rx = real_exit_of(orc, fill)
        self.assertEqual((rx.kind, rx.hand, rx.level),
                         ("venue_stop", "", 100.2))
        hand = SimpleNamespace(status="CLOSED", reason="t | closed:MANUAL",
                               outcome="manual_close", metadata={},
                               closed_at=_at(5), paper=True,
                               stop_loss=None, take_profit=None)
        self.assertEqual(real_exit_of(orc, hand).hand, "hand_close")
        killed = SimpleNamespace(killed=True)
        self.assertEqual(real_exit_of(killed, fill).hand, "kill")
        self.assertIsNone(real_exit_of(orc, SimpleNamespace(status="OPEN")))


class TheHandActTests(_Base):

    def test_hand_close_switches_o_arm_to_shadow(self):
        from bot_program.orcs import ghost
        from bot_program.orcs.models import Orc
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        row.reason = (row.reason or "") + " | closed:MANUAL"
        row.status, row.outcome = "CLOSED", "manual_close"
        row.exit_price, row.closed_at = Decimal("102.0"), _at(40)
        with self.captureOnCommitCallbacks(execute=True):
            row.save()
        ghost.step_bars(orc, now=_at(50))
        o = tracks_of(orc)["orc_shadow"]
        self.assertTrue(o.open, "it runs on as a shadow")
        self.assertEqual(o.state["mode"], "shadow")
        self.assertEqual(o.state["hand"]["how"], "hand_close")
        self.assertEqual(o.state["soft_stop"], 100.2,
                         "from the previous tick's record")
        self.assertTrue(Orc.objects.get(pk=orc.pk).hand_touched)
        line = ("The operator's hand acted (closed the position) at 10:40 "
                "UTC: the Orc arm continues as a shadow from here.")
        self.assertIn(line, headlines(orc, kind="fact"), "at the close")
        ghost.step_bars(orc, now=_at(60))
        self.assertEqual(headlines(orc, kind="fact").count(line), 1, "once")

    def test_hand_edit_switches_and_the_fact_names_no_person(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import OrcJournal
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        meta = dict(row.metadata)
        meta["level_edits"] = [{"at": _at(35).isoformat(),
                                "by": "a_named_operator", "stop": "101.0",
                                "target": None, "widened": False,
                                "broker": "bot"}]
        AssetBotTrade.objects.filter(pk=row.pk).update(
            metadata=meta, stop_loss=Decimal("101.0"))
        row.refresh_from_db()
        drive(self, self.cfg, row, [(_at(40), "102.0")])
        o = tracks_of(orc)["orc_shadow"]
        self.assertEqual((o.state["mode"], o.state["hand"]["how"]),
                         ("shadow", "edit"))
        self.assertEqual(o.state["venue_stop"], 98.0,
                         "the levels before the hand moved them")
        blob = json.dumps([[e.headline, e.body] for e in
                           OrcJournal.objects.filter(orc=orc)])
        self.assertNotIn("a_named_operator", blob)
        self.assertIn("edited the levels", blob)


class TheExitTests(_Base):

    def test_orc_noise_stop_ghost_runs_on_to_a_different_exit(self):
        """An Orc tightens to a noise level (O3 would, through its own
        stop): the row is stopped there; the ghost runs on under its own
        stop to a better exit, and the difference charges the Orc."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import ghost
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        AssetBotTrade.objects.filter(pk=row.pk).update(
            stop_loss=Decimal("101.5"))
        row.refresh_from_db()
        drive(self, self.cfg, row, [(_at(60), "101.4")])
        self.assertEqual(row.status, "CLOSED")
        _bars("BTCUSD", "1h", [(101.4, 103.0, 101.3, 102.8),
                               (102.8, 104.5, 102.6, 104.2),
                               (104.2, 104.3, 102.0, 102.2)],
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=5))
        tracks = tracks_of(orc)
        o, g = tracks["orc_shadow"], tracks["care"]
        self.assertFalse(o.open)
        self.assertEqual(o.state["exit"]["kind"], "engine_sl")
        self.assertFalse(g.open)
        self.assertEqual(g.state["exit"]["kind"], "stop")
        self.assertAlmostEqual(g.state["soft_stop"], 102.5)
        delta_care = o.exit_r - g.exit_r
        self.assertLess(delta_care, -0.3, "the noise stop cost the Orc")


class TheShadowRowTests(SimpleTestCase):

    def test_arm_r_counts_the_banked_part_on_the_birth_size(self):
        from bot_program.orcs.ghost import arm_r
        st = {"side": "BUY", "entry": 100.0, "rpu": 2.0, "qty": 1.0,
              "qty_open": 0.5, "banked": [{"qty": 0.5, "px": 102.0}]}
        self.assertAlmostEqual(arm_r(st, 104.0), (0.5 * 2 + 0.5 * 4) / 2.0)
        self.assertIsNone(arm_r({**st, "rpu": None}, 104.0))


# ── the review's findings (2026-10-16), each failing before its fix ──────

G0 = datetime(2026, 10, 14, 8, 0, tzinfo=dt_tz.utc)     # the 4h grid


def _grid_bars(n_before=40, after=()):
    """Venue 4h bars on the UTC grid: `n_before` flat ones ending at 08:00,
    then the bars in `after` from 08:00 on."""
    _bars("BTCUSD", "4h", [(100.0, 100.2, 99.8, 100.0)] * n_before,
          start=G0 - timedelta(hours=4 * n_before))
    if after:
        _bars("BTCUSD", "4h", list(after), start=G0)


def _hand_close(test, row, at, price="100.3"):
    row.refresh_from_db()
    row.reason = (row.reason or "") + " | closed:MANUAL"
    row.status, row.outcome = "CLOSED", "manual_close"
    row.exit_price, row.closed_at = Decimal(price), at
    with test.captureOnCommitCallbacks(execute=True):
        row.save()


class TheOneWriterTests(_Base):
    """ONE WRITER PER PHASE (2026-10-22). The tick (the fast worker) and
    track_ghosts (the slow one) both read and bulk-wrote an idea's arms
    with no lock: a tick landing between the task's read and its write was
    lost. While the row is open the tick alone steps the arms (the
    multi-ghost walks its 4h bars there); track_ghosts takes over once the
    row is closed or cancelled."""

    def test_track_ghosts_writes_no_track_while_the_root_is_open(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from bot_program.orcs import bars as bars_mod
        from bot_program.orcs import ghost
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(10), "100.5")])
        real_frame = bars_mod.frame
        fired = []

        def frame(*a, **kw):
            # the tick runs on the fast worker while the task reads bars
            if not fired:
                fired.append(1)
                drive(self, self.cfg, row, [(_at(20), "102.5")])
            return real_frame(*a, **kw)
        before = {a: t.state for a, t in tracks_of(orc).items()}
        with patch.object(bars_mod, "frame", side_effect=frame), \
                CaptureQueriesContext(connection) as q:
            out = ghost.step_bars(orc, now=_at(21))
        self.assertEqual(out, {"stepped": 0})
        self.assertFalse([x["sql"] for x in q.captured_queries
                          if x["sql"].startswith("UPDATE")
                          and "bot_program_orctrack" in x["sql"]])
        self.assertEqual({a: t.state for a, t in tracks_of(orc).items()},
                         before)
        if not fired:
            drive(self, self.cfg, row, [(_at(20), "102.5")])
        ghost.step_bars(orc, now=_at(21))
        self.assertEqual(tracks_of(orc)["care"].state["last_tick_at"],
                         _at(20).isoformat(), "the tick's step stands")

    def test_policy_arms_walk_on_the_tick_while_open_and_on_bars_after_close(
            self):
        """The 08:00 bar holds the birth (10:00) and dips under the stop
        before it: never walked. The tick walks the 12:00 bar; the task
        writes nothing while the row is open, then walks the 16:00 bar
        once it is closed."""
        from bot_program.orcs import ghost
        _grid_bars(after=[(100.0, 100.1, 97.5, 100.0),
                          (100.0, 100.3, 99.9, 100.1),
                          (100.1, 100.3, 99.9, 100.2)])
        row = _row(self.cfg)
        _open_at(row)
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(G0 + timedelta(hours=8, minutes=10),
                                     "100.1")])
        for arm in ("chandelier3", "staged"):
            t = tracks_of(orc)[arm]
            self.assertTrue(t.open, f"{arm}: the dip before its birth")
            self.assertEqual(t.state["bar_at"],
                             (G0 + timedelta(hours=8)).isoformat(), arm)
        before = {a: t.state for a, t in tracks_of(orc).items()}
        self.assertEqual(ghost.step_bars(orc, now=G0 + timedelta(
            hours=8, minutes=20)), {"stepped": 0})
        self.assertEqual({a: t.state for a, t in tracks_of(orc).items()},
                         before)
        _hand_close(self, row, G0 + timedelta(hours=8, minutes=30))
        # a refresh's pass after 20:00 made the 16:00 bar final
        ghost.step_bars(orc, now=G0 + timedelta(hours=12, minutes=15))
        for arm in ("chandelier3", "staged"):
            t = tracks_of(orc)[arm]
            self.assertTrue(t.open, arm)
            self.assertEqual(t.state["bar_at"],
                             (G0 + timedelta(hours=12)).isoformat(), arm)

    def test_a_cancelled_root_closes_every_arm_flat(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import ghost
        from bot_program.orcs.constants import GHOST_ARMS
        row, orc = self._born()
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CANCELED", closed_at=_at(5))
        out = ghost.step_bars(orc, now=_at(10))
        self.assertEqual(sorted(out["exited"]), sorted(GHOST_ARMS))
        for arm, t in tracks_of(orc).items():
            self.assertFalse(t.open, arm)
            self.assertEqual(t.exit_r, 0.0, arm)
            self.assertEqual(float(t.exit_price), 100.0, arm)
            self.assertEqual(t.exit_why,
                             "the order was cancelled before it filled")


class TheArmIsolationTests(_Base):

    def test_one_arm_that_raises_never_stops_the_others(self):
        from bot_program.orcs import ghost

        def boom(state, env):
            raise RuntimeError("the playbook broke")
        row, orc = self._born()
        before = tracks_of(orc)["playbook"].state
        with patch.dict(ghost.STEPPERS, {"playbook": boom}), \
                self.assertLogs("bot_program.orcs.ghost", "WARNING") as logs:
            drive(self, self.cfg, row, [(_at(30), "101.0")])
        self.assertIn("the playbook did not step: the playbook broke",
                      "\n".join(logs.output))
        tracks = tracks_of(orc)
        self.assertEqual(tracks["playbook"].state, before)
        for arm in ("care", "orc_shadow", "chandelier3", "staged"):
            self.assertEqual(tracks[arm].state["last_tick_at"],
                             _at(30).isoformat(), arm)


class TheManualLaneTests(TestCase):
    """THE MANUAL LANE'S CARE IN THE TAIL. The care never cuts an
    operator's ticket on a clock; after the row closed, the arms ran the
    tail with the bot's rules: the O arm never kept the tick's context
    while it recorded the real row, and an arm that never saw a tick had
    none at all."""

    def setUp(self):
        _on()
        _switch("aragorn")
        self.user = _user("orc_manual_tail")

    def _manual(self):
        from tests.orcs.helpers import _manual_config, _manual_row
        lane = _manual_config(self.user)
        row = _manual_row(lane)
        _open_at(row)
        orc = born(self, row, at=T0)
        self.assertTrue(orc.manual)
        return lane, row, orc

    def test_manual_idea_after_a_hand_close_runs_the_manual_care_in_both_arms(
            self):
        from bot_program.orcs import ghost
        lane, row, orc = self._manual()
        drive(self, lane, row, [(_at(30), "100.4")])
        self.assertTrue(tracks_of(orc)["orc_shadow"].state["ctx"]["manual"],
                        "the O arm keeps the tick's context")
        _hand_close(self, row, _at(40))
        _bars("BTCUSD", "1h", [100.3] * 90, start=T0)
        ghost.step_bars(orc, now=T0 + timedelta(hours=91))
        t = tracks_of(orc)
        self.assertEqual((t["care"].open, t["care"].exit_why),
                         (t["orc_shadow"].open, t["orc_shadow"].exit_why))
        self.assertTrue(t["care"].open, "no clock cuts a hand ticket")

    def test_manual_idea_closed_before_its_first_tick_is_never_cut_by_a_rule(
            self):
        from bot_program.orcs import ghost
        lane, row, orc = self._manual()
        self.assertTrue(tracks_of(orc)["care"].state["manual"],
                        "frozen at the seed")
        _hand_close(self, row, _at(5))
        _bars("BTCUSD", "1h", [100.3] * 90, start=T0)
        ghost.step_bars(orc, now=T0 + timedelta(hours=91))
        for arm in ("care", "playbook", "orc_shadow"):
            t = tracks_of(orc)[arm]
            self.assertTrue(t.open, f"{arm}: {t.exit_why}")


class TheBarSourceTests(_Base):

    def test_a_paper_replay_on_platform_bars_grades_platform(self):
        """The care ghost's own replay hits its resting stop on a bar the
        public feed wrote: the arm read platform bars, and says so."""
        from bot_program.orcs.grading import bar_source
        from bot_program.orcs.models import OrcTrack
        row, orc = self._born()
        drive(self, self.cfg, row, [(_at(10), "100.5")])
        ghost_t = tracks_of(orc)["care"]
        st = dict(ghost_t.state)
        st["soft_stop"], st["soft_why"] = 101.0, "its own lock"
        OrcTrack.objects.filter(pk=ghost_t.pk).update(state=st)
        _bars("BTCUSD", "1h", [(101.3, 101.4, 100.6, 101.1)],
              start=T0 + timedelta(hours=1), source="binance_public")
        drive(self, self.cfg, row, [(_at(130), "101.5")])
        ghost_t.refresh_from_db()
        self.assertFalse(ghost_t.open)
        self.assertEqual(ghost_t.state["exit"]["kind"], "resting")
        self.assertIn("platform", ghost_t.state["bar_sources"])
        orc.seen = {**(orc.seen or {}), "menu_source": "etoro"}
        self.assertEqual(bar_source(orc, [ghost_t]), "platform")


class TheBasisTests(_Base):

    def test_playbook_reads_the_basis_the_o_arm_collected(self):
        """The O arm samples the basis (D2's fallback) once an hour; the
        playbook's menu reads those samples."""
        from bot_program.orcs import menu as menus
        from bot_program.orcs.models import OrcTrack
        _bars("BTCUSD", "1h", _wave(60, amp=0.5), start=_at(35)
              - timedelta(hours=60))
        row, orc = self._born()
        o = tracks_of(orc)["orc_shadow"]
        samples = [0.01 * k for k in range(10)]
        OrcTrack.objects.filter(pk=o.pk).update(
            state={**o.state, "basis": samples})
        with patch.object(menus, "symbol_levels",
                          wraps=menus.symbol_levels) as spy:
            drive(self, self.cfg, row, [(_at(35), "101.3")])
        self.assertTrue(spy.called, "T-STRUCT read the menu")
        self.assertEqual(spy.call_args.kwargs["basis_samples"], samples)


class ThePlaybookArmTests(_Base):
    """The P arm through the real tick: its structure trail, its thesis
    exit, and its draw trim on paper only."""

    START = datetime(2026, 8, 1, 0, 0, tzinfo=dt_tz.utc)
    NOW = START + timedelta(hours=4 * 90)

    def _structured(self):
        """An idea 0.8R up on waves of venue bars, three ticks in: the
        playbook arm has trailed its stop to the latest 1h swing."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.bars import frame
        now = self.NOW
        _bars("BTCUSD", "4h", _wave(90, base=100.0, amp=3.0, period=14),
              start=self.START)
        _bars("BTCUSD", "1h", _wave(120, base=100.0, amp=1.5, period=10),
              start=now - timedelta(hours=120))
        last = frame("BTCUSD", "1h", asset_class="crypto",
                     now=now).last_close
        entry = round(last - 1.0, 2)
        row = _row(self.cfg, entry=str(entry), stop=str(entry - 2.0),
                   target=str(entry + 20))
        AssetBotTrade.objects.filter(pk=row.pk).update(
            opened_at=now - timedelta(minutes=30))
        row.refresh_from_db()
        orc = born(self, row, at=now - timedelta(minutes=30))
        for i, px in enumerate((entry + 1.2, entry + 1.4, entry + 1.6)):
            drive(self, self.cfg, row, [(now + timedelta(minutes=5 + 20 * i),
                                         str(round(px, 2)))])
        return row, orc, entry

    def test_playbook_arm_moves_its_stop_on_t_struct_through_the_tick(self):
        row, orc, entry = self._structured()
        pb = tracks_of(orc)["playbook"].state
        self.assertIsNotNone(pb["orc_stop"])
        self.assertTrue(pb["orc_why"].startswith("T-STRUCT S1h-L"),
                        pb["orc_why"])
        self.assertGreater(pb["orc_stop"], entry - 2.0, "tighter")
        self.assertIsNone(tracks_of(orc)["care"].state.get("orc_stop"),
                          "the care ghost never trails structure")

    def test_playbook_arm_trails_structure_in_the_tail_without_look_ahead(
            self):
        """After the row closed, the playbook arm keeps trailing the 1h
        swings, on the menu as it stood at each bar's close: stepping
        to hour 12 gives the same arm whether or not the later bars are
        already stored."""
        import math

        from bot_program.orcs import ghost
        from bot_program.orcs.models import OrcTrack
        row, orc, entry = self._structured()
        at_close = tracks_of(orc)["playbook"].state["orc_stop"]
        _hand_close(self, row, self.NOW + timedelta(minutes=50),
                    price=str(entry + 1.5))
        base, prev, tail = entry + 1.5, entry + 1.5, []
        for i in range(1, 49):
            c = base + 0.08 * i + 0.6 * math.sin(2 * math.pi * i / 8)
            tail.append((round(prev, 4), round(max(prev, c) + 0.05, 4),
                         round(min(prev, c) - 0.05, 4), round(c, 4)))
            prev = c
        fields = ("state", "open", "exit_price", "exit_at", "exit_why",
                  "exit_r", "mfe_r", "tail_capped", "last_bar_at")
        saved = list(OrcTrack.objects.filter(orc=orc).values("pk", *fields))
        h12 = self.NOW + timedelta(hours=12, minutes=15)

        def arm():
            p = tracks_of(orc)["playbook"]
            return (p.open, p.state.get("orc_stop"), p.state.get("orc_why"),
                    p.state.get("tstruct_bar"), p.state.get("mfe_r"),
                    p.last_bar_at)
        # the bars up to hour 12 only
        _bars("BTCUSD", "1h", tail[:12], start=self.NOW)
        ghost.step_bars(orc, now=h12)
        known = arm()
        self.assertGreater(known[1], at_close, "the trail moved in the tail")
        self.assertTrue(known[2].startswith("T-STRUCT S1h-"))
        self.assertGreater(known[3], (self.NOW + timedelta(hours=1))
                           .isoformat())
        # the same step with the next 36 bars already in the table
        for row_ in saved:
            pk = row_.pop("pk")
            OrcTrack.objects.filter(pk=pk).update(**row_)
        _bars("BTCUSD", "1h", tail, start=self.NOW)
        ghost.step_bars(orc, now=h12)
        self.assertEqual(arm(), known, "no bar after its close was read")
        # and on: the trail climbs with the swings
        ghost.step_bars(orc, now=self.NOW + timedelta(hours=24, minutes=15))
        self.assertGreater(arm()[1], known[1])

    def test_playbook_arm_exits_on_x_thesis_through_the_tick(self):
        from bot_program.orcs.models import Orc
        # the 12:00 bar closed at 99.4; the refresh's pass after 16:00
        # rewrote it and stored the forming 16:00 bar
        _grid_bars(after=[(100.0, 100.2, 99.8, 100.0),
                          (100.0, 100.1, 99.3, 99.4),
                          (99.4, 99.5, 99.35, 99.45)])
        row = _row(self.cfg)
        _open_at(row)
        orc = born(self, row, at=T0)
        th = dict(orc.thesis)
        th["invalidation"] = [{"kind": "close_beyond", "tf": "4h",
                               "level_id": "S4h-L1", "level": 99.5,
                               "side": "below", "by": "code"}]
        Orc.objects.filter(pk=orc.pk).update(thesis=th)
        drive(self, self.cfg, row, [(G0 + timedelta(hours=8, minutes=10),
                                     "100.2")])
        self.assertEqual(row.status, "OPEN")
        t = tracks_of(orc)
        self.assertFalse(t["playbook"].open)
        self.assertEqual(t["playbook"].exit_why,
                         "X-THESIS: invalidation met (close_beyond)")
        self.assertTrue(t["care"].open, "the care reads no predicate")

    def _k_draw_env(self, state):
        from types import SimpleNamespace

        import pandas as pd

        from bot_program.orcs import pricing
        from bot_program.orcs.bars import Frame
        now = T0 + timedelta(hours=2)
        idx = pd.DatetimeIndex([now - timedelta(hours=4 * (40 - i))
                                for i in range(40)])
        df = pd.DataFrame({"open": [100.0] * 40, "high": [100.5] * 40,
                           "low": [99.5] * 40, "close": [100.0] * 40,
                           "volume": [0] * 40}, index=idx)
        f4 = Frame(symbol="BTCUSD", tf="4h", df=df, swings=[],
                   source="etoro", newest_end=now + timedelta(hours=3),
                   fresh=True, n=40)
        return SimpleNamespace(
            frame=lambda tf: f4 if tf == "4h" else None, now=now,
            tick=pricing.Tick(at=now, p=100.4), row=SimpleNamespace(
                symbol="BTCUSD", asset_class="crypto"),
            meta={}, cache={}, basis=None)

    def test_k_draw_trims_only_on_paper(self):
        from bot_program.orcs import ghost, pricing
        row, orc = self._born()
        base = tracks_of(orc)["playbook"].state
        draw = {"draw": {"price": pricing.closing_mark(
            pricing.Tick(at=T0, p=100.4), "BUY", base["cf"])}}
        out = {}
        for paper in (True, False):
            state = {**base, "paper": paper, "mfe_r": 0.2, "banked": [],
                     "kdraw_done": []}
            with patch("brain.thesis_check.structure_read",
                       return_value=draw):
                ghost._playbook_bars(state, self._k_draw_env(state))
            out[paper] = state
        self.assertEqual([b["why"] for b in out[True]["banked"]],
                         ["K-DRAW"])
        self.assertEqual(out[True]["qty_open"], 0.5)
        self.assertEqual(out[False]["banked"], [], "a real leg is never "
                         "trimmed by the playbook in O1")
        self.assertEqual(out[False]["qty_open"], base["qty_open"])


class TheMissedTicksTests(SimpleTestCase):
    """`ticks_missed` counts open-market stretches of more than thirty
    minutes with no step; a flag on the grade, never an exclusion."""

    def test_missed_ticks_count_open_market_only(self):
        from bot_program.orcs.ghost import _missed
        fri = datetime(2026, 10, 16, 20, 55, tzinfo=dt_tz.utc)
        st = {"asset_class": "forex", "symbol": "EURUSD",
              "last_tick_at": fri.isoformat(), "ticks_missed": 0}
        # the FX week shut at 21:00 and opened again at Sunday 21:00
        _missed(st, datetime(2026, 10, 18, 21, 10, tzinfo=dt_tz.utc))
        self.assertEqual(st["ticks_missed"], 0, "fifteen open minutes")
        wed = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)
        st = {"asset_class": "forex", "symbol": "EURUSD",
              "last_tick_at": wed.isoformat(), "ticks_missed": 0}
        _missed(st, wed + timedelta(minutes=45))
        self.assertEqual(st["ticks_missed"], 1)
        self.assertEqual(st["last_tick_at"],
                         (wed + timedelta(minutes=45)).isoformat())


# ── the review's findings (2026-10-22), each failing before its fix ──────

class TheRootMarkTests(_Base):
    """R_AVAIL AFTER A HAND EDIT. Once a levels edit switched the O arm to
    its shadow, the root's best mark stopped on the tick: the row was
    still open and marked, but its best between the edit and the close
    was lost."""

    def test_the_root_best_mark_runs_on_after_a_hand_edit(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import pricing
        row, orc = self._born(target="120")
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        meta = dict(row.metadata)
        meta["level_edits"] = [{"at": _at(35).isoformat(), "by": "op",
                                "stop": "99.0", "target": None,
                                "widened": False, "broker": "bot"}]
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata=meta)
        row.refresh_from_db()
        drive(self, self.cfg, row, [(_at(40), "102.6"), (_at(90), "105.0"),
                                    (_at(150), "106.0"), (_at(170), "105.5")])
        o = tracks_of(orc)["orc_shadow"].state
        self.assertEqual(o["mode"], "shadow")
        self.assertAlmostEqual(o["best_m_r"], (pricing.closing_mark(
            pricing.Tick(at=None, p=106.0), "BUY", o["cf"]) - 100) / 2)


class TheBasisSampleTests(_Base):
    """THE BASIS, HOURLY FROM THE BIRTH. It was sampled only on ticks
    where the playbook arm read the 1h frame (MFE from 0.5R to 2R), so the
    platform-bar menu started unmeasured the first time T-STRUCT needed
    it."""

    def test_flat_ticks_below_half_an_r_sample_once_an_hour(self):
        _bars("BTCUSD", "1h", _wave(212, amp=0.5),
              start=T0 - timedelta(hours=200), source="yahoo")
        row, orc = self._born()
        # flat, a little apart (an identical mark for hours is a frozen
        # feed the engine does not decide on)
        drive(self, self.cfg, row, [(T0 + timedelta(hours=h, minutes=5),
                                     f"{100.5 + 0.01 * h:.2f}")
                                    for h in range(12)])
        o = tracks_of(orc)["orc_shadow"].state
        self.assertEqual(len(o["basis"]), 12)
        self.assertEqual(o["basis_at"],
                         (T0 + timedelta(hours=11, minutes=5)).isoformat())
        self.assertLess(tracks_of(orc)["playbook"].state["mfe_r"], 0.5)


class TheFinalBarTests(SimpleTestCase):
    """T-STRUCT AND K-DRAW ACT ON FINAL BARS. The refresh stores the
    forming candle and rewrites it on its next pass: a bar that just ended
    is a snapshot until then."""

    def _frame(self, n, now):
        import pandas as pd

        from bot_program.orcs.bars import Frame
        start = now - timedelta(hours=4 * n, minutes=5)
        idx = pd.DatetimeIndex([start + timedelta(hours=4 * i)
                                for i in range(n)])
        df = pd.DataFrame({"open": [100.0] * n, "high": [100.5] * n,
                           "low": [99.5] * n, "close": [100.0] * n,
                           "volume": [0] * n}, index=idx)
        return Frame(symbol="BTCUSD", tf="4h", df=df, source="etoro",
                     newest_end=idx[-1] + timedelta(hours=4), fresh=True,
                     n=n), idx

    def test_a_bar_is_final_with_its_successor_or_a_refresh_later(self):
        from bot_program.orcs.ghost import _closed_end
        now = datetime(2026, 10, 14, 8, 5, tzinfo=dt_tz.utc)
        f, idx = self._frame(40, now)          # the last ended at 08:00
        self.assertEqual(_closed_end(f, now), "2026-10-14T04:00:00+00:00",
                         "08:00 is a snapshot: the bar before it")
        self.assertEqual(_closed_end(f, now + timedelta(minutes=15)),
                         "2026-10-14T08:00:00+00:00", "a refresh later")
        g, _ = self._frame(41, now + timedelta(hours=4))   # its successor
        self.assertEqual(_closed_end(g, now), "2026-10-14T08:00:00+00:00")


class TheTailPlaybookTests(_Base):
    """THE PLAYBOOK ARM'S OWN CODE AFTER THE CLOSE. In the tail it ran only
    T-STRUCT: a predicate met after a hand close left it holding to its
    care stop or the 30-day cap, and the draw never trimmed."""

    def _hand_closed_at_10_30(self, thesis):
        from bot_program.orcs.models import Orc
        row = _row(self.cfg)
        _open_at(row)
        orc = born(self, row, at=T0)
        th = dict(orc.thesis)
        th["invalidation"] = thesis
        Orc.objects.filter(pk=orc.pk).update(thesis=th)
        orc.refresh_from_db()
        drive(self, self.cfg, row, [(_at(10), "100.1")])
        _hand_close(self, row, _at(30), price="100.1")
        orc.refresh_from_db()
        return row, orc

    def test_a_4h_close_beyond_after_a_hand_close_exits_at_that_bar(self):
        from bot_program.orcs import ghost, pricing
        _grid_bars(after=[(100.0, 100.2, 99.8, 100.0),
                          (100.0, 100.1, 99.3, 99.3)])
        row, orc = self._hand_closed_at_10_30([
            {"kind": "close_beyond", "tf": "4h", "level_id": "S4h-L1",
             "level": 99.5, "side": "below", "by": "code"}])
        _bars("BTCUSD", "1h", [100.0] * 5, start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=G0 + timedelta(hours=8, minutes=15))
        t = tracks_of(orc)
        pb = t["playbook"]
        self.assertFalse(pb.open)
        self.assertEqual(pb.exit_why, "X-THESIS: invalidation met "
                                      "(close_beyond)")
        self.assertEqual(pb.exit_at, G0 + timedelta(hours=8),
                         "at the close of the 4h bar beyond the level")
        self.assertAlmostEqual(float(pb.exit_price), pricing.market_exit_px(
            pricing.Tick(at=None, p=100.0), "BUY", pb.state["cf"]), places=6)
        self.assertTrue(t["care"].open, "the care reads no predicate")

    def test_k_draw_trims_a_paper_arm_in_the_tail(self):
        from bot_program.orcs import ghost, pricing
        _grid_bars(after=[(100.0, 100.2, 99.8, 100.0),
                          (100.0, 100.3, 99.9, 100.2)])
        row, orc = self._hand_closed_at_10_30([])
        _bars("BTCUSD", "1h", [100.2] * 5, start=T0 + timedelta(hours=1))
        cf = tracks_of(orc)["playbook"].state["cf"]
        m = pricing.closing_mark(pricing.Tick(at=None, p=100.2), "BUY", cf)
        with patch("brain.thesis_check.structure_read",
                   return_value={"draw": {"price": m}}):
            ghost.step_bars(orc, now=G0 + timedelta(hours=8, minutes=15))
        pb = tracks_of(orc)["playbook"].state
        self.assertEqual([b["why"] for b in pb["banked"]], ["K-DRAW"],
                         "once per draw")
        self.assertEqual(pb["banked"][0]["at"],
                         (G0 + timedelta(hours=4)).isoformat(),
                         "at the first 4h close after the hand close")
        self.assertEqual(pb["qty_open"], 0.5)
        self.assertEqual(tracks_of(orc)["care"].state["banked"], [],
                         "the care ghost never trims on a draw")


class TheFinalPolicyBarTests(_Base):

    def test_the_multi_ghost_walks_a_4h_bar_once_it_is_final(self):
        """The 12:00 bar ended at 16:00: at 16:05 the refresh has not
        rewritten it, and a walked bar is never walked again."""
        _grid_bars(after=[(100.0, 100.2, 99.8, 100.0),
                          (100.0, 100.3, 99.9, 100.1)])
        row = _row(self.cfg)
        _open_at(row)
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(G0 + timedelta(hours=8, minutes=5),
                                     "100.1")])
        for arm in ("chandelier3", "staged"):
            self.assertEqual(tracks_of(orc)[arm].state["bar_at"],
                             T0.isoformat(), f"{arm}: a snapshot")
        drive(self, self.cfg, row, [(G0 + timedelta(hours=8, minutes=15),
                                     "100.15")])
        for arm in ("chandelier3", "staged"):
            self.assertEqual(tracks_of(orc)[arm].state["bar_at"],
                             (G0 + timedelta(hours=8)).isoformat(), arm)
