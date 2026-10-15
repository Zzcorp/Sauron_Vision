"""The Big Money Board: the footprints' formulas, the dash rule, point in
time, health, no side effects, and the words (spec bigmoney/spec.md §2.13).

Nothing here touches the network: every input is seeded as PriceData 1d,
COTReport and MacroObservation rows, and the FRED reader is patched where a
test goes through it.

Run with:  python manage.py test tests.test_big_money_board
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from bigmoney import calendar as bmcal
from bigmoney import cells as C
from bigmoney import words as W
from bigmoney.inputs import Store, market_day
from bigmoney.read import lean_of, read_board, read_time_for

UTC = dt_tz.utc
REPO = Path(settings.BASE_DIR)


# ── fixtures (imported by the other big money test modules) ─────────────

def instrument(symbol, asset_class="index", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    return inst


def weekdays(start: date, end: date, skip=()):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5 and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


def seed_closes(symbol, closes_by_day, *, asset_class="index", volume=0,
                volumes=None, stamp_hour=4):
    """One PriceData 1d bar per day, stamped at `stamp_hour` UTC (04:00 is
    New York's midnight in summer, as Yahoo stamps it)."""
    from market_data.models import PriceData
    inst = instrument(symbol, asset_class)
    rows = []
    for i, (d, c) in enumerate(sorted(closes_by_day.items())):
        v = volumes[i] if volumes is not None else volume
        rows.append(PriceData(
            instrument=inst, timeframe="1d",
            timestamp=datetime.combine(d, time(stamp_hour, 0), tzinfo=UTC),
            open=Decimal(str(c)), high=Decimal(str(c)), low=Decimal(str(c)),
            close=Decimal(str(round(c, 8))), volume=int(v), source="test"))
    PriceData.objects.bulk_create(rows)
    return inst


def monthly_levels(days, monthly_returns, *, start_level=100.0, current=None):
    """A close per day, constant within each month, moving by the month's
    return at each new month; `current` overrides the last month's level as
    a multiple of the previous month's."""
    out, level, last_key, i = {}, start_level, None, 0
    keys = sorted({(d.year, d.month) for d in days})
    for d in days:
        k = (d.year, d.month)
        if k != last_key:
            if last_key is not None:
                r = monthly_returns[i % len(monthly_returns)]
                level = level * (1 + r)
                i += 1
            if current is not None and k == keys[-1]:
                level = out[max(out)] * current
            last_key = k
        out[d] = level
    return out


def seed_cot(symbol, report_dates, xs, *, asset_class="commodity", oi=1000):
    """A legacy COT row per report date with speculators' net/OI = x."""
    from scraping.models import COTReport
    inst = instrument(symbol, asset_class)
    for d, x in zip(report_dates, xs):
        ncl = int(round(oi * (0.5 + x / 2)))
        ncs = oi - ncl
        COTReport.objects.create(instrument=inst, report_date=d,
                                 commercial_long=ncs, commercial_short=ncl,
                                 non_commercial_long=ncl,
                                 non_commercial_short=ncs, open_interest=oi,
                                 net_speculative=ncl - ncs)
    return inst


def tuesdays(end: date, n: int):
    end = end - timedelta(days=(end.weekday() - 1) % 7)
    return [end - timedelta(weeks=n - 1 - i) for i in range(n)]


def seed_fred(series, rows, units=None):
    from market_data.models import MacroIndicator, MacroObservation
    ind, _ = MacroIndicator.objects.get_or_create(
        series_id=series, defaults={"name": series, "category": "macro",
                                    "frequency": "d"})
    if units is not None:
        ind.metadata = {"units": units}
        ind.save(update_fields=["metadata"])
    MacroObservation.objects.bulk_create([
        MacroObservation(indicator=ind, date=d, value=Decimal(str(v)))
        for d, v in rows])
    return ind


def ctx_for(as_of, *, run="morning", replayed=False, cal=None, now=None):
    cal = cal or bmcal.BusinessCalendar.from_db()
    store = Store(upto=as_of if replayed else None)
    rt = read_time_for(as_of) if replayed else (now or datetime.combine(
        as_of + timedelta(days=1), time(5, 20), tzinfo=UTC))
    return C.Ctx(store, cal, as_of, run=run, replayed=replayed, read_time=rt,
                 now=rt)


HISTORY_START = date(2023, 9, 1)
OCT = date(2026, 10, 30)
ALT = (0.01, -0.01, 0.02, -0.015)


def seed_equity_and_bonds(*, eq_current=1.05, bond="AGG", end=OCT,
                          bond_current=1.0):
    days = weekdays(HISTORY_START, end)
    seed_closes("SPX500", monthly_levels(days, ALT, current=eq_current))
    if bond:
        seed_closes(bond, monthly_levels(days, (0.002, -0.001),
                                         current=bond_current),
                    asset_class="etf")
    return days


def fake_cell(footprint, market, *, state="read", score=0.0, words="words",
              why="", frm="", proxy=None, h=None, as_of=date(2026, 10, 23),
              **extra):
    """A cell as cells.make writes it, for the score and surface tests."""
    from bigmoney.rows import ROWS
    role, grade, claim, horizon = C.FOOTPRINTS[footprint]
    p = C.prior(footprint, market,
                commodity=footprint == "cot_change" and market not in ROWS)
    if footprint == "cot_change" and p == 0:
        role, grade = "context", "FRAGILE"
    cell = {"footprint": footprint, "state": state,
            "score": score if state == "read" else None, "grade": grade,
            "role": role, "weight": p, "prior": p, "zeroed": False,
            "words": words if state != "unread" else "", "why": why,
            "from": frm, "data_as_of": as_of.isoformat(), "public_at": None,
            "age_days": 0, "claim": claim, "horizon_days": h or horizon,
            "proxy": proxy or (ROWS[market]["graded_on"] if market in ROWS
                               else market)}
    cell.update(extra)
    return cell


def fake_board(as_of=date(2026, 10, 23), *, run="morning", replayed=False,
               rows=None, instruments=None, global_cells=None, now=None):
    """A board as read_board returns it, every row defaulting to "No
    footprint with evidence in season"."""
    from bigmoney.rows import ROW_ORDER, ROWS
    out_rows = {}
    for key in ROW_ORDER:
        r = {"title": ROWS[key]["title"], "lean": None,
             "lean_label": W.NO_FOOTPRINT, "lean_from": [], "coverage": None,
             "current": [], "risk": [], "cells": {}, "unread": []}
        r.update((rows or {}).get(key, {}))
        out_rows[key] = r
    now = now or datetime.combine(as_of + timedelta(days=1), time(5, 20),
                                  tzinfo=UTC)
    return {"as_of": as_of.isoformat(), "run": run, "replayed": replayed,
            "computed_at": now.isoformat(), "read_time": now.isoformat(),
            "rows": out_rows,
            "global": {"cells": global_cells or {}, "current": [], "risk": [],
                       "unread": [], "sources": []},
            "instruments": {"cells": instruments or {}, "unread": []},
            "footprints": 1, "unread_count": 0, "reasons": []}


# ── 1. month-end rebalancing ────────────────────────────────────────────

class RebalanceTests(TestCase):

    def test_equities_ahead_sell_equities_buy_bonds_on_agg(self):
        seed_equity_and_bonds()
        ctx = ctx_for(date(2026, 10, 23))          # claims Mon 26 Oct
        eq = C.rebalance_cell(ctx, "us_equities")
        tsy = C.rebalance_cell(ctx, "treasuries")
        self.assertEqual(eq["state"], "read", eq)
        self.assertEqual(eq["leg"], "AGG")
        self.assertGreater(eq["z"], 0.66)
        self.assertLess(eq["score"], 0)
        self.assertGreater(tsy["score"], 0)
        self.assertEqual(eq["score"], -tsy["score"])
        self.assertIn("ran ahead of bonds", eq["words"])
        self.assertNotIn("TLT", eq["words"])
        # drift and z by hand: w = 0.6(1+R_eq) / (0.6(1+R_eq) + 0.4(1+R_bd))
        r = C.rebalance_z(ctx, ctx.as_of)
        w = 0.6 * 1.05 / (0.6 * 1.05 + 0.4 * 1.0)
        self.assertAlmostEqual(r["w"], w, places=9)
        self.assertAlmostEqual(r["drift"], w - 0.6, places=9)
        self.assertAlmostEqual(r["z"], r["drift"] / r["sigma"], places=9)
        self.assertEqual(r["n"], C.SIGMA_MONTHS)
        self.assertEqual(eq["weight"], 1.0)
        self.assertEqual(tsy["weight"], 0.5)

    def test_the_tlt_fallback_is_said(self):
        seed_equity_and_bonds(bond="TLT")
        eq = C.rebalance_cell(ctx_for(date(2026, 10, 23)), "us_equities")
        self.assertEqual(eq["leg"], "TLT")
        self.assertIn(W.REBALANCE_TLT.strip(), eq["words"])

    def test_with_no_bond_leg_the_equity_drift_alone(self):
        seed_equity_and_bonds(bond=None)
        ctx = ctx_for(date(2026, 10, 23))
        eq = C.rebalance_cell(ctx, "us_equities")
        tsy = C.rebalance_cell(ctx, "treasuries")
        self.assertEqual(eq["state"], "read")
        self.assertIsNone(eq["leg"])
        self.assertIn(W.REBALANCE_ONE_LEG.strip(), eq["words"])
        self.assertLess(eq["score"], 0)
        self.assertEqual(tsy["state"], "unread")
        self.assertIsNone(tsy["score"])
        self.assertIn("AGG", tsy["why"])

    def test_a_small_drift_is_little_to_rebalance(self):
        seed_equity_and_bonds(eq_current=1.0005)
        eq = C.rebalance_cell(ctx_for(date(2026, 10, 23)), "us_equities")
        self.assertLess(abs(eq["z"]), 0.66)
        self.assertEqual(eq["score"], 0.0)
        self.assertIn("little to rebalance", eq["words"])

    def test_out_of_season_names_the_window(self):
        seed_equity_and_bonds()
        eq = C.rebalance_cell(ctx_for(date(2026, 10, 9)), "us_equities")
        self.assertEqual(eq["state"], "out_of_season")
        self.assertIn("Mon 26 Oct", eq["words"])
        self.assertIsNone(eq["score"])

    def test_the_read_after_the_last_close_of_the_month_is_out(self):
        """The pressure is spent at the month's last close: the read made
        after it claims the first day of the next month."""
        seed_equity_and_bonds()
        eq = C.rebalance_cell(ctx_for(date(2026, 10, 30)), "us_equities")
        self.assertEqual(eq["state"], "out_of_season")


class ReversalTests(TestCase):

    def test_the_reversal_follows_last_months_z_in_season_only(self):
        seed_equity_and_bonds()
        ctx = ctx_for(date(2026, 10, 30))          # claims Mon 2 Nov
        eq = C.reversal_cell(ctx, "us_equities")
        tsy = C.reversal_cell(ctx, "treasuries")
        z_t = C.rebalance_z(ctx, date(2026, 10, 30))["z"]
        self.assertGreater(z_t, 0)
        self.assertEqual(eq["state"], "read")
        self.assertAlmostEqual(eq["score"], 0.5 * C.clip(z_t / 2), places=4)
        self.assertAlmostEqual(tsy["score"], -0.5 * C.clip(z_t / 2), places=4)
        self.assertEqual(eq["weight"], 0.5)
        self.assertEqual(tsy["weight"], 0.25)
        self.assertIn("reverse within two weeks", eq["words"])
        early = C.reversal_cell(ctx_for(date(2026, 10, 23)), "us_equities")
        self.assertEqual(early["state"], "out_of_season")


# ── 2. the month-end fix ────────────────────────────────────────────────

def seed_fix_indices(symbols=("STOXX50", "FTSE100", "NIKKEI225", "ASX200"),
                     current=1.10, end=OCT):
    days = weekdays(HISTORY_START, end)
    for i, s in enumerate(symbols):
        seed_closes(s, monthly_levels(days, (-0.01, 0.015, 0.0, 0.01)[i:] +
                                      (-0.01, 0.015, 0.0, 0.01)[:i],
                                      current=current))


class FxFixTests(TestCase):

    def setUp(self):
        seed_equity_and_bonds()

    def test_the_usd_side_in_each_pairs_frame(self):
        seed_fix_indices()
        ctx = ctx_for(date(2026, 10, 28))          # claims Thu 29 Oct
        eur = C.fx_fix_pair_cell(ctx, "EURUSD")
        jpy = C.fx_fix_pair_cell(ctx, "USDJPY")
        row = C.fx_fix_row_cell(ctx)
        self.assertEqual(eur["state"], "read", eur)
        self.assertGreater(eur["z"], 0)            # Europe beat the S&P 500
        self.assertLess(eur["score"], 0)           # hedgers sell EUR: EURUSD down
        self.assertGreater(jpy["score"], 0)        # sell JPY: USDJPY up
        self.assertIn("hedgers sell EUR", eur["words"])
        self.assertGreater(row["score"], 0)        # the dollar side
        self.assertIn("favour the dollar", row["words"])
        self.assertEqual(row["pairs"], 4)
        self.assertEqual(row["weight"], 0.5)

    def test_fewer_than_two_pairs_leave_the_row_unread(self):
        seed_fix_indices(symbols=("STOXX50",))
        row = C.fx_fix_row_cell(ctx_for(date(2026, 10, 28)))
        self.assertEqual(row["state"], "unread")
        self.assertIsNone(row["score"])
        self.assertIn("fewer than 2 fix pairs", row["why"])

    def test_out_of_season_before_the_last_two_days(self):
        seed_fix_indices()
        row = C.fx_fix_row_cell(ctx_for(date(2026, 10, 23)))
        self.assertEqual(row["state"], "out_of_season")
        self.assertIn("Thu 29 Oct", row["words"])


# ── 3. the speculators' weekly change, faded ────────────────────────────

def cot_series(n, last_jump=0.0):
    xs = [0.10 + (0.01 if i % 2 else -0.01) for i in range(n)]
    xs[-1] = xs[-2] + last_jump
    return xs


class CotChangeTests(TestCase):

    def test_a_hard_buy_is_faded(self):
        dates = tuesdays(date(2026, 10, 6), 60)
        seed_cot("XAUUSD", dates, cot_series(60, last_jump=0.08))
        cell = C.cot_change_cell(ctx_for(date(2026, 10, 9)), "gold", "XAUUSD",
                                 proxy="XAUUSD", title="Gold")
        self.assertEqual(cell["state"], "read", cell)
        self.assertGreaterEqual(cell["z"], 1)
        self.assertLess(cell["score"], 0)          # contrarian
        self.assertAlmostEqual(cell["score"], -C.clip(cell["z"] / 2), places=3)
        self.assertIn("bought hard", cell["words"])
        self.assertEqual(cell["role"], "lean")
        self.assertEqual(cell["weight"], 0.5)

    def test_an_ordinary_week_scores_zero(self):
        dates = tuesdays(date(2026, 10, 6), 60)
        seed_cot("XAUUSD", dates, cot_series(60, last_jump=0.005))
        cell = C.cot_change_cell(ctx_for(date(2026, 10, 9)), "gold", "XAUUSD",
                                 proxy="XAUUSD", title="Gold")
        self.assertLess(abs(cell["z"]), 1)
        self.assertEqual(cell["score"], 0.0)
        self.assertIn("ordinary", cell["words"])

    def test_fifty_two_weeks_are_needed(self):
        dates = tuesdays(date(2026, 10, 6), 40)
        seed_cot("XAUUSD", dates, cot_series(40, last_jump=0.08))
        cell = C.cot_change_cell(ctx_for(date(2026, 10, 9)), "gold", "XAUUSD",
                                 proxy="XAUUSD", title="Gold")
        self.assertEqual(cell["state"], "unread")
        self.assertIn("COT history thin: 40 weeks, 52 needed", cell["why"])
        self.assertIn("cot-backfill --yes", cell["why"])

    def test_context_only_on_the_dollar(self):
        dates = tuesdays(date(2026, 10, 6), 60)
        seed_cot("DXY", dates, cot_series(60, last_jump=0.08),
                 asset_class="index")
        cell = C.cot_change_cell(ctx_for(date(2026, 10, 9)), "us_dollar", "DXY",
                                 proxy="DXY", title="US dollar")
        self.assertEqual(cell["role"], "context")
        self.assertEqual(cell["grade"], "FRAGILE")
        self.assertEqual(cell["weight"], 0.0)
        self.assertIn("Context only here", cell["words"])

    def test_the_delayed_week_bound(self):
        """10 days, 14 when the next release is one the CFTC moved to a
        Monday (Nov 16, 2026: the report of Nov 10)."""
        dates = tuesdays(date(2026, 11, 3), 60)
        seed_cot("XAUUSD", dates, cot_series(60, last_jump=0.08))
        late = C.cot_change_cell(ctx_for(date(2026, 11, 16)), "gold", "XAUUSD",
                                 proxy="XAUUSD", title="Gold")
        self.assertEqual(late["state"], "read", late)

    def test_eleven_days_in_an_ordinary_week_is_stale(self):
        dates = tuesdays(date(2026, 9, 29), 60)
        seed_cot("XAUUSD", dates, cot_series(60, last_jump=0.08))
        stale = C.cot_change_cell(ctx_for(date(2026, 10, 10)), "gold", "XAUUSD",
                                  proxy="XAUUSD", title="Gold")
        self.assertEqual(stale["state"], "unread")
        self.assertEqual(stale["why"], "COT report stale (11 days, bound 10): "
                                       "manage.py smart_money cot-backfill --yes")
        self.assertIsNone(stale["score"])


# ── 4. crowding and a crowd losing ──────────────────────────────────────

def crowd_xs(n, newest):
    xs = [(i % 11) / 10.0 for i in range(n - 1)]     # spans 0..1
    return xs + [newest]


class CrowdingTests(TestCase):

    def _cell(self, newest):
        dates = tuesdays(date(2026, 10, 6), 60)
        seed_cot("XAGUSD", dates, crowd_xs(60, newest))
        return C.crowding_cell(ctx_for(date(2026, 10, 9)), "XAGUSD", "XAGUSD",
                               proxy="XAGUSD")

    def test_heavy_at_80(self):
        c = self._cell(0.8)
        self.assertEqual(c["idx"], 80.0)
        self.assertEqual(c["flag"], "heavy long")
        self.assertIn("heavy long", c["words"])
        self.assertAlmostEqual(c["score"], 0.6)
        self.assertEqual(c["role"], "risk")
        self.assertEqual(c["weight"], 0.0)
        self.assertEqual(c["claim"], "tail")

    def test_crowded_at_90(self):
        c = self._cell(0.9)
        self.assertEqual(c["flag"], "crowded long")
        self.assertIn("a fatter left tail, not a lower average", c["words"])

    def test_short_side(self):
        self.assertEqual(self._cell(0.1)["flag"], "crowded short")

    def test_not_crowded(self):
        c = self._cell(0.5)
        self.assertEqual(c["flag"], "")
        self.assertIn("not crowded", c["words"])


class CrowdLosingTests(TestCase):

    def _seed(self, log_move):
        report = date(2026, 10, 6)
        seed_cot("XAGUSD", tuesdays(report, 60), crowd_xs(60, 0.95))
        days = weekdays(date(2026, 8, 1), date(2026, 10, 12))
        closes = {d: 30.0 for d in days}
        closes[days[-1]] = 30.0 * math.exp(log_move)
        seed_closes("XAGUSD", closes, asset_class="commodity")
        return days[-1]

    def test_read_at_one_and_a_half_sd_against(self):
        as_of = self._seed(-0.0301)                # 4 business days, sd 0.01
        with mock.patch.object(C, "sigma_d", return_value=0.01):
            c = C.crowd_losing_cell(ctx_for(as_of), "XAGUSD", "XAGUSD",
                                    proxy="XAGUSD")
        self.assertEqual(c["state"], "read", c)
        self.assertEqual(c["score"], -1.0)          # against the long crowd
        self.assertIn("forced exits are likely", c["words"])
        self.assertGreaterEqual(c["against"], C.LOSING_AT)

    def test_silent_at_one_point_four(self):
        as_of = self._seed(-0.028)
        with mock.patch.object(C, "sigma_d", return_value=0.01):
            c = C.crowd_losing_cell(ctx_for(as_of), "XAGUSD", "XAGUSD",
                                    proxy="XAGUSD")
        self.assertEqual(c["state"], "out_of_season")
        self.assertIsNone(c["score"])


# ── 5. trend followers, the variance premium, flows ─────────────────────

class CtaTests(TestCase):

    def test_signs_and_the_trigger_level(self):
        days = weekdays(date(2025, 6, 2), date(2026, 10, 9))
        closes = {d: 100.0 + i * 0.1 for i, d in enumerate(days)}
        seed_closes("XAUUSD", closes, asset_class="commodity")
        c = C.cta_cell(ctx_for(days[-1]), "gold", "XAUUSD", title="Gold")
        self.assertEqual(c["state"], "read", c)
        self.assertEqual(c["score"], 1.0)
        self.assertIn("long on 3 of three horizons", c["words"])
        vals = [closes[d] for d in days]
        # The 1-month trigger: the close tomorrow's close is compared with,
        # C_{t+1-L} = closes[-21]; the nearest of the three on a steady rise.
        self.assertIn(C.fmt_level(vals[-21]), c["words"])
        self.assertIn("a close below", c["words"])
        self.assertIn("1-month", c["words"])

    def test_a_fall_is_short(self):
        days = weekdays(date(2025, 6, 2), date(2026, 10, 9))
        closes = {d: 200.0 - i * 0.1 for i, d in enumerate(days)}
        seed_closes("XAUUSD", closes, asset_class="commodity")
        c = C.cta_cell(ctx_for(days[-1]), "gold", "XAUUSD", title="Gold")
        self.assertEqual(c["score"], -1.0)
        self.assertIn("a close above", c["words"])


class VrpTests(TestCase):

    def test_units_vix_squared_over_twelve_minus_21_squared_daily_moves(self):
        days = weekdays(date(2025, 1, 1), date(2026, 10, 9))
        level, closes = 100.0, {}
        for i, d in enumerate(days):
            level = level * (1.01 if i % 2 else 1 / 1.01)
            closes[d] = level
        seed_closes("SPX500", closes)
        seed_fred("VIXCLS", [(d, 20.0) for d in days[:-1]] + [(days[-1], 30.0)],
                  units="Index")
        c = C.vrp_cell(ctx_for(days[-1]))
        self.assertEqual(c["state"], "read", c)
        rv = 21 * (100 * math.log(1.01)) ** 2
        self.assertAlmostEqual(c["vrp"], 30.0 ** 2 / 12 - rv, places=2)
        self.assertGreater(c["score"], 0)
        self.assertIn("Fear priced above", c["words"])


class FlowsTests(TestCase):

    def _seed(self, rising):
        days = weekdays(date(2026, 6, 1), date(2026, 10, 9))
        closes, vols = {}, []
        for i, d in enumerate(days):
            late = i >= len(days) - 5
            closes[d] = 50.0 + ((i - len(days) + 6) * (1 if rising else -1)
                                if late else 0)
            vols.append(3_000_000 if late else 1_000_000)
        seed_closes("SPY", closes, asset_class="etf", volumes=vols)
        return days[-1]

    def test_heavy_volume_on_a_rise_reads_up(self):
        c = C.flows_cell(ctx_for(self._seed(True)), "us_equities", "SPY")
        self.assertEqual(c["state"], "read", c)
        self.assertEqual(c["score"], 1.0)
        self.assertIn("price up", c["words"])
        self.assertEqual(c["role"], "context")
        self.assertEqual(c["weight"], 0.0)

    def test_heavy_volume_on_a_fall_reads_down(self):
        c = C.flows_cell(ctx_for(self._seed(False)), "us_equities", "SPY")
        self.assertEqual(c["score"], -1.0)


# ── 6. the tide ─────────────────────────────────────────────────────────

def wednesdays(end: date, n: int):
    end = end - timedelta(days=(end.weekday() - 2) % 7)
    return [end - timedelta(weeks=n - 1 - i) for i in range(n)]


def seed_tide(*, rrp_units="Billions of U.S. Dollars",
              walcl_units="Millions of U.S. Dollars", end=date(2026, 10, 7)):
    weds = wednesdays(end, 80)
    # A weekly wobble of a few billion that is flat over the last 5 weeks:
    # the last 4-week change is the reverse repo's alone.
    walcl = [(d, 7_000_000 + (1000 * ((i * 7) % 5 - 2) if i < len(weds) - 5
                              else 0)) for i, d in enumerate(weds)]
    tga = [(d, 800_000) for d in weds]
    rrp = [(d, 100.0 + (1 if i % 3 else -1)) for i, d in enumerate(weds[:-4])]
    rrp += [(d, v) for d, v in zip(weds[-4:], (60.0, 30.0, 10.0, 0.0))]
    seed_fred("WALCL", walcl, units=walcl_units)
    seed_fred("WTREGEN", tga, units="Millions of U.S. Dollars")
    seed_fred("RRPONTSYD", rrp, units=rrp_units)
    return weds[-1]


class TideTests(TestCase):

    def test_units_through_the_metadata(self):
        last = seed_tide()
        c = C.tide_cell(ctx_for(last + timedelta(days=1)))
        self.assertEqual(c["state"], "read", c)
        self.assertEqual(c["tide_state"], "adding")
        self.assertIn("adding over 4 weeks", c["words"])
        self.assertEqual(c["proxies"], ["SPX500", "BTCUSD"])
        self.assertEqual(c["weight"], 0.0)
        self.assertIn("Bank reserves unread", c["words"])

    def test_the_reverse_repo_in_millions_would_be_a_hundred_dollars(self):
        """Read as millions, a 100 bn drain is noise beside WALCL's weekly
        wobble: the units matter."""
        last = seed_tide(rrp_units="Millions of U.S. Dollars")
        c = C.tide_cell(ctx_for(last + timedelta(days=1)))
        self.assertEqual(c["tide_state"], "flat")

    def test_unknown_units_leave_it_unread(self):
        last = seed_tide(walcl_units="Percent")
        c = C.tide_cell(ctx_for(last + timedelta(days=1)))
        self.assertEqual(c["state"], "unread")
        self.assertEqual(c["why"], "units of WALCL unknown (Percent)")
        self.assertIsNone(c["score"])


# ── 7. the lean ─────────────────────────────────────────────────────────

def _lc(state, score, weight, frm="x"):
    return {"role": "lean", "state": state, "score": score, "weight": weight,
            "from": frm, "why": "a reason" if state == "unread" else ""}


class LeanTests(SimpleTestCase):

    def test_coverage_and_the_label(self):
        out = lean_of({"a": _lc("read", -1.0, 1.0, "month-end rebalancing"),
                       "b": _lc("unread", None, 0.5)})
        self.assertAlmostEqual(out["coverage"], 2 / 3, places=3)
        self.assertEqual(out["label"], W.LEANS_DOWN)
        self.assertEqual(out["lean"], -1.0)
        self.assertEqual(out["from"], ["month-end rebalancing"])

    def test_below_half_coverage_is_unread(self):
        out = lean_of({"a": _lc("read", -1.0, 0.5), "b": _lc("unread", None, 1.0)})
        self.assertEqual(out["label"], W.UNREAD)
        self.assertIsNone(out["lean"])
        self.assertEqual(out["reasons"], ["a reason"])

    def test_nothing_in_season(self):
        out = lean_of({"a": dict(_lc("read", 1, 1), state="out_of_season"),
                       "c": {"role": "current", "state": "read", "score": 1,
                             "weight": 0}})
        self.assertEqual(out["label"], W.NO_FOOTPRINT)
        self.assertIsNone(out["lean"])

    def test_no_clear_lean(self):
        out = lean_of({"a": _lc("read", 0.2, 1.0), "b": _lc("read", 0.1, 0.5)})
        self.assertEqual(out["label"], W.NO_CLEAR_LEAN)
        self.assertEqual(out["from"], ["x"])


# ── 8. the one automatic weight rule ────────────────────────────────────

def plant_record(footprint, market, n, *, against=True, replayed=False,
                 proxy="NOPROXY", start=date(2025, 1, 6), h=1):
    """n scored readings with mixed signs, each signed move against the
    claim (or for it), on non-overlapping days."""
    from bigmoney.models import BigMoneyCell, BigMoneyRead
    from django.utils import timezone
    days = weekdays(start, start + timedelta(days=4 * n))
    for i, d in enumerate(days[:n]):
        read = BigMoneyRead.objects.create(as_of=d, row=market,
                                           replayed=replayed, run="morning")
        s = -1.0 if i % 2 else 1.0
        move = 0.01 + (0.001 if i % 3 else -0.001)
        r = (-s if against else s) * move
        BigMoneyCell.objects.create(read=read, footprint=footprint,
                                    market=market, proxy=proxy, score=s,
                                    claim="direction", horizon_days=h,
                                    proxy_close=100.0, fwd_return=r,
                                    scored_at=timezone.now())


class WeightRuleTests(TestCase):

    def test_a_record_against_its_claim_zeroes_never_flips(self):
        from bigmoney.score import effective_weights, record
        plant_record("rebalance", "us_equities", 45)
        rec = [r for r in record(replayed=False)
               if r["footprint"] == "rebalance"][0]
        self.assertEqual(rec["verdict"], W.VERDICT_AGAINST)
        self.assertLessEqual(rec["stats"]["t"], -2)
        weights = effective_weights()
        self.assertEqual(weights[("rebalance", "us_equities")], (0.0, True))
        seed_equity_and_bonds()
        ctx = ctx_for(date(2026, 10, 23))
        ctx.weights = weights
        eq = C.rebalance_cell(ctx, "us_equities")
        self.assertEqual(eq["weight"], 0.0)
        self.assertTrue(eq["zeroed"])
        self.assertIn(W.ZEROED, eq["why"])
        self.assertLess(eq["score"], 0)            # never flipped
        self.assertEqual(eq["prior"], 1.0)

    def test_a_record_that_pays_never_raises_the_prior(self):
        from bigmoney.score import effective_weights, record
        plant_record("rebalance", "us_equities", 45, against=False)
        rec = [r for r in record(replayed=False)
               if r["footprint"] == "rebalance"][0]
        self.assertEqual(rec["verdict"], W.VERDICT_PAYS)
        self.assertEqual(effective_weights(), {})
        seed_equity_and_bonds()
        ctx = ctx_for(date(2026, 10, 23))
        ctx.weights = {("rebalance", "us_equities"): (5.0, False)}
        self.assertEqual(C.rebalance_cell(ctx, "us_equities")["weight"], 1.0)

    def test_the_replayed_record_speaks_while_the_live_is_thin(self):
        from bigmoney.score import effective_weights
        plant_record("rebalance", "us_equities", 45, replayed=True)
        plant_record("rebalance", "us_equities", 5, against=False,
                     start=date(2026, 6, 1))
        self.assertEqual(effective_weights()[("rebalance", "us_equities")],
                         (0.0, True))


# ── 9. the dash rule ────────────────────────────────────────────────────

class DashRuleTests(TestCase):

    def test_no_fred_key_is_said_never_zero(self):
        with mock.patch.dict("os.environ", {"FRED_API_KEY": ""}):
            c = C.tide_cell(ctx_for(date(2026, 10, 8)))
        self.assertEqual(c["state"], "unread")
        self.assertEqual(c["why"],
                         "FRED key not set (FRED_API_KEY): WALCL unread")
        self.assertIsNone(c["score"])

    def test_a_stale_series_with_a_key_names_its_age(self):
        seed_fred("VIXCLS", [(date(2026, 9, 25), 18.0)])
        ctx = ctx_for(date(2026, 10, 8))
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "k"}):
            with self.assertRaises(C.Unread) as cm:
                ctx.fred("VIXCLS")
        self.assertEqual(cm.exception.reason,
                         "VIXCLS: no observation in 13 days (bound 5)")

    def test_a_stale_close_is_unread(self):
        days = weekdays(date(2025, 6, 2), date(2026, 10, 2))
        seed_closes("XAUUSD", {d: 100.0 + i for i, d in enumerate(days)},
                    asset_class="commodity")
        c = C.cta_cell(ctx_for(date(2026, 10, 8)), "gold", "XAUUSD", title="Gold")
        self.assertEqual(c["state"], "unread")
        self.assertEqual(c["why"], "XAUUSD: last close 6 days old (bound 4)")

    def test_thin_closes_name_the_backfill_line(self):
        days = weekdays(date(2026, 9, 1), date(2026, 10, 8))
        seed_closes("XAUUSD", {d: 100.0 for d in days}, asset_class="commodity")
        c = C.cta_cell(ctx_for(date(2026, 10, 8)), "gold", "XAUUSD", title="Gold")
        self.assertIn("manage.py backfill_bars --symbols XAUUSD --intervals 1d "
                      "--bars 1600", c["why"])

    def test_the_evening_says_no_close_yet(self):
        days = weekdays(date(2025, 6, 2), date(2026, 10, 7))
        seed_closes("SPX500", {d: 100.0 + i for i, d in enumerate(days)})
        c = C.cta_cell(ctx_for(date(2026, 10, 8), run="evening"), "us_equities",
                       "SPX500", title="US equities")
        self.assertEqual(c["why"], "SPX500: no close for 2026-10-08 yet: the "
                                   "morning read fills it")

    def test_an_exception_inside_a_cell_is_unreadable_and_the_read_returns(self):
        seed_equity_and_bonds()
        with mock.patch.object(C, "log_returns", side_effect=ZeroDivisionError):
            board = read_board(date(2026, 10, 23), now=datetime(
                2026, 10, 24, 5, 20, tzinfo=UTC))
        cta = board["rows"]["us_equities"]["cells"]["cta"]
        self.assertEqual(cta["state"], "unread")
        self.assertEqual(cta["why"], "unreadable: ZeroDivisionError")
        self.assertIn("rebalance", board["rows"]["us_equities"]["cells"])

    def test_read_board_never_raises(self):
        with mock.patch("bigmoney.read._read", side_effect=RuntimeError("boom")):
            board = read_board(date(2026, 10, 23))
        self.assertEqual(board["rows"]["us_equities"]["lean_label"], W.UNREAD)
        self.assertEqual(board["reasons"], ["unreadable: RuntimeError"])

    def test_a_read_that_fails_before_its_day_is_known_is_marked_failed(self):
        with mock.patch("bigmoney.calendar.as_of_for",
                        side_effect=RuntimeError("boom")):
            board = read_board(now=datetime(2026, 10, 9, 5, 20, tzinfo=UTC))
        self.assertEqual(board["as_of"], "2026-10-08")
        self.assertTrue(board["failed"])
        self.assertEqual(board["reasons"], ["unreadable: RuntimeError"])


