"""Tests for Phase 58 — audit context in /research/ snapshot.

Covers:
  - _build_research_snapshot includes recent_audit_decisions key
  - Snapshot includes the 7 decision audit kinds within 14d window
  - Trade events (trade_open / trade_close) are NOT included (high-volume noise)
  - Old audit entries (>14d) excluded
  - Capped at 25 most recent
  - System prompt mentions recent_audit_decisions
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone


def _audit(kind: str, data: dict, *, hours_ago: int = 1):
    """Backdate the row's created_at to put it inside / outside the window."""
    from bot_program.audit import record_event
    from bot_program.audit_models import AuditLogEntry
    entry = record_event(kind, data)
    if entry is not None and hours_ago:
        AuditLogEntry.objects.filter(id=entry.id).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
    return entry


# ── Snapshot includes audit context ──────────────────────────────────────

class SnapshotIncludesAuditTests(TestCase):
    def test_recent_audit_decisions_key_present(self):
        from brain.research_agent import _build_research_snapshot
        snap = _build_research_snapshot()
        self.assertIn("recent_audit_decisions", snap)

    def test_includes_all_7_decision_kinds(self):
        from brain.research_agent import _build_research_snapshot
        # One row of each decision kind.
        for kind in ("gate_reject", "brain_soft_block",
                     "proposal_approved", "proposal_rejected",
                     "rule_demoted", "rule_restored",
                     "hypothesis_resolved"):
            _audit(kind, {"k": kind})
        snap = _build_research_snapshot()
        kinds = {a["kind"] for a in snap["recent_audit_decisions"]}
        self.assertEqual(kinds, {
            "gate_reject", "brain_soft_block",
            "proposal_approved", "proposal_rejected",
            "rule_demoted", "rule_restored",
            "hypothesis_resolved",
        })

    def test_excludes_trade_open_close(self):
        """High-volume trade events shouldn't pollute the research snapshot —
        the agent answers WHY questions, not 'list every fill'."""
        from brain.research_agent import _build_research_snapshot
        _audit("trade_open", {"symbol": "X"})
        _audit("trade_close", {"symbol": "X"})
        _audit("gate_reject", {"reason": "theme_cap"})
        snap = _build_research_snapshot()
        kinds = {a["kind"] for a in snap["recent_audit_decisions"]}
        self.assertEqual(kinds, {"gate_reject"})
        self.assertNotIn("trade_open", kinds)
        self.assertNotIn("trade_close", kinds)

    def test_excludes_old_entries(self):
        from brain.research_agent import _build_research_snapshot
        _audit("gate_reject", {"reason": "old"},
                hours_ago=24 * 30)  # 30 days back
        _audit("gate_reject", {"reason": "fresh"}, hours_ago=2)
        snap = _build_research_snapshot()
        reasons = [a["data"]["reason"]
                    for a in snap["recent_audit_decisions"]]
        self.assertEqual(reasons, ["fresh"])

    def test_capped_at_25(self):
        from brain.research_agent import _build_research_snapshot
        # 30 fresh gate_rejects.
        for i in range(30):
            _audit("gate_reject", {"reason": f"r{i}"})
        snap = _build_research_snapshot()
        self.assertLessEqual(len(snap["recent_audit_decisions"]), 25)

    def test_audit_data_field_serialized(self):
        """The agent reads `data` payloads to answer 'why' questions —
        make sure they're present + intact."""
        from brain.research_agent import _build_research_snapshot
        _audit("brain_soft_block", {
            "symbol": "AAPL",
            "rule_name": "momentum_alpha",
            "advisory_source": "brain_report (regime=risk_off)",
        })
        snap = _build_research_snapshot()
        rec = snap["recent_audit_decisions"][0]
        self.assertEqual(rec["kind"], "brain_soft_block")
        self.assertEqual(rec["data"]["symbol"], "AAPL")
        self.assertEqual(rec["data"]["rule_name"], "momentum_alpha")
        self.assertIn("regime=risk_off", rec["data"]["advisory_source"])


# ── System prompt mentions audit context ─────────────────────────────────

class SystemPromptTests(TestCase):
    def test_prompt_mentions_recent_audit_decisions(self):
        from brain.research_agent import ResearchAgent
        from unittest.mock import patch, MagicMock
        # Stub init so we don't hit real provider.
        def patched(self, *a, **kw):
            self.agent_name = "research"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
        with patch.object(ResearchAgent, "__init__", patched):
            agent = ResearchAgent()
            prompt = agent.get_system_prompt()
        self.assertIn("recent_audit_decisions", prompt)
        self.assertIn("immutable audit trail", prompt)
        # Mentions the example phrasing that guides "why" answers.
        self.assertIn("why", prompt.lower())
