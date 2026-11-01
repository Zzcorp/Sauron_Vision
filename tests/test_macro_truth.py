"""The macro lane: rules that can read, tasks that report what happened.

Five failures pinned here, all of the same family — code that looked healthy
because it could not fail out loud.

  * `signals/rules/macro_rules.py` and `strategies/templates/macro_regime.py`
    imported `MacroSeries` from market_data.models. There is no such model and
    never has been; the ImportError went into a bare except. The yield-curve
    rule returned None on every call of its life and detect_regime() answered
    the constant "risk_on" — an 80% risk-asset tilt no matter what the curve
    did.
  * `check_economic_calendar` merged the scraper's result INTO a hardcoded
    {"status": "success"}. The scraper's failure paths return an `error` key
    and no status, so a 403 kept the "success" and graded as a warning.
  * `_persist_earnings` counted creates only, while FMP serves the whole
    rolling fortnight every call — so 47 of the day's 48 beats reported
    parsed=hundreds / stored=0, which task_gate grades with its loudest
    warning.
  * The FRED adapter had no not-configured branch: a missing FRED_API_KEY
    returned exactly what a healthy quiet run returns.
  * `_eval_calendar_event` read EconomicEvent with no instrument link, while
    the only writer stamps every US issuer's earnings impact="high" — an
    always-true condition the pattern miner would happily mine.

Run with:  python manage.py test tests.test_macro_truth
"""
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone


def _read(*parts):
    return (Path(settings.BASE_DIR).joinpath(*parts)
            .read_text(encoding="utf-8", errors="replace"))


def _series(series_id, values):
    """A MacroIndicator with observations, newest first in `values`."""
    from market_data.models import MacroIndicator, MacroObservation

    indicator, _ = MacroIndicator.objects.get_or_create(
        series_id=series_id,
        defaults={"name": series_id, "category": "macro", "frequency": "daily"})
    today = date.today()
    for offset, value in enumerate(values):
        MacroObservation.objects.update_or_create(
            indicator=indicator, date=today - timedelta(days=offset),
            defaults={"value": Decimal(str(value))})
    return indicator


def _instrument(symbol, **kw):
    from instruments.models import Instrument
    defaults = {"name": symbol, "asset_class": "stock"}
    defaults.update(kw)
    inst, _ = Instrument.objects.get_or_create(symbol=symbol, defaults=defaults)
    return inst


# ───────────────────────────── the dead model ─────────────────────────────

class MacroSeriesIsGoneTests(TestCase):
    def test_the_model_the_old_code_imported_really_does_not_exist(self):
        """The premise. If someone ever adds a MacroSeries model, the reads
        below are still correct but this file's story stops being true."""
        from market_data import models
        self.assertFalse(hasattr(models, "MacroSeries"))

    def test_no_macro_reader_still_queries_it(self):
        """The name survives in both files' comments, explaining what went
        wrong. What must not survive is a read against it."""
        for parts in (("signals", "rules", "macro_rules.py"),
                      ("strategies", "templates", "macro_regime.py")):
            with self.subTest(module="/".join(parts)):
                source = _read(*parts)
                self.assertNotIn("import MacroSeries", source)
                self.assertNotIn("MacroSeries.objects", source)


def _bars(n=60):
    """Closed 4h bars (ATR 2 on a 100 close) for the rule's levels."""
    import pandas as pd
    idx = pd.date_range("2026-01-05", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                         "close": 100.0, "volume": 1.0}, index=idx)


def _dated_series(series_id, values_by_offset):
    """Observations at today - offset days."""
    from market_data.models import MacroIndicator, MacroObservation
    indicator, _ = MacroIndicator.objects.get_or_create(
        series_id=series_id,
        defaults={"name": series_id, "category": "macro", "frequency": "daily"})
    for offset, value in values_by_offset.items():
        MacroObservation.objects.update_or_create(
            indicator=indicator, date=date.today() - timedelta(days=offset),
            defaults={"value": Decimal(str(value))})


