"""Tests for Phase 54 — audit log expansion for brain-stack decisions.

Covers each new audit helper hook + verifies the chain stays valid:
  - approve/reject proposal → proposal_approved/rejected entries
  - demote_rule → rule_demoted entry
  - restore_rule → rule_restored entry
  - brain pause_recommended in scan_symbol → brain_soft_block entry
  - hypothesis resolution → hypothesis_resolved entry
  - verify_chain stays ok across all new event types
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="audit_t"):
    return User.objects.create_user(username=name, password="x")


# ── Generator approve / reject ───────────────────────────────────────────

class GeneratorAuditTests(TestCase):
    def _create_pending(self):
        from brain.strategy_generator import _persist_proposal
        return _persist_proposal({
            "name_slug": "audit_test", "rationale_md": "x",
            "direction": "bullish", "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma"},
                              "weight": 1.0}],
            "min_match_score": 0.6, "suggested_horizon_days": 5,
            "confidence": 0.5,
        }, model="t", tokens_in=0, tokens_out=0, cost_usd=0.0)

    def test_approve_writes_proposal_approved_audit(self):
        from brain.strategy_generator import approve_proposal
        from bot_program.audit_models import AuditLogEntry
        proposal = self._create_pending()
        approve_proposal(proposal, reviewed_by="alice", notes="ship it")
        entry = AuditLogEntry.objects.filter(kind="proposal_approved").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.data["proposal_id"], proposal.id)
        self.assertEqual(entry.data["reviewed_by"], "alice")
        self.assertEqual(entry.data["decision"], "approved")

    def test_reject_writes_proposal_rejected_audit(self):
        from brain.strategy_generator import reject_proposal
        from bot_program.audit_models import AuditLogEntry
        proposal = self._create_pending()
        reject_proposal(proposal, reviewed_by="bob", notes="meh")
        entry = AuditLogEntry.objects.filter(kind="proposal_rejected").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.data["reviewed_by"], "bob")


# ── Demoter audit ────────────────────────────────────────────────────────

class DemoterAuditTests(TestCase):
    def _make_rule(self, name):
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl
        OpportunitySetup.objects.create(
            name=name, description="t", direction="bullish",
            asset_classes=["stock"], conditions=[],
            min_match_score=0.6, suggested_horizon_days=5, sizing={},
            is_active=True,
        )
        RuleControl.objects.create(
            rule_name=name, status="active",
            weight_multiplier=1.0, allocator_weight=1.0,
            promotion_stage="research",
            parameters={"auto_generated": True},
        )

    def test_demote_writes_rule_demoted_audit(self):
        from brain.demoter import demote_rule
        from bot_program.audit_models import AuditLogEntry
        self._make_rule("dm_audit_rule")
        demote_rule("dm_audit_rule", "sustained_negative",
                     metrics={"avg_r": -0.7, "n": 8})
        entry = AuditLogEntry.objects.filter(kind="rule_demoted").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.data["rule_name"], "dm_audit_rule")
        self.assertEqual(entry.data["criterion"], "sustained_negative")
        self.assertEqual(entry.data["metrics"]["avg_r"], -0.7)

    def test_restore_writes_rule_restored_audit(self):
        from brain.demoter import demote_rule, restore_rule
        from bot_program.audit_models import AuditLogEntry
        self._make_rule("rs_audit_rule")
        demote_rule("rs_audit_rule", "sustained_negative")
        restore_rule("rs_audit_rule", restored_by="carol")
        entry = AuditLogEntry.objects.filter(kind="rule_restored").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.data["rule_name"], "rs_audit_rule")
        self.assertEqual(entry.data["restored_by"], "carol")


# ── Brain soft-block in scan_symbol ──────────────────────────────────────

class BrainSoftBlockAuditTests(TestCase):
    def test_brain_pause_recommendation_writes_audit(self):
        """When scan_symbol's brain advisory check returns pause_recommended,
        a brain_soft_block audit entry should be written."""
        from bot_program.audit import record_brain_soft_block
        from bot_program.audit_models import AuditLogEntry
        # Direct call to the helper (the integration path is exercised in
        # Phase 39 tests; here we verify the audit hook itself).
        u = _user()
        record_brain_soft_block(
            user=u, asset_class="stock", symbol="AAPL",
            rule_name="momentum_a", advisory_source="brain_report (regime=risk_off)",
        )
        entry = AuditLogEntry.objects.filter(kind="brain_soft_block").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.data["symbol"], "AAPL")
        self.assertEqual(entry.data["rule_name"], "momentum_a")
        self.assertIn("regime=risk_off", entry.data["advisory_source"])
        self.assertEqual(entry.user_id, u.id)


# ── Hypothesis resolution audit ─────────────────────────────────────────

class HypothesisResolveAuditTests(TestCase):
    def test_resolution_writes_hypothesis_resolved_audit(self):
        from brain.hypotheses import post_hypothesis, resolve_due
        from brain.knowledge_models import Hypothesis
        from brain.models import BrainReport
        from bot_program.audit_models import AuditLogEntry

        h = post_hypothesis(
            claim_text="regime stays trending",
            source_agent="sauron_mind", confidence=0.7,
            resolution_criteria={"kind": "regime_holds", "regime": "trending"},
            horizon_hours=1,
        )
        # Force deadline past + matching report.
        Hypothesis.objects.filter(id=h.id).update(
            resolution_deadline=timezone.now() - timedelta(minutes=5))
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.8)

        resolve_due()

        entry = AuditLogEntry.objects.filter(kind="hypothesis_resolved").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.data["hypothesis_id"], h.id)
        self.assertEqual(entry.data["outcome"], "confirmed")
        self.assertEqual(entry.data["source_agent"], "sauron_mind")


# ── Chain integrity across new events ───────────────────────────────────

class ChainIntegrityTests(TestCase):
    def _make_rule(self, name):
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl
        OpportunitySetup.objects.create(
            name=name, description="t", direction="bullish",
            asset_classes=["stock"], conditions=[],
            min_match_score=0.6, suggested_horizon_days=5, sizing={},
            is_active=True,
        )
        RuleControl.objects.create(
            rule_name=name, status="active",
            weight_multiplier=1.0, allocator_weight=1.0,
            promotion_stage="research",
            parameters={"auto_generated": True},
        )

    def test_chain_remains_valid_across_phase54_events(self):
        """Write several Phase-54 events; verify_chain reports ok=True."""
        from brain.demoter import demote_rule, restore_rule
        from brain.strategy_generator import _persist_proposal, approve_proposal
        from bot_program.audit import record_brain_soft_block, verify_chain

        # Mix of new event kinds.
        proposal = _persist_proposal({
            "name_slug": "chain_test", "rationale_md": "x",
            "direction": "bullish", "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma"},
                              "weight": 1.0}],
            "min_match_score": 0.6, "suggested_horizon_days": 5,
            "confidence": 0.5,
        }, model="t", tokens_in=0, tokens_out=0, cost_usd=0.0)
        approve_proposal(proposal, reviewed_by="alice")

        self._make_rule("chain_rule")
        demote_rule("chain_rule", "sustained_negative",
                     metrics={"avg_r": -0.5})
        restore_rule("chain_rule", restored_by="alice")

        u = _user("ch_u")
        record_brain_soft_block(
            user=u, asset_class="stock", symbol="X",
            rule_name="chain_rule", advisory_source="brain_report (regime=risk_off)",
        )

        result = verify_chain()
        self.assertTrue(result["ok"])
        self.assertEqual(result["breaks"], [])
        # Verify we did write multiple new-kind entries.
        self.assertGreaterEqual(result["verified"], 4)
