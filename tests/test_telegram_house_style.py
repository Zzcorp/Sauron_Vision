"""Every Telegram message in the house style (2026-09-26).

The operator, 2026-09-26: "je veux message en anglais toujours, et un
style irréprochable", then "vous n'avez update le styling et le formatage
de chacun des alertes et msgs?". Only the bot's fills, the Eye's replies
and the digest spoke the house style (HTML parse mode, every field
escaped, one leading emoji, a bold title, one fact per line, a refusal
logged with Telegram's own words). The signal dispatch, the price alert,
the scheduled digest, the newsletter, the news alert and the strategy
proposal posted legacy Markdown, most without reading the answer; the
price alert and the scheduled digest put the user's chat id in the bold
title and went to the platform chat. Every notifier but the fills handed
a bare title and body.

Pinned here, with requests.post patched (no real HTTP):
  * the one per-chat sender: HTML, escaped, no preview, 10 s, a refusal
    and a transport error logged at WARNING, never raises, cut to fit;
  * each path posts parse_mode HTML with a title and fields carrying <, &
    and an underscore, escaped, never Markdown;
  * the price alert and the scheduled digest reach the USER's chat, and
    the chat id is nowhere in the text; a scheduled run posts one digest
    per chat; a price alert that cannot be built is logged;
  * a signal reaches a chat two users share once, before any email, and
    a walk that fails half way still posts to the chats it had gathered;
  * a message cut to fit keeps all that fits;
  * every notifier sends its mark and at least one line; the
    notifications sender is cut to fit and never logs the bot token;
  * counts read as English plurals, Markdown emphasis comes off;
  * nothing French in any text sent, wherever the word stands.

Run with:  python manage.py test tests.test_telegram_house_style
"""
import html
import os
import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

TOKEN = "123456:house-style-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999",
       "DOMAIN": ""}
#: Words and letters that cannot be English.
FRENCH = (" le ", " la ", " les ", " des ", " du ", " une ", " est ",
          " pour ", " avec ", " sur ", " vous ", "é", "è", "ê", "à ", "ç",
          "ù")
PLATFORM_MARKS = "✕▲⊠⊟⟳◉⊕◯◌●▸◆◇"


def _ok():
    return MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _refused():
    return MagicMock(ok=False, status_code=400,
                     text="Bad Request: can't parse entities: can't find "
                          "end of the entity starting at byte offset 12")


def _payloads(post):
    return [c.kwargs["json"] for c in post.call_args_list]


def _user(name, *, chat="", staff=False, channel=None, **prefs):
    from alerts.models import UserNotificationPrefs
    u = User.objects.create_user(name, password="x", email=f"{name}@x.io",
                                 is_staff=staff)
    p, _ = UserNotificationPrefs.objects.get_or_create(user=u)
    p.telegram_chat_id = chat
    for k, v in prefs.items():
        setattr(p, k, v)
    p.save()
    if channel:
        from portfolio.trader_profile import TraderProfile
        tp, _ = TraderProfile.objects.get_or_create(user=u)
        tp.notify_channel = channel
        tp.save()
    return u


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _signal(inst, **kw):
    from signals.models import Signal
    fields = dict(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title=f"starter_stock_momentum matched on "
                                f"{inst.symbol}",
        description="d", rule_name="starter_stock_momentum", score=0.8234,
        sub_scores={}, price_at_signal=Decimal("421.37"),
        suggested_entry=Decimal("421.37000000"),
        suggested_stop=Decimal("410"), suggested_target=Decimal("440"),
        risk_reward_ratio=1.8456)
    fields.update(kw)
    return Signal.objects.create(**fields)


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def assertEnglish(self, text):
        # Every run of letters becomes one word between single spaces,
        # whatever sat before it (a line break, the <b> tag, the mark, an
        # escape), so a French word opening a line is seen too.
        low = " " + re.sub(r"[^a-zà-ÿ]+", " ",
                           html.unescape(text).lower()) + " "
        for word in FRENCH:
            self.assertNotIn(word, low, f"French {word!r} in {text!r}")

    def assertHouse(self, payload):
        """HTML, no preview, a bold first line, never Markdown."""
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        first = payload["text"].split("\n")[0]
        self.assertTrue(first.startswith("<b>") and first.endswith("</b>"),
                        first)
        self.assertNotIn("Markdown", str(payload))
        self.assertNotIn("*", payload["text"])
        self.assertEnglish(payload["text"])


