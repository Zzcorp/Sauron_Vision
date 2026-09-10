"""A venue that never answers must not blind the bot.

On 2026-09-10 the Gateway was logged in, its socket open and every forex
contract qualified — and a reqHistoricalData for EURUSD never came back.
ib_insync's default request timeout is 0, wait forever, so the bar writer
stopped at the first forex symbol with no error and no log line while the
pairs' bars aged 36 hours in the middle of a trading week. The signal
scanner read stale closes, every forex decision went `stale_signals`, and
`why_no_trade` found "no structural blocker".

Two halves. Every IBKR session now caps a blocking request, so the silence
becomes a warning. And a venue that answers a bar request with nothing —
a timeout, a pacing refusal, a symbol it will not serve — is replaced for
that symbol by the keyless feed the platform already trusts for accounts
with no broker at all, with the rows tagged as the feed's so provenance
still tells the truth.

Run with:  python manage.py test tests.test_bars_survive_a_mute_venue
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


class TheRequestTimeoutTests(SimpleTestCase):

    def test_connect_caps_every_blocking_request(self):
        from bot_program.engine import ibkr_client
        from bot_program.engine.ibkr_client import IBKRTrader
        session = MagicMock()
        mod = MagicMock()
        mod.IB.return_value = session
        t = IBKRTrader(timeout=0.1)
        with patch.object(ibkr_client, "_ib", mod), \
                patch.object(ibkr_client, "is_ibkr_available",
                             return_value=True):
            self.assertTrue(t._connect())
        self.assertEqual(session.RequestTimeout, IBKRTrader.REQUEST_TIMEOUT_S)

    def test_the_cap_is_a_real_wait_not_a_twitch(self):
        """Long enough for a paced historical request, short enough that
        a five-minute tick survives one mute symbol."""
        from bot_program.engine.ibkr_client import IBKRTrader
        self.assertGreaterEqual(IBKRTrader.REQUEST_TIMEOUT_S, 10)
        self.assertLessEqual(IBKRTrader.REQUEST_TIMEOUT_S, 120)


def _klines(n=3, start_ms=1_756_000_000_000, step_ms=14_400_000):
    return [[start_ms + i * step_ms, "1.10", "1.11", "1.09", "1.105", "0"]
            for i in range(n)]


class YFinanceFeed:
    """Named like the real one: the source tag is read off the class."""
    _sv_public_feed = True

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval, limit))
        return list(self.rows)


class TheMuteVenueTests(TestCase):

    def setUp(self):
        from django.core.cache import cache

        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        cache.clear()      # the mute memo lives there and outlives a test
        self.user = User.objects.create_user("mute_u", password="x")
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="EURUSD", defaults={"name": "EURUSD",
                                       "asset_class": "forex"})
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="MUTE", mode="live",
            symbols=["EURUSD"], capital=Decimal("150"), enabled=True)

    def _venue(self, rows=None, raises=None, public=False):
        client = MagicMock(name="IBKRTrader")
        client._sv_public_feed = public
        if raises is not None:
            client.klines.side_effect = raises
        else:
            client.klines.return_value = rows if rows is not None else []
        return client

    def _refresh(self, venue, feed):
        from market_data.bot_bars import refresh_bars_for_config
        with patch("market_data.bot_bars._client_for", return_value=venue), \
                patch("market_data.bot_bars._public_market_data_client",
                      return_value=feed) as pub:
            out = refresh_bars_for_config(self.cfg, intervals=("4h",),
                                          limit=3)
        return out, pub

    def _written(self):
        from market_data.models import PriceData
        return list(PriceData.objects.filter(instrument=self.inst)
                    .values_list("source", flat=True))

    def test_a_venue_with_nothing_to_say_is_replaced_by_the_public_feed(self):
        feed = YFinanceFeed(_klines(3))
        out, _pub = self._refresh(self._venue(rows=[]), feed)
        self.assertEqual(out["fallback"], 1)
        self.assertEqual(out["bars"], 3)
        self.assertEqual(set(self._written()), {"yfinance_public"})
        self.assertEqual(feed.calls, [("EURUSD", "4h", 3)])

    def test_a_venue_that_times_out_is_replaced_too(self):
        """The EURUSD case, once the cap turns the hang into an error."""
        feed = YFinanceFeed(_klines(3))
        out, _pub = self._refresh(self._venue(raises=TimeoutError("30s")),
                                  feed)
        self.assertEqual(out["errors"], 1)
        self.assertEqual(out["fallback"], 1)
        self.assertEqual(len(self._written()), 3)

    def test_a_venue_that_answers_is_never_second_guessed(self):
        feed = YFinanceFeed(_klines(3))
        out, pub = self._refresh(self._venue(rows=_klines(2)), feed)
        self.assertEqual(out["fallback"], 0)
        self.assertEqual(feed.calls, [])
        pub.assert_not_called()
        written = self._written()
        self.assertEqual(len(written), 2)
        self.assertNotIn("yfinance_public", written)

    def test_the_public_feed_is_not_asked_to_back_up_itself(self):
        """A keyless client that returned nothing IS the fallback; asking
        it again would only double the request."""
        out, pub = self._refresh(self._venue(rows=[], public=True),
                                 YFinanceFeed(_klines(3)))
        self.assertEqual(out["fallback"], 0)
        pub.assert_not_called()
        self.assertEqual(self._written(), [])

    def test_a_mute_venue_is_not_asked_again_for_a_while(self):
        """Seven forex CFDs times two intervals times a full request
        timeout is most of a ten-minute refresh spent on a venue that
        has already said no. Once is enough per window."""
        venue = self._venue(rows=[])
        feed = YFinanceFeed(_klines(3))
        first, _ = self._refresh(venue, feed)
        second, _ = self._refresh(venue, feed)
        self.assertEqual(venue.klines.call_count, 1)
        self.assertEqual((first["fallback"], second["fallback"]), (1, 1))
        self.assertEqual(len(feed.calls), 2)

    def test_the_memo_expires_and_the_venue_gets_a_fresh_chance(self):
        from django.core.cache import cache
        venue = self._venue(rows=[])
        feed = YFinanceFeed(_klines(3))
        self._refresh(venue, feed)
        cache.clear()                       # the window passed
        self._refresh(venue, feed)
        self.assertEqual(venue.klines.call_count, 2)
