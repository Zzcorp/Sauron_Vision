"""THE PROVING GROUND READS ONLY A MARKET (2026-10-06).

`prove rules --save` printed, for the ETF class alone: macd_bullish_crossover
long "expectancy +21.829R · holdout +54.819R · payoff 43.16 · worst run
+100.796R" — PROVEN — and short mirrors with a worst run of +45733R. Every
other class read under 0.5R a trade. One or more ETF series carried broken
bars, and single trades entered or gapped out on them read hundreds of R.
A false PROVEN is the dangerous outcome. Three guards, from the root out:

  * THE BAR SANITY (data.sanitize): non-positive or inverted bars and
    spikes past the class's jump bar are dropped and counted per symbol; a
    move that holds is read by its cause — a split or a re-based feed is
    adjusted, any other move is traded as the market it was, a feed that
    never settles leaves the symbol out of the run, each said;
  * THE STOP FLOOR (simulate): a stop under half the class's band floor,
    measured on the signal bar's close, is a broken entry — not simulated,
    counted (defence in depth: the bar sanity drops such an open first);
  * THE LAST GUARD (judge), one-sided: a win past PROVING_MAX_TRADE_R
    (20R) is excluded, a loss past it capped at -20R and kept, each
    counted; past MAX_EXCLUDED_SHARE (2%) of a run the verdict is
    INSUFFICIENT, with the symbols and the count.

The review of 2026-10-06 found the first version cut real tails: a quiet
forex short through a 2.5% Monday gap is an honest -28R, and a stock that
gaps -32% on earnings and holds is a market, not a split — dropping either
can print a false PROVEN.

A clean series reads exactly as before, verdict and words.

Run with:  python manage.py test tests.test_proving_sanity
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from backtester.proving import data as D
from backtester.proving import families as F
from backtester.proving import judge as J
from backtester.proving import run as R
from backtester.proving import simulate as S
from tests.test_proving_ground import flat, synth

OHLC = ["open", "high", "low", "close"]


def _split(df, at, ratio=10.0):
    """An unadjusted `ratio`:1 split from bar `at` on."""
    df = df.copy()
    df.iloc[at:, [df.columns.get_loc(c) for c in OHLC]] /= ratio
    return df


def _zero(df, at):
    df = df.copy()
    df.iloc[at, [df.columns.get_loc(c) for c in OHLC]] = 0.0
    return df


def _one_class(df, symbol="SYM"):
    return {"included": [(symbol, df, S.regimes(df))], "excluded": [],
            "dropped": {}, "broken": [], "start": df.index[0],
            "end": df.index[-1]}


class TheConstantsTests(SimpleTestCase):

    def test_the_bounds(self):
        self.assertEqual(D.MAX_BAR_JUMP, {"forex": 0.15, "index": 0.20,
                                          "commodity": 0.30, "etf": 0.30,
                                          "stock": 0.30, "crypto": 0.50})
        self.assertEqual(D.LEVEL_SHIFT_BARS, 3)
        self.assertEqual(D.max_jump("ETF"), 0.30)
        self.assertEqual(D.max_jump("nothing"), D.DEFAULT_MAX_BAR_JUMP)
        self.assertEqual(S.MIN_STOP_SHARE_OF_FLOOR, 0.5)
        self.assertEqual((J.PROVING_MAX_TRADE_R, J.MAX_EXCLUDED_SHARE),
                         (20.0, 0.02))
        self.assertEqual((D.MAX_RUN_BARS, D.SPLIT_TOL, D.MAX_HELD_MOVE),
                         (12, 0.02, 4.0))

    def test_every_split_read_is_past_the_bar(self):
        """A split must read as a held move to be adjusted at all."""
        for cls in ("stock", "etf"):
            for name, ratio in D.SPLIT_RATIOS.items():
                self.assertGreater(abs(ratio - 1.0), D.max_jump(cls),
                                   (cls, name))
        for cls in ("forex", "index", "commodity"):
            for name, ratio in D.REBASE_RATIOS.items():
                self.assertGreater(abs(ratio - 1.0), D.max_jump(cls),
                                   (cls, name))

    def test_the_ratios_by_class(self):
        self.assertEqual(D.ratios_for("ETF"), D.SPLIT_RATIOS)
        self.assertEqual(D.ratios_for("forex"), D.REBASE_RATIOS)
        self.assertEqual(D.ratios_for("crypto"), {})
        self.assertEqual(set(D.ratios_for(None)),
                         set(D.SPLIT_RATIOS) | set(D.REBASE_RATIOS))
        # a -33% gap and a +100% bid are markets, not splits
        self.assertEqual(D.ratio_name(0.665, D.SPLIT_RATIOS), "")
        self.assertEqual(D.ratio_name(2.0, D.SPLIT_RATIOS), "")
        self.assertEqual(D.ratio_name(0.505, D.SPLIT_RATIOS), "2:1")


class TheBarSanityTests(SimpleTestCase):

    def test_a_clean_series_comes_back_untouched_in_every_class(self):
        for cls in R.CLASSES:
            for seed, drift in ((5, 0.001), (11, 0.0), (3, -0.001)):
                df = synth(3400, seed=seed, drift=drift)
                out, check = D.sanitize(df, cls)
                self.assertIs(out, df, (cls, seed))
                self.assertEqual(check, {"bad": 0, "spikes": 0, "dropped": 0,
                                         "broken": "", "adjusted": [],
                                         "held": 0})

    def test_bad_bars_and_a_spike_are_dropped_and_counted(self):
        df = synth(400, seed=2)
        df = _zero(df, 100)                                     # zero bar
        df.iloc[150, df.columns.get_loc("low")] = \
            df.iloc[150]["high"] * 1.01                         # high < low
        df.iloc[200, df.columns.get_loc("open")] = 0.001        # near-zero open
        df.iloc[200, df.columns.get_loc("low")] = 0.001
        df.iloc[250, df.columns.get_loc("close")] *= 10         # a one-bar spike
        df.iloc[250, df.columns.get_loc("high")] = df.iloc[250]["close"]
        out, check = D.sanitize(df, "etf")
        self.assertEqual(check, {"bad": 2, "spikes": 2, "dropped": 4,
                                 "broken": "", "adjusted": [], "held": 0})
        self.assertEqual(len(out), len(df) - 4)
        for i in (100, 150, 200, 250):
            self.assertNotIn(df.index[i], out.index)

    def test_a_ten_to_one_split_is_adjusted_and_said(self):
        df = _split(synth(3400, seed=8), 2500)
        out, check = D.sanitize(df, "etf")
        self.assertEqual(check["broken"], "")
        self.assertEqual(check["adjusted"],
                         [f"a 10:1 split at {df.index[2500]:%Y-%m-%d %H:%M}"])
        self.assertEqual(len(out), len(df))
        # every bar before the split is on the new level, as an adjusted
        # series is: the step across it is an ordinary bar again
        step = out["open"].iloc[2500] / out["close"].iloc[2499] - 1.0
        self.assertLess(abs(step), 0.05)
        self.assertAlmostEqual(out["close"].iloc[100],
                               df["close"].iloc[100] / 10.0)
        self.assertEqual(out["close"].iloc[3000], df["close"].iloc[3000])

    def test_a_reverse_split_is_adjusted_too(self):
        df = _split(synth(3400, seed=8), 2500, ratio=1 / 3)     # 1:3, +200%
        self.assertEqual(D.sanitize(df, "etf")[1]["adjusted"],
                         [f"a 1:3 split at {df.index[2500]:%Y-%m-%d %H:%M}"])

    def test_a_crash_that_holds_is_traded_as_a_market(self):
        """-32% on earnings, held: every bar kept, the gap in the bars."""
        df = _split(synth(3400, seed=8), 2500, ratio=1 / 0.68)
        out, check = D.sanitize(df, "stock")
        self.assertEqual(check, {"bad": 0, "spikes": 0, "dropped": 0,
                                 "broken": "", "adjusted": [], "held": 1})
        self.assertEqual(len(out), len(df))
        self.assertLess(out["open"].iloc[2500] / out["close"].iloc[2499], 0.7)

    def test_a_gap_the_size_of_a_rare_split_is_still_a_market(self):
        """-35% is 2.5% off a 3:2 split, and 3:2 is not read as a split."""
        df = _split(synth(3400, seed=8), 2500, ratio=1 / 0.65)
        self.assertEqual(D.sanitize(df, "stock")[1]["held"], 1)
        df = _split(synth(3400, seed=8), 2500, ratio=0.5)       # +100%
        self.assertEqual(D.sanitize(df, "stock")[1]["held"], 1)

    def test_a_forex_reversal_that_holds_is_a_market(self):
        """USDTRY-like: 17.5 down to 13.2 and holding."""
        idx = pd.date_range("2024-01-01", periods=100, freq="4h", tz="UTC")
        px = np.r_[np.full(50, 17.5), np.full(50, 13.2)]
        df = pd.DataFrame({"open": px, "high": px * 1.001, "low": px * 0.999,
                           "close": px, "volume": 1.0}, index=idx)
        out, check = D.sanitize(df, "forex")
        self.assertEqual((check["held"], check["broken"], len(out)),
                         (1, "", 100))

    def test_a_re_based_forex_feed_is_adjusted(self):
        df = _split(synth(3400, seed=4), 1000, ratio=100.0)
        self.assertEqual(D.sanitize(df, "forex")[1]["adjusted"],
                         [f"a /100 re-based feed at "
                          f"{df.index[1000]:%Y-%m-%d %H:%M}"])

    def test_a_crypto_collapse_has_no_ratio_to_hide_in(self):
        df = _split(synth(3400, seed=4), 1000, ratio=10.0)      # -90%, held
        check = D.sanitize(df, "crypto")[1]
        self.assertEqual(check["adjusted"], [])
        self.assertIn(f"broken from {df.index[1000]:%Y-%m-%d %H:%M}: the "
                      f"close moved -90% from the last good close and held "
                      f"12 bars — past any market move and no split ratio",
                      check["broken"])

    def test_a_bad_first_print_is_a_spike_not_the_level(self):
        for bad in (0.001, 100.0):
            df = synth(3400)
            df.iloc[0, [df.columns.get_loc(c) for c in OHLC]] *= bad
            out, check = D.sanitize(df, "etf")
            self.assertEqual(check, {"bad": 0, "spikes": 1, "dropped": 1,
                                     "broken": "", "adjusted": [],
                                     "held": 0}, bad)
            self.assertNotIn(df.index[0], out.index)
            self.assertEqual(len(out), len(df) - 1)

    def test_a_short_run_of_zero_prints_is_dropped_not_a_level(self):
        df = synth(3400, seed=4)
        df.iloc[1000:1003, [df.columns.get_loc(c) for c in OHLC]] = 0.001
        out, check = D.sanitize(df, "etf")
        self.assertEqual((check["spikes"], check["broken"]), (3, ""))
        self.assertEqual(len(out), len(df) - 3)

    def test_a_feed_dead_past_the_run_is_left_out(self):
        df = synth(3400, seed=4)
        df.iloc[1000:1020, [df.columns.get_loc(c) for c in OHLC]] = 0.001
        check = D.sanitize(df, "etf")[1]
        self.assertIn(f"broken from {df.index[1000]:%Y-%m-%d %H:%M}",
                      check["broken"])
        self.assertIn("left out of this run", check["broken"])

    def test_an_erratic_feed_is_left_out_in_its_own_words(self):
        df = synth(3400, seed=4)
        c = [df.columns.get_loc(x) for x in OHLC]
        for k in range(12):
            df.iloc[1000 + k, c] = df.iloc[1000 + k, c] * (3.0 if k % 2
                                                          else 0.2)
        check = D.sanitize(df, "etf")[1]
        self.assertIn("12 bars in a row past the 30% bar that never settle "
                      "on one level — an erratic feed", check["broken"])

    def test_a_two_bar_spike_whose_return_bar_opens_off_level(self):
        """The return bar opens where the spike closed: dropped, and the
        level is read again from its close — never a break."""
        df = synth(3400, seed=4)
        c = [df.columns.get_loc(x) for x in OHLC]
        df.iloc[1500, c] = df.iloc[1500, c] * 2
        df.iloc[1501, c] = df.iloc[1501, c] * 2
        df.iloc[1502, df.columns.get_loc("open")] *= 2
        df.iloc[1502, df.columns.get_loc("high")] = df.iloc[1502]["open"]
        check = D.sanitize(df, "etf")[1]
        self.assertEqual((check["spikes"], check["broken"], check["held"]),
                         (3, "", 0))


class TheStopFloorTests(SimpleTestCase):

    def _fire(self, df, at=20):
        fires = np.zeros(len(df), dtype=bool)
        fires[at] = True
        return S.simulate(df, fires, F.LONG, asset_class="etf", care=False,
                          symbol="XYZ")

    def test_an_ordinary_entry_is_simulated(self):
        res = self._fire(flat())
        self.assertEqual(res["skipped"], 0)
        self.assertEqual(len(res["trades"]) + bool(res["open"]), 1)

    def test_a_near_zero_entry_is_not_simulated_and_is_counted(self):
        df = flat()
        df.loc[df.index[21], OHLC] = 0.01      # a broken bar to enter on
        res = self._fire(df)
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(res["trades"], [])
        # without the floor the same bar writes thousands of R
        with patch.object(S, "MIN_STOP_SHARE_OF_FLOOR", 0.0):
            t = self._fire(df)["trades"][0]
        self.assertGreater(t["r"], 1000)


def _pool_of(trades, symbol):
    return [dict(t, symbol=symbol) for t in trades]


def _absurd(start, end, n, r, symbol):
    """`n` trades of `r` R spread over [start, end], one per slot."""
    step = (end - start) / (n + 1)
    return [{"symbol": symbol, "entry_ts": start + step * (i + 1),
             "exit_ts": start + step * (i + 1), "entry": 1.0, "exit": 1.0,
             "r": float(r), "gross_r": float(r), "cost_r": 0.01, "mfe": 0.0,
             "mae": 0.0, "reason": "gap target", "bars": 1,
             "regime": "range", "scaled": False} for i in range(n)]


class TheLastGuardTests(SimpleTestCase):

    def test_the_bound_is_inclusive_and_one_sided(self):
        kept, out = J.sane_trades([{"r": 20.0}, {"r": -20.0}, {"r": 20.01},
                                   {"r": -300.0, "cost_r": 0.1}])
        self.assertEqual([t["r"] for t in kept], [20.0, -20.0, -20.0])
        self.assertEqual(kept[2]["r_raw"], -300.0)
        self.assertTrue(kept[2]["capped"])
        self.assertAlmostEqual(kept[2]["gross_r"] - kept[2]["cost_r"], -20.0)
        self.assertEqual([t["r"] for t in out], [20.01, -300.0])

    def test_a_clean_pool_is_judged_exactly_as_before(self):
        up = synth(4000, seed=7, drift=0.0015)
        tr = S.simulate(up, F.FAMILIES["tsmom"].fires(up, F.LONG, {"n": 500}),
                        F.LONG, asset_class="crypto", symbol="UP")["trades"]
        v = J.judge(tr, start=up.index[0], end=up.index[-1])
        self.assertEqual(v["verdict"], J.PROVEN)
        self.assertEqual(v["excluded"]["n"], 0)
        self.assertNotIn("past 20R", v["why"])

    def test_an_absurd_win_is_excluded_and_said(self):
        up = synth(4000, seed=7, drift=0.0015)
        tr = S.simulate(up, F.FAMILIES["tsmom"].fires(up, F.LONG, {"n": 500}),
                        F.LONG, asset_class="crypto", symbol="UP")["trades"]
        clean = J.judge(tr, start=up.index[0], end=up.index[-1])
        bad = _absurd(up.index[0], up.index[-1], 1, 5000.0, "XYZ")
        v = J.judge(tr + bad, start=up.index[0], end=up.index[-1])
        self.assertEqual(v["verdict"], J.PROVEN)
        self.assertEqual(v["all"], clean["all"], "the numbers never see it")
        n = len(tr) + 1
        self.assertEqual(v["why"],
                         f"{clean['why']}; 1 of {n} trades past 20R "
                         f"({1 / n:.1%}) on XYZ: 1 win excluded")
        self.assertEqual(v["excluded"]["wins_by_symbol"], {"XYZ": 1})
        self.assertEqual(v["excluded"]["capped_by_symbol"], {})

    def test_an_honest_gap_loss_is_capped_and_kept(self):
        """The review's case: a quiet forex short through a 2.5% Monday gap
        that the class's 15% jump bar keeps — an honest -28R. Dropped, it
        left 150 trades at +0.10R and a PROVEN; kept at -20R, the pool
        fails."""
        df = flat(60, lo=36 * (1 - 0.0003), hi=36 * (1 + 0.0003))
        df[["open", "close"]] = 36.0
        df.loc[df.index[30]:, OHLC] *= 1.025
        clean, check = D.sanitize(df, "forex")
        self.assertIs(clean, df)
        fires = np.zeros(len(df), dtype=bool)
        fires[20] = True
        [gap] = S.simulate(df, fires, F.SHORT, asset_class="forex",
                           care=False, symbol="USDTRY")["trades"]
        self.assertEqual(gap["reason"], "gap stop")
        self.assertAlmostEqual(gap["r"], -28.0, places=6)
        start = pd.Timestamp("2024-01-01", tz="UTC")
        end = start + pd.Timedelta(days=900)
        pool = _absurd(start, end, 150, 0.10, "EURUSD")
        gap = dict(gap, entry_ts=start + pd.Timedelta(days=450))
        v = J.judge(pool + [gap], start=start, end=end)
        self.assertEqual(v["verdict"], J.FAILED)
        self.assertAlmostEqual(v["all"]["expectancy"], (15.0 - 20.0) / 151)
        self.assertEqual(v["excluded"]["capped_by_symbol"], {"USDTRY": 1})
        self.assertIn("1 of 151 trades past 20R (0.7%) on USDTRY: 1 loss "
                      "capped at -20R", v["why"])
        # the guard of the first version: the loss dropped, a false pass
        dropped = [t for t in pool + [gap] if t["r"] > -20]
        self.assertGreater(J.judge(dropped, start=start, end=end)["all"]
                           ["expectancy"], 0)

    def test_past_two_percent_the_verdict_is_insufficient_with_its_words(self):
        rw = synth(3000, seed=11)
        tr = _pool_of(S.simulate(rw, F.FAMILIES["donchian"].fires(rw, F.LONG),
                                 F.LONG, asset_class="etf")["trades"], "SPY")
        start, end = rw.index[0], rw.index[-1]
        bad = (_absurd(start, end, 8, 150.0, "XYZ")
               + _absurd(start, end, 2, 90.0, "ABC"))
        # the guard off: the broken trades alone make it PROVEN
        with patch.object(J, "PROVING_MAX_TRADE_R", float("inf")):
            blind = J.judge(tr + bad, start=start, end=end)
        self.assertEqual(blind["verdict"], J.PROVEN, blind["why"])
        v = J.judge(tr + bad, start=start, end=end)
        self.assertEqual(v["verdict"], J.INSUFFICIENT)
        n = len(tr) + 10
        self.assertEqual(v["why"],
                         f"10 of {n} trades past 20R "
                         f"({10 / n:.1%}) on XYZ (8), ABC (2): 10 wins "
                         f"excluded — over the 2% a verdict may lose: the "
                         f"history is broken, not judged")
        self.assertLess(abs(v["all"]["expectancy"]), 1.0)

    def test_a_failed_pool_on_broken_data_is_not_read_as_a_fail_either(self):
        rw = synth(3000, seed=11)
        tr = _pool_of(S.simulate(rw, F.FAMILIES["donchian"].fires(rw, F.LONG),
                                 F.LONG, asset_class="etf")["trades"], "SPY")
        bad = _absurd(rw.index[0], rw.index[-1], 10, -400.0, "XYZ")
        v = J.judge(tr + bad, start=rw.index[0], end=rw.index[-1])
        self.assertEqual(v["verdict"], J.INSUFFICIENT)
        self.assertIn("10 of", v["why"])
        self.assertIn("10 losses capped at -20R", v["why"])


class TheCleanSeriesTests(SimpleTestCase):
    """The verdicts the proving ground gave before the sanity, on clean
    synthetic ETF histories, pinned word for word."""

    def _rows(self, seed, drift):
        df = synth(3400, seed=seed, drift=drift)
        clean, check = D.sanitize(df, "etf")
        self.assertEqual(check["dropped"], 0)
        data = _one_class(clean)
        out = {}
        for fam, d in F.live_rule_cases():
            trades, _open, skipped = R._pool(fam, d, {}, "none", data, "etf",
                                             "4h")
            self.assertEqual(skipped, {})
            j = R._judge_pool(trades, data, 1)
            out[(fam.key, d)] = (j["verdict"], j["why"], j["all"]["n"])
        return out

    def test_the_pre_sanity_verdicts_stand(self):
        rows = self._rows(5, 0.001)
        self.assertEqual(rows[("macd_cross", "long")],
                         ("proven", "+0.344R a trade, +0.498R on the holdout, "
                                    "lower bound +0.160R, 5/5 folds", 116))
        self.assertEqual(rows[("macd_cross", "short")],
                         ("failed", "expectancy -0.430R", 121))
        self.assertEqual(rows[("rsi_divergence", "short")],
                         ("failed", "expectancy -0.314R", 88))
        rows = self._rows(11, 0.0)
        self.assertEqual(rows[("macd_cross", "long")],
                         ("promising", "lower bound -0.12R at 0.0500 over 1 "
                                       "candidate(s)", 121))


def _seed_bars(symbol, df, asset_class="etf"):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class=asset_class)
    PriceData.objects.bulk_create([
        PriceData(instrument=inst, timeframe="4h", timestamp=ts,
                  open=Decimal(str(round(r.open, 6))),
                  high=Decimal(str(round(r.high, 6))),
                  low=Decimal(str(round(r.low, 6))),
                  close=Decimal(str(round(r.close, 6))),
                  volume=1, source="test")
        for ts, r in df.iterrows()], batch_size=1000)


class TheEtfRunTests(TestCase):
    """The server's shape: an ETF class with a 10:1 split, zero bars and a
    feed that died."""

    @classmethod
    def setUpTestData(cls):
        _seed_bars("CLEANETF", synth(3400, seed=11))
        _seed_bars("SPLITETF", _zero(_split(synth(3400, seed=8), 2500), 1200))
        broken = _zero(synth(3400, seed=9), 1500)
        broken.iloc[2200, [broken.columns.get_loc(c)
                           for c in ("open", "low")]] = 0.001
        _seed_bars("ZEROETF", broken)
        dead = synth(3400, seed=6)
        dead.iloc[1800:1830, [dead.columns.get_loc(c) for c in OHLC]] = 0.001
        _seed_bars("DEADETF", dead)

    def test_the_raw_split_series_writes_absurd_r(self):
        """What the run read before: the stored bars, the bad rows only
        filtered — one trade across the split is past 20R."""
        df = D.load_history("SPLITETF")
        worst = 0.0
        for fam, d in F.live_rule_cases():
            for t in S.simulate(df, fam.fires(df, d), d,
                                asset_class="etf")["trades"]:
                worst = max(worst, abs(t["r"]))
        self.assertGreater(worst, J.PROVING_MAX_TRADE_R)

    def test_the_run_adjusts_the_split_and_leaves_the_dead_feed_out(self):
        data = R.load_class(["CLEANETF", "SPLITETF", "ZEROETF", "DEADETF"],
                            "4h", "etf")
        self.assertEqual([s for s, _df, _l in data["included"]],
                         ["CLEANETF", "SPLITETF", "ZEROETF"])
        self.assertEqual(data["dropped"], {"SPLITETF": 1, "ZEROETF": 2})
        self.assertEqual(data["adjusted"], {"SPLITETF": [
            "a 10:1 split at 2024-02-21 16:00"]})
        [(sym, why)] = data["broken"]
        self.assertEqual(sym, "DEADETF")
        self.assertIn("-100%", why)
        self.assertIn(("DEADETF", why), data["excluded"])

    def test_prove_rules_prints_what_it_read_and_proves_nothing_absurd(self):
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        out = StringIO()
        call_command("prove", "rules", "--class", "etf", "--save", stdout=out)
        text = out.getvalue()
        self.assertIn("data: 3 bar(s) dropped on ZEROETF (2), SPLITETF (1) · "
                      "SPLITETF adjusted for a 10:1 split at 2024-02-21 16:00",
                      text)
        self.assertIn("DEADETF left out: broken from", text)
        rows = list(ProvingVerdict.objects.all())
        self.assertEqual(len(rows), len(F.live_rule_cases()))
        for v in rows:
            self.assertNotEqual(v.verdict, "proven", v.live_rule)
            self.assertEqual(v.symbols_n, 3)
            if v.expectancy is not None:
                self.assertLess(abs(v.expectancy), 1.0, v.live_rule)
                self.assertLess(v.payoff or 0, 5.0, v.live_rule)
                self.assertLess(v.max_dd_r, 100.0, v.live_rule)
            self.assertEqual(v.detail["data"]["bars_dropped"],
                             {"SPLITETF": 1, "ZEROETF": 2})
            self.assertEqual(v.detail["data"]["trades_excluded"], {})
            self.assertEqual(v.detail["data"]["trades_capped"], {})
            # the 0.001 open on ZEROETF went out with the bar sanity: the
            # stop floor behind it never fires on the run's own path
            self.assertEqual(v.detail["data"]["trades_skipped"], {})
        self.assertFalse(ProvingTrade.objects.filter(r__gt=20).exists())
        self.assertFalse(ProvingTrade.objects.filter(r__lt=-20).exists())
        # the saved run says the same on `prove show`
        out = StringIO()
        call_command("prove", "show", stdout=out)
        self.assertIn("data: 3 bar(s) dropped on ZEROETF (2), SPLITETF (1)",
                      out.getvalue())

    def test_prove_data_names_the_adjusted_and_the_broken(self):
        out = StringIO()
        call_command("prove", "data", "--class", "etf", stdout=out)
        text = out.getvalue()
        self.assertIn("── etf ─ 3 judged, 0 short, 1 broken", text)
        self.assertIn("DEADETF      BROKEN: broken from", text)
        self.assertIn("SPLITETF     ADJUSTED for a 10:1 split at "
                      "2024-02-21 16:00", text)
        self.assertIn("2 bar(s) dropped", text)


class TheDataWordsTests(SimpleTestCase):

    def test_a_clean_run_says_nothing(self):
        self.assertEqual(R.data_words({"bars_dropped": {}, "broken": [],
                                       "trades_skipped": {},
                                       "trades_excluded": {}}), "")
        self.assertEqual(R.data_words(None), "")

    def test_the_line(self):
        self.assertEqual(
            R.data_words({"bars_dropped": {"XYZ": 3},
                          "adjusted": {"SPY": ["a 10:1 split at 2026-03-02 "
                                               "16:00"]},
                          "held": {"USDTRY": 1},
                          "trades_skipped": {"ABC": 2},
                          "trades_excluded": {"XYZ": 38, "ABC": 3},
                          "trades_capped": {"USDTRY": 1},
                          "broken": [["QQQ", "broken from 2026-03-02"]]}),
            "3 bar(s) dropped on XYZ · SPY adjusted for a 10:1 split at "
            "2026-03-02 16:00 · 1 held move(s) past the class's jump bar "
            "traded as a market on USDTRY · 2 trade(s) skipped (stop under "
            "half the class floor) on ABC · 41 win(s) excluded past +20R on "
            "XYZ (38), ABC (3) · 1 loss(es) capped at -20R on USDTRY · QQQ "
            "left out: broken from 2026-03-02")


class TheGeneratorChoosesOnSaneTradesTests(SimpleTestCase):
    """generate() ranks its candidates on the trades the judge will read.
    Ranked on every trade, a pool lifted by broken-bar wins would take the
    shortlist and an honest leader would never be judged. Ten in-sample
    +500R wins, not one: at the Sidak level the bootstrap's low quantile
    sits in the resamples that never draw a single outlier."""

    def test_an_absurd_in_sample_pool_never_takes_the_shortlist(self):
        data = _one_class(synth(3400, seed=5))
        start, end = data["start"], data["end"]
        split = start + (end - start) * (1.0 - J.HOLDOUT_FRAC)
        honest = (_absurd(start, end, 30, 2.0, "A")
                  + _absurd(start, end, 30, -0.5, "A"))
        poisoned = (_absurd(start, end, 28, 0.5, "B")
                    + _absurd(start, end, 28, -1.0, "B")
                    + _absurd(start, split, 10, 500.0, "B"))

        def fake_pool(fam, d, params, flt, *_a, **_k):
            if (d, flt) == (F.LONG, "none"):
                if params == {"n": 20}:
                    return honest, 0, {}
                if params == {"n": 55}:
                    return poisoned, 0, {}
            return [], 0, {}

        with patch.object(R, "universe", return_value={"etf": ["A", "B"]}), \
                patch.object(R, "load_class", return_value=data), \
                patch.object(R, "_pool", side_effect=fake_pool):
            [row] = R.generate(asset_class="etf", families=["donchian"],
                               shortlist=1)
            # ranked on every trade, the poisoned pool leads
            with patch.object(J, "PROVING_MAX_TRADE_R", float("inf")):
                [blind] = R.generate(asset_class="etf",
                                     families=["donchian"], shortlist=1)
        self.assertEqual(row["params"], {"n": 20})
        self.assertEqual(blind["params"], {"n": 55})
