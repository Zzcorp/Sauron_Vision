"""Tests for Phase 60 — action markers (staff-only inline buttons).

Covers:
  - extract_action_markers: APPROVE / REJECT / RESTORE recognized; cleaned text
  - dedupe of identical markers in a single message
  - invalid values left in text verbatim (non-int proposal_id, empty rule_name)
  - cleaned_text strips marker without leaving double-spaces
  - non-action markers (RULE/HYP/etc.) NOT extracted (still pass through render_markers)
  - unknown action kinds left verbatim
  - view: staff users see action buttons, non-staff don't
  - view: marker text is removed from displayed body once extracted
  - System prompt mentions action markers + read-only stance
"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="r60_u", *, staff=False):
    u = User.objects.create_user(username=name, password="x")
    if staff:
        u.is_staff = True
        u.save()
    return u


def _conv_with_message(user, content, role="assistant"):
    from brain.research_models import ResearchConversation, ResearchMessage
    conv = ResearchConversation.objects.create(user=user, is_active=True)
    msg = ResearchMessage.objects.create(
        conversation=conv, role=role, content=content,
    )
    return conv, msg


# ── extract_action_markers ───────────────────────────────────────────────

class ExtractActionMarkersTests(TestCase):
    def test_approve_marker_extracted(self):
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers(
            "Approve this one. <<APPROVE:42>>")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["kind"], "approve")
        self.assertEqual(actions[0]["url"], "/generated/42/approve/")
        self.assertIn("#42", actions[0]["label"])
        # Marker stripped from cleaned text.
        self.assertNotIn("<<APPROVE", cleaned)

    def test_reject_marker_extracted(self):
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers("<<REJECT:51>>")
        self.assertEqual(actions[0]["kind"], "reject")
        self.assertEqual(actions[0]["url"], "/generated/51/reject/")
        self.assertEqual(actions[0]["css"], "danger")

    def test_restore_marker_extracted(self):
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers(
            "Consider <<RESTORE:fast_breakout>>")
        self.assertEqual(actions[0]["kind"], "restore")
        self.assertEqual(actions[0]["url"], "/generated/restore/fast_breakout/")

    def test_multiple_distinct_markers(self):
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers(
            "Two suggestions: <<APPROVE:1>> and <<REJECT:2>>")
        self.assertEqual(len(actions), 2)
        kinds = {a["kind"] for a in actions}
        self.assertEqual(kinds, {"approve", "reject"})

    def test_dedupe_identical_markers(self):
        """If the agent emits the same marker twice in one message, the
        button only appears once."""
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers(
            "<<APPROVE:42>> and again <<APPROVE:42>>")
        self.assertEqual(len(actions), 1)

    def test_invalid_proposal_id_left_verbatim(self):
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers(
            "<<APPROVE:not_a_number>>")
        self.assertEqual(actions, [])
        # Bad markers stay so they don't silently disappear.
        self.assertIn("<<APPROVE:not_a_number>>", cleaned)

    def test_empty_value_left_verbatim(self):
        from brain.research_renderer import extract_action_markers
        # Empty value — nothing to act on.
        cleaned, actions = extract_action_markers("text <<RESTORE: >> end")
        self.assertEqual(actions, [])

    def test_link_markers_not_extracted(self):
        """Phase-59 link markers (RULE/HYP/etc.) are NOT touched by the
        action extractor — they stay in the text for render_markers()."""
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers(
            "See <<RULE:foo>> and <<HYP:5>>")
        self.assertEqual(actions, [])
        self.assertIn("<<RULE:foo>>", cleaned)
        self.assertIn("<<HYP:5>>", cleaned)

    def test_empty_text_returns_empty(self):
        from brain.research_renderer import extract_action_markers
        cleaned, actions = extract_action_markers("")
        self.assertEqual(cleaned, "")
        self.assertEqual(actions, [])

    def test_cleaned_text_no_double_spaces(self):
        from brain.research_renderer import extract_action_markers
        cleaned, _ = extract_action_markers(
            "Word <<APPROVE:1>> word2 <<REJECT:2>> end")
        self.assertNotIn("  ", cleaned)


# ── /research/ view: staff sees buttons, non-staff doesn't ──────────────

class ResearchViewActionVisibilityTests(TestCase):
    def test_staff_sees_action_buttons(self):
        u = _user(staff=True)
        self.client.force_login(u)
        _conv_with_message(
            u, "I'd approve this proposal. <<APPROVE:42>>")
        r = self.client.get("/research/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Approve proposal #42", body)
        # Form action points at the existing admin endpoint.
        self.assertIn("/generated/42/approve/", body)
        # Marker text is gone from the visible body.
        self.assertNotIn("<<APPROVE:42>>", body)

    def test_non_staff_does_not_see_buttons(self):
        u = _user(staff=False)
        self.client.force_login(u)
        _conv_with_message(
            u, "I'd approve this proposal. <<APPROVE:42>>")
        r = self.client.get("/research/")
        body = r.content.decode("utf-8", errors="ignore")
        # No button, no form pointing at the admin endpoint.
        self.assertNotIn("/generated/42/approve/", body)
        # And the marker itself is still extracted from the body (no orphan
        # text); just no actions panel rendered.
        self.assertNotIn("<<APPROVE:42>>", body)

    def test_marker_does_not_appear_inline_in_body(self):
        """The action-marker text should not pollute the rendered prose."""
        u = _user(staff=True)
        self.client.force_login(u)
        _conv_with_message(
            u, "Recommendation: approve. <<APPROVE:7>>")
        r = self.client.get("/research/")
        body = r.content.decode("utf-8", errors="ignore")
        # Body shows the prose without the marker text; button shows separately.
        self.assertIn("Recommendation: approve.", body)
        self.assertNotIn("<<APPROVE:7>>", body)
        self.assertIn("Suggested actions", body)


# ── System prompt covers action markers ─────────────────────────────────

class SystemPromptCoversActionMarkersTests(TestCase):
    def test_prompt_documents_action_kinds(self):
        from brain.research_agent import ResearchAgent
        def patched_init(self, *a, **kw):
            self.agent_name = "research"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
        with patch.object(ResearchAgent, "__init__", patched_init):
            prompt = ResearchAgent().get_system_prompt()
        self.assertIn("<<APPROVE:", prompt)
        self.assertIn("<<REJECT:", prompt)
        self.assertIn("<<RESTORE:", prompt)
        # Read-only stance preserved.
        self.assertIn("agent never acts", prompt.lower())
