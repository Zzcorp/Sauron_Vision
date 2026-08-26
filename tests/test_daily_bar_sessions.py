"""Which calendar day a daily bar claims to be.

yfinance localises a NON-INTRADAY index to the EXCHANGE's timezone at local
midnight. For every exchange east of UTC that midnight lands on the PREVIOUS
UTC calendar day, and the adapter wrote the raw index straight into
PriceData.timestamp — so ^N225's Monday session was filed as Sunday
15:00Z and ^GDAXI's as Sunday 22:00Z, on the whole yfinance universe that
fetch_eod_all_instruments polls (Nikkei, Hang Seng, ASX, DAX, FTSE, CAC,
IBEX, STOXX, and EURUSD=X).

Nothing raised. What broke instead:

  * a day_of_week seasonal setup read Sunday for a Monday bar, so it
    measured Tuesday's sessions and traded them as Monday's edge;
  * two daily frames from different exchanges intersected on zero exact
    timestamps, so anything aligning them silently found nothing;
  * an as-of replay bounded by `timestamp__lte` was handed a session that
    had not closed at the instant being replayed.

Daily rows now carry midnight UTC of the session's own date, which is what
every other daily writer stores. Intraday rows are real instants and are
left exactly as they arrive.

Run with:  python manage.py test tests.test_daily_bar_sessions
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

# Monday. Tokyo opens it at 2026-08-24 00:00+09:00, i.e. Sunday 15:00Z.
SESSION_DAY = "2026-08-24"


def _frame(start=SESSION_DAY, periods=3, freq="1D", tz="Asia/Tokyo"):
    import pandas as pd
    idx = pd.date_range(start=start, periods=periods, freq=freq, tz=tz)
    return pd.DataFrame({
        "Open": [100.0 + i for i in range(periods)],
        "High": [101.0 + i for i in range(periods)],
        "Low": [99.0 + i for i in range(periods)],
        "Close": [100.5 + i for i in range(periods)],
        "Volume": [1000] * periods,
    }, index=idx)


def _ticker(frame):
    ticker = MagicMock()
    ticker.history = MagicMock(return_value=frame)
    return ticker


class SessionStampTests(SimpleTestCase):
    def test_a_tokyo_session_keeps_its_own_calendar_day(self):
        import pandas as pd
        from market_data.adapters.yfinance_adapter import session_timestamp

        stamp = session_timestamp(
            pd.Timestamp(SESSION_DAY, tz="Asia/Tokyo"), "1d")
        self.assertEqual(stamp.strftime("%Y-%m-%d"), SESSION_DAY)
        self.assertEqual(stamp.utcoffset().total_seconds(), 0)

    def test_the_weekday_a_seasonal_bucket_reads_is_the_sessions_own(self):
        import pandas as pd
        from market_data.adapters.yfinance_adapter import session_timestamp

        raw = pd.Timestamp(SESSION_DAY, tz="Asia/Tokyo")
        self.assertEqual(raw.tz_convert("UTC").strftime("%A"), "Sunday")
        self.assertEqual(
            session_timestamp(raw, "1d").strftime("%A"), "Monday")

    def test_two_exchanges_daily_bars_land_on_the_same_instant(self):
        """SMT and every other cross-market alignment intersects on exact
        timestamps; a Tokyo bar and a Frankfurt bar for the same session
        used to share none."""
        import pandas as pd
        from market_data.adapters.yfinance_adapter import session_timestamp

        tokyo = session_timestamp(pd.Timestamp(SESSION_DAY, tz="Asia/Tokyo"), "1d")
        frankfurt = session_timestamp(
            pd.Timestamp(SESSION_DAY, tz="Europe/Berlin"), "1d")
        new_york = session_timestamp(
            pd.Timestamp(SESSION_DAY, tz="America/New_York"), "1d")
        self.assertEqual({tokyo, frankfurt, new_york}, {tokyo})

    def test_intraday_instants_are_not_rounded_to_a_day(self):
        import pandas as pd
        from market_data.adapters.yfinance_adapter import session_timestamp

        raw = pd.Timestamp("2026-08-24 14:30", tz="America/New_York")
        for interval in ("1h", "30m", "1m"):
            self.assertEqual(session_timestamp(raw, interval), raw)


class DailyWriteTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        self.inst = Instrument.objects.create(
            symbol="NIKKEI225", name="Nikkei 225", asset_class="index")

    def test_the_stored_bar_is_filed_under_the_session_it_describes(self):
        from market_data.adapters.yfinance_adapter import save_history_to_db
        from market_data.models import PriceData

        with patch("market_data.adapters.yfinance_adapter._get_ticker",
                   return_value=_ticker(_frame())):
            self.assertEqual(save_history_to_db("NIKKEI225",
                                                fetch_symbol="^N225"), 3)

        stamps = sorted(PriceData.objects.filter(instrument=self.inst,
                                                 timeframe="1d")
                        .values_list("timestamp", flat=True))
        self.assertEqual([s.strftime("%Y-%m-%d %H:%M") for s in stamps],
                         ["2026-08-24 00:00", "2026-08-25 00:00",
                          "2026-08-26 00:00"])

    def test_a_refetch_updates_the_same_row_rather_than_shadowing_it(self):
        """Two conventions in one table would give a session two rows, and
        every window query would double-count it."""
        from market_data.adapters.yfinance_adapter import save_history_to_db
        from market_data.models import PriceData

        with patch("market_data.adapters.yfinance_adapter._get_ticker",
                   return_value=_ticker(_frame())):
            save_history_to_db("NIKKEI225", fetch_symbol="^N225")
            save_history_to_db("NIKKEI225", fetch_symbol="^N225")

        self.assertEqual(PriceData.objects.filter(instrument=self.inst).count(), 3)


class PublicFeedDailyTests(SimpleTestCase):
    def test_the_keyless_feed_dates_its_daily_klines_the_same_way(self):
        """bot_bars and backfill_bars both read `open_ms` from this feed, so
        a 1d request through it must agree with the EOD adapter."""
        from datetime import datetime, timezone as dt_timezone

        from market_data.public_feed import YFinanceFeed

        module = MagicMock()
        module.Ticker = MagicMock(return_value=_ticker(_frame()))
        with patch.dict("sys.modules", {"yfinance": module}):
            rows = YFinanceFeed("index").klines("NIKKEI225", interval="1d")

        first = datetime.fromtimestamp(rows[0][0] / 1000, tz=dt_timezone.utc)
        self.assertEqual(first.strftime("%Y-%m-%d %H:%M"), "2026-08-24 00:00")
