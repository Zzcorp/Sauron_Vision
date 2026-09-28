"""A broken interval is not a broken mapping.

Measured 2026-09-12: USDCNH=X and CNH=X both serve 1416 hourly rows and
exactly one daily row. The 4h frame resampled from those hourly rows wrote
400 bars in the same pass that wrote 1 daily bar. Before this, the feed
logged "check the symbol mapping" — pointing the next reader at a mapping
that was correct.
"""
from unittest.mock import patch

from django.test import TestCase


class NoDailySeriesTests(TestCase):

    def test_the_two_sets_mean_different_things_and_do_not_overlap(self):
        from market_data.public_feed import YF_NO_DAILY, YF_UNAVAILABLE
        self.assertTrue(YF_NO_DAILY)
        self.assertFalse(
            YF_NO_DAILY & YF_UNAVAILABLE,
            "a symbol in YF_UNAVAILABLE is skipped ENTIRELY; listing it in "
            "YF_NO_DAILY as well would claim its intraday frames work, and "
            "one of the two statements would be false")

    def test_a_no_daily_symbol_still_has_a_correct_mapping(self):
        """The point of the set is that the mapping is NOT the fault."""
        from market_data.public_feed import YF_NO_DAILY, yf_symbol
        for sym in YF_NO_DAILY:
            self.assertTrue(yf_symbol(sym, "forex").endswith("=X"),
                            f"{sym} must still resolve to a real Yahoo "
                            f"spelling — the daily series is what is broken")

    def test_the_daily_fetch_is_refused_by_name_and_not_by_a_404(self):
        from market_data.public_feed import YF_NO_DAILY, YFinanceFeed
        sym = sorted(YF_NO_DAILY)[0]
        feed = YFinanceFeed(asset_class="forex")
        with patch("yfinance.Ticker") as ticker:
            rows = feed.klines(sym, interval="1d", limit=400)
            self.assertEqual(rows, [])
            ticker.assert_not_called()   # refused before the network call

    def test_the_intraday_frame_of_a_no_daily_symbol_is_untouched(self):
        """The 4h frame is resampled from 1h and must still be attempted."""
        from market_data.public_feed import YF_NO_DAILY, YFinanceFeed
        sym = sorted(YF_NO_DAILY)[0]
        feed = YFinanceFeed(asset_class="forex")
        with patch("yfinance.Ticker") as ticker:
            ticker.return_value.history.return_value = None
            feed.klines(sym, interval="4h", limit=400)
            ticker.assert_called()       # 4h is NOT refused

    def test_one_d_is_not_quietly_resampled_from_one_h(self):
        """An FX day closes at 17:00 New York, not at midnight.

        Building a daily bar from hourly closes would produce a different
        object and store it indistinguishably beside native daily bars.
        """
        from market_data.public_feed import RESAMPLE_FROM
        self.assertNotIn("1d", RESAMPLE_FROM)
