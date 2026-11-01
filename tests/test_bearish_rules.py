"""The bearish price rules (2026-10-31, signals/rules/bearish_rules.py):
bull_trap_swing_high, po3_london_sweep_short, range_breakdown_short and
trend_continuation_short — each born at research, each the live face of
one proving-ground family.

What the file pins, per rule: a hand-built frame on which it fires, with
its levels (the bot's 1.5 ATR stop, a 2R target) and its words; one frame
per way it must stay quiet; and parity — on every prefix of a seeded
series the rule fires iff the family fires short on its last bar. Then
the shared spine: an open last bar is not read, and an unadjusted forward
split is no breakdown. And po3_london_sweep_short's entry, once promoted:
the bot's stop and target on the 1h ATR its verdict simulated, whatever
the config's atr_timeframe.

Run with:  python manage.py test tests.test_bearish_rules
"""
from datetime import datetime, time as dtime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase

from backtester.proving import families as F
from tests.test_bearish_mirrors import bars, inst, run, synth

NY = ZoneInfo("America/New_York")


def frame(rows, start="2024-03-04", freq="4h"):
    idx = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=idx).assign(volume=1.0)


def assert_levels(test, out, asset_class="stock", df=None):
    """Stop 1.5 ATR over the entry (inside the class's band), target 2R
    under it."""
    from bot_program.asset_engine.risk_levels import stop_band
    entry = out["entry"]
    test.assertEqual(out["direction"], "SHORT")
    test.assertGreater(out["stop"], entry)
    test.assertLess(out["target"], entry)
    test.assertAlmostEqual((entry - out["target"]) / (out["stop"] - entry),
                           2.0)
    if df is not None:
        a = float(F.atr(df).iloc[-1])
        lo, hi = stop_band(asset_class)
        frac = min(max(1.5 * a / entry, lo), hi)
        test.assertAlmostEqual(out["stop"], entry * (1 + frac))
    test.assertGreaterEqual(out["score"], 0.60)
    test.assertLessEqual(out["score"], 0.75)


def parity(test, rule, key, df, start, step=1, n_bars=None,
           instrument=None):
    """On every prefix from `start`, the rule fires iff the family fires
    short on the last bar of the frame the rule read."""
    fired = 0
    for m in range(start, len(df) + 1, step):
        p = df.iloc[:m]
        got = run(rule, p, instrument) is not None
        want = bool(F.FAMILIES[key].fires(p, F.SHORT)[-1])
        test.assertEqual(got, want, f"{key} at {m}")
        fired += got
    return fired


# ── bull_trap_swing_high ────────────────────────────────────────────────

def trap_rows(*, close_45=103.5, high_45=105.2, back_at=1, wick_only=False,
              old=False, reclaimed=False):
    """Range bars with flat highs at 101 (no swing there), the swing high
    of 104 at bar 40, a three-bar rally, the close over it at bar 64 and
    the close back under it at bar 64 + back_at."""
    n0 = 100 if old else 61
    rows = [(100.0, 101.0, 99.0, 100.0)] * n0
    rows[40] = (100.0, 104.0, 99.0, 100.0)
    rows += [(100.0, 102.0, 100.0, 101.5), (101.5, 103.0, 101.0, 102.5),
             (102.5, 103.9, 102.0, 103.5)]
    if reclaimed:
        # a first break and reclaim just before (the level is the same:
        # neither bar is a confirmed swing yet)
        rows[-2] = (101.5, 104.6, 101.0, 104.5)
        rows[-1] = (104.5, 104.6, 103.3, 103.5)
    if wick_only:
        rows.append((103.5, 104.8, 103.3, 103.8))
    else:
        rows.append((103.5, 104.8, 103.3, 104.6))
    for _ in range(back_at - 1):
        rows.append((104.6, 104.8, 104.2, 104.5))
    rows.append((104.6, high_45, 103.3, close_45))
    return rows


