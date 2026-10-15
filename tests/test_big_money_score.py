"""The Big Money Board's record: forward measures, the statistics, the
verdicts, the cost line and the calibration calls (spec §2.8, §2.13).

Run with:  python manage.py test tests.test_big_money_score
"""
from datetime import date, timedelta
from datetime import timezone as dt_tz
from types import SimpleNamespace
from unittest import mock
import math

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bigmoney import calendar as bmcal
from bigmoney import score as S
from bigmoney import words as W
from tests.test_big_money_board import (fake_board, fake_cell, seed_closes,
                                        weekdays)

UTC = dt_tz.utc


class FakeStore:
    """A store whose closes are given: {symbol: [(day, close)]}."""

    def __init__(self, series=None, classes=None):
        self._s = series or {}
        self._c = classes or {}

    def series(self, symbol):
        rows = self._s.get(symbol, [])
        return [d for d, _ in rows], [c for _, c in rows], [0] * len(rows)

    def asset_class(self, symbol):
        return self._c.get(symbol, "")


def _cell(**kw):
    base = {"proxy": "SPX500", "horizon_days": 1, "proxy_close": 100.0,
            "claim": "direction", "score": -1.0}
    base.update(kw)
    return SimpleNamespace(**base)


class ForwardMeasureTests(TestCase):

    def test_the_forward_return_and_the_adverse_excursion(self):
        from bigmoney.models import BigMoneyCell
        days = weekdays(date(2026, 9, 1), date(2026, 11, 30))
        closes = {d: 100.0 + i for i, d in enumerate(days)}
        as_of = date(2026, 10, 23)
        dip = days.index(as_of) + 3
        closes[days[dip]] = 90.0                     # a dip on the way
        seed_closes("SPX500", closes)
        board = fake_board(as_of, rows={"us_equities": {"cells": {
            "rebalance": fake_cell("rebalance", "us_equities", score=-1.0),
            "crowding": fake_cell("crowding", "us_equities", score=0.8)}}})
        S.store_board(board)
        self.assertEqual(BigMoneyCell.objects.count(), 2)
        n = S.score_due()
        self.assertEqual(n, 2)
        reb = BigMoneyCell.objects.get(footprint="rebalance")
        c_t = closes[as_of]
        nxt = days[days.index(as_of) + 1]
        self.assertEqual(reb.proxy_close, c_t)
        self.assertAlmostEqual(reb.fwd_return, math.log(closes[nxt] / c_t))
        crowd = BigMoneyCell.objects.get(footprint="crowding")
        self.assertAlmostEqual(crowd.fwd_adverse, 90.0 / c_t - 1.0)
        self.assertEqual(crowd.claim, "tail")

    def test_the_h_th_business_day_across_a_holiday(self):
        cal = bmcal.BusinessCalendar(())
        store = FakeStore({"SPX500": [(date(2026, 11, 25), 100.0),
                                      (date(2026, 11, 27), 101.0)]})
        got = S.measure(_cell(), date(2026, 11, 25), cal, store)
        self.assertAlmostEqual(got["fwd_return"], math.log(1.01))
        self.assertEqual(S.target_date(date(2026, 11, 25), 1, cal, False),
                         date(2026, 11, 27))
        self.assertEqual(S.target_date(date(2026, 11, 25), 1, cal, True),
                         date(2026, 11, 26))

    def test_no_close_past_the_grace_is_unscored(self):
        cal = bmcal.BusinessCalendar(())
        store = FakeStore({"SPX500": [(date(2025, 3, 3), 100.0)]})
        got = S.measure(_cell(), date(2025, 3, 3), cal, store)
        self.assertEqual(got, {"note": "no close on 2025-03-04: unscored"})

    def test_a_cell_not_yet_due_waits(self):
        cal = bmcal.BusinessCalendar(())
        today = timezone.now().date()
        store = FakeStore({"SPX500": [(today, 100.0)]})
        self.assertIsNone(S.measure(_cell(horizon_days=5), today, cal, store))

    def test_an_unscored_row_is_kept_and_left_out_of_the_statistics(self):
        from bigmoney.models import BigMoneyCell
        board = fake_board(date(2025, 3, 3), rows={"us_equities": {"cells": {
            "rebalance": fake_cell("rebalance", "us_equities", score=-1.0)}}})
        S.store_board(board)
        S.score_due()
        cell = BigMoneyCell.objects.get()
        self.assertTrue(cell.score_note.startswith("no close on 2025-03-03"))
        self.assertIsNotNone(cell.scored_at)
        rec = S.record()
        self.assertEqual(rec[0]["stats"]["n"], 0)
        self.assertEqual(rec[0]["stats"]["unscored"], 1)
        self.assertEqual(rec[0]["verdict"], "too few to judge (0 of 40)")