class FailedReadTests(TestCase):
    """A failed read is never stored (review finding): it would overwrite
    a good read of the same day and delete its pending claims, or, dated
    a weekend day, outrank Friday's read all Monday. Its warning still
    reaches the digest through the task's return value."""

    def setUp(self):
        from bigmoney.score import store_board
        self.good = fake_board(date(2026, 10, 8), rows={"us_equities": {
            "lean": -0.8, "lean_label": W.LEANS_DOWN,
            "lean_from": ["month-end rebalancing"], "cells": {
                "rebalance": fake_cell("rebalance", "us_equities", score=-0.8),
                "rebalance_reversal": fake_cell("rebalance_reversal",
                                                "us_equities", score=0.3)}}})
        store_board(self.good)

    def _unchanged(self, out):
        from bigmoney.models import BigMoneyCell, BigMoneyRead
        self.assertEqual(out["status"], "warning", out)
        self.assertIn("unreadable: RuntimeError", out["reason"])
        self.assertEqual(out["stored"], 0)
        eq = BigMoneyRead.objects.get(as_of=date(2026, 10, 8), row="us_equities",
                                      replayed=False)
        self.assertEqual((eq.lean, eq.lean_label), (-0.8, W.LEANS_DOWN))
        self.assertEqual(BigMoneyCell.objects.filter(read=eq).count(), 2)
        self.assertEqual(BigMoneyRead.objects.count(), 8)

    def test_an_evening_that_fails_before_its_day_keeps_the_good_read(self):
        from bigmoney.tasks import run_board
        with mock.patch("bigmoney.calendar.as_of_for",
                        side_effect=RuntimeError("boom")):
            out = run_board("evening",
                            now=datetime(2026, 10, 9, 23, 20, tzinfo=UTC))
        self._unchanged(out)

    def test_a_morning_that_fails_inside_the_read_keeps_the_evenings(self):
        from bigmoney.tasks import run_board
        with mock.patch("bigmoney.read._read", side_effect=RuntimeError("boom")), \
                mock.patch("ai_agents.calibration.log_direction_prediction") as log:
            out = run_board("morning",
                            now=datetime(2026, 10, 9, 5, 20, tzinfo=UTC))
        self._unchanged(out)
        log.assert_not_called()

    def test_a_weekend_failure_never_outranks_fridays_read(self):
        from bigmoney.read import newest
        from bigmoney.score import store_board
        from bigmoney.tasks import run_board
        store_board(fake_board(date(2026, 10, 9)))
        with mock.patch("bigmoney.calendar.as_of_for",
                        side_effect=RuntimeError("boom")):
            out = run_board("morning",
                            now=datetime(2026, 10, 11, 5, 20, tzinfo=UTC))
        self.assertEqual(out["status"], "warning")
        self.assertEqual(newest(max_age_h=None)["as_of"], date(2026, 10, 9))

    def test_the_command_stores_nothing_for_a_failed_read(self):
        from io import StringIO

        from django.core.management import call_command

        from bigmoney.models import BigMoneyRead
        out = StringIO()
        with mock.patch("bigmoney.read._read", side_effect=RuntimeError("boom")):
            call_command("big_money", "compute", "--date", "2026-10-08",
                         stdout=out)
        self.assertIn("failed: nothing stored", out.getvalue())
        self.assertEqual(BigMoneyRead.objects.count(), 8)

    def test_an_empty_database_reads_dashes_and_no_footprint(self):
        board = read_board(date(2026, 10, 8), now=datetime(
            2026, 10, 9, 5, 20, tzinfo=UTC))
        eq = board["rows"]["us_equities"]
        for name, c in eq["cells"].items():
            if c["state"] == "unread":
                self.assertIsNone(c["score"], name)
                self.assertTrue(c["why"], name)
        self.assertEqual(eq["lean_label"], W.NO_FOOTPRINT)
        self.assertEqual(board["rows"]["crypto"]["lean_label"], W.NO_FOOTPRINT)
        self.assertGreater(board["unread_count"], 0)


