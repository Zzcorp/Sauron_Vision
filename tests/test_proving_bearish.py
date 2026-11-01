"""The proving ground learns three things for the bearish pack
(2026-10-31): families judged on their own timeframe, families that name
their markets, and context columns read only as published.

What the file pins:
  * live_rule_cases at 4h leaves po3_london out, at 1h lists it, and the
    nightly 1h pass judges it alone under the 4h run's id;
  * the weekly generator's default grid is the families it had before the
    pack (the same candidate count, the same Sidak bar);
  * a class verdict pools only the symbols the family's live rule can
    fire on, names the others, and is not written for a class with none;
  * proof reads po3_london_sweep_short at 1h and every other rule at 4h,
    in newest_verdict and in proven_cases_for alike;
  * the VIX column never reads the bar's own day, the COT column never a
    report before its publication (bigmoney.inputs.cot_public_at: a
    holiday week's Monday release, the 2025 shutdown backlog from
    2026-01-01), and every family is causal with both columns attached.

Run with:  python manage.py test tests.test_proving_bearish
"""
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from backtester.proving import families as F
from backtester.proving import run as R
from tests.test_bearish_mirrors import synth

#: The families the weekly generator searched before the bearish pack.
GENERATOR_FAMILIES = (
    "rsi_divergence", "macd_cross", "ma_cross", "bb_squeeze", "donchian",
    "rsi_reversion", "ema_pullback", "fvg_retest", "sweep_reversal",
    "pool_sweep", "po3", "tsmom", "rsi2_pullback")
BEARISH = ("bull_trap", "po3_london", "range_breakdown", "trend_rally",
           "exhaustion_short", "vix_term_breakdown", "crowded_long")


class TheTimeframeTests(SimpleTestCase):

    def test_po3_london_is_judged_on_one_hour_bars_only(self):
        four = {f.key for f, _d in F.live_rule_cases("4h")}
        one = {f.key for f, _d in F.live_rule_cases("1h")}
        pinned = {f.key for f, _d in F.live_rule_cases("1h", pinned_only=True)}
        self.assertNotIn("po3_london", four)
        self.assertIn("po3_london", one)
        self.assertEqual(pinned, {"po3_london"})
        self.assertEqual({f.key for f, _d in F.live_rule_cases()}, four)

    def test_every_bearish_family_maps_its_short_to_a_born_name(self):
        from signals.rule_birth import BORN_AT_RESEARCH
        for key in BEARISH:
            fam = F.FAMILIES[key]
            self.assertEqual(fam.directions, (F.SHORT,), key)
            self.assertIn(fam.live_rules[F.SHORT], BORN_AT_RESEARCH, key)
            self.assertFalse(fam.in_generate, key)
            self.assertFalse(fam.fires(synth(400, seed=2), F.LONG).any(), key)

    def test_the_rule_reads_its_timeframe_s_verdict(self):
        from backtester.proving.proof import timeframe_for
        self.assertEqual(timeframe_for("po3_london_sweep_short"), "1h")
        for rule in ("golden_cross", "death_cross", "death_cross_evolved_v2",
                     "bull_trap_swing_high", "no_such_rule"):
            self.assertEqual(timeframe_for(rule), "4h", rule)


class TheGeneratorBarTests(SimpleTestCase):

    def test_the_default_grid_is_the_one_before_the_pack(self):
        default = [k for k, f in F.FAMILIES.items() if f.in_generate]
        self.assertEqual(tuple(default), GENERATOR_FAMILIES)
        k = sum(len(F.FAMILIES[f].directions) * len(F.FAMILIES[f].grid)
                * len(F.FILTERS) for f in default)
        self.assertEqual(k, 280)        # main dbfe0a9's grid

    def test_generate_builds_the_default_grid_and_a_named_family(self):
        seen = {}

        def fake_pool(fam, *a, **kw):
            seen.setdefault(fam.key, 0)
            seen[fam.key] += 1
            return [], 0, {}
        data = {"included": [("SYM", synth(900, seed=1), None)],
                "excluded": [], "dropped": {}, "broken": [], "adjusted": {},
                "held": {}, "start": synth(900, seed=1).index[0],
                "end": synth(900, seed=1).index[-1]}
        with patch.object(R, "universe", return_value={"stock": ["SYM"]}), \
                patch.object(R, "load_class", return_value=data), \
                patch.object(R, "_pool", side_effect=fake_pool):
            R.generate(shortlist=0)
            self.assertEqual(set(seen), set(GENERATOR_FAMILIES))
            seen.clear()
            R.generate(families=["bull_trap"], shortlist=0)
            self.assertEqual(set(seen), {"bull_trap"})


