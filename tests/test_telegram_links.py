"""The Telegram buttons that prepare an act (2026-10-24).

The operator, 2026-10-24 (option A): under each Sauron signal a URL
button "Prepare ticket" that opens the platform's TAKE TRADE ticket
filled for that signal; under each alert about one of his positions a
URL button "Close position" that opens the platform's close dialog for
it. He reads, types his trading PIN on the platform, and only then does
an order go. Nothing is bought or closed from Telegram, real or paper.

Pinned here, with requests.post patched (no real HTTP):
  * the button contract: one pair is the old markup exactly; two pairs
    one row of two URL buttons; a third is dropped; an invalid pair costs
    only its own button; never a callback; a refused button costs the
    buttons, never the message, and each page survives as a line;
  * the senders: a signal the platform could take carries Prepare ticket
    (never a neutral one, a class the lane does not trade, an instrument
    off, a symbol with no page), the same in a chat two users share; an
    open position's alerts carry Close position, a closed or queued one
    never; a portfolio-book review never; notify_staff only when asked;
    Morgul and the alarm bot only for ONE G2 or G5 finding about an open
    row;
  * a link carries an id and nothing else: no price, no side, no query;
  * the pages: a GET writes nothing, places nothing, reads no PIN and
    calls no execute; another user's trade and a missing one read the
    same neutral note; a signal no longer active opens the instrument's
    ticket with a note; a closed trade says so and opens nothing;
  * the login comes back to the link: the Wall carries it, both login
    steps return to it, the login mark the ACT doors read is set, and an
    address off the site is never followed (the open redirect closed).

Run with:  python manage.py test tests.test_telegram_links
"""
import html
import inspect
import json
import os
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

HOST = "sauron.invalid"
TOKEN = "123456:telegram-links-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999",
       "DOMAIN": HOST}
UTC = dt_tz.utc
#: What a link may be: a page by name, or an id and nothing else.
LINK_PATH = re.compile(
    r"^/(instruments/[A-Z]+|signals/\d+/ticket|forensics/\d+"
    r"|positions/\d+/close-dialog|positions)/$")


def _ok():
    return MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _refused():
    return MagicMock(ok=False, status_code=400,
                     text="Bad Request: BUTTON_URL_INVALID")


def _payloads(post):
    return [c.kwargs["json"] for c in post.call_args_list]


def _row(*pairs):
    return {"inline_keyboard": [[{"text": t, "url": f"https://{HOST}{p}"}
                                 for t, p in pairs]]}


def _paths(markup):
    """Every button's path, after the host."""
    return [b["url"][len(f"https://{HOST}"):]
            for row in (markup or {}).get("inline_keyboard", [])
            for b in row]


def _user(name, chat="123", *, staff=True, pin=None):
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    u = User.objects.create_user(name, password="pw-" + name,
                                 email=f"{name}@x.io", is_staff=staff)
    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=u)
    prefs.telegram_chat_id = chat
    prefs.receive_bot_alerts = True
    prefs.email_notifications = False
    prefs.save()
    tp, _ = TraderProfile.objects.get_or_create(user=u)
    tp.notify_channel = "telegram"
    if pin:
        tp.set_pin(pin)
    tp.save()
    return u


def _cfg(user, asset_class="stock", name="Stocks main", **kw):
    from bot_program.models import AssetBotConfig
    kw.setdefault("mode", "paper")
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, symbols=[],
        capital=Decimal("10000"), base_currency="USD", enabled=True, **kw)


def _trade(cfg, pk=None, **kw):
    from bot_program.models import AssetBotTrade
    fields = dict(symbol="AAPL", side="BUY", qty=Decimal("2"),
                  entry_price=Decimal("210"), stop_loss=Decimal("200.5"),
                  take_profit=Decimal("230"), paper=True,
                  rule_name="golden_cross", status="OPEN")
    fields.update(kw)
    if pk is not None:
        fields["id"] = pk
    return AssetBotTrade.objects.create(config=cfg,
                                        asset_class=cfg.asset_class,
                                        **fields)


def _instrument(symbol, asset_class="stock", active=True):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": active})
    return inst


def _signal(inst, **kw):
    from signals.models import Signal
    fields = dict(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title=f"rule matched on {inst.symbol}",
        description="d", rule_name="starter_stock_momentum", score=0.82,
        sub_scores={}, price_at_signal=Decimal("421.37"),
        suggested_entry=Decimal("421.37"), suggested_stop=Decimal("410"),
        suggested_target=Decimal("440"), risk_reward_ratio=1.85)
    fields.update(kw)
    return Signal.objects.create(**fields)


class _Env(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)


# ── T1: the button contract ──────────────────────────────────────────────