# ── 10. point in time ───────────────────────────────────────────────────

class PointInTimeTests(TestCase):

    def test_a_backlog_cot_report_is_invisible_to_a_december_replay(self):
        seed_cot("XAUUSD", tuesdays(date(2025, 10, 21), 5),
                 [0.1, 0.2, 0.3, 0.4, 0.5])
        store = Store(upto=date(2025, 12, 1))
        replay = store.cot_visible("XAUUSD", date(2025, 12, 1), True,
                                   read_time_for(date(2025, 12, 1)))
        self.assertNotIn(date(2025, 10, 21), [r[0] for r in replay])
        self.assertIn(date(2025, 9, 23), [r[0] for r in replay])
        live = Store().cot_visible("XAUUSD", date(2025, 12, 1), False,
                                   read_time_for(date(2025, 12, 1)))
        self.assertIn(date(2025, 10, 21), [r[0] for r in live])

    def test_a_cot_report_is_readable_from_six_days_at_21_utc(self):
        from bigmoney.inputs import cot_public_at
        self.assertEqual(cot_public_at(date(2026, 9, 29)),
                         datetime(2026, 10, 5, 21, 0, tzinfo=UTC))

    def test_a_replay_reads_no_close_after_as_of(self):
        days = weekdays(date(2025, 6, 2), date(2026, 10, 9))
        seed_closes("XAUUSD", {d: 100.0 + i for i, d in enumerate(days)},
                    asset_class="commodity")
        ctx = ctx_for(date(2026, 9, 15), replayed=True)
        got, closes, _ = ctx.prices("XAUUSD")
        self.assertEqual(got[-1], date(2026, 9, 15))
        board = read_board(date(2026, 9, 15), replayed=True)
        self.assertEqual(board["rows"]["gold"]["cells"]["cta"]["data_as_of"],
                         "2026-09-15")

    def test_fred_in_a_replay_by_release(self):
        seed_fred("WALCL", [(date(2026, 9, 30), 1.0), (date(2026, 10, 7), 2.0)])
        store = Store()
        rows, _ = store.fred_visible("WALCL", date(2026, 10, 8), True,
                                     read_time_for(date(2026, 10, 8)))
        self.assertEqual(rows[-1][0], date(2026, 10, 7))   # Fri 9 >= Wed 7 + 2
        rows, _ = store.fred_visible("WALCL", date(2026, 10, 7), True,
                                     read_time_for(date(2026, 10, 7)))
        self.assertEqual(rows[-1][0], date(2026, 9, 30))

    def test_a_bar_stamped_at_a_local_midnight_lands_on_its_own_day(self):
        tokyo = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)     # 8 Oct, Tokyo
        self.assertEqual(market_day(tokyo), date(2026, 10, 8))
        self.assertEqual(market_day(datetime(2026, 10, 8, 4, 0, tzinfo=UTC)),
                         date(2026, 10, 8))
        self.assertEqual(market_day(datetime(2026, 10, 8, 0, 0, tzinfo=UTC)),
                         date(2026, 10, 8))

    def test_live_and_replayed_are_never_pooled(self):
        from bigmoney.score import record
        plant_record("cot_change", "gold", 10, replayed=True)
        plant_record("cot_change", "gold", 4, replayed=False,
                     start=date(2026, 6, 1))
        live = record(replayed=False)
        replay = record(replayed=True)
        self.assertEqual(live[0]["stats"]["n"], 4)
        self.assertEqual(replay[0]["stats"]["n"], 10)


