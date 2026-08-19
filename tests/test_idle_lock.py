"""The idle PIN lock: a server flag, not a client decoration.

The platform treats the PIN as a server-verified second factor everywhere
— login gate, bot arming, kill switch. An idle lock that lived only in
the browser would be the one PIN gate dismissible from devtools, so the
lock is a session flag (`pin_locked`) enforced by
core.idle_lock.IdleLockMiddleware:

* JSON/XHR answers 423 while locked; page GETs render pre-locked; other
  POSTs bounce back to the page as a GET.
* The flag engages client-side (POST /api/session/lock/) AND server-side
  as a backstop when the session's activity gap exceeds the profile's
  window — a tab whose JS died still locks.
* Only /api/session/unlock/ with the correct PIN clears it; five wrong
  guesses end the session, because a 4-digit PIN is 10,000 combinations
  and an unlimited-attempt lock screen would be the weakest gate here.
* Users without a PIN are NEVER locked — nothing could release the lock.

Run with:  python manage.py test tests.test_idle_lock
"""
import time

from django.contrib.auth.models import User
from django.test import TestCase

from portfolio.trader_profile import TraderProfile, get_or_create_profile

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
HOST = {"HTTP_HOST": "127.0.0.1"}


def make_user(username="il_u", pin="4321", enabled=True, minutes=10):
    user = User.objects.create_user(username=username, password="x")
    prof = get_or_create_profile(user)
    if pin:
        prof.set_pin(pin)
    prof.idle_lock_enabled = enabled
    prof.idle_lock_minutes = minutes
    prof.save()
    return user


class MiddlewareBackstopTests(TestCase):
    """The server-side gap check — the lock that works with the JS dead."""

    def _age_session(self, seconds):
        s = self.client.session
        s["sv_last_seen"] = int(time.time()) - seconds
        s.save()

    def test_locks_after_the_configured_idle_gap(self):
        self.client.force_login(make_user())
        self._age_session(11 * 60)  # window is 10 minutes
        r = self.client.get("/signals/", **HOST)
        # Locked on the same request that noticed the gap — no free page.
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/locked/"))
        self.assertTrue(self.client.session.get("pin_locked"))

    def test_an_active_session_is_left_alone(self):
        self.client.force_login(make_user(username="il_active"))
        self._age_session(60)
        self.client.get("/signals/", **HOST)
        self.assertNotIn("pin_locked", self.client.session)

    def test_backstop_and_enforcement_land_in_the_same_request(self):
        """A locked-by-gap JSON request must not get one free answer."""
        self.client.force_login(make_user(username="il_json"))
        self._age_session(11 * 60)
        r = self.client.get("/api/live/health/", **AJAX)
        self.assertEqual(r.status_code, 423)
        self.assertTrue(r.json()["pin_locked"])

    def test_users_without_a_pin_are_never_locked(self):
        """No PIN means nothing could ever release the lock — engaging it
        would be denial of service, not security."""
        self.client.force_login(make_user(username="il_nopin", pin=None))
        self._age_session(24 * 3600)
        r = self.client.get("/signals/", **HOST)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("pin_locked", self.client.session)

    def test_disabled_setting_is_honoured(self):
        self.client.force_login(make_user(username="il_off", enabled=False))
        self._age_session(24 * 3600)
        self.client.get("/signals/", **HOST)
        self.assertNotIn("pin_locked", self.client.session)

    def test_the_first_request_seeds_the_activity_clock(self):
        """A fresh session has no sv_last_seen; without seeding it the gap
        would be unmeasurable forever."""
        self.client.force_login(make_user(username="il_seed"))
        self.client.get("/signals/", **HOST)
        self.assertIn("sv_last_seen", self.client.session)

    def test_health_poll_does_not_stamp_activity(self):
        """The 10s background poll would otherwise keep an abandoned tab's
        session 'active' forever — the exact hole the lock exists to close."""
        self.client.force_login(make_user(username="il_poll"))
        stale = int(time.time()) - 120  # old enough to re-stamp, too young to lock
        s = self.client.session
        s["sv_last_seen"] = stale
        s.save()
        self.client.get("/api/live/health/", **AJAX)
        self.assertEqual(self.client.session["sv_last_seen"], stale)
        # A real page view IS activity and moves the clock.
        self.client.get("/signals/", **HOST)
        self.assertGreater(self.client.session["sv_last_seen"], stale)


