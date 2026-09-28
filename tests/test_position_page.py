"""THE POSITION PAGE, FOR THE FATHER (2026-09-26).

/forensics/<id>/ opened on six technical cards and a strip of raw fields —
"too nerdy", in the operator's words, for the father who runs Sauron from
his phone for three weeks. The page now opens on a plain summary, keeps
itself live while the position is open, and puts the way out one tap away.
What this file pins:

  * the summary in words, for an open paper row, an open real-money row, a
    row closed by hand and a row closed by its stop: the headline, the
    chips from the row's own stamps, the P&L or the result, the ending;
  * no raw key, no "None", no "Decimal(" anywhere in it;
  * the live endpoint returns the fragment alone and never reaches a
    broker (the router and the clients are patched and must stay uncalled);
  * the close button reaches the EXISTING preview and close endpoints with
    the CSRF token, the PIN field exists exactly when the close endpoint
    will ask for one, and the dialog's words (run under node);
  * the technical record is all still there, folded and closed by default;
  * the page holds at 360px, and renders 200 for a position with no mark;
  * the review's fixes (2026-09-26): the preview can be cancelled and the
    close cannot, a timer tick never lands under the dialog (both run
    under node against a stub page), the poll is machinery to the idle
    lock, the shell's page takes a phone's whole width and its floating
    buttons clear the close bar, a working order is not "held", a broker
    row without a resting stop is not "closed by itself", an older forex
    row's figures carry their real currency, and the rule names read as
    words.

Nothing here sends an order: the one POST that reaches the close endpoint
has execute_close patched, as tests/test_manual_close.py's own do.

Run with:  python manage.py test tests.test_position_page
"""
import html as _html
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import resolve
from django.utils import timezone

NODE = shutil.which("node")
SNAKE = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")
PAGE = "/forensics/%d/"
LIVE = "/forensics/%d/live/"


# ── fixtures ─────────────────────────────────────────────────────────────

def _instrument(symbol="EURCAD", asset_class="forex", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    return inst


def _quote(inst, last, at=None):
    from market_data.models import LiveQuote
    q, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    if at is not None:
        # updated_at is auto_now: only a queryset update can age it.
        LiveQuote.objects.filter(pk=q.pk).update(updated_at=at)
    return q


def _config(user, asset_class="forex", mode="paper"):
    """One book per (class, mode): (user, class, name) is unique."""
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name="pp_" + mode,
        defaults={"enabled": True, "mode": mode, "symbols": [],
                  "capital": Decimal("10000"), "base_currency": "USD"})
    return cfg


def _signal(inst, rule="golden_cross"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction="bullish",
        urgency="medium", title="golden cross", description="d",
        rule_name=rule, score=0.8, sub_scores={},
        price_at_signal=Decimal("1.59"), suggested_entry=Decimal("1.59"))


def _trade(user, *, symbol="EURCAD", asset_class="forex", side="BUY",
           qty="1000", entry="1.59030", stop="1.52670", target="1.76780",
           paper=True, status="OPEN", metadata=None, config=None,
           rule="manual_take", reason="", **extra):
    from bot_program.models import AssetBotTrade
    meta = {"value_per_unit": 0.72, "initial_stop_loss": float(stop)
            if stop is not None else None}
    meta.update(metadata or {})
    return AssetBotTrade.objects.create(
        config=config or _config(user, asset_class=asset_class,
                                 mode="paper" if paper else "live"),
        asset_class=asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal(stop) if stop is not None else None,
        take_profit=Decimal(target) if target is not None else None,
        status=status, paper=paper, rule_name=rule, reason=reason,
        metadata=meta, **extra)


def _age(trade, *, opened, closed=None):
    """opened_at is auto_now_add: only a queryset update can move it."""
    from bot_program.models import AssetBotTrade
    fields = {"opened_at": opened}
    if closed is not None:
        fields["closed_at"] = closed
    AssetBotTrade.objects.filter(pk=trade.pk).update(**fields)
    trade.refresh_from_db()
    return trade


def _section(page):
    """The summary <section>, markup and all."""
    m = re.search(r'<section class="pd-sum[^"]*" data-pd-live="summary".*?</section>',
                  page, re.S)
    assert m, "no summary section on the page"
    return m.group(0)


def _visible(markup):
    """What a reader sees: tags, scripts and styles out, entities decoded."""
    markup = re.sub(r"<(script|style)\b.*?</\1>", " ", markup, flags=re.S)
    markup = re.sub(r"<[^>]+>", " ", markup)
    return re.sub(r"\s+", " ", _html.unescape(markup)).strip()


def _page_style(page):
    m = re.search(r"<style>\s*\.pd-sum \{.*?</style>", page, re.S)
    assert m, "the page's own style block is missing"
    return m.group(0)


class _Base(TestCase):
    username = "pp_user"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            self.username, password="x")
        self.client.force_login(self.user)
        self.inst = _instrument()
        _quote(self.inst, "1.61030")

    def get(self, trade):
        resp = self.client.get(PAGE % trade.id)
        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode("utf-8")
        return page, _section(page)

    def assertClean(self, section):
        text = _visible(section)
        self.assertEqual(SNAKE.findall(text), [], text)
        self.assertNotIn("None", section)
        self.assertNotIn("Decimal(", section)
        self.assertNotIn("nan", text.lower().split())
        return text


# ── D1: the summary in words ─────────────────────────────────────────────

