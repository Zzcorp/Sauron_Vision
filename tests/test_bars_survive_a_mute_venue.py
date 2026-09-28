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

    def _rows(self):
        from market_data.models import PriceData
        return sorted(PriceData.objects.filter(instrument=self.inst)
                      .values_list("timestamp", "source"))

    def test_the_stand_in_fills_the_gap_after_the_venues_last_bar(self):
        """Yahoo's 4h grid is anchored at exchange midnight and an execution
        venue's at its own session close, so the two never share a
        timestamp: side by side they read as ONE series at twice the
        density, and every ATR and IPDA range on the pair is measured on
        it. The stand-in covers only what the venue has not."""
        two_hours = 2 * 3_600_000
        feed = YFinanceFeed(_klines(4, start_ms=1_756_000_000_000 + two_hours))
        self._refresh(self._venue(rows=_klines(3)), feed)     # S, S+4h, S+8h
        out, _ = self._refresh(self._venue(rows=[]), feed)    # mute; S+2h.. on offer
        self.assertEqual(out["fallback"], 1)
        venue_ts = [ts for ts, src in self._rows() if src != "yfinance_public"]
        public_ts = [ts for ts, src in self._rows() if src == "yfinance_public"]
        self.assertEqual(len(venue_ts), 3)
        self.assertTrue(public_ts,
                        "the gap after the venue's last bar was not filled")
        self.assertGreater(min(public_ts), max(venue_ts))

    def test_a_venue_that_answers_again_takes_its_window_back(self):
        """Once the memo expires and the venue answers, its bars are the
        truth for the window they cover: the stand-in's rows from that
        window onward go, so the bot reads one grid, not two interleaved."""
        from django.core.cache import cache
        two_hours = 2 * 3_600_000
        feed = YFinanceFeed(_klines(3, start_ms=1_756_000_000_000 + two_hours))
        self._refresh(self._venue(rows=[]), feed)             # S+2h, S+6h, S+10h
        self.assertEqual(set(self._written()), {"yfinance_public"})
        cache.clear()                                         # the window passed
        out, _ = self._refresh(self._venue(rows=_klines(3)), feed)   # S, S+4h, S+8h
        self.assertEqual(out["fallback"], 0)
        self.assertEqual([src for _ts, src in self._rows()], ["magicmock"] * 3)

    def test_history_before_the_venues_window_is_left_alone(self):
        """A year of backfilled Yahoo bars behind the venue's 200 is what
        the long-window rules read: taking the window back means the
        window, not the table."""
        from datetime import datetime, timezone as dt_tz

        from market_data.models import PriceData
        old = datetime.fromtimestamp((1_756_000_000_000 - 40 * 3_600_000) / 1000,
                                     tz=dt_tz.utc)
        PriceData.objects.create(
            instrument=self.inst, timeframe="4h", timestamp=old, open=1,
            high=1, low=1, close=1, volume=0, source="yfinance_public")
        self._refresh(self._venue(rows=_klines(3)), YFinanceFeed([]))
        self.assertIn((old, "yfinance_public"), self._rows())


class OneTagForTheKeylessFeedTests(TestCase):
    """The provenance column is worth reading only if one feed has one name.

    The scheduled path stripped "Trader" and "Client" from the class name
    but not "Feed", so the same Yahoo feed wrote `yfinancefeed_public` for
    a config with no broker and `yfinance_public` from the fallback and
    from backfill_bars: an audit of the keyless rows by either spelling
    missed the other half.
    """

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        self.user = User.objects.create_user("tag_u", password="x")
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="EURUSD", defaults={"name": "EURUSD",
                                       "asset_class": "forex"})
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="TAG", mode="paper",
            symbols=["EURUSD"], capital=Decimal("150"), enabled=True)

    def _sources(self, inst):
        from market_data.models import PriceData
        return set(PriceData.objects.filter(instrument=inst)
                   .values_list("source", flat=True))

    def test_the_scheduled_path_spells_it_as_the_fallback_does(self):
        from market_data.bot_bars import refresh_bars_for_config
        with patch("market_data.bot_bars._client_for",
                   return_value=YFinanceFeed(_klines(3))), \
                patch("market_data.bot_bars._pace"):
            refresh_bars_for_config(self.cfg, intervals=("4h",), limit=3)
        self.assertEqual(self._sources(self.inst), {"yfinance_public"})

    def test_the_watchlist_path_spells_it_the_same(self):
        from instruments.models import Instrument
        from market_data.bot_bars import refresh_watchlist_bars
        star, _ = Instrument.objects.get_or_create(
            symbol="GBPUSD", defaults={"name": "GBPUSD",
                                       "asset_class": "forex"})
        Instrument.objects.filter(pk=star.pk).update(is_watchlist=True,
                                                     is_active=True)
        with patch("market_data.public_feed.public_feed_for",
                   return_value=YFinanceFeed(_klines(3))), \
                patch("market_data.bot_bars._pace"):
            refresh_watchlist_bars(intervals=("4h",), limit=3)
        self.assertEqual(self._sources(star), {"yfinance_public"})


class TheRefreshTotalsCountTheFallbackTests(TestCase):
    """`refresh_bars_for_config` counted the fallback; `refresh_bot_bars`
    summed every key but that one, so the pass-level "[bars] refresh
    complete" line the operator reads — and the task's return — said
    bars=N with no word that none of them came from the venue."""

    def setUp(self):
        from django.core.cache import cache

        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        cache.clear()
        self.user = User.objects.create_user("totals_u", password="x")
        Instrument.objects.get_or_create(
            symbol="EURUSD", defaults={"name": "EURUSD",
                                       "asset_class": "forex"})
        AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="TOTALS", mode="live",
            symbols=["EURUSD"], capital=Decimal("150"), enabled=True)

    def test_the_totals_and_the_log_line_carry_the_fallback(self):
        from market_data.bot_bars import refresh_bot_bars
        venue = MagicMock()
        venue._sv_public_feed = False
        venue.klines.return_value = []
        with patch("market_data.bot_bars._client_for", return_value=venue), \
                patch("market_data.bot_bars._public_market_data_client",
                      return_value=YFinanceFeed(_klines(3))), \
                self.assertLogs("market_data.bot_bars", level="INFO") as logs:
            totals = refresh_bot_bars(intervals=("4h",), limit=3)
        self.assertEqual(totals["fallback"], 1)
        line = next(x for x in logs.output if "refresh complete" in x)
        self.assertIn("'fallback': 1", line)
