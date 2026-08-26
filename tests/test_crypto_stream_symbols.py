"""What the Binance streamers actually subscribe to.

All three workers discovered their symbols by FILTERING the crypto
catalogue on Binance's quote assets — keeping only rows already spelled
*USDT (or *BUSD/*USDC/*BTC) — and instruments/services.py seeds every one
of the fifteen crypto rows as *USD. The filter therefore matched nothing,
ever, and each worker fell through to its hardcoded defaults on every
sixty-second refresh:

  * twelve of the fifteen instruments never received a real-time tick, so
    a bot on LINKUSD marked against the five-minute REST poll while the
    operator believed the stream covered the catalogue;
  * one of the four ticker subscriptions was spent on BNBUSDT, which has
    no Instrument row at all, so every tick it produced was dropped;
  * the documented "refreshes its symbol list every 60s so new watchlist
    entries are picked up without a restart" could never take effect;
  * FundingRate and LiquidationEvent were pinned to three symbols and
    OrderBookSnapshot to two, whatever the operator held.

Nothing logged, and "connecting to 4 stream(s)" looked like health.

Run with:  python manage.py test tests.test_crypto_stream_symbols
"""
from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase

CATALOGUE = ["BTCUSD", "ETHUSD", "SOLUSD", "LINKUSD", "MATICUSD"]


def _crypto(symbols=CATALOGUE):
    from instruments.models import Instrument
    for sym in symbols:
        Instrument.objects.get_or_create(
            symbol=sym, defaults={"name": sym, "asset_class": "crypto"})