class ClaimCloseTests(TestCase):
    """c_t is the proxy's close ON the as-of day, never an older one
    (review finding 1): a claim graded from a dead tape's last close
    would record the tape's whole gap as the claim's own move."""

    def _fix_board(self, as_of):
        return fake_board(as_of, instruments={"EURUSD": {"fx_fix": fake_cell(
            "fx_fix", "EURUSD", score=-1.0)}})

    def test_a_tape_that_ended_twelve_days_before_is_unscored(self):
        from bigmoney.models import BigMoneyCell
        as_of = date(2026, 9, 28)                          # a Monday
        seed_closes("EURUSD", {d: 1.1359 for d in weekdays(
            date(2026, 8, 3), date(2026, 9, 16))}, asset_class="forex")
        S.store_board(self._fix_board(as_of))
        cell = BigMoneyCell.objects.get(footprint="fx_fix")
        self.assertIsNone(cell.proxy_close)
        self.assertIsNone(cell.proxy_close_date)
        # The tape resumes (a period=5d backfill): the claim is still not
        # graded from the old close.
        seed_closes("EURUSD", {d: 1.20 for d in weekdays(
            date(2026, 9, 29), date(2026, 10, 9))}, asset_class="forex")
        S.score_due()
        cell.refresh_from_db()
        self.assertTrue(cell.score_note.startswith("no close on 2026-09-28"),
                        cell.score_note)
        self.assertIsNone(cell.fwd_return)
        self.assertIsNotNone(cell.scored_at)
        self.assertEqual(S.record()[0]["stats"]["n"], 0)

    def test_the_as_of_close_is_kept_with_its_day(self):
        from bigmoney.models import BigMoneyCell
        as_of = date(2026, 9, 28)
        days = weekdays(date(2026, 8, 3), date(2026, 10, 9))
        seed_closes("EURUSD", {d: 1.10 + 0.001 * i for i, d in enumerate(days)},
                    asset_class="forex")
        S.store_board(self._fix_board(as_of))
        cell = BigMoneyCell.objects.get(footprint="fx_fix")
        self.assertEqual(cell.proxy_close_date, as_of)
        self.assertAlmostEqual(cell.proxy_close, 1.10 + 0.001 * days.index(as_of))

    def test_a_missing_close_waits_for_the_next_read_of_the_day(self):
        """The evening may store a claim before its close lands; the
        morning's read of the same day fills it, so the cell waits until
        its target day has passed before it is called unscored."""
        cal = bmcal.BusinessCalendar(())
        today = timezone.now().date()
        self.assertIsNone(S.measure(_cell(proxy_close=None), today, cal,
                                    FakeStore()))

    def _btc(self):
        instrument_crypto = seed_closes(
            "BTCUSD", {date(2026, 10, 7): 100.0, date(2026, 10, 8): 200.0,
                       date(2026, 10, 9): 300.0},
            asset_class="crypto", stamp_hour=0)
        return instrument_crypto

    def _crypto_board(self, run):
        return fake_board(date(2026, 10, 9), run=run, rows={"crypto": {
            "cells": {"cta": fake_cell("cta", "crypto", score=1.0,
                                       proxy="BTCUSD")}}})

    def test_the_reads_own_run_decides_the_crypto_close_not_the_relabel(self):
        """compute --run evening stores as manual: the claim is still
        graded from the last complete crypto bar, the day before."""
        from bigmoney.models import BigMoneyCell, BigMoneyRead
        self._btc()
        S.store_board(self._crypto_board("evening"), run="manual")
        cell = BigMoneyCell.objects.get(footprint="cta")
        self.assertEqual(cell.proxy_close, 200.0)
        self.assertEqual(cell.proxy_close_date, date(2026, 10, 8))
        self.assertEqual(BigMoneyRead.objects.get(row="crypto").run, "manual")

    def test_the_morning_grades_crypto_from_the_as_of_close(self):
        from bigmoney.models import BigMoneyCell
        self._btc()
        S.store_board(self._crypto_board("morning"), run="manual")
        cell = BigMoneyCell.objects.get(footprint="cta")
        self.assertEqual((cell.proxy_close, cell.proxy_close_date),
                         (300.0, date(2026, 10, 9)))


