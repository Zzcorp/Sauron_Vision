"""THE GRADE (bot_program/orcs/grading.py, spec §6.1-6.4): one per dead idea,
once every arm resolved, priced by one function, forward-only, never moving
a seat; the tail on the venue's bars after the row closed, to its cap.

Run with:  python manage.py test tests.orcs.test_orc_grading
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import (_bars, _config, _manual_config, _manual_row,
                                _on, _row, _switch, _user, born, drive,
                                headlines, tracks_of)

T0 = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)


def _at(minutes):
    return T0 + timedelta(minutes=minutes)


class TheNumbersTests(SimpleTestCase):

    EXITS = {"orc_shadow": 0.8, "care": 1.1, "playbook": 0.9,
             "chandelier3": 0.4, "staged": 0.6}

    def test_capture_only_from_half_r(self):
        from bot_program.orcs.grading import numbers
        low = numbers(exits=self.EXITS, r_money=50, r_avail=0.4)
        self.assertIsNone(low["capture_orc"])
        high = numbers(exits=self.EXITS, r_avail=2.0, r_money=50)
        self.assertAlmostEqual(high["capture_orc"], 0.4)
        self.assertAlmostEqual(high["capture_ghost"], 0.55)
        self.assertAlmostEqual(high["capture_play"], 0.45)

    def test_net_edge_money_and_orc_r(self):
        from bot_program.orcs.grading import numbers
        n = numbers(exits=self.EXITS, r_money=Decimal("50"), r_avail=1.5)
        self.assertAlmostEqual(n["delta_care"], -0.3)
        self.assertAlmostEqual(n["delta_play"], -0.1)
        self.assertAlmostEqual(n["net_edge_money"], -15.0)
        self.assertAlmostEqual(n["orc_r"], 0.8, msg="no AI cost in O1")
        self.assertEqual(n["policy_r"], {"chandelier3": 0.4, "staged": 0.6})
        costed = numbers(exits=self.EXITS, r_money=50, ai_cost=0.5)
        self.assertAlmostEqual(costed["orc_r"], 0.79)
        self.assertAlmostEqual(costed["net_edge_money"], -15.5)

    def test_no_r_no_numbers(self):
        from bot_program.orcs.grading import numbers
        n = numbers(exits=self.EXITS, r_money=None, pnl=12, r_avail=2.0)
        self.assertTrue(all(v is None for k, v in n.items()
                            if k != "policy_r"))

    def test_actual_r_never_in_delta(self):
        from bot_program.orcs.grading import numbers
        a = numbers(exits=self.EXITS, r_money=50, pnl=5)
        b = numbers(exits=self.EXITS, r_money=50, pnl=500)
        self.assertEqual(a["delta_care"], b["delta_care"])
        self.assertEqual(a["net_edge_money"], b["net_edge_money"])
        self.assertAlmostEqual(b["actual_r"], 10.0)


class _Graded(TestCase):

    def setUp(self):
        _on()
        _switch("aragorn")
        self.user = _user("orc_grade")
        self.cfg = _config(self.user)

    def _dead(self, *, exits=None, meta_source="etoro", sources=("etoro",),
              hand=False, row=None):
        """A dead idea whose arms are closed at the given R."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcTrack
        row = row or _row(self.cfg)
        orc = born(self, row)
        exits = exits or TheNumbersTests.EXITS
        for t in OrcTrack.objects.filter(orc=orc):
            st = dict(t.state)
            st["bar_sources"] = list(sources)
            if t.arm == "orc_shadow":
                st["best_m_r"] = 1.6
            OrcTrack.objects.filter(pk=t.pk).update(
                open=False, exit_r=exits[t.arm], exit_price=Decimal("101"),
                exit_at=_at(60), exit_why="x", state=st)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", outcome="stopped_out", pnl=Decimal("3"),
            exit_price=Decimal("101"), closed_at=_at(60))
        seen = dict(orc.seen)
        seen["menu_source"] = meta_source
        Orc.objects.filter(pk=orc.pk).update(state="dead", died_at=_at(60),
                                             seen=seen, hand_touched=hand)
        orc.refresh_from_db()
        return orc