class YieldCurveRuleTests(TestCase):
    """The rule now reads MacroObservation, so it can actually fire — on the
    dates both legs share, while they are fresh, and only on what an
    un-inversion argues (2026-10-31)."""

    def _rule(self):
        from signals.rules.macro_rules import YieldCurveInversionRule
        return YieldCurveInversionRule()

    def _flip(self):
        """Yesterday 2s10s was -0.30, today it is +0.10."""
        _series("DGS10", [4.20, 4.00])
        _series("DGS2", [4.10, 4.30])

    def _eval(self, symbol, asset_class, bars=True):
        with patch("signals.smc.dataframe.load_ohlcv",
                   return_value=_bars() if bars else None):
            return self._rule().evaluate(_instrument(symbol,
                                                     asset_class=asset_class))

    def test_the_rule_can_read_an_observation(self):
        _series("DGS10", [4.20, 4.00])
        _series("DGS2", [4.10, 4.30])
        self.assertEqual(self._rule()._last_values("DGS10", n=2),
                         [Decimal("4.200000"), Decimal("4.000000")])

    def test_an_un_inversion_fires_the_signal(self):
        """This is the entire point of the rule and it had never once
        produced a dict — and now it is graded: an entry, a stop above it
        and a target under it, 2R."""
        self._flip()
        out = self._eval("SPY", "etf")
        self.assertIsNotNone(out, "the yield-curve rule is still inert")
        self.assertEqual(out["rule"], "yield_curve_inversion_flip")
        self.assertEqual(out["direction"], "SHORT")
        self.assertIn("SPY", out["symbol"])
        self.assertEqual(out["entry"], 100.0)
        self.assertAlmostEqual(out["stop"], 103.0)
        self.assertAlmostEqual(out["target"], 94.0)
        self.assertIn("flipped from -0.30 to +0.10 (paired on "
                      f"{date.today():%Y-%m-%d})", out["thesis"])

    def test_it_shorts_what_the_inversion_argues(self):
        self._flip()
        for symbol, cls in (("USDJPY", "forex"), ("AUDJPY", "forex"),
                            ("USDCHF", "forex"), ("AUDUSD", "forex"),
                            ("QQQ", "etf"), ("SPX500", "index"),
                            ("AAPL", "stock"), ("BTCUSD", "crypto"),
                            ("WTIUSD", "commodity"), ("HGUSD", "commodity")):
            with self.subTest(symbol=symbol):
                self.assertIsNotNone(self._eval(symbol, cls))

    def test_it_never_shorts_a_haven_nor_what_the_flip_does_not_argue(self):
        self._flip()
        for symbol, cls in (("XAUUSD", "commodity"), ("XAUEUR", "commodity"),
                            ("XAGUSD", "commodity"), ("GLD", "etf"),
                            ("TLT", "etf"), ("DXY", "index"),
                            ("USDCAD", "forex"), ("EURUSD", "forex"),
                            ("GBPUSD", "forex"), ("EURGBP", "forex"),
                            ("WHEATUSD", "commodity"),
                            ("COFFEEUSD", "commodity")):
            with self.subTest(symbol=symbol):
                self.assertIsNone(self._eval(symbol, cls))

    def test_short_havens_on_the_row_lets_a_haven_through(self):
        from signals.models import RuleControl
        self._flip()
        RuleControl.objects.create(rule_name="yield_curve_inversion_flip",
                                   promotion_stage="paper",
                                   parameters={"short_havens": True})
        self.assertIsNotNone(self._eval("GLD", "etf"))
        self.assertIsNone(self._eval("EURUSD", "forex"))

    def test_a_curve_that_did_not_cross_stays_quiet(self):
        _series("DGS10", [4.50, 4.40])
        _series("DGS2", [4.10, 4.00])
        self.assertIsNone(self._eval("QQQ", "etf"))

    def test_no_history_is_silence_not_a_crash(self):
        self.assertIsNone(self._eval("IWM", "etf"))

    def test_the_slope_is_read_on_the_dates_both_legs_share(self):
        """DGS10 today and yesterday, DGS2 yesterday and the day before:
        the old read mixed the days into a flip (+0.10 against -0.30); on
        the common dates the curve stayed under zero."""
        _dated_series("DGS10", {0: 4.20, 1: 4.00, 2: 4.00})
        _dated_series("DGS2", {1: 4.10, 2: 4.30})
        ten = [float(v) for v in self._rule()._last_values("DGS10", n=2)]
        two = [float(v) for v in self._rule()._last_values("DGS2", n=2)]
        self.assertTrue(ten[1] - two[1] < 0 <= ten[0] - two[0],
                        "the unpaired read would have flipped")
        self.assertIsNone(self._eval("SPY", "etf"))

    def test_a_dead_feed_does_not_keep_the_last_flip_true(self):
        _dated_series("DGS10", {10: 4.20, 11: 4.00})
        _dated_series("DGS2", {10: 4.10, 11: 4.30})
        self.assertIsNone(self._eval("SPY", "etf"))

    def test_no_bars_no_levels_no_signal(self):
        self._flip()
        self.assertIsNone(self._eval("SPY", "etf", bars=False))

    def test_the_levels_read_the_bars_the_proving_ground_reads(self):
        """An unadjusted 2:1 split six bars back: the raw ATR carries the
        100-point gap and would push the stop to the top of the class's
        band; the bar sanity adjusts the earlier bars, so the stop is the
        1.5 ATR of the market the judge reads (3 on a 100 close)."""
        self._flip()
        bars = _bars()
        for col in ("open", "high", "low", "close"):
            bars.iloc[:-6, bars.columns.get_loc(col)] *= 2.0
        with patch("signals.smc.dataframe.load_ohlcv", return_value=bars):
            out = self._rule().evaluate(_instrument("SPY", asset_class="etf"))
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out["stop"], 103.0)
        self.assertAlmostEqual(out["target"], 94.0)

    def test_one_flip_one_short_per_symbol(self):
        from signals.models import Signal
        from signals.rule_scope import cooldown_hours
        from signals.tasks import _create_signals_and_notify
        self._flip()
        self.assertEqual(cooldown_hours("yield_curve_inversion_flip"), 720.0)
        first = self._eval("SPY", "etf")
        with patch("signals.announce.announce_new_signal"):
            self.assertEqual(_create_signals_and_notify([first]), 1)
        sig = Signal.objects.get(rule_name="yield_curve_inversion_flip")
        Signal.objects.filter(pk=sig.pk).update(
            is_active=False, outcome="hit_target",
            expired_at=timezone.now() - timedelta(hours=100))
        with patch("signals.announce.announce_new_signal"):
            self.assertEqual(_create_signals_and_notify([self._eval(
                "SPY", "etf")]), 0)
        self.assertEqual(Signal.objects.filter(
            rule_name="yield_curve_inversion_flip").count(), 1)


