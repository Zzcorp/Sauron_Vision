"""Every new signal is announced, from every creator, once (2026-09-26).

MEASURED ON THE VPS, 2026-09-26: ten signals in 24 hours; the last one
(pk 464, "starter_stock_momentum matched on MSFT", the opportunity
scanner) replayed by hand reached the group at once. It had simply never
been sent: only the rule engine announced a new Signal. The scanner, the
fast rules and the TradingView webhook wrote rows and said nothing.

Pinned here: each creator announces once on create, never on the
scanner's reuse branch, never with emit=False, never on an as_of replay,
never for the HQ test button; a raising announcement step never breaks
its creator; the webhook's response does not wait on Telegram (queued
after the commit, one publish); the rule engine keeps its order (banner,
bell, channels); the flood guard holds a chat at 20 signal messages an
hour and the next one says "+N more", and a count is cleared only by the
number a message actually told.

Run with:  python manage.py test tests.test_signal_announce
"""
import os
import re
import time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

TOKEN = "123456:announce-test-token"
SECRET = "announce-test-secret"


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _signal(inst, **kw):
    from signals.models import Signal
    fields = dict(instrument=inst, signal_type="composite",
                  direction="bullish", urgency="medium", title="t",
                  description="d", rule_name="r_flood", score=0.7,
                  sub_scores={}, price_at_signal=Decimal("100"))
    fields.update(kw)
    return Signal.objects.create(**fields)


class AnnounceHelperTests(TestCase):
    def setUp(self):
        self.inst = _instrument("ANN1")
        User.objects.create_user("ann_staff", password="x", is_staff=True)

    def test_the_three_steps_in_the_rule_engines_order(self):
        from signals.announce import announce_new_signal
        calls = []

        def push(user, kind, payload):
            calls.append(("banner", kind, payload["symbol"]))
            return True

        def bell(signal):
            calls.append(("bell", signal.pk))

        def channels(signal):
            calls.append(("channels", signal.pk))
            return {"chats": 0, "sent": 0, "held": 0, "refused": 0}

        sig = _signal(self.inst)
        with patch("dashboard.consumers.push_eye_event", side_effect=push), \
                patch("alerts.notify.notify_new_signal", side_effect=bell), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=channels):
            out = announce_new_signal(sig)
        self.assertEqual(calls, [("banner", "new_signal", "ANN1"),
                                 ("bell", sig.pk), ("channels", sig.pk)])
        self.assertEqual(out["banner"], 1)
        self.assertEqual(out["bell"], "ok")
        self.assertEqual(out["channels"]["chats"], 0)

    def test_every_step_failing_never_raises(self):
        from signals.announce import announce_new_signal
        with patch("dashboard.consumers.push_eye_event",
                   side_effect=RuntimeError("socket down")), \
                patch("alerts.notify.notify_new_signal",
                      side_effect=RuntimeError("bell down")), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=RuntimeError("telegram down")), \
                self.assertLogs("signals.announce", "ERROR"):
            out = announce_new_signal(_signal(self.inst))
        self.assertEqual((out["banner"], out["bell"], out["channels"]),
                         ("failed", "failed", "failed"))


class RuleEngineTests(TestCase):
    def test_the_rule_engine_announces_through_the_helper_once(self):
        from signals.tasks import _create_signals_and_notify
        _instrument("SOLUSD", "crypto")
        payload = {"symbol": "SOLUSD", "rule": "golden_cross",
                   "direction": "LONG", "score": 0.8, "headline": "h",
                   "thesis": "t", "entry": 100.0, "stop": 98.0,
                   "target": 104.0}
        with patch("signals.announce.announce_new_signal") as ann:
            self.assertEqual(_create_signals_and_notify([payload]), 1)
            # the same rule on the same instrument is deduped: no row, no
            # second announcement
            self.assertEqual(_create_signals_and_notify([payload]), 0)
        ann.assert_called_once()
        self.assertEqual(ann.call_args.args[0].rule_name, "golden_cross")