class TheButtonContractTests(SimpleTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"DOMAIN": HOST})
        env.start()
        self.addCleanup(env.stop)

    def test_one_pair_is_the_old_markup_exactly(self):
        from alerts.channels.telegram_alert import button_markup
        self.assertEqual(button_markup(("Open positions", "/positions/")),
                         {"inline_keyboard": [[{
                             "text": "Open positions",
                             "url": f"https://{HOST}/positions/"}]]})
        # a list spelling of the one pair is the same pair
        self.assertEqual(button_markup(["Open positions", "/positions/"]),
                         button_markup(("Open positions", "/positions/")))

    def test_two_pairs_are_one_row_of_two_url_buttons(self):
        from alerts.channels.telegram_alert import button_markup
        markup = button_markup([("Open position", "/forensics/7/"),
                                ("Close position",
                                 "/positions/7/close-dialog/")])
        self.assertEqual(markup, _row(("Open position", "/forensics/7/"),
                                      ("Close position",
                                       "/positions/7/close-dialog/")))
        self.assertEqual(len(markup["inline_keyboard"]), 1)

    def test_a_third_pair_is_dropped_and_a_repeated_page_too(self):
        from alerts.channels.telegram_alert import MAX_BUTTONS, button_markup
        self.assertEqual(MAX_BUTTONS, 2)
        markup = button_markup([("A", "/a/"), ("B", "/b/"), ("C", "/c/")])
        self.assertEqual(_paths(markup), ["/a/", "/b/"])
        markup = button_markup([("A", "/a/"), ("Again", "/a/"),
                                ("B", "/b/")])
        self.assertEqual(_paths(markup), ["/a/", "/b/"])

    def test_an_invalid_pair_costs_only_its_own_button(self):
        from alerts.channels.telegram_alert import button_markup
        for bad in (("", "/x/"), ("Evil", "https://evil.io/"),
                    ("Evil", "//evil.io/"), ("No path", ""), None,
                    "oops", ("only one",)):
            with self.subTest(bad=bad):
                self.assertEqual(
                    button_markup([bad, ("Open", "/positions/")]),
                    _row(("Open", "/positions/")))
        self.assertIsNone(button_markup([("", "/x/"),
                                         ("Evil", "https://evil.io/")]))
        self.assertIsNone(button_markup([]))
        self.assertIsNone(button_markup(None))

    def test_no_host_a_phone_can_open_means_no_button(self):
        from alerts.channels.telegram_alert import button_markup
        for domain in ("", "localhost:8000", "sauron.example.com"):
            with self.subTest(domain), \
                    patch.dict(os.environ, {"DOMAIN": domain}):
                self.assertIsNone(button_markup(
                    [("A", "/a/"), ("B", "/b/")]))

    def test_never_a_callback_button(self):
        from alerts.channels import telegram_alert
        from alerts.channels.telegram_alert import button_markup
        markup = button_markup([("A", "/a/"), ("B", "/b/")])
        self.assertNotIn("callback_data", json.dumps(markup))
        for b in markup["inline_keyboard"][0]:
            self.assertEqual(set(b), {"text", "url"})
        src = inspect.getsource(telegram_alert)
        self.assertNotIn("callback_data", src)
        self.assertIn("a message never acts from\n    Telegram",
                      inspect.getsource(telegram_alert.button_markup))

    def test_button_lines_say_each_page(self):
        from alerts.channels.telegram_alert import button_lines
        self.assertEqual(button_lines(("Open", "/positions/")),
                         [f"Page: https://{HOST}/positions/"])
        self.assertEqual(
            button_lines([("Open instrument", "/instruments/MSFT/"),
                          ("Prepare ticket", "/signals/4/ticket/")]),
            [f"Open instrument: https://{HOST}/instruments/MSFT/",
             f"Prepare ticket: https://{HOST}/signals/4/ticket/"])
        with patch.dict(os.environ, {"DOMAIN": ""}):
            self.assertEqual(button_lines(("Open", "/positions/")),
                             ["Page: /positions/ on the platform"])
        # one button that prepares an act says what it opens, by its own
        # label: never a bare "Page:" for the close dialog or the ticket
        close = ("Close position", "/positions/12/close-dialog/")
        self.assertEqual(button_lines(close), [
            f"Close position: https://{HOST}/positions/12/close-dialog/"])
        self.assertEqual(button_lines([close]), button_lines(close))
        self.assertEqual(button_lines(("Prepare ticket",
                                       "/signals/4/ticket/")),
                         [f"Prepare ticket: https://{HOST}/signals/4/ticket/"])
        with patch.dict(os.environ, {"DOMAIN": ""}):
            self.assertEqual(button_lines(close), [
                "Close position: /positions/12/close-dialog/ on the "
                "platform"])

    def test_the_fallback_carries_both_pages_as_lines(self):
        from alerts.channels.telegram_alert import message_parts
        pair = [("Open position", "/forensics/7/"),
                ("Close position", "/positions/7/close-dialog/")]
        text, markup, fallback = message_parts("T", lines=["a"],
                                               button=pair)
        self.assertEqual(text, "<b>T</b>\na")
        self.assertEqual(_paths(markup), ["/forensics/7/",
                                          "/positions/7/close-dialog/"])
        self.assertEqual(fallback, "\n".join([
            "<b>T</b>", "a",
            f"Open position: https://{HOST}/forensics/7/",
            f"Close position: https://{HOST}/positions/7/close-dialog/"]))
        # a body, not lines: the pages under the body
        _t, _m, fallback = message_parts("T", "the body", button=pair)
        self.assertTrue(fallback.endswith(
            f"the body\nOpen position: https://{HOST}/forensics/7/\n"
            f"Close position: https://{HOST}/positions/7/close-dialog/"),
            fallback)
        # the old one-button call: the old "Page:" line
        _t, _m, fallback = message_parts("T", lines=["a"],
                                         button=("Open", "/positions/"))
        self.assertEqual(fallback,
                         f"<b>T</b>\na\nPage: https://{HOST}/positions/")

    def test_a_refused_button_is_sent_again_once_with_the_pages_as_lines(
            self):
        from alerts.channels.telegram_alert import send_to_chat
        pair = [("Open position", "/forensics/7/"),
                ("Close position", "/positions/7/close-dialog/")]
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN}), \
                patch("requests.post",
                      side_effect=[_refused(), _ok()]) as post, \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            self.assertTrue(send_to_chat("-1", "T", lines=["a"],
                                         button=pair))
        first, second = _payloads(post)
        self.assertEqual(post.call_count, 2)
        self.assertIn("reply_markup", first)
        self.assertNotIn("reply_markup", second)
        self.assertEqual(second["text"].split("\n")[-2:], [
            f"Open position: https://{HOST}/forensics/7/",
            f"Close position: https://{HOST}/positions/7/close-dialog/"])


# ── T2: the signal's "Prepare ticket" ────────────────────────────────────