# ── T1: the one per-chat sender ──────────────────────────────────────────

class SendToChatTests(_Base):
    def test_html_escaped_one_mark_bold_title_one_fact_per_line(self):
        from alerts.channels.telegram_alert import send_to_chat
        with patch("requests.post", return_value=_ok()) as post:
            ok = send_to_chat("-100", "A <b> & c_d", lines=["x < y", "rule_a"],
                              mark="\U0001F4C8")
        self.assertTrue(ok)
        post.assert_called_once()
        kw = post.call_args.kwargs
        self.assertEqual(kw["timeout"], 10)
        self.assertIn(f"/bot{TOKEN}/sendMessage", post.call_args.args[0])
        p = kw["json"]
        self.assertHouse(p)
        self.assertEqual(p["chat_id"], "-100")
        self.assertEqual(p["text"],
                         "<b>\U0001F4C8 A &lt;b&gt; &amp; c_d</b>\n"
                         "x &lt; y\nrule_a")

    def test_a_refusal_is_logged_with_telegrams_words_and_is_false(self):
        from alerts.channels.telegram_alert import send_to_chat
        with patch("requests.post", return_value=_refused()), \
                self.assertLogs("alerts.channels.telegram_alert",
                                "WARNING") as cm:
            ok = send_to_chat("-100", "Signal · MSFT · BUY", lines=["a_b"])
        self.assertFalse(ok)
        line = "\n".join(cm.output)
        self.assertIn("telegram refused (400)", line)
        self.assertIn("can't parse entities", line)

    def test_a_transport_error_is_logged_without_the_token(self):
        import requests
        from alerts.channels.telegram_alert import send_to_chat
        err = requests.ConnectionError(
            f"HTTPSConnectionPool(host='api.telegram.org'): Max retries "
            f"exceeded with url: /bot{TOKEN}/sendMessage")
        with patch("requests.post", side_effect=err), \
                self.assertLogs("alerts.channels.telegram_alert",
                                "WARNING") as cm:
            ok = send_to_chat("-100", "t", "b")
        self.assertFalse(ok)
        self.assertNotIn(TOKEN, "\n".join(cm.output))
        self.assertIn("telegram send failed", "\n".join(cm.output))

    def test_no_token_or_no_chat_posts_nothing(self):
        from alerts.channels.telegram_alert import send_to_chat
        with patch("requests.post") as post:
            self.assertFalse(send_to_chat("", "t", "b"))
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
                self.assertFalse(send_to_chat("-100", "t", "b"))
        post.assert_not_called()

    def test_a_long_message_is_cut_under_the_limit_and_says_so(self):
        from alerts.channels.telegram_alert import (CONTINUED,
                                                    TELEGRAM_MAX_CHARS,
                                                    fit_text)

        def units(s):
            return len(s.encode("utf-16-le")) // 2

        many = fit_text("Many", lines=[f"line {i} & more_words " * 3
                                       for i in range(400)],
                        mark="\U0001F4F0")
        self.assertLessEqual(units(many), TELEGRAM_MAX_CHARS)
        self.assertTrue(many.endswith(CONTINUED), many[-60:])
        self.assertIn("line 0 &amp; more_words", many)
        body = fit_text("Body", "&" * 10000)
        self.assertLessEqual(units(body), TELEGRAM_MAX_CHARS)
        self.assertTrue(body.endswith(CONTINUED))
        # the cut lands on the words, never inside an escape
        self.assertNotRegex(body, r"&(?!amp;)")
        one = fit_text("One", lines=["<" * 9000])
        self.assertLessEqual(units(one), TELEGRAM_MAX_CHARS)
        self.assertTrue(one.endswith(CONTINUED))
        # ...and it keeps all that fits: one more plain character would
        # not ("&" renders as five, "<" as four, an emoji counts two)
        for text, step in ((body, 5), (one, 4),
                           (fit_text("A <b> & c_d", "&" * 5000), 5),
                           (fit_text("Emoji", lines=["\U0001F600" * 3000]),
                            2)):
            self.assertGreater(units(text), TELEGRAM_MAX_CHARS - step,
                               text[-40:])
            self.assertTrue(text.endswith(CONTINUED))

    def test_send_telegram_keeps_its_signature_and_never_raises(self):
        from alerts.channels.telegram_alert import send_telegram
        with patch("requests.post", return_value=_ok()) as post:
            self.assertTrue(send_telegram("Strategy_x <approved>", "a & b"))
        p = post.call_args.kwargs["json"]
        self.assertHouse(p)
        self.assertEqual(p["chat_id"], "-100999")
        self.assertEqual(p["text"],
                         "<b>Strategy_x &lt;approved&gt;</b>\n\na &amp; b")
        with patch("requests.post", return_value=_refused()), \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            self.assertFalse(send_telegram("t", "b"))
        with patch("requests.post", side_effect=OSError("down")), \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            self.assertFalse(send_telegram("t", "b"))

    def test_send_telegram_unconfigured_is_false_and_posts_nothing(self):
        from alerts.channels.telegram_alert import send_telegram
        with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": ""}), \
                patch("requests.post") as post, \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            self.assertFalse(send_telegram("t", "b"))
        post.assert_not_called()

    def test_the_page_is_a_link_only_when_the_host_is_named(self):
        from alerts.channels.telegram_alert import page_line
        self.assertEqual(page_line("/instruments/MSFT/"),
                         "Page: /instruments/MSFT/ on the platform")
        with patch.dict(os.environ, {"DOMAIN": "sauron.invalid"}):
            self.assertEqual(page_line("/instruments/MSFT/"),
                             "Page: https://sauron.invalid/instruments/MSFT/")
        with patch.dict(os.environ, {"DOMAIN": "sauron.example.com"}):
            self.assertIn("on the platform", page_line("/signals/"))
        self.assertEqual(page_line(""), "")