def _data(symbols, cls="etf"):
    df = synth(900, seed=3)
    return {"included": [(s, df, None) for s in symbols],
            "excluded": [("THIN", "120 days of 4h history, 540 needed")],
            "dropped": {}, "broken": [], "adjusted": {}, "held": {},
            "start": df.index[0], "end": df.index[-1]}


class TheEligibilityTests(TestCase):

    def test_a_class_verdict_pools_only_the_markets_the_rule_fires_on(self):
        view = R.eligible_view(F.FAMILIES["exhaustion_short"],
                               _data(["SPY", "GLD", "QQQ"]), "etf")
        self.assertEqual([s for s, _df, _l in view["included"]],
                         ["SPY", "QQQ"])
        self.assertIn(("GLD", "not a market exhaustion_short fires on"),
                      view["excluded"])
        self.assertIn(("THIN", "120 days of 4h history, 540 needed"),
                      view["excluded"])

    def test_no_eligible_symbol_writes_no_verdict(self):
        data = _data(["XLE", "ARKK"])
        self.assertIsNone(R.eligible_view(F.FAMILIES["vix_term_breakdown"],
                                          data, "etf"))
        keys = {f.key for f, _d, _v in R.judged_cases(data, "etf")}
        self.assertNotIn("vix_term_breakdown", keys)
        self.assertNotIn("crowded_long", keys)     # no COT report
        self.assertIn("exhaustion_short", keys)
        self.assertIs(R.eligible_view(F.FAMILIES["ma_cross"], data, "etf"),
                      data)

    def test_the_markets_each_family_names(self):
        self.assertTrue(F.FAMILIES["vix_term_breakdown"].is_eligible(
            "SPX500", "index"))
        self.assertTrue(F.FAMILIES["vix_term_breakdown"].is_eligible(
            "SPY", "etf"))
        self.assertFalse(F.FAMILIES["vix_term_breakdown"].is_eligible(
            "AAPL", "stock"))
        self.assertFalse(F.FAMILIES["exhaustion_short"].is_eligible(
            "XAUUSD", "commodity"))
        # gold and silver in EUR or GBP, which posture.classify reads as
        # risk assets, are havens here too
        for cross in ("XAUEUR", "XAUGBP", "XAGEUR"):
            self.assertFalse(F.FAMILIES["exhaustion_short"].is_eligible(
                cross, "commodity"), cross)
        self.assertFalse(F.FAMILIES["exhaustion_short"].is_eligible(
            "EURUSD", "forex"))
        self.assertTrue(F.FAMILIES["exhaustion_short"].is_eligible(
            "WTI", "commodity"))
        self.assertTrue(F.FAMILIES["po3_london"].is_eligible("EURUSD",
                                                             "forex"))
        self.assertFalse(F.FAMILIES["po3_london"].is_eligible("AAPL",
                                                              "stock"))

    def test_the_one_hour_pass_loads_only_what_it_judges(self):
        loaded = []

        def fake_load(syms, timeframe, cls, **kw):
            loaded.append((cls, list(syms), timeframe))
            return {"included": [], "excluded": [
                (s, "300 days of 1h history, 365 needed") for s in syms],
                "dropped": {},
                    "broken": [], "adjusted": {}, "held": {}, "start": None,
                    "end": None}
        with patch.object(R, "universe", return_value={
                "forex": ["EURUSD"], "stock": ["AAPL"], "etf": ["SPY"]}), \
                patch.object(R, "load_class", side_effect=fake_load):
            rows = R.prove_live_rules(timeframe="1h", pinned_only=True,
                                      run_id="rules-night")
        self.assertEqual(loaded, [("forex", ["EURUSD"], "1h")])
        self.assertEqual({r["live_rule"] for r in rows},
                         {"po3_london_sweep_short"})
        self.assertEqual({r["run_id"] for r in rows}, {"rules-night"})


class TheNightlyTaskTests(TestCase):

    def test_the_night_is_one_run_with_a_one_hour_pass(self):
        from backtester import tasks
        calls = []

        def fake(**kw):
            calls.append(kw)
            return [{"run_id": "rules-abc", "verdict": "insufficient"}] \
                if len(calls) == 1 else []
        # the task's body, under its component gate (core.task_gate)
        body = tasks.run_proving_ground.run.__wrapped__
        with patch("backtester.proving.run.prove_live_rules",
                   side_effect=fake):
            out = body(mode="rules")
        self.assertEqual(out["verdicts"], 1)
        self.assertEqual(calls[0], {"save": True})
        self.assertEqual(calls[1], {"timeframe": "1h", "save": True,
                                    "pinned_only": True,
                                    "run_id": "rules-abc"})


