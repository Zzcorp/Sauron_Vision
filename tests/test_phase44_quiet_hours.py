"""Tests for Phase 44 — quiet hours respect.

Covers:
  - _in_quiet_hours: same-day window, midnight-wraparound window, edge cases
  - quiet_start == quiet_end → no quiet hours
  - missing prefs OR missing fields → False
  - dispatch_notification: in-app row IS created during quiet hours
  - dispatch_notification: external channels NOT called during quiet hours
  - dispatch_notification: external channels ARE called outside quiet hours
  - profile UI saves + clears quiet hours via the form
"""
from datetime import datetime, time, timezone as dt_tz
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user_with_prefs(name, **kw):
    from alerts.models import UserNotificationPrefs
    u = User.objects.create_user(username=name, password="x",
                                   email=f"{name}@x.com")
    UserNotificationPrefs.objects.create(user=u, **kw)
    return u


def _at_utc(hour, minute=0):
    """Return a TZ-aware UTC datetime today at hour:minute."""
    return timezone.now().replace(hour=hour, minute=minute, second=0, microsecond=0)


# ── _in_quiet_hours ───────────────────────────────────────────────────────

class InQuietHoursTests(TestCase):
    def test_same_day_window_inside(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("sd_in",
                              quiet_start=time(9, 0),
                              quiet_end=time(17, 0))
        self.assertTrue(_in_quiet_hours(u, now=_at_utc(13, 0)))

    def test_same_day_window_outside(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("sd_out",
                              quiet_start=time(9, 0),
                              quiet_end=time(17, 0))
        self.assertFalse(_in_quiet_hours(u, now=_at_utc(20, 0)))

    def test_wraparound_after_midnight(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("wrap_after",
                              quiet_start=time(22, 0),
                              quiet_end=time(7, 0))
        # 03:00 is within 22:00 → 07:00 wrap window.
        self.assertTrue(_in_quiet_hours(u, now=_at_utc(3, 0)))

    def test_wraparound_before_midnight(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("wrap_before",
                              quiet_start=time(22, 0),
                              quiet_end=time(7, 0))
        self.assertTrue(_in_quiet_hours(u, now=_at_utc(23, 30)))

    def test_wraparound_outside(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("wrap_out",
                              quiet_start=time(22, 0),
                              quiet_end=time(7, 0))
        # 14:00 falls outside the 22..07 wrap window.
        self.assertFalse(_in_quiet_hours(u, now=_at_utc(14, 0)))

    def test_start_equals_end_no_quiet(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("eq",
                              quiet_start=time(0, 0),
                              quiet_end=time(0, 0))
        self.assertFalse(_in_quiet_hours(u, now=_at_utc(3, 0)))

    def test_missing_either_field_no_quiet(self):
        from bot_program.notifications import _in_quiet_hours
        u = _user_with_prefs("partial", quiet_start=time(22, 0),
                              quiet_end=None)
        self.assertFalse(_in_quiet_hours(u))

    def test_no_prefs_returns_false(self):
        from bot_program.notifications import _in_quiet_hours
        u = User.objects.create_user(username="no_prefs", password="x")
        self.assertFalse(_in_quiet_hours(u))


# ── dispatch_notification gating ──────────────────────────────────────────

class DispatchQuietHoursTests(TestCase):
    def _user_with_telegram(self, name, **prefs_kw):
        from alerts.models import UserNotificationPrefs
        u = User.objects.create_user(username=name, password="x",
                                       email=f"{name}@x.com")
        UserNotificationPrefs.objects.create(
            user=u, telegram_chat_id="123",
            **prefs_kw,
        )
        # Patch the user's TraderProfile to use telegram channel.
        from portfolio.trader_profile import TraderProfile
        TraderProfile.objects.create(user=u, notify_channel="telegram")
        return u

    def test_in_app_row_created_during_quiet_hours(self):
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = self._user_with_telegram(
            "qh_in_app",
            quiet_start=time(0, 0), quiet_end=time(23, 59))
        # Force quiet=True via patch.
        with patch("bot_program.notifications._in_quiet_hours", return_value=True):
            ok = dispatch_notification(u, "bot_fill_open", title="t", body="b")
        # In-app row IS created (delivered=True).
        self.assertTrue(ok)
        self.assertEqual(Notification.objects.filter(user=u).count(), 1)

    def test_telegram_NOT_called_during_quiet_hours(self):
        from bot_program.notifications import dispatch_notification
        u = self._user_with_telegram(
            "qh_no_buzz",
            quiet_start=time(22, 0), quiet_end=time(7, 0))
        with patch("bot_program.notifications._in_quiet_hours", return_value=True):
            with patch("bot_program.notifications._send_telegram") as mock_tg:
                dispatch_notification(u, "bot_fill_open", title="t")
        mock_tg.assert_not_called()

    def test_telegram_IS_called_outside_quiet_hours(self):
        from bot_program.notifications import dispatch_notification
        u = self._user_with_telegram(
            "qh_buzz",
            quiet_start=time(22, 0), quiet_end=time(7, 0))
        with patch("bot_program.notifications._in_quiet_hours", return_value=False):
            with patch("bot_program.notifications._send_telegram",
                        return_value=True) as mock_tg:
                dispatch_notification(u, "bot_fill_open", title="t", body="b")
        mock_tg.assert_called_once()

    def test_briefing_respects_quiet_hours_too(self):
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = self._user_with_telegram(
            "qh_brief",
            receive_strategist_briefing=True,
            quiet_start=time(0, 0), quiet_end=time(23, 59))
        with patch("bot_program.notifications._in_quiet_hours", return_value=True):
            with patch("bot_program.notifications._send_telegram") as mock_tg:
                ok = dispatch_notification(u, "strategist_briefing",
                                            title="briefing", body="ok")
        self.assertTrue(ok)
        # Telegram NOT called; in-app row created.
        mock_tg.assert_not_called()
        self.assertEqual(Notification.objects.filter(user=u).count(), 1)


# ── Profile UI saves quiet hours ──────────────────────────────────────────

class ProfileUIQuietHoursTests(TestCase):
    def test_save_prefs_persists_quiet_hours(self):
        from alerts.models import UserNotificationPrefs
        u = User.objects.create_user(username="ui_qh", password="x")
        self.client.force_login(u)
        r = self.client.post("/notifications/settings/", {
            "action": "save_prefs",
            "quiet_start": "22:00",
            "quiet_end": "07:00",
        })
        self.assertEqual(r.status_code, 302)
        prefs = UserNotificationPrefs.objects.get(user=u)
        self.assertEqual(prefs.quiet_start, time(22, 0))
        self.assertEqual(prefs.quiet_end, time(7, 0))

    def test_save_prefs_clears_quiet_hours_with_empty(self):
        from alerts.models import UserNotificationPrefs
        u = User.objects.create_user(username="ui_qh_clear", password="x")
        UserNotificationPrefs.objects.create(
            user=u, quiet_start=time(22, 0), quiet_end=time(7, 0))
        self.client.force_login(u)
        r = self.client.post("/notifications/settings/", {
            "action": "save_prefs",
            "quiet_start": "",
            "quiet_end": "",
        })
        self.assertEqual(r.status_code, 302)
        prefs = UserNotificationPrefs.objects.get(user=u)
        self.assertIsNone(prefs.quiet_start)
        self.assertIsNone(prefs.quiet_end)

    def test_save_prefs_invalid_format_clears_field(self):
        """Bad input shouldn't 500 — degrade to None."""
        from alerts.models import UserNotificationPrefs
        u = User.objects.create_user(username="ui_qh_bad", password="x")
        self.client.force_login(u)
        r = self.client.post("/notifications/settings/", {
            "action": "save_prefs",
            "quiet_start": "not-a-time",
            "quiet_end": "07:00",
        })
        self.assertEqual(r.status_code, 302)
        prefs = UserNotificationPrefs.objects.get(user=u)
        self.assertIsNone(prefs.quiet_start)
        self.assertEqual(prefs.quiet_end, time(7, 0))
