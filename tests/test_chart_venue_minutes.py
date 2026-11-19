"""The venue's own minute candles on the chart, wherever they are stored
(2026-11-19).

The operator, 2026-11-19: "il y a un probleme d'affichage des prix sur
certaines charts comme la 30min ... sur d'autres pareil.... fix it". On an
instrument routed to eToro whose keyless feed is another instrument (gold:
Yahoo's GC=F, the front-month future), only 1H, 2H and 4H drew eToro's own
candles: 1m, 5m, 10m, 15m and 30m were fetched live from Yahoo, while the
price line, the hero and his position lines are eToro's. Switching 1H to
30m moved the last candle by the basis between the CFD and the future.

The module's own rule (dashboard/chart_source.py: "the venue's candles
when it has them for that frame and they are not stale") now holds for the
minute frames too. For an instrument routed to a venue, 5m, 10m, 15m and
30m draw the venue's own stored rows (the Orcs' eToro tape writes 15m and
5m), never a public feed's:

  * 5m from its 5m rows; 10m from them, folded on the 600 s UTC grid;
  * 15m from its 15m rows; 30m from stored 30m rows, else from the 15m
    rows folded on the 1800 s UTC grid (the 2h fold's own code);
  * 1m from 1m rows alone (nothing writes them today);
  * FRESH: the newest row ended within 2 x max(frame, 600 s) of now, or no
    earlier than the venue's newest 1h bar opened (a shut market, a bar
    pass itself behind), and never once the rows are stale by the 1h
    series' own bound (choose: 72 h, three hours for crypto). Otherwise
    the live frame draws as before, and the legend says where the venue's
    candles stop.

No request (the eToro client is never built, the keyless feed is not asked
when the venue draws), no write. Display only: the engine reads bars
through its own loaders, never the chart's.

Invented prices only: eToro's gold at 4120-4130, Yahoo's GC=F at 4152.

Run with:  python manage.py test tests.test_chart_venue_minutes
"""
import json
import time as _time
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

UTC = dt_tz.utc
#: Thursday 2026-11-19, 10:20 UTC: the CME session runs, the 30 min grid
#: line before it is 10:00, the 10 min one 10:20.
NOW = datetime(2026, 11, 19, 10, 20, tzinfo=UTC)
#: Saturday 2026-11-21, 10:00 UTC: the CME shut since Friday 22:00.
SATURDAY = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
FRIDAY = datetime(2026, 11, 20, tzinfo=UTC)


def _inst(symbol="XAUUSD", asset_class="commodity", name="Gold Spot"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": name, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _row(inst, tf, when, o, h, l, c, source="etoro", vol=0):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=inst, timeframe=tf, timestamp=when,
        open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(l)),
        close=Decimal(str(c)), volume=vol, source=source)


def _rows(inst, tf, first, n, step_min, source="etoro", base=4120):
    """`n` rows of `tf` from `first`, `step_min` apart: row k opens
    base+k, high +3, low -2, close +1, volume 10+k."""
    out = []
    for k in range(n):
        o = base + k
        out.append(_row(inst, tf, first + timedelta(minutes=step_min * k),
                        o, o + 3, o - 2, o + 1, source, vol=10 + k))
    return out


def _epoch(when):
    return int(when.timestamp())


def _yahoo_feed(step_s=1800, n=6, end=NOW):
    """The keyless feed: Yahoo's GC=F, the future, at 4152, `n` bars of
    `step_s` up to `end`, whatever it is asked."""
    feed = mock.MagicMock()
    last = _epoch(end) - _epoch(end) % step_s
    feed.klines.return_value = [
        [(last - (n - 1 - k) * step_s) * 1000, "4152.0", "4153.5", "4150.5",
         "4152.5", "100"] for k in range(n)]
    return feed


class _Venue(TestCase):
    """Gold routed to eToro. The keyless feed is a fake that answers
    Yahoo's level, and building an eToro client fails the test."""

    def setUp(self):
        cache.clear()
        self.inst = _inst()
        self.feed = _yahoo_feed()
        for p in (mock.patch("market_data.public_feed.public_feed_for",
                             return_value=self.feed),
                  mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                             side_effect=AssertionError(
                                 "the chart built an eToro client"))):
            p.start()
            self.addCleanup(p.stop)

    def series(self, interval, route="etoro", now=NOW, **kw):
        from dashboard.chart_source import intraday_series
        return intraday_series(self.inst, interval, route=route, now=now, **kw)

    @staticmethod
    def ohlcv(bar):
        return (bar["open"], bar["high"], bar["low"], bar["close"],
                bar["volume"])