class TheGradeTests(_Graded):

    def test_one_grade_per_idea(self):
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcGrade
        orc = self._dead()
        g = grade(orc, now=_at(70))
        self.assertIsNotNone(g)
        self.assertIs(type(grade(orc, now=_at(80))), type(g))
        self.assertEqual(OrcGrade.objects.filter(orc=orc).count(), 1)
        self.assertEqual(len(headlines(orc, kind="grade")), 1)
        self.assertEqual(headlines(orc, kind="grade")[0],
                         "Graded (shadow, no Orc action): the position "
                         "+0.80R, the care ghost +1.10R, the playbook "
                         "+0.90R; Δ against the care -0.30R. Won.")
        self.assertEqual((g.fell, g.sub_label, g.bar_source,
                          g.counts_for_seat),
                         ("won", "", "etoro", True))
        self.assertAlmostEqual(g.capture_orc, 0.8 / 1.6)

    def test_no_grade_while_an_arm_is_open_or_the_idea_lives(self):
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcTrack
        orc = self._dead()
        OrcTrack.objects.filter(orc=orc, arm="staged").update(open=True)
        self.assertIsNone(grade(orc, now=_at(70)))
        live = born(self, _row(self.cfg, symbol="ETHUSD"))
        self.assertIsNone(grade(live, now=_at(70)))

    def test_no_seat_moves(self):
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcSeat
        orc = self._dead()
        before = list(OrcSeat.objects.values())
        grade(orc, now=_at(70))
        self.assertEqual(list(OrcSeat.objects.values()), before)

    def test_hand_close_counts_flagged_hand_touched(self):
        from bot_program.orcs.grading import grade
        orc = self._dead(hand=True)
        g = grade(orc, now=_at(70))
        self.assertTrue(g.hand_touched)
        self.assertTrue(g.counts_for_seat, "a hand act censors nothing")

    def test_bar_source_never_pooled(self):
        from bot_program import scorecard as sc
        from bot_program.orcs.grading import grade
        a = grade(self._dead(), now=_at(70))
        b = grade(self._dead(row=_row(self.cfg, symbol="ETHUSD"),
                             sources=("etoro", "platform")), now=_at(70))
        c = grade(self._dead(row=_row(self.cfg, symbol="SOLUSD"),
                             meta_source="basis-shifted"), now=_at(70))
        self.assertEqual((a.bar_source, b.bar_source, c.bar_source),
                         ("etoro", "platform", "platform"))
        rows = sc.orc_rows(days=30, now=_at(120))
        groups = sc.group(rows, lambda r: (r["asset_class"], r["venue"],
                                           r["bar_source"], r["level"]))
        self.assertEqual(sorted(len(v) for v in groups.values()), [1, 2])

    def test_a_late_seed_never_counts(self):
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcTrack
        orc = self._dead()
        t = OrcTrack.objects.get(orc=orc, arm="care")
        OrcTrack.objects.filter(pk=t.pk).update(state={**t.state,
                                                       "seed": "late"})
        self.assertFalse(grade(orc, now=_at(70)).counts_for_seat)

    def test_ticks_missed_is_a_flag_never_an_exclusion(self):
        """§6.4 names no such exclusion: an idea whose ticks stopped
        for a while counts, and its grade says so."""
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcJournal, OrcTrack
        orc = self._dead()
        for arm in ("orc_shadow", "care"):
            t = OrcTrack.objects.get(orc=orc, arm=arm)
            OrcTrack.objects.filter(pk=t.pk).update(state={
                **t.state, "ticks_missed": 2})
        g = grade(orc, now=_at(70))
        self.assertTrue(g.counts_for_seat)
        body = OrcJournal.objects.get(orc=orc, kind="grade").body
        self.assertEqual(body["flags"]["ticks_missed"], 4)
        self.assertTrue(body["counts_for_seat"])

    def test_an_unfaithful_ghost_never_counts(self):
        """The seat's unit is O against G: a care ghost whose soft stop
        left the care's is no reference, so the idea is graded but never
        counted (the care's own soft stop never carries an Orc level,
        §3.3, so this holds in every PR)."""
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcJournal, OrcTrack
        orc = self._dead()
        t = OrcTrack.objects.get(orc=orc, arm="orc_shadow")
        faith = {**t.state["faith"], "ticks": 9, "soft_mismatch": 1,
                 "differ": 1}
        OrcTrack.objects.filter(pk=t.pk).update(state={**t.state,
                                                       "faith": faith})
        g = grade(orc, now=_at(70))
        self.assertFalse(g.counts_for_seat)
        self.assertIsNotNone(g.delta_care, "graded all the same")
        body = OrcJournal.objects.get(orc=orc, kind="grade").body
        self.assertEqual(body["flags"]["soft_mismatch"], 1)
        # a venue-stop difference alone (a refused mirror) still counts
        orc2 = self._dead(row=_row(self.cfg, symbol="ETHUSD"))
        t = OrcTrack.objects.get(orc=orc2, arm="orc_shadow")
        OrcTrack.objects.filter(pk=t.pk).update(state={**t.state, "faith": {
            **t.state["faith"], "ticks": 9, "venue_mismatch": 2,
            "differ": 2}})
        self.assertTrue(grade(orc2, now=_at(70)).counts_for_seat)

    def test_no_grade_for_a_living_idea(self):
        """Every arm closed while the row is still open (the arms can all
        exit before it): no grade until the idea is dead."""
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcGrade, OrcTrack
        live = born(self, _row(self.cfg, symbol="ETHUSD"))
        OrcTrack.objects.filter(orc=live).update(
            open=False, exit_r=0.5, exit_price=Decimal("101"),
            exit_at=_at(60))
        self.assertIsNone(grade(live, now=_at(70)))
        self.assertFalse(OrcGrade.objects.filter(orc=live).exists())

    def test_level_at_birth_is_frozen(self):
        """The seat's level when the idea was born, not when it is graded:
        a seat promoted in between changes nothing."""
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcSeat
        orc = self._dead()
        self.assertEqual(orc.seen["level_at_birth"], 0)
        OrcSeat.objects.filter(pk=orc.seat_id).update(level=2)
        orc.refresh_from_db()
        self.assertEqual(grade(orc, now=_at(70)).level_at_birth, 0)


