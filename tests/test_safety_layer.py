"""Circuit breakers, shadow mode and heartbeats.

Equivalent modules existed for the legacy bot but had zero call sites in
any trading path. These assert the asset-bot versions are actually wired
into the tick.

Run with:  python manage.py test tests.test_safety_layer
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="sf_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="AAPL"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    return inst


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="SF", mode="paper",
                    symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _closed(cfg, pnl, when=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("100"), pnl=Decimal(str(pnl)),
        status="CLOSED", paper=True,
        closed_at=when or timezone.now())


def _signal(inst, score=0.9):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title="t", description="d", rule_name="r1",
        score=score, sub_scores={}, price_at_signal=Decimal("100"),
        suggested_entry=Decimal("100"), is_active=True)


# ── circuit breakers ────────────────────────────────────────────────────

class CircuitBreakerTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_losing_streak_halts_new_entries(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, extras={"max_loss_streak": 3})
        for i in range(3):
            _closed(cfg, -10, timezone.now() - timedelta(minutes=i))
        ok, reason = StockBot(cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("consecutive losing", reason)

    def test_a_win_resets_the_streak(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, extras={"max_loss_streak": 3})
        _closed(cfg, -10, timezone.now() - timedelta(minutes=3))
        _closed(cfg, -10, timezone.now() - timedelta(minutes=2))
        _closed(cfg, +25, timezone.now() - timedelta(minutes=1))
        ok, _ = StockBot(cfg).can_open_new()
        self.assertTrue(ok)

    def test_drawdown_from_peak_halts(self):
        from bot_program.asset_engine.safety import CircuitBreakers
        cfg = _cfg(self.user, extras={"max_drawdown_pct": 5.0},
                   capital=Decimal("1000"))
        _closed(cfg, +200, timezone.now() - timedelta(minutes=6))
        for i in range(5):
            _closed(cfg, -50, timezone.now() - timedelta(minutes=5 - i))
        ok, reason = CircuitBreakers(cfg).check_drawdown_from_peak()
        self.assertFalse(ok)
        self.assertIn("drawdown", reason)

    def test_breakers_never_close_existing_positions(self):
        """Halting entries is safe; auto-closing on a heuristic is not."""
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, extras={"max_loss_streak": 2})
        for i in range(2):
            _closed(cfg, -10, timezone.now() - timedelta(minutes=i))
        open_trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            paper=True)

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            StockBot(cfg).tick()

        open_trade.refresh_from_db()
        self.assertEqual(open_trade.status, "OPEN")

    def test_a_tripped_breaker_notifies_once(self):
        from alerts.models import Notification
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, extras={"max_loss_streak": 2})
        for i in range(2):
            _closed(cfg, -10, timezone.now() - timedelta(minutes=i))
        StockBot(cfg).can_open_new()
        StockBot(cfg).can_open_new()
        self.assertEqual(Notification.objects.filter(
            user=self.user, title__startswith="🔌 Circuit breaker").count(), 1)


# ── shadow mode ─────────────────────────────────────────────────────────

class ShadowModeTests(TestCase):
    def setUp(self):
        self.user = _user("shadow_u")
        self.inst = _instrument()
        _signal(self.inst)

    def test_shadow_mode_computes_but_never_writes_a_trade(self):
        from bot_program.asset_engine.safety import enable_shadow
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade

        cfg = _cfg(self.user)
        enable_shadow(cfg, hours=24)

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.market_order = MagicMock()
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            result = StockBot(cfg).scan_symbol("AAPL")

        self.assertIsNone(result)
        client.market_order.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.filter(config=cfg).count(), 0)

    def test_expired_shadow_mode_trades_normally(self):
        from bot_program.asset_engine.safety import is_shadow
        cfg = _cfg(self.user, extras={
            "shadow_until": (timezone.now() - timedelta(hours=1)).isoformat()})
        self.assertFalse(is_shadow(cfg))

    def test_shadow_flag_survives_a_reload(self):
        from bot_program.asset_engine.safety import enable_shadow, is_shadow
        from bot_program.models import AssetBotConfig
        cfg = _cfg(self.user)
        enable_shadow(cfg, hours=2)
        self.assertTrue(is_shadow(AssetBotConfig.objects.get(pk=cfg.pk)))


# ── heartbeats ──────────────────────────────────────────────────────────

class HeartbeatTests(TestCase):
    def setUp(self):
        self.user = _user("hb_u")
        self.inst = _instrument()

    def test_tick_writes_a_heartbeat(self):
        from bot_program.asset_engine.safety import heartbeat_age_seconds
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotConfig
        cfg = _cfg(self.user)
        self.assertIsNone(heartbeat_age_seconds(cfg))

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            StockBot(cfg).tick()

        age = heartbeat_age_seconds(AssetBotConfig.objects.get(pk=cfg.pk))
        self.assertIsNotNone(age)
        self.assertLess(age, 60)

    def test_health_page_flags_a_bot_that_never_ticked(self):
        from dashboard.views_system_health import check_bot_heartbeats
        _cfg(self.user, name="NEVERTICKED")
        check = check_bot_heartbeats(self.user)
        self.assertEqual(check["state"], "fail")
        self.assertIn("NEVERTICKED", check["detail"])

    def test_health_page_accepts_a_fresh_heartbeat(self):
        from bot_program.asset_engine.safety import write_heartbeat
        from dashboard.views_system_health import check_bot_heartbeats
        cfg = _cfg(self.user, name="ALIVE")
        write_heartbeat(cfg)
        _closed(cfg, 5)
        self.assertEqual(check_bot_heartbeats(self.user)["state"], "ok")
