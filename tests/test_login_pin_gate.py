"""The login PIN gate: what must hold for an operator to actually get in.

The second gate had three ways to lock a legitimate user out for good:

* Focus stayed in the now-invisible password field when the PIN overlay
  appeared, so the typed PIN corrupted the password and Enter re-submitted
  the credentials form — with the error rendered into an element that is
  opacity:0 while pin-mode is on. (Client fix; the template contract for it
  is pinned here.)
* The overlay rendered exactly 4 boxes while the PIN policy allows 4-8
  digits — a 5+ digit PIN could never pass the gate.
* change_pin requires the current PIN and login requires the PIN, so a
  forgotten PIN was circular with no way out. login_pin_forgot breaks the
  circle by re-verifying the password of the pending user.

/login/pin/ was also unthrottled: a 4-digit PIN is 10,000 guesses, which
made the second gate the weakest link. The rate limiter now covers it.

Run with:  python manage.py test tests.test_login_pin_gate
"""
from django.contrib.auth.models import User
from django.test import TestCase

from core import security
from portfolio.trader_profile import get_or_create_profile

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
PENDING_KEY = "sauron_pending_user_id"


def make_pin_user(username="gate_u", password="correct-horse", pin="4321"):
    user = User.objects.create_user(username=username, password=password)
    prof = get_or_create_profile(user)
    prof.set_pin(pin)
    prof.save()
    return user


