"""More chart divisions: 10 min, 30 min, 2 h and weekly candles (2026-11-01).

The operator: "augmenter la division des chart ajout de 10min etc...". The
instrument chart offered candles of 1, 5 and 15 minutes, 1h and 4h, and
daily candles under 1D, 1W, 1M, 3M and 1Y. Those last five were all DAILY
candles: 1M, 3M and 1Y were ranges (60, 180 and 730 days, twice their
names), 1D the default daily view (420 days), and 1W, as deep as 1Y (730
days), drew the same two years of daily candles as 1Y: no button drew a
weekly candle.

What this pins (display only: the bots read no chart series):
  D1 2h candles fold the SAME feed's stored 1h rows that choose() picks, on
     the fixed UTC grid (00:00, 02:00 ...), with C1's suspect marks, hole
     cut and notes; a partial last bucket is the forming bar; a bucket the
     read cut is never drawn; no live request.
  D2 weekly candles fold ONE feed's days by ISO week (Monday 00:00 UTC);
     this week's forming candle takes today's forming day from the same
     feed's intraday rows only, as C1 does for the day. A day goes into
     the week of its SESSION, whatever midnight the feed stamps it at
     (Yahoo: the exchange's own). This week's candle takes the live tick
     only while it holds today's forming day, as the daily view's last
     candle does; otherwise it says why (`no_tick`).
  D3 10 min and 30 min come from the keyless feed, kept a minute and never
     stored: 30 min is Yahoo's and Binance's own interval; 10 min neither
     has, so it folds their 5 min bars.
  D4 the API takes the new frames and refuses a timeframe it does not know
     (any word drew 90 days of daily candles); the old ones, the legacy
     '1m' month included, still answer; the 1W range shows two weeks of
     daily candles, as 1M shows two months.
  D5 the toolbar: candle sizes 1m 5m 10m 15m 30m 1H 2H 4H D W, then the
     ranges 1W 1M 3M 1Y, each group named; the candle sizes keep one row
     from a 360 px phone up.

Run with:  python manage.py test tests.test_chart_divisions
"""
import json
import pathlib
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_close_advice import CHROME, _Chrome

UTC = dt_tz.utc
H = 3600
#: A Wednesday afternoon: the 2h grid line before it is 14:00 UTC, and its
#: ISO week opened on Monday 2026-10-26.
NOW = datetime(2026, 10, 28, 15, 20, tzinfo=UTC)
DAY = datetime(2026, 10, 28, tzinfo=UTC)


def _inst(symbol, asset_class, name=None):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": name or symbol,
                                 "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _bar(inst, tf, when, o, h, l, c, source, vol=0):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=inst, timeframe=tf, timestamp=when,
        open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(l)),
        close=Decimal(str(c)), volume=vol, source=source)


def _hour(inst, hour, source, base=4000, day=DAY):
    """The 1h row of `hour` on `day`: open base+hour, high +2, low -2,
    close +1, volume the hour."""
    o = base + hour
    return _bar(inst, "1h", day + timedelta(hours=hour), o, o + 2, o - 2,
                o + 1, source, vol=hour)


def _epoch(hour, day=DAY):
    return int((day + timedelta(hours=hour)).timestamp())


def _no_live_feed():
    """A keyless feed that fails the test if the chart asks it anything."""
    feed = mock.MagicMock()
    feed.klines.side_effect = AssertionError("the chart asked the live feed")
    return mock.patch("market_data.public_feed.public_feed_for",
                      return_value=feed)


# ═══ D1. 2h candles: the same feed's 1h rows, on the UTC grid ═════════

class TwoHourCandlesTests(TestCase):
    """eToro's gold 1h rows from 09:00 to 15:00 UTC, the chart read at
    15:20: the 2h grid lines are 08:00, 10:00, 12:00 and 14:00."""

    def setUp(self):
        cache.clear()
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")
        for hour in range(9, 16):
            _hour(self.inst, hour, "etoro")

    def series(self, route="etoro", now=NOW, **kw):
        from dashboard.chart_source import intraday_series
        with _no_live_feed():
            return intraday_series(self.inst, "2h", route=route, now=now, **kw)

    def test_they_fold_the_hours_on_the_fixed_utc_grid(self):
        bars, src = self.series()
        self.assertEqual([b["time"] for b in bars],
                         [_epoch(8), _epoch(10), _epoch(12), _epoch(14)])
        self.assertTrue(all(b["time"] % 7200 == 0 for b in bars))
        ten = bars[1]
        # first open, highest high, lowest low, last close, summed volume
        self.assertEqual((ten["open"], ten["high"], ten["low"], ten["close"],
                          ten["volume"]), (4010.0, 4013.0, 4008.0, 4012.0,
                                           21.0))
        self.assertEqual(src["family"], "etoro")
        self.assertIn("eToro's own candles", src["words"])

    def test_the_partial_last_bucket_is_the_forming_bar(self):
        """At 14:20 the 14:00 bucket holds the 14:00 hour alone: it is drawn
        as it stands, the last bar, and the live tick welds onto it."""
        from market_data.models import PriceData
        PriceData.objects.filter(timestamp=DAY + timedelta(hours=15)).delete()
        bars, _src = self.series(now=DAY + timedelta(hours=14, minutes=20))
        last = bars[-1]
        self.assertEqual(last["time"], _epoch(14))
        self.assertEqual((last["open"], last["high"], last["low"],
                          last["close"]), (4014.0, 4016.0, 4012.0, 4015.0))
        self.assertNotIn("suspect", last)

    def test_the_legend_says_they_are_folded_from_1h(self):
        _bars, src = self.series()
        self.assertTrue(any("2h candles folded from eToro's 1h candles" in n
                            for n in src["notes"]), src["notes"])

    def test_a_bucket_the_read_cut_is_never_drawn(self):
        """Read four 2h bars' worth of rows back from 14:00 (08:00 to 14:00
        stored, 09:00 to 14:00 read), the 08:00 bucket would hold 09:00
        alone: a 2h candle opening at 09:00's price."""
        from market_data.models import PriceData
        PriceData.objects.filter(timestamp=DAY + timedelta(hours=15)).delete()
        _hour(self.inst, 8, "etoro")
        bars, _src = self.series(now=DAY + timedelta(hours=14, minutes=20),
                                 limit=3)
        self.assertEqual([b["time"] for b in bars],
                         [_epoch(10), _epoch(12), _epoch(14)])

    def test_the_2h_frame_asks_no_live_feed(self):
        """Stored rows only: no request to the keyless feed, nor to eToro."""
        bars, _src = self.series()
        self.assertTrue(bars)


