"""The alarm bot: a second Telegram bot that rings only for a critical problem (2026-09-28).

The operator, 2026-09-28: his father must not be flooded with trading
chatter, and must be woken for real emergencies only. Pinned here
(bot_program/alarm.py; its two commands are pinned in
tests/test_alarm_bot_commands.py):
  - the configuration: its own token and chat, read at call time, refused
    when either is the Eye's (the same token; TELEGRAM_CHAT_ID; a chat
    saved on the notification settings form);
  - the gate: its own switch and never the master switch -- the two beat
    tasks run with automation paused, skip with the switch off, and stamp
    the row as every component does; the sender reads the switch itself;
  - the sender: the alarm token and the alarm chat, never the Eye's; HTML,
    every field escaped, under 4,096; never raises; a refusal logged with
    Telegram's words, a transport error without the token; no quiet
    hours, no Notification row;
  - THE MONEY TRIPWIRE: one money pattern over every text the module can
    produce, fed data that would leak if the code were careless (a Morgul
    finding whose facts carry margin, equity and P&L; faults whose
    messages quote balances; kill-switch errors that quote prices; a book
    full of prices behind /status);
  - the memory: a standing problem when first seen, again after three
    hours and not before; a fault every 24 hours; an event once; a problem
    that stopped is silence, never a clearing line; a refused delivery is
    not remembered as said; a flushed cache says it again; more than
    MAX_MESSAGES at once go as one message;
  - the six sources: Morgul's criticals by title and label, never facts; a
    warning never; a blind critical guard; the brake once; a relay that
    raises never breaks Morgul's run, whose result stays Morgul's own; the
    pause, once a day, alone but for an abandoned close; an abandoned live
    close; safety-critical components and feeds by name and kind, never
    their message, the warnings bucket never, the flood as one line; a
    live broker account by broker and number, never username; the flatten,
    counts only, on the commit, and a raising hook never fails either
    kill-switch view;
  - the wiring: the registry row (OFF, system, not exempt from the
    group's button), both beat entries and their queues, both env keys in
    both examples, the runbook, the ops registry, the health row, the
    command (bare prints and sends nothing; --test one message; --send one
    pass; the token never printed), and the module's source carries no
    call that arms, opens, closes, flattens or speaks with the Eye's voice.

Run with:  python manage.py test tests.test_alarm_bot
"""
import html
import inspect
import os
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from bot_program import alarm, morgul
from bot_program import telegram_eye as eye
from tests.test_morgul import (CLEAR, FAULTS, SEND, _cfg, _component, _etoro,
                               _scripted, _staff, _trade)
from tests.test_telegram_eye import FakeTelegram, _update

UTC = dt_tz.utc
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
TOKEN = "8888:alarm-bot-secret-token"
EYE_TOKEN = "1234:the-eye-s-own-token"
CHAT = "-1002222333"
EYE_GROUP = "-100999"
ENV = {"TELEGRAM_ALARM_BOT_TOKEN": TOKEN, "TELEGRAM_ALARM_CHAT_ID": CHAT,
       "TELEGRAM_BOT_TOKEN": EYE_TOKEN, "TELEGRAM_CHAT_ID": EYE_GROUP}
POST = "alerts.channels.telegram_alert.post_message"
KILL = "bot_program.engine.kill_switch.execute_kill_switch"
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
ACCENTED = re.compile(r"[À-ÖØ-öø-ÿŒœ]")
FRENCH = (" le ", " la ", " les ", " des ", " est ", " pas ", " une ",
          " du ", " et ")
#: THE MONEY TRIPWIRE: a currency sign or code beside a digit, an amount
#: with two decimals, or a money word followed by a number. Run over the
#: plain text of every message the module can produce.
MONEY = re.compile(
    r"[$€£¥]\s?\d"
    r"|\d\s?(?:USD|EUR|GBP|CHF|JPY|CAD|AUD|USDT)\b"
    r"|\b(?:USD|EUR|GBP|CHF|JPY|CAD|AUD|USDT)\s?\d"
    r"|\d[\d,]*\.\d{2}\b"
    r"|\d\s?%\s?of\s(?:equity|capital|margin)"
    r"|\b(?:P&L|PnL|equity|margin|balance|cash|capital|price|prices|profit"
    r"|loss|drawdown)\b\s*(?:[:=]|of|at|is|was|used|left)?\s*[-+−]?\d",
    re.IGNORECASE)
#: What Morgul's G6 and G7 facts carry: none of it may reach the chat.
MONEY_FACTS = ["Used margin: 60.00 USD", "Equity: 100.00 EUR",
               "Pledged: 60% of equity; the limit is 50%, the alarm 55%",
               "Realized live P&L, last 24 h: -900.00 USD",
               "Daily stop used: 2.0% of 10,000.00 USD = 200.00 USD"]
LEAKS = ("60.00", "100.00", "900.00", "10,000", "200.00", "1,234", "12,345",
         "12345", "336.", "326.", "180.55", "1.0850", "Used margin",
         "Equity", "P&L", "Pledged", "27h", "below the floor")


def _ok(*_args, **_kwargs):
    return MagicMock(ok=True, status_code=200, text='{"ok":true}'), None


def _refused(*_args, **_kwargs):
    return MagicMock(ok=False, status_code=400,
                     text="Bad Request: chat not found"), None


def _texts(post):
    """The HTML each post_message call carried."""
    return [c.args[1]["text"] for c in post.call_args_list]


