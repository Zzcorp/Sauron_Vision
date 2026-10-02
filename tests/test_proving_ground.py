"""The proving ground (backtester/proving, 2026-10-02): backtests that can
say no.

What the file pins, in order:
  * no family looks ahead — its fires on a prefix of the history are its
    fires on the whole history, bar for bar;
  * the simulator does what the bot does: entry at the NEXT bar's open,
    the ATR stop and target, the round trip charged, a gap through the
    stop filled at the open, stop first on a bar that touches both,
    position care's break-even lock;
  * the judge refuses: too few trades is INSUFFICIENT, a random walk
    FAILS, a trend the trend follower is paid on is PROVEN, and twenty
    candidates tried raise the bar (Sidak);
  * a quarter of history is refused before any verdict;
  * the command and the nightly task write verdicts and nothing else.

Run with:  python manage.py test tests.test_proving_ground
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

import numpy as np
import pandas as pd
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from backtester.proving import data as pdata
from backtester.proving import families as F
from backtester.proving import judge as J
from backtester.proving import simulate as S


def synth(n=3000, seed=1, drift=0.0, start="2023-01-01"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx = pd.date_range(start, periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": 1.0}, index=idx)


def flat(n=30, lo=99.0, hi=101.0):
    """Flat bars: ATR(14) = 2, so a 1.5 ATR stop is 3 under a 100 entry."""
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": 100.0, "high": hi, "low": lo,
                         "close": 100.0, "volume": 1.0}, index=idx)


class NoLookAheadTests(SimpleTestCase):

    def test_every_family_s_fires_on_a_prefix_are_its_fires_on_the_whole(self):
        df = synth(1500, seed=3)
        m = len(df) - 60
        for key, fam in F.FAMILIES.items():
            for d in fam.directions:
                for flt in F.FILTERS:
                    whole = fam.fires(df, d, flt=flt)
                    prefix = fam.fires(df.iloc[:m], d, flt=flt)
                    self.assertTrue(np.array_equal(whole[:m], prefix),
                                    f"{key} {d} {flt} looks ahead")

    def test_the_live_rules_are_mirrored(self):
        cases = {(f.key, d) for f, d in F.live_rule_cases()}
        for key in ("rsi_divergence", "macd_cross", "ma_cross", "bb_squeeze"):
            self.assertIn((key, F.LONG), cases)
            self.assertIn((key, F.SHORT), cases)


class SimulatorTests(SimpleTestCase):

    def _one(self, df, fire_at=20, **kw):
        fires = np.zeros(len(df), dtype=bool)
        fires[fire_at] = True
        return S.simulate(df, fires, F.LONG, asset_class="stock", **kw)

    def test_entry_is_the_next_bar_s_open_and_a_stop_is_minus_one_r(self):
        df = flat()
        df.loc[df.index[21], "open"] = 100.0
        df.loc[df.index[22], "low"] = 96.0          # through the 97 stop
        res = self._one(df, care=False)
        t = res["trades"][0]
        self.assertEqual(t["entry_ts"], df.index[21])
        self.assertEqual(t["entry"], 100.0)
        self.assertEqual(t["exit"], 97.0)
        self.assertEqual(t["reason"], "stop")
        self.assertAlmostEqual(t["gross_r"], -1.0)
        # the stock round trip, 5 bp of 100 against a 3-point risk
        self.assertAlmostEqual(t["cost_r"], 0.0005 * 100 / 3)
        self.assertLess(t["r"], -1.0)

    def test_a_bar_touching_both_is_a_stop(self):
        df = flat()
        df.loc[df.index[22], "low"] = 96.0
        df.loc[df.index[22], "high"] = 110.0
        self.assertEqual(self._one(df, care=False)["trades"][0]["reason"],
                         "stop")

    def test_a_gap_through_the_stop_fills_at_the_open(self):
        df = flat()
        df.loc[df.index[22], ["open", "high", "low", "close"]] = \
            [95.0, 95.5, 94.0, 95.0]
        t = self._one(df, care=False)["trades"][0]
        self.assertEqual(t["reason"], "gap stop")
        self.assertEqual(t["exit"], 95.0)
        self.assertAlmostEqual(t["gross_r"], -5 / 3)

    def test_the_target_is_two_r(self):
        df = flat()
        df.loc[df.index[23], "high"] = 107.0        # past the 106 target
        t = self._one(df, care=False)["trades"][0]
        self.assertEqual(t["reason"], "target")
        self.assertAlmostEqual(t["gross_r"], 2.0)

    def test_care_locks_break_even_after_one_r_and_binds_next_bar(self):
        df = flat()
        df.loc[df.index[22], "high"] = 103.6         # best +1.2R
        df.loc[df.index[23], "open"] = 101.0         # opens above the lock
        df.loc[df.index[23], "low"] = 100.0          # then back to the entry
        t = self._one(df, care=True)["trades"][0]
        self.assertEqual(t["reason"], "breakeven")
        self.assertAlmostEqual(t["exit"], 100.3)     # entry + 0.1R
        self.assertAlmostEqual(t["mfe"], 1.2)

    def test_a_position_open_at_the_end_is_reported_not_counted(self):
        df = flat()
        res = self._one(df, fire_at=27, care=False)
        self.assertEqual(res["trades"], [])
        self.assertIsNotNone(res["open"])


class JudgeTests(SimpleTestCase):

    def test_sidak_raises_the_bar_with_the_candidates(self):
        self.assertAlmostEqual(J.sidak(0.05, 1), 0.05)
        self.assertLess(J.sidak(0.05, 20), 0.003)

    def test_a_random_walk_fails_and_a_trend_is_proven(self):
        rw = synth(3000, seed=11)
        tr = S.simulate(rw, F.FAMILIES["donchian"].fires(rw, F.LONG), F.LONG,
                        asset_class="crypto")["trades"]
        v = J.judge(tr, start=rw.index[0], end=rw.index[-1])
        self.assertIn(v["verdict"], (J.FAILED, J.PROMISING, J.INSUFFICIENT))
        self.assertNotEqual(v["verdict"], J.PROVEN)

        up = synth(4000, seed=7, drift=0.0015)
        tr = S.simulate(up, F.FAMILIES["tsmom"].fires(up, F.LONG, {"n": 500}),
                        F.LONG, asset_class="crypto")["trades"]
        v = J.judge(tr, start=up.index[0], end=up.index[-1])
        self.assertEqual(v["verdict"], J.PROVEN, v["why"])
        self.assertGreater(v["holdout"]["expectancy"], 0)
        self.assertGreater(v["lower_bound"], 0)
        self.assertEqual(v["positive_folds"], 5)
        # the same trades, the best of forty tried: the bound tightens
        v40 = J.judge(tr, start=up.index[0], end=up.index[-1],
                      n_candidates=40)
        self.assertLess(v40["lower_bound"], v["lower_bound"])

    def test_too_few_trades_is_insufficient_never_a_pass(self):
        up = synth(400, seed=2, drift=0.002)
        tr = S.simulate(up, F.FAMILIES["donchian"].fires(up, F.LONG), F.LONG,
                        asset_class="crypto")["trades"]
        v = J.judge(tr, start=up.index[0], end=up.index[-1])
        self.assertEqual(v["verdict"], J.INSUFFICIENT)

    def test_no_data_is_said_as_such(self):
        v = J.judge([], start=pd.Timestamp("2024-01-01", tz="UTC"),
                    end=pd.Timestamp("2024-02-01", tz="UTC"), data_ok=False,
                    data_reason="90 days of 4h history, 540 needed")
        self.assertEqual(v["verdict"], J.INSUFFICIENT)
        self.assertIn("540 needed", v["why"])


class DataTests(SimpleTestCase):

    def test_a_quarter_of_history_is_refused(self):
        v = pdata.sufficiency(synth(540), "4h")     # 90 days
        self.assertFalse(v["ok"])
        self.assertIn("540 needed", v["reason"])

    def test_enough_history_passes_and_holes_are_counted(self):
        df = synth(3400)                            # ~567 days
        self.assertTrue(pdata.sufficiency(df, "4h")["ok"])
        holed = pd.concat([df.iloc[:1000], df.iloc[1100:]])
        v = pdata.sufficiency(holed, "4h")
        self.assertEqual(v["gaps"], 1)


class TheDoorTests(TestCase):
    """The command and the task, on a seeded instrument with enough bars."""

    @classmethod
    def setUpTestData(cls):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst = Instrument.objects.create(symbol="PROVUSD", name="Prov",
                                         asset_class="crypto")
        df = synth(3400, seed=5, drift=0.001)
        PriceData.objects.bulk_create([
            PriceData(instrument=inst, timeframe="4h", timestamp=ts,
                      open=Decimal(str(round(r.open, 4))),
                      high=Decimal(str(round(r.high, 4))),
                      low=Decimal(str(round(r.low, 4))),
                      close=Decimal(str(round(r.close, 4))),
                      volume=1, source="test")
            for ts, r in df.iterrows()], batch_size=1000)
        Instrument.objects.create(symbol="SHORTUSD", name="Short",
                                  asset_class="crypto")
        PriceData.objects.create(
            instrument=Instrument.objects.get(symbol="SHORTUSD"),
            timeframe="4h", timestamp=timezone.now() - timedelta(days=1),
            open=1, high=1, low=1, close=1, volume=1, source="test")

    def test_data_names_the_judged_and_the_short(self):
        out = StringIO()
        call_command("prove", "data", "--class", "crypto", stdout=out)
        text = out.getvalue()
        self.assertIn("PROVUSD", text)
        self.assertIn("SHORT: no history", text)

    def test_rules_judges_every_live_rule_and_saves_on_request(self):
        from backtester.models_proving import ProvingVerdict
        out = StringIO()
        call_command("prove", "rules", "--class", "crypto", stdout=out)
        self.assertEqual(ProvingVerdict.objects.count(), 0)
        text = out.getvalue()
        self.assertIn("rsi_bull_divergence · long", text)
        self.assertIn("rsi_divergence (short mirror) · short", text)
        call_command("prove", "rules", "--class", "crypto", "--save",
                     stdout=StringIO())
        n = ProvingVerdict.objects.count()
        self.assertEqual(n, len(F.live_rule_cases()))
        row = ProvingVerdict.objects.get(live_rule="golden_cross")
        self.assertEqual((row.asset_class, row.symbols_n), ("crypto", 1))
        self.assertIn(row.verdict, dict(ProvingVerdict.VERDICTS))
        out = StringIO()
        call_command("prove", "show", stdout=out)
        self.assertIn(f"{n} verdict(s)", out.getvalue())

    def test_generate_judges_a_shortlist_with_the_grid_s_correction(self):
        from backtester.models_proving import ProvingVerdict
        call_command("prove", "generate", "--class", "crypto",
                     "--families", "tsmom,donchian", "--save",
                     stdout=StringIO())
        rows = list(ProvingVerdict.objects.filter(generated=True))
        self.assertTrue(rows)
        grid = (len(F.FAMILIES["tsmom"].grid) + len(F.FAMILIES["donchian"].grid)) \
            * 2 * len(F.FILTERS)
        self.assertEqual({r.n_candidates for r in rows}, {grid})

    def test_the_task_runs_only_while_its_component_is_on(self):
        from backtester.models_proving import ProvingVerdict
        from backtester.tasks import run_proving_ground
        from core.platform_control import seed_components
        seed_components()
        out = StringIO()
        call_command("component", "on", "platform_master", stdout=out)
        call_command("component", "off", "proving_ground", stdout=out)
        run_proving_ground("rules")
        self.assertEqual(ProvingVerdict.objects.count(), 0)
        call_command("component", "on", "proving_ground", stdout=out)
        res = run_proving_ground("rules")
        self.assertEqual(res["verdicts"], ProvingVerdict.objects.count())
        self.assertGreater(res["verdicts"], 0)
