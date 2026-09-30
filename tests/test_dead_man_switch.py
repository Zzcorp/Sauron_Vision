"""The dead man's switch: the box pings a watcher that is not on it.

2026-09-30: the hosting month ran out, the VPS stopped, and every alarm
this platform has stopped with it, so nobody heard. core/dead_man_switch.py
pings an outside watcher (healthchecks.io) after every bot tick; when the
pings stop, the watcher raises the alarm. Pinned here:
  - off without a URL, refused without https, the trailing slash dropped;
  - an ok ping after the tick, /fail when it raises (the type only, never
    the message), and the exception still reaches Celery;
  - a paused platform still pings, and says it is skipped;
  - a ping that fails never fails the tick, is logged, and the URL (a
    secret) never reaches a log line, and the scrubber redacts it;
  - the wiring: the tick wears it OUTSIDE the gate, its Celery name and
    component key unchanged; the setting, both .env examples, the
    runbook and the command.

Run with:  python manage.py test tests.test_dead_man_switch
"""
import os
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from core import dead_man_switch as dms

BASE = Path(__file__).resolve().parent.parent
URL = "https://hc-ping.com/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"


def _answer(code=200):
    r = MagicMock()
    r.status_code = code
    return r


@override_settings(DEAD_MAN_SWITCH_URL=URL)
class ThePingTests(SimpleTestCase):

    def test_off_without_a_url_sends_nothing(self):
        with override_settings(DEAD_MAN_SWITCH_URL=""), \
                patch.object(dms.requests, "post") as post:
            self.assertFalse(dms.ping())
        post.assert_not_called()

    def test_an_ok_ping_posts_to_the_url_within_five_seconds(self):
        with patch.object(dms.requests, "post",
                          return_value=_answer()) as post:
            self.assertTrue(dms.ping(ok=True, detail="tick ran"))
        self.assertEqual(post.call_args.args[0], URL)
        self.assertEqual(post.call_args.kwargs["timeout"], 5)
        self.assertEqual(post.call_args.kwargs["data"], b"tick ran")

    def test_a_failure_posts_to_the_fail_endpoint(self):
        with patch.object(dms.requests, "post",
                          return_value=_answer()) as post:
            dms.ping(ok=False, detail="tick raised RuntimeError")
        self.assertEqual(post.call_args.args[0], URL + "/fail")

    def test_a_trailing_slash_is_dropped(self):
        with override_settings(DEAD_MAN_SWITCH_URL=URL + "/ "), \
                patch.object(dms.requests, "post",
                             return_value=_answer()) as post:
            dms.ping(ok=False)
        self.assertEqual(post.call_args.args[0], URL + "/fail")

    def test_http_is_refused_and_said(self):
        with override_settings(DEAD_MAN_SWITCH_URL="http://hc-ping.com/x"), \
                patch.object(dms.requests, "post") as post, \
                self.assertLogs("core.dead_man_switch", "WARNING") as logs:
            self.assertFalse(dms.ping())
        post.assert_not_called()
        self.assertIn("not an https URL", logs.output[0])

    def test_a_ping_that_cannot_land_is_logged_never_raised(self):
        with patch.object(dms.requests, "post",
                          side_effect=requests.ConnectionError(URL)), \
                self.assertLogs("core.dead_man_switch", "WARNING") as logs:
            self.assertFalse(dms.ping())
        line = "\n".join(logs.output)
        self.assertIn("hc-ping.com", line)
        self.assertIn("ConnectionError", line)
        self.assertNotIn("0f1e2d3c", line, "the URL's key reached the log")

    def test_a_refusing_watcher_is_logged(self):
        with patch.object(dms.requests, "post", return_value=_answer(404)), \
                self.assertLogs("core.dead_man_switch", "WARNING") as logs:
            self.assertFalse(dms.ping())
        self.assertIn("HTTP 404", logs.output[0])
        self.assertNotIn("0f1e2d3c", logs.output[0])

    def test_the_body_is_bounded(self):
        with patch.object(dms.requests, "post",
                          return_value=_answer()) as post:
            dms.ping(detail="x" * 5000)
        self.assertEqual(len(post.call_args.kwargs["data"]), dms.MAX_BODY)

    def test_where_names_the_host_and_never_the_key(self):
        self.assertEqual(dms.where(), "hc-ping.com")