class TwoHourCandlesAreOneFeedTests(TestCase):

    def setUp(self):
        cache.clear()
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")

    def series(self, route, now=NOW):
        from dashboard.chart_source import intraday_series
        with _no_live_feed():
            return intraday_series(self.inst, "2h", route=route, now=now)

    def test_a_bucket_never_mixes_two_feeds(self):
        """Yahoo GC=F's 08:00 hour shares the 08:00 bucket with eToro's
        09:00: routed to eToro, the bucket is eToro's 09:00 alone; on the
        public feed, Yahoo's hours alone."""
        for hour in range(9, 16):
            _hour(self.inst, hour, "etoro")
        for hour in (6, 7, 8):
            _hour(self.inst, hour, "yfinance_public", base=4036)
        bars, src = self.series("etoro")
        first = bars[0]
        self.assertEqual(first["time"], _epoch(8))
        self.assertEqual((first["open"], first["high"], first["close"]),
                         (4009.0, 4011.0, 4010.0))
        self.assertEqual(src["family"], "etoro")
        self.assertTrue(any("older bars from Yahoo GC=F" in n
                            and "not drawn" in n for n in src["notes"]),
                        src["notes"])

        public, psrc = self.series("")
        self.assertEqual(psrc["family"], "yahoo")
        self.assertEqual([b["time"] for b in public], [_epoch(6), _epoch(8)])
        self.assertEqual(public[1]["open"], 4044.0)       # Yahoo's 08:00
        self.assertEqual(public[1]["close"], 4045.0)      # nothing of eToro's
        self.assertEqual(public[1]["volume"], 8.0)

    def test_newer_hours_of_another_feed_are_named_not_folded(self):
        """eToro's hours stop at 13:00; Yahoo wrote 14:00 and 15:00 (eToro
        muted, paced or refused). Routed to eToro, the series is eToro's
        and the legend counts Yahoo's newer hours."""
        for hour in range(9, 14):
            _hour(self.inst, hour, "etoro")
        for hour in (14, 15):
            _hour(self.inst, hour, "yfinance_public", base=4036)
        bars, src = self.series("etoro")
        self.assertEqual([b["time"] for b in bars],
                         [_epoch(8), _epoch(10), _epoch(12)])
        self.assertEqual(bars[-1]["close"], 4014.0)      # eToro's 13:00
        self.assertTrue(any("2 newer bars from Yahoo GC=F are not drawn" in n
                            for n in src["notes"]), src["notes"])

    def test_a_stale_venue_gives_way_only_after_its_last_hour(self):
        """eToro's 1h stopped four days before; Yahoo holds history behind
        eToro's window and hours after it. The 2h series is Yahoo's hours
        after eToro's last one: never folded across the hole."""
        old = DAY - timedelta(days=4)
        for hour in range(8, 14):
            _hour(self.inst, hour, "etoro", day=old)
        for hour in range(0, 8):
            _hour(self.inst, hour, "yfinance_public", base=3000, day=old)
        for hour in range(10, 16):
            _hour(self.inst, hour, "yfinance_public", base=4036)
        bars, src = self.series("etoro")
        self.assertEqual(src["family"], "yahoo")
        self.assertEqual([b["time"] for b in bars],
                         [_epoch(10), _epoch(12), _epoch(14)])
        self.assertTrue(any("older bars from Yahoo GC=F, from before eToro's "
                            "last candle, are not drawn" in n
                            for n in src["notes"]), src["notes"])

    def test_a_bucket_holding_a_suspect_hour_is_marked(self):
        """eToro's 12:00 hour cannot have traded (its high under its open);
        folded with 13:00 its bucket's prices look possible, and it would
        be drawn solid. It inherits the hour's marking."""
        for hour in range(9, 16):
            if hour == 12:
                _bar(self.inst, "1h", DAY + timedelta(hours=12), 4012, 4011,
                     4010, 4011.5, "etoro", vol=12)
            else:
                _hour(self.inst, hour, "etoro")
        bars, src = self.series("etoro")
        noon = [b for b in bars if b["time"] == _epoch(12)][0]
        self.assertIn("suspect bar from eToro", noon.get("suspect", ""))
        self.assertIn("1h bar", noon["suspect"])
        self.assertEqual([b["time"] for b in bars if b.get("suspect")],
                         [_epoch(12)])
        self.assertIn("1 suspect bar, drawn hollow on candle charts",
                      src["notes"])