class TailMirrorTests(SimpleTestCase):

    def test_a_short_crowds_tail_is_measured_on_the_side_it_loses(self):
        """A crowd short (score < 0) loses on a rise: the worst close
        against it is the high, mirrored (spec §2.8)."""
        cal = bmcal.BusinessCalendar(())
        as_of = date(2026, 6, 1)
        days = weekdays(as_of, date(2026, 7, 31))
        series = [(d, 100.0) for d in days]
        series[3] = (series[3][0], 110.0)               # a rise on the way
        series[5] = (series[5][0], 95.0)                # and a dip
        store = FakeStore({"XAGUSD": series})
        got = S.measure(_cell(proxy="XAGUSD", claim="tail", score=-0.8,
                              horizon_days=20), as_of, cal, store)
        self.assertAlmostEqual(got["fwd_adverse"], 1 - 110.0 / 100.0)
        long_crowd = S.measure(_cell(proxy="XAGUSD", claim="tail", score=0.8,
                                     horizon_days=20), as_of, cal, store)
        self.assertAlmostEqual(long_crowd["fwd_adverse"], 95.0 / 100.0 - 1)


class MixedHorizonTests(SimpleTestCase):
    """opex stores one horizon per read day (5 business days on Monday, 1
    on Friday's eve): each row is benchmarked on its own horizon."""

    def _rows_and_store(self):
        days = weekdays(date(2026, 1, 5), date(2026, 6, 30))
        store = FakeStore({"SPX500": [(d, 100.0 * math.exp(0.001 * i))
                                      for i, d in enumerate(days)]})
        rows = []
        for i, d in enumerate(days[:100]):
            h = 5 - (i % 5)                              # 5, 4, 3, 2, 1, ...
            rows.append({"as_of": d, "score": 1.0, "h": h,
                         "fwd_return": 0.001 * h, "fwd_adverse": None})
        return rows, store

    def test_a_drifting_tape_gives_no_edge_on_mixed_horizons(self):
        rows, store = self._rows_and_store()
        st = S.stats_for(rows, h=rows[-1]["h"], proxy="SPX500",
                         cal=bmcal.BusinessCalendar(()), store=store)
        self.assertAlmostEqual(st["edge_bp"], 0.0, places=6)
        self.assertAlmostEqual(st["mean_bp"], 30.0, places=6)

    def test_the_subsample_steps_by_each_rows_own_horizon(self):
        rows, _store = self._rows_and_store()
        cal = bmcal.BusinessCalendar(())
        kept = S.non_overlapping(rows[:10], 1, cal)
        # Kept: day 0 (h 5) -> next allowed day 5 (h 5) -> ... every 5th.
        self.assertEqual([r["as_of"] for r in kept],
                         [rows[0]["as_of"], rows[5]["as_of"]])


class RecordCacheTests(TestCase):

    def test_the_record_is_computed_once_until_a_cell_is_graded(self):
        from django.core.cache import cache
        from tests.test_big_money_board import plant_record
        cache.clear()
        plant_record("fx_fix", "us_dollar", 12)
        first = S.record()
        with self.assertNumQueries(1):                 # the key's aggregate
            again = S.record()
        self.assertEqual(again, first)
        plant_record("fx_fix", "us_dollar", 3, start=date(2026, 6, 1))
        self.assertEqual(S.record()[0]["stats"]["n"], 15)

    def test_a_filtered_record_is_never_cached(self):
        from tests.test_big_money_board import plant_record
        plant_record("fx_fix", "us_dollar", 4)
        self.assertEqual(S._record_key(False).split(":")[-2], "4")
        with mock.patch.object(S, "_record_key") as key:
            S.record(footprint="fx_fix")
        key.assert_not_called()