# ── T2: signals ──────────────────────────────────────────────────────────

class SignalDispatchTests(_Base):
    def setUp(self):
        super().setUp()
        self.inst = _instrument("MSFT")

    def test_one_house_message_per_signal(self):
        from alerts.dispatch import dispatch_signal_alert
        from django.urls import reverse
        _user("sig_a", chat="-5337454557", receive_signals=True)
        sig = _signal(self.inst, rule_name="rule_a<b>&c")
        with patch("requests.post", return_value=_ok()) as post:
            out = dispatch_signal_alert(sig)
        self.assertEqual(out, {"chats": 1, "sent": 1, "held": 0,
                               "refused": 0})
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["chat_id"], "-5337454557")
        self.assertEqual(p["text"].split("\n"), [
            "<b>\U0001F4C8 Signal · MSFT · BUY</b>",
            "Score: 0.82",
            "Rule: rule_a&lt;b&gt;&amp;c",
            "Entry 421.37 · stop 410.00 · target 440.00",
            "Reward to risk: 1.85",
            "Urgency: medium",
            f"Page: {reverse('instrument_detail', args=['MSFT'])} "
            f"on the platform"])

    def test_the_page_is_a_link_when_the_host_is_named(self):
        from alerts.dispatch import signal_telegram
        with patch.dict(os.environ, {"DOMAIN": "sauron.invalid"}):
            _, lines, _ = signal_telegram(_signal(self.inst))
        self.assertEqual(lines[-1],
                         "Page: https://sauron.invalid/instruments/MSFT/")

    def test_a_sell_a_forex_price_and_missing_levels(self):
        from alerts.dispatch import signal_telegram
        fx = _instrument("USDJPY", "forex")
        title, lines, mark = signal_telegram(_signal(
            fx, direction="bearish", suggested_entry=Decimal("148.325"),
            suggested_stop=None, suggested_target=None,
            risk_reward_ratio=None, rule_name=""))
        self.assertEqual(title, "Signal · USDJPY · SELL")
        self.assertEqual(mark, "\U0001F4C9")
        self.assertIn("Entry 148.325", lines)
        self.assertFalse(any(ln.startswith("Rule") or "Reward" in ln
                             for ln in lines))

    def test_a_chat_shared_by_two_users_receives_the_signal_once(self):
        from alerts.dispatch import dispatch_signal_alert
        _user("share_a", chat="-5337454557", receive_signals=True)
        _user("share_b", chat=" -5337454557 ", receive_signals=True)
        _user("own_c", chat="42", receive_signals=True)
        with patch("requests.post", return_value=_ok()) as post:
            out = dispatch_signal_alert(_signal(self.inst))
        chats = sorted(p["chat_id"] for p in _payloads(post))
        self.assertEqual(chats, ["-5337454557", "42"])
        self.assertEqual(out["sent"], 2)

    def test_rules_email_and_whatsapp_are_unchanged(self):
        from alerts.dispatch import dispatch_signal_alert
        from alerts.models import AlertRule
        u = _user("rule_u", chat="77")
        AlertRule.objects.create(user=u, name="all", min_score=0.5,
                                 notify_telegram=True, notify_email=True,
                                 notify_whatsapp=True)
        quiet = _user("rule_q", chat="78")
        AlertRule.objects.create(user=quiet, name="high", min_score=0.95,
                                 notify_telegram=True)
        with patch("requests.post", return_value=_ok()) as post, \
                patch("alerts.channels.email_alert.send_email_to_user") as em, \
                patch("alerts.channels.whatsapp_alert."
                      "send_whatsapp_to_user") as wa:
            dispatch_signal_alert(_signal(self.inst))
        self.assertEqual([p["chat_id"] for p in _payloads(post)], ["77"])
        em.assert_called_once()
        self.assertEqual(em.call_args.args[1], "Signal: MSFT BULLISH")
        self.assertIn("Score: 0.82", em.call_args.args[2])
        wa.assert_called_once()
        self.assertEqual(wa.call_args.args[1], "Signal: MSFT BULLISH")

    def test_receive_signals_off_sends_nothing(self):
        from alerts.dispatch import dispatch_signal_alert
        _user("off_u", chat="-5337454557", receive_signals=False)
        with patch("requests.post") as post:
            out = dispatch_signal_alert(_signal(self.inst))
        post.assert_not_called()
        self.assertEqual(out["chats"], 0)

    def test_a_refused_signal_is_logged_and_counted_never_raised(self):
        from alerts.dispatch import dispatch_signal_alert
        _user("ref_u", chat="-5337454557", receive_signals=True)
        with patch("requests.post", return_value=_refused()), \
                self.assertLogs("alerts.channels.telegram_alert",
                                "WARNING") as cm:
            out = dispatch_signal_alert(_signal(self.inst))
        self.assertEqual(out["refused"], 1)
        self.assertIn("can't parse entities", "\n".join(cm.output))

    def test_telegram_goes_before_the_emails(self):
        from alerts.dispatch import dispatch_signal_alert
        order = []
        _user("order_u", chat="-21", receive_signals=True,
              email_notifications=True)

        def post(*args, **kwargs):
            order.append("telegram")
            return _ok()

        with patch("requests.post", side_effect=post), \
                patch("alerts.channels.email_alert.send_email_to_user",
                      side_effect=lambda *a, **k: order.append("email")):
            dispatch_signal_alert(_signal(self.inst))
        self.assertEqual(order, ["telegram", "email"])

    def test_a_walk_that_fails_half_way_still_posts_what_it_gathered(self):
        from alerts.dispatch import dispatch_signal_alert
        from alerts.models import AlertRule
        _user("walk_a", chat="-11", receive_signals=True)
        b = _user("walk_b", chat="-12")
        AlertRule.objects.create(user=b, name="all", min_score=0.1,
                                 notify_telegram=True)
        with patch("requests.post", return_value=_ok()) as post, \
                patch("alerts.dispatch._rule_matches",
                      side_effect=RuntimeError("a broken rule")), \
                self.assertRaises(RuntimeError):
            dispatch_signal_alert(_signal(self.inst))
        self.assertEqual([p["chat_id"] for p in _payloads(post)], ["-11"])


