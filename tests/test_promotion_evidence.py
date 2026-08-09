"""Walk-forward evidence gating live promotion.

A good recent live/paper record is a small, recent sample; a rule can look
good for three weeks by luck. Before real money is risked, the backtester
(which drives the same decide() the live bot uses) must show out-of-sample
evidence.

Run with:  python manage.py test tests.test_promotion_evidence
"""
from unittest.mock import patch

from django.test import TestCase


def _control(rule_name="r_evidence", stage="paper"):
    from signals.models_control import RuleControl
    ctrl, _ = RuleControl.objects.get_or_create(rule_name=rule_name)
    ctrl.promotion_stage = stage
    ctrl.save()
    return ctrl


def _result(train_exp, test_exp, test_n=50):
    return {
        "train": {"n": 100, "expectancy": train_exp, "hit_rate": 0.6},
        "test": {"n": test_n, "expectancy": test_exp, "hit_rate": 0.6},
    }


class JudgementTests(TestCase):
    def test_positive_out_of_sample_passes(self):
        from signals.promotion_evidence import _judge
        r = _result(0.40, 0.35)
        passed, reason = _judge(r["train"], r["test"])
        self.assertTrue(passed, reason)

    def test_negative_out_of_sample_fails(self):
        from signals.promotion_evidence import _judge
        r = _result(0.40, -0.10)
        passed, reason = _judge(r["train"], r["test"])
        self.assertFalse(passed)
        self.assertIn("not positive", reason)

    def test_collapse_versus_training_reads_as_overfitting(self):
        from signals.promotion_evidence import _judge
        r = _result(1.00, 0.10)  # keeps only 10% of in-sample edge
        passed, reason = _judge(r["train"], r["test"])
        self.assertFalse(passed)
        self.assertIn("overfitted", reason)

    def test_thin_out_of_sample_sample_fails(self):
        from signals.promotion_evidence import _judge
        r = _result(0.5, 0.5, test_n=3)
        passed, reason = _judge(r["train"], r["test"])
        self.assertFalse(passed)
        self.assertIn("out-of-sample trades", reason)


class GateTests(TestCase):
    def test_only_live_stages_require_evidence(self):
        from signals.promotion_evidence import gate_promotion
        allowed, reason = gate_promotion("anything", "paper")
        self.assertTrue(allowed)
        self.assertIn("no evidence required", reason)

    def test_live_promotion_blocked_without_out_of_sample_edge(self):
        from signals.promotion_evidence import gate_promotion
        with patch("signals.promotion_evidence.evaluate_rule",
                    return_value={"available": True, "passed": False,
                                   "reason": "out-of-sample expectancy -0.2 "
                                             "is not positive",
                                   "train": None, "test": None}):
            allowed, reason = gate_promotion("r1", "live_small")
        self.assertFalse(allowed)
        self.assertIn("walk-forward gate", reason)

    def test_live_promotion_allowed_with_evidence(self):
        from signals.promotion_evidence import gate_promotion
        with patch("signals.promotion_evidence.evaluate_rule",
                    return_value={"available": True, "passed": True,
                                   "reason": "out-of-sample 0.35R over 50 trades",
                                   "train": None, "test": None}):
            allowed, _ = gate_promotion("r1", "live_small")
        self.assertTrue(allowed)

    def test_rules_without_an_evaluator_are_not_frozen_out(self):
        """Blocking un-backtestable rules would freeze the whole ladder;
        the absence of evidence is recorded instead."""
        from signals.promotion_evidence import gate_promotion
        allowed, reason = gate_promotion("rule_with_no_evaluator", "live_small")
        self.assertTrue(allowed)
        self.assertIn("no backtest evidence", reason)


class AutoPromotionTests(TestCase):
    def test_auto_promotion_respects_the_gate(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        ctrl = _control(stage="paper")
        with patch("signals.promotion_pipeline.is_due_for_demotion",
                    return_value=None), \
             patch("signals.promotion_pipeline.is_eligible_for_promotion",
                    return_value="live_small"), \
             patch("signals.promotion_evidence.evaluate_rule",
                    return_value={"available": True, "passed": False,
                                   "reason": "no out-of-sample edge",
                                   "train": None, "test": None}):
            out = auto_evaluate_all_rules()

        self.assertEqual(out["n_promoted"], 0)
        self.assertEqual(out["n_blocked"], 1)
        ctrl.refresh_from_db()
        self.assertEqual(ctrl.promotion_stage, "paper")

    def test_auto_promotion_proceeds_with_evidence(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        ctrl = _control(stage="paper")
        with patch("signals.promotion_pipeline.is_due_for_demotion",
                    return_value=None), \
             patch("signals.promotion_pipeline.is_eligible_for_promotion",
                    return_value="live_small"), \
             patch("signals.promotion_evidence.evaluate_rule",
                    return_value={"available": True, "passed": True,
                                   "reason": "0.4R out-of-sample",
                                   "train": None, "test": None}):
            out = auto_evaluate_all_rules()

        self.assertEqual(out["n_promoted"], 1)
        ctrl.refresh_from_db()
        self.assertEqual(ctrl.promotion_stage, "live_small")

    def test_promotion_to_paper_needs_no_backtest(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        ctrl = _control(stage="research")
        with patch("signals.promotion_pipeline.is_due_for_demotion",
                    return_value=None), \
             patch("signals.promotion_pipeline.is_eligible_for_promotion",
                    return_value="paper"):
            out = auto_evaluate_all_rules()
        self.assertEqual(out["n_promoted"], 1)
        ctrl.refresh_from_db()
        self.assertEqual(ctrl.promotion_stage, "paper")