FLIP = "yield_curve_inversion_flip"


def _graded(rule, n, *, r=2.0, paired_on="2026-10-20", cls="stock",
            start=0):
    """`n` closed, graded shorts of `rule` on n instruments, all from the
    flip paired on `paired_on`."""
    from signals.models import Signal
    hit = "hit_target" if r > 0 else "stopped_out"
    for i in range(start, start + n):
        Signal.objects.create(
            instrument=_instrument(f"YC{i:03d}", asset_class=cls),
            signal_type="macro", direction="bearish", urgency="medium",
            title="MACRO · 2s10s yield curve un-inverted", description="",
            rule_name=rule, score=0.6,
            sub_scores={"paired_on": paired_on} if paired_on else {},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("103"), suggested_target=Decimal("94"),
            is_active=False, outcome=hit, realized_r=r,
            expired_at=timezone.now() - timedelta(days=1))


class OneFlipIsOneObservationTests(TestCase):
    """The fix grades the flip's shorts (entry, stop, target), and one
    un-inversion shorts every instrument it argues at once: its record
    counts flips, not signals (promotion_pipeline.EVENT_KEYED_RULES), so one
    flip neither proves the rule to full size nor bars it nor weighs it."""

    def test_one_flip_of_twenty_five_shorts_is_one_observation(self):
        from signals.promotion_pipeline import _stats_since
        _graded(FLIP, 25)
        s = _stats_since(FLIP)
        self.assertEqual((s["n"], s["signals"]), (1, 25))
        self.assertAlmostEqual(s["expectancy"], 2.0)
        self.assertEqual(s["hit_rate"], 1.0)

    def test_one_flip_does_not_prove_the_rule_to_full_size(self):
        from backtester.proving import proof
        _graded(FLIP, 25)
        p = proof.proof_for(FLIP, "stock", "SELL")
        self.assertEqual(p["tier"], proof.UNPROVEN)
        self.assertEqual(p["multiplier"], proof.REDUCED)
        self.assertIn("1 flip over 25 graded signals", p["words"])
        self.assertIn("proof needs 20 flips at +0.10R", p["words"])
        # any other rule's 25 graded signals still prove it, as before
        _graded("not_an_event_rule", 25, start=100)
        q = proof.proof_for("not_an_event_rule", "stock", "SELL")
        self.assertEqual(q["tier"], proof.LIVE_PROVEN)
        self.assertIn("25 graded signals all time", q["words"])

    def test_twenty_flips_can_prove_it(self):
        from backtester.proving import proof
        for k in range(20):
            _graded(FLIP, 2, r=1.0, paired_on=f"2006-{k % 12 + 1:02d}-01"
                    if k < 12 else f"2019-{k - 11:02d}-01", start=2 * k)
        p = proof.proof_for(FLIP, "stock", "SELL")
        self.assertEqual(p["tier"], proof.LIVE_PROVEN)
        self.assertIn("20 flips over 40 graded signals", p["words"])

    def test_one_losing_flip_is_no_measured_loser(self):
        from signals.promotion_pipeline import (is_due_for_demotion,
                                                measured_loser)
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name=FLIP, promotion_stage="live_full")
        _graded(FLIP, 25, r=-1.0)
        self.assertEqual(measured_loser(FLIP), "")
        self.assertIsNone(is_due_for_demotion(FLIP))
        _graded("not_an_event_rule", 25, r=-1.0, start=100)
        self.assertIn("25 graded signals all time",
                      measured_loser("not_an_event_rule"))

    def test_one_flip_climbs_no_rung(self):
        from signals.models import RuleControl
        from signals.promotion_pipeline import is_eligible_for_promotion
        RuleControl.objects.create(rule_name=FLIP, promotion_stage="research")
        _graded(FLIP, 40)
        self.assertIsNone(is_eligible_for_promotion(FLIP))

    def test_one_flip_does_not_weigh_its_votes(self):
        from bot_program.asset_engine.aggregation import rule_weight
        from bot_program.bot_grading import VENUE_LIVE
        from signals.performance import calculate_signal_stats
        _graded(FLIP, 25)
        stats = calculate_signal_stats(days=180, group_by="rule_name")
        self.assertEqual(stats[FLIP]["n_closed"], 25)
        self.assertEqual(rule_weight(FLIP, "stock", signal_stats=stats,
                                     venue=VENUE_LIVE), 1.0)
        # ten flips at +2R: the lane weighs it, as any rule's ten signals
        for k in range(1, 10):
            _graded(FLIP, 1, paired_on=f"2010-{k:02d}-01", start=100 + k)
        stats = calculate_signal_stats(days=180, group_by="rule_name")
        self.assertEqual(rule_weight(FLIP, "stock", signal_stats=stats,
                                     venue=VENUE_LIVE), 1.5)

    def test_one_flip_states_no_expected_r_on_the_capital_desk(self):
        from bot_program.capital_desk import DESK_MIN_N, _signal_rs, _stats
        cutoff = timezone.now() - timedelta(days=180)
        _graded(FLIP, 25)
        rs = _signal_rs(rule=FLIP, cutoff=cutoff)
        self.assertEqual(rs, [2.0])
        self.assertLess(_stats(rs)["n"] if _stats(rs) else 0, DESK_MIN_N)
        _graded("not_an_event_rule", 25, start=100)
        self.assertEqual(len(_signal_rs(rule="not_an_event_rule",
                                        cutoff=cutoff)), 25)

    def test_the_provenance_counts_flips_on_a_page_s_own_map(self):
        from signals.models import PromotionEvent, RuleControl
        from signals.promotion_pipeline import provenance_notes
        RuleControl.objects.create(rule_name=FLIP, promotion_stage="live_full")
        PromotionEvent.objects.create(
            rule_name=FLIP, from_stage="paper", to_stage="live_full",
            reason="manual_promote", n_at_transition=0)
        _graded(FLIP, 25)
        # the page's map counts signals (bot_program.evidence.rule_rows)
        page = {FLIP: {"n": 25, "expectancy": 2.0, "hit_rate": 1.0}}
        self.assertEqual(provenance_notes([FLIP], stats=page)[FLIP],
                         "by hand, unproven")
        self.assertEqual(provenance_notes([FLIP])[FLIP], "by hand, unproven")


