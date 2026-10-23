"""Turning a live-money switch on takes the trading PIN, on every path.

The operator's ask (2026-10-23): "Go for the PIN on the switches." The
finding behind it: the /ops/ toggle, the admin dashboard's forms, the
system map, the Django admin and `manage.py component on` each turned
any LIVE_MONEY_SWITCHES key ON with no PIN, while closing a position,
the kill switch and arming a live bot all asked for it. A hijacked
superuser session could arm real money with one POST.

The rule these tests pin (core/switch_pin.py is the one helper):

* OFF -> ON of a live-money key takes the PIN, checked server-side on
  the user's own TraderProfile hash, behind the idle lock's own session
  counter (five wrong answers end the session, wherever they were given);
* a missing, blank or wrong PIN changes nothing and says why;
* the shell and the Django admin never take a PIN: they refuse, and
  point at /ops/;
* turning OFF is free on every path;
* every ON, every refused ON and every live OFF lands on the audit
  chain with who, the door and when;
* non-live keys behave exactly as before, and "all on" keeps its
  exemptions.

The PIN below is a test-only value set through the profile's own helper.

Run with:  python manage.py test tests.test_switch_pin
"""
import json
import logging
import os
import re
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.management import CommandError, call_command
from django.test import Client, TestCase
from django.utils import timezone

from portfolio.trader_profile import get_or_create_profile

User = get_user_model()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Test-only values; never the operator's. Six digits so that neither can
# turn up by chance inside a timestamp or an id in a captured log line.
TEST_PIN = "583920"
WRONG_PIN = "104729"

NON_LIVE = ("scraper_news", "telegram_alarm", "proving_ground",
            "morgul_brake", "lore_staff", "platform_master")

TOGGLE = "/admin-dashboard/toggle/"
BULK = "/admin-dashboard/bulk-toggle/"
MAP = "/admin-dashboard/system-map/toggle/"
UNLOCK = "/api/session/unlock/"
ADMIN_LIST = "/admin/core/platformcomponent/"


def _live():
    from core.platform_control import LIVE_MONEY_SWITCHES
    return LIVE_MONEY_SWITCHES


def _row(key):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.get(key=key)


def _raw(key, on):
    """The test's own fixture write, not a door."""
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.filter(key=key).update(is_enabled=on)


def _audit(kind=None, key=None):
    from bot_program.audit_models import AuditLogEntry
    rows = AuditLogEntry.objects.filter(kind__startswith="switch_")
    if kind:
        rows = rows.filter(kind=kind)
    rows = list(rows.order_by("id"))
    if key:
        rows = [r for r in rows if (r.data or {}).get("key") == key]
    return rows


def _flashes(resp) -> str:
    return " | ".join(str(m) for m in get_messages(resp.wsgi_request))


def _last_flash(resp) -> str:
    """The message this request added (a redirect not followed leaves the
    earlier ones queued in the test client's storage)."""
    said = [str(m) for m in get_messages(resp.wsgi_request)]
    return said[-1] if said else ""


def _set_pin(user, pin=TEST_PIN):
    prof = get_or_create_profile(user)
    prof.set_pin(pin)
    prof.save()
    return prof


class _Fixture(TestCase):

    def setUp(self):
        from django.core.cache import cache
        from core.platform_control import seed_components
        cache.clear()
        seed_components()
        self.admin = User.objects.create_superuser(
            "switch_admin", "switch_admin@example.test", "x")
        self.prof = _set_pin(self.admin)
        self.client.force_login(self.admin)

    # ── the doors ───────────────────────────────────────────────────────
    def ops(self, key, **extra):
        return self.client.post(TOGGLE, {"key": key, "next": "ops", **extra})

    def dashboard(self, key, **extra):
        return self.client.post(TOGGLE, {"key": key, **extra})

    def map(self, key, **extra):
        return self.client.post(MAP, {"kind": "component", "key": key,
                                      **extra})

    def admin_changelist(self, key, on):
        row = _row(key)
        data = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(row.pk), "_save": "Save"}
        if on:
            data["form-0-is_enabled"] = "on"
        return self.client.post(ADMIN_LIST, data)

    @staticmethod
    def _admin_form_data(*, key, name, category, on):
        data = {"key": key, "name": name, "description": "",
                "category": category, "last_run_at_0": "",
                "last_run_at_1": "", "last_status": "", "last_message": "",
                "run_count": "0", "error_count": "0", "_save": "Save"}
        if on:
            data["is_enabled"] = "on"
        return data

    def admin_change(self, key, on, *, new_key=None):
        row = _row(key)
        return self.client.post(
            f"{ADMIN_LIST}{row.pk}/change/",
            self._admin_form_data(key=new_key or row.key, name=row.name,
                                  category=row.category, on=on))

    def admin_add(self, key, on):
        return self.client.post(
            f"{ADMIN_LIST}add/",
            self._admin_form_data(key=key, name=key.title(),
                                  category="system", on=on))