class BullTrapTests(SimpleTestCase):

    def rule(self):
        from signals.rules.bearish_rules import BullTrapSwingHighRule
        return BullTrapSwingHighRule()

    def test_the_failed_breakout_fires_with_its_level_and_extreme(self):
        df = frame(trap_rows())
        out = run(self.rule(), df, inst("TRAP", "stock"))
        self.assertIsNotNone(out)
        self.assertEqual(out["rule"], "bull_trap_swing_high")
        assert_levels(self, out, "stock", df)
        self.assertEqual(out["sub_scores"]["level"], 104.0)
        self.assertEqual(out["sub_scores"]["extreme"], 105.2)
        self.assertEqual(out["sub_scores"]["bars_above"], 1)
        self.assertIn("Closed above the swing high 104 (1 bar ago)",
                      out["thesis"])
        self.assertIn("Invalid above 105.2", out["thesis"])
        # half an ATR back under scores about the middle of the scale
        self.assertAlmostEqual(out["score"], 0.60 + 0.15 * min(
            1.0, 0.5 / (0.5 * float(F.atr(df).iloc[-1]))), places=3)

    def test_still_above_the_level_is_quiet(self):
        self.assertIsNone(run(self.rule(), frame(trap_rows(close_45=104.3))))

    def test_back_under_five_bars_after_the_break_is_quiet(self):
        self.assertIsNone(run(self.rule(), frame(trap_rows(back_at=5))))

    def test_a_wick_above_is_a_sweep_not_a_trap(self):
        self.assertIsNone(run(self.rule(), frame(trap_rows(wick_only=True))))

    def test_an_extreme_far_above_puts_the_stop_inside_the_pattern(self):
        self.assertIsNone(run(self.rule(), frame(trap_rows(high_45=115.0))))

    def test_a_level_older_than_sixty_bars_is_quiet(self):
        self.assertIsNone(run(self.rule(), frame(trap_rows(old=True))))

    def test_a_level_broken_and_reclaimed_before_does_not_fire_twice(self):
        df = frame(trap_rows(reclaimed=True))
        fires = F.FAMILIES["bull_trap"].fires(df, F.SHORT)
        self.assertEqual(list(np.flatnonzero(fires)), [len(df) - 3])
        self.assertIsNone(run(self.rule(), df))

    def test_parity_with_the_family(self):
        df = synth(700, seed=5)
        self.assertGreater(parity(self, self.rule(), "bull_trap", df, 320),
                           0)
        parity(self, self.rule(), "bull_trap", frame(trap_rows()), 60)


# ── po3_london_sweep_short ──────────────────────────────────────────────

DAY = datetime(2026, 9, 15).date()


def po3_frame(bars=None, base=(1.1003, 1.1019, 1.1011), end_hour=12,
              day=DAY):
    """1h bars from three New York days before `day` to `end_hour` NY on
    it, every bar inside 1.1003-1.1019; the Asian window of the evening
    before reaches 1.1000-1.1020. `bars` sets {NY hour: (o, h, l, c)}."""
    start = pd.Timestamp(datetime.combine(day - timedelta(days=3), dtime(0),
                                          tzinfo=NY)).tz_convert("UTC")
    end = pd.Timestamp(datetime.combine(day, dtime(end_hour),
                                        tzinfo=NY)).tz_convert("UTC")
    idx = pd.date_range(start, end, freq="1h")
    lo, hi, c = base
    df = pd.DataFrame({"open": c, "high": hi, "low": lo, "close": c,
                       "volume": 1.0}, index=idx)

    def at(h, d=day):
        return pd.Timestamp(datetime.combine(d, dtime(h), tzinfo=NY)) \
            .tz_convert("UTC")
    asia = day - timedelta(days=1)
    df.loc[at(21, asia), "high"] = 1.1020
    df.loc[at(22, asia), "low"] = 1.1000
    for h, v in (bars or {}).items():
        df.loc[at(h), ["open", "high", "low", "close"]] = v
    return df.loc[:at(end_hour)]


SWEEP = (1.1012, 1.1035, 1.1010, 1.1028)
BACK = (1.1028, 1.1030, 1.1012, 1.1015)


