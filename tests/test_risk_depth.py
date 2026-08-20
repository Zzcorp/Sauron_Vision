"""Tests for the Phase-2 risk-depth layer.

Covers:
  - portfolio.correlation — pairwise correlation, edge cases
  - portfolio.kelly_from_history — Kelly inputs from realized signal history
  - portfolio.position_sizing.correlation_aware_scale
  - bot_program.engine.risk — graduated drawdown throttle
  - portfolio.risk_gate — unified evaluate_proposed_trade

Run with:  python manage.py test tests.test_risk_depth
"""
from datetime import timedelta
from decimal import Decimal

import numpy as np
from django.test import TestCase
from django.utils import timezone


# ── shared helpers ──────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_prices(instrument, returns, base_price=100.0):
    """Seed daily PriceData such that simple returns match the given list."""
    from market_data.models import PriceData
    now = timezone.now()
    price = base_price
    rows = []
    for i, r in enumerate(returns):
        next_price = price * (1 + r)
        ts = now - timedelta(days=len(returns) - i)
        rows.append(PriceData(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=Decimal(str(round(price, 6))),
            high=Decimal(str(round(max(price, next_price), 6))),
            low=Decimal(str(round(min(price, next_price), 6))),
            close=Decimal(str(round(next_price, 6))),
            volume=0, source="test",
        ))
        price = next_price
    PriceData.objects.bulk_create(rows)


def _portfolio():
    from portfolio.models import Portfolio
    pf, _ = Portfolio.objects.get_or_create(
        name="test_portfolio",
        defaults={
            "initial_capital": Decimal("10000"),
            "current_value": Decimal("10000"),
            "cash_available": Decimal("10000"),
            "currency": "USD",
            "max_correlation_threshold": 0.7,
        },
    )
    return pf


def _open_position(portfolio, instrument, qty=1, price=100):
    from portfolio.models import Position
    return Position.objects.create(
        portfolio=portfolio, instrument=instrument,
        direction="long", quantity=Decimal(str(qty)),
        entry_price=Decimal(str(price)), current_price=Decimal(str(price)),
        opened_at=timezone.now(),
    )


# ── correlation ─────────────────────────────────────────────────────────────

class CorrelationTests(TestCase):
    def test_perfectly_correlated_returns(self):
        from portfolio.correlation import compute_correlation
        rng = np.random.RandomState(42)
        rs = list(rng.normal(0, 0.01, 60))
        a = _instrument("AAA")
        b = _instrument("BBB")
        _seed_prices(a, rs)
        _seed_prices(b, rs)  # identical returns → corr ≈ 1
        cm = compute_correlation([a, b])
        self.assertAlmostEqual(cm.get("AAA", "BBB"), 1.0, places=2)

    def test_anti_correlated_returns(self):
        from portfolio.correlation import compute_correlation
        rng = np.random.RandomState(7)
        rs = list(rng.normal(0, 0.01, 60))
        a = _instrument("AAA2")
        b = _instrument("BBB2")
        _seed_prices(a, rs)
        _seed_prices(b, [-r for r in rs])
        cm = compute_correlation([a, b])
        self.assertAlmostEqual(cm.get("AAA2", "BBB2"), -1.0, places=2)

    def test_missing_history_listed_as_missing(self):
        from portfolio.correlation import compute_correlation
        a = _instrument("HASDATA")
        b = _instrument("NODATA")
        rng = np.random.RandomState(1)
        _seed_prices(a, list(rng.normal(0, 0.01, 60)))
        # b has no PriceData
        cm = compute_correlation([a, b])
        self.assertIn("NODATA", cm.missing)
        self.assertNotIn("NODATA", cm.symbols)

    def test_max_correlation_to_open_book_picks_largest_abs(self):
        from portfolio.correlation import max_correlation_to_open_book
        pf = _portfolio()
        rng = np.random.RandomState(11)
        a = _instrument("CAND")
        b = _instrument("OPEN1")
        c = _instrument("OPEN2")
        rs = list(rng.normal(0, 0.01, 60))
        _seed_prices(a, rs)
        _seed_prices(b, rs)            # corr ≈ 1.0 with a
        _seed_prices(c, [r * 0.1 for r in rs])  # weak corr with a
        _open_position(pf, b)
        _open_position(pf, c)
        corr, peer = max_correlation_to_open_book(pf, a)
        self.assertEqual(peer, "OPEN1")
        self.assertGreater(abs(corr), 0.9)


# ── correlation_aware_scale ─────────────────────────────────────────────────