@override_settings(DEAD_MAN_SWITCH_URL=URL)
class TheHeartbeatTests(SimpleTestCase):

    def test_a_tick_that_returns_pings_ok_and_returns_its_result(self):
        @dms.heartbeat
        def tick():
            return {"configs_ticked": 3}
        with patch.object(dms, "ping") as ping:
            self.assertEqual(tick(), {"configs_ticked": 3})
        ping.assert_called_once_with(ok=True, detail="tick ran")

    def test_a_paused_platform_still_pings_and_says_so(self):
        @dms.heartbeat
        def tick():
            return {"status": "skipped", "reason": "platform_disabled"}
        with patch.object(dms, "ping") as ping:
            tick()
        self.assertTrue(ping.call_args.kwargs["ok"])
        self.assertEqual(ping.call_args.kwargs["detail"],
                         "tick skipped (platform_disabled)")

    def test_a_tick_that_raises_pings_fail_with_the_type_alone(self):
        @dms.heartbeat
        def tick():
            raise RuntimeError("lost 2,400.00 on BTCUSD")
        with patch.object(dms, "ping") as ping, \
                self.assertRaises(RuntimeError):
            tick()
        ping.assert_called_once_with(ok=False,
                                     detail="tick raised RuntimeError")

    def test_a_watcher_that_is_down_never_fails_the_tick(self):
        @dms.heartbeat
        def tick():
            return "done"
        with patch.object(dms.requests, "post",
                          side_effect=requests.Timeout()), \
                self.assertLogs("core.dead_man_switch", "WARNING"):
            self.assertEqual(tick(), "done")

    def test_the_url_is_scrubbed_from_any_message(self):
        from core.secret_scrub import scrub
        with patch.dict(os.environ, {"DEAD_MAN_SWITCH_URL": URL}):
            self.assertNotIn("0f1e2d3c", scrub(f"POST {URL}/fail failed"))


class TheWiringTests(TestCase):

    def test_the_tick_wears_it_outside_the_gate(self):
        """So a gate skip still pings: the wrapper's __wrapped__ is the
        gate's wrapper, which carries the component key."""
        from bot_program.tasks import tick_all_asset_bots
        run = tick_all_asset_bots.run
        self.assertEqual(run.__wrapped__.component_key, "pipeline_asset_bots")
        self.assertEqual(run.__wrapped__.__wrapped__.__name__,
                      "tick_all_asset_bots")
        self.assertEqual(tick_all_asset_bots.name,
                         "bot_program.tasks.tick_all_asset_bots")

    def test_the_digest_still_reads_the_component(self):
        from bot_program.tasks import tick_all_asset_bots
        from core.component_digest import _component_key_of
        self.assertEqual(_component_key_of(tick_all_asset_bots),
                         "pipeline_asset_bots")

    @override_settings(DEAD_MAN_SWITCH_URL=URL)
    def test_a_gated_off_tick_pings_skipped(self):
        """No component rows in a fresh test database: the gate skips, the
        tick body never runs, and the watcher still hears the box."""
        from bot_program.tasks import tick_all_asset_bots
        with patch.object(dms.requests, "post",
                          return_value=_answer()) as post, \
                patch("bot_program.asset_engine.runner.run_all_asset_bots"
                      ) as run_all:
            out = tick_all_asset_bots.run()
        run_all.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(post.call_args.args[0], URL)
        self.assertIn(b"tick skipped", post.call_args.kwargs["data"])

    def test_the_setting_reads_the_environment(self):
        src = (BASE / "config" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('DEAD_MAN_SWITCH_URL = os.getenv("DEAD_MAN_SWITCH_URL", '
                      '"").strip()', src)

    def test_both_env_examples_document_it(self):
        for name in (".env.example", ".env.production.example"):
            text = (BASE / name).read_text(encoding="utf-8")
            self.assertIn("DEAD_MAN_SWITCH_URL=\n", text, name)

    def test_the_runbook_has_the_section(self):
        text = (BASE / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("## When the box itself goes silent", text)
        for line in ("DEAD_MAN_SWITCH_URL=", "manage.py dead_man_switch --ping",
                     "Period **5 minutes**", "Grace\n     **15 minutes**",
                     "auto-renewal ON", "/healthz/"):
            self.assertIn(line, text)


class TheCommandTests(SimpleTestCase):

    def test_off_says_so(self):
        with override_settings(DEAD_MAN_SWITCH_URL=""), \
                self.assertRaisesMessage(CommandError, "is OFF"):
            call_command("dead_man_switch")

    def test_http_is_refused(self):
        with override_settings(DEAD_MAN_SWITCH_URL="http://hc-ping.com/x"), \
                self.assertRaisesMessage(CommandError, "not an https"):
            call_command("dead_man_switch")

    @override_settings(DEAD_MAN_SWITCH_URL=URL)
    def test_on_names_the_host_and_never_the_key(self):
        out = StringIO()
        call_command("dead_man_switch", stdout=out)
        self.assertIn("ON", out.getvalue())
        self.assertIn("hc-ping.com", out.getvalue())
        self.assertNotIn("0f1e2d3c", out.getvalue())

    @override_settings(DEAD_MAN_SWITCH_URL=URL)
    def test_ping_sends_one_and_reports_it(self):
        out = StringIO()
        with patch.object(dms.requests, "post",
                          return_value=_answer()) as post:
            call_command("dead_man_switch", "--ping", stdout=out)
        post.assert_called_once()
        self.assertIn("Ping landed", out.getvalue())

    @override_settings(DEAD_MAN_SWITCH_URL=URL)
    def test_a_ping_that_does_not_land_is_an_error(self):
        with patch.object(dms.requests, "post", return_value=_answer(500)), \
                self.assertLogs("core.dead_man_switch", "WARNING"), \
                self.assertRaisesMessage(CommandError, "did not land"):
            call_command("dead_man_switch", "--ping")
