"""What LiveQuote.change_pct means, and who is allowed to write it.

The column is day-scale everywhere it is produced by a poller — yfinance
stores regularMarketChangePercent, Binance the 24h figure, CoinGecko
usd_24h_change — and day-scale everywhere it is read: /instruments/ buckets
gainers and losers on it, and the morning briefing takes its "top movers"
from an order_by on it.

The two tick streamers wrote something else entirely into it: the move since
the PREVIOUS PRINT, a sub-second jitter whose sign is essentially random.
Nothing could tell the two meanings apart. A stock down 3% on the session
was filed as a gainer because its last trade ticked up a cent, and the
pollers could not correct it because the live stream held the row for its
full precedence hold while a 60-second poll kept being refused. The
briefing's biggest movers became whichever symbols were NOT being streamed.

A trade print carries no change figure, so the streamers now measure against
the previous session's close, and write nothing at all when there is no
daily bar to measure from — leaving the column to whoever can produce it.

Run with:  python manage.py test tests.test_stream_change_scale
"""
from datetime import timedelta
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    return Instrument.objects.create(
        symbol=symbol, name=symbol, asset_class=asset_class)


def _daily_bar(inst, close, *, days_ago=1):
    from market_data.models import PriceData
    midnight = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return PriceData.objects.create(
        instrument=inst, timeframe="1d",
        timestamp=midnight - timedelta(days=days_ago),
        open=Decimal(str(close)), high=Decimal(str(close)),
        low=Decimal(str(close)), close=Decimal(str(close)),
        volume=1000, source="test")


def _quote(inst, *, last, change_pct, source):
    from market_data.models import LiveQuote
    return LiveQuote.objects.create(
        instrument=inst, last=Decimal(str(last)),
        change_pct=Decimal(str(change_pct)), source=source)


class QuoteScaleTestCase(TestCase):
    def setUp(self):
        from market_data.quotes import _PREV_CLOSE_CACHE
        # Process-local read cache in front of an immutable bar; instrument
        # ids are recycled between tests, so it must not carry over.
        _PREV_CLOSE_CACHE.clear()
        self.addCleanup(_PREV_CLOSE_CACHE.clear)


class SessionChangeTests(QuoteScaleTestCase):
    def setUp(self):
        super().setUp()
        self.inst = _instrument()

    def test_a_print_is_measured_against_the_last_session_close(self):
        from market_data.quotes import session_change_pct
        _daily_bar(self.inst, 100)
        self.assertAlmostEqual(session_change_pct(self.inst, 103.0), 3.0, places=6)

    def test_no_daily_bar_means_no_answer_rather_than_zero(self):
        from market_data.quotes import session_change_pct
        self.assertIsNone(session_change_pct(self.inst, 103.0))

    def test_todays_own_bar_is_not_mistaken_for_the_previous_close(self):
        """An in-progress daily row would make every print read ~0% and
        wipe the real session move off the movers screen."""
        from market_data.quotes import session_change_pct
        _daily_bar(self.inst, 103, days_ago=0)
        self.assertIsNone(session_change_pct(self.inst, 103.0))

    def test_a_zero_or_absent_close_is_not_divided_by(self):
        from market_data.quotes import session_change_pct
        _daily_bar(self.inst, 0)
        self.assertIsNone(session_change_pct(self.inst, 103.0))


class FinnhubStreamTests(QuoteScaleTestCase):
    def setUp(self):
        super().setUp()
        self.inst = _instrument()

    def _live(self):
        from market_data.models import LiveQuote
        return LiveQuote.objects.get(instrument=self.inst)

    def test_a_streamed_tick_reports_the_session_move_not_the_tick_move(self):
        from market_data.management.commands.stream_finnhub import (
            update_live_quote,
        )
        _daily_bar(self.inst, 100)
        _quote(self.inst, last=102.99, change_pct=Decimal("2.99"),
               source="yfinance")

        async_to_sync(update_live_quote)("AAPL", 103.0, 10)

        row = self._live()
        self.assertEqual(row.last, Decimal("103.00000000"))
        self.assertEqual(row.change_pct, Decimal("3.0000"))

    def test_a_down_day_is_not_reclassified_as_a_gainer_by_one_uptick(self):
        from market_data.management.commands.stream_finnhub import (
            update_live_quote,
        )
        _daily_bar(self.inst, 100)
        _quote(self.inst, last=96.99, change_pct=Decimal("-3.01"),
               source="yfinance")

        async_to_sync(update_live_quote)("AAPL", 97.0, 5)

        self.assertLess(self._live().change_pct, 0)

    def test_with_no_daily_bar_the_pollers_figure_survives_the_stream(self):
        from market_data.management.commands.stream_finnhub import (
            update_live_quote,
        )
        _quote(self.inst, last=102.99, change_pct=Decimal("-3.2000"),
               source="yfinance")

        async_to_sync(update_live_quote)("AAPL", 103.0, 10)

        row = self._live()
        self.assertEqual(row.last, Decimal("103.00000000"))
        self.assertEqual(row.change_pct, Decimal("-3.2000"))

    def test_the_stream_is_stamped_at_the_tier_reserved_for_it(self):
        """'finnhub' is absent from SOURCE_PRIORITY, so a real-time trade
        print used to rank at the anonymous default; 'finnhub_ws' is the
        row the table has always had for it."""
        from market_data.management.commands.stream_finnhub import (
            update_live_quote,
        )
        from market_data.quotes import SOURCE_PRIORITY

        async_to_sync(update_live_quote)("AAPL", 103.0, 10)

        self.assertEqual(self._live().source, "finnhub_ws")
        self.assertIn("finnhub_ws", SOURCE_PRIORITY)

    def test_a_symbol_with_no_instrument_is_dropped_not_crashed(self):
        from market_data.management.commands.stream_finnhub import (
            update_live_quote,
        )
        from market_data.models import LiveQuote

        async_to_sync(update_live_quote)("NOSUCH", 103.0, 10)
        self.assertEqual(LiveQuote.objects.count(), 0)


class OandaStreamTests(QuoteScaleTestCase):
    def setUp(self):
        super().setUp()
        self.inst = _instrument("EURUSD", asset_class="forex")

    def test_a_streamed_pair_reports_the_session_move(self):
        from market_data.management.commands.stream_oanda import (
            update_live_quote,
        )
        from market_data.models import LiveQuote

        _daily_bar(self.inst, "1.10000")
        async_to_sync(update_live_quote)("EUR_USD", 1.1109, 1.1111)

        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(row.source, "oanda_stream")
        self.assertAlmostEqual(float(row.change_pct), 1.0, places=3)

    def test_with_no_daily_bar_the_pair_keeps_the_pollers_figure(self):
        from market_data.management.commands.stream_oanda import (
            update_live_quote,
        )
        from market_data.models import LiveQuote

        _quote(self.inst, last="1.1000", change_pct=Decimal("-0.4500"),
               source="yfinance")
        async_to_sync(update_live_quote)("EUR_USD", 1.1109, 1.1111)

        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(row.change_pct, Decimal("-0.4500"))