class RegimeDetectionTests(TestCase):
    def test_an_inverted_curve_is_not_reported_as_risk_on(self):
        from strategies.templates.macro_regime import detect_regime
        _series("DGS10", [3.80])
        _series("DGS2", [4.30])
        self.assertEqual(detect_regime(), "late_cycle")

    def test_a_deep_inversion_with_a_screaming_vix_is_a_recession_call(self):
        from strategies.templates.macro_regime import detect_regime, regime_allocation
        _series("DGS10", [3.50])
        _series("DGS2", [4.50])
        _series("VIXCLS", [31.0])
        self.assertEqual(detect_regime(), "recession")
        self.assertEqual(regime_allocation()["allocation"]["risk_assets"], 0.1)

    def test_an_empty_database_still_answers_risk_on(self):
        """A fresh install has no FRED history. That is a data gap, and the
        default has to stay a default rather than becoming a crash."""
        from strategies.templates.macro_regime import detect_regime
        self.assertEqual(detect_regime(), "risk_on")


# ────────────────────────── the calendar task ─────────────────────────────

class CalendarTaskStatusTests(TestCase):
    def setUp(self):
        from core.platform_control import PlatformComponent
        for key, category in (("platform_master", "system"),
                              ("scraper_calendar", "scraper")):
            PlatformComponent.objects.update_or_create(
                key=key, defaults={"name": key, "category": category,
                                   "is_enabled": True})

    def _run(self, scraper_result, macro_result=None):
        """Both halves, because the task now fetches both.

        Leaving the macro half unmocked let a real, keyless call decide the
        verdict of a test about the earnings contract — the task would
        report `warning` for a reason the test never mentioned.
        """
        from scraping.tasks import check_economic_calendar
        with patch("scraping.scrapers.earnings_calendar."
                   "fetch_earnings_calendar_fmp",
                   return_value=scraper_result), \
                patch("scraping.scrapers.macro_calendar."
                      "fetch_macro_calendar",
                      return_value=macro_result or {"parsed": 3, "stored": 3}):
            return check_economic_calendar()

    def test_a_macro_failure_is_not_averaged_away_by_a_good_earnings_run(self):
        """The macro half failing still leaves every forex position's
        event-risk check blind, so it must not vanish into a green run."""
        out = self._run({"parsed": 12, "stored": 12},
                        macro_result={"parsed": 0, "stored": 0,
                                      "error": "403 Forbidden"})
        self.assertEqual(out["status"], "error")
        self.assertIn("macro", out["error"])

    def test_a_macro_skip_is_reported_too(self):
        out = self._run({"parsed": 12, "stored": 12},
                        macro_result={"parsed": 0, "stored": 0,
                                      "skipped": "no_api_key"})
        self.assertEqual(out["status"], "warning")

    def test_the_macro_counts_travel_with_the_result(self):
        out = self._run({"parsed": 12, "stored": 12},
                        macro_result={"parsed": 5, "stored": 4})
        self.assertEqual(out["macro_parsed"], 5)
        self.assertEqual(out["macro_stored"], 4)

    def test_a_scraper_error_grades_as_an_error_not_a_warning(self):
        from core.task_gate import judge_result
        out = self._run({"parsed": 0, "stored": 0, "error": "403 Forbidden"})
        self.assertEqual(out["status"], "error")
        status, message = judge_result(out)
        self.assertEqual(status, "error")
        self.assertIn("403", message)

    def test_the_component_records_that_error(self):
        from core.platform_control import PlatformComponent
        self._run({"parsed": 0, "stored": 0, "error": "timed out"})
        comp = PlatformComponent.objects.get(key="scraper_calendar")
        self.assertEqual(comp.last_status, "error")
        self.assertEqual(comp.error_count, 1)

    def test_a_working_run_is_still_a_success(self):
        from core.task_gate import judge_result
        out = self._run({"parsed": 12, "stored": 12})
        self.assertEqual(out["status"], "success")
        self.assertEqual(judge_result(out)[0], "success")

    def test_a_missing_key_still_reads_as_not_configured(self):
        from core.task_gate import judge_result
        out = self._run({"parsed": 0, "stored": 0, "skipped": "no_api_key"})
        status, message = judge_result(out)
        self.assertEqual(status, "warning")
        self.assertIn("not configured", message)