class TheSignalTicketButtonTests(_Env):
    def setUp(self):
        super().setUp()
        self.user = _user("sig_ops")

    def _sent(self, signal, domain=HOST):
        from alerts.dispatch import dispatch_signal_alert
        with patch.dict(os.environ, {"DOMAIN": domain}), \
                patch("requests.post", return_value=_ok()) as post:
            dispatch_signal_alert(signal)
        return _payloads(post)

    def test_an_active_bullish_stock_signal_carries_prepare_ticket(self):
        sig = _signal(_instrument("MSFT"))
        (p,) = self._sent(sig)
        self.assertEqual(p["reply_markup"], _row(
            ("Open instrument", "/instruments/MSFT/"),
            ("Prepare ticket", f"/signals/{sig.pk}/ticket/")))

    def test_a_link_carries_an_id_and_nothing_else(self):
        sig = _signal(_instrument("MSFT"), direction="bearish")
        (p,) = self._sent(sig)
        for path in _paths(p["reply_markup"]):
            with self.subTest(path):
                self.assertRegex(path, LINK_PATH)
                self.assertNotIn("?", path)
                self.assertNotIn("SELL", path.upper().replace(
                    "/SIGNALS/", ""))
                for price in ("421", "410", "440", "1.85"):
                    self.assertNotIn(price, path)

    def test_no_ticket_for_a_signal_the_platform_could_not_take(self):
        from alerts.dispatch import signal_extras
        cases = {
            "neutral": _signal(_instrument("MSFT"), direction="neutral"),
            "an index": _signal(_instrument("SPX", "index")),
            "an instrument off": _signal(_instrument("OFF", active=False)),
            "no page": _signal(_instrument("BTC/USD", "crypto")),
        }
        for why, sig in cases.items():
            with self.subTest(why):
                extras = signal_extras(sig)
                self.assertNotIn("buttons", extras)
                (p,) = self._sent(sig)
                for path in _paths(p["reply_markup"]):
                    self.assertNotIn("/ticket/", path)
                self.assertEqual(len(_paths(p["reply_markup"])), 1)

    def test_the_old_button_key_is_kept(self):
        from alerts.dispatch import signal_extras
        sig = _signal(_instrument("MSFT"))
        extras = signal_extras(sig)
        self.assertEqual(extras["button"],
                         ("Open instrument", "/instruments/MSFT/"))
        self.assertEqual(extras["buttons"], [
            ("Open instrument", "/instruments/MSFT/"),
            ("Prepare ticket", f"/signals/{sig.pk}/ticket/")])

    def test_a_chat_two_users_share_gets_one_message_one_markup(self):
        _user("sig_keeper", chat="123")
        sig = _signal(_instrument("MSFT"))
        sent = self._sent(sig)
        self.assertEqual(len(sent), 1)
        self.assertEqual(_paths(sent[0]["reply_markup"]), [
            "/instruments/MSFT/", f"/signals/{sig.pk}/ticket/"])

    def test_without_a_host_no_markup_and_the_page_line_as_before(self):
        sig = _signal(_instrument("MSFT"))
        (p,) = self._sent(sig, domain="")
        self.assertNotIn("reply_markup", p)
        self.assertTrue(p["text"].endswith(
            "Page: /instruments/MSFT/ on the platform"), p["text"])
        self.assertNotIn("ticket", p["text"])

    def test_a_refused_pair_keeps_both_pages_as_lines(self):
        from alerts.dispatch import dispatch_signal_alert
        sig = _signal(_instrument("MSFT"))
        with patch("requests.post",
                   side_effect=[_refused(), _ok()]) as post, \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            dispatch_signal_alert(sig)
        first, second = _payloads(post)
        self.assertNotIn("reply_markup", second)
        self.assertTrue(second["text"].endswith(
            f"Open instrument: https://{HOST}/instruments/MSFT/\n"
            f"Prepare ticket: https://{HOST}/signals/{sig.pk}/ticket/"),
            second["text"])


# ── T3: the position alerts' "Close position" ────────────────────────────

