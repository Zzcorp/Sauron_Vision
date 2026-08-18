"""Async "Run now" + briefing reader + list-ordering fixes.

Every manually initiated task used to run synchronously inside the
click's request — an LLM generation held the page for minutes and
answered with a reload. XHR clicks now enqueue the real beat task and
return 202; completion is announced on the operator's socket. Plain
form POSTs keep the old synchronous path, so nothing breaks without JS.

Run with:  python manage.py test tests.test_run_now_async
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

XHR = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def _staff(name="run_admin"):
    return User.objects.create_user(name, password="x", is_staff=True,
                                    is_superuser=True)


class AsyncDispatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _staff()

    def setUp(self):
        from django.core.cache import cache
        cache.clear()   # the in-flight dispatch locks live here
        self.client.force_login(self.admin)

    def test_xhr_click_enqueues_and_returns_202(self):
        from brain.tasks import run_sauron_mind
        with patch.object(run_sauron_mind, "apply_async",
                          return_value=MagicMock(id="task-1")) as enq:
            resp = self.client.post("/brain/run/", **XHR)
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(resp.json()["ok"])
        enq.assert_called_once()

    def test_plain_form_post_keeps_the_sync_path(self):
        with patch("brain.synthesizer.synthesize_now",
                   return_value={"status": "ok"}) as sync:
            resp = self.client.post("/brain/run/")
        self.assertEqual(resp.status_code, 302)
        sync.assert_called_once()

    def test_second_click_is_refused_while_in_flight(self):
        """The button's disabled state is per page load — a reload or a
        second tab must not enqueue a concurrent duplicate of an
        expensive LLM run."""
        from brain.tasks import run_sauron_mind
        with patch.object(run_sauron_mind, "apply_async",
                          return_value=MagicMock(id="t")) as enq:
            first = self.client.post("/brain/run/", **XHR)
            second = self.client.post("/brain/run/", **XHR)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        enq.assert_called_once()

    def test_broker_down_frees_the_lock_for_the_next_click(self):
        from django.core.cache import cache
        from brain.tasks import run_sauron_mind
        from dashboard.run_async import lock_key
        with patch.object(run_sauron_mind, "apply_async",
                          side_effect=OSError("broker down")), \
             patch("brain.synthesizer.synthesize_now",
                   return_value={"status": "ok"}):
            self.client.post("/brain/run/", **XHR)
        self.assertIsNone(cache.get(lock_key("Brain synthesis")))

    def test_broker_down_degrades_to_sync(self):
        from brain.tasks import run_sauron_mind
        with patch.object(run_sauron_mind, "apply_async",
                          side_effect=OSError("broker down")), \
             patch("brain.synthesizer.synthesize_now",
                   return_value={"status": "ok"}) as sync:
            resp = self.client.post("/brain/run/", **XHR)
        self.assertEqual(resp.status_code, 302)
        sync.assert_called_once()

    def test_evolution_click_forces_past_the_cadence_gate(self):
        from signals.tasks import propose_strategy_evolutions
        with patch.object(propose_strategy_evolutions, "apply_async",
                          return_value=MagicMock(id="task-2")) as enq:
            resp = self.client.post("/admin-dashboard/evolution/run/", **XHR)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(enq.call_args.kwargs["kwargs"], {"force": True})

    def test_force_bypasses_the_weekday_gate(self):
        """A human's explicit click must never be silently skipped by the
        beat task's evidence-cadence gate."""
        from core.platform_control import PlatformComponent, seed_components
        from signals.tasks import propose_strategy_evolutions
        seed_components()
        PlatformComponent.objects.filter(
            key__in=("platform_master", "pipeline_evolution")
        ).update(is_enabled=True)
        tuesday = timezone.now().replace(year=2026, month=8, day=18,
                                         hour=5, minute=0)
        with patch("django.utils.timezone.now", return_value=tuesday), \
             patch("signals.evolution.propose_for_decaying_rules",
                   return_value={"total_proposals": 0}) as sweep:
            out = propose_strategy_evolutions(force=True)
        self.assertEqual(out["status"], "ok")
        sweep.assert_called_once()


class AnnounceTests(TestCase):
    def test_completion_lands_as_a_silent_notification_plus_run_complete(self):
        from dashboard.tasks import announce_run_complete
        from alerts.models import Notification
        u = User.objects.create_user("announce_u")
        with patch("dashboard.consumers.push_eye_event") as pushed:
            announce_run_complete({"status": "ok", "n": 3},
                                  u.pk, "Brain synthesis", "/brain/")
        n = Notification.objects.get(user=u)
        self.assertIn("Brain synthesis finished", n.title)
        self.assertEqual(n.url, "/brain/")
        kinds = [c.args[1] for c in pushed.call_args_list]
        # The Notification row pushes silent (badge only); run_complete
        # draws the visible card — one event, one banner.
        self.assertIn("notification", kinds)
        self.assertIn("run_complete", kinds)
        notif_call = next(c for c in pushed.call_args_list
                          if c.args[1] == "notification")
        self.assertTrue(notif_call.args[2]["silent"])

    def test_failure_callback_says_so_plainly(self):
        """Called exactly as the worker's inline errback protocol does:
        (request, exc, traceback) prepended before the .s() partials —
        a (task_id, ...) signature dies with TypeError inside Celery's
        failure handling and no announcement ever fires."""
        from dashboard.tasks import announce_run_failed
        from alerts.models import Notification
        u = User.objects.create_user("announce_f")
        with patch("dashboard.consumers.push_eye_event"):
            announce_run_failed(None, RuntimeError("boom"), None,
                                u.pk, "Critic pass", "/hypotheses/")
        n = Notification.objects.get(user=u)
        self.assertIn("failed", n.title)
        self.assertIn("boom", n.body)

    def test_completion_clears_the_inflight_lock(self):
        from django.core.cache import cache
        from dashboard.run_async import lock_key
        from dashboard.tasks import announce_run_complete
        u = User.objects.create_user("announce_lock")
        cache.set(lock_key("Brain synthesis"), "1", 60)
        with patch("dashboard.consumers.push_eye_event"):
            announce_run_complete({"status": "ok"}, u.pk,
                                  "Brain synthesis", "/brain/")
        self.assertIsNone(cache.get(lock_key("Brain synthesis")))


class BriefingReaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from brain.briefing_models import StrategistBriefing
        cls.user = User.objects.create_user("brf_u")
        cls.old = StrategistBriefing.objects.create(
            posture="defensive", outlook_md="The old outlook body.",
            ideas=[], watchlist=[], model_used="m", tokens_in=1,
            tokens_out=1, cost_usd=0)
        cls.new = StrategistBriefing.objects.create(
            posture="balanced", outlook_md="The newest outlook body.",
            ideas=[], watchlist=[], model_used="m", tokens_in=1,
            tokens_out=1, cost_usd=0)

    def setUp(self):
        self.client.force_login(self.user)

    def test_default_shows_the_latest(self):
        resp = self.client.get("/briefing/")
        self.assertContains(resp, "The newest outlook body.")
        self.assertContains(resp, "Today ·")

    def test_id_opens_a_past_briefing(self):
        resp = self.client.get(f"/briefing/?id={self.old.pk}")
        self.assertContains(resp, "The old outlook body.")
        self.assertNotContains(resp, "Today ·")
        self.assertContains(resp, "latest &#9656;")

    def test_bad_id_falls_back_to_latest(self):
        resp = self.client.get("/briefing/?id=999999")
        self.assertContains(resp, "The newest outlook body.")
        resp = self.client.get("/briefing/?id=nonsense")
        self.assertContains(resp, "The newest outlook body.")

    def test_history_rows_are_clickable_with_previews(self):
        resp = self.client.get("/briefing/")
        self.assertContains(resp, f"?id={self.old.pk}")
        self.assertContains(resp, "data-brf-summary")
        self.assertContains(resp, "HOVER_DELAY_MS = 2000")


class OrderingRegressionTests(TestCase):
    def test_hypotheses_leaderboard_deduplicates_agents(self):
        """Meta.ordering used to ride into the DISTINCT projection and
        return one 'distinct' row per created_at — duplicate leaderboard
        cards for every agent."""
        from brain.knowledge_models import Hypothesis
        for i in range(3):
            Hypothesis.objects.create(
                source_agent="critic", claim_text=f"claim {i}",
                confidence=0.5)
        u = _staff("ord_admin")
        self.client.force_login(u)
        resp = self.client.get("/hypotheses/")
        self.assertEqual(resp.status_code, 200)
        agents = [r["agent"] for r in resp.context["leaderboard"]]
        self.assertEqual(agents.count("critic"), 1,
                         "one leaderboard row per agent, not per row")

    def test_upcoming_events_api_serves_the_future_not_the_archive(self):
        from datetime import timedelta
        from market_data.models import EconomicEvent
        EconomicEvent.objects.create(
            title="ancient", datetime=timezone.now() - timedelta(days=900),
            country="US", impact="high", source="test")
        EconomicEvent.objects.create(
            title="tomorrow", datetime=timezone.now() + timedelta(days=1),
            country="US", impact="high", source="test")
        u = User.objects.create_user("api_u")
        self.client.force_login(u)
        resp = self.client.get("/api/calendar/")
        body = resp.content.decode()
        self.assertIn("tomorrow", body)
        self.assertNotIn("ancient", body,
                         "the API served the 50 OLDEST rows ever stored")
        # The global OrderingFilter used to call .order_by() on a sliced
        # queryset — ?ordering= was a one-parameter 500.
        resp = self.client.get("/api/calendar/?ordering=datetime")
        self.assertEqual(resp.status_code, 200)

    def test_pattern_miner_task_still_expires_stale_discoveries(self):
        """The async lane made signals.tasks.mine_patterns the ONLY
        production path to the expiry sweep — it must actually run it."""
        from core.platform_control import PlatformComponent, seed_components
        from signals.tasks import mine_patterns
        seed_components()
        PlatformComponent.objects.filter(
            key__in=("platform_master", "pipeline_pattern_miner")
        ).update(is_enabled=True)
        with patch("signals.pattern_miner.expire_stale_discoveries",
                   return_value=2) as sweep, \
             patch("signals.pattern_miner.mine_all_active",
                   return_value={"n_discovered": 0}):
            mine_patterns()
        sweep.assert_called_once()
