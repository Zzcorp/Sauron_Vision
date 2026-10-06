"""THE PROVING GROUND READS ONLY A MARKET (2026-10-06).

`prove rules --save` printed, for the ETF class alone: macd_bullish_crossover
long "expectancy +21.829R · holdout +54.819R · payoff 43.16 · worst run
+100.796R" — PROVEN — and short mirrors with a worst run of +45733R. Every
other class read under 0.5R a trade. One or more ETF series carried broken
bars, and single trades entered or gapped out on them read hundreds of R.
A false PROVEN is the dangerous outcome. Three guards, from the root out:

  * THE BAR SANITY (data.sanitize): non-positive or inverted bars and
    spikes past the class's jump bar are dropped and counted per symbol; a
    level shift that holds (an unadjusted split) leaves the symbol out of
    the run, said;
  * THE STOP FLOOR (simulate): a stop under half the class's band floor,
    measured on the signal bar's close, is a broken entry — not simulated,
    counted;
  * THE LAST GUARD (judge): a trade past PROVING_MAX_TRADE_R (20R) is
    excluded and counted; past MAX_EXCLUDED_SHARE (2%) of a run the
    verdict is INSUFFICIENT, with the symbols and the count.

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

    def test_every_split_that_matters_is_past_the_bar(self):
        # 3:2 is -33%, 2:1 is -50%, 1:2 reverse is +100%
        for cls in ("stock", "etf"):
            for move in (-1 / 3, -0.5, 1.0):
                self.assertGreater(abs(move), D.max_jump(cls), (cls, move))


class TheBarSanityTests(SimpleTestCase):

    def test_a_clean_series_comes_back_untouched_in_every_class(self):
        for cls in R.CLASSES:
            for seed, drift in ((5, 0.001), (11, 0.0), (3, -0.001)):
                df = synth(3400, seed=seed, drift=drift)
                out, check = D.sanitize(df, cls)
                self.assertIs(out, df, (cls, seed))
                self.assertEqual(check, {"bad": 0, "spikes": 0, "dropped": 0,
                                         "broken": ""})

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
                                 "broken": ""})
        self.assertEqual(len(out), len(df) - 4)
        for i in (100, 150, 200, 250):
            self.assertNotIn(df.index[i], out.index)

    def test_a_ten_to_one_split_breaks_the_series_from_that_bar(self):
        df = _split(synth(3400, seed=8), 2500)
        out, check = D.sanitize(df, "etf")
        self.assertIn(f"broken from {df.index[2500]:%Y-%m-%d %H:%M}",
                      check["broken"])
        self.assertIn("the close moved -90% from the last good close",
                      check["broken"])
        self.assertIn("3 bars in a row stayed past the 30% bar",
                      check["broken"])
        self.assertIn("unadjusted split", check["broken"])
        self.assertIn("left out of this run", check["broken"])

    def test_a_reverse_split_breaks_it_too(self):
        df = _split(synth(3400, seed=8), 2500, ratio=0.5)       # 1:2, +100%
        self.assertIn("the close moved +", D.sanitize(df, "etf")[1]["broken"])


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

    def test_the_bound_is_inclusive(self):
        kept, out = J.sane_trades([{"r": 20.0}, {"r": -20.0}, {"r": 20.01},
                                   {"r": -300.0}])
        self.assertEqual([t["r"] for t in kept], [20.0, -20.0])
        self.assertEqual([t["r"] for t in out], [20.01, -300.0])

    def test_a_clean_pool_is_judged_exactly_as_before(self):
        up = synth(4000, seed=7, drift=0.0015)
        tr = S.simulate(up, F.FAMILIES["tsmom"].fires(up, F.LONG, {"n": 500}),
                        F.LONG, asset_class="crypto", symbol="UP")["trades"]
        v = J.judge(tr, start=up.index[0], end=up.index[-1])
        self.assertEqual(v["verdict"], J.PROVEN)
        self.assertEqual(v["excluded"]["n"], 0)
        self.assertNotIn("excluded", v["why"])

    def test_a_few_absurd_trades_are_excluded_and_said(self):
        up = synth(4000, seed=7, drift=0.0015)
        tr = S.simulate(up, F.FAMILIES["tsmom"].fires(up, F.LONG, {"n": 500}),
                        F.LONG, asset_class="crypto", symbol="UP")["trades"]
        clean = J.judge(tr, start=up.index[0], end=up.index[-1])
        bad = _absurd(up.index[0], up.index[-1], 1, -5000.0, "XYZ")
        v = J.judge(tr + bad, start=up.index[0], end=up.index[-1])
        self.assertEqual(v["verdict"], J.PROVEN)
        self.assertEqual(v["all"], clean["all"], "the numbers never see it")
        n = len(tr) + 1
        self.assertEqual(v["why"],
                         f"{clean['why']}; 1 of {n} trades excluded past "
                         f"20R ({1 / n:.1%}) on XYZ")
        self.assertEqual(v["excluded"]["by_symbol"], {"XYZ": 1})

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
                         f"10 of {n} trades excluded past 20R "
                         f"({10 / n:.1%}) on XYZ (8), ABC (2) — over the 2% "
                         f"a verdict may lose: the history is broken, not "
                         f"judged")
        self.assertLess(abs(v["all"]["expectancy"]), 1.0)

    def test_a_failed_pool_on_broken_data_is_not_read_as_a_fail_either(self):
        rw = synth(3000, seed=11)
        tr = _pool_of(S.simulate(rw, F.FAMILIES["donchian"].fires(rw, F.LONG),
                                 F.LONG, asset_class="etf")["trades"], "SPY")
        bad = _absurd(rw.index[0], rw.index[-1], 10, -400.0, "XYZ")
        v = J.judge(tr + bad, start=rw.index[0], end=rw.index[-1])
        self.assertEqual(v["verdict"], J.INSUFFICIENT)
        self.assertIn("10 of", v["why"])


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
    """The server's shape: an ETF class with a 10:1 split and zero bars."""

    @classmethod
    def setUpTestData(cls):
        _seed_bars("CLEANETF", synth(3400, seed=11))
        _seed_bars("SPLITETF", _zero(_split(synth(3400, seed=8), 2500), 1200))
        broken = _zero(synth(3400, seed=9), 1500)
        broken.iloc[2200, [broken.columns.get_loc(c)
                           for c in ("open", "low")]] = 0.001
        _seed_bars("ZEROETF", broken)

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

    def test_the_run_leaves_the_split_out_and_counts_the_zero_bars(self):
        data = R.load_class(["CLEANETF", "SPLITETF", "ZEROETF"], "4h", "etf")
        self.assertEqual([s for s, _df, _l in data["included"]],
                         ["CLEANETF", "ZEROETF"])
        self.assertEqual(data["dropped"], {"ZEROETF": 2})
        [(sym, why)] = data["broken"]
        self.assertEqual(sym, "SPLITETF")
        self.assertIn("-90%", why)
        self.assertIn(("SPLITETF", why), data["excluded"])

    def test_prove_rules_prints_what_it_dropped_and_proves_nothing_absurd(self):
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        out = StringIO()
        call_command("prove", "rules", "--class", "etf", "--save", stdout=out)
        text = out.getvalue()
        self.assertIn("data: 2 bar(s) dropped on ZEROETF · SPLITETF left "
                      "out: broken from", text)
        rows = list(ProvingVerdict.objects.all())
        self.assertEqual(len(rows), len(F.live_rule_cases()))
        for v in rows:
            self.assertNotEqual(v.verdict, "proven", v.live_rule)
            self.assertEqual(v.symbols_n, 2)
            if v.expectancy is not None:
                self.assertLess(abs(v.expectancy), 1.0, v.live_rule)
                self.assertLess(v.payoff or 0, 5.0, v.live_rule)
                self.assertLess(v.max_dd_r, 100.0, v.live_rule)
            self.assertEqual(v.detail["data"]["bars_dropped"],
                             {"ZEROETF": 2})
            self.assertEqual(v.detail["data"]["trades_excluded"], {})
        self.assertFalse(ProvingTrade.objects.filter(r__gt=20).exists())
        self.assertFalse(ProvingTrade.objects.filter(r__lt=-20).exists())
        # the saved run says the same on `prove show`
        out = StringIO()
        call_command("prove", "show", stdout=out)
        self.assertIn("data: 2 bar(s) dropped on ZEROETF", out.getvalue())

    def test_prove_data_names_the_broken_series(self):
        out = StringIO()
        call_command("prove", "data", "--class", "etf", stdout=out)
        text = out.getvalue()
        self.assertIn("── etf ─ 2 judged, 0 short, 1 broken", text)
        self.assertIn("SPLITETF     BROKEN: broken from", text)
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
                          "trades_skipped": {"ABC": 2},
                          "trades_excluded": {"XYZ": 38, "ABC": 3},
                          "broken": [["QQQ", "broken from 2026-03-02"]]}),
            "3 bar(s) dropped on XYZ · 2 trade(s) skipped (stop under half "
            "the class floor) on ABC · 41 trade(s) excluded past 20R on XYZ "
            "(38), ABC (3) · QQQ left out: broken from 2026-03-02")
