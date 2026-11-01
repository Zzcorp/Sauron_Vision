"""The bearish context rules (2026-10-31, signals/rules/bearish_rules.py):
risk_off_exhaustion_short, vix_inversion_index_short,
crowded_long_reversal_short and positioning_crowd_reversal_short — each a
price pattern AND a reading beyond the bars, each born at research.

What the file pins, per rule: the frame and the reading on which it fires
(levels, words); every way it stays quiet — the reading against it,
unreadable, stale or not yet published; the markets it may not short; and
parity with its proving-ground family. The crowd gate is its own name
(2026-11-01): the COT gate fires only where a COT report maps the market,
the crowd gate only where none does, and size by proof never reads the
COT gate's class verdict for a crowd-gate short.

Run with:  python manage.py test tests.test_bearish_context_rules
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from backtester.proving import families as F
from tests.test_bearish_mirrors import inst, run, synth
from tests.test_bearish_rules import assert_levels, frame, parity


def recent(rows, freq_hours=4):
    """`rows` as closed 4h bars ending on the newest bar that has closed."""
    now = pd.Timestamp(timezone.now()).tz_convert("UTC")
    last = now.floor(f"{freq_hours}h") - pd.Timedelta(hours=freq_hours)
    start = last - pd.Timedelta(hours=freq_hours * (len(rows) - 1))
    return frame(rows, start=start)


# ── risk_off_exhaustion_short ───────────────────────────────────────────

def exh_rows(flat=None, last=(104.0, 105.0, 103.7, 103.8), rally=True):
    """A down tape from 150 to 100 (ATR about 1), a relief rally of ten
    bars, and a shooting star."""
    rows = []
    for i in range(220):
        c = flat if flat is not None else 150 - 50 * i / 219
        rows.append((c + 0.3, c + 0.5, c - 0.5, c))
    base = rows[-1][3]
    for k in range(1, 11):
        c = base + (0.42 * k if rally else 0.05 * k)
        rows.append((c - 0.3, c + 0.4, c - 0.5, c))
    rows.append(last)
    return rows


RISK_OFF = {"open": True, "why": "the Mind: risk_off at 80%",
            "regime": "risk_off", "regime_confidence": 0.8, "stress": "calm"}
RISK_ON = {"open": False, "why": "", "regime": "risk_on",
           "regime_confidence": 0.9, "stress": "calm"}


class RiskOffExhaustionTests(SimpleTestCase):

    def rule(self):
        from signals.rules.bearish_rules import RiskOffExhaustionShortRule
        return RiskOffExhaustionShortRule()

    def _run(self, rows, symbol="SPY", cls="etf", gate=RISK_OFF):
        with patch("signals.rules.bearish_rules.regime_gate",
                   return_value=gate):
            return run(self.rule(), frame(rows), inst(symbol, cls))

    def test_the_shooting_star_in_risk_off_fires(self):
        out = self._run(exh_rows())
        self.assertIsNotNone(out)
        assert_levels(self, out, "etf", frame(exh_rows()))
        self.assertEqual(out["sub_scores"]["regime"], "risk_off")
        self.assertEqual(out["sub_scores"]["regime_confidence"], 0.8)
        self.assertGreaterEqual(out["sub_scores"]["rally_atr"], 2.5)
        self.assertIn("Risk-off (the Mind: risk_off at 80%)", out["thesis"])
        self.assertIn("not in the proving ground's replay", out["thesis"])

    def test_risk_on_is_quiet(self):
        self.assertIsNone(self._run(exh_rows(), gate=RISK_ON))

    def test_an_unreadable_gate_is_closed(self):
        from signals.rules.bearish_rules import regime_gate
        with patch("brain.context.get_brain_context",
                   side_effect=RuntimeError("down")), \
                patch("bot_program.market_stress.current",
                      side_effect=RuntimeError("down")):
            self.assertFalse(regime_gate()["open"])
        with patch("brain.context.get_brain_context",
                   side_effect=RuntimeError("down")), \
                patch("bot_program.market_stress.current",
                      side_effect=RuntimeError("down")):
            self.assertIsNone(run(self.rule(), frame(exh_rows()),
                                  inst("SPY", "etf")))

    def test_the_gate_reads_the_mind_then_the_stress(self):
        from signals.rules.bearish_rules import regime_gate
        calm = {"level": "calm", "fresh": True, "score": 10}
        with patch("brain.context.get_brain_context",
                   return_value={"regime_label": "risk_off",
                                 "regime_confidence": 0.7}), \
                patch("bot_program.market_stress.current", return_value=calm):
            self.assertTrue(regime_gate()["open"])
        with patch("brain.context.get_brain_context",
                   return_value={"regime_label": "risk_off",
                                 "regime_confidence": 0.5}), \
                patch("bot_program.market_stress.current", return_value=calm):
            self.assertFalse(regime_gate()["open"])
        with patch("brain.context.get_brain_context", return_value=None), \
                patch("bot_program.market_stress.current",
                      return_value={"level": "stressed", "fresh": True,
                                    "score": 55}):
            g = regime_gate()
        self.assertTrue(g["open"])
        self.assertIn("stressed", g["why"])
        with patch("brain.context.get_brain_context", return_value=None), \
                patch("bot_program.market_stress.current",
                      return_value={"level": "crisis", "fresh": False}):
            self.assertFalse(regime_gate()["open"])

    def test_havens_and_forex_are_never_shorted(self):
        for sym, cls in (("XAUUSD", "commodity"), ("GLD", "etf"),
                         ("EURUSD", "forex")):
            self.assertIsNone(self._run(exh_rows(), sym, cls), sym)

    def test_above_the_sma200_is_quiet(self):
        self.assertIsNone(self._run(exh_rows(flat=95.0)))

    def test_a_short_wick_is_quiet(self):
        self.assertIsNone(self._run(exh_rows(
            last=(104.6, 105.0, 103.6, 104.2))))

    def test_a_one_atr_rally_is_quiet(self):
        self.assertIsNone(self._run(exh_rows(
            rally=False, last=(100.6, 101.3, 100.3, 100.4))))

    def test_a_four_atr_wick_puts_the_stop_inside_the_pattern(self):
        self.assertIsNone(self._run(exh_rows(
            last=(104.0, 108.0, 103.7, 103.8))))

    def test_parity_with_the_family(self):
        with patch("signals.rules.bearish_rules.regime_gate",
                   return_value=RISK_OFF):
            fired = parity(self, self.rule(), "exhaustion_short",
                           synth(700, seed=1, drift=-0.002), 300,
                           instrument=inst("SPY", "etf"))
        self.assertGreater(fired, 0)


# ── vix_inversion_index_short ───────────────────────────────────────────

def _fred(series_id, values_by_offset):
    from market_data.models import MacroIndicator, MacroObservation
    ind, _ = MacroIndicator.objects.get_or_create(
        series_id=series_id,
        defaults={"name": series_id, "category": "macro",
                  "frequency": "daily"})
    today = date.today()
    for offset, value in values_by_offset.items():
        MacroObservation.objects.update_or_create(
            indicator=ind, date=today - timedelta(days=offset),
            defaults={"value": Decimal(str(value))})


def vix_curve(ratio, offsets=range(1, 12), vix3m=20.0):
    _fred("VIXCLS", {k: round(vix3m * ratio, 4) for k in offsets})
    _fred("VXVCLS", {k: vix3m for k in offsets})


def index_rows(breakdown_prev=False):
    rows = [(5000.0, 5010.0, 4990.0, 5000.0)] * 40
    if breakdown_prev:
        rows.append((4992.0, 4995.0, 4983.0, 4985.0))
        rows.append((4985.0, 4987.0, 4973.0, 4975.0))
    else:
        rows.append((4992.0, 4995.0, 4978.0, 4980.0))
    return rows


class VixInversionTests(TestCase):

    def rule(self):
        from signals.rules.bearish_rules import VixInversionIndexShortRule
        return VixInversionIndexShortRule()

    def _run(self, rows=None, symbol="SPX500", cls="index"):
        return run(self.rule(), recent(rows or index_rows()),
                   inst(symbol, cls))

    def test_an_inverted_curve_and_a_ten_bar_low_fire(self):
        vix_curve(1.10)
        out = self._run()
        self.assertIsNotNone(out)
        assert_levels(self, out, "index", recent(index_rows()))
        self.assertAlmostEqual(out["sub_scores"]["vix_term"], 1.10)
        self.assertAlmostEqual(out["score"], 0.75)
        self.assertIn("VIX/VIX3M at 1.10 (the term structure inverted, as of "
                      f"{out['sub_scores']['vix_term_date']})", out["thesis"])
        self.assertLess(date.fromisoformat(out["sub_scores"]["vix_term_date"]),
                        date.today())
        self.assertIsNotNone(self._run(symbol="SPY", cls="etf"))

    def test_a_calm_curve_is_quiet(self):
        vix_curve(0.95)
        self.assertIsNone(self._run())

    def test_only_today_inverted_is_not_yet_published_to_the_bar(self):
        vix_curve(0.95)
        vix_curve(1.10, offsets=[0])
        self.assertIsNone(self._run())

    def test_a_curve_eight_days_old_is_stale(self):
        vix_curve(1.10, offsets=range(8, 15))
        self.assertIsNone(self._run())

    def test_no_vix3m_no_fire(self):
        _fred("VIXCLS", {k: 22.0 for k in range(1, 12)})
        self.assertIsNone(self._run())

    def test_the_breakdown_already_happened_is_quiet(self):
        vix_curve(1.10)
        self.assertIsNone(self._run(index_rows(breakdown_prev=True)))

    def test_a_stock_and_a_pair_are_not_shorted_here(self):
        vix_curve(1.10)
        self.assertIsNone(self._run(symbol="AAPL", cls="stock"))
        self.assertIsNone(self._run(symbol="EURUSD", cls="forex"))
        self.assertIsNone(self._run(symbol="GLD", cls="etf"))

    def test_parity_with_the_family(self):
        from backtester.proving import context
        vix_curve(1.05, offsets=range(1, 400))
        df = synth(700, seed=3)
        df.index = df.index + (pd.Timestamp(timezone.now()).floor("4h")
                               - pd.Timedelta(hours=4) - df.index[-1])
        fired = 0
        for m in range(300, 701, 2):
            p = df.iloc[:m]
            got = run(self.rule(), p, inst("SPX500", "index")) is not None
            want = bool(F.FAMILIES["vix_term_breakdown"].fires(
                context.attach(p, "SPX500", "index"), F.SHORT)[-1])
            self.assertEqual(got, want, m)
            fired += got
        self.assertGreater(fired, 0)


# ── crowded_long_reversal_short ─────────────────────────────────────────

def crowd_rows(top_back=10, break_prev=False):
    """A climb to a top `top_back` bars before the last, a swing low after
    it, a small bounce, and the last bar closing under the swing low."""
    rows = [(100 + 0.1 * i, 101 + 0.1 * i, 99 + 0.1 * i, 100 + 0.1 * i)
            for i in range(80)]
    c = rows[-1][3]
    for _ in range(5):
        c += 1.0
        rows.append((c - 1.0, c + 0.5, c - 1.2, c))
    for _ in range(3):
        c -= 0.6
        rows.append((c + 0.6, c + 0.7, c - 0.3, c))
    sl = c - 0.3
    for k in range(top_back - 4):
        rows.append((c, c + 0.5, sl + 0.1 + 0.02 * k, c + 0.2))
    cl = rows[-1][3]
    if break_prev:
        rows[-1] = (c, c + 0.2, sl - 0.5, sl - 0.2)
        cl = sl - 0.2
    rows.append((cl, cl + 0.1, sl - 0.6, sl - 0.3))
    return rows


def cot_rows(symbol, bar_day, *, newest_lag=8, newest_value=2.0,
             n=60, asset_class="commodity", rising=False):
    """Weekly COT reports, the newest `newest_lag` days before `bar_day`
    (8: published, context.cot_released_at, by the last bar's open): the
    older ones falling from 1.0 to 0.5 of the open interest, the newest at
    `newest_value` (2.0 tops the range) — or, `rising`, every report a new
    top of its window."""
    from instruments.models import Instrument
    from scraping.models import COTReport
    inst_row, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    for k in range(n):
        if rising:
            frac = 0.5 + 0.5 * (n - 1 - k) / (n - 1)
        else:
            frac = newest_value if k == 0 else 0.5 + 0.5 * k / (n - 1)
        net = int(1000 * frac)
        COTReport.objects.create(
            instrument=inst_row,
            report_date=bar_day - timedelta(days=newest_lag + 7 * k),
            commercial_long=1000, commercial_short=1000 + net,
            non_commercial_long=1000 + net, non_commercial_short=1000,
            open_interest=1000, net_speculative=net)
    return inst_row


def _bar_day(df):
    return pd.Timestamp(df.index[-1]).tz_convert("UTC").date()


class CrowdedLongTests(TestCase):

    def rule(self):
        from signals.rules.bearish_rules import CrowdedLongReversalShortRule
        return CrowdedLongReversalShortRule()

    def test_speculators_at_the_top_and_the_swing_low_broken_fire(self):
        df = recent(crowd_rows())
        cot_rows("XAUUSD", _bar_day(df))
        out = run(self.rule(), df, inst("XAUUSD", "commodity"))
        self.assertIsNotNone(out)
        assert_levels(self, out, "commodity", df)
        self.assertEqual(out["sub_scores"]["gate"], "cot")
        self.assertEqual(out["sub_scores"]["spec_index"], 100.0)
        self.assertEqual(out["sub_scores"]["report_date"],
                         (_bar_day(df) - timedelta(days=8)).isoformat())
        self.assertIn("Speculators crowded long (COT index 100, report",
                      out["thesis"])

    def test_a_spec_index_of_seventy_is_quiet(self):
        df = recent(crowd_rows())
        # the newest at 70% of the older range (0.5-1.0)
        cot_rows("XAUUSD", _bar_day(df), newest_value=0.85)
        self.assertIsNone(run(self.rule(), df, inst("XAUUSD", "commodity")))

    def test_a_report_thirty_days_old_is_stale(self):
        df = recent(crowd_rows())
        cot_rows("XAUUSD", _bar_day(df), newest_lag=30)
        self.assertIsNone(run(self.rule(), df, inst("XAUUSD", "commodity")))

    def test_a_report_not_yet_released_is_not_read(self):
        df = recent(crowd_rows())
        cot_rows("XAUUSD", _bar_day(df), newest_lag=2)
        self.assertIsNone(run(self.rule(), df, inst("XAUUSD", "commodity")))

    def test_a_report_is_read_from_its_publication_not_its_friday(self):
        # five days old: out on a Friday in an ordinary week, but a holiday
        # week publishes on the Monday — cot_released_at waits for both
        from backtester.proving import context
        df = recent(crowd_rows())
        day = _bar_day(df)
        cot_rows("XAUUSD", day, newest_lag=5)
        self.assertGreater(context.cot_released_at(day - timedelta(days=5)),
                           pd.Timestamp(df.index[-1]).to_pydatetime())
        self.assertIsNone(run(self.rule(), df, inst("XAUUSD", "commodity")))

    def test_a_break_at_the_bar_before_is_quiet(self):
        df = recent(crowd_rows(break_prev=True))
        cot_rows("XAUUSD", _bar_day(df))
        self.assertIsNone(run(self.rule(), df, inst("XAUUSD", "commodity")))

    def test_a_top_forty_bars_back_is_quiet(self):
        df = recent(crowd_rows(top_back=40))
        cot_rows("XAUUSD", _bar_day(df))
        self.assertIsNone(run(self.rule(), df, inst("XAUUSD", "commodity")))

    def test_a_market_no_cot_report_maps_is_not_this_rule_s(self):
        df = recent(crowd_rows())
        funding = {"funding": {"score": 0.8, "words": "funding +0.040% per 8h"}}
        with patch("bot_program.positioning.crowd_read",
                   return_value=_crowd(0.9, funding)) as read:
            self.assertIsNone(run(self.rule(), df, inst("ETHUSD", "crypto")))
        read.assert_not_called()


    def test_the_cot_history_replays_cot_read(self):
        from backtester.proving import context
        from bot_program.smart_money import cot_read, cot_spec_history
        df = recent(crowd_rows())
        day = _bar_day(df)
        cot_rows("XAUUSD", day, newest_value=0.8)
        col = context.cot_column(df, cot_spec_history("XAUUSD"))
        live = cot_read("XAUUSD", "BUY", now=timezone.now())
        self.assertIsNotNone(live["spec_index"])
        self.assertAlmostEqual(col[-1], live["spec_index"], places=1)

    def test_parity_with_the_family(self):
        from backtester.proving import context
        from bot_program.smart_money import cot_spec_history
        df = synth(700, seed=4)
        df.index = df.index + (pd.Timestamp(timezone.now()).floor("4h")
                               - pd.Timedelta(hours=4) - df.index[-1])
        cot_rows("XAUUSD", _bar_day(df), newest_lag=5, n=90, rising=True)
        hist = cot_spec_history("XAUUSD")
        fired = 0
        for m in [m for m in range(200, 701) if m % 3 == 0 or 228 <= m <= 236]:
            p = df.iloc[:m]
            got = run(self.rule(), p, inst("XAUUSD", "commodity")) is not None
            q = p.assign(cot_spec_index=context.cot_column(p, hist))
            want = bool(F.FAMILIES["crowded_long"].fires(q, F.SHORT)[-1])
            self.assertEqual(got, want, m)
            fired += got
        self.assertGreater(fired, 0)


def _crowd(score, components):
    return {"score": score, "label": "crowded", "components": components}


class PositioningCrowdTests(TestCase):
    """The crowd gate under its own name: a market no COT report maps,
    the positioning map's crowd score at CROWDED or more."""

    FUNDING = {"funding": {"score": 0.8, "words": "funding +0.040% per 8h"}}

    def rule(self):
        from signals.rules.bearish_rules import \
            PositioningCrowdReversalShortRule
        return PositioningCrowdReversalShortRule()

    def test_the_crowd_gate_for_a_market_no_cot_report_maps(self):
        from instruments.models import Instrument
        Instrument.objects.create(symbol="ETHUSD", name="ETH",
                                  asset_class="crypto")
        df = recent(crowd_rows())
        with patch("bot_program.positioning.crowd_read",
                   return_value=_crowd(0.6, self.FUNDING)) as read:
            out = run(self.rule(), df, inst("ETHUSD", "crypto"))
        self.assertIsNotNone(out)
        assert_levels(self, out, "crypto", df)
        self.assertEqual(out["rule"], "positioning_crowd_reversal_short")
        self.assertEqual(out["sub_scores"]["gate"], "crowd")
        self.assertEqual(out["sub_scores"]["crowd_score"], 0.6)
        self.assertNotIn("df", read.call_args.kwargs)
        self.assertEqual(len(read.call_args.args), 2)
        self.assertIn("the proving ground does not judge it", out["thesis"])
        with patch("bot_program.positioning.crowd_read",
                   return_value=_crowd(0.4, self.FUNDING)):
            self.assertIsNone(run(self.rule(), df, inst("ETHUSD", "crypto")))
        volume_only = {"volume": {"score": 0.9, "words": "volume"},
                       "cot_speculators": {"score": None, "words": "no COT"}}
        with patch("bot_program.positioning.crowd_read",
                   return_value=_crowd(0.9, volume_only)):
            self.assertIsNone(run(self.rule(), df, inst("ETHUSD", "crypto")))

    def test_a_market_a_cot_report_maps_is_the_cot_gate_s(self):
        df = recent(crowd_rows())
        cot_rows("BTCUSD", _bar_day(df), newest_value=0.85,
                 asset_class="crypto")
        with patch("bot_program.positioning.crowd_read",
                   return_value=_crowd(0.9, self.FUNDING)) as read:
            self.assertIsNone(run(self.rule(), df, inst("BTCUSD", "crypto")))
        read.assert_not_called()

    def test_an_unreadable_cot_map_is_no_crowd_fire(self):
        df = recent(crowd_rows())
        with patch("scraping.models.COTReport.objects.filter",
                   side_effect=RuntimeError("db down")), \
                patch("bot_program.positioning.crowd_read",
                      return_value=_crowd(0.9, self.FUNDING)) as read:
            self.assertIsNone(run(self.rule(), df, inst("ETHUSD", "crypto")))
        read.assert_not_called()

    def test_size_by_proof_never_reads_the_cot_gate_s_verdict(self):
        from backtester.models_proving import ProvingVerdict
        from backtester.proving import proof
        from backtester.proving.run import RULES_RUN_PREFIX
        ProvingVerdict.objects.create(
            run_id=f"{RULES_RUN_PREFIX}t", family="crowded_long",
            live_rule="crowded_long_reversal_short", asset_class="crypto",
            direction="short", timeframe="4h", policy=proof.POLICY,
            filter=proof.FILTER, generated=False, verdict="proven",
            trades_n=60, expectancy=0.4)
        with patch.object(proof, "GATE", True):
            cot = proof.proof_for("crowded_long_reversal_short", "crypto",
                                  "SELL")
            crowd = proof.proof_for("positioning_crowd_reversal_short",
                                    "crypto", "SELL")
        self.assertEqual(cot["tier"], proof.PROVEN)
        self.assertEqual(crowd["tier"], proof.UNPROVEN)
        self.assertEqual(crowd["multiplier"], proof.REDUCED)
        self.assertIn("replays no family for positioning_crowd_reversal_short",
                      crowd["words"])