# ── 11. health ──────────────────────────────────────────────────────────

class HealthTests(TestCase):

    def setUp(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=("platform_master", "big_money_board")).update(is_enabled=True)

    def test_a_blind_input_is_a_warning_in_its_own_words(self):
        from bigmoney.tasks import compute_big_money_board
        from core.platform_control import PlatformComponent
        from core.task_gate import judge_result
        out = compute_big_money_board.run("morning")
        self.assertEqual(out["status"], "warning")
        self.assertTrue(out["reason"].startswith("Big money board: "))
        self.assertIn("footprints unread", out["reason"])
        status, words = judge_result(out)
        self.assertEqual((status, words), ("warning", out["reason"]))
        row = PlatformComponent.objects.get(key="big_money_board")
        self.assertEqual(row.last_status, "warning")
        self.assertEqual(row.last_message, out["reason"][:500])

    def test_a_board_with_nothing_blind_is_a_success(self):
        from bigmoney.tasks import compute_big_money_board
        from core.platform_control import PlatformComponent
        from core.task_gate import judge_result
        clean = read_board(date(2026, 10, 8))
        clean.update({"unread_count": 0, "footprints": 12, "reasons": []})
        with mock.patch("bigmoney.read.read_board", return_value=clean):
            out = compute_big_money_board.run("evening")
        self.assertEqual(out["status"], "success")
        self.assertEqual(judge_result(out)[0], "success")
        self.assertEqual(PlatformComponent.objects.get(
            key="big_money_board").last_status, "success")

    def test_off_it_skips(self):
        from bigmoney.models import BigMoneyRead
        from bigmoney.tasks import compute_big_money_board
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key="big_money_board").update(
            is_enabled=False)
        out = compute_big_money_board.run("morning")
        self.assertEqual(out["status"], "skipped")
        self.assertFalse(BigMoneyRead.objects.exists())


