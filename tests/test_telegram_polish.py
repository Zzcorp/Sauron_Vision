"""The Telegram polish (2026-09-27): what the Telegram v2 critic left.

Pinned here, requests.post patched (no real HTTP):
  * the track-record decay in words: the rule read aloud, its results in
    multiples of the risk, the triggers in words, the rule's key folded
    as code, the strategies button;
  * ONE message for a stop the venue rewrote: the fill message names it;
    the staff alert goes only where no fill message does (a fill message
    not delivered, or whose notifier raised);
  * the Eye's position line at the instrument's decimals, the quantity
    trimmed, the stop the venue holds named as the fill message names it;
    eye.price untouched (Morgul prints with it);
  * the manual lane, the orchestrator's refusal and the evidence chain in
    words: no snake_case outside a code key, the account's currency, one
    summary sentence, a button;
  * the fills' bell titles and bodies, and the e-mail and Discord copies,
    from the message; the bell's title dedupes (the drawdown, a refused
    close) still working;
  * a close's money with its currency wherever it is known;
  * a rounding under the instrument's tick never called a moved stop
    (venue_moved_stop), in the engine and in the hand lane; eToro's "no
    stop" still one.

Run with:  python manage.py test tests.test_telegram_polish
"""
import inspect
import os
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from tests.test_telegram_v2 import (ENV, HOST, _Base, _button, _cfg,
                                    _eurcad, _eurusd_attack, _ok, _payloads,
                                    _trade, jargon)

GREEN = chr(0x1F7E2)
GAIN = chr(0x2705)
MINUS = chr(0x2212)
DECAY = chr(0x2198) + chr(0xFE0F)
BLOCKED = chr(0x26D4)
LANE_LIVE = chr(0x1F534)
LANE_PAPER = chr(0x1F4C4)
COLD = chr(0x2744) + chr(0xFE0F)
HAND = chr(0x270B)

BTC_MOVED = ("Stop moved by eToro: it holds 75745.80, not the 79934.97 "
             "sent (10.0% below the entry)")


def _bell(user=None, **filters):
    from alerts.models import Notification
    qs = Notification.objects.all()
    if user is not None:
        qs = qs.filter(user=user)
    return qs.filter(**filters).order_by("pk")


# ── P1: the decay, in words ──────────────────────────────────────────────

class TheDecayTests(_Base):
    def test_the_decay_reads_in_words_with_the_strategies_button(self):
        from bot_program.notifications import notify_track_record_decay
        p = self._send(lambda: notify_track_record_decay(
            self.user, rule_name="golden_cross", asset_class="stock",
            recent_avg_r=-0.2, baseline_avg_r=0.4, recent_n=12,
            triggers=["avg_r_drop", "gone_negative"]), domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{DECAY} Golden cross is losing its edge</b>",
            f"Over its last 12 trades it made {MINUS}0.20 times the risk, "
            f"against +0.40 before.",
            "",
            f"Last 12 trades: {MINUS}0.20 times the risk per trade, on "
            f"average",
            "Before: +0.40 times the risk per trade, on average",
            "Flagged because: the average result fell sharply and the "
            "average trade now loses",
            "Market: Stocks",
            "<blockquote expandable>Rule key: <code>golden_cross</code>"
            "</blockquote>"]))
        self.assertEqual(p["reply_markup"],
                         _button("/strategies/", "Open strategies"))
        self.assertEqual(jargon(p["text"]), [])
        n = _bell(self.user).get()
        self.assertEqual(n.title, "▲ Golden cross is losing its edge")
        self.assertEqual(n.body, f"Over its last 12 trades it made "
                                 f"{MINUS}0.20 times the risk, against "
                                 f"+0.40 before.")
        self.assertEqual(n.url, "/bot-performance/")
        self.assertNotIn("golden_cross", " ".join(n.data["items"]))

    def test_one_trade_a_rule_that_is_no_strategy_and_an_unknown_trigger(
            self):
        from bot_program.notifications import notify_track_record_decay
        p = self._send(lambda: notify_track_record_decay(
            self.user, rule_name="manual", asset_class="etf",
            recent_avg_r=0.0, baseline_avg_r=1.234, recent_n=1,
            triggers=["new_trigger"]))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{DECAY} A rule is losing its "
                                   f"edge</b>")
        self.assertEqual(lines[1], "Over its last 1 trade it made 0.00 "
                                   "times the risk, against +1.23 before.")
        self.assertIn("Flagged because: new trigger", lines)
        self.assertIn("Market: ETFs", lines)
        self.assertEqual(jargon(p["text"]), [])