class LockedEnforcementTests(TestCase):
    """What the pin_locked flag actually means, request by request."""

    def setUp(self):
        self.user = make_user(username="il_locked")
        self.client.force_login(self.user)
        s = self.client.session
        s["pin_locked"] = True
        s.save()

    def test_json_requests_answer_423(self):
        r = self.client.get("/api/live/health/", **AJAX)
        self.assertEqual(r.status_code, 423)
        self.assertEqual(r.json(), {"pin_locked": True})

    def test_api_paths_answer_423_even_without_xhr_headers(self):
        """The health poll's fetch() sends neither X-Requested-With nor an
        Accept worth reading — an API answering HTML while locked would be
        a data leak, not a courtesy."""
        r = self.client.get("/api/live/health/")
        self.assertEqual(r.status_code, 423)

    def test_page_gets_go_to_the_lock_screen(self):
        """Passing pages through was only safe for the app shell, which
        paints its own gate — /admin/ and the PDF reports extend nothing
        and would have rendered in full behind a "locked" screen."""
        r = self.client.get("/signals/", **HOST)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/locked/?next="))
        self.assertIn("signals", r["Location"])

    def test_the_django_admin_is_not_readable_while_locked(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        r = self.client.get("/admin/", **HOST)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/locked/"))

    def test_the_lock_screen_itself_renders_and_carries_no_data(self):
        r = self.client.get("/locked/?next=/signals/", **HOST)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SECOND GATE")
        self.assertContains(r, "data-lk-pin")
        # Standalone: none of the app shell's live regions come with it.
        self.assertNotContains(r, "signalRail")

    def test_the_lock_screen_refuses_to_bounce_off_site(self):
        r = self.client.get("/locked/?next=https://evil.example/", **HOST)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "evil.example")

    def test_the_lock_screen_steps_aside_once_unlocked(self):
        session = self.client.session
        session.pop("pin_locked")
        session.save()
        r = self.client.get("/locked/?next=/signals/", **HOST)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/signals/")

    def test_posts_bounce_to_the_lock_screen(self):
        """No state may change from behind the lock — and the operator
        sees WHY instead of getting a silently blank form back."""
        r = self.client.post("/profile/", {"display_name": "smuggled"}, **HOST)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/locked/"))
        self.assertNotEqual(
            TraderProfile.objects.get(user=self.user).display_name, "smuggled")

    def test_allowlisted_paths_stay_reachable(self):
        """The ways OUT — logout, the wall, health probes — must never sit
        behind the gate, or a locked-out operator has no move left."""
        self.assertEqual(self.client.get("/healthz/", **HOST).status_code, 200)
        # The wall view itself bounces logged-in users home (302) — the
        # point here is that the middleware answered with the view's own
        # behaviour, not with a 423.
        self.assertIn(self.client.get("/wall/", **HOST).status_code, (200, 302))
        r = self.client.post("/logout/", **HOST)
        self.assertEqual(r.status_code, 302)

    def test_locked_polling_never_unidles_the_session(self):
        """A locked tab keeps polling; if that stamped activity, the lock
        would hold its own door open."""
        stale = int(time.time()) - 3600
        s = self.client.session
        s["sv_last_seen"] = stale
        s.save()
        self.client.get("/signals/", **HOST)
        self.assertEqual(self.client.session["sv_last_seen"], stale)


class LockUnlockEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user(username="il_ep")
        self.client.force_login(self.user)

    def _lock(self):
        s = self.client.session
        s["pin_locked"] = True
        s.save()

    def test_lock_endpoint_sets_the_flag_and_is_idempotent(self):
        for _ in range(2):
            r = self.client.post("/api/session/lock/", **AJAX)
            self.assertEqual(r.status_code, 204)
            self.assertTrue(self.client.session.get("pin_locked"))

    def test_lock_endpoint_refuses_a_pinless_lockout(self):
        """A user with no PIN locked behind a PIN prompt could never get
        back in short of logging out — so the flag must not engage."""
        self.client.force_login(make_user(username="il_ep_nopin", pin=None))
        r = self.client.post("/api/session/lock/", **AJAX)
        self.assertEqual(r.status_code, 204)
        self.assertNotIn("pin_locked", self.client.session)

    def test_correct_pin_unlocks_and_audits(self):
        from core.audit import AuditLog
        self._lock()
        r = self.client.post("/api/session/unlock/", {"pin": "4321"}, **AJAX)
        self.assertEqual(r.json()["status"], "ok")
        self.assertNotIn("pin_locked", self.client.session)
        self.assertTrue(AuditLog.objects.filter(
            user=self.user, description__icontains="Idle lock released").exists())
        # The session survived — this is a flag, not a re-login.
        self.assertEqual(self.client.get("/signals/", **HOST).status_code, 200)

    def test_wrong_pin_counts_down_the_attempts(self):
        self._lock()
        r = self.client.post("/api/session/unlock/", {"pin": "0000"}, **AJAX)
        self.assertEqual(r.json()["status"], "error")
        self.assertEqual(r.json()["attempts_left"], 4)
        r = self.client.post("/api/session/unlock/", {"pin": "1111"}, **AJAX)
        self.assertEqual(r.json()["attempts_left"], 3)
        self.assertTrue(self.client.session.get("pin_locked"))

    def test_a_correct_pin_resets_the_attempt_counter(self):
        self._lock()
        self.client.post("/api/session/unlock/", {"pin": "0000"}, **AJAX)
        self.client.post("/api/session/unlock/", {"pin": "4321"}, **AJAX)
        self._lock()
        r = self.client.post("/api/session/unlock/", {"pin": "0000"}, **AJAX)
        self.assertEqual(r.json()["attempts_left"], 4)

    def test_the_fifth_failure_ends_the_session(self):
        """10,000 combinations at 4 digits: the lock screen must not be
        the one place on the platform a PIN can be brute-forced."""
        self._lock()
        for _ in range(4):
            r = self.client.post("/api/session/unlock/", {"pin": "0000"}, **AJAX)
            self.assertEqual(r.json()["status"], "error")
        r = self.client.post("/api/session/unlock/", {"pin": "0000"}, **AJAX)
        self.assertEqual(r.json()["status"], "logged_out")
        # The session is gone: a page now redirects to the login wall.
        self.assertEqual(self.client.get("/signals/", **HOST).status_code, 302)