# ── T3: the price alert and the scheduled digest, to the USER's chat ─────

class UserChatTests(_Base):
    def test_the_price_alert_reaches_the_users_chat(self):
        from alerts.models import Notification, PriceAlert, check_price_alerts
        from market_data.models import LiveQuote
        u = _user("px_u", chat="-4242")
        inst = _instrument("AAPL")
        LiveQuote.objects.create(instrument=inst, last=Decimal("151"),
                                 source="test")
        PriceAlert.objects.create(user=u, instrument=inst, condition="above",
                                  target_price=Decimal("150"),
                                  note="note <x> & y_z", notify_telegram=True)
        with patch("requests.post", return_value=_ok()) as post:
            self.assertEqual(check_price_alerts(), 1)
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["chat_id"], "-4242")
        self.assertNotIn("-4242", p["text"])
        self.assertNotIn("-100999", p["text"])
        lines = p["text"].split("\n")
        self.assertEqual(lines[0],
                         "<b>\U0001F514 Price alert · AAPL above 150.00</b>")
        self.assertIn("Price now: 151.00", lines)
        self.assertIn("Note: note &lt;x&gt; &amp; y_z", lines)
        # the bell row is unchanged
        self.assertTrue(Notification.objects.filter(
            user=u, title__startswith="Price Alert: AAPL").exists())

    def test_the_scheduled_digest_reaches_the_users_chat(self):
        from alerts.models import Notification
        from alerts.scheduled_digests import send_digest
        u = _user("dg_u", chat="-4343")
        digest = {"type": "morning_brief", "sections": {
            "signals": [{"symbol": "MSFT", "type": "a<b & c_d",
                         "direction": "bullish"}],
            "portfolio": {"value": 1234.5, "cash": 100.0,
                          "open_positions": 2, "top_movers": []},
            "news": []}}
        with patch("requests.post", return_value=_ok()) as post:
            send_digest(digest, user=u)
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["chat_id"], "-4343")
        self.assertNotIn("-4343", p["text"])
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], "<b>\u2600\uFE0F Morning Market Brief</b>")
        self.assertIn("<b>Active signals</b>", lines)
        self.assertIn("• Symbol: MSFT, Type: a&lt;b &amp; c_d, "
                      "Direction: bullish", lines)
        self.assertIn("• Value: 1,234.50", lines)
        self.assertIn("• Top movers: 0", lines)
        self.assertIn("• Nothing to report", lines)
        n = Notification.objects.get(user=u)
        self.assertNotIn("**", n.body)

    def test_a_shared_chat_gets_one_digest_per_run(self):
        from alerts.tasks import send_eod_digest, send_morning_digest
        _user("run_a", chat="-5337454557")
        _user("run_b", chat=" -5337454557 ")
        _user("run_c", chat="-99")
        for task, kind in ((send_morning_digest, "morning_brief"),
                           (send_eod_digest, "end_of_day")):
            digest = {"type": kind, "sections": {"news": []}}
            with self.subTest(kind), \
                    patch("requests.post", return_value=_ok()) as post, \
                    patch("alerts.scheduled_digests.generate_morning_digest",
                          return_value=digest), \
                    patch("alerts.scheduled_digests.generate_eod_digest",
                          return_value=digest):
                task.__wrapped__.__wrapped__()  # past the component gate
                self.assertEqual(sorted(p["chat_id"] for p in _payloads(post)),
                                 ["-5337454557", "-99"])

    def test_a_price_alert_that_cannot_be_built_is_said(self):
        from alerts.models import PriceAlert, check_price_alerts
        from market_data.models import LiveQuote
        u = _user("px_bad", chat="-4545")
        inst = _instrument("AAPL")
        LiveQuote.objects.create(instrument=inst, last=Decimal("151"),
                                 source="test")
        PriceAlert.objects.create(user=u, instrument=inst, condition="above",
                                  target_price=Decimal("150"),
                                  notify_telegram=True)
        with patch("alerts.models.price_alert_telegram",
                   side_effect=ValueError("no level")), \
                patch("requests.post") as post, \
                self.assertLogs("alerts.models", "WARNING") as cm:
            self.assertEqual(check_price_alerts(), 1)
        post.assert_not_called()
        self.assertIn("the Telegram message was not sent: no level",
                      "\n".join(cm.output))