class TheTailTests(_Graded):

    def _closed_by_hand_stop(self):
        """A paper row moved to break-even, then stopped where its row's
        stop was tightened (O3's Orc stop): the arms run on after it."""
        from bot_program.models import AssetBotTrade
        row = _row(self.cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row)
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        AssetBotTrade.objects.filter(pk=row.pk).update(
            stop_loss=Decimal("101.5"))
        row.refresh_from_db()
        drive(self, self.cfg, row, [(_at(60), "101.4")])
        return orc, row

    def test_ghost_equals_direct_plan_loop_for_row_with_no_orc(self):
        from bot_program.position_care import plan
        from tests.test_aragorn import _row as care_row
        from bot_program.models import AssetBotTrade
        marks = [(_at(30 * i), p) for i, p in enumerate(
            ["101.0", "102.2", "103.0", "104.2", "103.6", "102.1"], start=1)]
        row = _row(self.cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row)
        drive(self, self.cfg, row, marks)
        plain = care_row(cls="crypto", paper=True)
        plain.opened_at = T0
        care, closed_at = {}, None
        for at, p in marks:
            plain.metadata = {"initial_stop_loss": 98.0, "care": care}
            out = plan(plain, float(p), now=at, live=False)
            care = {k: v for k, v in out["care"].items() if k != "exit"}
            if out["action"] == "close":
                closed_at = at
                break
        g = tracks_of(orc)["care"]
        for key in ("peak", "worst", "soft_stop", "soft_why", "mfe_r"):
            self.assertEqual(g.state[key], care.get(key), key)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(g.exit_at, closed_at, "the ghost closed with it")
        self.assertEqual(g.state["exit"]["kind"], "care")

    def test_tail_on_bars_gap_tie_catch_up_idempotent(self):
        from bot_program.orcs import ghost, pricing
        orc, row = self._closed_by_hand_stop()
        _bars("BTCUSD", "1h", [(101.4, 102.0, 101.0, 101.8)],
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=5))
        self.assertIsNone(tracks_of(orc)["care"].last_bar_at,
                          "a snapshot until the refresh's next pass")
        ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=15))
        g = tracks_of(orc)["care"]
        self.assertTrue(g.open)
        self.assertEqual(g.last_bar_at, T0 + timedelta(hours=2))
        state = dict(g.state)
        ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=30))
        self.assertEqual(tracks_of(orc)["care"].state, state,
                         "no new bar: nothing moves")
        # catch-up: two bars at once, the second gaps through the stop
        _bars("BTCUSD", "1h", [(101.8, 102.1, 101.2, 101.5),
                               (99.9, 100.0, 99.5, 99.8)],
              start=T0 + timedelta(hours=2))
        ghost.step_bars(orc, now=T0 + timedelta(hours=5))
        g = tracks_of(orc)["care"]
        self.assertFalse(g.open)
        self.assertEqual(g.state["exit"]["kind"], "gap")
        self.assertAlmostEqual(float(g.exit_price), pricing.level_exit_px(
            99.9, "BUY", g.state["cf"]), places=6)
        exit_r = g.exit_r
        ghost.step_bars(orc, now=T0 + timedelta(hours=6))
        self.assertEqual(tracks_of(orc)["care"].exit_r, exit_r)

    def test_a_tie_in_the_tail_goes_to_the_stop(self):
        from bot_program.orcs import ghost
        from bot_program.orcs.models import OrcTrack
        orc, row = self._closed_by_hand_stop()
        t = tracks_of(orc)["care"]
        OrcTrack.objects.filter(pk=t.pk).update(state={**t.state,
                                                       "target": 103.0})
        _bars("BTCUSD", "1h", [(101.4, 103.5, 100.0, 101.0)],
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=3))
        g = tracks_of(orc)["care"]
        self.assertEqual(g.state["exit"]["kind"], "stop")
        self.assertIn("100.2", g.exit_why)

    def test_tail_cap_bot_and_manual_marked_to_market(self):
        """No bar after the close: a bar of each arm's timeframe past the
        cap (the bar that spans it may still come), every arm still open
        is marked at the newest price known, the O arm's last tick."""
        from bot_program.orcs import ghost, pricing
        orc, row = self._closed_by_hand_stop()
        cap = ghost.tail_cap(orc, row)
        self.assertEqual(cap, orc.born_at + timedelta(hours=72 * 1.5))
        arms = ("care", "playbook", "chandelier3", "staged")
        ghost.step_bars(orc, now=cap + timedelta(minutes=1))
        self.assertTrue(all(tracks_of(orc)[a].open for a in arms))
        ghost.step_bars(orc, now=cap + timedelta(hours=1, minutes=15))
        tracks = tracks_of(orc)
        last = tracks["orc_shadow"].state["last"]["p"]
        for arm in ("care", "playbook"):
            t = tracks[arm]
            self.assertEqual((t.open, t.tail_capped), (False, True), arm)
            self.assertEqual(t.exit_at, cap)
            self.assertAlmostEqual(float(t.exit_price), pricing.market_exit_px(
                pricing.Tick(at=cap, p=last), "BUY", t.state["cf"]), places=6)
        self.assertTrue(tracks["staged"].open, "a 4h bar past the cap")
        ghost.step_bars(orc, now=cap + timedelta(hours=4, minutes=15))
        for arm in arms:
            self.assertFalse(tracks_of(orc)[arm].open, arm)
            self.assertTrue(tracks_of(orc)[arm].tail_capped, arm)
        self.assertIn("The care ghost reached its tail cap and was marked "
                      "to market at ", "\n".join(headlines(orc)))
        lane = _manual_config(self.user)
        hand = _manual_row(lane, symbol="ETHUSD")
        hand_orc = born(self, hand)
        hand.status, hand.closed_at = "CLOSED", T0
        self.assertEqual(ghost.tail_cap(hand_orc, hand),
                         T0 + timedelta(days=30))


