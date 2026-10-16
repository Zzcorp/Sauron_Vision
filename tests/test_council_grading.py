"""THE COUNCIL's grader (2026-10-08, ai_agents/council_grading.py).

Every voice is graded on what the market did next. A sent trade is
judged by its own realized R; anything else (not sent, not taken, an
unpriced close, a trade still open after 30 days, a ticket whose levels
moved) by walking its own bracket over the bars with the capital desk's
walk_bracket, minus the round trip in R. Each claim is graded once.

Run with:  python manage.py test tests.test_council_grading
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

SYMBOL = "CNCL"


def _inst(symbol=SYMBOL, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _bars(start, rows, symbol=SYMBOL, tf="1h"):
    """One bar per row (high, low, close), the first an hour after start."""
    from market_data.models import PriceData
    inst = _inst(symbol)
    for i, (h, lo, c) in enumerate(rows, 1):
        PriceData.objects.create(
            instrument=inst, timeframe=tf,
            timestamp=start + timedelta(hours=i), open=Decimal(str(c)),
            high=Decimal(str(h)), low=Decimal(str(lo)), close=Decimal(str(c)),
            volume=0, source="test")


TARGET_HIT = [(100.5, 99.5, 100.2), (104.5, 100.0, 104.0)]     # +2R
STOPPED = [(100.2, 97.5, 98.0)]                                  # -1R
WICK_THEN_TARGET = [(100.5, 97.8, 99.0), (104.5, 99.0, 104.0)]   # -1R


def _session(*, origin="bot", entry=100.0, stop=98.0, target=104.0,
             side="BUY", horizon=24.0, hours_ago=48, trade=None, cost=0.0,
             symbol=SYMBOL, config=None, user=None, rule="r",
             levels_match=None, regime="trending"):
    from ai_agents.council_models import CouncilSession
    s = CouncilSession.objects.create(
        origin=origin, status="done", symbol=symbol, asset_class="stock",
        side=side, rule_name=rule, entry=entry, stop=stop, target=target,
        horizon_hours=horizon, cost_fraction=cost, trade=trade,
        config=config, user=user, regime=regime, levels_match=levels_match)
    CouncilSession.objects.filter(id=s.id).update(
        created_at=timezone.now() - timedelta(hours=hours_ago))
    s.refresh_from_db()
    return s


def _claim(s, voice, kind, **kw):
    from ai_agents.council_models import CouncilClaim, CouncilVoice
    row, _ = CouncilVoice.objects.get_or_create(
        session=s, voice=voice, defaults={"status": "spoke", "wave": 1})
    return CouncilClaim.objects.create(
        session=s, voice=row, voice_key=voice, regime=s.regime,
        asset_class=s.asset_class, venue="live", origin=s.origin, kind=kind,
        **kw)


def _grade(s, now=None):
    from ai_agents.council_grading import grade_session
    from ai_agents.council_models import CouncilSession
    grade_session(CouncilSession.objects.get(id=s.id), now)
    return CouncilSession.objects.get(id=s.id)


class _Rows(TestCase):

    @classmethod
    def setUpTestData(cls):
        from tests.test_risk_limits_bind import _config
        cls.user = get_user_model().objects.create_user("cg_u", password="x")
        cls.cfg = _config(cls.user, asset_class="stock", mode="live")

    def _trade(self, *, status="CLOSED", r=None, days_open=0, paper=False,
               symbol=SYMBOL, side="BUY", rule="r", stop="98",
               target="104", minutes_after=None, session=None, cfg=None):
        from bot_program.models import AssetBotTrade
        t = AssetBotTrade.objects.create(
            config=cfg or self.cfg, asset_class="stock", symbol=symbol,
            side=side, qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal(stop), take_profit=Decimal(target),
            status=status, realized_r=r, paper=paper, rule_name=rule)
        opened = timezone.now() - timedelta(days=days_open)
        if minutes_after is not None:
            opened = session.created_at + timedelta(minutes=minutes_after)
        AssetBotTrade.objects.filter(id=t.id).update(opened_at=opened)
        t.refresh_from_db()
        return t


class TheTruthTests(_Rows):

    def test_a_closed_linked_trade_is_judged_by_its_realized_r(self):
        t = self._trade(r=1.5)
        s = _session(trade=t)
        c = _claim(s, "gambler", "work", p=0.8)
        s = _grade(s)
        self.assertEqual((s.truth, s.truth_r, s.y), ("realized", 1.5, 1))
        c.refresh_from_db()
        self.assertEqual(c.grade, "right")
        self.assertAlmostEqual(c.brier, 0.04)
        self.assertIsNotNone(s.graded_at)

    def test_an_unpriced_close_is_replayed_and_says_so(self):
        s = _session(trade=self._trade(r=None))
        _bars(s.created_at, TARGET_HIT)
        _claim(s, "gambler", "work", p=0.8)
        s = _grade(s)
        self.assertEqual((s.truth, s.truth_r), ("replay", 2.0))
        self.assertEqual(s.grade_notes, "replayed: realized R unpriced")

    def test_an_open_trade_waits_then_is_replayed_after_30_days(self):
        t = self._trade(status="OPEN", days_open=2)
        s = _session(trade=t)
        _bars(s.created_at, TARGET_HIT)
        c = _claim(s, "gambler", "work", p=0.8)
        s = _grade(s)
        c.refresh_from_db()
        self.assertEqual((c.grade, s.truth), ("pending", ""))
        self.assertIsNone(s.graded_at)
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(id=t.id).update(
            opened_at=timezone.now() - timedelta(days=31))
        s = _grade(s)
        self.assertEqual(s.truth, "replay")
        self.assertEqual(s.grade_notes, "replayed: still open after 30 days")

    def test_a_not_sent_candidate_is_replayed_once_its_horizon_has_passed(self):
        young = _session(hours_ago=10)
        _claim(young, "gambler", "work", p=0.8)
        young = _grade(young)
        self.assertIsNone(young.graded_at)
        waiting = _session(hours_ago=30, rule="w")
        _claim(waiting, "gambler", "work", p=0.8)
        self.assertIsNone(_grade(waiting).graded_at, "no bars yet, in grace")
        lapsed = _session(hours_ago=80, rule="l")
        c = _claim(lapsed, "gambler", "work", p=0.8)
        lapsed = _grade(lapsed)
        c.refresh_from_db()
        self.assertEqual((c.grade, c.grade_notes),
                         ("unresolvable", "not sent; no bars"))
        self.assertIsNotNone(lapsed.graded_at)
        due = _session(hours_ago=48, rule="d")
        _bars(due.created_at, STOPPED)
        _claim(due, "gambler", "work", p=0.8)
        due = _grade(due)
        self.assertEqual((due.truth, due.truth_r, due.y), ("replay", -1.0, 0))
        self.assertEqual(due.grade_notes, "replayed: not sent")
        self.assertEqual(due.replay_outcome, "stop")

    def test_a_ticket_whose_levels_moved_is_replayed(self):
        t = self._trade(r=3.0)
        s = _session(origin="ticket", trade=t, levels_match=False)
        _bars(s.created_at, STOPPED)
        _claim(s, "gambler", "work", p=0.8)
        s = _grade(s)
        self.assertEqual((s.truth, s.truth_r), ("replay", -1.0))
        self.assertEqual(s.grade_notes, "replayed: levels moved")

    def test_a_repeated_candidate_is_graded_once(self):
        first = _session(hours_ago=50, config=self.cfg)
        again = _session(hours_ago=48, config=self.cfg)
        c = _claim(again, "gambler", "work", p=0.8)
        again = _grade(again)
        c.refresh_from_db()
        self.assertEqual((c.grade, c.grade_notes),
                         ("ungraded", f"a repeat of session #{first.id}"))
        other_rule = _session(hours_ago=47, config=self.cfg, rule="x")
        _claim(other_rule, "gambler", "work", p=0.8)
        self.assertNotEqual(_grade(other_rule).grade_notes[:8], "a repeat")

    def test_the_time_window_links_the_right_hand_trade(self):
        from ai_agents.council_models import CouncilSession
        from bot_program.manual_trade import MANUAL_RULE
        from tests.test_council_ticket import _live_manual
        manual = _live_manual(self.user, "stock")
        s = _session(origin="ticket", user=self.user, hours_ago=5)
        self._trade(status="OPEN", rule=MANUAL_RULE, symbol="OTHR",
                    minutes_after=5, session=s, cfg=manual)
        self._trade(status="OPEN", rule=MANUAL_RULE, paper=True,
                    minutes_after=6, session=s, cfg=manual)
        self._trade(status="OPEN", rule=MANUAL_RULE, minutes_after=40,
                    session=s, cfg=manual)
        right = self._trade(status="OPEN", rule=MANUAL_RULE,
                            minutes_after=10, session=s, cfg=manual)
        _grade(s)
        s = CouncilSession.objects.get(id=s.id)
        self.assertEqual((s.trade_id, s.linked_by, s.levels_match),
                         (right.id, "time", True))

    def test_the_time_window_never_links_a_demo_world_row(self):
        """A hand trade placed on eToro's DEMO portfolio is stamped
        broker_env "paper" (paper=False, a live config): it never grades
        into the live record."""
        from ai_agents.council_models import CouncilSession
        from bot_program.manual_trade import MANUAL_RULE
        from tests.test_council_ticket import _live_manual
        manual = _live_manual(self.user, "stock")
        s = _session(origin="ticket", user=self.user, hours_ago=5)
        demo = self._trade(status="OPEN", rule=MANUAL_RULE, minutes_after=5,
                           session=s, cfg=manual)
        demo.metadata = {"broker_env": "paper"}
        demo.save(update_fields=["metadata"])
        _grade(s)
        self.assertIsNone(CouncilSession.objects.get(id=s.id).trade_id)
        real = self._trade(status="OPEN", rule=MANUAL_RULE, minutes_after=8,
                           session=s, cfg=manual)
        real.metadata = {"broker_env": "live"}
        real.save(update_fields=["metadata"])
        _grade(s)
        self.assertEqual(CouncilSession.objects.get(id=s.id).trade_id,
                         real.id)

    def test_the_bot_link_never_takes_a_demo_world_row(self):
        from ai_agents.council_models import CouncilSession
        s = _session()
        t = self._trade(r=1.0)
        t.metadata = {"debate": {"council_id": s.id}, "broker_env": "paper"}
        t.save(update_fields=["metadata"])
        _grade(s)
        self.assertIsNone(CouncilSession.objects.get(id=s.id).trade_id)

    def test_a_sim_fill_is_closed_ungraded_never_replayed_as_not_sent(self):
        """A bot order on a Saxo SIM / OANDA practice / Alpaca paper client
        (no .demo: the debate argued it) fills stamped broker_env "paper",
        the demo world (world_of). Its record is never linked, and never
        graded by replay as "not sent" into the live weights: it is closed
        with every claim ungraded."""
        from ai_agents.council_grading import REHEARSAL_NOTES
        from ai_agents.council_models import CouncilClaim
        s = _session()
        _bars(s.created_at, STOPPED)
        work = _claim(s, "executioner", "work", p=0.2)
        stance = _claim(s, "champion", "stance", stance="for")
        t = self._trade(status="OPEN")
        t.metadata = {"debate": {"council_id": s.id}, "broker": "saxo",
                      "broker_env": "paper"}
        t.save(update_fields=["metadata"])
        s = _grade(s)
        self.assertIsNone(s.trade_id)
        self.assertIsNotNone(s.graded_at)
        self.assertEqual(s.grade_notes, REHEARSAL_NOTES)
        self.assertEqual((s.truth, s.truth_r, s.replay_r), ("", None, None))
        for c in (work, stance):
            c.refresh_from_db()
            self.assertEqual((c.grade, c.y, c.brier), ("ungraded", None,
                                                       None))
        self.assertFalse(CouncilClaim.objects.filter(
            venue="live", y__isnull=False).exists())
        # a paper row carrying the id is no link either
        s2 = _session()
        _claim(s2, "gambler", "work", p=0.8)
        p = self._trade(r=1.0, paper=True)
        p.metadata = {"debate": {"council_id": s2.id}}
        p.save(update_fields=["metadata"])
        s2 = _grade(s2)
        self.assertIsNone(s2.trade_id)
        self.assertEqual(s2.grade_notes, REHEARSAL_NOTES)

    def test_a_not_sent_candidate_waits_its_first_hour(self):
        """The row an order writes lands with the debate: a bot record with
        no trade is not judged "not sent" in its first hour, even past its
        horizon with bars."""
        from market_data.models import PriceData
        from ai_agents.council_grading import NOT_SENT_AFTER
        self.assertEqual(NOT_SENT_AFTER, timedelta(hours=1))
        young = _session(hours_ago=0.5, horizon=0.25, symbol="NS1",
                         rule="ns1")
        twin = _session(hours_ago=0.5, horizon=0.25, symbol="NS1",
                        rule="ns2")
        PriceData.objects.create(
            instrument=_inst("NS1"), timeframe="1h",
            timestamp=young.created_at + timedelta(minutes=10),
            open=Decimal("100"), high=Decimal("104.5"), low=Decimal("99.5"),
            close=Decimal("104"), volume=0, source="test")
        c = _claim(young, "gambler", "work", p=0.8)
        young = _grade(young)
        c.refresh_from_db()
        self.assertEqual(c.grade, "pending")
        self.assertIsNone(young.graded_at)
        self.assertEqual(young.truth, "")
        # the same record without the first hour's wait would be graded
        c2 = _claim(twin, "gambler", "work", p=0.8)
        with patch("ai_agents.council_grading.NOT_SENT_AFTER", timedelta(0)):
            twin = _grade(twin)
        c2.refresh_from_db()
        self.assertEqual((twin.truth, c2.grade), ("replay", "right"))

    def test_the_bot_fallback_link_reads_the_rows_stamp(self):
        from ai_agents.council_models import CouncilSession
        s = _session()
        t = self._trade(r=1.0)
        t.metadata = {"debate": {"council_id": s.id}}
        t.save(update_fields=["metadata"])
        _grade(s)
        s = CouncilSession.objects.get(id=s.id)
        self.assertEqual((s.trade_id, s.linked_by, s.truth),
                         (t.id, "meta", "realized"))

    def test_the_round_trip_is_paid_in_r(self):
        from ai_agents.council_grading import cost_r
        self.assertAlmostEqual(cost_r(0.01, 100, 98), 0.5)
        s = _session(cost=0.01)
        _bars(s.created_at, TARGET_HIT)
        _claim(s, "gambler", "work", p=0.8)
        self.assertAlmostEqual(_grade(s).truth_r, 1.5)


class TheClaimTests(_Rows):

    def _realized(self, r, **kw):
        return _session(trade=self._trade(r=r), **kw)

    def test_work_is_a_brier_against_the_band(self):
        s = self._realized(1.0)
        c = _claim(s, "gambler", "work", p=0.8)
        _grade(s)
        c.refresh_from_db()
        self.assertEqual((c.grade, c.y), ("right", 1))
        self.assertAlmostEqual(c.brier, 0.04)
        s2 = self._realized(0.1)
        c2 = _claim(s2, "gambler", "work", p=0.8)
        _grade(s2)
        c2.refresh_from_db()
        self.assertEqual((c2.grade, c2.brier), ("unresolvable", None))

    def test_the_executioners_veto_saves_its_r(self):
        s = self._realized(-1.0)
        c = _claim(s, "executioner", "stance", stance="against",
                   payload={"verdict": "veto", "scale": 1.0})
        cut = _claim(s, "champion", "stance", stance="for",
                     payload={"verdict": "back"})
        _grade(s)
        c.refresh_from_db()
        cut.refresh_from_db()
        self.assertEqual((c.grade, c.value_r), ("right", 1.0))
        self.assertEqual(cut.grade, "wrong")
        s2 = self._realized(2.0)
        c2 = _claim(s2, "executioner", "stance", stance="against",
                    payload={"verdict": "cut", "scale": 0.5})
        _grade(s2)
        c2.refresh_from_db()
        self.assertEqual((c2.grade, c2.value_r), ("wrong", -1.0))

    def test_a_half_takes_no_side_and_no_attack_on_it_is_right(self):
        """0.5 is "cannot tell" (COUNCIL_LAW). Its Brier (0.25) still
        counts in the weight, but it is neither right nor wrong, so the
        Skeptic cannot farm it and the chair's statistics skip it."""
        for r in (2.0, -1.0):
            with self.subTest(r=r):
                s = self._realized(r)
                half = _claim(s, "theorist", "work", p=0.5)
                attack = _claim(s, "skeptic", "attack", p=1.0,
                                payload={"target": "theorist"})
                _grade(s)
                half.refresh_from_db()
                attack.refresh_from_db()
                self.assertEqual((half.grade, half.grade_notes),
                                 ("unresolvable", "0.5: no side taken"))
                self.assertEqual((half.y, half.brier), (int(r > 0), 0.25))
                self.assertEqual(attack.grade, "unresolvable")
                self.assertIsNone(attack.brier)

    def test_all_in_must_win_its_full_risk(self):
        for r, grade in ((1.2, "right"), (0.5, "unresolvable"),
                         (-0.3, "wrong")):
            with self.subTest(r=r):
                s = self._realized(r)
                c = _claim(s, "gambler", "boldness")
                _grade(s)
                c.refresh_from_db()
                self.assertEqual(c.grade, grade)

    def test_the_strikers_trigger(self):
        cases = (
            # fired at 99, the original won 2R, the wait won 5R: right
            ([(100.5, 99.0, 99.5), (104.2, 99.5, 104.0)], 99.0, "right", 3.0),
            # never touched 99, the trade won: wrong
            (TARGET_HIT, 99.0, "wrong", -2.0),
            # never touched 102, the trade lost: right
            (STOPPED, 102.0, "right", 1.0),
        )
        for i, (rows, level, grade, value) in enumerate(cases):
            with self.subTest(level=level, grade=grade):
                s = _session(rule=f"t{i}", symbol=f"TR{i}")
                _bars(s.created_at, rows, symbol=f"TR{i}")
                c = _claim(s, "striker", "trigger",
                           payload={"level": level, "within_hours": 24})
                _grade(s)
                c.refresh_from_db()
                self.assertEqual(c.grade, grade)
                self.assertAlmostEqual(c.value_r, value)

    def test_a_wait_or_an_entry_stopped_in_its_own_fill_bar_won_nothing(self):
        """walk_bracket's rule, "when one bar contains both, the stop
        wins", holds in the bar the waited entry fills in: a bar through
        the trigger AND the stop stops the waited trade there."""
        through = [(100.2, 97.5, 99.0), (104.5, 99.0, 104.0)]
        s = _session(symbol="FB1", rule="fb1")
        _bars(s.created_at, through, symbol="FB1")
        trigger = _claim(s, "striker", "trigger",
                         payload={"level": 99.0, "within_hours": 24})
        entry = _claim(s, "fixer", "fix", payload={
            "kind": "entry", "value": 99.0, "valid_hours": 12})
        s = _grade(s)
        trigger.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(s.replay_r, -1.0, "the trade as proposed: stopped")
        self.assertEqual((trigger.grade, trigger.value_r),
                         ("unresolvable", 0.0))
        self.assertEqual((entry.grade, entry.value_r), ("unresolvable", 0.0))
        # a SELL waited above, stopped in the same bar: the mirror
        sell = _session(symbol="FB2", rule="fb2", side="SELL", entry=100.0,
                        stop=102.0, target=96.0)
        _bars(sell.created_at, [(102.5, 99.8, 101.0), (101.0, 95.5, 96.0)],
              symbol="FB2")
        t2 = _claim(sell, "striker", "trigger",
                    payload={"level": 101.0, "within_hours": 24})
        _grade(sell)
        t2.refresh_from_db()
        self.assertEqual((t2.grade, t2.value_r), ("unresolvable", 0.0))

    def test_the_fixers_measured_fixes(self):
        s = _session(symbol="FX1", rule="f1")
        _bars(s.created_at, WICK_THEN_TARGET, symbol="FX1")
        wider = _claim(s, "fixer", "fix", payload={"kind": "stop",
                                                   "value": 97.0})
        never = _session(symbol="FX2", rule="f2")
        _bars(never.created_at, STOPPED, symbol="FX2")
        entry = _claim(never, "fixer", "fix", payload={
            "kind": "entry", "value": 101.0, "valid_hours": 12})
        gone = _session(symbol="FX3", rule="f3")
        _bars(gone.created_at, STOPPED + [(99, 98.5, 98.8)], symbol="FX3")
        timing = _claim(gone, "fixer", "fix", payload={
            "kind": "timing", "valid_hours": 2})
        sized = self._realized(-1.0, rule="f4")
        size = _claim(sized, "fixer", "fix", payload={"kind": "size",
                                                      "value": 0.5})
        for sess in (s, never, gone, sized):
            _grade(sess)
        for c in (wider, entry, timing, size):
            c.refresh_from_db()
        self.assertEqual(wider.grade, "right", "survives the wick")
        self.assertAlmostEqual(wider.value_r, 4.0 / 3.0 + 1.0, places=5)
        self.assertEqual((entry.grade, entry.value_r), ("right", 1.0))
        self.assertEqual((timing.grade, timing.grade_notes),
                         ("ungraded", "the levels were gone at the named hour"))
        self.assertEqual((size.grade, size.value_r), ("right", 0.5))

    def test_the_awakeneds_level(self):
        s = _session(symbol="AW1", rule="a1")
        _bars(s.created_at, TARGET_HIT, symbol="AW1")
        touched = _claim(s, "awakened", "touch",
                         payload={"level": 103.0, "within_hours": 24})
        missed = _claim(s, "awakened", "touch",
                        payload={"level": 106.0, "within_hours": 24})
        blind = _session(symbol="AW2", rule="a2", hours_ago=100)
        no_bars = _claim(blind, "awakened", "touch",
                         payload={"level": 103.0, "within_hours": 24})
        _grade(s)
        _grade(blind)
        for c in (touched, missed, no_bars):
            c.refresh_from_db()
        self.assertEqual(touched.grade, "right")
        self.assertEqual(missed.grade, "wrong")
        self.assertEqual((no_bars.grade, no_bars.grade_notes),
                         ("unresolvable", "no bars"))

    def test_the_skeptic_is_right_when_his_target_was_wrong(self):
        s = self._realized(-1.0)
        _claim(s, "champion", "stance", stance="for")
        _claim(s, "champion", "work", p=0.9)
        attack = _claim(s, "skeptic", "attack", p=0.7,
                        payload={"target": "champion", "flaw": "noise"})
        _grade(s)
        attack.refresh_from_db()
        self.assertEqual((attack.grade, attack.y), ("right", 1))
        self.assertAlmostEqual(attack.brier, 0.09)
        s2 = self._realized(2.0)
        _claim(s2, "champion", "work", p=0.9)
        a2 = _claim(s2, "skeptic", "attack", p=0.7,
                    payload={"target": "champion"})
        _grade(s2)
        a2.refresh_from_db()
        self.assertEqual((a2.grade, a2.y), ("wrong", 0))
        self.assertAlmostEqual(a2.brier, 0.49)
        s3 = self._realized(2.0)
        a3 = _claim(s3, "skeptic", "attack", p=0.7,
                    payload={"target": "gambler"})
        _grade(s3)
        a3.refresh_from_db()
        self.assertEqual(a3.grade, "unresolvable")

    def test_the_opportunists_call_copies_the_calibration_grade(self):
        from ai_agents.models import AgentPrediction
        s = self._realized(1.0)
        claims = []
        for i, (correct, actual) in enumerate(((True, "up"), (False, "down"),
                                               (None, "ungradeable_no_bar"))):
            pred = AgentPrediction.objects.create(
                agent="council_opportunist", prediction_type="direction",
                instrument_symbol=f"S{i}", predicted_value="up",
                actual_value=actual, was_correct=correct, confidence=0.6)
            claims.append(_claim(s, "opportunist", "direction", p=0.6,
                                 prediction=pred))
        _grade(s)
        for c in claims:
            c.refresh_from_db()
        self.assertEqual([c.grade for c in claims],
                         ["right", "wrong", "unresolvable"])

    def test_the_theorists_theory_copies_the_market(self):
        from brain.knowledge_models import Hypothesis
        s = self._realized(1.0)
        out = []
        for outcome in ("confirmed", "refuted", "pending"):
            h = Hypothesis.objects.create(claim_text="t",
                                          source_agent="council_theorist",
                                          outcome=outcome)
            out.append(_claim(s, "theorist", "theory", p=0.6, hypothesis=h))
        refused = _claim(s, "theorist", "theory", grade="refused",
                         grade_notes="no price to measure from")
        _grade(s)
        for c in out + [refused]:
            c.refresh_from_db()
        self.assertEqual([c.grade for c in out],
                         ["right", "wrong", "pending"])
        self.assertEqual(refused.grade, "refused")

    def test_the_emperors_battles_and_the_chairs_statistics(self):
        from ai_agents.council_grading import record_matrix
        from ai_agents.council_models import CouncilVoice
        cases = ((1.0, 1.0, "right", 0.0), (0.5, -1.0, "right", 0.5),
                 (1.0, -1.0, "wrong", 0.0), (0.5, 1.0, "wrong", -0.5))
        for commit, r, grade, value in cases:
            with self.subTest(commit=commit, r=r):
                s = self._realized(r)
                c = _claim(s, "emperor", "battle",
                           payload={"commit": commit})
                _grade(s)
                c.refresh_from_db()
                self.assertEqual(c.grade, grade)
                self.assertAlmostEqual(c.value_r, value)
        s = self._realized(-1.0)
        _claim(s, "executioner", "stance", stance="for",
               payload={"verdict": "pass"})
        _claim(s, "champion", "stance", stance="against")
        _claim(s, "emperor", "battle", payload={"commit": 0.0})
        CouncilVoice.objects.filter(session=s, voice="emperor").update(
            answer={"verdict": "refuse", "overruled": [
                {"voice": "executioner", "why": "w"}],
                "followed": ["champion"]})
        _grade(s)
        chair = record_matrix()["chair"]
        self.assertEqual((chair["over_wrong"], chair["over_n"]), (1, 1))
        self.assertEqual((chair["follow_right"], chair["follow_n"]), (1, 1))