# ── 1. every door refuses ON without the PIN ─────────────────────────────
class EveryDoorRefusesOnWithoutThePinTests(_Fixture):

    def _refused(self, key, via, *, who="switch_admin", door=""):
        self.assertFalse(_row(key).is_enabled, f"{door}: {key} turned ON")
        rows = _audit("switch_refused", key)
        self.assertTrue(rows, f"{door}: no switch_refused row for {key}")
        data = rows[-1].data
        self.assertEqual(data["via"], via, door)
        self.assertEqual(data["who"], who, door)
        self.assertFalse(data["after"], door)
        self.assertFalse(_audit("switch_armed", key), door)

    def test_the_ops_toggle_without_a_pin_changes_nothing_and_says_why(self):
        for key in _live():
            old = timezone.now() - timedelta(days=3)
            from core.platform_control import PlatformComponent
            PlatformComponent.objects.filter(key=key).update(updated_at=old)
            resp = self.ops(key, want="on")
            self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
            said = _flashes(resp)
            self.assertIn("trading PIN", said, key)
            self.assertIn("Nothing was changed", said, key)
            self._refused(key, "ops", door="ops, no pin")
            # nothing was written: not even the flip's timestamp
            self.assertEqual(_row(key).updated_at, old, key)

    def test_a_blank_pin_is_a_missing_pin(self):
        for key in _live():
            resp = self.ops(key, want="on", pin="")
            self.assertIn("trading PIN", _flashes(resp), key)
            self._refused(key, "ops", door="ops, blank pin")

    def test_a_form_without_want_still_cannot_arm(self):
        """An old page, or a hand-made POST with no `want`: the toggle
        reads the row (OFF), so the ask is ON, and ON takes the PIN."""
        for key in _live():
            resp = self.ops(key)
            self.assertIn("trading PIN", _flashes(resp), key)
            self._refused(key, "ops", door="ops, no want")

    def test_the_admin_dashboard_forms_refuse_too(self):
        for key in _live():
            resp = self.dashboard(key)
            self.assertRedirects(resp, "/admin-dashboard/",
                                 fetch_redirect_response=False)
            self.assertIn("trading PIN", _flashes(resp), key)
            self._refused(key, "admin_dashboard", door="admin dashboard")

    def test_the_system_map_refuses_with_a_sentence_naming_ops(self):
        for key in _live():
            resp = self.map(key)
            self.assertEqual(resp.status_code, 403, key)
            body = resp.json()
            self.assertFalse(body["ok"], key)
            self.assertFalse(body["enabled"], key)
            self.assertIn("trading PIN", body["error"], key)
            self.assertIn("/ops/", body["detail"], key)
            self._refused(key, "system_map", door="system map")

    def test_all_on_beside_system_still_leaves_every_live_switch_off(self):
        resp = self.client.post(BULK, {"category": "system",
                                       "action": "enable", "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        for key in _live():
            self.assertFalse(_row(key).is_enabled, key)
            self.assertFalse(_audit("switch_armed", key), key)

    def test_the_django_admin_changelist_checkbox_refuses(self):
        for key in _live():
            resp = self.admin_changelist(key, on=True)
            # Not a form error (that would drop every other row's save):
            # the row stays as stored and a message says why.
            self.assertEqual(resp.status_code, 302, key)
            said = _last_flash(resp)
            self.assertIn("/ops/", said, key)
            self.assertIn("trading PIN", said, key)
            self._refused(key, "django_admin", door="admin changelist")

    def test_the_django_admin_change_form_refuses(self):
        for key in _live():
            resp = self.admin_change(key, on=True)
            self.assertEqual(resp.status_code, 200, key)
            self.assertContains(resp, "/ops/")
            self._refused(key, "django_admin", door="admin change form")

    def test_the_django_admin_add_form_cannot_create_a_live_row_on(self):
        from core.platform_control import PlatformComponent
        for key in _live():
            PlatformComponent.objects.filter(key=key).delete()
            resp = self.admin_add(key, on=True)
            self.assertEqual(resp.status_code, 200, key)
            self.assertContains(resp, "/ops/")
            self.assertFalse(PlatformComponent.objects.filter(
                key=key, is_enabled=True).exists(), key)
            self.assertEqual(_audit("switch_refused", key)[-1].data["via"],
                             "django_admin")

    def test_renaming_an_enabled_row_into_a_live_key_is_refused(self):
        from core.platform_control import PlatformComponent
        _raw("scraper_news", True)
        for key in _live():
            PlatformComponent.objects.filter(key=key).delete()
            resp = self.admin_change("scraper_news", on=True, new_key=key)
            self.assertEqual(resp.status_code, 200, key)
            self.assertFalse(PlatformComponent.objects.filter(
                key=key).exists(), key)
            self.assertTrue(_row("scraper_news").is_enabled)
            self.assertEqual(_audit("switch_refused", key)[-1].data["via"],
                             "django_admin")

    def test_manage_py_component_on_refuses_and_points_to_ops(self):
        for key in _live():
            with self.assertRaises(CommandError) as ctx:
                call_command("component", "on", key, stdout=StringIO())
            said = str(ctx.exception)
            self.assertIn("/ops/", said, key)
            self.assertIn("PIN", said, key)
            self.assertIn("Nothing was changed", said, key)
            self._refused(key, "shell", who="shell", door="shell")

    def test_a_programmatic_call_without_a_request_is_refused(self):
        from core.switch_pin import set_switch
        for key in _live():
            res = set_switch(key, True, via="shell")
            self.assertFalse(res.ok, key)
            self.assertEqual(res.refusal, "no_pin_here", key)
            self.assertFalse(_row(key).is_enabled, key)


# ── 2. the right PIN arms, and leaves no trace of itself ─────────────────
class TheRightPinArmsTests(_Fixture):

    def test_ops_with_the_pin_turns_each_live_switch_on_and_records_it(self):
        from core.platform_control import PlatformComponent
        for key in _live():
            old = timezone.now() - timedelta(days=3)
            PlatformComponent.objects.filter(key=key).update(updated_at=old)
            resp = self.ops(key, want="on", pin=TEST_PIN)
            self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
            row = _row(key)
            self.assertTrue(row.is_enabled, key)
            # the flip's instant, which the alarm bot reads elsewhere
            self.assertGreater(row.updated_at, old, key)
            self.assertEqual(_last_flash(resp), f"{row.name} started.")
            [armed] = _audit("switch_armed", key)
            self.assertEqual(armed.data["who"], "switch_admin")
            self.assertEqual(armed.data["via"], "ops")
            self.assertFalse(armed.data["before"])
            self.assertTrue(armed.data["after"])
            self.assertEqual(armed.user, self.admin)
            self.assertIsNotNone(armed.created_at)

    def test_the_admin_dashboard_forms_arm_with_the_pin(self):
        for key in _live():
            resp = self.dashboard(key, want="on", pin=TEST_PIN)
            self.assertRedirects(resp, "/admin-dashboard/",
                                 fetch_redirect_response=False)
            self.assertTrue(_row(key).is_enabled, key)
            self.assertEqual(_audit("switch_armed", key)[-1].data["via"],
                             "admin_dashboard")

    def test_a_stale_turn_on_never_spends_the_pin_on_a_stop(self):
        """want=on on a switch someone else already armed: it stays ON,
        and the toggle does not read the click as 'flip it OFF'."""
        key = "aragorn"
        _raw(key, True)
        resp = self.ops(key, want="on", pin=TEST_PIN)
        self.assertTrue(_row(key).is_enabled)
        self.assertIn("already ON", _flashes(resp))
        self.assertFalse(_audit(key=key))

    def test_the_pin_and_its_hash_appear_nowhere(self):
        from bot_program.audit_models import AuditLogEntry
        from core.audit import AuditLog

        lines = []

        class _Grab(logging.Handler):
            def emit(self, record):
                try:
                    lines.append(record.getMessage())
                except Exception:  # noqa: BLE001
                    lines.append(str(record.msg))

        grab = _Grab(level=logging.DEBUG)
        # The app loggers do not propagate to root (core/logging_config.py
        # sets propagate=False on each of SAURON_APPS): a handler on root
        # alone would never see what core.switch_pin or dashboard logs.
        from core.logging_config import SAURON_APPS
        targets = [logging.getLogger()] + [
            logging.getLogger(n) for n in (*SAURON_APPS, "django", "celery")]
        saved = [(lg, lg.level) for lg in targets]
        for lg in targets:
            lg.addHandler(grab)
            lg.setLevel(logging.DEBUG)
        said = []
        try:
            logging.getLogger("core.switch_pin").debug("capture-canary")
            for key in ("aragorn", "smart_money"):
                said.append(_flashes(self.ops(key, want="on", pin=WRONG_PIN)))
                said.append(_flashes(self.ops(key, want="on", pin=TEST_PIN)))
                said.append(_flashes(self.ops(key, want="off")))
            said.append(json.dumps(self.map("crisis_mode",
                                            pin=WRONG_PIN).json()))
        finally:
            for lg, level in saved:
                lg.removeHandler(grab)
                lg.setLevel(level)
        # the capture is not blind: an app logger's line reached it
        self.assertIn("capture-canary", lines)
        secret_hash = get_or_create_profile(self.admin).access_pin_hash
        chain = json.dumps([e.data for e in AuditLogEntry.objects.all()])
        core_log = json.dumps([[a.description, a.metadata]
                               for a in AuditLog.objects.all()])
        session = json.dumps(dict(self.client.session.items()))
        for blob, where in ((chain, "audit chain"), (core_log, "AuditLog"),
                            (" ".join(said), "messages"),
                            ("\n".join(lines), "logs"),
                            (session, "session")):
            for secret in (TEST_PIN, WRONG_PIN, secret_hash):
                self.assertNotIn(secret, blob, where)
        self.assertTrue(_audit("switch_armed"))   # it did record something

    def test_the_right_pin_clears_the_session_counter(self):
        from dashboard.lock_views import ATTEMPTS_KEY
        s = self.client.session
        s[ATTEMPTS_KEY] = 2
        s.save()
        self.ops("aragorn", want="on", pin=TEST_PIN)
        self.assertTrue(_row("aragorn").is_enabled)
        self.assertNotIn(ATTEMPTS_KEY, self.client.session)


# ── 3. OFF is free on every door ─────────────────────────────────────────
class OffIsFreeEverywhereTests(_Fixture):

    def _disarmed(self, key, via, door, *, who="switch_admin"):
        self.assertFalse(_row(key).is_enabled, f"{door}: {key} still ON")
        rows = _audit("switch_disarmed", key)
        self.assertTrue(rows, f"{door}: no switch_disarmed row for {key}")
        self.assertEqual(rows[-1].data["via"], via, door)
        self.assertEqual(rows[-1].data["who"], who, door)
        self.assertTrue(rows[-1].data["before"], door)
        self.assertFalse(rows[-1].data["after"], door)
        self.assertFalse(_audit("switch_refused", key), door)

    def test_every_door_turns_a_live_switch_off_with_no_pin(self):
        from dashboard.lock_views import ATTEMPTS_KEY
        doors = (
            ("ops toggle", "ops", lambda k: self.ops(k)),
            ("ops want=off", "ops", lambda k: self.ops(k, want="off")),
            ("admin dashboard", "admin_dashboard", lambda k: self.dashboard(k)),
            ("system map", "system_map", lambda k: self.map(k)),
            ("admin changelist", "django_admin",
             lambda k: self.admin_changelist(k, on=False)),
            ("admin change form", "django_admin",
             lambda k: self.admin_change(k, on=False)),
        )
        for key in _live():
            for door, via, flip in doors:
                _raw(key, True)
                resp = flip(key)
                self.assertIn(resp.status_code, (200, 302), door)
                self._disarmed(key, via, f"{door} / {key}")
                _audit_clear()
        # the shell, and no PIN prompt anywhere
        for key in _live():
            _raw(key, True)
            out = StringIO()
            call_command("component", "off", key, stdout=out)
            self.assertIn(f"{key}: ON → OFF", out.getvalue())
            self._disarmed(key, "shell", "shell", who="shell")
        self.assertNotIn(ATTEMPTS_KEY, self.client.session)

    def test_the_map_answers_off_in_its_usual_shape(self):
        _raw("aragorn", True)
        resp = self.map("aragorn")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, "enabled": False,
                                       "label": _row("aragorn").name})

    def test_all_off_turns_every_live_switch_off_and_records_each(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(category="system").update(
            is_enabled=True)
        resp = self.client.post(BULK, {"category": "system",
                                       "action": "disable", "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertFalse(PlatformComponent.objects.filter(
            category="system", is_enabled=True).exists())
        for key in _live():
            [row] = _audit("switch_disarmed", key)
            self.assertEqual(row.data["via"], "all_off")
            self.assertEqual(row.data["who"], "switch_admin")


def _audit_clear():
    from bot_program.audit_models import AuditLogEntry
    AuditLogEntry.objects.filter(kind__startswith="switch_").delete()


# ── 4. non-live keys: exactly as before ─────────────────────────────────
class NonLiveKeysUnchangedTests(_Fixture):

    def test_every_door_flips_a_non_live_key_both_ways_without_a_pin(self):
        for key in NON_LIVE:
            name = _row(key).name
            resp = self.ops(key)
            self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
            self.assertEqual(_last_flash(resp), f"{name} started.")
            self.assertTrue(_row(key).is_enabled, key)
            resp = self.ops(key)
            self.assertEqual(_last_flash(resp), f"{name} stopped.")
            self.assertFalse(_row(key).is_enabled, key)

            resp = self.dashboard(key)
            self.assertRedirects(resp, "/admin-dashboard/",
                                 fetch_redirect_response=False)
            self.assertTrue(_row(key).is_enabled, key)
            self.dashboard(key)
            self.assertFalse(_row(key).is_enabled, key)

            resp = self.map(key)
            self.assertEqual(resp.json(), {"ok": True, "enabled": True,
                                           "label": name})
            self.map(key)
            self.assertFalse(_row(key).is_enabled, key)

            out = StringIO()
            call_command("component", "on", key, stdout=out)
            self.assertIn(f"{key}: OFF → ON", out.getvalue())
            call_command("component", "off", key, stdout=StringIO())

            self.admin_changelist(key, on=True)
            self.assertTrue(_row(key).is_enabled, key)
            self.admin_change(key, on=False)
            self.assertFalse(_row(key).is_enabled, key)
        self.assertFalse(_audit(), "a non-live key wrote a switch_* row")

    def test_all_on_keeps_its_exemptions_and_its_count(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           PlatformComponent)
        expected = PlatformComponent.objects.filter(
            category="system").exclude(key__in=BULK_ENABLE_EXEMPT).count()
        resp = self.client.post(BULK, {"category": "system",
                                       "action": "enable", "next": "ops"})
        self.assertEqual(_last_flash(resp),
                         f"{expected} system components started.")
        for key in BULK_ENABLE_EXEMPT:
            row = PlatformComponent.objects.filter(key=key).first()
            if row is not None:
                self.assertFalse(row.is_enabled, key)
        self.assertFalse(PlatformComponent.objects.filter(
            category="system", is_enabled=False).exclude(
                key__in=BULK_ENABLE_EXEMPT).exists())
        self.assertFalse(_audit())

    def test_an_unknown_key_reads_as_before(self):
        resp = self.ops("no_such_component")
        self.assertEqual(_last_flash(resp),
                         "Component 'no_such_component' not found.")
        resp = self.map("no_such_component")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"ok": False, "error":
                                       "no component 'no_such_component'"})