# ── the review's findings (2026-10-22), each failing before its fix ──────

def _orc_tables():
    """The Orcs' own tables, from their models (an `orc` prefix alone would
    also take bot_program's orchestrator table)."""
    from django.apps import apps
    return {m._meta.db_table for m in apps.get_models()
            if m.__module__ == "bot_program.orcs.models"}


def _written_tables(queries):
    import re
    out = []
    for q in queries:
        m = re.match(r'\s*(?:INSERT INTO|UPDATE|DELETE FROM)\s+"([^"]+)"',
                     q["sql"])
        if m:
            out.append((q["sql"].split()[0].upper(), m.group(1)))
    return out


def _closed_now(test, row, at, **fields):
    """The row closed at `at` (a plain update, as a reconcile books it)
    and its Orc dead, as the death receiver or the sweep leaves it."""
    from bot_program.models import AssetBotTrade
    from bot_program.orcs.models import Orc
    values = {"status": "CLOSED", "closed_at": at,
              "exit_price": Decimal("101"), "reason": "t | closed:SIGNAL",
              "outcome": "win"}
    values.update(fields)
    AssetBotTrade.objects.filter(pk=row.pk).update(**values)
    row.refresh_from_db()
    Orc.objects.filter(root_trade=row).update(state="dead", died_at=at)


def _hand_closed(test, row, at, price="102.0"):
    row.refresh_from_db()
    row.reason = (row.reason or "") + " | closed:MANUAL"
    row.status, row.outcome = "CLOSED", "manual_close"
    row.exit_price, row.closed_at = Decimal(price), at
    with test.captureOnCommitCallbacks(execute=True):
        row.save()