class PO3LondonTests(SimpleTestCase):

    def rule(self):
        from signals.rules.bearish_rules import PO3LondonSweepShortRule
        return PO3LondonSweepShortRule()

    def fx(self):
        return inst("EURUSD", "forex")

    def test_the_london_sweep_back_under_fires_at_four_new_york(self):
        df = po3_frame({3: SWEEP, 4: BACK}, end_hour=4)
        out = run(self.rule(), df, self.fx())
        self.assertIsNotNone(out)
        self.assertEqual(out["rule"], "po3_london_sweep_short")
        assert_levels(self, out, "forex", df)
        self.assertEqual(out["sub_scores"]["asian_high"], 1.102)
        self.assertEqual(out["sub_scores"]["extreme"], 1.1035)
        self.assertIn("London ran the Asian high (1.102) to 1.1035",
                      out["thesis"])
        self.assertAlmostEqual(out["sub_scores"]["quality"], 0.25, places=3)

    def test_the_rule_reads_one_hour_bars(self):
        df = po3_frame({3: SWEEP, 4: BACK}, end_hour=4)
        with bars(df) as load:
            self.rule().evaluate(self.fx())
        self.assertEqual(load.call_args[0][1], "1h")

    def test_a_run_at_six_new_york_is_not_london(self):
        df = po3_frame({6: SWEEP, 7: BACK}, end_hour=7)
        self.assertIsNone(run(self.rule(), df, self.fx()))

    def test_the_lows_run_before_the_fire_is_no_clean_day(self):
        df = po3_frame({3: SWEEP, 4: (1.1028, 1.1030, 1.0995, 1.1015)},
                       end_hour=4)
        self.assertIsNone(run(self.rule(), df, self.fx()))

    def test_back_under_only_at_noon_is_too_late(self):
        held = {h: (1.1026, 1.1030, 1.1022, 1.1026) for h in range(4, 12)}
        df = po3_frame({3: SWEEP, **held, 12: BACK}, end_hour=12)
        self.assertIsNone(run(self.rule(), df, self.fx()))

    def test_a_london_high_far_above_puts_the_stop_inside_the_pattern(self):
        narrow = (1.1007, 1.1015, 1.1011)
        df = po3_frame({3: (1.1012, 1.1200, 1.1010, 1.1028), 4: BACK},
                       base=narrow, end_hour=4)
        self.assertIsNone(run(self.rule(), df, self.fx()))

    def test_no_tz_database_no_fires(self):
        df = po3_frame({3: SWEEP, 4: BACK}, end_hour=4)
        with patch("signals.smc.sessions.new_york_timezone",
                   return_value=None):
            self.assertIsNone(run(self.rule(), df, self.fx()))

    def test_a_second_close_back_under_the_same_day_is_quiet(self):
        df = po3_frame({3: SWEEP, 4: BACK,
                        5: (1.1015, 1.1027, 1.1013, 1.1025),
                        6: (1.1025, 1.1026, 1.1012, 1.1014)}, end_hour=6)
        fires = F.FAMILIES["po3_london"].fires(df, F.SHORT)
        self.assertEqual(int(fires.sum()), 1)
        self.assertIsNone(run(self.rule(), df, self.fx()))

    def test_stocks_and_etfs_stay_silent(self):
        df = po3_frame({3: SWEEP, 4: BACK}, end_hour=4)
        for cls in ("stock", "etf"):
            self.assertIsNone(run(self.rule(), df, inst("SYM", cls)), cls)

    def test_parity_with_the_family(self):
        df = synth(1200, seed=4, freq="1h", start="2026-01-05")
        self.assertGreater(parity(self, self.rule(), "po3_london", df, 360,
                                  instrument=self.fx()), 0)