# ── 5. a wrong PIN counts toward the idle lock's own five ───────────────
class AWrongPinCountsTowardTheLockoutTests(_Fixture):

    def test_a_wrong_pin_counts_and_changes_nothing(self):
        from dashboard.lock_views import ATTEMPTS_KEY, MAX_ATTEMPTS
        resp = self.ops("aragorn", want="on", pin=WRONG_PIN)
        self.assertFalse(_row("aragorn").is_enabled)
        said = _flashes(resp)
        self.assertIn("Incorrect PIN", said)
        self.assertIn(f"{MAX_ATTEMPTS - 1} attempts left", said)
        self.assertEqual(self.client.session[ATTEMPTS_KEY], 1)
        self.assertEqual(_audit("switch_refused", "aragorn")[-1]
                         .data["reason"], "pin_wrong")

    def test_five_wrong_pins_end_the_session(self):
        from core.audit import AuditLog
        from dashboard.lock_views import MAX_ATTEMPTS
        for _ in range(MAX_ATTEMPTS - 1):
            self.ops("aragorn", want="on", pin=WRONG_PIN)
        self.assertEqual(self.client.get("/ops/").status_code, 200)
        resp = self.ops("aragorn", want="on", pin=WRONG_PIN)
        self.assertIn("session has ended", _flashes(resp))
        self.assertFalse(_row("aragorn").is_enabled)
        page = self.client.get("/ops/")
        self.assertEqual(page.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditLog.objects.filter(
            user=self.admin, action="login",
            description__contains="session terminated").exists())
        self.assertEqual(_audit("switch_refused", "aragorn")[-1]
                         .data["reason"], "locked_out")

    def test_the_counter_is_shared_with_the_lock_screen(self):
        from dashboard.lock_views import MAX_ATTEMPTS
        for _ in range(MAX_ATTEMPTS - 1):
            self.ops("smart_money", want="on", pin=WRONG_PIN)
        r = self.client.post(UNLOCK, {"pin": WRONG_PIN})
        self.assertEqual(r.json()["status"], "logged_out")

    def test_wrong_answers_at_the_lock_screen_count_at_a_switch(self):
        from dashboard.lock_views import MAX_ATTEMPTS
        for _ in range(MAX_ATTEMPTS - 1):
            self.client.post(UNLOCK, {"pin": WRONG_PIN})
        self.ops("smart_money", want="on", pin=WRONG_PIN)
        self.assertEqual(self.client.get("/ops/").status_code, 302)

    def test_the_map_counts_too_and_says_the_session_ended(self):
        from dashboard.lock_views import MAX_ATTEMPTS
        for _ in range(MAX_ATTEMPTS - 1):
            self.map("crisis_mode", pin=WRONG_PIN)
        resp = self.map("crisis_mode", pin=WRONG_PIN)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("session has ended", resp.json()["error"])
        self.assertFalse(_row("crisis_mode").is_enabled)

    def test_a_blank_pin_and_a_pinless_account_are_refused_uncounted(self):
        from dashboard.lock_views import ATTEMPTS_KEY
        for _ in range(8):
            self.ops("aragorn", want="on", pin="")
        self.assertNotIn(ATTEMPTS_KEY, self.client.session)
        self.assertEqual(self.client.get("/ops/").status_code, 200)

        bare = User.objects.create_superuser("bare_admin", "b@x.test", "x")
        self.client.force_login(bare)
        for _ in range(8):
            resp = self.ops("aragorn", want="on", pin=WRONG_PIN)
        self.assertIn("no trading PIN yet", _flashes(resp))
        self.assertNotIn(ATTEMPTS_KEY, self.client.session)
        self.assertFalse(_row("aragorn").is_enabled)
        self.assertEqual(_audit("switch_refused", "aragorn")[-1]
                         .data["reason"], "pin_not_set")

    def test_the_count_is_per_session(self):
        from dashboard.lock_views import ATTEMPTS_KEY, MAX_ATTEMPTS
        for _ in range(MAX_ATTEMPTS - 1):
            self.ops("aragorn", want="on", pin=WRONG_PIN)
        other = Client()
        other.force_login(self.admin)
        other.post(TOGGLE, {"key": "aragorn", "next": "ops", "want": "on",
                            "pin": WRONG_PIN})
        self.assertEqual(other.session[ATTEMPTS_KEY], 1)
        self.assertEqual(other.get("/ops/").status_code, 200)