# ═══ D2. Weekly candles: one feed's days, by ISO week ═════════════════

class WeeklyCandlesTests(TestCase):
    """Yahoo's daily gold from Monday 2026-10-12 to Tuesday 2026-10-27, read
    on Wednesday 2026-10-28 at 15:20 UTC."""

    DAYS = (["2026-10-%02d" % d for d in (12, 13, 14, 15, 16)]
            + ["2026-10-%02d" % d for d in (19, 20, 21, 22, 23)]
            + ["2026-10-26", "2026-10-27"])

    def setUp(self):
        cache.clear()
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")
        for i, d in enumerate(self.DAYS):
            o = 100 + i
            _bar(self.inst, "1d", datetime.fromisoformat(d).replace(tzinfo=UTC),
                 o, o + 3, o - 2, o + 1, "yfinance", vol=10)

    def series(self, route="", now=NOW, since=None):
        from dashboard.chart_source import weekly_series
        with _no_live_feed():
            return weekly_series(self.inst, since=since, route=route, now=now)

    def test_days_fold_by_iso_week_from_monday(self):
        bars, src = self.series()
        self.assertEqual([b["time"] for b in bars],
                         ["2026-10-12", "2026-10-19", "2026-10-26"])
        first = bars[0]
        self.assertEqual((first["open"], first["high"], first["low"],
                          first["close"], first["volume"]),
                         (100.0, 107.0, 98.0, 105.0, 50.0))
        self.assertEqual(src["family"], "yahoo")
        self.assertTrue(any("weekly candles folded from Yahoo GC=F's days" in n
                            for n in src["notes"]), src["notes"])

    def test_only_the_last_week_forms_and_only_while_it_runs(self):
        bars, _src = self.series()
        self.assertTrue(bars[-1].get("forming"))
        self.assertFalse(any(b.get("forming") for b in bars[:-1]))
        # Monday 00:20 of the week after, with nothing of it stored: the
        # last candle is last week's, closed.
        monday = datetime(2026, 11, 2, 0, 20, tzinfo=UTC)
        later, _src = self.series(now=monday)
        self.assertEqual(later[-1]["time"], "2026-10-26")
        self.assertFalse(later[-1].get("forming"))

    def test_this_weeks_candle_takes_today_from_the_same_feeds_hours(self):
        for hour in (13, 14, 15):
            o = 200 + hour
            _bar(self.inst, "1h", DAY + timedelta(hours=hour), o, o + 2,
                 o - 2, o + 1, "yfinance_public", vol=1)
        bars, src = self.series()
        week = bars[-1]
        self.assertEqual(week["time"], "2026-10-26")
        self.assertEqual(week["open"], 110.0)             # Monday's open
        self.assertEqual(week["close"], 216.0)            # today's 15:00 close
        self.assertEqual(week["high"], 217.0)
        self.assertTrue(week.get("forming"))
        self.assertNotIn("no_tick", week, "it holds today's forming day")
        self.assertTrue(any("this week's candle is forming" in n
                            for n in src["notes"]), src["notes"])
        self.assertFalse(any(n.startswith("today's candle") for n in
                             src["notes"]), src["notes"])

    def test_never_from_another_feeds_hours(self):
        """Today's hours are eToro's: this week's candle keeps Yahoo's days
        and leaves today out, and the legend says why."""
        for hour in (13, 14, 15):
            _bar(self.inst, "1h", DAY + timedelta(hours=hour), 300, 302, 298,
                 301, "etoro")
        bars, src = self.series(route="etoro")
        week = bars[-1]
        self.assertEqual(week["close"], 112.0)            # Tuesday's close
        self.assertEqual(week["high"], 114.0)
        self.assertTrue(week.get("forming"), "the week has not ended")
        self.assertEqual(week.get("no_tick"),
                         "this week's candle leaves today out")
        self.assertTrue(any("this week's candle leaves today out" in n
                            and "eToro" in n for n in src["notes"]),
                        src["notes"])

    def test_another_feeds_day_is_not_folded_in(self):
        """An Alpha Vantage row on Saturday 2026-10-24: the daily series is
        Yahoo's, so the week of the 19th ends on Yahoo's Friday."""
        _bar(self.inst, "1d", datetime(2026, 10, 24, tzinfo=UTC), 500, 900,
             400, 800, "alpha_vantage")
        bars, _src = self.series()
        week = [b for b in bars if b["time"] == "2026-10-19"][0]
        self.assertEqual((week["close"], week["high"], week["low"]),
                         (110.0, 112.0, 103.0))

    def test_a_week_holding_a_suspect_day_is_marked(self):
        from market_data.models import PriceData
        PriceData.objects.filter(
            timestamp=datetime(2026, 10, 21, tzinfo=UTC)).update(
            high=Decimal("106"), open=Decimal("107"), close=Decimal("106.5"),
            low=Decimal("105"))
        bars, src = self.series()
        week = [b for b in bars if b["time"] == "2026-10-19"][0]
        self.assertIn("suspect bar from Yahoo GC=F", week.get("suspect", ""))
        self.assertIn("2026-10-21", week["suspect"])
        self.assertEqual(sum(1 for b in bars if b.get("suspect")), 1)
        self.assertIn("1 suspect bar, drawn hollow on candle charts",
                      src["notes"])

    def test_the_read_starts_on_a_monday(self):
        """Read from Wednesday the 14th, the first week would open at
        Wednesday's price."""
        bars, _src = self.series(since=datetime(2026, 10, 14, 9, tzinfo=UTC))
        self.assertEqual(bars[0]["time"], "2026-10-12")
        self.assertEqual(bars[0]["open"], 100.0)


