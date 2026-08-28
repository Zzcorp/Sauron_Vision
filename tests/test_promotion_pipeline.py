"""Tests for Phase-8 promotion pipeline.

Covers:
  - Stage ordering + size factors
  - Promotion eligibility checks (research → paper → live_small → live_full)
  - Demotion criteria on degradation
  - rule_size_multiplier composes admin × allocator × promotion correctly
  - Manual promote/demote validation
  - auto_evaluate_all_rules is idempotent on a stable system
  - PAPER stage forces 0 size factor (no live exposure to under-tested rules)
  - Default LIVE_FULL preserves backwards compat for legacy rules

Run with:  python manage.py test tests.test_promotion_pipeline
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "crypto"},
    )
    return inst


def _seed_signals(rule_name: str, rs: list[float], days_ago_start: int = 0):
    """Seed N closed signals for one rule with given realized_r values."""
    from signals.models import Signal
    inst = _instrument(f"PROM_{rule_name}")
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
            realized_r=r,
            expired_at=timezone.now() - timedelta(days=days_ago_start + i),
        )


def _seed_fills(rule_name: str, rs: list, *, paper: bool = True,
                days_ago_start: int = 0):
    """Seed graded BOT TRADES — what a broker actually filled.

    The promotion ladder used to read `Signal` for every stage, so the
    paper rung could be cleared without a single fill existing anywhere.
    It reads the trade ledger now, and a test that seeds only signals is
    testing the platform's predictions, not its execution.
    """
    from django.contrib.auth.models import User
    from bot_program.models import AssetBotConfig, AssetBotTrade
    user, _ = User.objects.get_or_create(username="promo_fill_user")
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, name=f"PF_{rule_name}",
        defaults=dict(asset_class="stock", mode="paper", symbols=["PFX"],
                      capital=Decimal("10000"), enabled=True))
    for i, r in enumerate(rs):
        closed = timezone.now() - timedelta(days=days_ago_start + i,
                                            hours=1)
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="PFX", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), exit_price=Decimal("110"),
            pnl=Decimal(str(round(r * 50, 4))), status="CLOSED",
            paper=paper, rule_name=rule_name,
            outcome="hit_target" if r > 0 else "stopped_out",
            realized_r=r,
            opened_at=closed - timedelta(hours=2))
        AssetBotTrade.objects.filter(pk=t.pk).update(closed_at=closed)


def _set_stage(rule_name: str, stage: str, *, baseline=None, entered_days_ago=None):
    from signals.models import RuleControl
    ctrl, _ = RuleControl.objects.get_or_create(
        rule_name=rule_name,
        defaults={"status": "active", "promotion_stage": "research"},
    )
    ctrl.promotion_stage = stage
    if baseline is not None:
        ctrl.stage_baseline_expectancy = baseline
    if entered_days_ago is not None:
        ctrl.stage_entered_at = timezone.now() - timedelta(days=entered_days_ago)
    else:
        ctrl.stage_entered_at = timezone.now()
    ctrl.save()
    return ctrl


# ── Stage taxonomy ─────────────────────────────────────────────────────────

class StageTaxonomyTests(TestCase):
    def test_size_factors_form_strict_ladder(self):
        from signals.promotion_pipeline import SIZE_FACTORS
        self.assertEqual(SIZE_FACTORS["research"], 0.0)
        self.assertEqual(SIZE_FACTORS["paper"], 0.0)
        self.assertEqual(SIZE_FACTORS["live_small"], 0.25)
        self.assertEqual(SIZE_FACTORS["live_full"], 1.0)

    def test_promotion_size_factor_for_unknown_rule_defaults_to_full(self):
        from signals.promotion_pipeline import promotion_size_factor
        self.assertEqual(promotion_size_factor("never_seen"), 1.0)


# ── Eligibility + transitions ──────────────────────────────────────────────

class EligibilityTests(TestCase):
    def test_research_to_paper_requires_data_and_positive_expectancy(self):
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rA", "research")
        # Only 5 closed signals — below the 30 min — so not eligible.
        _seed_signals("rA", [2.0] * 5)
        self.assertIsNone(is_eligible_for_promotion("rA"))

    def test_research_to_paper_succeeds_with_30_signals_positive(self):
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rB", "research")
        _seed_signals("rB", [2.0] * 20 + [-1.0] * 12)  # n=32, hit_rate=20/32=0.625
        self.assertEqual(is_eligible_for_promotion("rB"), "paper")

    def test_paper_to_live_small_requires_30_days_in_stage(self):
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rC", "paper", baseline=1.0, entered_days_ago=10)
        _seed_signals("rC", [2.0] * 25)
        self.assertIsNone(is_eligible_for_promotion("rC"))  # only 10 days in stage

    def test_paper_to_live_small_succeeds_when_retention_met(self):
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rD", "paper", baseline=1.0, entered_days_ago=35)
        # 25 closed, expectancy ≈ 1.5 (≥ 70% of baseline 1.0)
        _seed_signals("rD", [2.0] * 20 + [-1.0] * 5, days_ago_start=0)
        # …and the PAPER FILLS the stage exists to require. Signals are
        # what the platform predicted; these are what a venue executed.
        _seed_fills("rD", [2.0] * 20 + [-1.0] * 5)
        self.assertEqual(is_eligible_for_promotion("rD"), "live_small")

    def test_paper_to_live_small_refuses_on_signals_alone(self):
        """The whole point of the stage. Before the venue leg this rule
        promoted itself to LIVE CAPITAL on a signal table it had never
        traded — three date windows of one measurement, reported as
        research, paper and live expectancy."""
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rD2", "paper", baseline=1.0, entered_days_ago=35)
        _seed_signals("rD2", [2.0] * 20 + [-1.0] * 5, days_ago_start=0)
        self.assertIsNone(is_eligible_for_promotion("rD2"))

    def test_losing_paper_fills_block_promotion(self):
        """Good predictions, bad execution — the gap the paper stage is
        supposed to find."""
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rD3", "paper", baseline=1.0, entered_days_ago=35)
        _seed_signals("rD3", [2.0] * 20 + [-1.0] * 5, days_ago_start=0)
        _seed_fills("rD3", [-1.0] * 25)
        self.assertIsNone(is_eligible_for_promotion("rD3"))

    def test_live_full_returns_none(self):
        from signals.promotion_pipeline import is_eligible_for_promotion
        _set_stage("rE", "live_full")
        self.assertIsNone(is_eligible_for_promotion("rE"))


class DemotionTests(TestCase):
    def test_live_full_degraded_demotes_to_live_small(self):
        from signals.promotion_pipeline import is_due_for_demotion
        _set_stage("rF", "live_full", baseline=2.0)
        # Recent 14d: 12 closed at expectancy ~ -1.0 — well below 0.5 × baseline
        _seed_signals("rF", [-1.0] * 12)
        self.assertEqual(is_due_for_demotion("rF"), "live_small")

    def test_live_full_stable_no_demotion(self):
        from signals.promotion_pipeline import is_due_for_demotion
        _set_stage("rG", "live_full", baseline=1.0)
        _seed_signals("rG", [1.5] * 12)  # holding above threshold
        self.assertIsNone(is_due_for_demotion("rG"))

    def test_paper_demoted_when_negative_expectancy(self):
        from signals.promotion_pipeline import is_due_for_demotion
        _set_stage("rH", "paper")
        _seed_signals("rH", [-1.0] * 15)
        self.assertEqual(is_due_for_demotion("rH"), "research")


# ── Manual transitions ─────────────────────────────────────────────────────

class ManualTransitionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="prom_admin", is_superuser=True)

    def test_promote_creates_event_and_advances_stage(self):
        from signals.promotion_pipeline import promote_rule
        from signals.models import RuleControl, PromotionEvent
        _set_stage("rI", "research")
        _seed_signals("rI", [2.0] * 5)  # need data for the baseline snapshot
        ev = promote_rule("rI", user=self.user)
        self.assertEqual(ev.from_stage, "research")
        self.assertEqual(ev.to_stage, "paper")
        self.assertEqual(RuleControl.objects.get(rule_name="rI").promotion_stage, "paper")
        self.assertEqual(PromotionEvent.objects.filter(rule_name="rI").count(), 1)

    def test_promote_at_top_stage_raises(self):
        from signals.promotion_pipeline import promote_rule, PipelineError
        _set_stage("rJ", "live_full")
        with self.assertRaises(PipelineError):
            promote_rule("rJ", user=self.user)

    def test_demote_at_bottom_stage_raises(self):
        from signals.promotion_pipeline import demote_rule, PipelineError
        _set_stage("rK", "research")
        with self.assertRaises(PipelineError):
            demote_rule("rK", user=self.user)

    def test_promote_with_non_forward_target_raises(self):
        from signals.promotion_pipeline import promote_rule, PipelineError
        _set_stage("rL", "live_small")
        with self.assertRaises(PipelineError):
            promote_rule("rL", target_stage="research", user=self.user)


# ── Sizing composition ─────────────────────────────────────────────────────

class SizingCompositionTests(TestCase):
    def test_paper_stage_zeroes_effective_size_regardless_of_other_lanes(self):
        from signals.models import RuleControl
        from signals.rule_actuator import rule_size_multiplier
        RuleControl.objects.create(
            rule_name="rM", status="active",
            weight_multiplier=1.0, allocator_weight=2.5,
            promotion_stage="paper",
        )
        # 1.0 (admin) × 2.5 (allocator) × 0.0 (paper) = 0
        self.assertEqual(rule_size_multiplier("rM"), 0.0)

    def test_live_small_quarters_the_size(self):
        from signals.models import RuleControl
        from signals.rule_actuator import rule_size_multiplier
        RuleControl.objects.create(
            rule_name="rN", status="active",
            weight_multiplier=1.0, allocator_weight=1.5,
            promotion_stage="live_small",
        )
        # 1.0 × 1.5 × 0.25 = 0.375
        self.assertAlmostEqual(rule_size_multiplier("rN"), 0.375, places=4)

    def test_live_full_passes_through_other_lanes(self):
        from signals.models import RuleControl
        from signals.rule_actuator import rule_size_multiplier
        RuleControl.objects.create(
            rule_name="rO", status="reduced",
            weight_multiplier=0.5, allocator_weight=1.5,
            promotion_stage="live_full",
        )
        # 0.5 (admin reduced) × 1.5 (allocator) × 1.0 (live_full) = 0.75
        self.assertAlmostEqual(rule_size_multiplier("rO"), 0.75, places=4)


# ── Auto-evaluation ────────────────────────────────────────────────────────

class AutoEvaluationTests(TestCase):
    def test_auto_eval_promotes_eligible_demotes_degraded(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        # Eligible rule: research → paper
        _set_stage("rP", "research")
        _seed_signals("rP", [2.0] * 25 + [-1.0] * 8)  # n=33, hit_rate ~0.76
        # Degrading rule: live_full → live_small
        _set_stage("rQ", "live_full", baseline=2.0)
        _seed_signals("rQ", [-1.0] * 12)
        result = auto_evaluate_all_rules()
        self.assertIn("rP", result["promoted"])
        self.assertIn("rQ", result["demoted"])

    def test_auto_eval_idempotent_on_stable_system(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        _set_stage("rR", "live_full", baseline=1.0)
        _seed_signals("rR", [1.2] * 12)  # holding above threshold
        result1 = auto_evaluate_all_rules()
        result2 = auto_evaluate_all_rules()
        self.assertEqual(result1["n_promoted"] + result1["n_demoted"], 0)
        self.assertEqual(result2["n_promoted"] + result2["n_demoted"], 0)

    def test_auto_eval_skips_admin_paused_rules(self):
        from signals.models import RuleControl
        from signals.promotion_pipeline import auto_evaluate_all_rules
        # A degraded LIVE_FULL rule, but admin has paused it — pipeline must not act.
        _set_stage("rS", "live_full", baseline=2.0)
        RuleControl.objects.filter(rule_name="rS").update(status="paused")
        _seed_signals("rS", [-1.0] * 12)
        result = auto_evaluate_all_rules()
        self.assertNotIn("rS", result["demoted"])