def _verdict(rule, cls, side, verdict, timeframe="4h", family="po3_london"):
    from backtester.models_proving import ProvingVerdict
    return ProvingVerdict.objects.create(
        run_id="rules-test", family=family, live_rule=rule, params={},
        direction=side, filter="none", policy="care", asset_class=cls,
        timeframe=timeframe, generated=False, verdict=verdict, why="test")


class TheProofReadTests(TestCase):

    def test_the_one_hour_rule_reads_its_one_hour_rows(self):
        from backtester.proving import proof
        _verdict("po3_london_sweep_short", "forex", "short", "proven", "1h")
        _verdict("po3_london_sweep_short", "forex", "short", "failed", "4h")
        _verdict("golden_cross", "forex", "long", "proven", "4h",
                 family="ma_cross")
        _verdict("golden_cross", "forex", "long", "failed", "1h",
                 family="ma_cross")
        self.assertEqual(proof.newest_verdict("po3_london_sweep_short",
                                              "forex", "short").verdict,
                         "proven")
        self.assertEqual(proof.newest_verdict("golden_cross", "forex",
                                              "long").verdict, "proven")
        self.assertEqual(proof.proven_cases_for(
            ["po3_london_sweep_short", "golden_cross"]),
            {"po3_london_sweep_short": ["forex short"],
             "golden_cross": ["forex long"]})

    def test_a_new_short_name_reads_its_own_row(self):
        from backtester.proving import proof
        _verdict("death_cross", "stock", "short", "failed", family="ma_cross")
        p = proof.proof_for("death_cross", "stock", "SELL")
        self.assertEqual(p["tier"], proof.FAILED)
        p = proof.proof_for("death_cross", "stock", "BUY")
        self.assertIn("replays death_cross short only", p["words"])


def _fred(series_id, values_by_day):
    from decimal import Decimal

    from market_data.models import MacroIndicator, MacroObservation
    ind, _ = MacroIndicator.objects.get_or_create(
        series_id=series_id, defaults={"name": series_id,
                                       "category": "macro",
                                       "frequency": "daily"})
    for day, value in values_by_day.items():
        MacroObservation.objects.update_or_create(
            indicator=ind, date=day, defaults={"value": Decimal(str(value))})