class TheEveryIdeaEndsTests(_Graded):
    """EVERY IDEA ENDS. One arm that raised in step_bars froze the whole
    idea for good: never graded, and its closed real symbol asked of
    eToro on every bar pass. A row with no stop raised in every policy
    walk, an O1a care track on a dead Orc raised in the tail, and an O arm
    whose real exit nobody priced stayed open past the cap."""

    def _open(self, row):
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        return born(self, row, at=T0)

    def test_a_row_with_no_stop_ends_and_is_graded_without_an_r(self):
        from bot_program.orcs import ghost
        from bot_program.orcs.grading import grade
        row = _row(self.cfg, stop=None)
        orc = self._open(row)
        with self.assertNoLogs("bot_program.orcs.ghost", "WARNING"):
            drive(self, self.cfg, row, [(_at(10), "100.5")])
        for arm in ("chandelier3", "staged"):
            t = tracks_of(orc)[arm]
            self.assertEqual((t.open, t.exit_why, t.exit_r),
                             (False, "no R: the row has no stop", None), arm)
        closed = _at(120)
        _closed_now(self, row, closed)
        orc.refresh_from_db()
        _bars("BTCUSD", "1h", [100.5] * 10, start=closed)
        with self.assertNoLogs("bot_program.orcs.ghost", "WARNING"):
            ghost.step_bars(orc, now=closed + timedelta(hours=11))
        self.assertTrue(tracks_of(orc)["care"].open, "it walks its tail")
        cap = ghost.tail_cap(orc, row)
        ghost.step_bars(orc, now=cap + timedelta(hours=4, minutes=15))
        self.assertEqual([a for a, t in tracks_of(orc).items() if t.open], [])
        g = grade(orc, now=cap + timedelta(hours=5))
        self.assertIsNotNone(g, "graded: no idea is frozen")
        self.assertEqual((g.orc_r_gross, g.delta_care, g.counts_for_seat),
                         (None, None, False), "no R, no numbers")

    def test_an_o1a_care_track_on_a_dead_orc_is_upgraded_and_walks(self):
        from bot_program.orcs import census, ghost, tracks
        from bot_program.orcs.models import OrcTrack
        row = _row(self.cfg, paper=False)
        orc = self._open(row)
        # as O1a left it: the care arm alone, in O1a's format (no `cf`)
        OrcTrack.objects.filter(orc=orc).exclude(arm="care").delete()
        OrcTrack.objects.filter(orc=orc, arm="care").update(
            state=tracks.seed_care(orc, row))
        closed = _at(120)
        _closed_now(self, row, closed, reason="t | closed:SL",
                    outcome="stopped_out")
        orc.refresh_from_db()
        _bars("BTCUSD", "1h", [100.5] * 10, start=closed)
        census._seed_late(closed + timedelta(hours=11))   # living Orcs only
        ghost.step_bars(orc, now=closed + timedelta(hours=11))
        t = tracks_of(orc)["care"]
        self.assertIn("cf", t.state, "upgraded in place")
        self.assertEqual(t.state["seed"], "late")
        self.assertEqual(t.last_bar_at, closed + timedelta(hours=10))
        cap = ghost.tail_cap(orc, row)
        ghost.step_bars(orc, now=cap + timedelta(hours=1, minutes=15))
        self.assertFalse(tracks_of(orc)["care"].open)

    def test_an_unpriced_real_exit_is_closed_at_the_cap_and_flagged(self):
        from bot_program.orcs import ghost, pricing
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcJournal
        row = _row(self.cfg)
        orc = self._open(row)
        drive(self, self.cfg, row, [(_at(10), "100.5")])
        closed = _at(120)
        _closed_now(self, row, closed, exit_price=None,
                    reason="t | closed:other", outcome="")
        orc.refresh_from_db()
        ghost.step_bars(orc, now=closed + timedelta(hours=1))
        self.assertTrue(tracks_of(orc)["orc_shadow"].open,
                        "the row's price may still be booked")
        cap = ghost.tail_cap(orc, row)
        ghost.step_bars(orc, now=cap + timedelta(hours=4, minutes=15))
        tracks = tracks_of(orc)
        self.assertEqual([a for a, t in tracks.items() if t.open], [])
        o = tracks["orc_shadow"]
        self.assertEqual((o.state["exit"]["kind"], o.state["exit"]["inferred"],
                          o.exit_at), ("unpriced", True, closed))
        self.assertAlmostEqual(float(o.exit_price), pricing.market_exit_px(
            pricing.Tick(at=_at(10), p=100.5), "BUY", o.state["cf"]),
            places=6)
        grade(orc, now=cap + timedelta(hours=5))
        body = OrcJournal.objects.get(orc=orc, kind="grade").body
        self.assertTrue(body["flags"]["inferred_exit"])