def _plain(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _report(findings=(), *, outcomes=None, failed=(), now=None,
            result=None, messages=()):
    """A Morgul Report as cycle() builds one, without a run."""
    ctx = morgul.Context(now or NOW)
    res = {"status": "success", "guards": len(morgul.GUARDS),
           "findings": len(findings), "sent": 0, "stopped": []}
    res.update(result or {})
    return morgul.Report(ctx, list(morgul.GUARDS), list(findings),
                         list(failed), res, list(messages),
                         dict(outcomes or {}))


def _finding(subject="account:3:pledged", *, key="margin",
             severity="critical", event=False,
             label="eToro live account (Main)", facts=None, guard=None):
    g = guard or morgul.GUARD[key]
    return morgul.Finding(g, subject, title=g.title, label=label,
                          facts=list(MONEY_FACTS if facts is None else facts),
                          severity=severity, event=event)


def _blind(key="boom", name="Boom test", severity="critical"):
    """A guard that raises, run through Morgul's own collect(): the
    warning finding Morgul files for it, in a Report."""
    guard = morgul.Guard(key, name, severity, f"Morgul — {name.lower()}",
                         lambda c, g: 1 / 0)
    ctx, findings, failed = morgul.collect(now=NOW, guards=[guard])
    return morgul.Report(ctx, [guard], findings, failed,
                         {"status": "success", "guards": 1,
                          "findings": len(findings), "sent": 0,
                          "stopped": [], "failed": failed}, [], {})


def _row():
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.get(key=alarm.COMPONENT_KEY)


FAULTS_WITH_MONEY = {
    "errors": [
        {"key": "pipeline_asset_bots",
         "name": "Multi-Asset Bots (stocks/forex/commodities)",
         "message": "equity 1,234.56 USD below the floor; last ran 2h ago",
         "last_run": None, "errors": 3},
        {"key": "scraper_crypto_news", "name": "Crypto News",
         "message": "boom", "last_run": None, "errors": 1}],
    "warnings": [
        {"key": "pipeline_signals", "name": "Signal Engine",
         "message": "ran and produced nothing", "last_run": None,
         "errors": 0}],
    "silent": [
        {"key": "morgul_guards", "name": "Morgul Guards (book watchdog)",
         "message": "last ran 27h ago (every 5 minutes)", "last_run": None,
         "errors": 0}],
    "feeds": [
        {"key": "oanda_stream", "name": "OANDA stream", "state": "red",
         "message": "no tick for 3h; last 1.0850", "last_run": None,
         "errors": 0}],
    "checked": 54}


class _AlarmCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        _component(alarm.COMPONENT_KEY)
        _component("platform_master")

    def relay(self, report):
        with patch(POST, side_effect=_ok) as post:
            out = alarm.relay_morgul(report)
        return out, _texts(post)

    def sentinel(self, now=NOW, faults=None, post=_ok):
        with patch(FAULTS, return_value=faults or CLEAR), \
                patch(POST, side_effect=post) as p:
            out = alarm.sentinel(now=now)
        return out, _texts(p)

    def settle(self, alarms, now, post=_ok):
        with patch(POST, side_effect=post) as p:
            out = alarm._settle("sentinel", alarms, now)
        return out, _texts(p)


# ── the configuration ────────────────────────────────────────────────────

class ConfigTests(_AlarmCase):
    """A second bot with the Eye's token steals the Eye's updates; a
    second bot in one of the Eye's chats pours the trading messages into
    the father's phone. Both are refused, in words, never with the token."""

    def test_both_variables_are_read_at_call_time(self):
        self.assertEqual(alarm.config(), (TOKEN, CHAT, ""))
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": " -1007 "}):
            self.assertEqual(alarm.config()[1], "-1007")
        self.assertEqual(alarm.config()[1], CHAT)

    def test_a_missing_token_or_chat_is_not_configured(self):
        with patch.dict(os.environ, {"TELEGRAM_ALARM_BOT_TOKEN": ""}):
            token, chat, why = alarm.config()
        self.assertEqual((token, chat), ("", CHAT))
        self.assertEqual(why, "TELEGRAM_ALARM_BOT_TOKEN is not set")
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": ""}):
            self.assertEqual(alarm.config()[2],
                             "TELEGRAM_ALARM_CHAT_ID is not set")

    def test_the_eyes_token_is_refused_without_printing_it(self):
        with patch.dict(os.environ, {"TELEGRAM_ALARM_BOT_TOKEN": EYE_TOKEN}):
            _t, _c, why = alarm.config()
        self.assertIn("the Eye's token", why)
        self.assertIn("second bot", why)
        self.assertNotIn(EYE_TOKEN, why)

    def test_the_eyes_chats_are_refused(self):
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": EYE_GROUP}):
            self.assertIn("TELEGRAM_CHAT_ID", alarm.config()[2])
        # a chat saved on the notification settings form is the Eye's
        _staff("operator", chat=CHAT)
        self.assertIn("/notifications/settings/", alarm.config()[2])

    def test_a_refusal_sends_nothing_and_is_logged_once_an_hour(self):
        _staff("operator", chat=CHAT)
        with patch(POST, side_effect=_ok) as post, \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            self.assertFalse(alarm.send_alarm("Sauron alarm — x", ["a"]))
            self.assertFalse(alarm.send_alarm("Sauron alarm — y", ["b"]))
        post.assert_not_called()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("/notifications/settings/", logs.output[0])


# ── the gate ─────────────────────────────────────────────────────────────

class GateTests(_AlarmCase):
    """Its own switch, never the master switch: a bot gated by the master
    switch goes quiet exactly when the platform pauses, which is one of
    the things it must say."""

    def test_the_sentinel_runs_with_automation_paused_and_stamps_the_row(self):
        from bot_program.tasks import run_alarm_sentinel
        _component("platform_master", on=False)
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post:
            out = run_alarm_sentinel()
        self.assertEqual(out["status"], "success")
        self.assertEqual((out["problems"], out["due"], out["sent"]), (1, 1, 1))
        self.assertIn("automation is paused", _texts(post)[0])
        row = _row()
        self.assertEqual((row.last_status, row.run_count), ("success", 1))
        self.assertIsNotNone(row.last_run_at)

    def test_the_poll_runs_with_automation_paused(self):
        from bot_program.tasks import poll_telegram_alarm
        _component("platform_master", on=False)
        fake = FakeTelegram([_update(700, "/status", chat=CHAT)])
        with patch("requests.get", side_effect=fake.get), \
                patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            out = poll_telegram_alarm()
        self.assertEqual(out["answered"], 1)
        self.assertIn("Automation: paused", _texts(post)[0])

    def test_both_tasks_skip_with_the_switch_off_and_write_nothing(self):
        from bot_program.tasks import poll_telegram_alarm, run_alarm_sentinel
        _component(alarm.COMPONENT_KEY, on=False)
        _component("platform_master", on=False)
        with patch("requests.get") as get, patch(POST) as post:
            self.assertEqual(run_alarm_sentinel(),
                             {"status": "skipped", "reason": "telegram_alarm off"})
            self.assertEqual(poll_telegram_alarm(),
                             {"status": "skipped", "reason": "telegram_alarm off"})
        get.assert_not_called()
        post.assert_not_called()
        self.assertEqual(_row().run_count, 0)

    def test_send_alarm_reads_the_switch_itself(self):
        with patch(POST, side_effect=_ok) as post:
            self.assertTrue(alarm.send_alarm("Sauron alarm — x", ["a"]))
            _component(alarm.COMPONENT_KEY, on=False)
            self.assertFalse(alarm.send_alarm("Sauron alarm — x", ["a"]))
        self.assertEqual(post.call_count, 1)

    def test_an_idle_poll_keeps_the_sentinels_verdict(self):
        from bot_program.tasks import poll_telegram_alarm, run_alarm_sentinel
        _component("platform_master", on=False)
        with patch(FAULTS, return_value=CLEAR), patch(POST, side_effect=_ok):
            run_alarm_sentinel()
        fake = FakeTelegram([])
        with patch("requests.get", side_effect=fake.get):
            out = poll_telegram_alarm()
        self.assertEqual(out["idle"], "nothing to read")
        self.assertEqual((_row().last_status, _row().run_count),
                         ("success", 1))

    def test_a_refused_delivery_is_an_error_on_the_row(self):
        from bot_program.tasks import run_alarm_sentinel
        _component("platform_master", on=False)
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_refused):
            out = run_alarm_sentinel()
        self.assertEqual(out["status"], "error")
        self.assertIn("not delivered", out["error"])
        self.assertEqual(_row().last_status, "error")

    def test_a_refused_configuration_is_a_warning_on_the_row_not_silence(self):
        from bot_program.tasks import run_alarm_sentinel
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": ""}), \
                patch(POST) as post:
            out = run_alarm_sentinel()
        post.assert_not_called()
        self.assertEqual(out["skipped"], "TELEGRAM_ALARM_CHAT_ID is not set")
        self.assertEqual(_row().last_status, "warning")
        self.assertIn("not configured", _row().last_message)

    def test_the_gate_names_its_component_for_the_digest(self):
        from bot_program.tasks import poll_telegram_alarm, run_alarm_sentinel
        from core.component_digest import beat_periods
        for task in (poll_telegram_alarm, run_alarm_sentinel):
            self.assertEqual(task.__wrapped__.component_key,
                             alarm.COMPONENT_KEY)
            self.assertEqual(task.run.component_key, alarm.COMPONENT_KEY)
        self.assertIn(alarm.COMPONENT_KEY, beat_periods())

    def test_the_gate_never_reads_the_master_switch(self):
        src = inspect.getsource(alarm.alarm_task)
        self.assertNotIn('"platform_master"', src)
        self.assertNotIn("guarded_task(", inspect.getsource(alarm))


# ── the sender ───────────────────────────────────────────────────────────