class EarningsUpsertCountTests(TestCase):
    """FMP returns the whole rolling window on every call, 48 times a day."""

    ROWS = [{"symbol": "AAPL", "date": "2026-09-01", "time": "amc"},
            {"symbol": "MSFT", "date": "2026-09-02", "time": "bmo"}]

    def test_a_re_asserted_row_counts_as_done(self):
        from scraping.scrapers.earnings_calendar import _persist_earnings
        self.assertEqual(_persist_earnings(self.ROWS), 2)
        self.assertEqual(_persist_earnings(self.ROWS), 2,
                         "re-asserting an unchanged row still reports zero stored")

    def test_the_second_run_of_the_day_is_not_graded_as_a_warning(self):
        """parsed=N / stored=0 is judge_result's loudest warning, and it is
        reserved for 'the source answered and we kept nothing'. A window we
        already hold is not that."""
        from core.task_gate import judge_result
        from scraping.scrapers.earnings_calendar import _persist_earnings
        _persist_earnings(self.ROWS)
        second = {"parsed": len(self.ROWS), "stored": _persist_earnings(self.ROWS)}
        self.assertEqual(judge_result(second)[0], "success")

    def test_an_upsert_does_not_duplicate_the_row(self):
        from market_data.models import EconomicEvent
        from scraping.scrapers.earnings_calendar import _persist_earnings
        _persist_earnings(self.ROWS)
        _persist_earnings(self.ROWS)
        self.assertEqual(EconomicEvent.objects.filter(source="fmp").count(), 2)

    def test_a_junk_row_is_still_not_counted(self):
        from scraping.scrapers.earnings_calendar import _persist_earnings
        self.assertEqual(_persist_earnings([{"symbol": "X", "date": "soon"}]), 0)


