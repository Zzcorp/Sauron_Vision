"""Defects the adversarial review caught in the PIN wave before it shipped.

Each class here corresponds to one confirmed finding. They are separate
from tests/test_login_pin_gate.py and tests/test_idle_lock.py because
they are regression pins for specific ways the wave was WRONG, not
descriptions of the features themselves.

Run with:  python manage.py test tests.test_pin_wave_review
"""
from django.contrib.auth.models import User
from django.test import TestCase

from core import security
from portfolio.trader_profile import get_or_create_profile

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def _pin_user(username="rev_u", password="correct-horse", pin="4321"):
    user = User.objects.create_user(username=username, password=password)
    prof = get_or_create_profile(user)
    prof.set_pin(pin)
    prof.save()
    return user


class ThrottleSpeaksJsonTests(TestCase):
    """A throttled gate answered HTML; the overlay parsed "no message",
    showed "Invalid PIN" and WIPED the pad — so the operator retried a
    correct PIN forever against a closed gate."""

    def setUp(self):
        security._login_attempts.clear()
        self.user = _pin_user()

    def _exhaust(self, path, payload):
        for _ in range(5):
            self.client.post(path, payload, **AJAX)

    def test_ajax_throttle_answers_json_429_with_the_real_reason(self):
        self._exhaust("/login/pin/", {"pin": "0000"})
        r = self.client.post("/login/pin/", {"pin": "4321"}, **AJAX)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertIn("Too many", r.json()["message"])

    def test_plain_browser_still_gets_the_html_refusal(self):
        self._exhaust("/login/", {"username": "rev_u", "password": "x"})
        r = self.client.post("/login/", {"username": "rev_u", "password": "x"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(b"Too many", r.content)

    def test_the_overlay_keeps_the_pin_on_a_throttle(self):
        # The client half of the same defect: only a non-429 failure clears.
        with open("templates/landing/the_wall.html", encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("if (res.status !== 429) pinClear();", body)


class ThrottleIpTrustTests(TestCase):
    """The limiter believed X-Forwarded-For unconditionally, so an
    attacker minted a fresh 5-attempt budget per request — against a
    4-digit PIN that is the whole brute-force defence."""

    def setUp(self):
        security._login_attempts.clear()
        _pin_user("ip_u")

    def test_spoofed_forwarded_header_cannot_mint_new_budgets(self):
        # Django facing the client directly (dev runserver, or a deploy
        # without the proxy): REMOTE_ADDR is public, so X-Forwarded-For is
        # whatever the attacker typed and must not key the bucket.
        # A genuinely routable address: Python's ipaddress counts the
        # 203.0.113.0/24 documentation range as private, which would put
        # this request back in the trusted-proxy case.
        for i in range(6):
            r = self.client.post(
                "/login/pin/", {"pin": "0000"}, REMOTE_ADDR="8.8.8.8",
                HTTP_X_FORWARDED_FOR=f"9.9.9.{i}", **AJAX)
        self.assertEqual(r.status_code, 429)

    def test_behind_the_proxy_each_real_client_keeps_its_own_budget(self):
        # A private REMOTE_ADDR means Caddy, which REPLACES the header with
        # the address it observed — there the header is the truth, and one
        # throttled operator must not lock out everyone behind the proxy.
        for _ in range(6):
            self.client.post("/login/pin/", {"pin": "0000"},
                             REMOTE_ADDR="127.0.0.1",
                             HTTP_X_FORWARDED_FOR="198.51.100.4", **AJAX)
        blocked = self.client.post("/login/pin/", {"pin": "0000"},
                                   REMOTE_ADDR="127.0.0.1",
                                   HTTP_X_FORWARDED_FOR="198.51.100.4", **AJAX)
        other = self.client.post("/login/pin/", {"pin": "0000"},
                                 REMOTE_ADDR="127.0.0.1",
                                 HTTP_X_FORWARDED_FOR="198.51.100.9", **AJAX)
        self.assertEqual(blocked.status_code, 429)
        self.assertNotEqual(other.status_code, 429)


class ForgotPinModalTests(TestCase):
    """Arriving from "I forgot my PIN", the modal still asked for the
    current PIN — the exact value the user just said they don't know."""

    def setUp(self):
        self.user = _pin_user("forgot_u")
        self.client.force_login(self.user)

    def test_modal_asks_for_the_current_pin_normally(self):
        r = self.client.get("/htmx/profile/pin-modal/")
        self.assertContains(r, "CURRENT PIN")

    def test_modal_waives_and_explains_after_a_verified_reset(self):
        session = self.client.session
        session["force_pin_reset"] = True
        session.save()
        r = self.client.get("/htmx/profile/pin-modal/")
        self.assertNotContains(r, "CURRENT PIN")
        self.assertContains(r, "IDENTITY CONFIRMED")


class LockedDataPathTests(TestCase):
    """The lock 423s JSON, but the live-data partials are fetched with no
    XHR header at all — they streamed signals, ticker rows and position
    counts to a locked tab."""

    def setUp(self):
        self.user = _pin_user("locked_u")
        self.client.force_login(self.user)
        session = self.client.session
        session["pin_locked"] = True
        session.save()

    def test_partials_are_refused_while_locked(self):
        for path in ("/partials/panel-counts/", "/partials/signal-rail/",
                     "/partials/ticker/"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 423, path)
                self.assertTrue(r.json()["pin_locked"])

    def test_the_way_out_is_still_open(self):
        r = self.client.get("/wall/")
        self.assertNotEqual(r.status_code, 423)


class KeepAliveTests(TestCase):
    """Reading a chart for ten minutes is not idleness, but it sends no
    HTTP request — the server's clock went stale and the backstop locked
    an operator who had never stopped working."""

    def setUp(self):
        self.user = _pin_user("ping_u")
        self.client.force_login(self.user)

    def test_ping_refreshes_the_server_side_activity_clock(self):
        import time as _time

        session = self.client.session
        stale = int(_time.time()) - 400
        session["sv_last_seen"] = stale
        session.save()
        r = self.client.post("/api/session/ping/", **AJAX)
        self.assertEqual(r.status_code, 204)
        self.assertGreater(self.client.session["sv_last_seen"], stale)
        self.assertNotIn("pin_locked", self.client.session)

    def test_ping_is_refused_once_the_lock_is_on(self):
        # That refusal is how a second tab discovers the lock.
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        r = self.client.post("/api/session/ping/", **AJAX)
        self.assertEqual(r.status_code, 423)

    def test_a_ping_cannot_outrun_the_users_own_window(self):
        """The tab only pings while it SEES activity; a gap past the
        window still locks (the backstop runs before the stamp)."""
        import time as _time

        prof = get_or_create_profile(self.user)
        prof.idle_lock_minutes = 5
        prof.idle_lock_enabled = True
        prof.save()
        session = self.client.session
        session["sv_last_seen"] = int(_time.time()) - 400
        session.save()
        r = self.client.post("/api/session/ping/", **AJAX)
        self.assertEqual(r.status_code, 423)


class MachineTrafficTests(TestCase):
    """An unattended tab renewed itself all day: the WebSocket-driven
    partial refreshes counted as human activity, so on a busy market the
    lock never engaged at all."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = _pin_user("machine_u")
        prof = get_or_create_profile(self.user)
        prof.idle_lock_minutes = 5
        prof.save()
        self.client.force_login(self.user)

    def _set_gap(self, seconds):
        import time as _time

        session = self.client.session
        session["sv_last_seen"] = int(_time.time()) - seconds
        session.save()

    def test_machine_polls_do_not_hold_the_session_open(self):
        self._set_gap(120)
        before = self.client.session["sv_last_seen"]
        for path in ("/api/live/health/", "/partials/ticker/",
                     "/partials/panel-counts/"):
            self.client.get(path)
        self.assertEqual(self.client.session["sv_last_seen"], before)

    def test_a_real_page_visit_still_counts(self):
        self._set_gap(120)
        before = self.client.session["sv_last_seen"]
        self.client.get("/signals/")
        self.assertGreater(self.client.session["sv_last_seen"], before)

    def test_an_unattended_tab_locks_even_while_its_feeds_chatter(self):
        self._set_gap(400)
        r = self.client.get("/partials/ticker/")
        self.assertEqual(r.status_code, 423)
        self.assertTrue(self.client.session["pin_locked"])


class LockConfigCacheTests(TestCase):
    """The backstop re-read the profile on every request for the whole
    idle stretch — six queries a minute from the health poll alone, and
    forever for anyone who had switched the lock off."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = _pin_user("cfg_u")
        self.client.force_login(self.user)

    def test_the_config_is_read_once_per_window_not_per_request(self):
        import time as _time

        session = self.client.session
        session["sv_last_seen"] = int(_time.time()) - 400
        session.save()
        # Lock disabled: the gap stays wide, so every request would have
        # re-queried without the cache.
        prof = get_or_create_profile(self.user)
        prof.idle_lock_enabled = False
        prof.save()
        from core.idle_lock import IdleLockMiddleware
        IdleLockMiddleware._should_lock(self.user, 400)   # primes the cache
        with self.assertNumQueries(0):
            for _ in range(5):
                IdleLockMiddleware._should_lock(self.user, 400)

    def test_saving_the_profile_drops_the_cached_config(self):
        from django.core.cache import cache

        from core.idle_lock import IdleLockMiddleware
        prof = get_or_create_profile(self.user)
        prof.idle_lock_enabled = False
        prof.save()
        self.assertFalse(IdleLockMiddleware._should_lock(self.user, 999))
        prof.idle_lock_enabled = True
        prof.idle_lock_minutes = 5
        prof.save()   # must invalidate, or the lock stays off for a minute
        self.assertIsNone(cache.get(f"idlelock:cfg:{self.user.pk}"))
        self.assertTrue(IdleLockMiddleware._should_lock(self.user, 999))


class LockedSocketTests(TestCase):
    """WebSockets never meet HTTP middleware: quotes, fills and signals
    kept streaming to a locked tab — the one feed the lock missed."""

    def test_consumers_refuse_a_locked_session(self):
        from asgiref.sync import async_to_sync

        from dashboard.consumers import _session_pin_locked
        self.assertTrue(async_to_sync(_session_pin_locked)(
            {"session": {"pin_locked": True}}))
        self.assertFalse(async_to_sync(_session_pin_locked)(
            {"session": {}}))
        # A session backend that raises must not take the socket down.
        self.assertFalse(async_to_sync(_session_pin_locked)({}))

    def test_both_consumers_check_before_accepting(self):
        with open("dashboard/consumers.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertEqual(src.count("await _session_pin_locked(self.scope)"), 2)

    def test_an_already_open_eye_socket_is_cut_from_the_server(self):
        """Connect-time refusal only covers NEW sockets; the one already
        streaming an operator's fills has to be closed, not asked."""
        from asgiref.sync import async_to_sync

        from dashboard.consumers import EyeConsumer
        closed = {"n": 0}
        consumer = EyeConsumer()
        consumer.close = lambda *a, **k: _noop_async(closed)
        consumer.send = lambda *a, **k: _noop_async({"n": 0})
        async_to_sync(consumer.eye_event)({"kind": "session_locked", "data": {}})
        self.assertEqual(closed["n"], 1)

    def test_locking_tells_the_socket_to_go(self):
        from unittest.mock import patch

        user = _pin_user("sock_u")
        self.client.force_login(user)
        with patch("dashboard.consumers.push_eye_event") as pushed:
            r = self.client.post("/api/session/lock/", **AJAX)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(pushed.call_args.args[1], "session_locked")


async def _noop_async(counter):
    counter["n"] += 1


class KeyboardReachabilityTests(TestCase):
    """Enter was swallowed for every element while pin-mode was on, so a
    keyboard-only operator could reach "PIN forgotten?" but never
    activate it — trapped on the gate."""

    def test_router_lets_enter_through_for_links_and_buttons(self):
        for path in ("templates/landing/the_wall.html",
                     "templates/registration/login_pin.html"):
            with self.subTest(path=path):
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                self.assertIn("closest('a, button')", body)

    def test_enter_below_the_minimum_is_not_silent(self):
        with open("templates/landing/the_wall.html", encoding="utf-8") as fh:
            body = fh.read()
        # submitPin() owns the "at least 4 digits" message; the router
        # used to guard the call and swallow the keypress instead.
        self.assertNotIn("if (pinValue().length >= PIN_MIN) submitPin();", body)

    def test_a_pasted_pin_is_spread_across_the_boxes(self):
        for path in ("templates/landing/the_wall.html",
                     "templates/registration/login_pin.html"):
            with self.subTest(path=path):
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                self.assertIn("'paste'", body)

    def test_reentering_the_gate_starts_from_a_clean_pad(self):
        with open("templates/landing/the_wall.html", encoding="utf-8") as fh:
            body = fh.read()
        gate = body.split("classList.add('pin-mode')")[1][:1200]
        self.assertIn("pinClear();", gate)
        self.assertIn("hideError(pinErrors);", gate)
