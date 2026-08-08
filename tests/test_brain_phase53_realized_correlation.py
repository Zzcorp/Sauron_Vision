"""Tests for Phase 53 — realized-return correlation detector.

Covers:
  - _pearson: known correlations, edge cases (zero variance, length mismatch, n<2)
  - _daily_realized_r_series: aggregates trades closed on same date; respects lookback
  - detect_realized_return_correlation:
      - high correlation (parallel returns) emits anomaly
      - low correlation (uncorrelated) skipped
      - insufficient overlap days skipped
      - inactive rules ignored
      - rules with no realized_r data skipped
  - Integration: detector registered in anomaly_scanner.DETECTORS
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="rcorr_t"):
    return User.objects.create_user(username=name, password="x")


def _bot_config(user, name="rcfg"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name,
        enabled=True, mode="paper", symbols=["X"],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )


def _closed_trade(cfg, *, rule_name, realized_r, days_ago):
    """Create a closed AssetBotTrade with closed_at = N days ago."""
    from bot_program.models import AssetBotTrade
    closed = timezone.now() - timedelta(days=days_ago)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="X", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("100") + Decimal(str(realized_r)),
        pnl=Decimal(str(realized_r)),
        rule_name=rule_name, paper=True, status="CLOSED",
        outcome="hit_target" if realized_r >= 0 else "stopped_out",
        realized_r=realized_r, duration_minutes=60,
        opened_at=closed - timedelta(hours=1), closed_at=closed,
    )


def _active_rule_control(rule_name):
    from signals.models_control import RuleControl
    return RuleControl.objects.create(
        rule_name=rule_name, status="active",
        weight_multiplier=1.0, allocator_weight=1.0,
        promotion_stage="research", parameters={},
    )


# ── _pearson helper ──────────────────────────────────────────────────────

class PearsonTests(TestCase):
    def test_perfect_positive_correlation(self):
        from brain.correlation_audit import _pearson
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = _pearson(xs, ys)
        self.assertAlmostEqual(r, 1.0, places=4)

    def test_perfect_negative_correlation(self):
        from brain.correlation_audit import _pearson
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [10.0, 8.0, 6.0, 4.0, 2.0]
        r = _pearson(xs, ys)
        self.assertAlmostEqual(r, -1.0, places=4)

    def test_uncorrelated(self):
        from brain.correlation_audit import _pearson
        # Symmetrically uncorrelated pair
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [3.0, 1.0, 4.0, 2.0]
        r = _pearson(xs, ys)
        self.assertIsNotNone(r)
        self.assertLess(abs(r), 0.6)

    def test_zero_variance_returns_none(self):
        from brain.correlation_audit import _pearson
        # ys is constant — undefined.
        self.assertIsNone(_pearson([1, 2, 3], [5, 5, 5]))

    def test_length_mismatch_returns_none(self):
        from brain.correlation_audit import _pearson
        self.assertIsNone(_pearson([1, 2, 3], [1, 2]))

    def test_too_short_returns_none(self):
        from brain.correlation_audit import _pearson
        self.assertIsNone(_pearson([1.0], [1.0]))


# ── _daily_realized_r_series ─────────────────────────────────────────────

class DailySeriesTests(TestCase):
    def test_aggregates_same_day_trades(self):
        from brain.correlation_audit import _daily_realized_r_series
        u = _user()
        cfg = _bot_config(u)
        _closed_trade(cfg, rule_name="x", realized_r=1.0, days_ago=2)
        _closed_trade(cfg, rule_name="x", realized_r=0.5, days_ago=2)
        _closed_trade(cfg, rule_name="x", realized_r=-1.0, days_ago=4)
        s = _daily_realized_r_series("x", lookback_days=10)
        self.assertEqual(len(s), 2)
        # Sum the two same-day trades.
        same_day_total = max(s.values())
        self.assertAlmostEqual(same_day_total, 1.5)

    def test_respects_lookback(self):
        from brain.correlation_audit import _daily_realized_r_series
        u = _user()
        cfg = _bot_config(u)
        _closed_trade(cfg, rule_name="x", realized_r=1.0, days_ago=5)
        _closed_trade(cfg, rule_name="x", realized_r=1.0, days_ago=50)
        s = _daily_realized_r_series("x", lookback_days=14)
        self.assertEqual(len(s), 1)

    def test_excludes_other_rules(self):
        from brain.correlation_audit import _daily_realized_r_series
        u = _user()
        cfg = _bot_config(u)
        _closed_trade(cfg, rule_name="x", realized_r=1.0, days_ago=2)
        _closed_trade(cfg, rule_name="y", realized_r=1.0, days_ago=2)
        s_x = _daily_realized_r_series("x", lookback_days=10)
        self.assertEqual(len(s_x), 1)
        self.assertAlmostEqual(list(s_x.values())[0], 1.0)


# ── detect_realized_return_correlation ───────────────────────────────────

class DetectRealizedReturnCorrelationTests(TestCase):
    def test_parallel_returns_emit_anomaly(self):
        """Two rules with identical daily returns → correlation 1.0."""
        from brain.correlation_audit import detect_realized_return_correlation
        u = _user()
        cfg = _bot_config(u)
        _active_rule_control("twin_a")
        _active_rule_control("twin_b")
        # Same returns on the same days for both rules.
        for d in range(1, 11):
            r = (d % 5) - 2.0  # varies enough to have variance
            _closed_trade(cfg, rule_name="twin_a", realized_r=r, days_ago=d)
            _closed_trade(cfg, rule_name="twin_b", realized_r=r, days_ago=d)
        anoms = detect_realized_return_correlation(
            min_overlap_days=8, threshold=0.7)
        self.assertEqual(len(anoms), 1)
        self.assertGreaterEqual(anoms[0]["correlation"], 0.95)

    def test_uncorrelated_no_anomaly(self):
        from brain.correlation_audit import detect_realized_return_correlation
        u = _user()
        cfg = _bot_config(u)
        _active_rule_control("uncorr_a")
        _active_rule_control("uncorr_b")
        a_returns = [1.0, -2.0, 0.5, -1.5, 2.0, -0.5, 1.5, -1.0, 0.5, -0.5]
        b_returns = [-2.0, 1.0, -1.0, 0.5, -0.5, 2.0, 0.5, 1.0, -1.5, 0.0]
        for i, (ra, rb) in enumerate(zip(a_returns, b_returns), start=1):
            _closed_trade(cfg, rule_name="uncorr_a", realized_r=ra, days_ago=i)
            _closed_trade(cfg, rule_name="uncorr_b", realized_r=rb, days_ago=i)
        anoms = detect_realized_return_correlation(
            min_overlap_days=8, threshold=0.7)
        self.assertEqual(anoms, [])

    def test_insufficient_overlap_days_skipped(self):
        from brain.correlation_audit import detect_realized_return_correlation
        u = _user()
        cfg = _bot_config(u)
        _active_rule_control("short_a")
        _active_rule_control("short_b")
        # Only 5 shared days — below default min_overlap_days=8
        for i in range(1, 6):
            _closed_trade(cfg, rule_name="short_a", realized_r=i * 1.0, days_ago=i)
            _closed_trade(cfg, rule_name="short_b", realized_r=i * 1.0, days_ago=i)
        self.assertEqual(detect_realized_return_correlation(), [])

    def test_inactive_rule_excluded(self):
        from brain.correlation_audit import detect_realized_return_correlation
        from signals.models_control import RuleControl
        u = _user()
        cfg = _bot_config(u)
        _active_rule_control("inact_a")
        # Second rule is paused.
        RuleControl.objects.create(
            rule_name="inact_b", status="paused",
            weight_multiplier=1.0, allocator_weight=1.0,
            promotion_stage="research", parameters={},
        )
        for i in range(1, 11):
            _closed_trade(cfg, rule_name="inact_a", realized_r=i * 1.0, days_ago=i)
            _closed_trade(cfg, rule_name="inact_b", realized_r=i * 1.0, days_ago=i)
        # Only inact_a is active → can't form a pair → empty.
        self.assertEqual(detect_realized_return_correlation(), [])

    def test_no_trades_no_anomaly(self):
        from brain.correlation_audit import detect_realized_return_correlation
        _active_rule_control("dry_a")
        _active_rule_control("dry_b")
        # Active rules but zero trade history → empty series → can't pair.
        self.assertEqual(detect_realized_return_correlation(), [])


# ── Integration: detector registered ─────────────────────────────────────

class IntegrationTests(TestCase):
    def test_detector_in_DETECTORS(self):
        from brain.anomaly_scanner import DETECTORS
        from brain.correlation_audit import detect_realized_return_correlation
        self.assertIn(detect_realized_return_correlation, DETECTORS)

    def test_scan_anomalies_now_picks_up_correlation(self):
        from brain.anomaly_scanner import scan_anomalies_now
        from brain.models import BrainObservation
        u = _user()
        cfg = _bot_config(u)
        _active_rule_control("scan_corr_a")
        _active_rule_control("scan_corr_b")
        for d in range(1, 11):
            r = (d % 5) - 2.0
            _closed_trade(cfg, rule_name="scan_corr_a",
                            realized_r=r, days_ago=d)
            _closed_trade(cfg, rule_name="scan_corr_b",
                            realized_r=r, days_ago=d)
        result = scan_anomalies_now()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(
            result["by_detector"].get("detect_realized_return_correlation", 0),
            1)
        self.assertTrue(any(
            (obs.payload or {}).get("detector") == "realized_return_correlation"
            for obs in BrainObservation.objects.filter(kind="anomaly_detected")))