# ───────────────────────────────── FRED ───────────────────────────────────

class FredNotConfiguredTests(TestCase):
    def setUp(self):
        from core.platform_control import PlatformComponent
        for key, category in (("platform_master", "system"),
                              ("scraper_fred", "scraper")):
            PlatformComponent.objects.update_or_create(
                key=key, defaults={"name": key, "category": category,
                                   "is_enabled": True})

    def test_the_adapter_says_why_it_did_nothing(self):
        from market_data.adapters.fred_adapter import save_series_to_db
        with patch.dict(os.environ, {"FRED_API_KEY": ""}, clear=False):
            out = save_series_to_db("DGS10")
        self.assertEqual(out["skipped"], "no_api_key")
        self.assertEqual(out["observations_saved"], 0)

    def test_the_task_carries_the_marker_up_to_the_gate(self):
        from core.task_gate import judge_result
        from market_data.tasks import fetch_fred_updates
        with patch.dict(os.environ, {"FRED_API_KEY": ""}, clear=False):
            out = fetch_fred_updates()
        self.assertEqual(out["skipped"], "no_api_key")
        status, message = judge_result(out)
        self.assertEqual(status, "warning")
        self.assertIn("no_api_key", message)

    def test_the_key_is_read_per_call_not_frozen_at_import(self):
        """It was a module-level constant, so a key added to the environment
        after the worker booted never took effect."""
        from market_data.adapters import fred_adapter
        with patch.dict(os.environ, {"FRED_API_KEY": "later"}, clear=False):
            self.assertEqual(fred_adapter._api_key(), "later")


