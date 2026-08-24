"""The Ask-Sauron session is live — it survives changing page.

The failure this replaces: `research_ask_ajax` called the agent
synchronously inside the request. One LLM turn takes tens of seconds, so
navigating away aborted the fetch and the operator lost an answer that had
already been produced and paid for. Nothing pushed it from the server
either, and the floating panel had no load path at all — so a page change
emptied a conversation that never stopped existing in the database.

What is asserted here:
  - asking returns immediately with a PENDING exchange, no LLM in the request
  - the worker settles that same row in place and announces it on the
    asking user's socket, and only theirs
  - the panel's load path serves a pending question after a page change and
    the same row afterwards carries the answer
  - a dead broker degrades to answering synchronously, as it used to
  - two questions in flight at once never swap answers
  - the daily AI ceiling now covers chat, and its refusal is visible

Run with:  python manage.py test tests.test_live_session
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

XHR = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def _user(name="live_u"):
    return User.objects.create_user(username=name, password="x")


def _echo_provider():
    """Stub provider that answers WITH the question it was handed.

    An answer that quotes its own question is the only way to see a
    crossed pairing: two placeholders filled with plausible text look
    identical until you check which question produced which.
    """
    usage = {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01}

    def patched_init(self, *a, **kw):
        self.agent_name = "research"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()

        def complete(*, system_prompt, user_message, model,
                     agent_name="unattributed", record=True, source_ref=""):
            # The signature mirrors the real provider contract — which now
            # carries the ledger kwargs (agent_name/record/source_ref). A
            # stub frozen on an old shape TypeErrors the ask and reports it
            # as a budget refusal — it has caught two contract steps now.
            q = user_message.split("User's current question:")[-1].strip()
            return ("ANSWER TO: " + q, usage)

        self.provider.complete = complete
    return patch("brain.research_agent.ResearchAgent.__init__", patched_init)


def _never_called_provider():
    """Blows up if the agent is touched — proves a request stayed cheap."""
    def patched_init(self, *a, **kw):
        raise AssertionError("the LLM must not run inside the web request")
    return patch("brain.research_agent.ResearchAgent.__init__", patched_init)


# ── Asking returns immediately ───────────────────────────────────────────

class AsyncAskTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_xhr_ask_returns_a_pending_exchange_without_calling_the_agent(self):
        from brain.tasks import answer_research_question
        from brain.research_models import ResearchMessage

        with patch.object(answer_research_question, "apply_async",
                          return_value=MagicMock(id="t-1")) as enq, \
             _never_called_provider():
            resp = self.client.post("/research/ask-ajax/",
                                    {"question": "What is the regime?"}, **XHR)

        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["pending"])
        enq.assert_called_once()

        pending = ResearchMessage.objects.get(pk=body["pending_message_id"])
        self.assertEqual(pending.role, "assistant")
        self.assertEqual(pending.status, ResearchMessage.STATUS_PENDING)
        self.assertEqual(pending.content, "")
        # The question is durable from the first millisecond.
        self.assertEqual(pending.replies_to_id, body["user_message_id"])
        self.assertEqual(pending.replies_to.content, "What is the regime?")

    def test_the_dispatch_carries_the_announce_callbacks(self):
        """The push is what reaches the page the operator moved to."""
        from brain.tasks import answer_research_question
        with patch.object(answer_research_question, "apply_async",
                          return_value=MagicMock(id="t-2")) as enq, \
             _never_called_provider():
            self.client.post("/research/ask-ajax/", {"question": "hi"}, **XHR)
        kwargs = enq.call_args.kwargs
        self.assertIn("link", kwargs)
        self.assertIn("link_error", kwargs)
        self.assertEqual(kwargs["kwargs"]["message_id"],
                         kwargs["link"].args[1])

    def test_empty_question_is_still_refused(self):
        from brain.research_models import ResearchMessage
        resp = self.client.post("/research/ask-ajax/", {"question": "  "},
                                **XHR)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ResearchMessage.objects.count(), 0)

    def test_two_tabs_asking_at_once_do_not_share_a_lock(self):
        """Run-now's one-in-flight-per-job lock would 409 the second
        question; every question is its own job."""
        from brain.tasks import answer_research_question
        with patch.object(answer_research_question, "apply_async",
                          return_value=MagicMock(id="t")) as enq, \
             _never_called_provider():
            first = self.client.post("/research/ask-ajax/",
                                     {"question": "one"}, **XHR)
            second = self.client.post("/research/ask-ajax/",
                                      {"question": "two"}, **XHR)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(enq.call_count, 2)
        self.assertNotEqual(first.json()["pending_message_id"],
                            second.json()["pending_message_id"])


# ── The worker settles the row ───────────────────────────────────────────

class WorkerSettlesTests(TestCase):
    def setUp(self):
        self.user = _user("worker_u")

    def _ask(self, question="What is the regime?"):
        from brain.research_agent import (begin_ask,
                                          get_or_create_active_conversation)
        conv = get_or_create_active_conversation(self.user)
        return begin_ask(conv, question)

    def test_task_fills_the_same_row_in_place(self):
        from brain.research_models import ResearchMessage
        from brain.tasks import answer_research_question
        _q, pending = self._ask()

        with _echo_provider():
            out = answer_research_question(message_id=pending.pk)

        self.assertTrue(out["ok"])
        self.assertEqual(out["assistant_message_id"], pending.pk)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ResearchMessage.STATUS_DONE)
        self.assertIn("What is the regime?", pending.content)
        # In place: one exchange, two rows — never a third.
        self.assertEqual(ResearchMessage.objects.count(), 2)

    def test_answering_twice_does_not_bill_twice(self):
        """A Celery retry must not re-run an LLM call already paid for."""
        from brain.tasks import answer_research_question
        _q, pending = self._ask()
        with _echo_provider():
            answer_research_question(message_id=pending.pk)
        pending.refresh_from_db()
        first = pending.content

        with _never_called_provider():
            out = answer_research_question(message_id=pending.pk)
        self.assertTrue(out["already_settled"])
        pending.refresh_from_db()
        self.assertEqual(pending.content, first)

    def test_agent_failure_settles_the_row_rather_than_hanging_it(self):
        from brain.research_models import ResearchMessage
        from brain.tasks import answer_research_question
        _q, pending = self._ask()

        def bad_init(self, *a, **kw):
            self.agent_name = "research"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(
                side_effect=RuntimeError("api 500"))

        with patch("brain.research_agent.ResearchAgent.__init__", bad_init):
            answer_research_question(message_id=pending.pk)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ResearchMessage.STATUS_DONE)
        self.assertIn("api 500", pending.error)
        self.assertIn("temporarily unavailable", pending.content)

    def test_worker_death_settles_the_row_through_the_errback(self):
        """Without this the operator watches a bubble that never resolves."""
        from brain.research_models import ResearchMessage
        from brain.tasks import announce_research_failed
        _q, pending = self._ask()

        with patch("dashboard.consumers.push_eye_event") as pushed:
            announce_research_failed(None, RuntimeError("worker died"), None,
                                     self.user.pk, pending.pk)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ResearchMessage.STATUS_DONE)
        self.assertIn("worker died", pending.error)
        self.assertFalse(pushed.call_args.args[2]["ok"])


# ── The announcement reaches the operator, and only them ─────────────────

class AnnounceTests(TestCase):
    def test_answer_pushes_sauron_answer_to_the_asking_user_only(self):
        from brain.research_agent import (begin_ask,
                                          get_or_create_active_conversation)
        from brain.tasks import (answer_research_question,
                                 announce_research_answer)
        asker = _user("asker")
        bystander = _user("bystander")
        conv = get_or_create_active_conversation(asker)
        _q, pending = begin_ask(conv, "Why did the gate reject AAPL?")
        with _echo_provider():
            result = answer_research_question(message_id=pending.pk)

        with patch("dashboard.consumers.push_eye_event") as pushed:
            announce_research_answer(result, asker.pk, pending.pk)

        self.assertEqual(pushed.call_count, 1)
        user_arg, kind, data = pushed.call_args.args
        self.assertEqual(user_arg.pk, asker.pk)
        self.assertNotEqual(user_arg.pk, bystander.pk)
        self.assertEqual(kind, "sauron_answer")
        self.assertEqual(data["message_id"], pending.pk)
        self.assertEqual(data["question"], "Why did the gate reject AAPL?")
        self.assertIn("AAPL", data["preview"])
        self.assertTrue(data["ok"])

    def test_a_failed_answer_announces_as_not_ok(self):
        from brain.research_agent import (begin_ask,
                                          get_or_create_active_conversation)
        from brain.tasks import (answer_research_question,
                                 announce_research_answer)
        u = _user("failer")
        conv = get_or_create_active_conversation(u)
        _q, pending = begin_ask(conv, "anything")

        def bad_init(self, *a, **kw):
            self.agent_name = "research"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("nope"))

        with patch("brain.research_agent.ResearchAgent.__init__", bad_init):
            result = answer_research_question(message_id=pending.pk)
        with patch("dashboard.consumers.push_eye_event") as pushed:
            announce_research_answer(result, u.pk, pending.pk)
        self.assertFalse(pushed.call_args.args[2]["ok"])


# ── The panel restores the thread on any page ────────────────────────────

class ThreadRestoreTests(TestCase):
    def setUp(self):
        self.user = _user("restore_u")
        self.client.force_login(self.user)

    def test_pending_question_survives_a_page_change_and_resolves_in_place(self):
        from brain.tasks import answer_research_question

        with patch.object(answer_research_question, "apply_async",
                          return_value=MagicMock(id="t")), \
             _never_called_provider():
            asked = self.client.post("/research/ask-ajax/",
                                     {"question": "Read on USD?"}, **XHR).json()
        pid = asked["pending_message_id"]

        # The operator changes page. Any page's panel asks the server what
        # the thread currently is.
        self.client.get("/signals/", HTTP_HOST="127.0.0.1")
        thread = self.client.get("/research/thread/", **XHR).json()
        self.assertTrue(thread["ok"])
        self.assertTrue(thread["pending"])
        self.assertEqual([m["id"] for m in thread["messages"]],
                         [asked["user_message_id"], pid])
        last = thread["messages"][-1]
        self.assertTrue(last["pending"])
        self.assertIn("still answering", last["text"])

        # The worker lands.
        with _echo_provider():
            answer_research_question(message_id=pid)

        thread = self.client.get("/research/thread/", **XHR).json()
        self.assertFalse(thread["pending"])
        # Same id — the pending bubble becomes the answer rather than a new
        # bubble appearing beside an abandoned one.
        self.assertEqual([m["id"] for m in thread["messages"]],
                         [asked["user_message_id"], pid])
        self.assertFalse(thread["messages"][-1]["pending"])
        self.assertIn("Read on USD?", thread["messages"][-1]["text"])

    def test_thread_never_creates_a_conversation(self):
        """It is called on every page load; a write there would spawn an
        empty conversation row per page view."""
        from brain.research_models import ResearchConversation
        thread = self.client.get("/research/thread/", **XHR).json()
        self.assertEqual(thread["messages"], [])
        self.assertIsNone(thread["conversation_id"])
        self.assertEqual(ResearchConversation.objects.count(), 0)

    def test_thread_requires_login(self):
        self.client.logout()
        resp = self.client.get("/research/thread/", **XHR)
        self.assertEqual(resp.status_code, 302)

    def test_the_panel_ships_with_a_load_path(self):
        """The panel painted only what the page in front of you typed."""
        body = self.client.get("/signals/",
                               HTTP_HOST="127.0.0.1").content.decode("utf-8")
        self.assertIn("/research/thread/", body)
        self.assertIn("sauron_answer", body)

    def test_research_page_shows_a_pending_question_rather_than_a_blank_turn(self):
        from brain.tasks import answer_research_question
        with patch.object(answer_research_question, "apply_async",
                          return_value=MagicMock(id="t")), \
             _never_called_provider():
            self.client.post("/research/ask-ajax/",
                             {"question": "pending one"}, **XHR)
        body = self.client.get("/research/",
                               HTTP_HOST="127.0.0.1").content.decode("utf-8")
        self.assertIn("pending one", body)
        self.assertIn("still answering", body)


# ── A dead broker degrades, it does not lose the question ────────────────

class BrokerDownTests(TestCase):
    def setUp(self):
        self.user = _user("broker_u")
        self.client.force_login(self.user)

    def test_dead_broker_answers_inside_the_request(self):
        from brain.research_models import ResearchMessage
        from brain.tasks import answer_research_question
        with patch.object(answer_research_question, "apply_async",
                          side_effect=OSError("broker down")), \
             _echo_provider():
            resp = self.client.post("/research/ask-ajax/",
                                    {"question": "still works?"}, **XHR)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["pending"])
        self.assertIn("still works?", body["assistant_html"])
        asst = ResearchMessage.objects.get(pk=body["assistant_message_id"])
        self.assertEqual(asst.status, ResearchMessage.STATUS_DONE)

    def test_a_plain_non_xhr_caller_keeps_the_synchronous_contract(self):
        """The /research/ page's own form has no socket handler to hear a
        later announcement, so it must be answered in the response."""
        from brain.tasks import answer_research_question
        with patch.object(answer_research_question, "apply_async",
                          return_value=MagicMock(id="t")) as enq, \
             _echo_provider():
            resp = self.client.post("/research/ask-ajax/",
                                    {"question": "form ask"})
        enq.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("form ask", resp.json()["assistant_html"])

    def test_the_form_endpoint_still_answers_end_to_end(self):
        from brain.research_models import ResearchMessage
        with _echo_provider():
            resp = self.client.post("/research/ask/", {"question": "classic"})
        self.assertEqual(resp.status_code, 302)
        rows = list(ResearchMessage.objects.order_by("created_at"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].status, ResearchMessage.STATUS_DONE)
        self.assertIn("classic", rows[1].content)


# ── Nothing crosses ──────────────────────────────────────────────────────

class NoCrossingTests(TestCase):
    def test_two_questions_in_flight_keep_their_own_answers(self):
        """Rows from two tabs interleave inside one conversation; pairing by
        position would hand tab A's answer to tab B's question."""
        from brain.research_agent import (begin_ask, complete_ask,
                                          get_or_create_active_conversation)
        u = _user("two_tabs")
        conv = get_or_create_active_conversation(u)
        _q1, p1 = begin_ask(conv, "QUESTION ALPHA")
        _q2, p2 = begin_ask(conv, "QUESTION BRAVO")

        # Settled out of order, as two workers would.
        with _echo_provider():
            complete_ask(p2.pk)
            complete_ask(p1.pk)

        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertIn("QUESTION ALPHA", p1.content)
        self.assertNotIn("BRAVO", p1.content)
        self.assertIn("QUESTION BRAVO", p2.content)
        self.assertNotIn("ALPHA", p2.content)

    def test_two_users_threads_are_separate(self):
        from brain.research_agent import (begin_ask, complete_ask,
                                          get_or_create_active_conversation)
        u1 = _user("cross_1")
        u2 = _user("cross_2")
        with _echo_provider():
            complete_ask(begin_ask(get_or_create_active_conversation(u1),
                                   "SECRET OF ONE")[1].pk)
            complete_ask(begin_ask(get_or_create_active_conversation(u2),
                                   "SECRET OF TWO")[1].pk)

        self.client.force_login(u2)
        thread = self.client.get("/research/thread/", **XHR).json()
        blob = str(thread)
        self.assertIn("SECRET OF TWO", blob)
        self.assertNotIn("SECRET OF ONE", blob)

    def test_a_pending_placeholder_never_enters_the_prompt(self):
        """An empty ASSISTANT turn in the history teaches the model that
        answering with nothing is acceptable."""
        from brain.research_agent import (
            _conversation_history_for_prompt, begin_ask, complete_ask,
            get_or_create_active_conversation)
        u = _user("history_u")
        conv = get_or_create_active_conversation(u)
        _q1, p1 = begin_ask(conv, "first")
        with _echo_provider():
            complete_ask(p1.pk)
        begin_ask(conv, "second")   # left pending on purpose
        history = _conversation_history_for_prompt(conv)
        self.assertTrue(all(m["content"] for m in history))
        self.assertEqual(history[-1]["content"], "second")


# ── The spend ceiling now covers chat ────────────────────────────────────

class SpendGuardTests(TestCase):
    def test_a_spent_budget_refuses_visibly_instead_of_hanging(self):
        from brain.research_agent import (begin_ask,
                                          get_or_create_active_conversation)
        from brain.research_models import ResearchMessage
        from brain.tasks import answer_research_question
        u = _user("broke_u")
        conv = get_or_create_active_conversation(u)
        _q, pending = begin_ask(conv, "expensive question")

        with patch("brain.research_agent.can_spend",
                   return_value=(False, "daily AI budget spent")), \
             _never_called_provider():
            out = answer_research_question(message_id=pending.pk)

        self.assertFalse(out["ok"])
        pending.refresh_from_db()
        # Settled, not left pending: a refusal the operator can read beats a
        # bubble that spins forever.
        self.assertEqual(pending.status, ResearchMessage.STATUS_DONE)
        self.assertIn("budget", pending.content.lower())
        self.assertIn("budget", pending.error.lower())

    def test_a_healthy_budget_lets_the_answer_through(self):
        from brain.research_agent import (begin_ask,
                                          get_or_create_active_conversation)
        from brain.tasks import answer_research_question
        u = _user("solvent_u")
        conv = get_or_create_active_conversation(u)
        _q, pending = begin_ask(conv, "cheap question")
        with patch("brain.research_agent.can_spend",
                   return_value=(True, "$5.00 of $5.00 remaining")), \
             _echo_provider():
            out = answer_research_question(message_id=pending.pk)
        self.assertTrue(out["ok"])
