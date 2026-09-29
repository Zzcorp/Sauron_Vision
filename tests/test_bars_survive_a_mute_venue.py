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


import time as _time

_FOUR_H = 14_400_000

#: The fixtures' bars end at the present. They were dated August 2025,
#: and since 2026-09-29 a venue window that old is a STALE answer the
#: public feed fills after (market_data.bot_bars._venue_window_is_stale);
#: these tests are about a venue answering with today's bars.
RECENT_MS = (int(_time.time() * 1000) // _FOUR_H) * _FOUR_H - 3 * _FOUR_H


def _klines(n=3, start_ms=RECENT_MS, step_ms=_FOUR_H):
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
        feed = YFinanceFeed(_klines(4, start_ms=RECENT_MS + two_hours))
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
        feed = YFinanceFeed(_klines(3, start_ms=RECENT_MS + two_hours))
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
        old = datetime.fromtimestamp((RECENT_MS - 40 * 3_600_000) / 1000,
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


class AStaleVenueWindowTests(TestCase):
    """2026-09-29: eToro answered BTCUSD's 4h request with a window whose
    newest bar was 33.7 days old. The refresh evicted every public bar from
    that window's start ONWARD — last night's 600-bar backfill with them —
    every ten minutes, and an armed bot decided on a month-old candle. The
    eviction now stops one interval past the venue's newest bar, and a
    stale window is followed by the public feed, as a mute venue is."""

    DAY_MS = 86_400_000

    def setUp(self):
        from django.core.cache import cache

        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        cache.clear()
        self.user = User.objects.create_user("stale_u", password="x")
        self.btc, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "Bitcoin",
                                       "asset_class": "crypto"})
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="STALE", mode="live",
            symbols=["BTCUSD"], capital=Decimal("225"), enabled=True)

    def _venue(self, rows):
        client = MagicMock(name="EtoroTrader")
        client._sv_public_feed = False
        client.klines.return_value = rows
        return client

    def _refresh(self, venue, feed, cfg=None):
        from market_data.bot_bars import refresh_bars_for_config
        with patch("market_data.bot_bars._client_for", return_value=venue), \
                patch("market_data.bot_bars._public_market_data_client",
                      return_value=feed):
            return refresh_bars_for_config(cfg or self.cfg, intervals=("4h",),
                                           limit=3)

    def _rows(self, inst=None):
        from market_data.models import PriceData
        return sorted(PriceData.objects.filter(instrument=inst or self.btc)
                      .values_list("timestamp", "source"))

    def _seed_public(self, stamps_ms, inst=None):
        from datetime import datetime, timezone as dt_tz

        from market_data.models import PriceData
        for ms in stamps_ms:
            PriceData.objects.create(
                instrument=inst or self.btc, timeframe="4h",
                timestamp=datetime.fromtimestamp(ms / 1000, tz=dt_tz.utc),
                open=1, high=1, low=1, close=1, volume=0,
                source="binance_public")

    def test_fresh_public_bars_beyond_a_stale_window_survive(self):
        old = RECENT_MS - 34 * self.DAY_MS
        fresh = [RECENT_MS + i * _FOUR_H for i in range(3)]
        self._seed_public(fresh)
        self._refresh(self._venue(_klines(3, start_ms=old)), YFinanceFeed([]))
        public = [ts for ts, src in self._rows() if src == "binance_public"]
        self.assertEqual(len(public), 3,
                         "the fresh backfill was evicted by a month-old window")

    def test_a_stale_window_is_followed_by_the_public_feed(self):
        old = RECENT_MS - 34 * self.DAY_MS
        feed = YFinanceFeed(_klines(3))                  # today's bars
        out = self._refresh(self._venue(_klines(3, start_ms=old)), feed)
        self.assertEqual(out["fallback"], 1)
        self.assertEqual(feed.calls, [("BTCUSD", "4h", 3)])
        newest_ts, newest_src = self._rows()[-1]
        self.assertEqual(newest_src, "yfinance_public")
        self.assertGreater(newest_ts.timestamp() * 1000, RECENT_MS - _FOUR_H)

    def test_the_warning_is_said_once_per_window(self):
        old = RECENT_MS - 34 * self.DAY_MS
        venue = self._venue(_klines(3, start_ms=old))
        with self.assertLogs("market_data.bot_bars", level="WARNING") as logs:
            self._refresh(venue, YFinanceFeed(_klines(3)))
            self._refresh(venue, YFinanceFeed(_klines(3)))
        said = [m for m in logs.output if "answered with a window" in m]
        self.assertEqual(len(said), 1)

    def test_inside_the_window_the_venue_still_wins(self):
        """The old promise holds within the window: a public bar that
        interleaves with the venue's grid there goes."""
        old = RECENT_MS - 34 * self.DAY_MS
        self._seed_public([old + 2 * 3_600_000])
        self._refresh(self._venue(_klines(3, start_ms=old)), YFinanceFeed([]))
        self.assertNotIn("binance_public", [src for _ts, src in self._rows()])

    def test_a_closed_market_is_not_a_stale_venue(self):
        """Forex over a weekend: the venue's newest 4h bar is two days old
        because the market is shut. Under 72 h, nobody second-guesses it."""
        from instruments.models import Instrument
        from bot_program.models import AssetBotConfig
        eur, _ = Instrument.objects.get_or_create(
            symbol="EURUSD", defaults={"name": "EURUSD", "asset_class": "forex"})
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="WEEKEND", mode="live",
            symbols=["EURUSD"], capital=Decimal("1200"), enabled=True)
        weekend = RECENT_MS - 2 * self.DAY_MS
        feed = YFinanceFeed(_klines(3))
        out = self._refresh(self._venue(_klines(3, start_ms=weekend)), feed, cfg)
        self.assertEqual(out["fallback"], 0)
        self.assertEqual(feed.calls, [])

    def test_the_judgement_in_isolation(self):
        from datetime import datetime, timezone as dt_tz

        from market_data.bot_bars import _venue_window_is_stale
        now = datetime.fromtimestamp((RECENT_MS + 3 * _FOUR_H) / 1000, tz=dt_tz.utc)
        fresh = _klines(3)
        self.assertIsNone(_venue_window_is_stale(self.btc, "4h", fresh, now=now))
        thirteen_h = _klines(1, start_ms=RECENT_MS + 3 * _FOUR_H - 13 * 3_600_000)
        self.assertIsNotNone(_venue_window_is_stale(self.btc, "4h", thirteen_h, now=now))
        self.assertIsNone(_venue_window_is_stale(self.btc, "4h", [], now=now))