class ThePositionCloseButtonTests(_Env):
    def setUp(self):
        super().setUp()
        self.user = _user("pos_ops")
        self.cfg = _cfg(self.user)
        self.row = _trade(self.cfg, 115)

    def _sent(self, call):
        with patch("requests.post", return_value=_ok()) as post:
            call()
        return _payloads(post)

    def test_a_fill_open_carries_its_page_and_its_close_dialog(self):
        from bot_program.notifications import (fill_open_message,
                                               notify_bot_fill_open)
        msg = fill_open_message(asset_class="stock", symbol="AAPL",
                                side="BUY", qty=2, entry_price=210,
                                trade=self.row)
        self.assertEqual(msg["button"], [
            ("Open position", "/forensics/115/"),
            ("Close position", "/positions/115/close-dialog/")])
        (p,) = self._sent(lambda: notify_bot_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=self.row.qty, entry_price=self.row.entry_price,
            rule_name="golden_cross", trade=self.row, trade_id=self.row.id))
        self.assertEqual(_paths(p["reply_markup"]), [
            "/forensics/115/", "/positions/115/close-dialog/"])

    def test_a_queued_order_and_a_close_carry_no_close_button(self):
        from bot_program.notifications import (fill_close_message,
                                               fill_queued_message)
        queued = fill_queued_message(asset_class="stock", symbol="AAPL",
                                     side="BUY", qty=1, trade=self.row)
        closed = fill_close_message(asset_class="stock", symbol="AAPL",
                                    side="BUY", qty=2, exit_price=220,
                                    pnl=20, trade=self.row)
        for msg in (queued, closed):
            self.assertEqual(msg["button"],
                             ("Open position", "/forensics/115/"))

    def test_a_refused_close_and_a_vanished_stop_carry_close_position(self):
        from bot_program import notifications as N
        for call in (
                lambda: N.notify_manual_close_refused(
                    self.user, asset_class="stock", symbol="AAPL",
                    trade_id=self.row.id),
                lambda: N.notify_protection_vanished(
                    self.user, asset_class="stock", symbol="AAPL",
                    side="BUY", qty=self.row.qty,
                    stop_loss=self.row.stop_loss, reason="gone",
                    trade_id=self.row.id)):
            (p,) = self._sent(call)
            self.assertEqual(_paths(p["reply_markup"]), [
                "/forensics/115/", "/positions/115/close-dialog/"])
        # without a trade: the positions list alone, as before
        cache.clear()
        (p,) = self._sent(lambda: N.notify_manual_close_refused(
            self.user, asset_class="stock", symbol="MSFT", trade_id=None))
        self.assertEqual(p["reply_markup"],
                         _row(("Open positions", "/positions/")))

    def _review(self, book):
        return SimpleNamespace(
            verdict="exit", symbol="AAPL", side="BUY", confidence=0.7,
            suggested_stop=None, take_part_pct=None, unrealized_r=-0.4,
            triggers=[], facts={}, reasoning_md="", book=book,
            position_id=115, id=9)

    def test_a_review_of_the_bot_book_carries_close_the_portfolio_book_not(
            self):
        from bot_program.notifications import position_review_message
        bot = position_review_message(review=self._review("bot"),
                                      row=self.row)
        self.assertEqual(bot["button"], [
            ("Open position", "/forensics/115/"),
            ("Close position", "/positions/115/close-dialog/")])
        book = position_review_message(review=self._review("portfolio"))
        self.assertEqual(book["button"], ("Open positions", "/positions/"))

    def test_a_dead_thesis_on_the_bot_book_carries_close(self):
        from bot_program.notifications import thesis_exit_message
        facts = {"thesis": {"why": ["structure broke"]},
                 "unrealized_r": 0.4}
        bot = thesis_exit_message(pos={"symbol": "AAPL", "side": "BUY",
                                       "book": "bot", "position_id": 115},
                                  facts=facts, row=self.row)
        self.assertEqual(_paths(_row(*bot["button"])), [
            "/forensics/115/", "/positions/115/close-dialog/"])
        other = thesis_exit_message(pos={"symbol": "AAPL", "side": "BUY",
                                         "book": "portfolio",
                                         "position_id": 115},
                                    facts=facts)
        self.assertNotIn("Close position", json.dumps(other["button"]))

    def test_notify_staff_carries_close_only_when_asked(self):
        from bot_program.notifications import notify_staff
        (p,) = self._sent(lambda: notify_staff(
            title="⚠ AAPL: filled at eToro with no stop read", body="b",
            close_trade_id=self.row.id))
        self.assertEqual(p["reply_markup"], _row(
            ("Close position", "/positions/115/close-dialog/")))
        (p,) = self._sent(lambda: notify_staff(title="the brain failed",
                                               body="b"))
        self.assertNotIn("reply_markup", p)

    def test_the_email_copy_carries_both_pages(self):
        from bot_program.notifications import (_external_copy,
                                               fill_open_message)
        msg = fill_open_message(asset_class="stock", symbol="AAPL",
                                side="BUY", qty=2, entry_price=210,
                                trade=self.row)
        _title, body = _external_copy(msg, "t", "b")
        self.assertIn(f"Open position: https://{HOST}/forensics/115/",
                      body)
        self.assertIn(
            f"Close position: https://{HOST}/positions/115/close-dialog/",
            body)

    def test_the_three_staff_call_sites_name_their_row(self):
        from bot_program import venue_exit
        from bot_program.asset_engine import base
        src = inspect.getsource(base)
        self.assertEqual(src.count("close_trade_id="), 2)
        self.assertIn("close_trade_id=(None if is_entry_working(trade)",
                      src)
        self.assertEqual(
            inspect.getsource(venue_exit).count("close_trade_id=trade.id"),
            1)


# ── T4: Morgul and the alarm bot ─────────────────────────────────────────

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _finding(key, subject, *, severity="critical", event=False,
             title=None, label="AAPL long #12 · live", closable=True):
    from bot_program import morgul
    g = morgul.GUARD[key]
    return morgul.Finding(g, subject, title=title or g.title, label=label,
                          facts=["Used margin: 60.00 USD"],
                          severity=severity, event=event, closable=closable)


class MorgulButtonTests(SimpleTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"DOMAIN": HOST})
        env.start()
        self.addCleanup(env.stop)

    def test_one_g2_or_g5_finding_carries_close_position(self):
        from bot_program import morgul
        for f in (_finding("no_stop", "trade:12"),
                  _finding("proofs", "trade:12"),
                  _finding("no_stop", "trade:12:stop", severity="warning",
                           title="Morgul — the broker moved a stop "
                                 "farther away")):
            with self.subTest(f.key):
                self.assertEqual(f.trade_id, 12)
                (reply,) = morgul.build_messages([f], {}, NOW)
                self.assertEqual(reply.meta["button"], (
                    "Close position", "/positions/12/close-dialog/"))

    def test_none_for_several_findings_events_and_the_other_guards(self):
        from bot_program import morgul
        two = morgul.build_messages([_finding("no_stop", "trade:12"),
                                     _finding("no_stop", "trade:13")],
                                    {}, NOW)
        self.assertEqual(len(two), 1)
        self.assertNotIn("button", two[0].meta)
        for f in (_finding("stuck_close", "trade:12", severity="warning"),
                  _finding("stop_overshoot", "trade:12"),
                  _finding("market_shut", "trade:12", event=True),
                  _finding("price_sanity", "trade:12", event=True),
                  _finding("proofs", "trade:12", event=True),
                  # an order still waiting at the broker: no position
                  _finding("proofs", "trade:12", closable=False),
                  _finding("margin", "account:3:pledged")):
            with self.subTest(f.key):
                self.assertIsNone(morgul.close_button(f))
                (reply,) = morgul.build_messages([f], {}, NOW)
                self.assertNotIn("button", reply.meta)
        self.assertIsNone(_finding("margin", "account:3").trade_id)

    def test_the_eye_sends_the_button_of_a_reply_and_none_otherwise(self):
        from bot_program import telegram_eye as eye
        user = SimpleNamespace(pk=1)
        reply = eye.Reply("M", "T", ["a"], meta={"button": (
            "Close position", "/positions/12/close-dialog/")})
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as send:
            eye._send(user, reply)
            eye._send(user, eye.Reply("M", "T", ["a"]))
        first, second = send.call_args_list
        self.assertEqual(first.kwargs["button"],
                         ("Close position", "/positions/12/close-dialog/"))
        self.assertNotIn("button", second.kwargs)


