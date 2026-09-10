"""One keyless download per symbol per pass, sized to what is kept.

Yahoo has no 4h bar, so 4h is resampled from 1h — and the first version
asked for the full 730-day hourly window, twice per symbol per pass (once
per interval), to keep 200 rows of it. A research fleet of 150 symbols
would have made that 300 two-year downloads every ten minutes, and Yahoo
cuts off a burst. Three changes, each pinned here: the window is sized
from the bars the caller keeps; the fetched frame is remembered for a few
minutes so the 1h request reuses the 4h download; and the bar writer asks
for the larger interval first and breathes between symbols.

Run with:  python manage.py test tests.test_public_feed_cost
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


def _frame(n=100, start="2026-01-01", freq="1h", price=100.0):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"Open": price, "High": price + 1, "Low": price - 1,
                         "Close": price, "Volume": 1000}, index=idx)


def _fake_yf(df):
    fake = MagicMock()
    fake.Ticker.return_value.history.return_value = df
    return fake


class TheWindowIsSizedToWhatIsKeptTests(SimpleTestCase):

    def test_two_hundred_hourly_bars_do_not_need_two_years(self):
        from market_data.public_feed import days_for
        self.assertLess(days_for("1h", 200), 100)
        self.assertGreaterEqual(days_for("1h", 200), 40)

    def test_two_hundred_four_hour_bars_need_more_and_stay_under_the_cap(self):
        from market_data.public_feed import days_for
        d = days_for("4h", 200)
        self.assertGreater(d, days_for("1h", 200))
        self.assertGreaterEqual(d, 150)
        self.assertLessEqual(d, 730)

    def test_daily_bars_and_the_ten_year_cap(self):
        from market_data.public_feed import days_for, period_for
        self.assertEqual(period_for(days_for("1d", 300)), "488d")
        self.assertEqual(period_for(days_for("1d", 3000)), "10y")

    def test_no_limit_means_the_whole_window(self):
        from market_data.public_feed import days_for
        self.assertEqual(days_for("1h", 0), 730)
        self.assertEqual(days_for("5m", None), 60)

    def test_the_request_carries_the_sized_period(self):
        from market_data.public_feed import YFinanceFeed, clear_frame_memo
        clear_frame_memo()
        fake = _fake_yf(_frame(n=40))
        with patch.dict("sys.modules", {"yfinance": fake}):
            YFinanceFeed("stock").klines("AAPL", interval="1h", limit=200)
        period = fake.Ticker.return_value.history.call_args.kwargs["period"]
        self.assertTrue(period.endswith("d"))
        self.assertLess(int(period[:-1]), 100)


class TheFrameIsRememberedTests(SimpleTestCase):

    def setUp(self):
        from market_data.public_feed import clear_frame_memo
        clear_frame_memo()

    def test_the_hourly_request_reuses_the_four_hour_download(self):
        from market_data.public_feed import YFinanceFeed
        fake = _fake_yf(_frame(n=800))
        with patch.dict("sys.modules", {"yfinance": fake}):
            feed = YFinanceFeed("stock")
            four = feed.klines("AAPL", interval="4h", limit=200)
            one = feed.klines("AAPL", interval="1h", limit=200)
        fake.Ticker.return_value.history.assert_called_once()
        self.assertEqual(len(four), 200)
        self.assertEqual(len(one), 200)

    def test_a_smaller_download_does_not_serve_a_larger_request(self):
        """1h first would remember a short window; 4h then needs more."""
        from market_data.public_feed import YFinanceFeed
        fake = _fake_yf(_frame(n=800))
        with patch.dict("sys.modules", {"yfinance": fake}):
            feed = YFinanceFeed("stock")
            feed.klines("AAPL", interval="1h", limit=200)
            feed.klines("AAPL", interval="4h", limit=200)
        self.assertEqual(fake.Ticker.return_value.history.call_count, 2)

    def test_another_symbol_is_its_own_download(self):
        from market_data.public_feed import YFinanceFeed
        fake = _fake_yf(_frame(n=800))
        with patch.dict("sys.modules", {"yfinance": fake}):
            feed = YFinanceFeed("stock")
            feed.klines("AAPL", interval="4h", limit=200)
            feed.klines("MSFT", interval="4h", limit=200)
        self.assertEqual(fake.Ticker.return_value.history.call_count, 2)

    def test_the_memo_expires(self):
        from market_data import public_feed
        fake = _fake_yf(_frame(n=800))
        with patch.dict("sys.modules", {"yfinance": fake}):
            feed = public_feed.YFinanceFeed("stock")
            feed.klines("AAPL", interval="4h", limit=200)
            with patch.object(public_feed.time, "monotonic",
                              return_value=public_feed.time.monotonic()
                              + public_feed.FRAME_MEMO_S + 1):
                feed.klines("AAPL", interval="1h", limit=200)
        self.assertEqual(fake.Ticker.return_value.history.call_count, 2)

    def test_an_empty_answer_is_not_remembered(self):
        from market_data.public_feed import YFinanceFeed
        fake = _fake_yf(pd.DataFrame())
        with patch.dict("sys.modules", {"yfinance": fake}):
            feed = YFinanceFeed("stock")
            feed.klines("NOPE", interval="4h", limit=200)
            feed.klines("NOPE", interval="1h", limit=200)
        self.assertEqual(fake.Ticker.return_value.history.call_count, 2)


class TheWriterBreathesTests(TestCase):

    def test_the_larger_interval_is_asked_first(self):
        from market_data.bot_bars import DEFAULT_INTERVALS
        self.assertEqual(DEFAULT_INTERVALS[0], "4h")

    def _cfg(self, symbols):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        user = User.objects.create_user("pace_u", password="x")
        for s in symbols:
            Instrument.objects.get_or_create(
                symbol=s, defaults={"name": s, "asset_class": "stock"})
        return AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="PACE", mode="paper",
            symbols=list(symbols), capital=Decimal("1000"), enabled=True)

    def test_it_breathes_once_per_symbol_on_the_keyless_feed(self):
        from market_data.bot_bars import refresh_bars_for_config
        cfg = self._cfg(["AAPL", "MSFT", "NVDA"])
        client = MagicMock()
        client._sv_public_feed = True
        client.klines.return_value = []
        with patch("market_data.bot_bars._client_for", return_value=client), \
                patch("market_data.bot_bars._pace") as pace:
            refresh_bars_for_config(cfg, intervals=("4h",), limit=3)
        self.assertEqual(pace.call_count, 3)

    def test_a_broker_venue_is_not_paced(self):
        from market_data.bot_bars import refresh_bars_for_config
        cfg = self._cfg(["AAPL"])
        client = MagicMock()
        client._sv_public_feed = False
        client.klines.return_value = [[1_756_000_000_000, "1", "1", "1",
                                       "1", "1"]]
        with patch("market_data.bot_bars._client_for", return_value=client), \
                patch("market_data.bot_bars._pace") as pace:
            refresh_bars_for_config(cfg, intervals=("4h",), limit=3)
        pace.assert_not_called()