# ── 6. the shell never takes a PIN ─────────────────────────────────────
class TheShellNeverTakesAPinTests(_Fixture):

    def test_the_command_has_no_pin_option(self):
        from core.management.commands.component import Command
        parser = Command().create_parser("manage.py", "component")
        options = [s for a in parser._actions for s in a.option_strings]
        self.assertFalse([s for s in options if "pin" in s.lower()],
                         options)
        with self.assertRaises(CommandError):
            call_command("component", "on", "aragorn", "--pin", "000000",
                         stdout=StringIO())
        self.assertFalse(_row("aragorn").is_enabled)

    def test_a_terminal_changes_nothing_and_nothing_is_ever_prompted(self):
        with patch("sys.stdin.isatty", return_value=True), \
                patch("getpass.getpass",
                      side_effect=AssertionError("prompted")) as prompt:
            with self.assertRaises(CommandError) as ctx:
                call_command("component", "on", "aragorn", stdout=StringIO())
        prompt.assert_not_called()
        self.assertIn("/ops/", str(ctx.exception))
        self.assertFalse(_row("aragorn").is_enabled)

    def test_a_refused_key_is_not_seeded(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key="smart_money").delete()
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("component", "on", "smart_money", stdout=out)
        self.assertFalse(PlatformComponent.objects.filter(
            key="smart_money").exists())
        self.assertNotIn("registered", out.getvalue())

    def test_a_mixed_list_writes_nothing(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("component", "on", "telegram_alarm", "aragorn",
                         "crisis_mode", stdout=StringIO())
        self.assertFalse(_row("telegram_alarm").is_enabled)
        self.assertFalse(_row("aragorn").is_enabled)
        self.assertFalse(_row("crisis_mode").is_enabled)
        self.assertIn("aragorn", str(ctx.exception))
        self.assertIn("crisis_mode", str(ctx.exception))

    def test_a_live_switch_already_on_reads_unchanged(self):
        _raw("aragorn", True)
        out = StringIO()
        call_command("component", "on", "aragorn", stdout=out)
        self.assertIn("aragorn: ON → ON (unchanged)", out.getvalue())
        self.assertFalse(_audit())

    def test_off_works_from_the_shell(self):
        _raw("aragorn", True)
        out = StringIO()
        call_command("component", "off", "aragorn", stdout=out)
        self.assertIn("aragorn: ON → OFF", out.getvalue())
        self.assertFalse(_row("aragorn").is_enabled)

    def test_every_documented_non_live_command_still_arms_its_key(self):
        from core.platform_control import DEFAULT_COMPONENTS
        known = {c["key"] for c in DEFAULT_COMPONENTS}
        documented = {k for k, _ in _documented_on_commands()} & known
        # the scan is not vacuous: the runbook's own lines are in it
        self.assertTrue({"proving_ground", "telegram_alarm",
                         "pipeline_capital_desk", "newsletter_send",
                         "generator_auto_research"} <= documented,
                        documented)
        for key in sorted(documented):
            _raw(key, False)
            out = StringIO()
            call_command("component", "on", key, stdout=out)
            self.assertIn(f"{key}: OFF → ON", out.getvalue(), key)
            self.assertTrue(_row(key).is_enabled, key)


# ── 7. no page or document still advises a refused command ─────────────
_ON_RE = re.compile(
    r"component\s+on(?:[\s\"'`]|\\n)+([a-z][a-z0-9_]*(?:[ ]+[a-z][a-z0-9_]*)*)")
_SKIP_DIRS = {"venv", ".venv", "staticfiles", "node_modules", ".git",
              "tests", ".claude", "media", "__pycache__"}


# The ORM's own arming idiom, as a runbook would print it for the shell:
# `...filter(key='etoro_leverage_live').update(is_enabled=True)`, and any
# line that names a quoted key beside `is_enabled=True` / `"is_enabled":
# True` (an update_or_create's defaults, a save()). The shell is not a
# door the PIN can guard; a document must not send real money through it.
_ORM_RE = re.compile(
    r"""key\s*=\s*\\?["']([a-z][a-z0-9_]*)\\?["']\s*\)\s*"""
    r"""\.update\(\s*is_enabled\s*=\s*True""")
_ENABLED_TRUE_RE = re.compile(r"""is_enabled\\?["']?\s*[=:]\s*True""")
_QUOTED_KEY_RE = re.compile(r"""\\?["']([a-z][a-z0-9_]*)\\?["']""")


def _operator_texts(root=None):
    """(relative path, text) for every file the repository shows an
    operator: every *.md (the root's DEPLOY.md and README.md included),
    every *.html under any `templates` directory (app templates too), and
    every non-test *.py."""
    root = root or ROOT
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            if fn.endswith(".py"):
                pass
            elif fn.endswith(".html") and "templates" in rel.split(os.sep):
                pass
            elif fn.endswith(".md"):
                pass
            else:
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            yield os.path.relpath(path, root), text


def _documented_on_commands(root=None):
    """(key, where) for every `component on <key ...>` the repository
    shows an operator."""
    found = []
    for where, text in _operator_texts(root):
        for m in _ON_RE.finditer(text):
            for key in m.group(1).split():
                found.append((key, where))
    return found


def _documented_orm_arms(root=None):
    """(key, where) for every place the repository arms a switch through
    the ORM by name: `.filter(key=...).update(is_enabled=True)`, or a line
    pairing a quoted key with `is_enabled=True`."""
    found = []
    for where, text in _operator_texts(root):
        for m in _ORM_RE.finditer(text):
            found.append((m.group(1), where))
        for line in text.splitlines():
            if _ENABLED_TRUE_RE.search(line):
                for m in _QUOTED_KEY_RE.finditer(line):
                    found.append((m.group(1), where))
    return found


class NoDocAdvisesARefusedCommandTests(_Fixture):

    def test_no_document_tells_the_operator_to_arm_real_money_by_shell(self):
        live = set(_live())
        bad = [(k, where) for k, where in _documented_on_commands()
               if k in live]
        self.assertEqual(bad, [], "these would now be refused: say /ops/ "
                                  "with the trading PIN instead")

    def test_no_document_arms_real_money_through_the_orm(self):
        """deploy/ETORO_DEPARTURE.md's THE FLIP once printed a `manage.py
        shell -c` that set etoro_leverage_live with an ORM update: no PIN,
        and no switch_armed row on the audit chain."""
        live = set(_live())
        bad = sorted({(k, where) for k, where in _documented_orm_arms()
                      if k in live})
        self.assertEqual(bad, [], "these arm real money by the shell: say "
                                  "/ops/ with the trading PIN instead")

    def test_the_scans_see_every_place_advice_lives(self):
        """The scans read the root's docs, every app's templates and the
        ORM idiom: plant each form in a scratch tree and see it caught."""
        import tempfile
        planted = {
            "DEPLOY.md": "./deploy/dc exec -T web python manage.py "
                         "component on aragorn\n",
            os.path.join("bot_program", "templates", "bot_program",
                         "home.html"):
                "<code>manage.py component on smart_money</code>\n",
            os.path.join("deploy", "X.md"):
                "shell -c \"from core.platform_control import "
                "PlatformComponent; PlatformComponent.objects.filter("
                "key='etoro_leverage_live').update(is_enabled=True)\"\n",
            os.path.join("deploy", "Y.md"):
                "update_or_create(key=\"crisis_mode\", defaults="
                "{\"is_enabled\": True})\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for rel, text in planted.items():
                path = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            on = set(_documented_on_commands(tmp))
            orm = set(_documented_orm_arms(tmp))
        self.assertIn(("aragorn", "DEPLOY.md"), on)
        self.assertIn(("smart_money", os.path.join(
            "bot_program", "templates", "bot_program", "home.html")), on)
        self.assertIn(("etoro_leverage_live", os.path.join("deploy", "X.md")),
                      orm)
        self.assertIn(("crisis_mode", os.path.join("deploy", "Y.md")), orm)

    def test_the_desk_page_sends_staff_to_ops_for_the_live_mode(self):
        staff = User.objects.create_user("desk_staff", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        html = self.client.get("/desk/").content.decode()
        self.assertNotIn("component on capital_desk_mode_live", html)
        self.assertIn("/ops/", html)
        self.assertIn("trading PIN", html)
        self.assertIn("component on pipeline_capital_desk", html)


# ── 8. a seed never arms ───────────────────────────────────────────────
class SeedNeverArmsTests(TestCase):

    def test_every_live_switch_seeds_off(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent, seed_components)
        seed_components()
        for key in _live():
            row = PlatformComponent.objects.filter(key=key).first()
            self.assertIsNotNone(row, f"{key} is not seeded")
            self.assertFalse(row.is_enabled, key)
        self.assertFalse([c["key"] for c in DEFAULT_COMPONENTS
                          if "is_enabled" in c])

    def test_a_reseed_leaves_an_armed_switch_armed(self):
        from core.platform_control import seed_components
        seed_components()
        _raw("aragorn", True)
        seed_components()
        self.assertTrue(_row("aragorn").is_enabled)


# ── 9. the pages ask for the PIN only where it is needed ───────────────
_FORM_RE = re.compile(r'<form method="post" action="/admin-dashboard/toggle/"'
                      r'[^>]*>(.*?)</form>', re.S)
_KEY_RE = re.compile(r'name="key" value="([^"]+)"')


def _toggle_forms(html):
    forms = []
    for body in _FORM_RE.findall(html):
        m = _KEY_RE.search(body)
        if m:
            forms.append((m.group(1), body))
    return forms


class TheOpsPageAsksOnlyWhereItMustTests(_Fixture):

    def _check(self, html, page):
        live = set(_live())
        forms = _toggle_forms(html)
        self.assertTrue(forms, page)
        seen_live_off = seen_live_on = seen_plain = False
        for key, body in forms:
            row = _row(key)
            has_pin = 'name="pin"' in body
            if key in live and not row.is_enabled:
                seen_live_off = True
                self.assertTrue(has_pin, f"{page}: {key} OFF has no PIN field")
                self.assertIn('name="want" value="on"', body, f"{page}: {key}")
                self.assertIn('type="password"', body, f"{page}: {key}")
            else:
                self.assertFalse(has_pin, f"{page}: {key} asks for a PIN")
                if key in live:
                    seen_live_on = True
                    self.assertIn('name="want" value="off"', body, key)
                else:
                    seen_plain = True
                    self.assertNotIn('name="want"', body, f"{page}: {key}")
        self.assertTrue(seen_live_off and seen_live_on and seen_plain, page)

    def test_ops_puts_a_pin_field_on_each_off_live_row_only(self):
        _raw("aragorn", True)
        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        self._check(resp.content.decode(), "/ops/")
        rows = {r["comp"].key: r for g in resp.context["switches"]["groups"]
                for r in g["rows"]}
        for key in _live():
            self.assertTrue(rows[key]["live"], key)
        self.assertFalse(rows["scraper_news"]["live"])

    def test_the_held_line_names_the_pin_and_stays_one_line_a_group(self):
        resp = self.client.get("/ops/")
        lines = [ln for ln in resp.content.decode().splitlines()
                 if "all on leaves" in ln]
        self.assertEqual(len(lines), 2, lines)
        system_line = next(ln for ln in lines if "morgul_brake" in ln)
        self.assertIn("trading PIN", system_line)
        for key in _live():
            self.assertIn(key, system_line)
        agent_line = next(ln for ln in lines if ln is not system_line)
        self.assertNotIn("trading PIN", agent_line)

    def test_the_admin_dashboard_asks_on_its_live_forms_while_off(self):
        _raw("meta_allocator_mode_live", True)
        resp = self.client.get("/admin-dashboard/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self._check(html, "/admin-dashboard/")
        keys = [k for k, _ in _toggle_forms(html)]
        for key in ("actuator_mode_live", "meta_allocator_mode_live",
                    "share_allocator_mode_live",
                    "share_allocator_auto_derisk"):
            # the named card form and the table row
            self.assertGreaterEqual(keys.count(key), 2, key)


# ── 10. the audit kinds fit their column ───────────────────────────────
class SwitchAuditKindsFitTheColumnTests(TestCase):

    def test_every_switch_kind_fits_twenty_characters(self):
        from bot_program.audit import AUDIT_KINDS_SWITCH
        from bot_program.audit_models import AuditLogEntry
        width = AuditLogEntry._meta.get_field("kind").max_length
        self.assertEqual(width, 20)
        self.assertEqual(set(AUDIT_KINDS_SWITCH),
                         {"switch_armed", "switch_disarmed", "switch_refused"})
        for kind in AUDIT_KINDS_SWITCH:
            self.assertLessEqual(len(kind), width, kind)


# ── 11. the Django admin's list: a refusal never costs a stop ──────────
class TheAdminListNeverLosesAStopTests(_Fixture):
    """Django validates every row of the list before it saves any. A
    refused live ON used to be a form error, which dropped every OFF in
    the same save; and a list holding a live switch already ON has to
    save as before."""

    def _list_data(self):
        """The changelist's own POST, built from the page it renders: one
        form per row, ticked where the row is ON."""
        resp = self.client.get(ADMIN_LIST)
        self.assertEqual(resp.status_code, 200)
        forms = resp.context["cl"].formset.forms
        data = {"form-TOTAL_FORMS": str(len(forms)),
                "form-INITIAL_FORMS": str(len(forms)),
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
                "_save": "Save"}
        idx = {}
        for i, f in enumerate(forms):
            data[f"form-{i}-id"] = str(f.instance.pk)
            if f.instance.is_enabled:
                data[f"form-{i}-is_enabled"] = "on"
            idx[f.instance.key] = i
        return data, idx

    @staticmethod
    def _two_rows(on_key, off_key):
        a, b = _row(on_key), _row(off_key)
        return {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(a.pk), "form-0-is_enabled": "on",
                "form-1-id": str(b.pk), "_save": "Save"}

    def test_a_stale_live_tick_does_not_block_another_rows_stop(self):
        """The page showed aragorn ON; it was turned off elsewhere before
        Save. The operator unticks scraper_news, a stop."""
        _raw("aragorn", False)
        _raw("scraper_news", True)
        resp = self.client.post(ADMIN_LIST,
                                self._two_rows("aragorn", "scraper_news"))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(_row("scraper_news").is_enabled, "the stop was lost")
        self.assertFalse(_row("aragorn").is_enabled)
        self.assertEqual(len(_audit("switch_refused", "aragorn")), 1)
        self.assertFalse(_audit("switch_disarmed"))
        self.assertFalse(_audit("switch_armed"))
        said = _flashes(resp)
        self.assertIn("/ops/", said)
        self.assertIn("trading PIN", said)
        self.assertIn("1 platform component was changed", said)

    def test_a_refused_live_on_and_a_live_off_in_one_save(self):
        """Ticks aragorn (refused) and unticks smart_money (a live stop):
        the stop lands and is recorded, the refusal is recorded, and
        nothing reads aragorn as disarmed."""
        _raw("aragorn", False)
        _raw("smart_money", True)
        resp = self.client.post(ADMIN_LIST,
                                self._two_rows("aragorn", "smart_money"))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(_row("smart_money").is_enabled, "the stop was lost")
        self.assertFalse(_row("aragorn").is_enabled)
        [stop] = _audit("switch_disarmed")
        self.assertEqual(stop.data["key"], "smart_money")
        self.assertEqual(stop.data["via"], "django_admin")
        self.assertEqual(len(_audit("switch_refused")), 1)
        self.assertEqual(_audit("switch_refused")[0].data["key"], "aragorn")

    def test_a_refused_row_writes_no_admin_log_entry(self):
        from django.contrib.admin.models import LogEntry
        before = LogEntry.objects.count()
        self.admin_changelist("aragorn", on=True)
        self.assertEqual(LogEntry.objects.count(), before)
        self.assertFalse(_row("aragorn").is_enabled)

    def test_the_whole_list_saves_while_a_live_switch_is_on(self):
        _raw("aragorn", True)
        data, idx = self._list_data()
        self.assertIn("aragorn", idx)
        data[f"form-{idx['scraper_news']}-is_enabled"] = "on"
        resp = self.client.post(ADMIN_LIST, data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(_row("scraper_news").is_enabled)
        self.assertTrue(_row("aragorn").is_enabled)
        self.assertFalse(_audit("switch_refused"))

    def test_a_live_switch_that_is_on_can_still_be_edited(self):
        _raw("aragorn", True)
        row = _row("aragorn")
        data = self._admin_form_data(key="aragorn", name=row.name,
                                     category=row.category, on=True)
        data["description"] = "edited"
        resp = self.client.post(f"{ADMIN_LIST}{row.pk}/change/", data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(_row("aragorn").description, "edited")
        self.assertTrue(_row("aragorn").is_enabled)
        self.assertFalse(_audit("switch_refused"))


# ── 12. only a session that logged in under the current PIN arms ────────
class OnlyALoginUnderTheCurrentPinArmsTests(_Fixture):
    """A hijacked session cannot set a first PIN, or replace the PIN, and
    then use it at a switch: the login's mark of the stored PIN no longer
    matches, and only a fresh login (the password) renews it."""

    def _says_log_in_again(self, resp, key="aragorn"):
        from dashboard.lock_views import ATTEMPTS_KEY
        said = _last_flash(resp)
        self.assertIn("Log in again", said)
        self.assertIn("Nothing was changed", said)
        self.assertFalse(_row(key).is_enabled)
        self.assertEqual(_audit("switch_refused", key)[-1].data["reason"],
                         "login_again")
        self.assertNotIn(ATTEMPTS_KEY, self.client.session)  # not a guess

    def test_a_first_pin_set_in_this_session_cannot_arm(self):
        bare = User.objects.create_superuser("pinless_admin", "p@x.test",
                                             "pw-of-the-test")
        self.client.force_login(bare)
        r = self.client.post("/profile/change-pin-modal/",
                             {"new_pin": TEST_PIN, "confirm_pin": TEST_PIN})
        self.assertTrue(r.json()["ok"])
        self._says_log_in_again(self.ops("aragorn", want="on", pin=TEST_PIN))
        # the password proves the account; the new PIN then arms
        self.client.logout()
        self.assertTrue(self.client.login(username="pinless_admin",
                                          password="pw-of-the-test"))
        self.ops("aragorn", want="on", pin=TEST_PIN)
        self.assertTrue(_row("aragorn").is_enabled)

    def test_a_pin_replaced_through_the_modal_cannot_arm(self):
        r = self.client.post("/profile/change-pin-modal/",
                             {"current_pin": TEST_PIN, "new_pin": "2468",
                              "confirm_pin": "2468"})
        self.assertTrue(r.json()["ok"])
        self._says_log_in_again(self.ops("aragorn", want="on", pin="2468"))
        # nor the old one
        self.ops("aragorn", want="on", pin=TEST_PIN)
        self.assertFalse(_row("aragorn").is_enabled)

    def test_a_pin_replaced_through_the_profile_form_cannot_arm(self):
        self.client.post("/profile/change-pin/",
                         {"current_pin": TEST_PIN, "new_pin": "2468",
                          "confirm_pin": "2468"})
        self.assertTrue(get_or_create_profile(self.admin).check_pin("2468"))
        self._says_log_in_again(
            self.ops("crisis_mode", want="on", pin="2468"), key="crisis_mode")

    def test_a_pin_written_by_any_other_door_cannot_arm(self):
        """The Django admin's TraderProfile page, the shell: whatever
        writes the hash, the session's mark no longer matches."""
        _set_pin(self.admin, "97531")
        resp = self.dashboard("smart_money", want="on", pin="97531")
        self.assertIn("Log in again", _last_flash(resp))
        self.assertFalse(_row("smart_money").is_enabled)
        resp = self.map("crisis_mode", pin="97531")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Log in again", resp.json()["error"])
        self.assertFalse(_row("crisis_mode").is_enabled)

    def test_a_session_with_no_mark_must_log_in_again(self):
        """A session that logged in before the mark existed."""
        from core.switch_pin import LOGIN_MARK_KEY
        s = self.client.session
        s.pop(LOGIN_MARK_KEY, None)
        s.save()
        self._says_log_in_again(self.ops("aragorn", want="on", pin=TEST_PIN))

    def test_the_real_two_step_login_marks_the_session(self):
        user = User.objects.create_superuser("two_step", "t@x.test",
                                             "pw-of-the-test")
        _set_pin(user)
        c = Client()
        r = c.post("/login/", {"username": "two_step",
                               "password": "pw-of-the-test"})
        self.assertEqual(r.status_code, 302)
        r = c.post("/login/pin/", {"pin": TEST_PIN})
        self.assertEqual(r.status_code, 302)
        c.post(TOGGLE, {"key": "aragorn", "next": "ops", "want": "on",
                        "pin": TEST_PIN})
        self.assertTrue(_row("aragorn").is_enabled)
        [armed] = _audit("switch_armed", "aragorn")
        self.assertEqual(armed.data["who"], "two_step")

    def test_the_mark_is_neither_the_pin_nor_its_hash(self):
        from core.switch_pin import LOGIN_MARK_KEY
        mark = self.client.session[LOGIN_MARK_KEY]
        stored = get_or_create_profile(self.admin).access_pin_hash
        self.assertTrue(mark)
        self.assertNotIn(TEST_PIN, mark)
        self.assertNotIn(mark, stored)
        self.assertNotIn(stored, mark)

    def test_non_live_keys_ignore_the_mark(self):
        from core.switch_pin import LOGIN_MARK_KEY
        s = self.client.session
        s.pop(LOGIN_MARK_KEY, None)
        s.save()
        self.ops("scraper_news")
        self.assertTrue(_row("scraper_news").is_enabled)
        _raw("aragorn", True)
        self.ops("aragorn", want="off")     # OFF is free, mark or not
        self.assertFalse(_row("aragorn").is_enabled)


# ── 13. a spent counter is never given a sixth guess ───────────────────
class ASpentCounterIsNeverCheckedTests(_Fixture):

    def test_the_right_pin_on_a_spent_counter_ends_the_session(self):
        from dashboard.lock_views import ATTEMPTS_KEY, MAX_ATTEMPTS
        s = self.client.session
        s[ATTEMPTS_KEY] = MAX_ATTEMPTS
        s.save()
        resp = self.ops("aragorn", want="on", pin=TEST_PIN)
        self.assertIn("session has ended", _last_flash(resp))
        self.assertFalse(_row("aragorn").is_enabled)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(_audit("switch_refused", "aragorn")[-1]
                         .data["reason"], "locked_out")
