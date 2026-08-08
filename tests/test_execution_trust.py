"""Execution-trust arc: broker-side stops, CLOSE_PENDING, real fills.

Run with:  python manage.py test tests.test_execution_trust
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="exec_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, asset_class="stock", *, mode="live", name="EX"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
    )


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _signal(inst, rule="r1", direction="bullish", score=0.9):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title="t", description="d", rule_name=rule,
        score=score, sub_scores={}, price_at_signal=Decimal("100"),
        suggested_entry=Decimal("100"), is_active=True,
    )


def _trade(cfg, **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=False,
    )
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


# ── CLOSE_PENDING lifecycle ─────────────────────────────────────────────

class ClosePendingTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def test_failed_live_close_marks_close_pending_not_closed(self):
        """The old behaviour marked the row CLOSED even when the broker
        rejected the close, so the DB claimed flat while the position was
        still live at the broker."""
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg)
        client = MagicMock()
        client.market_order = MagicMock(side_effect=RuntimeError("broker down"))
        bot = StockBot(self.cfg)

        ok = bot._close_trade(trade, Decimal("99"), client, reason="SL")

        self.assertFalse(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.closed_at)
        self.assertIn("close-failed", trade.reason)

    def test_successful_live_close_still_closes(self):
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg)
        client = MagicMock()
        client.market_order = MagicMock(return_value={"orderId": "1"})
        ok = StockBot(self.cfg)._close_trade(
            trade, Decimal("104"), client, reason="TP")

        self.assertTrue(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("104"))
        self.assertEqual(trade.pnl, Decimal("40"))

    def test_close_pending_counts_as_exposure(self):
        """A stranded position still occupies a concurrency slot and blocks a
        duplicate entry on the same symbol."""
        from bot_program.asset_engine.stock_bot import StockBot

        _trade(self.cfg, status="CLOSE_PENDING")
        self.cfg.max_concurrent_positions = 1
        self.cfg.save()
        ok, reason = StockBot(self.cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("concurrent", reason)

    def test_retry_closes_when_broker_recovers(self):
        from bot_program.pending_closes import retry_all_pending_closes

        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.market_order = MagicMock(return_value={"orderId": "9"})
        client.ticker = MagicMock(return_value={"lastPrice": "103"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            out = retry_all_pending_closes()

        self.assertEqual(out, {"pending": 1, "closed": 1, "still_pending": 0})
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("103"))
        self.assertEqual(trade.pnl, Decimal("30"))

    def test_retry_keeps_pending_and_counts_attempts_on_failure(self):
        from bot_program.pending_closes import retry_all_pending_closes

        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.market_order = MagicMock(side_effect=RuntimeError("still down"))
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            out = retry_all_pending_closes()

        self.assertEqual(out["still_pending"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(trade.metadata.get("close_retry_attempts"), 1)

    def test_retry_alerts_after_repeated_failures(self):
        from alerts.models import Notification
        from bot_program.pending_closes import retry_all_pending_closes, ALERT_AFTER_ATTEMPTS

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"close_retry_attempts": ALERT_AFTER_ATTEMPTS - 1})
        client = MagicMock()
        client.market_order = MagicMock(side_effect=RuntimeError("down"))
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            retry_all_pending_closes()

        self.assertTrue(Notification.objects.filter(
            user=self.user, title__startswith="🚨 Stranded position").exists())

    def test_beat_schedule_has_retry_task(self):
        from config.celery import app
        entry = app.conf.beat_schedule.get("retry-pending-closes")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["task"], "bot_program.tasks.retry_pending_closes")


# ── Broker-side protective stops ────────────────────────────────────────

class BrokerSideStopsTests(TestCase):
    def setUp(self):
        self.user = _user("prot_u")
        self.cfg = _cfg(self.user)
        self.inst = _instrument()
        _signal(self.inst)

    def test_entry_requests_bracket_and_marks_trade_protected(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.market_order = MagicMock(return_value={
            "orderId": "abc", "status": "ACCEPTED",
            "avgPrice": "100.25", "executedQty": "10",
            "protectedOnFill": True, "protectiveOrders": ["sl1", "tp1"],
        })
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")

        kwargs = client.market_order.call_args.kwargs
        self.assertIn("stop_loss", kwargs)
        self.assertIn("take_profit", kwargs)
        trade = AssetBotTrade.objects.get(config=self.cfg, symbol="AAPL")
        self.assertTrue(trade.metadata.get("protected"))
        self.assertEqual(trade.metadata.get("protective_order_ids"), ["sl1", "tp1"])

    def test_protected_trades_are_not_managed_bot_side(self):
        """Double-closing a broker-protected trade would flatten it here and
        leave the broker's resting stop to open a REVERSE position later."""
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg, metadata={"protected": True,
                                            "protective_order_ids": ["sl1"]})
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "50"})  # way below SL
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            closed = StockBot(self.cfg).manage_positions()

        self.assertEqual(closed, 0)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_manual_close_cancels_resting_protective_orders(self):
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg, metadata={"protective_order_ids": ["sl1", "tp1"]})
        client = MagicMock()
        client.market_order = MagicMock(return_value={"orderId": "1"})
        StockBot(self.cfg)._close_trade(trade, Decimal("101"), client,
                                         reason="MANUAL")
        cancelled = [c.args[0] for c in client.cancel_order.call_args_list]
        self.assertEqual(sorted(cancelled), ["sl1", "tp1"])


# ── Real fills ──────────────────────────────────────────────────────────

