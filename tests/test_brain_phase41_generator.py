"""Tests for Phase 41 — autonomous strategy generator.

Covers:
  - validate_proposal: catches unknown evaluators / bad direction / bad weights / bad slug
  - _persist_proposal: creates OpportunitySetup at is_active=False + RuleControl
    research stage + Hypothesis + GeneratedSetupProposal
  - generate_strategies_now happy path with stubbed Opus provider
  - generate_strategies_now error path returns ok=False, no rows persisted
  - approve_proposal flips setup.is_active=True
  - reject_proposal does NOT activate setup
  - approve already-approved proposal is no-op
  - expire_old_proposals stamps stale pending → expired
  - /generated/ dashboard renders 200
  - admin approve/reject endpoints work; non-staff blocked
  - Setup name auto-prefixed `generated_<date>_<slug>`
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(name="staff_p41"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.save()
    return u


def _stub_generator_provider(parsed_dict, raw_text=None, usage=None):
    import json
    raw = raw_text if raw_text is not None else json.dumps(parsed_dict)
    usage = usage or {"input_tokens": 10000, "output_tokens": 2000,
                       "cost_usd": 0.50}

    def patched_init(self, *a, **kw):
        self.agent_name = "strategy_generator"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))
    return patch("brain.strategy_generator.StrategyGeneratorAgent.__init__",
                 patched_init)


# ── Validation ────────────────────────────────────────────────────────────

class ValidateProposalTests(TestCase):
    def _good(self):
        return {
            "name_slug": "ok_slug",
            "rationale_md": "x",
            "direction": "bullish",
            "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma"},
                              "weight": 1.0}],
            "min_match_score": 0.6,
            "suggested_horizon_days": 5,
        }

    def test_good_proposal_validates(self):
        from brain.strategy_generator import validate_proposal
        ok, why = validate_proposal(self._good())
        self.assertTrue(ok, why)

    def test_unknown_evaluator_kind_rejected(self):
        from brain.strategy_generator import validate_proposal
        p = self._good()
        p["conditions"][0]["kind"] = "totally_made_up_evaluator"
        ok, why = validate_proposal(p)
        self.assertFalse(ok)
        self.assertIn("unknown evaluator", why)

    def test_bad_direction_rejected(self):
        from brain.strategy_generator import validate_proposal
        p = self._good()
        p["direction"] = "sideways"
        ok, why = validate_proposal(p)
        self.assertFalse(ok)

    def test_bad_slug_rejected(self):
        from brain.strategy_generator import validate_proposal
        p = self._good()
        p["name_slug"] = "Has Spaces & Caps"
        ok, why = validate_proposal(p)
        self.assertFalse(ok)

    def test_weight_out_of_range_rejected(self):
        from brain.strategy_generator import validate_proposal
        p = self._good()
        p["conditions"][0]["weight"] = 100.0
        ok, why = validate_proposal(p)
        self.assertFalse(ok)
        self.assertIn("weight", why)

    def test_empty_conditions_rejected(self):
        from brain.strategy_generator import validate_proposal
        p = self._good()
        p["conditions"] = []
        ok, why = validate_proposal(p)
        self.assertFalse(ok)


# ── Persistence ───────────────────────────────────────────────────────────

class PersistProposalTests(TestCase):
    def _good(self):
        return {
            "name_slug": "test_persist",
            "rationale_md": "demo",
            "inspiration": "top_rule:X + regime:trending",
            "direction": "bullish",
            "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma", "ma_period": 20},
                              "weight": 1.0}],
            "min_match_score": 0.6,
            "suggested_horizon_days": 5,
            "sizing": {"stop_pct": 2.0, "target_rr": 2.5},
            "confidence": 0.6,
        }

    def test_creates_inactive_setup_research_rule_and_hypothesis(self):
        from brain.strategy_generator import _persist_proposal, _final_setup_name
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl
        from brain.knowledge_models import Hypothesis
        from brain.generator_models import GeneratedSetupProposal

        row = _persist_proposal(self._good(), model="t",
                                 tokens_in=100, tokens_out=20, cost_usd=0.01)
        self.assertIsNotNone(row)

        # Setup created at is_active=False with prefixed name.
        expected_name = _final_setup_name("test_persist")
        setup = OpportunitySetup.objects.get(name=expected_name)
        self.assertFalse(setup.is_active)

        # RuleControl at research stage.
        rule = RuleControl.objects.get(rule_name=expected_name)
        self.assertEqual(rule.promotion_stage, "research")
        self.assertEqual(rule.parameters.get("auto_generated"), True)

        # Hypothesis posted with rule_avg_r resolution criteria.
        hyp = Hypothesis.objects.filter(source_agent="strategy_generator").first()
        self.assertIsNotNone(hyp)
        self.assertEqual(hyp.resolution_criteria.get("kind"), "rule_avg_r")
        self.assertEqual(hyp.resolution_criteria.get("rule_name"), expected_name)

        # GeneratedSetupProposal links them all.
        self.assertEqual(row.setup_id, setup.id)
        self.assertEqual(row.rule_control_id, rule.id)
        self.assertEqual(row.hypothesis_id, hyp.id)
        self.assertEqual(row.status, GeneratedSetupProposal.STATUS_PENDING)

    def test_invalid_proposal_returns_none(self):
        from brain.strategy_generator import _persist_proposal
        bad = self._good()
        bad["direction"] = "wibble"
        row = _persist_proposal(bad, model="t",
                                 tokens_in=0, tokens_out=0, cost_usd=0.0)
        self.assertIsNone(row)

    def test_name_collision_returns_none(self):
        from brain.strategy_generator import _persist_proposal, _final_setup_name
        from signals.models_opportunity import OpportunitySetup
        # Pre-create a setup with the exact name we'd generate today.
        OpportunitySetup.objects.create(
            name=_final_setup_name("test_persist"),
            description="pre-existing",
            direction="bullish",
            asset_classes=["stock"],
            conditions=[],
            min_match_score=0.6,
            suggested_horizon_days=5,
            sizing={},
        )
        # Persisting with the same slug today should return None.
        row = _persist_proposal(self._good(), model="t",
                                 tokens_in=0, tokens_out=0, cost_usd=0.0)
        self.assertIsNone(row)


# ── Top-level generate_strategies_now ─────────────────────────────────────

class GenerateStrategiesNowTests(TestCase):
    def test_happy_path_persists_valid_only(self):
        from brain.strategy_generator import generate_strategies_now
        from brain.generator_models import GeneratedSetupProposal

        parsed = {
            "proposals": [
                # Valid
                {"name_slug": "valid_a", "rationale_md": "x",
                 "inspiration": "y", "direction": "bullish",
                 "asset_classes": ["stock"],
                 "conditions": [{"kind": "price_pattern",
                                  "params": {"pattern": "above_ma"},
                                  "weight": 1.0}],
                 "min_match_score": 0.6, "suggested_horizon_days": 5,
                 "confidence": 0.6},
                # Invalid (unknown evaluator) — should be filtered out
                {"name_slug": "bad_a", "rationale_md": "x",
                 "direction": "bullish", "asset_classes": ["stock"],
                 "conditions": [{"kind": "fake_evaluator", "weight": 1.0}],
                 "min_match_score": 0.6, "suggested_horizon_days": 5},
            ]
        }
        with _stub_generator_provider(parsed):
            r = generate_strategies_now(max_proposals=3)
        self.assertTrue(r["ok"])
        self.assertEqual(r["n_persisted"], 1)
        self.assertEqual(r["n_validation_rejected"], 1)
        self.assertEqual(GeneratedSetupProposal.objects.count(), 1)

    def test_error_path_returns_ok_false(self):
        from brain.strategy_generator import generate_strategies_now
        def bad_init(self, *a, **kw):
            self.agent_name = "strategy_generator"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("api down"))
        with patch("brain.strategy_generator.StrategyGeneratorAgent.__init__", bad_init):
            r = generate_strategies_now()
        self.assertFalse(r["ok"])
        self.assertEqual(r["n_persisted"], 0)

    def test_max_proposals_caps(self):
        from brain.strategy_generator import generate_strategies_now
        from brain.generator_models import GeneratedSetupProposal

        proposals = []
        for i in range(6):
            proposals.append({
                "name_slug": f"valid_{i}", "rationale_md": "x",
                "direction": "bullish", "asset_classes": ["stock"],
                "conditions": [{"kind": "price_pattern",
                                 "params": {"pattern": "above_ma"},
                                 "weight": 1.0}],
                "min_match_score": 0.6, "suggested_horizon_days": 5,
            })
        with _stub_generator_provider({"proposals": proposals}):
            generate_strategies_now(max_proposals=2)
        self.assertEqual(GeneratedSetupProposal.objects.count(), 2)


# ── Approve / Reject / Expire ─────────────────────────────────────────────

class ApproveRejectExpireTests(TestCase):
    def _create_pending(self):
        from brain.strategy_generator import _persist_proposal
        return _persist_proposal({
            "name_slug": "ar_test", "rationale_md": "x",
            "direction": "bullish", "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma"},
                              "weight": 1.0}],
            "min_match_score": 0.6, "suggested_horizon_days": 5,
            "confidence": 0.5,
        }, model="t", tokens_in=0, tokens_out=0, cost_usd=0.0)

    def test_approve_activates_setup(self):
        from brain.strategy_generator import approve_proposal
        proposal = self._create_pending()
        ok = approve_proposal(proposal, reviewed_by="me", notes="lgtm")
        self.assertTrue(ok)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "approved")
        self.assertEqual(proposal.reviewed_by, "me")
        proposal.setup.refresh_from_db()
        self.assertTrue(proposal.setup.is_active)

    def test_reject_does_not_activate(self):
        from brain.strategy_generator import reject_proposal
        proposal = self._create_pending()
        ok = reject_proposal(proposal, reviewed_by="me", notes="meh")
        self.assertTrue(ok)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "rejected")
        proposal.setup.refresh_from_db()
        self.assertFalse(proposal.setup.is_active)

    def test_double_approve_no_op(self):
        from brain.strategy_generator import approve_proposal
        proposal = self._create_pending()
        approve_proposal(proposal, reviewed_by="a")
        ok = approve_proposal(proposal, reviewed_by="b")
        self.assertFalse(ok)

    def test_expire_old_proposals(self):
        from brain.strategy_generator import expire_old_proposals
        from brain.generator_models import GeneratedSetupProposal
        proposal = self._create_pending()
        # Force created_at backwards.
        old_time = timezone.now() - timedelta(days=20)
        GeneratedSetupProposal.objects.filter(id=proposal.id).update(
            created_at=old_time)
        n = expire_old_proposals(days=14)
        self.assertEqual(n, 1)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "expired")


# ── Dashboard + admin actions ─────────────────────────────────────────────

class GeneratedDashboardTests(TestCase):
    def test_renders_empty(self):
        u = User.objects.create_user(username="g_view", password="x")
        self.client.force_login(u)
        r = self.client.get("/generated/")
        self.assertEqual(r.status_code, 200)


class GeneratedAdminTests(TestCase):
    def _create_pending(self):
        from brain.strategy_generator import _persist_proposal
        return _persist_proposal({
            "name_slug": "adm_test", "rationale_md": "x",
            "direction": "bullish", "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma"},
                              "weight": 1.0}],
            "min_match_score": 0.6, "suggested_horizon_days": 5,
        }, model="t", tokens_in=0, tokens_out=0, cost_usd=0.0)

    def test_admin_can_approve(self):
        u = _staff()
        self.client.force_login(u)
        proposal = self._create_pending()
        r = self.client.post(f"/generated/{proposal.id}/approve/",
                              {"notes": "ship it"})
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "approved")

    def test_admin_can_reject(self):
        u = _staff()
        self.client.force_login(u)
        proposal = self._create_pending()
        r = self.client.post(f"/generated/{proposal.id}/reject/")
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "rejected")

    def test_non_staff_blocked_from_approve(self):
        u = User.objects.create_user(username="not_staff_g", password="x")
        self.client.force_login(u)
        proposal = self._create_pending()
        r = self.client.post(f"/generated/{proposal.id}/approve/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "pending")  # still pending
