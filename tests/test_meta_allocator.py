"""Tests for Phase-7 meta-allocator (non-falling design).

Covers:
  - Three method outputs (uniform, inverse_vol, expectancy) sum to 1
  - Sample-tier selection — sparse data → tier3 (pure uniform)
  - Per-rule sample floor pulls noisy rules to uniform weight
  - Hard caps clip extremes [1%, 30%] then renormalise
  - Smoothing applies only 30% of the delta per rebalance
  - Effective rule_size_multiplier = admin × allocator
  - propose_allocation creates a shadow row regardless of data quantity
  - Shadow mode blocks apply
  - apply + rollback round-trip restores allocator_weight
  - Running-only filter — a pause still in force is untouched by apply.
    NOT "paused/reduced": a `reduced` rule is still trading and IS budgeted,
    and so is one whose pause has elapsed. See tests/test_engine_control_surfaces.py.

Run with:  python manage.py test tests.test_meta_allocator
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _seed_components():
    from core.platform_control import seed_components
    seed_components()


def _set_live(enabled: bool):
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key="meta_allocator_mode_live",
        defaults={"name": "Meta-Allocator Live Mode", "category": "system"},
    )
    c.is_enabled = enabled
    c.save()


def _instrument(symbol):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "crypto"},
    )
    return inst


def _seed_signals(rule_name: str, rs: list[float], symbol_prefix="ALLOC"):
    """Seed N closed signals with the given realized_r values for one rule."""
    from signals.models import Signal
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=f"{symbol_prefix}_{rule_name}",
        defaults={"name": rule_name, "asset_class": "crypto"},
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


# ── Method outputs ─────────────────────────────────────────────────────────

class MethodOutputsTests(TestCase):
    def test_uniform_sums_to_one(self):
        from signals.meta_allocator import _uniform_weights
        out = _uniform_weights(["a", "b", "c", "d"])
        self.assertAlmostEqual(sum(out.values()), 1.0)
        self.assertEqual(set(out.values()), {0.25})

    def test_inverse_vol_penalises_high_vol_rule(self):
        from signals.meta_allocator import _inverse_vol_weights
        stats = {
            "calm":   {"n": 30, "mean": 0.5, "std": 0.5, "rs": []},
            "noisy":  {"n": 30, "mean": 0.5, "std": 5.0, "rs": []},
        }
        out = _inverse_vol_weights(stats)
        self.assertGreater(out["calm"], out["noisy"])
        self.assertAlmostEqual(sum(out.values()), 1.0)

    def test_expectancy_excludes_negative_mean(self):
        from signals.meta_allocator import _expectancy_weights
        stats = {
            "winner": {"n": 30, "mean": 1.5, "std": 1.0, "rs": []},
            "loser":  {"n": 30, "mean": -0.5, "std": 1.0, "rs": []},
        }
        out = _expectancy_weights(stats)
        self.assertEqual(out["loser"], 0.0)
        self.assertAlmostEqual(out["winner"], 1.0)

    def test_expectancy_falls_back_to_uniform_when_all_negative(self):
        from signals.meta_allocator import _expectancy_weights
        stats = {
            "a": {"n": 30, "mean": -1.0, "std": 1.0, "rs": []},
            "b": {"n": 30, "mean": -2.0, "std": 1.0, "rs": []},
        }
        out = _expectancy_weights(stats)
        self.assertAlmostEqual(out["a"], 0.5)
        self.assertAlmostEqual(out["b"], 0.5)


# ── Tier selection ─────────────────────────────────────────────────────────

class TierSelectionTests(TestCase):
    def test_sparse_data_goes_tier3(self):
        from signals.meta_allocator import _choose_tier
        stats = {"a": {"n": 5, "mean": 1, "std": 1}}
        tier, factors = _choose_tier(stats)
        self.assertEqual(tier, "tier3")
        self.assertEqual(factors[0], 1.0)  # 100% uniform

    def test_medium_data_goes_tier2(self):
        from signals.meta_allocator import _choose_tier
        stats = {"a": {"n": 15, "mean": 1, "std": 1}}
        tier, _ = _choose_tier(stats)
        self.assertEqual(tier, "tier2")

    def test_mature_data_goes_tier1(self):
        from signals.meta_allocator import _choose_tier
        stats = {"a": {"n": 50, "mean": 1, "std": 1},
                 "b": {"n": 100, "mean": 1, "std": 1}}
        tier, _ = _choose_tier(stats)
        self.assertEqual(tier, "tier1")

    def test_minimum_n_drives_tier_conservative(self):
        from signals.meta_allocator import _choose_tier
        # One rule with mature data, one with sparse — pick tier3 (conservative)
        stats = {"mature": {"n": 100, "mean": 1, "std": 1},
                 "sparse": {"n": 3, "mean": 1, "std": 1}}
        tier, _ = _choose_tier(stats)
        self.assertEqual(tier, "tier3")


# ── Caps + smoothing ───────────────────────────────────────────────────────

class CapsAndSmoothingTests(TestCase):
    def test_caps_clip_extremes_with_many_rules(self):
        from signals.meta_allocator import _apply_caps, MAX_RULE_WEIGHT
        # 10 rules — N-aware max is max(0.30, 2/N) = 0.30 (so MAX_RULE_WEIGHT applies).
        weights = {f"r{i}": 0.0 for i in range(10)}
        weights["r0"] = 0.95  # dominant
        for i in range(1, 10):
            weights[f"r{i}"] = 0.005  # tiny
        out = _apply_caps(weights)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=4)
        self.assertLessEqual(out["r0"], MAX_RULE_WEIGHT + 1e-6)
        # And the small ones get pulled up to MIN.
        for i in range(1, 10):
            self.assertGreater(out[f"r{i}"], 0.0)

    def test_caps_relax_for_small_portfolio(self):
        """With 2 rules, the 30% MAX cap is too tight (uniform = 50%).
        N-aware cap = max(0.30, 2/2) = 1.0, so no effective cap."""
        from signals.meta_allocator import _apply_caps
        out = _apply_caps({"a": 0.7, "b": 0.3})
        self.assertAlmostEqual(out["a"], 0.7, places=4)
        self.assertAlmostEqual(out["b"], 0.3, places=4)

    def test_smoothing_applies_partial_delta(self):
        from signals.meta_allocator import _smooth, SMOOTHING_ALPHA
        current = {"a": 1.0, "b": 1.0}
        target = {"a": 2.0, "b": 0.5}
        smoothed = _smooth(current, target)
        # a: 1.0 + 0.3*(2.0 - 1.0) = 1.3
        # b: 1.0 + 0.3*(0.5 - 1.0) = 0.85
        self.assertAlmostEqual(smoothed["a"], 1.3, places=4)
        self.assertAlmostEqual(smoothed["b"], 0.85, places=4)

    def test_smoothing_drops_in_new_rules_immediately(self):
        from signals.meta_allocator import _smooth
        smoothed = _smooth(current={}, target={"new_rule": 2.5})
        self.assertEqual(smoothed["new_rule"], 2.5)


# ── Effective sizing multiplier integrates both lanes ──────────────────────

class EffectiveMultiplierTests(TestCase):
    def test_active_rule_uses_admin_times_allocator(self):
        from signals.models import RuleControl
        from signals.rule_actuator import rule_size_multiplier
        RuleControl.objects.create(
            rule_name="active_rule", status="active",
            weight_multiplier=1.0, allocator_weight=1.5,
        )
        # active → admin lane = 1.0; allocator = 1.5; product = 1.5
        self.assertEqual(rule_size_multiplier("active_rule"), 1.5)

    def test_reduced_rule_combines_both(self):
        from signals.models import RuleControl
        from signals.rule_actuator import rule_size_multiplier
        RuleControl.objects.create(
            rule_name="reduced_rule", status="reduced",
            weight_multiplier=0.5, allocator_weight=2.0,
        )
        # reduced → admin lane honoured: 0.5; allocator: 2.0; product: 1.0
        self.assertEqual(rule_size_multiplier("reduced_rule"), 1.0)

    def test_unknown_rule_defaults_to_one(self):
        from signals.rule_actuator import rule_size_multiplier
        self.assertEqual(rule_size_multiplier("never_seen"), 1.0)


# ── Propose / apply / rollback flow ─────────────────────────────────────────

class ProposeApplyRollbackTests(TestCase):
    def setUp(self):
        _seed_components()
        self.user = User.objects.create_user(username="alloc_admin", is_superuser=True)
        # Bootstrap two active rules with mature data.
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="rA", status="active",
                                    weight_multiplier=1.0, allocator_weight=1.0)
        RuleControl.objects.create(rule_name="rB", status="active",
                                    weight_multiplier=1.0, allocator_weight=1.0)
        # rA is the winner, rB is the noisy loser.
        _seed_signals("rA", [2.0] * 30 + [-1.0] * 5)  # n=35, expectancy +1.6R
        _seed_signals("rB", [1.0, -1.0] * 18)         # n=36, expectancy ~0

    def test_propose_creates_shadow_allocation(self):
        from signals.meta_allocator import propose_allocation
        from signals.models import MetaAllocation
        alloc = propose_allocation()
        self.assertEqual(alloc.state, MetaAllocation.STATE_SHADOW)
        self.assertGreater(alloc.rules_considered, 0)
        self.assertIn("multipliers", alloc.target_weights)

    def test_shadow_mode_blocks_apply(self):
        from signals.meta_allocator import propose_allocation, apply_allocation, AllocatorError
        _set_live(False)
        alloc = propose_allocation()
        with self.assertRaises(AllocatorError):
            apply_allocation(alloc.id, self.user)

    def test_live_apply_updates_allocator_weights(self):
        from signals.meta_allocator import propose_allocation, apply_allocation
        from signals.models import RuleControl
        _set_live(True)
        alloc = propose_allocation()
        apply_allocation(alloc.id, self.user)

        rA = RuleControl.objects.get(rule_name="rA")
        rB = RuleControl.objects.get(rule_name="rB")
        # Winner's allocator_weight should rise above neutral, loser's stays ≤ neutral.
        self.assertGreater(rA.allocator_weight, rB.allocator_weight)

    def test_rollback_restores_snapshot(self):
        from signals.meta_allocator import propose_allocation, apply_allocation, rollback_allocation
        from signals.models import RuleControl
        _set_live(True)
        # Pre-set non-default weights so we can verify restoration.
        RuleControl.objects.filter(rule_name="rA").update(allocator_weight=0.7)
        RuleControl.objects.filter(rule_name="rB").update(allocator_weight=1.3)
        alloc = propose_allocation()
        apply_allocation(alloc.id, self.user)
        # After apply, weights moved.
        self.assertNotEqual(RuleControl.objects.get(rule_name="rA").allocator_weight, 0.7)
        rollback_allocation(alloc.id, self.user)
        self.assertAlmostEqual(RuleControl.objects.get(rule_name="rA").allocator_weight, 0.7, places=4)
        self.assertAlmostEqual(RuleControl.objects.get(rule_name="rB").allocator_weight, 1.3, places=4)

    def test_paused_rule_untouched_by_apply(self):
        from signals.meta_allocator import propose_allocation, apply_allocation
        from signals.models import RuleControl
        _set_live(True)
        # Pause rB before allocating (admin lane wins).
        RuleControl.objects.filter(rule_name="rB").update(
            status="paused", weight_multiplier=0.0, allocator_weight=0.42,
        )
        alloc = propose_allocation()
        apply_allocation(alloc.id, self.user)
        # rB's allocator_weight must NOT have been touched (paused = admin's lane).
        self.assertEqual(RuleControl.objects.get(rule_name="rB").allocator_weight, 0.42)