class ThisWeeksCandleAndTheLiveTickTests(TestCase):
    """This week's candle is `forming` while its ISO week runs (the FORMING
    legend), and takes the live tick only while it holds today's forming
    day: exactly when the daily view's last candle takes it (2026-11-01).

    EURUSD routed to eToro, its normal state: Yahoo EURUSD=X's daily rows
    end on Tuesday 2026-10-27 (the 22:30 UTC pass), and today's hours are
    eToro's (bot_bars writes the venue at 1h and 4h only). Marked forming
    without today, the candle took eToro's quote every 15 s and the 60 s
    refresh took it away again: the week's close, and its high or low,
    flipped once a minute between Tuesday's figures and the live price,
    while the daily view, its last candle Tuesday's and closed, refused
    the same quote."""

    DAYS = ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22",
            "2026-10-23", "2026-10-26", "2026-10-27")

    def setUp(self):
        cache.clear()
        self.inst = _inst("EURUSD", "forex", "Euro")
        for i, d in enumerate(self.DAYS):
            o = round(1.1 + i / 1000, 4)
            _bar(self.inst, "1d", datetime.fromisoformat(d).replace(tzinfo=UTC),
                 o, round(o + 0.003, 4), round(o - 0.002, 4),
                 round(o + 0.001, 4), "yfinance")

    def hours(self, source):
        for hour in (12, 13, 14, 15):
            _bar(self.inst, "1h", DAY + timedelta(hours=hour), 1.12, 1.123,
                 1.119, 1.122, source)

    def weekly(self, route="etoro", now=NOW):
        from dashboard.chart_source import weekly_series
        with _no_live_feed():
            return weekly_series(self.inst, route=route, now=now)

    def test_a_week_without_today_says_it_takes_no_tick(self):
        from dashboard.chart_source import daily_series
        self.hours("etoro")
        bars, src = self.weekly()
        week = bars[-1]
        self.assertEqual((week["time"], week["close"], week["high"]),
                         ("2026-10-26", 1.107, 1.109))    # Tuesday's figures
        self.assertTrue(week.get("forming"), "the week has not ended")
        self.assertEqual(week.get("no_tick"),
                         "this week's candle leaves today out")
        self.assertFalse(any("no_tick" in b for b in bars[:-1]))
        self.assertIn("this week's candle leaves today out: today's intraday "
                      "bars are eToro's, not Yahoo EURUSD=X's", src["notes"])
        self.assertEqual(src["stand_in"], "")
        self.assertFalse(src["same_feed_only"])
        # The daily view of the same instrument: Tuesday's candle, closed.
        with _no_live_feed():
            days, _dsrc = daily_series(self.inst, route="etoro", now=NOW)
        self.assertEqual(days[-1]["time"], "2026-10-27")
        self.assertFalse(days[-1].get("forming"))

    def test_a_week_holding_todays_forming_day_takes_it(self):
        self.hours("yfinance_public")
        bars, _src = self.weekly(route="")
        week = bars[-1]
        self.assertEqual((week["open"], week["high"], week["close"]),
                         (1.105, 1.123, 1.122))           # today's 15:00 close
        self.assertTrue(week.get("forming"))
        self.assertNotIn("no_tick", week)

    def test_a_week_with_nothing_of_today_takes_no_tick(self):
        """No feed has a bar of today yet (forex just after the Sunday
        reopen, a stock before its open): the candle is Monday's and
        Tuesday's."""
        bars, _src = self.weekly(route="")
        self.assertTrue(bars[-1].get("forming"))
        self.assertEqual(bars[-1].get("no_tick"),
                         "this week's candle leaves today out")

    def test_a_week_ending_on_todays_stored_day_takes_no_tick(self):
        """After the 22:30 UTC pass Yahoo's row of today is stored: the
        daily view draws it as a closed candle and takes no tick, nor does
        the week that ends on it."""
        _bar(self.inst, "1d", DAY, 1.107, 1.112, 1.105, 1.111, "yfinance")
        bars, _src = self.weekly(route="",
                                 now=DAY + timedelta(hours=22, minutes=40))
        week = bars[-1]
        self.assertEqual((week["time"], week["close"]), ("2026-10-26", 1.111))
        self.assertTrue(week.get("forming"))
        self.assertEqual(week.get("no_tick"), "today's daily candle has closed")

    def test_a_closed_week_carries_no_reason(self):
        """Monday 00:20 of the week after: last week's candle has closed,
        and the widget's own "the last candle has closed" says so."""
        bars, _src = self.weekly(route="",
                                 now=datetime(2026, 11, 2, 0, 20, tzinfo=UTC))
        self.assertEqual(bars[-1]["time"], "2026-10-26")
        self.assertFalse(bars[-1].get("forming"))
        self.assertNotIn("no_tick", bars[-1])


def _sessions(first_monday, weeks):
    """Monday to Friday of `weeks` weeks from `first_monday`."""
    return [first_monday + timedelta(days=7 * w + d)
            for w in range(weeks) for d in range(5)]


