"""Tests for Phase-9 strategy evolution.

Covers:
  - Schema validation (rejects bad shapes)
  - Schema registration is idempotent
  - generate_mutant respects bounds + step + type
  - generate_mutant requires a registered schema
  - score_mutant_heuristic returns 0 when no parent data
  - propose_evolution creates top-K RuleMutation rows
  - apply_evolution forks a NEW rule in RESEARCH stage with mutated params
  - apply does not modify the parent
  - reject_evolution marks rejected
  - propose_for_decaying_rules skips rules without a schema
  - Forked rule names are unique (_v1, _v2, ...)

Run with:  python manage.py test tests.test_evolution
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _seed_signals(rule_name: str, rs: list[float]):
    from signals.models import Signal
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=f"EVO_{rule_name}", defaults={"name": rule_name, "asset_class": "crypto"},
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


def _clear_registry():
    from signals.evolution import SCHEMA_REGISTRY
    SCHEMA_REGISTRY.clear()


# ── Schema registration ────────────────────────────────────────────────────

class SchemaRegistrationTests(TestCase):
    def setUp(self):
        _clear_registry()

    def test_register_and_lookup(self):
        from signals.evolution import register_schema, has_schema
        register_schema("rule_test", {
            "atr_mult": {"type": "float", "min": 1.0, "max": 5.0, "default": 2.0},
        })
        self.assertTrue(has_schema("rule_test"))
        self.assertFalse(has_schema("never_registered"))

    def test_invalid_schema_rejected(self):
        from signals.evolution import register_schema
        with self.assertRaises(ValueError):
            register_schema("bad", {"x": {"type": "float", "min": 5, "max": 1}})  # min > max
        with self.assertRaises(ValueError):
            register_schema("bad", {"x": {"min": 1, "max": 2}})  # missing type
        with self.assertRaises(ValueError):
            register_schema("bad", {"x": {"type": "string", "min": 1, "max": 2}})

    def test_re_register_overrides(self):
        from signals.evolution import register_schema, SCHEMA_REGISTRY
        register_schema("r", {"x": {"type": "int", "min": 1, "max": 5, "default": 3}})
        register_schema("r", {"y": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.5}})
        self.assertNotIn("x", SCHEMA_REGISTRY["r"])
        self.assertIn("y", SCHEMA_REGISTRY["r"])


# ── Mutation generation ────────────────────────────────────────────────────

class GenerateMutantTests(TestCase):
    def setUp(self):
        _clear_registry()
        from signals.evolution import register_schema
        register_schema("mut_rule", {
            "atr_mult": {"type": "float", "min": 1.0, "max": 5.0, "default": 2.0, "step": 0.1},
            "rsi_lower": {"type": "int", "min": 20, "max": 40, "default": 30},
            "lookback": {"type": "int", "min": 10, "max": 100, "default": 20},
        })

    def test_mutant_respects_bounds_for_all_params(self):
        from signals.evolution import generate_mutant
        rng = random.Random(42)
        for _ in range(50):
            m = generate_mutant("mut_rule", rng=rng)
            self.assertTrue(1.0 <= m["atr_mult"] <= 5.0)
            self.assertTrue(20 <= m["rsi_lower"] <= 40)
            self.assertTrue(10 <= m["lookback"] <= 100)
            self.assertIsInstance(m["rsi_lower"], int)
            self.assertIsInstance(m["lookback"], int)

    def test_mutant_requires_schema(self):
        from signals.evolution import generate_mutant
        with self.assertRaises(ValueError):
            generate_mutant("never_registered")

    def test_mutant_changes_subset_of_params(self):
        """Each mutant changes between 1 and MAX_PARAMS_TO_MUTATE params (not all of them every time)."""
        from signals.evolution import generate_mutant, current_params
        rng = random.Random(1)
        parent = current_params("mut_rule")
        # Multiple draws — at least one should leave some params unchanged.
        unchanged_count_observed = 0
        for _ in range(20):
            m = generate_mutant("mut_rule", rng=rng)
            unchanged = sum(1 for k in parent if m[k] == parent[k])
            if unchanged > 0:
                unchanged_count_observed += 1
        self.assertGreater(unchanged_count_observed, 0)


# ── Heuristic scorer ───────────────────────────────────────────────────────

class HeuristicScorerTests(TestCase):
    def setUp(self):
        _clear_registry()
        from signals.evolution import register_schema
        register_schema("score_rule", {
            "x": {"type": "float", "min": 0.0, "max": 10.0, "default": 5.0},
        })

    def test_score_with_no_parent_data_returns_zero(self):
        from signals.evolution import score_mutant_heuristic
        result = score_mutant_heuristic("score_rule", {"x": 7.0})
        self.assertEqual(result, 0.0)

    def test_score_centred_near_parent_expectancy_for_zero_delta(self):
        from signals.evolution import score_mutant_heuristic, current_params
        _seed_signals("score_rule", [2.0] * 30)  # parent expectancy ≈ 2.0
        # Mutant identical to parent → delta = 0 → score = parent + small noise
        rng = random.Random(0)
        scores = [score_mutant_heuristic("score_rule", current_params("score_rule"), rng=rng)
                  for _ in range(50)]
        avg = sum(scores) / len(scores)
        self.assertAlmostEqual(avg, 2.0, delta=0.5)


# ── propose_evolution + persistence ────────────────────────────────────────

class ProposeEvolutionTests(TestCase):
    def setUp(self):
        _clear_registry()
        from signals.evolution import register_schema
        register_schema("propose_rule", {
            "x": {"type": "float", "min": 0.0, "max": 10.0, "default": 5.0},
            "y": {"type": "int", "min": 1, "max": 20, "default": 10},
        })
        _seed_signals("propose_rule", [1.5] * 25 + [-1.0] * 5)

    def test_creates_top_k_rule_mutation_rows(self):
        from signals.evolution import propose_evolution
        from signals.models import RuleMutation
        saved = propose_evolution("propose_rule", n_mutants=15, top_k=3, seed=7)
        self.assertEqual(len(saved), 3)
        self.assertEqual(RuleMutation.objects.filter(parent_rule="propose_rule").count(), 3)
        for m in saved:
            self.assertEqual(m.state, "proposed")
            self.assertIn("x", m.mutated_params)
            self.assertIn("y", m.mutated_params)
            self.assertGreaterEqual(len(m.parameters_changed), 1)

    def test_propose_without_schema_raises(self):
        from signals.evolution import propose_evolution, EvolutionError
        with self.assertRaises(EvolutionError):
            propose_evolution("no_schema_rule")


# ── apply_evolution forks a new rule ───────────────────────────────────────

class ApplyEvolutionTests(TestCase):
    def setUp(self):
        _clear_registry()
        from signals.evolution import register_schema
        register_schema("apply_rule", {
            "x": {"type": "float", "min": 0.0, "max": 10.0, "default": 5.0},
        })
        _seed_signals("apply_rule", [1.5] * 30)
        self.user = User.objects.create_user(username="evolver", is_superuser=True)

    def test_apply_forks_new_rule_in_research_stage(self):
        from signals.evolution import propose_evolution, apply_evolution
        from signals.models import RuleControl
        proposals = propose_evolution("apply_rule", n_mutants=10, top_k=1, seed=3)
        new_ctrl = apply_evolution(proposals[0].id, self.user)
        self.assertEqual(new_ctrl.rule_name, "apply_rule_evolved_v1")
        self.assertEqual(new_ctrl.promotion_stage, "research")
        self.assertEqual(new_ctrl.parameters, proposals[0].mutated_params)

    def test_apply_does_not_modify_parent(self):
        from signals.evolution import propose_evolution, apply_evolution
        from signals.models import RuleControl
        # Create the parent's RuleControl with explicit current params.
        parent = RuleControl.objects.create(
            rule_name="apply_rule", parameters={"x": 4.5},
            promotion_stage="live_full",
        )
        proposals = propose_evolution("apply_rule", n_mutants=10, top_k=1, seed=11)
        apply_evolution(proposals[0].id, self.user)
        parent.refresh_from_db()
        self.assertEqual(parent.parameters, {"x": 4.5})
        self.assertEqual(parent.promotion_stage, "live_full")

    def test_apply_twice_creates_unique_forked_names(self):
        from signals.evolution import propose_evolution, apply_evolution
        proposals = propose_evolution("apply_rule", n_mutants=12, top_k=2, seed=99)
        c1 = apply_evolution(proposals[0].id, self.user)
        c2 = apply_evolution(proposals[1].id, self.user)
        self.assertEqual(c1.rule_name, "apply_rule_evolved_v1")
        self.assertEqual(c2.rule_name, "apply_rule_evolved_v2")

    def test_reject_marks_state(self):
        from signals.evolution import propose_evolution, reject_evolution
        from signals.models import RuleMutation
        proposals = propose_evolution("apply_rule", n_mutants=8, top_k=1, seed=5)
        reject_evolution(proposals[0].id, self.user)
        proposals[0].refresh_from_db()
        self.assertEqual(proposals[0].state, RuleMutation.STATE_REJECTED)


# ── Bulk proposer respects schemas + decay flag ────────────────────────────

class ProposeForDecayingRulesTests(TestCase):
    def setUp(self):
        _clear_registry()
        from signals.evolution import register_schema
        register_schema("decaying_rule", {
            "x": {"type": "float", "min": 0.0, "max": 10.0, "default": 5.0},
        })

        # Build a clear decay pattern for "decaying_rule":
        # baseline (40-80d ago) +2R, recent (last 14d) -1R.
        from signals.models import Signal
        from instruments.models import Instrument
        inst, _ = Instrument.objects.get_or_create(
            symbol="EVO_DECAYING", defaults={"name": "x", "asset_class": "crypto"},
        )
        for i in range(8):
            Signal.objects.create(
                instrument=inst, signal_type="composite",
                direction="bullish", urgency="medium",
                title="t", description="t", rule_name="decaying_rule",
                score=0.7, sub_scores={},
                price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
                suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
                risk_reward_ratio=2.0,
                is_active=False, outcome="hit_target", realized_r=2.0,
                expired_at=timezone.now() - timedelta(days=50 + i * 4),
            )
        for i in range(8):
            Signal.objects.create(
                instrument=inst, signal_type="composite",
                direction="bullish", urgency="medium",
                title="t", description="t", rule_name="decaying_rule",
                score=0.7, sub_scores={},
                price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
                suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
                risk_reward_ratio=2.0,
                is_active=False, outcome="stopped_out", realized_r=-1.0,
                expired_at=timezone.now() - timedelta(days=i + 1),
            )

        # And a stable rule WITHOUT a schema — proposer must skip it.
        _seed_signals("stable_no_schema", [1.0] * 20)

    def test_proposer_skips_rules_without_schema(self):
        from signals.evolution import propose_for_decaying_rules
        from signals.models import RuleMutation
        result = propose_for_decaying_rules()
        # decaying_rule has a schema and is decaying → proposals
        self.assertGreater(result["total_proposals"], 0)
        # stable_no_schema has no schema → no proposals for it
        self.assertEqual(
            RuleMutation.objects.filter(parent_rule="stable_no_schema").count(), 0,
        )

    def test_proposer_skips_non_decaying_rules_with_schema(self):
        """A rule that's not decaying gets no proposals even if it has a schema."""
        from signals.evolution import register_schema, propose_for_decaying_rules
        from signals.models import RuleMutation
        register_schema("stable_rule_with_schema", {
            "x": {"type": "float", "min": 0.0, "max": 10.0, "default": 5.0},
        })
        _seed_signals("stable_rule_with_schema", [1.5] * 20)  # not decaying
        result = propose_for_decaying_rules()
        self.assertEqual(
            RuleMutation.objects.filter(parent_rule="stable_rule_with_schema").count(), 0,
        )