class OpenPaperForexTests(_Base):
    username = "pp_open_paper"

    def setUp(self):
        super().setUp()
        sig = _signal(self.inst)
        self.trade = _trade(self.user, metadata={"manual": True,
                                                 "signal_id": sig.id},
                            reason="TAKE TRADE · signal #%d · golden_cross"
                                   % sig.id)
        self.sig = sig
        self.page, self.section = self.get(self.trade)
        self.text = self.assertClean(self.section)

    def test_the_headline_and_the_three_chips(self):
        self.assertIn('<h2 class="pd-headline" id="pdHeadline">Long EURCAD</h2>',
                      self.section)
        self.assertIn('pd-chip-open">Open</span>', self.section)
        self.assertIn('pd-chip-sim">Simulated</span>', self.section)
        self.assertIn('pd-chip-broker">Paper trading</span>', self.section)

    def test_the_pnl_is_big_coloured_and_in_the_account_currency(self):
        """(1.61030 - 1.59030) x 1,000 units x 0.72 USD per CAD = 14.40 USD,
        +1.26% of the position — the positions page's own reading."""
        self.assertIn('class="pd-big pd-up"', self.section)
        self.assertIn('<span class="pd-big-value">+14.40 USD</span>',
                      self.section)
        self.assertIn("+1.26% of the position", self.text)

    def test_the_prices_the_size_and_the_levels_in_plain_words(self):
        self.assertIn("Entry price 1.59030", self.text)
        self.assertIn("Price now 1.61030 as of ", self.text)
        self.assertRegex(self.text, r"as of \d\d:\d\d:\d\d UTC")
        self.assertIn("Position size 1,159.42 USD 1,000 units at the current "
                      "price", self.text)
        self.assertIn("Stop 1.52670 5.2% away", self.text)
        self.assertIn("Target 1.76780 9.8% away", self.text)
        self.assertIn("It closes by itself at the stop 1.52670 (5.2% away) "
                      "or the target 1.76780 (9.8% away).", self.text)

    def test_the_time_held_is_in_words(self):
        now = timezone.now()
        _age(self.trade, opened=now - timedelta(days=3, hours=4, minutes=5))
        _page, section = self.get(self.trade)
        self.assertIn("Held for 3 days 4 hours", _visible(section))

    def test_why_sauron_took_it_and_the_risk_it_carries(self):
        """|1.59030 - 1.52670| x 1,000 x 0.72 = 45.79 USD — the size of 1R
        manual_close._risk_dollars already quotes."""
        self.assertIn("Why Sauron took it", self.text)
        self.assertIn("Golden cross on EURCAD \u2014 taken by hand from "
                      "signal #%d." % self.sig.id, self.text)
        self.assertIn("It carries 45.79 USD of risk: the loss at the stop it "
                      "opened with.", self.text)

    def test_it_says_it_refreshes_and_when_it_was_checked(self):
        self.assertIn('data-pd-state="open"', self.section)
        self.assertIn('data-pd-live-url="%s"' % (LIVE % self.trade.id),
                      self.section)
        self.assertIn("Refreshes by itself every 15 seconds.", self.text)


class OpenLiveTests(_Base):
    username = "pp_open_live"

    def test_real_money_at_etoro_says_so_and_asks_for_the_pin(self):
        trade = _trade(self.user, paper=False, rule="golden_cross",
                       metadata={"broker": "etoro", "broker_env": "live"})
        page, section = self.get(trade)
        self.assertClean(section)
        self.assertIn('pd-chip-real">Real money</span>', section)
        self.assertIn('pd-chip-broker">eToro</span>', section)
        self.assertIn('id="pdClosePin"', page)
        self.assertIn("This is real money. A close at the broker cannot be "
                      "undone.", page)
        self.assertIn("Golden cross on EURCAD \u2014 opened automatically by "
                      "Sauron.", _visible(section))

    def test_the_etoro_demo_is_simulated_but_the_endpoint_still_asks(self):
        """A live-mode row in eToro's demo world: simulated money, held at
        a broker. requires_pin is `not trade.paper`, so the close endpoint
        asks for the PIN — the field is there and the page says why."""
        trade = _trade(self.user, paper=False,
                       metadata={"broker": "etoro", "broker_env": "paper"})
        page, section = self.get(trade)
        self.assertIn('pd-chip-sim">Simulated</span>', section)
        self.assertIn('pd-chip-broker">eToro demo</span>', section)
        self.assertIn('id="pdClosePin"', page)
        self.assertIn("held at a broker, so your trading PIN is needed", page)

    def test_a_live_row_with_no_stamp_is_real_money_at_an_unnamed_broker(self):
        trade = _trade(self.user, paper=False)
        _page, section = self.get(trade)
        self.assertIn('pd-chip-real">Real money</span>', section)
        self.assertIn('pd-chip-broker">Broker not recorded</span>', section)

    def test_a_short_at_ibkr(self):
        _instrument("AAPL", "stock", "NASDAQ")
        trade = _trade(self.user, symbol="AAPL", asset_class="stock",
                       side="SELL", qty="0.04", entry="230", stop="240",
                       target="210", paper=False,
                       metadata={"broker": "ibkr", "broker_env": "live",
                                 "value_per_unit": 1.0})
        _page, section = self.get(trade)
        self.assertIn(">Short AAPL</h2>", section)
        self.assertIn('pd-chip-broker">IBKR</span>', section)
        self.assertIn("0.04 shares", _visible(section))


class ClosedByHandTests(_Base):
    username = "pp_closed_hand"

    def setUp(self):
        super().setUp()
        opened = timezone.now() - timedelta(days=5)
        self.trade = _trade(
            self.user, status="CLOSED", exit_price=Decimal("1.61030"),
            pnl=Decimal("17.38"), realized_r=0.04, outcome="manual_close",
            reason="TAKE TRADE · manual BUY from instrument view"
                   " | closed:MANUAL",
            metadata={"manual": True})
        _age(self.trade, opened=opened,
             closed=opened + timedelta(days=3, hours=4))
        self.page, self.section = self.get(self.trade)
        self.text = self.assertClean(self.section)

    def test_the_result_the_r_in_words_and_the_ending(self):
        self.assertIn('pd-chip-closed">Closed</span>', self.section)
        self.assertIn('<span class="pd-big-value">+17.38 USD</span>',
                      self.section)
        self.assertIn("0.04 times the risk", self.text)
        self.assertRegex(self.text, r"Closed by hand on \d{4}-\d\d-\d\d "
                                    r"\d\d:\d\d UTC\.")
        self.assertIn("Exit price 1.61030 closed ", self.text)
        self.assertIn("Held for 3 days 4 hours", self.text)
        self.assertIn("Taken by hand on EURCAD from its instrument page.",
                      self.text)
        self.assertIn("It carried 45.79 USD of risk", self.text)

    def test_a_closed_position_has_no_close_button_and_does_not_refresh(self):
        self.assertIn('data-pd-state="closed"', self.section)
        self.assertNotIn('id="pdCloseBtn"', self.page)
        self.assertNotIn('id="pdClosePin"', self.page)
        self.assertNotIn("Refreshes by itself", self.text)


class ClosedByStopTests(_Base):
    username = "pp_closed_stop"

    def test_a_stop_out_reads_as_a_loss_in_words(self):
        trade = _trade(self.user, status="CLOSED",
                       exit_price=Decimal("1.52670"), pnl=Decimal("-45.79"),
                       realized_r=-1.0, outcome="stopped_out",
                       rule="golden_cross", reason="x | closed:SL",
                       closed_at=timezone.now())
        _page, section = self.get(trade)
        text = self.assertClean(section)
        self.assertIn('class="pd-big pd-down"', section)
        self.assertIn('<span class="pd-big-value">-45.79 USD</span>', section)
        self.assertIn("a loss of 1.00 times the risk", text)
        self.assertIn("Stop loss hit on ", text)
        self.assertIn("Exit price 1.52670", text)


