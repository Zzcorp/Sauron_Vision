"""COT: does the scraper tell the truth, and is what it stored still true?

Four failures live here, and they share one shape — a COT reader that cannot
tell "no data" from "data that has stopped moving":

  1. `fetch_latest_cot_report` published its stored count through a function
     ATTRIBUTE that was written only on the success path and never reset. A
     Celery prefork child outlives many beats, so a week where every CFTC
     source failed re-reported the previous week's upsert count and
     `task_gate.judge_result` graded a dead scraper "stored N" — a false green
     over a total outage.
  2. `_persist_cot_reports` caught every persistence exception at DEBUG and
     returned 0. A missing migration, a locked database and an integrity
     failure therefore all reached the gate as "ran and produced nothing",
     indistinguishable from a quiet CFTC week and invisible in the logs.
  3. The three COT consumers each took the newest report with `report_date__lte`
     and NO lower bound on freshness. Price keeps moving while positioning
     freezes, so once the scraper stops, `smart_money_divergence` starts
     manufacturing divergences out of nothing but its own downtime.
  4. MARKET_NAME_MAP carried an OATS entry for a contract the legacy
     futures-only report no longer publishes.

Run with:  python manage.py test tests.test_cot_truth
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase
from django.utils import timezone


# Two REAL positional rows in the shape of the live deafut.txt (GOLD and
# WHEAT-SRW), so persistence is exercised through the parser it actually feeds.
DEAFUT_SAMPLE = (
    '"GOLD - COMMODITY EXCHANGE INC.",260811,2026-08-11,088691,CMX ,00,001 ,'
    '  500000,  200000,  100000,   50000,  120000,  180000,  400000,  410000,'
    '   30000,   20000\n'
    '"WHEAT-SRW - CHICAGO BOARD OF TRADE",260811,2026-08-11,001602,CBT ,00,'
    '001 ,  475566,  114979,  139889,  150164,  171852,  149098,  436995,'
    '  439151,   38571,   36415\n'
)


def _instrument(symbol, asset_class="commodity"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_cot(instrument, report_date, nc_long, nc_short):
    from scraping.models import COTReport
    return COTReport.objects.create(
        instrument=instrument, report_date=report_date,
        commercial_long=nc_short, commercial_short=nc_long,
        non_commercial_long=nc_long, non_commercial_short=nc_short,
        open_interest=nc_long + nc_short,
        net_speculative=nc_long - nc_short,
    )


def _seed_prices(instrument, closes, end=None):
    from market_data.models import PriceData
    end = end or timezone.now()
    PriceData.objects.bulk_create([
        PriceData(instrument=instrument, timeframe="1d",
                  timestamp=end - timedelta(days=len(closes) - i),
                  open=Decimal(str(c)), high=Decimal(str(c)),
                  low=Decimal(str(c)), close=Decimal(str(c)),
                  volume=1000, source="test")
        for i, c in enumerate(closes)
    ])


def _run_task():
    """fetch_cot_reports with the gate and the Celery wrapper peeled off."""
    from scraping.tasks import fetch_cot_reports
    fn = fetch_cot_reports
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn()


# ── The stored count belongs to THIS run ───────────────────────────────────

class CotStoredCountTests(TestCase):
    def setUp(self):
        _instrument("XAUUSD")
        _instrument("WHEATUSD")

    def test_a_failed_fetch_reports_zero_not_last_weeks_count(self):
        """The prefork-child failure, replayed: one good week, then a week
        where every source is down, in the same process."""
        from scraping.scrapers import cot_reports

        with patch.object(cot_reports, "_fetch_txt_direct", return_value=DEAFUT_SAMPLE):
            good = _run_task()
        self.assertEqual(good["stored"], 2)

        with patch.object(cot_reports, "_fetch_txt_direct", return_value=None), \
             patch.object(cot_reports, "_fetch_zip", return_value=None):
            dead = _run_task()

        self.assertEqual(dead["parsed"], 0)
        self.assertEqual(dead["stored"], 0,
                         msg="a total outage re-reported the previous run's count")
        self.assertEqual(cot_reports.fetch_latest_cot_report.last_upserted, 0)

    def test_the_gate_grades_a_dead_week_amber(self):
        from core.task_gate import judge_result
        from scraping.scrapers import cot_reports

        with patch.object(cot_reports, "_fetch_txt_direct", return_value=DEAFUT_SAMPLE):
            _run_task()
        with patch.object(cot_reports, "_fetch_txt_direct", return_value=None), \
             patch.object(cot_reports, "_fetch_zip", return_value=None):
            status, message = judge_result(_run_task())

        self.assertEqual(status, "warning")
        self.assertEqual(message, "ran and produced nothing")

    def test_a_healthy_run_still_grades_green(self):
        from core.task_gate import judge_result
        from scraping.scrapers import cot_reports

        with patch.object(cot_reports, "_fetch_txt_direct", return_value=DEAFUT_SAMPLE):
            status, message = judge_result(_run_task())
        self.assertEqual(status, "success")
        self.assertIn("stored 2", message)

    def test_a_mapped_symbol_with_no_instrument_row_is_named(self):
        """Not counted silently, and NOT under the gate's 'skipped' key —
        that word grades a missing credential, and this is a seeding gap."""
        from instruments.models import Instrument
        from scraping.scrapers import cot_reports

        Instrument.objects.filter(symbol="WHEATUSD").delete()
        with patch.object(cot_reports, "_fetch_txt_direct", return_value=DEAFUT_SAMPLE):
            out = _run_task()

        self.assertEqual(out["stored"], 1)
        self.assertEqual(out["missing_instruments"], ["WHEATUSD"])
        self.assertNotIn("skipped", out)


# ── A persistence error is an error ────────────────────────────────────────

class CotPersistenceErrorTests(TestCase):
    def setUp(self):
        _instrument("XAUUSD")
        _instrument("WHEATUSD")

    def test_a_database_error_is_not_swallowed_into_a_silent_zero(self):
        from scraping.models import COTReport
        from scraping.scrapers.cot_reports import (
            _parse_fixed_width_txt, _persist_cot_reports)

        rows = _parse_fixed_width_txt(DEAFUT_SAMPLE)
        with patch.object(COTReport.objects, "update_or_create",
                          side_effect=DatabaseError("no such column")):
            with self.assertLogs("scraping.scrapers.cot_reports", "ERROR") as logs:
                with self.assertRaises(DatabaseError):
                    _persist_cot_reports(rows)
        self.assertTrue(any("Traceback" in line for line in logs.output),
                        msg="the failure has to leave a traceback behind")

    def test_the_task_reports_a_persistence_failure_as_an_error(self):
        from core.task_gate import judge_result
        from scraping.models import COTReport
        from scraping.scrapers import cot_reports

        with patch.object(cot_reports, "_fetch_txt_direct", return_value=DEAFUT_SAMPLE), \
             patch.object(COTReport.objects, "update_or_create",
                          side_effect=DatabaseError("database is locked")):
            out = _run_task()

        self.assertEqual(out["status"], "error")
        self.assertIn("database is locked", out["error"])
        self.assertEqual(judge_result(out)[0], "error")


# ── A stale report scores nothing, and says so ─────────────────────────────

class CotStalenessTests(TestCase):
    """21 days is the ceiling: the CFTC publishes weekly, so three weeks
    absorbs a holiday, a shutdown-delayed release and a slipped beat."""

    def test_a_thirty_day_old_report_scores_nothing_and_says_why(self):
        from signals.opportunity_scanner import _eval_cot_report
        inst = _instrument("STALE1")
        today = timezone.now().date()
        _seed_cot(inst, today - timedelta(days=30), nc_long=150000, nc_short=50000)

        res = _eval_cot_report({"direction": "long_extreme", "min_ratio": 0.25},
                               inst, timezone.now())
        self.assertFalse(res["matched"])
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["details"]["reason"], "COT report stale (30 days)")

    def test_a_five_day_old_report_still_scores(self):
        from signals.opportunity_scanner import _eval_cot_report
        inst = _instrument("FRESH1")
        today = timezone.now().date()
        _seed_cot(inst, today - timedelta(days=5), nc_long=150000, nc_short=50000)

        res = _eval_cot_report({"direction": "long_extreme", "min_ratio": 0.25},
                               inst, timezone.now())
        self.assertTrue(res["matched"], msg=res["details"])
        self.assertEqual(res["details"]["report_date"],
                         str(today - timedelta(days=5)))

    def test_the_boundary_is_inclusive_at_twenty_one_days(self):
        from signals.opportunity_scanner import COT_MAX_AGE_DAYS, latest_fresh_cot_report
        inst = _instrument("EDGE1")
        today = timezone.now().date()
        _seed_cot(inst, today - timedelta(days=COT_MAX_AGE_DAYS),
                  nc_long=150000, nc_short=50000)

        report, reason = latest_fresh_cot_report(inst, timezone.now())
        self.assertIsNotNone(report)
        self.assertIsNone(reason)

    def test_missing_and_stale_are_different_answers(self):
        from signals.opportunity_scanner import latest_fresh_cot_report
        inst = _instrument("EMPTY1")
        self.assertEqual(latest_fresh_cot_report(inst, timezone.now())[1],
                         "no COT report")

    def test_staleness_is_measured_against_now_not_the_wall_clock(self):
        """A replay evaluating a date the report WAS fresh on still scores it:
        the bound is an age relative to `now`, not to today."""
        from signals.opportunity_scanner import _eval_cot_report
        inst = _instrument("REPLAY1")
        today = timezone.now().date()
        _seed_cot(inst, today - timedelta(days=30), nc_long=150000, nc_short=50000)

        res = _eval_cot_report({"direction": "long_extreme", "min_ratio": 0.25},
                               inst, timezone.now() - timedelta(days=25))
        self.assertTrue(res["matched"], msg=res["details"])

    def test_smart_money_divergence_refuses_a_stale_report(self):
        """The expensive one: a live price slope against frozen positioning
        invents a divergence that never happened."""
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = _instrument("STALE2")
        today = timezone.now().date()
        # Price rising hard, specs deeply short 40 days ago — the textbook
        # "price up, smart money short" match, if the report were current.
        _seed_prices(inst, [100.0 + i * 0.5 for i in range(40)])
        _seed_cot(inst, today - timedelta(days=40), nc_long=50000, nc_short=150000)

        res = _eval_smart_money_divergence(
            {"slope_lookback": 20, "slope_threshold": 0.0005, "min_ratio": 0.3},
            inst, timezone.now())
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["reason"], "COT report stale (40 days)")

    def test_smart_money_divergence_still_fires_on_a_fresh_report(self):
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = _instrument("FRESH2")
        today = timezone.now().date()
        _seed_prices(inst, [100.0 + i * 0.5 for i in range(40)])
        _seed_cot(inst, today - timedelta(days=5), nc_long=50000, nc_short=150000)

        res = _eval_smart_money_divergence(
            {"slope_lookback": 20, "slope_threshold": 0.0005, "min_ratio": 0.3},
            inst, timezone.now())
        self.assertTrue(res["matched"], msg=res["details"])
        self.assertEqual(res["details"]["direction"], "price_up_smart_short")

    def test_the_mined_feature_refuses_a_stale_report_too(self):
        from signals.pattern_miner import FEATURE_EXTRACTORS
        stale = _instrument("STALE3")
        fresh = _instrument("FRESH3")
        today = timezone.now().date()
        _seed_cot(stale, today - timedelta(days=30), nc_long=150000, nc_short=50000)
        _seed_cot(fresh, today - timedelta(days=5), nc_long=150000, nc_short=50000)

        feat = FEATURE_EXTRACTORS["cot_long_extreme"]
        self.assertFalse(feat(stale, timezone.now()))
        self.assertTrue(feat(fresh, timezone.now()))


# ── The map names contracts the CFTC still publishes ───────────────────────

class CotMarketMapTests(TestCase):
    def test_the_delisted_oats_contract_is_gone(self):
        from scraping.scrapers.cot_reports import (
            MARKET_NAME_MAP, _map_market_to_symbol)
        self.assertNotIn("OATS", MARKET_NAME_MAP)
        self.assertIsNone(_map_market_to_symbol("OATS - CHICAGO BOARD OF TRADE"))