class StoreBoardTests(TestCase):

    def test_the_morning_updates_the_evening_rows(self):
        from bigmoney.models import BigMoneyCell, BigMoneyRead
        ev = fake_board(run="evening", rows={"us_equities": {
            "lean": -0.5, "lean_label": W.LEANS_DOWN, "cells": {
                "rebalance": fake_cell("rebalance", "us_equities", score=-0.5)}}})
        S.store_board(ev)
        am = fake_board(run="morning", rows={"us_equities": {
            "lean": -0.8, "lean_label": W.LEANS_DOWN, "cells": {
                "rebalance": fake_cell("rebalance", "us_equities", score=-0.8)}}})
        S.store_board(am)
        self.assertEqual(BigMoneyRead.objects.filter(row="us_equities").count(), 1)
        read = BigMoneyRead.objects.get(row="us_equities")
        self.assertEqual(read.run, "morning")
        self.assertEqual(read.lean, -0.8)
        self.assertEqual(BigMoneyCell.objects.get().score, -0.8)
        self.assertEqual(BigMoneyRead.objects.count(), 8)   # 6 rows + 2

    def test_the_tide_is_scored_on_two_proxies(self):
        from bigmoney.models import BigMoneyCell
        board = fake_board(global_cells={"tide": fake_cell(
            "tide", "global", score=0.5, proxy="SPX500",
            proxies=["SPX500", "BTCUSD"])})
        S.store_board(board)
        self.assertEqual(sorted(BigMoneyCell.objects.values_list(
            "market", "proxy")), [("BTCUSD", "BTCUSD"), ("SPX500", "SPX500")])

    def test_unread_and_out_of_season_cells_make_no_claim(self):
        from bigmoney.models import BigMoneyCell
        board = fake_board(rows={"us_equities": {"cells": {
            "rebalance": fake_cell("rebalance", "us_equities", state="unread",
                                   why="x"),
            "opex": fake_cell("opex", "us_equities", state="out_of_season")}}})
        S.store_board(board)
        self.assertFalse(BigMoneyCell.objects.exists())

    def test_live_and_replayed_reads_are_separate_rows(self):
        from bigmoney.models import BigMoneyRead
        S.store_board(fake_board())
        S.store_board(fake_board(replayed=True, run="replay"))
        self.assertEqual(BigMoneyRead.objects.filter(replayed=True).count(), 8)
        self.assertEqual(BigMoneyRead.objects.filter(replayed=False).count(), 8)


def _rows(scores, rets, start=date(2026, 2, 17)):      # no holiday for weeks
    days = weekdays(start, start + timedelta(days=3 * len(scores) + 10))
    return [{"as_of": d, "score": s, "fwd_return": r, "fwd_adverse": None}
            for d, s, r in zip(days, scores, rets)]


