"""Tests for Phase 45 — HTML email template for the daily briefing.

Covers:
  - send_briefing_email renders both HTML + plaintext alternatives
  - subject line includes the posture
  - body contains structured fields (outlook, posture, watchlist, ideas)
  - empty user.email returns False
  - dispatch_notification routes to HTML path when kind=strategist_briefing
    and channel=email AND payload is provided
  - dispatch_notification falls back to plain email when payload is missing
  - dispatch_notification still uses plain email for non-briefing kinds
"""
from datetime import time
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings


def _user_with_email_channel(name):
    """User with email pref + TraderProfile.notify_channel='email'."""
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    u = User.objects.create_user(username=name, password="x",
                                   email=f"{name}@x.com")
    UserNotificationPrefs.objects.create(
        user=u, email_notifications=True,
        receive_strategist_briefing=True,
        receive_bot_alerts=True,
    )
    TraderProfile.objects.create(user=u, notify_channel="email")
    return u


def _make_briefing(**overrides):
    from brain.briefing_models import StrategistBriefing
    defaults = dict(
        outlook_md="USD weakens; equities firm. Watch DXY.",
        posture="defensive",
        posture_rationale="risk-off pulse",
        watchlist=[{"kind": "macro", "ref": "DXY",
                     "what_to_watch": "below 102"}],
        ideas=[{"summary": "fade USD strength",
                 "horizon_hours": 24, "confidence": 0.8,
                 "hypothesis_kind": "regime_holds"}],
        model_used="claude-stub",
        cost_usd="0.30000",
    )
    defaults.update(overrides)
    return StrategistBriefing.objects.create(**defaults)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                    DEFAULT_FROM_EMAIL="sauron@example.com")
class SendBriefingEmailTests(TestCase):
    def test_sends_with_subject_and_html_alternative(self):
        from alerts.channels.briefing_email import send_briefing_email
        briefing = _make_briefing()
        ok = send_briefing_email("user@example.com", briefing)
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        # Subject includes posture.
        self.assertIn("DEFENSIVE", msg.subject)
        # Plain body has the outlook.
        self.assertIn("USD weakens", msg.body)
        # HTML alternative present.
        self.assertEqual(len(msg.alternatives), 1)
        html, mime = msg.alternatives[0]
        self.assertEqual(mime, "text/html")
        self.assertIn("DEFENSIVE", html)
        self.assertIn("DXY", html)
        self.assertIn("fade USD strength", html)

    def test_includes_watchlist_and_ideas_in_html(self):
        from alerts.channels.briefing_email import send_briefing_email
        briefing = _make_briefing(
            watchlist=[{"kind": "rule", "ref": "starter_stock_momentum",
                          "what_to_watch": "decay continuing"}],
            ideas=[{"summary": "pause momentum rules", "confidence": 0.7,
                     "hypothesis_kind": None, "horizon_hours": 48}])
        send_briefing_email("user@example.com", briefing)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("starter_stock_momentum", html)
        self.assertIn("pause momentum rules", html)
        self.assertIn("Watchlist", html)
        self.assertIn("Ideas", html)

    def test_empty_email_returns_false(self):
        from alerts.channels.briefing_email import send_briefing_email
        briefing = _make_briefing()
        ok = send_briefing_email("", briefing)
        self.assertFalse(ok)
        self.assertEqual(len(mail.outbox), 0)

    def test_template_handles_error_briefing(self):
        """An error-stamped briefing (synthesis failed) still produces an email
        without raising."""
        from alerts.channels.briefing_email import send_briefing_email
        briefing = _make_briefing(error="api 500", outlook_md="",
                                    watchlist=[], ideas=[])
        ok = send_briefing_email("user@example.com", briefing)
        self.assertTrue(ok)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("Synthesis error", html)


# ── Routing through dispatch_notification ────────────────────────────────

@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                    DEFAULT_FROM_EMAIL="sauron@example.com")
class DispatchRoutesToHtmlEmailTests(TestCase):
    def test_briefing_with_payload_uses_html_email(self):
        from bot_program.notifications import dispatch_notification
        u = _user_with_email_channel("html_route")
        briefing = _make_briefing()
        ok = dispatch_notification(
            u, "strategist_briefing",
            title="t", body="b", url="/briefing/",
            payload=briefing,
        )
        self.assertTrue(ok)
        # HTML alternative should be present (plain _send_email uses send_mail
        # which doesn't attach an alternative).
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)

    def test_briefing_without_payload_falls_back_to_plain(self):
        from bot_program.notifications import dispatch_notification
        u = _user_with_email_channel("plain_fallback")
        ok = dispatch_notification(
            u, "strategist_briefing",
            title="t", body="b", url="/briefing/",
            payload=None,
        )
        self.assertTrue(ok)
        # Plain send_mail → no html alternative.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].alternatives), 0)

    def test_non_briefing_kind_uses_plain_email(self):
        from bot_program.notifications import dispatch_notification
        u = _user_with_email_channel("non_brief")
        # Even with payload, a non-briefing kind ignores it.
        ok = dispatch_notification(
            u, "bot_fill_open", title="X BUY", body="qty 1 @ 100",
            payload=_make_briefing(),
        )
        self.assertTrue(ok)
        # Plain email — no HTML alternative for fills.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].alternatives), 0)

    def test_quiet_hours_blocks_html_email_too(self):
        """Phase 44 + 45 interaction: quiet hours mute the email channel
        regardless of html-vs-plain."""
        from bot_program.notifications import dispatch_notification
        u = _user_with_email_channel("html_quiet")
        # Configure quiet hours that wrap the entire day.
        from alerts.models import UserNotificationPrefs
        UserNotificationPrefs.objects.filter(user=u).update(
            quiet_start=time(0, 0), quiet_end=time(23, 59))
        with patch("bot_program.notifications._in_quiet_hours",
                    return_value=True):
            dispatch_notification(
                u, "strategist_briefing",
                title="t", body="b", payload=_make_briefing(),
            )
        # No emails sent.
        self.assertEqual(len(mail.outbox), 0)
