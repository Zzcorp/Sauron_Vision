"""Tests for the Phase-1.0 self-grading layer in signals.performance.

Run with:  python manage.py test tests.test_performance
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _make_instrument(symbol="EURUSD", asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _make_signal(
    *, symbol="EURUSD", asset_class="forex", direction="bullish",
    entry="100", stop="95", target="110", signal_type="composite",
    urgency="medium", rule_name="rule_a", is_active=True,
):
    """Create an active Signal with sensible defaults."""
    from signals.models import Signal
    inst = _make_instrument(symbol=symbol, asset_class=asset_class)
    return Signal.objects.create(
        instrument=inst,
        signal_type=signal_type,
        direction=direction,
        urgency=urgency,
        title=f"test {symbol} {direction}",
        description="test",
        rule_name=rule_name,
        score=0.7,
        sub_scores={},
        price_at_signal=Decimal(entry),
        suggested_entry=Decimal(entry),
        suggested_stop=Decimal(stop),
        suggested_target=Decimal(target),
        risk_reward_ratio=2.0,
        is_active=is_active,
    )


class ComputeRealizedRTests(TestCase):
    def test_bullish_hit_target_yields_positive_r(self):
        from signals.performance import _compute_realized_r
        sig = _make_signal(direction="bullish", entry="100", stop="95", target="110")
        # Closed at target → (110 - 100) / 5 = 2.0R
        self.assertEqual(_compute_realized_r(sig, Decimal("110")), 2.0)

    def test_bullish_stop_out_yields_minus_one(self):
        from signals.performance import _compute_realized_r
        sig = _make_signal(direction="bullish", entry="100", stop="95")
        self.assertEqual(_compute_realized_r(sig, Decimal("95")), -1.0)

    def test_bearish_hit_target_yields_positive_r(self):
        from signals.performance import _compute_realized_r
        sig = _make_signal(direction="bearish", entry="100", stop="105", target="90")
        # Closed at target → (100 - 90) / 5 = 2.0R
        self.assertEqual(_compute_realized_r(sig, Decimal("90")), 2.0)

    def test_zero_risk_returns_zero(self):
        from signals.performance import _compute_realized_r
        sig = _make_signal(direction="bullish", entry="100", stop="100", target="110")
        self.assertEqual(_compute_realized_r(sig, Decimal("110")), 0.0)


class UpdateExtremesTests(TestCase):
    def test_bullish_tracks_high_as_mfe_low_as_mae(self):
        from signals.performance import _update_extremes
        sig = _make_signal(direction="bullish")
        _update_extremes(sig, Decimal("105"))
        _update_extremes(sig, Decimal("98"))
        _update_extremes(sig, Decimal("103"))
        self.assertEqual(sig.mfe, Decimal("105"))   # peak favorable
        self.assertEqual(sig.mae, Decimal("98"))    # peak adverse

    def test_bearish_tracks_low_as_mfe_high_as_mae(self):
        from signals.performance import _update_extremes
        sig = _make_signal(direction="bearish")
        _update_extremes(sig, Decimal("95"))
        _update_extremes(sig, Decimal("102"))
        _update_extremes(sig, Decimal("97"))
        self.assertEqual(sig.mfe, Decimal("95"))    # peak favorable for bearish
        self.assertEqual(sig.mae, Decimal("102"))   # peak adverse for bearish


class EvaluateSignalOutcomeTests(TestCase):
    def test_hit_target_closes_with_positive_r(self):
        from signals.performance import evaluate_signal_outcome
        sig = _make_signal(direction="bullish", entry="100", stop="95", target="110")
        outcome = evaluate_signal_outcome(sig, current_price=Decimal("110"))
        self.assertEqual(outcome, "hit_target")
        sig.refresh_from_db()
        self.assertFalse(sig.is_active)
        self.assertEqual(sig.outcome, "hit_target")
        self.assertEqual(sig.realized_r, 2.0)
        self.assertIsNotNone(sig.expired_at)
        self.assertIsNotNone(sig.time_to_outcome_seconds)

    def test_stopped_out_closes_with_minus_one_r(self):
        from signals.performance import evaluate_signal_outcome
        sig = _make_signal(direction="bullish", entry="100", stop="95", target="110")
        outcome = evaluate_signal_outcome(sig, current_price=Decimal("94"))
        self.assertEqual(outcome, "stopped_out")
        sig.refresh_from_db()
        self.assertEqual(sig.realized_r, -1.0)

    def test_active_tick_updates_extremes_without_closing(self):
        from signals.performance import evaluate_signal_outcome
        sig = _make_signal(direction="bullish", entry="100", stop="95", target="110")
        outcome = evaluate_signal_outcome(sig, current_price=Decimal("104"))
        self.assertEqual(outcome, "active")
        sig.refresh_from_db()
        self.assertTrue(sig.is_active)
        self.assertEqual(sig.mfe, Decimal("104"))


class CalculateSignalStatsTests(TestCase):
    def setUp(self):
        # 3 closed: 2 hits, 1 stop. All bullish, signal_type=composite.
        for symbol, outcome, r in [
            ("AAA", "hit_target", 2.0),
            ("BBB", "hit_target", 1.5),
            ("CCC", "stopped_out", -1.0),
        ]:
            sig = _make_signal(symbol=symbol, asset_class="forex", signal_type="composite")
            sig.is_active = False
            sig.outcome = outcome
            sig.realized_r = r
            sig.expired_at = timezone.now()
            sig.time_to_outcome_seconds = 3600
            sig.save()
        # 1 closed of a different type
        sig = _make_signal(symbol="DDD", asset_class="crypto", signal_type="technical")
        sig.is_active = False
        sig.outcome = "hit_target"
        sig.realized_r = 1.0
        sig.expired_at = timezone.now()
        sig.time_to_outcome_seconds = 3600
        sig.save()

    def test_overall_stats(self):
        from signals.performance import calculate_signal_stats
        stats = calculate_signal_stats()
        self.assertEqual(stats["n_closed"], 4)
        self.assertEqual(stats["hit_rate"], 0.75)  # 3 hits / 4
        self.assertAlmostEqual(stats["expectancy_r"], (2.0 + 1.5 - 1.0 + 1.0) / 4, places=4)

    def test_group_by_signal_type(self):
        from signals.performance import calculate_signal_stats
        grouped = calculate_signal_stats(group_by="signal_type")
        self.assertIn("composite", grouped)
        self.assertIn("technical", grouped)
        self.assertEqual(grouped["composite"]["n_closed"], 3)
        self.assertEqual(grouped["technical"]["n_closed"], 1)

    def test_group_by_asset_class(self):
        from signals.performance import calculate_signal_stats
        grouped = calculate_signal_stats(group_by="asset_class")
        self.assertEqual(grouped["forex"]["n_closed"], 3)
        self.assertEqual(grouped["crypto"]["n_closed"], 1)

    def test_invalid_group_by_raises(self):
        from signals.performance import calculate_signal_stats
        with self.assertRaises(ValueError):
            calculate_signal_stats(group_by="banana")


class SetupPerformanceSummaryTests(TestCase):
    """The previously-missing function — must return the shape callers expect."""

    def test_empty_when_no_closed_smc_signals(self):
        from signals.performance import setup_performance_summary
        out = setup_performance_summary(days=30)
        self.assertEqual(out, {})

    def test_returns_per_setup_stats(self):
        from signals.models_smc import SmcSignal
        from signals.performance import setup_performance_summary
        # Closed SMC signals: 2 hits, 1 stop on RP_BREAKER
        for r, status in [(2.0, "TARGET_HIT"), (1.5, "TARGET_HIT"), (-1.0, "STOPPED")]:
            SmcSignal.objects.create(
                symbol="BTCUSDT", timeframe="4h", setup="RP_BREAKER",
                direction="LONG", headline="t", thesis="t", invalidation="t",
                entry=100, stop=95, target=110, r_multiple=2,
                status=status, closed_at=timezone.now(), realized_r=r,
            )
        out = setup_performance_summary(days=30)
        self.assertIn("RP_BREAKER", out)
        self.assertEqual(out["RP_BREAKER"]["n_closed"], 3)
        self.assertAlmostEqual(out["RP_BREAKER"]["hit_rate"], 2 / 3, places=4)
        self.assertAlmostEqual(out["RP_BREAKER"]["expectancy_r"], (2.0 + 1.5 - 1.0) / 3, places=4)
        # All required keys present (matches template + caller expectations)
        self.assertEqual(
            set(out["RP_BREAKER"].keys()),
            {"n_closed", "hit_rate", "expectancy_r", "is_empirical"},
        )


class DecayFlagTests(TestCase):
    def _close(self, sig, r, outcome, days_ago):
        sig.is_active = False
        sig.outcome = outcome
        sig.realized_r = r
        sig.expired_at = timezone.now() - timedelta(days=days_ago)
        sig.time_to_outcome_seconds = 3600
        sig.save()

    def test_decay_detected_when_recent_below_baseline_ratio(self):
        from signals.performance import decay_flag
        # Baseline (days 50–80 ago): 5 hits @ 2R each → expectancy = +2.0R, n=5
        for i in range(5):
            sig = _make_signal(symbol=f"OLD{i}", rule_name="decaying_rule")
            self._close(sig, 2.0, "hit_target", days_ago=50 + i * 5)
        # Recent (last 14d): 5 stops → expectancy = -1.0R, n=5
        for i in range(5):
            sig = _make_signal(symbol=f"NEW{i}", rule_name="decaying_rule")
            self._close(sig, -1.0, "stopped_out", days_ago=i + 1)
        flag = decay_flag("decaying_rule")
        self.assertTrue(flag["is_decaying"])
        self.assertEqual(flag["recent_n"], 5)
        self.assertGreaterEqual(flag["baseline_n"], 5)

    def test_no_decay_when_consistent_performance(self):
        from signals.performance import decay_flag
        # 10 hits at +2R spread across the window
        for i in range(10):
            sig = _make_signal(symbol=f"S{i}", rule_name="solid_rule")
            self._close(sig, 2.0, "hit_target", days_ago=i + 1)
        flag = decay_flag("solid_rule")
        self.assertFalse(flag["is_decaying"])
