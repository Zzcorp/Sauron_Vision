"""The short mirrors (2026-10-31): rsi_bear_divergence,
macd_bearish_crossover and death_cross (with its forks), each its own
name, born at research (signals/rule_birth).

What the file pins:
  * each mirror fires exactly where its long twin fires on the REFLECTED
    bars (K - price: the RSI of the reflection is 100 - the RSI, its MACD
    the MACD negated, its SMA K - the SMA), with the same score, on fifty
    prefixes of three seeded random walks — and the long rules are left as
    they were;
  * each fires where the proving ground's family fires short on the same
    bars (the family maps the short to the new name);
  * the levels are the twins' percentages, mirrored (2R);
  * a death cross on an unadjusted forward split is no fire: the rule
    reads its bars through the judge's own bar sanity;
  * each reads its CLOSED bars (closed_frame): a cross on the bar still
    forming is no fire until that bar has closed — the family that judges
    it fires on the close of bar t;
  * the death cross is parameter-aware, its forks run under their own
    names, and the evolution registry holds its schema, evaluator and
    universe.

Run with:  python manage.py test tests.test_bearish_mirrors
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from backtester.proving import families as F


def synth(n=700, seed=1, drift=0.0, start="2023-01-01", freq="4h", px=100.0):
    rng = np.random.default_rng(seed)
    c = px * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c,
                         "volume": 1.0}, index=idx)


def reflect(df):
    """Prices K - p with K = 2 x the highest high + 1: positive, the high
    and the low swapped."""
    k = 2.0 * float(df["high"].max()) + 1.0
    out = df.copy()
    out["open"] = k - df["open"]
    out["high"] = k - df["low"]
    out["low"] = k - df["high"]
    out["close"] = k - df["close"]
    return out


def bars(df):
    """load_ohlcv patched to the frame's newest `bars` rows, as the real
    one reads them."""
    return patch("signals.smc.dataframe.load_ohlcv",
                 side_effect=lambda symbol, timeframe="4h", bars=500,
                 source=None: None if df is None else df.tail(bars))


def inst(symbol="SYN", asset_class="crypto"):
    return SimpleNamespace(symbol=symbol, asset_class=asset_class)


def run(rule, df, instrument=None):
    with bars(df):
        return rule.evaluate(instrument or inst())


SEEDS = (6, 7, 10)
PREFIXES = range(400, 700, 6)          # fifty prefixes


class TheReflectionTests(SimpleTestCase):

    def _pairs(self, long_rule, short_rule):
        fired = 0
        for seed in SEEDS:
            df = synth(700, seed=seed)
            for m in PREFIXES:
                p = df.iloc[:m]
                a = run(long_rule, p)
                b = run(short_rule, reflect(p))
                self.assertEqual(a is None, b is None,
                                 f"seed {seed} m {m}: {a} / {b}")
                if a is None:
                    continue
                fired += 1
                self.assertEqual(b["direction"], "SHORT")
                self.assertAlmostEqual(b["score"], a["score"], places=3)
        return fired

    def test_rsi_bear_divergence_is_the_reflected_twin(self):
        from signals.rules.technical_rules import (RSIBearDivergenceRule,
                                                   RSIDivergenceRule)
        self.assertGreater(self._pairs(RSIDivergenceRule(),
                                       RSIBearDivergenceRule()), 0)

    def test_macd_bearish_crossover_is_the_reflected_twin(self):
        from signals.rules.technical_rules import (MACDBearishCrossoverRule,
                                                   MACDCrossoverRule)
        self.assertGreater(self._pairs(MACDCrossoverRule(),
                                       MACDBearishCrossoverRule()), 0)

    def test_death_cross_is_the_reflected_twin(self):
        from signals.rules.technical_rules import DeathCrossRule, GoldenCrossRule
        fired = 0
        for seed in SEEDS:
            df = synth(700, seed=seed)
            for m in range(320, 700):
                p = df.iloc[:m]
                a = run(GoldenCrossRule(), p)
                b = run(DeathCrossRule(), reflect(p))
                self.assertEqual(a is None, b is None, f"seed {seed} m {m}")
                fired += a is not None
        self.assertGreater(fired, 0)


class TheFamilyParityTests(SimpleTestCase):
    """The rule fires on its last bar iff the family's short fires there,
    on the same bars the rule read."""

    def _parity(self, rule, key, n_bars, step=3):
        fired = 0
        for seed in SEEDS:
            df = reflect(synth(700, seed=seed))
            for m in range(320, 700, step):
                p = df.iloc[:m]
                got = run(rule, p) is not None
                want = bool(F.FAMILIES[key].fires(p.tail(n_bars), F.SHORT)[-1])
                self.assertEqual(got, want, f"{key} seed {seed} m {m}")
                fired += got
        self.assertGreater(fired, 0, key)

    def test_the_families_map_the_short_to_the_new_names(self):
        self.assertEqual(F.FAMILIES["rsi_divergence"].live_rules[F.SHORT],
                         "rsi_bear_divergence")
        self.assertEqual(F.FAMILIES["macd_cross"].live_rules[F.SHORT],
                         "macd_bearish_crossover")
        self.assertEqual(F.FAMILIES["ma_cross"].live_rules[F.SHORT],
                         "death_cross")
        # the long stays the long (backtester.proving.memory.rule_case)
        from backtester.proving.memory import rule_case
        self.assertEqual(rule_case("rsi_bull_divergence")[1], F.LONG)
        self.assertEqual(rule_case("death_cross")[1], F.SHORT)

    def test_rsi(self):
        from signals.rules.technical_rules import RSIBearDivergenceRule
        self._parity(RSIBearDivergenceRule(), "rsi_divergence", 300)

    def test_macd(self):
        from signals.rules.technical_rules import MACDBearishCrossoverRule
        self._parity(MACDBearishCrossoverRule(), "macd_cross", 300)

    def test_death_cross(self):
        from signals.rules.technical_rules import DeathCrossRule
        self._parity(DeathCrossRule(), "ma_cross", 300, step=1)


def _first_fire(rule, df, start=320):
    for m in range(start, len(df) + 1):
        p = df.iloc[:m]
        out = run(rule, p)
        if out is not None:
            return p, out
    return None, None


class TheMirrorWordsTests(SimpleTestCase):

    def test_the_rsi_mirror_s_levels_words_and_quiet_cases(self):
        from signals.rules.technical_rules import (RSI_THRESHOLD, _rsi,
                                                   RSIBearDivergenceRule)
        rule = RSIBearDivergenceRule()
        p, out = None, None
        for seed in SEEDS:
            p, out = _first_fire(rule, reflect(synth(700, seed=seed)), 400)
            if out is not None and \
                    p["high"].iloc[-30:].idxmax() != p.index[-1]:
                break
        self.assertIsNotNone(out)
        close = float(p["close"].iloc[-1])
        self.assertEqual(out["rule"], "rsi_bear_divergence")
        self.assertAlmostEqual(out["stop"], close * 1.015)
        self.assertAlmostEqual(out["target"], close * 0.97)
        self.assertIn("SHORT · RSI bearish divergence", out["headline"])
        self.assertIn("higher high while RSI made a lower high",
                      out["thesis"])
        # fewer than 60 bars
        self.assertIsNone(run(rule, p.tail(59)))
        # a lower high: the prior window's top raised over the recent one
        lower = p.copy()
        prior = lower["high"].iloc[-60:-30].idxmax()
        lower.loc[prior, "high"] = float(lower["high"].iloc[-30:].max()) * 1.01
        self.assertIsNone(run(rule, lower))
        # the same higher high with the RSI under 65: the last close lowered
        weak = p.copy()
        for cut in np.linspace(0.0, 0.08, 81):
            weak.loc[weak.index[-1], "close"] = close * (1 - cut)
            weak.loc[weak.index[-1], "low"] = min(
                float(p["low"].iloc[-1]), close * (1 - cut))
            last = float(_rsi(weak["close"].tail(300)).iloc[-1])
            if last <= 100 - RSI_THRESHOLD:
                break
        self.assertLessEqual(last, 100 - RSI_THRESHOLD)
        self.assertGreater(last, 50)
        self.assertIsNone(run(rule, weak))

    def test_the_macd_mirror_s_levels_and_a_line_already_under(self):
        from signals.rules.technical_rules import MACDBearishCrossoverRule
        rule = MACDBearishCrossoverRule()
        p, out = _first_fire(rule, reflect(synth(700, seed=8)), 300)
        self.assertIsNotNone(out)
        close = float(p["close"].iloc[-1])
        self.assertEqual(out["score"], 0.55)
        self.assertAlmostEqual(out["stop"], close * 1.02)
        self.assertAlmostEqual(out["target"], close * 0.96)
        # the bar after the cross: the line is already under, no new cross
        df = reflect(synth(700, seed=8))
        self.assertIsNone(run(rule, df.iloc[:len(p) + 1]))
        # (a cross under always has a falling histogram: hist goes from
        # >= 0 to < 0, so the "acceleration" clause cannot be the one that
        # is missing; the twin carries the same redundant clause)

    def test_the_death_cross_s_levels_and_degenerate_parameters(self):
        from signals.rules.technical_rules import DeathCrossRule
        p, out = None, None
        for seed in SEEDS:
            p, out = _first_fire(DeathCrossRule(), reflect(synth(700, seed=seed)))
            if out is not None:
                break
        self.assertIsNotNone(out)
        close = float(p["close"].iloc[-1])
        self.assertAlmostEqual(out["stop"], close * 1.05)
        self.assertAlmostEqual(out["target"], close * 0.90)
        self.assertIn("SMA50 crossed under SMA200", out["thesis"])
        for params in ({"fast": 200, "slow": 50}, {"stop_pct": 0},
                       {"target_pct": -0.1}):
            self.assertIsNone(run(DeathCrossRule(params=params), p), params)


def _restamp(df, last_open):
    """`df` moved in time so that its last bar opens at `last_open`."""
    out = df.copy()
    out.index = df.index + (last_open - df.index[-1])
    return out


class TheClosedBarTests(SimpleTestCase):
    """The newest stored 4h bar may still be forming (eToro's newest candle
    is stored while forming; the public feed resamples a partial bin): a
    mirror fires on the close of its last CLOSED bar, as its family does."""

    def _check(self, rule, start, seeds=SEEDS + (8,)):
        for seed in seeds:
            p, out = _first_fire(rule, reflect(synth(700, seed=seed)), start)
            if out is not None and len(p) > start:
                break
        self.assertIsNotNone(out)
        self.assertGreater(len(p), start)
        forming = pd.Timestamp(timezone.now()).floor("4h")
        # the cross on the bar that opened at the current boundary: no fire
        self.assertIsNone(run(rule, _restamp(p, forming)))
        # the same bars one bar older: that bar has closed, the cross holds
        closed = run(rule, _restamp(p, forming - pd.Timedelta(hours=4)))
        self.assertIsNotNone(closed)
        self.assertAlmostEqual(closed["score"], out["score"], places=6)
        self.assertAlmostEqual(closed["entry"], out["entry"], places=6)

    def test_the_rsi_mirror_waits_for_the_close(self):
        from signals.rules.technical_rules import RSIBearDivergenceRule
        self._check(RSIBearDivergenceRule(), 400)

    def test_the_macd_mirror_waits_for_the_close(self):
        from signals.rules.technical_rules import MACDBearishCrossoverRule
        self._check(MACDBearishCrossoverRule(), 300)

    def test_the_death_cross_waits_for_the_close(self):
        from signals.rules.technical_rules import DeathCrossRule
        self._check(DeathCrossRule(), 320)


def _split_stock(n=420, at=400, ratio=10.0):
    """An up-trending stock whose stored bars carry an unadjusted 10:1
    forward split at bar `at`."""
    rng = np.random.default_rng(4)
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.004, n)))
    c[at:] = c[at:] / ratio
    o = np.r_[c[0], c[:-1]]
    o[at] = c[at]
    h = np.maximum(o, c) * 1.002
    lo = np.minimum(o, c) * 0.998
    idx = pd.date_range("2023-01-02", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c,
                         "volume": 1.0}, index=idx)


class TheSplitTests(SimpleTestCase):

    def test_an_unadjusted_split_is_a_death_cross_on_raw_bars_only(self):
        from signals.rules.technical_rules import DeathCrossRule
        df = _split_stock()
        raw = F.FAMILIES["ma_cross"].fires(df, F.SHORT)
        self.assertTrue(raw[400:].any(), "the raw bars cross")
        for m in range(401, len(df) + 1):
            self.assertIsNone(run(DeathCrossRule(), df.iloc[:m],
                                  inst("SPLT", "stock")), m)


class TheForkTests(TestCase):

    def test_a_fork_row_runs_under_its_own_name_and_parameters(self):
        from signals.models import RuleControl
        from signals.rules.technical_rules import _death_cross_family
        RuleControl.objects.create(rule_name="death_cross_evolved_v1",
                                   promotion_stage="research",
                                   parameters={"fast": 20, "slow": 120})
        fam = {r.name: r for r in _death_cross_family()}
        self.assertEqual(set(fam), {"death_cross", "death_cross_evolved_v1"})
        self.assertEqual(fam["death_cross_evolved_v1"].params["fast"], 20)
        self.assertEqual(fam["death_cross_evolved_v1"].params["slow"], 120)
        self.assertEqual(fam["death_cross"].params["slow"], 200)

    def test_the_engine_runs_every_born_name(self):
        from signals.engine import SignalEngine
        from signals.rule_birth import BORN_AT_RESEARCH
        names = {r.name for r in SignalEngine().rules}
        self.assertTrue(BORN_AT_RESEARCH <= names,
                        sorted(BORN_AT_RESEARCH - names))
        for long_rule in ("rsi_bull_divergence", "macd_bullish_crossover",
                          "golden_cross"):
            self.assertIn(long_rule, names)


class TheEvolutionTests(TestCase):

    def test_the_registry_holds_the_death_cross(self):
        from signals.evolution import (SCHEMA_REGISTRY,
                                       _ensure_rules_registered)
        from signals.evolution_backtest import (EVALUATOR_REGISTRY,
                                                UNIVERSE_REGISTRY)
        from signals.evolution_rules import (DEATH_CROSS_SCHEMA,
                                             GOLDEN_CROSS_SCHEMA)
        _ensure_rules_registered()
        self.assertIs(DEATH_CROSS_SCHEMA, GOLDEN_CROSS_SCHEMA)
        self.assertIn("death_cross", SCHEMA_REGISTRY)
        self.assertIn("death_cross", EVALUATOR_REGISTRY)
        self.assertIn("death_cross", UNIVERSE_REGISTRY)
        from signals.promotion_evidence import _evaluator_name
        self.assertEqual(_evaluator_name("death_cross_evolved_v4"),
                         "death_cross")

    def test_the_evaluator_is_paid_on_a_fall_after_the_cross(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        from signals.evolution_rules import death_cross_evaluator
        inst = Instrument.objects.create(symbol="FALLX", name="FALLX",
                                         asset_class="stock")
        up = list(np.linspace(100, 130, 60))
        down = list(np.linspace(130, 80, 60))
        closes = up + down
        t0 = timezone.now() - timedelta(hours=4 * len(closes))
        for i, c in enumerate(closes):
            PriceData.objects.create(
                instrument=inst, timeframe="4h",
                timestamp=t0 + timedelta(hours=4 * i),
                open=Decimal(str(round(c, 4))),
                high=Decimal(str(round(c * 1.002, 4))),
                low=Decimal(str(round(c * 0.998, 4))),
                close=Decimal(str(round(c, 4))), volume=1, source="test")
        start = t0 + timedelta(hours=4 * 30)
        rs = death_cross_evaluator(
            {"fast": 5, "slow": 30, "stop_pct": 0.05, "target_pct": 0.10},
            start, timezone.now(), universe=[inst.id])
        self.assertTrue(rs, "the cross down happened in the window")
        self.assertAlmostEqual(rs[0], 2.0)
        self.assertEqual(death_cross_evaluator({"fast": 30, "slow": 5},
                                               start, timezone.now(),
                                               universe=[inst.id]), [])
