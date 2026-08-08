"""System health checks + trade forensics.

Run with:  python manage.py test tests.test_health_forensics
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="hf_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="HF", mode="paper",
                    symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _trade(cfg, **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=True, rule_name="rule_a",
        composite_score=0.8, reason="signal a · signal b")
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


# ── health checks ───────────────────────────────────────────────────────

class HealthCheckTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_beat_registration_check_passes(self):
        """This check is the guard for the bug class that already bit us:
        beat entries pointing at unregistered tasks."""
        from dashboard.views_system_health import check_beat_registration
        c = check_beat_registration()
        self.assertEqual(c["state"], "ok", c["detail"])

    def test_bars_check_fails_when_no_4h_bars_exist(self):
        from dashboard.views_system_health import check_bot_bars
        _instrument()
        _cfg(self.user)
        c = check_bot_bars()
        self.assertEqual(c["state"], "fail")
        self.assertIn("HOLD", c["detail"])

    def test_bars_check_passes_with_fresh_bars(self):
        from dashboard.views_system_health import check_bot_bars
        from market_data.models import PriceData
        inst = _instrument()
        _cfg(self.user)
        PriceData.objects.create(
            instrument=inst, timeframe="4h", timestamp=timezone.now(),
            open=1, high=2, low=1, close=2, volume=10, source="test")
        c = check_bot_bars()
        self.assertEqual(c["state"], "ok")

    def test_close_pending_check_flags_stranded_positions(self):
        from dashboard.views_system_health import check_close_pending
        cfg = _cfg(self.user)
        _trade(cfg, status="CLOSE_PENDING", paper=False,
               metadata={"close_retry_attempts": 4})
        c = check_close_pending(self.user)
        self.assertEqual(c["state"], "fail")
        self.assertIn("4 retries", c["detail"])

    def test_close_pending_check_ok_when_none(self):
        from dashboard.views_system_health import check_close_pending
        self.assertEqual(check_close_pending(self.user)["state"], "ok")

    def test_quote_freshness_flags_stale_source(self):
        from dashboard.views_system_health import check_quote_freshness
        from market_data.models import LiveQuote
        inst = _instrument("MSFT")
        q = LiveQuote.objects.create(instrument=inst, last=Decimal("10"),
                                      source="frozen_feed")
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(hours=3))
        c = check_quote_freshness()
        self.assertEqual(c["state"], "warn")
        self.assertIn("frozen_feed", c["detail"])

    def test_ai_models_check_reads_catalog(self):
        from dashboard.views_system_health import check_ai_models
        self.assertEqual(check_ai_models()["state"], "ok")

    def test_page_renders_and_summarises(self):
        self.client.force_login(self.user)
        r = self.client.get("/health/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SYSTEM HEALTH")

    def test_a_broken_check_never_breaks_the_page(self):
        from unittest.mock import patch
        self.client.force_login(self.user)
        with patch("dashboard.views_system_health.check_bot_bars",
                    side_effect=RuntimeError("boom")):
            r = self.client.get("/health/")
        self.assertEqual(r.status_code, 200)


# ── forensics ───────────────────────────────────────────────────────────

class ForensicsTests(TestCase):
    def setUp(self):
        self.user = _user("fx_u")
        self.inst = _instrument()
        self.cfg = _cfg(self.user)
        self.client.force_login(self.user)

    def test_list_renders_and_links_detail(self):
        trade = _trade(self.cfg)
        r = self.client.get("/forensics/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"/forensics/{trade.id}/")

    def test_list_filters_by_symbol(self):
        _trade(self.cfg, symbol="AAPL")
        _instrument("TSLA")
        _trade(self.cfg, symbol="TSLA")
        r = self.client.get("/forensics/?symbol=TSLA")
        self.assertContains(r, "TSLA")
        self.assertNotContains(r, ">AAPL<")

    def test_detail_shows_reasons_and_lifecycle(self):
        trade = _trade(self.cfg, metadata={"fill_source": "broker"})
        r = self.client.get(f"/forensics/{trade.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "signal a")
        self.assertContains(r, "Entry filled")
        self.assertContains(r, "broker fill")

    def test_detail_surfaces_close_pending(self):
        trade = _trade(self.cfg, status="CLOSE_PENDING", paper=False,
                       metadata={"close_retry_attempts": 2,
                                  "close_retry_last_error": "broker 503"})
        r = self.client.get(f"/forensics/{trade.id}/")
        self.assertContains(r, "Close failed")
        self.assertContains(r, "broker 503")

    def test_detail_lists_nearby_signals(self):
        from signals.models import Signal
        trade = _trade(self.cfg)
        Signal.objects.create(
            instrument=self.inst, signal_type="composite", direction="bullish",
            urgency="medium", title="breakout confirmed", description="d",
            rule_name="rule_a", score=0.9, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"))
        r = self.client.get(f"/forensics/{trade.id}/")
        self.assertContains(r, "breakout confirmed")

    def test_detail_shows_broker_protection(self):
        trade = _trade(self.cfg, metadata={"protected": True,
                                            "protective_order_ids": ["a", "b"]})
        r = self.client.get(f"/forensics/{trade.id}/")
        self.assertContains(r, "Broker-side protection")
        self.assertContains(r, "2 legs")

    def test_other_users_trades_are_not_visible(self):
        other = _user("fx_other")
        other_trade = _trade(_cfg(other, name="OTHER"))
        r = self.client.get(f"/forensics/{other_trade.id}/")
        self.assertEqual(r.status_code, 404)
