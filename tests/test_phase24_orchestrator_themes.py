"""Phase-24 multi-theme orchestrator tests:
  - classify_currencies (forex pairs incl. crosses like EURGBP)
  - classify_sector (Instrument.sector pulled for stocks/options)
  - classify_vol_long (long-premium options always +1)
  - current_exposures aggregates correctly across all dimensions
  - gate rejects on currency / sector / vol cap exceeded
  - default-zero caps preserve Phase-15 behaviour (back-compat)
  - Eye dashboard surfaces extras when caps non-zero

Run with:  python manage.py test tests.test_phase24_orchestrator_themes
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client


def _user(name="th_u"):
    return User.objects.create_user(username=name, password="x")


def _profile(user, **kw):
    from portfolio.trader_profile import TraderProfile
    p, _ = TraderProfile.objects.get_or_create(user=user)
    for k, v in kw.items():
        setattr(p, k, v)
    p.save()
    return p


def _instrument(symbol, asset_class="stock", sector=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class, "sector": sector},
    )
    if sector and inst.sector != sector:
        inst.sector = sector
        inst.save()
    return inst


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


# ── Currency classification ──────────────────────────────────────────────

class CurrencyClassifyTests(TestCase):
    def test_buy_eurusd(self):
        from bot_program.orchestrator import classify_currencies
        c = classify_currencies("forex", "EURUSD", "BUY")
        self.assertEqual(c, {"EUR": +1.0, "USD": -1.0})

    def test_sell_eurusd_inverts(self):
        from bot_program.orchestrator import classify_currencies
        c = classify_currencies("forex", "EURUSD", "SELL")
        self.assertEqual(c, {"EUR": -1.0, "USD": +1.0})

    def test_buy_eurgbp_cross(self):
        """The Phase-15 USD model returned {} — Phase-24 captures the cross."""
        from bot_program.orchestrator import classify_currencies
        c = classify_currencies("forex", "EURGBP", "BUY")
        self.assertEqual(c, {"EUR": +1.0, "GBP": -1.0})

    def test_buy_audjpy(self):
        from bot_program.orchestrator import classify_currencies
        c = classify_currencies("forex", "AUDJPY", "BUY")
        self.assertEqual(c, {"AUD": +1.0, "JPY": -1.0})

    def test_non_forex_returns_empty(self):
        from bot_program.orchestrator import classify_currencies
        self.assertEqual(classify_currencies("stock", "AAPL", "BUY"), {})
        self.assertEqual(classify_currencies("crypto", "BTCUSDT", "BUY"), {})

    def test_unknown_currency_returns_empty(self):
        from bot_program.orchestrator import classify_currencies
        # XYZ isn't in KNOWN_CURRENCIES
        self.assertEqual(classify_currencies("forex", "XYZUSD", "BUY"), {})


# ── Sector classification ────────────────────────────────────────────────

class SectorClassifyTests(TestCase):
    def test_stock_sector_lower_normalised(self):
        from bot_program.orchestrator import classify_sector
        _instrument("AAPL", asset_class="stock", sector="Technology")
        self.assertEqual(classify_sector("stock", "AAPL"), "technology")

    def test_options_inherits_sector(self):
        from bot_program.orchestrator import classify_sector
        _instrument("AAPL_OPT", asset_class="options", sector="Technology")
        self.assertEqual(classify_sector("options", "AAPL_OPT"), "technology")

    def test_forex_returns_blank(self):
        from bot_program.orchestrator import classify_sector
        _instrument("EURUSD", asset_class="forex")
        self.assertEqual(classify_sector("forex", "EURUSD"), "")

    def test_unknown_symbol_returns_blank(self):
        from bot_program.orchestrator import classify_sector
        self.assertEqual(classify_sector("stock", "DOESNOTEXIST"), "")


# ── Vol-long classification ──────────────────────────────────────────────

class VolLongClassifyTests(TestCase):
    def test_long_call_is_vol_long(self):
        from bot_program.orchestrator import classify_vol_long
        self.assertEqual(classify_vol_long("options", "BUY"), 1.0)

    def test_long_put_is_also_vol_long(self):
        """Both calls AND puts contribute to vol_long when bought (vega-positive)."""
        from bot_program.orchestrator import classify_vol_long
        self.assertEqual(classify_vol_long("options", "BUY"), 1.0)

    def test_non_options_zero(self):
        from bot_program.orchestrator import classify_vol_long
        self.assertEqual(classify_vol_long("stock", "BUY"), 0.0)
        self.assertEqual(classify_vol_long("forex", "BUY"), 0.0)


# ── Aggregator ───────────────────────────────────────────────────────────

class CurrentExposuresTests(TestCase):
    def setUp(self):
        self.user = _user("agg_u")

    def test_empty(self):
        from bot_program.orchestrator import current_exposures
        e = current_exposures(self.user)
        self.assertEqual(e["themes"]["usd"], 0)
        self.assertEqual(e["currencies"], {})
        self.assertEqual(e["sectors"], {})

    def test_currency_aggregation_includes_crosses(self):
        from bot_program.orchestrator import current_exposures
        fx = _abc(self.user, "forex", name="FX")
        # BUY EURUSD → EUR +1, USD -1
        # BUY EURGBP → EUR +1, GBP -1   (Phase-15 missed entirely)
        _open_trade(fx, symbol="EURUSD", side="BUY")
        _open_trade(fx, symbol="EURGBP", side="BUY")
        e = current_exposures(self.user)
        self.assertEqual(e["currencies"]["EUR"], +2.0)
        self.assertEqual(e["currencies"]["USD"], -1.0)
        self.assertEqual(e["currencies"]["GBP"], -1.0)

    def test_sector_concentration_count(self):
        from bot_program.orchestrator import current_exposures
        st = _abc(self.user, "stock", name="ST")
        _instrument("AAPL", asset_class="stock", sector="Technology")
        _instrument("MSFT", asset_class="stock", sector="Technology")
        _instrument("JPM",  asset_class="stock", sector="Finance")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(st, symbol="MSFT", side="BUY")
        _open_trade(st, symbol="JPM",  side="BUY")
        e = current_exposures(self.user)
        self.assertEqual(e["sectors"]["technology"], 2)
        self.assertEqual(e["sectors"]["finance"], 1)

    def test_vol_long_counts_options(self):
        from bot_program.orchestrator import current_exposures
        opt = _abc(self.user, "options", name="OPT")
        _open_trade(opt, symbol="AAPL", side="BUY", asset_class="options",
                    metadata={"right": "C"})
        _open_trade(opt, symbol="MSFT", side="BUY", asset_class="options",
                    metadata={"right": "P"})
        e = current_exposures(self.user)
        self.assertEqual(e["themes"]["vol_long"], 2.0)


# ── Gate ─────────────────────────────────────────────────────────────────

class GateMultiThemeTests(TestCase):
    def setUp(self):
        self.user = _user("gate24_u")

    def test_currency_cap_zero_disables(self):
        """max_currency_exposure=0 → no currency check (Phase-15 back-compat)."""
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=10.0,
                 max_currency_exposure=0)
        fx = _abc(self.user, "forex", name="FX")
        # 5 EUR-long positions — would breach if currency cap set.
        for sym in ("EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURAUD"):
            _open_trade(fx, symbol=sym, side="BUY")
        ok, reason = gate_new_entry(self.user, "forex", "EURNZD", "BUY")
        self.assertTrue(ok)  # no cap → allowed

    def test_currency_cap_blocks_over_limit(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=10.0,
                 max_currency_exposure=2.0)
        fx = _abc(self.user, "forex", name="FX")
        _open_trade(fx, symbol="EURUSD", side="BUY")  # EUR +1
        _open_trade(fx, symbol="EURGBP", side="BUY")  # EUR +2
        ok, reason = gate_new_entry(self.user, "forex", "EURJPY", "BUY")
        self.assertFalse(ok)
        self.assertIn("EUR", reason)
        self.assertIn("currency", reason)

    def test_sector_cap_zero_disables(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=99.0,
                 max_equity_theme_exposure=99.0,
                 max_sector_exposure=0)
        st = _abc(self.user, "stock", name="ST")
        for sym in ("A", "B", "C", "D"):
            _instrument(sym, asset_class="stock", sector="Technology")
            _open_trade(st, symbol=sym, side="BUY")
        _instrument("E", asset_class="stock", sector="Technology")
        ok, _ = gate_new_entry(self.user, "stock", "E", "BUY")
        self.assertTrue(ok)

    def test_sector_cap_blocks_concentration(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=99.0,
                 max_equity_theme_exposure=99.0,
                 max_sector_exposure=3)
        st = _abc(self.user, "stock", name="ST")
        for sym in ("A", "B", "C"):
            _instrument(sym, asset_class="stock", sector="Technology")
            _open_trade(st, symbol=sym, side="BUY")
        _instrument("D", asset_class="stock", sector="Technology")
        ok, reason = gate_new_entry(self.user, "stock", "D", "BUY")
        self.assertFalse(ok)
        self.assertIn("technology", reason)
        self.assertIn("sector", reason)

    def test_sector_cap_doesnt_block_different_sector(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=99.0,
                 max_equity_theme_exposure=99.0,
                 max_sector_exposure=3)
        st = _abc(self.user, "stock", name="ST")
        for sym in ("A", "B", "C"):
            _instrument(sym, asset_class="stock", sector="Technology")
            _open_trade(st, symbol=sym, side="BUY")
        _instrument("FIN1", asset_class="stock", sector="Finance")
        ok, _ = gate_new_entry(self.user, "stock", "FIN1", "BUY")
        self.assertTrue(ok)

    def test_vol_cap_blocks_options_stack(self):
        from bot_program.orchestrator import gate_new_entry
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=99.0,
                 max_equity_theme_exposure=99.0,
                 max_vol_theme_exposure=2)
        opt = _abc(self.user, "options", name="OPT")
        _instrument("AAPL", asset_class="options")
        _instrument("MSFT", asset_class="options")
        _open_trade(opt, symbol="AAPL", side="BUY", asset_class="options",
                    metadata={"right": "C"})
        _open_trade(opt, symbol="MSFT", side="BUY", asset_class="options",
                    metadata={"right": "C"})
        _instrument("NVDA", asset_class="options")
        ok, reason = gate_new_entry(self.user, "options", "NVDA", "BUY", right="C")
        self.assertFalse(ok)
        self.assertIn("vol_long", reason)


# ── Eye dashboard surfaces extras ───────────────────────────────────────

class EyeExtrasTests(TestCase):
    def test_eye_shows_currency_extras_when_cap_set(self):
        from django.test import Client
        u = _user("eye_extra_u")
        _profile(u, cross_asset_orchestrator_enabled=True,
                 max_currency_exposure=2.0)
        fx = _abc(u, "forex", name="FX")
        _open_trade(fx, symbol="EURUSD", side="BUY")
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "per-currency exposure")
        self.assertContains(r, "EUR")

    def test_eye_hides_extras_when_caps_zero(self):
        from django.test import Client
        u = _user("eye_extra_u_off")
        _profile(u, cross_asset_orchestrator_enabled=True,
                 max_currency_exposure=0,
                 max_vol_theme_exposure=0,
                 max_sector_exposure=0)
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "per-currency exposure")
        self.assertNotContains(r, "sector concentration")
