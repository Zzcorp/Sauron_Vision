"""The thesis check (brain/thesis_check.py, 2026-10-03): is the reason for
this trade still alive?

The operator, on an exit proposal for a long that printed -2.09R and came
back to flat: "Sauron should not be so procedural ... can the price come
back and make the position a winner, or at least break even? If yes,
adjust." The review's triggers are arithmetic on the R; a trader reads
the structure first. These tests pin, in the order the risk runs:

  the structure   a sweep in the trade's favour that reclaimed is alive
                  and carries a structure stop; a displaced break against,
                  not reclaimed, is dead; a quiet tape is unread
  the odds        the proving ground's trades that were this deep, and
                  what share came back — none without a family or a run
  the verdict     hold / adjust / exit / watch / unread, the sweep that
                  reclaimed outranking a bias against, never a displaced
                  break
  the review      facts["thesis"] on every measured position, the dead
                  thesis as a trigger, the alive one damping the
                  adverse-excursion trigger, the snapshot and the bell
  Aragorn         the structure stop on the row, applied by the care as a
                  tighten-only candidate, never on the manual lane, never
                  stale
  the record      the verdicts graded from what the position did
  the memory      simulate() keeps the worst excursion; ProvingTrade.mae

Run with:  python manage.py test tests.test_thesis_check
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from brain import thesis_check as TC


# ── fixtures ──────────────────────────────────────────────────────────────

def _df(rows):
    """rows: [(open, high, low, close)] oldest first, 4h bars."""
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="4h")
    return pd.DataFrame([{"open": o, "high": h, "low": lo, "close": c,
                          "volume": 1.0} for o, h, lo, c in rows], index=idx)


def _flat(n, c=100.0, half=1.0):
    return [(c, c + half, c - half, c)] * n


def _bars(rows):
    from signals.smc.pivots import classify_swings, get_swings
    df = _df(rows)
    return df, classify_swings(get_swings(df, 3, 3))


def _swept_and_reclaimed():
    """Flat at 100 with a swing low at 96; the last bar wicks through it
    to 95.5 and closes back at 100.2: the stops under 96 were taken."""
    rows = _flat(40)
    rows[20] = (97.0, 98.0, 96.0, 97.0)
    rows[-1] = (100.0, 100.5, 95.5, 100.2)
    return _bars(rows)


def _broken_down():
    """The same swing low at 96, then three bars that close under it and
    keep going: a displaced break of structure against a long."""
    rows = _flat(40)
    rows[20] = (97.0, 98.0, 96.0, 97.0)
    rows[-3] = (100.0, 100.2, 93.0, 93.5)
    rows[-2] = (93.5, 94.0, 92.0, 92.5)
    rows[-1] = (92.5, 93.0, 91.5, 92.0)
    return _bars(rows)


def _facts(**over):
    base = {"stale_quote": False, "symbol": "T", "side": "BUY", "book": "bot",
            "position_id": 1, "mark": 100.2, "entry": 100.0, "stop": 97.0,
            "initial_stop": 97.0, "risk_per_unit": 3.0, "unrealized_r": 0.07,
            "mae_r": -1.5, "mfe_r": 0.1, "rule_name": "", "asset_class": "forex"}
    base.update(over)
    return base


def _structure(**over):
    """A canned alive read: a sweep of the lows at 99.5, a stop under it."""
    base = {"ok": True, "atr": 1.0, "mark": 101.0, "bars": 60,
            "bias": None, "confidence": None, "zone": None, "opposing": None,
            "draw": None, "draw_room_atr": None,
            "sweep_with": {"bar": -1, "level": 99.8}, "sweep_against": None,
            "sweep_why": "with a fresh sweep of the lows at 99.8",
            "break_against": None,
            "structure_stop": 99.5, "structure_stop_why": "the sweep's low 100"}
    base.update(over)
    return base


NO_ODDS = {"ok": False, "n": 0, "thin": True, "why": "no family"}


# ═══ 1. the structure ═════════════════════════════════════════════════════

class TheStructureTests(SimpleTestCase):

    def test_a_sweep_in_favour_that_reclaimed_is_read_with_its_stop(self):
        from bot_program.smart_money import HUNT_DEPTH_ATR
        df, sw = _swept_and_reclaimed()
        st = TC.structure_read("T", "BUY", 100.2, bars=(df, sw))
        self.assertTrue(st["ok"])
        self.assertEqual(st["sweep_with"], {"bar": -1, "level": 96.0})
        self.assertIsNone(st["break_against"])
        self.assertAlmostEqual(st["structure_stop"],
                               95.5 - HUNT_DEPTH_ATR * st["atr"], places=6)
        self.assertIn("the sweep's low 95.5", st["structure_stop_why"])

    def test_a_displaced_break_against_not_reclaimed_is_read_as_one(self):
        df, sw = _broken_down()
        st = TC.structure_read("T", "BUY", 92.0, bars=(df, sw))
        brk = st["break_against"]
        self.assertEqual(brk["level"], 96.0)
        self.assertTrue(brk["displaced"])
        self.assertFalse(brk["reclaimed"])
        self.assertEqual(brk["bars_ago"], 2)
        self.assertIsNone(st["sweep_with"])

    def test_the_same_break_reclaimed_is_not_displaced_any_more(self):
        df, sw = _broken_down()
        st = TC.structure_read("T", "BUY", 97.5, bars=(df, sw))
        brk = st["break_against"]
        self.assertTrue(brk["reclaimed"])
        self.assertFalse(brk["displaced"])

    def test_a_quiet_tape_has_no_swings_and_reads_nothing(self):
        df, sw = _bars(_flat(40))
        st = TC.structure_read("T", "BUY", 100.0, bars=(df, sw))
        self.assertFalse(st["ok"])
        self.assertIn("too few bars", st["why"])

    def test_the_held_swing_is_the_stop_when_nothing_was_swept(self):
        from bot_program.smart_money import HUNT_DEPTH_ATR
        rows = _flat(40)
        rows[20] = (97.0, 98.0, 96.0, 97.0)
        df, sw = _bars(rows)
        st = TC.structure_read("T", "BUY", 100.0, bars=(df, sw))
        self.assertIsNone(st["sweep_with"])
        self.assertAlmostEqual(st["structure_stop"],
                               96.0 - HUNT_DEPTH_ATR * st["atr"], places=6)
        self.assertIn("held swing low 96", st["structure_stop_why"])


# ═══ 2. the verdict ═══════════════════════════════════════════════════════

class TheVerdictTests(SimpleTestCase):

    def _check(self, facts, structure, odds=NO_ODDS):
        return TC.thesis_check({"side": facts["side"]}, facts,
                               structure=structure, odds=odds)

    def test_the_operator_s_case_is_alive_not_dead(self):
        """-1.5R against it, back at the entry, the lows swept and
        reclaimed: hold — and the stop in place is already beyond the
        sweep, so nothing to adjust."""
        df, sw = _swept_and_reclaimed()
        st = TC.structure_read("T", "BUY", 100.2, bars=(df, sw))
        th = self._check(_facts(), st)
        self.assertEqual(th["verdict"], TC.HOLD)
        self.assertTrue(th["alive"])
        self.assertIn("those stops are gone", th["why"][0])
        self.assertIn("back at the entry after -1.50R", th["why"][1])
        self.assertIsNone(th["adjust"])
        self.assertTrue(th["words"].startswith("Thesis ALIVE — hold: "))

    def test_a_wider_stop_in_place_is_adjusted_to_under_the_sweep(self):
        """The venue held a wider stop than sent (eToro rewrites one on
        fill): the structure stop under the sweep tightens it."""
        df, sw = _swept_and_reclaimed()
        st = TC.structure_read("T", "BUY", 100.2, bars=(df, sw))
        th = self._check(_facts(stop=93.0), st)
        self.assertEqual(th["verdict"], TC.ADJUST)
        self.assertAlmostEqual(th["adjust"]["stop"], st["structure_stop"])
        self.assertIn("beyond the sweep's low 95.5", th["adjust"]["why"])
        self.assertLess(th["adjust"]["r"], 0)
        self.assertIn("Stop to", th["words"])

    def test_a_displaced_break_is_dead_whatever_the_r_says(self):
        df, sw = _broken_down()
        st = TC.structure_read("T", "BUY", 92.0, bars=(df, sw))
        th = self._check(_facts(mark=92.0, unrealized_r=-2.67, mae_r=-2.8), st)
        self.assertEqual(th["verdict"], TC.EXIT)
        self.assertFalse(th["alive"])
        self.assertIn("structure broke against it", th["why"][0])

    def test_a_confident_bias_against_with_no_sweep_is_dead(self):
        st = _structure(sweep_with=None, structure_stop=None,
                        bias="short", confidence=0.7)
        th = self._check(_facts(unrealized_r=-0.5), st)
        self.assertEqual(th["verdict"], TC.EXIT)
        self.assertIn("the bias is short at 0.70", th["why"][0])

    def test_the_sweep_that_reclaimed_outranks_the_bias_against(self):
        st = _structure(bias="short", confidence=0.7)
        th = self._check(_facts(), st)
        self.assertIn(th["verdict"], TC.ALIVE)

    def test_the_sweep_never_outranks_a_displaced_break(self):
        st = _structure(break_against={"level": 99.0, "close": 97.0,
                                       "bars_ago": 1, "displaced": True,
                                       "displacement_score": 0.8,
                                       "reclaimed": False})
        th = self._check(_facts(), st)
        self.assertEqual(th["verdict"], TC.EXIT)

    def test_a_bias_with_the_trade_is_alive(self):
        st = _structure(sweep_with=None, structure_stop=None,
                        bias="long", confidence=0.6)
        th = self._check(_facts(mae_r=-0.2, unrealized_r=0.3), st)
        self.assertEqual(th["verdict"], TC.HOLD)
        self.assertIn("the bias is long at 0.60", th["why"][0])

    def test_nothing_structural_is_watch_and_the_triggers_decide(self):
        st = _structure(sweep_with=None, structure_stop=None)
        th = self._check(_facts(mae_r=-0.2, unrealized_r=0.3), st)
        self.assertEqual(th["verdict"], TC.WATCH)
        self.assertIsNone(th["alive"])

    def test_the_odds_decide_when_the_structure_is_silent(self):
        st = _structure(sweep_with=None, structure_stop=None)
        poor = {"ok": True, "n": 30, "thin": False, "won_pct": 0.2,
                "avg_r": -0.6, "fell_back": False}
        th = self._check(_facts(unrealized_r=-0.9, mae_r=-0.95), st, poor)
        self.assertEqual(th["verdict"], TC.EXIT)
        self.assertIn("only 20% of 30 analogs -0.95R deep", th["why"][0])
        good = dict(poor, won_pct=0.6, avg_r=0.4)
        th = self._check(_facts(unrealized_r=-0.9, mae_r=-0.95), st, good)
        self.assertEqual(th["verdict"], TC.HOLD)
        self.assertIn("60% of 30 analogs", th["why"][0])

    def test_thin_odds_say_nothing_but_are_said(self):
        st = _structure(sweep_with=None, structure_stop=None)
        thin = {"ok": True, "n": 4, "thin": True, "won_pct": 0.0,
                "avg_r": -1.0, "fell_back": False}
        th = self._check(_facts(unrealized_r=-0.9, mae_r=-0.95), st, thin)
        self.assertEqual(th["verdict"], TC.WATCH)
        self.assertIn("Only 4 analog(s) this deep", th["words"])

    def test_no_mark_or_no_bars_is_unread_never_a_verdict(self):
        th = TC.thesis_check({}, _facts(stale_quote=True, mark=None))
        self.assertEqual(th["verdict"], TC.UNREAD)
        th = self._check(_facts(), {"ok": False, "why": "too few bars"})
        self.assertEqual(th["verdict"], TC.UNREAD)
        self.assertIn("too few bars", th["words"])

    def test_the_adjustment_needs_room_and_must_tighten(self):
        # a structure stop a hair under the mark: no room
        st = _structure(structure_stop=100.9, atr=1.0)
        th = self._check(_facts(mark=101.0, stop=97.0), st)
        self.assertEqual(th["verdict"], TC.HOLD)
        # a structure stop looser than the stop in place: nothing to adjust
        st = _structure(structure_stop=96.0)
        th = self._check(_facts(stop=97.0), st)
        self.assertEqual(th["verdict"], TC.HOLD)

    def test_the_deep_threshold_is_the_review_s(self):
        from brain.position_review import ADVERSE_EXCURSION_R
        self.assertEqual(TC.DEEP_MAE_R, ADVERSE_EXCURSION_R)


# ═══ 3. the odds ══════════════════════════════════════════════════════════

class TheOddsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        cls.v = ProvingVerdict.objects.create(
            run_id="odds1", family="macd_cross", direction="long",
            asset_class="crypto", timeframe="4h", policy="care",
            generated=False, filter="none", verdict="proven")
        t0 = timezone.now() - timedelta(days=200)
        rows = []
        for i in range(12):           # deep, came back
            rows.append(("trend", -0.9, 1.5, "target"))
        for i in range(8):            # deep, stopped
            rows.append(("trend", -1.0, -1.0, "stop"))
        for i in range(5):            # shallow: not this deep
            rows.append(("range", -0.3, 0.8, "target"))
        ProvingTrade.objects.bulk_create([
            ProvingTrade(verdict=cls.v, symbol="X",
                         entry_ts=t0 + timedelta(hours=4 * i),
                         exit_ts=t0 + timedelta(hours=4 * i + 20),
                         r=r, mfe=max(r, 0.0), mae=mae, regime=reg,
                         reason=reason, bars=5)
            for i, (reg, mae, r, reason) in enumerate(rows)])

    def test_the_trades_this_deep_and_their_share_that_came_back(self):
        od = TC.recovery_odds("macd_bullish_crossover", "crypto", -0.8)
        self.assertTrue(od["ok"])
        self.assertEqual(od["n"], 20)
        self.assertFalse(od["thin"])
        self.assertAlmostEqual(od["won_pct"], 0.6)
        self.assertAlmostEqual(od["target_pct"], 0.6)
        self.assertAlmostEqual(od["avg_r"], (12 * 1.5 - 8) / 20)
        self.assertEqual(od["run_id"], "odds1")
        self.assertEqual(od["family"], "macd_cross")

    def test_too_few_in_the_regime_falls_back_to_every_tape_and_says_so(self):
        od = TC.recovery_odds("macd_bullish_crossover", "crypto", -0.8,
                              regime="range")
        self.assertTrue(od["fell_back"])
        self.assertEqual(od["n"], 20)
        od = TC.recovery_odds("macd_bullish_crossover", "crypto", -0.8,
                              regime="trend")
        self.assertFalse(od["fell_back"])

    def test_deeper_than_any_analog_is_no_odds_said(self):
        od = TC.recovery_odds("macd_bullish_crossover", "crypto", -2.0)
        self.assertFalse(od["ok"])
        self.assertEqual(od["n"], 0)
        self.assertIn("-2.00R deep", od["why"])

    def test_no_family_and_no_run_are_no_odds_never_a_number(self):
        od = TC.recovery_odds("smc_composite", "crypto", -0.8)
        self.assertFalse(od["ok"])
        self.assertIn("no proving family", od["why"])
        self.assertIsNone(od["won_pct"])
        od = TC.recovery_odds("macd_bullish_crossover", "forex", -0.8)
        self.assertFalse(od["ok"])
        self.assertIn("no saved verdict", od["why"])


# ═══ 4. the review ════════════════════════════════════════════════════════

class TheReviewTests(SimpleTestCase):

    def _facts(self, **over):
        from tests.test_position_review import _facts as base
        return base(**over)

    def test_a_dead_thesis_is_a_trigger_whatever_the_r_says(self):
        from brain.position_review import (THESIS_DEAD_SEVERITY,
                                           evaluate_triggers)
        fired = evaluate_triggers(self._facts(
            thesis={"verdict": "exit", "why": ["structure broke against it"]}))
        dead = [t for t in fired if t["code"] == "thesis_dead"]
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["severity"], THESIS_DEAD_SEVERITY)
        self.assertIn("structure broke against it", dead[0]["text"])

    def test_an_alive_thesis_damps_the_adverse_excursion_and_answers_it(self):
        from brain.position_review import THESIS_ALIVE_DAMP, evaluate_triggers
        plain = [t for t in evaluate_triggers(self._facts(
            mae_r=-1.0, unrealized_r=-0.1))
            if t["code"] == "adverse_excursion"][0]
        alive = [t for t in evaluate_triggers(self._facts(
            mae_r=-1.0, unrealized_r=-0.1,
            thesis={"verdict": "hold", "why": ["the lows were swept"]}))
            if t["code"] == "adverse_excursion"][0]
        self.assertAlmostEqual(alive["severity"],
                               round(plain["severity"] * THESIS_ALIVE_DAMP, 3))
        self.assertIn("The structure says otherwise: the lows were swept",
                      alive["text"])
        self.assertNotIn("structure", plain["text"])

    def test_a_thesis_that_turns_is_a_new_question(self):
        from brain.position_review import facts_fingerprint
        a = facts_fingerprint(self._facts(thesis={"verdict": "hold"}), [])
        b = facts_fingerprint(self._facts(thesis={"verdict": "exit"}), [])
        self.assertNotEqual(a, b)

    def test_the_model_reads_the_structure_first(self):
        from brain.position_review_agent import (PositionReviewerAgent,
                                                 build_snapshot)
        snap = build_snapshot({"position": {"book": "bot", "position_id": 1,
                                            "symbol": "T", "side": "BUY"},
                               "facts": self._facts(thesis={"verdict": "hold"}),
                               "triggers": []})
        self.assertEqual(snap["thesis_check"], {"verdict": "hold"})
        prompt = PositionReviewerAgent.get_system_prompt(
            SimpleNamespace())
        self.assertIn("Read the STRUCTURE before the R arithmetic", prompt)
        self.assertIn("thesis_check", prompt)


class TheReviewOnTheBookTests(TestCase):

    def setUp(self):
        from tests.test_position_review import _quote, _trade
        self.trade = _trade("THS", entry="100", initial_stop="99", stop="99",
                            target="103", rule_name="")
        _quote("THS", 101.0)

    def test_every_measured_position_carries_its_thesis(self):
        from brain.position_review import bot_position, measure
        with patch("brain.thesis_check.structure_read",
                   return_value=_structure()):
            facts = measure(bot_position(self.trade))
        self.assertEqual(facts["thesis"]["verdict"], TC.ADJUST)
        self.assertEqual(facts["thesis"]["adjust"]["stop"], 99.5)

    def test_a_failed_check_is_unread_and_the_pass_goes_on(self):
        from brain.position_review import bot_position, measure
        with patch("brain.thesis_check.structure_read",
                   side_effect=RuntimeError("bars down")):
            facts = measure(bot_position(self.trade))
        self.assertEqual(facts["thesis"]["verdict"], TC.UNREAD)
        self.assertIn("structure unread", facts["thesis"]["why"][0])

    def test_the_pass_writes_the_verdict_on_the_bot_row(self):
        from brain.position_review import deterministic_pass
        with patch("brain.thesis_check.structure_read",
                   return_value=_structure()):
            deterministic_pass()
        self.trade.refresh_from_db()
        th = self.trade.metadata["thesis"]
        self.assertEqual(th["verdict"], TC.ADJUST)
        self.assertEqual(th["stop"], 99.5)
        self.assertIn("Thesis ALIVE — adjust", th["words"])
        self.assertTrue(th["at"])

    def test_the_bell_says_what_the_structure_said(self):
        from alerts.models import Notification
        from brain.position_review_agent import _notify
        from brain.position_review_models import PositionReview
        review = PositionReview.objects.create(
            book="bot", position_id=self.trade.id, symbol="THS", side="BUY",
            user=self.trade.config.user, verdict="exit",
            reasoning_md="The model's prose.", unrealized_r=-0.1,
            triggers=[{"code": "thesis_dead", "text": "The thesis is dead."}],
            facts={"thesis": {"verdict": "exit",
                              "words": "Thesis DEAD: structure broke."}})
        self.assertTrue(_notify(review))
        body = Notification.objects.filter(
            user=self.trade.config.user).latest("created_at").body
        self.assertIn("Thesis DEAD: structure broke.", body)
        self.assertLess(body.find("Thesis DEAD"), body.find("The model's prose"))


# ═══ 5. Aragorn ═══════════════════════════════════════════════════════════

def _row(stop=98.0, thesis=None, hours_ago=1):
    meta = {"initial_stop_loss": stop}
    if thesis:
        meta["thesis"] = thesis
    return SimpleNamespace(
        side="BUY", entry_price=Decimal("100"), stop_loss=Decimal(str(stop)),
        metadata=meta, asset_class="forex", paper=False,
        opened_at=timezone.now() - timedelta(hours=hours_ago))


def _adjust(stop=98.5, hours_ago=0.5, verdict="adjust"):
    return {"verdict": verdict, "stop": stop, "why": "beyond the sweep",
            "at": (timezone.now() - timedelta(hours=hours_ago)).isoformat()}


class TheCareTests(SimpleTestCase):

    def test_the_structure_stop_is_read_fresh_and_only_as_an_adjust(self):
        now = timezone.now()
        self.assertEqual(TC.care_stop({"thesis": _adjust()}, now),
                         (98.5, "structure"))
        self.assertIsNone(TC.care_stop({"thesis": _adjust(verdict="hold")}, now))
        self.assertIsNone(TC.care_stop(
            {"thesis": _adjust(hours_ago=TC.THESIS_STOP_TTL_HOURS + 1)}, now))
        self.assertIsNone(TC.care_stop({}, now))
        self.assertIsNone(TC.care_stop({"thesis": {"verdict": "adjust",
                                                   "stop": None}}, now))

    def test_the_care_takes_it_as_a_tighten_only_candidate(self):
        from bot_program.position_care import plan
        p = plan(_row(thesis=_adjust()), 99.0)
        self.assertEqual(p["action"], "hold")
        self.assertEqual(p["care"]["soft_stop"], 98.5)
        self.assertEqual(p["care"]["soft_why"], "structure")
        # the mark crossing it closes, like every soft stop
        p2 = plan(_row(thesis=_adjust()), 98.4)
        self.assertEqual((p2["action"], p2["reason"]), ("close", "SL"))
        self.assertIn("structure soft stop", p2["why"])

    def test_it_never_loosens_a_lock_already_in_place(self):
        from bot_program.position_care import plan
        p = plan(_row(thesis=_adjust()), 102.2)          # +2.1R: break-even
        self.assertEqual(p["care"]["soft_why"], "breakeven")
        self.assertGreater(p["care"]["soft_stop"], 98.5)

    def test_not_on_the_manual_lane_and_not_when_stale(self):
        from bot_program.position_care import plan
        p = plan(_row(thesis=_adjust()), 99.0, manual=True)
        self.assertNotIn("soft_stop", p["care"])
        p = plan(_row(thesis=_adjust(hours_ago=30)), 99.0)
        self.assertNotIn("soft_stop", p["care"])

    def test_the_crowd_read_does_not_move_it(self):
        from bot_program.position_care import CROWD_MOVABLE
        self.assertNotIn("structure", CROWD_MOVABLE)


# ═══ 6. the record and the command ════════════════════════════════════════

class TheRecordTests(TestCase):

    def setUp(self):
        from brain.position_review_models import PositionReview
        from tests.test_position_review import _config
        from bot_program.models import AssetBotTrade
        cfg = _config(name="ths_rec")
        self.closed = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="REC", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("99"), status="CLOSED", paper=True,
            realized_r=1.0)
        self.open = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="REC2", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("99"), status="OPEN", paper=True)

        def review(pid, verdict, r_at):
            return PositionReview.objects.create(
                book="bot", position_id=pid, symbol="REC", side="BUY",
                r_at_review=r_at, facts={"thesis": {"verdict": verdict}})
        review(self.closed.id, "hold", -0.5)       # held, closed +1.0: right
        review(self.closed.id, "exit", -0.5)       # said exit, it paid: wrong
        review(self.closed.id, "adjust", 0.9)      # +0.1R: inside the band
        review(self.open.id, "adjust", -0.3)       # still open: pending
        review(self.open.id, "watch", -0.3)        # no verdict to grade

    def test_the_verdicts_are_graded_from_what_the_position_did(self):
        rec = TC.track_record(days=30)
        self.assertEqual(rec["alive"]["n"], 3)
        self.assertEqual((rec["alive"]["right"], rec["alive"]["wrong"]), (1, 0))
        self.assertEqual(rec["alive"]["unresolved"], 1)
        self.assertEqual(rec["alive"]["pending"], 1)
        self.assertAlmostEqual(rec["alive"]["r_delta"], 1.5)
        self.assertEqual((rec["exit"]["right"], rec["exit"]["wrong"]), (0, 1))

    def test_the_command_prints_the_record(self):
        out = StringIO()
        call_command("thesis", "record", "--days", "30", stdout=out)
        text = out.getvalue()
        self.assertIn("alive  n=3", text)
        self.assertIn("right=1", text)
        self.assertIn("exit   n=1", text)


class TheCommandTests(TestCase):

    def test_no_open_position_is_said(self):
        out = StringIO()
        call_command("thesis", stdout=out)
        self.assertIn("no open position", out.getvalue())
        out = StringIO()
        call_command("thesis", "show", "GBPCHF", stdout=out)
        self.assertIn("no open position on GBPCHF", out.getvalue())

    def test_an_open_position_is_listed_with_its_verdict(self):
        from tests.test_position_review import _quote, _trade
        _trade("THC", entry="100", initial_stop="99", stop="99", target="103")
        _quote("THC", 101.0)
        out = StringIO()
        with patch("brain.thesis_check.structure_read",
                   return_value=_structure()):
            call_command("thesis", "show", "THC", stdout=out)
        text = out.getvalue()
        self.assertIn("THC", text)
        self.assertIn("ADJUST", text)
        self.assertIn("structure: bias None", text)
        self.assertIn("adjust: {'stop': 99.5", text)

    def test_it_is_registered_as_a_read_only_command(self):
        from core import ops_commands
        entry = ops_commands.get("thesis")
        self.assertTrue(entry["read_only"])
        self.assertEqual(entry["category"], "read")
        self.assertIn("thesis", ops_commands.runnable_names())


# ═══ 7. the memory keeps the worst excursion ══════════════════════════════

class TheMemoryTests(TestCase):

    def test_simulate_keeps_the_worst_excursion(self):
        from backtester.proving.simulate import simulate
        rows = _flat(60)
        for k, c in enumerate(range(99, 89, -1)):        # bars 32..41 fall
            rows[32 + k] = (float(c + 1), float(c + 1), float(c - 0.5),
                            float(c))
        df = _df(rows)
        fires = np.zeros(len(df), dtype=bool)
        fires[30] = True
        trades = simulate(df, fires, "long", asset_class="forex",
                          care=False)["trades"]
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertIn("stop", t["reason"])
        self.assertLessEqual(t["mae"], -1.0)
        self.assertLessEqual(t["mae"], 0.0)

    def test_a_saved_run_keeps_it_on_each_trade(self):
        from backtester.models_proving import ProvingTrade
        from tests.test_setup_memory import _seed
        _seed("MAEUSD")
        call_command("prove", "rules", "--class", "crypto", "--save",
                     stdout=StringIO())
        qs = ProvingTrade.objects.all()
        self.assertTrue(qs.exists())
        self.assertFalse(qs.filter(mae__gt=0).exists())
        self.assertTrue(qs.filter(mae__lt=-0.5).exists())