class SenderTests(_AlarmCase):
    """The alarm bot speaks with its own voice into its own chat: the
    alarm token and chat, never TELEGRAM_BOT_TOKEN, and nothing the Eye's
    path applies (quiet hours, the bot-alert preference, the bell row)."""

    def test_the_alarm_token_and_chat_never_the_eyes(self):
        with patch(POST, side_effect=_ok) as post:
            self.assertTrue(alarm.send_alarm("Sauron alarm — x",
                                             ["Stocks <live> & co", "Two"]))
        call = post.call_args
        self.assertEqual(call.args[0], TOKEN)
        self.assertNotEqual(call.args[0], EYE_TOKEN)
        payload = call.args[1]
        self.assertEqual(payload["chat_id"], CHAT)
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        self.assertEqual(call.kwargs["timeout"], 10)
        self.assertEqual(payload["text"],
                         f"<b>{alarm.MARK} Sauron alarm — x</b>\n"
                         "Stocks &lt;live&gt; &amp; co\nTwo")

    def test_a_long_message_fits_telegrams_limit(self):
        with patch(POST, side_effect=_ok) as post:
            alarm.send_alarm("Sauron alarm — x",
                             [f"Line {i} " + "word " * 40 for i in range(200)])
        text = _texts(post)[0]
        self.assertLessEqual(len(text), 4096)
        self.assertIn("more on the platform", text)

    def test_a_refusal_is_logged_with_telegrams_words_and_is_false(self):
        answer = MagicMock(ok=False, status_code=400,
                           text="Bad Request: chat not found")
        with patch("requests.post", return_value=answer), \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            self.assertFalse(alarm.send_alarm("Sauron alarm — x", ["a"]))
        self.assertIn("chat not found", logs.output[0])
        self.assertIn("400", logs.output[0])
        self.assertNotIn(TOKEN, "".join(logs.output))

    def test_a_transport_error_never_raises_and_never_logs_the_token(self):
        boom = requests.ConnectionError(
            f"HTTPSConnectionPool: https://api.telegram.org/bot{TOKEN}/"
            f"sendMessage timed out")
        with patch("requests.post", side_effect=boom), \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            self.assertFalse(alarm.send_alarm("Sauron alarm — x", ["a"]))
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn(TOKEN, logs.output[0])
        self.assertIn("not sent", logs.output[0])

    def test_post_message_raising_is_false_not_an_exception(self):
        with patch(POST, side_effect=RuntimeError("boom")):
            self.assertFalse(alarm.send_alarm("Sauron alarm — x", ["a"]))

    def test_no_quiet_hours_no_preference_no_notification_row(self):
        from datetime import time

        from alerts.models import Notification
        user = _staff()
        prefs = user.notification_prefs
        prefs.quiet_start, prefs.quiet_end = time(0, 0), time(23, 59)
        prefs.receive_bot_alerts = False
        prefs.save()
        before = Notification.objects.count()
        with patch(POST, side_effect=_ok) as post:
            self.assertTrue(alarm.send_alarm("Sauron alarm — x", ["a"]))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(Notification.objects.count(), before)


# ── the money tripwire ───────────────────────────────────────────────────

class MoneyTripwireTests(_AlarmCase):
    """No money figure in any text the bot sends: no amount, no P&L, no
    equity, no margin, no price. The data here would leak from a careless
    relay: Morgul facts with margin and P&L, a fault message quoting a
    balance, kill-switch errors quoting prices, a book full of prices
    behind /status and /stopall."""

    def _every_text(self):
        user = _staff("gandalf_senior")
        live = _cfg(user, "Stocks <live>", "stock", mode="live",
                    capital="10000")
        paper = _cfg(user, "Forex swing")
        _trade(live, "AAPL", entry="336.10", stop="326.02", paper=False,
               metadata={"protected": True})
        _trade(live, "NVDA", entry="180.55", stop="170.25", paper=False,
               metadata={"entry_working": True, "protected": False})
        _trade(paper, "EURUSD", entry="1.0850", stop="1.0790")
        _trade(live, "MSFT", entry="420.15", stop="410.00", paper=False,
               status="ERROR", pnl="-900.00")
        acct = _etoro(user, demo=False, last_equity=Decimal("12345.67"),
                      last_equity_currency="USD",
                      last_used_margin=Decimal("6000.50"),
                      last_margin_at=NOW, last_margin_world="live")
        _component("broker_account_sync")
        cache.set(f"broker_sync:miss:etoro:{acct.pk}", 4, 3600)
        texts = []
        # A: a Morgul run with money in its facts, a blind critical guard
        # and the brake acting
        report = _report(
            [_finding(),
             _finding(f"user:{user.pk}:USD", key="daily_loss",
                      label=f"Live bots of account #{user.pk} · USD")]
            + _blind().findings,
            outcomes={"proofs|trade:5": ("stopped", ["Stocks <live> #4"],
                                         [], {"broker": 1, "bare": 1,
                                              "paper": 0})})
        texts += [("relay", t) for t in self.relay(report)[1]]
        # B to E: the sentinel running, then paused
        texts += [("sentinel", t)
                  for t in self.sentinel(faults=FAULTS_WITH_MONEY)[1]]
        _component("platform_master", on=False)
        texts += [("paused", t) for t in self.sentinel(
            now=NOW + timedelta(minutes=10), faults=FAULTS_WITH_MONEY)[1]]
        _component("platform_master")
        # the bundle
        texts += [("bundle", t) for t in self.settle(
            [alarm.Alarm(f"x|{i}", f"problem number {i}") for i in range(7)],
            NOW + timedelta(days=1))[1]]
        # F: the flatten
        results = {"bots_disabled": 1, "asset_bots_disabled": 2,
                   "positions_closed": 1, "asset_positions_closed": 2,
                   "portfolio_positions_closed": 0,
                   "paper_waiting": ["EURUSD at 1.0850, market shut"],
                   "errors": ["AAPL: close failed at 336.10 USD",
                              "NVDA: equity 12,345.67 USD"]}
        with patch(POST, side_effect=_ok) as post:
            alarm.announce_kill_switch(alarm.kill_counts(results, NOW))
        texts += [("flatten", t) for t in _texts(post)]
        # the replies
        with patch(POST, side_effect=_ok) as post, \
                patch(FAULTS, return_value=FAULTS_WITH_MONEY), \
                patch.object(eye, "_withdraw", return_value=True), \
                self.captureOnCommitCallbacks(execute=True):
            for text in ("/status", "/help", "/stopall"):
                cache.delete(alarm.RATE_KEY.format(chat=CHAT))
                alarm.handle(_update(1, text, chat=CHAT), token=TOKEN,
                             chat=CHAT, now=NOW)
        texts += [("reply", t) for t in _texts(post)]
        texts.append(("could not answer",
                      alarm.could_not_answer("DatabaseError").text()))
        # the command's own test message
        with patch(POST, side_effect=_ok) as post:
            call_command("alarm", "--test", stdout=StringIO())
        texts += [("manage.py alarm --test", t) for t in _texts(post)]
        return texts

    def test_no_money_figure_in_any_text_the_module_can_produce(self):
        texts = self._every_text()
        self.assertGreaterEqual(len(texts), 14, texts)
        for where, text in texts:
            plain = _plain(text)
            self.assertIsNone(MONEY.search(plain),
                              f"{where}: money in {plain!r}")
            for leak in LEAKS:
                self.assertNotIn(leak, plain, f"{where}: {leak!r} leaked")
            self.assertNotIn("gandalf_senior", plain, where)

    def test_the_tripwire_itself_catches_what_it_must(self):
        """A tripwire that matches nothing pins nothing."""
        for fact in MONEY_FACTS:
            self.assertIsNotNone(MONEY.search(fact), fact)
        for text in ("Equity: 100 EUR", "$12", "P&L -900", "price 336",
                     "1,234.56", "balance is 12", "USD 60", "60 USD"):
            self.assertIsNotNone(MONEY.search(text), text)
        for text in ("Bots running: 3 (1 live)", "Open positions: 2 (1 live)",
                     "Guards: 2 findings — Daily loss, Margin (last ran "
                     "12 min ago)", "Checked: 2026-09-28 12:00 UTC",
                     "Live bots of account #3 · USD", "EURUSD #12",
                     "Bots turned off: 3", "Close errors: 1",
                     "the daily loss is past the stop"):
            self.assertIsNone(MONEY.search(text), text)