class TheWritesTests(_Graded):

    def test_step_bars_and_the_grade_write_only_orc_tables(self):
        """Hard rule: everything O1 adds writes only the Orc tables."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from bot_program.models import AssetBotTrade
        from bot_program.orcs import ghost
        from bot_program.orcs.grading import grade
        row = _row(self.cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(_at(10), "100.5")])
        _closed_now(self, row, _at(20))
        orc.refresh_from_db()
        _bars("BTCUSD", "1h", [100.5] * 4, start=T0 + timedelta(hours=1))
        cap = ghost.tail_cap(orc, row)
        with CaptureQueriesContext(connection) as q:
            ghost.step_bars(orc, now=T0 + timedelta(hours=5))
            ghost.step_bars(orc, now=cap + timedelta(hours=4, minutes=15))
            self.assertIsNotNone(grade(orc, now=cap + timedelta(hours=5)))
        writes = _written_tables(q.captured_queries)
        self.assertEqual([w for w in writes if w[1] not in _orc_tables()], [])
        self.assertIn(("UPDATE", "bot_program_orctrack"), writes)
        self.assertIn(("INSERT", "bot_program_orcgrade"), writes)


class TheTailFenceTests(_Graded):

    _closed_by_hand_stop = TheTailTests._closed_by_hand_stop

    def test_an_arm_that_raises_never_stops_the_others_nor_the_cap(self):
        from unittest.mock import patch

        from bot_program.orcs import ghost
        orc, row = self._closed_by_hand_stop()
        _bars("BTCUSD", "1h", [(101.4, 102.0, 101.0, 101.8)] * 2,
              start=T0 + timedelta(hours=1))
        before = {a: tracks_of(orc)[a].state for a in ("staged", "playbook")}
        real = ghost._tail_bar

        def flaky(state, bar, **kw):
            if state.get("version"):            # the playbook arm only
                raise RuntimeError("the playbook broke")
            return real(state, bar, **kw)
        with patch.object(ghost, "_policy_walk",
                          side_effect=RuntimeError("the walk broke")), \
                patch.object(ghost, "_tail_bar", side_effect=flaky), \
                self.assertLogs("bot_program.orcs.ghost", "WARNING") as logs:
            ghost.step_bars(orc, now=T0 + timedelta(hours=3, minutes=15))
        said = "\n".join(logs.output)
        self.assertIn("the staged did not walk its bars: the walk broke", said)
        self.assertIn("the playbook did not walk its bars: the playbook "
                      "broke", said)
        tracks = tracks_of(orc)
        self.assertEqual(tracks["care"].last_bar_at,
                         T0 + timedelta(hours=3), "the others walked")

        def bare(state):
            return {k: v for k, v in state.items() if k != "shared"}
        for arm in ("staged", "playbook"):
            self.assertTrue(tracks[arm].open, arm)
            self.assertEqual(bare(tracks[arm].state), bare(before[arm]),
                             f"{arm}: put back as it stood")
        self.assertIsNone(tracks["playbook"].last_bar_at)
        cap = ghost.tail_cap(orc, row)
        with patch.object(ghost, "_policy_walk",
                          side_effect=RuntimeError("the walk broke")), \
                patch.object(ghost, "_tail_bar", side_effect=flaky):
            ghost.step_bars(orc, now=cap + timedelta(hours=4, minutes=15))
        self.assertEqual([a for a, t in tracks_of(orc).items() if t.open],
                         [], "no idea outlives its cap")


class TheTailStartTests(_Graded):
    """AN ARM'S FIRST TAIL BAR OPENS AT OR AFTER ITS LAST TICK. The tail
    started at the hour of the last tick and walked that whole bar: its
    open and its extremes, from before the tick, were tested against the
    levels the tick set (a lock binds from the next bar, §6.1)."""

    def _row_at(self, **kw):
        from bot_program.models import AssetBotTrade
        row = _row(self.cfg, **kw)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        return row

    def test_a_lock_set_mid_bar_is_not_gapped_at_that_bars_open(self):
        from bot_program.orcs import ghost
        row = self._row_at()
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        self.assertEqual(tracks_of(orc)["care"].state["soft_stop"], 100.2)
        _hand_closed(self, row, _at(45), price="102.4")
        _bars("BTCUSD", "1h", [(100.0, 103.0, 99.9, 102.6),
                               (102.6, 104.0, 102.5, 103.9),
                               (103.9, 105.0, 103.8, 104.9)], start=T0)
        ghost.step_bars(orc, now=T0 + timedelta(hours=4))
        tracks = tracks_of(orc)
        for arm in ("care", "orc_shadow", "playbook"):
            t = tracks[arm]
            self.assertTrue(t.open, f"{arm}: {t.exit_why}")
            self.assertEqual(t.last_bar_at, T0 + timedelta(hours=3), arm)

    def test_a_non_shared_exit_leaves_the_ghost_on_its_own_stop(self):
        from bot_program.orcs import ghost
        row = self._row_at()
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(_at(65), "100.2"), (_at(85), "103")])
        g = tracks_of(orc)["care"].state
        self.assertEqual((g["soft_stop"], g["soft_why"]), (101.0, "trail"))
        _closed_now(self, row, _at(90), exit_price=Decimal("103"))
        orc.refresh_from_db()
        # the 11:00 bar opened at 100 and rose to 103 by 11:25; then flat
        _bars("BTCUSD", "1h", [(100.0, 103.0, 99.9, 103.0)] + [103.0] * 3,
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=5, minutes=15))
        tracks = tracks_of(orc)
        for arm in ("care", "playbook"):
            self.assertTrue(tracks[arm].open, f"{arm}: {tracks[arm].exit_why}")
            self.assertEqual(tracks[arm].last_bar_at,
                             T0 + timedelta(hours=5), arm)
        self.assertFalse(tracks["orc_shadow"].open, "the real exit")


class TheCapMarkTests(_Graded):
    """THE CAP MARKS AT THE BAR THAT SPANS IT. The first pass past the cap
    marked every arm at the O arm's last tick, the price the row closed
    at days before: the ghost was valued at the Orc's own exit."""

    def test_the_cap_marks_at_the_close_of_the_bar_that_spans_it(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import ghost, pricing
        row = _row(self.cfg, target=None)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row, at=T0 + timedelta(minutes=7))
        drive(self, self.cfg, row, [(_at(30), "102.5")])
        _hand_closed(self, row, _at(40), price="102.4")
        cap = ghost.tail_cap(orc, row)
        self.assertEqual(cap.minute, 7)
        start = T0 + timedelta(hours=1)
        n = int((cap - start).total_seconds() // 3600)
        ohlc, px = [], 102.5
        for _ in range(n):
            o, px = px, px + 0.06
            ohlc.append((o, px + 0.01, o - 0.01, px))
        _bars("BTCUSD", "1h", ohlc, start=start)
        spans = start + timedelta(hours=n)               # 22:00, the cap 22:07
        ghost.step_bars(orc, now=spans + timedelta(minutes=1))
        ghost.step_bars(orc, now=cap + timedelta(minutes=3))
        arms = ("care", "playbook", "orc_shadow", "chandelier3", "staged")
        self.assertTrue(all(tracks_of(orc)[a].open for a in arms),
                        "the bar that spans the cap has not closed")
        close = round(px + 0.05, 5)
        _bars("BTCUSD", "1h", [(px, close + 0.01, px - 0.01, close)],
              start=spans)
        ghost.step_bars(orc, now=spans + timedelta(hours=1, minutes=15))
        tracks = tracks_of(orc)
        for arm in ("care", "playbook", "orc_shadow"):
            t = tracks[arm]
            self.assertEqual((t.open, t.tail_capped), (False, True), arm)
            self.assertAlmostEqual(float(t.exit_price), pricing.market_exit_px(
                pricing.Tick(at=None, p=close), "BUY", t.state["cf"]),
                places=6, msg=arm)
            self.assertGreater(t.exit_r, 4.0, arm)
        self.assertTrue(tracks["staged"].open, "no 4h bar: a 4h bar later")
        ghost.step_bars(orc, now=cap + timedelta(hours=4, minutes=15))
        for arm in ("chandelier3", "staged"):
            t = tracks_of(orc)[arm]
            self.assertEqual((t.open, t.tail_capped), (False, True), arm)
            self.assertAlmostEqual(float(t.exit_price), pricing.market_exit_px(
                pricing.Tick(at=None, p=close), "BUY", t.state["cf"]),
                places=6, msg=arm)


class TheRAvailTests(_Graded):
    """R_AVAIL, PINNED (§6.3): the root leg's best closing-side mark over
    [entry, the latest exit], on the tick and in the tail; every capture
    divides by it."""

    def test_r_avail_through_the_tick_the_tail_and_the_grade(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import ghost, pricing
        from bot_program.orcs.grading import grade
        from bot_program.orcs.models import OrcTrack
        row = _row(self.cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(_at(10), "101.0", "100.95", "101.05"),
                                    (_at(20), "103.0", "102.9", "103.1"),
                                    (_at(30), "101.5", "101.45", "101.55")])
        o = tracks_of(orc)["orc_shadow"].state
        cf = o["cf"]
        self.assertAlmostEqual(o["best_m_r"], (pricing.closing_mark(
            pricing.Tick(at=None, p=103.0, bid=102.9, ask=103.1), "BUY", cf)
            - 100) / 2)
        self.assertAlmostEqual(o["worst_m_r"], (100.95 - 100) / 2)
        _hand_closed(self, row, _at(40), price="101.5")
        _bars("BTCUSD", "1h", [(101.6, 104.0, 101.6, 103.8)],
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=15))
        best = ((104.0 - pricing.half_spread(104.0, cf)) - 100) / 2
        self.assertAlmostEqual(
            tracks_of(orc)["orc_shadow"].state["best_m_r"], best)
        OrcTrack.objects.filter(orc=orc, open=True).update(
            open=False, exit_r=0.8, exit_price=Decimal("101.5"),
            exit_at=_at(200))
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead")
        g = grade(orc, now=_at(210))
        self.assertAlmostEqual(g.r_avail, best)
        self.assertAlmostEqual(g.capture_orc, g.orc_r_gross / best)