# ── 12. no side effects ─────────────────────────────────────────────────

class NoSideEffectTests(TestCase):

    def test_a_compute_writes_no_signal_rule_trade_stress_or_event(self):
        from bigmoney.tasks import run_board
        from bot_program.aragorn_models import MarketStressReading
        from bot_program.asset_models import AssetBotTrade
        from market_data.models import EconomicEvent
        from signals.models import Signal
        from signals.models_control import RuleControl
        seed_equity_and_bonds()
        models = [Signal, AssetBotTrade, EconomicEvent, RuleControl,
                  MarketStressReading]
        before = {m: m.objects.count() for m in models}
        run_board("morning", now=datetime(2026, 10, 24, 5, 20, tzinfo=UTC))
        for m in models:
            self.assertEqual(m.objects.count(), before[m], m.__name__)

    def test_no_money_path_imports_the_board(self):
        paths = list((REPO / "bot_program" / "asset_engine").rglob("*.py"))
        paths += [REPO / "bot_program" / "manual_trade.py",
                  REPO / "portfolio" / "risk_gate.py",
                  REPO / "bot_program" / "smart_money.py",
                  REPO / "bot_program" / "alarm.py"]
        for p in paths:
            src = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\bbigmoney\b", src), str(p))

    def test_the_board_never_imports_the_alarm(self):
        for p in (REPO / "bigmoney").rglob("*.py"):
            src = p.read_text(encoding="utf-8")
            self.assertNotIn("bot_program.alarm", src, str(p))
            self.assertNotIn("from bot_program import alarm", src, str(p))
            self.assertNotIn("EconomicEvent.objects.create", src, str(p))