def _yahoo_days(symbol, yahoo_symbol, days, tz):
    """`days` written by the EOD writer itself
    (market_data.adapters.yfinance_adapter.save_history_to_db) from what
    yfinance's Ticker.history(interval="1d") answers: each session at
    midnight in the exchange's own zone. Session i opens 100+i, high +3,
    low -2, close +1, volume 10."""
    import pandas as pd

    from market_data.adapters import yfinance_adapter
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days]).tz_localize(tz)
    opens = [100.0 + i for i in range(len(days))]
    frame = pd.DataFrame({"Open": opens, "High": [o + 3 for o in opens],
                          "Low": [o - 2 for o in opens],
                          "Close": [o + 1 for o in opens],
                          "Volume": [10] * len(days)}, index=index)
    ticker = mock.MagicMock()
    ticker.history.return_value = frame
    with mock.patch.object(yfinance_adapter, "_get_ticker",
                           return_value=ticker):
        return yfinance_adapter.save_history_to_db(
            symbol, period="3mo", fetch_symbol=yahoo_symbol)


class WeeklyCandlesBySessionTests(TestCase):
    """A day goes into the week of its SESSION (2026-11-01).

    Yahoo stamps a daily bar at midnight in the exchange's zone, and the
    EOD writer stores that instant as it is: DAX40's Monday 2026-10-12 at
    Sunday 22:00 UTC (summer time), its Monday 2026-10-26 at Sunday 23:00
    UTC, the Nikkei's and the ASX's Mondays on Sunday afternoon UTC,
    EURUSD=X's days in British Summer Time at 23:00 UTC the day before.
    Folded by the UTC date of the stamp, Monday's session went into the
    week before: every weekly candle opened at Tuesday's open and closed at
    the next Monday's close, and the Monday 22:30 UTC pass moved Monday out
    of this week's candle into last week's."""

    def setUp(self):
        cache.clear()

    def weekly(self, inst, now, since=None, route=""):
        from dashboard.chart_source import weekly_series
        with _no_live_feed():
            return weekly_series(inst, since=since, route=route, now=now)

    def test_monday_opens_its_own_week(self):
        from market_data.models import PriceData
        inst = _inst("DAX40", "index", "Germany 40")
        self.assertEqual(_yahoo_days("DAX40", "^GDAXI",
                                     _sessions(date(2026, 10, 12), 3),
                                     "Europe/Berlin"), 15)
        stamps = list(PriceData.objects.filter(instrument=inst, timeframe="1d")
                      .order_by("timestamp")
                      .values_list("timestamp", flat=True))
        self.assertEqual(stamps[0], datetime(2026, 10, 11, 22, tzinfo=UTC))
        self.assertEqual(stamps[10], datetime(2026, 10, 25, 23, tzinfo=UTC))
        bars, _src = self.weekly(inst, datetime(2026, 10, 31, 10, tzinfo=UTC))
        self.assertEqual(
            [(b["time"], b["open"], b["high"], b["low"], b["close"],
              b["volume"]) for b in bars],
            [("2026-10-12", 100.0, 107.0, 98.0, 105.0, 50.0),
             ("2026-10-19", 105.0, 112.0, 103.0, 110.0, 50.0),
             ("2026-10-26", 110.0, 117.0, 108.0, 115.0, 50.0)])

    def test_east_of_utc_every_monday_is_its_own(self):
        for symbol, yahoo, tz in (("NIKKEI225", "^N225", "Asia/Tokyo"),
                                  ("ASX200", "^AXJO", "Australia/Sydney"),
                                  ("FTSE100", "^FTSE", "Europe/London")):
            with self.subTest(symbol):
                inst = _inst(symbol, "index")
                _yahoo_days(symbol, yahoo, _sessions(date(2026, 9, 14), 2), tz)
                bars, _src = self.weekly(inst,
                                         datetime(2026, 9, 26, 10, tzinfo=UTC))
                self.assertEqual(
                    [(b["time"], b["open"], b["close"]) for b in bars],
                    [("2026-09-14", 100.0, 105.0),
                     ("2026-09-21", 105.0, 110.0)])

    def test_forex_in_british_summer_time(self):
        inst = _inst("EURUSD", "forex", "Euro")
        _yahoo_days("EURUSD", "EURUSD=X", _sessions(date(2026, 7, 6), 2),
                    "Europe/London")
        bars, _src = self.weekly(inst, datetime(2026, 7, 18, 10, tzinfo=UTC))
        self.assertEqual([(b["time"], b["open"], b["close"]) for b in bars],
                         [("2026-07-06", 100.0, 105.0),
                          ("2026-07-13", 105.0, 110.0)])

    def test_monday_stays_in_this_week_after_the_eod_pass(self):
        """Monday 2026-10-26: through the session this week's candle forms
        from Yahoo's own hours; after the 22:30 UTC pass writes Monday's
        daily bar (at Sunday 23:00 UTC) that bar is this week's candle, and
        last week's closes on Friday."""
        inst = _inst("DAX40", "index", "Germany 40")
        days = _sessions(date(2026, 10, 12), 2)
        _yahoo_days("DAX40", "^GDAXI", days, "Europe/Berlin")
        monday = datetime(2026, 10, 26, tzinfo=UTC)
        for hour in range(8, 16):
            o = 500 + hour
            _bar(inst, "1h", monday + timedelta(hours=hour), o, o + 2, o - 2,
                 o + 1, "yfinance_public", vol=1)
        during, _src = self.weekly(inst, monday + timedelta(hours=16))
        self.assertEqual((during[-1]["time"], during[-1]["open"],
                          during[-1]["close"]), ("2026-10-26", 508.0, 516.0))
        self.assertTrue(during[-1].get("forming"))

        _yahoo_days("DAX40", "^GDAXI", days + [date(2026, 10, 26)],
                    "Europe/Berlin")
        after, src = self.weekly(inst, monday + timedelta(hours=22, minutes=40))
        self.assertEqual([(b["time"], b["open"], b["close"]) for b in after],
                         [("2026-10-12", 100.0, 105.0),
                          ("2026-10-19", 105.0, 110.0),
                          ("2026-10-26", 110.0, 111.0)])
        self.assertFalse(after[1].get("forming"))
        self.assertTrue(after[2].get("forming"))
        # Today's session is in it, stored: no word says it is left out.
        self.assertEqual(after[2].get("no_tick"),
                         "today's daily candle has closed")
        self.assertFalse(any("leaves today out" in n for n in src["notes"]),
                         src["notes"])

    def test_the_first_monday_of_the_read_is_kept(self):
        """The view reads from a Monday 00:00 UTC, and DAX40's Monday
        session is stamped two hours before it; the week before is not
        drawn."""
        inst = _inst("DAX40", "index", "Germany 40")
        _yahoo_days("DAX40", "^GDAXI", _sessions(date(2026, 10, 5), 3),
                    "Europe/Berlin")
        bars, _src = self.weekly(inst, datetime(2026, 10, 24, 10, tzinfo=UTC),
                                 since=datetime(2026, 10, 14, 9, tzinfo=UTC))
        self.assertEqual([(b["time"], b["open"], b["close"]) for b in bars],
                         [("2026-10-12", 105.0, 110.0),
                          ("2026-10-19", 110.0, 115.0)])

    def test_new_york_midnight_stays_on_its_day(self):
        """A stamp west of UTC sits on its own UTC date already (00:00 New
        York is 04:00 UTC), as a 00:00 UTC stamp does (WeeklyCandlesTests)."""
        inst = _inst("AAPL", "stock", "Apple")
        _yahoo_days("AAPL", "AAPL", _sessions(date(2026, 10, 12), 2),
                    "America/New_York")
        bars, _src = self.weekly(inst, datetime(2026, 10, 24, 10, tzinfo=UTC))
        self.assertEqual([(b["time"], b["open"], b["close"]) for b in bars],
                         [("2026-10-12", 100.0, 105.0),
                          ("2026-10-19", 105.0, 110.0)])


