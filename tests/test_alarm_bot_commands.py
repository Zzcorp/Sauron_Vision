"""The alarm bot's two commands: /status and /stopall in the alarm chat (2026-09-28).

The operator, 2026-09-28: the chat he shares with his father obeys two
commands and nothing else. Pinned here (bot_program/alarm.py; the alarms
themselves are pinned in tests/test_alarm_bot.py):
  - the words: /status and its French alias, /stopall and "/stop all",
    the help; every other command, a quoted question, ordinary chatter:
    no reply;
  - who is obeyed: the alarm chat and no other (another chat gets no
    reply and changes nothing); a command named for another bot
    (/cmd@OtherBot, checked against getMe) is not this bot's; a bot is
    ignored, the anonymous admin heard; a group turned supergroup is said
    at WARNING with the variable to change;
  - /status: counts and names, never an amount -- automation, bots and
    positions (how many, how many live), the guards' line, the critical
    problems now or "No critical problem now.", the time;
  - /stopall: THE BRAKE, the Eye's own apply_brake with withdraw=True for
    every account with a bot running (an inactive account's too: the
    fleet ticks its bots all the same), one reply per account named by
    number; never the kill switch, never the master switch, never a
    close; nothing running says so;
  - the Eye's order, kept whole: a stale or rate-limited command dropped
    but never the brake, the reply on the commit, the batch ending at the
    brake, a locked batch doing nothing, the belt per bot, the confirm
    getUpdates(offset = last + 1) only after the atomic block (a
    TransactionTestCase: a commit that fails announces nothing and
    Telegram still holds the brake), a refusal logged once an hour, the
    token never in the log;
  - the style: every reply English, escaped, a bold first line, no None,
    no snake_case, at most 25 lines and 4,096 characters.

Run with:  python manage.py test tests.test_alarm_bot_commands
"""
import os
import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from bot_program import alarm, morgul
from bot_program import telegram_eye as eye
from tests.test_alarm_bot import (ACCENTED, CHAT, ENV, EYE_GROUP, EYE_TOKEN,
                                  FRENCH, KILL, MONEY, NOW, POST, RESULTS,
                                  SNAKE, TOKEN, _ok, _plain, _texts)
from tests.test_morgul import CLEAR, FAULTS, _cfg, _component, _etoro, _staff, _trade
from tests.test_telegram_eye import FakeTelegram, _update


def _chat(uid, text, **kw):
    return _update(uid, text, chat=CHAT, **kw)


class _ChatCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        _component(alarm.COMPONENT_KEY)
        _component("platform_master")
        self.user = _staff()

    def said(self, update, now=NOW):
        """handle() one update, then what it left for the commit."""
        cache.delete(alarm.RATE_KEY.format(chat=CHAT))
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            verdict = alarm.handle(update, token=TOKEN, chat=CHAT, now=now)
        return verdict, _texts(post)

    def polled(self):
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            out = alarm.poll()
        return out, _texts(post)


# ── the words ────────────────────────────────────────────────────────────

class ParseTests(SimpleTestCase):
    def test_the_two_commands_the_help_and_nothing_else(self):
        yes = {"/status": "status", "/etat": "status", "/État": "status",
               "/STATUS": "status", "status": "status",
               "état des lieux": "status", '"status"': "status",
               "/status@SauronAlarmBot": "status",
               "/stopall": "stopall", "/STOPALL": "stopall",
               "/stop all": "stopall", "/stop tout": "stopall",
               "/stop tous": "stopall", "/stopall@SauronAlarmBot": "stopall",
               "/help": "help", "/start": "help", "/aide": "help"}
        for text, command in yes.items():
            self.assertEqual(alarm.parse(text), (command, ""), text)
        for text in ("/positions", "/why AAPL", "/pourquoi EURUSD",
                     "/stop 4", "/stop", "/stop 4 all", "/q what happened",
                     '"what happened"', "« état des lieux et plus »",
                     "hello", "", "/unknown", "stop all"):
            self.assertEqual(alarm.parse(text), (None, ""), text)


# ── /status ──────────────────────────────────────────────────────────────