# ═══ The 30 minute frame: eToro's 15m rows, folded ═════════════════════

class ThirtyMinutesTests(_Venue):
    """eToro's 15m gold rows from 08:30 to the forming 10:15 (the Orcs'
    tape), and eToro's forming 10:00 hour, read at 10:20."""

    def setUp(self):
        super().setUp()
        _rows(self.inst, "15m", NOW.replace(hour=8, minute=30), 8, 15)
        _row(self.inst, "1h", NOW.replace(hour=10, minute=0), 4126, 4130,
             4124, 4128)

    def test_30min_folds_etoros_15m_rows_on_the_utc_grid(self):
        bars, src = self.series("30m")
        self.assertEqual(src["family"], "etoro")
        self.assertEqual(src["words"], "eToro's own candles")
        self.assertEqual(src["stand_in"], "")
        self.assertIsNone(src["close_side"], "nothing is welded on eToro's candles")
        at = lambda h, m: _epoch(NOW.replace(hour=h, minute=m))  # noqa: E731
        self.assertEqual([b["time"] for b in bars],
                         [at(8, 30), at(9, 0), at(9, 30), at(10, 0)])
        self.assertTrue(all(b["time"] % 1800 == 0 for b in bars))
        # first open, highest high, lowest low, last close, summed volume
        self.assertEqual([self.ohlcv(b) for b in bars],
                         [(4120.0, 4124.0, 4118.0, 4122.0, 21.0),
                          (4122.0, 4126.0, 4120.0, 4124.0, 25.0),
                          (4124.0, 4128.0, 4122.0, 4126.0, 29.0),
                          (4126.0, 4130.0, 4124.0, 4128.0, 33.0)])
        # the 10:00 bucket runs to 10:30: the forming bar, its close the
        # forming 10:15 candle's
        self.assertEqual(bars[-1]["close"], 4128.0)
        self.assertIn("30 min candles folded from eToro's 15m candles, on "
                      "the UTC grid", src["notes"])
        self.feed.klines.assert_not_called()

    def test_stored_30min_rows_come_first(self):
        """A venue that stores 30m rows draws them as they are, unfolded."""
        _rows(self.inst, "30m", NOW.replace(hour=8, minute=30), 4, 30,
              base=4110)
        bars, src = self.series("30m")
        self.assertEqual(src["family"], "etoro")
        self.assertEqual([b["open"] for b in bars], [4110.0, 4111.0, 4112.0,
                                                     4113.0])
        self.assertFalse(any("folded" in n for n in src["notes"]),
                         src["notes"])
        self.feed.klines.assert_not_called()

    def test_the_chart_reply_draws_them(self):
        """The endpoint, routed to eToro, at the wall clock's own time."""
        from market_data.models import PriceData
        PriceData.objects.all().delete()
        now = int(_time.time())
        grid = datetime.fromtimestamp(now - now % 1800, tz=UTC)
        _rows(self.inst, "15m", grid - timedelta(minutes=60), 5, 15)
        _row(self.inst, "1h", grid.replace(minute=0), 4126, 4130, 4124, 4128)
        user = User.objects.create_user("venue_min_u", password="x")
        self.client.force_login(user)
        with mock.patch(
                "bot_program.engine.broker_router.broker_name_for_symbol",
                return_value="etoro"):
            resp = self.client.get("/api/chart-data/",
                                   {"symbol": "XAUUSD", "timeframe": "30min"})
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content.decode())
        self.assertEqual(body["source"]["family"], "etoro")
        self.assertEqual(body["source"]["route"], "etoro")
        self.assertEqual([b["time"] for b in body["bars"]],
                         [_epoch(grid) - 3600, _epoch(grid) - 1800,
                          _epoch(grid)])
        self.feed.klines.assert_not_called()


# ═══ 15 min, 5 min and 10 min ══════════════════════════════════════════