class TheNightlyPassTests(_Rows):

    def test_the_pass_is_idempotent_and_settles_stuck_sittings(self):
        from ai_agents.council_grading import grade_due
        from ai_agents.council_models import CouncilSession, CouncilVoice
        s = _session(trade=self._trade(r=1.0))
        _claim(s, "gambler", "work", p=0.8)
        queued = _session(hours_ago=2)
        sitting = _session(hours_ago=2, rule="q")
        CouncilSession.objects.filter(id=queued.id).update(status="queued")
        CouncilSession.objects.filter(id=sitting.id).update(status="sitting")
        v = CouncilVoice.objects.create(session=sitting, voice="emperor",
                                        wave=3, status="asked")
        CouncilVoice.objects.filter(id=v.id).update(
            created_at=timezone.now() - timedelta(hours=2))
        first = grade_due()
        self.assertEqual(first["stuck"], 2)
        self.assertGreaterEqual(first["claims"], 1)
        self.assertEqual(CouncilSession.objects.get(id=queued.id).why,
                         "never sat: the queue did not take it")
        self.assertEqual(CouncilSession.objects.get(id=sitting.id).why,
                         "the sitting did not finish")
        self.assertEqual(CouncilVoice.objects.get(id=v.id).why, "timeout")
        second = grade_due()
        self.assertEqual(second["claims"], 0)

    def test_the_calibration_task_grades_the_council_and_survives_it(self):
        from ai_agents.tasks import resolve_pending_calibrations
        from tests.test_council_sitting import switch
        switch("platform_master")
        switch("pipeline_calibration")
        _claim(_session(trade=self._trade(r=1.0)), "gambler", "work", p=0.8)
        out = resolve_pending_calibrations()
        self.assertEqual(out["status"], "ok")
        self.assertIn("resolved", out)
        self.assertEqual(out["council"]["graded"], 1)
        with patch("ai_agents.council_grading.grade_due",
                   side_effect=RuntimeError("boom")):
            out = resolve_pending_calibrations()
        self.assertEqual(out["status"], "ok")
        self.assertIn("resolved", out)
        self.assertEqual(out["council"], {"error": "RuntimeError"})

    def test_the_debates_history_is_backfilled_once(self):
        from ai_agents.council_models import CouncilSession
        from ai_agents.management.commands.council import backfill_debates
        t = self._trade(r=-1.0)
        t.metadata = {"debate": {
            "ran": True, "executioner": {"verdict": "veto",
                                         "conviction": 0.8},
            "champion": None, "why": "champion unavailable (timeout)"},
            "initial_stop_loss": 97.5}
        t.save(update_fields=["metadata"])
        self._trade(r=1.0)                       # never debated
        demo = self._trade(r=1.0)
        demo.metadata = {"debate": {"ran": True}, "broker_env": "paper"}
        demo.save(update_fields=["metadata"])
        import bot_program.persona_mix as pm
        with patch("bot_program.persona_mix.regime_series",
                   wraps=pm.regime_series) as series:
            self.assertEqual(backfill_debates(), 1)
        series.assert_called_once()
        self.assertEqual(backfill_debates(), 0, "idempotent")
        s = CouncilSession.objects.get()
        self.assertEqual((s.trade_id, s.linked_by, s.status, s.stop),
                         (t.id, "meta", "record", 97.5))
        self.assertEqual(s.created_at, t.opened_at)
        ex = s.voices.get(voice="executioner")
        self.assertEqual((ex.status, ex.wave), ("copied", 0))
        self.assertEqual(s.voices.get(voice="champion").status, "silent")
        s = _grade(s)
        self.assertEqual(s.truth, "realized")
        self.assertEqual(s.claims.get(voice_key="executioner",
                                      kind="stance").grade, "right")


class TheMigrationTests(SimpleTestCase):
    """THE COUNCIL's record is ONE line of ai_agents migrations, on main's
    0012_agenttask_cache_tokens: two leaves would stop every migrate and
    every test run."""

    def test_the_council_follows_the_newest_ai_agents_migration(self):
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(None, ignore_no_migrations=True)
        self.assertEqual(loader.detect_conflicts(), {})
        leaves = [n for n in loader.graph.leaf_nodes() if n[0] == "ai_agents"]
        # one leaf, whatever its name: a later ai_agents migration on main
        # (0014_*) follows the council and leaves the graph healthy
        self.assertEqual(len(leaves), 1, leaves)
        parents = {p.key for p in loader.graph.node_map[
            ("ai_agents", "0013_council")].parents if p.key[0] == "ai_agents"}
        self.assertEqual(parents, {("ai_agents",
                                    "0012_agenttask_cache_tokens")})
