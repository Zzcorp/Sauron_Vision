"""A shut market's snapshot is not a live price.

OANDA's v20 pricing stream sends a PRICE snapshot per instrument on every
(re)connect, the market shut included, where it carries "tradeable": false.
The streamer read only "type", so each snapshot went through write_quote
as source "oanda_stream" and refreshed LiveQuote.updated_at: every weekend
restart of stream-oanda rewrote Friday's last price with a fresh timestamp.

Measured on the VPS on Saturday 2026-09-26, the forex market shut since
Friday 21:00 UTC: at 13:51 UTC the EURCAD and GBPCAD quotes were dated
11:31 UTC, past the paper trader's MAX_QUOTE_AGE_SECONDS of 900. At about
13:53 UTC two paper forex closes found them "fresh" and were marked against
Friday's price. Pairs the account does not stream (USDNOK, USDZAR) were
correctly refused, which is what EURCAD and GBPCAD should have been.

Run with:  python manage.py test tests.test_oanda_shut_market
"""
import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from django.test import TestCase
from django.utils import timezone


def _price(instrument="EUR_CAD", bid="1.47810", ask="1.47830", **extra):
    """A PRICE message in the shape the v20 stream sends it."""
    msg = {"type": "PRICE", "instrument": instrument,
           "time": "2026-09-26T13:52:40.000000000Z",
           "bids": [{"price": bid, "liquidity": 1000000}],
           "asks": [{"price": ask, "liquidity": 1000000}],
           "closeoutBid": bid, "closeoutAsk": ask}
    msg.update(extra)
    return msg


def _shut(instrument="EUR_CAD", **kw):
    return _price(instrument, status="non-tradeable", tradeable=False, **kw)


class _StreamCase(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        self.eurcad = Instrument.objects.create(
            symbol="EURCAD", name="EURCAD", asset_class="forex",
            is_active=True)
        self.gbpcad = Instrument.objects.create(
            symbol="GBPCAD", name="GBPCAD", asset_class="forex",
            is_active=True)

    def _connection(self, *msgs):
        """Every message through the loop's own handler, on ONE connection.

        The write is the real one, deferred to this thread: the real
        update_live_quote is a sync_to_async wrapper whose worker thread
        opens its own database connection, which cannot see the
        transaction a TestCase wraps each test in, and the ORM refuses to
        run inside the event loop itself. So the handler's calls are
        recorded, and the wrapped writer runs for each one once the loop
        has finished. Returns the broadcast mock.
        """
        from market_data.management.commands import stream_oanda

        writes = []

        async def record(sym, bid, ask):
            writes.append((sym, bid, ask))

        async def drive():
            shut = set()
            for msg in msgs:
                await stream_oanda.on_message(msg, shut)
            pending = asyncio.all_tasks() - {asyncio.current_task()}
            await asyncio.gather(*pending)

        with patch.object(stream_oanda, "update_live_quote", new=record), \
                patch.object(stream_oanda, "broadcast",
                             new=AsyncMock()) as sent:
            asyncio.run(drive())
        for sym, bid, ask in writes:
            stream_oanda.update_live_quote.func(sym, bid, ask)
        return sent

    def _quote(self, inst):
        from market_data.models import LiveQuote
        return LiveQuote.objects.filter(instrument=inst).first()

    def _friday_quote(self, inst, last="1.47500"):
        """A quote the way the VPS held it at 13:51 UTC: dated 11:31, stale."""
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        write_quote(inst.symbol, last=Decimal(last), source="oanda_stream",
                    bid=Decimal(last), ask=Decimal(last), instrument=inst)
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=timezone.now() - timedelta(hours=2, minutes=20))
        return self._quote(inst).updated_at


class AShutSnapshotWritesNothingTests(_StreamCase):

    def test_a_tradeable_false_snapshot_writes_no_live_quote(self):
        sent = self._connection(_shut())
        self.assertIsNone(self._quote(self.eurcad))
        sent.assert_not_awaited()

    def test_it_does_not_refresh_a_stale_quote(self):
        """The failure as it happened: Friday's price, re-stamped."""
        before = self._friday_quote(self.eurcad)
        self._connection(_shut())
        row = self._quote(self.eurcad)
        self.assertEqual(row.updated_at, before)
        self.assertEqual(Decimal(str(row.last)), Decimal("1.47500"))

    def test_the_paper_trader_still_refuses_the_weekend_quote(self):
        """The promise the snapshot broke: no mark against a fossil."""
        from bot_program.engine.paper_trader import PaperTrader
        self._friday_quote(self.eurcad)
        self._connection(_shut())
        got = PaperTrader(None).ticker("EURCAD")
        self.assertEqual(got["lastPrice"], "0")
        self.assertTrue(got.get("stale"))


class ALivePriceStillWritesTests(_StreamCase):

    def test_a_tradeable_true_tick_writes_one(self):
        sent = self._connection(_price(tradeable=True))
        row = self._quote(self.eurcad)
        self.assertIsNotNone(row)
        self.assertEqual(row.source, "oanda_stream")
        self.assertEqual(Decimal(str(row.last)), Decimal("1.4782"))
        self.assertEqual(Decimal(str(row.bid)), Decimal("1.4781"))
        self.assertEqual(Decimal(str(row.ask)), Decimal("1.4783"))
        sent.assert_awaited_once()
        self.assertEqual(sent.await_args.args[0], "EUR_CAD")
        self.assertIsNone(sent.await_args.args[2])

    def test_a_message_without_the_flag_still_writes(self):
        """Backwards compatible: only an explicit false is skipped."""
        msg = _price()
        self.assertNotIn("tradeable", msg)
        sent = self._connection(msg)
        self.assertIsNotNone(self._quote(self.eurcad))
        sent.assert_awaited_once()

    def test_a_pair_that_reopens_on_the_same_connection_writes_again(self):
        """Sunday's open arrives on a connection that may date from
        Saturday; being reported shut must not mute the pair for good."""
        self._connection(_shut(), _price(tradeable=True))
        self.assertIsNotNone(self._quote(self.eurcad))


class TheShutPairIsReportedOncePerConnectionTests(_StreamCase):

    def test_once_per_instrument_at_debug(self):
        with self.assertLogs("stream_oanda", level="DEBUG") as logs:
            self._connection(_shut("EUR_CAD"), _shut("EUR_CAD"),
                             _shut("GBP_CAD"), _shut("EUR_CAD"))
        shut_lines = [r for r in logs.records
                      if "not tradeable" in r.getMessage()]
        self.assertEqual(len(shut_lines), 2)
        self.assertTrue(all(r.levelname == "DEBUG" for r in shut_lines))
        self.assertEqual(sum("EUR_CAD" in r.getMessage()
                             for r in shut_lines), 1)
        self.assertEqual(sum("GBP_CAD" in r.getMessage()
                             for r in shut_lines), 1)

    def test_a_new_connection_reports_it_again(self):
        with self.assertLogs("stream_oanda", level="DEBUG") as logs:
            self._connection(_shut("EUR_CAD"))
            self._connection(_shut("EUR_CAD"))
        self.assertEqual(sum("not tradeable" in r.getMessage()
                             for r in logs.records), 2)
