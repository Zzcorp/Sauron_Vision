"""Tests for Phase 59 — research chat action layer.

Covers:
  - render_markers: each kind → correct link path; unknown kinds left verbatim;
    long values truncated; mixed inline-with-prose preserved
  - extract_strategy_draft: parses fenced ```strategy-draft block; returns
    None when missing; None on bad JSON; case-insensitive fence
  - has_strategy_draft: cheap pre-check
  - research_save_as_draft view: persists valid draft via Phase-41 path;
    rejects invalid (unknown evaluator); not-yours / not-found gives error;
    cross-user isolation (can't save someone else's message)
  - System prompt mentions both markers + strategy-draft block format
"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="r59_u"):
    return User.objects.create_user(username=name, password="x")


def _conv_with_message(user, content: str, role: str = "assistant"):
    """Helper — build an active conversation with one message."""
    from brain.research_models import ResearchConversation, ResearchMessage
    conv = ResearchConversation.objects.create(user=user, is_active=True)
    msg = ResearchMessage.objects.create(
        conversation=conv, role=role, content=content,
    )
    return conv, msg


# ── render_markers ───────────────────────────────────────────────────────

class RenderMarkersTests(TestCase):
    def test_rule_marker_becomes_link(self):
        from brain.research_renderer import render_markers
        out = render_markers("See <<RULE:starter_stock_momentum>> for context.")
        self.assertIn("[rule starter_stock_momentum →](/generated/)", out)

    def test_hyp_marker_becomes_link(self):
        from brain.research_renderer import render_markers
        out = render_markers("That bet (<<HYP:42>>) refuted yesterday.")
        self.assertIn("[hypothesis #42 →](/hypotheses/)", out)

    def test_audit_marker_becomes_link(self):
        from brain.research_renderer import render_markers
        out = render_markers("AAPL was soft-blocked at <<AUDIT:1234>>.")
        self.assertIn("[audit #1234 →](/audit/)", out)

    def test_report_marker_becomes_link(self):
        from brain.research_renderer import render_markers
        out = render_markers("Per <<REPORT:17>>, regime is risk_off.")
        self.assertIn("[BrainReport #17 →](/brain/)", out)

    def test_briefing_earnings_knowledge_markers(self):
        from brain.research_renderer import render_markers
        out = render_markers(
            "<<BRIEFING:9>> · <<EARNINGS:5>> · <<KNOWLEDGE:regime:portfolio>>")
        self.assertIn("/briefing/", out)
        self.assertIn("/earnings-reviews/", out)
        self.assertIn("/knowledge/", out)

    def test_unknown_marker_kept_verbatim(self):
        """Forward-compat: an agent emitting <<FUTURE:x>> won't break the UI."""
        from brain.research_renderer import render_markers
        out = render_markers("This <<FUTURE:something>> stays as-is.")
        self.assertIn("<<FUTURE:something>>", out)

    def test_long_value_truncated(self):
        from brain.research_renderer import render_markers
        long_name = "a" * 60
        out = render_markers(f"<<RULE:{long_name}>>")
        # Long value truncated with ellipsis to keep link tidy.
        self.assertIn("…", out)

    def test_mixed_with_prose_preserved(self):
        from brain.research_renderer import render_markers
        text = "USD weakening per <<REPORT:5>>. Watch <<RULE:usd_long>>."
        out = render_markers(text)
        self.assertIn("USD weakening per", out)
        self.assertIn("Watch", out)
        self.assertIn("/brain/", out)
        self.assertIn("/generated/", out)

    def test_empty_string_returns_empty(self):
        from brain.research_renderer import render_markers
        self.assertEqual(render_markers(""), "")
        self.assertEqual(render_markers(None), "")


# ── extract_strategy_draft ───────────────────────────────────────────────

class ExtractStrategyDraftTests(TestCase):
    def _msg_with_draft(self, payload_dict):
        import json
        return (
            "Here's the proposal:\n\n"
            "```strategy-draft\n"
            f"{json.dumps(payload_dict)}\n"
            "```"
        )

    def test_extracts_valid_draft(self):
        from brain.research_renderer import extract_strategy_draft
        msg = self._msg_with_draft({
            "name_slug": "test_one", "direction": "bullish",
        })
        d = extract_strategy_draft(msg)
        self.assertIsNotNone(d)
        self.assertEqual(d["name_slug"], "test_one")

    def test_returns_none_when_missing(self):
        from brain.research_renderer import extract_strategy_draft
        self.assertIsNone(extract_strategy_draft("no draft here"))

    def test_returns_none_on_bad_json(self):
        from brain.research_renderer import extract_strategy_draft
        msg = "```strategy-draft\nthis is not json\n```"
        self.assertIsNone(extract_strategy_draft(msg))

    def test_case_insensitive_fence(self):
        from brain.research_renderer import extract_strategy_draft
        msg = '```Strategy-DRAFT\n{"name_slug": "case"}\n```'
        d = extract_strategy_draft(msg)
        self.assertEqual(d["name_slug"], "case")

    def test_has_strategy_draft_pre_check(self):
        from brain.research_renderer import has_strategy_draft
        self.assertFalse(has_strategy_draft("plain text"))
        self.assertTrue(has_strategy_draft(
            '```strategy-draft\n{"x": 1}\n```'))


# ── research_save_as_draft view ──────────────────────────────────────────

