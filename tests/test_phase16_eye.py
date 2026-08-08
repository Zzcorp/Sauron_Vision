"""Phase-16 Sauron's Eye tests:
  - OrchestratorEvent persists from gate decisions (rejects always logged)
  - Eye view renders empty + populated
  - Theme exposure status flag (ok/near/over)
  - Aggregation across AssetBotTrade + BotTrade
  - HTMX partial endpoint returns body fragment

Run with:  python manage.py test tests.test_phase16_eye
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client


def _user(name="eye_u"):
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


# ── OrchestratorEvent + gate logging ──────────────────────────────────────

class OrchestratorEventLoggingTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_reject_always_logs(self):
        from bot_program.orchestrator import gate_new_entry
        from bot_program.orchestrator_models import OrchestratorEvent
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=2.0,
                 max_usd_theme_exposure=10.0)
        st = _abc(self.user, "stock", name="ST")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(st, symbol="MSFT", side="BUY")
        ok, _ = gate_new_entry(self.user, "stock", "NVDA", "BUY")
        self.assertFalse(ok)

        events = OrchestratorEvent.objects.filter(user=self.user)
        self.assertEqual(events.count(), 1)
        ev = events.first()
        self.assertEqual(ev.decision, "reject")
        self.assertEqual(ev.symbol, "NVDA")
        self.assertIn("equity", ev.reason)
        self.assertEqual(ev.exposure_before["equity"], 2.0)
        self.assertEqual(ev.exposure_after["equity"], 3.0)

    def test_orchestrator_off_does_not_log(self):
        """No profile or disabled → no event row."""
        from bot_program.orchestrator import gate_new_entry
        from bot_program.orchestrator_models import OrchestratorEvent
        ok, reason = gate_new_entry(self.user, "stock", "AAPL", "BUY")
        self.assertTrue(ok)
        self.assertEqual(reason, "orchestrator_off")
        self.assertEqual(OrchestratorEvent.objects.count(), 0)

    def test_allow_logs_at_sample_rate(self):
        """Allows are sampled at ~10% — patch random to force a log."""
        from bot_program.orchestrator import gate_new_entry
        from bot_program.orchestrator_models import OrchestratorEvent
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=10.0,
                 max_usd_theme_exposure=10.0)
        with patch("random.random", return_value=0.05):  # below 0.10 → logged
            ok, _ = gate_new_entry(self.user, "stock", "AAPL", "BUY")
        self.assertTrue(ok)
        self.assertEqual(OrchestratorEvent.objects.count(), 1)
        self.assertEqual(OrchestratorEvent.objects.first().decision, "allow")

    def test_allow_skipped_above_sample_threshold(self):
        from bot_program.orchestrator import gate_new_entry
        from bot_program.orchestrator_models import OrchestratorEvent
        _profile(self.user,
                 cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=10.0,
                 max_usd_theme_exposure=10.0)
        with patch("random.random", return_value=0.50):  # above 0.10 → skipped
            ok, _ = gate_new_entry(self.user, "stock", "AAPL", "BUY")
        self.assertTrue(ok)
        self.assertEqual(OrchestratorEvent.objects.count(), 0)


# ── Eye view ──────────────────────────────────────────────────────────────

class EyeViewTests(TestCase):
    def setUp(self):
        self.user = _user("eye_view_u")
        self.client = Client()
        self.client.force_login(self.user)

    def test_empty_eye_renders(self):
        """User with nothing — page should still render 200."""
        r = self.client.get("/eye/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SAURON")
        self.assertContains(r, "orchestrator: OFF")

    def test_partial_endpoint_returns_body(self):
        r = self.client.get("/eye/partial/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Theme Exposure")

    def test_with_open_positions_renders_table(self):
        st = _abc(self.user, "stock", name="ST")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(st, symbol="MSFT", side="BUY")
        r = self.client.get("/eye/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "AAPL")
        self.assertContains(r, "MSFT")

    def test_with_orchestrator_enabled_shows_on_pill(self):
        _profile(self.user, cross_asset_orchestrator_enabled=True)
        r = self.client.get("/eye/")
        self.assertContains(r, "orchestrator: ON")

    def test_recent_gate_events_render(self):
        from bot_program.orchestrator_models import OrchestratorEvent
        OrchestratorEvent.objects.create(
            user=self.user, asset_class="stock", symbol="NVDA",
            side="BUY", decision="reject",
            reason="orchestrator: equity theme cap |+3.0| > 2.0",
            exposure_before={"usd": 0, "equity": 2.0},
            exposure_after={"usd": 0, "equity": 3.0},
            caps={"usd": 10, "equity": 2.0},
        )
        r = self.client.get("/eye/")
        self.assertContains(r, "NVDA")
        self.assertContains(r, "REJECT")


# ── Theme exposure status pills ───────────────────────────────────────────

class ThemeExposureStatusTests(TestCase):
    def setUp(self):
        self.user = _user("eye_status_u")

    def _exposure(self):
        from dashboard.views_eye import _theme_exposure
        return _theme_exposure(self.user)

    def test_no_profile_off(self):
        result = self._exposure()
        self.assertFalse(result["enabled"])
        self.assertEqual(result["exposure"]["usd"]["status"], "ok")

    def test_disabled_orchestrator_still_computes(self):
        _profile(self.user, cross_asset_orchestrator_enabled=False)
        result = self._exposure()
        self.assertFalse(result["enabled"])
        # values still 0, status 'ok'
        self.assertEqual(result["exposure"]["usd"]["value"], 0)

    def test_under_cap_is_ok(self):
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=10.0)
        st = _abc(self.user, "stock", name="ST")
        _open_trade(st, symbol="AAPL", side="BUY")  # equity +1
        result = self._exposure()
        self.assertEqual(result["exposure"]["equity"]["status"], "ok")

    def test_near_cap(self):
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=4.0)
        st = _abc(self.user, "stock", name="ST")
        for sym in ("A", "B", "C"):
            _open_trade(st, symbol=sym, side="BUY")  # 3/4 = 0.75 → near
        result = self._exposure()
        self.assertEqual(result["exposure"]["equity"]["status"], "near")

    def test_over_cap(self):
        _profile(self.user, cross_asset_orchestrator_enabled=True,
                 max_usd_theme_exposure=10.0,
                 max_equity_theme_exposure=2.0)
        st = _abc(self.user, "stock", name="ST")
        for sym in ("A", "B", "C"):
            _open_trade(st, symbol=sym, side="BUY")  # 3/2 = 1.5 → over
        result = self._exposure()
        self.assertEqual(result["exposure"]["equity"]["status"], "over")


# ── Aggregation helpers ───────────────────────────────────────────────────

class AggregationTests(TestCase):
    def setUp(self):
        self.user = _user("eye_agg_u")

    def test_open_positions_unified_across_classes(self):
        from dashboard.views_eye import _open_positions
        st = _abc(self.user, "stock", name="ST")
        fx = _abc(self.user, "forex", name="FX")
        _open_trade(st, symbol="AAPL", side="BUY")
        _open_trade(fx, symbol="EURUSD", side="BUY")
        rows = _open_positions(self.user)
        symbols = sorted(r["symbol"] for r in rows)
        self.assertEqual(symbols, ["AAPL", "EURUSD"])

    def test_pnl_24h_sums_by_class(self):
        from datetime import timedelta
        from django.utils import timezone
        from bot_program.models import AssetBotTrade
        from dashboard.views_eye import _pnl_24h
        st = _abc(self.user, "stock", name="ST")
        fx = _abc(self.user, "forex", name="FX")
        # Two CLOSED stock trades, one CLOSED forex trade — within 24h.
        AssetBotTrade.objects.create(
            config=st, asset_class="stock", symbol="A", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            exit_price=Decimal("110"), pnl=Decimal("10"),
            status="CLOSED", closed_at=timezone.now() - timedelta(hours=1),
        )
        AssetBotTrade.objects.create(
            config=st, asset_class="stock", symbol="B", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("50"),
            exit_price=Decimal("48"), pnl=Decimal("-2"),
            status="CLOSED", closed_at=timezone.now() - timedelta(hours=2),
        )
        AssetBotTrade.objects.create(
            config=fx, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("1"),
            exit_price=Decimal("1.01"), pnl=Decimal("5"),
            status="CLOSED", closed_at=timezone.now() - timedelta(hours=3),
        )
        result = _pnl_24h(self.user)
        self.assertEqual(result["total"], Decimal("13"))
        self.assertEqual(result["by_class"]["stock"]["pnl"], Decimal("8"))
        self.assertEqual(result["by_class"]["stock"]["count"], 2)
        self.assertEqual(result["by_class"]["forex"]["pnl"], Decimal("5"))

    def test_bot_health_lists_configs(self):
        from dashboard.views_eye import _bot_health
        _abc(self.user, "stock", name="A")
        _abc(self.user, "forex", name="B")
        rows = _bot_health(self.user)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["asset_class"] for r in rows}, {"stock", "forex"})
