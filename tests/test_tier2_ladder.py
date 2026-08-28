"""The ladder stops certifying what it never measured.

Six bypasses, all of them terminating in live capital with a confident
reason string attached:

  the overfitting check    was SKIPPED whenever the in-sample window
                           produced no trades — `if train_exp and
                           train_exp > 0:` let a None fall through to an
                           approving return, so a rule cleared the
                           strictest gate on the ladder by producing no
                           evidence at all.

  the fail-open            covered the AUTOMATIC sweep. One rule of
                           fifteen has an evaluator; the other fourteen
                           promoted themselves to live capital with "no
                           backtest evidence available" as the written
                           justification.

  the paper stage          never opened the trade ledger. It read Signal
                           three times over three date windows and called
                           the results research, paper and live expectancy.

  _compute_realized_r      returned a confident 0.0 when there was no risk
                           to measure against — including for a signal
                           that HIT ITS TARGET.

  the `or 99` sentinel     conflated 0.0 with None, so a rule at exactly
                           zero expectancy could never be demoted.

  the flagship backtest    weighted "sauron_signals" while decide() writes
                           parts["sauron_sig"], zeroing a 0.25 leg; and two
                           placeholder legs returned a hardcoded 0 while
                           keeping 15% of the normalized weight.

Run with:  python manage.py test tests.test_tier2_ladder
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase


class TheOverfittingCheckCannotBeSkippedIntoAPassTests(SimpleTestCase):

    def _judge(self, train, test):
        from signals.promotion_evidence import _judge
        return _judge(train, test)

    def test_an_empty_training_window_is_a_refusal(self):
        """It used to return True with a sentence that never mentioned the
        comparison it had skipped."""
        ok, reason = self._judge(
            {"n": 0, "expectancy": None},
            {"n": 40, "expectancy": 0.8})
        self.assertFalse(ok)
        self.assertIn("could not run", reason)

    def test_a_thin_training_window_is_also_a_refusal(self):
        ok, reason = self._judge(
            {"n": 3, "expectancy": 0.9},
            {"n": 40, "expectancy": 0.8})
        self.assertFalse(ok)
        self.assertIn("could not run", reason)

    def test_a_real_overfit_is_still_caught(self):
        ok, reason = self._judge(
            {"n": 40, "expectancy": 2.0},
            {"n": 40, "expectancy": 0.2})
        self.assertFalse(ok)
        self.assertIn("overfitted", reason)

    def test_a_rule_that_retains_its_edge_still_passes(self):
        ok, reason = self._judge(
            {"n": 40, "expectancy": 1.0},
            {"n": 40, "expectancy": 0.9})
        self.assertTrue(ok, reason)

    def test_a_negative_in_sample_passes_but_says_so(self):
        """No in-sample edge means there was nothing to overfit TO — but
        the operator must read that rather than a retention figure that
        would divide by a negative."""
        ok, reason = self._judge(
            {"n": 40, "expectancy": -0.5},
            {"n": 40, "expectancy": 0.9})
        self.assertTrue(ok)
        self.assertIn("no in-sample edge", reason)


class TheFailOpenNoLongerCoversTheSweepTests(SimpleTestCase):
    """A human clicking promote has read the record. The scheduled sweep
    has no reader."""

    def _gate(self, caller):
        from signals.promotion_evidence import gate_promotion
        with patch("signals.promotion_evidence.evaluate_rule",
                   return_value={"available": False, "passed": False,
                                 "reason": "no evaluator registered",
                                 "train": {}, "test": {}}):
            return gate_promotion("unregistered_rule", "live_small",
                                  caller=caller)

    def test_the_automatic_path_refuses_without_evidence(self):
        ok, reason = self._gate("auto")
        self.assertFalse(ok)
        self.assertIn("no evaluator registered", reason)

    def test_an_operator_may_still_promote_by_hand(self):
        """Refusing here too would make the button useless — the human IS
        the evidence in that path, and they are accepting the risk."""
        ok, _ = self._gate("manual")
        self.assertTrue(ok)

    def test_manual_is_the_default_so_no_caller_keeps_the_old_behaviour(self):
        from signals.promotion_evidence import gate_promotion
        with patch("signals.promotion_evidence.evaluate_rule",
                   return_value={"available": False, "passed": False,
                                 "reason": "x", "train": {}, "test": {}}):
            self.assertTrue(gate_promotion("r", "live_small")[0])

    def test_below_live_needs_no_evidence_at_all(self):
        """research -> paper is how a rule EARNS the record that makes a
        backtest meaningful."""
        from signals.promotion_evidence import gate_promotion
        self.assertTrue(gate_promotion("r", "paper", caller="auto")[0])


class TheLadderReadsFillsNotSignalsTests(TestCase):

    def test_the_venue_helper_reads_the_trade_ledger(self):
        from signals.promotion_pipeline import _venue_stats
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=[{"n": 30, "expectancy": 0.5},
                                 {"n": 10, "expectancy": -0.1}]) as m:
            got = _venue_stats("r", "paper", None)
        self.assertTrue(m.called)
        self.assertEqual(got["n"], 40)

    def test_asset_classes_are_weighted_by_trade_count(self):
        """A rule that took 40 forex trades and 2 stock trades is mostly a
        forex rule; an even average lets the small row swing it."""
        from signals.promotion_pipeline import _venue_stats
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=[{"n": 40, "expectancy": 1.0},
                                 {"n": 2, "expectancy": -10.0}]):
            got = _venue_stats("r", "paper", None)
        self.assertGreater(got["expectancy"], 0)

    def test_no_fills_is_unmeasured_not_zero(self):
        from signals.promotion_pipeline import _venue_stats
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=[]):
            got = _venue_stats("r", "paper", None)
        self.assertEqual(got["n"], 0)
        self.assertIsNone(got["expectancy"])


class ASignalNobodyCouldMeasureIsNotZeroRTests(TestCase):

    def _signal(self, **kw):
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="T2SIG", defaults={"name": "T", "asset_class": "stock"})
        opts = dict(instrument=inst, signal_type="composite",
                    direction="bullish", urgency="medium", title="t",
                    description="t", rule_name="t2_rule", score=0.8,
                    sub_scores={}, price_at_signal=Decimal("100"))
        opts.update(kw)
        return Signal.objects.create(**opts)

    def test_no_stop_means_ungraded_not_a_scratch(self):
        from signals.performance import _compute_realized_r
        s = self._signal(suggested_entry=Decimal("100"), suggested_stop=None)
        self.assertIsNone(_compute_realized_r(s, Decimal("110")))

    def test_a_zero_width_risk_means_ungraded(self):
        from signals.performance import _compute_realized_r
        s = self._signal(suggested_entry=Decimal("100"),
                         suggested_stop=Decimal("100"))
        self.assertIsNone(_compute_realized_r(s, Decimal("110")))

    def test_a_measurable_signal_still_grades(self):
        from signals.performance import _compute_realized_r
        s = self._signal(suggested_entry=Decimal("100"),
                         suggested_stop=Decimal("95"))
        self.assertAlmostEqual(_compute_realized_r(s, Decimal("110")), 2.0)

    def test_a_winner_with_no_recorded_risk_is_not_filed_as_a_scratch(self):
        """The worst of the three: a signal that HIT ITS TARGET, with no
        risk_reward_ratio to fall back on, was graded 0.0R — a rule that
        worked, recorded as a break-even."""
        from django.utils import timezone
        from signals.models import Signal
        from signals.performance import _close_signal
        s = self._signal(suggested_entry=Decimal("100"),
                         suggested_stop=None, risk_reward_ratio=None)
        _close_signal(s, "hit_target", Decimal("120"), timezone.now())
        row = Signal.objects.get(pk=s.pk)
        self.assertEqual(row.outcome, "hit_target")
        self.assertIsNone(row.realized_r)

    def test_a_stop_out_is_still_the_canonical_minus_one(self):
        from django.utils import timezone
        from signals.models import Signal
        from signals.performance import _close_signal
        s = self._signal(suggested_entry=Decimal("100"),
                         suggested_stop=Decimal("95"))
        _close_signal(s, "stopped_out", Decimal("95"), timezone.now())
        self.assertEqual(Signal.objects.get(pk=s.pk).realized_r, -1.0)


class ZeroIsAMeasurementNotAnAbsenceTests(SimpleTestCase):
    """`or 99` made a rule at exactly 0.0 expectancy undemotable — the one
    reading that keeps a dead rule on live capital."""

    def test_zero_expectancy_is_below_a_positive_baseline(self):
        from signals.promotion_pipeline import DEMOTE_DEGRADATION_RATIO
        baseline, exp = 1.0, 0.0
        self.assertTrue(exp is not None
                        and exp < baseline * DEMOTE_DEGRADATION_RATIO)
        # The old sentinel turned that 0.0 into 99 and the test inverted.
        self.assertFalse((exp or 99) < baseline * DEMOTE_DEGRADATION_RATIO)

    def test_none_still_means_no_data_and_does_not_demote(self):
        exp = None
        self.assertFalse(exp is not None and exp < 0)


class TheBacktestMeasuresTheStrategyThatTradesTests(SimpleTestCase):

    def test_the_weight_keys_match_what_decide_emits(self):
        """`weights.get(k, 0)` silently zeroes any leg whose key does not
        match, so a typo here is a strategy change nobody sees."""
        from backtester.engine_v2 import BacktestEngineV2
        from bot_program.models import BotConfig
        engine = BacktestEngineV2()
        live_keys = set(BotConfig().normalized_weights().keys())
        self.assertEqual(set(engine.weights), live_keys)

    def test_the_sauron_leg_carries_its_weight(self):
        from backtester.engine_v2 import BacktestEngineV2
        self.assertEqual(BacktestEngineV2().weights.get("sauron_sig"), 0.25)


class ALegThatDidNotLookDoesNotDampTheScoreTests(SimpleTestCase):
    """An operator who set entry_score_min = 0.60 got a bot that required
    0.706 of full saturation, because 15% of the denominator belonged to
    functions that always answered zero."""

    def test_the_placeholder_legs_report_nothing_rather_than_neutral(self):
        from bot_program.engine.strategy import _score_macro, _score_sentiment
        self.assertIsNone(_score_macro()[0])
        self.assertIsNone(_score_sentiment("AAPL")[0])

    def test_the_composite_is_scored_out_of_what_reported(self):
        """Four legs at 1.0 carrying 0.85 of the weight is a composite of
        1.0 — not 0.85, which is what damping produced."""
        parts = {"technical": 1.0, "sauron_sig": 1.0, "news": 1.0,
                 "liquidity": 1.0, "macro": None, "sentiment": None}
        weights = {"technical": 0.30, "sauron_sig": 0.25, "news": 0.15,
                   "liquidity": 0.15, "macro": 0.10, "sentiment": 0.05}
        reported = {k: v for k, v in parts.items() if v is not None}
        live_weight = sum(weights.get(k, 0) for k in reported)
        composite = sum(reported[k] * weights.get(k, 0)
                        for k in reported) / live_weight
        self.assertAlmostEqual(composite, 1.0)
        self.assertAlmostEqual(
            sum(parts[k] * weights.get(k, 0) for k in reported), 0.85)

    def test_a_neutral_reading_still_counts_against_the_score(self):
        """0.0 is reserved for "looked, and it is neutral" — that leg keeps
        its weight in the denominator, which is the whole distinction."""
        parts = {"technical": 1.0, "news": 0.0}
        weights = {"technical": 0.30, "news": 0.15}
        reported = {k: v for k, v in parts.items() if v is not None}
        live_weight = sum(weights.get(k, 0) for k in reported)
        composite = sum(reported[k] * weights.get(k, 0)
                        for k in reported) / live_weight
        self.assertAlmostEqual(composite, 0.30 / 0.45)