# ── P4: the manual lane, the orchestrator, the evidence chain ────────────

class TheManualLaneTests(_Base):
    def test_armed_live_reads_in_words_in_the_accounts_currency(self):
        from bot_program.notifications import notify_manual_lane_mode
        p = self._send(lambda: notify_manual_lane_mode(
            self.user, asset_class="stock", mode="live", capital=2000,
            currency="USD"), domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{LANE_LIVE} Hand-taken trades in stocks now use real "
            f"money</b>",
            "From now on, a TAKE TRADE in stocks places a real order at the "
            "broker, from a pool of 2,000.00 USD.",
            "",
            "Money: real, at the broker",
            "Pool: 2,000.00 USD"]))
        self.assertEqual(p["reply_markup"],
                         _button("/positions/", "Open positions"))
        n = _bell(self.user).get()
        self.assertEqual(n.title,
                         "◆ Hand-taken trades in stocks now use real money")
        self.assertNotIn("$", n.body + " ".join(n.data["items"]))

    def test_back_to_simulated_and_a_pool_without_a_currency(self):
        from bot_program.notifications import notify_manual_lane_mode
        p = self._send(lambda: notify_manual_lane_mode(
            self.user, asset_class="forex", mode="paper"))
        self.assertEqual(p["text"], "\n".join([
            f"<b>{LANE_PAPER} Hand-taken trades in forex are back on "
            f"simulated money</b>",
            "From now on, a TAKE TRADE in forex books a simulated trade; no "
            "real money moves.",
            "",
            "Money: simulated, for rehearsal only"]))
        p = self._send(lambda: notify_manual_lane_mode(
            self.user, asset_class="crypto", mode="live", capital=500))
        self.assertIn("Pool: 500.00", p["text"].split("\n"))
        self.assertNotIn("$", p["text"])

    def test_the_lane_hands_the_manual_configs_currency(self):
        from bot_program import manual_trade
        src = inspect.getsource(manual_trade.arm_manual_lane)
        self.assertIn("currency=str(cfg.base_currency", src)


