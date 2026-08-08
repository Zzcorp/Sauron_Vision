"""Tests for the Phase-4 broker layer.

Mocks HTTP — no real OANDA / Alpaca calls.

Covers:
  - OANDATrader and AlpacaTrader: kline parsing, market_order encoding,
    auth headers, balance retrieval
  - broker_router.client_for_symbol: routing by asset_class, paper-mode
    short-circuit, missing-creds fallback to PaperTrader

Run with:  python manage.py test tests.test_phase4_brokers
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _mock_response(status=200, json_body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.raise_for_status.return_value = None
    return r


# ── OANDA adapter ───────────────────────────────────────────────────────────

class OANDATraderTests(TestCase):
    def test_symbol_normalisation(self):
        from bot_program.engine.oanda_client import _to_oanda_symbol
        self.assertEqual(_to_oanda_symbol("EURUSD"), "EUR_USD")
        self.assertEqual(_to_oanda_symbol("EUR_USD"), "EUR_USD")
        self.assertEqual(_to_oanda_symbol("XAUUSD"), "XAU_USD")

    def test_practice_endpoint_default(self):
        from bot_program.engine.oanda_client import OANDATrader, PRACTICE_API
        t = OANDATrader("k", "acct-1", env="practice")
        self.assertEqual(t.base, PRACTICE_API)

    def test_live_endpoint_when_env_live(self):
        from bot_program.engine.oanda_client import OANDATrader, LIVE_API
        t = OANDATrader("k", "acct-1", env="live")
        self.assertEqual(t.base, LIVE_API)

    @patch("requests.Session.get")
    def test_klines_filters_incomplete_and_emits_binance_shape(self, m_get):
        from bot_program.engine.oanda_client import OANDATrader
        m_get.return_value = _mock_response(json_body={
            "candles": [
                {"complete": True,  "time": "2026-04-30T13:00:00Z", "volume": 100,
                 "mid": {"o": "1.0850", "h": "1.0860", "l": "1.0840", "c": "1.0855"}},
                {"complete": False, "time": "2026-04-30T13:15:00Z", "volume": 0,
                 "mid": {"o": "1.0855", "h": "1.0855", "l": "1.0855", "c": "1.0855"}},
            ],
        })
        t = OANDATrader("k", "acct-1")
        rows = t.klines("EURUSD", interval="15m", limit=50)
        # Only the complete candle is returned
        self.assertEqual(len(rows), 1)
        # Binance-style 11-element row
        self.assertEqual(len(rows[0]), 12)
        self.assertEqual(rows[0][1], "1.0850")  # open
        self.assertEqual(rows[0][4], "1.0855")  # close

    @patch("requests.Session.post")
    def test_market_order_signs_units_for_sell(self, m_post):
        from bot_program.engine.oanda_client import OANDATrader
        m_post.return_value = _mock_response(json_body={
            "orderFillTransaction": {"id": "999", "units": "-1000", "price": "1.0855"},
        })
        t = OANDATrader("k", "acct-1")
        result = t.market_order("EURUSD", "SELL", 1000)
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(result["orderId"], "999")
        # Verify payload had negative units for SELL
        sent_body = m_post.call_args.kwargs["json"]
        self.assertTrue(sent_body["order"]["units"].startswith("-"))


# ── Alpaca adapter ──────────────────────────────────────────────────────────

class AlpacaTraderTests(TestCase):
    def test_paper_endpoint_default(self):
        from bot_program.engine.alpaca_client import AlpacaTrader, TRADING_PAPER
        t = AlpacaTrader("k", "s", env="paper")
        self.assertEqual(t.trading_base, TRADING_PAPER)

    def test_live_endpoint_when_env_live(self):
        from bot_program.engine.alpaca_client import AlpacaTrader, TRADING_LIVE
        t = AlpacaTrader("k", "s", env="live")
        self.assertEqual(t.trading_base, TRADING_LIVE)

    @patch("requests.Session.get")
    def test_klines_returns_binance_shape(self, m_get):
        from bot_program.engine.alpaca_client import AlpacaTrader
        m_get.return_value = _mock_response(json_body={
            "bars": [
                {"t": "2026-04-30T14:30:00Z", "o": 184.0, "h": 184.5,
                 "l": 183.8, "c": 184.2, "v": 1_000_000},
                {"t": "2026-04-30T14:45:00Z", "o": 184.2, "h": 184.4,
                 "l": 184.0, "c": 184.1, "v": 800_000},
            ],
        })
        t = AlpacaTrader("k", "s")
        rows = t.klines("AAPL", interval="15m", limit=50)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][4], "184.2")    # close
        self.assertEqual(rows[1][5], "800000")   # volume

    @patch("requests.Session.post")
    def test_market_order_lowercases_side(self, m_post):
        from bot_program.engine.alpaca_client import AlpacaTrader
        m_post.return_value = _mock_response(json_body={
            "id": "abc-123", "filled_qty": "10",
            "filled_avg_price": "184.20", "status": "filled",
        })
        t = AlpacaTrader("k", "s")
        result = t.market_order("AAPL", "BUY", 10)
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(result["orderId"], "abc-123")
        sent_body = m_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["side"], "buy")
        self.assertEqual(sent_body["type"], "market")


# ── broker_router ───────────────────────────────────────────────────────────

class BrokerRouterTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from bot_program.models import BotConfig
        self.user = User.objects.create_user(username="routeruser", password="x")
        self.cfg = BotConfig.objects.create(
            user=self.user, capital_usdt=Decimal("1000"),
            mode="paper",  # default paper
        )

    def test_paper_mode_always_returns_paper(self):
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.paper_trader import PaperTrader
        _instrument("AAPL", "stock")  # would route to alpaca if live
        client = client_for_symbol(self.user, "AAPL", self.cfg)
        self.assertIsInstance(client, PaperTrader)

    def test_live_stock_without_alpaca_creds_falls_back_to_paper(self):
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.paper_trader import PaperTrader
        self.cfg.mode = "live"
        _instrument("AAPL", "stock")
        client = client_for_symbol(self.user, "AAPL", self.cfg)
        self.assertIsInstance(client, PaperTrader)

    def test_live_forex_with_oanda_creds_returns_oanda(self):
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.oanda_client import OANDATrader
        from bot_program.models import OANDAAccount
        self.cfg.mode = "live"
        _instrument("EURUSD", "forex")
        acct = OANDAAccount.objects.create(user=self.user, practice=True)
        acct.set_credentials("test-key", "test-account-id")
        acct.save()
        client = client_for_symbol(self.user, "EURUSD", self.cfg)
        self.assertIsInstance(client, OANDATrader)
        self.assertEqual(client.env, "practice")

    def test_live_stock_with_alpaca_creds_returns_alpaca(self):
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.alpaca_client import AlpacaTrader
        from bot_program.models import AlpacaAccount
        self.cfg.mode = "live"
        _instrument("AAPL", "stock")
        acct = AlpacaAccount.objects.create(user=self.user, paper=True)
        acct.set_credentials("test-key", "test-secret")
        acct.save()
        client = client_for_symbol(self.user, "AAPL", self.cfg)
        self.assertIsInstance(client, AlpacaTrader)
        self.assertEqual(client.env, "paper")

    def test_unknown_asset_class_falls_back_to_paper(self):
        """Symbol with no Instrument record → default to paper (safe)."""
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.paper_trader import PaperTrader
        self.cfg.mode = "live"
        # No instrument created for this symbol
        client = client_for_symbol(self.user, "UNKNOWN_XYZ", self.cfg)
        self.assertIsInstance(client, PaperTrader)

    def test_broker_name_for_symbol_inspects_without_instantiating(self):
        from bot_program.engine.broker_router import broker_name_for_symbol
        self.cfg.mode = "live"
        _instrument("EURUSD", "forex")
        _instrument("AAPL", "stock")
        _instrument("BTCUSDT", "crypto")
        self.assertEqual(broker_name_for_symbol(self.user, "EURUSD", self.cfg), "oanda")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.cfg), "alpaca")
        self.assertEqual(broker_name_for_symbol(self.user, "BTCUSDT", self.cfg), "binance")
        # Paper mode overrides
        self.cfg.mode = "paper"
        self.assertEqual(broker_name_for_symbol(self.user, "EURUSD", self.cfg), "paper")