class TheTailInputsTests(_Graded):
    """THE TAIL'S CARE INPUTS, PINNED: the event read at each bar, the
    engine's knobs, the context the tick last gave the arm."""

    def _hand_closed_flat(self, cfg=None):
        from bot_program.models import AssetBotTrade
        cfg = cfg or self.cfg
        row = _row(cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row, at=T0)
        drive(self, cfg, row, [(_at(30), "100.6")])
        _hand_closed(self, row, _at(40), price="100.6")
        return orc, row

    def test_the_event_window_locks_in_the_tail(self):
        from bot_program.orcs import ghost
        from market_data.models import EconomicEvent
        orc, row = self._hand_closed_flat()
        EconomicEvent.objects.create(
            title="US payrolls", country="US", impact="High",
            currency_affected="USD", source="forexfactory",
            datetime=T0 + timedelta(hours=2, minutes=30))
        _bars("BTCUSD", "1h", [(100.6, 101.3, 100.5, 101.2)],
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=15))
        st = tracks_of(orc)["care"].state
        self.assertEqual((st["soft_why"], st["soft_stop"]),
                         ("event lock", 100.2))

    def test_the_engine_knobs_move_the_stop_in_the_tail(self):
        from bot_program.orcs import ghost
        cfg = _config(self.user, name="knobs",
                      extras={"breakeven_at_r": 0.5,
                              "breakeven_buffer_r": 0.1})
        orc, row = self._hand_closed_flat(cfg)
        self.assertEqual(tracks_of(orc)["care"].state["venue_stop"], 98.0)
        _bars("BTCUSD", "1h", [(100.6, 101.3, 100.5, 101.2)],
              start=T0 + timedelta(hours=1))
        ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=15))
        st = tracks_of(orc)["care"].state
        self.assertAlmostEqual(st["venue_stop"], 100.2)
        self.assertTrue(st["breakeven_armed"])

    def test_the_tail_runs_plan_with_the_context_the_tick_gave(self):
        from unittest.mock import patch

        from bot_program import position_care
        from bot_program.orcs import ghost
        from bot_program.orcs.models import OrcTrack
        orc, row = self._hand_closed_flat()
        t = OrcTrack.objects.get(orc=orc, arm="care")
        ctx = {"posture_level": "crisis", "kind": "risk_on_long",
               "live": True, "manual": False, "scale": False}
        OrcTrack.objects.filter(pk=t.pk).update(state={**t.state, "ctx": ctx})
        _bars("BTCUSD", "1h", [(100.6, 100.8, 100.5, 100.7)],
              start=T0 + timedelta(hours=1))
        with patch.object(position_care, "plan",
                          wraps=position_care.plan) as spy:
            ghost.step_bars(orc, now=T0 + timedelta(hours=2, minutes=15))
        crisis = [c for c in spy.call_args_list
                  if c.kwargs.get("posture_level") == "crisis"]
        self.assertEqual(len(crisis), 1, "the care arm's bar")
        self.assertEqual((crisis[0].kwargs["kind"], crisis[0].kwargs["live"]),
                         ("risk_on_long", True))