class TheOrchestratorTests(_Base):
    def _refused(self, reason, *, symbol="NVDA", side="BUY",
                 asset_class="stock", domain=""):
        from bot_program.notifications import notify_orchestrator_reject
        return self._send(lambda: notify_orchestrator_reject(
            self.user, asset_class=asset_class, symbol=symbol, side=side,
            reason=reason), domain=domain)

    def test_a_theme_cap_reads_as_what_the_trade_would_have_done(self):
        p = self._refused("orchestrator: equity theme cap |+3.0| > 2.0 "
                          "(was |+2.0|, ++1.0)", domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{BLOCKED} Buying NVDA was blocked</b>",
            "Sauron did not buy NVDA: it would take the stock market "
            "exposure to +3.0, past its cap of 2.0.",
            "",
            "Limit: stock market exposure, at most 2.0",
            "After this trade: +3.0",
            "Before this trade: +2.0",
            "Market: Stocks",
            "No order was sent",
            "<blockquote expandable>Gate reason: <code>orchestrator: equity "
            "theme cap |+3.0| &gt; 2.0 (was |+2.0|, ++1.0)</code>"
            "</blockquote>"]))
        self.assertEqual(p["reply_markup"],
                         _button("/eye/exposure/", "Open exposure"))
        self.assertEqual(jargon(p["text"]), [])
        n = _bell(self.user).get()
        self.assertEqual(n.title, "✕ Buying NVDA was blocked")
        self.assertEqual(n.url, "/eye/")
        self.assertTrue(n.body.startswith("Sauron did not buy NVDA: "))

    def test_a_currency_a_sector_and_a_reason_of_another_shape(self):
        p = self._refused("orchestrator: USD currency cap |+3.2| > 3.0",
                          symbol="EURCAD", side="SELL", asset_class="forex")
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{BLOCKED} Selling EURCAD short was "
                                   f"blocked</b>")
        self.assertEqual(lines[1], "Sauron did not sell EURCAD short: it "
                                   "would take the USD exposure to +3.2, "
                                   "past its cap of 3.0.")
        self.assertIn("Market: Forex", lines)
        p = self._refused("orchestrator: usd theme cap |-4.1| > 4.0 (was "
                          "|-3.5|, +-0.6)")
        self.assertIn("Sauron did not buy NVDA: it would take the exposure "
                      f"to the US dollar across markets to {MINUS}4.1, past "
                      "its cap of 4.0.", p["text"])
        p = self._refused("orchestrator: tech sector cap 4 > 3",
                          symbol="MSFT")
        lines = p["text"].split("\n")
        self.assertEqual(lines[1], "Sauron did not buy MSFT: it would make 4 "
                                   "positions in the tech sector, past its "
                                   "cap of 3.")
        self.assertIn("Limit: at most 3 positions in the tech sector", lines)
        p = self._refused("orchestrator: vol_regime_gate closed",
                          symbol="MSFT")
        lines = p["text"].split("\n")
        self.assertEqual(lines[1], "Sauron did not buy MSFT: the exposure "
                                   "limits held it back.")
        self.assertIn("Reason: vol regime gate closed", lines)
        for text in [p["text"]]:
            self.assertEqual(jargon(text), [])


class TheEvidenceChainTests(_Base):
    def test_the_links_read_in_words_the_keys_only_folded(self):
        from bot_program.notifications import notify_evidence_chain_cold
        blocker = ("pipeline_promotion is off — the ladder that grades the "
                   "fills never runs, so the ladder will read n=0 after 90 "
                   "days and there will be nothing to show (turn it on at "
                   "/ops/)")
        p = self._send(lambda: notify_evidence_chain_cold(
            self.user, cold=["pipeline_promotion"], blockers=[blocker]),
            domain=HOST)
        self.assertEqual(p["text"], "\n".join([
            f"<b>{COLD} The evidence chain is broken at the promotion "
            f"pipeline</b>",
            "The promotion pipeline is not running, so the days passing now "
            "give the promotion ladder nothing to grade.",
            "",
            "Not running: the promotion pipeline (the ladder that grades the "
            "fills)",
            "First problem: the promotion pipeline is off — the ladder that "
            "grades the fills never runs, so the ladder will read no graded "
            "trades after 90 days and there will be nothing to show (turn it "
            "on at /ops/)",
            "A link that is off is a decision; a link with no row was never "
            "set up",
            "<blockquote expandable>Links: <code>pipeline_promotion</code>",
            f"Blocker: <code>{blocker}</code>",
            "Full check: <code>manage.py paper_readiness</code>"
            "</blockquote>"]))
        self.assertEqual(p["reply_markup"],
                         _button("/ops/", "Open ops page"))
        self.assertEqual(jargon(p["text"]), [])
        n = _bell(self.user).get()
        self.assertEqual(n.title, "▲ The evidence chain is broken at the "
                                  "promotion pipeline")
        self.assertEqual(jargon(n.title + "\n" + n.body + "\n"
                                + "\n".join(n.data["items"])), [])

    def test_several_links_and_none_named(self):
        from bot_program.notifications import notify_evidence_chain_cold
        p = self._send(lambda: notify_evidence_chain_cold(
            self.user, cold=["platform_master", "pipeline_signals"],
            blockers=[]))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{COLD} The evidence chain is broken "
                                   f"at the master switch and the signal "
                                   f"pipeline</b>")
        self.assertEqual(lines[1], "The master switch and the signal "
                                   "pipeline are not running, so the days "
                                   "passing now give the promotion ladder "
                                   "nothing to grade.")
        self.assertIn("Not running: the master switch (every scheduled "
                      "task)", lines)
        p = self._send(lambda: notify_evidence_chain_cold(
            self.user, cold=[], blockers=["no enabled config lists a "
                                          "symbol — nothing will be "
                                          "measured"]))
        lines = p["text"].split("\n")
        self.assertEqual(lines[0], f"<b>{COLD} The evidence chain is "
                                   f"broken</b>")
        self.assertIn("First problem: no enabled config lists a symbol — "
                      "nothing will be measured", lines)
        self.assertEqual(jargon(p["text"]), [])


