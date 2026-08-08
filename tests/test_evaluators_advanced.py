"""Tests for Phase 34-36 advanced evaluators + quant primitives.

Covers:
  - quant_primitives: hurst, garch_lite, cvar, anchored_vwap, bootstrap_quantile,
    rolling_zscore, linear_slope (happy-path + insufficient data)
  - Phase 34 quant evaluators: hurst_regime, garch_vol_forecast, cvar_tail_risk
  - Phase 35 tradecraft: liquidity_sweep, fair_value_gap, order_block,
    session_break, relative_volume, anchored_vwap_break
  - Phase 36 behavioral: news_price_divergence, crowd_extreme, anchoring_zone,
    capitulation_detector, parabolic_exhaustion, fakeout_pattern,
    narrative_consensus, smart_money_divergence
  - Registration: every advanced kind appears in EVALUATOR_REGISTRY
  - Seed command idempotency

Run with:  python manage.py test tests.test_evaluators_advanced
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


# ── Helpers ───────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_bars(instrument, bars: list, end=None, timeframe: str = "1d"):
    """Seed PriceData rows. `bars` is a list of (open, high, low, close, volume) tuples,
    oldest first. End at `end` (defaults to now). Spacing is 1 day if timeframe='1d'
    else 1 hour."""
    from market_data.models import PriceData
    end = end or timezone.now()
    delta = timedelta(days=1) if timeframe == "1d" else timedelta(hours=1)
    rows = []
    for i, b in enumerate(bars):
        o, h, lo, c, v = b
        ts = end - delta * (len(bars) - i)
        rows.append(PriceData(
            instrument=instrument, timeframe=timeframe, timestamp=ts,
            open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(lo)),
            close=Decimal(str(c)), volume=int(v), source="test",
        ))
    PriceData.objects.bulk_create(rows)


def _flat_bars(price: float, n: int, vol: int = 1000):
    return [(price, price, price, price, vol)] * n


# ══════════════════════════════════════════════════════════════════════════
# Quant primitives
# ══════════════════════════════════════════════════════════════════════════

class QuantPrimitivesTests(TestCase):
    def test_hurst_trending(self):
        from signals.quant_primitives import hurst_exponent, hurst_regime_label
        # A clean uptrend → H should be > 0.5
        closes = [100.0 + i * 0.5 for i in range(120)]
        h = hurst_exponent(closes, max_lag=20)
        self.assertIsNotNone(h)
        self.assertGreater(h, 0.5)
        self.assertEqual(hurst_regime_label(h), "trending")

    def test_hurst_insufficient_data(self):
        from signals.quant_primitives import hurst_exponent
        self.assertIsNone(hurst_exponent([1.0, 2.0, 3.0]))

    def test_hurst_label_unknown(self):
        from signals.quant_primitives import hurst_regime_label
        self.assertEqual(hurst_regime_label(None), "unknown")
        self.assertEqual(hurst_regime_label(0.5), "random")

    def test_garch_lite_returns_positive(self):
        from signals.quant_primitives import garch_lite_forecast
        closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(60)]
        sigma = garch_lite_forecast(closes)
        self.assertIsNotNone(sigma)
        self.assertGreater(sigma, 0.0)

    def test_garch_insufficient(self):
        from signals.quant_primitives import garch_lite_forecast
        self.assertIsNone(garch_lite_forecast([1, 2, 3]))

    def test_cvar_tail(self):
        from signals.quant_primitives import cvar
        # Returns with a known tail
        rets = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
        cv = cvar(rets, alpha=0.2)  # worst 20% = 2 values: -5, -4 → mean -4.5
        self.assertAlmostEqual(cv, -4.5, places=4)

    def test_cvar_invalid(self):
        from signals.quant_primitives import cvar
        self.assertIsNone(cvar([], alpha=0.05))
        self.assertIsNone(cvar([1, 2], alpha=0.0))

    def test_anchored_vwap(self):
        from signals.quant_primitives import anchored_vwap
        # 2 bars: typical 100 with vol 100, typical 110 with vol 100
        bars = [
            {"high": 100, "low": 100, "close": 100, "volume": 100},
            {"high": 110, "low": 110, "close": 110, "volume": 100},
        ]
        avwap = anchored_vwap(bars)
        self.assertAlmostEqual(avwap, 105.0)

    def test_anchored_vwap_zero_volume(self):
        from signals.quant_primitives import anchored_vwap
        self.assertIsNone(anchored_vwap([{"high": 1, "low": 1, "close": 1, "volume": 0}]))

    def test_bootstrap_quantile(self):
        from signals.quant_primitives import bootstrap_quantile
        samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        q = bootstrap_quantile(samples, q=0.25, n_resamples=100, rng_seed=42)
        self.assertIsNotNone(q)
        # Lower-quartile of bootstrap means should sit somewhere between 4 and 6.
        self.assertGreater(q, 3.0)
        self.assertLess(q, 7.0)

    def test_rolling_zscore(self):
        from signals.quant_primitives import rolling_zscore
        # 19 values at 1.0, 20th at 2.0 → z huge
        vals = [1.0] * 19 + [2.0]
        # Need len >= window+1 = 21; pad
        z = rolling_zscore(vals + [3.0], window=20)
        self.assertIsNotNone(z)
        self.assertGreater(z, 1.0)

    def test_rolling_zscore_constant(self):
        from signals.quant_primitives import rolling_zscore
        z = rolling_zscore([5.0] * 30, window=20)
        self.assertEqual(z, 0.0)

    def test_linear_slope_rising(self):
        from signals.quant_primitives import linear_slope
        s = linear_slope([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertAlmostEqual(s, 1.0)

    def test_linear_slope_short_input(self):
        from signals.quant_primitives import linear_slope
        self.assertIsNone(linear_slope([1.0, 2.0]))


# ══════════════════════════════════════════════════════════════════════════
# Registration sanity
# ══════════════════════════════════════════════════════════════════════════

class AdvancedRegistrationTests(TestCase):
    def test_all_advanced_kinds_registered(self):
        from signals.opportunity_scanner import has_kind
        from signals.evaluators_advanced import ADVANCED_EVALUATORS
        for kind in ADVANCED_EVALUATORS:
            self.assertTrue(has_kind(kind), f"{kind} not registered")


# ══════════════════════════════════════════════════════════════════════════
# Phase 34 — quant evaluators
# ══════════════════════════════════════════════════════════════════════════

class HurstRegimeTests(TestCase):
    def test_trending_match(self):
        from signals.evaluators_advanced import _eval_hurst_regime
        inst = _instrument("HRT1")
        # Strong uptrend.
        bars = [(p, p, p, p, 1000) for p in [100 + i * 0.4 for i in range(150)]]
        _seed_bars(inst, bars)
        r = _eval_hurst_regime({"regime": "trending", "lookback": 130}, inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_insufficient_data(self):
        from signals.evaluators_advanced import _eval_hurst_regime
        inst = _instrument("HRT2")
        _seed_bars(inst, _flat_bars(100, 5))
        r = _eval_hurst_regime({"regime": "trending"}, inst, timezone.now())
        self.assertFalse(r["matched"])


class GarchVolForecastTests(TestCase):
    def test_above_threshold_match(self):
        from signals.evaluators_advanced import _eval_garch_vol_forecast
        inst = _instrument("GVF1")
        # High-vol series.
        seq = [100.0]
        for i in range(120):
            seq.append(seq[-1] * (1 + (0.02 if i % 2 == 0 else -0.02)))
        bars = [(p, p, p, p, 1000) for p in seq]
        _seed_bars(inst, bars)
        r = _eval_garch_vol_forecast({"direction": "above", "threshold_pct": 0.5}, inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_below_threshold_match(self):
        from signals.evaluators_advanced import _eval_garch_vol_forecast
        inst = _instrument("GVF2")
        # Constant series → near-zero vol.
        bars = _flat_bars(100, 100)
        _seed_bars(inst, bars)
        r = _eval_garch_vol_forecast({"direction": "below", "threshold_pct": 0.5,
                                       "lookback": 100}, inst, timezone.now())
        self.assertTrue(r["matched"])


class CvarTailRiskTests(TestCase):
    def test_worse_than_match(self):
        from signals.evaluators_advanced import _eval_cvar_tail_risk
        inst = _instrument("CVR1")
        # Multiple sharp drops so the worst-α tail averages well below threshold.
        seq = [100.0] * 20 + [90.0, 100.0, 88.0, 100.0, 92.0, 100.0] + [100.0] * 80
        bars = [(p, p, p, p, 1000) for p in seq]
        _seed_bars(inst, bars)
        r = _eval_cvar_tail_risk({"direction": "worse_than", "threshold_pct": -3.0,
                                   "alpha": 0.05, "lookback": 110}, inst, timezone.now())
        self.assertTrue(r["matched"])
        self.assertLess(r["details"]["cvar_pct"], -3.0)


# ══════════════════════════════════════════════════════════════════════════
# Phase 35 — tradecraft evaluators
# ══════════════════════════════════════════════════════════════════════════

class LiquiditySweepTests(TestCase):
    def test_bullish_sweep_match(self):
        from signals.evaluators_advanced import _eval_liquidity_sweep
        inst = _instrument("LS1")
        # 20 prior bars with low=95; last bar wicks to 90 then closes 99.
        prior = [(96, 97, 95, 96, 1000)] * 20
        last = (96, 100, 90, 99, 1000)  # wick took out the 95 swing low
        _seed_bars(inst, prior + [last])
        r = _eval_liquidity_sweep({"direction": "bullish_sweep", "lookback": 20,
                                    "wick_pct": 0.3}, inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_no_sweep_no_match(self):
        from signals.evaluators_advanced import _eval_liquidity_sweep
        inst = _instrument("LS2")
        bars = [(96, 97, 95, 96, 1000)] * 21
        _seed_bars(inst, bars)
        r = _eval_liquidity_sweep({"direction": "bullish_sweep"}, inst, timezone.now())
        self.assertFalse(r["matched"])


class FairValueGapTests(TestCase):
    def test_bullish_fvg_match(self):
        from signals.evaluators_advanced import _eval_fair_value_gap
        inst = _instrument("FVG1")
        # 5 leading flat bars, then 3-bar bullish FVG: bar[-3].high < bar[-1].low
        flat = _flat_bars(100, 5)
        triple = [
            (100, 101, 99, 100, 1000),   # bar -3
            (102, 110, 102, 109, 2000),  # bar -2 (impulse)
            (109, 112, 105, 111, 1500),  # bar -1; low 105 > 101
        ]
        _seed_bars(inst, flat + triple)
        r = _eval_fair_value_gap({"direction": "bullish", "max_age": 5}, inst, timezone.now())
        self.assertTrue(r["matched"])
        self.assertGreater(r["details"]["gap_size"], 0)

    def test_no_fvg_when_overlap(self):
        from signals.evaluators_advanced import _eval_fair_value_gap
        inst = _instrument("FVG2")
        bars = [(100, 102, 99, 101, 1000)] * 8
        _seed_bars(inst, bars)
        r = _eval_fair_value_gap({"direction": "bullish"}, inst, timezone.now())
        self.assertFalse(r["matched"])


class OrderBlockTests(TestCase):
    def test_bullish_order_block_match(self):
        from signals.evaluators_advanced import _eval_order_block
        inst = _instrument("OB1")
        # Build: padding flat → red candle → strong impulse up → return to block.
        pad = _flat_bars(100, 25)
        red = (100, 100.5, 99, 99.2, 1000)            # red OB candle
        impulse = [(99.5, 105, 99.5, 104, 2000),
                   (104, 106, 103, 105.5, 2000),
                   (105.5, 107, 105, 106, 2000)]
        # Then drift back to ~99.5 (close to OB body)
        retrace = [(106, 106.5, 99.4, 99.5, 1500)]
        _seed_bars(inst, pad + [red] + impulse + retrace)
        r = _eval_order_block({"direction": "bullish", "lookback": 30,
                                "impulse_window": 3, "min_impulse_pct": 1.5,
                                "proximity_pct": 2.0}, inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_no_order_block_no_impulse(self):
        from signals.evaluators_advanced import _eval_order_block
        inst = _instrument("OB2")
        bars = _flat_bars(100, 40)
        _seed_bars(inst, bars)
        r = _eval_order_block({"direction": "bullish"}, inst, timezone.now())
        self.assertFalse(r["matched"])


class SessionBreakTests(TestCase):
    def test_break_above_match(self):
        from signals.evaluators_advanced import _eval_session_break
        inst = _instrument("SB1")
        # 8 hours of price 100..101 then a bar with close 105.
        bars = [(100, 101, 100, 100.5, 1000)] * 8 + [(101, 106, 101, 105, 2000)]
        _seed_bars(inst, bars, timeframe="1h")
        r = _eval_session_break({"range_hours": 8, "timeframe": "1h",
                                  "direction": "above"}, inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_no_break(self):
        from signals.evaluators_advanced import _eval_session_break
        inst = _instrument("SB2")
        bars = [(100, 101, 100, 100.5, 1000)] * 9
        _seed_bars(inst, bars, timeframe="1h")
        r = _eval_session_break({"range_hours": 8, "timeframe": "1h",
                                  "direction": "above"}, inst, timezone.now())
        self.assertFalse(r["matched"])


class RelativeVolumeTests(TestCase):
    def test_match_high_vol(self):
        from signals.evaluators_advanced import _eval_relative_volume
        inst = _instrument("RV1")
        bars = [(100, 100, 100, 100, 1000)] * 20 + [(100, 100, 100, 100, 5000)]
        _seed_bars(inst, bars)
        r = _eval_relative_volume({"period": 20, "threshold": 2.0}, inst, timezone.now())
        self.assertTrue(r["matched"])
        self.assertGreater(r["details"]["ratio"], 2.0)

    def test_no_match_normal_vol(self):
        from signals.evaluators_advanced import _eval_relative_volume
        inst = _instrument("RV2")
        bars = [(100, 100, 100, 100, 1000)] * 20 + [(100, 100, 100, 100, 1100)]
        _seed_bars(inst, bars)
        r = _eval_relative_volume({"period": 20, "threshold": 2.0}, inst, timezone.now())
        self.assertFalse(r["matched"])


class AnchoredVwapBreakTests(TestCase):
    def test_above_match(self):
        from signals.evaluators_advanced import _eval_anchored_vwap_break
        inst = _instrument("AVB1")
        # 30 days at 100 (vol 1000 each), last close 110.
        bars = [(100, 100, 100, 100, 1000)] * 30 + [(100, 110, 100, 110, 1000)]
        _seed_bars(inst, bars)
        r = _eval_anchored_vwap_break({"anchor_days_ago": 30, "direction": "above"},
                                       inst, timezone.now())
        self.assertTrue(r["matched"])


# ══════════════════════════════════════════════════════════════════════════
# Phase 36 — behavioral evaluators
# ══════════════════════════════════════════════════════════════════════════

class NewsPriceDivergenceTests(TestCase):
    def test_bullish_news_bearish_price_match(self):
        from signals.evaluators_advanced import _eval_news_price_divergence
        from scraping.models import NewsArticle
        inst = _instrument("NPD1")
        # Flat-to-down price.
        bars = [(100, 100, 100, 100, 1000)] * 4
        _seed_bars(inst, bars)
        # Bullish news.
        for i in range(5):
            NewsArticle.objects.create(
                title=f"{inst.symbol} earnings beat {i}",
                source="test", url=f"http://example.com/{inst.symbol}/{i}",
                published_at=timezone.now() - timedelta(hours=i + 1),
                content_summary=f"Great news for {inst.symbol}",
                ai_sentiment_score=0.6,
            )
        r = _eval_news_price_divergence({"sentiment_dir": "bullish_news_bearish_price",
                                          "lookback_days": 2, "min_articles": 3,
                                          "min_sentiment": 0.3,
                                          "max_price_move_pct": 0.5}, inst, timezone.now())
        self.assertTrue(r["matched"])


class CrowdExtremeTests(TestCase):
    def test_euphoric_match(self):
        from signals.evaluators_advanced import _eval_crowd_extreme
        from scraping.models import SentimentSnapshot
        inst = _instrument("CE1")
        base = timezone.now() - timedelta(days=40)
        # 30 baseline near 0.0 + last 5 spike to 1.5
        for i in range(30):
            SentimentSnapshot.objects.create(
                instrument=inst, source="reddit",
                composite_score=0.0, volume=10,
                timestamp=base + timedelta(hours=i),
            )
        for i in range(5):
            SentimentSnapshot.objects.create(
                instrument=inst, source="reddit",
                composite_score=1.5, volume=10,
                timestamp=timezone.now() - timedelta(minutes=10 - i),
            )
        r = _eval_crowd_extreme({"direction": "euphoric", "z_threshold": 1.0,
                                  "window": 30, "lookback_days": 60},
                                 inst, timezone.now())
        self.assertTrue(r["matched"])


class AnchoringZoneTests(TestCase):
    def test_round_number_match(self):
        from signals.evaluators_advanced import _eval_anchoring_zone
        inst = _instrument("AZ1")
        # Last close at 100.2 → near round 100 (within 0.5%).
        bars = _flat_bars(99, 5) + [(99, 101, 99, 100.2, 1000)]
        _seed_bars(inst, bars)
        r = _eval_anchoring_zone({"mode": "round_number", "proximity_pct": 0.5},
                                  inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_prior_swing_high_match(self):
        from signals.evaluators_advanced import _eval_anchoring_zone
        inst = _instrument("AZ2")
        # Prior swing high = 105, last close = 105.1 (within 0.5%).
        bars = [(100, 100, 100, 100, 1000)] * 20
        bars.append((100, 105, 100, 102, 1000))  # swing
        bars.extend([(102, 102, 100, 101, 1000)] * 5)
        bars.append((101, 105.5, 101, 105.1, 1000))
        _seed_bars(inst, bars)
        r = _eval_anchoring_zone({"mode": "prior_swing_high", "proximity_pct": 0.5,
                                   "lookback": 30}, inst, timezone.now())
        self.assertTrue(r["matched"])


class CapitulationDetectorTests(TestCase):
    def test_capitulation_match(self):
        from signals.evaluators_advanced import _eval_capitulation_detector
        inst = _instrument("CAP1")
        # 25 calm bars, 5 declining bars 100 → 92, then a HUGE red volume spike 92 → 85.
        baseline = [(100, 100.5, 99.5, 100, 1000)] * 25
        decline = [(100, 100, 98, 98, 1100),
                   (98, 98.5, 96, 96, 1200),
                   (96, 96.5, 94, 94, 1100),
                   (94, 94.5, 93, 93, 1200),
                   (93, 93.5, 92, 92, 1300)]
        cap = (92, 92, 84, 85, 5000)  # 7-pt body, vs avg ~0.5 body
        _seed_bars(inst, baseline + decline + [cap])
        r = _eval_capitulation_detector({"decline_bars": 5, "decline_min_pct": 5.0,
                                          "body_z": 2.0, "vol_multiplier": 1.8,
                                          "window": 20}, inst, timezone.now())
        self.assertTrue(r["matched"])


class ParabolicExhaustionTests(TestCase):
    def test_exhaustion_up_match(self):
        from signals.evaluators_advanced import _eval_parabolic_exhaustion
        inst = _instrument("PE1")
        # 5 calm bars + 3 accelerating bullish candles.
        calm = _flat_bars(100, 5)
        accel = [(100, 102, 100, 101.5, 1000),    # body 1.5
                 (101.5, 105, 101.5, 104.5, 1000),  # body 3.0
                 (104.5, 110, 104.5, 109.5, 1000)]  # body 5.0
        _seed_bars(inst, calm + accel)
        r = _eval_parabolic_exhaustion({"direction": "exhaustion_up",
                                          "min_consecutive": 3}, inst, timezone.now())
        self.assertTrue(r["matched"])

    def test_no_exhaustion_when_decelerating(self):
        from signals.evaluators_advanced import _eval_parabolic_exhaustion
        inst = _instrument("PE2")
        bars = _flat_bars(100, 5) + [
            (100, 105, 100, 104, 1000),    # body 4
            (104, 107, 104, 106, 1000),    # body 2
            (106, 107, 106, 106.5, 1000),  # body 0.5
        ]
        _seed_bars(inst, bars)
        r = _eval_parabolic_exhaustion({"direction": "exhaustion_up"},
                                        inst, timezone.now())
        self.assertFalse(r["matched"])


class FakeoutPatternTests(TestCase):
    def test_bull_trap_match(self):
        from signals.evaluators_advanced import _eval_fakeout_pattern
        inst = _instrument("FK1")
        # Level high = 105 from prior bars; recovery bar broke to 110, last bar closed 102.
        # Need ≥ lookback + recovery_bars + 1 = 23 bars total.
        level = [(100, 105, 100, 102, 1000)] * 23
        breakout = (102, 110, 102, 108, 1500)  # broke above
        revert = (108, 108, 100, 102, 1500)    # closed back inside
        _seed_bars(inst, level + [breakout, revert])
        r = _eval_fakeout_pattern({"direction": "bull_trap", "lookback": 20,
                                    "recovery_bars": 2}, inst, timezone.now())
        self.assertTrue(r["matched"])


class NarrativeConsensusTests(TestCase):
    def test_narrative_baked_in_match(self):
        from signals.evaluators_advanced import _eval_narrative_consensus
        from scraping.models import NewsArticle
        inst = _instrument("NC1")
        # Tiny price move.
        _seed_bars(inst, _flat_bars(100, 6))
        # Lots of articles.
        for i in range(10):
            NewsArticle.objects.create(
                title=f"Story about {inst.symbol} #{i}",
                source="test", url=f"http://example.com/{inst.symbol}/{i}",
                published_at=timezone.now() - timedelta(hours=i + 1),
                content_summary=f"{inst.symbol} narrative",
            )
        r = _eval_narrative_consensus({"lookback_days": 5, "min_articles": 8,
                                        "max_price_move_pct": 1.5}, inst, timezone.now())
        self.assertTrue(r["matched"])


class SmartMoneyDivergenceTests(TestCase):
    def test_divergence_match_price_up_smart_short(self):
        from signals.evaluators_advanced import _eval_smart_money_divergence
        from scraping.models import COTReport
        inst = _instrument("SMD1")
        # Rising price.
        seq = [100.0 + i * 0.3 for i in range(25)]
        bars = [(p, p, p, p, 1000) for p in seq]
        _seed_bars(inst, bars)
        # COT non-commercials net SHORT (extreme).
        COTReport.objects.create(
            instrument=inst, report_date=timezone.now().date() - timedelta(days=1),
            non_commercial_long=10000, non_commercial_short=30000,
            net_speculative=-20000, commercial_long=0, commercial_short=0,
            open_interest=50000,
        )
        r = _eval_smart_money_divergence({"slope_lookback": 20, "slope_threshold": 0.0001,
                                           "min_ratio": 0.3}, inst, timezone.now())
        self.assertTrue(r["matched"])


# ══════════════════════════════════════════════════════════════════════════
# Seed command idempotency
# ══════════════════════════════════════════════════════════════════════════

class SeedAdvancedStrategiesTests(TestCase):
    def test_seed_creates_setups_and_rules(self):
        from signals.management.commands.seed_advanced_strategies import (
            seed_setups, _setup_definitions,
        )
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl
        r = seed_setups(activate=False)
        n = len(_setup_definitions())
        self.assertEqual(r["created"], n)
        self.assertEqual(r["rules_created"], n)
        self.assertEqual(OpportunitySetup.objects.filter(name__startswith="advanced_").count(), n)
        self.assertEqual(RuleControl.objects.filter(rule_name__startswith="advanced_").count(), n)

    def test_seed_idempotent(self):
        from signals.management.commands.seed_advanced_strategies import seed_setups
        seed_setups(activate=False)
        r2 = seed_setups(activate=True)
        self.assertEqual(r2["created"], 0)
        self.assertGreater(r2["updated"], 0)

    def test_seed_reset(self):
        from signals.management.commands.seed_advanced_strategies import (
            seed_setups, reset_setups,
        )
        from signals.models_opportunity import OpportunitySetup
        seed_setups(activate=False)
        self.assertGreater(OpportunitySetup.objects.filter(name__startswith="advanced_").count(), 0)
        r = reset_setups()
        self.assertGreater(r["setups_deleted"], 0)
        self.assertEqual(OpportunitySetup.objects.filter(name__startswith="advanced_").count(), 0)
