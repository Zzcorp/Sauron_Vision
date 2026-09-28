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
        """MATICUSD is in the catalogue but MATICUSDT is not what the stream
        subscribes to: Binance renamed MATIC to POL in September 2024 and
        MATICUSDT stopped answering. `venue_symbol` carries the rename
        (BINANCE_RENAMES in backfill_bars, asserted by
        tests/test_catalogue_spellings), so the correct subscription is
        POLUSDT. This assertion spelled the retired ticker until 2026-09-13,
        which made a working stream look broken."""
        from market_data.management.commands.stream_binance import discover_symbols
        found = async_to_sync(discover_symbols)(None)
        self.assertEqual(
            sorted(found),
            ["BTCUSDT", "ETHUSDT", "LINKUSDT", "POLUSDT", "SOLUSDT"])

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


class BothStreamersRefuseAnEmptySymbolListTests(SimpleTestCase):
    """A subscription to nothing is the quietest failure in this codebase.

    With no symbols, the futures loop's two joins both collapse to "" and the
    url becomes the websocket base plus a bare "/". Binance ACCEPTS that and
    then sends nothing, ever. The container stays Up, reports healthy, never
    disconnects, logs no warning — and FundingRate and LiquidationEvent stay
    empty for as long as it runs.

    Measured on the live box 2026-09-13: `docker logs` on a twelve-minute-old
    stream-binance-futures container returned NOT ONE LINE, while
    `setups diagnose` refused advanced_funding_carry_short on all 15 crypto
    instruments for want of the snapshots that loop is supposed to write.

    `stream_binance.py` already guarded this — "no crypto symbols to stream;
    retrying in 30s" — and its futures sibling, written later, did not. This
    holds the two together so the next streamer added here inherits the
    guard by failing this test rather than by someone remembering.
    """

    STREAMERS = ("stream_binance", "stream_binance_futures")

    def _source(self, name):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "market_data" / "management" /
                "commands" / f"{name}.py").read_text(encoding="utf-8")

    def test_each_streamer_refuses_to_subscribe_to_nothing(self):
        for name in self.STREAMERS:
            with self.subTest(streamer=name):
                src = self._source(name)
                self.assertIn("if not symbols:", src,
                              f"{name} builds a subscription url without "
                              f"checking that it has anything to subscribe to")
                # Wide enough to contain a guard whose warning explains
                # itself: the futures message names the shell command that
                # reproduces the empty discovery, which is worth more than
                # brevity to whoever reads it at 02:00.
                guard = src[src.index("if not symbols:"):][:1200]
                self.assertIn("log.warning", guard,
                              f"{name} skips an empty list silently — the "
                              f"operator learns nothing from an empty table")
                self.assertIn("continue", guard,
                              f"{name} does not retry after an empty list")

    def test_the_futures_connect_line_survives_a_production_log_level(self):
        """core.logging_config puts root at WARNING when DEBUG is off, so an
        INFO line is invisible exactly where it is needed. The one line that
        says what this process subscribed to has to clear that bar; it fires
        once per connection, not per tick."""
        src = self._source("stream_binance_futures")
        self.assertIn('log.warning("futures: connecting for %d symbols', src)
        self.assertNotIn('log.info("futures: connecting', src)


class ARenamedPairComesBackAsTheCatalogueSpellsItTests(TestCase):
    """The MATIC -> POL rename was applied on the way OUT (the stream
    subscribes to polusdt@ticker) and not on the way back IN: every tick
    arrived as POLUSDT, `write_quote` found no Instrument for it and
    dropped it at DEBUG, and the broadcast named a symbol no headband card
    carries. MATICUSD's LiveQuote lived on the five-minute REST sweep while
    a real-time stream ticked for it every second."""

    def setUp(self):
        _crypto()

    def test_the_rename_is_reversed_on_the_way_in(self):
        from market_data.management.commands.backfill_bars import (
            catalogue_symbol, venue_symbol,
        )
        self.assertEqual(catalogue_symbol(venue_symbol("MATICUSD")), "MATICUSD")
        # The stablecoin suffix is write_quote's own business, as before.
        self.assertEqual(catalogue_symbol("BTCUSDT"), "BTCUSDT")

    def test_a_pol_tick_lands_on_the_matic_row(self):
        from market_data.management.commands.backfill_bars import catalogue_symbol
        from market_data.management.commands.stream_binance import update_live_quote
        from market_data.models import LiveQuote
        async_to_sync(update_live_quote)(
            catalogue_symbol("POLUSDT"), 0.41, 1.2, 0.409, 0.411, 1000)
        lq = LiveQuote.objects.get(instrument__symbol="MATICUSD")
        self.assertEqual(lq.source, "binance_ws")

    def test_the_spot_loop_hands_the_row_and_the_headband_the_catalogue_spelling(self):
        """Read off the source: the loop is a closure over a live socket."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "market_data" / "management" /
               "commands" / "stream_binance.py").read_text(encoding="utf-8")
        loop = src[src.index("async def stream_loop"):]
        self.assertIn("catalogue_symbol(", loop)


class _FreshSpotStats:
    """STATS is module state shared by one streamer per container. Tests
    must not inherit each other's counts."""

    def setUp(self):
        super().setUp()
        from market_data.management.commands import stream_binance as spot
        self._saved = dict(spot.STATS)
        for key in spot.STATS:
            spot.STATS[key] = 0

    def tearDown(self):
        from market_data.management.commands import stream_binance as spot
        spot.STATS.clear()
        spot.STATS.update(self._saved)
        super().tearDown()