# ── the memory ───────────────────────────────────────────────────────────

class MemoryTests(_AlarmCase):
    """Said when first seen, again after its kind's window while it stands,
    never for a problem that stopped; a delivery Telegram refused is not
    remembered as said; a flushed cache says it again; too many at once
    go as one message."""

    def test_a_standing_problem_is_said_again_after_three_hours(self):
        standing = [alarm.Alarm("k|1", "a problem stands")]
        self.assertEqual(len(self.settle(standing, NOW)[1]), 1)
        for hours in (1, 2.9):
            self.assertEqual(self.settle(
                standing, NOW + timedelta(hours=hours))[1], [])
        said = self.settle(standing, NOW + timedelta(hours=3))[1]
        self.assertEqual(len(said), 1)
        self.assertIn("a problem stands", said[0])

    def test_a_fault_is_said_every_24_hours(self):
        fault = [alarm.Alarm("fault|errors|x", "x is failing",
                             kind=alarm.FAULT)]
        self.assertEqual(len(self.settle(fault, NOW)[1]), 1)
        self.assertEqual(self.settle(fault, NOW + timedelta(hours=23))[1], [])
        self.assertEqual(len(self.settle(fault, NOW + timedelta(hours=24))[1]),
                         1)

    def test_an_event_is_said_once_and_never_again(self):
        event = [alarm.Alarm("brake|x", "the brake stopped 1 bot",
                             kind=alarm.EVENT)]
        self.assertEqual(len(self.settle(event, NOW)[1]), 1)
        for later in (timedelta(minutes=1), timedelta(hours=4),
                      timedelta(days=6)):
            self.assertEqual(self.settle(event, NOW + later)[1], [])

    def test_a_problem_that_stopped_is_silence_never_a_clearing_line(self):
        standing = [alarm.Alarm("k|1", "a problem stands")]
        self.settle(standing, NOW)
        for later in (timedelta(hours=1), timedelta(hours=4),
                      timedelta(days=2)):
            out, said = self.settle([], NOW + later)
            self.assertEqual(said, [])
            self.assertEqual(out, {"problems": 0, "due": 0, "sent": 0,
                                   "failed": 0})
        # and one that comes back inside its window is not said again
        self.assertEqual(self.settle(standing, NOW + timedelta(hours=1))[1],
                         [])
        self.assertEqual(len(self.settle(
            standing, NOW + timedelta(hours=3, minutes=1))[1]), 1)

    def test_a_refused_delivery_is_not_remembered_as_said(self):
        standing = [alarm.Alarm("k|1", "a problem stands")]
        out, said = self.settle(standing, NOW, post=_refused)
        self.assertEqual((out["sent"], out["failed"]), (0, 1))
        self.assertEqual(len(said), 1)   # attempted once, refused
        out, said = self.settle(standing, NOW + timedelta(minutes=1))
        self.assertEqual((out["sent"], out["failed"]), (1, 0))
        self.assertEqual(len(said), 1)

    def test_a_refused_event_is_said_from_memory_once_its_source_is_gone(self):
        event = [alarm.Alarm("brake|x", "the brake stopped 1 bot",
                             ["Stopped: Forex swing #4"], kind=alarm.EVENT)]
        self.settle(event, NOW, post=_refused)
        out, said = self.settle([], NOW + timedelta(minutes=1))
        self.assertEqual(out["sent"], 1)
        self.assertIn("the brake stopped 1 bot", said[0])
        self.assertIn("Stopped: Forex swing #4", said[0])
        self.assertEqual(self.settle([], NOW + timedelta(minutes=2))[1], [])

    def test_a_flushed_cache_says_a_standing_problem_again(self):
        standing = [alarm.Alarm("k|1", "a problem stands")]
        self.settle(standing, NOW)
        cache.clear()
        self.assertEqual(len(self.settle(
            standing, NOW + timedelta(minutes=1))[1]), 1)

    def test_more_than_max_messages_due_at_once_go_as_one(self):
        many = [alarm.Alarm(f"k|{i}", f"problem number {i}")
                for i in range(alarm.MAX_MESSAGES + 1)]
        out, said = self.settle(many, NOW)
        self.assertEqual(len(said), 1)
        self.assertEqual(out, {"problems": 6, "due": 6, "sent": 1,
                               "failed": 0})
        self.assertIn(f"Sauron alarm — 6 critical problems at once", said[0])
        for a in many:
            self.assertIn(a.words, said[0])
        # all six remembered: nothing more for three hours
        self.assertEqual(self.settle(many, NOW + timedelta(hours=1))[1], [])
        # exactly MAX_MESSAGES go one by one
        cache.clear()
        self.assertEqual(len(self.settle(many[:alarm.MAX_MESSAGES], NOW)[1]),
                         alarm.MAX_MESSAGES)

    def test_the_relays_memory_is_its_own_not_morguls(self):
        """A finding Morgul said as a warning, or while this switch was
        off, is new here; and the alarm bot's send never marks Morgul's
        memory."""
        guard, box = _scripted(severity="critical")
        box["subjects"], box["severity"] = ["one"], "critical"
        with patch(SEND, return_value=True):
            report = morgul.cycle(now=NOW, send=True, guards=[guard])
        self.assertIn("scripted|one", cache.get(morgul.STATE_KEY))
        out, said = self.relay(report)
        self.assertEqual(len(said), 1)
        self.assertIn("morgul|scripted|one",
                      cache.get(alarm.STATE_KEY.format(source="morgul")))
        self.assertNotIn("morgul|scripted|one", cache.get(morgul.STATE_KEY))
        # five minutes on: Morgul says nothing, and neither does this bot
        with patch(SEND, return_value=True) as send:
            report = morgul.cycle(now=NOW + timedelta(minutes=5), send=True,
                                  guards=[guard])
        send.assert_not_called()
        self.assertEqual(self.relay(report)[1], [])

    def test_one_pass_per_source_at_a_time(self):
        cache.add(alarm.LOCK_KEY.format(source="sentinel"), "held", 60)
        _component("platform_master", on=False)
        out, said = self.sentinel()
        self.assertEqual(out["idle"], "another alarm pass is in progress")
        self.assertEqual(said, [])
        cache.add(alarm.LOCK_KEY.format(source="morgul"), "held", 60)
        with self.assertLogs("bot_program.alarm", level="WARNING"):
            self.assertEqual(self.relay(_report([_finding()]))[1], [])

    def test_a_reader_that_raises_is_said_never_silence(self):
        boom = MagicMock(side_effect=RuntimeError("boom"))
        boom.__name__ = "read_abandoned"
        with patch.object(alarm, "READERS",
                          (("abandoned closes", boom),)):
            out, said = self.sentinel()
        self.assertEqual(len(said), 1)
        self.assertIn("the alarm bot cannot check abandoned closes", said[0])
        self.assertIn("RuntimeError", said[0])


# ── A: Morgul ────────────────────────────────────────────────────────────

