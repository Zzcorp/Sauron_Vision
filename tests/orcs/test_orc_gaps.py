"""THE GAP MODEL (bot_program/orcs/gaps.py, spec §3.6): measured on the
venue's own 1h bars; an unmeasured gap refuses what leans on it.

Run with:  python manage.py test tests.orcs.test_orc_gaps
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _bars

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=dt_tz.utc)      # a Friday


class TheMeasurementsTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_print_gap_p90_of_1h_range_at_past_prints(self):
        from market_data.models import EconomicEvent

        from bot_program.orcs.gaps import print_gap
        start = NOW - timedelta(days=20)
        _bars("BTCUSD", "1h", [100.0] * (24 * 20), start=start)
        from market_data.models import PriceData
        prints = []
        for k in range(10):
            at = start + timedelta(days=k + 1, hours=12, minutes=30)
            bar = at.replace(minute=0)
            PriceData.objects.filter(timestamp=bar, timeframe="1h").update(
                high=100 + (k + 1) / 2, low=100 - (k + 1) / 2)
            EconomicEvent.objects.create(
                title="US CPI m/m", country="US", datetime=at, impact="High",
                currency_affected="USD", source="forexfactory")
            prints.append(at)
        EconomicEvent.objects.create(
            title="US CPI m/m", country="EU", datetime=prints[0],
            impact="High", currency_affected="EUR", source="forexfactory")
        gap = print_gap("BTCUSD", "crypto", "US CPI m/m", now=NOW)
        self.assertEqual((gap.kind, gap.n, gap.source),
                         ("print", 10, "etoro"))
        self.assertAlmostEqual(gap.p90, 9.0, msg="the nearest-rank p90")
        self.assertEqual(print_gap("BTCUSD", "crypto", "UK GDP",
                                   now=NOW).n, 0)
        # forex reads either leg: the EUR print counts on EURUSD
        _bars("EURUSD", "1h", [1.1] * 48, start=prints[0] - timedelta(
            hours=24, minutes=30), asset_class="forex")
        fx = print_gap("EURUSD", "forex", "US CPI m/m", now=NOW)
        self.assertGreaterEqual(fx.n, 1)

    def test_weekend_gap(self):
        from bot_program.orcs.gaps import weekend_gap
        # three weekends: Friday's 19:00 and 20:00 bars, then Sunday 21:00
        moves = [0.004, 0.002, 0.010]
        for k, move in enumerate(moves):
            fri = datetime(2026, 9, 25, 19, 0, tzinfo=dt_tz.utc) + timedelta(
                weeks=k)
            _bars("EURUSD", "1h", [1.10, 1.10], start=fri,
                  asset_class="forex")
            sun = fri + timedelta(days=2, hours=2)
            _bars("EURUSD", "1h", [(1.10 + move, 1.10 + move, 1.10 + move,
                                    1.10 + move)] * 2, start=sun,
                  asset_class="forex")
        gap = weekend_gap("EURUSD", "forex", now=NOW)
        self.assertEqual(gap.n, 3)
        self.assertAlmostEqual(gap.p90, 0.010, places=6)

    def test_overnight_gap_from_the_session_clock(self):
        from bot_program.orcs.gaps import overnight_gap
        mon = datetime(2026, 10, 12, 18, 0, tzinfo=dt_tz.utc)
        _bars("AAPL", "1h", [200.0, 200.0], start=mon, asset_class="stock")
        tue = datetime(2026, 10, 13, 13, 0, tzinfo=dt_tz.utc)
        _bars("AAPL", "1h", [(203.0, 203.0, 203.0, 203.0)] * 2, start=tue,
              asset_class="stock")
        # a hole while the session is open is not a shut
        _bars("AAPL", "1h", [(203.0, 203.0, 203.0, 203.0)], start=tue +
              timedelta(hours=4), asset_class="stock")
        gap = overnight_gap("AAPL", "stock", now=NOW)
        self.assertEqual(gap.n, 1)
        self.assertAlmostEqual(gap.p90, 3.0)
        self.assertEqual(overnight_gap("EURUSD", "forex", now=NOW).n, 0)

    def test_crypto_range_gap(self):
        from bot_program.orcs.gaps import next_shut_gap, range_gap
        bars = [(100, 100 + i % 10, 100 - i % 10, 100) for i in range(200)]
        _bars("ETHUSD", "1h", bars, start=NOW - timedelta(hours=200))
        gap = range_gap("ETHUSD", "crypto", now=NOW)
        self.assertEqual(gap.kind, "range")
        self.assertEqual(gap.n, 200)
        self.assertAlmostEqual(gap.p90, 16.0)
        self.assertEqual(next_shut_gap("ETHUSD", "crypto", now=NOW), gap)


class TheLongWindowTests(TestCase):
    """THE WINDOW'S NEWEST BARS (2026-10-22). The gap model reads 400
    days of 1h bars; the reader it used returned the OLDEST 2,200 of them
    (about 13 forex weeks), so every weekend gap was measured on a window
    that ended ten months ago."""

    def setUp(self):
        cache.clear()

    def _bulk(self, symbol, asset_class, rows):
        from market_data.models import PriceData

        from tests.orcs.helpers import _inst
        inst = _inst(symbol, asset_class)
        PriceData.objects.bulk_create([
            PriceData(instrument=inst, timeframe="1h", timestamp=t,
                      open=o, high=h, low=lo, close=c, volume=0,
                      source="etoro") for t, (o, h, lo, c) in rows],
            batch_size=2000)
        return inst

    def test_weekend_gap_reads_the_newest_bars_of_a_long_window(self):
        from decimal import Decimal

        from bot_program.orcs.gaps import weekend_gap
        last_sun = datetime(2026, 10, 11, 21, 0, tzinfo=dt_tz.utc)
        cutoff = NOW - timedelta(days=200)
        rows, price = [], 1.10
        sundays = [last_sun - timedelta(weeks=k) for k in range(57, -1, -1)]
        for sun in sundays:
            # the weekend before an old week moved 0.001, a recent one 0.02
            price = round(price + (0.001 if sun < cutoff else 0.02), 6)
            p = Decimal(str(price))
            t = sun
            while t < sun + timedelta(days=5) and t <= NOW - timedelta(
                    hours=1):
                rows.append((t, (p, p, p, p)))
                t += timedelta(hours=1)
        self._bulk("EURUSD", "forex", rows)
        self.assertGreater(len(rows), 2200)
        gap = weekend_gap("EURUSD", "forex", now=NOW)
        self.assertEqual(gap.n, 57, "every weekend of the 400-day window")
        self.assertAlmostEqual(gap.p90, 0.02, places=9,
                               msg="the recent weekends weigh in")

    def test_print_gap_finds_prints_older_than_2200_hours(self):
        from decimal import Decimal

        from market_data.models import EconomicEvent

        from bot_program.orcs.gaps import print_gap
        start = NOW - timedelta(days=270)
        prints = [start + timedelta(days=10 + 25 * k, hours=12, minutes=30)
                  for k in range(10)]
        wide = {p.replace(minute=0): Decimal(str(1 + k))
                for k, p in enumerate(prints)}
        rows, t = [], start
        while t <= NOW - timedelta(hours=1):
            half = wide.get(t, Decimal("0")) / 2
            rows.append((t, (Decimal(100), Decimal(100) + half,
                             Decimal(100) - half, Decimal(100))))
            t += timedelta(hours=1)
        self._bulk("BTCUSD", "crypto", rows)
        for at in prints:
            EconomicEvent.objects.create(
                title="US CPI m/m", country="US", datetime=at,
                impact="High", currency_affected="USD",
                source="forexfactory")
        self.assertGreater(len(rows), 2200)
        gap = print_gap("BTCUSD", "crypto", "US CPI m/m", now=NOW)
        self.assertEqual(gap.n, 10, "the prints of the whole window")
        self.assertAlmostEqual(gap.p90, 9.0)


class TheVerdictTests(SimpleTestCase):

    def test_unmeasured_under_8_and_12_for_corsairs(self):
        from bot_program.orcs.constants import (CORSAIR_GAP_MIN_SAMPLES,
                                                GAP_MIN_SAMPLES)
        from bot_program.orcs.gaps import Gap, in_r, measured
        eight = Gap("print", "US CPI m/m", 8, 0.5, "etoro")
        self.assertTrue(measured(eight, GAP_MIN_SAMPLES))
        self.assertFalse(measured(eight, CORSAIR_GAP_MIN_SAMPLES))
        self.assertFalse(measured(Gap("print", "x", 7, 0.5, "etoro")))
        self.assertFalse(measured(Gap("print", "x", 9, None, "")))
        self.assertAlmostEqual(in_r(eight, 2.0), 0.25)
        self.assertIsNone(in_r(eight, 0))

    def test_waiver_check_refuses_unmeasured_and_below_floor(self):
        from bot_program.orcs.gaps import Gap, waiver_check
        thin = Gap("print", "US CPI m/m", 5, 0.5, "etoro")
        ok, why, gap_r = waiver_check(0.2, thin, 2.0)
        self.assertFalse(ok)
        self.assertIn("unmeasured (5 of 8 samples)", why)
        wide = Gap("print", "US CPI m/m", 9, 2.0, "etoro")
        ok, why, gap_r = waiver_check(0.2, wide, 2.0)
        self.assertEqual((ok, gap_r), (False, 1.0))
        self.assertIn("-0.80R", why)
        ok, _why, _ = waiver_check(0.2, Gap("print", "x", 9, 0.4, "etoro"),
                                   2.0)
        self.assertTrue(ok)
        ok, _why, _ = waiver_check(0.0, Gap("print", "x", 13, 0.8, "etoro"),
                                   2.0, -0.3, min_n=12)
        self.assertFalse(ok, "the Corsairs' floor is -0.3R")
