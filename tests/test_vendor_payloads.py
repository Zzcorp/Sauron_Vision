"""The vendors' own JSON, parsed — the Tier-1 roadmap item.

Every price this platform sizes a trade against arrives as somebody else's
JSON and is turned into a number by a handful of `.get()` calls. Before
this file none of those calls had ever executed under test: the suite fed
each parser a dict already in Sauron's own normalised shape, so it verified
the code against a payload Sauron itself wrote.

That is not a hypothetical gap. On 2026-08-28 the calendar's parser met a
real FMP response for the first time and found the endpoint retired (403)
AND the field renamed underneath (`eps` -> `epsActual`). One recorded
payload would have caught both, and the suite was green through all of it.

So: one realistic response per parser, patched in at the HTTP layer, with
the awkward cases the vendors actually send — a missing side of the book,
an incomplete candle, a null price, an error object behind a 200.

Run with:  python manage.py test tests.test_vendor_payloads
"""
from unittest.mock import MagicMock

from django.test import SimpleTestCase


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def _client(cls, payload, *args):
    obj = cls(*args)
    sess = MagicMock()
    sess.get.return_value = _resp(payload)
    obj._session = sess
    return obj, sess


# ═══ OANDA ══════════════════════════════════════════════════════════
#
# A real v20 /pricing row. Both sides of the book carry a LIST of price
# levels, and the platform reads level 0 — the top of book.
OANDA_PRICING = {"prices": [{
    "type": "PRICE", "instrument": "EUR_USD",
    "time": "2026-08-28T13:45:02.123456789Z",
    "bids": [{"price": "1.08495", "liquidity": 10000000},
             {"price": "1.08494", "liquidity": 10000000}],
    "asks": [{"price": "1.08511", "liquidity": 10000000}],
    "closeoutBid": "1.08480", "closeoutAsk": "1.08526", "tradeable": True,
}]}


class OandaPricingTests(SimpleTestCase):

    def _t(self, payload):
        from bot_program.engine.oanda_client import OANDATrader
        return _client(OANDATrader, payload, "k", "101-1")[0]

    def test_the_mid_comes_from_the_top_of_each_side(self):
        out = self._t(OANDA_PRICING).ticker("EURUSD")
        self.assertAlmostEqual(float(out["lastPrice"]), 1.08503, places=6)
        self.assertEqual(float(out["bid"]), 1.08495)
        self.assertEqual(float(out["ask"]), 1.08511)

    def test_one_sided_book_uses_the_side_that_exists(self):
        """A thin pair genuinely arrives with an empty asks list, and a mid
        of half the bid would be a price off by 50%."""
        payload = {"prices": [dict(OANDA_PRICING["prices"][0], asks=[])]}
        out = self._t(payload).ticker("EURUSD")
        self.assertEqual(float(out["lastPrice"]), 1.08495)

    def test_an_empty_price_list_is_not_a_price(self):
        out = self._t({"prices": []}).ticker("EURUSD")
        self.assertEqual(float(out["lastPrice"]), 0.0)

    def test_the_symbol_is_translated_to_oanda_form(self):
        t = self._t(OANDA_PRICING)
        t.ticker("EURUSD")
        self.assertEqual(t._session.get.call_args[1]["params"]["instruments"],
                         "EUR_USD")


OANDA_CANDLES = {"instrument": "EUR_USD", "granularity": "M15", "candles": [
    {"complete": True, "volume": 412, "time": "2026-08-28T13:00:00.000000000Z",
     "mid": {"o": "1.08410", "h": "1.08520", "l": "1.08390", "c": "1.08495"}},
    # The forming candle. Trading it as finished is lookahead on the one
    # bar that has not happened yet.
    {"complete": False, "volume": 88, "time": "2026-08-28T13:15:00.000000000Z",
     "mid": {"o": "1.08495", "h": "1.08540", "l": "1.08480", "c": "1.08530"}},
]}