class EndingWordsTests(TestCase):
    """The outcome codes the code actually writes, and the close tags that
    tell a hand close from the others; an unknown code reads "Closed"."""

    def _t(self, outcome, reason=""):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade(outcome=outcome, reason=reason)

    def test_every_written_code_has_words(self):
        from dashboard.position_summary import ending_words
        self.assertEqual(ending_words(self._t("hit_target")), "Target reached")
        self.assertEqual(ending_words(self._t("stopped_out")), "Stop loss hit")
        self.assertEqual(ending_words(self._t("time_stop")),
                         "Time limit reached")
        self.assertEqual(ending_words(self._t("expired")), "Closed at expiry")
        self.assertEqual(ending_words(self._t("manual_close", "a | closed:MANUAL")),
                         "Closed by hand")
        self.assertEqual(ending_words(self._t("manual_close",
                                              "a | closed:FUNDING · take-trade")),
                         "Closed to make room for a new trade")
        self.assertEqual(ending_words(self._t("manual_close",
                                              "a | reconciled-orphan")),
                         "Closed at the broker")

    def test_an_untagged_manual_close_and_an_unknown_code_say_closed(self):
        """The kill switch and reconciliation write manual_close with no
        tag of their own: "Closed", never a guess."""
        from dashboard.position_summary import ending_words
        self.assertEqual(ending_words(self._t("manual_close")), "Closed")
        self.assertEqual(ending_words(self._t("some_new_code")), "Closed")

    def test_an_unknown_code_never_reaches_the_page(self):
        user = get_user_model().objects.create_user("pp_unknown", password="x")
        self.client.force_login(user)
        trade = _trade(user, status="CLOSED", exit_price=Decimal("1.6"),
                       pnl=Decimal("1"), outcome="some_new_code",
                       closed_at=timezone.now())
        page = self.client.get(PAGE % trade.id).content.decode("utf-8")
        section = _section(page)
        self.assertNotIn("some_new_code", section)
        self.assertIn("Closed on ", _visible(section))


class WordsTests(SimpleTestCase):

    def test_rule_names_read_aloud(self):
        from dashboard.position_summary import rule_words
        self.assertEqual(rule_words("golden_cross"), "Golden cross")
        self.assertEqual(rule_words("rsi_reversal_4h"), "RSI reversal 4h")
        self.assertEqual(rule_words("breakout_1h"), "Breakout 1h")
        self.assertEqual(rule_words("manual_take"), "")
        self.assertEqual(rule_words(""), "")
        self.assertEqual(rule_words("dxy_breakout"), "DXY breakout")
        self.assertEqual(rule_words("asset_bot_weighted_consensus"),
                         "Several of Sauron's signals agreed")
        self.assertEqual(rule_words("asset_bot_signal_consensus"),
                         "Several of Sauron's signals agreed")
        self.assertEqual(rule_words("tradingview:my_strat v2"),
                         "TradingView alert")
        self.assertEqual(rule_words("tradingview"), "TradingView alert")

    def test_durations_and_quantities(self):
        from dashboard.position_summary import (countdown_words,
                                                duration_words, quantity)
        self.assertEqual(duration_words(3 * 86400 + 4 * 3600 + 120),
                         "3 days 4 hours")
        self.assertEqual(duration_words(3700), "1 hour 1 minute")
        self.assertEqual(duration_words(59), "less than a minute")
        self.assertEqual(quantity(Decimal("1000.00000000")), "1,000")
        self.assertEqual(quantity(Decimal("0.00020000")), "0.0002")
        self.assertEqual(countdown_words("1d 9h"), "1 day 9 hours")
        self.assertEqual(countdown_words("45m"), "45 minutes")
        self.assertEqual(countdown_words(""), "")


# ── D2: live, from the platform's own marks ──────────────────────────────

def _no_broker():
    """Every door to a broker, patched to fail the test if it is opened."""
    boom = AssertionError("a broker was reached")
    return [
        mock.patch("bot_program.engine.broker_router.client_for_symbol",
                   side_effect=boom),
        mock.patch("bot_program.engine.broker_router._etoro_client_for",
                   side_effect=boom),
        mock.patch("bot_program.engine.broker_router._ibkr_client_for",
                   side_effect=boom),
        mock.patch("bot_program.engine.broker_router._saxo_client_for",
                   side_effect=boom),
        mock.patch("bot_program.asset_engine.base.make_bot", side_effect=boom),
        mock.patch("bot_program.manual_close.preview_close", side_effect=boom),
        mock.patch("bot_program.manual_close.execute_close", side_effect=boom),
    ]