class TheSharedEventPriceTests(_Graded):

    def test_a_target_close_between_ticks_is_the_same_event_at_its_price(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import ghost, pricing
        from bot_program.scorecard import HIT_TARGET
        row = _row(self.cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row, at=T0)
        drive(self, self.cfg, row, [(_at(10), "100.5")])
        _closed_now(self, row, _at(50), exit_price=Decimal("110"),
                    outcome=HIT_TARGET, reason="t | closed:TP")
        orc.refresh_from_db()
        ghost.step_bars(orc, now=_at(55))
        tracks = tracks_of(orc)
        cf = tracks["care"].state["cf"]
        px = pricing.target_exit_px(110, "BUY", cf)
        for arm in ("care", "orc_shadow"):
            t = tracks[arm]
            self.assertFalse(t.open, arm)
            self.assertAlmostEqual(float(t.exit_price), px, places=6, msg=arm)
        self.assertTrue(tracks["care"].exit_why.startswith(
            "the same event as the row"))
        self.assertEqual(tracks["care"].exit_r, tracks["orc_shadow"].exit_r)

    def test_a_close_after_the_bot_cap_is_its_own_cap(self):
        from bot_program.orcs import ghost
        row = _row(self.cfg)
        orc = born(self, row, at=T0)
        row.status, row.closed_at = "CLOSED", T0 + timedelta(hours=200)
        self.assertEqual(ghost.tail_cap(orc, row), row.closed_at)