class ScannerTests(TestCase):
    def setUp(self):
        from market_data.models import PriceData
        from signals.models import OpportunitySetup
        self.inst = _instrument("ANNSC")
        PriceData.objects.create(
            instrument=self.inst, timeframe="1d",
            timestamp=timezone.now() - timedelta(hours=1),
            open=Decimal("100"), high=Decimal("100"), low=Decimal("100"),
            close=Decimal("100"), volume=0, source="test")
        self.setup = OpportunitySetup.objects.create(
            name="ann_setup", direction="bullish", conditions=[],
            min_match_score=0.0, suggested_horizon_days=5, asset_classes=[],
            sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=True)

    def test_a_live_scan_announces_the_row_it_creates_once(self):
        from signals.opportunity_scanner import scan_setup
        with patch("signals.announce.announce_new_signal") as ann:
            first = scan_setup(self.setup, self.inst, as_of=False)
            second = scan_setup(self.setup, self.inst, as_of=False)
        self.assertEqual(first["signal_id"], second["signal_id"])
        ann.assert_called_once()
        self.assertEqual(ann.call_args.args[0].pk, first["signal_id"])

    def test_emit_false_and_a_replay_announce_nothing(self):
        from signals.opportunity_scanner import _emit_match, scan_setup
        with patch("signals.announce.announce_new_signal") as ann:
            pending = scan_setup(self.setup, self.inst, as_of=False,
                                 emit=False)
            self.assertTrue(pending.get("pending"))
            replay = scan_setup(self.setup, self.inst, now=timezone.now())
            self.assertTrue(replay["matched"])
            # a direct call (a test, a diagnostic) announces nothing either
            from signals.models import Signal
            Signal.objects.filter(pk=replay["signal_id"]).update(
                is_active=False)
            _emit_match(self.setup, self.inst, 0.9, [], 100.0)
        ann.assert_not_called()

    def test_a_live_pass_announces_a_replayed_pass_does_not(self):
        from signals.opportunity_scanner import scan_all_setups
        with patch("signals.announce.announce_new_signal") as ann:
            replay = scan_all_setups(now=timezone.now())
        self.assertEqual(replay["matches"], 1)
        ann.assert_not_called()
        from signals.models import Signal
        Signal.objects.update(is_active=False)
        with patch("signals.announce.announce_new_signal") as ann:
            live = scan_all_setups()
        self.assertEqual(live["matches"], 1)
        ann.assert_called_once()

    def test_a_broken_announcement_never_breaks_the_scan(self):
        from signals.models import OpportunityFlag
        from signals.opportunity_scanner import scan_setup
        User.objects.create_user("scan_staff", password="x", is_staff=True)
        with patch("dashboard.consumers.push_eye_event",
                   side_effect=RuntimeError("socket down")), \
                patch("alerts.notify.notify_new_signal",
                      side_effect=RuntimeError("bell down")), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=RuntimeError("telegram down")), \
                self.assertLogs("signals.announce", "ERROR"):
            out = scan_setup(self.setup, self.inst, as_of=False)
        self.assertTrue(out["matched"])
        self.assertEqual(OpportunityFlag.objects.filter(
            setup=self.setup).count(), 1)


class FastRulesTests(TestCase):
    def setUp(self):
        from signals.fast_rules import (FastRule, SignalSpec,
                                        register_fast_rule, reset_fast_rules)
        reset_fast_rules()
        self.addCleanup(self._restore)
        self.inst = _instrument("ANNFR")

        class _Always(FastRule):
            rule_name = "ann_fast_rule"
            event_types = ["ann_evt"]
            cooldown_seconds = 0

            def evaluate(self, event_type, payload):
                from instruments.models import Instrument
                inst = Instrument.objects.get(symbol=payload["symbol"])
                return SignalSpec(instrument=inst, direction="bullish",
                                  score=0.8, price=100.0, stop=98.0,
                                  target=104.0)

        register_fast_rule(_Always())

    @staticmethod
    def _restore():
        from signals.fast_rules import register_default_rules, reset_fast_rules
        reset_fast_rules()
        register_default_rules()

    def test_each_created_row_is_announced_once(self):
        from signals.fast_rules import dispatch_event
        with patch("signals.announce.announce_new_signal") as ann:
            out = dispatch_event("ann_evt", {"symbol": "ANNFR"})
            dispatch_event("other_evt", {"symbol": "ANNFR"})
        self.assertEqual(len(out["signal_ids"]), 1)
        ann.assert_called_once()
        self.assertEqual(ann.call_args.args[0].pk, out["signal_ids"][0])

    def test_the_admin_test_button_announces_nothing(self):
        from signals.fast_rules import dispatch_event
        with patch("signals.announce.announce_new_signal") as ann, \
                self.assertLogs("signals.fast_rules", "INFO") as cm:
            out = dispatch_event("ann_evt", {"symbol": "ANNFR"},
                                 source="admin")
        self.assertEqual(len(out["signal_ids"]), 1)
        ann.assert_not_called()
        self.assertIn("not announced", "\n".join(cm.output))

    def test_a_broken_announcement_never_breaks_the_dispatch(self):
        from signals.fast_rules import dispatch_event
        from signals.models import FastEvent
        with patch("alerts.notify.notify_new_signal",
                   side_effect=RuntimeError("bell down")), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=RuntimeError("telegram down")), \
                self.assertLogs("signals.announce", "ERROR"):
            out = dispatch_event("ann_evt", {"symbol": "ANNFR"})
        self.assertEqual(len(out["signal_ids"]), 1)
        self.assertTrue(FastEvent.objects.filter(pk=out["event_id"]).exists())