# ═══ D3. 10 min and 30 min, live from the keyless feed ════════════════

class TheLiveFinerFramesTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("div_u", password="x")
        self.client.force_login(self.user)

    @staticmethod
    def _feed(step_s=300, n=5, start=1_700_000_400):
        """A keyless feed answering `n` bars of `step_s` from `start` (a
        multiple of 600), for any interval."""
        feed = mock.MagicMock()
        rows = []
        for k in range(n):
            t = start + k * step_s
            o = 100 + k
            rows.append([t * 1000, str(o), str(o + 2), str(o - 1),
                         str(o + 1), "10"])
        feed.klines.return_value = rows
        return feed

    def chart(self, symbol, tf):
        resp = self.client.get("/api/chart-data/",
                               {"symbol": symbol, "timeframe": tf})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return json.loads(resp.content.decode())

    def test_neither_keyless_feed_serves_10_minutes(self):
        from dashboard.chart_source import _native
        self.assertFalse(_native("yahoo", "10m"))
        self.assertFalse(_native("binance", "10m"))
        self.assertTrue(_native("yahoo", "30m"))
        self.assertTrue(_native("binance", "30m"))
        self.assertTrue(_native("yahoo", "5m"))
        self.assertTrue(_native("binance", "5m"))

    def test_10_minutes_fold_the_feeds_5_minute_bars(self):
        _inst("AAPL", "stock", "Apple")
        start = 1_700_000_400                      # a 10-minute grid line
        feed = self._feed(step_s=300, n=5, start=start)
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            body = self.chart("AAPL", "10min")
        call = feed.klines.call_args
        self.assertEqual(call.kwargs.get("interval"), "5m")
        self.assertEqual(call.kwargs.get("limit"), 480)
        bars = body["bars"]
        self.assertEqual([b["time"] for b in bars],
                         [start, start + 600, start + 1200])
        self.assertEqual((bars[0]["open"], bars[0]["high"], bars[0]["low"],
                          bars[0]["close"], bars[0]["volume"]),
                         (100.0, 103.0, 99.0, 102.0, 20.0))
        # the partial last bucket is drawn as it stands: the forming bar
        self.assertEqual((bars[2]["open"], bars[2]["close"]), (104.0, 105.0))
        self.assertTrue(any("10 min candles folded from Yahoo AAPL's 5 min "
                            "bars" in n for n in body["source"]["notes"]),
                        body["source"]["notes"])

    def test_10_minutes_are_kept_a_minute_apart_from_the_5_minute_view(self):
        _inst("BTCUSD", "crypto", "Bitcoin")
        feed = self._feed(step_s=300, n=4)
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            first = self.chart("BTCUSD", "10min")
            self.chart("BTCUSD", "10min")
            self.assertEqual(feed.klines.call_count, 1,
                             "the second hit inside a minute is cached")
            self.assertEqual(feed.klines.call_args.args[0], "BTCUSDT")
            self.chart("BTCUSD", "5min")
        self.assertEqual(feed.klines.call_count, 2)
        self.assertEqual(feed.klines.call_args.kwargs.get("limit"), 240,
                         "the 5 min view keeps its own 240 bars")
        self.assertEqual(first["source"]["family"], "binance")
        self.assertIn("Binance BTCUSDT", first["source"]["words"])

    def test_30_minutes_are_the_feeds_own(self):
        _inst("AAPL", "stock", "Apple")
        feed = self._feed(step_s=1800, n=3, start=1_699_999_200)
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            body = self.chart("AAPL", "30min")
        self.assertEqual(feed.klines.call_args.kwargs.get("interval"), "30m")
        self.assertEqual(feed.klines.call_args.kwargs.get("limit"), 240)
        self.assertEqual([b["time"] for b in body["bars"]],
                         [1_699_999_200, 1_700_001_000, 1_700_002_800])
        self.assertFalse(any("folded" in n for n in body["source"]["notes"]))

    def test_nothing_is_stored(self):
        from market_data.models import PriceData
        _inst("AAPL", "stock", "Apple")
        feed = self._feed()
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            self.chart("AAPL", "10min")
            self.chart("AAPL", "30min")
        self.assertFalse(PriceData.objects.exists())