class FifteenFiveAndTenMinutesTests(_Venue):

    def setUp(self):
        super().setUp()
        _row(self.inst, "1h", NOW.replace(hour=10, minute=0), 4126, 4130,
             4124, 4128)

    def test_15min_and_5min_are_etoros_own_rows(self):
        fifteen = _rows(self.inst, "15m", NOW.replace(hour=8, minute=30), 8,
                        15)
        five = _rows(self.inst, "5m", NOW.replace(hour=9, minute=50), 6, 5,
                     base=4140)
        for interval, stored in (("15m", fifteen), ("5m", five)):
            with self.subTest(interval):
                bars, src = self.series(interval)
                self.assertEqual(src["family"], "etoro")
                self.assertEqual(src["words"], "eToro's own candles")
                self.assertEqual(
                    [(b["time"],) + self.ohlcv(b) for b in bars],
                    [(_epoch(p.timestamp), float(p.open), float(p.high),
                      float(p.low), float(p.close), float(p.volume))
                     for p in stored])
                self.assertFalse(any("folded" in n for n in src["notes"]))
        self.feed.klines.assert_not_called()

    def test_10min_folds_etoros_5m_rows(self):
        _rows(self.inst, "5m", NOW.replace(hour=9, minute=40), 8, 5)
        bars, src = self.series("10m")
        at = lambda h, m: _epoch(NOW.replace(hour=h, minute=m))  # noqa: E731
        self.assertEqual(src["family"], "etoro")
        self.assertEqual([b["time"] for b in bars],
                         [at(9, 40), at(9, 50), at(10, 0), at(10, 10)])
        self.assertEqual([self.ohlcv(b) for b in bars],
                         [(4120.0, 4124.0, 4118.0, 4122.0, 21.0),
                          (4122.0, 4126.0, 4120.0, 4124.0, 25.0),
                          (4124.0, 4128.0, 4122.0, 4126.0, 29.0),
                          (4126.0, 4130.0, 4124.0, 4128.0, 33.0)])
        self.assertIn("10 min candles folded from eToro's 5m candles, on "
                      "the UTC grid", src["notes"])
        self.feed.klines.assert_not_called()


# ═══ When the venue's rows are not fresh ═══════════════════════════════

class FreshnessTests(_Venue):

    def test_a_stopped_tape_gives_way_to_the_live_feed(self):
        """eToro's 15m rows end at 04:00, six hours before eToro's newest
        1h bar opened (10:00): the tape stopped while the bar pass ran. The
        live frame draws, and the legend says where eToro's candles stop."""
        _rows(self.inst, "15m", NOW.replace(hour=2, minute=0), 8, 15)
        _row(self.inst, "1h", NOW.replace(hour=10, minute=0), 4126, 4130,
             4124, 4128)
        bars, src = self.series("30m")
        self.assertEqual(src["family"], "yahoo")
        self.assertEqual(src["stand_in"], "future")
        self.assertEqual(self.feed.klines.call_args.kwargs.get("interval"),
                         "30m")
        self.assertEqual(bars[-1]["close"], 4152.5)
        self.assertIn("eToro's 15m candles stop at 2026-11-19 03:45 UTC; "
                      "these are Yahoo GC=F's", src["notes"])

    def test_a_shut_market_keeps_etoros_last_candles(self):
        """Saturday: eToro's 15m rows end at Friday 22:00 and its newest
        1h bar opened at 21:00. The market is shut, not the tape."""
        _rows(self.inst, "15m", FRIDAY.replace(hour=20), 8, 15)
        _row(self.inst, "1h", FRIDAY.replace(hour=21), 4126, 4130, 4124,
             4128)
        bars, src = self.series("30m", now=SATURDAY)
        self.assertEqual(src["family"], "etoro")
        self.assertEqual(bars[-1]["time"], _epoch(FRIDAY.replace(hour=21,
                                                                 minute=30)))
        self.assertEqual(bars[-1]["close"], 4128.0)
        self.feed.klines.assert_not_called()

    def test_without_a_1h_row_the_age_alone_decides(self):
        _rows(self.inst, "15m", NOW.replace(hour=9, minute=0), 4, 15)
        _bars, fresh = self.series("30m")
        self.assertEqual(fresh["family"], "etoro", "ended at 10:00, 20 min ago")
        _bars, old = self.series("30m", now=NOW + timedelta(minutes=50))
        self.assertEqual(old["family"], "yahoo", "ended 70 min ago, past 60")
        self.assertTrue(any(n.startswith("eToro's 15m candles stop at")
                            for n in old["notes"]), old["notes"])

    def test_never_once_stale_by_the_1h_series_own_bound(self):
        """The bar pass and the tape both stopped four days ago: the 1H
        series gives way to newer public bars after 72 h, and so do the
        minute frames."""
        old = NOW - timedelta(days=4)
        _rows(self.inst, "15m", old.replace(hour=8), 8, 15)
        _row(self.inst, "1h", old.replace(hour=9), 4126, 4130, 4124, 4128)
        _bars, src = self.series("30m")
        self.assertEqual(src["family"], "yahoo")


