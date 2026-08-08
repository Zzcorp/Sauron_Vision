"""Tests for Phase-9.5 walk-forward backtest scorer.

Covers:
  - Evaluator registry: registers, looks up, rejects non-callables
  - walk_forward_window: split is contiguous, sums to lookback_days
  - backtest_with_params: returns expectancy/n/hit_rate/std from evaluator output
  - score_mutant_walkforward: a robustly-better mutant scores above parent
  - score_mutant_walkforward: an OVERFIT mutant (good train, bad test) scores
    BELOW parent because worst_delta is negative
  - score_mutant_walkforward: insufficient data triggers heavy penalty
  - score_mutant() dispatcher: picks walk_forward when evaluator registered
  - score_mutant() dispatcher: falls back to heuristic when no evaluator
  - propose_evolution sets score_method='walk_forward' and populates score_details

Run with:  python manage.py test tests.test_evolution_backtest
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _clear_registries():
    from signals.evolution import SCHEMA_REGISTRY
    from signals.evolution_backtest import EVALUATOR_REGISTRY
    SCHEMA_REGISTRY.clear()
    EVALUATOR_REGISTRY.clear()


def _seed_signals(rule_name: str, rs: list[float]):
    """Seed parent realized_r history so heuristic fallback has data."""
    from signals.models import Signal
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=f"WF_{rule_name}", defaults={"name": rule_name, "asset_class": "crypto"},
    )
    for i, r in enumerate(rs):
        Signal.objects.create(
            instrument=inst, signal_type="composite",
            direction="bullish", urgency="medium",
            title="t", description="t", rule_name=rule_name,
            score=0.7, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            risk_reward_ratio=2.0,
            is_active=False, outcome="hit_target" if r > 0 else "stopped_out",
            realized_r=r, expired_at=timezone.now() - timedelta(days=i),
        )


# ── Evaluator registry ─────────────────────────────────────────────────────

class EvaluatorRegistryTests(TestCase):
    def setUp(self):
        _clear_registries()

    def test_register_and_lookup(self):
        from signals.evolution_backtest import register_evaluator, has_evaluator
        register_evaluator("rule1", lambda p, s, e: [1.0, 2.0])
        self.assertTrue(has_evaluator("rule1"))
        self.assertFalse(has_evaluator("rule2"))

    def test_register_rejects_non_callable(self):
        from signals.evolution_backtest import register_evaluator
        with self.assertRaises(TypeError):
            register_evaluator("rule_bad", "not a function")

    def test_re_register_overrides(self):
        from signals.evolution_backtest import register_evaluator, EVALUATOR_REGISTRY
        register_evaluator("r", lambda p, s, e: [1.0])
        register_evaluator("r", lambda p, s, e: [9.9])
        # Latest registration wins.
        result = EVALUATOR_REGISTRY["r"]({}, None, None)
        self.assertEqual(result, [9.9])


# ── walk_forward_window ────────────────────────────────────────────────────

class WindowTests(TestCase):
    def test_split_is_contiguous_and_spans_lookback(self):
        from signals.evolution_backtest import walk_forward_window
        now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt_tz.utc)
        tr_s, tr_e, te_s, te_e = walk_forward_window(
            lookback_days=100, train_frac=0.7, now=now,
        )
        self.assertEqual(tr_e, te_s)  # contiguous
        self.assertEqual(te_e, now)
        self.assertEqual((te_e - tr_s).days, 100)
        self.assertEqual((tr_e - tr_s).days, 70)


# ── backtest_with_params ───────────────────────────────────────────────────

class BacktestWithParamsTests(TestCase):
    def setUp(self):
        _clear_registries()

    def test_returns_expectancy_n_hitrate(self):
        from signals.evolution_backtest import register_evaluator, backtest_with_params
        register_evaluator("rule_bt", lambda p, s, e: [2.0, 1.0, -1.0, 2.0, -1.0])
        result = backtest_with_params("rule_bt", {}, None, None)
        self.assertEqual(result["n"], 5)
        self.assertAlmostEqual(result["expectancy"], 0.6, places=4)
        self.assertEqual(result["hit_rate"], 0.6)  # 3 wins out of 5

    def test_no_evaluator_raises(self):
        from signals.evolution_backtest import backtest_with_params
        with self.assertRaises(LookupError):
            backtest_with_params("never_registered", {}, None, None)

    def test_evaluator_exception_returns_empty(self):
        from signals.evolution_backtest import register_evaluator, backtest_with_params
        register_evaluator("rule_throws", lambda p, s, e: 1 / 0)
        result = backtest_with_params("rule_throws", {}, None, None)
        self.assertEqual(result["n"], 0)


# ── score_mutant_walkforward ───────────────────────────────────────────────

class WalkForwardScoringTests(TestCase):
    def setUp(self):
        _clear_registries()

    def test_robust_mutant_scores_above_parent(self):
        """A mutant that beats the parent on BOTH train and test scores above parent."""
        from signals.evolution_backtest import (
            register_evaluator, score_mutant_walkforward,
        )
        # Parent: 1.0R consistently. Mutant: 2.0R consistently. Both windows.
        def evaluator(params, start, end):
            return [params.get("x", 1.0)] * 10
        register_evaluator("rule_robust", evaluator)
        result = score_mutant_walkforward(
            "rule_robust",
            mutant_params={"x": 2.0},
            parent_params={"x": 1.0},
        )
        self.assertEqual(result["method"], "walk_forward")
        self.assertTrue(result["sufficient_data"])
        self.assertEqual(result["train_delta"], 1.0)
        self.assertEqual(result["test_delta"], 1.0)
        self.assertEqual(result["worst_delta"], 1.0)
        # parent expectancy = 1.0; worst_delta = 1.0 → score = 2.0
        self.assertAlmostEqual(result["score"], 2.0, places=4)
        self.assertIn("ROBUST", result["notes"])

    def test_overfit_mutant_scored_below_parent(self):
        """Mutant that wins on train but loses on test must score below parent."""
        from signals.evolution_backtest import (
            register_evaluator, score_mutant_walkforward, walk_forward_window,
        )
        # Pre-compute split at the same `now` we'll pass.
        now = timezone.now()
        tr_s, tr_e, te_s, te_e = walk_forward_window(now=now)

        def evaluator(params, start, end):
            x = params.get("x", 1.0)
            in_train = start < tr_e <= end or end <= tr_e
            # Simpler: identify by checking if `end == tr_e` (train) vs `end == te_e` (test).
            if end == tr_e:
                # TRAIN window: mutant looks GREAT at high x.
                return [x * 2.0] * 10
            else:
                # TEST window: mutant is TERRIBLE at high x (overfit).
                return [-x * 2.0] * 10
        register_evaluator("rule_overfit", evaluator)
        result = score_mutant_walkforward(
            "rule_overfit",
            mutant_params={"x": 3.0},
            parent_params={"x": 1.0},
            now=now,
        )
        self.assertTrue(result["sufficient_data"])
        # parent train: 1×2=2.0; mutant train: 3×2=6.0 → train_delta = +4
        # parent test: -1×2=-2.0; mutant test: -3×2=-6.0 → test_delta = -4
        # worst = -4 (test)
        # parent_combined = (2.0 + -2.0) / 2 = 0.0
        # score = 0.0 + (-4.0) = -4.0  (mutant scores far below parent)
        self.assertEqual(result["worst_delta"], -4.0)
        self.assertLess(result["score"], 0)
        self.assertIn("OVERFIT", result["notes"])

    def test_insufficient_data_penalty(self):
        from signals.evolution_backtest import (
            register_evaluator, score_mutant_walkforward, INSUFFICIENT_DATA_PENALTY,
        )
        # Evaluator returns only 2 trades — below MIN_TRADES_PER_SPLIT=5.
        register_evaluator("rule_thin", lambda p, s, e: [1.0, 1.0])
        result = score_mutant_walkforward(
            "rule_thin",
            mutant_params={"x": 2.0},
            parent_params={"x": 1.0},
        )
        self.assertFalse(result["sufficient_data"])
        # score = parent_mean (1.0) + penalty (-1.0) = 0.0
        self.assertAlmostEqual(result["score"], 0.0, places=4)


# ── Dispatcher: score_mutant ───────────────────────────────────────────────

class ScoreMutantDispatchTests(TestCase):
    def setUp(self):
        _clear_registries()
        from signals.evolution import register_schema
        register_schema("disp_rule", {"x": {"type": "float", "min": 0.0, "max": 5.0, "default": 1.0}})

    def test_picks_heuristic_when_no_evaluator(self):
        from signals.evolution import score_mutant
        _seed_signals("disp_rule", [1.5] * 10)
        result = score_mutant("disp_rule", {"x": 2.0}, {"x": 1.0})
        self.assertEqual(result["method"], "heuristic")
        self.assertEqual(result["details"], {})

    def test_picks_walk_forward_when_evaluator_registered(self):
        from signals.evolution import score_mutant
        from signals.evolution_backtest import register_evaluator
        register_evaluator("disp_rule", lambda p, s, e: [p.get("x", 1.0)] * 8)
        result = score_mutant("disp_rule", {"x": 2.0}, {"x": 1.0})
        self.assertEqual(result["method"], "walk_forward")
        self.assertIn("train_mutant", result["details"])
        self.assertIn("notes", result["details"])


# ── propose_evolution end-to-end with walk-forward ─────────────────────────

class ProposeWithWalkForwardTests(TestCase):
    def setUp(self):
        _clear_registries()
        from signals.evolution import register_schema
        from signals.evolution_backtest import register_evaluator
        register_schema("e2e_rule", {
            "x": {"type": "float", "min": 0.0, "max": 5.0, "default": 1.0},
        })
        # Higher x → better mutant.
        register_evaluator("e2e_rule", lambda p, s, e: [p.get("x", 1.0)] * 10)
        _seed_signals("e2e_rule", [1.0] * 30)

    def test_score_method_recorded_as_walk_forward(self):
        from signals.evolution import propose_evolution
        from signals.models import RuleMutation
        propose_evolution("e2e_rule", n_mutants=8, top_k=3, seed=42)
        for m in RuleMutation.objects.filter(parent_rule="e2e_rule"):
            self.assertEqual(m.score_method, "walk_forward")
            self.assertIn("train_mutant", m.score_details)
            self.assertIn("notes", m.score_details)