# ── 12b. the risk flags, the stress read, the trigger wiring ────────────

class RiskFlagTests(SimpleTestCase):

    def _cells(self, side, degree="crowded", losing=False):
        return {"crowding": {"state": "read", "flag": f"{degree} {side}",
                             "side": side, "degree": degree},
                "crowd_losing": {"state": "read" if losing else "out_of_season"}}

    def test_the_lean_on_the_crowded_side_is_a_fatter_left_tail(self):
        from bigmoney.read import _risk_flags
        self.assertEqual(_risk_flags(self._cells("long"), 0.5, [], []),
                         ["crowded long", W.FLAG_LEAN_CROWDED])
        self.assertEqual(_risk_flags(self._cells("short"), -0.4, [], []),
                         ["crowded short", W.FLAG_LEAN_CROWDED])
        # The lean against the crowd, below LEAN_AT, or absent: the crowd
        # alone.
        self.assertEqual(_risk_flags(self._cells("short"), 0.5, [], []),
                         ["crowded short"])
        self.assertEqual(_risk_flags(self._cells("long"), 0.2, [], []),
                         ["crowded long"])
        self.assertEqual(_risk_flags(self._cells("long"), None, [], []),
                         ["crowded long"])

    def test_a_losing_crowd_the_stress_and_the_forced_flows_are_listed(self):
        from bigmoney.read import _risk_flags
        flags = _risk_flags(self._cells("long", "heavy", losing=True), None,
                            [W.FLAG_STRESSED],
                            [W.EV_REBALANCE_OPENS, W.EV_MONTH_END])
        self.assertEqual(flags, ["heavy long", W.FLAG_CROWD_LOSING,
                                 W.FLAG_STRESSED,
                                 "forced flows within 2 business days: "
                                 "Month-end rebalancing window opens, Month-end"])
        self.assertEqual(_risk_flags({}, None, [], []), [])