class TheSpotStreamerKeepsItsMouthTests(_FreshSpotStats, TestCase):
    """The futures sibling learned on 2026-09-14 that a write path failing
    on every tick and saying so at DEBUG says nothing in production (root
    at WARNING), and that a task handed to `asyncio.create_task` and
    dropped is owned by nobody. The spot streamer wrote LiveQuote the same
    way and was not fixed with it: a stream whose every DB write failed
    looked exactly like a healthy one while the inline broadcast kept the
    headband animating from the same ticks. tests/test_futures_stream_
    visibility.py is the pattern."""

    def setUp(self):
        super().setUp()
        _crypto()

    def test_a_failed_quote_write_warns_and_names_the_symbol(self):
        import logging
        from unittest import mock

        from market_data.management.commands import stream_binance as spot
        with mock.patch("market_data.quotes.write_quote",
                        side_effect=ValueError("column is too narrow")):
            with self.assertLogs(spot.log, level=logging.WARNING) as caught:
                ok = async_to_sync(spot.update_live_quote)(
                    "BTCUSDT", 60000, 1.0, 59999, 60001, 10)
        self.assertFalse(ok)
        self.assertEqual(spot.STATS["quotes_failed"], 1)
        joined = "\n".join(caught.output)
        self.assertIn("BTCUSDT", joined)
        self.assertIn("ValueError", joined)
        self.assertIn("column is too narrow", joined)

    def test_a_successful_quote_write_is_counted(self):
        from market_data.management.commands import stream_binance as spot
        from market_data.models import LiveQuote
        ok = async_to_sync(spot.update_live_quote)(
            "BTCUSDT", 60000, 1.0, 59999, 60001, 10)
        self.assertTrue(ok)
        self.assertEqual(spot.STATS["quotes_written"], 1)
        self.assertEqual(
            LiveQuote.objects.get(instrument__symbol="BTCUSD").source,
            "binance_ws")

    def test_a_broken_feed_does_not_flood_but_does_not_hide(self):
        import logging

        from market_data.management.commands import stream_binance as spot
        with self.assertLogs(spot.log, level=logging.WARNING) as caught:
            for n in range(1, 251):
                spot._report_failure("update_live_quote", "BTCUSDT",
                                     ValueError("x"), n)
        self.assertEqual(len(caught.output), 3)
        self.assertIn("failure #1", caught.output[0])

    def test_fire_holds_the_task_until_it_finishes(self):
        import asyncio

        from market_data.management.commands import stream_binance as spot

        async def _drive():
            async def _slow():
                await asyncio.sleep(0.02)
                return "done"

            task = spot._fire(_slow())
            self.assertIn(task, spot._PENDING)
            self.assertEqual(await task, "done")
            await asyncio.sleep(0)
            self.assertNotIn(task, spot._PENDING)

        asyncio.run(_drive())

    def test_the_source_owns_its_writes_and_reports_above_debug(self):
        import re
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "market_data" / "management" /
               "commands" / "stream_binance.py").read_text(encoding="utf-8")
        self.assertIn("_fire(update_live_quote(", src)
        self.assertIsNone(
            re.search(r"asyncio\.create_task\(\s*update_live_quote\(", src),
            "the LiveQuote write is still fired as a task nobody holds")
        self.assertNotIn('log.debug("update_live_quote(', src,
                         "a failed LiveQuote write is reported at DEBUG, "
                         "which production deletes")