class PO3EntryLevelsTests(TestCase):
    """The bot's entry levels for a rule whose family pins its bars
    (risk_levels.rule_atr_timeframe): po3_london's 1h verdict sizes a 1h
    ATR stop, never the config's 4h one (about twice as wide)."""

    ATR = {"1h": 0.0010, "4h": 0.0020, "1d": 0.0050}

    def _levels(self, rule, extras=None):
        from types import SimpleNamespace

        from bot_program.asset_engine import risk_levels as RL
        cfg = SimpleNamespace(asset_class="forex", extras=extras or {},
                              stop_loss_pct=1.0, take_profit_pct=2.0)
        seen = []

        def atr(symbol, timeframe="4h", period=14):
            seen.append(timeframe)
            return self.ATR[timeframe]
        with patch.object(RL, "atr_for", side_effect=atr):
            sl, tp, meta = RL.stop_and_target(cfg, "EURUSD", 1.1, "SELL",
                                              rule_name=rule)
        return seen[-1], sl, tp, meta

    def test_po3_reads_the_one_hour_atr(self):
        tf, sl, tp, meta = self._levels("po3_london_sweep_short")
        self.assertEqual(tf, "1h")
        self.assertAlmostEqual(sl - 1.1, 1.5 * self.ATR["1h"])
        self.assertAlmostEqual(1.1 - tp, 3.0 * self.ATR["1h"])
        self.assertEqual(meta["atr_timeframe"], "1h")
        # the config's own atr_timeframe does not move it
        tf, *_rest = self._levels("po3_london_sweep_short",
                                  {"atr_timeframe": "1d"})
        self.assertEqual(tf, "1h")

    def test_every_other_rule_keeps_the_config_s_bars(self):
        for rule in ("bull_trap_swing_high", "rsi_bull_divergence", ""):
            tf, sl, _tp, meta = self._levels(rule)
            self.assertEqual(tf, "4h", rule)
            self.assertAlmostEqual(sl - 1.1, 1.5 * self.ATR["4h"])
            self.assertNotIn("atr_timeframe", meta)
            self.assertEqual(self._levels(rule, {"atr_timeframe": "1d"})[0],
                             "1d", rule)

    def _propose(self, rule):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from django.contrib.auth.models import User
        from django.utils import timezone

        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from market_data.models import PriceData
        from signals.models import RuleControl, Signal
        user = User.objects.create_user(f"po3_{rule}", password="x")
        inst = Instrument.objects.create(symbol="POX", name="POX",
                                         asset_class="stock")
        now = timezone.now()
        # ATR(1h) 2.0, ATR(4h) 8.0: a 3.0 stop on the 1h bars, 12.0 on 4h
        for tf, hours, half in (("4h", 4, 4.0), ("1h", 1, 1.0)):
            start = now - timedelta(hours=hours * 61)
            PriceData.objects.bulk_create([PriceData(
                instrument=inst, timeframe=tf,
                timestamp=start + timedelta(hours=hours * i), open=150,
                high=150 + half, low=150 - half, close=150, source="t")
                for i in range(60)])
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="PO3", enabled=True,
            mode="paper", symbols=["POX"], capital=Decimal("10000"),
            base_currency="USD", position_size_pct=2.0,
            max_concurrent_positions=5, max_daily_loss_pct=2.0,
            stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
            min_signals_for_entry=1, cool_down_minutes=0)
        RuleControl.objects.create(rule_name=rule, promotion_stage="paper")
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bearish",
            urgency="medium", title="POX", description="t", rule_name=rule,
            score=0.7, sub_scores={}, price_at_signal=Decimal("150"),
            suggested_entry=Decimal("150"), suggested_stop=Decimal("151"),
            suggested_target=Decimal("148"))
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "150.00"}
        client.get_positions.return_value = []
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(cfg).propose_entry("POX")

    def test_the_bot_s_entry_places_the_judged_stop(self):
        cand = self._propose("po3_london_sweep_short")
        self.assertIsNotNone(cand)
        self.assertEqual(cand.level_meta["atr_timeframe"], "1h")
        self.assertAlmostEqual(cand.level_meta["atr"], 2.0, places=6)
        self.assertAlmostEqual(cand.stop - cand.price, 1.5 * 2.0, places=6)

    def test_another_rule_s_entry_keeps_the_four_hour_atr(self):
        cand = self._propose("bull_trap_swing_high")
        self.assertIsNotNone(cand)
        self.assertNotIn("atr_timeframe", cand.level_meta)
        self.assertAlmostEqual(cand.level_meta["atr"], 8.0, places=6)
        self.assertAlmostEqual(cand.stop - cand.price, 1.5 * 8.0, places=6)


# ── range_breakdown_short ───────────────────────────────────────────────

def range_rows(*, wide=False, break_close=97.8, t_close=97.0,
               break_high=99.6, extra=None):
    """Sixty bars of 99-101 (ATR 2), a break bar closing under 99, and a
    follow-through bar."""
    if wide:
        rows = [(105 - i / 3, 105.5 - i / 3, 104.5 - i / 3, 105 - i / 3)
                for i in range(60)]
        last = rows[-1][3]
        rows += [(last, last + 0.1, last - 1.4, last - 1.3),
                 (last - 1.3, last - 1.2, last - 2.0, last - 1.9)]
        return rows
    rows = [(100.0, 101.0, 99.0, 100.0)] * 60
    rows.append((99.5, break_high, min(97.6, break_close - 0.2), break_close))
    rows.append((break_close, min(98.0, break_close + 0.2),
                 min(96.9, t_close - 0.1), t_close))
    rows += extra or []
    return rows


