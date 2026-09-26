"""The Telegram eye: Sauron answers its group (2026-09-26).

The operator's ask, 2026-09-26: "Sauron peut-il faire un état des lieux sur
Telegram? Répondre quand demandé entre guillemets", and the rule that came
with it: every message in English, in an irreproachable style. Pinned here:
  - who may speak: only the configured staff chat, claimed by ONE account.
    Another chat gets no reply and changes nothing, and its text never
    reaches the log; a chat two accounts claim is refused and said so; a
    bot is ignored, an anonymous admin heard; a group turned supergroup is
    said at WARNING;
  - every trigger and every French alias routes to its builder, and every
    reply is English (no accented letter, no French word);
  - the house style: money, quantities, prices, percentages, ages, the em
    dash for the unmeasured, a bold heading, and no None / Decimal( /
    snake_case in ANY reply the module builds (engine skip details
    included), at most 25 lines and 4,096 characters;
  - the status report with a demo row, one open trade and the live world
    read patched (and a read that raises);
  - the brake: /stop turns off exactly the named config of that user and
    never another user's, reads bot numbers only; /stopall; its words kept
    whole however long the list; a live position with no stop at the broker
    is said; a late brake says when it was sent; it is never rate-limited
    or dropped as stale; the module's source carries no call that arms,
    opens or closes anything;
  - the question: begin_ask for real, the answer queued after the commit
    and behind the reply, plain and trimmed on the way back, the daily
    cap, every failure said, a stale question billed nothing;
  - the poll: the confirm carries offset = last + 1, a batch ends at a
    brake, a flood is drained, a locked batch skips, a lost confirm cannot
    answer twice, a refusal is logged once an hour and its end once, the
    token never reaches the log, the belt is per bot;
  - the commit (a TransactionTestCase): the reply leaves after the commit,
    and a batch that fails after the brake announces nothing and is
    applied when Telegram delivers it again;
  - the wiring: the registry row (OFF on arrival), the beat entry, the two
    routes, and the dormant reader stays unscheduled.

Run with:  python manage.py test tests.test_telegram_eye
"""
import inspect
import os
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from html import escape
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from bot_program import telegram_eye as eye

GROUP = "-5337454557"
TOKEN = "SECRET123"
SEND = "bot_program.notifications._send_telegram"
TRADER = "bot_program.engine.etoro_client.EtoroTrader"
FAULTS = "core.component_digest.collect_faults"
DELAY = "bot_program.tasks.answer_telegram_question.delay"
CLEAR = {"errors": [], "warnings": [], "silent": [], "feeds": [],
         "checked": 54}
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
ACCENTED = re.compile(r"[À-ÖØ-öø-ÿŒœ]")
FRENCH = (" le ", " la ", " les ", " des ", " est ", " pas ", " une ",
          " du ", " et ")
BRAIN_DETAIL = "brain pause_recommended for momentum_breakout: drawdown 7%"
LEVERAGE_DETAIL = ("at 2x: the etoro_leverage_live switch is OFF "
                   "(leverageValues [1, 2], maxStopLossPercentage None, "
                   "headroom Decimal('0.00'))")


def _staff(name="Sauron", chat=GROUP, channel="telegram", staff=True):
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    user = User.objects.create_user(username=name, password="x",
                                    is_staff=staff)
    profile, _ = TraderProfile.objects.get_or_create(user=user)
    profile.notify_channel = channel
    profile.save()
    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=user)
    prefs.telegram_chat_id = chat
    prefs.save()
    return user


def _cfg(user, name="Crypto momentum", asset_class="crypto", *,
         enabled=True, mode="paper", symbols=None, extras=None):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=enabled,
        mode=mode, symbols=list(symbols or []), extras=dict(extras or {}))


def _trade(cfg, symbol="AAPL", *, side="BUY", qty="0.04", entry="336.10",
           stop="326.02", target=None, paper=True, status="OPEN",
           metadata=None):
    from bot_program.asset_models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=None if stop is None else Decimal(stop),
        take_profit=None if target is None else Decimal(target),
        paper=paper, status=status, metadata=dict(metadata or {}))


def _etoro(user, **fields):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, **fields)
    acct.set_credentials("the-api-key", "the-user-key")
    acct.save()
    return acct


def _update(uid, text, *, chat=GROUP, chat_type="group", sender=111,
            age_s=0):
    return {"update_id": uid,
            "message": {"message_id": uid,
                        "date": int(timezone.now().timestamp()) - age_s,
                        "chat": {"id": int(chat), "type": chat_type},
                        "from": {"id": sender, "is_bot": False,
                                 "first_name": "P"},
                        "text": text}}


def _texts(send):
    """What each _send_telegram call would have put on the wire."""
    from bot_program.notifications import _telegram_text
    return [_telegram_text(c.args[1], c.args[2], lines=c.kwargs.get("lines"),
                           mark=c.kwargs.get("mark", ""))
            for c in send.call_args_list]


def _lines(reply):
    return [str(ln) for ln in reply.lines]


class FakeTelegram:
    """getUpdates with Telegram's rule: an offset forgets what is below it."""

    def __init__(self, updates, honour_offset=True):
        self.updates = list(updates)
        self.honour_offset = honour_offset
        self.calls = []

    def get(self, url, params=None, timeout=None):
        assert url.endswith("/getUpdates"), url
        params = dict(params or {})
        self.calls.append(params)
        if "offset" in params and self.honour_offset:
            self.updates = [u for u in self.updates
                            if u["update_id"] >= params["offset"]]
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {
            "ok": True, "result": list(self.updates[:params.get("limit", 100)])}
        return resp


class _EyeCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = _staff()

    def said(self, update):
        """handle() one update, then run what it left for the commit."""
        with self.captureOnCommitCallbacks(execute=True):
            return eye.handle(update)

    def polled(self):
        """One poll, then what it left for the commit (replies, belt)."""
        with self.captureOnCommitCallbacks(execute=True):
            return eye.poll()


# ── what was said ────────────────────────────────────────────────────────