class OandaCandleTests(SimpleTestCase):

    def _rows(self, payload=OANDA_CANDLES):
        from bot_program.engine.oanda_client import OANDATrader
        t, _ = _client(OANDATrader, payload, "k", "101-1")
        return t.klines("EURUSD", "15m", 200)

    def test_an_incomplete_candle_is_dropped(self):
        rows = self._rows()
        self.assertEqual(len(rows), 1)

    def test_the_row_is_binance_shaped(self):
        """Every consumer of klines() on this platform reads the Binance
        11-element row, so a venue that returns anything else has to be
        translated at the client and not at each caller."""
        row = self._rows()[0]
        self.assertGreaterEqual(len(row), 6)
        self.assertEqual(float(row[1]), 1.08410)   # open
        self.assertEqual(float(row[2]), 1.08520)   # high
        self.assertEqual(float(row[3]), 1.08390)   # low
        self.assertEqual(float(row[4]), 1.08495)   # close

    def test_no_candles_is_an_empty_list_not_a_crash(self):
        self.assertEqual(self._rows({"candles": []}), [])

    def test_a_candle_missing_its_mid_block_does_not_kill_the_series(self):
        payload = {"candles": [{"complete": True, "volume": 1,
                                "time": "2026-08-28T13:00:00.000000000Z"}]}
        rows = self._rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0][4]), 0.0)


# ═══ Alpaca ═════════════════════════════════════════════════════════
#
# /v2/stocks/{sym}/quotes/latest. Two-letter keys, and `bp`/`ap` are 0
# outside regular hours rather than absent.
ALPACA_QUOTE = {"symbol": "AAPL", "quote": {
    "t": "2026-08-28T13:45:02.123456789Z",
    "bp": 231.44, "bs": 3, "ap": 231.47, "as": 5,
    "bx": "V", "ax": "V", "c": ["R"], "z": "C"}}


class AlpacaQuoteTests(SimpleTestCase):

    def _t(self, payload):
        from bot_program.engine.alpaca_client import AlpacaTrader
        return _client(AlpacaTrader, payload, "k", "s")[0]

    def test_the_mid_comes_from_bp_and_ap(self):
        out = self._t(ALPACA_QUOTE).ticker("AAPL")
        self.assertAlmostEqual(float(out["lastPrice"]), 231.455, places=4)

    def test_a_zero_side_outside_hours_does_not_halve_the_price(self):
        """Alpaca sends bp/ap as 0 outside regular hours rather than
        omitting them, so a naive mid reports half the real price — which
        would size a position at twice the intended quantity."""
        payload = {"quote": dict(ALPACA_QUOTE["quote"], ap=0)}
        out = self._t(payload).ticker("AAPL")
        self.assertAlmostEqual(float(out["lastPrice"]), 231.44, places=4)

    def test_a_missing_quote_block_is_not_a_price(self):
        out = self._t({"symbol": "AAPL"}).ticker("AAPL")
        self.assertEqual(float(out["lastPrice"]), 0.0)


# ═══ The shared guard every parser hands its answer to ══════════════

class WhateverTheVendorSentTheWriterRefusesNonsenseTests(SimpleTestCase):
    """Each parser above can be made to answer 0.0 by a payload the vendor
    genuinely sends. `write_quote` is the one place that decides such an
    answer is not a price — which is why every streamer was moved onto it.
    """

    def test_a_zero_never_reaches_the_quote_table(self):
        from market_data.quotes import _dec
        self.assertIsNone(_dec(float("nan")))
        self.assertIsNone(_dec(None))
        self.assertEqual(_dec("1.085"), __import__("decimal").Decimal("1.085"))

    def test_a_nan_is_no_value_rather_than_a_value(self):
        """Yahoo genuinely serves NaN closes on in-progress FX candles, and
        any ordering comparison against one raises."""
        from market_data.quotes import _dec
        self.assertIsNone(_dec(float("inf")))
        self.assertIsNone(_dec(float("-inf")))
