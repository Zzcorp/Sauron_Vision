"""Live notification banners — every Notification row raises a 4s
hover-pausing banner on its user's open tabs the moment it is written,
and the bell badge moves from server truth.

The push rides the existing per-user /ws/eye/ socket. Two chokepoints
cover every creation path: a post_save receiver (all save() paths,
including the five direct-create producer sites) and an explicit loop in
create_for_all (bulk_create fires no signals).

Run with:  python manage.py test tests.test_live_notification_banners
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase


class NotificationPushTests(TestCase):
    def test_create_for_user_pushes_the_live_kind(self):
        from alerts.models import Notification
        u = User.objects.create_user("push_u1")
        with patch("dashboard.consumers.push_eye_event") as pushed:
            Notification.create_for_user(
                u, "system", "Anomaly", body="b", url="/quotes/")
        pushed.assert_called_once()
        args = pushed.call_args.args
        self.assertEqual(args[0], u)
        self.assertEqual(args[1], "notification")
        self.assertEqual(args[2]["title"], "Anomaly")
        self.assertEqual(args[2]["url"], "/quotes/")
        self.assertFalse(args[2]["silent"])

    def test_create_for_all_pushes_once_per_user(self):
        from alerts.models import Notification
        users = [User.objects.create_user(f"push_all{i}") for i in range(3)]
        with patch("dashboard.consumers.push_eye_event") as pushed:
            Notification.create_for_all("system", "Broadcast")
        self.assertEqual(pushed.call_count, 3)
        self.assertEqual({c.args[0] for c in pushed.call_args_list},
                         set(users))

    def test_direct_object_create_pushes_via_the_receiver(self):
        """The five producer sites that bypass the classmethods still
        announce — the post_save receiver catches every save() path."""
        from alerts.models import Notification
        u = User.objects.create_user("push_u2")
        with patch("dashboard.consumers.push_eye_event") as pushed:
            Notification.objects.create(
                user=u, notification_type="portfolio", title="direct")
        pushed.assert_called_once()

    def test_bot_fills_push_silent(self):
        """Fills already raise their richer engine banner — the mirrored
        Notification row must move the badge but draw no second card."""
        from bot_program.notifications import dispatch_notification
        u = User.objects.create_user("push_u3")
        with patch("dashboard.consumers.push_eye_event") as pushed, \
             patch("bot_program.notifications._user_wants_bot_alerts",
                   return_value=True), \
             patch("bot_program.notifications._in_quiet_hours",
                   return_value=True):
            dispatch_notification(u, kind="bot_fill_open",
                                  title="t", body="b", url="/asset-bots/")
        self.assertTrue(pushed.called)
        self.assertTrue(pushed.call_args.args[2]["silent"])

    def test_a_broken_push_never_loses_the_row(self):
        from alerts.models import Notification
        u = User.objects.create_user("push_u4")
        with patch("dashboard.consumers.push_eye_event",
                   side_effect=RuntimeError("channel layer down")):
            Notification.create_for_user(u, "system", "still stored")
        self.assertTrue(Notification.objects.filter(
            user=u, title="still stored").exists())


class BannerMarkupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("banner_mk")

    def test_the_client_ships_the_contract(self):
        """The behavior the user asked for, pinned: a ~4s TTL, hover
        pause, a notification branch, and the live badge wiring."""
        self.client.force_login(self.user)
        html = self.client.get("/getting-started/").content.decode()
        self.assertIn("notification: 4000", html)
        self.assertIn("mouseenter", html)
        self.assertIn('kind === "notification"', html)
        self.assertIn("refreshNotifBadge", html)
        # The exit animation lives in the stylesheet, pinned by name.
        import pathlib
        from django.conf import settings
        css = (pathlib.Path(settings.BASE_DIR) / "static" / "css"
               / "sauron.css").read_text(encoding="utf-8")
        self.assertIn("svBannerOut", css)

    def test_panel_counts_carries_the_unread_total(self):
        from alerts.models import Notification
        Notification.create_for_user(self.user, "system", "one unread")
        self.client.force_login(self.user)
        data = self.client.get("/partials/panel-counts/").json()
        self.assertEqual(data["notifications"], 1)
