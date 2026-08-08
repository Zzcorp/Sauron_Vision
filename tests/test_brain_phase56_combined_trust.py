"""Tests for Phase 56 — combined trust score (Brier + operator override).

Covers:
  - both signals present → weighted average
  - only Brier → returns Brier
  - only override → returns 1 - override_rate
  - neither → None
  - weight knobs respected
  - clamps to [0, 1]
  - leaderboard view exposes both columns
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _resolve_hypothesis(*, agent: str, confidence: float,
                          confirmed: bool, hours_ago: int = 1):
    """Create a resolved Hypothesis row directly to drive Brier."""
    from brain.knowledge_models import Hypothesis
    h = Hypothesis.objects.create(
        claim_text="x", source_agent=agent, confidence=confidence,
        outcome=(Hypothesis.OUTCOME_CONFIRMED if confirmed
                  else Hypothesis.OUTCOME_REFUTED),
        resolved_at=timezone.now() - timedelta(hours=hours_ago),
    )
    return h


def _audit(kind: str, data: dict, *, hours_ago: int = 1):
    """Append an audit-chain entry, optionally backdated."""
    from bot_program.audit import record_event
    from bot_program.audit_models import AuditLogEntry
    entry = record_event(kind, data)
    if entry is not None and hours_ago:
        AuditLogEntry.objects.filter(id=entry.id).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
    return entry


# ── agent_combined_trust ─────────────────────────────────────────────────

class CombinedTrustTests(TestCase):
    def test_neither_signal_returns_none(self):
        from brain.hypotheses import agent_combined_trust
        self.assertIsNone(agent_combined_trust("nobody"))

    def test_only_brier_returns_brier(self):
        from brain.hypotheses import agent_combined_trust, agent_trust_score
        # Confidence 1.0 + confirmed → Brier 0.0 → trust 1.0
        for _ in range(5):
            _resolve_hypothesis(
                agent="brier_only", confidence=1.0, confirmed=True)
        brier = agent_trust_score("brier_only")
        combined = agent_combined_trust("brier_only")
        self.assertEqual(combined, brier)

    def test_only_override_returns_one_minus_rate(self):
        """No hypothesis history but 4/10 admin actions = override → 0.6 trust."""
        from brain.hypotheses import agent_combined_trust
        for _ in range(6):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(4):
            _audit("proposal_rejected", {"proposed_name": "n"})
        # rate = 4/10 = 0.4 → trust = 0.6
        combined = agent_combined_trust("strategy_generator")
        self.assertAlmostEqual(combined, 0.6, places=2)

    def test_blends_both_signals_with_default_weights(self):
        """Brier 1.0 + override rate 0.5 → 0.7*1.0 + 0.3*0.5 = 0.85"""
        from brain.hypotheses import agent_combined_trust
        for _ in range(5):
            _resolve_hypothesis(
                agent="strategy_generator", confidence=1.0, confirmed=True)
        for _ in range(5):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(5):
            _audit("proposal_rejected", {"proposed_name": "n"})
        # Brier=1.0, override_rate=0.5 → operator_trust=0.5
        # blended = 0.7*1.0 + 0.3*0.5 = 0.85
        combined = agent_combined_trust("strategy_generator")
        self.assertAlmostEqual(combined, 0.85, places=2)

    def test_custom_weights_respected(self):
        """Equal weights → straight average."""
        from brain.hypotheses import agent_combined_trust
        for _ in range(5):
            _resolve_hypothesis(
                agent="strategy_generator", confidence=1.0, confirmed=True)
        for _ in range(5):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(5):
            _audit("proposal_rejected", {"proposed_name": "n"})
        # brier=1.0, op_trust=0.5 → 50/50 = 0.75
        combined = agent_combined_trust(
            "strategy_generator",
            brier_weight=0.5, override_weight=0.5)
        self.assertAlmostEqual(combined, 0.75, places=2)

    def test_zero_brier_high_override_pulls_down(self):
        """Bad Brier + high override rate → very low combined trust."""
        from brain.hypotheses import agent_combined_trust
        # Confidence 1.0 + refuted → max-bad Brier
        for _ in range(5):
            _resolve_hypothesis(
                agent="strategy_generator", confidence=1.0, confirmed=False)
        # All rejected
        for _ in range(5):
            _audit("proposal_rejected", {"proposed_name": "n"})
        # Brier ~0.0 (clamped), op_rate 1.0 → op_trust 0.0
        # Blended = 0.7*0.0 + 0.3*0.0 = 0.0
        combined = agent_combined_trust("strategy_generator")
        self.assertAlmostEqual(combined, 0.0, places=2)

    def test_clamps_to_unit_interval(self):
        from brain.hypotheses import agent_combined_trust
        # Even with weird inputs, result must be in [0, 1].
        for _ in range(5):
            _resolve_hypothesis(
                agent="strategy_generator", confidence=1.0, confirmed=True)
        for _ in range(5):
            _audit("proposal_approved", {"proposed_name": "y"})
        # No rejections — override rate 0.0 → op_trust 1.0
        combined = agent_combined_trust("strategy_generator")
        self.assertGreaterEqual(combined, 0.0)
        self.assertLessEqual(combined, 1.0)


# ── Leaderboard view exposes both columns ────────────────────────────────

class HypothesesLeaderboardTests(TestCase):
    def test_leaderboard_shows_combined_and_brier(self):
        u = User.objects.create_user(username="lb_view", password="x")
        self.client.force_login(u)
        for _ in range(5):
            _resolve_hypothesis(
                agent="strategy_generator", confidence=1.0, confirmed=True)
        for _ in range(8):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(2):
            _audit("proposal_rejected", {"proposed_name": "n"})
        r = self.client.get("/hypotheses/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("combined", body.lower())
        self.assertIn("brier-only", body.lower())
        self.assertIn("strategy_generator", body)