class MorgulWorkingEntryTests(TestCase):
    """G5 judges a live eToro ORDER still waiting at the broker too
    (check_proofs has no working-entry skip, on purpose: an unproven
    order may fill). Such an order has no position to close, so its
    finding carries no "Close position"; a filled row's does."""

    def test_g5_on_a_working_entry_carries_no_close_button(self):
        from bot_program import morgul
        from bot_program.asset_engine import base
        from instruments.models import Instrument
        from tests.test_morgul import LIVE_ETORO, _cfg as m_cfg, _check
        from tests.test_morgul import _trade as m_trade
        Instrument.objects.create(symbol="AAPL", name="Apple",
                                  asset_class="stock", exchange="NASDAQ")
        cfg = m_cfg(User.objects.create_user("g5_owner"), "Stocks live",
                    "stock", mode="live")
        filled = m_trade(cfg, "AAPL", entry="336.10", stop="326.02",
                         paper=False, metadata=LIVE_ETORO)
        working = m_trade(cfg, "AAPL", entry="336.10", stop="326.02",
                          paper=False,
                          metadata=dict(LIVE_ETORO, entry_working=True))
        with patch.dict(os.environ, {"DOMAIN": HOST}), \
                patch.object(base, "ETORO_PROVEN", frozenset()), \
                patch.object(base, "ETORO_SHORT_PROVEN", frozenset()):
            found = {f.subject: f for f in _check("proofs", NOW)[1]}
            self.assertEqual(
                morgul.close_button(found[f"trade:{filled.pk}"]),
                ("Close position", f"/positions/{filled.pk}/close-dialog/"))
            self.assertFalse(found[f"trade:{working.pk}"].closable)
            self.assertIsNone(
                morgul.close_button(found[f"trade:{working.pk}"]))


class AlarmButtonTests(TestCase):
    def setUp(self):
        from tests.test_alarm_bot import ENV as ALARM_ENV
        from tests.test_alarm_bot import _component, _resumed
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict(os.environ, dict(ALARM_ENV, DOMAIN=HOST))
        env.start()
        self.addCleanup(env.stop)
        from bot_program import alarm
        _component(alarm.COMPONENT_KEY)
        _component("platform_master")
        _resumed(NOW - timedelta(days=3))

    def _relay(self, findings, post=None):
        from bot_program import alarm
        from tests.test_alarm_bot import POST, _ok, _report
        with patch(POST, side_effect=post or _ok) as p:
            alarm.relay_morgul(_report(list(findings), now=NOW))
        return p.call_args_list

    def test_a_critical_g2_carries_one_url_button(self):
        (call,) = self._relay([_finding("no_stop", "trade:12")])
        markup = call.kwargs["markup"]
        self.assertEqual(markup, _row(("Close position",
                                       "/positions/12/close-dialog/")))
        self.assertNotIn("callback_data", json.dumps(markup))
        self.assertIn(
            f"Close position: https://{HOST}/positions/12/close-dialog/",
            call.kwargs["fallback_text"])
        self.assertNotIn("Page: ", call.kwargs["fallback_text"])

    def test_the_texts_and_the_fallback_carry_no_money(self):
        from tests.test_alarm_bot import MONEY, _plain
        (call,) = self._relay([_finding("no_stop", "trade:12")])
        for text in (call.args[1]["text"], call.kwargs["fallback_text"]):
            self.assertIsNone(MONEY.search(_plain(text)), _plain(text))

    def test_a_bundle_the_brake_and_an_abandoned_close_carry_none(self):
        from bot_program import alarm
        from tests.test_alarm_bot import POST, _ok
        many = [_finding("no_stop", f"trade:{n}")
                for n in range(alarm.MAX_MESSAGES + 1)]
        (call,) = self._relay(many)
        self.assertIsNone(call.kwargs.get("markup"))
        cfg = _cfg(User.objects.create_user("alarm_owner"))
        _trade(cfg, 31, status="ERROR", paper=False)
        abandoned = alarm.read_abandoned(NOW)
        self.assertEqual([a.button for a in abandoned], [None])
        with patch(POST, side_effect=_ok) as p:
            alarm._settle("sentinel", abandoned, NOW)
        self.assertIsNone(p.call_args.kwargs.get("markup"))

    def test_send_alarm_without_a_button_is_as_before(self):
        from bot_program import alarm
        from tests.test_alarm_bot import POST, _ok
        with patch(POST, side_effect=_ok) as p:
            self.assertTrue(alarm.send_alarm("t", ["a"]))
        self.assertIsNone(p.call_args.kwargs.get("markup"))
        self.assertIsNone(p.call_args.kwargs.get("fallback_text"))

    def test_a_refused_button_still_delivers_the_alarm(self):
        from bot_program import alarm
        from alerts.channels import telegram_alert
        answers = [_refused(), _ok()]
        with patch("requests.post", side_effect=answers) as post, \
                self.assertLogs("bot_program.alarm", "WARNING") as logs:
            self.assertTrue(alarm.send_alarm(
                "t", ["a"], button=("Close position",
                                    "/positions/12/close-dialog/")))
        first, second = _payloads(post)
        self.assertIn("reply_markup", first)
        self.assertNotIn("reply_markup", second)
        self.assertTrue(second["text"].endswith(
            f"Close position: https://{HOST}/positions/12/close-dialog/"))
        self.assertNotIn(os.environ["TELEGRAM_ALARM_BOT_TOKEN"],
                         "\n".join(logs.output))
        self.assertTrue(callable(telegram_alert.post_message))


# ── T5: the pages a button opens ─────────────────────────────────────────