class RelayTests(_AlarmCase):
    """After each run of Morgul's beat: every CRITICAL finding by its own
    severity, its title and label and never its facts; a blind critical
    guard; the brake once. Morgul's own messages, memory and pins are
    untouched, and a relay that raises never breaks the run."""

    def test_a_critical_finding_is_relayed_by_title_and_label_never_facts(self):
        out, said = self.relay(_report([_finding()]))
        self.assertEqual(out, {"problems": 1, "due": 1, "sent": 1,
                               "failed": 0})
        self.assertEqual(len(said), 1)
        text = said[0]
        self.assertTrue(text.startswith(
            f"<b>{alarm.MARK} Sauron alarm — the margin pledged is past the "
            f"limit</b>\n"), text)
        self.assertIn("eToro live account (Main)", text)
        self.assertIn("/health/", text)
        for fact in MONEY_FACTS:
            self.assertNotIn(html.escape(fact), text)
        for leak in ("60.00", "USD", "EUR", "Equity", "P&amp;L", "Pledged"):
            self.assertNotIn(leak, text)

    def test_a_warning_finding_is_never_relayed_whatever_its_guard(self):
        # a warning finding of a CRITICAL guard (G6 with doubts)
        out, said = self.relay(_report([_finding(severity="warning")]))
        self.assertEqual((out, said), ({"problems": 0, "due": 0, "sent": 0,
                                        "failed": 0}, []))
        # a critical finding of a WARNING guard (G3 at four hours)
        out, said = self.relay(_report([_finding(
            "trade:9", key="stuck_close", label="MSFT long #9 · live",
            facts=["Close pending for 4 h"])]))
        self.assertEqual(len(said), 1)
        self.assertIn("a close stuck at the broker", said[0])

    def test_a_blind_critical_guard_is_relayed(self):
        out, said = self.relay(_blind())
        self.assertEqual(len(said), 1)
        self.assertIn("Sauron alarm — a safety check cannot run: Boom test",
                      said[0])
        self.assertIn("nothing watches what it watches", said[0])
        # a blind warning guard is not: it could find nothing critical
        self.assertEqual(self.relay(_blind("quiet", "Quiet test",
                                           "warning"))[1], [])
        # but the stuck-close guard, filed as a warning, turns critical at
        # four hours: blind, it hides criticals too
        self.assertEqual(len(self.relay(_blind("stuck_close", "Stuck close",
                                               "warning"))[1]), 1)

    def test_the_brake_acting_is_relayed_once_in_its_own_words(self):
        outcome = ("stopped", ["Stocks <live> #4", "Forex swing #5"], [],
                   {"broker": 1, "bare": 1, "paper": 2})
        report = _report([_finding()], outcomes={"margin|account:3:pledged":
                                                 outcome})
        out, said = self.relay(report)
        self.assertEqual(out["sent"], 2)
        brake = next(t for t in said if "the brake stopped 2 bots" in t)
        self.assertIn("Stopped: Stocks &lt;live&gt; #4, Forex swing #5 — "
                      "no position was closed", brake)
        self.assertIn("At the broker without a stop: 1", brake)
        self.assertIn("Paper positions: 2", brake)
        self.assertIn("At: 2026-09-28 12:00 UTC", brake)
        # said once: the next run, the same outcome, nothing
        self.assertEqual(self.relay(_report(
            [_finding()], outcomes={"margin|account:3:pledged": outcome},
            now=NOW + timedelta(minutes=5)))[1], [])
        # what the brake would do, or did earlier, is not the brake acting
        for kind in (("would", ["Forex swing #5"]),
                     ("earlier", ["Forex swing #5"], [], {}),
                     ("held", ["Forex swing #5"])):
            cache.clear()
            said = self.relay(_report([_finding(severity="warning")],
                                      outcomes={"x|y": kind}))[1]
            self.assertEqual(said, [], kind)

    def test_a_standing_finding_every_three_hours_an_event_once(self):
        standing = _report([_finding()])
        self.assertEqual(len(self.relay(standing)[1]), 1)
        self.assertEqual(self.relay(_report(
            [_finding()], now=NOW + timedelta(hours=1)))[1], [])
        self.assertEqual(len(self.relay(_report(
            [_finding()], now=NOW + timedelta(hours=3)))[1]), 1)
        cache.clear()
        booking = _finding("trade:8", key="market_shut", event=True,
                           label="EURCAD long #8 · paper · Forex swing #5",
                           facts=["Booked at 13:53 UTC on a Saturday"])
        self.assertEqual(len(self.relay(_report([booking]))[1]), 1)
        self.assertEqual(self.relay(_report(
            [booking], now=NOW + timedelta(hours=4)))[1], [])

    def test_a_refused_delivery_is_retried_on_the_next_run(self):
        with patch(POST, side_effect=_refused):
            out = alarm.relay_morgul(_report([_finding()]))
        self.assertEqual((out["sent"], out["failed"]), (0, 1))
        out, said = self.relay(_report([_finding()],
                                       now=NOW + timedelta(minutes=5)))
        self.assertEqual((out["sent"], len(said)), (1, 1))

    def test_morguls_own_messages_are_never_forwarded(self):
        """Morgul's "back to normal", its warnings and its money-carrying
        bodies live in report.messages: the relay reads the findings."""
        clearing = morgul.back_to_normal(
            [{"name": "Margin", "label": "eToro live account (Main)",
              "subject": "account:3:pledged"}], NOW)
        warning = morgul.build_messages([_finding(severity="warning")], {},
                                        NOW)
        report = _report([], messages=[clearing] + warning,
                         result={"cleared": 1, "sent": 2})
        out, said = self.relay(report)
        self.assertEqual(said, [])
        self.assertEqual(out["problems"], 0)

    def test_nothing_while_off_idle_or_refused(self):
        with patch(POST) as post:
            self.assertEqual(alarm.relay_morgul(None), {})
            self.assertEqual(alarm.relay_morgul(_report(
                [_finding()], result={"idle": "another Morgul run"})), {})
            with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": ""}), \
                    self.assertLogs("bot_program.alarm", level="WARNING"):
                self.assertEqual(alarm.relay_morgul(_report([_finding()])),
                                 {})
            _component(alarm.COMPONENT_KEY, on=False)
            self.assertEqual(alarm.relay_morgul(_report([_finding()])), {})
        post.assert_not_called()

    def test_the_beat_task_hears_morguls_run_and_returns_morguls_result(self):
        from bot_program.tasks import run_morgul_guards
        _component(morgul.COMPONENT_KEY)
        guard, box = _scripted(severity="critical")
        box["subjects"], box["severity"] = ["one"], "critical"
        with patch.object(morgul, "GUARDS", [guard]), \
                patch(SEND, return_value=True), \
                patch(POST, side_effect=_ok) as post:
            out = run_morgul_guards()
        self.assertEqual((out["status"], out["guards"], out["findings"]),
                         ("success", 1, 1))
        self.assertEqual(len(_texts(post)), 1)
        self.assertIn("Sauron alarm — scripted", _texts(post)[0])
        self.assertIn("Subject one", _texts(post)[0])

    def test_a_relay_that_raises_never_breaks_morguls_run(self):
        from bot_program.tasks import run_morgul_guards
        _component(morgul.COMPONENT_KEY)
        with patch(SEND, return_value=True), \
                patch("bot_program.alarm.relay_morgul",
                      side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.tasks", level="WARNING") as logs:
            out = run_morgul_guards()
        self.assertEqual((out["status"], out["guards"]),
                         ("success", len(morgul.GUARDS)))
        self.assertIn("not relayed", logs.output[0])

    def test_the_beat_task_returns_exactly_what_run_guards_returns(self):
        """run_morgul_guards used to return morgul.run_guards(); it now
        drives cycle(send=True) itself to see the Report, and hands back
        the same object run_guards would: cycle's own result dict."""
        from bot_program.tasks import run_morgul_guards
        _component(morgul.COMPONENT_KEY)
        fake = _report([], result={"marker": "cycle's own dict"})
        with patch("bot_program.morgul.cycle", return_value=fake) as cycle, \
                patch(POST) as post:
            self.assertIs(run_morgul_guards(), fake.result)
            self.assertIs(morgul.run_guards(), fake.result)
        for call in cycle.call_args_list:
            self.assertTrue(call.kwargs.get("send"), call)
        post.assert_not_called()


# ── B: the pause ─────────────────────────────────────────────────────────

class PauseTests(_AlarmCase):
    def test_automation_paused_is_one_line_once_a_day(self):
        _component("platform_master", on=False)
        out, said = self.sentinel()
        self.assertEqual(len(said), 1)
        self.assertIn("Sauron alarm — automation is paused: no bot trades "
                      "and no safety check runs", said[0])
        self.assertIn("START PLATFORM", said[0])
        self.assertEqual(self.sentinel(now=NOW + timedelta(hours=23))[1], [])
        self.assertEqual(len(self.sentinel(
            now=NOW + timedelta(hours=24))[1]), 1)
        # resumed: silence, never "resumed" or "back to normal"
        _component("platform_master")
        self.assertEqual(self.sentinel(now=NOW + timedelta(hours=25))[1], [])

    def test_while_paused_the_faults_are_the_pause_but_an_abandoned_close_is_not(self):
        user = _staff()
        cfg = _cfg(user, "Stocks <live>", "stock", mode="live")
        gone = _trade(cfg, "MSFT", paper=False, status="ERROR")
        acct = _etoro(user, demo=False)
        _component("broker_account_sync")
        cache.set(f"broker_sync:miss:etoro:{acct.pk}", 5, 3600)
        _component("platform_master", on=False)
        out, said = self.sentinel(faults=FAULTS_WITH_MONEY)
        self.assertEqual(out["problems"], 2)
        self.assertEqual(len(said), 2)
        self.assertTrue(any("automation is paused" in t for t in said))
        self.assertTrue(any(f"a close was abandoned: MSFT #{gone.pk}" in t
                            for t in said))
        for word in ("is failing", "has stopped running",
                     "is not delivering quotes", "syncs in a row"):
            self.assertFalse(any(word in t for t in said), word)


# ── C: abandoned closes ──────────────────────────────────────────────────

class AbandonedCloseTests(_AlarmCase):
    def test_a_live_error_row_still_open_is_said(self):
        user = _staff()
        cfg = _cfg(user, "Stocks <live>", "stock", mode="live")
        gone = _trade(cfg, "eurusd", paper=False, status="ERROR",
                      pnl="-900.00", entry="1.0850")
        out, said = self.sentinel()
        self.assertEqual(len(said), 1)
        self.assertIn(f"Sauron alarm — a close was abandoned: EURUSD "
                      f"#{gone.pk} may still be open at the broker", said[0])
        self.assertIn("/forensics/", said[0])
        # standing: three hours later it is said again
        self.assertEqual(self.sentinel(now=NOW + timedelta(hours=1))[1], [])
        self.assertEqual(len(self.sentinel(now=NOW + timedelta(hours=3))[1]),
                         1)

    def test_a_paper_row_or_a_closed_row_is_not(self):
        user = _staff()
        cfg = _cfg(user, "Stocks <live>", "stock", mode="live")
        _trade(cfg, "AAPL", paper=True, status="ERROR")
        _trade(cfg, "NVDA", paper=False, status="ERROR", closed=NOW)
        _trade(cfg, "MSFT", paper=False, status="CLOSE_PENDING")
        self.assertEqual(self.sentinel()[1], [])


# ── D: components and feeds ──────────────────────────────────────────────

class FaultTests(_AlarmCase):
    def test_a_critical_component_by_name_and_kind_never_its_message(self):
        out, said = self.sentinel(faults=FAULTS_WITH_MONEY)
        self.assertEqual(len(said), 3)
        titles = [t.split("\n")[0] for t in said]
        self.assertIn(f"<b>{alarm.MARK} Sauron alarm — Multi-Asset Bots "
                      f"(stocks/forex/commodities) is failing</b>", titles)
        self.assertIn(f"<b>{alarm.MARK} Sauron alarm — Morgul Guards (book "
                      f"watchdog) has stopped running</b>", titles)
        self.assertIn(f"<b>{alarm.MARK} Sauron alarm — OANDA stream is not "
                      f"delivering quotes</b>", titles)
        joined = "\n".join(said)
        for leak in ("27h", "1,234", "below the floor", "no tick", "1.0850",
                     "pipeline_asset_bots", "morgul_guards", "oanda_stream"):
            self.assertNotIn(leak, joined)

    def test_a_component_off_the_list_and_the_warnings_bucket_are_ignored(self):
        joined = "\n".join(self.sentinel(faults=FAULTS_WITH_MONEY)[1])
        self.assertNotIn("Crypto News", joined)
        # Signal Engine is critical, but "ran and produced nothing" is the
        # warnings bucket: never
        self.assertNotIn("Signal Engine", joined)
        self.assertNotIn(alarm.COMPONENT_KEY, alarm.CRITICAL_COMPONENTS)

    def test_a_fault_is_said_every_24_hours(self):
        self.sentinel(faults=FAULTS_WITH_MONEY)
        self.assertEqual(self.sentinel(now=NOW + timedelta(hours=23),
                                       faults=FAULTS_WITH_MONEY)[1], [])
        self.assertEqual(len(self.sentinel(now=NOW + timedelta(hours=24),
                                           faults=FAULTS_WITH_MONEY)[1]), 3)
        # fixed: silence
        self.assertEqual(self.sentinel(now=NOW + timedelta(hours=25))[1], [])

    def test_a_flood_of_stopped_tasks_is_one_line(self):
        silent = [{"key": k, "name": n, "message": "last ran 27h ago",
                   "last_run": None, "errors": 0}
                  for k, n in (("pipeline_asset_bots", "Multi-Asset Bots"),
                               ("broker_account_sync", "Broker Sync"),
                               ("scraper_live_quotes", "Live Quotes"),
                               ("morgul_guards", "Morgul Guards"),
                               ("scraper_crypto_news", "Crypto News"))]
        out, said = self.sentinel(faults=dict(CLEAR, silent=silent))
        self.assertEqual(len(said), 1)
        self.assertIn("Sauron alarm — the scheduler seems stopped: 4 "
                      "safety-critical tasks have not run", said[0])
        self.assertIn("Multi-Asset Bots, Broker Sync, Live Quotes, Morgul "
                      "Guards", said[0])
        self.assertNotIn("Crypto News", said[0])
        # three is not a flood: three lines
        self.assertEqual(len(self.sentinel(
            now=NOW + timedelta(days=2),
            faults=dict(CLEAR, silent=silent[:3]))[1]), 3)

    def test_the_critical_list_names_real_registry_keys(self):
        from core.platform_control import DEFAULT_COMPONENTS
        keys = {c["key"] for c in DEFAULT_COMPONENTS}
        for key in alarm.CRITICAL_COMPONENTS:
            self.assertIn(key, keys)
        self.assertEqual(alarm.FLOOD_AT, 4)


# ── E: the brokers ───────────────────────────────────────────────────────

class BrokerTests(_AlarmCase):
    def setUp(self):
        super().setUp()
        _component("broker_account_sync")

    def test_a_live_account_past_the_miss_threshold_by_broker_and_number(self):
        from bot_program.tasks import BROKER_MISS_ALERT_AFTER
        user = _staff("gandalf_senior")
        acct = _etoro(user, demo=False)
        cache.set(f"broker_sync:miss:etoro:{acct.pk}",
                  BROKER_MISS_ALERT_AFTER, 3600)
        out, said = self.sentinel()
        self.assertEqual(len(said), 1)
        self.assertIn(f"Sauron alarm — eToro account #{acct.pk} has not "
                      f"answered {BROKER_MISS_ALERT_AFTER} syncs in a row",
                      said[0])
        self.assertIn("/brokers/", said[0])
        self.assertNotIn("gandalf_senior", said[0])
        self.assertNotIn("Main", said[0])

    def test_below_the_threshold_demo_and_paper_are_not(self):
        from bot_program.models import IBKRAccount
        from bot_program.tasks import BROKER_MISS_ALERT_AFTER
        a = _staff("a")
        b = _staff("b")
        c = _staff("c")
        live = _etoro(a, demo=False)
        cache.set(f"broker_sync:miss:etoro:{live.pk}",
                  BROKER_MISS_ALERT_AFTER - 1, 3600)
        demo = _etoro(b, demo=True)
        cache.set(f"broker_sync:miss:etoro:{demo.pk}", 9, 3600)
        paper = IBKRAccount.objects.create(user=c, port=7497)
        paper.set_credentials("DU1234567")
        paper.save()
        cache.set(f"broker_sync:miss:ibkr:{paper.pk}", 9, 3600)
        self.assertEqual(self.sentinel()[1], [])

    def test_an_ibkr_live_port_is_live_and_an_unknown_port_is_not_safe(self):
        from bot_program.models import IBKRAccount
        a = _staff("a")
        b = _staff("b")
        live = IBKRAccount.objects.create(user=a, port=7496)
        live.set_credentials("U1234567")
        live.save()
        unknown = IBKRAccount.objects.create(user=b, port=7946)
        unknown.set_credentials("U7654321")
        unknown.save()
        for acct in (live, unknown):
            cache.set(f"broker_sync:miss:ibkr:{acct.pk}", 4, 3600)
        out, said = self.sentinel()
        self.assertEqual(len(said), 2)
        for acct in (live, unknown):
            self.assertTrue(any(f"IBKR account #{acct.pk} has not answered "
                                f"4 syncs" in t for t in said))

    def test_a_frozen_count_is_not_a_current_one(self):
        """With the sync switched off nothing counts misses: an old count
        says nothing about the broker now."""
        user = _staff()
        acct = _etoro(user, demo=False)
        cache.set(f"broker_sync:miss:etoro:{acct.pk}", 9, 3600)
        _component("broker_account_sync", on=False)
        self.assertEqual(self.sentinel()[1], [])


# ── F: the flatten ───────────────────────────────────────────────────────

RESULTS = {"bots_disabled": 1, "asset_bots_disabled": 2,
           "positions_closed": 1, "asset_positions_closed": 2,
           "portfolio_positions_closed": 1,
           "paper_waiting": ["EURUSD at 1.0850, market shut"],
           "errors": ["AAPL: close failed at 336.10 USD"]}


class FlattenTests(_AlarmCase):
    """The emergency flatten, told to the alarm chat once the kill has
    committed, in counts only; a hook that raises never fails the kill or
    its page."""

    def test_the_announcement_leaves_on_the_commit_with_counts_only(self):
        with patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True) as callbacks:
            alarm.after_kill_switch(RESULTS)
            post.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(post.call_count, 1)
        text = _texts(post)[0]
        self.assertTrue(text.startswith(
            f"<b>{alarm.MARK} Sauron alarm — the emergency flatten ran</b>\n"))
        for line in ("Bots turned off: 3", "Positions closed: 4",
                     "Close errors: 1",
                     "Some positions may still be open at the broker — "
                     "check /positions/.",
                     "Paper positions left open, their market shut: 1"):
            self.assertIn(line, text)
        for leak in ("AAPL", "336", "USD", "EURUSD", "1.0850"):
            self.assertNotIn(leak, text)

    def test_the_announcement_goes_from_the_request_not_through_a_worker(self):
        """A flatten is the moment the workers may be what is broken: the
        one fenced call leaves from the kill's own process after the
        commit, never queued behind a worker that may be dead."""
        import bot_program.tasks as tasks
        self.assertFalse(hasattr(tasks, "announce_alarm_kill_switch"))
        self.assertNotIn("apply_async", inspect.getsource(alarm))
        self.assertNotIn("delay(", inspect.getsource(alarm))

    def test_no_errors_no_warning_line_and_nothing_while_off(self):
        clean = dict(RESULTS, errors=[], paper_waiting=[])
        with patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            alarm.after_kill_switch(clean)
        self.assertNotIn("may still be open", _texts(post)[0])
        self.assertNotIn("Paper positions", _texts(post)[0])
        _component(alarm.COMPONENT_KEY, on=False)
        with patch(POST) as post, self.captureOnCommitCallbacks(execute=True):
            alarm.after_kill_switch(RESULTS)
        post.assert_not_called()

    def test_the_hook_never_raises(self):
        with patch("bot_program.alarm.kill_counts",
                   side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.alarm", level="WARNING"):
            alarm.after_kill_switch(RESULTS)
        with patch(POST, side_effect=RuntimeError("boom")), \
                self.captureOnCommitCallbacks(execute=True):
            alarm.after_kill_switch(RESULTS)

    def _pinned(self, superuser=False):
        from portfolio.trader_profile import get_or_create_profile
        make = (User.objects.create_superuser if superuser
                else User.objects.create_user)
        user = make("root", "root@example.test", "x")
        prof = get_or_create_profile(user)
        prof.set_pin("4321")
        prof.save()
        self.client.force_login(user)
        return user

    def test_the_api_view_tells_the_chat_and_a_raising_hook_never_fails_it(self):
        import json
        self._pinned()
        with patch(KILL, return_value=RESULTS) as ks, \
                patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.client.post("/api/kill-switch/",
                                 data=json.dumps({"pin": "4321"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), RESULTS)
        ks.assert_called_once()
        self.assertEqual(post.call_count, 1)
        with patch(KILL, return_value=RESULTS), \
                patch("bot_program.alarm.after_kill_switch",
                      side_effect=RuntimeError("boom")), \
                self.assertLogs("dashboard.views", level="WARNING"):
            r = self.client.post("/api/kill-switch/",
                                 data=json.dumps({"pin": "4321"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), RESULTS)

    def test_the_hq_button_tells_the_chat_and_a_raising_hook_never_fails_it(self):
        self._pinned(superuser=True)
        with patch(KILL, return_value=RESULTS) as ks, \
                patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.client.post("/admin-hq/flatten-all/",
                                 {"pin": "4321", "reason": "test"})
        self.assertEqual(r.status_code, 302)
        ks.assert_called_once()
        self.assertEqual(post.call_count, 1)
        with patch(KILL, return_value=RESULTS), \
                patch("bot_program.alarm.after_kill_switch",
                      side_effect=RuntimeError("boom")), \
                self.assertLogs("dashboard.views_admin_hq", level="WARNING"):
            r = self.client.post("/admin-hq/flatten-all/",
                                 {"pin": "4321", "reason": "test"})
        self.assertEqual(r.status_code, 302)


# ── the wiring ───────────────────────────────────────────────────────────

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


class WiringTests(TestCase):
    def test_the_registry_row_arrives_off_and_is_not_exempt(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES,
                                           PlatformComponent, seed_components)
        entry = next(c for c in DEFAULT_COMPONENTS
                     if c["key"] == alarm.COMPONENT_KEY)
        self.assertLess(len(entry["description"]), 300)
        self.assertLessEqual(len(entry["name"]), 100)
        self.assertEqual(entry["category"], "system")
        self.assertNotIn("is_enabled", entry)
        for word in ("CRITICAL", "/status", "/stopall", "master switch",
                     "OFF on arrival"):
            self.assertIn(word, entry["description"])
        self.assertNotIn(alarm.COMPONENT_KEY, BULK_ENABLE_EXEMPT)
        self.assertNotIn(alarm.COMPONENT_KEY, LIVE_MONEY_SWITCHES)
        seed_components()
        self.assertFalse(PlatformComponent.objects.get(
            key=alarm.COMPONENT_KEY).is_enabled)

    def test_the_groups_all_on_arms_it_and_all_off_silences_it(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        admin = User.objects.create_superuser("root", "root@example.test",
                                              "x")
        self.client.force_login(admin)

        def state():
            return PlatformComponent.objects.get(
                key=alarm.COMPONENT_KEY).is_enabled
        self.client.post("/admin-dashboard/bulk-toggle/",
                         {"category": "system", "action": "enable",
                          "next": "ops"})
        self.assertTrue(state())
        self.client.post("/admin-dashboard/bulk-toggle/",
                         {"category": "system", "action": "disable",
                          "next": "ops"})
        self.assertFalse(state())

    def test_the_two_beat_entries_their_queues_and_the_registered_tasks(self):
        from celery.app.routes import MapRoute
        from config.celery import app
        poll = app.conf.beat_schedule["poll-telegram-alarm"]
        self.assertEqual(poll["task"], "bot_program.tasks.poll_telegram_alarm")
        self.assertEqual(poll["schedule"], 15.0)
        sentinel = app.conf.beat_schedule["alarm-sentinel"]
        self.assertEqual(sentinel["task"],
                         "bot_program.tasks.run_alarm_sentinel")
        self.assertEqual(sentinel["schedule"], 600.0)
        route = MapRoute(app.conf.task_routes)
        self.assertEqual(
            (route("bot_program.tasks.poll_telegram_alarm") or {})
            .get("queue"), "fast")
        self.assertEqual(
            (route("bot_program.tasks.run_alarm_sentinel") or {})
            .get("queue"), "default")
        app.loader.import_default_modules()
        for name in ("bot_program.tasks.poll_telegram_alarm",
                     "bot_program.tasks.run_alarm_sentinel"):
            self.assertIn(name, app.tasks)

    def test_its_lock_and_cache_namespaces_are_its_own(self):
        self.assertNotEqual(alarm.BATCH_LOCK_ID, eye.BATCH_LOCK_ID)
        for key in (alarm.STATE_KEY, alarm.LOCK_KEY, alarm.NOTE_KEY,
                    alarm.FAILING_KEY, alarm.RATE_KEY, alarm.ME_KEY):
            self.assertTrue(key.startswith("telegram_alarm:"), key)
        self.assertEqual(alarm.REMIND_S[alarm.STANDING], morgul.REMIND_S)
        self.assertEqual(alarm.REMIND_S[alarm.FAULT], 24 * 3600)
        self.assertIsNone(alarm.REMIND_S[alarm.EVENT])

    def test_the_token_variable_is_scrubbed_from_every_log(self):
        from core.secret_scrub import scrub
        self.assertTrue(alarm.TOKEN_ENV.endswith("_TOKEN"))
        with patch.dict(os.environ, ENV):
            self.assertNotIn(TOKEN, scrub(f"failed at bot{TOKEN}/send"))

    def test_the_command_is_in_the_ops_registry_and_not_on_the_web(self):
        from core import ops_commands
        entry = ops_commands.get("alarm")
        self.assertEqual(entry["category"], "decide")
        self.assertFalse(entry["read_only"])
        self.assertFalse(ops_commands.is_runnable(entry))
        self.assertNotIn("alarm", ops_commands.runnable_names())

    def test_the_module_carries_no_call_that_arms_opens_closes_or_flattens(self):
        src = inspect.getsource(alarm)
        for needle in ("execute_kill_switch(", "enabled = True",
                       "is_enabled =", ").update(", ".save(",
                       ".objects.create(", "update_or_create", "cancel_order",
                       "market_order", "close_position", "select_for_update",
                       "set_credentials", "requests.post",
                       # the Eye's voice: every sender that reads its token
                       "send_to_chat(", "send_telegram(", "_send_telegram(",
                       "notify_staff(", "dispatch_notification(",
                       "Notification.objects", "notify_channel"):
            self.assertNotIn(needle, src, needle)
        self.assertEqual(src.count("apply_brake("), 1)
        self.assertEqual(src.count("post_message("), 1)
        self.assertEqual(src.count("requests.get("), 1)
        self.assertNotIn("morgul.STATE_KEY", src)


# ── the command ──────────────────────────────────────────────────────────

class CommandTests(_AlarmCase):
    def _run(self, *args):
        out = StringIO()
        call_command("alarm", *args, stdout=out)
        text = out.getvalue()
        self.assertNotIn(TOKEN, text)
        return text

    def test_bare_prints_the_verdict_and_what_it_sees_and_sends_nothing(self):
        _component("platform_master", on=False)
        with patch(FAULTS, return_value=CLEAR), patch(POST) as post:
            text = self._run()
        post.assert_not_called()
        self.assertIn("Switch: on", text)
        self.assertIn(f"Configuration: ready — token set, chat {CHAT}", text)
        self.assertIn("Critical problems now: 1", text)
        self.assertIn("[fault] Sauron alarm — automation is paused", text)
        self.assertIn("(master|off)", text)
        self.assertIn("nothing was sent", text)
        self.assertIsNone(cache.get(alarm.STATE_KEY.format(source="sentinel")))
        _component(alarm.COMPONENT_KEY, on=False)
        self.assertIn("Switch: off (manage.py component on telegram_alarm)",
                      self._run())

    def test_test_sends_one_message_and_refuses_when_not_configured(self):
        from bot_program.management.commands.alarm import TEST_TITLE
        _component(alarm.COMPONENT_KEY, on=False)   # an operator act, not gated
        with patch(POST, side_effect=_ok) as post:
            text = self._run("--test")
        self.assertIn("Test message: delivered", text)
        self.assertEqual(post.call_count, 1)
        self.assertIn(html.escape(TEST_TITLE), _texts(post)[0])
        self.assertIn("critical problems only", _texts(post)[0])
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": ""}), \
                patch(POST) as post:
            text = self._run("--test")
        post.assert_not_called()
        self.assertIn("Configuration: refused — TELEGRAM_ALARM_CHAT_ID is "
                      "not set", text)
        self.assertIn("Not sent: the configuration is refused.", text)
        with patch(POST, side_effect=_refused):
            self.assertIn("NOT delivered", self._run("--test"))

    def test_send_runs_one_sentinel_pass(self):
        _component("platform_master", on=False)
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post:
            text = self._run("--send")
        self.assertEqual(post.call_count, 1)
        self.assertIn("Problems: 1 · due: 1 · messages sent: 1 · not "
                      "delivered: 0", text)
        _component(alarm.COMPONENT_KEY, on=False)
        with patch(POST) as post:
            self.assertIn("Not sent: the switch is off.", self._run("--send"))
        post.assert_not_called()

    def test_chats_lists_what_wrote_to_the_bot_without_confirming(self):
        updates = [{"update_id": 1, "message": {"chat": {
            "id": -1002222333, "type": "group", "title": "Sauron alarms"}}},
                   {"update_id": 2, "message": {"chat": {
                       "id": 42, "type": "private"}}}]
        with patch.object(alarm, "_api", return_value=(updates, None)) as api:
            text = self._run("--chats")
        self.assertIn("-1002222333  group  Sauron alarms", text)
        self.assertIn("42  private", text)
        self.assertIn("TELEGRAM_ALARM_CHAT_ID", text)
        self.assertNotIn("offset", api.call_args.args[2])
        with patch.object(alarm, "_api", return_value=([], None)):
            self.assertIn("No chat seen", self._run("--chats"))


# ── the health row ───────────────────────────────────────────────────────

class HealthRowTests(_AlarmCase):
    def test_off_refused_and_configured(self):
        from dashboard.views_system_health import check_alarm_bot, system_health
        _component(alarm.COMPONENT_KEY, on=False)
        row = check_alarm_bot()
        self.assertEqual((row["label"], row["state"], row["configured"]),
                         ("Alarm bot", "ok", False))
        self.assertIn("off", row["detail"])
        self.assertIn("component on telegram_alarm", row["hint"])
        _component(alarm.COMPONENT_KEY)
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": EYE_GROUP}):
            row = check_alarm_bot()
        self.assertEqual(row["state"], "fail")
        self.assertIn("TELEGRAM_CHAT_ID", row["detail"])
        row = check_alarm_bot()
        self.assertEqual((row["state"], row["configured"]), ("ok", True))
        self.assertIn("unverified", row["detail"])
        self.assertIn("alarm --test", row["hint"])
        self.assertIn("(check_alarm_bot, False, True)",
                      inspect.getsource(system_health))

    def test_the_page_renders_the_row(self):
        self.client.force_login(_staff())
        page = self.client.get("/health/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Alarm bot", page.content.decode())