class RangeBreakdownTests(SimpleTestCase):

    def rule(self):
        from signals.rules.bearish_rules import RangeBreakdownShortRule
        return RangeBreakdownShortRule()

    def test_the_break_with_follow_through_fires(self):
        df = frame(range_rows())
        out = run(self.rule(), df, inst("RNG", "stock"))
        self.assertIsNotNone(out)
        assert_levels(self, out, "stock", df)
        self.assertEqual(out["sub_scores"]["range_low"], 99.0)
        self.assertEqual(out["sub_scores"]["extreme"], 99.6)
        self.assertIn("Broke the low of a 30-bar range (99)", out["thesis"])

    def test_a_wide_range_is_a_trend_leg_not_a_consolidation(self):
        self.assertIsNone(run(self.rule(), frame(range_rows(wide=True))))

    def test_no_follow_through_is_quiet(self):
        self.assertIsNone(run(self.rule(), frame(range_rows(t_close=98.7))))

    def test_a_break_of_a_tenth_of_an_atr_is_quiet(self):
        self.assertIsNone(run(self.rule(), frame(range_rows(
            break_close=98.8, t_close=98.5))))

    def test_a_second_follow_through_bar_after_a_fire_is_quiet(self):
        df = frame(range_rows(extra=[(97.0, 97.1, 95.9, 96.0)]))
        fires = F.FAMILIES["range_breakdown"].fires(df, F.SHORT)
        self.assertEqual(list(np.flatnonzero(fires)), [len(df) - 2])
        self.assertIsNone(run(self.rule(), df))

    def test_a_break_bar_high_far_above_puts_the_stop_inside(self):
        self.assertIsNone(run(self.rule(), frame(range_rows(
            break_high=103.8))))

    def test_parity_with_the_family(self):
        parity(self, self.rule(), "range_breakdown", frame(range_rows()), 60)
        fired = 0
        for seed in (3, 5):
            fired += parity(self, self.rule(), "range_breakdown",
                            synth(1500, seed=seed, drift=-0.0005), 1100)
        self.assertGreater(fired, 0)


# ── trend_continuation_short ────────────────────────────────────────────

def trend_fire():
    """A seeded downtrend and the prefix that ends on a fire."""
    df = synth(700, seed=1, drift=-0.002)
    fires = np.flatnonzero(F.FAMILIES["trend_rally"].fires(df, F.SHORT))
    return df, int(fires[2])