# ── P5 P6: the bell rows, the copies, the currency ───────────────────────

class TheBellAndTheCopiesTests(_Base):
    def _open(self, row):
        from bot_program.notifications import notify_bot_fill_open
        return notify_bot_fill_open(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, entry_price=row.entry_price,
            rule_name=row.rule_name, trade=row, trade_id=row.id)

    def _channel(self, channel):
        profile = self.user.trader_profile
        profile.notify_channel = channel
        profile.save(update_fields=["notify_channel"])

    def test_the_fills_bell_rows_carry_the_new_title_and_summary(self):
        from bot_program.notifications import (notify_bot_fill_close,
                                               notify_manual_fill_open)
        row = _eurcad(_cfg(self.user, "forex", "FX trend"))
        self._send(lambda: self._open(row))
        n = _bell(self.user).get()
        self.assertEqual((n.title, n.body), (
            "◉ Bought EURCAD", "7,900 units at 1.60726 — about 9,269 USD."))
        n.delete()
        row.status, row.outcome = "CLOSED", "hit_target"
        row.exit_price, row.pnl = Decimal("1.61035"), Decimal("17.8400")
        row.save(update_fields=["status", "outcome", "exit_price", "pnl"])
        self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="forex", symbol="EURCAD", side="BUY",
            qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
            outcome=row.outcome, trade=row))
        n = _bell(self.user).get()
        self.assertEqual((n.title, n.body), (
            "⊕ Closed EURCAD · +17.84 USD", "Sold 7,900 units at 1.61035."))
        n.delete()
        self._send(lambda: notify_manual_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("3.00000000"), entry_price=Decimal("227.53000000")))
        self._send(lambda: notify_manual_fill_open(
            self.user, asset_class="stock", symbol="AAPL", side="SELL",
            qty=Decimal("1"), entry_price=None, working=True, live=True))
        rows = list(_bell(self.user))
        self.assertEqual([(r.title, r.body) for r in rows], [
            ("▸ Bought AAPL by hand", "3 shares at 227.53."),
            ("▸ Waiting to sell AAPL short",
             "The broker has the order for 1 share; nothing has filled yet, "
             "so no position is open.")])
        for r in rows:
            self.assertEqual(jargon(r.title + "\n" + r.body), [])
            for old in ("BUY", "SELL", "QUEUED", "TAKE TRADE", "qty"):
                self.assertNotIn(old, r.title + r.body)

    def test_the_email_copy_is_the_message_in_plain_text(self):
        self._channel("email")
        row = _eurcad(_cfg(self.user, "forex", "FX trend"))
        with patch("alerts.channels.email_alert.send_email_alert",
                   return_value=True) as mail:
            self.assertTrue(self._open(row))
        to, title, body = mail.call_args.args
        self.assertEqual((to, title), ("tg2_ops@x.io", "Bought EURCAD"))
        self.assertEqual(body, "\n".join([
            "Simulated",
            "7,900 units at 1.60726 — about 9,269 USD.",
            "",
            "Stop: 1.52689 (5.0% below)",
            "Target: 1.76798 (10.0% above)",
            "Risk if the stop is hit: 463.45 USD",
            "Why: Golden cross",
            "Page: /forensics/108/ on the platform"]))
        for old in ("FOREX", "qty", "7900.00000000", "1.60725571",
                    "golden_cross"):
            self.assertNotIn(old, title + body)

    def test_the_discord_copy_is_the_message_and_a_plain_caller_is_kept(
            self):
        from bot_program.notifications import dispatch_notification
        self._channel("discord")
        row = _eurcad(_cfg(self.user, "forex", "FX trend"))
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL":
                                     "https://discord.invalid/hook",
                                     "DOMAIN": HOST}), \
                patch("requests.post", return_value=_ok()) as post:
            self._open(row)
            dispatch_notification(self.user, "bot_fill_open",
                                  title="◉ Plain title", body="plain body")
        first, second = [c.kwargs["json"]["content"]
                         for c in post.call_args_list]
        self.assertTrue(first.startswith(
            "**Bought EURCAD**\nSimulated\n7,900 units at 1.60726 — about "
            "9,269 USD.\n\nStop: 1.52689 (5.0% below)"), first)
        self.assertTrue(first.endswith(
            f"Page: https://{HOST}/forensics/108/"), first)
        self.assertEqual(second, "**Plain title**\nplain body")

    def test_the_bells_title_dedupes_still_hold(self):
        from bot_program.notifications import (notify_drawdown_warning,
                                               notify_manual_close_refused)
        self._send(lambda: notify_drawdown_warning(
            self.user, asset_class="stock", config_name="ST",
            realized_pnl=-200.0, limit=-100.0, currency="USD"))
        self.assertTrue(_bell(self.user, title__startswith=(
            "▲ Drawdown limit reached")).exists())
        self._send(lambda: notify_manual_close_refused(
            self.user, asset_class="stock", symbol="MSFT", trade_id=None))
        self.assertFalse(self._send(lambda: notify_manual_close_refused(
            self.user, asset_class="stock", symbol="MSFT", trade_id=None),
            posts=0))
        self.assertEqual(_bell(self.user, title="✕ Close refused: MSFT")
                         .count(), 1)