class CorrelationAwareSizingTests(TestCase):
    def test_no_open_positions_returns_unit_scale(self):
        from portfolio.position_sizing import PositionSizer
        pf = _portfolio()
        cand = _instrument("LONELY")
        result = PositionSizer(pf).correlation_aware_scale(cand)
        self.assertEqual(result["scale"], 1.0)
        self.assertIsNone(result["max_corr"])

    def test_high_correlation_scales_down(self):
        from portfolio.position_sizing import PositionSizer
        pf = _portfolio()
        rng = np.random.RandomState(5)
        rs = list(rng.normal(0, 0.01, 60))
        cand = _instrument("CAND_HIGH")
        peer = _instrument("PEER_HIGH")
        _seed_prices(cand, rs)
        _seed_prices(peer, rs)  # corr ≈ 1
        _open_position(pf, peer)
        result = PositionSizer(pf).correlation_aware_scale(cand)
        self.assertLess(result["scale"], 1.0)
        self.assertGreaterEqual(result["scale"], 0.25)

    def test_low_correlation_keeps_full_size(self):
        from portfolio.position_sizing import PositionSizer
        pf = _portfolio()
        rng = np.random.RandomState(3)
        cand = _instrument("CAND_LOW")
        peer = _instrument("PEER_LOW")
        _seed_prices(cand, list(rng.normal(0, 0.01, 60)))
        _seed_prices(peer, list(np.random.RandomState(99).normal(0, 0.01, 60)))
        _open_position(pf, peer)
        result = PositionSizer(pf).correlation_aware_scale(cand)
        # Random series — likely below threshold; scale = 1.0
        if abs(result["max_corr"]) <= 0.7:
            self.assertEqual(result["scale"], 1.0)


# ── kelly_from_history ──────────────────────────────────────────────────────

class KellyFromHistoryTests(TestCase):
    def _close(self, sig, r):
        sig.is_active = False
        sig.outcome = "hit_target" if r > 0 else "stopped_out"
        sig.realized_r = r
        sig.expired_at = timezone.now()
        sig.save()

    def _make_signal(self, rule_name="rule_kelly"):
        from signals.models import Signal
        inst = _instrument("KELLY1", asset_class="forex")
        return Signal.objects.create(
            instrument=inst, signal_type="composite",
            direction="bullish", urgency="medium",
            title="t", description="t", rule_name=rule_name,
            score=0.7, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            risk_reward_ratio=2.0,
        )

    def test_fallback_below_min_sample(self):
        from portfolio.kelly_from_history import kelly_inputs_for_rule
        # Only 5 closed signals — below MIN_KELLY_SAMPLE=10
        for r in [2, 2, 2, -1, -1]:
            self._close(self._make_signal("kelly_few"), r)
        out = kelly_inputs_for_rule("kelly_few")
        self.assertFalse(out["is_empirical"])
        self.assertEqual(out["n"], 5)

    def test_empirical_inputs_match_realized(self):
        from portfolio.kelly_from_history import kelly_inputs_for_rule
        # 12 signals: 8 wins @ +2R, 4 losses @ -1R
        for _ in range(8):
            self._close(self._make_signal("kelly_real"), 2.0)
        for _ in range(4):
            self._close(self._make_signal("kelly_real"), -1.0)
        out = kelly_inputs_for_rule("kelly_real")
        self.assertTrue(out["is_empirical"])
        self.assertEqual(out["n"], 12)
        self.assertAlmostEqual(out["win_rate"], 8 / 12, places=4)
        self.assertAlmostEqual(out["avg_win_pct"], 2.0, places=4)
        self.assertAlmostEqual(out["avg_loss_pct"], 1.0, places=4)


# ── drawdown throttle ───────────────────────────────────────────────────────

class DrawdownThrottleTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from bot_program.models import BotConfig
        self.user = User.objects.create_user(username="rmuser", password="x")
        self.cfg = BotConfig.objects.create(
            user=self.user, capital_usdt=Decimal("1000"),
            max_daily_loss_pct=3.0, max_concurrent_positions=4,
            position_size_pct=10.0, leverage=1.0, halt_on_drawdown=True,
        )

    def _record_loss(self, usdt):
        """Record a CLOSED BotTrade with the given (negative) P&L."""
        from bot_program.models import BotTrade
        BotTrade.objects.create(
            config=self.cfg, symbol="BTCUSDT", side="BUY",
            qty=Decimal("0.001"), entry_price=Decimal("100"), exit_price=Decimal("99"),
            status="CLOSED", pnl_usdt=Decimal(str(usdt)), closed_at=timezone.now(),
            paper=True,
        )

    def test_no_loss_full_scale(self):
        from bot_program.engine.risk import RiskManager
        rm = RiskManager(self.cfg)
        self.assertEqual(rm.drawdown_fraction(), 0.0)
        self.assertEqual(rm.drawdown_scale(), 1.0)

    def test_below_floor_full_scale(self):
        # 20% of the 30 USDT limit = 6 USDT loss → below FLOOR_FRAC=0.25
        from bot_program.engine.risk import RiskManager
        self._record_loss(-6)
        rm = RiskManager(self.cfg)
        self.assertEqual(rm.drawdown_scale(), 1.0)

    def test_mid_drawdown_scales_down(self):
        # 60% of limit = 18 USDT loss
        from bot_program.engine.risk import RiskManager
        self._record_loss(-18)
        rm = RiskManager(self.cfg)
        scale = rm.drawdown_scale()
        self.assertLess(scale, 1.0)
        self.assertGreater(scale, 0.1)

    def test_at_limit_scale_at_floor(self):
        # 100% of limit = 30 USDT loss
        from bot_program.engine.risk import RiskManager
        self._record_loss(-30)
        rm = RiskManager(self.cfg)
        # binary halt also triggers
        ok, _ = rm.can_open_new()
        self.assertFalse(ok)
        # And the throttle floor is the minimum
        self.assertAlmostEqual(rm.drawdown_scale(), 0.10, places=4)

    def test_position_size_applies_scale(self):
        from bot_program.engine.risk import RiskManager
        # Baseline: no drawdown → cap × pct × leverage / price
        rm = RiskManager(self.cfg)
        baseline = rm.position_size(price=100.0)
        self._record_loss(-18)  # mid drawdown
        rm = RiskManager(self.cfg)
        throttled = rm.position_size(price=100.0)
        self.assertLess(throttled, baseline)


# ── unified risk gate ───────────────────────────────────────────────────────

class RiskGateTests(TestCase):
    def test_oversize_intended_capped_to_position_max(self):
        """The ceiling is derived, not typed.

        This asserted a literal 1,000 — 10% of a 10,000 book — and broke the
        day the shipped `max_single_position_pct` moved to agree with the
        sizing engine. What the gate promises is "cap to the configured
        percentage", so that is what the test states; the number follows the
        field.
        """
        from portfolio.risk_gate import evaluate_proposed_trade
        pf = _portfolio()
        cand = _instrument("GATE_CAND")
        ceiling = float(pf.current_value) * float(pf.max_single_position_pct) / 100.0
        intended = ceiling * 5
        result = evaluate_proposed_trade(pf, cand, intended_size_usd=intended)
        self.assertTrue(result["checks"]["position_cap"]["over_cap"])
        # approved = capped × scale (scale=1 with no positions/correlation)
        self.assertLessEqual(result["approved_size_usd"], ceiling)

    def test_decay_halves_size_when_rule_decaying(self):
        """Bridge to Phase 1: a decaying rule scales the gate down."""
        from portfolio.risk_gate import evaluate_proposed_trade
        from signals.models import Signal
        pf = _portfolio()
        cand = _instrument("GATE_DECAY")
        # Build a clear decay pattern: 5 baseline wins at +2R (40-80d ago), 5 recent stops at -1R
        for i in range(5):
            sig = Signal.objects.create(
                instrument=cand, signal_type="composite",
                direction="bullish", urgency="medium",
                title="t", description="t", rule_name="decay_in_gate",
                score=0.7, sub_scores={},
                price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
                suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
                risk_reward_ratio=2.0,
            )
            sig.is_active = False
            sig.outcome = "hit_target"
            sig.realized_r = 2.0
            sig.expired_at = timezone.now() - timedelta(days=50 + i * 5)
            sig.save()
        for i in range(5):
            sig = Signal.objects.create(
                instrument=cand, signal_type="composite",
                direction="bullish", urgency="medium",
                title="t", description="t", rule_name="decay_in_gate",
                score=0.7, sub_scores={},
                price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
                suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
                risk_reward_ratio=2.0,
            )
            sig.is_active = False
            sig.outcome = "stopped_out"
            sig.realized_r = -1.0
            sig.expired_at = timezone.now() - timedelta(days=i + 1)
            sig.save()
        result = evaluate_proposed_trade(pf, cand, intended_size_usd=500, rule_name="decay_in_gate")
        self.assertIn("decay", result["checks"])
        self.assertTrue(result["checks"]["decay"]["is_decaying"])
        self.assertLessEqual(result["scale"], 0.5)