class WebhookTests(TestCase):
    def setUp(self):
        import json
        from market_data.models import LiveQuote
        self.json = json
        os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = SECRET
        self.addCleanup(os.environ.pop, "TRADINGVIEW_WEBHOOK_SECRET", None)
        self.inst = _instrument("ANNTV", "commodity")
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("82.45"),
                                 source="test")

    def _post(self):
        return self.client.post(
            "/api/webhook/tradingview/", content_type="application/json",
            data=self.json.dumps({"secret": SECRET, "symbol": "ANNTV",
                                  "action": "buy", "strategy": "squeeze"}))

    def test_the_response_never_waits_on_telegram(self):
        from signals import tasks
        with patch("requests.post") as post, \
                patch("alerts.dispatch.dispatch_signal_alert") as dispatch, \
                patch.object(tasks.announce_signal, "apply_async") as queue, \
                self.captureOnCommitCallbacks(execute=False) as callbacks:
            r = self._post()
        self.assertEqual(r.status_code, 200)
        sid = r.json()["signal_id"]
        # answered without waiting on Telegram: nothing announced, and
        # (inside this test's transaction) nothing queued before the commit
        post.assert_not_called()
        dispatch.assert_not_called()
        queue.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        # the commit queues the task with one publish (no retries while a
        # broker is down), and still nothing reaches Telegram
        with patch.object(tasks.announce_signal, "apply_async") as queue, \
                patch("alerts.dispatch.dispatch_signal_alert") as dispatch:
            for callback in callbacks:
                callback()
        queue.assert_called_once_with((sid,), retry=False)
        dispatch.assert_not_called()
        # the worker announces it, once
        with patch("alerts.dispatch.dispatch_signal_alert",
                   return_value={"chats": 1, "sent": 1, "held": 0,
                                 "refused": 0}) as dispatch:
            out = tasks.announce_signal(sid)
        dispatch.assert_called_once()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["channels"]["sent"], 1)

    def test_a_duplicate_alert_queues_nothing(self):
        with self.captureOnCommitCallbacks(execute=False):
            self._post()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            r = self._post()
        self.assertTrue(r.json().get("duplicate"))
        self.assertEqual(len(callbacks), 0)

    def test_a_broker_that_cannot_take_it_is_logged_and_the_answer_stands(self):
        from signals import tasks
        with patch.object(tasks.announce_signal, "apply_async",
                          side_effect=OSError("broker down")), \
                self.assertLogs("signals.announce", "WARNING") as cm, \
                self.captureOnCommitCallbacks(execute=True):
            r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertIn("could not be queued", "\n".join(cm.output))

    def test_the_task_on_a_missing_row(self):
        from signals.tasks import announce_signal
        self.assertEqual(announce_signal(987654)["status"],
                         "signal_not_found")