class StatusTests(_ChatCase):
    def test_counts_and_names_never_an_amount(self):
        live = _cfg(self.user, "Stocks <live>", "stock", mode="live",
                    capital="10000")
        paper = _cfg(self.user, "Forex swing")
        _cfg(self.user, "Off duty", "stock", enabled=False, mode="live")
        # an inactive account's bot is ticked by the fleet: counted
        gone = User.objects.create_user("gone_fishing", password="x",
                                        is_active=False)
        _cfg(gone, "Still ticking", "crypto")
        _trade(live, "AAPL", entry="336.10", stop="326.02", paper=False,
               metadata={"protected": True})
        _trade(live, "NVDA", entry="180.55", stop="170.25", paper=False,
               metadata={"entry_working": True})
        _trade(paper, "EURUSD", entry="1.0850", stop="1.0790")
        _trade(live, "MSFT", paper=False, status="CLOSED", pnl="-900.00",
               exit_price="400")
        _etoro(self.user, demo=False, last_equity=Decimal("12345.67"),
               last_equity_currency="USD",
               last_used_margin=Decimal("6000.50"))
        _component(morgul.COMPONENT_KEY)
        cache.set(morgul.SUMMARY_KEY, {
            "at": NOW.isoformat(), "guards": 10, "failed": [],
            "findings": [{"guard": "daily_loss", "name": "Daily loss",
                          "severity": "critical", "label": "x"}]})
        with patch(FAULTS, return_value=CLEAR):
            reply = alarm.build_status(NOW)
        self.assertEqual(reply.title, "Sauron alarm — status")
        self.assertEqual([str(ln) for ln in reply.lines], [
            "Automation: on",
            "Bots running: 3 (1 live)",
            "Open positions: 2 (1 live)",
            "Orders waiting at the broker: 1",
            "Guards: 1 critical finding — Daily loss",
            "No critical problem now.",
            "Checked: 2026-09-28 12:00 UTC"])
        plain = _plain(reply.text())
        self.assertIsNone(MONEY.search(plain), plain)
        for leak in ("336", "326", "180", "1.0850", "12,345", "12345",
                     "6,000", "900", "USD", "Equity", "cash", "margin",
                     "AAPL", "NVDA"):
            self.assertNotIn(leak, plain)

    def test_the_critical_problems_now_are_listed_by_name(self):
        live = _cfg(self.user, "Stocks <live>", "stock", mode="live")
        gone = _trade(live, "MSFT", paper=False, status="ERROR")
        _component("platform_master", on=False)
        with patch(FAULTS, return_value=CLEAR):
            reply = alarm.build_status(NOW)
        lines = [str(ln) for ln in reply.lines]
        self.assertEqual(lines[0], "Automation: paused — no bot trades and "
                                   "no safety check runs")
        self.assertIn("Guards: off", lines)
        self.assertIn("Critical problems now: 2", lines)
        self.assertIn(f"{eye.BULLET}automation is paused: no bot trades and "
                      f"no safety check runs", lines)
        self.assertIn(f"{eye.BULLET}a close was abandoned: MSFT #{gone.pk} "
                      f"may still be open at the broker", lines)
        self.assertNotIn("No critical problem now.", lines)

    def test_a_guards_line_that_raises_never_breaks_the_status(self):
        _component(morgul.COMPONENT_KEY)
        with patch(FAULTS, return_value=CLEAR), \
                patch.object(morgul, "_summary",
                             side_effect=RuntimeError("boom")):
            reply = alarm.build_status(NOW)
        self.assertIn("Guards: unreadable (RuntimeError)",
                      [str(ln) for ln in reply.lines])

    def test_the_guards_line_names_critical_findings_only(self):
        """Morgul's own status_line names every finding of its last run,
        warnings included: the Eye's line. This chat hears no warning,
        not even a guard's name in a reply."""
        def summary(at, *findings):
            cache.set(morgul.SUMMARY_KEY, {
                "at": at.isoformat(), "guards": 10, "failed": [],
                "findings": [{"guard": g, "name": n, "severity": s,
                              "label": "x"} for g, n, s in findings]})

        def line():
            with patch(FAULTS, return_value=CLEAR):
                reply = alarm.build_status(NOW)
            return next(str(ln) for ln in reply.lines
                        if str(ln).startswith("Guards:"))
        _component(morgul.COMPONENT_KEY)
        summary(NOW, ("stuck_close", "Stuck close", "warning"),
                ("margin", "Margin", "warning"))
        self.assertEqual(line(), "Guards: no critical finding")
        summary(NOW - timedelta(hours=1),
                ("stuck_close", "Stuck close", "warning"),
                ("daily_loss", "Daily loss", "critical"),
                ("margin", "Margin", "critical"),
                ("no_stop", "No stop", "critical"),
                ("proofs", "Proofs", "critical"),
                ("proofs", "Proofs", "critical"))
        self.assertEqual(line(), "Guards: 5 critical findings — Daily loss, "
                                 "Margin, No stop, +1 more (last ran 1 h ago)")
        cache.delete(morgul.SUMMARY_KEY)
        self.assertEqual(line(), "Guards: no run recorded yet")
        _component(morgul.COMPONENT_KEY, on=False)
        self.assertEqual(line(), "Guards: off")

    def test_many_problems_are_counted_not_listed_whole(self):
        live = _cfg(self.user, "Stocks <live>", "stock", mode="live")
        for i in range(alarm.MAX_PROBLEMS_LISTED + 2):
            _trade(live, f"SYM{i}", paper=False, status="ERROR")
        with patch(FAULTS, return_value=CLEAR):
            reply = alarm.build_status(NOW)
        lines = [str(ln) for ln in reply.lines]
        self.assertIn(f"Critical problems now: {alarm.MAX_PROBLEMS_LISTED + 2}",
                      lines)
        self.assertIn("+2 more on /health/", lines)
        self.assertEqual(sum(1 for ln in lines if "a close was abandoned" in ln),
                         alarm.MAX_PROBLEMS_LISTED)
        self.assertLessEqual(len(reply.text()), 4096)


