"""A Gateway that is UP is not a Gateway that is LOGGED IN.

The operator's first real IB Gateway sat behind a notice dialog for three
hours while `dc ps` said "Up 3 hours" and nothing on the platform said a
word. IB Gateway 10.45 shows a generic box titled "Gateway" for server
replies, account notices and marketing interstitials; the IBC automation
in the container cannot read its HTML body and, by design, leaves it on
screen with no timeout (open IBC defects #360/#382, maintainer-confirmed
August 2026). No 2FA push arrives because the server never reached that
step, so the operator watches a phone that will never ring.

Three things now say so, pinned here:
  * the container healthcheck probes the Gateway's INTERNAL API port,
    which only listens after login — `ps` reads (unhealthy) when stalled;
  * VNC can be switched on inside the container to SEE the dialog, with
    nothing published to the host (two tests already forbid that);
  * the account sync, the one thing that asks every 15 minutes, raises a
    system_health notification after three consecutive misses, once per
    six hours — a live Gateway restarts for 2FA daily, and an alert that
    fires on every blip is one the operator mutes.

Run with:  python manage.py test tests.test_gateway_stall
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

REPO = Path(settings.BASE_DIR)


def _compose():
    return yaml.safe_load((REPO / "deploy" / "docker-compose.yml"
                           ).read_text(encoding="utf-8"))


SLOTS = ["ibgateway"] + [f"ibgateway-{n}" for n in range(2, 6)]


class TheHealthcheckProbesTheLoginNotTheProcessTests(TestCase):

    def test_every_slot_inherits_a_healthcheck(self):
        services = _compose()["services"]
        for name in SLOTS:
            hc = services[name].get("healthcheck")
            self.assertTrue(hc, f"{name} has no healthcheck")
            self.assertIn("socat", " ".join(hc["test"]))

    def test_it_probes_the_internal_api_ports_not_the_relays(self):
        """4003/4004 accept a TCP connect even while the Gateway behind
        them is stuck — socat is up before the login is. Only the
        Gateway's own 4001/4002 prove a completed login."""
        test = " ".join(_compose()["services"]["ibgateway"]["healthcheck"]["test"])
        self.assertIn("127.0.0.1:4001", test)
        self.assertIn("127.0.0.1:4002", test)
        self.assertNotIn("4003", test)
        self.assertNotIn("4004", test)

    def test_the_start_period_outlasts_a_java_login(self):
        """A Gateway takes minutes to boot and log in; a healthcheck that
        fails it before that is a false alarm on every start."""
        hc = _compose()["services"]["ibgateway"]["healthcheck"]
        self.assertGreaterEqual(int(str(hc["start_period"]).rstrip("s")), 180)


class VNCIsAvailableAndPublishesNothingTests(TestCase):

    def test_every_slot_can_start_vnc_from_one_variable(self):
        raw = (REPO / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertEqual(raw.count("VNC_SERVER_PASSWORD: ${IBKR_VNC_PASSWORD:-}"),
                         len(SLOTS))

    def test_blank_keeps_it_off(self):
        """`:-` with no default — an operator who never set it must not
        get a VNC server with an empty password."""
        raw = (REPO / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("${IBKR_VNC_PASSWORD:-}", raw)
        self.assertNotIn("${IBKR_VNC_PASSWORD:-s", raw)

    def test_still_no_port_is_published(self):
        """Seeing the screen must not mean exposing it. The route is an
        SSH tunnel to the container's compose-network IP."""
        services = _compose()["services"]
        for name in SLOTS:
            self.assertFalse(services[name].get("ports"), name)

    def test_the_variable_is_documented_with_the_tunnel_route(self):
        for f in (".env.example", ".env.production.example"):
            text = (REPO / f).read_text(encoding="utf-8")
            self.assertIn("IBKR_VNC_PASSWORD=", text, f)
            self.assertIn("ssh -L 5900:", text, f)
            self.assertIn("docker inspect", text, f)


class TheRunbookNamesTheStallTests(TestCase):

    def test_it_describes_the_dialog_the_healthcheck_and_the_log(self):
        text = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("IBC: GATEWAY", text)
        self.assertIn("(unhealthy)", text)
        self.assertIn("launcher.log", text)
        self.assertIn("#382", text)

    def test_it_says_no_push_is_coming(self):
        """The most expensive misunderstanding: watching a phone that
        will never ring because the server never reached 2FA."""
        text = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("No IB Key push arrives", text)


class TheSyncRaisesTheAlarmTests(TestCase):

    def setUp(self):
        cache.clear()
        from django.contrib.auth.models import User
        from bot_program.models import IBKRAccount
        self.user = User.objects.create_user("stall_u", password="x")
        self.acct = IBKRAccount.objects.create(
            user=self.user, label="ISA_CAPITAL", host="ibgateway",
            port=4003, client_id=1)
        self.acct.set_credentials("U1234567")
        self.acct.save()

    def _sync(self, reachable):
        from bot_program.tasks import sync_broker_account
        trader = MagicMock()
        trader.net_liquidation.return_value = (1.0, "GBP") if reachable else None
        trader.broker_portfolio.return_value = [] if reachable else None
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch("bot_program.engine.ibkr_client.IBKRTrader",
                   return_value=trader), \
             patch("bot_program.notifications.notify_broker_unreachable") \
                as notify:
            sync_broker_account.__wrapped__.__wrapped__()
        return notify

    def test_two_misses_say_nothing(self):
        """A live Gateway restarts for 2FA daily; two 15-minute blips are
        not a stall and an alert on every blip gets muted."""
        self._sync(False)
        notify = self._sync(False)
        notify.assert_not_called()

    def test_the_third_consecutive_miss_alerts_once(self):
        self._sync(False)
        self._sync(False)
        notify = self._sync(False)
        notify.assert_called_once()
        kw = notify.call_args.kwargs
        self.assertEqual(kw["label"], "ISA_CAPITAL")
        self.assertEqual(kw["port"], 4003)
        self.assertEqual(kw["misses"], 3)

    def test_and_not_again_inside_the_cooldown(self):
        for _ in range(3):
            self._sync(False)
        notify = self._sync(False)
        notify.assert_not_called()

    def test_a_successful_sync_resets_the_count(self):
        self._sync(False)
        self._sync(False)
        self._sync(True)
        self._sync(False)
        notify = self._sync(False)
        notify.assert_not_called()

    def test_the_alert_uses_a_registered_kind(self):
        """A new kind is a migration in another app; system_health is
        what this is, and it already exists."""
        from bot_program.notifications import BOT_KINDS, notify_broker_unreachable
        self.assertIn("system_health", BOT_KINDS)
        with patch("bot_program.notifications.dispatch_notification") as d:
            notify_broker_unreachable(self.user, label="ISA_CAPITAL",
                                      host="ibgateway", port=4003, misses=3)
        self.assertEqual(d.call_args.args[1], "system_health")