def _counts():
    from alerts.models import Notification
    from bot_program.audit_models import AuditLogEntry
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from core.audit import AuditLog
    return {m.__name__: m.objects.count()
            for m in (AssetBotTrade, AssetBotConfig, Notification,
                      AuditLog, AuditLogEntry)}


#: Every door that could act or read a PIN: none may run on a GET.
DOORS = ("core.trading_pin.check", "core.trading_pin.gate",
         "bot_program.manual_trade.preview_take_trade",
         "bot_program.manual_trade.execute_take_trade",
         "bot_program.manual_trade.preview_asset_trade",
         "bot_program.manual_trade.execute_asset_trade",
         "bot_program.manual_trade.manual_config_for",
         "bot_program.manual_close.preview_close",
         "bot_program.manual_close.execute_close")


def _run(body):
    """The page's #svDeepLink JSON, or None."""
    m = re.search(r'<script id="svDeepLink" type="application/json">'
                  r'(.*?)</script>', body, re.S)
    return json.loads(m.group(1)) if m else None


def _note(body):
    m = re.search(r'<span class="sv-deeplink-note__text">(.*?)</span>',
                  body, re.S)
    return html.unescape(m.group(1)) if m else None


class _Pages(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = _user("page_ops")
        self.other = _user("page_other", chat="456")
        self.inst = _instrument("MSFT")

    def get(self, path, user=None):
        """GET `path` as `user` with every acting door watched."""
        self.client.force_login(user or self.user)
        before = _counts()
        patches = [patch(d) for d in DOORS]
        mocks = [p.start() for p in patches]
        try:
            resp = self.client.get(path)
        finally:
            for p in patches:
                p.stop()
        for name, mock in zip(DOORS, mocks):
            self.assertFalse(mock.called, f"{name} ran on a GET")
        self.assertEqual(_counts(), before)
        self.assertNotIn("pin_lock_attempts", self.client.session)
        return resp


class TheTicketPageTests(_Pages):
    def test_anonymous_goes_to_the_wall_with_the_link_as_next(self):
        sig = _signal(self.inst)
        resp = self.client.get(f"/signals/{sig.pk}/ticket/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"],
                         f"/wall/?next=/signals/{sig.pk}/ticket/")

    def test_an_active_signal_opens_its_own_ticket_by_id(self):
        sig = _signal(self.inst)
        resp = self.get(f"/signals/{sig.pk}/ticket/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "dashboard/instrument_detail.html")
        body = resp.content.decode()
        self.assertEqual(_run(body), {"open": "signal", "signal_id": sig.pk,
                                      "auto": False})
        self.assertIn("OPEN THE TICKET", body)
        self.assertIn(f"signal #{sig.pk}", _note(body))
        self.assertIn("trading PIN", _note(body))
        # no lane yet: nothing opens by itself, and the note says the
        # click, never "opens below"
        self.assertTrue(_note(body).startswith(
            f"Press OPEN THE TICKET to open the TAKE TRADE ticket for "
            f"signal #{sig.pk}."), _note(body))
        self.assertNotIn("below", _note(body))
        # the page is the instrument's own: its venue badge is there
        self.assertEqual(resp.context["lane_mode"], "paper")

    def test_the_ticket_opens_by_itself_once_the_lane_exists(self):
        from bot_program.manual_trade import (MANUAL_CONFIG_NAME,
                                              manual_config_if_any)
        _cfg(self.user, "stock", MANUAL_CONFIG_NAME)
        self.assertIsNotNone(manual_config_if_any(self.user, "stock"))
        sig = _signal(self.inst)
        body = self.get(f"/signals/{sig.pk}/ticket/").content.decode()
        self.assertTrue(_run(body)["auto"])
        self.assertTrue(_note(body).startswith(
            f"The TAKE TRADE ticket for signal #{sig.pk} opens below."),
            _note(body))
        self.assertNotIn("Press OPEN THE TICKET", _note(body))
        # a signal no longer active, with the lane: the ticket is below
        old = _signal(self.inst, is_active=False, outcome="hit_target")
        body = self.get(f"/signals/{old.pk}/ticket/").content.decode()
        self.assertTrue(_run(body)["auto"])
        self.assertIn("(it hit its target). The ticket below is built from "
                      "live prices", _note(body))

    def test_a_signal_no_longer_active_opens_the_instruments_ticket(self):
        for direction, side in (("bullish", "BUY"), ("bearish", "SELL")):
            with self.subTest(direction):
                sig = _signal(self.inst, direction=direction,
                              is_active=False, outcome="expired")
                body = self.get(f"/signals/{sig.pk}/ticket/").content.decode()
                self.assertEqual(_run(body), {"open": "asset",
                                              "symbol": "MSFT", "side": side,
                                              "auto": False})
                self.assertIn("is no longer active (it expired)",
                              _note(body))
                # no lane: the click, never "the ticket below"
                self.assertIn("Press OPEN THE TICKET for a ticket built "
                              "from live prices", _note(body))
                self.assertNotIn("below", _note(body))

    def test_a_signal_without_a_trade_says_so_and_opens_nothing(self):
        for sig in (_signal(self.inst, direction="neutral"),
                    _signal(_instrument("SPX", "index"))):
            with self.subTest(sig.pk):
                body = self.get(f"/signals/{sig.pk}/ticket/").content.decode()
                self.assertIsNone(_run(body))
                self.assertIn("no ticket to prepare", _note(body))
                self.assertNotIn("OPEN THE TICKET", body)

    def test_a_missing_signal_or_one_without_a_page_is_a_404(self):
        self.assertEqual(self.get("/signals/999999/ticket/").status_code,
                         404)
        sig = _signal(_instrument("BTC/USD", "crypto"))
        self.assertEqual(self.get(f"/signals/{sig.pk}/ticket/").status_code,
                         404)

    def test_a_post_is_refused(self):
        sig = _signal(self.inst)
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(f"/signals/{sig.pk}/ticket/").status_code, 405)

    def test_an_investor_is_sent_to_the_panel(self):
        from portfolio.investor_models import InvestorAccess
        investor = User.objects.create_user("page_investor", password="x")
        InvestorAccess.objects.create(investor=investor, owner=self.user)
        sig = _signal(self.inst)
        self.client.force_login(investor)
        resp = self.client.get(f"/signals/{sig.pk}/ticket/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/investor/"))

    def test_the_json_never_carries_a_price(self):
        sig = _signal(self.inst, is_active=False)
        body = self.get(f"/signals/{sig.pk}/ticket/").content.decode()
        raw = json.dumps(_run(body))
        for price in ("421", "410", "440", "1.85"):
            self.assertNotIn(price, raw)


