"""The Eye — admin presence view — and the middleware that feeds it.

Presence must be invisible to users (throttled, fenced, after the
response), and the Eye must be superuser-only: it shows addresses.

Run with:  python manage.py test tests.test_admin_eye
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase


def _mw():
    from core.presence import PresenceMiddleware
    return PresenceMiddleware(lambda r: HttpResponse("ok"))


def _req(path="/dashboard/", user=None, ip="9.9.9.9", **extra):
    req = RequestFactory().get(path, REMOTE_ADDR=ip,
                               HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) "
                                               "Chrome/126.0 Safari/537.36",
                               **extra)
    if user is not None:
        req.user = user
    return req


class PresenceMiddlewareTests(TestCase):
    def setUp(self):
        cache.clear()  # the throttle key must not leak between tests
        self.user = User.objects.create_user("pres_u", password="x")

    def test_an_authenticated_request_stamps_presence(self):
        from core.presence import UserPresence
        _mw()(_req(user=self.user))
        p = UserPresence.objects.get(user=self.user)
        self.assertEqual(p.last_ip, "9.9.9.9")
        self.assertEqual(p.last_path, "/dashboard/")
        self.assertIn("Chrome", p.user_agent)

    def test_writes_are_throttled(self):
        from core.presence import UserPresence
        _mw()(_req(user=self.user, path="/first/"))
        _mw()(_req(user=self.user, path="/second/"))
        self.assertEqual(UserPresence.objects.get(user=self.user).last_path,
                         "/first/", "second write inside the throttle window")

    def test_anonymous_requests_leave_no_row(self):
        from django.contrib.auth.models import AnonymousUser
        from core.presence import UserPresence
        _mw()(_req(user=AnonymousUser()))
        self.assertEqual(UserPresence.objects.count(), 0)

    def test_forwarded_for_takes_the_last_untrusted_hop(self):
        """Caddy fronts gunicorn — REMOTE_ADDR is the proxy and the client
        rides X-Forwarded-For. The LAST entry is what Caddy observed; the
        first is client-typed and forgeable, and must never be recorded."""
        from core.presence import UserPresence
        _mw()(_req(user=self.user, ip="172.18.0.2",
                   HTTP_X_FORWARDED_FOR="6.6.6.6, 8.8.4.4"))
        self.assertEqual(UserPresence.objects.get(user=self.user).last_ip,
                         "8.8.4.4")

    def test_a_presence_failure_never_breaks_the_page(self):
        with patch("core.presence.UserPresence.objects") as mock_qs:
            mock_qs.update_or_create.side_effect = RuntimeError("db down")
            resp = _mw()(_req(user=self.user))
        self.assertEqual(resp.status_code, 200)

    def test_forwarded_for_is_ignored_when_django_faces_the_client(self):
        """Without the Caddy front (dev runserver, direct exposure) the
        connection address is public and X-Forwarded-For is whatever the
        client typed — it must never be recorded."""
        from core.presence import UserPresence
        _mw()(_req(user=self.user, ip="8.8.4.4",
                   HTTP_X_FORWARDED_FOR="6.6.6.6"))
        self.assertEqual(UserPresence.objects.get(user=self.user).last_ip,
                         "8.8.4.4")


class GeoLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_private_addresses_never_hit_the_network(self):
        from core.presence import geo_for_ip
        with patch("requests.get") as mock_get:
            self.assertEqual(geo_for_ip("192.168.1.10"), "local network")
            self.assertEqual(geo_for_ip("127.0.0.1"), "local network")
        mock_get.assert_not_called()

    def test_lookup_is_cached_including_failures(self):
        # 8.8.8.8 / 1.1.1.1, not a documentation range: Python 3.12+
        # counts TEST-NET addresses as private, which is exactly what
        # _is_private should do — so the test must use real public space.
        from core.presence import geo_for_ip
        ok = MagicMock(ok=True)
        ok.json.return_value = {"city": "Paris", "country_name": "France"}
        with patch("requests.get", return_value=ok) as mock_get:
            self.assertEqual(geo_for_ip("8.8.8.8"), "Paris, France")
            self.assertEqual(geo_for_ip("8.8.8.8"), "Paris, France")
        self.assertEqual(mock_get.call_count, 1, "second call must be cached")

        with patch("requests.get", side_effect=OSError("down")) as mock_get:
            self.assertEqual(geo_for_ip("1.1.1.1"), "")
            self.assertEqual(geo_for_ip("1.1.1.1"), "")
        self.assertEqual(mock_get.call_count, 1,
                         "a dead geo service must be cached too")

    def test_cached_only_never_touches_the_network(self):
        """The Eye's render path passes cached_only=True — a geo outage
        must cost the page nothing."""
        from core.presence import geo_for_ip
        with patch("requests.get") as mock_get:
            self.assertEqual(geo_for_ip("8.8.8.8", cached_only=True), "")
        mock_get.assert_not_called()

    def test_a_dead_cache_backend_does_not_raise(self):
        """Production cache is Redis; the monitoring page must not 500
        during the exact outage it exists to observe."""
        from core.presence import geo_for_ip
        with patch("django.core.cache.cache.get",
                   side_effect=RuntimeError("redis down")):
            self.assertEqual(geo_for_ip("8.8.8.8", cached_only=True), "")

    def test_device_label_is_human_sized(self):
        from core.presence import device_label
        self.assertEqual(device_label(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            "Chrome · Windows")
        self.assertEqual(device_label(""), "—")


class AdminEyeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("eye_admin", password="x")
        cls.user = User.objects.create_user("eye_user", password="x")

    def setUp(self):
        cache.clear()

    def test_superuser_sees_the_eye(self):
        self.client.force_login(self.admin)
        resp = self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "eye_user")
        self.assertContains(resp, "ONLINE NOW")
        self.assertContains(resp, "hq-divisions")

    def test_normal_users_are_refused(self):
        self.client.force_login(self.user)
        resp = self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_users_are_bounced_to_login(self):
        resp = self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)

    def test_the_admin_own_visit_shows_up_as_presence(self):
        """The middleware stamps AFTER the response is built, so the very
        first page view cannot see itself — the second one can."""
        self.client.force_login(self.admin)
        self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        resp = self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        self.assertContains(resp, "● ONLINE")

    def test_capital_and_trade_columns_aggregate(self):
        from decimal import Decimal
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="starter_crypto",
            symbols=["BTCUSD"], enabled=True, capital=Decimal("12345"))
        self.client.force_login(self.admin)
        resp = self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        self.assertContains(resp, "$12345")

    def test_close_pending_counts_as_live_exposure(self):
        """CLOSE_PENDING is a position the broker still holds — every
        exposure count on the platform includes it, and the Eye must not
        under-report it to the operator."""
        from decimal import Decimal
        from django.utils import timezone
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="starter_crypto2",
            symbols=["BTCUSD"], enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("0.1"), entry_price=Decimal("60000"),
            status="CLOSE_PENDING", paper=True, rule_name="r",
            opened_at=timezone.now())
        self.client.force_login(self.admin)
        resp = self.client.get("/admin-dashboard/eye/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.context["metrics"]["open_trades"], 1)

    def test_geo_endpoint_is_superuser_only_and_returns_json(self):
        from core.presence import UserPresence
        from django.utils import timezone
        UserPresence.objects.create(user=self.user, last_seen=timezone.now(),
                                    last_ip="192.168.0.9")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(
            "/admin-dashboard/eye/geo/", HTTP_HOST="127.0.0.1").status_code,
            403)
        self.client.force_login(self.admin)
        resp = self.client.get("/admin-dashboard/eye/geo/",
                               HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("geo", resp.json())


class DivisionNavEverywhereTests(TestCase):
    """The division cards must appear on EVERY admin page — Health shipped
    without them and the only way back was the browser."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("nav_admin", password="x")

    def test_every_admin_division_carries_the_nav(self):
        self.client.force_login(self.admin)
        for url in ("/admin-dashboard/", "/admin-dashboard/system-map/",
                    "/health/", "/admin-dashboard/eye/"):
            resp = self.client.get(url, HTTP_HOST="127.0.0.1")
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, "hq-divisions", msg_prefix=url)
            self.assertContains(resp, 'href="/admin-dashboard/eye/"',
                                msg_prefix=url)
