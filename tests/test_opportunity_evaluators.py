"""Tests for the Phase-10 evaluator additions: macro_regime, sentiment_snapshot,
cot_report, options_flow, volatility_regime, correlation_pair.

Each evaluator has at least one matched case + one non-matched case.

Run with:  python manage.py test tests.test_opportunity_evaluators
"""
import math
import statistics
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_prices(instrument, closes, end=None):
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


# ── macro_regime ────────────────────────────────────────────────────────────

def _seed_macro(series_id, value, name="x", category="x", when=None):
    """An indicator plus the observation the FRED ingest writes alongside it.

    macro_regime reads the observation history, not the mutable `last_value`
    column, so that an as-of scan gets the value that was published by `now`
    rather than the one sitting in the row today. A fixture that sets only
    `last_value` describes a series with no history — see
    tests/test_seed_param_integrity.py for that case.
    """
    from market_data.models import MacroIndicator, MacroObservation
    when = when or date.today()
    indicator = MacroIndicator.objects.create(
        series_id=series_id, name=name, category=category, frequency="d",
        last_value=Decimal(str(value)), last_date=when,
    )
    MacroObservation.objects.create(
        indicator=indicator, date=when, value=Decimal(str(value)))
    return indicator


class MacroRegimeTests(TestCase):
    def test_above_threshold_matches(self):
        from signals.opportunity_scanner import _eval_macro_regime
        _seed_macro("DGS10", "4.50", name="10Y", category="rate")
        inst = _instrument("MR1")
        result = _eval_macro_regime(
            {"series_id": "DGS10", "direction": "above", "threshold": 4.0},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["details"]["value"], 4.5)

    def test_below_threshold_matches(self):
        from signals.opportunity_scanner import _eval_macro_regime
        _seed_macro("VIXCLS", "12", name="VIX", category="vol")
        inst = _instrument("MR2")
        result = _eval_macro_regime(
            {"series_id": "VIXCLS", "direction": "below", "threshold": 20.0},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])

    def test_missing_indicator_no_match(self):
        from signals.opportunity_scanner import _eval_macro_regime
        inst = _instrument("MR3")
        result = _eval_macro_regime(
            {"series_id": "MISSING", "direction": "above", "threshold": 1.0},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_above_when_value_below_threshold_no_match(self):
        from signals.opportunity_scanner import _eval_macro_regime
        _seed_macro("MR4_S", "3.0")
        result = _eval_macro_regime(
            {"series_id": "MR4_S", "direction": "above", "threshold": 5.0},
            _instrument("MR4"), timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── sentiment_snapshot ─────────────────────────────────────────────────────

class SentimentSnapshotTests(TestCase):
    def test_avg_above_threshold_matches(self):
        from signals.opportunity_scanner import _eval_sentiment_snapshot
        from scraping.models import SentimentSnapshot
        inst = _instrument("SS1")
        for i in range(3):
            SentimentSnapshot.objects.create(
                instrument=inst, source="reddit",
                timestamp=timezone.now() - timedelta(hours=i),
                composite_score=0.6,
            )
        result = _eval_sentiment_snapshot(
            {"direction": "above", "threshold": 0.4, "min_count": 2},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertAlmostEqual(result["details"]["avg_score"], 0.6, places=4)

    def test_below_min_count_no_match(self):
        from signals.opportunity_scanner import _eval_sentiment_snapshot
        from scraping.models import SentimentSnapshot
        inst = _instrument("SS2")
        SentimentSnapshot.objects.create(
            instrument=inst, source="reddit",
            timestamp=timezone.now(), composite_score=0.8,
        )
        result = _eval_sentiment_snapshot(
            {"direction": "above", "threshold": 0.4, "min_count": 3},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_source_filter_excludes_other_sources(self):
        from signals.opportunity_scanner import _eval_sentiment_snapshot
        from scraping.models import SentimentSnapshot
        inst = _instrument("SS3")
        for i in range(3):
            SentimentSnapshot.objects.create(
                instrument=inst, source="stocktwits",
                timestamp=timezone.now() - timedelta(hours=i),
                composite_score=0.9,
            )
        result = _eval_sentiment_snapshot(
            {"direction": "above", "threshold": 0.4, "min_count": 2, "source": "reddit"},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── cot_report ─────────────────────────────────────────────────────────────

class CotReportTests(TestCase):
    def test_long_extreme_matches_when_ratio_high_and_net_positive(self):
        from signals.opportunity_scanner import _eval_cot_report
        from scraping.models import COTReport
        inst = _instrument("XAUUSD", asset_class="commodity")
        COTReport.objects.create(
            instrument=inst, report_date=date.today(),
            commercial_long=10000, commercial_short=10000,
            non_commercial_long=8000, non_commercial_short=2000,
            open_interest=20000, net_speculative=6000,  # ratio = 6000/10000 = 0.6
        )
        result = _eval_cot_report(
            {"direction": "long_extreme", "min_ratio": 0.4},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["details"]["ratio"], 0.6)

    def test_long_extreme_no_match_when_ratio_low(self):
        from signals.opportunity_scanner import _eval_cot_report
        from scraping.models import COTReport
        inst = _instrument("XAGUSD", asset_class="commodity")
        COTReport.objects.create(
            instrument=inst, report_date=date.today(),
            commercial_long=5000, commercial_short=5000,
            non_commercial_long=5500, non_commercial_short=4500,
            open_interest=10000, net_speculative=1000,  # ratio = 0.1
        )
        result = _eval_cot_report(
            {"direction": "long_extreme", "min_ratio": 0.4},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_no_report_no_match(self):
        from signals.opportunity_scanner import _eval_cot_report
        inst = _instrument("WTIUSD", asset_class="commodity")
        result = _eval_cot_report(
            {"direction": "long", "min_ratio": 0.4},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── options_flow ───────────────────────────────────────────────────────────

class OptionsFlowTests(TestCase):
    def test_unusual_bullish_count_matches(self):
        from signals.opportunity_scanner import _eval_options_flow
        from scraping.models import OptionsFlow
        inst = _instrument("OF1")
        for i in range(5):
            OptionsFlow.objects.create(
                instrument=inst,
                timestamp=timezone.now() - timedelta(hours=i),
                contract_type="call", strike=Decimal("100"),
                expiry=date.today() + timedelta(days=30),
                volume=10000, open_interest=2000,
                premium=Decimal("5.00"),
                sentiment="bullish", is_unusual=True, source="test",
            )
        result = _eval_options_flow(
            {"sentiment": "bullish", "is_unusual": True, "min_count": 3,
             "lookback_days": 1},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["details"]["n"], 5)

    def test_filter_non_unusual_excluded(self):
        from signals.opportunity_scanner import _eval_options_flow
        from scraping.models import OptionsFlow
        inst = _instrument("OF2")
        # 5 normal flows but only 1 unusual
        for i in range(4):
            OptionsFlow.objects.create(
                instrument=inst, timestamp=timezone.now() - timedelta(hours=i),
                contract_type="call", strike=Decimal("100"),
                expiry=date.today() + timedelta(days=30),
                volume=100, open_interest=2000, premium=Decimal("5"),
                sentiment="bullish", is_unusual=False, source="test",
            )
        OptionsFlow.objects.create(
            instrument=inst, timestamp=timezone.now(),
            contract_type="call", strike=Decimal("100"),
            expiry=date.today() + timedelta(days=30),
            volume=10000, open_interest=2000, premium=Decimal("5"),
            sentiment="bullish", is_unusual=True, source="test",
        )
        result = _eval_options_flow(
            {"sentiment": "bullish", "is_unusual": True, "min_count": 3},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])  # only 1 unusual flow, below 3


# ── volatility_regime ──────────────────────────────────────────────────────

class VolatilityRegimeTests(TestCase):
    def test_high_volatility_above_threshold_matches(self):
        from signals.opportunity_scanner import _eval_volatility_regime
        # 25 closes with ~3% daily moves
        rng = [100.0]
        for i in range(25):
            rng.append(rng[-1] * (1 + (-0.03 if i % 2 else 0.03)))
        inst = _instrument("VR1")
        _seed_prices(inst, rng)
        result = _eval_volatility_regime(
            {"period": 20, "direction": "above", "threshold_pct": 1.0},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertGreater(result["details"]["daily_vol_pct"], 1.0)

    def test_low_volatility_below_threshold_matches(self):
        from signals.opportunity_scanner import _eval_volatility_regime
        # 25 closes with ~0.1% daily moves
        rng = [100.0]
        for i in range(25):
            rng.append(rng[-1] * (1 + (-0.001 if i % 2 else 0.001)))
        inst = _instrument("VR2")
        _seed_prices(inst, rng)
        result = _eval_volatility_regime(
            {"period": 20, "direction": "below", "threshold_pct": 1.0},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])

    def test_insufficient_data_no_match(self):
        from signals.opportunity_scanner import _eval_volatility_regime
        inst = _instrument("VR3")
        _seed_prices(inst, [100.0, 101.0])
        result = _eval_volatility_regime(
            {"period": 20, "direction": "above", "threshold_pct": 1.0},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── correlation_pair ───────────────────────────────────────────────────────

class CorrelationPairTests(TestCase):
    def test_high_correlation_above_threshold_matches(self):
        from signals.opportunity_scanner import _eval_correlation_pair
        # Two instruments with identical relative moves → corr = 1.0
        inst_a = _instrument("CP1A")
        inst_b = _instrument("CP1B")
        moves = [100.0]
        for i in range(35):
            moves.append(moves[-1] * (1.005 if i % 2 == 0 else 0.998))
        _seed_prices(inst_a, moves)
        _seed_prices(inst_b, moves)
        result = _eval_correlation_pair(
            {"reference_symbol": "CP1B", "period": 30,
             "direction": "above", "threshold": 0.7},
            inst_a, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertGreater(result["details"]["correlation"], 0.9)

    def test_anti_correlation_below_threshold_matches(self):
        from signals.opportunity_scanner import _eval_correlation_pair
        inst_a = _instrument("CP2A")
        inst_b = _instrument("CP2B")
        moves_a = [100.0]
        moves_b = [100.0]
        for i in range(35):
            moves_a.append(moves_a[-1] * (1.01 if i % 2 == 0 else 0.99))
            moves_b.append(moves_b[-1] * (0.99 if i % 2 == 0 else 1.01))
        _seed_prices(inst_a, moves_a)
        _seed_prices(inst_b, moves_b)
        result = _eval_correlation_pair(
            {"reference_symbol": "CP2B", "period": 30,
             "direction": "below", "threshold": -0.7},
            inst_a, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertLess(result["details"]["correlation"], -0.9)

    def test_missing_reference_no_match(self):
        from signals.opportunity_scanner import _eval_correlation_pair
        inst = _instrument("CP3")
        _seed_prices(inst, [100.0] * 35)
        result = _eval_correlation_pair(
            {"reference_symbol": "GHOST", "period": 30,
             "direction": "above", "threshold": 0.5},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_self_reference_no_match(self):
        from signals.opportunity_scanner import _eval_correlation_pair
        inst = _instrument("CP4")
        _seed_prices(inst, [100.0] * 35)
        result = _eval_correlation_pair(
            {"reference_symbol": "CP4", "period": 30,
             "direction": "above", "threshold": 0.5},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── Registry coverage ──────────────────────────────────────────────────────

class RegistryCoverageTests(TestCase):
    def test_all_six_new_kinds_registered(self):
        from signals.opportunity_scanner import has_kind
        for kind in ("macro_regime", "sentiment_snapshot", "cot_report",
                     "options_flow", "volatility_regime", "correlation_pair"):
            self.assertTrue(has_kind(kind), f"{kind} not registered")