# ── T4: the newsletter, the news alert, the strategy proposal ────────────

class PlatformChatTests(_Base):
    def test_the_newsletter_is_lines_not_markdown(self):
        from alerts.models import Newsletter
        from alerts.newsletter_service import send_newsletter
        nl = Newsletter.objects.create(
            title="Weekly Market Report", status="approved",
            send_email=False, send_telegram=True,
            content_markdown="# Market Overview\n\n**Risk** on, rates_up "
                             "& <volatile>\n- item_one *now*\n* item two\n"
                             "Read [the note](https://sauron.invalid/n/1) "
                             "_today_\n---\n")
        with patch("requests.post", return_value=_ok()) as post:
            out = send_newsletter(nl)
        self.assertEqual(out["recipients"], 1)
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["chat_id"], "-100999")
        self.assertEqual(p["text"].split("\n"), [
            "<b>\U0001F4F0 Sauron Vision · Weekly Market Report</b>",
            "<b>Market Overview</b>",
            "Risk on, rates_up &amp; &lt;volatile&gt;",
            "• item_one now", "• item two",
            "Read the note (https://sauron.invalid/n/1) today"])

    def test_markdown_emphasis_comes_off_but_never_inside_a_word(self):
        from alerts.channels.telegram_alert import markdown_lines
        self.assertEqual(markdown_lines(
            "5 * 3 = 15, a*b*c, golden_cross_up\n"
            "## *Rates* _now_\n"
            "![chart](https://sauron.invalid/c.png) [https://x.io](https://x.io)"),
            ["5 * 3 = 15, a*b*c, golden_cross_up", "Rates now",
             "chart (https://sauron.invalid/c.png) https://x.io"])

    def test_a_refused_newsletter_is_not_counted_and_does_not_raise(self):
        from alerts.models import Newsletter
        from alerts.newsletter_service import send_newsletter
        nl = Newsletter.objects.create(title="W", status="approved",
                                       send_email=False,
                                       content_markdown="x")
        with patch("requests.post", return_value=_refused()), \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            out = send_newsletter(nl)
        self.assertEqual(out["recipients"], 0)

    def test_the_news_alert(self):
        from alerts.dispatch import dispatch_news_alert
        article = SimpleNamespace(title="Fed <cuts> & rates_now",
                                  source="Reuters", ai_urgency="critical",
                                  pk=None)
        with patch("requests.post", return_value=_ok()) as post:
            self.assertTrue(dispatch_news_alert(article))
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["text"].split("\n"), [
            "<b>\U0001F6A8 Breaking news</b>",
            "Fed &lt;cuts&gt; &amp; rates_now",
            "Source: Reuters", "Urgency: critical"])

    def test_the_strategy_proposal_keeps_its_approve_and_reject_lines(self):
        from alerts.channels.telegram_alert import send_strategy_proposal
        strategy = SimpleNamespace(
            name="Mean_rev <x> & y", time_horizon="swing",
            max_portfolio_allocation_pct=5, description="Buys dips_on "
            "strength.", id=12)
        with patch("requests.post", return_value=_ok()) as post:
            self.assertTrue(send_strategy_proposal(strategy))
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["text"].split("\n"), [
            "<b>\U0001F4DD New strategy proposal · Mean_rev &lt;x&gt; "
            "&amp; y</b>",
            "Horizon: swing", "Maximum allocation: 5%",
            "Buys dips_on strength.",
            "Reply /approve 12 to approve it",
            "Reply /reject 12 to reject it"])

    def test_the_dormant_readers_replies_render_in_the_house_style(self):
        from alerts.channels import telegram_alert
        _signal(_instrument("MSFT"))
        updates = MagicMock(ok=True)
        updates.json.return_value = {"result": [
            {"message": {"text": "/signals"}}]}
        with patch.object(telegram_alert, "BOT_TOKEN", TOKEN), \
                patch("requests.get", return_value=updates), \
                patch("requests.post", return_value=_ok()) as post:
            self.assertEqual(telegram_alert.process_commands(), 1)
        p = _payloads(post)[0]
        self.assertHouse(p)
        self.assertEqual(p["text"].split("\n")[0], "<b>Active signals</b>")
        self.assertIn("MSFT bullish — 0.82", p["text"])