class TheCurrencyTests(_Base):
    def test_a_close_without_a_row_says_the_currency_it_is_handed(self):
        from bot_program.notifications import notify_bot_fill_close
        p = self._send(lambda: notify_bot_fill_close(
            self.user, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), exit_price=Decimal("200"), pnl=Decimal("195"),
            outcome="hit_target", currency="USD"))
        self.assertEqual(p["text"].split("\n")[0],
                         f"<b>{GAIN} Closed AAPL · +195.00 USD</b>")
        self.assertIn("Result: +195.00 USD", p["text"].split("\n"))

    def test_a_close_whose_message_cannot_be_built_keeps_the_currency(self):
        from bot_program import notifications as N
        row = _eurcad(_cfg(self.user, "forex", "FX trend"), status="CLOSED",
                      exit_price=Decimal("1.61035"), pnl=Decimal("0.0020"),
                      outcome="manual_close")
        with patch.object(N, "fill_close_message",
                          side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.notifications", "ERROR"):
            p = self._send(lambda: N.notify_bot_fill_close(
                self.user, asset_class="forex", symbol="EURCAD", side="BUY",
                qty=row.qty, exit_price=row.exit_price, pnl=row.pnl,
                outcome=row.outcome, trade=row))
        n = _bell(self.user).get()
        self.assertEqual(n.title, "◯ Closed EURCAD · 0.00 USD")
        self.assertEqual(n.data["items"], ["Sold 7,900 units at 1.61035.",
                                           "Result: 0.00 USD"])
        self.assertEqual(p["text"].split("\n")[0],
                         f"<b>{chr(0x26AA)} Closed EURCAD · 0.00 USD</b>")
        self.assertEqual(jargon(p["text"]), [])

    def test_an_open_whose_message_cannot_be_built_reads_in_words(self):
        from bot_program import notifications as N
        with patch.object(N, "fill_open_message",
                          side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.notifications", "ERROR"):
            self._send(lambda: N.notify_bot_fill_open(
                self.user, asset_class="forex", symbol="EURUSD", side="SELL",
                qty=Decimal("1700.00000000"),
                entry_price=Decimal("1.17650000"), rule_name="ema_cross_4h"))
        n = _bell(self.user).get()
        self.assertEqual((n.title, n.body), (
            "◉ Sold short EURUSD",
            "1,700 units at 1.17650. Why: EMA cross 4h."))
        self.assertEqual(n.data["mark"], chr(0x1F534))


# ── P2: one message for a stop the venue rewrote ─────────────────────────

class OneMessageForAMovedStopTests(TestCase):
    """The real BTC fill (tests/test_etoro_client._real_btc_lookup) on the
    held path, _finish_working_entry: the owner is not staff, a staff user
    exists, so a staff alert and a fill message land on two users."""

    def setUp(self):
        cache.clear()
        from bot_program.models import AssetBotConfig, AssetBotTrade
        self.owner = User.objects.create_user("tgp_btc", password="x")
        self.staff = User.objects.create_user("tgp_staff", password="x",
                                              is_staff=True)
        cfg = AssetBotConfig.objects.create(
            user=self.owner, asset_class="crypto", name="REALBTC",
            mode="live", symbols=["BTCUSD"], capital=Decimal("2249.98"),
            enabled=True)
        self.trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("0.0002"), entry_price=Decimal("84142.07"),
            stop_loss=Decimal("79934.97"), take_profit=Decimal("88349.17"),
            status="OPEN", paper=False, broker_order_id="1596774178",
            rule_name="btc_rule",
            metadata={"entry_working": True, "qty_requested": 0.0002,
                      "protective_order_ids": [], "protected": False,
                      "initial_stop_loss": 79934.97})
        self.cfg = cfg

    def _fill(self, held=75745.8):
        from bot_program.asset_engine.crypto_bot import CryptoBot
        from tests.test_etoro_client import (_client, _lookup_router,
                                             _real_btc_lookup)
        body = _real_btc_lookup("open")
        body["positionExecutions"][0]["stopLossRate"] = held
        t, fake = _client([], env="live")
        _lookup_router(fake, by_order=(200, body))
        st = t.order_status("1596774178")
        CryptoBot(self.cfg)._finish_working_entry(
            self.trade, t, qty=st["filled"], price=st["avgPrice"],
            source="broker", venue=st)
        self.trade.refresh_from_db()

    def _staff_alerts(self):
        return list(_bell(self.staff, title__contains="rewrote the stop"))

    def test_the_fill_message_is_the_one_message(self):
        self._fill()
        self.assertEqual(self.trade.metadata["stop_rewritten_by_venue"],
                         {"sent": 79934.97, "held": 75745.8})
        self.assertEqual(self._staff_alerts(), [])
        fill = _bell(self.owner).get()
        self.assertEqual(fill.title, "◉ Bought BTCUSD")
        self.assertIn(BTC_MOVED, fill.data["items"])
        self.assertIn("Stop: 75745.80 at eToro (10.0% below)",
                      fill.data["items"])
        self.assertEqual(sum(BTC_MOVED in i for i in fill.data["items"]), 1)

    def test_a_fill_message_not_delivered_leaves_the_staff_alert(self):
        with patch("bot_program.notifications.notify_bot_fill_open",
                   return_value=False):
            self._fill()
        alerts = self._staff_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].title,
                         "⚠ BTCUSD: the venue rewrote the stop")
        self.assertEqual(alerts[0].body, (
            f"{BTC_MOVED}. The fill message was not delivered, so this is "
            f"the one notice. The loss at this stop is not the risk the "
            f"entry was sized for; read the position at eToro (trade "
            f"#{self.trade.id} on the platform)."))
        self.assertEqual(alerts[0].url, f"/forensics/{self.trade.id}/")
        self.assertEqual(jargon(alerts[0].body), [])

    def test_a_fill_notifier_that_raises_leaves_the_staff_alert(self):
        with patch("bot_program.notifications.notify_bot_fill_open",
                   side_effect=RuntimeError("down")):
            self._fill()
        self.assertEqual(len(self._staff_alerts()), 1)

    def test_a_rounding_under_the_tick_is_not_a_moved_stop(self):
        self._fill(held=79934.974)
        self.assertNotIn("stop_rewritten_by_venue", self.trade.metadata)
        self.assertTrue(self.trade.metadata["protected"])
        self.assertEqual(self._staff_alerts(), [])
        items = _bell(self.owner).get().data["items"]
        self.assertIn("Stop: 79934.97 (5.0% below)", items)
        self.assertFalse([i for i in items if "moved" in i or "eToro" in i
                          and i.startswith("Stop")], items)

    def test_the_immediate_fill_waits_for_its_message_too(self):
        """execute_entry: the staff alert comes AFTER the booking, and only
        when the fill message did not go (the source says so)."""
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        stamp = src.index('entry_meta["stop_rewritten_by_venue"] = {')
        told = src.index("told = bool(notify_bot_fill_open(")
        alert = src.index("self._alert_stop_rewrite(")
        self.assertLess(stamp, told)
        self.assertLess(told, alert)
        self.assertEqual(src.count("the venue reports"), 0)
        self.assertEqual(src.count("the venue rewrote the stop"), 0)