class SaveAsDraftViewTests(TestCase):
    def _draft_msg_content(self, name_slug="from_chat"):
        import json
        payload = {
            "name_slug": name_slug,
            "rationale_md": "x",
            "direction": "bullish",
            "asset_classes": ["stock"],
            "conditions": [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma"},
                              "weight": 1.0}],
            "min_match_score": 0.6,
            "suggested_horizon_days": 5,
            "confidence": 0.6,
        }
        return (
            "Here's a strategy idea worth testing:\n\n"
            f"```strategy-draft\n{json.dumps(payload)}\n```"
        )

    def test_valid_draft_persisted_via_phase41_path(self):
        from brain.generator_models import GeneratedSetupProposal
        u = _user()
        self.client.force_login(u)
        _conv, msg = _conv_with_message(u, self._draft_msg_content())
        r = self.client.post(f"/research/save-draft/{msg.id}/")
        self.assertEqual(r.status_code, 302)
        # Proposal landed at is_active=False with research:<username> source.
        proposal = GeneratedSetupProposal.objects.first()
        self.assertIsNotNone(proposal)
        self.assertIn("from_chat", proposal.proposed_name)
        self.assertEqual(proposal.status, "pending")
        self.assertFalse(proposal.setup.is_active)
        # Audit record uses research:<username> as model.
        self.assertEqual(proposal.model_used, f"research:{u.username}")

    def test_invalid_evaluator_kind_rejected(self):
        from brain.generator_models import GeneratedSetupProposal
        import json
        u = _user()
        self.client.force_login(u)
        bad_payload = {
            "name_slug": "bad_one", "rationale_md": "x",
            "direction": "bullish", "asset_classes": ["stock"],
            "conditions": [{"kind": "totally_made_up_kind",
                              "params": {}, "weight": 1.0}],
            "min_match_score": 0.6, "suggested_horizon_days": 5,
        }
        content = (f"draft:\n```strategy-draft\n{json.dumps(bad_payload)}\n```")
        _conv, msg = _conv_with_message(u, content)
        self.client.post(f"/research/save-draft/{msg.id}/")
        # Validation fails — no proposal persisted.
        self.assertEqual(GeneratedSetupProposal.objects.count(), 0)

    def test_message_without_draft_block_errors_cleanly(self):
        from brain.generator_models import GeneratedSetupProposal
        u = _user()
        self.client.force_login(u)
        _conv, msg = _conv_with_message(u, "no draft in this one")
        r = self.client.post(f"/research/save-draft/{msg.id}/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(GeneratedSetupProposal.objects.count(), 0)

    def test_cross_user_isolation(self):
        """User B cannot save User A's message as a draft."""
        from brain.generator_models import GeneratedSetupProposal
        a = _user("alice_r59")
        b = _user("bob_r59")
        _conv, msg = _conv_with_message(a, self._draft_msg_content())
        self.client.force_login(b)
        r = self.client.post(f"/research/save-draft/{msg.id}/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(GeneratedSetupProposal.objects.count(), 0)

    def test_user_message_role_rejected(self):
        """Only assistant messages can produce drafts (user role rejected)."""
        from brain.generator_models import GeneratedSetupProposal
        u = _user()
        self.client.force_login(u)
        _conv, msg = _conv_with_message(
            u, self._draft_msg_content(), role="user")
        self.client.post(f"/research/save-draft/{msg.id}/")
        self.assertEqual(GeneratedSetupProposal.objects.count(), 0)


# ── System prompt covers Phase 59 conventions ────────────────────────────

class SystemPromptTests(TestCase):
    def test_prompt_mentions_markers_and_drafts(self):
        from brain.research_agent import ResearchAgent
        def patched_init(self, *a, **kw):
            self.agent_name = "research"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
        with patch.object(ResearchAgent, "__init__", patched_init):
            prompt = ResearchAgent().get_system_prompt()
        # Markers documented.
        self.assertIn("<<RULE:", prompt)
        self.assertIn("<<HYP:", prompt)
        self.assertIn("<<AUDIT:", prompt)
        # Strategy-draft block documented.
        self.assertIn("strategy-draft", prompt)
        self.assertIn("name_slug", prompt)
        # Read-only stance preserved.
        self.assertIn("cannot take actions", prompt)


# ── /research/ view exposes draft button + rendered markers ──────────────

class ResearchViewIntegrationTests(TestCase):
    def test_view_renders_marker_links(self):
        u = _user()
        self.client.force_login(u)
        _conv_with_message(u, "Per <<REPORT:7>>, regime is trending.")
        r = self.client.get("/research/")
        body = r.content.decode("utf-8", errors="ignore")
        # Marker rendered as link, not raw.
        self.assertIn("/brain/", body)
        self.assertNotIn("&lt;&lt;REPORT", body)

    def test_view_shows_save_as_draft_button_when_block_present(self):
        u = _user()
        self.client.force_login(u)
        import json
        payload = {"name_slug": "btn_test", "direction": "bullish"}
        _conv_with_message(
            u, f"```strategy-draft\n{json.dumps(payload)}\n```")
        r = self.client.get("/research/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Save as draft", body)
        self.assertIn("research/save-draft/", body)

    def test_no_button_when_no_draft(self):
        u = _user()
        self.client.force_login(u)
        _conv_with_message(u, "just a plain answer")
        r = self.client.get("/research/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertNotIn("Save as draft", body)
