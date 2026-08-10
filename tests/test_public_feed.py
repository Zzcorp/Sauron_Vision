"""Keyless market data for every asset class.

Requiring broker credentials for BARS was a structural dead end: no keys
meant no bars, no bars meant no indicators and no rule could fire, so the
platform could not produce the evidence that would justify opening a broker
account. Crypto escaped it because Binance klines are public — which made
crypto look like the only asset class the platform supported, when in fact
stock, forex and commodity bots all existed and were merely starved.

These tests use a fake yfinance rather than the network, so they assert the
translation logic — which is where this silently fails — not Yahoo's uptime.

Run with:  python manage.py test tests.test_public_feed
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase


def _frame(n=100, start="2026-01-01", freq="1h", price=100.0):
    import pandas as pd
    idx = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "Open": [price + i for i in range(n)],
        "High": [price + i + 1 for i in range(n)],
        "Low": [price + i - 1 for i in range(n)],
        "Close": [price + i + 0.5 for i in range(n)],
        "Volume": [1000] * n,
    }, index=idx)


class SymbolMappingTests(SimpleTestCase):
    """A wrong mapping returns an EMPTY FRAME rather than an error, which is
    indistinguishable from 'this instrument has no history' — so the mapping
    is exactly the thing worth pinning."""

    def test_commodities_map_to_front_month_futures(self):
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("XAUUSD", "commodity"), "GC=F")
        self.assertEqual(yf_symbol("WTIUSD", "commodity"), "CL=F")
        self.assertEqual(yf_symbol("HGUSD", "commodity"), "HG=F")

    def test_forex_pairs_get_the_yahoo_suffix(self):
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("EURUSD", "forex"), "EURUSD=X")
        self.assertEqual(yf_symbol("USDJPY", "forex"), "USDJPY=X")

    def test_indices_map_to_carets(self):
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("SPX", "index"), "^GSPC")

    def test_equities_pass_through_unchanged(self):
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("AAPL", "stock"), "AAPL")

    def test_a_six_letter_equity_is_not_mistaken_for_a_pair(self):
        """The =X suffix is applied on asset_class, not on shape — GOOGL is
        five letters but a six-letter ticker exists and must not become FX."""
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("ABCDEF", "stock"), "ABCDEF")


class IntervalTests(SimpleTestCase):
    """Yahoo has no 4h bar, and 4h is the timeframe the whole rule layer
    reads. 1h is fetched and resampled."""

    def _feed_with(self, df):
        fake_yf = MagicMock()
        fake_yf.Ticker.return_value.history.return_value = df
        return fake_yf

    def test_a_four_hour_request_resamples_from_one_hour(self):
        from market_data.public_feed import YFinanceFeed
        df = _frame(n=40, freq="1h")
        fake = self._feed_with(df)
        with patch.dict("sys.modules", {"yfinance": fake}):
            rows = YFinanceFeed("stock").klines("AAPL", interval="4h", limit=100)
        fake.Ticker.return_value.history.assert_called_once()
        self.assertEqual(fake.Ticker.return_value.history.call_args
                         .kwargs["interval"], "1h")
        self.assertEqual(len(rows), 10)      # 40 hourly bars -> 10 four-hour

    def test_a_resampled_candle_aggregates_its_hours_exactly(self):
        from market_data.public_feed import YFinanceFeed
        df = _frame(n=4, freq="1h")
        with patch.dict("sys.modules", {"yfinance": self._feed_with(df)}):
            rows = YFinanceFeed("stock").klines("AAPL", interval="4h", limit=10)
        self.assertEqual(len(rows), 1)
        _ts, o, h, l, c, _v = rows[0]
        self.assertAlmostEqual(float(o), float(df["Open"].iloc[0]), places=6)
        self.assertAlmostEqual(float(h), float(df["High"].max()), places=6)
        self.assertAlmostEqual(float(l), float(df["Low"].min()), places=6)
        self.assertAlmostEqual(float(c), float(df["Close"].iloc[-1]), places=6)

    def test_a_native_interval_is_not_resampled(self):
        from market_data.public_feed import YFinanceFeed
        fake = self._feed_with(_frame(n=10, freq="1h"))
        with patch.dict("sys.modules", {"yfinance": fake}):
            rows = YFinanceFeed("stock").klines("AAPL", interval="1h", limit=50)
        self.assertEqual(len(rows), 10)

    def test_an_empty_frame_yields_no_rows_rather_than_raising(self):
        import pandas as pd
        from market_data.public_feed import YFinanceFeed
        with patch.dict("sys.modules", {"yfinance": self._feed_with(pd.DataFrame())}):
            self.assertEqual(
                YFinanceFeed("stock").klines("NOPE", interval="4h"), [])

    def test_rows_are_binance_shaped(self):
        """bot_bars._upsert_rows consumes Binance kline rows; the feed must
        speak that shape or nothing downstream needs to know the venue."""
        from market_data.public_feed import YFinanceFeed
        with patch.dict("sys.modules", {"yfinance": self._feed_with(_frame(n=4))}):
            rows = YFinanceFeed("stock").klines("AAPL", interval="4h")
        self.assertEqual(len(rows[0]), 6)
        self.assertIsInstance(rows[0][0], int)          # open time, epoch ms


class FeedSelectionTests(SimpleTestCase):
    def test_crypto_uses_the_execution_venue(self):
        from market_data.public_feed import public_feed_for
        self.assertEqual(type(public_feed_for("crypto")).__name__,
                         "BinanceClient")

    def test_the_other_tradeable_classes_get_a_feed(self):
        from market_data.public_feed import public_feed_for
        for ac in ("stock", "etf", "index", "commodity", "forex"):
            self.assertIsNotNone(public_feed_for(ac), msg=ac)

    def test_options_have_no_keyless_feed(self):
        """Deliberate: there is no free option-chain source worth trusting,
        and options route exclusively through IBKR."""
        from market_data.public_feed import public_feed_for
        self.assertIsNone(public_feed_for("options"))

    def test_every_public_feed_is_tagged_as_such(self):
        """bot_bars stamps the source from this flag, so a data-only bar is
        never confused with one from the venue an order filled on."""
        from market_data.public_feed import public_feed_for
        for ac in ("crypto", "stock", "forex", "commodity"):
            self.assertTrue(getattr(public_feed_for(ac), "_sv_public_feed", False),
                            msg=ac)


class BarsWithoutCredentialsTests(TestCase):
    def test_a_paper_stock_config_gets_a_market_data_client(self):
        """The whole point: no broker account, and bars still arrive."""
        from decimal import Decimal
        from django.contrib.auth.models import User
        from bot_program.models import AssetBotConfig
        from market_data.bot_bars import _client_for

        user = User.objects.create_user(username="pf_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="PF", mode="paper",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        client = _client_for(user, "AAPL", cfg)
        self.assertIsNotNone(
            client, "a stock config still cannot get bars without a broker")
        self.assertTrue(getattr(client, "_sv_public_feed", False))