class TheCloseDialogPageTests(_Pages):
    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        self.theirs = _trade(_cfg(self.other, name="Their stocks"), 501,
                             symbol="ZQXWT")

    def test_an_own_open_row_opens_its_close_dialog(self):
        for status in ("OPEN", "CLOSE_PENDING"):
            with self.subTest(status):
                row = _trade(self.cfg, symbol="AAPL", status=status)
                resp = self.get(f"/positions/{row.pk}/close-dialog/")
                self.assertEqual(resp.status_code, 200)
                self.assertTemplateUsed(resp,
                                        "dashboard/positions_list.html")
                body = resp.content.decode()
                self.assertEqual(_run(body), {"open": "close",
                                              "trade_id": row.pk,
                                              "auto": True})
                self.assertIn(f"AAPL #{row.pk}", _note(body))
                self.assertIn("trading PIN", _note(body))

    def test_an_order_still_waiting_names_the_dialog_that_opens(self):
        """closeFlow draws the same close dialog for an order still
        waiting (its confirm withdraws the order): the note names that
        dialog and what its confirm does, never a "withdraw dialog"."""
        row = _trade(self.cfg, symbol="AAPL",
                     metadata={"entry_working": True})
        body = self.get(f"/positions/{row.pk}/close-dialog/").content.decode()
        self.assertEqual(_run(body), {"open": "close", "trade_id": row.pk,
                                      "auto": True})
        note = _note(body)
        self.assertIn(f"The order for AAPL #{row.pk} has not filled yet",
                      note)
        self.assertIn("The close dialog opens below; for this order, "
                      "confirming it withdraws the order.", note)
        self.assertNotIn("withdraw dialog", note)
        self.assertIn("trading PIN", note)

    def test_a_closed_canceled_or_abandoned_row_says_so_and_opens_nothing(
            self):
        cases = {"CLOSED": "is already closed",
                 "CANCELED": "never filled",
                 "ERROR": "stopped retrying the close"}
        for status, words in cases.items():
            with self.subTest(status):
                row = _trade(self.cfg, symbol="AAPL", status=status)
                body = self.get(
                    f"/positions/{row.pk}/close-dialog/").content.decode()
                self.assertIsNone(_run(body))
                self.assertIn(words, _note(body))

    def test_another_users_row_and_a_missing_one_read_the_same(self):
        theirs = self.get(f"/positions/{self.theirs.pk}/close-dialog/")
        missing = self.get("/positions/999999/close-dialog/")
        for resp in (theirs, missing):
            self.assertEqual(resp.status_code, 200)
        a, b = theirs.content.decode(), missing.content.decode()
        self.assertEqual(_note(a), _note(b))
        self.assertEqual(_note(a), "This link does not match a position "
                                   "in your book.")
        self.assertIsNone(_run(a))
        self.assertIsNone(_run(b))
        self.assertNotIn("ZQXWT", a)
        self.assertNotIn("Their stocks", a)

    def test_a_post_is_refused(self):
        row = _trade(self.cfg)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(
            f"/positions/{row.pk}/close-dialog/").status_code, 405)

    def test_the_live_refresh_never_opens_it_again(self):
        self.client.force_login(self.user)
        body = self.client.get("/positions/live/").content.decode()
        self.assertNotIn("svDeepLink", body)


