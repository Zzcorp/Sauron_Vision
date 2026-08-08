"""Phase-15 cross-asset orchestrator tests:
  - Theme classification per asset_class/symbol/side
  - Aggregate exposure across open AssetBotTrade + BotTrade
  - Gate accept/reject + opt-in/opt-out via TraderProfile
  - Profile UI persists toggle + thresholds

Run with:  python manage.py test tests.test_phase15_orchestrator
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse


def _user(name="orch_u"):
    return User.objects.create_user(username=name, password="x")


def _profile(user, **kwargs):
    from portfolio.trader_profile import TraderProfile
    p, _ = TraderProfile.objects.get_or_create(user=user)
    for k, v in kwargs.items():
        setattr(p, k, v)
    p.save()
    return p


def _abc(user, asset_class, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


def _open_trade(cfg, *, symbol, side, asset_class=None, **kw):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class,
        symbol=symbol, side=side,
        qty=Decimal("1"), entry_price=Decimal("100"),
        status="OPEN", **kw,
    )


# ── Classification ────────────────────────────────────────────────────────

class ClassifyPositionTests(TestCase):
    def test_forex_buy_eurusd_is_short_usd(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("forex", "EURUSD", "BUY")
        self.assertEqual(c, {"usd": -1.0, "equity": 0.0})

    def test_forex_buy_usdjpy_is_long_usd(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("forex", "USDJPY", "BUY")
        self.assertEqual(c, {"usd": +1.0, "equity": 0.0})

    def test_forex_sell_eurusd_is_long_usd(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("forex", "EURUSD", "SELL")
        self.assertEqual(c, {"usd": +1.0, "equity": 0.0})

    def test_stock_buy_is_long_equity_no_usd(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("stock", "AAPL", "BUY")
        self.assertEqual(c, {"usd": 0.0, "equity": +1.0})

    def test_stock_sell_is_short_equity(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("stock", "AAPL", "SELL")
        self.assertEqual(c, {"usd": 0.0, "equity": -1.0})

    def test_gold_buy_is_short_usd(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("commodity", "GC", "BUY")
        self.assertEqual(c, {"usd": -1.0, "equity": 0.0})

    def test_xauusd_spot_buy_is_short_usd(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("commodity", "XAUUSD", "BUY")
        self.assertEqual(c["usd"], -1.0)

    def test_crypto_btc_buy_is_short_usd_long_equity(self):
        from bot_program.orchestrator import classify_position
        c = classify_position("crypto", "BTCUSDT", "BUY")
        self.assertEqual(c, {"usd": -1.0, "equity": +1.0})

    def test_options_long_call(self):
        from bot_program.orchestrator import classify_option_position
        c = classify_option_position("BUY", "C")
        self.assertEqual(c, {"usd": 0.0, "equity": +1.0})

    def test_options_long_put(self):
        from bot_program.orchestrator import classify_option_position
        c = classify_option_position("BUY", "P")
        self.assertEqual(c, {"usd": 0.0, "equity": -1.0})


# ── Exposure aggregation ──────────────────────────────────────────────────

class ExposureAggregationTests(TestCase):
    def setUp(self):
        self.user = _user("agg_u")

    def test_no_open_positions(self):
        from bot_program.orchestrator import current_theme_exposure
        self.assertEqual(current_theme_exposure(self.user),
                         {"usd": 0.0, "equity": 0.0})

    def test_sums_across_asset_bot_trades(self):
        from bot_program.orchestrator import current_theme_exposure
        fx = _abc(self.user, "forex", name="FX")
        st = _abc(self.user, "stock", name="ST")
        _open_trade(fx, symbol="EURUSD", side="BUY")    # usd -1
        _open_trade(fx, symbol="GBPUSD", side="BUY")    # usd -1
        _open_trade(st, symbol="AAPL", side="BUY")      # equity +1
        _open_trade(st, symbol="MSFT", side="BUY")      # equity +1
        e = current_theme_exposure(self.user)
        self.assertEqual(e["usd"], -2.0)
        self.assertEqual(e["equity"], +2.0)

    def test_options_long_call_adds_equity(self):
        from bot_program.orchestrator import current_theme_exposure
        opt = _abc(self.user, "options", name="OPT")
        _open_trade(opt, symbol="AAPL", side="BUY",
                    asset_class="options",
                    metadata={"right": "C", "strike": 180})
        _open_trade(opt, symbol="MSFT", side="BUY",
                    asset_class="options",
                    metadata={"right": "P", "strike": 400})
        e = current_theme_exposure(self.user)
        self.assertEqual(e["equity"], 0.0)  # +1 (call) -1 (put)

    def test_closed_trades_not_counted(self):
        from bot_program.orchestrator import current_theme_exposure
        fx = _abc(self.user, "forex", name="FX")
        t = _open_trade(fx, symbol="EURUSD", side="BUY")
        t.status = "CLOSED"
        t.save()
        self.assertEqual(current_theme_exposure(self.user),
                         {"usd": 0.0, "equity": 0.0})


# ── Gate ──────────────────────────────────────────────────────────────────

class GateTests(TestCase):
    def setUp(self):
        self.user = _user("gate_u")

    def test_no_profile_passes_through(self):
        """User with no TraderProfile → orchestrator_off."""
        from bot_program.orchestrator import gate_new_entry
        ok, reason = gate_new_entry(self.user, "stock", "AAPL", "BUY")
        self.assertTrue(ok)
        self.assertEqual(reason, "orchestrator_off")

    def test_profile_disabled_passes_through(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=False)
        ok, reason = gate_new_entry(self.user, "stock", "AAPL", "BUY")
        self.assertTrue(ok)
        self.assertEqual(reason, "orchestrator_off")

    def test_profile_enabled_within_caps_allows(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=3.0,
                 max_equity_theme_exposure=3.0)
        ok, reason = gate_new_entry(self.user, "stock", "AAPL", "BUY")
        self.assertTrue(ok)
        self.assertEqual(reason, "orchestrator_pass")

    def test_blocks_when_new_entry_would_exceed_equity_cap(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=2.0)
        # Already +2 equity from existing positions.
        st = _abc(self.user, "stock", name="ST")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(st, symbol="MSFT", side="BUY")
        ok, reason = gate_new_entry(self.user, "stock", "NVDA", "BUY")
        self.assertFalse(ok)
        self.assertIn("equity", reason)

    def test_blocks_when_new_entry_would_exceed_usd_cap(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=2.0,
                 max_equity_theme_exposure=10.0)
        # +2 long USD already (two USD-base forex BUYs).
        fx = _abc(self.user, "forex", name="FX")
        _open_trade(fx, symbol="USDJPY", side="BUY")
        _open_trade(fx, symbol="USDCAD", side="BUY")
        ok, reason = gate_new_entry(self.user, "forex", "USDCHF", "BUY")
        self.assertFalse(ok)
        self.assertIn("usd", reason)

    def test_allows_opposite_direction_to_reduce_exposure(self):
        """Already long +3 equity, cap is 2 — but a SELL should still pass
        because it *reduces* exposure (closes never get gated, but a fresh
        short is also fine since after_value < cur_value)."""
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=2.0)
        st = _abc(self.user, "stock", name="ST")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(st, symbol="MSFT", side="BUY")
        _open_trade(st, symbol="NVDA", side="BUY")
        # Currently equity = +3, cap = 2 → already over, but a SELL reduces.
        ok, reason = gate_new_entry(self.user, "stock", "TSLA", "SELL")
        self.assertTrue(ok)

    def test_options_long_call_counts_as_equity(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=2.0)
        st = _abc(self.user, "stock", name="ST")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(st, symbol="MSFT", side="BUY")
        # Already +2 equity; another long call would push to +3 → block.
        ok, reason = gate_new_entry(
            self.user, "options", "NVDA", "BUY", right="C")
        self.assertFalse(ok)


# ── AssetBot integration ──────────────────────────────────────────────────

class AssetBotGateIntegrationTests(TestCase):
    """The gate is consulted from `AssetBot.scan_symbol`. With the toggle off,
    nothing changes; with it on and exposure full, scan_symbol returns None."""

    def setUp(self):
        self.user = _user("integ_u")

    def test_scan_symbol_blocked_when_orchestrator_rejects(self):
        from bot_program.asset_engine import StockBot
        from instruments.models import Instrument
        from signals.models import Signal
        # Strict cap so two existing trades fill the budget.
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=2.0,
                 max_usd_theme_exposure=10.0)
        st = _abc(self.user, "stock", name="ST", symbols=["NEW"])
        # Two existing long-equity positions saturate the cap.
        _open_trade(st, symbol="A", side="BUY")
        _open_trade(st, symbol="B", side="BUY")
        # Seed a bullish signal for "NEW" so default decide() returns BUY.
        inst, _ = Instrument.objects.get_or_create(
            symbol="NEW", defaults={"name": "NEW", "asset_class": "stock"})
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )
        result = StockBot(st).scan_symbol("NEW")
        self.assertIsNone(result)


# ── Profile UI persistence ────────────────────────────────────────────────

class ProfileSettingsUITests(TestCase):
    def test_post_persists_orchestrator_fields(self):
        from portfolio.trader_profile import TraderProfile
        u = _user("ui_u")
        c = Client()
        c.force_login(u)
        # Minimal POST mimicking what the form sends.
        c.post("/profile/", {
            "email": "x@y.z", "first_name": "A", "last_name": "B",
            "display_name": "", "bio": "", "location": "", "phone": "",
            "timezone_preference": "UTC",
            "experience_level": "intermediate",
            "trading_style": "swing_trader",
            "risk_appetite": "moderate",
            "analysis_approach": "mixed",
            "preferred_session": "european",
            "available_hours_per_day": "2",
            "monthly_return_target_pct": "3",
            "max_acceptable_drawdown_pct": "10",
            "annual_income_target": "0",
            "ai_autonomy": "suggest",
            "ai_commentary_detail": "detailed",
            "notify_channel": "telegram",
            # Orchestrator fields:
            "cross_asset_orchestrator_enabled": "on",
            "max_usd_theme_exposure": "5",
            "max_equity_theme_exposure": "4",
        })
        p = TraderProfile.objects.get(user=u)
        self.assertTrue(p.cross_asset_orchestrator_enabled)
        self.assertEqual(p.max_usd_theme_exposure, 5.0)
        self.assertEqual(p.max_equity_theme_exposure, 4.0)

    def test_post_without_checkbox_disables_orchestrator(self):
        from portfolio.trader_profile import TraderProfile
        u = _user("ui_u_off")
        # Pre-enable to make sure POST clears it.
        _profile(u, cross_asset_orchestrator_enabled=True)
        c = Client()
        c.force_login(u)
        c.post("/profile/", {
            "email": "", "first_name": "", "last_name": "",
            "display_name": "", "bio": "", "location": "", "phone": "",
            "timezone_preference": "UTC",
            "experience_level": "intermediate",
            "trading_style": "swing_trader",
            "risk_appetite": "moderate",
            "analysis_approach": "mixed",
            "preferred_session": "european",
            "available_hours_per_day": "2",
            "monthly_return_target_pct": "3",
            "max_acceptable_drawdown_pct": "10",
            "annual_income_target": "0",
            "ai_autonomy": "suggest",
            "ai_commentary_detail": "detailed",
            "notify_channel": "telegram",
            "max_usd_theme_exposure": "3",
            "max_equity_theme_exposure": "3",
            # cross_asset_orchestrator_enabled intentionally absent
        })
        p = TraderProfile.objects.get(user=u)
        self.assertFalse(p.cross_asset_orchestrator_enabled)
