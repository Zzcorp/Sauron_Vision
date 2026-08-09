"""Data-feed integrity: symbol resolution, source precedence, staleness,
and free-tier budgets.

Run with:  python manage.py test tests.test_data_quality
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(inst, last, source, age_seconds=0):
    from market_data.models import LiveQuote
    q = LiveQuote.objects.create(instrument=inst, last=Decimal(str(last)),
                                  source=source)
    if age_seconds:
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_seconds))
        q.refresh_from_db()
    return q


# ── symbol resolution ───────────────────────────────────────────────────

class SymbolResolutionTests(TestCase):
    def test_exchange_symbol_resolves_to_the_instrument(self):
        """Binance streams BTCUSDT while the Instrument is BTCUSD — the
        mismatch meant every tick from the best crypto feed was dropped."""
        from market_data.quotes import resolve_instrument
        inst = _instrument("BTCUSD")
        self.assertEqual(resolve_instrument("BTCUSDT"), inst)

    def test_exact_symbol_still_resolves(self):
        from market_data.quotes import resolve_instrument
        inst = _instrument("ETHUSD")
        self.assertEqual(resolve_instrument("ETHUSD"), inst)

    def test_forex_underscore_form_resolves(self):
        from market_data.quotes import resolve_instrument
        inst = _instrument("EUR_USD", asset_class="forex")
        self.assertEqual(resolve_instrument("EURUSD"), inst)

    def test_unknown_symbol_returns_none(self):
        from market_data.quotes import resolve_instrument
        self.assertIsNone(resolve_instrument("NOSUCHPAIR"))


# ── source precedence ───────────────────────────────────────────────────

class SourcePrecedenceTests(TestCase):
    def setUp(self):
        self.inst = _instrument("AAPL", asset_class="stock")

    def test_delayed_source_cannot_clobber_a_fresh_live_stream(self):
        """LiveQuote is one row with one source column and several writers;
        a 15-minute-delayed yfinance poll used to overwrite a live tick."""
        from market_data.quotes import write_quote
        _quote(self.inst, 100, "finnhub_ws")
        self.assertFalse(
            write_quote("AAPL", last=95, source="yfinance"))
        from market_data.models import LiveQuote
        self.assertEqual(LiveQuote.objects.get(instrument=self.inst).source,
                         "finnhub_ws")

    def test_live_stream_overwrites_a_delayed_source(self):
        from market_data.quotes import write_quote
        _quote(self.inst, 100, "yfinance")
        self.assertTrue(write_quote("AAPL", last=101, source="finnhub_ws"))

    def test_a_source_may_always_update_itself(self):
        from market_data.quotes import write_quote
        _quote(self.inst, 100, "yfinance")
        self.assertTrue(write_quote("AAPL", last=101, source="yfinance"))

    def test_a_dead_premium_feed_stops_holding_the_row(self):
        """Otherwise one frozen stream freezes the price forever."""
        from market_data.quotes import write_quote
        _quote(self.inst, 100, "finnhub_ws", age_seconds=3600)
        self.assertTrue(write_quote("AAPL", last=105, source="yfinance"))

    def test_zero_prices_are_refused(self):
        """Several adapters default a missing field to 0, and a 0 in
        LiveQuote reads downstream as a real price."""
        from market_data.quotes import write_quote
        self.assertFalse(write_quote("AAPL", last=0, source="alpha_vantage"))
        self.assertFalse(write_quote("AAPL", last=None, source="alpha_vantage"))


# ── staleness guard on the learning loop ────────────────────────────────

class LifecycleStalenessTests(TestCase):
    def _signal(self, inst):
        from signals.models import Signal
        return Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="d", rule_name="r",
            score=0.7, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), suggested_stop=Decimal("95"),
            suggested_target=Decimal("110"), risk_reward_ratio=2.0,
            is_active=True)

    def test_stale_quote_does_not_resolve_an_outcome(self):
        """realized_r feeds decay -> actuator -> allocator and ultimately
        multiplies live position size."""
        from signals.performance import evaluate_signal_outcome
        inst = _instrument("STALE", asset_class="stock")
        sig = self._signal(inst)
        _quote(inst, 120, "yfinance", age_seconds=7200)  # above target
        self.assertIsNone(evaluate_signal_outcome(sig))
        sig.refresh_from_db()
        self.assertTrue(sig.is_active)

    def test_fresh_quote_resolves_normally(self):
        from signals.performance import evaluate_signal_outcome
        inst = _instrument("FRESH", asset_class="stock")
        sig = self._signal(inst)
        _quote(inst, 120, "yfinance")
        self.assertEqual(evaluate_signal_outcome(sig), "hit_target")


# ── free-tier budgets ───────────────────────────────────────────────────

class ApiBudgetTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_budget_is_consumed_and_then_blocks(self):
        from market_data.tasks import (
            _daily_budget_remaining, _record_api_call)
        self.assertEqual(_daily_budget_remaining("testprov", limit=3), 3)
        _record_api_call("testprov", 3)
        self.assertEqual(_daily_budget_remaining("testprov", limit=3), 0)

    def test_forex_task_skips_once_the_daily_budget_is_spent(self):
        from market_data.tasks import _record_api_call, AV_DAILY_LIMIT
        from market_data.tasks import fetch_forex_quotes
        _instrument("EURUSD", asset_class="forex")
        _record_api_call("alpha_vantage", AV_DAILY_LIMIT)
        result = fetch_forex_quotes()
        self.assertEqual(result.get("status"), "skipped")

    def test_beat_cadences_respect_free_tier_limits(self):
        """Alpha Vantage allows 25 calls/day; the old 120s cadence was
        ~288x over."""
        from config.celery import app
        schedule = app.conf.beat_schedule
        self.assertGreaterEqual(schedule["fetch-forex-live"]["schedule"], 900)
        self.assertGreaterEqual(schedule["fetch-breaking-news"]["schedule"], 600)
        self.assertGreaterEqual(schedule["fetch-crypto-prices"]["schedule"], 300)