class FredQuietRunTests(TestCase):
    """These series are monthly or daily and the beat is four-hourly: on most
    runs FRED serves nothing this database does not already hold."""

    OBS = [{"date": "2026-08-03", "value": Decimal("4.2")},
           {"date": "2026-08-04", "value": Decimal("4.3")}]

    def test_observations_seen_are_reported_as_parsed(self):
        from market_data.adapters import fred_adapter
        with patch.dict(os.environ, {"FRED_API_KEY": "k"}, clear=False), \
                patch.object(fred_adapter, "fetch_series_info", return_value=None), \
                patch.object(fred_adapter, "fetch_series", return_value=self.OBS):
            first = fred_adapter.save_series_to_db("DGS10")
            second = fred_adapter.save_series_to_db("DGS10")
        self.assertEqual((first["parsed"], first["created"]), (2, 2))
        self.assertEqual((second["parsed"], second["created"]), (2, 0),
                         "the second run re-created rows it already held")
        self.assertEqual(second["observations_saved"], 2,
                         "a re-asserted observation is not counted as done")

    def test_a_run_that_wrote_nothing_new_is_not_a_warning(self):
        """parsed=N / done=0 is judge_result's loudest verdict and belongs to
        'the source answered and we kept none of it'. A four-hourly beat over
        monthly series is not that."""
        from core.task_gate import judge_result
        from market_data.adapters import fred_adapter
        with patch.dict(os.environ, {"FRED_API_KEY": "k"}, clear=False),                 patch.object(fred_adapter, "fetch_series_info", return_value=None),                 patch.object(fred_adapter, "fetch_series", return_value=self.OBS):
            fred_adapter.save_series_to_db("DGS10")
            quiet = fred_adapter.save_series_to_db("DGS10")
        self.assertEqual(judge_result({"status": "success", **quiet})[0], "success")

    def test_a_revised_figure_replaces_the_first_print(self):
        """FRED restates CPI, GDP and payrolls for months. get_or_create keeps
        whichever number arrived first, so a regime read would have been made
        against a figure the source itself had retracted."""
        from market_data.adapters import fred_adapter
        from market_data.models import MacroObservation
        revised = [dict(self.OBS[0]), {**self.OBS[1], "value": Decimal("9.9")}]
        with patch.dict(os.environ, {"FRED_API_KEY": "k"}, clear=False),                 patch.object(fred_adapter, "fetch_series_info", return_value=None),                 patch.object(fred_adapter, "fetch_series", return_value=self.OBS):
            fred_adapter.save_series_to_db("CPIAUCSL")
        with patch.dict(os.environ, {"FRED_API_KEY": "k"}, clear=False),                 patch.object(fred_adapter, "fetch_series_info", return_value=None),                 patch.object(fred_adapter, "fetch_series", return_value=revised):
            out = fred_adapter.save_series_to_db("CPIAUCSL")
        self.assertEqual(out["revised"], 1)
        row = MacroObservation.objects.get(indicator__series_id="CPIAUCSL",
                                           date=date(2026, 8, 4))
        self.assertEqual(row.value, Decimal("9.9"))


class FredQueueRouteTests(TestCase):
    def _route(self, task_name):
        """What Celery itself would resolve, not what the dict looks like —
        an exact key and a glob both match here, and only MapRoute knows
        which wins."""
        from celery.app.routes import MapRoute
        from config.celery import app
        return (MapRoute(app.conf.task_routes)(task_name) or {}).get("queue")

    def test_the_cold_fred_run_does_not_share_the_quote_poller_queue(self):
        """Twelve series x 500 observations in front of the 60-second quote
        poller is how the headband goes stale."""
        self.assertEqual(self._route("market_data.tasks.fetch_fred_updates"),
                         "slow")

    def test_the_quote_poller_is_still_on_the_fast_queue(self):
        self.assertEqual(self._route("market_data.tasks.fetch_live_quotes"),
                         "fast")


# ────────────────────── the calendar-event condition ──────────────────────