class StressTests(TestCase):
    """The market stress read: the functions of bot_program/market_stress,
    read-only and live only; never the task behind the crisis_mode switch."""

    def _board(self, sc, subs, comps, *, replayed=False):
        from bot_program import market_stress as ms
        with mock.patch.object(ms, "read_components",
                               return_value=(comps, [])) as rc, \
                mock.patch.object(ms, "score", return_value=(sc, subs)), \
                mock.patch.object(ms, "_vix_term", return_value=None):
            board = read_board(date(2026, 10, 8), replayed=replayed,
                               now=datetime(2026, 10, 9, 5, 20, tzinfo=UTC))
        return board, rc

    def test_a_crisis_score_flags_every_market(self):
        board, _rc = self._board(60.0, {"vix": 90.0, "index_drawdown": 70.0,
                                        "hy_spread": 20.0, "realized_vol": 5.0},
                                 {"index_drawdown": 0.25, "vix": 45.0})
        st = board["global"]["cells"]["stress"]
        self.assertEqual(st["state"], "read", st)
        self.assertEqual(st["score"], 60.0)
        self.assertEqual(st["level"], "crisis")
        self.assertEqual(st["words"],
                         "In crisis (score 60 of 100): the VIX 90, the drawdown "
                         "70, credit spreads 20. Read here only; the posture "
                         "that binds real money is set by the crisis mode, not "
                         "by this board.")
        self.assertEqual(board["global"]["risk"], [W.FLAG_CRISIS])
        for key, row in board["rows"].items():
            self.assertIn(W.FLAG_CRISIS, row["risk"], key)
            self.assertNotIn(W.FLAG_STRESSED, row["risk"], key)

    def test_stressed_at_30_and_calm_below(self):
        board, _rc = self._board(35.0, {"vix": 50.0}, {"vix": 28.0})
        self.assertTrue(board["global"]["cells"]["stress"]["words"]
                        .startswith("Stressed (score 35 of 100): the VIX 50."))
        self.assertEqual(board["global"]["risk"], [W.FLAG_STRESSED])
        self.assertIn(W.FLAG_STRESSED, board["rows"]["gold"]["risk"])
        board, _rc = self._board(12.0, {"vix": 10.0}, {"vix": 14.0})
        self.assertTrue(board["global"]["cells"]["stress"]["words"]
                        .startswith("Calm (score 12 of 100)"))
        self.assertEqual(board["global"]["risk"], [])
        for row in board["rows"].values():
            self.assertNotIn(W.FLAG_STRESSED, row["risk"])
            self.assertNotIn(W.FLAG_CRISIS, row["risk"])

    def test_too_little_to_call_is_a_dash(self):
        board, _rc = self._board(None, {}, {})
        st = board["global"]["cells"]["stress"]
        self.assertEqual(st["state"], "unread")
        self.assertEqual(st["why"], W.R_STRESS_NONE)
        self.assertIsNone(st["score"])
        self.assertEqual(board["global"]["risk"], [])

    def test_never_replayed(self):
        board, rc = self._board(60.0, {"vix": 90.0}, {"vix": 45.0},
                                replayed=True)
        st = board["global"]["cells"]["stress"]
        self.assertEqual((st["state"], st["why"]), ("unread", W.R_NOT_REPLAYED))
        rc.assert_not_called()
        self.assertEqual(board["global"]["risk"], [])


class TrendTriggerWiringTests(TestCase):

    def test_a_trigger_within_one_daily_move_reaches_the_calendar_and_the_brief(self):
        """A close that alternates 100, 101: the 1-month trigger C_{t-20}
        is today's close, zero daily moves away, so it enters the global
        calendar as an estimate dated the next business day, the market's
        risk flags name it, and the brief says the market is near one."""
        from bigmoney.read import brief_lines
        from bigmoney.score import store_board
        days = weekdays(date(2025, 6, 2), date(2026, 10, 8))
        seed_closes("SPX500", {d: 100.0 + (i % 2) for i, d in enumerate(days)})
        board = read_board(date(2026, 10, 8), now=datetime(
            2026, 10, 9, 5, 20, tzinfo=UTC))
        cta = board["rows"]["us_equities"]["cells"]["cta"]
        self.assertEqual(cta["state"], "read", cta)
        self.assertIsNotNone(cta["trigger"])
        self.assertLessEqual(cta["trigger"]["k"], C.CTA_NEAR)
        self.assertEqual(cta["trigger"]["date"], "2026-10-09")
        self.assertEqual(cta["trigger"]["horizon"], "1-month")
        self.assertIn("(0.0 daily moves away)", cta["words"])
        events = board["global"]["cells"]["calendar"]["events"]
        trig = [e for e in events if e["kind"] == "estimate"]
        self.assertEqual(len(trig), 1, events)
        self.assertEqual(trig[0]["event"], "Trend followers' trigger on US equities")
        self.assertEqual(trig[0]["date"], "2026-10-09")
        self.assertEqual(trig[0]["rows"], ["us_equities"])
        self.assertEqual(trig[0]["play"], W.PLAY_TREND)
        self.assertTrue(trig[0]["directional"] and trig[0]["forced"])
        self.assertTrue(any("Trend followers' trigger on US equities" in f
                            for f in board["rows"]["us_equities"]["risk"]),
                        board["rows"]["us_equities"]["risk"])
        self.assertFalse(any("Trend followers" in f
                             for f in board["rows"]["gold"]["risk"]))
        store_board(board)
        self.assertIn("• Trend followers: US equities within one daily move of "
                      "a trigger", brief_lines(head=_head_now()))


class SourcesPanelTests(TestCase):
    """The Sources panel judges each tape against the read's own day: a
    read at a past date (the reversal reads last month's last close) never
    leaves a dead tape shown as fresh (spec §2.4 R1)."""

    def test_tapes_dead_since_month_end_are_stale_in_the_reversal_season(self):
        seed_equity_and_bonds()                         # SPX500, AGG to Oct 30
        seed_closes("TLT", {d: 90.0 for d in weekdays(date(2026, 6, 1), OCT)},
                    asset_class="etf", volume=1000)
        board = read_board(date(2026, 11, 4), now=datetime(
            2026, 11, 5, 5, 20, tzinfo=UTC))
        rev = board["rows"]["us_equities"]["cells"]["rebalance_reversal"]
        self.assertEqual(rev["state"], "read", rev)     # read at Oct 30
        sources = {s["input"]: s for s in board["global"]["sources"]}
        for sym in ("SPX500", "AGG", "TLT"):
            self.assertEqual(sources[sym]["state"], "stale", sym)
            self.assertEqual(sources[sym]["newest"], "2026-10-30", sym)
            self.assertEqual(sources[sym]["age"], 5, sym)
        self.assertIn("SPX500: last close 5 days old (bound 4)",
                      board["rows"]["us_equities"]["unread"])

    def test_a_fresh_tape_read_at_a_past_date_stays_fresh(self):
        seed_equity_and_bonds(end=date(2026, 11, 4))
        board = read_board(date(2026, 11, 4), now=datetime(
            2026, 11, 5, 5, 20, tzinfo=UTC))
        sources = {s["input"]: s for s in board["global"]["sources"]}
        self.assertEqual(sources["AGG"]["state"], "fresh")
        self.assertEqual(sources["SPX500"]["state"], "fresh")


class EveningCloseTests(TestCase):
    """At 23:20 UTC every market but crypto has closed: a missing as-of
    close is said, never yesterday's read as today's (spec §2.10)."""

    def _gold(self, end):
        days = weekdays(date(2025, 6, 2), end)
        seed_closes("XAUUSD", {d: 100.0 + i for i, d in enumerate(days)},
                    asset_class="commodity")

    def test_gold_without_its_as_of_close_says_so_in_the_evening(self):
        self._gold(date(2026, 10, 7))
        ev = C.cta_cell(ctx_for(date(2026, 10, 8), run="evening"), "gold",
                        "XAUUSD", title="Gold")
        self.assertEqual(ev["state"], "unread")
        self.assertEqual(ev["why"], "XAUUSD: no close for 2026-10-08 yet: the "
                                    "morning read fills it")
        am = C.cta_cell(ctx_for(date(2026, 10, 8)), "gold", "XAUUSD",
                        title="Gold")
        self.assertEqual(am["state"], "read", am)

    def test_gold_with_its_as_of_close_is_read_in_the_evening(self):
        self._gold(date(2026, 10, 8))
        ev = C.cta_cell(ctx_for(date(2026, 10, 8), run="evening"), "gold",
                        "XAUUSD", title="Gold")
        self.assertEqual((ev["state"], ev["data_as_of"]), ("read", "2026-10-08"))