class TrendContinuationTests(SimpleTestCase):

    def rule(self):
        from signals.rules.bearish_rules import TrendContinuationShortRule
        return TrendContinuationShortRule()

    def test_the_rejected_rally_fires_and_reads_six_hundred_bars(self):
        df, t = trend_fire()
        p = df.iloc[:t + 1]
        with bars(p) as load:
            out = self.rule().evaluate(inst("TRND", "crypto"))
        self.assertEqual(load.call_args[0][2], 600)
        self.assertIsNotNone(out)
        assert_levels(self, out, "crypto", p)
        self.assertLess(out["sub_scores"]["extreme"],
                        out["sub_scores"]["swing_high"])
        self.assertIn("EMA20 < EMA50 < SMA200", out["thesis"])

    def _edit(self, **cols):
        df, t = trend_fire()
        p = df.iloc[:t + 1].copy()
        for col, value in cols.items():
            p.loc[p.index[-1], col] = value(p)
        return p

    def test_a_rally_that_takes_out_the_swing_high_is_quiet(self):
        df, t = trend_fire()
        _f, info = F.trend_rally(df.iloc[:t + 1], F.SHORT, detail=True)
        p1 = float(info["swing_high"][-1])
        p = self._edit(high=lambda p: p1 * 1.001)
        self.assertIsNone(run(self.rule(), p))

    def test_a_close_above_the_short_ema_is_quiet(self):
        def above(p):
            ef = p["close"].ewm(span=20, adjust=False).mean()
            return float(ef.iloc[-2]) * 1.002
        p = self._edit(close=above)
        p.loc[p.index[-1], "open"] = float(p["close"].iloc[-1]) * 1.003
        p.loc[p.index[-1], "high"] = float(p["open"].iloc[-1]) * 1.001
        self.assertIsNone(run(self.rule(), p))

    def test_averages_stacked_up_are_quiet(self):
        from tests.test_bearish_mirrors import reflect
        df, t = trend_fire()
        up = reflect(df.iloc[:t + 1])
        self.assertIsNone(run(self.rule(), up))

    def test_a_green_rejection_bar_is_quiet(self):
        p = self._edit(open=lambda p: float(p["close"].iloc[-1]) * 0.999)
        self.assertIsNone(run(self.rule(), p))

    def test_a_second_rejection_under_the_same_swing_high_is_quiet(self):
        df, t = trend_fire()
        p = df.iloc[:t + 1].copy()
        _f, info = F.trend_rally(p, F.SHORT, detail=True)
        p1 = float(info["swing_high"][-1])
        c0 = float(p["close"].iloc[-1])
        # the bar after the fire tops the two before it (so neither becomes
        # a confirmed swing high by the second rejection) and stays under P1
        top = max(float(p["high"].iloc[-2]), float(p["high"].iloc[-1]))
        nxt = pd.DataFrame(
            {"open": [c0], "close": [c0 * 1.002],
             "high": [top + 0.25 * (p1 - top)],
             "low": [c0 * 0.999], "volume": [1.0]},
            index=[p.index[-1] + pd.Timedelta(hours=4)])
        p = pd.concat([p, nxt])
        ef1 = float(p["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        c2 = ef1 * 0.997
        second = pd.DataFrame(
            {"open": [c2 * 1.004], "close": [c2], "high": [ef1 * 1.0005],
             "low": [c2 * 0.998], "volume": [1.0]},
            index=[p.index[-1] + pd.Timedelta(hours=4)])
        p = pd.concat([p, second])
        fires = F.FAMILIES["trend_rally"].fires(p, F.SHORT)
        self.assertTrue(fires[-3])
        self.assertFalse(fires[-1])
        self.assertIsNone(run(self.rule(), p))
        # the same bar fires once the first rejection is not one (green):
        # it is the swing high's one fire that keeps it quiet
        green = p.copy()
        green.iloc[-3, green.columns.get_loc("open")] = \
            float(green["close"].iloc[-3]) * 0.999
        self.assertTrue(F.FAMILIES["trend_rally"].fires(green, F.SHORT)[-1])

    def test_parity_with_the_family(self):
        df = synth(700, seed=1, drift=-0.002)
        self.assertGreater(parity(self, self.rule(), "trend_rally", df, 300,
                                  step=2), 0)


# ── the spine ───────────────────────────────────────────────────────────

class TheSpineTests(SimpleTestCase):

    def test_an_open_last_bar_is_not_read(self):
        from signals.rules.bearish_rules import closed_frame
        df = frame(range_rows())
        last = df.index[-1]
        self.assertEqual(len(closed_frame(df, "4h",
                                          last + pd.Timedelta(hours=3))),
                         len(df) - 1)
        self.assertEqual(len(closed_frame(df, "4h",
                                          last + pd.Timedelta(hours=4))),
                         len(df))
        self.assertEqual(len(closed_frame(df, "1h",
                                          last + pd.Timedelta(hours=1))),
                         len(df))

    def test_the_fire_bar_still_open_is_no_fire_yet(self):
        from signals.rules.bearish_rules import RangeBreakdownShortRule
        df = frame(range_rows())
        with bars(df), patch("django.utils.timezone.now",
                             return_value=df.index[-1].to_pydatetime()
                             + timedelta(hours=2)):
            self.assertIsNone(RangeBreakdownShortRule().evaluate(inst()))

    def test_short_levels_are_the_bot_s_and_clamped_to_the_band(self):
        from signals.rules.bearish_rules import short_levels
        stop, target = short_levels(100.0, 2.0, "stock")
        self.assertAlmostEqual(stop, 103.0)
        self.assertAlmostEqual(target, 94.0)
        # a forex ATR under the 0.03% floor is widened to the floor
        stop, target = short_levels(1.1, 0.0001, "forex")
        self.assertAlmostEqual(stop, 1.1 * 1.0003)
        self.assertIsNone(short_levels(100.0, float("nan"), "stock"))
        self.assertIsNone(short_levels(0.0, 1.0, "stock"))

    def test_an_unadjusted_split_is_no_breakdown(self):
        from signals.rules.bearish_rules import RangeBreakdownShortRule
        rows = [(100.0, 100.5, 99.5, 100.0)] * 60
        rows += [(10.0, 10.05, 9.9, 9.95), (9.95, 9.96, 9.85, 9.9)]
        df = frame(rows)
        self.assertTrue(F.FAMILIES["range_breakdown"].fires(df, F.SHORT)[-1],
                        "the raw bars break down")
        self.assertIsNone(run(RangeBreakdownShortRule(), df,
                              inst("SPLT", "stock")))
