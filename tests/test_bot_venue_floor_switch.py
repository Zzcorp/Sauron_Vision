"""The switch of the venue floor for bots: bots_venue_floor_live
(2026-11-12).

A live-money switch: ON, a bot's order under the venue's smallest size
opens at that size, which is more and larger real-money entries. So it is
named by hand in LIVE_MONEY_SWITCHES: its ON takes the trading PIN at
/ops/, the shell and the Django admin refuse it, "all on" never arms it,
and it arrives OFF. A row that is missing reads OFF.

Run with:  python manage.py test tests.test_bot_venue_floor_switch
"""
from io import StringIO

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

KEY = "bots_venue_floor_live"
TEST_PIN = "583920"     # a test-only value


def _flashes(resp) -> str:
    return " | ".join(str(m) for m in get_messages(resp.wsgi_request))


def _row():
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.get(key=KEY)


class TheSwitchTests(TestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()
        self.admin = User.objects.create_superuser("floor_admin", "a@x", "x")
        self.client.force_login(self.admin)

    def test_it_is_a_live_money_switch_named_by_hand(self):
        from bot_program.asset_engine.base import VENUE_FLOOR_SWITCH_KEY
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           LIVE_MONEY_SWITCHES,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        from core.switch_pin import is_live, needs_pin
        self.assertEqual(VENUE_FLOOR_SWITCH_KEY, KEY)
        self.assertIn(KEY, LIVE_MONEY_SWITCHES)
        self.assertNotIn(KEY, ORC_MIND_SWITCHES)
        self.assertIn(KEY, PIN_SWITCHES)
        self.assertIn(KEY, BULK_ENABLE_EXEMPT)
        self.assertTrue(is_live(KEY))
        self.assertTrue(needs_pin(KEY, was_on=False, want_on=True))
        self.assertFalse(needs_pin(KEY, was_on=True, want_on=False))

    def test_it_is_seeded_off_in_the_system_group(self):
        from core.platform_control import DEFAULT_COMPONENTS
        (seed,) = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        self.assertNotIn("is_enabled", seed)
        self.assertEqual(seed["category"], "system")
        self.assertEqual(seed["name"], "Bots: Venue Floor")
        row = _row()
        self.assertEqual((row.category, row.is_enabled, row.name),
                         ("system", False, "Bots: Venue Floor"))

    def test_its_description_fits_the_column_and_says_what_on_does(self):
        from core.platform_control import DEFAULT_COMPONENTS
        (seed,) = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        words = seed["description"]
        self.assertLessEqual(len(words), 300, len(words))
        self.assertTrue(words.startswith("Off (default)"), words)
        self.assertIn("venue's smallest size", words)
        self.assertIn("MAX BOT FLOOR RISK", words)
        self.assertIn("/setup/", words)

    def test_a_missing_row_reads_off(self):
        from bot_program.asset_engine.base import venue_floor_on
        from core.platform_control import PlatformComponent
        self.assertFalse(venue_floor_on())
        PlatformComponent.objects.filter(key=KEY).delete()
        self.assertFalse(venue_floor_on())

    def test_all_on_never_arms_it(self):
        resp = self.client.post("/admin-dashboard/bulk-toggle/",
                                {"category": "system", "action": "enable",
                                 "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertFalse(_row().is_enabled)
        from core.platform_control import PlatformComponent
        self.assertTrue(PlatformComponent.objects.get(
            key="platform_master").is_enabled)

    def test_turning_it_on_takes_the_trading_pin(self):
        from bot_program.asset_engine.base import venue_floor_on
        from portfolio.trader_profile import get_or_create_profile
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops"})
        self.assertIn("trading PIN", _flashes(resp))
        self.assertFalse(_row().is_enabled)
        prof = get_or_create_profile(self.admin)
        prof.set_pin(TEST_PIN)
        prof.save()
        self.client.force_login(self.admin)   # the login after the PIN
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops", "want": "on",
                                 "pin": "104729"})
        self.assertFalse(_row().is_enabled)
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops", "want": "on",
                                 "pin": TEST_PIN})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertTrue(_row().is_enabled)
        self.assertTrue(venue_floor_on())

    def test_turning_it_off_is_free(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key=KEY).update(is_enabled=True)
        self.client.post("/admin-dashboard/toggle/",
                         {"key": KEY, "next": "ops", "want": "off"})
        self.assertFalse(_row().is_enabled)

    def test_the_shell_never_turns_it_on(self):
        out, err = StringIO(), StringIO()
        try:
            call_command("component", "on", KEY, stdout=out, stderr=err)
        except SystemExit:
            pass
        except Exception as e:  # noqa: BLE001 — a CommandError is a refusal
            err.write(str(e))
        self.assertFalse(_row().is_enabled)
        self.assertIn("trading PIN", out.getvalue() + err.getvalue())