class ProfileSettingsPersistenceTests(TestCase):
    """The idle-lock settings ride the same flat profile POST as
    everything else on the page."""

    FORM = {
        "email": "x@y.z", "first_name": "", "last_name": "",
        "display_name": "", "bio": "", "location": "", "phone": "",
        "timezone_preference": "UTC",
        "experience_level": "intermediate", "trading_style": "swing_trader",
        "risk_appetite": "moderate", "analysis_approach": "mixed",
        "preferred_session": "european", "available_hours_per_day": "2",
        "monthly_return_target_pct": "3", "max_acceptable_drawdown_pct": "10",
        "annual_income_target": "0",
        "ai_autonomy": "suggest", "ai_commentary_detail": "detailed",
        "notify_channel": "telegram",
        "max_usd_theme_exposure": "3", "max_equity_theme_exposure": "3",
    }

    def test_post_persists_the_idle_lock_fields(self):
        u = make_user(username="il_form")
        self.client.force_login(u)
        self.client.post("/profile/", dict(
            self.FORM, idle_lock_enabled="on", idle_lock_minutes="30"), **HOST)
        p = TraderProfile.objects.get(user=u)
        self.assertTrue(p.idle_lock_enabled)
        self.assertEqual(p.idle_lock_minutes, 30)

    def test_post_without_the_checkbox_disables_the_lock(self):
        u = make_user(username="il_form_off")
        self.client.force_login(u)
        self.client.post("/profile/", dict(
            self.FORM, idle_lock_minutes="15"), **HOST)
        p = TraderProfile.objects.get(user=u)
        self.assertFalse(p.idle_lock_enabled)
        self.assertEqual(p.idle_lock_minutes, 15)

    def test_a_tampered_minutes_value_is_rejected(self):
        """Only the choice list is accepted — a crafted POST must not set
        a 0-minute (permanent lock) or 9999-minute (never) window."""
        u = make_user(username="il_form_bad", minutes=10)
        self.client.force_login(u)
        self.client.post("/profile/", dict(
            self.FORM, idle_lock_enabled="on", idle_lock_minutes="7"), **HOST)
        self.assertEqual(
            TraderProfile.objects.get(user=u).idle_lock_minutes, 10)


class OverlayMarkupTests(TestCase):
    """The gate ships in the authenticated shell and pre-opens when the
    session is already locked — no unlocked flash before the JS runs."""

    def test_the_authenticated_shell_carries_the_gate(self):
        self.client.force_login(make_user(username="il_shell"))
        body = self.client.get("/signals/", **HOST).content.decode("utf-8", "replace")
        self.assertIn('id="idleLockOverlay"', body)
        self.assertIn("data-sv-persist", body)      # Escape must not dismiss it
        self.assertIn('data-sv-backdrop="none"', body)  # it is its own scrim
        self.assertIn("js/idle-lock.js", body)
        self.assertIn('data-il-has-pin="1"', body)
        self.assertIn('data-il-locked="0"', body)
        # The recovery path is logout → login-time PIN reset, so the card
        # must offer the way out.
        self.assertIn("PIN forgotten?", body)

    def test_a_locked_session_is_sent_to_the_standalone_gate(self):
        """The in-page overlay covers the page you were ALREADY on, so
        your chart and half-typed form survive. A navigation while locked
        is a different thing: it gets the dataless lock screen."""
        self.client.force_login(make_user(username="il_pre"))
        s = self.client.session
        s["pin_locked"] = True
        s.save()
        r = self.client.get("/signals/", **HOST)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/locked/"))
        body = self.client.get("/locked/", **HOST).content.decode("utf-8", "replace")
        self.assertIn("data-lk-pin", body)

    def test_the_public_wall_has_no_gate(self):
        body = self.client.get("/wall/", **HOST).content.decode("utf-8", "replace")
        self.assertNotIn("idleLockOverlay", body)


class MigrationTests(TestCase):
    def test_the_migration_is_in_the_graph_with_house_naming(self):
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(connection)
        self.assertIn(("portfolio", "0010_traderprofile_idle_lock"),
                      loader.graph.nodes)

    def test_field_defaults_lock_on_at_ten_minutes(self):
        """Existing rows must come out of the migration with the lock ON —
        a security feature that ships disabled protects nobody — but it
        still only engages for users who actually hold a PIN."""
        prof = get_or_create_profile(
            User.objects.create_user(username="il_defaults"))
        self.assertTrue(prof.idle_lock_enabled)
        self.assertEqual(prof.idle_lock_minutes, 10)