class TranslationTests(SimpleTestCase):
    def test_catalogue_spelling_is_translated_not_discarded(self):
        from market_data.management.commands.stream_binance import binance_symbols
        self.assertEqual(binance_symbols(["BTCUSD", "ETHUSD"]),
                         ["BTCUSDT", "ETHUSDT"])

    def test_venue_spelling_survives_unchanged(self):
        from market_data.management.commands.stream_binance import binance_symbols
        self.assertEqual(binance_symbols(["BTCUSDT"]), ["BTCUSDT"])

    def test_separators_the_catalogue_may_carry_are_normalised(self):
        from market_data.management.commands.stream_binance import binance_symbols
        self.assertEqual(binance_symbols(["BTC/USD", "eth-usd", "SOL_USD"]),
                         ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    def test_a_symbol_with_no_binance_pair_is_dropped_and_named(self):
        from market_data.management.commands.stream_binance import binance_symbols
        with self.assertLogs("stream_binance", level="WARNING") as logs:
            self.assertEqual(binance_symbols(["XAUUSD1", "BTCUSD"]), ["BTCUSDT"])
        self.assertIn("XAUUSD1", "".join(logs.output))

    def test_duplicate_spellings_collapse_to_one_subscription(self):
        from market_data.management.commands.stream_binance import binance_symbols
        self.assertEqual(binance_symbols(["BTCUSD", "BTCUSDT", "btc/usd"]),
                         ["BTCUSDT"])

    def test_futures_takes_usdt_perps_only(self):
        from market_data.management.commands.stream_binance import binance_symbols
        from market_data.management.commands.stream_binance_futures import (
            FUTURES_QUOTE_ASSETS,
        )
        self.assertEqual(
            binance_symbols(["BTCUSD", "ETHBTC"], FUTURES_QUOTE_ASSETS),
            ["BTCUSDT"])


class DiscoveryTests(TestCase):
    def setUp(self):
        _crypto()

    def test_the_ticker_stream_covers_the_whole_crypto_catalogue(self):
        from market_data.management.commands.stream_binance import discover_symbols
        found = async_to_sync(discover_symbols)(None)
        self.assertEqual(
            sorted(found),
            ["BTCUSDT", "ETHUSDT", "LINKUSDT", "MATICUSDT", "SOLUSDT"])

    def test_the_ticker_stream_no_longer_falls_back_to_bnb(self):
        """BNBUSDT has no Instrument row, so every tick it produced was
        dropped by write_quote — a wasted subscription that looked live."""
        from market_data.management.commands.stream_binance import discover_symbols
        self.assertNotIn("BNBUSDT", async_to_sync(discover_symbols)(None))

    def test_funding_and_liquidations_follow_the_catalogue(self):
        from market_data.management.commands.stream_binance_futures import (
            discover_symbols,
        )
        found = async_to_sync(discover_symbols)(None)
        self.assertIn("LINKUSDT", found)
        self.assertEqual(len(found), len(CATALOGUE))

    def test_the_order_book_follows_the_catalogue(self):
        from market_data.management.commands.stream_binance_depth import (
            discover_symbols,
        )
        found = async_to_sync(discover_symbols)(None)
        self.assertIn("SOLUSDT", found)
        self.assertEqual(len(found), len(CATALOGUE))

    def test_the_order_book_stays_within_its_subscription_cap(self):
        """depth20@100ms is a firehose; the cap bounds the socket and the
        write rate, and a catalogue that grows must not quietly remove it."""
        from market_data.management.commands.stream_binance_depth import (
            MAX_DEPTH_SYMBOLS, discover_symbols,
        )
        _crypto([f"AA{i:02d}USD" for i in range(MAX_DEPTH_SYMBOLS + 5)])
        found = async_to_sync(discover_symbols)(None)
        self.assertEqual(len(found), MAX_DEPTH_SYMBOLS)

    def test_an_explicit_symbol_list_is_taken_as_given(self):
        from market_data.management.commands.stream_binance import discover_symbols
        self.assertEqual(async_to_sync(discover_symbols)(["dogeusdt"]),
                         ["DOGEUSDT"])

    def test_an_empty_catalogue_still_streams_something_and_says_so(self):
        from instruments.models import Instrument
        from market_data.management.commands.stream_binance import (
            DEFAULT_SYMBOLS, discover_symbols,
        )
        Instrument.objects.all().delete()
        with self.assertLogs("stream_binance", level="WARNING") as logs:
            found = async_to_sync(discover_symbols)(None)
        self.assertEqual(found, DEFAULT_SYMBOLS)
        self.assertIn("cannot be stored", "".join(logs.output))


class DepthCapKeepsTheDeepestBooksTests(TestCase):
    """The depth worker books at most MAX_DEPTH_SYMBOLS order books.

    Something has to be dropped once the catalogue outgrows that, and
    alphabetical order drops exactly the wrong things: AAVE, ADA, ATOM
    and AVAX all sort ahead of BTC. Fifteen crypto rows fit today, so
    nothing is cut — but the first person to widen the watchlist would
    silently lose the order book for the two symbols this worker exists
    to measure, and depth feeds a liquidity score.
    """

    def test_the_majors_lead_however_the_catalogue_sorts(self):
        from market_data.management.commands.stream_binance_depth import (
            _by_depth_priority,
        )
        out = _by_depth_priority(
            ["AAVEUSDT", "ADAUSDT", "ETHUSDT", "ATOMUSDT", "BTCUSDT"])
        self.assertEqual(out[:2], ["BTCUSDT", "ETHUSDT"])

    def test_the_remainder_stays_deterministic(self):
        """Stable order, so a restart books the same books."""
        from market_data.management.commands.stream_binance_depth import (
            _by_depth_priority,
        )
        pairs = ["ZILUSDT", "AAVEUSDT", "ADAUSDT"]
        self.assertEqual(_by_depth_priority(pairs),
                         _by_depth_priority(list(reversed(pairs))))
        self.assertEqual(_by_depth_priority(pairs),
                         ["AAVEUSDT", "ADAUSDT", "ZILUSDT"])

    def test_a_truncated_booking_says_what_it_dropped(self):
        """A silent truncation reads as 'we booked everything' — which is
        how the original filter hid for as long as it did."""
        from asgiref.sync import async_to_sync
        from django.test import override_settings  # noqa: F401

        from instruments.models import Instrument
        from market_data.management.commands import stream_binance_depth as d

        Instrument.objects.all().delete()
        for i in range(d.MAX_DEPTH_SYMBOLS + 3):
            Instrument.objects.create(
                symbol=f"AA{i:02d}USD", name=f"Coin {i}",
                asset_class="crypto", is_active=True)
        Instrument.objects.create(symbol="BTCUSD", name="Bitcoin",
                                  asset_class="crypto", is_active=True)

        with self.assertLogs("stream_binance_depth", level="WARNING") as logs:
            found = async_to_sync(d.discover_symbols)(None)

        self.assertEqual(len(found), d.MAX_DEPTH_SYMBOLS)
        self.assertIn("BTCUSDT", found, "the cap dropped a major")
        self.assertIn("dropping", "".join(logs.output))