class StatisticsTests(SimpleTestCase):

    def test_the_non_overlapping_subsample(self):
        cal = bmcal.BusinessCalendar(())
        rows = _rows([1.0] * 20, [0.01] * 20)
        self.assertEqual(len(S.non_overlapping(rows, 5, cal)), 4)
        self.assertEqual(len(S.non_overlapping(rows, 1, cal)), 20)

    def test_a_bull_market_does_not_flatter_leans_up(self):
        """Every reading 'up' in a market that rose the same every day: a
        hit rate of one, an edge over drift of zero."""
        days = weekdays(date(2026, 1, 1), date(2026, 3, 31))
        store = FakeStore({"SPX500": [(d, 100.0 * math.exp(0.001 * i))
                                      for i, d in enumerate(days)]})
        rows = [{"as_of": d, "score": 1.0, "fwd_return": 0.001,
                 "fwd_adverse": None} for d in days[:40]]
        st = S.stats_for(rows, h=1, proxy="SPX500",
                         cal=bmcal.BusinessCalendar(()), store=store)
        self.assertEqual(st["hit"], 1.0)
        self.assertAlmostEqual(st["mean_bp"], 10.0)
        self.assertAlmostEqual(st["edge_bp"], 0.0, places=6)
        self.assertAlmostEqual(st["drift"], 0.001, places=9)

    def test_the_inactive_readings_are_counted_but_not_signed(self):
        rows = _rows([0.1, 0.5, -0.5], [0.01, 0.02, -0.03])
        st = S.stats_for(rows, h=1, proxy="X", cal=bmcal.BusinessCalendar(()),
                         store=FakeStore())
        self.assertEqual(st["n"], 3)
        self.assertEqual(st["n_active"], 2)
        self.assertEqual(st["hit"], 1.0)
        self.assertIsNotNone(st["spearman"])

    def test_the_verdict_thresholds(self):
        self.assertEqual(S.verdict({"n_eff": 39, "t": 5, "edge_bp": 3}),
                         "too few to judge (39 of 40)")
        self.assertEqual(S.verdict({"n_eff": 40, "t": 2.0, "edge_bp": 3}),
                         W.VERDICT_PAYS)
        self.assertEqual(S.verdict({"n_eff": 40, "t": 2.5, "edge_bp": -1}),
                         W.VERDICT_NONE)
        self.assertEqual(S.verdict({"n_eff": 60, "t": -2.0, "edge_bp": -3}),
                         W.VERDICT_AGAINST)
        self.assertEqual(S.verdict({"n_eff": 60, "t": 1.0, "edge_bp": 3}),
                         W.VERDICT_NONE)

    def test_the_tail_verdict(self):
        rows = ([{"score": 0.9, "fwd_adverse": -0.06}] * 20
                + [{"score": 0.1, "fwd_adverse": -0.02}] * 20)
        st = S.tail_stats(rows)
        self.assertEqual(st["n_flagged"], 20)
        self.assertAlmostEqual(st["ratio"], 0.06 / 0.04)
        self.assertEqual(S.tail_verdict(st), "crowded readings were followed by "
                                             "1.5 times the usual drawdown "
                                             "(20 readings)")
        self.assertEqual(S.tail_verdict(S.tail_stats(rows[:5])),
                         "too few to judge (5 of 20)")

    def test_the_cost_line_reads_the_platforms_round_trip(self):
        from bot_program.asset_engine.risk_levels import DEFAULT_COST_BPS
        store = FakeStore(classes={"EURUSD": "forex", "SPX500": "index"})
        c = DEFAULT_COST_BPS["forex"]
        line = S.cost_line({"mean_bp": 3.0}, "EURUSD", store)
        self.assertEqual(line, f"Measured: +3.0 bp per signed reading. The "
                               f"platform's assumed round trip for forex: "
                               f"{c:g} bp. Does not clear twice the round trip.")
        self.assertNotIn("Does not clear",
                         S.cost_line({"mean_bp": 2 * c + 1}, "EURUSD", store))
        self.assertIn("round trip for index: 8 bp",
                      S.cost_line({"mean_bp": 30.0}, "SPX500", store))
        self.assertEqual(S.cost_line({"mean_bp": None}, "SPX500", store), "")


class CalibrationTests(SimpleTestCase):

    def _board(self, **kw):
        return fake_board(rows={
            "us_equities": {"lean": -0.5, "lean_label": W.LEANS_DOWN,
                            "lean_from": ["month-end rebalancing"]},
            "gold": {"lean": 0.2, "lean_label": W.NO_CLEAR_LEAN}},
            instruments={"XAGUSD": {"_lean": {"lean": 0.4,
                                              "label": W.LEANS_UP,
                                              "from": ["x"]}}}, **kw)

    def test_a_call_only_past_the_lean_threshold_and_only_in_the_morning(self):
        with mock.patch("ai_agents.calibration.log_direction_prediction",
                        return_value=object()) as log:
            self.assertEqual(S.calibrate(self._board()), 2)
        calls = {c.args[1]: c for c in log.call_args_list}
        self.assertEqual(set(calls), {"SPX500", "XAGUSD"})
        spx = calls["SPX500"]
        self.assertEqual(spx.args, ("big_money", "SPX500", "down"))
        self.assertEqual(spx.kwargs["horizon_hours"], 120)
        self.assertEqual(spx.kwargs["confidence"], 0.55)
        self.assertEqual(spx.kwargs["notes"], "lean from: month-end rebalancing")
        with mock.patch("ai_agents.calibration.log_direction_prediction") as log:
            self.assertEqual(S.calibrate(self._board(run="evening")), 0)
            self.assertEqual(S.calibrate(self._board(run="manual")), 0)
            self.assertEqual(S.calibrate(self._board(replayed=True)), 0)
        log.assert_not_called()


class RecordTests(TestCase):

    def test_the_record_reads_the_scored_cells(self):
        from tests.test_big_money_board import plant_record
        plant_record("fx_fix", "us_dollar", 12)
        rec = S.record()
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["verdict"], "too few to judge (12 of 40)")
        self.assertEqual(rec[0]["stats"]["n_eff"], 12)
        self.assertIn("Measured:", rec[0]["cost"])