class LiveEndpointTests(_Base):
    username = "pp_live"

    def setUp(self):
        super().setUp()
        self.trade = _trade(self.user, paper=False,
                            metadata={"broker": "etoro", "broker_env": "live"})

    def test_it_returns_the_fragment_alone(self):
        resp = self.client.get(LIVE % self.trade.id)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn('data-pd-live="summary"', body)
        self.assertIn("+14.40 USD", body)
        self.assertNotIn("<html", body)
        self.assertNotIn("Technical details", body)
        self.assertNotIn("pdCloseBtn", body)
        self.assertClean(_section(body))
        self.assertIn("no-cache", resp.get("Cache-Control", ""))

    def test_it_never_reaches_a_broker_and_neither_does_the_page(self):
        patches = _no_broker()
        mocks = [p.start() for p in patches]
        try:
            live = self.client.get(LIVE % self.trade.id)
            page = self.client.get(PAGE % self.trade.id)
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(live.status_code, 200)
        self.assertEqual(page.status_code, 200)
        for m in mocks:
            self.assertFalse(m.called, m)

    def test_the_quote_moving_moves_the_fragment(self):
        _quote(self.inst, "1.62030")
        body = self.client.get(LIVE % self.trade.id).content.decode("utf-8")
        # (1.62030 - 1.59030) x 1,000 x 0.72
        self.assertIn("+21.60 USD", body)

    def test_it_is_get_only_and_owner_scoped(self):
        self.assertEqual(self.client.post(LIVE % self.trade.id).status_code,
                         405)
        other = get_user_model().objects.create_user("pp_live_other",
                                                     password="x")
        self.client.force_login(other)
        self.assertEqual(self.client.get(LIVE % self.trade.id).status_code,
                         404)
        self.client.logout()
        self.assertEqual(self.client.get(LIVE % self.trade.id).status_code,
                         302)

    def test_the_page_refreshes_every_15_seconds_and_not_while_hidden(self):
        page = self.client.get(PAGE % self.trade.id).content.decode("utf-8")
        self.assertIn("var EVERY_MS = 15000;", page)
        self.assertIn("document.hidden || !wasOpen || dialogOpen()", page)
        self.assertIn('fetch(url, {credentials: "same-origin", '
                      'cache: "no-store",', page)
        self.assertIn('headers: {"X-Requested-With": "XMLHttpRequest"}})',
                      page)

    def test_the_poll_is_machinery_to_the_idle_lock(self):
        """The poll carries X-Requested-With, so the idle lock neither
        counts it as a person (the server-side idle backstop still fires
        with the page on screen) nor answers a locked session with the
        lock page every 15 seconds: it gets a 423."""
        from django.test import RequestFactory
        from core.idle_lock import IdleLockMiddleware, _wants_json
        poll = RequestFactory().get(LIVE % self.trade.id,
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(_wants_json(poll))
        self.assertFalse(IdleLockMiddleware._is_human(poll))
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        locked = self.client.get(LIVE % self.trade.id,
                                 HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(locked.status_code, 423)
        self.assertEqual(locked.json(), {"pin_locked": True})


class MarketAndStaleTests(_Base):
    username = "pp_market"
    SATURDAY = datetime(2026, 9, 26, 12, 0, tzinfo=dt_timezone.utc)
    WEDNESDAY = datetime(2026, 9, 23, 12, 0, tzinfo=dt_timezone.utc)

    def _summary(self, now):
        from dashboard.position_summary import build_summary
        trade = _trade(self.user)
        return build_summary(trade, now=now)

    def test_a_shut_market_says_so_with_the_platforms_own_clock(self):
        _quote(self.inst, "1.61030", at=self.SATURDAY - timedelta(hours=15))
        notes = " ".join(n["text"] for n in self._summary(self.SATURDAY)["notes"])
        self.assertIn("The market for EURCAD is shut right now; it opens "
                      "again in 1 day 9 hours.", notes)
        self.assertIn("The last price came in 15 hours ago, which is normal "
                      "while the market is shut.", notes)

    def test_an_old_price_in_an_open_market_is_stale(self):
        _quote(self.inst, "1.61030", at=self.WEDNESDAY - timedelta(hours=2))
        summary = self._summary(self.WEDNESDAY)
        notes = " ".join(n["text"] for n in summary["notes"])
        self.assertNotIn("shut", notes)
        self.assertIn("The price is stale: the last one came in 2 hours ago",
                      notes)
        price_now = [f for f in summary["facts"] if f["label"] == "Price now"]
        self.assertEqual(price_now[0]["sub"], "as of 10:00:00 UTC")

    def test_a_fresh_price_in_an_open_market_carries_no_note(self):
        _quote(self.inst, "1.61030", at=self.WEDNESDAY - timedelta(seconds=30))
        self.assertEqual(self._summary(self.WEDNESDAY)["notes"], [])


class MissingMarkTests(_Base):
    username = "pp_nomark"

    def test_a_position_with_no_quote_and_no_instrument_still_renders(self):
        trade = _trade(self.user, symbol="NOQUOTE", asset_class="stock",
                       qty="3", entry="25.10", stop="24.00", target="28.00",
                       metadata={"value_per_unit": 1.0})
        page, section = self.get(trade)
        text = self.assertClean(section)
        self.assertIn('<span class="pd-big-value">\u2014</span>', section)
        self.assertIn("No live price has come in for NOQUOTE yet", text)
        self.assertIn("Price now \u2014 no live price yet", text)
        self.assertIn("Position size 75.30 USD 3 shares at the entry price",
                      text)
        self.assertIn("It closes by itself at the stop 24.00 or the target "
                      "28.00.", text)
        self.assertIn('id="pdCloseBtn"', page)


# ── D3: the close, through the endpoints the positions page uses ─────────

class CloseButtonTests(_Base):
    username = "pp_close"

    def test_the_button_reaches_the_existing_endpoints(self):
        trade = _trade(self.user)
        page, _section_ = self.get(trade)
        preview = "/positions/%d/close/preview/" % trade.id
        close = "/positions/%d/close/" % trade.id
        self.assertIn('data-preview-url="%s"' % preview, page)
        self.assertIn('data-close-url="%s"' % close, page)
        self.assertEqual(resolve(preview).url_name, "close_position_preview")
        self.assertEqual(resolve(close).url_name, "close_position_execute")
        self.assertIn(">Close this position</button>", page)
        # One close, never all of them.
        top = page.split('id="pdTech"', 1)[0]
        self.assertNotIn("close-all", top.split('data-pd-live="summary"', 1)[1])

    def test_the_script_posts_json_with_the_csrf_token_and_guards_a_double_tap(self):
        page, _s = self.get(_trade(self.user))
        self.assertIn('name="csrfmiddlewaretoken"', page)
        self.assertIn('headers: {"X-CSRFToken": csrf(), '
                      '"Content-Type": "application/json"}', page)
        self.assertIn('{pin: pin ? pin.value : ""}', page)
        self.assertIn("if (sending || ok.disabled) return;", page)
        self.assertIn("ok.disabled = true;", page)
        self.assertIn('post(btn.getAttribute("data-preview-url"), {})', page)

    def test_the_csrf_round_trip_reaches_the_close_endpoint(self):
        """The token the page carries is the one the endpoint accepts; the
        close itself is patched, so nothing is sent anywhere."""
        trade = _trade(self.user)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        page = strict.get(PAGE % trade.id).content.decode("utf-8")
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',
                          page).group(1)
        url = "/positions/%d/close/" % trade.id
        with mock.patch("bot_program.manual_close.execute_close",
                        return_value={"ok": True, "trade_id": trade.id,
                                      "symbol": "EURCAD", "side": "BUY",
                                      "qty": 1000.0, "exit": 1.6103,
                                      "pnl": 14.4, "r": 0.23,
                                      "outcome": "manual_close"}) as ex:
            refused = strict.post(url, data="{}",
                                  content_type="application/json")
            self.assertEqual(refused.status_code, 403)
            self.assertFalse(ex.called)
            answered = strict.post(url, data=json.dumps({"pin": ""}),
                                   content_type="application/json",
                                   HTTP_X_CSRFTOKEN=token)
        self.assertEqual(answered.status_code, 200)
        self.assertTrue(answered.json()["ok"])
        self.assertEqual(ex.call_count, 1)

    def test_the_pin_field_is_there_only_when_the_endpoint_will_ask(self):
        paper_page, _s = self.get(_trade(self.user))
        self.assertNotIn('id="pdClosePin"', paper_page)
        self.assertIn("This is a simulated position: no real money moves.",
                      paper_page)
        live_page, _s = self.get(_trade(self.user, paper=False))
        self.assertIn('id="pdClosePin"', live_page)
        self.assertIn('<label for="pdClosePin">Your trading PIN</label>',
                      live_page)

    def test_a_working_order_and_a_pending_close_use_the_endpoints_words(self):
        working = _trade(self.user, paper=False,
                         metadata={"entry_working": True})
        page, section = self.get(working)
        self.assertIn(">Withdraw this order</button>", page)
        self.assertIn('pd-chip-working">Order waiting</span>', section)
        self.assertIn('data-pd-kind="working"', section)
        text = self.assertClean(section)
        # Said once, and nothing reads as if the position were held.
        self.assertEqual(text.count("Nothing has filled yet"), 1, text)
        self.assertIn("Waiting for less than a minute", text)
        self.assertIn("Order price 1.59030 placed ", text)
        self.assertNotIn("Entry price", text)
        self.assertIn("Order size 1,159.42 USD", text)
        self.assertNotIn("Held for", text)
        self.assertIn("If it fills, it carries 45.79 USD of risk: the loss "
                      "at its stop.", text)
        self.assertNotIn("It carries", text)
        pending = _trade(self.user, paper=False, status="CLOSE_PENDING",
                         metadata={"close_retry_attempts": 2})
        page, section = self.get(pending)
        self.assertIn(">Retry the close</button>", page)
        self.assertIn("the broker refused 2 times", _visible(section))


@unittest.skipUnless(NODE, "node is not installed")
class DialogWordsTests(_Base):
    """The dialog's sentences, run under node exactly as the page ships
    them — the preview's JSON in, the words the father reads out."""
    username = "pp_words"

    def _run(self, calls):
        page, _s = self.get(_trade(self.user))
        src = [b for b in re.findall(r"<script>(.*?)</script>", page, re.S)
               if "root.pdWords" in b]
        self.assertEqual(len(src), 1)
        info = {"headline": "Long EURCAD", "decimals": 5, "ccy": "USD"}
        prog = ("var window = {};\n" + src[0] + "\nvar info = "
                + json.dumps(info) + ";\nprocess.stdout.write(JSON.stringify(["
                + ",".join(calls) + "]));\n")
        tmp = Path(tempfile.mkdtemp(prefix="pd-words-"))
        (tmp / "words.js").write_text(prog, encoding="utf-8")
        out = subprocess.run([NODE, str(tmp / "words.js")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_the_preview_in_plain_words(self):
        close, withdraw, retry, refused, shut = self._run([
            'window.pdWords.preview({"action": "close", "mark": 1.6103, '
            '"exit": 1.6103, "pnl": 17.38, "r": 0.04, "requires_pin": false}, info)',
            'window.pdWords.preview({"action": "withdraw", "working": true}, info)',
            'window.pdWords.preview({"action": "retry", "pending": true}, info)',
            'window.pdWords.preview({"error": "No usable price mark for EURCAD"}, info)',
            'window.pdWords.preview({"error": "EURCAD: the forex market is shut '
            '(reopens Sunday 21:00 UTC) — no paper exit. The position stays '
            'OPEN and nothing was booked", "market_shut": true}, info)',
        ])
        self.assertFalse(shut["ok"])
        self.assertEqual(shut["title"], "The market is shut")
        self.assertTrue(shut["text"].endswith("nothing was booked."))
        self.assertEqual(close["text"], "Close Long EURCAD now at about "
                                        "1.61030? Result about +17.38 USD.")
        self.assertTrue(close["ok"])
        self.assertIn("Withdraw the Long EURCAD order now?", withdraw["text"])
        self.assertIn("Retry closing Long EURCAD?", retry["text"])
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["text"], "No usable price mark for EURCAD.")

    def test_a_locked_screen_and_a_preview_with_no_price_are_not_offers(self):
        locked, no_price, answered = self._run([
            'window.pdWords.preview({"pin_locked": true}, info)',
            'window.pdWords.preview({"action": "close"}, info)',
            'window.pdWords.answer({"pin_locked": true}, info)',
        ])
        self.assertFalse(locked["ok"])
        self.assertEqual(locked["title"], "The screen is locked")
        self.assertFalse(no_price["ok"])
        self.assertNotIn("\u2014", no_price["text"])
        self.assertFalse(answered["done"])
        self.assertTrue(answered["text"].startswith("Not closed. The screen "
                                                    "is locked"))

    def test_the_answer_closed_refused_or_pending(self):
        closed, refused, pending = self._run([
            'window.pdWords.answer({"ok": true, "exit": 1.6103, "pnl": -2.5}, info)',
            'window.pdWords.answer({"error": "EURCAD is a LIVE position \u2014 '
            'the trading PIN is required to close it. Nothing was closed"}, info)',
            'window.pdWords.answer({"error": "The broker rejected the close", '
            '"pending": true}, info)',
        ])
        self.assertEqual(closed["text"], "Done. Long EURCAD is closed at "
                                         "1.61030. Result -2.50 USD.")
        self.assertTrue(closed["done"])
        self.assertTrue(refused["text"].startswith("Not closed. EURCAD is a "
                                                   "LIVE position"))
        self.assertTrue(refused["text"].endswith("Nothing was closed."))
        self.assertEqual(pending["text"], "Not closed yet. The broker "
                                          "rejected the close.")


class BrokerLevelsTests(_Base):
    """"It closes by itself" only where it is true: in the platform's own
    simulator, or at a broker that holds a resting stop ("protected", the
    engine's own fact). A broker row without one is closed by Sauron's
    engine alone, and the page says so."""
    username = "pp_levels"

    def _aapl(self, **meta):
        _instrument("AAPL", "stock", "NASDAQ")
        stamps = {"broker": "ibkr", "broker_env": "live",
                  "value_per_unit": 1.0}
        stamps.update(meta)
        return _trade(self.user, symbol="AAPL", asset_class="stock",
                      side="SELL", qty="2", entry="230", stop="236",
                      target="215", paper=False, rule="golden_cross",
                      metadata=stamps)

    def test_a_broker_row_without_a_resting_stop_says_sauron_closes_it(self):
        _page, section = self.get(self._aapl())
        text = self.assertClean(section)
        self.assertIn("Sauron closes it at the stop 236.00", text)
        self.assertIn("as long as Sauron itself is running; the broker does not hold these "
                      "levels.", text)
        self.assertNotIn("closes by itself", text)

    def test_a_protected_broker_row_closes_by_itself(self):
        _page, section = self.get(self._aapl(protected=True))
        text = _visible(section)
        self.assertIn("It closes by itself at the stop 236.00", text)
        self.assertIn("The broker holds these levels, so they work even when "
                      "Sauron is offline.", text)

    def test_the_etoro_demo_is_at_a_broker_too(self):
        trade = _trade(self.user, paper=False,
                       metadata={"broker": "etoro", "broker_env": "paper"})
        _page, section = self.get(trade)
        text = _visible(section)
        self.assertIn("Sauron closes it at the stop 1.52670", text)
        self.assertIn("the broker does not hold these levels.", text)

    def test_a_stop_alone_at_a_broker_is_this_level(self):
        trade = _trade(self.user, paper=False, target=None,
                       metadata={"broker": "etoro", "broker_env": "live"})
        _page, section = self.get(trade)
        self.assertIn("as long as Sauron itself is running; the broker does not hold this "
                      "level. No target is set.", _visible(section))

    def test_a_paper_row_still_closes_by_itself(self):
        _page, section = self.get(_trade(self.user))
        self.assertIn("It closes by itself at the stop 1.52670",
                      _visible(section))


class OlderForexRowTests(_Base):
    """A forex row opened before value_per_unit was stamped is marked in the
    pair's QUOTE currency by the positions page's own reader. The number is
    that reader's; the page labels it with the currency it is really in."""
    username = "pp_fx_legacy"

    def test_a_yen_profit_is_labelled_in_yen_with_a_note(self):
        inst = _instrument("GBPJPY")
        _quote(inst, "190.10")
        trade = _trade(self.user, symbol="GBPJPY", entry="189.00",
                       stop="187.00", target="193.00",
                       metadata={"value_per_unit": None})
        _page, section = self.get(trade)
        text = self.assertClean(section)
        self.assertIn('<span class="pd-big-value">+1,100.00 JPY</span>',
                      section)
        self.assertIn("Position size 190,100.00 JPY", text)
        self.assertIn("so its profit or loss and its size are shown in JPY, "
                      "not USD.", text)

    def test_a_stamped_row_and_a_usd_quote_are_untouched(self):
        _page, section = self.get(_trade(self.user))
        self.assertNotIn("conversion rate", _visible(section))
        inst = _instrument("EURUSD")
        _quote(inst, "1.1010")
        trade = _trade(self.user, symbol="EURUSD", entry="1.1000",
                       stop="1.0900", target="1.1200",
                       metadata={"value_per_unit": None})
        _page, section = self.get(trade)
        self.assertIn("+1.00 USD", section)
        self.assertNotIn("conversion rate", _visible(section))

    def test_a_closed_older_row_labels_its_size_only(self):
        inst = _instrument("GBPJPY")
        _quote(inst, "190.10")
        trade = _trade(self.user, symbol="GBPJPY", entry="189.00",
                       stop="187.00", target="193.00", status="CLOSED",
                       exit_price=Decimal("190.10"), pnl=Decimal("7.40"),
                       outcome="hit_target", closed_at=timezone.now(),
                       metadata={"value_per_unit": None})
        _page, section = self.get(trade)
        text = self.assertClean(section)
        self.assertIn('<span class="pd-big-value">+7.40 USD</span>', section)
        self.assertIn("Position size 189,000.00 JPY", text)
        self.assertIn("so its size is shown in JPY, not USD.", text)


# ── the close and the live refresh, run under node on a stub page ────────

FLOW_PRELUDE = r"""
var out = {};
var timers = [];
var intervals = [];
var reloads = 0;
var calls = [];
function mk(id, attrs) {
    return {id: id, hidden: false, disabled: false, textContent: "",
            value: "", className: "", attrs: attrs || {}, _l: {},
            getAttribute: function (k) {
                return Object.prototype.hasOwnProperty.call(this.attrs, k)
                    ? this.attrs[k] : null; },
            addEventListener: function (t, f) {
                (this._l[t] = this._l[t] || []).push(f); },
            fire: function (t, e) {
                var self = this;
                (this._l[t] || []).forEach(function (f) { f(e || {target: self}); }); },
            click: function () { this.fire("click", {target: this}); },
            focus: function () {},
            querySelector: function () { return null; }};
}
var parent = {replaceChild: function (n) { liveRegion = n; n.parentNode = parent; }};
function mkRegion(state, kind) {
    var r = mk("region", {"data-pd-live": "summary", "data-pd-state": state,
                          "data-pd-kind": kind,
                          "data-pd-live-url": "/forensics/1/live/"});
    r.parentNode = parent;
    return r;
}
var liveRegion = mkRegion("open", "open");
var els = {};
["pdCloseDialog", "pdCloseTitle", "pdCloseText", "pdCloseAnswer",
 "pdCloseConfirm", "pdCloseCancel", "pdLiveStatus"].forEach(function (id) {
    els[id] = mk(id); });
els.pdCloseDialog.hidden = true;
els.pdCloseAnswer.hidden = true;
els.pdLiveStatus.hidden = true;
els.pdCloseConfirm.disabled = true;
els.pdCloseDialog.querySelector = function () { return {value: "tok"}; };
els.pdCloseBtn = mk("pdCloseBtn", {
    "data-preview-url": "/positions/1/close/preview/",
    "data-close-url": "/positions/1/close/", "data-headline": "Long EURCAD",
    "data-decimals": "5", "data-ccy": "USD"});
els.pdCloseBtn.textContent = "Close this position";
var docL = {};
var document = {
    hidden: false, cookie: "", activeElement: null,
    body: {appendChild: function () {}},
    querySelector: function () { return liveRegion; },
    getElementById: function (id) { return els[id] || null; },
    addEventListener: function (t, f) { (docL[t] = docL[t] || []).push(f); },
    importNode: function (n) { return n; }
};
function DOMParser() {}
DOMParser.prototype.parseFromString = function (text) {
    var o = JSON.parse(text);
    return {querySelector: function () { return mkRegion(o.state, o.kind); }};
};
var window = globalThis;
window.location = {reload: function () { reloads += 1; }};
globalThis.setTimeout = function (f, ms) { timers.push(ms); };
globalThis.setInterval = function (f, ms) { intervals.push({f: f, ms: ms}); };
function fetch(url, opts) {
    var c = {url: url, opts: opts || {}};
    c.p = new Promise(function (res, rej) { c.res = res; c.rej = rej; });
    calls.push(c);
    return c.p;
}
function reply(c, body) {
    var text = JSON.stringify(body);
    c.res({ok: true, status: 200, redirected: false,
           text: function () { return Promise.resolve(text); }});
}
function tick() { return new Promise(function (r) { setImmediate(r); }); }
async function settle() { await tick(); await tick(); await tick(); }
"""

FLOW_CLOSE = r"""
(async function () {
    var btn = els.pdCloseBtn, dlg = els.pdCloseDialog;
    var ok = els.pdCloseConfirm, cancel = els.pdCloseCancel;
    btn.click();
    out.previewsAsked = calls.length;
    out.openWhileAsking = !dlg.hidden;
    cancel.click();
    out.cancelWorksWhileAsking = dlg.hidden;
    out.buttonBack = !btn.disabled;
    reply(calls[0], {action: "close", mark: 1.6103, exit: 1.6103, pnl: 17.38});
    await settle();
    out.lateAnswerDropped = dlg.hidden && ok.disabled;
    btn.click();
    btn.click();
    out.previewsAfterDoubleTap = calls.length;
    docL.keydown.forEach(function (f) { f({key: "Escape"}); });
    out.escapeWorksWhileAsking = dlg.hidden;
    btn.click();
    reply(calls[2], {action: "close", mark: 1.6103, exit: 1.6103, pnl: 17.38});
    await settle();
    out.offer = els.pdCloseText.textContent;
    out.confirmOn = !ok.disabled;
    ok.click();
    ok.click();
    out.closePosts = calls.filter(function (c) {
        return c.url === "/positions/1/close/"; }).length;
    out.closeHeaders = calls[3].opts.headers;
    out.closeBody = calls[3].opts.body;
    cancel.click();
    docL.keydown.forEach(function (f) { f({key: "Escape"}); });
    out.heldOpenWhileSending = !dlg.hidden;
    intervals[0].f();
    out.callsAfterTickUnderDialog = calls.length;
    reply(calls[3], {ok: true, exit: 1.6103, pnl: 14.4});
    await settle();
    out.answer = els.pdCloseAnswer.textContent;
    out.forcedRefresh = calls.length === 5 && calls[4].url === "/forensics/1/live/";
    out.reloadTimers = timers;
    out.reloads = reloads;
    process.stdout.write(JSON.stringify(out));
})();
"""

FLOW_LIVE = r"""
(async function () {
    liveRegion = mkRegion("open", "working");
    out.everyMs = intervals[0].ms;
    intervals[0].f();
    out.asked = calls.length;
    out.header = (calls[0].opts.headers || {})["X-Requested-With"];
    reply(calls[0], {state: "open", kind: "working"});
    await settle();
    out.reloadsWhenSame = reloads;
    intervals[0].f();
    els.pdCloseDialog.hidden = false;       /* opened while it was on its way */
    reply(calls[1], {state: "closed", kind: "closed"});
    await settle();
    out.droppedUnderDialog = reloads === 0
        && liveRegion.getAttribute("data-pd-state") === "open";
    intervals[0].f();
    out.noTickUnderDialog = calls.length === 2;
    els.pdCloseDialog.hidden = true;
    intervals[0].f();
    reply(calls[2], {state: "open", kind: "open"});   /* the order filled */
    await settle();
    out.reloadsOnKindChange = reloads;
    document.hidden = true;
    intervals[0].f();
    out.noTickWhileHidden = calls.length === 3;
    process.stdout.write(JSON.stringify(out));
})();
"""


@unittest.skipUnless(NODE, "node is not installed")
class CloseFlowTests(_Base):
    """The page's own scripts, as shipped, driven under node against a stub
    page and a fetch whose answers the test releases one by one."""
    username = "pp_flow"

    def _run(self, scenario):
        page, _s = self.get(_trade(self.user))
        blocks = re.findall(r"<script>(.*?)</script>", page, re.S)
        wanted = [b for b in blocks if "root.pdWords" in b
                  or "var EVERY_MS" in b
                  or 'getElementById("pdCloseBtn")' in b]
        self.assertEqual(len(wanted), 3)
        prog = FLOW_PRELUDE + "\n".join(wanted) + scenario
        tmp = Path(tempfile.mkdtemp(prefix="pd-flow-"))
        (tmp / "flow.js").write_text(prog, encoding="utf-8")
        out = subprocess.run([NODE, str(tmp / "flow.js")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_the_preview_can_be_cancelled_and_the_close_cannot(self):
        r = self._run(FLOW_CLOSE)
        self.assertEqual(r["previewsAsked"], 1)
        self.assertTrue(r["openWhileAsking"])
        self.assertTrue(r["cancelWorksWhileAsking"])
        self.assertTrue(r["buttonBack"])
        self.assertTrue(r["lateAnswerDropped"])
        self.assertEqual(r["previewsAfterDoubleTap"], 2)
        self.assertTrue(r["escapeWorksWhileAsking"])
        self.assertEqual(r["offer"], "Close Long EURCAD now at about 1.61030? "
                                     "Result about +17.38 USD.")
        self.assertTrue(r["confirmOn"])
        self.assertEqual(r["closePosts"], 1)
        self.assertEqual(r["closeHeaders"]["X-CSRFToken"], "tok")
        self.assertEqual(json.loads(r["closeBody"]), {"pin": ""})
        self.assertTrue(r["heldOpenWhileSending"])
        self.assertEqual(r["callsAfterTickUnderDialog"], 4)
        self.assertEqual(r["answer"], "Done. Long EURCAD is closed at 1.61030. "
                                      "Result +14.40 USD.")
        self.assertTrue(r["forcedRefresh"])
        self.assertEqual(r["reloadTimers"], [2500])
        self.assertEqual(r["reloads"], 0)

    def test_the_timer_never_lands_under_the_dialog(self):
        r = self._run(FLOW_LIVE)
        self.assertEqual(r["everyMs"], 15000)
        self.assertEqual(r["asked"], 1)
        self.assertEqual(r["header"], "XMLHttpRequest")
        self.assertEqual(r["reloadsWhenSame"], 0)
        self.assertTrue(r["droppedUnderDialog"])
        self.assertTrue(r["noTickUnderDialog"])
        self.assertEqual(r["reloadsOnKindChange"], 1)
        self.assertTrue(r["noTickWhileHidden"])


# ── D4: the technical record, folded ─────────────────────────────────────

class TechnicalDetailsTests(_Base):
    username = "pp_tech"

    def test_everything_is_still_there_folded_and_closed_by_default(self):
        trade = _trade(self.user, metadata={"fill_source": "broker",
                                            "protected": True,
                                            "protective_order_ids": ["a"]})
        page, _s = self.get(trade)
        self.assertIn('<details class="pd-tech" id="pdTech">', page)
        self.assertNotRegex(page, r'<details class="pd-tech" id="pdTech"\s+open')
        folded = page.split('<details class="pd-tech" id="pdTech">', 1)[1]
        folded = folded.split("</details>", 1)[0]
        for title in ("Technical details", "Lifecycle", "Why it fired",
                      "Signals it saw", "Sizing &amp; rule state",
                      "Orchestrator gate decisions", "Audit trail",
                      "Raw metadata", "oc-strip", "Entry filled",
                      "broker fill", "Broker-side protection"):
            self.assertIn(title, folded)
        # The summary comes first.
        self.assertLess(page.index('data-pd-live="summary"'),
                        page.index('id="pdTech"'))


# ── D5: a phone ──────────────────────────────────────────────────────────

class PhoneTests(_Base):
    """A test has no viewport; what it can hold is the set of rules that
    keep a page inside 360px — the same kind of pin
    tests/test_card_responsiveness.py and test_position_detail.py make."""
    username = "pp_phone"

    def setUp(self):
        super().setUp()
        self.page, _s = self.get(_trade(self.user))
        self.css = _page_style(self.page)

    def test_no_floor_is_wider_than_a_360px_screen(self):
        for prop, px in re.findall(r"(?<![-\w])(min-width|width)\s*:\s*(\d+)px",
                                   self.css):
            self.assertLessEqual(int(px), 360, prop)
        for track in re.findall(r"grid-template-columns\s*:\s*([^;]+);",
                                self.css):
            self.assertIn("minmax(0, 1fr)", track)
        self.assertIn("overflow-wrap: anywhere", self.css.split(".pd-sum {", 1)[1]
                      .split("}", 1)[0])

    def test_the_phone_layout_and_the_close_bar_at_the_bottom(self):
        phone = self.css.split("@media (max-width: 768px) {", 1)[1]
        self.assertIn(".pd-facts { grid-template-columns: repeat(2, "
                      "minmax(0, 1fr)); }", phone)
        bar = phone.split(".pd-closebar {", 1)[1].split("}", 1)[0]
        self.assertIn("position: fixed", bar)
        self.assertIn("bottom: 0", bar)
        # Above the signals rail the shell keeps on a phone (--z-rail) —
        # which only holds once .page-content stops being a stacking
        # context (its fade-in fills forwards).
        self.assertIn("z-index: calc(var(--z-rail, 600) + 1)", bar)
        self.assertIn(".page-content:has(#pdCloseBtn) { "
                      "animation-fill-mode: none; }", phone)
        self.assertIn(".pd-closebar-space { display: block;", phone)
        # The room the fixed bar needs is at the END of the page, so the
        # last line of the technical record is never under the button.
        opens = self.page.index('<details class="pd-tech"')
        self.assertGreater(self.page.index('class="pd-closebar-space"'),
                           self.page.index("</details>", opens))

    def test_the_tap_targets_are_big(self):
        for selector in (".pd-close-btn {", ".pd-dialog-actions button {",
                         ".pd-pin input {", ".pd-tech > summary {"):
            block = self.css.split(selector, 1)[1].split("}", 1)[0]
            height = re.search(r"min-height:\s*(\d+)px", block)
            self.assertIsNotNone(height, selector)
            self.assertGreaterEqual(int(height.group(1)), 48, selector)

    def test_the_shells_page_takes_a_phones_whole_width(self):
        """sauron.css caps .main-content at 100vw minus the sidebar; the
        phone block lifted the margin but not the cap, so a 360px screen
        got a 100px column (measured in a browser at 360x780)."""
        from django.conf import settings
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
               ).read_text(encoding="utf-8")
        block = css.split("/* ── Mobile Responsive ───────────────────── */",
                          1)[1][:1500]
        self.assertIn(".main-content { margin-left: 0 !important; "
                      "max-width: 100vw !important; }", block)

    def test_the_floating_buttons_clear_the_close_bar(self):
        phone = self.css.split("@media (max-width: 768px) {", 1)[1]
        lift = phone.split("html.pd-js body:has(#pdCloseBtn) {", 1)[1]
        self.assertIn("--se-bottom-edge: calc(89px", lift.split("}", 1)[0])
        panel = phone.split("html.pd-js body:has(#pdCloseBtn):has("
                            ".info-panel-wrap:not(.minimized)) {", 1)[1]
        self.assertIn("--se-bottom-edge: calc(149px", panel.split("}", 1)[0])

    def test_the_topbar_keeps_a_short_title_on_a_phone(self):
        self.assertIn('<span class="topbar-title">\u25ce <span class='
                      '"pd-title-long">Long EURCAD \u00b7 </span>Position #',
                      self.page)
        phone = self.css.split("@media (max-width: 768px) {", 1)[1]
        self.assertIn(".pd-title-long { display: none; }", phone)
        self.assertIn(".topbar-title { white-space: nowrap;", phone)

    def test_without_javascript_nothing_promises_what_only_it_does(self):
        head = self.page.split("<body", 1)[0]
        self.assertIn('<script>document.documentElement.classList.add('
                      '"pd-js");</script>', head)
        self.assertIn(".pd-closebar { display: none;", self.css)
        self.assertIn("html.pd-js .pd-closebar { display: block; }", self.css)
        self.assertIn(".pd-refresh-note { display: none; }", self.css)
        self.assertIn('<span class="pd-refresh-note">Refreshes by itself',
                      self.page)
        self.assertIn("<noscript><p class=\"pd-note pd-note-warn\">Closing "
                      "from this page needs JavaScript", self.page)

    def test_colours_are_the_theme_tokens_and_layers_the_ladder(self):
        for z in re.findall(r"z-index\s*:\s*([^;]+);", self.css):
            self.assertRegex(z.strip(), r"^(calc\()?var\(--z-", z)
        self.assertIn("var(--bg-card)", self.css)
        self.assertIn("var(--text-primary)", self.css)
        self.assertNotIn("<script src=", self.page.split('id="pdTech"', 1)[0]
                         .split('data-pd-live="summary"', 1)[1])