class TheContextTests(TestCase):

    def _bars(self, days=6):
        end = pd.Timestamp(timezone.now()).floor("4h") - pd.Timedelta(hours=4)
        idx = pd.date_range(end=end, periods=6 * days, freq="4h", tz="UTC")
        return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0,
                             "close": 1.0, "volume": 1.0}, index=idx)

    def test_the_vix_column_never_reads_the_bar_s_own_day(self):
        from backtester.proving import context
        from signals.smc.sessions import new_york_index
        today = date.today()
        days = [today - timedelta(days=k) for k in range(0, 10)]
        # each day's ratio encodes the day: 1 + k/100
        _fred("VIXCLS", {d: 20 * (1 + k / 100) for k, d in enumerate(days)})
        _fred("VXVCLS", {d: 20 for d in days})
        df = context.attach(self._bars(), "SPX500", "index")
        ny = new_york_index(df).date
        read = 0
        for i in range(len(df)):
            when = df["vix_term_date"].iloc[i]
            if pd.isna(when):
                continue
            read += 1
            self.assertLess(pd.Timestamp(when).date(), ny[i])
            self.assertEqual(pd.Timestamp(when).date(),
                             ny[i] - timedelta(days=1))
            k = (today - pd.Timestamp(when).date()).days
            self.assertAlmostEqual(df["vix_term"].iloc[i], 1 + k / 100)
        self.assertGreater(read, 0)

    def test_a_vix_read_older_than_five_days_is_none(self):
        from backtester.proving import context
        old = date.today() - timedelta(days=9)
        _fred("VIXCLS", {old: 25})
        _fred("VXVCLS", {old: 20})
        df = context.attach(self._bars(2), "SPX500", "index")
        self.assertTrue(df["vix_term"].isna().all())

    def test_the_cot_column_waits_for_the_publication(self):
        from backtester.proving import context
        df = self._bars(10)
        days = sorted({ts.date() for ts in df.index})
        tuesday = days[2]
        # the older reports fall, the newest tops the range: before its
        # publication the newest published report is the bottom of its
        # window
        history = [(tuesday - timedelta(days=7 * k), 0.1 * k)
                   for k in range(60, 0, -1)] + [(tuesday, 99.0)]
        col = context.cot_column(df, history)
        public = context.cot_released_at(tuesday)
        self.assertEqual(public.date(), tuesday + timedelta(days=6))
        self.assertEqual((public.hour, public.minute), (21, 0))
        seen = set()
        for i, ts in enumerate(df.index):
            want = 100.0 if ts.to_pydatetime() >= public else 0.0
            self.assertEqual(col[i], want, ts)
            seen.add(want)
        self.assertEqual(seen, {0.0, 100.0})
        # the Friday release and its Saturday read are no longer enough: a
        # holiday week's release moves to the Monday
        saturday = pd.Timestamp(tuesday + timedelta(days=4), tz="UTC")
        self.assertLess(saturday.to_pydatetime(), public)

    def test_the_shutdown_backlog_is_read_once_the_cftc_caught_up(self):
        from backtester.proving import context
        # weekly reports through the 2025 shutdown, the newest topping its
        # window; 4h bars from the shutdown to January
        reports = [date(2025, 9, 30) - timedelta(days=7 * k)
                   for k in range(60, 0, -1)]
        reports += [date(2025, 9, 30) + timedelta(days=7 * k)
                    for k in range(0, 14)]
        history = [(d, float(i)) for i, d in enumerate(reports)]
        idx = pd.date_range("2025-10-01", "2026-01-10", freq="4h", tz="UTC")
        df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0,
                           "close": 1.0, "volume": 1.0}, index=idx)
        col = pd.Series(context.cot_column(df, history), index=idx)
        # the 2025-09-23 report, the last before the backlog, ages past
        # COT_MAX_AGE_DAYS: no column until the backlog is public
        self.assertTrue(col["2025-10-15":"2025-12-31"].isna().all())
        self.assertTrue(col["2026-01-01":"2026-01-04"].notna().all())
        self.assertEqual(context.cot_released_at(date(2025, 10, 14)),
                         context.cot_released_at(date(2025, 12, 23)))

    def test_every_family_is_causal_with_the_columns_attached(self):
        df = synth(1500, seed=3, drift=-0.0005)
        rng = np.random.default_rng(3)
        df["vix_term"] = 0.9 + 0.25 * rng.random(len(df))
        df["cot_spec_index"] = 100 * rng.random(len(df))
        m = len(df) - 60
        for key in BEARISH:
            fam = F.FAMILIES[key]
            whole = fam.fires(df, F.SHORT)
            self.assertTrue(np.array_equal(whole[:m],
                                           fam.fires(df.iloc[:m], F.SHORT)),
                            f"{key} looks ahead")
        hourly = synth(3000, seed=4, freq="1h")
        fam = F.FAMILIES["po3_london"]
        whole = fam.fires(hourly, F.SHORT)
        self.assertTrue(whole.any())
        self.assertTrue(np.array_equal(whole[:2900],
                                       fam.fires(hourly.iloc[:2900], F.SHORT)))

    def test_load_class_attaches_the_columns(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        from decimal import Decimal
        inst = Instrument.objects.create(symbol="CTXI", name="CTXI",
                                         asset_class="index")
        df = synth(3400, seed=2)
        df.index = df.index + (pd.Timestamp(timezone.now()).floor("4h")
                               - pd.Timedelta(hours=4) - df.index[-1])
        PriceData.objects.bulk_create([
            PriceData(instrument=inst, timeframe="4h", timestamp=ts,
                      open=Decimal(str(round(r.open, 6))),
                      high=Decimal(str(round(r.high, 6))),
                      low=Decimal(str(round(r.low, 6))),
                      close=Decimal(str(round(r.close, 6))), volume=1,
                      source="test") for ts, r in df.iterrows()])
        today = date.today()
        _fred("VIXCLS", {today - timedelta(days=k): 22 for k in range(200)})
        _fred("VXVCLS", {today - timedelta(days=k): 20 for k in range(200)})
        data = R.load_class(["CTXI"], "4h", "index")
        [(_sym, got, _l)] = data["included"]
        self.assertIn("vix_term", got.columns)
        self.assertAlmostEqual(float(got["vix_term"].iloc[-1]), 1.1)
        self.assertNotIn("cot_spec_index", got.columns)