# ═══ Guards: what never changes ════════════════════════════════════════

class GuardsTests(_Venue):

    def setUp(self):
        super().setUp()
        _rows(self.inst, "15m", NOW.replace(hour=8, minute=30), 8, 15)
        _rows(self.inst, "5m", NOW.replace(hour=9, minute=40), 8, 5)
        _row(self.inst, "1h", NOW.replace(hour=10, minute=0), 4126, 4130,
             4124, 4128)

    def test_not_routed_to_a_venue_the_live_feed_draws(self):
        for route in ("", "paper"):
            with self.subTest(route=route):
                cache.clear()      # the live frame is kept a minute
                _bars, src = self.series("30m", route=route)
                self.assertEqual(src["family"], "yahoo")
        self.assertEqual(self.feed.klines.call_count, 2)

    def test_not_routed_through_the_endpoint(self):
        user = User.objects.create_user("venue_min_paper", password="x")
        self.client.force_login(user)
        with mock.patch(
                "bot_program.engine.broker_router.broker_name_for_symbol",
                return_value="paper"):
            body = self.client.get("/api/chart-data/", {
                "symbol": "XAUUSD", "timeframe": "15min"}).json()
        self.assertEqual(body["source"]["family"], "yahoo")
        self.feed.klines.assert_called_once()

    def test_stored_public_minute_rows_are_never_drawn(self):
        """Yahoo's own 15m rows, fresh, stored (a backfill): the venue has
        none, so the live frame draws, never the stored public rows."""
        from market_data.models import PriceData
        PriceData.objects.filter(source="etoro",
                                 timeframe__in=("15m", "5m")).delete()
        _rows(self.inst, "15m", NOW.replace(hour=8, minute=30), 8, 15,
              source="yfinance_public", base=4300)
        bars, src = self.series("15m")
        self.assertEqual(src["family"], "yahoo")
        self.assertFalse(any(b["open"] >= 4300 for b in bars), bars)
        self.feed.klines.assert_called_once()
        self.assertFalse(any("stop at" in n for n in src["notes"]),
                         "the venue never had minute rows")

    def test_a_venues_public_tag_is_not_its_own(self):
        """Crypto routed to Binance: the keyless client's binance_public
        rows are the family's tag but not the venue's own candles."""
        btc = _inst("BTCUSD", "crypto", "Bitcoin")
        _rows(btc, "15m", NOW.replace(hour=8, minute=30), 8, 15,
              source="binance_public", base=91000)
        from dashboard.chart_source import intraday_series
        _bars, src = intraday_series(btc, "15m", route="binance", now=NOW)
        self.assertEqual(src["family"], "binance")
        self.feed.klines.assert_called_once()

    def test_1min_stays_live_without_1m_rows(self):
        _bars, src = self.series("1m")
        self.assertEqual(src["family"], "yahoo")
        self.assertEqual(self.feed.klines.call_args.kwargs.get("interval"),
                         "1m")

    def test_1min_draws_the_venues_1m_rows_when_there_are_some(self):
        _rows(self.inst, "1m", NOW.replace(hour=10, minute=15), 4, 1)
        bars, src = self.series("1m")
        self.assertEqual(src["family"], "etoro")
        self.assertEqual(len(bars), 4)
        self.feed.klines.assert_not_called()

    def test_nothing_is_written_and_no_venue_is_asked(self):
        from market_data.models import PriceData
        before = sorted(PriceData.objects.values_list(
            "timeframe", "timestamp", "source", "close"))
        for interval in ("1m", "5m", "10m", "15m", "30m", "1h", "2h"):
            self.series(interval)
        after = sorted(PriceData.objects.values_list(
            "timeframe", "timestamp", "source", "close"))
        self.assertEqual(after, before)