# ── /stopall ─────────────────────────────────────────────────────────────

class StopAllTests(_ChatCase):
    def test_every_bot_of_every_account_is_stopped_with_withdraw_and_nothing_else(self):
        from core.platform_control import PlatformComponent
        other = User.objects.create_user("gone_fishing", password="x",
                                         is_active=False)
        third = _staff("third")
        live = _cfg(self.user, "Stocks <live>", "stock", mode="live")
        paper = _cfg(self.user, "Forex swing")
        theirs = _cfg(other, "Inactive account's bot", "crypto")
        off = _cfg(third, "Already off", enabled=False)
        working = _trade(live, "NVDA", paper=False,
                         metadata={"entry_working": True})
        _trade(live, "AAPL", paper=False, metadata={"protected": True})
        with patch.object(eye, "_withdraw", return_value=True) as withdraw, \
                patch(KILL) as kill, \
                patch.object(eye, "apply_brake",
                             wraps=eye.apply_brake) as brake:
            replies = alarm.stop_all(now=NOW)
        kill.assert_not_called()
        self.assertTrue(PlatformComponent.objects.get(
            key="platform_master").is_enabled)
        for cfg in (live, paper, theirs, off):
            cfg.refresh_from_db()
            self.assertFalse(cfg.enabled, cfg.name)
        self.assertEqual(brake.call_count, 2)
        for call in brake.call_args_list:
            self.assertEqual((call.kwargs["everything"],
                              call.kwargs["withdraw"]), (True, True))
        withdraw.assert_called_once()
        self.assertEqual(withdraw.call_args.args[0].pk, working.pk)
        self.assertEqual(len(replies), 2)
        self.assertTrue(all(r.title == "Sauron alarm — stop all"
                            for r in replies))
        texts = [r.text() for r in replies]
        # accounts by number, never by username
        self.assertIn(f"Account #{self.user.pk}", _plain(texts[0]))
        self.assertIn(f"Account #{other.pk}", _plain(texts[1]))
        for text in texts:
            self.assertNotIn("gone_fishing", text)
            self.assertNotIn("operator", text)
        mine = texts[0]
        self.assertIn("Stopped (2)", mine)
        self.assertIn("Stocks &lt;live&gt;", mine)
        self.assertIn("Orders withdrawn: 1 (NVDA)", mine)
        self.assertIn("Positions left open: 1 (1 live · 0 paper)", mine)
        for word in eye.BRAKE_WORDS:
            self.assertIn(word, mine)
        self.assertIn("Inactive account&#x27;s bot", texts[1])

    def test_nothing_running_says_so(self):
        _cfg(self.user, "Already off", enabled=False)
        with patch.object(eye, "apply_brake") as brake:
            replies = alarm.stop_all(now=NOW)
        brake.assert_not_called()
        self.assertEqual(len(replies), 1)
        self.assertEqual([str(ln) for ln in replies[0].lines],
                         ["No bot was running: nothing was stopped.",
                          "Checked: 2026-09-28 12:00 UTC"])

    def test_one_account_carries_no_heading(self):
        _cfg(self.user)
        replies = alarm.stop_all(now=NOW)
        self.assertEqual(len(replies), 1)
        self.assertNotIn("Account #", replies[0].text())
        self.assertIn("Stopped (1)", replies[0].text())

    def test_one_accounts_failure_neither_undoes_another_nor_hides_it(self):
        """/stopall over two accounts, the second's brake raising: the
        first stays stopped (a withdrawal at the broker cannot be rolled
        back, and a config the reply calls stopped must stay so), the
        second's reply says the brake failed there, and nothing reads
        "nothing was changed"."""
        from django.db import DatabaseError
        other = User.objects.create_user("gone_fishing", password="x",
                                         is_active=False)
        mine = _cfg(self.user, "Stocks <live>", "stock", mode="live")
        theirs = _cfg(other, "Inactive account's bot", "crypto")
        real = eye.apply_brake

        def brake(user, *args, **kwargs):
            if user.pk == other.pk:
                raise DatabaseError("lost mid-command")
            return real(user, *args, **kwargs)
        with patch.object(eye, "apply_brake", side_effect=brake), \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            verdict, said = self.said(_chat(1, "/stopall"))
        self.assertEqual(verdict, "answered:stopall")
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertFalse(mine.enabled)
        self.assertTrue(theirs.enabled)
        self.assertEqual(len(said), 2)
        first, second = _plain(said[0]), _plain(said[1])
        self.assertIn(f"Account #{self.user.pk}", first)
        self.assertIn("Stopped (1)", first)
        self.assertIn(f"Account #{other.pk}", second)
        self.assertIn("The brake failed on this account (DatabaseError)",
                      second)
        self.assertIn("still be running", second)
        for text in (first, second):
            self.assertNotIn("nothing was changed", text)
            self.assertNotIn("gone_fishing", text)
        self.assertTrue(any(f"account #{other.pk}" in ln
                            and "DatabaseError" in ln for ln in logs.output))

    def test_six_accounts_the_biggest_ones_remainder_counted_right(self):
        """The Eye caps apply_brake's head itself, ending it on "+X more
        on the platform"; the account heading costs one more line, and
        the second cap must fold X into its own count, not drop that
        line as if it were a bot."""
        users = [self.user] + [User.objects.create_user(f"u{i}", password="x")
                               for i in range(5)]
        for u in users[1:]:
            _cfg(u, f"Bot of {u.pk}")
        for i in range(24):
            _cfg(self.user, f"Bot {i:02d}", "stock")
        replies = alarm.stop_all(now=NOW)
        self.assertEqual(len(replies), 6)
        for reply in replies:
            lines = [str(ln) for ln in reply.lines]
            self.assertLessEqual(len(lines), eye.MAX_LINES)
            listed = sum(1 for ln in lines if ln.startswith(eye.BULLET))
            more = sum(int(m.group(1).replace(",", ""))
                       for ln in lines for m in [eye._MORE_RE.match(ln)] if m)
            self.assertEqual(listed + more, len(reply.meta["stopped"]),
                             lines)
        big = [str(ln) for ln in replies[0].lines]
        self.assertIn("Stopped (24)", big)
        self.assertIn("+6 more on the platform", big)
        self.assertEqual(len(big), eye.MAX_LINES)


