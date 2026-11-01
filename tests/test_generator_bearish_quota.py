"""THE BEARISH SHARE (2026-10-31, brain/strategy_generator.py): at least
one of every three slots of a generation cycle is held for a bearish
proposal.

What the file pins:
  * three valid bullish proposals: two persisted, the third recorded as
    rejected with the quota's reason (a trace, no setup);
  * two bullish and one bearish: all three persisted, the bearish first;
  * an invalid bearish is rejected for its own reason and holds no
    bullish slot back beyond the share;
  * the cap slices first — a fourth proposal is never read;
  * the prompt carries rule 8, the snapshot the direction balance and the
    bearish branches, every one a value the evaluator registry accepts;
  * with auto-research on, a bearish proposal waits for the operator while
    the bullish one is armed.

Run with:  python manage.py test tests.test_generator_bearish_quota
"""
from django.test import TestCase

from tests.test_frontier_imagination import _component, _stub_generator


def _p(slug, direction="bullish", valid=True):
    kind = "price_pattern" if valid else "no_such_evaluator"
    pattern = "above_ma" if direction == "bullish" else "below_ma"
    return {"name_slug": slug, "rationale_md": "cites direction_balance",
            "inspiration": "balance", "direction": direction,
            "asset_classes": ["stock"],
            "conditions": [{"kind": kind, "params": {"pattern": pattern},
                            "weight": 1.0}],
            "min_match_score": 0.6, "suggested_horizon_days": 5,
            "confidence": 0.6}


def _run(proposals, **kw):
    from brain.strategy_generator import generate_strategies_now
    with _stub_generator({"proposals": proposals}):
        return generate_strategies_now(**kw)


class TheQuotaTests(TestCase):

    def test_bearish_min(self):
        from brain.strategy_generator import bearish_min
        self.assertEqual([bearish_min(n) for n in (0, 1, 2, 3, 4, 6)],
                         [0, 1, 1, 1, 2, 2])

    def test_three_bullish_keep_two_and_trace_the_third(self):
        from brain.generator_models import GeneratedSetupProposal
        out = _run([_p("bull_a"), _p("bull_b"), _p("bull_c")])
        self.assertEqual(out["n_persisted"], 2)
        self.assertEqual(out["n_quota_dropped"], 1)
        self.assertEqual(out["n_validation_rejected"], 0)
        trace = GeneratedSetupProposal.objects.get(
            status=GeneratedSetupProposal.STATUS_REJECTED)
        self.assertEqual(trace.proposed_name, "bull_c")
        self.assertIsNone(trace.setup)
        self.assertEqual(trace.review_notes,
                         "bearish quota: 0 of 1 bearish proposals this cycle "
                         "— a slot is held for the short side")

    def test_two_bullish_and_one_bearish_are_all_kept(self):
        from brain.generator_models import GeneratedSetupProposal
        out = _run([_p("bull_a"), _p("bull_b"), _p("bear_a", "bearish")])
        self.assertEqual(out["n_persisted"], 3)
        self.assertEqual(out["n_quota_dropped"], 0)
        first = GeneratedSetupProposal.objects.get(pk=out["proposal_ids"][0])
        self.assertEqual(first.direction, "bearish")
        self.assertFalse(first.setup.is_active)
        self.assertEqual(first.rule_control.promotion_stage, "research")

    def test_an_invalid_bearish_is_rejected_for_its_own_reason(self):
        from brain.generator_models import GeneratedSetupProposal
        out = _run([_p("bull_a"), _p("bull_b"),
                    _p("bear_bad", "bearish", valid=False)])
        self.assertEqual(out["n_persisted"], 2)
        self.assertEqual(out["n_quota_dropped"], 0)
        self.assertEqual(out["n_validation_rejected"], 1)
        trace = GeneratedSetupProposal.objects.get(
            status=GeneratedSetupProposal.STATUS_REJECTED)
        self.assertEqual(trace.proposed_name, "bear_bad")
        self.assertIn("unknown evaluator", trace.review_notes)

    def test_the_cap_slices_first(self):
        from brain.generator_models import GeneratedSetupProposal
        out = _run([_p("bull_a"), _p("bull_b"), _p("bull_c"),
                    _p("bear_late", "bearish")])
        self.assertEqual(out["n_persisted"], 2)
        self.assertEqual(out["n_quota_dropped"], 1)
        self.assertFalse(GeneratedSetupProposal.objects.filter(
            proposed_name__contains="bear_late").exists())

    def test_two_bearish_leave_one_bullish_slot(self):
        out = _run([_p("bull_x"), _p("bear_x", "bearish"),
                    _p("bear_y", "bearish")])
        self.assertEqual(out["n_persisted"], 3)
        self.assertEqual(out["n_quota_dropped"], 0)


class TheSnapshotAndPromptTests(TestCase):

    def test_the_prompt_carries_the_share(self):
        from brain.strategy_generator import StrategyGeneratorAgent
        prompt = StrategyGeneratorAgent.get_system_prompt(
            StrategyGeneratorAgent.__new__(StrategyGeneratorAgent))
        self.assertIn("8. At least 1 of your proposals MUST have direction "
                      "`bearish`", prompt)
        self.assertIn("direction_balance", prompt)
        self.assertIn("bearish_branches", prompt)
        self.assertIn("fakeout_pattern:bull_trap", prompt)
        self.assertIn("cot_report:long_extreme", prompt)

    def test_the_snapshot_counts_the_balance(self):
        from brain.strategy_generator import _build_generation_snapshot
        from signals.models_opportunity import OpportunitySetup
        OpportunitySetup.objects.create(
            name="armed_bull", direction="bullish", asset_classes=["stock"],
            conditions=[{"kind": "price_pattern",
                         "params": {"pattern": "above_ma"}, "weight": 1.0}],
            min_match_score=0.6, is_active=True)
        snap = _build_generation_snapshot()
        bal = snap["direction_balance"]
        self.assertEqual(bal["active_setups"], {"bullish": 1, "bearish": 0})
        self.assertIn("proposals_last_8_weeks", bal)
        self.assertEqual(set(bal["graded_by_side"]), {"long", "short"})

    def test_every_bearish_branch_is_a_value_the_registry_accepts(self):
        from brain.strategy_generator import (BEARISH_BRANCHES,
                                              _build_generation_snapshot)
        from signals.opportunity_scanner import (EVALUATOR_REGISTRY,
                                                 param_choices)
        self.assertEqual(_build_generation_snapshot()["bearish_branches"],
                         BEARISH_BRANCHES)
        for kind, params in BEARISH_BRANCHES.items():
            self.assertIn(kind, EVALUATOR_REGISTRY, kind)
            choices = param_choices(kind)
            for key, value in params.items():
                self.assertIn(value, choices.get(key, ()), f"{kind}.{key}")


class TheArmingTests(TestCase):

    def test_auto_research_arms_the_bullish_and_leaves_the_bearish(self):
        from brain.generator_models import GeneratedSetupProposal
        _component("generator_auto_research", True)
        out = _run([_p("bull_a"), _p("bear_a", "bearish")])
        self.assertEqual(out["n_persisted"], 2)
        self.assertEqual(out["n_armed_research"], 1)
        bear = GeneratedSetupProposal.objects.get(direction="bearish")
        bull = GeneratedSetupProposal.objects.get(direction="bullish")
        self.assertEqual(bear.status, GeneratedSetupProposal.STATUS_PENDING)
        self.assertFalse(bear.setup.is_active)
        self.assertEqual(bull.status, GeneratedSetupProposal.STATUS_APPROVED)
        self.assertTrue(bull.setup.is_active)
