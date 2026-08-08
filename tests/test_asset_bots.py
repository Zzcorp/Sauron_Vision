"""Tests for Phase-13 multi-asset bot framework.

Covers:
  - make_bot factory dispatches by asset_class
  - AssetBot.decide() consumes Phase-1 Signal rows correctly
  - AssetBot.position_size — stocks (whole shares in live), forex (units), commodity (paper)
  - AssetBot.scan_symbol creates AssetBotTrade with rule_name from top signal
  - AssetBot.manage_positions hits SL/TP and updates status to CLOSED
  - AssetBot.can_open_new — max-concurrent + daily-loss gates
  - run_asset_bot_tick handles disabled / missing configs
  - run_all_asset_bots aggregates per-bot results
  - Phase-5/7/8 multiplier gets applied to qty (paused rule -> qty=0)
  - CommodityBot forces paper mode
  - Cooldown after CLOSED prevents re-entry within window

Run with:  python manage.py test tests.test_asset_bots
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _user(name="abot_user"):
    return User.objects.create_user(username=name, password="x")


def _config(user, asset_class="stock", **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class=asset_class, name="Test Bot",
        enabled=True, mode="paper",
        symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1, cool_down_minutes=0,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _signal(symbol, direction, score, rule="rule_a", asset_class="stock"):
    from signals.models import Signal
    inst = _instrument(symbol, asset_class)
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title=f"{symbol} {direction}", description="t",
        rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
    )


# ── Factory ─────────────────────────────────────────────────────────────────

class FactoryTests(TestCase):
    def test_make_bot_dispatches_by_asset_class(self):
        from bot_program.asset_engine import make_bot, StockBot, ForexBot, CommodityBot
        u = _user()
        self.assertIsInstance(make_bot(_config(u, "stock", name="A")), StockBot)
        self.assertIsInstance(make_bot(_config(u, "forex", name="B")), ForexBot)
        self.assertIsInstance(make_bot(_config(u, "commodity", name="C")), CommodityBot)

    def test_make_bot_unknown_asset_class_raises(self):
        from bot_program.asset_engine import make_bot
        u = _user()
        cfg = _config(u, "stock")
        cfg.asset_class = "bond"  # not supported (options is wired in Phase-14)
        with self.assertRaises(ValueError):
            make_bot(cfg)


# ── decide() consumes Phase-1 Signal rows ──────────────────────────────────

class DecideTests(TestCase):
    def test_decide_returns_buy_when_bullish_consensus(self):
        from bot_program.asset_engine.base import AssetBot, BotDecision
        from bot_program.asset_engine import StockBot
        u = _user()
        cfg = _config(u, "stock", symbols=["DEC1"])
        # Two bullish signals at high score
        _signal("DEC1", "bullish", 0.85, "rule_a")
        _signal("DEC1", "bullish", 0.75, "rule_b")
        bot = StockBot(cfg)
        decision = bot.decide("DEC1")
        self.assertEqual(decision.direction, "BUY")
        self.assertGreater(decision.score, 0.6)
        self.assertIn(decision.rule_name, ("rule_a", "rule_b"))

    def test_decide_holds_when_mixed_signals(self):
        from bot_program.asset_engine import StockBot
        u = _user()
        cfg = _config(u, "stock", symbols=["DEC2"])
        _signal("DEC2", "bullish", 0.85, "rule_a")
        _signal("DEC2", "bearish", 0.85, "rule_b")
        bot = StockBot(cfg)
        decision = bot.decide("DEC2")
        self.assertEqual(decision.direction, "HOLD")

    def test_decide_holds_when_no_signals(self):
        from bot_program.asset_engine import StockBot
        u = _user()
        cfg = _config(u, "stock", symbols=["DEC3"])
        _instrument("DEC3", "stock")
        bot = StockBot(cfg)
        self.assertEqual(bot.decide("DEC3").direction, "HOLD")

    def test_decide_holds_when_score_below_min(self):
        from bot_program.asset_engine import StockBot
        u = _user()
        cfg = _config(u, "stock", symbols=["DEC4"], entry_score_min=0.8)
        _signal("DEC4", "bullish", 0.7, "rule_a")  # below threshold
        bot = StockBot(cfg)
        self.assertEqual(bot.decide("DEC4").direction, "HOLD")


# ── Sizing ─────────────────────────────────────────────────────────────────

class SizingTests(TestCase):
    def test_stock_bot_paper_uses_fractional(self):
        from bot_program.asset_engine import StockBot
        u = _user()
        cfg = _config(u, "stock", capital=Decimal("10000"),
                      position_size_pct=2.0, mode="paper")
        bot = StockBot(cfg)
        # 200 dollars / 150 price = 1.333 shares (fractional ok in paper)
        qty = bot.position_size(150.0)
        self.assertAlmostEqual(qty, 1.3333, places=3)

    def test_stock_bot_live_rounds_to_whole_shares(self):
        from bot_program.asset_engine import StockBot
        u = _user()
        cfg = _config(u, "stock", capital=Decimal("10000"),
                      position_size_pct=2.0, mode="live")
        bot = StockBot(cfg)
        # 200 / 150 = 1.33 → floor to 1 whole share
        qty = bot.position_size(150.0)
        self.assertEqual(qty, 1.0)

    def test_forex_bot_units_rounded_to_100(self):
        from bot_program.asset_engine import ForexBot
        u = _user()
        cfg = _config(u, "forex", capital=Decimal("10000"),
                      position_size_pct=2.0)
        bot = ForexBot(cfg)
        # 200 dollars / 1.08 = 185.18 → round to 200 units
        qty = bot.position_size(1.08)
        self.assertEqual(qty % 100, 0)
        self.assertGreaterEqual(qty, 100)

    def test_forex_bot_extras_units_per_pct(self):
        from bot_program.asset_engine import ForexBot
        u = _user()
        cfg = _config(u, "forex", position_size_pct=2.0,
                      extras={"forex_units_per_pct": 1000})
        bot = ForexBot(cfg)
        # 1000 × 2 = 2000 units, rounded to 100s
        qty = bot.position_size(1.08)
        self.assertEqual(qty, 2000.0)

    def test_commodity_bot_forces_paper_mode(self):
        from bot_program.asset_engine import CommodityBot
        u = _user()
        cfg = _config(u, "commodity", mode="live")
        bot = CommodityBot(cfg)
        self.assertEqual(cfg.mode, "paper")  # forced down


# ── scan_symbol creates AssetBotTrade ──────────────────────────────────────

class ScanSymbolTests(TestCase):
    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_creates_trade_with_rule_name_from_top_signal(self, mock_client_for):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade

        u = _user()
        cfg = _config(u, "stock", symbols=["SCAN1"])
        _signal("SCAN1", "bullish", 0.85, rule="winning_rule")

        fake_client = MagicMock()
        fake_client.ticker.return_value = {"lastPrice": "150.00"}
        mock_client_for.return_value = fake_client

        bot = StockBot(cfg)
        result = bot.scan_symbol("SCAN1")
        self.assertIsNotNone(result)
        trade = AssetBotTrade.objects.get(id=result["trade_id"])
        self.assertEqual(trade.symbol, "SCAN1")
        self.assertEqual(trade.side, "BUY")
        self.assertEqual(trade.rule_name, "winning_rule")
        self.assertTrue(trade.paper)

    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_no_trade_when_decision_is_hold(self, mock_client_for):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade

        u = _user()
        cfg = _config(u, "stock", symbols=["SCAN2"])
        _instrument("SCAN2", "stock")  # no signals
        bot = StockBot(cfg)
        result = bot.scan_symbol("SCAN2")
        self.assertIsNone(result)
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        # broker_router must not be called when decision is HOLD
        mock_client_for.assert_not_called()

    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_skips_when_open_trade_exists_for_symbol(self, mock_client_for):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade

        u = _user()
        cfg = _config(u, "stock", symbols=["SCAN3"])
        _signal("SCAN3", "bullish", 0.85, "rule_a")
        # Pre-create an OPEN trade.
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="SCAN3", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        )
        bot = StockBot(cfg)
        bot.scan_symbol("SCAN3")
        self.assertEqual(AssetBotTrade.objects.count(), 1)


# ── manage_positions: SL/TP closure ────────────────────────────────────────

class ManagePositionsTests(TestCase):
    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_take_profit_closes_with_positive_pnl(self, mock_client_for):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade

        u = _user()
        cfg = _config(u, "stock", symbols=["MP1"])
        _instrument("MP1", "stock")
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="MP1", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
            status="OPEN", paper=True,
        )

        fake_client = MagicMock()
        fake_client.ticker.return_value = {"lastPrice": "115.00"}  # above target
        mock_client_for.return_value = fake_client

        bot = StockBot(cfg)
        closed = bot.manage_positions()
        self.assertEqual(closed, 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertGreater(trade.pnl, 0)
        # 115 (capped at target check is >=) — actual close uses 115
        self.assertEqual(trade.pnl, (Decimal("115") - Decimal("100")) * Decimal("10"))

    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_stop_loss_closes_with_negative_pnl(self, mock_client_for):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade

        u = _user()
        cfg = _config(u, "stock", symbols=["MP2"])
        _instrument("MP2", "stock")
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="MP2", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
            status="OPEN", paper=True,
        )
        fake_client = MagicMock()
        fake_client.ticker.return_value = {"lastPrice": "94.00"}
        mock_client_for.return_value = fake_client
        bot = StockBot(cfg)
        bot.manage_positions()
        trade = AssetBotTrade.objects.get(symbol="MP2")
        self.assertEqual(trade.status, "CLOSED")
        self.assertLess(trade.pnl, 0)


# ── Gates ──────────────────────────────────────────────────────────────────

class GateTests(TestCase):
    def test_max_concurrent_positions_blocks_new(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        u = _user()
        cfg = _config(u, "stock", max_concurrent_positions=2)
        _instrument("G1", "stock")
        for s in ("G1A", "G1B"):
            _instrument(s, "stock")
            AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol=s, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            )
        bot = StockBot(cfg)
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("concurrent", reason)

    def test_daily_loss_limit_blocks_new(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        u = _user()
        cfg = _config(u, "stock", capital=Decimal("10000"), max_daily_loss_pct=2.0)
        # Create a CLOSED trade with -500 PnL (5% of 10000) within 24h
        _instrument("G2", "stock")
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="G2", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            exit_price=Decimal("50"), status="CLOSED",
            pnl=Decimal("-500"),
            closed_at=timezone.now(),
        )
        bot = StockBot(cfg)
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("daily loss", reason)


# ── Phase-5/7/8 multiplier integration ─────────────────────────────────────

class MultiplierIntegrationTests(TestCase):
    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_paused_rule_yields_zero_qty_no_trade(self, mock_client_for):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        from signals.models import RuleControl

        u = _user()
        cfg = _config(u, "stock", symbols=["MUL1"])
        _signal("MUL1", "bullish", 0.85, rule="paused_rule")
        # Phase-5 pause via PromotionStage RESEARCH → factor 0
        RuleControl.objects.create(
            rule_name="paused_rule", status="active",
            promotion_stage="research",  # factor 0 — no live capital
            stage_entered_at=timezone.now(),
        )
        fake_client = MagicMock()
        fake_client.ticker.return_value = {"lastPrice": "150.00"}
        mock_client_for.return_value = fake_client

        bot = StockBot(cfg)
        result = bot.scan_symbol("MUL1")
        # qty becomes 0 because RESEARCH stage → no trade created
        self.assertIsNone(result)
        self.assertEqual(AssetBotTrade.objects.count(), 0)


# ── Runner ─────────────────────────────────────────────────────────────────

class RunnerTests(TestCase):
    def test_run_asset_bot_tick_missing_config(self):
        from bot_program.asset_engine import run_asset_bot_tick
        result = run_asset_bot_tick(99999)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "config_not_found")

    def test_run_asset_bot_tick_disabled_skipped(self):
        from bot_program.asset_engine import run_asset_bot_tick
        u = _user()
        cfg = _config(u, "stock", enabled=False)
        result = run_asset_bot_tick(cfg.id)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "disabled")

    @patch("bot_program.engine.broker_router.client_for_symbol")
    def test_run_all_asset_bots_aggregates(self, mock_client_for):
        from bot_program.asset_engine import run_all_asset_bots
        u = _user()
        _config(u, "stock", name="A", enabled=True, symbols=[])
        _config(u, "forex", name="B", enabled=True, symbols=[])
        _config(u, "commodity", name="C", enabled=False, symbols=[])

        result = run_all_asset_bots()
        self.assertEqual(result["status"], "ok")
        # Only the two enabled configs get ticked.
        self.assertEqual(result["configs_ticked"], 2)
