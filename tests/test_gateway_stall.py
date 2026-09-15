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


class AMissMustNotBeSilentTests(TestCase):
    """Eight misses, not one log line (2026-09-15).

    Measured on the live box:

        misses = 8 | last_equity_at = 2026-09-14 23:33:43

    and six hours of `worker-fast worker-slow` logs grepped for "broker sync"
    returned only routine `_follow_the_account` INFO lines. Not one
    `broker sync: ... unreadable:` warning, although that line sat
    immediately before every increment of the counter that reached 8.

    THE REASON, AND WHY IT IS A DESIGN TRAP RATHER THAN A TYPO

    `sync_broker_account` logged from its `except`. Neither read raises:

        account_values()    if not self._connect(): return None   # no log
        broker_portfolio()  if not self._connect(): return None   # no log

    "None means UNREADABLE" is their documented contract and a good one —
    `account_values` argues for it at length, because a caller that cannot
    tell "no reading" from "an empty account" will eventually tell an
    operator their money is gone. The caller's mistake was to rely on an
    exception it had never been promised.

    So the exact case that matters most — a Gateway that is UP and not
    logged in, the one the whole ibkr-doctor exists for — was the one case
    that produced no log at all, while every equity figure on every page
    quietly aged.

    These tests pin the caller's own line. The client is a MagicMock whose
    methods RETURN None and never raise, so a log that depends on an
    exception cannot satisfy them.
    """

    def setUp(self):
        cache.clear()
        from django.contrib.auth.models import User

        from bot_program.models import IBKRAccount
        self.user = User.objects.create_user("silent_u", password="x")
        self.acct = IBKRAccount.objects.create(
            user=self.user, label="Main", host="ibgateway",
            port=4003, client_id=1)
        self.acct.set_credentials("U7654321")
        self.acct.save()

    def _sync_unreadable(self):
        """One pass where both reads answer None WITHOUT raising."""
        from bot_program.tasks import sync_broker_account
        trader = MagicMock()
        trader.net_liquidation.return_value = None
        trader.broker_portfolio.return_value = None
        trader.net_liquidation.side_effect = None      # explicitly: no raise
        trader.broker_portfolio.side_effect = None
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch("bot_program.engine.ibkr_client.IBKRTrader",
                   return_value=trader), \
             patch("bot_program.notifications.notify_broker_unreachable"):
            with self.assertLogs("bot_program.tasks", level="WARNING") as got:
                out = sync_broker_account.__wrapped__.__wrapped__()
        return out, "\n".join(got.output)

    def test_a_miss_that_raised_nothing_still_writes_a_line(self):
        out, logged = self._sync_unreadable()
        self.assertEqual(out["unreachable"], 1)
        self.assertIn("broker sync", logged)

    def test_the_line_names_the_account_and_the_socket(self):
        """An operator reading `docker logs` needs to know WHICH account and
        WHERE, because a box can carry five Gateways on five ports."""
        _out, logged = self._sync_unreadable()
        self.assertIn("Main", logged)
        self.assertIn("ibgateway", logged)
        self.assertIn("4003", logged)

    def test_the_line_says_nothing_raised(self):
        """The distinction that cost the six hours: an operator who greps for
        a failure and finds nothing concludes the sync is not running. The
        line has to say the reads ANSWERED, and answered nothing."""
        _out, logged = self._sync_unreadable()
        self.assertIn("None", logged)
        self.assertIn("raise", logged.lower())

    def test_it_points_at_the_tool_that_diagnoses_it(self):
        _out, logged = self._sync_unreadable()
        self.assertIn("ibkr-doctor", logged)

    def test_every_miss_is_logged_not_only_the_alerting_one(self):
        """The notification waits for the third miss and then goes quiet for
        six hours. The log must not: a miss the operator can only learn about
        from an alert they have already been shown is a miss they cannot
        follow."""
        for expected in (1, 2, 3, 4):
            out, logged = self._sync_unreadable()
            self.assertIn("broker sync", logged)
            self.assertIn(f"miss {expected}", logged)

    def test_the_reads_it_guards_are_the_kind_that_return_none(self):
        """The confrontation. If either read is ever changed to RAISE, the
        caller's own line becomes redundant — harmless, but this test is
        where that shows up rather than in a silent log six months later."""
        import inspect

        from bot_program.engine.ibkr_client import IBKRTrader
        for name in ("account_values", "broker_portfolio"):
            src = inspect.getsource(getattr(IBKRTrader, name))
            self.assertIn(
                "if not self._connect():", src,
                f"{name} no longer has a connect-failure branch; the caller's "
                f"unconditional log was written for exactly that branch")
            branch = src[src.index("if not self._connect():"):][:120]
            self.assertIn(
                "return None", branch,
                f"{name}'s connect-failure branch no longer returns None — if "
                f"it now raises, say so and simplify the caller")

    def test_the_log_precedes_the_alert_gate(self):
        """Read off the source. The warning must sit ABOVE the
        `misses < BROKER_MISS_ALERT_AFTER` return, or the first two misses of
        every outage are silent again — which is most of a 45-minute window."""
        from pathlib import Path as _P

        from django.conf import settings as _s
        src = (_P(_s.BASE_DIR) / "bot_program" / "tasks.py").read_text(
            encoding="utf-8")
        head = src.index("def _note_broker_miss")
        body = src[head:src.index("def _clear_broker_miss")]
        self.assertIn("logger.warning", body)
        self.assertLess(
            body.index("logger.warning"),
            body.index("BROKER_MISS_ALERT_AFTER"),
            "the line is written only after the alert gate, so the first two "
            "misses of every outage would still be silent")
