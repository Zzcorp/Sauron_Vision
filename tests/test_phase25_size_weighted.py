"""Phase-25 size-weighted orchestrator tests:
  - trade_size_weight returns ~1.0 for default-sized trades
  - 2x notional → ~2.0 weight
  - 0.5x notional → ~0.5 weight
  - clamp to [0.1, 5.0]
  - missing config / invalid capital / zero notional → 1.0 (neutral)
  - current_exposures default = unweighted (Phase 15-24 back-compat)
  - current_exposures size_weighted=True scales theme + currency contributions
  - sector concentration stays count-based regardless of size weighting
  - gate uses weighted exposure when toggle is on
  - profile POST persists toggle
  - Eye dashboard shows the size-weighted pill

Run with:  python manage.py test tests.test_phase25_size_weighted
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client


def _user(name="sw_u"):
    return User.objects.create_user(username=name, password="x")


def _profile(user, **kw):
    from portfolio.trader_profile import TraderProfile
    p, _ = TraderProfile.objects.get_or_create(user=user)
    for k, v in kw.items():
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


def _trade(cfg, *, symbol, side, qty, entry_price, asset_class=None, **kw):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class,
        symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry_price)),
        status="OPEN", **kw,
    )


# ── Weight calc ───────────────────────────────────────────────────────────

class WeightCalcTests(TestCase):
    def setUp(self):
        # capital=10000, position_size_pct=2 → default_notional = 200
        self.user = _user("w_u")
        self.cfg = _abc(self.user, "stock", name="ST")

    def test_default_size_returns_one(self):
        from bot_program.orchestrator import trade_size_weight
        # qty 2, entry 100 → notional 200 = default → weight 1.0
        t = _trade(self.cfg, symbol="X", side="BUY", qty=2, entry_price=100)
        self.assertAlmostEqual(trade_size_weight(t), 1.0, places=4)

    def test_double_size_returns_two(self):
        from bot_program.orchestrator import trade_size_weight
        # qty 4, entry 100 → notional 400 = 2× default → 2.0
        t = _trade(self.cfg, symbol="X", side="BUY", qty=4, entry_price=100)
        self.assertAlmostEqual(trade_size_weight(t), 2.0, places=4)

    def test_half_size_returns_half(self):
        from bot_program.orchestrator import trade_size_weight
        t = _trade(self.cfg, symbol="X", side="BUY", qty=1, entry_price=100)
        self.assertAlmostEqual(trade_size_weight(t), 0.5, places=4)

    def test_clamped_high(self):
        from bot_program.orchestrator import trade_size_weight
        # qty 100, entry 100 → notional 10000 = 50× default → clamp to 5.0
        t = _trade(self.cfg, symbol="X", side="BUY", qty=100, entry_price=100)
        self.assertEqual(trade_size_weight(t), 5.0)

    def test_clamped_low(self):
        from bot_program.orchestrator import trade_size_weight
        # qty 0.01, entry 100 → notional 1 = 0.005× default → clamp to 0.1
        t = _trade(self.cfg, symbol="X", side="BUY",
                   qty=Decimal("0.01"), entry_price=100)
        self.assertEqual(trade_size_weight(t), 0.1)

    def test_zero_notional_returns_one(self):
        from bot_program.orchestrator import trade_size_weight
        t = _trade(self.cfg, symbol="X", side="BUY", qty=0, entry_price=100)
        self.assertEqual(trade_size_weight(t), 1.0)

    def test_zero_position_pct_returns_one(self):
        from bot_program.orchestrator import trade_size_weight
        cfg = _abc(self.user, "stock", name="ZP",
                    position_size_pct=0.0)
        t = _trade(cfg, symbol="X", side="BUY", qty=2, entry_price=100)
        self.assertEqual(trade_size_weight(t), 1.0)


# ── Aggregator: back-compat default ──────────────────────────────────────

class AggregatorBackCompatTests(TestCase):
    def setUp(self):
        self.user = _user("agg_bc_u")
        self.cfg = _abc(self.user, "stock", name="ST")

    def test_default_unweighted(self):
        """Without size_weighted toggle, contributions stay ±1 (Phase 15-24)."""
        from bot_program.orchestrator import current_exposures
        # 4× sized position — would be weight 4 if weighting were on.
        _trade(self.cfg, symbol="A", side="BUY", qty=8, entry_price=100)
        e = current_exposures(self.user)
        self.assertEqual(e["themes"]["equity"], 1.0)  # not 4.0

    def test_weighted_on_scales_contributions(self):
        from bot_program.orchestrator import current_exposures
        _profile(self.user, size_weighted_orchestrator=True)
        # 2× sized position
        _trade(self.cfg, symbol="A", side="BUY", qty=4, entry_price=100)
        e = current_exposures(self.user)
        self.assertAlmostEqual(e["themes"]["equity"], 2.0, places=4)

    def test_currency_contributions_scaled(self):
        from bot_program.orchestrator import current_exposures
        _profile(self.user, size_weighted_orchestrator=True)
        fx = _abc(self.user, "forex", name="FX")
        # 3× sized (qty 6, entry 100 → notional 600 = 3× default)
        _trade(fx, symbol="EURUSD", side="BUY", qty=6, entry_price=100)
        e = current_exposures(self.user)
        self.assertAlmostEqual(e["currencies"]["EUR"], +3.0, places=4)
        self.assertAlmostEqual(e["currencies"]["USD"], -3.0, places=4)

    def test_sector_count_stays_integer_regardless_of_weight(self):
        from bot_program.orchestrator import current_exposures
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock",
                                       "sector": "Technology"})
        _profile(self.user, size_weighted_orchestrator=True)
        # Even at 5× size, sector count is 1.
        _trade(self.cfg, symbol="AAPL", side="BUY", qty=10, entry_price=100)
        e = current_exposures(self.user)
        self.assertEqual(e["sectors"]["technology"], 1)


# ── Gate uses weighted exposure ──────────────────────────────────────────

class GateWeightedTests(TestCase):
    def setUp(self):
        self.user = _user("gw_u")
        self.cfg = _abc(self.user, "stock", name="ST")

    def test_unweighted_gate_passes(self):
        """Without size weighting, single 4× position is 1.0 equity → under cap of 2."""
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=2.0,
                 max_usd_theme_exposure=10.0,
                 size_weighted_orchestrator=False)
        _trade(self.cfg, symbol="A", side="BUY", qty=8, entry_price=100)  # 4× size
        ok, _ = gate_new_entry(self.user, "stock", "B", "BUY")
        self.assertTrue(ok)

    def test_weighted_gate_blocks_oversized(self):
        """With weighting on, 4× position alone is 4.0 equity → over cap of 2."""
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=2.0,
                 max_usd_theme_exposure=10.0,
                 size_weighted_orchestrator=True)
        _trade(self.cfg, symbol="A", side="BUY", qty=8, entry_price=100)  # 4× size
        ok, reason = gate_new_entry(self.user, "stock", "B", "BUY")
        self.assertFalse(ok)
        self.assertIn("equity", reason)


# ── Profile UI ───────────────────────────────────────────────────────────

class ProfileToggleTests(TestCase):
    def test_post_persists_toggle(self):
        from portfolio.trader_profile import TraderProfile
        u = _user("prof_t_u")
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
            "max_vol_theme_exposure": "0",
            "max_currency_exposure": "0",
            "max_sector_exposure": "0",
            "size_weighted_orchestrator": "on",
        })
        p = TraderProfile.objects.get(user=u)
        self.assertTrue(p.size_weighted_orchestrator)


# ── Eye dashboard surfaces the indicator ─────────────────────────────────

class EyeIndicatorTests(TestCase):
    def test_eye_shows_pill_when_enabled(self):
        u = _user("eye_w_u")
        _profile(u, cross_asset_orchestrator_enabled=True,
                 size_weighted_orchestrator=True)
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        self.assertContains(r, "size-weighted")

    def test_eye_hides_pill_when_disabled(self):
        u = _user("eye_w_off_u")
        _profile(u, cross_asset_orchestrator_enabled=True,
                 size_weighted_orchestrator=False)
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        self.assertNotContains(r, "size-weighted")