# ── P7: a rounding is not a moved stop ───────────────────────────────────

class TheTickTests(SimpleTestCase):
    def test_the_tick_decides(self):
        from bot_program.asset_engine.base import venue_moved_stop as moved
        # sub-tick roundings: never a moved stop
        self.assertFalse(moved(1.526892917, 1.52689, "forex", "EURCAD"))
        self.assertFalse(moved(220.704, 220.70, "stock", "AAPL"))
        self.assertFalse(moved(79934.974, 79934.97, "crypto", "BTCUSD"))
        self.assertFalse(moved(148.3254, 148.325, "forex", "USDJPY"))
        self.assertFalse(moved(0.85004, 0.8500, "crypto", "ADAUSD"))
        # a tick or more, either way: a moved stop
        self.assertTrue(moved(1.52689, 1.52690, "forex", "EURCAD"))
        self.assertTrue(moved(82.17, 83.06, "stock", "GLDM"))
        self.assertTrue(moved(79934.97, 75745.8, "crypto", "BTCUSD"))
        self.assertTrue(moved(148.325, 148.326, "forex", "USDJPY"))
        # eToro's "no stop" is a rewrite while a stop was sent (Morgul's G2
        # reads the stamp for it)
        self.assertTrue(moved(79934.97, 0.0001, "crypto", "BTCUSD"))
        self.assertTrue(moved(1.15297, 0.0, "forex", "EURUSD"))
        self.assertFalse(moved(0.0, 0.0001))
        # anything unreadable is no rewrite
        for bad in ((None, 1.0), ("x", 1.0), (float("nan"), 1.0),
                    (1.0, float("nan"))):
            self.assertFalse(moved(*bad), bad)

    def test_no_raw_compare_is_left(self):
        from bot_program import manual_trade
        from bot_program.asset_engine import base
        for fn in (base.AssetBot.execute_entry,
                   base.AssetBot._finish_working_entry, manual_trade._execute):
            src = inspect.getsource(fn)
            self.assertIn("venue_moved_stop(", src, fn.__name__)
            self.assertNotIn("abs(held - sent) > 1e-9", src)
            self.assertNotIn("abs(held - float(sl)) > 1e-9", src)
            self.assertNotIn("abs(held - float(stop)) > 1e-9", src)


