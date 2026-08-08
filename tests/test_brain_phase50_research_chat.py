"""Tests for Phase 50 — /research/ conversational tab.

Covers:
  - get_or_create_active_conversation: idempotent, one active per user
  - archive_active_conversation: flips is_active=False
  - _conversation_history_for_prompt: oldest-first, capped at MAX_HISTORY
  - _build_research_snapshot: shape (empty DB returns expected keys)
  - ask(): persists user message; on success persists assistant message;
    on failure persists error-stamped assistant message
  - ask(): empty question rejected
  - ask(): auto-titles conversation from first message
  - /research/ renders 200; new conversation form works
  - /research/ask/ POST creates messages + redirects
  - Login required
  - Conversations are scoped per user (cannot see others')
"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="research_u"):
    return User.objects.create_user(username=name, password="x")


def _stub_provider(answer_text):
    """Build a context manager that stubs the Research agent's provider."""
    usage = {"input_tokens": 4500, "output_tokens": 700, "cost_usd": 0.18}

    def patched_init(self, *a, **kw):
        self.agent_name = "research"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(answer_text, usage))
    return patch("brain.research_agent.ResearchAgent.__init__", patched_init)


# ── Conversation lifecycle ────────────────────────────────────────────────

class ConversationLifecycleTests(TestCase):
    def test_get_or_create_idempotent(self):
        from brain.research_agent import get_or_create_active_conversation
        u = _user()
        c1 = get_or_create_active_conversation(u)
        c2 = get_or_create_active_conversation(u)
        self.assertEqual(c1.id, c2.id)

    def test_archive_then_create_new(self):
        from brain.research_agent import (
            get_or_create_active_conversation, archive_active_conversation,
        )
        u = _user()
        c1 = get_or_create_active_conversation(u)
        archive_active_conversation(u)
        c1.refresh_from_db()
        self.assertFalse(c1.is_active)
        c2 = get_or_create_active_conversation(u)
        self.assertNotEqual(c1.id, c2.id)
        self.assertTrue(c2.is_active)


# ── ask() ────────────────────────────────────────────────────────────────

class AskTests(TestCase):
    def test_happy_path_persists_both_messages(self):
        from brain.research_agent import (
            get_or_create_active_conversation, ask,
        )
        from brain.research_models import ResearchMessage
        u = _user()
        conv = get_or_create_active_conversation(u)
        with _stub_provider(
                "USD has been weakening per the latest brain regime."):
            r = ask(conv, "What's your read on USD?")
        self.assertTrue(r["ok"])
        self.assertEqual(ResearchMessage.objects.count(), 2)
        last = ResearchMessage.objects.order_by("-created_at").first()
        self.assertEqual(last.role, "assistant")
        self.assertIn("USD has been weakening", last.content)

    def test_first_message_auto_titles(self):
        from brain.research_agent import (
            get_or_create_active_conversation, ask,
        )
        u = _user()
        conv = get_or_create_active_conversation(u)
        self.assertEqual(conv.title, "")
        with _stub_provider("ok."):
            ask(conv, "Why is starter_stock_momentum on watch?")
        conv.refresh_from_db()
        self.assertIn("starter_stock_momentum", conv.title)

    def test_provider_failure_persists_error_stamp(self):
        from brain.research_agent import (
            get_or_create_active_conversation, ask,
        )
        from brain.research_models import ResearchMessage
        u = _user()
        conv = get_or_create_active_conversation(u)

        def bad_init(self, *a, **kw):
            self.agent_name = "research"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("api 500"))
        with patch("brain.research_agent.ResearchAgent.__init__", bad_init):
            r = ask(conv, "hi")
        self.assertFalse(r["ok"])
        # Both user message AND error-stamped assistant message persisted.
        self.assertEqual(ResearchMessage.objects.count(), 2)
        asst = ResearchMessage.objects.filter(role="assistant").first()
        self.assertIn("api 500", asst.error)
        self.assertIn("temporarily unavailable", asst.content)

    def test_empty_question_rejected(self):
        from brain.research_agent import (
            get_or_create_active_conversation, ask,
        )
        from brain.research_models import ResearchMessage
        u = _user()
        conv = get_or_create_active_conversation(u)
        r = ask(conv, "   ")
        self.assertFalse(r["ok"])
        self.assertEqual(ResearchMessage.objects.count(), 0)


