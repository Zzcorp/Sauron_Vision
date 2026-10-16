"""THE SESSION CALENDAR (spec §1.6, O1): when does this instrument's market
next shut, for how long, and why — read from core/exchange_status.py's
market_clock and one additive helper, next_close_utc, never from the
care's is_weekend_window (which answers only "is it Friday's last hour").

Run with:  python manage.py test tests.orcs.test_orc_sessions
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import SimpleTestCase

UTC = dt_tz.utc
#: Wednesday 2026-10-14, 15:00 UTC: New York (EDT) open since 13:30.
WED = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
#: Friday 2026-10-16, 15:00 UTC.
FRI = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)


class TheNextShutTests(SimpleTestCase):

    def test_an_nyse_weekday_shuts_overnight(self):
        from bot_program.orcs.sessions import next_shut
        s = next_shut("stock", "AAPL", WED, exchange="NASDAQ")
        self.assertEqual(s["at"], datetime(2026, 10, 14, 20, 0, tzinfo=UTC))
        self.assertEqual(s["reopens"],
                         datetime(2026, 10, 15, 13, 30, tzinfo=UTC))
        self.assertEqual(s["kind"], "overnight")
        self.assertEqual(s["hours"], 17.5)
        self.assertEqual(s["session"], "NASDAQ")
        self.assertFalse(s["now_shut"])
        self.assertTrue(s["modelled"])

    def test_friday_shuts_for_the_weekend(self):
        from bot_program.orcs.sessions import next_shut
        s = next_shut("stock", "AAPL", FRI)
        self.assertEqual(s["at"], datetime(2026, 10, 16, 20, 0, tzinfo=UTC))
        self.assertEqual(s["reopens"],
                         datetime(2026, 10, 19, 13, 30, tzinfo=UTC))
        self.assertEqual(s["kind"], "weekend")
        self.assertEqual(s["hours"], 65.5)
        # asked inside the shut: the running shut, said so
        sat = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
        inside = next_shut("stock", "AAPL", sat)
        self.assertTrue(inside["now_shut"])
        self.assertEqual(inside["at"], s["at"])
        self.assertEqual(inside["reopens"], s["reopens"])
        self.assertEqual(inside["kind"], "weekend")

    def test_thanksgiving_is_a_holiday_and_the_early_close_counts(self):
        from bot_program.orcs.sessions import next_shut
        wed = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)       # EST
        s = next_shut("stock", "AAPL", wed)
        self.assertEqual(s["at"], datetime(2026, 11, 25, 21, 0, tzinfo=UTC))
        self.assertEqual(s["reopens"],
                         datetime(2026, 11, 27, 14, 30, tzinfo=UTC))
        self.assertEqual(s["kind"], "holiday")
        self.assertEqual(s["hours"], 41.5)
        fri = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
        early = next_shut("stock", "AAPL", fri)
        self.assertEqual(early["at"],
                         datetime(2026, 11, 27, 18, 0, tzinfo=UTC),
                         "the 13:00 New York early close")
        self.assertEqual(early["kind"], "weekend")
        thu = datetime(2026, 11, 26, 16, 0, tzinfo=UTC)
        on_the_day = next_shut("stock", "AAPL", thu)
        self.assertTrue(on_the_day["now_shut"])
        self.assertEqual(on_the_day["kind"], "holiday")

    def test_forex_shuts_on_friday_only(self):
        from bot_program.orcs.sessions import next_shut, shuts_within
        s = next_shut("forex", "EURUSD", WED)
        self.assertEqual(s["at"], datetime(2026, 10, 16, 21, 0, tzinfo=UTC))
        self.assertEqual(s["reopens"],
                         datetime(2026, 10, 18, 21, 0, tzinfo=UTC))
        self.assertEqual(s["kind"], "weekend")
        self.assertEqual(len(shuts_within("forex", "EURUSD", WED, hours=72)),
                         1, "no overnight shut in the FX week")

    def test_cme_metals_daily_break_is_a_break(self):
        from bot_program.orcs.sessions import next_shut
        s = next_shut("commodity", "XAUUSD", WED)
        self.assertEqual(s["session"], "CME")
        self.assertEqual(s["at"], datetime(2026, 10, 14, 21, 0, tzinfo=UTC))
        self.assertEqual(s["reopens"],
                         datetime(2026, 10, 14, 22, 0, tzinfo=UTC))
        self.assertEqual(s["kind"], "break")
        self.assertEqual(s["hours"], 1.0)

    def test_crypto_never_shuts(self):
        from bot_program.orcs.sessions import next_shut, shuts_within
        self.assertIsNone(next_shut("crypto", "BTCUSD", WED))
        self.assertEqual(shuts_within("crypto", "BTCUSD", WED, hours=720), [])

    def test_an_unmodelled_class_says_so(self):
        from bot_program.orcs.sessions import next_shut, shuts_within
        self.assertEqual(next_shut("cfd", "XYZ", WED), {"modelled": False})
        self.assertEqual(next_shut("", "XYZ", WED), {"modelled": False})
        self.assertEqual(shuts_within("cfd", "XYZ", WED, hours=72), [])

    def test_shuts_within_lists_each_shut(self):
        from bot_program.orcs.sessions import shuts_within
        shuts = shuts_within("stock", "AAPL", WED, hours=72)
        self.assertEqual([s["kind"] for s in shuts],
                         ["overnight", "overnight", "weekend"])
        self.assertEqual([s["at"].day for s in shuts], [14, 15, 16])
        self.assertEqual(shuts_within("stock", "AAPL", WED, hours=1), [],
                         "nothing shuts in the next hour")


class TheNextCloseTests(SimpleTestCase):

    CASES = (
        ("stock", "NASDAQ", "AAPL", WED),
        ("stock", "", "AAPL", datetime(2026, 11, 27, 15, 0, tzinfo=UTC)),
        ("stock", "LSE", "VOD", WED),
        ("forex", "", "EURUSD", WED),
        ("forex", "", "EURUSD", datetime(2026, 12, 2, 12, 0, tzinfo=UTC)),
        ("commodity", "", "XAUUSD", WED),
        ("commodity", "", "WHEATUSD", WED),
        ("commodity", "", "COTTONUSD", WED),
        ("index", "", "SPX500", WED),
        ("stock", "", "AAPL", datetime(2026, 10, 17, 12, 0, tzinfo=UTC)),
    )

    def test_next_close_agrees_with_market_clock(self):
        from core.exchange_status import market_clock, next_close_utc
        minute = timedelta(minutes=1)
        for cls, exchange, symbol, now in self.CASES:
            with self.subTest(cls=cls, symbol=symbol, now=now):
                close = next_close_utc(cls, exchange, symbol, now)
                self.assertIsNotNone(close)
                self.assertGreater(close, now)
                self.assertTrue(market_clock(cls, exchange, symbol,
                                             now_utc=close - minute)["is_open"],
                                "open one minute before")
                self.assertFalse(market_clock(cls, exchange, symbol,
                                              now_utc=close + minute)["is_open"],
                                 "shut one minute after")

    def test_crypto_and_unmodelled_have_no_close(self):
        from core.exchange_status import next_close_utc
        self.assertIsNone(next_close_utc("crypto", "", "BTCUSD", WED))
        self.assertIsNone(next_close_utc("cfd", "", "XYZ", WED))

    def test_market_clock_itself_is_untouched(self):
        """The helper is additive: market_clock's answer for a known instant
        is the one it gave before O1."""
        from core.exchange_status import market_clock
        c = market_clock("stock", "", "AAPL", now_utc=WED)
        self.assertEqual((c["is_open"], c["session"], c["modelled"]),
                         (True, "NYSE", True))
        self.assertEqual(c["opened"],
                         datetime(2026, 10, 14, 13, 30, tzinfo=UTC))


class TheSourcePinTests(SimpleTestCase):

    def test_sessions_never_reads_is_weekend_window(self):
        import inspect

        from bot_program.orcs import sessions
        src = inspect.getsource(sessions)
        self.assertNotIn("is_weekend_window", src)
        self.assertIn("market_clock", src)