class PinRequiredFlowTests(TestCase):
    """The two-step AJAX flow the wall's overlay drives."""

    def setUp(self):
        # The rate limiter's bucket is module-global and would otherwise
        # accumulate attempts across every test in this file.
        security._login_attempts.clear()
        self.user = make_pin_user()

    def _pending(self):
        r = self.client.post(
            "/login/", {"username": "gate_u", "password": "correct-horse"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        return r

    def test_correct_credentials_signal_pin_required_without_logging_in(self):
        r = self._pending()
        self.assertEqual(r.json()["status"], "pin_required")
        self.assertEqual(r.json()["username"], "gate_u")
        # First gate alone must NOT create an authenticated session.
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.session.get(PENDING_KEY), self.user.id)

    def test_correct_pin_completes_the_login(self):
        self._pending()
        r = self.client.post("/login/pin/", {"pin": "4321"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertIn("_auth_user_id", self.client.session)
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_wrong_pin_is_refused_and_does_not_log_in(self):
        self._pending()
        r = self.client.post("/login/pin/", {"pin": "0000"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["status"], "error")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_pin_post_without_pending_session_is_rejected(self):
        r = self.client.post("/login/pin/", {"pin": "4321"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Session expired", r.json()["message"])

    def test_non_ajax_flow_redirects_to_the_standalone_pin_page(self):
        r = self.client.post(
            "/login/", {"username": "gate_u", "password": "correct-horse"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/pin/", r["Location"])
        page = self.client.get("/login/pin/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "gate_u")


class LongPinTests(TestCase):
    """The policy allows 4-8 digit PINs (views_profile_modals enforces it),
    so a 5+ digit PIN must be able to pass the gate end-to-end. The old
    overlay hard-rendered exactly 4 boxes, making such PINs unusable."""

    def setUp(self):
        security._login_attempts.clear()

    def test_a_five_digit_pin_user_can_log_in_end_to_end(self):
        make_pin_user(username="five_u", pin="12345")
        r = self.client.post(
            "/login/", {"username": "five_u", "password": "correct-horse"}, **AJAX)
        self.assertEqual(r.json()["status"], "pin_required")
        r = self.client.post("/login/pin/", {"pin": "12345"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertIn("_auth_user_id", self.client.session)

    def test_an_eight_digit_pin_user_can_log_in_end_to_end(self):
        make_pin_user(username="eight_u", pin="12345678")
        self.client.post(
            "/login/", {"username": "eight_u", "password": "correct-horse"}, **AJAX)
        r = self.client.post("/login/pin/", {"pin": "12345678"}, **AJAX)
        self.assertEqual(r.json()["status"], "ok")


class PinThrottleTests(TestCase):
    """/login/pin/ and /login/pin/forgot/ accept a credential, so they get
    the same 5-attempts-per-5-minutes window as /login/ — but in their own
    per-path bucket, so the normal login+PIN sequence never self-throttles."""

    def setUp(self):
        security._login_attempts.clear()
        make_pin_user()
        self.client.post(
            "/login/", {"username": "gate_u", "password": "correct-horse"}, **AJAX)

    def test_pin_guessing_is_rate_limited_after_five_attempts(self):
        for _ in range(5):
            r = self.client.post("/login/pin/", {"pin": "0000"}, **AJAX)
            self.assertEqual(r.status_code, 400)
        r = self.client.post("/login/pin/", {"pin": "0000"}, **AJAX)
        # 429 with a JSON body: the overlay reads JSON, and an HTML
        # refusal surfaced to the operator as "Invalid PIN".
        self.assertEqual(r.status_code, 429)
        self.assertIn(b"Too many login attempts", r.content)

    def test_pin_bucket_does_not_consume_the_password_bucket(self):
        for _ in range(6):
            self.client.post("/login/pin/", {"pin": "0000"}, **AJAX)
        # /login/ has only seen one POST (setUp) — it must still answer.
        r = self.client.post(
            "/login/", {"username": "gate_u", "password": "correct-horse"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "pin_required")

    def test_forgot_endpoint_is_rate_limited_too(self):
        for _ in range(5):
            r = self.client.post("/login/pin/forgot/", {"password": "nope"}, **AJAX)
            self.assertEqual(r.status_code, 400)
        r = self.client.post("/login/pin/forgot/", {"password": "nope"}, **AJAX)
        self.assertEqual(r.status_code, 429)


class ForgotPinTests(TestCase):
    """login_pin_forgot: password re-entry for the PENDING user (same session
    mechanism as login_pin) → full login + a one-shot force_pin_reset flag
    that sends them straight into the profile PIN modal."""

    def setUp(self):
        security._login_attempts.clear()
        self.user = make_pin_user()
        self.client.post(
            "/login/", {"username": "gate_u", "password": "correct-horse"}, **AJAX)

    def test_correct_password_logs_in_and_flags_the_forced_reset(self):
        r = self.client.post(
            "/login/pin/forgot/", {"password": "correct-horse"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertEqual(r.json()["redirect"], "/profile/?modal=pin")
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(self.client.session.get("force_pin_reset"))
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_wrong_password_refuses_and_grants_nothing(self):
        r = self.client.post("/login/pin/forgot/", {"password": "wrong"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("force_pin_reset", self.client.session)
        # The pending state survives, so the user can still try their PIN.
        self.assertEqual(self.client.session.get(PENDING_KEY), self.user.id)

    def test_non_ajax_success_redirects_to_the_pin_modal(self):
        r = self.client.post("/login/pin/forgot/", {"password": "correct-horse"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/profile/?modal=pin")

    def test_without_a_pending_session_it_is_rejected(self):
        fresh = self.client_class()
        r = fresh.post("/login/pin/forgot/", {"password": "correct-horse"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Session expired", r.json()["message"])


class ForcePinResetWaiverTests(TestCase):
    """The profile modal waives the current-PIN check when (and only when)
    the session carries force_pin_reset — and the waiver dies with the
    reset it authorised."""

    def setUp(self):
        security._login_attempts.clear()
        self.user = make_pin_user()
        self.client.force_login(self.user)

    def _set_flag(self):
        session = self.client.session
        session["force_pin_reset"] = True
        session.save()

    def test_the_flag_waives_the_current_pin_exactly_once(self):
        self._set_flag()
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "8888", "confirm_pin": "8888"})
        self.assertTrue(r.json()["ok"], msg=r.json())
        self.assertTrue(get_or_create_profile(self.user).check_pin("8888"))
        self.assertNotIn("force_pin_reset", self.client.session)
        # Second attempt without the current PIN must be refused again.
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "7777", "confirm_pin": "7777"})
        self.assertFalse(r.json()["ok"])
        self.assertTrue(get_or_create_profile(self.user).check_pin("8888"))

    def test_a_typo_in_the_new_pin_does_not_burn_the_waiver(self):
        self._set_flag()
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "8888", "confirm_pin": "9999"})
        self.assertFalse(r.json()["ok"])
        self.assertTrue(self.client.session.get("force_pin_reset"),
                        msg="a validation error must not dead-end the reset")
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "8888", "confirm_pin": "8888"})
        self.assertTrue(r.json()["ok"])

    def test_without_the_flag_the_current_pin_is_still_required(self):
        r = self.client.post("/profile/change-pin-modal/", {
            "current_pin": "0000", "new_pin": "8888", "confirm_pin": "8888"})
        self.assertFalse(r.json()["ok"])
        self.assertTrue(get_or_create_profile(self.user).check_pin("4321"))

    def test_the_forced_reset_is_audit_logged(self):
        from core.audit import AuditLog
        self._set_flag()
        self.client.post("/profile/change-pin-modal/", {
            "current_pin": "", "new_pin": "8888", "confirm_pin": "8888"})
        self.assertTrue(AuditLog.objects.filter(
            user=self.user, action="config_change",
            description__contains="PIN reset").exists())


class PinGateTemplateContractTests(TestCase):
    """Pin the markup/JS contract the fix relies on — and regression-pin the
    entrance animation, which the fix was explicitly forbidden to alter."""

    def _wall(self):
        r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        return r.content.decode("utf-8", errors="ignore")

    def test_wall_pin_overlay_contract(self):
        body = self._wall()
        # Errors during the PIN step must land inside the overlay.
        self.assertIn('id="pinErrors"', body)
        # OTP semantics on the boxes: 4 static inputs + the JS-created ones
        # (the JS sets it via setAttribute, hence counting the bare token).
        self.assertEqual(body.count('autocomplete="one-time-code"'), 4)
        self.assertGreaterEqual(body.count("one-time-code"), 5)
        # Immediate focus with preventScroll — the root-cause fix.
        self.assertIn("preventScroll", body)
        # The hidden credentials form is neutralised while pin-mode is on.
        self.assertIn("setCredentialFieldsDisabled", body)
        # Forgot-PIN escape hatch is wired to the new endpoint.
        self.assertIn('id="pinForgotLink"', body)
        self.assertIn("/login/pin/forgot/", body)

    def test_wall_entrance_animation_is_untouched(self):
        body = self._wall()
        for cls in ("pa-1", "pa-2", "pa-3", "pa-4", "pa-5"):
            self.assertIn("pin-anim " + cls, body)
        self.assertIn("body.pin-mode .pin-anim", body)
        self.assertIn("body.pin-mode .pin-anim.pa-5 { transition-delay: 1.3s; }", body)

    def test_wall_never_auto_submits_at_four_digits(self):
        """A 6-digit operator must be able to keep typing — submit is Enter
        or the Verify button, never the 4th box filling."""
        body = self._wall()
        self.assertIn("no auto-submit", body)
        self.assertIn("PIN_MAX = 8", body)

    def test_standalone_pin_page_mirrors_the_contract(self):
        make_pin_user()
        security._login_attempts.clear()
        self.client.post(
            "/login/", {"username": "gate_u", "password": "correct-horse"})
        r = self.client.get("/login/pin/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        self.assertEqual(body.count('autocomplete="one-time-code"'), 4)
        self.assertGreaterEqual(body.count("one-time-code"), 5)
        self.assertIn('id="pinForgotLink"', body)
        self.assertIn("/login/pin/forgot/", body)
        self.assertIn("no auto-submit", body)
        self.assertIn("PIN_MAX = 8", body)
        # Its own entrance animation (fade-up stagger) is untouched.
        for cls in ("d1", "d2", "d3", "d4", "d5"):
            self.assertIn("fade-up " + cls, body)
        self.assertIn("@keyframes fadeUp", body)
