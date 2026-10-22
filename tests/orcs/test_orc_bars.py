"""THE VENUE'S BARS, READ ONE WAY (bot_program/orcs/bars.py, spec §5.2): the
venue's own frame first, one stand-in source when it is thin and never
mixed with it, a freshness read in OPEN market time, and the daily frame
built from the venue's 4h bars (no 1d candle is ever asked or written).

Run with:  python manage.py test tests.orcs.test_orc_bars
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import TestCase

from tests.orcs.helpers import _bars, _wave

T0 = datetime(2026, 9, 1, 0, 0, tzinfo=dt_tz.utc)


class TheFrameTests(TestCase):

    def test_venue_frame_etoro_only(self):
        from bot_program.orcs.bars import frame
        _bars("BTCUSD", "4h", _wave(40), start=T0, source="etoro")
        # a stand-in on another grid (two hours off) sits beside it
        _bars("BTCUSD", "4h", _wave(40, base=101), start=T0 + timedelta(
            hours=2), source="binance_public")
        now = T0 + timedelta(hours=4 * 40)
        f = frame("BTCUSD", "4h", asset_class="crypto", now=now)
        self.assertEqual((f.source, f.label, f.n), ("etoro", "etoro", 40))
        self.assertTrue(all(ts.hour % 4 == 0 for ts in f.df.index),
                        "the venue's grid only")
        self.assertEqual(f.newest_end, T0 + timedelta(hours=4 * 40))
        self.assertTrue(f.fresh)
        self.assertTrue(f.swings, "swings read off the frame")
        self.assertGreater(f.atr, 0)

    def test_platform_frame_one_source_never_mixed(self):
        from bot_program.orcs.bars import frame
        _bars("ETHUSD", "1h", _wave(10), start=T0 + timedelta(hours=60),
              source="etoro")                       # thin: 10 bars
        _bars("ETHUSD", "1h", _wave(50, base=99), start=T0,
              source="binance_public")              # newest stand-in
        _bars("ETHUSD", "1h", _wave(40, base=98), start=T0 - timedelta(
            hours=100), source="oanda")             # older stand-in
        f = frame("ETHUSD", "1h", asset_class="crypto",
                  now=T0 + timedelta(hours=70))
        self.assertEqual((f.source, f.label, f.n),
                         ("binance_public", "platform", 50))
        self.assertIsNone(frame("NOPE", "1h", asset_class="crypto",
                                now=T0))

    def test_frames_are_read_once_per_pass(self):
        from bot_program.orcs.bars import frame
        _bars("BTCUSD", "4h", _wave(40), start=T0)
        cache = {}
        now = T0 + timedelta(hours=160)
        first = frame("BTCUSD", "4h", asset_class="crypto", now=now,
                      cache=cache)
        with self.assertNumQueries(0):
            again = frame("BTCUSD", "4h", asset_class="crypto", now=now,
                          cache=cache)
        self.assertIs(first, again)

    def test_complete_bars_after_one_source_and_complete_only(self):
        from bot_program.orcs.bars import complete_bars_after
        _bars("BTCUSD", "1h", _wave(10), start=T0)
        _bars("BTCUSD", "1h", _wave(10, base=90),
              start=T0 + timedelta(minutes=30), source="binance_public")
        bars, source = complete_bars_after(
            "BTCUSD", "1h", T0 + timedelta(hours=3),
            T0 + timedelta(hours=9, minutes=30))
        self.assertEqual(source, "etoro")
        self.assertEqual([b["ts"] for b in bars],
                         [T0 + timedelta(hours=h) for h in range(3, 9)],
                         "the forming 09:00 bar is not complete")


    def test_complete_bars_after_newest_reads_the_end_of_a_long_window(self):
        """The default reads the window oldest first up to the limit (the
        tail's catch-up); `newest=True` reads its newest `limit` bars, still
        returned oldest first (the gap model's 400-day window)."""
        from bot_program.orcs.bars import complete_bars_after
        _bars("BTCUSD", "1h", [100.0 + i for i in range(30)], start=T0)
        now = T0 + timedelta(hours=40)
        old, _ = complete_bars_after("BTCUSD", "1h", T0, now, limit=10)
        new, src = complete_bars_after("BTCUSD", "1h", T0, now, limit=10,
                                       newest=True)
        self.assertEqual([b["close"] for b in old],
                         [100.0 + i for i in range(10)])
        self.assertEqual([b["close"] for b in new],
                         [100.0 + i for i in range(20, 30)])
        self.assertEqual(src, "etoro")


def _daily_4h(symbol, days, *, start, asset_class="stock"):
    """Six venue 4h bars a UTC day, each day's bars rising inside it:
    day k opens at 100 + k and closes at 100 + k + 0.5."""
    ohlc = []
    for k in range(days):
        for j in range(6):
            o = 100.0 + k + j * 0.1
            ohlc.append((o, o + 0.3 + (0.4 if j == 2 else 0.0), o - 0.2
                         - (0.6 if j == 4 else 0.0), o + 0.1))
    return _bars(symbol, "4h", ohlc, start=start, asset_class=asset_class)


class TheDailyFrameTests(TestCase):
    """THE ORCS' 1d IS THE VENUE'S 4h BY UTC DAY (2026-10-22). eToro's
    OneDay candle is anchored at 00:00 UTC; the nightly EOD job writes
    Yahoo's 1d bars at its own anchor, unfiltered readers (the regime, the
    posture, the charts) read every 1d row, and a second grid beside it
    would have doubled their daily bars. So no 1d candle is asked: the
    daily frame is built in memory from the venue's 4h bars, grouped by
    UTC date, and no row is written."""

    START = datetime(2026, 7, 1, 0, 0, tzinfo=dt_tz.utc)

    def test_daily_frame_is_the_venues_4h_bars_by_utc_day(self):
        from bot_program.orcs.bars import frame
        _daily_4h("AAPL", 70, start=self.START)
        # Yahoo's EOD bars at 04:00 UTC: never in the venue's frame
        _bars("AAPL", "1d", [99.0] * 70, start=self.START + timedelta(
            hours=4), source="yfinance", asset_class="stock")
        now = self.START + timedelta(days=69, hours=23, minutes=30)
        f = frame("AAPL", "1d", asset_class="stock", now=now, n=60)
        self.assertEqual((f.source, f.label, f.n, f.tf),
                         ("etoro", "etoro", 60, "1d"))
        self.assertTrue(all((ts.hour, ts.minute) == (0, 0)
                            for ts in f.df.index), "one bar a UTC day")
        day = f.df.iloc[-1]
        k = 69
        self.assertAlmostEqual(day["open"], 100.0 + k)
        self.assertAlmostEqual(day["close"], 100.0 + k + 0.5 + 0.1)
        self.assertAlmostEqual(day["high"], 100.0 + k + 0.2 + 0.7)
        self.assertAlmostEqual(day["low"], 100.0 + k + 0.4 - 0.8)
        self.assertEqual(f.newest_end, self.START + timedelta(days=70))
        self.assertTrue(f.fresh)
        self.assertGreater(f.atr, 0)

    def test_daily_frame_writes_no_row(self):
        from bot_program.orcs.bars import frame
        from market_data.models import PriceData
        _daily_4h("AAPL", 65, start=self.START)
        before = list(PriceData.objects.values_list("pk", "timeframe",
                                                    "source"))
        frame("AAPL", "1d", asset_class="stock",
              now=self.START + timedelta(days=65))
        self.assertEqual(list(PriceData.objects.values_list(
            "pk", "timeframe", "source")), before)

    def test_a_thin_venue_day_series_stands_in_with_one_other_source(self):
        """Fewer derived days than the frame's floor: the EOD job's own 1d
        bars stand in, labelled platform, never mixed with the venue's."""
        from bot_program.orcs.bars import frame
        _daily_4h("AAPL", 10, start=self.START + timedelta(days=50))
        _bars("AAPL", "1d", [99.0] * 60, start=self.START + timedelta(
            hours=4), source="yfinance", asset_class="stock")
        f = frame("AAPL", "1d", asset_class="stock",
                  now=self.START + timedelta(days=60))
        self.assertEqual((f.source, f.label, f.n),
                         ("yfinance", "platform", 60))

    def test_the_menu_reads_60_derived_days_and_the_decision_bar_is_1d(self):
        from bot_program.orcs.menu import symbol_levels
        from bot_program.orcs.predicates import decision_tf
        _daily_4h("AAPL", 61, start=self.START)
        now = self.START + timedelta(days=60, hours=23)
        _bars("AAPL", "1h", _wave(60, base=160.0), asset_class="stock",
              start=now - timedelta(hours=60))
        menu = symbol_levels("AAPL", "stock", now=now)
        self.assertEqual(menu.n.get("1d"), 61)
        self.assertTrue(menu.fresh.get("1d"))
        self.assertEqual(decision_tf("stock", "line", menu), "1d")


class TheFreshnessTests(TestCase):

    def test_fresh_ignores_weekend_and_session_shut(self):
        from bot_program.orcs.bars import fresh
        # forex: the last 4h bar ended Friday 20:00 UTC; it is Sunday
        # 22:30 UTC, the FX week open again since 21:00
        fri = datetime(2026, 10, 9, 20, 0, tzinfo=dt_tz.utc)
        sun = datetime(2026, 10, 11, 22, 30, tzinfo=dt_tz.utc)
        self.assertTrue(fresh(fri, "4h", "forex", "EURUSD", sun))
        # a US stock: the last 1h bar ended at Monday's close (20:00 UTC);
        # Tuesday 14:00 UTC is half an hour into the session
        mon = datetime(2026, 10, 12, 20, 0, tzinfo=dt_tz.utc)
        tue = datetime(2026, 10, 13, 14, 0, tzinfo=dt_tz.utc)
        self.assertTrue(fresh(mon, "1h", "stock", "AAPL", tue))
        # crypto never shuts: a weekend is wall time
        self.assertFalse(fresh(fri, "4h", "crypto", "BTCUSD", sun))

    def test_stale_past_two_bar_lengths_of_open_market(self):
        from bot_program.orcs.bars import fresh
        now = datetime(2026, 10, 14, 12, 0, tzinfo=dt_tz.utc)    # Wednesday
        self.assertTrue(fresh(now - timedelta(hours=2), "1h", "crypto",
                              "BTCUSD", now))
        self.assertFalse(fresh(now - timedelta(hours=2, minutes=1), "1h",
                               "crypto", "BTCUSD", now))
        self.assertFalse(fresh(now - timedelta(hours=9), "4h", "forex",
                               "EURUSD", now))
        self.assertFalse(fresh(None, "4h", "forex", "EURUSD", now))