class CryptoCloseTests(TestCase):
    """Crypto closes at 00:00 UTC: the evening reads the last complete bar,
    the morning the as-of one; the bound is 2 calendar days (spec §2.4 R0)."""

    def _btc(self, end):
        d, closes = date(2025, 6, 1), {}
        while d <= end:
            closes[d] = 50_000.0 + d.toordinal() % 97
            d += timedelta(days=1)
        seed_closes("BTCUSD", closes, asset_class="crypto", stamp_hour=0)

    def test_the_evening_reads_the_day_before_the_morning_the_day(self):
        self._btc(date(2026, 10, 9))
        days, _c, _v = ctx_for(date(2026, 10, 9), run="evening").prices("BTCUSD")
        self.assertEqual(days[-1], date(2026, 10, 8))
        days, _c, _v = ctx_for(date(2026, 10, 9)).prices("BTCUSD")
        self.assertEqual(days[-1], date(2026, 10, 9))

    def test_three_days_is_stale_and_names_the_nightly_close(self):
        self._btc(date(2026, 10, 6))
        cell = C.cta_cell(ctx_for(date(2026, 10, 9)), "crypto", "BTCUSD",
                          title="Crypto")
        self.assertEqual(cell["state"], "unread")
        self.assertTrue(cell["why"].startswith(
            "BTCUSD: last close 3 days old (bound 2)"), cell["why"])
        self.assertIn("fetch-eod-crypto", cell["why"])
        self.assertEqual(C.CLOSE_BOUND_CRYPTO, 2)

    def test_two_days_is_fresh(self):
        self._btc(date(2026, 10, 7))
        cell = C.cta_cell(ctx_for(date(2026, 10, 9)), "crypto", "BTCUSD",
                          title="Crypto")
        self.assertEqual(cell["state"], "read", cell)


class StressFlagTests(TestCase):
    """The stress flag and the stress words come from one judgement,
    market_stress.raw_level: never "market in crisis" beside "Stressed"."""

    def _board(self, comps, sc=None, *, term=None):
        from bot_program import market_stress as ms
        patches = [mock.patch.object(ms, "read_components",
                                     return_value=(dict(comps), [])),
                   mock.patch.object(ms, "_vix_term", return_value=term)]
        if sc is not None:
            patches.append(mock.patch.object(ms, "score",
                                             return_value=(sc, {"vix": 50.0})))
        else:
            patches.append(mock.patch.object(ms, "score", wraps=ms.score))
        for p in patches:
            p.start()
        try:
            board = read_board(date(2026, 10, 8),
                               now=datetime(2026, 10, 9, 5, 20, tzinfo=UTC))
            score_mock = ms.score
        finally:
            for p in reversed(patches):
                p.stop()
        return board, score_mock

    def _flags(self, board):
        return board["global"]["risk"], board["rows"]["gold"]["risk"]

    def test_the_lines_at_55_and_30(self):
        with_index = {"index_drawdown": 0.25, "vix": 30.0}
        for sc, flag in ((55.0, W.FLAG_CRISIS), (54.9, W.FLAG_STRESSED),
                         (30.0, W.FLAG_STRESSED)):
            board, _ = self._board(with_index, sc)
            g, gold = self._flags(board)
            self.assertEqual(g, [flag], sc)
            self.assertIn(flag, gold, sc)
        board, _ = self._board(with_index, 29.9)
        self.assertEqual(self._flags(board), ([], []))

    def test_no_index_and_the_vix_under_35_is_stressed_in_words_and_flag(self):
        """A dead index feed: the VIX at 33 and credit spreads at 8 score
        past the crisis line, but raw_level refuses a crisis without an
        index unless the VIX is at 35."""
        board, _ = self._board({"vix": 33.0, "hy_spread": 8.0})
        st = board["global"]["cells"]["stress"]
        self.assertGreaterEqual(st["score"], 55.0, st)
        self.assertEqual(st["level"], "stressed")
        self.assertTrue(st["words"].startswith("Stressed (score "), st["words"])
        self.assertEqual(board["global"]["risk"], [W.FLAG_STRESSED])
        for key, row in board["rows"].items():
            self.assertNotIn(W.FLAG_CRISIS, row["risk"], key)

    def test_the_vix_curve_reaches_the_score_with_smart_money_off(self):
        board, score_mock = self._board({"vix": 20.0}, term=1.15)
        self.assertEqual(score_mock.call_args.args[0]["vix_term"], 1.15)
        self.assertEqual(board["global"]["cells"]["stress"]["state"], "read")


class LookaheadTests(TestCase):
    """The production replay shares one Store across every replayed day;
    only Store.closes_upto keeps each day point in time."""

    def test_the_replay_command_reads_no_close_after_its_day(self):
        from django.core.management import call_command

        from bigmoney.models import BigMoneyRead
        days = weekdays(date(2025, 6, 2), date(2026, 10, 9))
        seed_closes("XAUUSD", {d: 100.0 + i for i, d in enumerate(days)},
                    asset_class="commodity")
        call_command("big_money", "replay", "--from", "2026-09-15",
                     "--to", "2026-09-15", "--yes", stdout=StringIO())
        gold = BigMoneyRead.objects.get(as_of=date(2026, 9, 15), row="gold",
                                        replayed=True)
        self.assertEqual(gold.cells["cta"]["state"], "read", gold.cells["cta"])
        self.assertEqual(gold.cells["cta"]["data_as_of"], "2026-09-15")

    def test_a_replay_weighs_by_the_priors_never_its_future_record(self):
        plant_record("rebalance", "us_equities", 45, replayed=True)
        seed_equity_and_bonds()
        board = read_board(date(2026, 10, 23), replayed=True)
        reb = board["rows"]["us_equities"]["cells"]["rebalance"]
        self.assertEqual(reb["state"], "read", reb)
        self.assertEqual(reb["weight"], 1.0)
        self.assertFalse(reb["zeroed"])


class ForcedSoonTests(SimpleTestCase):

    def test_the_window_is_two_business_days(self):
        from bigmoney.read import _forced_soon
        cal = bmcal.BusinessCalendar(())
        today = date(2026, 10, 22)                      # Thu
        evs = [{"event": "two", "date": "2026-10-26", "forced": True,
                "rows": ["us_equities"]},                # Mon: +2 business days
               {"event": "three", "date": "2026-10-27", "forced": True,
                "rows": ["us_equities"]},                # Tue: +3
               {"event": "not forced", "date": "2026-10-23", "forced": False,
                "rows": ["us_equities"]},
               {"event": "other row", "date": "2026-10-23", "forced": True,
                "rows": ["gold"]}]
        self.assertEqual(_forced_soon(evs, "us_equities", today, cal), ["two"])


class ReuseTests(SimpleTestCase):

    def test_the_cot_window_and_floor_are_the_smart_moneys(self):
        from bot_program import smart_money as sm
        self.assertEqual((C.COT_WINDOW_WEEKS, C.COT_MIN_WEEKS),
                         (sm.COT_WINDOW_WEEKS, sm.COT_MIN_WEEKS))
        self.assertEqual((C.COT_WINDOW_WEEKS, C.COT_MIN_WEEKS), (156, 52))


# ── 13. the words ───────────────────────────────────────────────────────

class WordsTests(TestCase):

    def test_every_string_and_the_template_are_english(self):
        from tests.test_alarm_bot import FRENCH
        accented = re.compile(r"[À-ÖØ-öø-ÿŒœ]")
        texts = W.every_string()
        texts.append((REPO / "templates" / "bigmoney" / "board.html")
                     .read_text(encoding="utf-8"))
        self.assertGreater(len(texts), 150)
        for t in texts:
            low = f" {t.lower()} "
            for word in FRENCH:
                self.assertNotIn(word, low, t[:80])
            self.assertIsNone(accented.search(t), t[:80])

    def test_every_brief_line_passes_the_money_tripwire(self):
        from bigmoney.read import brief_lines
        from bigmoney.score import store_board
        from tests.test_alarm_bot import MONEY
        seed_equity_and_bonds()
        seed_tide(end=date(2026, 10, 21))
        board = read_board(date(2026, 10, 23), now=datetime(
            2026, 10, 24, 5, 20, tzinfo=UTC))
        store_board(board)
        lines = brief_lines(head=_head_now())
        self.assertLessEqual(len(lines), 9)
        self.assertTrue(any("US equities" in ln for ln in lines), lines)
        for ln in lines:
            self.assertIsNone(MONEY.search(ln), ln)
            self.assertTrue(ln.startswith("• "), ln)


def _head_now():
    from bigmoney.read import newest
    return newest(max_age_h=None) | {"ok": True}