# ── History compression ──────────────────────────────────────────────────

class ConversationHistoryTests(TestCase):
    def test_history_oldest_first_capped(self):
        from brain.research_agent import (
            get_or_create_active_conversation,
            _conversation_history_for_prompt, MAX_HISTORY_MESSAGES,
        )
        from brain.research_models import ResearchMessage
        u = _user()
        conv = get_or_create_active_conversation(u)
        # Create 12 messages alternating user/assistant.
        for i in range(12):
            ResearchMessage.objects.create(
                conversation=conv,
                role="user" if i % 2 == 0 else "assistant",
                content=f"msg{i}",
            )
        history = _conversation_history_for_prompt(conv)
        self.assertEqual(len(history), MAX_HISTORY_MESSAGES)
        # Oldest first within the window — content of first should be
        # earlier than content of last.
        self.assertEqual(history[0]["content"], "msg4")  # oldest of last 8
        self.assertEqual(history[-1]["content"], "msg11")


# ── Snapshot builder shape ───────────────────────────────────────────────

class SnapshotShapeTests(TestCase):
    def test_empty_db_returns_expected_keys(self):
        from brain.research_agent import _build_research_snapshot
        snap = _build_research_snapshot()
        for key in ("as_of", "recent_brain_reports", "knowledge_graph",
                    "recent_resolved_hypotheses", "pending_hypotheses",
                    "recent_earnings_reviews", "open_demotions"):
            self.assertIn(key, snap)


# ── /research/ views ─────────────────────────────────────────────────────

class ResearchViewsTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_renders_empty_200(self):
        r = self.client.get("/research/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertIn("Ask Sauron", body)
        # Empty state hint visible.
        self.assertIn("regime", body.lower())

    def test_ask_endpoint_creates_messages(self):
        from brain.research_models import ResearchMessage
        with _stub_provider("USD trending lower."):
            r = self.client.post("/research/ask/", {"question": "USD?"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ResearchMessage.objects.filter(
            conversation__user=self.user).count(), 2)

    def test_ask_with_empty_question_no_messages(self):
        from brain.research_models import ResearchMessage
        r = self.client.post("/research/ask/", {"question": "  "})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ResearchMessage.objects.count(), 0)

    def test_new_conversation_archives_old(self):
        from brain.research_agent import get_or_create_active_conversation
        from brain.research_models import ResearchConversation
        c1 = get_or_create_active_conversation(self.user)
        r = self.client.post("/research/new/")
        self.assertEqual(r.status_code, 302)
        c1.refresh_from_db()
        self.assertFalse(c1.is_active)
        # Visiting /research/ creates a new active conversation.
        self.client.get("/research/")
        active = ResearchConversation.objects.filter(
            user=self.user, is_active=True).count()
        self.assertEqual(active, 1)

    def test_login_required(self):
        self.client.logout()
        r = self.client.get("/research/")
        self.assertEqual(r.status_code, 302)


class CrossUserIsolationTests(TestCase):
    def test_user_cannot_see_other_users_conversations(self):
        from brain.research_agent import (
            get_or_create_active_conversation, ask,
        )
        u1 = _user("u1")
        u2 = _user("u2")
        c1 = get_or_create_active_conversation(u1)
        with _stub_provider("answer for u1"):
            ask(c1, "u1 question")

        self.client.force_login(u2)
        r = self.client.get("/research/")
        body = r.content.decode("utf-8")
        # u2 must not see u1's conversation content.
        self.assertNotIn("u1 question", body)
        self.assertNotIn("answer for u1", body)
