"""Tests for Phase-5 rule actuator — closed-loop self-adjustment.

Covers:
  - propose_actions_from_decay: idempotent, skips informational actions
  - apply_action: shadow mode blocks; live mode applies; snapshots taken
  - rollback_action: restores the snapshot exactly
  - reject_action: marks rejected without enforcement
  - is_rule_active / rule_size_multiplier: read-side helpers
  - Daily rate limit: caps applied actions per type
  - Auto-expiry of stale proposals
  - Signal persistence respects paused rules

Run with:  python manage.py test tests.test_rule_actuator
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _seed_components():
    from core.platform_control import seed_components
    seed_components()


def _set_live_mode(enabled: bool):
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key="actuator_mode_live",
        defaults={"name": "Actuator Live Mode", "category": "system"},
    )
    c.is_enabled = enabled
    c.save()


def _make_decay_investigation(rule_name="rule_a", action="pause_rule"):
    from ai_agents.models import DecayInvestigation
    return DecayInvestigation.objects.create(
        rule_name=rule_name,
        recent_expectancy=-1.0, baseline_expectancy=2.0,
        recent_n=5, baseline_n=10,
        hypothesis="Regime shifted to ranging",
        contributing_factors=["regime shift"],
        recommended_action=action,
    )


# ── Proposal generation ────────────────────────────────────────────────────

class ProposalGenerationTests(TestCase):
    def test_creates_proposal_for_pause_rule(self):
        from signals.rule_actuator import propose_actions_from_decay
        from signals.models import RuleAction
        _make_decay_investigation("rule_a", "pause_rule")
        n = propose_actions_from_decay()
        self.assertEqual(n, 1)
        a = RuleAction.objects.get(rule_name="rule_a")
        self.assertEqual(a.action, "pause_rule")
        self.assertEqual(a.state, RuleAction.STATE_PROPOSED)

    def test_skips_informational_actions(self):
        from signals.rule_actuator import propose_actions_from_decay
        from signals.models import RuleAction
        for action in ("monitor", "investigate_data", "retune_params"):
            _make_decay_investigation(f"rule_{action}", action)
        n = propose_actions_from_decay()
        self.assertEqual(n, 0)
        self.assertEqual(RuleAction.objects.count(), 0)

    def test_idempotent_reruns_dont_duplicate(self):
        from signals.rule_actuator import propose_actions_from_decay
        from signals.models import RuleAction
        _make_decay_investigation("rule_a", "reduce_size")
        propose_actions_from_decay()
        propose_actions_from_decay()
        propose_actions_from_decay()
        self.assertEqual(RuleAction.objects.count(), 1)


# ── Apply / shadow mode / live mode ─────────────────────────────────────────

class ApplyActionTests(TestCase):
    def setUp(self):
        _seed_components()
        self.user = User.objects.create_user(username="actadmin", is_superuser=True)
        inv = _make_decay_investigation("rule_x", "pause_rule")
        from signals.rule_actuator import propose_actions_from_decay
        propose_actions_from_decay()
        from signals.models import RuleAction
        self.action = RuleAction.objects.get(rule_name="rule_x")

    def test_shadow_mode_blocks_apply(self):
        from signals.rule_actuator import apply_action, ActuatorError
        _set_live_mode(False)
        with self.assertRaises(ActuatorError) as cm:
            apply_action(self.action.id, self.user)
        self.assertIn("shadow", str(cm.exception).lower())

    def test_live_mode_applies_pause(self):
        from signals.rule_actuator import apply_action, is_rule_active
        from signals.models import RuleControl
        _set_live_mode(True)
        a = apply_action(self.action.id, self.user)
        self.assertEqual(a.state, "applied")
        self.assertEqual(a.previous_status, "active")  # snapshot took the default
        self.assertEqual(a.previous_weight, 1.0)
        ctrl = RuleControl.objects.get(rule_name="rule_x")
        self.assertEqual(ctrl.status, "paused")
        self.assertIsNotNone(ctrl.paused_until)
        self.assertFalse(is_rule_active("rule_x"))

    def test_apply_twice_fails(self):
        from signals.rule_actuator import apply_action, ActuatorError
        _set_live_mode(True)
        apply_action(self.action.id, self.user)
        with self.assertRaises(ActuatorError):
            apply_action(self.action.id, self.user)


class ReduceSizeTests(TestCase):
    def setUp(self):
        _seed_components()
        _set_live_mode(True)
        self.user = User.objects.create_user(username="reduceadmin", is_superuser=True)
        _make_decay_investigation("rule_r", "reduce_size")
        from signals.rule_actuator import propose_actions_from_decay
        propose_actions_from_decay()
        from signals.models import RuleAction
        self.action = RuleAction.objects.get(rule_name="rule_r")

    def test_reduce_size_sets_multiplier(self):
        from signals.rule_actuator import apply_action, rule_size_multiplier
        apply_action(self.action.id, self.user)
        self.assertEqual(rule_size_multiplier("rule_r"), 0.5)


# ── Rollback ───────────────────────────────────────────────────────────────

class RollbackTests(TestCase):
    def setUp(self):
        _seed_components()
        _set_live_mode(True)
        self.user = User.objects.create_user(username="rolladmin", is_superuser=True)

    def test_rollback_restores_previous_state(self):
        from signals.models import RuleAction, RuleControl
        from signals.rule_actuator import propose_actions_from_decay, apply_action, rollback_action

        # First, manually pre-set the rule to "reduced" so rollback has something
        # non-default to restore.
        RuleControl.objects.create(rule_name="rule_y", status="reduced",
                                    weight_multiplier=0.7)
        _make_decay_investigation("rule_y", "pause_rule")
        propose_actions_from_decay()
        action = RuleAction.objects.get(rule_name="rule_y")

        apply_action(action.id, self.user)
        # Now status=paused
        self.assertEqual(RuleControl.objects.get(rule_name="rule_y").status, "paused")

        rollback_action(action.id, self.user)
        ctrl = RuleControl.objects.get(rule_name="rule_y")
        self.assertEqual(ctrl.status, "reduced")
        self.assertEqual(ctrl.weight_multiplier, 0.7)


# ── Rate limit ─────────────────────────────────────────────────────────────

class RateLimitTests(TestCase):
    def setUp(self):
        _seed_components()
        _set_live_mode(True)
        self.user = User.objects.create_user(username="rateadmin", is_superuser=True)

    def test_daily_pause_cap_enforced(self):
        from signals.rule_actuator import (
            propose_actions_from_decay, apply_action, ActuatorError,
            MAX_PAUSES_PER_DAY,
        )
        from signals.models import RuleAction
        # Create MAX + 1 proposals
        for i in range(MAX_PAUSES_PER_DAY + 1):
            _make_decay_investigation(f"rule_p{i}", "pause_rule")
        propose_actions_from_decay()

        proposals = list(RuleAction.objects.filter(state="proposed"))
        self.assertEqual(len(proposals), MAX_PAUSES_PER_DAY + 1)

        # First MAX should succeed
        for p in proposals[:MAX_PAUSES_PER_DAY]:
            apply_action(p.id, self.user)

        # Next one should fail rate-limit
        with self.assertRaises(ActuatorError) as cm:
            apply_action(proposals[MAX_PAUSES_PER_DAY].id, self.user)
        self.assertIn("Daily cap", str(cm.exception))


# ── Reject + auto-expiry ───────────────────────────────────────────────────

class RejectAndExpireTests(TestCase):
    def setUp(self):
        _seed_components()
        self.user = User.objects.create_user(username="rejadmin", is_superuser=True)

    def test_reject_marks_rejected(self):
        from signals.rule_actuator import propose_actions_from_decay, reject_action
        from signals.models import RuleAction
        _make_decay_investigation("rule_z", "pause_rule")
        propose_actions_from_decay()
        a = RuleAction.objects.get(rule_name="rule_z")
        reject_action(a.id, self.user)
        a.refresh_from_db()
        self.assertEqual(a.state, "rejected")
        self.assertIsNotNone(a.rejected_at)

    def test_expire_stale_proposals(self):
        from signals.rule_actuator import (
            propose_actions_from_decay, expire_stale_proposals, PROPOSAL_TTL_DAYS,
        )
        from signals.models import RuleAction
        _make_decay_investigation("rule_old", "pause_rule")
        propose_actions_from_decay()
        a = RuleAction.objects.get(rule_name="rule_old")
        # Force proposed_at backdate
        RuleAction.objects.filter(id=a.id).update(
            proposed_at=timezone.now() - timedelta(days=PROPOSAL_TTL_DAYS + 1)
        )
        n = expire_stale_proposals()
        self.assertEqual(n, 1)
        a.refresh_from_db()
        self.assertEqual(a.state, "expired")


# ── Read-side helpers ──────────────────────────────────────────────────────

class ReadSideHelperTests(TestCase):
    def test_unknown_rule_defaults_to_active(self):
        from signals.rule_actuator import is_rule_active, rule_size_multiplier
        self.assertTrue(is_rule_active("never_seen"))
        self.assertEqual(rule_size_multiplier("never_seen"), 1.0)

    def test_paused_until_in_future_blocks(self):
        from signals.models import RuleControl
        from signals.rule_actuator import is_rule_active
        RuleControl.objects.create(
            rule_name="rule_locked", status="paused", weight_multiplier=0.0,
            paused_until=timezone.now() + timedelta(days=1),
        )
        self.assertFalse(is_rule_active("rule_locked"))

    def test_paused_until_in_past_auto_reactivates(self):
        from signals.models import RuleControl
        from signals.rule_actuator import is_rule_active
        RuleControl.objects.create(
            rule_name="rule_recovered", status="paused", weight_multiplier=0.0,
            paused_until=timezone.now() - timedelta(days=1),
        )
        # paused_until elapsed → effectively active again
        self.assertTrue(is_rule_active("rule_recovered"))


# ── Signal persistence respects paused rules ────────────────────────────────

class SignalPersistencePausedTests(TestCase):
    def test_paused_rule_blocks_signal_creation(self):
        from instruments.models import Instrument
        from signals.models import Signal, RuleControl
        from signals.tasks import _create_signals_and_notify

        inst = Instrument.objects.create(symbol="TEST_PAUSE", name="t",
                                          asset_class="crypto")
        RuleControl.objects.create(
            rule_name="paused_rule", status="paused", weight_multiplier=0.0,
            paused_until=timezone.now() + timedelta(days=1),
        )
        results = [{
            "instrument": inst, "rule_name": "paused_rule",
            "signal_type": "composite", "direction": "bullish", "urgency": "medium",
            "title": "t", "description": "t", "score": 0.7, "sub_scores": {},
            "price_at_signal": Decimal("100"),
        }]
        n = _create_signals_and_notify(results)
        self.assertEqual(n, 0)
        self.assertEqual(Signal.objects.filter(rule_name="paused_rule").count(), 0)

    def test_reduced_rule_attaches_multiplier_to_sub_scores(self):
        from instruments.models import Instrument
        from signals.models import Signal, RuleControl
        from signals.tasks import _create_signals_and_notify

        inst = Instrument.objects.create(symbol="TEST_REDUCE", name="t",
                                          asset_class="crypto")
        RuleControl.objects.create(
            rule_name="reduced_rule", status="reduced", weight_multiplier=0.5,
        )
        results = [{
            "instrument": inst, "rule_name": "reduced_rule",
            "signal_type": "composite", "direction": "bullish", "urgency": "medium",
            "title": "t", "description": "t", "score": 0.7, "sub_scores": {},
            "price_at_signal": Decimal("100"),
        }]
        _create_signals_and_notify(results)
        sig = Signal.objects.get(rule_name="reduced_rule")
        self.assertEqual(sig.sub_scores.get("actuator_multiplier"), 0.5)