class TheRunnerAndTheNoteTests(SimpleTestCase):
    def _base(self):
        return (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")

    def _runner(self):
        src = self._base()
        start = src.index("A TELEGRAM BUTTON'S PAGE (2026-10-24)")
        return src[start:src.index("})();", start)]

    def test_the_runner_only_calls_the_pages_own_doors(self):
        runner = self._runner()
        for door in ("window.svTakeTrade(", "window.svTakeTradeAsset(",
                     "window.svCloseTrade("):
            self.assertIn(door, runner)
        self.assertNotIn("fetch(", runner)
        self.assertNotIn("/take-trade/", runner)
        self.assertNotIn("/close/", runner)
        self.assertNotIn("pin", runner.lower().replace("trading pin", ""))

    def test_the_execute_posts_stay_inside_their_flows_after_confirm(self):
        src = self._base()
        trade_flow = src[src.index("function tradeFlow("):
                         src.index("window.svTakeTrade = function")]
        self.assertLess(trade_flow.index("sizeDialog(p).then"),
                        trade_flow.index("fetch(executeUrl"))
        close_flow = src[src.index("function closeFlow(btn)"):
                         src.index("window.svCloseTrade = function")]
        self.assertLess(close_flow.index("SV.overlay.confirm"),
                        close_flow.index("'/close/'"))
        self.assertEqual(src.count("fetch(executeUrl"), 1)
        self.assertEqual(src.count("'/close/', {"), 1)
        # svCloseTrade hands a button to closeFlow, nothing else
        close_door = src[src.index("window.svCloseTrade = function"):]
        close_door = close_door[:close_door.index("};")]
        self.assertNotIn("fetch(", close_door)
        self.assertIn("closeFlow(btn)", close_door)

    def test_the_note_is_english_and_escaped(self):
        from django.template.loader import render_to_string
        from tests.test_telegram_house_style import FRENCH
        out = render_to_string("_partials/deep_link_note.html", {
            "deep_link": {"note": "Signal <b>#4</b> & co",
                          "run": {"open": "signal", "signal_id": 4,
                                  "auto": False}}})
        self.assertIn("Signal &lt;b&gt;#4&lt;/b&gt; &amp; co", out)
        self.assertIn('role="status"', out)
        self.assertIn('<script id="svDeepLink" type="application/json">',
                      out)
        from dashboard import views_links
        words = " ".join([views_links.NOT_YOURS,
                          *views_links.OUTCOME_WORDS.values(),
                          inspect.getsource(views_links.ticket_link),
                          inspect.getsource(views_links.close_link)])
        low = " " + re.sub(r"[^a-zà-ÿ]+", " ", words.lower()) + " "
        for word in FRENCH:
            self.assertNotIn(word, low)


# ── T6: the login comes back to the link ─────────────────────────────────

class TheLoginReturnTests(TestCase):
    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        from core import security
        security._login_attempts.clear()
        cache.clear()
        self.addCleanup(cache.clear)
        self.pin_user = _user("login_pin_u", pin="4321")
        self.plain = _user("login_plain_u")

    def _wall_next(self, query):
        body = self.client.get("/wall/" + query).content.decode()
        m = re.search(r'<input type="hidden" name="next" value="([^"]*)">',
                      body)
        return m.group(1), body

    def test_the_wall_carries_a_deep_link_and_nothing_else(self):
        value, body = self._wall_next("?next=/signals/7/ticket/")
        self.assertEqual(value, "/signals/7/ticket/")
        self.assertIn('<body class="login-mode">', body)
        value, _ = self._wall_next("?next=/positions/12/close-dialog/")
        self.assertEqual(value, "/positions/12/close-dialog/")
        for bad in ("https://evil.example/", "//evil.example/", "/admin/",
                    "/signals/7/ticket/?x=1", "/signals/7/ticket/extra",
                    "/" + "planted-words-" * 20):
            with self.subTest(bad):
                value, body = self._wall_next("?next=" + bad)
                self.assertEqual(value, "/intro/")
                self.assertNotIn("evil", body)
                self.assertNotIn("planted", body)
                self.assertIn("<body>", body)

    def test_a_signed_in_visitor_goes_straight_to_the_link(self):
        self.client.force_login(self.plain)
        resp = self.client.get("/wall/?next=/signals/7/ticket/")
        self.assertEqual(resp["Location"], "/signals/7/ticket/")
        resp = self.client.get("/wall/?next=https://evil.example/")
        self.assertEqual(resp["Location"], "/")

    def test_the_pin_login_returns_to_the_link_with_its_mark(self):
        from core.trading_pin import LOGIN_MARK_KEY, _pin_mark
        link = "/positions/12/close-dialog/"
        r = self.client.post("/login/", {"username": "login_pin_u",
                                         "password": "pw-login_pin_u",
                                         "next": link})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.session["sauron_pending_next"], link)
        r = self.client.post("/login/pin/", {"pin": "4321"})
        self.assertEqual(r["Location"], link)
        prof = self.pin_user.trader_profile
        prof.refresh_from_db()
        self.assertEqual(self.client.session[LOGIN_MARK_KEY],
                         _pin_mark(prof.access_pin_hash))

    def test_the_ajax_pin_login_returns_to_the_link(self):
        link = "/signals/7/ticket/"
        r = self.client.post("/login/", {"username": "login_pin_u",
                                         "password": "pw-login_pin_u",
                                         "next": link}, **self.AJAX)
        self.assertEqual(r.json()["status"], "pin_required")
        r = self.client.post("/login/pin/", {"pin": "4321"}, **self.AJAX)
        self.assertEqual(r.json(), {"status": "ok", "redirect": link})

    def test_a_login_without_a_pin_returns_to_the_link(self):
        link = "/signals/7/ticket/"
        r = self.client.post("/login/", {"username": "login_plain_u",
                                         "password": "pw-login_plain_u",
                                         "next": link})
        self.assertEqual(r["Location"], link)
        self.client.logout()
        r = self.client.post("/login/", {"username": "login_plain_u",
                                         "password": "pw-login_plain_u",
                                         "next": link}, **self.AJAX)
        self.assertEqual(r.json()["redirect"], link)

    def test_an_address_off_the_site_is_never_followed(self):
        from core import security
        for bad in ("https://evil.example/", "//evil.example/x",
                    "/\\evil.example", "javascript:alert(1)"):
            with self.subTest(bad):
                security._login_attempts.clear()
                self.client.logout()
                self.client.post("/login/", {"username": "login_pin_u",
                                             "password": "pw-login_pin_u",
                                             "next": bad})
                self.assertEqual(self.client.session["sauron_pending_next"],
                                 "/intro/")
                r = self.client.post("/login/pin/", {"pin": "4321"})
                self.assertEqual(r["Location"], "/intro/")
                self.client.logout()
                r = self.client.post("/login/", {
                    "username": "login_plain_u",
                    "password": "pw-login_plain_u", "next": bad})
                self.assertEqual(r["Location"], "/intro/")

    def test_a_pending_next_an_older_deploy_stored_is_checked_again(self):
        self.client.post("/login/", {"username": "login_pin_u",
                                     "password": "pw-login_pin_u"})
        session = self.client.session
        session["sauron_pending_next"] = "https://evil.example/"
        session.save()
        r = self.client.post("/login/pin/", {"pin": "4321"})
        self.assertEqual(r["Location"], "/intro/")

    def test_the_link_is_reached_after_the_login(self):
        sig = _signal(_instrument("MSFT"))
        link = f"/signals/{sig.pk}/ticket/"
        first = self.client.get(link)
        self.assertEqual(first["Location"], f"/wall/?next={link}")
        r = self.client.post("/login/", {"username": "login_pin_u",
                                         "password": "pw-login_pin_u",
                                         "next": link})
        r = self.client.post("/login/pin/", {"pin": "4321"}, follow=True)
        self.assertEqual(r.redirect_chain[0][0], link)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_run(r.content.decode())["signal_id"], sig.pk)