# ═══ D4. The API: the new frames, the old ones, and no others ═════════

class TheApiTakesTheFramesItKnowsTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("div_api", password="x")
        self.client.force_login(self.user)
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")
        now = timezone.now()
        self.today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for k in range(1, 40):
            _bar(self.inst, "1d", self.today - timedelta(days=k), 100, 103,
                 98, 101, "yfinance")
        base = now.replace(minute=0, second=0, microsecond=0)
        for k in range(1, 30):
            _bar(self.inst, "1h", base - timedelta(hours=k), 100, 102, 99,
                 101, "yfinance_public")

    def get(self, tf):
        return self.client.get("/api/chart-data/",
                               {"symbol": "XAUUSD", "timeframe": tf})

    def test_the_new_frames_answer(self):
        feed = TheLiveFinerFramesTests._feed()
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            for tf in ("10min", "30min"):
                resp = self.get(tf)
                self.assertEqual(resp.status_code, 200, tf)
                self.assertNotIn("error", resp.json(), tf)
        two = self.get("2h").json()
        self.assertNotIn("error", two)
        self.assertTrue(two["bars"])
        self.assertTrue(all(isinstance(b["time"], int) and b["time"] % 7200 == 0
                            for b in two["bars"]))
        week = self.get("1wk").json()
        self.assertNotIn("error", week)
        self.assertTrue(week["bars"])
        for b in week["bars"]:
            self.assertEqual(
                datetime.fromisoformat(b["time"]).weekday(), 0, b["time"])

    def test_the_old_frames_still_answer(self):
        feed = TheLiveFinerFramesTests._feed()
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            for tf in ("1min", "5min", "15min", "1h", "4h", "1d", "1w", "1mo",
                       "1m", "3m", "1y", "1D", "1W"):
                resp = self.get(tf)
                self.assertEqual(resp.status_code, 200, tf)

    def test_a_timeframe_it_does_not_know_is_refused(self):
        """It drew 90 days of daily candles for any word. '10m' and '30m'
        are refused too: on this API a bare 'm' has always meant a month."""
        for tf in ("7min", "2w", "1q", "weekly", "10m", "30m", "1wkk"):
            resp = self.get(tf)
            self.assertEqual(resp.status_code, 400, tf)
            body = resp.json()
            self.assertEqual(body["bars"], [], tf)
            self.assertIn(tf, body["error"])

    def test_the_1w_range_is_two_weeks_of_daily_candles(self):
        """It read 730 days, the same two years as 1Y; as 1M reads two
        months, 1W reads two weeks."""
        days = {b["time"] for b in self.get("1w").json()["bars"]}
        self.assertIn((self.today - timedelta(days=10)).strftime("%Y-%m-%d"),
                      days)
        self.assertNotIn((self.today - timedelta(days=20))
                         .strftime("%Y-%m-%d"), days)
        month = {b["time"] for b in self.get("1mo").json()["bars"]}
        self.assertIn((self.today - timedelta(days=20)).strftime("%Y-%m-%d"),
                      month)


# ═══ D5. The toolbar ══════════════════════════════════════════════════

def _widget(**ctx):
    base = {"chart_id": "t", "symbol": "XAUUSD", "height": "420",
            "timeframe": "1d", "decimals": 2}
    base.update(ctx)
    return render_to_string("_partials/chart_widget.html", base)


BUTTON = re.compile(r'<button class="sv-tf-btn([^"]*)" data-tf="([^"]+)"'
                    r'[^>]*>([^<]+)</button>')


