"""Tests for Phase-10 multi-modal opportunity scanner.

Covers:
  - Evaluator registry: register_kind / has_kind
  - Built-in evaluators:
      price_pattern: above_ma, below_ma, breakout_high, breakout_low
      news_volume: count of relevant news
      news_sentiment: avg sentiment threshold
      calendar_event: filter match
  - scan_setup creates an OpportunityFlag + linked Signal when score ≥ min
  - scan_setup respects asset_class filter (skip)
  - scan_setup creates nothing when score is below threshold
  - resolve_pending_flags: hit / miss / neutral classification
  - Signal that's created has the right rule_name + price levels (so Phase 1 grades it)

Run with:  python manage.py test tests.test_opportunity_scanner
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from typing import List

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_prices(instrument, closes: List[float], end=None):
    """Seed daily PriceData with the given closes (oldest first)."""
    from market_data.models import PriceData
    end = end or timezone.now()
    rows = []
    for i, c in enumerate(closes):
        ts = end - timedelta(days=len(closes) - i)
        rows.append(PriceData(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=Decimal(str(c)), high=Decimal(str(c)), low=Decimal(str(c)),
            close=Decimal(str(c)), volume=0, source="test",
        ))
    PriceData.objects.bulk_create(rows)


def _seed_news(symbol, count: int, sentiment: float = 0.5, days_ago_max=2):
    """Seed NewsArticle rows mentioning the symbol."""
    from scraping.models import NewsArticle
    rows = []
    for i in range(count):
        rows.append(NewsArticle(
            title=f"News {i} about {symbol}",
            source="test",
            url=f"http://example.com/{symbol}/{i}",
            published_at=timezone.now() - timedelta(hours=i + 1),
            content_summary=f"Some summary about {symbol} happening.",
            ai_sentiment_score=sentiment,
        ))
    NewsArticle.objects.bulk_create(rows)


# ── Evaluator registry ─────────────────────────────────────────────────────

class EvaluatorRegistryTests(TestCase):
    def test_built_in_kinds_registered(self):
        from signals.opportunity_scanner import has_kind
        self.assertTrue(has_kind("price_pattern"))
        self.assertTrue(has_kind("news_volume"))
        self.assertTrue(has_kind("news_sentiment"))
        self.assertTrue(has_kind("calendar_event"))
        self.assertFalse(has_kind("nonexistent"))

    def test_register_rejects_non_callable(self):
        from signals.opportunity_scanner import register_kind
        with self.assertRaises(TypeError):
            register_kind("bad", "not callable")


# ── Built-in evaluators ────────────────────────────────────────────────────

class PricePatternEvaluatorTests(TestCase):
    def test_above_ma_matches(self):
        from signals.opportunity_scanner import _eval_price_pattern
        inst = _instrument("AB1")
        # Closes trending up: MA(50) ≈ middle, last is highest.
        closes = [float(50 + i) for i in range(60)]
        _seed_prices(inst, closes)
        result = _eval_price_pattern({"pattern": "above_ma", "ma_period": 50}, inst, timezone.now())
        self.assertTrue(result["matched"])
        self.assertGreater(result["details"]["last"], result["details"]["ma"])

    def test_above_ma_does_not_match_when_below(self):
        from signals.opportunity_scanner import _eval_price_pattern
        inst = _instrument("AB2")
        # Trending down: last is lowest, well below MA(50).
        closes = [float(100 - i) for i in range(60)]
        _seed_prices(inst, closes)
        result = _eval_price_pattern({"pattern": "above_ma", "ma_period": 50}, inst, timezone.now())
        self.assertFalse(result["matched"])

    def test_breakout_high_matches(self):
        from signals.opportunity_scanner import _eval_price_pattern
        inst = _instrument("BO1")
        # 20 closes around 100, last close is 110 (clear breakout).
        closes = [100.0] * 20 + [110.0]
        _seed_prices(inst, closes)
        result = _eval_price_pattern({"pattern": "breakout_high", "lookback": 20}, inst, timezone.now())
        self.assertTrue(result["matched"])

    def test_breakout_high_no_match_when_inside_range(self):
        from signals.opportunity_scanner import _eval_price_pattern
        inst = _instrument("BO2")
        closes = [100.0] * 20 + [99.0]
        _seed_prices(inst, closes)
        result = _eval_price_pattern({"pattern": "breakout_high", "lookback": 20}, inst, timezone.now())
        self.assertFalse(result["matched"])

    def test_insufficient_data_no_match(self):
        from signals.opportunity_scanner import _eval_price_pattern
        inst = _instrument("BO3")
        _seed_prices(inst, [100.0, 101.0])  # only 2 closes
        result = _eval_price_pattern({"pattern": "above_ma", "ma_period": 50}, inst, timezone.now())
        self.assertFalse(result["matched"])


class NewsVolumeEvaluatorTests(TestCase):
    def test_matches_when_volume_meets_min(self):
        from signals.opportunity_scanner import _eval_news_volume
        inst = _instrument("NV1")
        _seed_news("NV1", count=5)
        result = _eval_news_volume(
            {"keywords": ["NV1"], "min_count": 3, "lookback_days": 2},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertGreaterEqual(result["details"]["n"], 3)

    def test_no_match_when_below_min(self):
        from signals.opportunity_scanner import _eval_news_volume
        inst = _instrument("NV2")
        _seed_news("NV2", count=2)
        result = _eval_news_volume(
            {"keywords": ["NV2"], "min_count": 5, "lookback_days": 2},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


class NewsSentimentEvaluatorTests(TestCase):
    def test_matches_when_avg_sentiment_above_threshold(self):
        from signals.opportunity_scanner import _eval_news_sentiment
        inst = _instrument("NS1")
        _seed_news("NS1", count=5, sentiment=0.6)
        result = _eval_news_sentiment(
            {"keywords": ["NS1"], "direction": "above",
             "threshold": 0.3, "min_count": 3, "lookback_days": 2},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])

    def test_no_match_when_below_threshold(self):
        from signals.opportunity_scanner import _eval_news_sentiment
        inst = _instrument("NS2")
        _seed_news("NS2", count=5, sentiment=0.1)
        result = _eval_news_sentiment(
            {"keywords": ["NS2"], "direction": "above",
             "threshold": 0.5, "min_count": 3, "lookback_days": 2},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


class CalendarEventEvaluatorTests(TestCase):
    def test_matches_when_event_filter_hits(self):
        from signals.opportunity_scanner import _eval_calendar_event
        from market_data.models import EconomicEvent
        EconomicEvent.objects.create(
            title="FOMC Statement", country="US", impact="high",
            datetime=timezone.now() - timedelta(days=1),
        )
        inst = _instrument("CAL1")
        result = _eval_calendar_event(
            {"title_contains": "FOMC", "lookback_days": 3, "impact": "high"},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])

    def test_no_match_outside_window(self):
        from signals.opportunity_scanner import _eval_calendar_event
        from market_data.models import EconomicEvent
        EconomicEvent.objects.create(
            title="FOMC Statement", country="US", impact="high",
            datetime=timezone.now() - timedelta(days=20),
        )
        inst = _instrument("CAL2")
        result = _eval_calendar_event(
            {"title_contains": "FOMC", "lookback_days": 3},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── scan_setup end-to-end ──────────────────────────────────────────────────

class ScanSetupTests(TestCase):
    def setUp(self):
        from signals.models import OpportunitySetup
        self.inst = _instrument("AAPL", asset_class="stock")
        # Trending up — above_ma should match.
        _seed_prices(self.inst, [float(100 + i) for i in range(60)])

        self.setup = OpportunitySetup.objects.create(
            name="trending_above_ma",
            description="Simple uptrend above MA(50)",
            direction="bullish",
            asset_classes=["stock", "etf"],
            conditions=[
                {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 50},
                 "weight": 1.0},
            ],
            min_match_score=0.5,
            suggested_horizon_days=5,
            sizing={"stop_pct": 2.0, "target_rr": 2.0},
            is_active=True,
        )

    def test_match_creates_flag_and_signal(self):
        from signals.opportunity_scanner import scan_setup
        from signals.models import OpportunityFlag, Signal
        result = scan_setup(self.setup, self.inst)
        self.assertTrue(result["matched"])

        flag = OpportunityFlag.objects.get(id=result["flag_id"])
        self.assertEqual(flag.setup, self.setup)
        self.assertEqual(flag.instrument, self.inst)
        self.assertEqual(flag.direction, "bullish")
        self.assertIsNotNone(flag.signal)

        signal = Signal.objects.get(id=result["signal_id"])
        self.assertEqual(signal.rule_name, self.setup.name)
        self.assertEqual(signal.direction, "bullish")
        self.assertGreater(signal.suggested_target, signal.suggested_entry)
        self.assertLess(signal.suggested_stop, signal.suggested_entry)

    def test_asset_class_filter_skips(self):
        from signals.opportunity_scanner import scan_setup
        forex_inst = _instrument("EURUSD", asset_class="forex")
        _seed_prices(forex_inst, [float(1.0 + i * 0.01) for i in range(60)])
        result = scan_setup(self.setup, forex_inst)
        self.assertFalse(result["matched"])
        self.assertTrue(result.get("skipped"))

    def test_no_signal_when_score_below_min(self):
        from signals.opportunity_scanner import scan_setup
        from signals.models import OpportunityFlag
        # Bump min_match_score above what a single matched condition can produce.
        self.setup.min_match_score = 1.5
        self.setup.save()
        result = scan_setup(self.setup, self.inst)
        self.assertFalse(result["matched"])
        self.assertEqual(OpportunityFlag.objects.count(), 0)


# ── Resolution ─────────────────────────────────────────────────────────────

class ResolutionTests(TestCase):
    def test_hit_outcome_when_target_reached(self):
        from signals.models import OpportunitySetup, OpportunityFlag
        from signals.opportunity_scanner import resolve_pending_flags

        inst = _instrument("RES1", asset_class="stock")
        _seed_prices(inst, [120.0])  # current price above target (=110)

        setup = OpportunitySetup.objects.create(
            name="res_test_1", direction="bullish",
            conditions=[], min_match_score=0.0, suggested_horizon_days=5,
            asset_classes=[],
        )
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=inst, direction="bullish", score=0.8,
            price_at_flag=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            horizon_days=5,
        )
        # Backdate scanned_at so the horizon has passed.
        OpportunityFlag.objects.filter(id=flag.id).update(
            scanned_at=timezone.now() - timedelta(days=10)
        )

        result = resolve_pending_flags()
        self.assertEqual(result["hit"], 1)
        flag.refresh_from_db()
        self.assertEqual(flag.outcome, "hit")
        self.assertIsNotNone(flag.resolved_at)

    def test_miss_outcome_when_stop_breached(self):
        from signals.models import OpportunitySetup, OpportunityFlag
        from signals.opportunity_scanner import resolve_pending_flags

        inst = _instrument("RES2", asset_class="stock")
        _seed_prices(inst, [90.0])  # below stop (=95)

        setup = OpportunitySetup.objects.create(
            name="res_test_2", direction="bullish",
            conditions=[], min_match_score=0.0, suggested_horizon_days=5,
            asset_classes=[],
        )
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=inst, direction="bullish", score=0.8,
            price_at_flag=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            horizon_days=5,
        )
        OpportunityFlag.objects.filter(id=flag.id).update(
            scanned_at=timezone.now() - timedelta(days=10)
        )

        result = resolve_pending_flags()
        self.assertEqual(result["miss"], 1)
        flag.refresh_from_db()
        self.assertEqual(flag.outcome, "miss")

    def test_neutral_outcome_when_inside_band(self):
        from signals.models import OpportunitySetup, OpportunityFlag
        from signals.opportunity_scanner import resolve_pending_flags

        inst = _instrument("RES3", asset_class="stock")
        _seed_prices(inst, [102.0])  # inside [95, 110]

        setup = OpportunitySetup.objects.create(
            name="res_test_3", direction="bullish",
            conditions=[], min_match_score=0.0, suggested_horizon_days=5,
            asset_classes=[],
        )
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=inst, direction="bullish", score=0.8,
            price_at_flag=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            horizon_days=5,
        )
        OpportunityFlag.objects.filter(id=flag.id).update(
            scanned_at=timezone.now() - timedelta(days=10)
        )

        result = resolve_pending_flags()
        self.assertEqual(result["neutral"], 1)
        flag.refresh_from_db()
        self.assertEqual(flag.outcome, "neutral")

    def test_skipped_when_horizon_not_yet_passed(self):
        from signals.models import OpportunitySetup, OpportunityFlag
        from signals.opportunity_scanner import resolve_pending_flags

        inst = _instrument("RES4", asset_class="stock")
        _seed_prices(inst, [120.0])

        setup = OpportunitySetup.objects.create(
            name="res_test_4", direction="bullish",
            conditions=[], min_match_score=0.0, suggested_horizon_days=10,
            asset_classes=[],
        )
        # Just-scanned flag; horizon hasn't passed yet.
        OpportunityFlag.objects.create(
            setup=setup, instrument=inst, direction="bullish", score=0.8,
            price_at_flag=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            horizon_days=10,
        )
        result = resolve_pending_flags()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["hit"], 0)
