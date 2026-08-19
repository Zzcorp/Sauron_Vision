"""Live delivery must be able to say whether it is working.

The operator opened a trade and saw no banner, no badge movement and no
notification — everything appeared only after a refresh. The code path was
complete end to end: manual_trade pushes fill_open, the consumer relays it,
base.html renders it. What was missing was any way to tell a working pipe
from a broken one, because BOTH failure modes are silent — push_eye_event
swallows its exception and returns a False nobody reads, and a browser
whose socket never opened looks exactly like a quiet platform.

So: a self-test that sends a real event through the real pipe and reports
each half separately, a visible state on the bell, and a fallback poll so a
dead socket costs a few seconds of delay instead of the whole update.

Run with:  python manage.py test tests.test_live_delivery
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase


class SelfTestEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("live_u", password="x")
        self.client.force_login(self.user)

    def test_it_reports_a_successful_dispatch(self):
        with patch("dashboard.consumers.push_eye_event", return_value=True):
            r = self.client.post("/api/live/selftest/",
                                 HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["dispatched"])

    def test_it_reports_a_failed_dispatch_instead_of_pretending(self):
        """A push that could not reach the channel layer is the single most
        useful thing this endpoint can report, and the only thing the
        platform never said out loud."""
        with patch("dashboard.consumers.push_eye_event", return_value=False):
            r = self.client.post("/api/live/selftest/",
                                 HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertFalse(r.json()["dispatched"])

    def test_it_names_the_channel_layer_in_use(self):
        r = self.client.post("/api/live/selftest/",
                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        body = r.json()
        self.assertIn("layer", body)
        self.assertIn("layer_reachable", body)

    def test_an_in_memory_layer_is_called_out_not_called_healthy(self):
        """In-memory is per-process: a push from a Celery worker can never
        reach a browser attached to the web process, which is precisely the
        configuration that looks fine and delivers nothing."""
        from dashboard.views_livecheck import channel_layer_report
        report = channel_layer_report()
        if "InMemory" in report["backend"]:
            self.assertIn("in-memory", report["detail"])

    def test_it_is_post_only_and_login_required(self):
        self.assertEqual(self.client.get("/api/live/selftest/").status_code, 405)
        self.client.logout()
        self.assertEqual(
            self.client.post("/api/live/selftest/").status_code, 302)


class FallbackAndVisibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("live_v", password="x")
        self.client.force_login(self.user)

    def test_the_shell_reports_socket_state_and_polls_when_it_is_down(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            src = fh.read()
        # A visible state, not a console message.
        self.assertIn("is-offline", src)
        self.assertIn("window.svLive", src)
        # And the numbers keep moving without the socket.
        self.assertIn("pollTimer", src)
        self.assertIn("setLive(false)", src)

    def test_the_offline_mark_is_styled_for_both_themes(self):
        with open("static/css/sauron.css", encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn(".notif-bell.is-offline", css)
        self.assertIn("body.light-mode .notif-bell.is-offline", css)

    def test_the_settings_page_offers_the_test(self):
        r = self.client.get("/notifications/settings/", HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Send a test banner")
        self.assertContains(r, "/api/live/selftest/")


class FillStillPushesTests(TestCase):
    """The push itself, so a refactor cannot quietly remove the thing this
    whole diagnostic exists to observe."""

    def test_a_manual_trade_announces_its_fill(self):
        with open("bot_program/manual_trade.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('push_eye_event', src)
        self.assertIn('"fill_open"', src)

    def test_the_shell_renders_a_banner_for_a_fill(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('kind === "fill_open"', src)