class ParseTests(SimpleTestCase):
    def test_every_trigger_and_every_french_alias(self):
        cases = {
            "/status": ("status", ""), "/etat": ("status", ""),
            "/état": ("status", ""), "/ÉTAT": ("status", ""),
            "/status@Sauron_vision_alerts_bot": ("status", ""),
            "status": ("status", ""), "Status": ("status", ""),
            "état des lieux": ("status", ""),
            "Etat des lieux ?": ("status", ""),
            '"état des lieux"': ("status", ""),
            "« état des lieux »": ("status", ""),
            "“status”": ("status", ""),
            "/positions": ("positions", ""),
            "/why AAPL": ("why", "AAPL"), "/pourquoi eurusd": ("why", "eurusd"),
            "/help": ("help", ""), "/aide": ("help", ""),
            "/stop 4": ("stop", "4"), "/stopall": ("stopall", ""),
            "/q What is the regime?": ("ask", "What is the regime?"),
            "/ask Why so quiet?": ("ask", "Why so quiet?"),
            '"What is the regime?"': ("ask", "What is the regime?"),
            "« Que fait l'or ? »": ("ask", "Que fait l'or ?"),
            "“Why no trade today?”": ("ask", "Why no trade today?"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(eye.parse(text), expected)

    def test_ordinary_chatter_and_unknown_commands_are_never_answered(self):
        for text in ("hello", "status report please",
                     "the état des lieux later", "/buy AAPL", "", '""', "/",
                     "«»"):
            with self.subTest(text=text):
                self.assertEqual(eye.parse(text), (None, ""))


# ── the house style ──────────────────────────────────────────────────────

class StyleTests(SimpleTestCase):
    def test_money_quantities_prices_and_percentages(self):
        self.assertEqual(eye.money(Decimal("332443.09"), "USD"),
                         "332,443.09 USD")
        self.assertEqual(eye.money(1234.5, "usd"), "1,234.50 USD")
        self.assertEqual(eye.money(0, "USD"), "0.00 USD")
        self.assertEqual(eye.money(None, "USD"), "—")
        self.assertEqual(eye.money("unread", "USD"), "—")
        self.assertEqual(eye.quantity(Decimal("0.04000000")), "0.04")
        self.assertEqual(eye.quantity(Decimal("1.00000000")), "1")
        self.assertEqual(eye.quantity(10000), "10,000")
        self.assertEqual(eye.price(Decimal("336.10000000")), "336.10")
        self.assertEqual(eye.price(Decimal("1.08345000")), "1.08345")
        self.assertEqual(eye.price(60123.5), "60,123.50")
        self.assertEqual(eye.price(None), "—")
        self.assertEqual(eye.percent(7), "7.0%")
        self.assertEqual(eye.percent(None), "—")

    def test_ages_and_absolute_times(self):
        now = timezone.now()
        self.assertEqual(eye.ago(now - timedelta(seconds=20), now), "just now")
        self.assertEqual(eye.ago(now - timedelta(minutes=12), now),
                         "12 min ago")
        self.assertEqual(eye.ago(now - timedelta(hours=3, minutes=5), now),
                         "3 h ago")
        self.assertEqual(eye.ago(now - timedelta(days=2, hours=1), now),
                         "2 d ago")
        self.assertEqual(eye.ago(None, now), "—")
        self.assertEqual(
            eye.when(datetime(2026, 9, 27, 14, 5, 33, tzinfo=dt_tz.utc)),
            "2026-09-27 14:05 UTC")

    def test_a_heading_is_bold_and_a_plain_line_renders_as_before(self):
        from bot_program.notifications import TelegramHeading, _telegram_text
        text = _telegram_text("Sauron — status report",
                              lines=[TelegramHeading("Bots <running>"),
                                     "Equity: 1.00 USD"],
                              mark=eye.MARK_STATUS)
        self.assertEqual(text.split("\n"),
                         ["<b>\U0001F4CB Sauron — status report</b>",
                          "<b>Bots &lt;running&gt;</b>", "Equity: 1.00 USD"])

    def test_the_line_cap_counts_what_it_cuts(self):
        lines = eye._cap([f"line {i}" for i in range(40)])
        self.assertEqual(len(lines), eye.MAX_LINES)
        self.assertEqual(lines[-1], "+16 more on the platform")

    def test_a_reply_past_telegram_limit_is_cut_and_keeps_its_tail(self):
        block = "&" * 80
        reply = eye.Reply(eye.MARK_BRAKE, "Sauron — brake applied",
                          [f"  • {block} #{i} — paper" for i in range(24)]
                          + ["No position was closed.", "Applied: now"],
                          meta={"keep_tail": 2})
        self.assertGreater(len(reply.text()), eye.TELEGRAM_MAX_CHARS)
        text = eye.fit(reply).text()
        self.assertLessEqual(len(text), eye.TELEGRAM_MAX_CHARS)
        self.assertTrue(text.endswith("No position was closed.\nApplied: now"))
        more = re.search(r"\+(\d+) more on the platform", text)
        self.assertEqual(text.count(escape(block)) + int(more.group(1)), 24)
        short = eye.Reply(eye.MARK_HELP, "Sauron — commands", ["one"])
        self.assertIs(eye.fit(short), short)

    def test_an_engine_detail_reads_as_words(self):
        self.assertEqual(eye.plain_detail(BRAIN_DETAIL),
                         "brain pause recommended for momentum breakout: "
                         "drawdown 7%")
        self.assertEqual(
            eye.plain_detail(LEVERAGE_DETAIL),
            "at 2x: the etoro leverage live switch is OFF (leverage values "
            "[1, 2], max stop loss percentage —, headroom 0.00)")
        self.assertEqual(
            eye.plain_detail("fell back to PaperTrader: "
                             "https://api.test/v1?apikey=abcdef123456"),
            "fell back to paper trader: (a link)")
        self.assertEqual(eye.plain_detail("eToro said no; IBKR too"),
                         "eToro said no; IBKR too")
        self.assertEqual(len(eye.plain_detail("word " * 100)), 200)

    def test_every_skip_code_has_english_words(self):
        from bot_program.asset_engine import skips
        codes = {v for k, v in vars(skips).items()
                 if k.isupper() and isinstance(v, str)}
        self.assertTrue(codes)
        self.assertEqual(codes - set(eye.SKIP_WORDS), set())

    def test_the_answer_loses_its_markdown_and_keeps_its_words(self):
        text = eye.plain_answer(
            "## Regime\n\n**Mean-reverting** since *Tuesday*, per "
            "<<REPORT:17>> and [the brief](/briefing/).\n\n- one\n- two "
            "`code`\n\n<<APPROVE:12>>\n```strategy-draft\n{}\n```")
        self.assertEqual(text.split("\n")[:3],
                         ["Regime", "", "Mean-reverting since Tuesday, per "
                          "brain report #17 and the brief."])
        self.assertIn("• one", text)
        self.assertIn("• two code", text)
        for mark in ("**", "##", "`", "<<", "APPROVE", "{}"):
            self.assertNotIn(mark, text)

    def test_the_trim_counts_the_escaped_text(self):
        text = eye.trim_answer("a < b & c " * 800)
        self.assertLessEqual(len(escape(text)), eye.ANSWER_MAX_CHARS)
        self.assertTrue(text.endswith("… (continued on the platform)"))
        self.assertEqual(eye.trim_answer("short"), "short")


# ── who may speak ────────────────────────────────────────────────────────

class AuthorisationTests(_EyeCase):
    def test_another_chat_gets_no_reply_no_write_and_its_text_is_not_logged(self):
        cfg = _cfg(self.user)
        with patch(SEND) as send, \
                self.assertLogs("bot_program.telegram_eye", level="INFO") as logs:
            verdict = self.said(_update(1, "/stopall secret words",
                                        chat="-999"))
        self.assertEqual(verdict, "unauthorised")
        send.assert_not_called()
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        self.assertTrue(any("-999" in ln for ln in logs.output))
        self.assertFalse(any("secret" in ln or "stopall" in ln
                             for ln in logs.output), logs.output)

    def test_a_private_chat_that_is_not_the_configured_one_is_ignored(self):
        with patch(SEND) as send:
            verdict = self.said(_update(2, "/status", chat="111",
                                        chat_type="private"))
        self.assertEqual(verdict, "unauthorised")
        send.assert_not_called()

    def test_only_an_active_staff_user_on_telegram_authorises_a_chat(self):
        _staff("not_staff", chat="-100", staff=False)
        _staff("by_mail", chat="-200", channel="email")
        chats = eye.authorised_chats()
        self.assertEqual(set(chats), {GROUP})
        self.assertEqual(chats[GROUP].pk, self.user.pk)

    def test_a_chat_two_accounts_claim_is_refused_and_said_once(self):
        mine = _cfg(self.user)
        theirs = _cfg(_staff("twin"), "Theirs")
        with patch(SEND, return_value=True) as send, \
                self.assertLogs("bot_program.telegram_eye",
                                level="WARNING") as logs:
            first = self.said(_update(40, "/stopall"))
            second = self.said(_update(41, "/status"))
        self.assertEqual((first, second), ("ambiguous", "ambiguous"))
        for row in (mine, theirs):
            row.refresh_from_db()
            self.assertTrue(row.enabled)
        self.assertEqual(eye.authorised_chats(), {})
        (text,) = _texts(send)
        self.assertIn("This chat is configured for several accounts.", text)
        self.assertTrue(any("Sauron" in ln and "twin" in ln
                            for ln in logs.output), logs.output)

    def test_a_bot_is_ignored_and_an_anonymous_admin_is_heard(self):
        bot = _update(42, "/help")
        bot["message"]["from"]["is_bot"] = True
        anon = _update(43, "/help")
        anon["message"]["from"] = {"id": 1087968824, "is_bot": True,
                                   "first_name": "Group"}
        anon["message"]["sender_chat"] = {"id": int(GROUP), "type": "group"}
        with patch(SEND, return_value=True) as send:
            self.assertEqual(self.said(bot), "ignored")
            self.assertEqual(self.said(anon), "answered:help")
        self.assertEqual(send.call_count, 1)

    def test_a_group_turned_supergroup_is_said_at_warning(self):
        new_id = "-1001234567890"
        old = _update(44, "")
        old["message"].pop("text")
        old["message"]["migrate_to_chat_id"] = int(new_id)
        new = _update(45, "", chat=new_id, chat_type="supergroup")
        new["message"].pop("text")
        new["message"]["migrate_from_chat_id"] = int(GROUP)
        with patch(SEND) as send, \
                self.assertLogs("bot_program.telegram_eye",
                                level="WARNING") as logs:
            self.assertEqual(self.said(old), "migrated")
            self.assertEqual(self.said(new), "migrated")
        send.assert_not_called()
        self.assertEqual(sum(new_id in ln and "Sauron" in ln
                             for ln in logs.output), 2, logs.output)

    def test_chatter_in_the_group_gets_nothing(self):
        with patch(SEND) as send:
            self.assertEqual(self.said(_update(3, "good morning all")),
                             "chatter")
        send.assert_not_called()

    def test_a_command_is_logged_by_its_word_never_by_its_text(self):
        with patch(SEND, return_value=True), patch(DELAY), \
                self.assertLogs("bot_program", level="INFO") as logs:
            self.said(_update(46, "/q zebra secret plans"))
        self.assertTrue(any(f"chat {GROUP} · ask · sender 111" in ln
                            for ln in logs.output), logs.output)
        self.assertFalse(any("zebra" in ln for ln in logs.output),
                         logs.output)


# ── every trigger, in English ────────────────────────────────────────────

class RoutingTests(_EyeCase):
    def test_every_trigger_routes_to_its_builder_and_answers_in_english(self):
        cfg = _cfg(self.user, symbols=["AAPL"])
        _trade(cfg)
        client = MagicMock()
        client.net_liquidation.return_value = (2013.4, "USD")
        client.get_positions.return_value = []
        titles = {
            "/status": "Sauron — status report",
            "/etat": "Sauron — status report",
            "/état": "Sauron — status report",
            "état des lieux": "Sauron — status report",
            "« état des lieux »": "Sauron — status report",
            "/positions": "Sauron — open positions",
            "/why AAPL": "Sauron — why no trade on AAPL",
            "/pourquoi aapl": "Sauron — why no trade on AAPL",
            "/help": "Sauron — commands",
            "/aide": "Sauron — commands",
        }
        for i, (text, title) in enumerate(titles.items()):
            cache.clear()
            with self.subTest(text=text), \
                    patch(SEND, return_value=True) as send, \
                    patch(TRADER, return_value=client), \
                    patch(FAULTS, return_value=CLEAR):
                verdict = self.said(_update(10 + i, text))
                self.assertEqual(verdict, "answered:" + eye.parse(text)[0])
                self.assertEqual(send.call_args.args[1], title)
                (rendered,) = _texts(send)
                self.assertIsNone(ACCENTED.search(rendered), rendered)
                for word in FRENCH:
                    self.assertNotIn(word, rendered.lower())


# ── the status report ────────────────────────────────────────────────────

class StatusReportTests(_EyeCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.acct = _etoro(
            self.user, demo=True, is_primary_for_stocks=True,
            is_primary_for_crypto=True, last_equity=Decimal("100012.50"),
            last_equity_currency="USD",
            last_equity_at=now - timedelta(minutes=12),
            last_available_cash=Decimal("99500"), last_used_margin=None)
        self.cfg = _cfg(self.user)
        _trade(self.cfg)
        self.client = MagicMock()
        self.client.net_liquidation.return_value = (2013.4, "USD")
        self.client.get_positions.return_value = [{"symbol": "ETORO:1001"}]
        env = patch.dict(os.environ, {"SAURON_GIT_SHA": "abc1234",
                                      "SAURON_BUILT_AT": ""})
        env.start()
        self.addCleanup(env.stop)

    def _report(self, faults=CLEAR):
        with patch(TRADER, return_value=self.client) as trader, \
                patch(FAULTS, return_value=faults):
            reply = eye.build_status(self.user)
        self.trader = trader
        return reply

    def test_the_report_lines(self):
        reply = self._report()
        self.assertEqual(reply.title, "Sauron — status report")
        self.assertEqual(reply.mark, eye.MARK_STATUS)
        lines = _lines(reply)
        for expected in (
                "Version: abc1234", "eToro", "World: Demo",
                "Classes routed here: Stocks, Crypto",
                "Demo account · synced 12 min ago",
                "Equity: 100,012.50 USD", "Available cash: 99,500.00 USD",
                "Used margin: —", "Live account · read now",
                "Equity: 2,013.40 USD", "Open positions: 1",
                "Bots running (1)",
                f"  • Crypto momentum #{self.cfg.pk} — paper",
                "Platform health: all clear (54 components checked)",
                "Demo proofs pinned: none yet", "Open on the platform (1)",
                "  • AAPL long 0.04 @ 336.10 · stop 326.02 · paper"):
            self.assertIn(expected, lines)
        self.assertLessEqual(len(lines), eye.MAX_LINES)
        self.assertIsInstance(reply.lines[1], type(eye.heading("x")))

    def test_the_live_world_is_read_through_the_client_and_only_read(self):
        self._report()
        self.assertEqual(self.trader.call_args.kwargs.get("env"), "live")
        self.assertEqual(self.trader.call_args.args[:2],
                         ("the-api-key", "the-user-key"))
        self.assertEqual({c[0] for c in self.client.method_calls},
                         {"net_liquidation", "get_positions"})

    def test_a_live_read_that_raises_says_so_and_never_shows_the_key(self):
        self.client.get_positions.side_effect = requests.ConnectionError(
            "https://x/?key=the-api-key")
        text = self._report().text()
        self.assertIn("Live account: unreadable (ConnectionError)", text)
        self.assertNotIn("the-api-key", text)
        self.assertNotIn("Live account · read now", text)

    def test_no_etoro_row_no_bot_and_a_hand_taken_config_read_as_words(self):
        self.acct.delete()
        self.cfg.enabled = False
        self.cfg.save()
        lines = _lines(self._report())
        self.assertIn("Connection: not set up", lines)
        self.assertIn("No bot is running", lines)
        manual = _cfg(self.user, "manual", "stock")
        self.assertIn(f"  • Hand-taken trades (Stocks) #{manual.pk} — paper",
                      _lines(self._report()))

    def test_faults_are_counted_by_kind(self):
        faults = dict(CLEAR, errors=[{"name": "Breaking News"}],
                      silent=[{"name": "Crypto Prices"},
                              {"name": "Forex Quotes"}])
        lines = _lines(self._report(faults))
        self.assertIn("Platform health: 3 issues", lines)
        self.assertIn("Failing: 1 (Breaking News)", lines)
        self.assertIn("Stopped: 2 (Crypto Prices, Forex Quotes)", lines)

    def test_a_long_book_fits_the_cap_and_counts_the_rest(self):
        for i in range(14):
            _trade(self.cfg, symbol=f"SYM{i}")
        lines = _lines(self._report())
        self.assertLessEqual(len(lines), eye.MAX_LINES)
        more = re.fullmatch(r"\+(\d+) more: send /positions", lines[-1])
        self.assertIsNotNone(more, lines[-1])
        shown = [ln for ln in lines if ln.startswith("  • ") and " @ " in ln]
        self.assertEqual(len(shown) + int(more.group(1)), 15)

    def test_no_reply_carries_a_repr_snake_case_french_or_too_much(self):
        """EVERY reply the module builds, through the style pin: the
        builders make the style, and this checks each of them, the
        engine's own skip details included."""
        from brain.research_models import ResearchMessage
        from bot_program.asset_engine import skips
        skips.record(self.cfg, "AAPL", skips.BRAIN_PAUSED, BRAIN_DETAIL)
        forex = _cfg(self.user, "Forex swing", "forex", symbols=["EURUSD"])
        skips.record(forex, "EURUSD", skips.LEVERAGE_REFUSED, LEVERAGE_DETAIL)
        _trade(forex, symbol="EURUSD", side="SELL", qty="1000",
               entry="1.08345", stop=None, paper=False)
        late = timezone.now() - timedelta(hours=2)
        replies = []
        with patch(TRADER, return_value=self.client), \
                patch(FAULTS, return_value=CLEAR):
            replies += [eye.build_status(self.user),
                        eye.build_positions(self.user),
                        eye.build_why(self.user, "AAPL"),
                        eye.build_why(self.user, "EURUSD"),
                        eye.build_why(self.user, "ZZZ"),
                        eye.build_why(self.user, ""),
                        eye.build_help(), eye.which_bot(),
                        eye.ambiguous_reply(),
                        eye.could_not_answer("RuntimeError")]
            for command, arg in (("status", ""), ("positions", ""),
                                 ("why", "aapl"), ("help", ""),
                                 ("stop", ""), ("stop", "4 à 14h30"),
                                 ("ask", ""), ("ask", "What now?")):
                replies.append(eye.route(command, arg, self.user, GROUP))
            conv = eye._conversation(self.user, GROUP)
            for i in range(eye.QUESTIONS_PER_DAY - 1):
                ResearchMessage.objects.create(conversation=conv, role="user",
                                               content=f"q{i}")
            replies.append(eye.ask_question(self.user, GROUP, "one more?"))
            replies.append(eye.apply_brake(self.user, [self.cfg.pk, 999999],
                                           sent_at=late))
            replies.append(eye.apply_brake(self.user, everything=True))
        faults = dict(CLEAR, errors=[{"key": "scraper_news"}],
                      feeds=[{"name": "Crypto Prices"}])
        with patch(TRADER, side_effect=RuntimeError("down")), \
                patch(FAULTS, return_value=faults):
            replies.append(eye.build_status(self.user))
        self.acct.delete()
        with patch(FAULTS, side_effect=RuntimeError("unread")):
            replies.append(eye.build_status(self.user))
        self.assertEqual(len(replies), 23)
        for reply in replies:
            text = eye.fit(reply).text()
            with self.subTest(title=reply.title, first=_lines(reply)[:1]):
                self.assertTrue(text.startswith("<b>"), text)
                self.assertNotIn("None", text)
                self.assertNotIn("Decimal(", text)
                self.assertEqual(SNAKE.findall(text), [])
                self.assertLessEqual(len(text.split("\n")) - 1,
                                     eye.MAX_LINES)
                self.assertLessEqual(len(text), eye.TELEGRAM_MAX_CHARS)
                self.assertIsNone(ACCENTED.search(text), text)
                for word in FRENCH:
                    self.assertNotIn(word, text.lower())


# ── the open book, and why no trade ──────────────────────────────────────

class PositionsAndWhyTests(_EyeCase):
    def test_the_open_book(self):
        cfg = _cfg(self.user)
        _trade(cfg, target="352.90")
        _trade(cfg, symbol="EURUSD", side="SELL", qty="10000",
               entry="1.08345", stop="1.09", paper=False)
        _etoro(self.user, demo=True, broker_positions=[{"symbol": "EURUSD"}],
               broker_positions_at=timezone.now() - timedelta(minutes=5))
        lines = _lines(eye.build_positions(self.user))
        self.assertEqual(lines[0], "Open on the platform: 2 (1 live · 1 paper)")
        self.assertIn("  • AAPL long 0.04 @ 336.10 · stop 326.02 · target "
                      "352.90 · paper · opened just now", lines)
        self.assertIn("  • EURUSD short 10,000 @ 1.08345 · stop 1.09 · "
                      "target — · live · opened just now", lines)
        self.assertIn("Held at eToro (demo, synced 5 min ago): 1", lines)

    def test_the_last_skip_in_words(self):
        at = (timezone.now() - timedelta(minutes=12)).isoformat()
        cfg = _cfg(self.user, symbols=["AAPL"], extras={
            "skips": {"AAPL": {"code": "no_signals",
                               "detail": "nothing fresh in 4 h", "at": at}},
            "skip_counts": {"no_signals": 3, "hold": 1}})
        _trade(cfg)
        reply = eye.build_why(self.user, "aapl")
        self.assertEqual(reply.title, "Sauron — why no trade on AAPL")
        lines = _lines(reply)
        self.assertIn("Open now: AAPL long 0.04 @ 336.10 · stop 326.02 · "
                      "paper", lines)
        self.assertIn(f"Crypto momentum #{cfg.pk} — running · paper", lines)
        self.assertIn("Last reason: No fresh signal to vote on", lines)
        self.assertIn("When: 12 min ago", lines)
        self.assertIn("Detail: nothing fresh in 4 h", lines)
        self.assertIn("Bot overall: no fresh signal to vote on in 75.0% of "
                      "4 skips", lines)

    def test_an_engine_detail_and_a_single_skip_read_as_english(self):
        from bot_program.asset_engine import skips
        cfg = _cfg(self.user, symbols=["AAPL"])
        skips.record(cfg, "AAPL", skips.BRAIN_PAUSED, BRAIN_DETAIL)
        lines = _lines(eye.build_why(self.user, "AAPL"))
        self.assertIn("Last reason: The brain advised a pause", lines)
        self.assertIn("Detail: brain pause recommended for momentum "
                      "breakout: drawdown 7%", lines)
        self.assertIn("Bot overall: the brain advised a pause in 100.0% of "
                      "1 skip", lines)

    def test_a_long_why_is_cut_to_what_telegram_accepts(self):
        from bot_program.asset_engine import skips
        for i in range(4):
            cfg = _cfg(self.user, f"Bot {i}", symbols=["AAPL"])
            skips.record(cfg, "AAPL", skips.HOLD, '"' * 200)
        with patch(SEND, return_value=True) as send:
            self.said(_update(50, "/why AAPL"))
        (text,) = _texts(send)
        self.assertLessEqual(len(text), eye.TELEGRAM_MAX_CHARS)
        self.assertIn("more on the platform", text)

    def test_a_symbol_no_bot_of_this_user_watches(self):
        _cfg(_staff("other", chat="-42"), symbols=["AAPL"])
        _cfg(self.user, symbols=["MSFT"])
        self.assertIn("No bot watches AAPL.",
                      _lines(eye.build_why(self.user, "AAPL")))


# ── the brake ────────────────────────────────────────────────────────────

class BrakeTests(_EyeCase):
    def test_stop_turns_off_exactly_the_named_config_of_that_user(self):
        a = _cfg(self.user, "Crypto momentum")
        b = _cfg(self.user, "Stocks core", "stock")
        c = _cfg(_staff("other", chat="-42"), "Theirs")
        with patch(SEND, return_value=True) as send, \
                self.assertLogs("bot_program.telegram_eye",
                                level="WARNING") as logs:
            self.said(_update(20, f"/stop {a.pk}"))
            self.said(_update(21, f"/stop {c.pk}"))
        for row in (a, b, c):
            row.refresh_from_db()
        self.assertFalse(a.enabled)
        self.assertTrue(b.enabled)
        self.assertTrue(c.enabled)
        first, second = _texts(send)
        self.assertIn("Sauron — brake applied", first)
        self.assertIn(f"Crypto momentum #{a.pk} — paper", first)
        self.assertIn("Sauron — nothing to stop", second)
        self.assertIn(f"No bot #{c.pk} on this account.", second)
        self.assertTrue(any("BRAKE" in ln and f"[{a.pk}]" in ln
                            for ln in logs.output), logs.output)

    def test_stop_reads_bot_numbers_and_nothing_else(self):
        a = _cfg(self.user, "Crypto momentum")
        b = _cfg(self.user, "Stocks core", "stock")
        with patch(SEND, return_value=True) as send:
            self.assertEqual(self.said(_update(60, f"/stop {a.pk} à 14h30")),
                             "answered:stop")
            a.refresh_from_db()
            self.assertTrue(a.enabled)
            self.said(_update(61, f"/stop #{a.pk}, #{b.pk}."))
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual([a.enabled, b.enabled], [False, False])
        first, second = _texts(send)
        self.assertIn("Sauron — which bot?", first)
        self.assertIn("Numbers only: /stop 4 7 stops two bots.", first)
        self.assertIn("Stopped (2)", second)

    def test_stopall_stops_every_running_bot_of_that_user_and_closes_nothing(self):
        from bot_program.asset_models import AssetBotTrade
        a = _cfg(self.user, "Crypto momentum")
        b = _cfg(self.user, "Stocks core", "stock", mode="live")
        off = _cfg(self.user, "Forex idle", "forex", enabled=False)
        theirs = _cfg(_staff("other", chat="-42"), "Theirs")
        _trade(a)
        _trade(b, paper=False, metadata={"protected": True})
        with patch(SEND, return_value=True) as send:
            self.assertEqual(self.said(_update(22, "/stopall")),
                             "answered:stopall")
        for row in (a, b, off, theirs):
            row.refresh_from_db()
        self.assertEqual([a.enabled, b.enabled, off.enabled, theirs.enabled],
                         [False, False, False, True])
        (text,) = _texts(send)
        self.assertIn("Stopped (2)", text)
        self.assertIn("Positions left open: 2 (1 live · 1 paper)", text)
        for words in eye.BRAKE_WORDS:
            self.assertIn(words, text)
        self.assertIn("Paper stops are simulated by the bot and pause while "
                      "it is stopped.", text)
        self.assertNotIn("Live without a stop at the broker", text)
        self.assertEqual(AssetBotTrade.objects.filter(status="OPEN").count(), 2)

    def test_stop_all_in_french_is_the_same_brake(self):
        a = _cfg(self.user, "Crypto momentum")
        with patch(SEND, return_value=True) as send:
            self.assertEqual(self.said(_update(65, "/stop tout")),
                             "answered:stop")
        a.refresh_from_db()
        self.assertFalse(a.enabled)
        self.assertIn("Sauron — brake applied", _texts(send)[0])

    def test_a_live_position_without_a_stop_at_the_broker_is_said(self):
        a = _cfg(self.user, "Stocks core", "stock", mode="live")
        _trade(a, paper=False)
        _trade(a, symbol="MSFT", paper=False, metadata={"protected": True})
        with patch(SEND, return_value=True) as send:
            self.said(_update(62, f"/stop {a.pk}"))
        (text,) = _texts(send)
        self.assertIn("Live without a stop at the broker: 1", text)
        self.assertIn("The bot managed those stops; while it is stopped, "
                      "nothing protects them.", text)

    def test_a_late_brake_says_when_it_was_sent(self):
        a = _cfg(self.user)
        with patch(SEND, return_value=True) as send:
            self.said(_update(63, f"/stop {a.pk}", age_s=7200))
        a.refresh_from_db()
        self.assertFalse(a.enabled)
        (text,) = _texts(send)
        self.assertRegex(text, r"Sent: \d{4}-\d\d-\d\d \d\d:\d\d UTC "
                               r"\(2 h ago\)")

    def test_a_long_stopall_keeps_the_brake_words_whole(self):
        from bot_program.asset_models import AssetBotConfig
        for i in range(30):
            _cfg(self.user, f"{'&' * 70} {i}")
        with patch(SEND, return_value=True) as send:
            self.said(_update(64, "/stopall"))
        (text,) = _texts(send)
        self.assertLessEqual(len(text), eye.TELEGRAM_MAX_CHARS)
        for words in eye.BRAKE_WORDS:
            self.assertIn(words, text)
        self.assertIn("more on the platform", text)
        self.assertFalse(AssetBotConfig.objects.filter(
            user=self.user, enabled=True).exists())

    def test_the_brake_is_never_rate_limited_nor_dropped_as_stale(self):
        a = _cfg(self.user, "Crypto momentum")
        b = _cfg(self.user, "Stocks core", "stock")
        with patch(SEND, return_value=True) as send:
            self.said(_update(23, "/help"))
            self.said(_update(24, f"/stop {a.pk}"))
            self.said(_update(25, f"/stop {b.pk}", age_s=3600))
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.enabled)
        self.assertFalse(b.enabled)
        self.assertEqual(send.call_count, 3)

    def test_nothing_to_stop_and_a_missing_number_answer_in_words(self):
        with patch(SEND, return_value=True) as send:
            self.said(_update(26, "/stopall"))
            self.said(_update(27, "/stop"))
        first, second = _texts(send)
        self.assertIn("Sauron — nothing to stop", first)
        self.assertIn("No bot was running.", first)
        self.assertIn("Give the bot number, for example: /stop 4", second)

    def test_the_module_carries_no_call_that_arms_opens_or_closes(self):
        src = inspect.getsource(eye)
        for needle in ("enabled = True", "market_order", "close_position",
                       "update(enabled=True", "demo=False", "demo = False",
                       "modify_protective", "modify_target", "cancel_order",
                       "set_credentials", "is_enabled =",
                       "select_for_update"):
            self.assertNotIn(needle, src)
        self.assertEqual(re.findall(r"\.save\([^)]*\)", src),
                         ['.save(update_fields=["enabled", "updated_at"])'])
        self.assertEqual(re.findall(r"(\w+)\.objects\.create\(", src),
                         ["ResearchConversation"])


# ── the question ─────────────────────────────────────────────────────────

class QuestionTests(_EyeCase):
    def _pending(self):
        from brain.research_agent import begin_ask
        _q, pending = begin_ask(eye._conversation(self.user, GROUP),
                                "What now?")
        return pending

    def test_a_quoted_question_is_queued_after_the_commit_behind_the_reply(self):
        from brain.research_models import ResearchMessage
        with patch(SEND, return_value=True) as send, patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                verdict = eye.handle(_update(30, "« What is the regime? »"))
            self.assertEqual(verdict, "answered:ask")
            send.assert_not_called()
            delay.assert_not_called()
            self.assertEqual(len(callbacks), 2)
            callbacks[0]()
            self.assertEqual(send.call_count, 1)
            delay.assert_not_called()
            callbacks[1]()
        question = ResearchMessage.objects.get(role="user")
        pending = ResearchMessage.objects.get(role="assistant")
        self.assertTrue(question.content.startswith("What is the regime?"))
        self.assertIn("Answer in English", question.content)
        self.assertEqual(question.conversation.title,
                         f"Telegram · chat {GROUP}")
        self.assertFalse(question.conversation.is_active)
        delay.assert_called_once_with(pending.pk)
        (text,) = _texts(send)
        self.assertIn("Sauron — question received", text)
        self.assertIn("The answer follows here in a few minutes.", text)
        self.assertIn("Questions today: 1 of 30", text)

    def test_the_answer_is_plain_trimmed_and_sent_to_the_group(self):
        from brain.research_models import ResearchMessage
        pending = self._pending()
        answer = ("## Regime\n\n**Mean-reverting** since Tuesday, per "
                  "<<REPORT:17>>.\n\n- first point\n\n" + "word " * 1200)

        def complete(pk):
            from brain.research_agent import _settle
            _settle(ResearchMessage.objects.get(pk=pk), content=answer)
            return {"ok": True}

        with patch("brain.research_agent.complete_ask",
                   side_effect=complete), \
                patch(SEND, return_value=True) as send:
            out = eye.answer_question(pending.pk)
        self.assertEqual(out, {"status": "success", "sent": 1})
        self.assertEqual(send.call_args.args[1], "Sauron — answer")
        body = send.call_args.args[2]
        self.assertTrue(body.startswith("Regime\n\nMean-reverting since "
                                        "Tuesday, per brain report #17."))
        self.assertIn("• first point", body)
        self.assertTrue(body.endswith("… (continued on the platform)"))
        self.assertLessEqual(len(body), eye.ANSWER_MAX_CHARS)
        for mark in ("**", "##", "<<"):
            self.assertNotIn(mark, body)

    def test_an_agent_that_raises_is_said_and_the_row_is_settled(self):
        pending = self._pending()
        with patch("brain.research_agent.complete_ask",
                   side_effect=RuntimeError("boom")), \
                patch(SEND, return_value=True) as send:
            out = eye.answer_question(pending.pk)
        self.assertEqual(out, {"status": "error", "error": "RuntimeError"})
        (text,) = _texts(send)
        self.assertIn("Sauron could not answer (RuntimeError).", text)
        pending.refresh_from_db()
        self.assertFalse(pending.is_pending)

    def test_a_spent_budget_is_said_in_words(self):
        pending = self._pending()
        with patch("brain.research_agent.can_spend",
                   return_value=(False, "the daily cap is reached")), \
                patch(SEND, return_value=True) as send:
            eye.answer_question(pending.pk)
        (text,) = _texts(send)
        self.assertIn("Sauron could not answer (daily AI budget spent).", text)

    def test_the_daily_cap(self):
        from brain.research_models import ResearchMessage
        conv = eye._conversation(self.user, GROUP)
        for i in range(eye.QUESTIONS_PER_DAY):
            ResearchMessage.objects.create(conversation=conv, role="user",
                                           content=f"q{i}")
        with patch(SEND, return_value=True) as send, \
                patch(DELAY) as delay:
            self.said(_update(31, "/q one more?"))
        delay.assert_not_called()
        self.assertEqual(ResearchMessage.objects.filter(role="user").count(),
                         eye.QUESTIONS_PER_DAY)
        (text,) = _texts(send)
        self.assertIn("Sauron — daily question limit reached", text)
        self.assertIn("Questions today: 30 of 30", text)
        self.assertIn("The limit resets at 00:00 UTC.", text)

    def test_a_queue_that_refuses_settles_the_row_and_says_so(self):
        from brain.research_models import ResearchMessage

        class BrokerDown(Exception):
            pass

        with patch(SEND, return_value=True) as send, \
                patch(DELAY, side_effect=BrokerDown()):
            self.said(_update(32, "/q still there?"))
        received, failed = _texts(send)
        self.assertIn("Sauron — question received", received)
        self.assertIn("Sauron could not answer (BrokerDown).", failed)
        self.assertFalse(ResearchMessage.objects.filter(
            status=ResearchMessage.STATUS_PENDING).exists())

    def test_an_empty_question_asks_for_one(self):
        with patch(SEND, return_value=True) as send:
            self.said(_update(33, "/q"))
        (text,) = _texts(send)
        self.assertIn("Write the question after /q, for example:", text)

    def test_a_stale_command_is_dropped_and_a_stale_question_bills_nothing(self):
        from brain.research_models import ResearchMessage
        with patch(SEND) as send, patch(DELAY) as delay:
            self.assertEqual(self.said(_update(34, "/q old news?",
                                               age_s=3600)), "stale")
            self.assertEqual(self.said(_update(35, "/help", age_s=3600)),
                             "stale")
        send.assert_not_called()
        delay.assert_not_called()
        self.assertFalse(ResearchMessage.objects.exists())


# ── the poll ─────────────────────────────────────────────────────────────

class PollTests(_EyeCase):
    def setUp(self):
        super().setUp()
        from core.platform_control import PlatformComponent
        self.row, _ = PlatformComponent.objects.update_or_create(
            key="telegram_eye", defaults={"name": "Telegram Eye",
                                          "category": "system",
                                          "is_enabled": True})
        env = patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def test_the_confirm_carries_offset_last_plus_one(self):
        fake = FakeTelegram([_update(500, "/help"), _update(501, "hello")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send:
            out = self.polled()
            again = self.polled()
        self.assertEqual(out, {"status": "success", "updates": 2,
                               "answered": 1, "confirmed": True})
        self.assertEqual(fake.calls[0], {"timeout": 0, "limit": 100,
                                         "allowed_updates": '["message"]'})
        self.assertEqual(fake.calls[1], {"offset": 502, "timeout": 0,
                                         "limit": 1,
                                         "allowed_updates": '["message"]'})
        self.assertEqual(again["updates"], 0)
        self.assertEqual(send.call_count, 1)

    def test_a_brake_ends_the_batch_and_the_rest_waits_for_the_next_poll(self):
        a = _cfg(self.user)
        fake = FakeTelegram([_update(520, "/stopall"),
                             _update(521, "/status")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send, \
                patch(FAULTS, return_value=CLEAR):
            first = self.polled()
            self.assertEqual(first["answered"], 1)
            self.assertEqual(fake.calls[1]["offset"], 521)
            self.assertEqual(send.call_args.args[1], "Sauron — brake applied")
            a.refresh_from_db()
            self.assertFalse(a.enabled)
            second = self.polled()
        self.assertEqual(second["answered"], 1)
        self.assertEqual(send.call_args.args[1], "Sauron — status report")

    def test_a_flood_from_other_chats_is_drained_and_logged_once(self):
        flood = [_update(1000 + i, "/stopall", chat="-999")
                 for i in range(150)]
        fake = FakeTelegram(flood + [_update(1150, "/help")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send, \
                self.assertLogs("bot_program.telegram_eye",
                                level="INFO") as logs:
            out = self.polled()
        self.assertEqual(out["updates"], 151)
        self.assertEqual(out["answered"], 1)
        self.assertEqual([c.get("offset") for c in fake.calls],
                         [None, 1100, 1151])
        self.assertTrue(all(c["allowed_updates"] == '["message"]'
                            for c in fake.calls))
        self.assertEqual(sum("ignored chat -999" in ln
                             for ln in logs.output), 1)
        self.assertEqual(send.call_count, 1)

    def test_a_locked_batch_skips_and_a_lost_confirm_cannot_answer_twice(self):
        fake = FakeTelegram([_update(600, "/help")], honour_offset=False)
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send:
            with patch("bot_program.telegram_eye._take_lock",
                       return_value=False):
                busy = self.polled()
            self.assertEqual(busy, {"status": "skipped",
                                    "reason": "another poll holds the batch"})
            self.assertEqual(fake.calls, [])
            first = self.polled()
            cache.delete(eye.RATE_KEY.format(chat=GROUP))
            with self.assertLogs("bot_program.telegram_eye",
                                 level="WARNING") as logs:
                second = self.polled()
        self.assertEqual(first["answered"], 1)
        self.assertEqual(second["answered"], 0)
        self.assertEqual(send.call_count, 1)
        self.assertTrue(any("update 600 from chat " + GROUP in ln
                            and "handled before" in ln
                            for ln in logs.output), logs.output)

    def test_the_batch_lock_is_an_advisory_lock_taken_without_waiting(self):
        fake_db = MagicMock(vendor="postgresql")
        cursor = fake_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (False,)
        with patch("django.db.connection", fake_db):
            self.assertFalse(eye._take_lock())
        sql, params = cursor.execute.call_args.args
        self.assertIn("pg_try_advisory_xact_lock", sql)
        self.assertEqual(params, [eye.BATCH_LOCK_ID])
        self.assertEqual(connection.vendor, "sqlite")
        self.assertTrue(eye._take_lock())

    def test_the_belt_is_kept_per_bot_and_never_holds_the_token(self):
        self.assertNotEqual(eye._cursor_key("111:A"), eye._cursor_key("222:B"))
        self.assertNotIn(TOKEN, eye._cursor_key(TOKEN))
        eye._remember("ANOTHER-BOT", 10 ** 6)
        fake = FakeTelegram([_update(530, "/help")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send:
            out = self.polled()
        self.assertEqual(out["answered"], 1)
        self.assertEqual(eye._last_handled(TOKEN), 530)
        self.assertEqual(send.call_count, 1)

    def test_a_refusal_or_a_network_error_is_logged_and_never_raises(self):
        refused = MagicMock(ok=False, status_code=409)
        refused.json.return_value = {
            "ok": False,
            "description": "Conflict: terminated by other getUpdates request"}
        with patch("requests.get", return_value=refused), \
                self.assertLogs("bot_program.telegram_eye",
                                level="WARNING") as first:
            out = self.polled()
        self.assertEqual(out["status"], "error")
        self.assertIn("getUpdates refused (409): Conflict", out["error"])
        with patch("requests.get", side_effect=requests.ConnectionError(
                "Max retries exceeded with url: /botSECRET123/getUpdates")), \
                self.assertLogs("bot_program.telegram_eye",
                                level="WARNING") as second:
            out = self.polled()
        self.assertEqual(out, {"status": "error",
                               "error": "getUpdates unreachable "
                                        "(ConnectionError)"})
        self.assertFalse(any(TOKEN in ln
                             for ln in first.output + second.output))

    def test_a_lasting_refusal_is_logged_once_and_its_end_once(self):
        refused = MagicMock(ok=False, status_code=409)
        refused.json.return_value = {"ok": False, "description": "Conflict"}
        with patch("requests.get", return_value=refused), \
                self.assertLogs("bot_program.telegram_eye",
                                level="DEBUG") as logs:
            for _ in range(4):
                self.assertEqual(self.polled()["status"], "error")
        warnings = [ln for ln in logs.output if ln.startswith("WARNING")]
        self.assertEqual(len(warnings), 1, logs.output)
        fake = FakeTelegram([])
        with patch("requests.get", side_effect=fake.get), \
                self.assertLogs("bot_program.telegram_eye",
                                level="INFO") as back:
            self.polled()
            self.polled()
        self.assertEqual(sum("getUpdates answers again" in ln
                             for ln in back.output), 1, back.output)

    def test_a_burst_answers_once(self):
        fake = FakeTelegram([_update(701, "/help"), _update(702, "/aide")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send:
            out = self.polled()
        self.assertEqual(out["answered"], 1)
        self.assertEqual(send.call_count, 1)

    def test_no_token_or_no_configured_chat_reads_nothing(self):
        fake = FakeTelegram([_update(750, "/help")])
        with patch("requests.get", side_effect=fake.get):
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
                self.assertEqual(self.polled()["status"], "skipped")
            self.user.is_staff = False
            self.user.save()
            self.assertEqual(self.polled()["status"], "skipped")
        self.assertEqual(fake.calls, [])

    def test_the_guarded_task_reads_nothing_while_the_component_is_off(self):
        from bot_program.tasks import poll_telegram_eye
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="platform_master", defaults={"name": "Master",
                                             "category": "system",
                                             "is_enabled": True})
        self.row.is_enabled = False
        self.row.save()
        fake = FakeTelegram([_update(800, "/help")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(poll_telegram_eye()["status"], "skipped")
            self.assertEqual(fake.calls, [])
            send.assert_not_called()
            self.row.is_enabled = True
            self.row.save()
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(poll_telegram_eye()["answered"], 1)
        self.assertEqual(send.call_count, 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.last_status, "success")


# ── the commit, for real ─────────────────────────────────────────────────

class CommitTests(TransactionTestCase):
    """Real commits (no test transaction around them): the reply leaves
    after the COMMIT, and a batch that dies after its brake was handled
    announces nothing, moves no belt, and applies the brake when Telegram
    delivers it again."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = _staff()
        env = patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def test_the_brake_reply_leaves_after_the_commit(self):
        from bot_program.asset_models import AssetBotConfig
        cfg = _cfg(self.user)
        seen = []

        def send(*args, **kwargs):
            seen.append((connection.in_atomic_block,
                         AssetBotConfig.objects.get(pk=cfg.pk).enabled))
            return True

        fake = FakeTelegram([_update(900, f"/stop {cfg.pk}")])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, side_effect=send):
            out = eye.poll()
        self.assertEqual(out["answered"], 1)
        self.assertEqual(seen, [(False, False)])
        self.assertEqual(eye._last_handled(TOKEN), 900)

    def test_a_batch_that_dies_after_the_brake_announces_nothing(self):
        cfg = _cfg(self.user)
        stop = _update(910, f"/stop {cfg.pk}")

        def api(token, method, params):
            if "offset" in params:  # the confirm: the worker dies here
                raise RuntimeError("killed")
            return [stop], None

        with patch.object(eye, "_api", side_effect=api), \
                patch(SEND, return_value=True) as send:
            with self.assertRaises(RuntimeError):
                eye.poll()
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        send.assert_not_called()
        self.assertIsNone(eye._last_handled(TOKEN))
        fake = FakeTelegram([stop])
        with patch("requests.get", side_effect=fake.get), \
                patch(SEND, return_value=True) as send:
            out = eye.poll()
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertEqual(out["answered"], 1)
        self.assertEqual(send.call_count, 1)


# ── the wiring ───────────────────────────────────────────────────────────

class WiringTests(TestCase):
    def test_the_registry_row_arrives_off_and_fits_its_column(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent, seed_components)
        entry = next(c for c in DEFAULT_COMPONENTS
                     if c["key"] == "telegram_eye")
        self.assertLessEqual(len(entry["description"]), 300)
        self.assertEqual(entry["category"], "system")
        self.assertNotIn("is_enabled", entry)
        seed_components()
        self.assertFalse(
            PlatformComponent.objects.get(key="telegram_eye").is_enabled)

    def test_the_beat_entry_and_the_two_routes(self):
        from celery.app.routes import MapRoute
        from config.celery import app
        entry = app.conf.beat_schedule["poll-telegram-eye"]
        self.assertEqual(entry["task"], "bot_program.tasks.poll_telegram_eye")
        self.assertEqual(entry["schedule"], 15.0)
        route = MapRoute(app.conf.task_routes)
        self.assertEqual(
            (route("bot_program.tasks.poll_telegram_eye") or {}).get("queue"),
            "fast")
        self.assertEqual(
            (route("bot_program.tasks.answer_telegram_question") or {})
            .get("queue"), "ai")

    def test_the_dormant_reader_stays_unscheduled_and_says_why(self):
        from alerts.channels import telegram_alert
        from config.celery import app
        tasks = {e.get("task") for e in app.conf.beat_schedule.values()}
        self.assertNotIn("alerts.tasks.check_telegram_commands", tasks)
        self.assertIn("bot_program/telegram_eye.py", telegram_alert.__doc__)
        self.assertIn("must never be scheduled", telegram_alert.__doc__)

    def test_the_help_names_the_privacy_setting_verbatim(self):
        self.assertEqual(
            eye.PRIVACY_LINE,
            "/q <question> always works; for bare quotes, turn the bot's "
            "Group Privacy off at @BotFather (Bot Settings → Group Privacy → "
            "Turn off), then remove and re-add the bot to the group.")
        text = eye.build_help().text()
        self.assertIn(escape(eye.PRIVACY_LINE), text)
        self.assertIn("Replies are always in English.", text)
        self.assertIn("A quoted question sent as a reply to a Sauron message "
                      "works too.", text)
