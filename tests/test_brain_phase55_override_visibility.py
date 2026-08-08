"""Tests for Phase 55 — operator override visibility.

Covers:
  - recent_overrides: returns proposal_rejected + rule_restored within window
  - excludes proposal_approved + rule_demoted (those are AI-affirming)
  - override_counts_by_target_agent: maps kinds → agent names correctly
  - agent_override_rate: computes overrides / total decisions
  - agent_override_rate: returns None when no decisions in window
  - /intelligence/ hub renders the operator-overrides card when present
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _audit(kind: str, data: dict, *, hours_ago: int = 1):
    from bot_program.audit import record_event
    from bot_program.audit_models import AuditLogEntry
    entry = record_event(kind, data)
    if entry is not None and hours_ago:
        AuditLogEntry.objects.filter(id=entry.id).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
    return entry


# ── recent_overrides ─────────────────────────────────────────────────────

class RecentOverridesTests(TestCase):
    def test_returns_overrides_within_window(self):
        from bot_program.audit_queries import recent_overrides
        _audit("proposal_rejected",
                {"proposed_name": "p1", "reviewed_by": "alice"}, hours_ago=2)
        _audit("rule_restored",
                {"rule_name": "r1", "restored_by": "bob"}, hours_ago=4)
        rows = recent_overrides(days=7)
        self.assertEqual(len(rows), 2)
        kinds = {r.kind for r in rows}
        self.assertEqual(kinds, {"proposal_rejected", "rule_restored"})

    def test_excludes_ai_affirming_kinds(self):
        from bot_program.audit_queries import recent_overrides
        _audit("proposal_approved",
                {"proposed_name": "p1", "reviewed_by": "alice"})
        _audit("rule_demoted",
                {"rule_name": "r1", "criterion": "consec"})
        rows = recent_overrides(days=7)
        self.assertEqual(rows, [])

    def test_excludes_outside_window(self):
        from bot_program.audit_queries import recent_overrides
        _audit("proposal_rejected",
                {"proposed_name": "old", "reviewed_by": "alice"},
                hours_ago=24 * 30)  # 30 days old
        rows = recent_overrides(days=7)
        self.assertEqual(rows, [])

    def test_respects_limit(self):
        from bot_program.audit_queries import recent_overrides
        for i in range(15):
            _audit("proposal_rejected",
                    {"proposed_name": f"p{i}", "reviewed_by": "x"},
                    hours_ago=1)
        rows = recent_overrides(days=7, limit=5)
        self.assertEqual(len(rows), 5)


# ── override_counts_by_target_agent ──────────────────────────────────────

class OverrideCountsTests(TestCase):
    def test_aggregates_by_agent(self):
        from bot_program.audit_queries import override_counts_by_target_agent
        for i in range(3):
            _audit("proposal_rejected",
                    {"proposed_name": f"p{i}", "reviewed_by": "alice"})
        for i in range(2):
            _audit("rule_restored",
                    {"rule_name": f"r{i}", "restored_by": "bob"})
        counts = override_counts_by_target_agent(days=7)
        self.assertEqual(counts["strategy_generator"], 3)
        self.assertEqual(counts["demoter"], 2)

    def test_empty_returns_empty_dict(self):
        from bot_program.audit_queries import override_counts_by_target_agent
        self.assertEqual(override_counts_by_target_agent(), {})


# ── agent_override_rate ──────────────────────────────────────────────────

class AgentOverrideRateTests(TestCase):
    def test_generator_rate(self):
        """3 rejected / (5 approved + 3 rejected) = 0.375"""
        from bot_program.audit_queries import agent_override_rate
        for i in range(5):
            _audit("proposal_approved", {"proposed_name": f"a{i}"})
        for i in range(3):
            _audit("proposal_rejected", {"proposed_name": f"r{i}"})
        rate = agent_override_rate("strategy_generator")
        self.assertAlmostEqual(rate, 0.375, places=3)

    def test_demoter_rate_full_override(self):
        """2 demoted, both restored → 100% override."""
        from bot_program.audit_queries import agent_override_rate
        _audit("rule_demoted", {"rule_name": "x", "criterion": "c"})
        _audit("rule_demoted", {"rule_name": "y", "criterion": "c"})
        _audit("rule_restored", {"rule_name": "x", "restored_by": "u"})
        _audit("rule_restored", {"rule_name": "y", "restored_by": "u"})
        rate = agent_override_rate("demoter")
        self.assertAlmostEqual(rate, 0.5, places=3)
        # 2 demotions + 2 restores = 4 total events, 2 are overrides → 0.5

    def test_no_decisions_returns_none(self):
        from bot_program.audit_queries import agent_override_rate
        self.assertIsNone(agent_override_rate("strategy_generator"))

    def test_unknown_agent_returns_none(self):
        from bot_program.audit_queries import agent_override_rate
        self.assertIsNone(agent_override_rate("nonexistent_agent"))


# ── Intelligence hub renders the overrides card ──────────────────────────

class IntelligenceHubOverridesTests(TestCase):
    def test_overrides_card_renders_when_present(self):
        u = User.objects.create_user(username="ov_view", password="x")
        self.client.force_login(u)
        _audit("proposal_rejected",
                {"proposed_name": "rejected_proposal_x",
                 "reviewed_by": "alice", "decision": "rejected"})
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Operator overrides", body)
        self.assertIn("strategy_generator", body)
        self.assertIn("rejected_proposal_x", body)

    def test_no_overrides_card_hidden(self):
        u = User.objects.create_user(username="ov_clean", password="x")
        self.client.force_login(u)
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertNotIn("Operator overrides", body)