class FloodGuardTests(TestCase):
    CHAT = "-5337454557"

    def setUp(self):
        from alerts.models import UserNotificationPrefs
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN,
                                      "DOMAIN": ""})
        env.start()
        self.addCleanup(env.stop)
        u = User.objects.create_user("flood_u", password="x")
        UserNotificationPrefs.objects.create(user=u, telegram_chat_id=self.CHAT,
                                             receive_signals=True)
        self.inst = _instrument("FLOOD")

    def _dispatch(self, n):
        from alerts.dispatch import dispatch_signal_alert
        ok = MagicMock(ok=True, status_code=200, text="{}")
        with patch("requests.post", return_value=ok) as post:
            outs = [dispatch_signal_alert(_signal(self.inst))
                    for _ in range(n)]
        return post, outs

    def _age_the_hour(self):
        from alerts.dispatch import _FLOOD_SENT_KEY
        key = _FLOOD_SENT_KEY.format(chat=self.CHAT)
        cache.set(key, [time.time() - 3601] * len(cache.get(key) or []), 3600)

    def test_twenty_an_hour_then_held_then_counted(self):
        with self.assertLogs("alerts.dispatch", "INFO") as cm:
            post, outs = self._dispatch(22)
        self.assertEqual(post.call_count, 20)
        self.assertEqual(sum(o["held"] for o in outs), 2)
        self.assertEqual(len([ln for ln in cm.output
                              if "not posted" in ln]), 2)
        self._age_the_hour()
        post, _ = self._dispatch(2)
        first = post.call_args_list[0].kwargs["json"]["text"].split("\n")
        self.assertRegex(first[-1], r"^\+2 more signals since \d\d:\d\d UTC "
                                    r"on the platform$")
        second = post.call_args_list[1].kwargs["json"]["text"]
        self.assertNotIn("more signal", second)

    def test_one_held_signal_is_singular(self):
        with self.assertLogs("alerts.dispatch", "INFO"):
            self._dispatch(21)
        self._age_the_hour()
        post, _ = self._dispatch(1)
        last = post.call_args.kwargs["json"]["text"].split("\n")[-1]
        self.assertRegex(last, r"^\+1 more signal since \d\d:\d\d UTC on the "
                               r"platform$")

    def test_a_refused_message_keeps_the_count_for_the_next(self):
        from alerts.dispatch import dispatch_signal_alert
        with self.assertLogs("alerts.dispatch", "INFO"):
            self._dispatch(21)
        self._age_the_hour()
        refused = MagicMock(ok=False, status_code=429, text="Too Many Requests")
        with patch("requests.post", return_value=refused), \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            dispatch_signal_alert(_signal(self.inst))
        post, _ = self._dispatch(1)
        self.assertIn("+1 more signal since",
                      post.call_args.kwargs["json"]["text"])

    def test_a_signal_held_while_the_count_was_told_stays_counted(self):
        from alerts.dispatch import _FLOOD_HELD_KEY, dispatch_signal_alert
        with self.assertLogs("alerts.dispatch", "INFO"):
            self._dispatch(22)
        self._age_the_hour()
        key = _FLOOD_HELD_KEY.format(chat=self.CHAT)

        def meanwhile(*args, **kwargs):
            cache.incr(key)  # another worker held one while this posted
            return MagicMock(ok=True, status_code=200, text="{}")

        with patch("requests.post", side_effect=meanwhile) as post:
            dispatch_signal_alert(_signal(self.inst))
        self.assertIn("+2 more signals since",
                      post.call_args.kwargs["json"]["text"])
        post, _ = self._dispatch(1)
        self.assertIn("+1 more signal since",
                      post.call_args.kwargs["json"]["text"])
        post, _ = self._dispatch(1)
        self.assertNotIn("more signal", post.call_args.kwargs["json"]["text"])

    def test_a_count_cut_off_a_long_message_is_told_next_time(self):
        with self.assertLogs("alerts.dispatch", "INFO"):
            self._dispatch(21)
        self._age_the_hour()
        with patch("alerts.dispatch.signal_telegram",
                   return_value=("Signal · FLOOD · BUY", ["long " * 1000],
                                 "\U0001F4C8")):
            post, _ = self._dispatch(1)
        text = post.call_args.kwargs["json"]["text"]
        self.assertTrue(text.endswith("(continued on the platform)"))
        self.assertNotIn("more signal", text)
        post, _ = self._dispatch(1)
        self.assertIn("+1 more signal since",
                      post.call_args.kwargs["json"]["text"])