class RealFillTests(TestCase):
    def setUp(self):
        self.user = _user("fill_u")
        self.cfg = _cfg(self.user)
        self.inst = _instrument()
        _signal(self.inst)

    def test_entry_recorded_at_broker_fill_price_not_ticker(self):
        """Slippage must land in the trade, or grading runs on fiction."""
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.market_order = MagicMock(return_value={
            "orderId": "o1", "status": "FILLED",
            "avgPrice": "100.42", "executedQty": "9",
        })
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")

        trade = AssetBotTrade.objects.get(config=self.cfg, symbol="AAPL")
        self.assertEqual(trade.entry_price, Decimal("100.42"))
        self.assertEqual(trade.qty, Decimal("9"))
        self.assertEqual(trade.metadata.get("fill_source"), "broker")

    def test_falls_back_to_ticker_when_broker_reports_no_fill_price(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.market_order = MagicMock(return_value={
            "orderId": "o2", "status": "ACCEPTED",
            "avgPrice": "0", "executedQty": "0",
        })
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")

        trade = AssetBotTrade.objects.get(config=self.cfg, symbol="AAPL")
        self.assertEqual(trade.entry_price, Decimal("100"))
        self.assertEqual(trade.metadata.get("fill_source"), "ticker")


# ── Client-level contracts (no network) ─────────────────────────────────

class ClientContractTests(TestCase):
    def test_alpaca_sends_bracket_and_reports_legs(self):
        from bot_program.engine.alpaca_client import AlpacaTrader

        trader = AlpacaTrader("k", "s", env="paper")
        resp = MagicMock()
        resp.json = MagicMock(return_value={
            "id": "o1", "status": "accepted", "filled_qty": "10",
            "filled_avg_price": "101.5",
            "legs": [{"id": "leg_sl"}, {"id": "leg_tp"}],
        })
        resp.raise_for_status = MagicMock()
        sess = MagicMock()
        sess.post = MagicMock(return_value=resp)
        with patch.object(trader, "_sess", return_value=sess):
            out = trader.market_order("AAPL", "BUY", 10,
                                       stop_loss=98.0, take_profit=104.0)

        body = sess.post.call_args.kwargs["json"]
        self.assertEqual(body["order_class"], "bracket")
        self.assertEqual(body["stop_loss"]["stop_price"], "98.00")
        self.assertEqual(body["take_profit"]["limit_price"], "104.00")
        self.assertEqual(body["time_in_force"], "gtc")
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual(out["protectiveOrders"], ["leg_sl", "leg_tp"])
        self.assertEqual(out["avgPrice"], "101.5")

    def test_alpaca_plain_order_without_protection_args(self):
        from bot_program.engine.alpaca_client import AlpacaTrader

        trader = AlpacaTrader("k", "s", env="paper")
        resp = MagicMock()
        resp.json = MagicMock(return_value={
            "id": "o2", "status": "filled", "filled_qty": "5",
            "filled_avg_price": "10.0",
        })
        resp.raise_for_status = MagicMock()
        sess = MagicMock()
        sess.post = MagicMock(return_value=resp)
        with patch.object(trader, "_sess", return_value=sess):
            trader.market_order("AAPL", "BUY", 5)

        body = sess.post.call_args.kwargs["json"]
        self.assertNotIn("order_class", body)
        self.assertEqual(body["time_in_force"], "day")

    def test_oanda_attaches_on_fill_protection(self):
        from bot_program.engine.oanda_client import OANDATrader

        trader = OANDATrader("k", "acct", env="practice")
        resp = MagicMock()
        resp.json = MagicMock(return_value={
            "orderFillTransaction": {"id": "f1", "units": "1000",
                                      "price": "1.10550"},
        })
        resp.raise_for_status = MagicMock()
        sess = MagicMock()
        sess.post = MagicMock(return_value=resp)
        with patch.object(trader, "_sess", return_value=sess):
            out = trader.market_order("EURUSD", "BUY", 1000,
                                       stop_loss=1.10, take_profit=1.11)

        order = sess.post.call_args.kwargs["json"]["order"]
        self.assertEqual(order["stopLossOnFill"]["price"], "1.10000")
        self.assertEqual(order["takeProfitOnFill"]["price"], "1.11000")
        self.assertTrue(out["protectedOnFill"])

    def test_oanda_jpy_pairs_use_three_decimals(self):
        from bot_program.engine.oanda_client import OANDATrader

        trader = OANDATrader("k", "acct", env="practice")
        resp = MagicMock()
        resp.json = MagicMock(return_value={"orderFillTransaction": {}})
        resp.raise_for_status = MagicMock()
        sess = MagicMock()
        sess.post = MagicMock(return_value=resp)
        with patch.object(trader, "_sess", return_value=sess):
            trader.market_order("USDJPY", "BUY", 1000,
                                 stop_loss=150.5, take_profit=152.25)

        order = sess.post.call_args.kwargs["json"]["order"]
        self.assertEqual(order["stopLossOnFill"]["price"], "150.500")
        self.assertEqual(order["takeProfitOnFill"]["price"], "152.250")

    def test_binance_futures_market_order_accepts_shared_kwargs(self):
        """The shared interface passes client_order_id/stop_loss/take_profit;
        futures previously had no **kwargs and would TypeError."""
        import inspect
        from bot_program.engine.binance_futures_client import BinanceFuturesClient
        sig = inspect.signature(BinanceFuturesClient.market_order)
        self.assertTrue(any(p.kind == p.VAR_KEYWORD
                            for p in sig.parameters.values()))