class CalendarEventInstrumentLinkTests(TestCase):
    """Every US issuer's print is written impact='high'. Unlinked, the
    condition 'a high-impact event happened in the last 3 days' is TRUE for
    every instrument on nearly every day of earnings season — and
    signals/pattern_miner.py mines that feature into setups people approve."""

    def _event(self, title, **kw):
        from market_data.models import EconomicEvent
        defaults = {"country": "US", "impact": "high", "source": "fmp",
                    "datetime": timezone.now() - timedelta(days=1)}
        defaults.update(kw)
        return EconomicEvent.objects.create(title=title, **defaults)

    def _eval(self, symbol, **params):
        from signals.opportunity_scanner import _eval_calendar_event
        return _eval_calendar_event({"lookback_days": 3, **params},
                                    _instrument(symbol), timezone.now())

    def test_another_companys_earnings_does_not_match_this_instrument(self):
        self._event("AAPL Earnings", currency_affected="AAPL")
        out = self._eval("MSFT", impact="high")
        self.assertFalse(out["matched"],
                         "every instrument still matches every issuer's print")
        self.assertEqual(out["details"]["n"], 0)

    def test_its_own_earnings_still_matches(self):
        self._event("AAPL Earnings", currency_affected="AAPL")
        self.assertTrue(self._eval("AAPL", impact="high")["matched"])

    def test_a_macro_event_still_concerns_everybody(self):
        """FOMC is not issuer-scoped; narrowing it to a symbol would break
        every macro setup on the platform."""
        self._event("FOMC Statement", source="calendar", currency_affected="USD")
        self.assertTrue(self._eval("MSFT", title_contains="FOMC")["matched"])

    def test_a_single_character_symbol_does_not_match_on_the_title(self):
        """'F' is a substring of almost every headline, which would rebuild
        the always-true condition this link exists to remove."""
        self._event("AAPL Earnings", currency_affected="AAPL")
        self.assertFalse(self._eval("F", impact="high")["matched"])

    def test_the_window_still_bounds_the_match(self):
        self._event("AAPL Earnings", currency_affected="AAPL",
                    datetime=timezone.now() - timedelta(days=20))
        self.assertFalse(self._eval("AAPL", impact="high")["matched"])


class TheMacroHalfCanLowerTheGradeTests(TestCase):
    """`judge_result` sums the two halves, so it could not see this.

    `check_economic_calendar` fetches earnings AND macro and returns one
    dict. Its counts reach `core.task_gate.judge_result` as `parsed`/`stored`
    (the earnings half) plus `macro_parsed`/`macro_stored` — and the macro
    pair is in neither WORK_KEYS nor DONE_KEYS, so it was invisible to the
    verdict. Even nested, the sum would hide it: "handled N rows and stored
    none" only fires when the COMBINED done is zero, so an earnings half
    storing normally masks a macro half that kept nothing at all.
    """

    def _run(self, macro):
        from scraping import tasks
        earnings = {"parsed": 10, "stored": 10, "status": "success"}
        with patch("scraping.scrapers.earnings_calendar."
                   "fetch_earnings_calendar_fmp", return_value=earnings), \
             patch("scraping.scrapers.macro_calendar."
                   "fetch_macro_calendar", return_value=macro):
            return tasks.check_economic_calendar.__wrapped__.__wrapped__()

    def test_parsed_rows_that_stored_none_is_a_warning(self):
        out = self._run({"parsed": 200, "stored": 0})
        self.assertEqual(out["status"], "warning")
        self.assertIn("stored none", out["skipped"])

    def test_a_healthy_macro_half_stays_success(self):
        out = self._run({"parsed": 200, "stored": 200})
        self.assertEqual(out["status"], "success")

    def test_a_genuinely_empty_fortnight_is_not_a_warning(self):
        """Parsed nothing and stored nothing is a quiet calendar, not a
        drop — the distinction the whole scraper is built around."""
        out = self._run({"parsed": 0, "stored": 0})
        self.assertEqual(out["status"], "success")

    def test_an_error_still_outranks_it(self):
        out = self._run({"parsed": 200, "stored": 0, "error": "402"})
        self.assertEqual(out["status"], "error")