class TheHandLaneTickTests(_Base):
    def test_the_hand_lane_ignores_a_rounding_and_records_a_move(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (ROUTER, _arm_live,
                                                _components_on,
                                                _fake_live_client,
                                                _filled_response, _quote)
        from tests.test_take_trade_live import _signal as _tt_signal
        inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)

        def take(offset):
            fake = _fake_live_client()
            fake.market_order.side_effect = lambda *a, **k: _filled_response(
                venueStopLoss=float(k["stop_loss"]) + offset)
            cache.clear()
            with patch(ROUTER, return_value=fake), \
                    patch("requests.post", return_value=_ok()) as post:
                out = execute_take_trade(self.user, _tt_signal(inst),
                                         pin_ok=True)
            self.assertTrue(out.get("ok"), out)
            row = AssetBotTrade.objects.get(pk=out["trade_id"])
            AssetBotTrade.objects.filter(pk=row.pk).update(status="CLOSED")
            texts = [p["text"] for p in _payloads(post)
                     if "Bought BTCUSD by hand" in p["text"]]
            self.assertEqual(len(texts), 1)
            return row, float(fake.market_order.call_args.kwargs[
                "stop_loss"]), texts[0]

        row, sent, text = take(0.004)
        self.assertNotIn("stop_rewritten_by_venue", row.metadata)
        self.assertNotIn("Stop moved", text)
        self.assertNotIn("at eToro (", text)
        row, sent, text = take(-250.0)
        self.assertEqual(row.metadata["stop_rewritten_by_venue"],
                         {"sent": sent, "held": sent - 250.0})
        self.assertIn("Stop moved by eToro", text)