# ── one update ───────────────────────────────────────────────────────────

class HandleTests(_ChatCase):
    def test_only_the_alarm_chat_is_obeyed(self):
        """No reply, and nothing changed: a bot running stays running,
        and the brake is not even called."""
        cfg = _cfg(self.user)
        with patch.object(eye, "apply_brake") as brake:
            for update in (_update(1, "/stopall", chat=EYE_GROUP),
                           _update(2, "/status", chat="-5337454557"),
                           _update(3, "/stopall", chat="111",
                                   chat_type="private")):
                verdict, said = self.said(update)
                self.assertEqual((verdict, said), ("unauthorised", []))
            verdict, said = self.said(_chat(4, "/status"))
        brake.assert_not_called()
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        self.assertEqual(verdict, "answered:status")
        self.assertEqual(len(said), 1)

    def test_a_command_named_for_another_bot_is_ignored(self):
        with patch.object(alarm, "_api",
                          return_value=({"username": "SauronAlarmBot"},
                                        None)) as api:
            self.assertEqual(self.said(_chat(1, "/status@OtherBot")),
                             ("elsewhere", []))
            self.assertEqual(self.said(_chat(2, "/stopall@Sauron_vision_bot")),
                             ("elsewhere", []))
            self.assertEqual(self.said(_chat(3, "/status@SauronAlarmBot"))[0],
                             "answered:status")
            self.assertEqual(self.said(_chat(4, "/STATUS@sauronalarmbot"))[0],
                             "answered:status")
        # getMe once a day, not once a command
        self.assertEqual(api.call_count, 1)
        self.assertEqual(api.call_args.args[1], "getMe")

    def test_get_me_unanswered_acts_the_direction_is_safe(self):
        with patch.object(alarm, "_api",
                          return_value=(None, "getMe refused (401)")):
            verdict, said = self.said(_chat(1, "/stopall@OtherBot"))
        self.assertEqual(verdict, "answered:stopall")
        self.assertIn("No bot was running", said[0])

    def test_anything_but_the_two_commands_gets_no_reply(self):
        for i, text in enumerate(("/positions", "/why AAPL", "/stop 4",
                                  "/stop", "/q what happened",
                                  '"what happened"', "hello", "/unknown",
                                  "")):
            self.assertEqual(self.said(_chat(i, text)), ("chatter", []), text)

    def test_the_help_lists_exactly_the_two_commands(self):
        for i, text in enumerate(("/help", "/start", "/aide")):
            verdict, said = self.said(_chat(i, text))
            self.assertEqual(verdict, "answered:help")
            plain = _plain(said[0])
            self.assertEqual(set(re.findall(r"/[a-z]+", plain)),
                             {"/status", "/stopall"})
            self.assertEqual(len(plain.split("\n")), 3)
            self.assertIn("never an amount", plain)
            self.assertIn("no position is closed", plain)

    def test_a_stale_status_is_dropped_but_never_the_brake(self):
        cfg = _cfg(self.user)
        self.assertEqual(self.said(_chat(1, "/status", age_s=700), now=None),
                         ("stale", []))
        verdict, said = self.said(_chat(2, "/stopall", age_s=700), now=None)
        self.assertEqual(verdict, "answered:stopall")
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertIn("Sent: ", said[0])
        self.assertIn("(11 min ago)", said[0])

    def test_the_rate_limit_spares_the_brake(self):
        _cfg(self.user)
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post, \
                self.captureOnCommitCallbacks(execute=True):
            verdicts = [alarm.handle(_chat(i, text), token=TOKEN, chat=CHAT,
                                     now=NOW)
                        for i, text in enumerate(("/status", "/status",
                                                  "/stopall", "/stopall"))]
        self.assertEqual(verdicts, ["answered:status", "rate_limited",
                                    "answered:stopall", "answered:stopall"])
        self.assertEqual(post.call_count, 3)

    def test_a_bot_is_ignored_and_the_anonymous_admin_heard(self):
        bot = _chat(1, "/status")
        bot["message"]["from"]["is_bot"] = True
        self.assertEqual(self.said(bot), ("ignored", []))
        admin = _chat(2, "/status")
        admin["message"]["from"] = {"id": 1087968824, "is_bot": True,
                                    "first_name": "Group"}
        admin["message"]["sender_chat"] = {"id": int(CHAT), "type": "group"}
        self.assertEqual(self.said(admin)[0], "answered:status")

    def test_the_reply_leaves_on_the_commit(self):
        with patch(FAULTS, return_value=CLEAR), \
                patch(POST, side_effect=_ok) as post:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                verdict = alarm.handle(_chat(1, "/status"), token=TOKEN,
                                       chat=CHAT, now=NOW)
                post.assert_not_called()
            self.assertEqual(verdict, "answered:status")
            self.assertEqual(len(callbacks), 1)
            post.assert_not_called()
            callbacks[0]()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], TOKEN)
        self.assertEqual(post.call_args.args[1]["chat_id"], CHAT)

    def test_a_builder_that_raises_is_said_and_nothing_changes(self):
        with patch.object(alarm, "build_status",
                          side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.alarm", level="WARNING"):
            verdict, said = self.said(_chat(1, "/status"))
        self.assertEqual(verdict, "answered:status")
        self.assertIn("Sauron alarm — could not answer", said[0])
        self.assertIn("RuntimeError", said[0])
        self.assertIn("nothing was changed", said[0])

    def test_a_supergroup_migration_names_the_variable(self):
        moved = _chat(1, "")
        moved["message"]["migrate_to_chat_id"] = -1009999
        with self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            self.assertEqual(self.said(moved), ("migrated", []))
        self.assertIn("TELEGRAM_ALARM_CHAT_ID=-1009999", logs.output[0])
        self.assertIn(CHAT, logs.output[0])

    def test_the_brake_is_logged_with_the_sender(self):
        cfg = _cfg(self.user)
        with self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            self.said(_chat(1, "/stopall", sender=4242))
        line = next(ln for ln in logs.output if "BRAKE" in ln)
        self.assertIn("sender 4242", line)
        self.assertIn(f"[{cfg.pk}]", line)


# ── the poll ─────────────────────────────────────────────────────────────

class PollTests(_ChatCase):
    def test_the_confirm_carries_offset_last_plus_one(self):
        fake = FakeTelegram([_chat(500, "/help"), _chat(501, "hello")])
        with patch("requests.get", side_effect=fake.get):
            out, said = self.polled()
            again, more = self.polled()
        self.assertEqual(out, {"status": "success", "updates": 2,
                               "answered": 1, "confirmed": True})
        self.assertEqual(fake.calls[0], {"timeout": 0, "limit": 100,
                                         "allowed_updates": '["message"]'})
        self.assertEqual(fake.calls[1], {"offset": 502, "timeout": 0,
                                         "limit": 1,
                                         "allowed_updates": '["message"]'})
        self.assertEqual(again["idle"], "nothing to read")
        self.assertEqual((len(said), more), (1, []))

    def test_a_brake_ends_the_batch_and_the_rest_waits_for_the_next_poll(self):
        cfg = _cfg(self.user)
        fake = FakeTelegram([_chat(520, "/stopall"), _chat(521, "/status")])
        with patch("requests.get", side_effect=fake.get):
            out, said = self.polled()
            cfg.refresh_from_db()
            self.assertFalse(cfg.enabled)
            self.assertEqual(out["answered"], 1)
            self.assertEqual(fake.calls[1]["offset"], 521)
            self.assertIn("Sauron alarm — stop all", said[0])
            out, said = self.polled()
        self.assertEqual(out["answered"], 1)
        self.assertIn("Sauron alarm — status", said[0])
        self.assertEqual(fake.calls[-1]["offset"], 522)

    def test_a_locked_batch_does_nothing(self):
        with patch.object(alarm, "_take_lock", return_value=False), \
                patch("requests.get") as get:
            out = alarm.poll()
        self.assertEqual(out["idle"], "another alarm poll holds the batch")
        get.assert_not_called()
        self.assertIsNone(eye._last_handled(TOKEN))

    def test_a_refusal_is_an_error_logged_once_an_hour_and_its_end_once(self):
        conflict = MagicMock(ok=False, status_code=409)
        conflict.json.return_value = {
            "ok": False,
            "description": "Conflict: terminated by other getUpdates request"}
        with patch("requests.get", return_value=conflict), \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            out = alarm.poll()
        self.assertEqual(out["status"], "error")
        self.assertIn("getUpdates refused (409)", out["error"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("409", logs.output[0])
        with patch("requests.get", return_value=conflict), \
                self.assertLogs("bot_program.alarm", level="DEBUG") as logs:
            alarm.poll()
        self.assertEqual([r for r in logs.records if r.levelno >= 30], [])
        fake = FakeTelegram([])
        with patch("requests.get", side_effect=fake.get), \
                self.assertLogs("bot_program.alarm", level="INFO") as logs:
            alarm.poll()
        self.assertTrue(any("answers again" in ln for ln in logs.output))

    def test_a_redelivered_update_is_skipped_by_the_belt(self):
        eye._remember(TOKEN, 600)
        fake = FakeTelegram([_chat(600, "/status")])
        with patch("requests.get", side_effect=fake.get), \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            out, said = self.polled()
        self.assertEqual((out["answered"], said), (0, []))
        self.assertTrue(any("update 600" in ln and "handled before" in ln
                            for ln in logs.output))

    def test_the_belt_is_per_bot(self):
        eye._remember(EYE_TOKEN, 700)
        fake = FakeTelegram([_chat(700, "/status")])
        with patch("requests.get", side_effect=fake.get):
            out, said = self.polled()
        self.assertEqual((out["answered"], len(said)), (1, 1))
        self.assertEqual(eye._last_handled(TOKEN), 700)

    def test_another_chat_is_confirmed_and_ignored(self):
        cfg = _cfg(self.user)
        fake = FakeTelegram([_update(610, "/stopall", chat=EYE_GROUP)])
        with patch("requests.get", side_effect=fake.get), \
                patch.object(eye, "apply_brake") as brake, \
                self.assertLogs("bot_program.alarm", level="INFO") as logs:
            out, said = self.polled()
        self.assertEqual(out, {"status": "success", "updates": 1,
                               "answered": 0, "confirmed": True})
        self.assertEqual(said, [])
        self.assertEqual(fake.calls[1]["offset"], 611)
        self.assertTrue(any(f"ignored chat {EYE_GROUP}" in ln
                            for ln in logs.output))
        self.assertFalse(any("/stopall" in ln for ln in logs.output))
        # the brake was not called, and the bot still runs
        brake.assert_not_called()
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)

    def test_the_token_never_reaches_the_log(self):
        boom = requests.ConnectionError(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates")
        with patch("requests.get", side_effect=boom), \
                self.assertLogs("bot_program.alarm", level="WARNING") as logs:
            out = alarm.poll()
        self.assertEqual(out["error"], "getUpdates unreachable (ConnectionError)")
        self.assertNotIn(TOKEN, "".join(logs.output))

    def test_a_refused_configuration_polls_nothing(self):
        with patch.dict(os.environ, {"TELEGRAM_ALARM_CHAT_ID": EYE_GROUP}), \
                patch("requests.get") as get, \
                self.assertLogs("bot_program.alarm", level="WARNING"):
            out = alarm.poll()
        self.assertIn("TELEGRAM_CHAT_ID", out["skipped"])
        get.assert_not_called()


class CommitTests(TransactionTestCase):
    """Real commits: the brake's reply leaves after the COMMIT, and the
    confirm is issued after the atomic block. A batch whose commit fails
    announces nothing, moves no belt, and Telegram still holds the brake
    for the next poll."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        _component(alarm.COMPONENT_KEY)
        _component("platform_master")
        self.user = _staff()

    def test_the_brake_reply_leaves_after_the_commit_and_the_confirm_after_the_block(self):
        from bot_program.asset_models import AssetBotConfig
        cfg = _cfg(self.user)
        seen, calls = [], []
        fake = FakeTelegram([_chat(900, "/stopall")])

        def post(token, payload, **kwargs):
            seen.append((connection.in_atomic_block,
                         AssetBotConfig.objects.get(pk=cfg.pk).enabled))
            return _ok()

        def get(url, params=None, timeout=None):
            calls.append((connection.in_atomic_block,
                          (params or {}).get("offset")))
            return fake.get(url, params=params, timeout=timeout)

        with patch("requests.get", side_effect=get), \
                patch(POST, side_effect=post), \
                patch(FAULTS, return_value=CLEAR):
            out = alarm.poll()
        self.assertEqual(out["answered"], 1)
        self.assertEqual(seen, [(False, False)])
        self.assertEqual(calls, [(True, None), (False, 901)])
        self.assertEqual(eye._last_handled(TOKEN), 900)

    def test_a_commit_that_fails_announces_nothing_and_telegram_still_holds_the_brake(self):
        from django.db import DatabaseError, connections
        cfg = _cfg(self.user)
        fake = FakeTelegram([_chat(910, "/stopall")])
        with patch("requests.get", side_effect=fake.get), \
                patch(POST, side_effect=_ok) as post, \
                patch.object(connections["default"], "commit",
                             side_effect=DatabaseError("lost at commit")):
            with self.assertRaises(DatabaseError):
                alarm.poll()
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        post.assert_not_called()
        self.assertIsNone(eye._last_handled(TOKEN))
        self.assertEqual([c.get("offset") for c in fake.calls], [None])
        with patch("requests.get", side_effect=fake.get), \
                patch(POST, side_effect=_ok) as post:
            out = alarm.poll()
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertEqual((out["answered"], post.call_count), (1, 1))
        self.assertEqual([c.get("offset") for c in fake.calls],
                         [None, None, 911])


# ── the style ────────────────────────────────────────────────────────────

class StyleTests(_ChatCase):
    def test_every_reply_is_english_escaped_and_fits(self):
        live = _cfg(self.user, "Stocks <live>", "stock", mode="live")
        _trade(live, "NVDA", paper=False, metadata={"entry_working": True})
        _trade(live, "AAPL", paper=False, metadata={"protected": False})
        _trade(live, "MSFT", paper=False, status="ERROR")
        _component("platform_master", on=False)
        replies = []
        with patch(FAULTS, return_value=CLEAR), \
                patch.object(eye, "_withdraw", return_value=False):
            replies.append(alarm.build_status(NOW))
            replies.append(alarm.build_help())
            replies.append(alarm.could_not_answer("DatabaseError"))
            replies += alarm.stop_all(now=NOW, sent_at=NOW - timedelta(hours=1))
            replies.append(alarm._bundle(
                [alarm.Alarm(f"k|{i}", f"problem number {i}")
                 for i in range(30)], NOW))
            for a in alarm.problems(NOW):
                replies.append(eye.Reply(alarm.MARK, a.title, a.lines))
        texts = [r.text() for r in replies]
        with patch(POST, side_effect=_ok) as post:
            alarm.announce_kill_switch(alarm.kill_counts(RESULTS, NOW))
        texts += _texts(post)
        self.assertGreaterEqual(len(texts), 8)
        for text in texts:
            self.assertTrue(text.startswith("<b>"), text)
            plain = _plain(text)
            self.assertNotIn("None", plain)
            self.assertNotIn("Decimal(", plain)
            self.assertIsNone(SNAKE.search(plain), plain)
            self.assertIsNone(ACCENTED.search(plain), plain)
            low = " " + re.sub(r"[^a-zà-ÿ]+", " ", plain.lower()) + " "
            for word in FRENCH:
                self.assertNotIn(word, low, plain)
            self.assertLessEqual(len(text.split("\n")), eye.MAX_LINES + 1)
            self.assertLessEqual(len(text), 4096)