# ── T5: every notifier, its mark and its lines ───────────────────────────

class NotifierTests(_Base):
    def setUp(self):
        super().setUp()
        self.user = _user("tg_ops", chat="123", staff=True,
                          channel="telegram", receive_bot_alerts=True,
                          receive_strategist_briefing=True)

    def _briefing(self):
        return SimpleNamespace(
            pk=5, posture="defensive", created_at=timezone.now(),
            outlook_md="**Risk** is <rising> & rates_up.",
            posture_rationale="breadth_thin & credit <wide>",
            ideas=[{"summary": "fade USD_strength"}],
            watchlist=[{"ref": "SPX"}], cost_usd=0.0123, tokens_in=10,
            tokens_out=5)

    def _cases(self):
        from bot_program import notifications as N
        u = self.user
        return [
            ("orchestrator_reject", lambda: N.notify_orchestrator_reject(
                u, asset_class="stock", symbol="NVDA", side="BUY",
                reason="theme cap <3> & more_x")),
            ("manual_fill_open", lambda: N.notify_manual_fill_open(
                u, asset_class="crypto", symbol="BTCUSD", side="BUY",
                qty=Decimal("0.5"), entry_price=Decimal("60000"),
                trade_id=7)),
            ("manual_fill_queued", lambda: N.notify_manual_fill_open(
                u, asset_class="stock", symbol="AAPL", side="BUY",
                qty=Decimal("1"), entry_price=None, working=True, live=True)),
            ("manual_lane_live", lambda: N.notify_manual_lane_mode(
                u, asset_class="stock", mode="live", capital=2000)),
            ("manual_lane_paper", lambda: N.notify_manual_lane_mode(
                u, asset_class="stock", mode="paper")),
            ("manual_close_refused", lambda: N.notify_manual_close_refused(
                u, asset_class="stock", symbol="MSFT", trade_id=9)),
            ("drawdown_warning", lambda: N.notify_drawdown_warning(
                u, asset_class="stock", config_name="Stocks_main <1>",
                realized_pnl=-200.0, limit=Decimal("-100"))),
            ("protection_vanished", lambda: N.notify_protection_vanished(
                u, asset_class="stock", symbol="AAPL", side="BUY", qty=2,
                stop_loss=Decimal("210.5"), reason="stop_order <gone>",
                trade_id=3)),
            ("unclaimed_position", lambda: N.notify_unclaimed_position(
                u, symbols=["AAPL", "MSFT"], venue="IBKR")),
            ("track_record_decay", lambda: N.notify_track_record_decay(
                u, rule_name="golden_cross", asset_class="stock",
                recent_avg_r=-0.4, baseline_avg_r=0.6, recent_n=12,
                triggers=["avg_r_drop", "gone_negative"])),
            ("strategist_briefing",
             lambda: N.notify_strategist_briefing_to_all(self._briefing())),
            ("system_health", lambda: N.notify_staff(
                title="Brain failed 3 times", body="timeout_x <5s> & retry")),
            # a caller's ⚠ keeps a warning sign on Telegram
            ("staff_warning", lambda: N.notify_staff(
                title="⚠ AAPL: queued order cannot be withdrawn",
                body="order_id <77> & still working")),
            ("broker_unreachable", lambda: N.notify_broker_unreachable(
                u, label="ISA_CAPITAL", host="ibgateway", port=4003,
                misses=3, broker="ibkr")),
            ("evidence_chain_cold", lambda: N.notify_evidence_chain_cold(
                u, cold=["pipeline_promotion"],
                blockers=["pipeline_promotion is off."])),
        ]

    def test_every_notifier_sends_its_mark_and_at_least_one_line(self):
        from bot_program.notifications import NOTIFY_MARKS
        for key, call in self._cases():
            with self.subTest(key), \
                    patch("requests.post", return_value=_ok()) as post:
                call()
                self.assertEqual(post.call_count, 1, key)
                p = _payloads(post)[0]
                self.assertHouse(p)
                self.assertEqual(p["chat_id"], "123")
                lines = p["text"].split("\n")
                self.assertTrue(lines[0].startswith(
                    f"<b>{NOTIFY_MARKS[key]} "), lines[0])
                head = lines[0][len(f"<b>{NOTIFY_MARKS[key]} "):]
                self.assertFalse(set(head[:1]) & set(PLATFORM_MARKS + "⚠"),
                                 lines[0])
                self.assertGreaterEqual(
                    len([ln for ln in lines[1:] if ln.strip()]), 1, key)
                self.assertNotIn("{'label'", p["text"])

    def test_the_bell_and_telegram_share_the_lines(self):
        from alerts.models import Notification
        from bot_program.notifications import notify_drawdown_warning
        with patch("requests.post", return_value=_ok()) as post:
            notify_drawdown_warning(self.user, asset_class="stock",
                                    config_name="ST", realized_pnl=-200.0,
                                    limit=-100.0)
        n = Notification.objects.get(user=self.user)
        self.assertTrue(n.title.startswith("▲ Drawdown limit reached"))
        text = _payloads(post)[0]["text"]
        self.assertEqual([html.unescape(ln) for ln in text.split("\n")[1:]],
                         n.data["items"])
        self.assertEqual(n.data["items"], [
            "Bot: ST", "Asset class: STOCK", "Realized 24h P&L: -200.00",
            "Limit: -100.00", "New entries halted"])

    def test_the_briefing_reads_label_and_detail_never_a_dict(self):
        from bot_program.notifications import notify_strategist_briefing_to_all
        with patch("requests.post", return_value=_ok()) as post:
            notify_strategist_briefing_to_all(self._briefing())
        text = _payloads(post)[0]["text"]
        self.assertIn("Posture: breadth_thin &amp; credit &lt;wide&gt;",
                      text)
        self.assertIn("Idea 1: fade USD_strength", text)
        self.assertIn("Watchlist: 1 item · SPX", text)

    def test_counts_read_as_english_plurals(self):
        from alerts.models import Notification
        from bot_program.notifications import notify_unclaimed_position
        with patch("requests.post", return_value=_ok()) as post:
            notify_unclaimed_position(self.user, symbols=["AAPL"],
                                      venue="IBKR")
            notify_unclaimed_position(self.user, symbols=["AAPL", "MSFT"],
                                      venue="IBKR")
        heads = [p["text"].split("\n")[0] for p in _payloads(post)]
        self.assertEqual(heads, [
            "<b>❓ 1 position at IBKR that no row claims</b>",
            "<b>❓ 2 positions at IBKR that no row claims</b>"])
        self.assertFalse(Notification.objects.filter(
            title__contains="(s)").exists())

    def test_the_notifications_sender_cuts_to_fit_and_never_logs_the_token(
            self):
        import requests
        from bot_program.notifications import _send_telegram
        err = requests.ConnectionError(
            f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
        with patch("requests.post", side_effect=err), \
                self.assertLogs("bot_program.notifications", "WARNING") as cm:
            self.assertFalse(_send_telegram(self.user, "t", "b"))
        self.assertNotIn(TOKEN, "\n".join(cm.output))
        self.assertIn("/bot<token>/", "\n".join(cm.output))
        with patch("requests.post", return_value=_ok()) as post:
            self.assertTrue(_send_telegram(
                self.user, "Long", "",
                lines=[f"line {i} & more_words" for i in range(1000)]))
        kw = post.call_args.kwargs
        self.assertEqual(kw["timeout"], 5)
        text = kw["json"]["text"]
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertTrue(text.endswith("… (continued on the platform)"))

    def test_the_bell_card_draws_a_string_item_as_one_line(self):
        from pathlib import Path

        from django.conf import settings
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-notif-card.js").read_text(encoding="utf-8")
        self.assertIn('if (typeof it === "string")', js)
        self.assertIn("nf-pop-item--line", js)
        self.assertIn("linked ? \"click a line to open it\"", js)


class EnglishOnlyTests(_Base):
    def test_nothing_french_in_any_text_sent(self):
        """Every path once, every text read for words that cannot be
        English."""
        from alerts.dispatch import dispatch_news_alert, dispatch_signal_alert
        from alerts.scheduled_digests import send_digest
        from bot_program import notifications as N
        u = _user("en_u", chat="321", staff=True, channel="telegram",
                  receive_signals=True)
        inst = _instrument("MSFT")
        with patch("requests.post", return_value=_ok()) as post:
            dispatch_signal_alert(_signal(inst))
            dispatch_news_alert(SimpleNamespace(
                title="Rates", source="Reuters", ai_urgency="high", pk=None))
            send_digest({"type": "end_of_day", "sections": {
                "daily_pnl": {"pnl": 1.5}}}, user=u)
            N.notify_drawdown_warning(u, asset_class="stock",
                                      config_name="ST", realized_pnl=-2,
                                      limit=-1)
            N.notify_unclaimed_position(u, symbols=["AAPL"], venue="IBKR")
        texts = [p["text"] for p in _payloads(post)]
        self.assertEqual(len(texts), 5)
        for text in texts:
            self.assertEnglish(text)

    def test_the_check_sees_a_french_word_wherever_it_stands(self):
        for text in ("<b>❓ Title</b>\nLes positions restent ouvertes",
                     "<b>\U0001F4C8 La position</b>",
                     "Rule: x\nDes ordres &amp; une note",
                     "<b>Title</b>\n\nDu calme"):
            with self.subTest(text), self.assertRaises(AssertionError):
                self.assertEnglish(text)
        self.assertEnglish("<b>\U0001F4C8 Signal · MSFT · BUY</b>\n"
                           "Rule: golden_cross\nLast 12 trades")
