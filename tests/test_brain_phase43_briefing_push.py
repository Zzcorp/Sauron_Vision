"""Tests for Phase 43 — daily strategist briefing push.

Covers:
  - 'strategist_briefing' is in BOT_KINDS
  - dispatch_notification gates briefings on receive_strategist_briefing
    (NOT receive_bot_alerts)
  - default OFF: a fresh prefs row blocks delivery
  - opted-in user gets in-app notification row
  - notify_strategist_briefing_to_all walks only opted-in users
  - run_strategist_now triggers fan-out (delivery counts in result)
  - profile UI checkbox saves the new pref
"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _user_with_prefs(name, *, receive_strategist_briefing=False,
                       receive_bot_alerts=True):
    from alerts.models import UserNotificationPrefs
    u = User.objects.create_user(username=name, password="x", email=f"{name}@x.com")
    UserNotificationPrefs.objects.create(
        user=u, receive_strategist_briefing=receive_strategist_briefing,
        receive_bot_alerts=receive_bot_alerts,
    )
    return u


def _make_briefing(**overrides):
    from brain.briefing_models import StrategistBriefing
    defaults = dict(
        outlook_md="USD weakens; equities firm.",
        posture="balanced",
        posture_rationale="neutral signals",
        watchlist=[{"kind": "macro", "ref": "DXY", "what_to_watch": "below 102"}],
        ideas=[{"summary": "regime stays trending", "horizon_hours": 24,
                 "confidence": 0.7}],
    )
    defaults.update(overrides)
    return StrategistBriefing.objects.create(**defaults)


# ── BOT_KINDS registration ────────────────────────────────────────────────

class BotKindsTests(TestCase):
    def test_strategist_briefing_in_bot_kinds(self):
        from bot_program.notifications import BOT_KINDS
        self.assertIn("strategist_briefing", BOT_KINDS)


# ── dispatch_notification gating ──────────────────────────────────────────

class DispatchGatingTests(TestCase):
    def test_default_prefs_blocks_briefing(self):
        from bot_program.notifications import dispatch_notification
        u = _user_with_prefs("default_off")
        ok = dispatch_notification(u, "strategist_briefing", title="t")
        self.assertFalse(ok)

    def test_opted_in_delivers_in_app(self):
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = _user_with_prefs("opt_in", receive_strategist_briefing=True)
        ok = dispatch_notification(u, "strategist_briefing", title="t", body="b")
        self.assertTrue(ok)
        self.assertEqual(Notification.objects.filter(user=u).count(), 1)

    def test_briefing_does_not_use_receive_bot_alerts(self):
        """Even with receive_bot_alerts=False, briefing should deliver if the
        user opted into receive_strategist_briefing."""
        from bot_program.notifications import dispatch_notification
        u = _user_with_prefs("split_prefs",
                              receive_strategist_briefing=True,
                              receive_bot_alerts=False)
        ok = dispatch_notification(u, "strategist_briefing", title="t")
        self.assertTrue(ok)

    def test_bot_fill_uses_receive_bot_alerts(self):
        """Sanity: non-briefing kinds still respect the legacy pref."""
        from bot_program.notifications import dispatch_notification
        u = _user_with_prefs("bot_only",
                              receive_strategist_briefing=True,
                              receive_bot_alerts=False)
        ok = dispatch_notification(u, "bot_fill_open", title="t")
        self.assertFalse(ok)


# ── notify_strategist_briefing_to_all ────────────────────────────────────

class NotifyToAllTests(TestCase):
    def test_walks_only_opted_in(self):
        from bot_program.notifications import notify_strategist_briefing_to_all
        from alerts.models import Notification
        # Two opt-in users, one default-off.
        a = _user_with_prefs("a", receive_strategist_briefing=True)
        b = _user_with_prefs("b", receive_strategist_briefing=True)
        _user_with_prefs("c")  # default off

        briefing = _make_briefing()
        result = notify_strategist_briefing_to_all(briefing)

        self.assertEqual(result["n_eligible"], 2)
        self.assertEqual(result["n_delivered"], 2)
        # In-app rows for the two opt-in users; none for the third.
        self.assertEqual(Notification.objects.filter(user=a).count(), 1)
        self.assertEqual(Notification.objects.filter(user=b).count(), 1)
        self.assertEqual(Notification.objects.exclude(user__in=[a, b]).count(), 0)

    def test_no_users_returns_zeros(self):
        from bot_program.notifications import notify_strategist_briefing_to_all
        briefing = _make_briefing()
        result = notify_strategist_briefing_to_all(briefing)
        self.assertEqual(result["n_eligible"], 0)
        self.assertEqual(result["n_delivered"], 0)

    def test_truncates_long_outlook(self):
        """Body has a hard cap so we never blow up Telegram/email payloads."""
        from bot_program.notifications import notify_strategist_briefing_to_all
        from alerts.models import Notification
        _user_with_prefs("trunc_user", receive_strategist_briefing=True)
        briefing = _make_briefing(outlook_md="x" * 5000)
        notify_strategist_briefing_to_all(briefing)
        n = Notification.objects.first()
        self.assertLessEqual(len(n.body), 4000)

    def test_includes_posture_and_ideas_in_body(self):
        from bot_program.notifications import notify_strategist_briefing_to_all
        from alerts.models import Notification
        _user_with_prefs("rich_user", receive_strategist_briefing=True)
        briefing = _make_briefing(
            posture_rationale="risk-off pulse",
            ideas=[{"summary": "fade USD strength", "confidence": 0.8},
                    {"summary": "watch SPX 5500 break", "confidence": 0.6}])
        notify_strategist_briefing_to_all(briefing)
        n = Notification.objects.first()
        self.assertIn("Posture:", n.body)
        self.assertIn("fade USD strength", n.body)


# ── End-to-end: run_strategist_now triggers fan-out ──────────────────────

class StrategistRunFansOutTests(TestCase):
    def _stub_provider(self, parsed_dict):
        import json
        raw = json.dumps(parsed_dict)
        usage = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.05}

        def patched_init(self, *a, **kw):
            self.agent_name = "strategist"
            self.provider_name = "stub"
            self.model = "claude-stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(return_value=(raw, usage))
        return patch("brain.strategist.StrategistAgent.__init__", patched_init)

    def test_run_strategist_now_delivers_to_opted_in_users(self):
        from brain.strategist import run_strategist_now
        _user_with_prefs("e2e_a", receive_strategist_briefing=True)
        _user_with_prefs("e2e_b", receive_strategist_briefing=True)
        _user_with_prefs("e2e_c")  # opt-out

        with self._stub_provider({
            "outlook_md": "ok", "posture": "balanced",
            "watchlist": [], "ideas": [],
        }):
            r = run_strategist_now()

        self.assertTrue(r["ok"])
        self.assertEqual(r["n_eligible"], 2)
        self.assertEqual(r["n_delivered"], 2)


# ── Profile UI saves the new pref ─────────────────────────────────────────

class ProfileUISavesPrefTests(TestCase):
    def test_save_prefs_form_persists_briefing_toggle(self):
        from alerts.models import UserNotificationPrefs
        u = User.objects.create_user(username="ui_user", password="x")
        self.client.force_login(u)
        # POST with the briefing checkbox checked.
        r = self.client.post("/notifications/", {
            "action": "save_prefs",
            "receive_strategist_briefing": "on",
            "receive_bot_alerts": "on",
        })
        self.assertEqual(r.status_code, 302)
        prefs = UserNotificationPrefs.objects.get(user=u)
        self.assertTrue(prefs.receive_strategist_briefing)
        self.assertTrue(prefs.receive_bot_alerts)

    def test_save_prefs_form_unchecks_briefing(self):
        from alerts.models import UserNotificationPrefs
        u = User.objects.create_user(username="ui_user_off", password="x")
        UserNotificationPrefs.objects.create(
            user=u, receive_strategist_briefing=True)
        self.client.force_login(u)
        r = self.client.post("/notifications/", {"action": "save_prefs"})
        self.assertEqual(r.status_code, 302)
        prefs = UserNotificationPrefs.objects.get(user=u)
        self.assertFalse(prefs.receive_strategist_briefing)
