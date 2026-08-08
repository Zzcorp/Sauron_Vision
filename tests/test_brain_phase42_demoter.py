"""Tests for Phase 42 — auto-demoter for generated rules.

Covers:
  - _check_hypothesis_refuted returns metrics when proposal's hypothesis is refuted
  - _check_sustained_negative thresholds (avg_r, min_n)
  - _check_consecutive_losses correctly detects N-in-a-row losses
  - demote_rule flips setup off + RuleControl paused + writes RuleDemotion
  - demote_rule no-ops when rule already paused
  - restore_rule reverses + stamps the demotion
  - scan_generated_rules_now respects min_age_days (skips young rules)
  - scan_generated_rules_now ignores non-auto-generated rules
  - scan_generated_rules_now demotes on each criterion
  - dashboard surfaces open demotions
  - admin restore endpoint works; non-staff blocked
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(name="staff_p42"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.save()
    return u


def _make_generated_rule(rule_name: str, *, age_days: int = 30,
                          status: str = "active",
                          extra_params: dict = None) -> tuple:
    """Create a synthetic generated OpportunitySetup + RuleControl pair."""
    from signals.models_opportunity import OpportunitySetup
    from signals.models_control import RuleControl
    setup = OpportunitySetup.objects.create(
        name=rule_name, description="test", direction="bullish",
        asset_classes=["stock"], conditions=[],
        min_match_score=0.6, suggested_horizon_days=5, sizing={},
        is_active=True,
    )
    params = {"asset_classes": ["stock"], "auto_generated": True}
    if extra_params:
        params.update(extra_params)
    rule = RuleControl.objects.create(
        rule_name=rule_name, status=status,
        weight_multiplier=1.0, allocator_weight=1.0,
        promotion_stage="research", parameters=params,
    )
    # Force created_at backwards.
    if age_days:
        old = timezone.now() - timedelta(days=age_days)
        type(rule).objects.filter(id=rule.id).update(created_at=old)
        type(setup).objects.filter(id=setup.id).update(created_at=old)
        rule.refresh_from_db()
    return setup, rule


def _make_bot_trade(rule_name: str, realized_r: float, *, days_ago: int = 1):
    """Create a closed AssetBotTrade for a rule_name."""
    from bot_program.models import AssetBotConfig, AssetBotTrade
    user = User.objects.filter(username="trader").first() or \
            User.objects.create_user(username="trader", password="x")
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="stock", name="t",
        defaults=dict(
            enabled=True, mode="paper", symbols=["X"],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        ),
    )
    closed = timezone.now() - timedelta(days=days_ago)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="X", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("100") + Decimal(str(realized_r)),
        pnl=Decimal(str(realized_r)),
        rule_name=rule_name, paper=True, status="CLOSED",
        outcome="hit_target" if realized_r >= 0 else "stopped_out",
        realized_r=realized_r, duration_minutes=60,
        opened_at=closed - timedelta(hours=1), closed_at=closed,
    )


# ── Kill criteria ─────────────────────────────────────────────────────────

class CheckHypothesisRefutedTests(TestCase):
    def test_refuted_returns_metrics(self):
        from brain.demoter import _check_hypothesis_refuted
        from brain.hypotheses import post_hypothesis
        from brain.knowledge_models import Hypothesis
        from brain.generator_models import GeneratedSetupProposal
        setup, rule = _make_generated_rule("ref_test")
        h = post_hypothesis(claim_text="x", source_agent="strategy_generator",
                              confidence=0.5, horizon_hours=24,
                              resolution_criteria={"kind": "rule_avg_r",
                                                    "rule_name": "ref_test"})
        Hypothesis.objects.filter(id=h.id).update(
            outcome=Hypothesis.OUTCOME_REFUTED,
            resolved_at=timezone.now())
        GeneratedSetupProposal.objects.create(
            proposed_name="ref_test", direction="bullish",
            asset_classes=["stock"], conditions=[],
            setup=setup, rule_control=rule, hypothesis=h,
        )
        m = _check_hypothesis_refuted("ref_test")
        self.assertIsNotNone(m)
        self.assertEqual(m["hypothesis_id"], h.id)

    def test_pending_hypothesis_returns_none(self):
        from brain.demoter import _check_hypothesis_refuted
        from brain.hypotheses import post_hypothesis
        from brain.generator_models import GeneratedSetupProposal
        setup, rule = _make_generated_rule("pend_test")
        h = post_hypothesis(claim_text="x", source_agent="strategy_generator",
                              confidence=0.5, horizon_hours=24,
                              resolution_criteria={"kind": "rule_avg_r"})
        GeneratedSetupProposal.objects.create(
            proposed_name="pend_test", direction="bullish",
            asset_classes=["stock"], conditions=[],
            setup=setup, rule_control=rule, hypothesis=h,
        )
        self.assertIsNone(_check_hypothesis_refuted("pend_test"))

    def test_no_proposal_returns_none(self):
        from brain.demoter import _check_hypothesis_refuted
        self.assertIsNone(_check_hypothesis_refuted("nonexistent_rule"))


class CheckSustainedNegativeTests(TestCase):
    def test_negative_avg_r_with_enough_n_returns_metrics(self):
        from brain.demoter import _check_sustained_negative
        _make_generated_rule("neg_rule")
        for _ in range(5):
            _make_bot_trade("neg_rule", realized_r=-1.0, days_ago=2)
        m = _check_sustained_negative("neg_rule", window_days=30,
                                        min_n=5, min_avg_r=0.0)
        self.assertIsNotNone(m)
        self.assertLess(m["avg_r"], 0.0)

    def test_positive_avg_r_returns_none(self):
        from brain.demoter import _check_sustained_negative
        _make_generated_rule("pos_rule")
        for _ in range(5):
            _make_bot_trade("pos_rule", realized_r=1.0, days_ago=2)
        self.assertIsNone(_check_sustained_negative("pos_rule",
                                                       window_days=30,
                                                       min_n=5, min_avg_r=0.0))

    def test_insufficient_n_returns_none(self):
        from brain.demoter import _check_sustained_negative
        _make_generated_rule("few_rule")
        for _ in range(2):
            _make_bot_trade("few_rule", realized_r=-1.0, days_ago=2)
        self.assertIsNone(_check_sustained_negative("few_rule",
                                                      window_days=30,
                                                      min_n=5, min_avg_r=0.0))


class CheckConsecutiveLossesTests(TestCase):
    def test_five_losses_in_a_row_triggers(self):
        from brain.demoter import _check_consecutive_losses
        _make_generated_rule("clo_rule")
        for i in range(5):
            _make_bot_trade("clo_rule", realized_r=-1.0, days_ago=5 - i)
        m = _check_consecutive_losses("clo_rule", consec_threshold=5)
        self.assertIsNotNone(m)
        self.assertEqual(len(m["last_realized_rs"]), 5)

    def test_one_winner_in_streak_returns_none(self):
        from brain.demoter import _check_consecutive_losses
        _make_generated_rule("clw_rule")
        # 4 losses + 1 win as most recent → streak broken
        _make_bot_trade("clw_rule", realized_r=-1.0, days_ago=5)
        _make_bot_trade("clw_rule", realized_r=-1.0, days_ago=4)
        _make_bot_trade("clw_rule", realized_r=-1.0, days_ago=3)
        _make_bot_trade("clw_rule", realized_r=-1.0, days_ago=2)
        _make_bot_trade("clw_rule", realized_r=1.5, days_ago=1)
        self.assertIsNone(_check_consecutive_losses("clw_rule",
                                                       consec_threshold=5))

    def test_too_few_trades_returns_none(self):
        from brain.demoter import _check_consecutive_losses
        _make_generated_rule("ftw_rule")
        for _ in range(3):
            _make_bot_trade("ftw_rule", realized_r=-1.0)
        self.assertIsNone(_check_consecutive_losses("ftw_rule",
                                                       consec_threshold=5))


# ── demote_rule + restore_rule ────────────────────────────────────────────

class DemoteAndRestoreTests(TestCase):
    def test_demote_rule_flips_setup_and_writes_audit(self):
        from brain.demoter import demote_rule
        from brain.demoter_models import RuleDemotion
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl
        setup, rule = _make_generated_rule("dem_rule")
        row = demote_rule("dem_rule", "sustained_negative",
                            metrics={"avg_r": -0.7, "n": 8})
        self.assertIsNotNone(row)
        setup.refresh_from_db()
        rule.refresh_from_db()
        self.assertFalse(setup.is_active)
        self.assertEqual(rule.status, "paused")
        self.assertEqual(RuleDemotion.objects.count(), 1)
        self.assertEqual(row.metrics["avg_r"], -0.7)

    def test_demote_already_paused_no_op(self):
        from brain.demoter import demote_rule
        from brain.demoter_models import RuleDemotion
        _make_generated_rule("paused_rule", status="paused")
        row = demote_rule("paused_rule", "sustained_negative")
        self.assertIsNone(row)
        self.assertEqual(RuleDemotion.objects.count(), 0)

    def test_restore_rule_reverses(self):
        from brain.demoter import demote_rule, restore_rule
        from brain.demoter_models import RuleDemotion
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl
        _make_generated_rule("res_rule")
        demote_rule("res_rule", "sustained_negative")
        ok = restore_rule("res_rule", restored_by="admin1")
        self.assertTrue(ok)
        setup = OpportunitySetup.objects.get(name="res_rule")
        rule = RuleControl.objects.get(rule_name="res_rule")
        self.assertTrue(setup.is_active)
        self.assertEqual(rule.status, "active")
        last = RuleDemotion.objects.first()
        self.assertIsNotNone(last.restored_at)
        self.assertEqual(last.restored_by, "admin1")


# ── scan_generated_rules_now ─────────────────────────────────────────────

class ScanGeneratedRulesNowTests(TestCase):
    def test_demotes_on_consecutive_losses(self):
        from brain.demoter import scan_generated_rules_now
        from brain.demoter_models import RuleDemotion
        _make_generated_rule("scan_clo")
        for i in range(5):
            _make_bot_trade("scan_clo", realized_r=-1.0, days_ago=5 - i)
        result = scan_generated_rules_now(min_age_days=14)
        self.assertEqual(result["n_demoted"], 1)
        self.assertEqual(result["breakdown"]["consecutive_losses"], 1)
        self.assertEqual(RuleDemotion.objects.count(), 1)

    def test_skips_young_rules(self):
        from brain.demoter import scan_generated_rules_now
        from brain.demoter_models import RuleDemotion
        # Rule is only 5 days old — too young to kill.
        _make_generated_rule("young_rule", age_days=5)
        for i in range(5):
            _make_bot_trade("young_rule", realized_r=-1.0, days_ago=4 - i)
        result = scan_generated_rules_now(min_age_days=14)
        self.assertEqual(result["n_demoted"], 0)
        self.assertGreaterEqual(result["n_skipped_too_young"], 1)
        self.assertEqual(RuleDemotion.objects.count(), 0)

    def test_ignores_non_auto_generated_rules(self):
        from brain.demoter import scan_generated_rules_now
        from brain.demoter_models import RuleDemotion
        # Auto_generated=False — Phase 8 owns its lifecycle.
        _make_generated_rule("manual_rule",
                                extra_params={"auto_generated": False})
        for i in range(5):
            _make_bot_trade("manual_rule", realized_r=-1.0, days_ago=5 - i)
        result = scan_generated_rules_now(min_age_days=14)
        self.assertEqual(result["n_demoted"], 0)
        self.assertEqual(RuleDemotion.objects.count(), 0)

    def test_demotes_on_hypothesis_refuted(self):
        from brain.demoter import scan_generated_rules_now
        from brain.hypotheses import post_hypothesis
        from brain.knowledge_models import Hypothesis
        from brain.generator_models import GeneratedSetupProposal
        from brain.demoter_models import RuleDemotion

        setup, rule = _make_generated_rule("hyp_ref_rule")
        h = post_hypothesis(claim_text="x", source_agent="strategy_generator",
                              confidence=0.5, horizon_hours=1,
                              resolution_criteria={"kind": "rule_avg_r"})
        Hypothesis.objects.filter(id=h.id).update(
            outcome=Hypothesis.OUTCOME_REFUTED,
            resolved_at=timezone.now())
        GeneratedSetupProposal.objects.create(
            proposed_name="hyp_ref_rule", direction="bullish",
            asset_classes=["stock"], conditions=[],
            setup=setup, rule_control=rule, hypothesis=h,
        )
        result = scan_generated_rules_now(min_age_days=14)
        self.assertEqual(result["n_demoted"], 1)
        self.assertEqual(result["breakdown"]["hypothesis_refuted"], 1)


# ── Dashboard / admin ─────────────────────────────────────────────────────

class DemoterDashboardTests(TestCase):
    def test_dashboard_shows_open_demotions(self):
        from brain.demoter_models import RuleDemotion
        u = User.objects.create_user(username="dem_view", password="x")
        self.client.force_login(u)
        RuleDemotion.objects.create(rule_name="x", criterion="manual",
                                      metrics={"avg_r": -0.5})
        r = self.client.get("/generated/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("auto-demoted", body)
        self.assertIn("x", body)


class AdminEndpointsTests(TestCase):
    def test_admin_can_run_demoter_now(self):
        u = _staff()
        self.client.force_login(u)
        r = self.client.post("/generated/demote-now/")
        self.assertEqual(r.status_code, 302)

    def test_admin_can_restore_rule(self):
        from brain.demoter import demote_rule
        u = _staff()
        self.client.force_login(u)
        _make_generated_rule("rest_rule")
        demote_rule("rest_rule", "sustained_negative")
        r = self.client.post(f"/generated/restore/rest_rule/")
        self.assertEqual(r.status_code, 302)
        from signals.models_control import RuleControl
        self.assertEqual(RuleControl.objects.get(rule_name="rest_rule").status,
                          "active")

    def test_non_staff_cannot_run_demoter(self):
        u = User.objects.create_user(username="ns_dem", password="x")
        self.client.force_login(u)
        r = self.client.post("/generated/demote-now/")
        self.assertIn("/admin/login/", r.url)