# ── P3: the Eye speaks the fill messages' words ──────────────────────────

class TheEyeLineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tgp_eye", password="x")

    def test_the_position_line_at_the_instruments_decimals(self):
        from bot_program import telegram_eye as eye
        row = _eurcad(_cfg(self.user, "forex", "FX trend", mode="live"),
                      paper=False)
        self.assertEqual(eye.position_line(row),
                         "  • EURCAD long 7,900 @ 1.60726 · stop 1.52689 · "
                         "live")
        self.assertEqual(eye.position_line(row, detailed=True, bullet=False),
                         "EURCAD long 7,900 @ 1.60726 · stop 1.52689 · "
                         "target 1.76798 · live · opened just now")
        lines = [str(x) for x in eye.build_positions(self.user).lines]
        self.assertIn("  • EURCAD long 7,900 @ 1.60726 · stop 1.52689 · "
                      "target 1.76798 · live · opened just now", lines)
        for line in lines:
            self.assertEqual(jargon(line), [], line)

    def test_the_stop_the_venue_holds_is_the_one_named(self):
        from bot_program import telegram_eye as eye
        cfg = _cfg(self.user, "forex", "FX attack", mode="live",
                   capital="2000")
        row = _eurusd_attack(cfg)
        self.assertEqual(eye.position_line(row, bullet=False),
                         "EURUSD long 1,700 @ 1.17650 · stop 1.14000 at "
                         "eToro · live")
        row.metadata["stop_rewritten_by_venue"]["held"] = 0.0001
        self.assertEqual(eye.position_line(row, bullet=False),
                         "EURUSD long 1,700 @ 1.17650 · no stop at eToro · "
                         "live")
        stock = _trade(_cfg(self.user, "stock", "Stocks"), 160,
                       symbol="AAPL", side="SELL",
                       qty=Decimal("10.00000000"),
                       entry_price=Decimal("227.53000000"), stop_loss=None,
                       paper=True)
        self.assertEqual(eye.position_line(stock, detailed=True,
                                           bullet=False),
                         "AAPL short 10 @ 227.53 · stop — · target — · "
                         "paper · opened just now")

    def test_the_eyes_own_price_is_untouched_for_morgul(self):
        from bot_program import telegram_eye as eye
        self.assertEqual(eye.price(Decimal("1.60725571")), "1.60725571")
        self.assertEqual(eye.price(Decimal("336.10000000")), "336.10")