class TheToolbarTests(SimpleTestCase):

    def test_candle_sizes_then_ranges_in_order(self):
        got = [(tf, label) for _cls, tf, label in BUTTON.findall(_widget())]
        self.assertEqual(got, [
            ("1min", "1m"), ("5min", "5m"), ("10min", "10m"),
            ("15min", "15m"), ("30min", "30m"), ("1h", "1H"), ("2h", "2H"),
            ("4h", "4H"), ("1d", "D"), ("1wk", "W"),
            ("1w", "1W"), ("1mo", "1M"), ("3m", "3M"), ("1y", "1Y")])

    def test_each_group_is_named(self):
        html = _widget()
        sizes = html.split('aria-label="Candle size"', 1)[1].split("</div>", 1)[0]
        ranges = html.split('aria-label="Range of daily candles"', 1)[1] \
            .split("</div>", 1)[0]
        self.assertEqual([tf for _c, tf, _l in BUTTON.findall(sizes)],
                         ["1min", "5min", "10min", "15min", "30min", "1h",
                          "2h", "4h", "1d", "1wk"])
        self.assertEqual([tf for _c, tf, _l in BUTTON.findall(ranges)],
                         ["1w", "1mo", "3m", "1y"])
        self.assertIn('<span class="sv-tf-cap" aria-hidden="true">Candle</span>',
                      sizes)
        self.assertIn('<span class="sv-tf-cap" aria-hidden="true">Range</span>',
                      ranges)

    def test_every_button_says_what_it_draws(self):
        html = _widget()
        for tf, words in (("10min", "10-minute candles"),
                          ("2h", "2-hour candles"),
                          ("1d", "Daily candles"),
                          ("1wk", "Weekly candles"),
                          ("1w", "Daily candles over the last two weeks"),
                          ("1y", "Daily candles over the last two years")):
            tag = re.search(r'<button class="sv-tf-btn[^"]*" data-tf="%s"[^>]*>'
                            % tf, html).group(0)
            self.assertIn('title="%s' % words, tag)

    def test_the_include_marks_a_new_frame_active(self):
        for tf in ("10min", "30min", "2h", "1wk"):
            active = [t for cls, t, _l in BUTTON.findall(_widget(timeframe=tf))
                      if "active" in cls]
            self.assertEqual(active, [tf])

    def test_the_new_intraday_frames_have_their_seconds(self):
        html = _widget()
        self.assertIn("var INTRADAY     = ['1min', '5min', '10min', '15min', "
                      "'30min', '1h', '2h', '4h'];", html)
        self.assertIn("var TF_SECONDS   = { '1min': 60, '5min': 300, "
                      "'10min': 600, '15min': 900, '30min': 1800, "
                      "'1h': 3600, '2h': 7200, '4h': 14400 };", html)
        self.assertIn("var WEEKLY_TF    = '1wk';", html)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class ThePhoneToolbarMeasuredTests(TestCase):
    """The instrument page's chart toolbar measured in Chromium at phone
    widths (2026-11-01): the page the test client renders, its stylesheets
    read from static/, its scripts dropped and no web font, so the labels
    are drawn in the fallback monospace, wider than Share Tech Mono (the
    harder case: about 0.6 em a character against 0.54).

    The ten candle sizes and their name keep one row from a 360 px phone
    up, and nothing runs past the screen. With 5 px of air in each button
    and 2 px between them the group needed 307 px in the fallback font
    (291 in Share Tech Mono), the toolbar holds 284 at 360 px and 299 at
    375, and W, or D and W, wrapped onto a line of its own directly above
    RANGE 1W: the W/1W confusion the group names were there to end."""

    WIDTHS = ((360, 780), (375, 812), (390, 844))
    PROBE = r"""(function () {
        var c = document.querySelector('.sv-candle-container');
        var bar = c.querySelector('.sv-chart-toolbar');
        /* The group's lines: an item whose middle sits within 6 px of the
           line's is on it (the 9 px name and the 10 px buttons share a
           line without sharing a top). */
        function rows(sel) {
            var lines = [];
            Array.prototype.forEach.call(c.querySelector(sel).children, function (el) {
                var r = el.getBoundingClientRect(), mid = (r.top + r.bottom) / 2;
                var line = lines.filter(function (l) { return Math.abs(l.mid - mid) <= 6; })[0];
                if (!line) lines.push(line = { mid: mid, words: [] });
                line.words.push((el.textContent || '').trim());
            });
            return lines.sort(function (a, b) { return a.mid - b.mid; })
                .map(function (l) { return l.words.join(' '); });
        }
        return JSON.stringify({
            width: window.innerWidth,
            candle: rows('.sv-chart-timeframes[aria-label="Candle size"]'),
            ranges: rows('.sv-chart-timeframes[aria-label="Range of daily candles"]'),
            toolbarOverflow: bar.scrollWidth - bar.clientWidth,
            pageScroll: document.documentElement.scrollWidth
                        - document.documentElement.clientWidth
        });
    })()"""

    @classmethod
    def setUpTestData(cls):
        """One render, one browser, the three widths (inside the class's
        transaction, which a failure here rolls back)."""
        from django.test import Client
        user = User.objects.create_user("div_phone", password="x")
        _inst("XAUUSD", "commodity", "Gold Spot")
        client = Client()
        client.force_login(user)
        page = client.get("/instruments/XAUUSD/").content.decode("utf-8")
        page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
        page = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", page)
        page = page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
        tmp = tempfile.mkdtemp(prefix="sv-tf-phone-")
        try:
            path = pathlib.Path(tmp) / "instrument.html"
            path.write_text(page, encoding="utf-8")
            chrome = _Chrome(CHROME)
            try:
                cls.got = {}
                for width, height in cls.WIDTHS:
                    sid = chrome.page(width, height, True)
                    chrome.open(sid, path.as_uri())
                    cls.got[width] = json.loads(chrome.eval(sid, cls.PROBE))
            finally:
                chrome.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_candle_sizes_keep_one_row(self):
        for width, _height in self.WIDTHS:
            got = self.got[width]
            with self.subTest(width=width):
                self.assertEqual(got["width"], width)
                self.assertEqual(got["candle"],
                                 ["Candle 1m 5m 10m 15m 30m 1H 2H 4H D W"], got)
                self.assertEqual(got["ranges"], ["Range 1W 1M 3M 1Y"], got)

    def test_nothing_runs_past_the_screen(self):
        for width, _height in self.WIDTHS:
            got = self.got[width]
            with self.subTest(width=width):
                self.assertLessEqual(got["toolbarOverflow"], 0, got)
                self.assertLessEqual(got["pageScroll"], 0, got)
