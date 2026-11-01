"""The chart shows one honest price (2026-10-31).

The operator: "sometimes the graph and the price written arent perfectly
the same and some spikes up or down happen for no reason". The instrument
page drew one instrument from up to five feeds: eToro's CFD candles on 1h
and 4h, Yahoo's future or cash index on the daily and the minute frames,
the platform quote (LiveQuote, whichever feed won last) in the hero and
welded onto the last candle every 15 seconds, eToro's bid in the
positions row. Nothing filtered a bar that could not have traded.

What this pins, display and data hygiene only (no gate moves):

  F1  one feed per chart series, named in words the legend prints;
  F3a the hero says whose price it is, its age, the stand-in words, and
      the venue's last known price beside it, with no new eToro request;
  F4  a quote write that carries no bid/ask clears the row's sides, and
      the day change chip says when it is another feed's (M3);
  F5a a bar that cannot have traded is refused at the writer; an eToro
      answer of nothing but such bars is "not now", never a 6-hour mute;
  F5b the chart marks such a bar (hollow, "suspect bar from ...");
  F6a the daily view builds today's forming candle from same-feed bars;
  F6b the crypto EOD writes only closed daily klines;
  F7  the hero repaints at the instrument's own precision;
  F8  Yahoo's 4h on a fixed UTC grid, and a dry-run-first command for the
      off-grid duplicates;
  F9  the EOD pass rewrites the last two days;
  M1  the watchlist pass never writes the public feed over the venue's
      bars;
  M2  a streamer broadcasts only the ticks write_quote accepted;
  M4  position lines (venue prices) over public-feed candles: the legend
      says so;
  R   the review of the first cut: a stale venue gives way only to newer
      bars and never across a hole; newer bars of another feed are named;
      a day folded from intraday rows forms; routed crypto says why today
      is not drawn; a venue is one the operator holds; crypto candles
      weld only their own feed; the venue's last price is dated by its
      own answer; a refused bar keeps its slot; the read loop never waits
      on a write.

Run with:  python manage.py test tests.test_chart_one_price
"""
import json
import time as _time
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

H = 3600
FOUR_H = 4 * H
STEP4 = timedelta(hours=4)


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


def _grid_now(step=FOUR_H):
    now = int(_time.time())
    return datetime.fromtimestamp(now - now % step, tz=dt_tz.utc)


def _route(name):
    """The router's answer for every symbol (no account, no request)."""
    return mock.patch(
        "bot_program.engine.broker_router.broker_name_for_symbol",
        return_value=name)


def _src(name):
    return (Path(settings.BASE_DIR) / name).read_text(encoding="utf-8")


def _open_tag(body, cls):
    """The opening tag of the first element whose class is exactly `cls`."""
    before, after = body.split(f'class="{cls}"', 1)
    return before.rsplit("<", 1)[1] + f'class="{cls}"' + after.split(">", 1)[0]


class _Logged(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("onepx_u", password="x")
        self.client.force_login(self.user)

    def chart(self, symbol, tf, overlays=False):
        q = {"symbol": symbol, "timeframe": tf}
        if overlays:
            q["overlays"] = "1"
        resp = self.client.get("/api/chart-data/", q)
        self.assertEqual(resp.status_code, 200)
        # A NaN anywhere makes the reply invalid JSON for the browser.
        return json.loads(resp.content.decode(), parse_constant=self._nan)

    @staticmethod
    def _nan(word):
        raise AssertionError(f"the reply carries a bare {word}")


# ═══ F1. One feed per series, named ═══════════════════════════════════

class OneFeedPerSeriesTests(_Logged):
    """eToro's 4h closes 4000-4003, then two Yahoo GC=F stand-ins at
    4036-4037 written after eToro's newest bar, and Yahoo history behind
    eToro's first bar: the report's proof run drew all of it as one
    series."""

    def setUp(self):
        super().setUp()
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")
        end = _grid_now()
        venue = [end - STEP4 * k for k in (5, 4, 3, 2)]
        for i, t in enumerate(venue):
            c = 4000 + i
            _bar(self.inst, "4h", t, c, c + 2, c - 2, c, "etoro")
        _bar(self.inst, "4h", end - STEP4, 4036, 4038, 4034, 4036,
             "yfinance_public")
        _bar(self.inst, "4h", end, 4037, 4039, 4035, 4037,
             "yfinance_public")
        for k in (9, 8, 7):
            _bar(self.inst, "4h", end - STEP4 * k, 4030, 4032, 4028, 4031,
                 "yfinance_public")

    def test_routed_to_etoro_the_series_is_etoros_alone(self):
        with _route("etoro"):
            body = self.chart("XAUUSD", "4h")
        closes = [b["close"] for b in body["bars"]]
        self.assertEqual(closes, [4000.0, 4001.0, 4002.0, 4003.0])
        src = body["source"]
        self.assertEqual(src["family"], "etoro")
        self.assertIn("eToro", src["words"])
        # History before eToro's first bar is cut, and the legend says so.
        self.assertTrue(any("older bars" in n for n in src["notes"]),
                        src["notes"])

    def test_newer_bars_of_another_feed_are_named_not_hidden(self):
        """eToro's 4h ends eight hours ago and Yahoo GC=F has the two bars
        since (written while eToro was muted, paced or refused): the chart
        ended at eToro's last candle with nothing saying newer bars
        exist (2026-10-31, review of the first cut)."""
        with _route("etoro"):
            body = self.chart("XAUUSD", "4h")
        notes = body["source"]["notes"]
        self.assertTrue(any("2 newer bars from Yahoo GC=F are not drawn" in n
                            for n in notes), notes)
        self.assertTrue(any("eToro's newest 4h candle is" in n
                            for n in notes), notes)

    def test_not_routed_to_a_venue_the_public_feed_alone(self):
        with _route("paper"):
            body = self.chart("XAUUSD", "4h")
        closes = [b["close"] for b in body["bars"]]
        self.assertEqual(closes, [4031.0, 4031.0, 4031.0, 4036.0, 4037.0])
        src = body["source"]
        self.assertEqual(src["family"], "yahoo")
        self.assertEqual(src["stand_in"], "future")
        self.assertIn("Yahoo GC=F", src["words"])
        self.assertIn("future", src["words"])

    def test_routed_to_etoro_without_its_candles_says_whose_they_are(self):
        from market_data.models import PriceData
        PriceData.objects.filter(source="etoro").delete()
        with _route("etoro"):
            body = self.chart("XAUUSD", "4h")
        src = body["source"]
        self.assertEqual(src["family"], "yahoo")
        self.assertIn("GC=F", src["words"])
        self.assertIn("not eToro", src["words"])

    def test_a_feed_the_table_does_not_know_still_draws(self):
        """Every other writer (a test fixture, IBKR, Alpha Vantage) keeps
        its chart: the newest row's feed is the fallback."""
        other = _inst("AAPL", "stock", "Apple")
        base = _grid_now(H)
        for k in range(3):
            _bar(other, "1h", base - timedelta(hours=k), 1, 2, 0.5, 1.5,
                 "test")
        with _route("paper"):
            body = self.chart("AAPL", "1h")
        self.assertEqual(len(body["bars"]), 3)
        self.assertEqual(body["source"]["family"], "test")

    def test_the_daily_series_is_one_feed(self):
        day = timezone.now().replace(hour=4, minute=0, second=0,
                                     microsecond=0)
        for k in range(1, 5):
            src = "yfinance" if k % 2 else "alpha_vantage"
            _bar(self.inst, "1d", day - timedelta(days=k), 4000, 4010, 3990,
                 4000 + k, src)
        with _route("paper"):
            body = self.chart("XAUUSD", "1d")
        stored = [b for b in body["bars"] if not b.get("forming")]
        self.assertEqual([b["close"] for b in stored], [4003.0, 4001.0])
        # Today's candle, when drawn, is the same feed's (Yahoo's 4h
        # stand-ins of today), never eToro's.
        for b in body["bars"]:
            if b.get("forming"):
                self.assertEqual(b["close"], 4037.0)
        self.assertEqual(body["source"]["family"], "yahoo")
        self.assertIn("Yahoo GC=F", body["source"]["words"])

    def test_the_minute_frames_name_their_feed(self):
        feed = mock.MagicMock()
        feed.klines.return_value = [
            [1700000000000, "1", "2", "0.5", "1.5", "10"]]
        btc = _inst("BTCUSD", "crypto", "Bitcoin")
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed), _route("paper"):
            body = self.chart("BTCUSD", "5min")
        self.assertEqual(body["source"]["family"], "binance")
        self.assertIn("Binance BTCUSDT", body["source"]["words"])
        self.assertTrue(btc)


# ═══ F5b. A bar that cannot have traded is marked, not hidden ═════════

class SuspectBarsAreMarkedTests(_Logged):

    def test_a_stored_impossible_bar_is_drawn_and_named(self):
        inst = _inst("EURUSD", "forex", "Euro")
        base = _grid_now(H)
        _bar(inst, "1h", base - timedelta(hours=2), 1.08, 1.09, 1.07, 1.085,
             "yfinance_public")
        # high under the open, low at zero: the report's proof bar
        _bar(inst, "1h", base - timedelta(hours=1), 1.085, 1.084, 0, 1.0855,
             "yfinance_public")
        _bar(inst, "1h", base, 1.0855, 1.087, 1.084, 1.086,
             "yfinance_public")
        with _route("paper"):
            body = self.chart("EURUSD", "1h")
        self.assertEqual(len(body["bars"]), 3, "a suspect bar is not hidden")
        flagged = [b for b in body["bars"] if b.get("suspect")]
        self.assertEqual(len(flagged), 1)
        self.assertIn("suspect bar from Yahoo EURUSD=X", flagged[0]["suspect"])
        self.assertTrue(any("suspect" in n for n in body["source"]["notes"]))

    def test_the_note_says_hollow_only_of_candles(self):
        """A line or area chart draws the close alone, so "drawn hollow"
        was untrue there (2026-10-31, review of the first cut)."""
        inst = _inst("EURUSD", "forex", "Euro")
        base = _grid_now(H)
        _bar(inst, "1h", base - timedelta(hours=1), 1.085, 1.084, 0, 1.0855,
             "yfinance_public")
        _bar(inst, "1h", base, 1.0855, 1.087, 1.084, 1.086,
             "yfinance_public")
        with _route("paper"):
            body = self.chart("EURUSD", "1h")
        self.assertIn("1 suspect bar, drawn hollow on candle charts",
                      body["source"]["notes"])

    def test_the_live_minute_path_marks_them_and_drops_an_unreadable_one(self):
        """The skeptic's M5 trigger: a NaN in a Yahoo minute frame made the
        whole reply invalid JSON, and the empty answer was cached."""
        _inst("AAPL", "stock", "Apple")
        feed = mock.MagicMock()
        feed.klines.return_value = [
            [1700000000000, "1", "2", "0.5", "1.5", "10"],
            [1700000060000, "nan", "2", "0.5", "1.5", "10"],
            [1700000120000, "1.5", "1.2", "1", "1.4", "10"],
            [1700000180000, "1.4", "1.6", "1.3", "1.5", "10"],
        ]
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed), _route("paper"):
            body = self.chart("AAPL", "1min")
        times = [b["time"] for b in body["bars"]]
        self.assertEqual(times, [1700000000, 1700000120, 1700000180])
        self.assertTrue(body["bars"][1].get("suspect"))
        self.assertFalse(body["bars"][0].get("suspect"))
        self.assertTrue(any("left out" in n for n in body["source"]["notes"]))


class BarShapeTests(SimpleTestCase):

    def test_the_invariants(self):
        from market_data.bar_shape import possible
        self.assertTrue(possible(1, 2, 0.5, 1.5))
        self.assertTrue(possible(1, 1, 1, 1))           # a flat bar traded
        self.assertFalse(possible(100, 99, 0, 100.5))   # the proof bar
        self.assertFalse(possible(1, 2, 0, 1.5))        # a low at zero
        self.assertFalse(possible(1, 0.9, 0.5, 0.8))    # high under the open
        self.assertFalse(possible(1, 2, 1.2, 1.5))      # low over the open
        self.assertFalse(possible(float("nan"), 2, 0.5, 1.5))
        self.assertFalse(possible(1, float("inf"), 0.5, 1.5))
        self.assertFalse(possible(None, 2, 0.5, 1.5))
        self.assertFalse(possible("x", 2, 0.5, 1.5))

    def test_a_spike_from_another_feed_is_suspect_and_one_from_its_own_is_not(self):
        from market_data.bar_shape import mark_suspects
        bars = [{"time": i, "open": 100, "high": 101, "low": 99,
                 "close": 100, "src": "eToro"} for i in range(9)]
        bars[4] = {"time": 4, "open": 100, "high": 130, "low": 70,
                   "close": 100, "src": "Yahoo GC=F"}
        mark_suspects(bars, "eToro")
        self.assertIn("suspect bar from Yahoo GC=F", bars[4]["suspect"])
        self.assertEqual([b for b in bars if b.get("suspect")], [bars[4]])
        own = [dict(b, src="eToro") for b in bars]
        for b in own:
            b.pop("suspect", None)
        mark_suspects(own, "eToro")
        self.assertFalse(any(b.get("suspect") for b in own),
                         "a real flash move on the series' own feed is "
                         "never marked")


# ═══ F6a. Today's forming daily candle, from the same feed ════════════

class TheDailyFormingCandleTests(_Logged):

    def setUp(self):
        super().setUp()
        self.inst = _inst("AAPL", "stock", "Apple")
        today = timezone.now().replace(hour=0, minute=0, second=0,
                                       microsecond=0)
        self.today = today
        for k in (3, 2, 1):
            _bar(self.inst, "1d", today - timedelta(days=k), 250, 253, 249,
                 252, "yfinance")

    def _hours(self, source, n=3):
        start = self.today + timedelta(minutes=30)
        now = timezone.now()
        made = 0
        for k in range(24):
            t = start + timedelta(hours=k)
            if t > now - timedelta(minutes=1) or made >= n:
                break
            _bar(self.inst, "1h", t, 255 + made, 258 + made, 254 + made,
                 256 + made, source, vol=10)
            made += 1
        return made

    def test_it_is_built_from_yahoos_own_hourly_bars(self):
        made = self._hours("yfinance_public")
        if not made:
            self.skipTest("the UTC day is under an hour old")
        with _route("paper"):
            body = self.chart("AAPL", "1d")
        last = body["bars"][-1]
        self.assertEqual(last["time"], self.today.strftime("%Y-%m-%d"))
        self.assertTrue(last.get("forming"))
        self.assertEqual(last["open"], 255.0)
        self.assertEqual(last["close"], 256.0 + made - 1)
        self.assertEqual(last["high"], 258.0 + made - 1)
        self.assertEqual(last["low"], 254.0)
        self.assertTrue(any("forming" in n for n in body["source"]["notes"]))
        self.assertFalse(any(b.get("forming") for b in body["bars"][:-1]))

    def test_never_from_another_feeds_bars(self):
        made = self._hours("etoro")
        if not made:
            self.skipTest("the UTC day is under an hour old")
        with _route("paper"):
            body = self.chart("AAPL", "1d")
        self.assertFalse(any(b.get("forming") for b in body["bars"]))
        self.assertEqual(body["bars"][-1]["close"], 252.0)

    def test_not_when_the_newest_daily_bar_is_already_today(self):
        made = self._hours("yfinance_public")
        _bar(self.inst, "1d", self.today + timedelta(hours=4), 255, 260, 254,
             259, "yfinance")
        with _route("paper"):
            body = self.chart("AAPL", "1d")
        self.assertFalse(any(b.get("forming") for b in body["bars"]))
        self.assertEqual(body["bars"][-1]["close"], 259.0)
        self.assertTrue(made >= 0)


# ═══ F6b / F9. The daily writers ══════════════════════════════════════

class TheCryptoCloseIsClosedTests(TestCase):

    def setUp(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=("platform_master", "scraper_eod")).update(is_enabled=True)

    def test_todays_forming_kline_is_not_written(self):
        """At 00:10 UTC the last of the five klines is today's, ten minutes
        old: written, it stood as today's daily bar for a day."""
        from market_data.models import PriceData
        from market_data.tasks import fetch_eod_crypto
        inst = _inst("BTCUSD", "crypto", "Bitcoin")
        day_ms = 86_400_000
        today_ms = int(_time.time() * 1000) // day_ms * day_ms
        rows = [[today_ms - k * day_ms, "100", "110", "90", "105", "5",
                 today_ms - k * day_ms + day_ms - 1] for k in (2, 1, 0)]
        feed = mock.MagicMock()
        feed.klines.return_value = rows
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            fetch_eod_crypto.run()
        stamps = sorted(int(t.timestamp() * 1000) for t in
                        PriceData.objects.filter(instrument=inst,
                                                 timeframe="1d")
                        .values_list("timestamp", flat=True))
        self.assertEqual(stamps, [today_ms - 2 * day_ms, today_ms - day_ms])


class TheEodRewritesItsLastTwoDaysTests(TestCase):

    def _history(self, closes, lows=None):
        out = []
        base = datetime(2026, 10, 26, 4, tzinfo=dt_tz.utc)
        for i, c in enumerate(closes):
            low = (lows or {}).get(i, c - 1)
            out.append({"timestamp": base + timedelta(days=i),
                        "open": Decimal(str(c)), "high": Decimal(str(c + 2)),
                        "low": Decimal(str(low)), "close": Decimal(str(c)),
                        "volume": 10})
        return out

    def test_a_snapshot_is_completed_and_older_days_are_left_alone(self):
        from market_data.adapters import yfinance_adapter as ya
        from market_data.models import PriceData
        inst = _inst("AAPL", "stock", "Apple")
        with mock.patch.object(ya, "fetch_history",
                               return_value=self._history([100, 101, 102])):
            ya.save_history_to_db("AAPL", period="5d")
        # The next night Yahoo's figures for every day differ: the last two
        # are rewritten, the first is history and stays.
        with mock.patch.object(ya, "fetch_history",
                               return_value=self._history([200, 201, 202])):
            ya.save_history_to_db("AAPL", period="5d")
        closes = list(PriceData.objects.filter(instrument=inst,
                                               timeframe="1d")
                      .order_by("timestamp").values_list("close", flat=True))
        self.assertEqual([float(c) for c in closes], [100.0, 201.0, 202.0])

    def test_a_bar_that_cannot_have_traded_is_refused(self):
        from market_data.adapters import yfinance_adapter as ya
        from market_data.models import PriceData
        inst = _inst("AAPL", "stock", "Apple")
        with mock.patch.object(ya, "fetch_history",
                               return_value=self._history([100, 101, 102],
                                                          lows={1: 0})):
            ya.save_history_to_db("AAPL", period="5d")
        lows = list(PriceData.objects.filter(instrument=inst,
                                             timeframe="1d")
                    .values_list("low", flat=True))
        self.assertEqual(len(lows), 2)
        self.assertNotIn(Decimal("0"), lows)


# ═══ F5a. The writer refuses a bar that cannot have traded ════════════

class TheWriterRefusesImpossibleBarsTests(TestCase):

    def setUp(self):
        cache.clear()
        self.inst = _inst("EURUSD", "forex", "Euro")

    def test_upsert_refuses_them(self):
        from market_data.bot_bars import _upsert_rows
        from market_data.models import PriceData
        rows = [
            [1700000000000, "1.1", "1.2", "1.0", "1.15", "1"],      # fine
            [1700003600000, "100", "99", "0", "100.5", "1"],        # proof
            [1700007200000, "nan", "1.2", "1.0", "1.15", "1"],      # NaN
            [1700010800000, None, "1.2", "1.0", "1.15", "1"],       # missing
            [1700014400000, "1.1", "1.2", "1.12", "1.15", "1"],     # low>open
        ]
        written, skipped = _upsert_rows(self.inst, "1h", rows, "etoro")
        self.assertEqual((written, skipped), (1, 4))
        self.assertEqual(PriceData.objects.filter(instrument=self.inst)
                         .count(), 1)

    def test_etoro_maps_a_missing_field_to_none_not_zero(self):
        from tests.test_etoro_client import SEARCH_AAPL, _client
        candles = {"candles": [{"instrumentId": 1001, "candles": [
            {"instrumentID": 1001, "fromDate": "2026-09-29T08:00:00Z",
             "high": 2, "low": 0.5, "close": 1.5, "volume": 3}]}],
            "interval": "FourHours"}
        t, _ = _client([SEARCH_AAPL, ("GET", "/history/candles", 200,
                                      candles)])
        rows = t.klines("AAPL", interval="4h", limit=2)
        self.assertIsNone(rows[0][1])
        self.assertEqual(rows[0][2:5], ["2", "0.5", "1.5"])

    def test_an_answer_of_nothing_but_impossible_bars_is_not_now(self):
        """The skeptic's correction: a venue whose every bar the writer
        refuses was muted for six hours, and the bots read the stand-in
        (for gold the future) all that time. It is a 429's "not now": the
        public feed fills this pass, and the venue is asked next pass."""
        from bot_program.models import AssetBotConfig
        from market_data import bot_bars
        from market_data.models import PriceData

        user = User.objects.create_user("mute2_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="M", mode="live",
            symbols=["EURUSD"], capital=Decimal("150"), enabled=True)
        step = 14_400_000
        start = (int(_time.time() * 1000) // step) * step - 3 * step
        bad = [[start + i * step, "1.1", "1.0", "0", "1.105", "0"]
               for i in range(3)]
        good = [[start + i * step, "1.10", "1.11", "1.09", "1.105", "0"]
                for i in range(3)]

        venue = mock.MagicMock(name="venue")
        venue._sv_public_feed = False
        venue.klines.return_value = bad

        class YFinanceFeed:
            _sv_public_feed = True

            def klines(self, *a, **k):
                return list(good)

        with mock.patch("market_data.bot_bars._client_for",
                        return_value=venue), \
                mock.patch("market_data.bot_bars._public_market_data_client",
                           return_value=YFinanceFeed()):
            out = bot_bars.refresh_bars_for_config(cfg, intervals=("4h",),
                                                   limit=3)
        self.assertEqual(out["fallback"], 1)
        self.assertEqual(set(PriceData.objects.filter(instrument=self.inst)
                             .values_list("source", flat=True)),
                         {"yfinance_public"})
        self.assertFalse(bot_bars._venue_is_mute(
            bot_bars._source_tag(venue), "EURUSD", "4h"))


# ═══ M1. The watchlist pass never writes over the venue's bars ════════

class TheWatchlistKeepsTheVenuesBarsTests(TestCase):

    def test_a_starred_symbol_eToro_wrote_keeps_eToros_window(self):
        from market_data import bot_bars
        from market_data.models import PriceData
        cache.clear()
        inst = _inst("XAUUSD", "commodity", "Gold Spot")
        inst.is_watchlist = True
        inst.save()
        end = _grid_now()
        for k in (3, 2, 1):
            _bar(inst, "4h", end - STEP4 * k, 4000, 4002, 3998, 4001,
                 "etoro")
        rows = [[int((end - STEP4 * k).timestamp() * 1000), "4036", "4038",
                 "4034", "4037", "1"] for k in (3, 2, 1, 0)]

        class YFinanceFeed:
            _sv_public_feed = True

            def klines(self, *a, **k):
                return list(rows)

        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=YFinanceFeed()), \
                mock.patch("brain.synthesizer._held_symbols",
                           return_value=[]), \
                mock.patch.object(bot_bars, "_pace"):
            bot_bars.refresh_watchlist_bars(intervals=("4h",), limit=4)
        got = dict(PriceData.objects.filter(instrument=inst, timeframe="4h")
                   .values_list("timestamp", "source"))
        self.assertEqual(sorted(got.values()),
                         ["etoro", "etoro", "etoro", "yfinance_public"])
        self.assertEqual(got[end], "yfinance_public",
                         "the feed still fills after the venue's newest bar")


# ═══ F4 / M3. The quote row: whose sides, whose change ════════════════

class TheQuoteRowTellsWhoseItIsTests(_Logged):

    def setUp(self):
        super().setUp()
        self.inst = _inst("EURUSD", "forex", "Euro")

    def test_a_write_without_sides_clears_the_other_feeds_sides(self):
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        write_quote("EURUSD", last=Decimal("1.08000"), source="oanda_stream",
                    bid=Decimal("1.07995"), ask=Decimal("1.08005"))
        LiveQuote.objects.filter(instrument=self.inst).update(
            updated_at=timezone.now() - timedelta(hours=3))
        self.assertTrue(write_quote("EURUSD", last=Decimal("1.09500"),
                                    source="yfinance"))
        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(row.last, Decimal("1.09500"))
        self.assertIsNone(row.bid)
        self.assertIsNone(row.ask)

    def test_the_change_says_which_feed_measured_it(self):
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        write_quote("EURUSD", last=Decimal("1.0800"), source="yfinance",
                    change_pct=Decimal("0.42"))
        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(row.change_source, "yfinance")
        write_quote("EURUSD", last=Decimal("1.0850"), source="oanda_stream",
                    bid=Decimal("1.0849"), ask=Decimal("1.0851"))
        row.refresh_from_db()
        # The day column is still the poller's (test_feed_change_truth),
        # and the row now says so.
        self.assertEqual(Decimal(str(row.change_pct)), Decimal("0.42"))
        self.assertEqual(row.change_source, "yfinance")
        with _route("paper"):
            d = self.client.get("/api/instrument-preview/EURUSD/").json()
        self.assertIs(d["change_same_feed"], False)
        self.assertEqual(d["source"], "oanda_stream")
        self.assertEqual(d["sides_source"], "oanda_stream")
        self.assertIn("OANDA", d["sides_words"])

    def test_the_same_feeds_change_is_its_own(self):
        from market_data.quotes import write_quote
        write_quote("EURUSD", last=Decimal("1.0800"), source="yfinance",
                    change_pct=Decimal("0.42"))
        with _route("paper"):
            d = self.client.get("/api/instrument-preview/EURUSD/").json()
        self.assertIs(d["change_same_feed"], True)
        self.assertIsNone(d["sides_source"])


# ═══ F3a. The hero says whose price it is ═════════════════════════════

class TheHeroSaysWhosePriceTests(_Logged):

    def setUp(self):
        super().setUp()
        from market_data.models import LiveQuote
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")
        LiveQuote.objects.create(instrument=self.inst,
                                 last=Decimal("4036.40"), source="yfinance")
        LiveQuote.objects.filter(instrument=self.inst).update(
            updated_at=timezone.now() - timedelta(seconds=130))

    def _preview(self, route="etoro"):
        boom = AssertionError("an eToro request was built for the hero")
        with _route(route), \
                mock.patch("bot_program.engine.broker_router."
                           "client_for_symbol", side_effect=boom), \
                mock.patch("bot_program.engine.etoro_client.EtoroTrader."
                           "__init__", side_effect=boom):
            resp = self.client.get("/api/instrument-preview/XAUUSD/")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_the_quote_names_its_feed_its_age_and_its_stand_in(self):
        d = self._preview(route="paper")
        self.assertEqual(d["source"], "yfinance")
        self.assertEqual(d["stand_in"], "future")
        self.assertIn("Yahoo GC=F", d["source_words"])
        self.assertIn("future", d["source_words"])
        self.assertGreaterEqual(d["quote_age_seconds"], 120)
        self.assertIsNone(d["venue"], "not routed to a venue: no venue price")
        self.assertEqual(d["decimals"], 2)

    def test_the_venues_last_candle_rides_beside_it(self):
        end = _grid_now(H)
        _bar(self.inst, "1h", end - timedelta(hours=1), 4005, 4012, 4001,
             4010, "etoro")
        _bar(self.inst, "4h", _grid_now() - timedelta(hours=8), 3990, 4000,
             3980, 3995, "etoro")
        d = self._preview()
        v = d["venue"]
        self.assertEqual(v["price"], 4010.0)
        self.assertEqual(v["label"], "eToro")
        self.assertEqual(v["price_text"], "4010.00")
        self.assertIsNotNone(v["age_s"])
        self.assertAlmostEqual(d["gap_pct"], (4036.40 / 4010 - 1) * 100,
                               places=4)

    def test_a_real_rows_newer_venue_mark_wins(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        _bar(self.inst, "1h", _grid_now(H) - timedelta(hours=3), 4005, 4012,
             4001, 4010, "etoro")
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="G", mode="live",
            symbols=[], capital=Decimal("100"), enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, symbol="XAUUSD", side="BUY", qty=Decimal("0.01"),
            entry_price=Decimal("4000"), status="OPEN", paper=False,
            asset_class="commodity",
            metadata={"broker": "etoro", "venue_mark": {
                "price": 4012.5, "source": "etoro", "via": "tick",
                "at": (timezone.now() - timedelta(seconds=40)).isoformat()}})
        d = self._preview()
        self.assertEqual(d["venue"]["price"], 4012.5)
        self.assertLess(d["venue"]["age_s"], 120)

    def test_the_page_paints_it_at_first_load(self):
        _bar(self.inst, "1h", _grid_now(H) - timedelta(hours=1), 4005, 4012,
             4001, 4010, "etoro")
        with _route("etoro"):
            body = self.client.get("/instruments/XAUUSD/").content.decode()
        hero = body.split('class="dtl-price"', 1)[1].split("dtl-mkt", 1)[0]
        self.assertIn('data-decimals="2"', _open_tag(body, "dtl-price"))
        self.assertIn('data-hero="src"', hero)
        self.assertIn("Yahoo GC=F", hero)
        self.assertIn('data-hero="venue"', hero)
        self.assertIn("4010.00", hero)


# ═══ F7. The hero repaints at the instrument's own precision ══════════

class TheHeroKeepsItsPrecisionTests(_Logged):

    def setUp(self):
        super().setUp()
        from market_data.models import LiveQuote
        inst = _inst("EURUSD", "forex", "Euro")
        LiveQuote.objects.create(instrument=inst, last=Decimal("1.08345"),
                                 bid=Decimal("1.08340"),
                                 ask=Decimal("1.08350"), source="oanda_stream",
                                 change_pct=Decimal("0.10"))

    def test_the_hero_carries_the_pages_decimal_count(self):
        body = self.client.get("/instruments/EURUSD/").content.decode()
        self.assertIn('data-decimals="5"', _open_tag(body, "dtl-price"))
        self.assertIn('class="dtl-last"', body)
        self.assertIn("1.08345", body)

    def test_the_painter_never_rounds_to_four(self):
        js = _src("static/js/sv-instrument-live.js")
        self.assertNotIn("price.toFixed(4)", js)
        self.assertIn("decimalsFor(", js)

    def test_the_latest_quote_card_is_repainted(self):
        body = self.client.get("/instruments/EURUSD/").content.decode()
        card = body.split("Latest Quote", 1)[1][:3000]
        for hook in ("last", "change", "sides", "source", "updated"):
            self.assertIn(f'data-lq="{hook}"', card, hook)
        js = _src("static/js/sv-instrument-live.js")
        self.assertIn("[data-lq=", js)


# ═══ M4. Venue position lines over public-feed candles ════════════════

class ThePositionLinesSayWhosePricesTests(_Logged):

    def test_the_legend_says_the_lines_are_etoro_prices(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        inst = _inst("XAUUSD", "commodity", "Gold Spot")
        base = _grid_now(H)
        for k in range(3):
            _bar(inst, "1h", base - timedelta(hours=k), 4030, 4034, 4028,
                 4032, "yfinance_public")
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="G", mode="live",
            symbols=[], capital=Decimal("100"), enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, symbol="XAUUSD", side="BUY", qty=Decimal("0.01"),
            entry_price=Decimal("4000"), stop_loss=Decimal("3980"),
            status="OPEN", paper=False, asset_class="commodity",
            metadata={"broker": "etoro"})
        with _route("etoro"):
            body = self.chart("XAUUSD", "1h", overlays=True)
        words = body["source"]["positions"]
        self.assertIn("eToro", words)
        self.assertIn("Yahoo GC=F", words)

    def test_no_words_when_the_lines_and_the_candles_share_a_feed(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        inst = _inst("XAUUSD", "commodity", "Gold Spot")
        base = _grid_now(H)
        for k in range(3):
            _bar(inst, "1h", base - timedelta(hours=k), 4000, 4004, 3998,
                 4002, "etoro")
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="G", mode="live",
            symbols=[], capital=Decimal("100"), enabled=True)
        AssetBotTrade.objects.create(
            config=cfg, symbol="XAUUSD", side="BUY", qty=Decimal("0.01"),
            entry_price=Decimal("4000"), status="OPEN", paper=False,
            asset_class="commodity", metadata={"broker": "etoro"})
        with _route("etoro"):
            body = self.chart("XAUUSD", "1h", overlays=True)
        self.assertEqual(body["source"]["positions"], "")


# ═══ F8. Yahoo's 4h on one fixed UTC grid ═════════════════════════════

class TheFourHourGridIsFixedTests(SimpleTestCase):

    def _session_frame(self, start):
        import pandas as pd
        idx = pd.date_range(start, "2026-10-30 16:00", freq="1h",
                            tz="America/New_York")
        idx = idx[(idx.hour >= 9) & (idx.hour < 16) & (idx.weekday < 5)]
        n = len(idx)
        return pd.DataFrame({"Open": [100.0] * n, "High": [101.0] * n,
                             "Low": [99.0] * n, "Close": [100.5] * n,
                             "Volume": [10] * n}, index=idx)

    def _hours(self, start):
        from market_data.public_feed import YFinanceFeed, clear_frame_memo
        clear_frame_memo()
        fake = mock.MagicMock()
        fake.Ticker.return_value.history.return_value = \
            self._session_frame(start)
        with mock.patch.dict("sys.modules", {"yfinance": fake}):
            rows = YFinanceFeed("stock").klines("AAPL", interval="4h",
                                                limit=12)
        return {r[0] // 1000 % 86400 // 3600 for r in rows}, rows

    def test_a_window_starting_in_winter_or_summer_lands_on_one_grid(self):
        winter, rows = self._hours("2026-03-01 09:30")
        summer, _ = self._hours("2026-04-15 09:30")
        self.assertEqual(winter, summer)
        for r in rows:
            self.assertEqual(r[0] // 1000 % FOUR_H, 0,
                             "a 4h bar off the UTC 4h grid")


class TheOffGridCommandTests(TestCase):

    def setUp(self):
        self.inst = _inst("AAPL", "stock", "Apple")
        base = datetime(2026, 10, 20, tzinfo=dt_tz.utc)
        # on the UTC grid
        for h in (12, 16):
            _bar(self.inst, "4h", base + timedelta(hours=h), 1, 2, 0.5, 1.5,
                 "yfinance_public")
        # the old grid one hour later, beside them
        for h in (13, 17):
            _bar(self.inst, "4h", base + timedelta(hours=h), 1, 2, 0.5, 1.5,
                 "yfinance_public")
        # off-grid history nothing on-grid stands beside: kept
        _bar(self.inst, "4h", base - timedelta(days=30, hours=-13), 1, 2, 0.5,
             1.5, "yfinance_public")
        # a venue's bar off the UTC grid is the venue's: never touched
        _bar(self.inst, "4h", base + timedelta(hours=21), 1, 2, 0.5, 1.5,
             "etoro")

    def _count(self):
        from market_data.models import PriceData
        return PriceData.objects.filter(instrument=self.inst).count()

    def test_it_lists_and_deletes_nothing_by_default(self):
        out = StringIO()
        call_command("prune_offgrid_4h", stdout=out)
        self.assertEqual(self._count(), 6)
        text = out.getvalue()
        self.assertIn("AAPL", text)
        self.assertIn("2", text)
        self.assertIn("--yes", text)

    def test_yes_deletes_only_the_duplicates(self):
        from market_data.models import PriceData
        call_command("prune_offgrid_4h", "--yes", stdout=StringIO())
        left = sorted(t.hour for t in PriceData.objects.filter(
            instrument=self.inst, timestamp__gte=datetime(
                2026, 10, 20, tzinfo=dt_tz.utc))
            .values_list("timestamp", flat=True))
        self.assertEqual(left, [12, 16, 21])
        self.assertEqual(self._count(), 4)


# ═══ M2. Only an accepted tick reaches the browser ════════════════════

class OnlyAcceptedTicksAreBroadcastTests(SimpleTestCase):
    """A tick write_quote refused (a lower-priority feed while a better one
    holds the row) still went to every browser, so the rail, the headband
    and the hero showed three prices for one symbol.

    And the read loop never waits on a write (2026-10-31, review of the
    first cut): `if await _fire(update_live_quote(...))` paused the socket
    read on every database write, one at a time on the single executor
    thread; under a Finnhub open the websocket's queue filled, reading
    paused, the pong went unread and the keepalive closed the stream.
    The loop hands each tick to market_data.stream_writes.LatestPerSymbol
    (one write in flight per symbol, the newest tick behind it) and reads
    on."""

    def _loop(self, name, start):
        src = _src(f"market_data/management/commands/{name}.py")
        seg = src[src.index(start):]
        return seg[:seg.index("except Exception as e:")]

    @staticmethod
    def _indent(text, at):
        return at - text.rfind("\n", 0, at) - 1

    def _gated(self, loop, write, say):
        """The broadcast is the body of `if await <the write>:` and nothing
        else stands between them at the `if`'s own level; and both sit in
        a coroutine the loop defines and hands to LATEST.submit, so the
        read loop itself awaits neither the write nor the broadcast."""
        i = loop.index(f"if await _fire({write}")
        j = loop.index(f"await broadcast({say}")
        self.assertLess(i, j)
        if_indent = self._indent(loop, i)
        say_start = loop.rfind("\n", 0, j) + 1
        self.assertGreater(j - say_start, if_indent,
                           "the broadcast is not the accepted write's body")
        for line in loop[i:say_start].split("\n")[1:]:
            if line.strip():
                self.assertGreater(len(line) - len(line.lstrip()), if_indent,
                                   line)
        self.assertEqual(loop.count("await broadcast("), 1)
        # The write runs in a coroutine of its own, not in the read loop.
        d = loop.rfind("async def _tick(", 0, i)
        self.assertGreaterEqual(d, 0, "the write is not in its own coroutine")
        def_indent = self._indent(loop, d)
        self.assertLess(def_indent, if_indent)
        k = loop.index("LATEST.submit(sym, _tick)", j)
        self.assertEqual(self._indent(loop, k), def_indent)
        for line in loop[d:k].split("\n")[1:]:
            if line.strip():
                self.assertGreater(len(line) - len(line.lstrip()), def_indent,
                                   line)
        outside = loop[:d] + loop[k:]
        self.assertNotIn("update_live_quote(", outside,
                         "the read loop waits on the write")
        self.assertNotIn("broadcast(", outside)

    def test_binance(self):
        loop = self._loop("stream_binance", "async for raw in ws:")
        self._gated(loop, "update_live_quote(sym, last, change_pct",
                    "sym, last, change_pct")

    def test_finnhub(self):
        loop = self._loop("stream_finnhub", "async for raw in ws:")
        self._gated(loop, "update_live_quote(sym, last, vol)",
                    "sym, last, None, vol)")

    def test_oanda(self):
        loop = self._loop("stream_oanda", "async for line in r.content:")
        self._gated(loop, "update_live_quote(sym, bid, ask)",
                    "sym, mid, None, bid, ask)")


class OneWriteInFlightPerSymbolTests(SimpleTestCase):
    """market_data.stream_writes.LatestPerSymbol: the read loop hands a
    tick over and reads on. One write per symbol is in flight; a tick that
    arrives meanwhile waits, and a newer one replaces it, so a burst costs
    two writes, not one per print, and the backlog is at most one tick per
    symbol (the old background writes queued without bound)."""

    def test_accepted_ticks_alone_are_said_and_the_newest_waits(self):
        import asyncio

        from market_data.stream_writes import LatestPerSymbol

        async def scenario():
            tasks = set()

            def fire(coro):
                t = asyncio.ensure_future(coro)
                tasks.add(t)
                return t

            gate = asyncio.Event()
            written, said = [], []

            def job(price, accepted):
                async def run():
                    written.append(price)
                    await gate.wait()
                    if accepted:
                        said.append(price)
                return run

            w = LatestPerSymbol(fire)
            w.submit("X", job(1, True))
            w.submit("X", job(2, True))
            w.submit("X", job(3, False))       # replaces the waiting 2
            w.submit("Y", job(10, True))
            await asyncio.sleep(0)
            in_flight = sorted(written)
            gate.set()
            while tasks:
                done = list(tasks)
                tasks.clear()
                await asyncio.gather(*done)
            w.submit("X", job(4, True))        # idle again: runs at once
            while tasks:
                done = list(tasks)
                tasks.clear()
                await asyncio.gather(*done)
            return in_flight, written, said, len(w._busy)

        in_flight, written, said, busy = asyncio.run(scenario())
        self.assertEqual(in_flight, [1, 10], "one write per symbol at once")
        self.assertNotIn(2, written, "a newer tick replaces a waiting one")
        self.assertEqual(sorted(written), [1, 3, 4, 10])
        self.assertEqual(sorted(said), [1, 4, 10],
                         "only an accepted write is broadcast")
        self.assertEqual(busy, 0)

    def test_a_failing_job_never_wedges_its_symbol(self):
        import asyncio

        from market_data.stream_writes import LatestPerSymbol

        async def scenario():
            tasks = []

            def fire(coro):
                t = asyncio.ensure_future(coro)
                tasks.append(t)
                return t

            ran = []

            async def boom():
                raise RuntimeError("db gone")

            async def fine():
                ran.append(1)

            w = LatestPerSymbol(fire)
            w.submit("X", boom)
            await asyncio.gather(*tasks)
            w.submit("X", fine)
            await asyncio.gather(*tasks)
            return ran

        with self.assertLogs("market_data.stream_writes", "WARNING") as said:
            self.assertEqual(asyncio.run(scenario()), [1])
        self.assertIn("db gone", said.output[0])


# ═══ The review of the first cut (2026-10-31) ═════════════════════════
#
# What the first cut still drew wrong: a stale venue gave way to a public
# feed with nothing newer, and to old history joined to new rows with no
# seam; newer bars of another feed were dropped without a word; a daily
# view built from intraday rows never said today's candle was forming;
# routed crypto lost today's daily candle in silence; the router's default
# broker was named for a user with no such account; eToro's forming candle
# read as just read; a refused newest bar cost its slot.

class AStaleVenueGivesWayOnlyToNewerBarsTests(_Logged):

    def test_the_public_feed_draws_only_after_the_venues_last_bar(self):
        """eToro's crypto 1h stopped four hours ago (past the three-bar
        bound), Binance's history sits behind eToro's window and four
        Binance stand-ins after it: the bars between were evicted, so the
        history and the stand-ins were drawn as adjacent candles, one
        price step that never traded."""
        inst = _inst("BTCUSD", "crypto", "Bitcoin")
        now = _grid_now(H)
        venue_end = now - timedelta(hours=4)
        for k in range(30):
            _bar(inst, "1h", venue_end - timedelta(hours=k), 70000, 70010,
                 69990, 70000, "etoro")
        first = venue_end - timedelta(hours=29)
        for k in range(1, 21):
            _bar(inst, "1h", first - timedelta(hours=k), 60000, 60010,
                 59990, 60000, "binance_public")
        for k in range(4):
            _bar(inst, "1h", now - timedelta(hours=k), 70050, 70060, 70040,
                 70050, "binance_public")
        with _route("etoro"):
            body = self.chart("BTCUSD", "1h")
        src = body["source"]
        self.assertEqual(src["family"], "binance")
        times = [b["time"] for b in body["bars"]]
        self.assertEqual(len(times), 4, "no history joined across the hole")
        self.assertGreater(min(times), int(venue_end.timestamp()))
        self.assertTrue(any("older bars from Binance BTCUSDT" in n
                            and "not drawn" in n for n in src["notes"]),
                        src["notes"])

    def test_a_public_feed_with_nothing_newer_never_replaces_the_venue(self):
        """eToro's gold 4h stopped four days ago (past the 72 h bound: a
        long weekend is enough) and Yahoo holds only history from before
        eToro's window: the chart drew Yahoo's bars weeks older and
        dropped eToro's."""
        inst = _inst("XAUUSD", "commodity", "Gold Spot")
        end = _grid_now() - timedelta(days=4)
        for k in range(10):
            _bar(inst, "4h", end - STEP4 * k, 4000, 4002, 3998, 4001, "etoro")
        for k in range(5):
            _bar(inst, "4h", end - timedelta(days=60) - STEP4 * k, 3000, 3002,
                 2998, 3001, "yfinance_public")
        with _route("etoro"):
            body = self.chart("XAUUSD", "4h")
        self.assertEqual(body["source"]["family"], "etoro")
        self.assertEqual(body["bars"][-1]["time"], int(end.timestamp()))
        self.assertEqual(len(body["bars"]), 10)


class TheDailyFromIntradayRowsFormsTodayTests(_Logged):

    def test_todays_folded_day_is_marked_forming(self):
        """USDCNH has no Yahoo daily bar (YF_NO_DAILY), and a fresh
        deployment has none for anything: the day is folded from 1h rows,
        and today's was served as a closed candle, so the caption said
        'the last candle has closed' while it traded."""
        inst = _inst("USDCNH", "forex", "Dollar Yuan")
        base = _grid_now(H)
        today = base.replace(hour=0)
        for k in range(30):
            _bar(inst, "1h", base - timedelta(hours=k), 7.10, 7.12, 7.09,
                 7.11, "yfinance_public")
        with _route("paper"):
            body = self.chart("USDCNH", "1d")
        last = body["bars"][-1]
        self.assertEqual(last["time"], today.strftime("%Y-%m-%d"))
        self.assertTrue(last.get("forming"))
        self.assertFalse(any(b.get("forming") for b in body["bars"][:-1]))
        self.assertTrue(any("forming" in n for n in body["source"]["notes"]),
                        body["source"]["notes"])


class RoutedCryptoSaysWhyTodayIsNotDrawnTests(_Logged):

    def test_the_daily_view_says_todays_bars_are_the_venues(self):
        """BTCUSD routed to eToro: the daily series is Binance's, today's
        1h rows are eToro's (Binance's gave way to them), and the EOD now
        writes only closed klines, so the daily view ended on yesterday
        all day with nothing said."""
        inst = _inst("BTCUSD", "crypto", "Bitcoin")
        today = timezone.now().replace(hour=0, minute=0, second=0,
                                       microsecond=0)
        for k in (3, 2, 1):
            _bar(inst, "1d", today - timedelta(days=k), 67000, 67500, 66500,
                 67200, "binance_public")
        base = _grid_now(H)
        for k in range(int((base - today).total_seconds() // H) + 1):
            _bar(inst, "1h", today + timedelta(hours=k), 67200, 67300, 67100,
                 67250, "etoro")
        with _route("etoro"):
            body = self.chart("BTCUSD", "1d")
        self.assertFalse(any(b.get("forming") for b in body["bars"]),
                         "one feed per series: no eToro candle on Binance's")
        notes = body["source"]["notes"]
        self.assertTrue(any("today's candle is not drawn" in n and "eToro" in n
                            for n in notes), notes)


class TheRouteIsAVenueTheOperatorHoldsTests(_Logged):
    """broker_name_for_symbol falls through to the class's default broker
    (OANDA, Alpaca, Binance) whatever the credentials: the chart named a
    venue the operator has no account at, and the hero printed the
    public feed's Binance candle as 'the venue's last known price'."""

    def test_no_account_no_venue(self):
        from dashboard.chart_source import route_of
        for sym, cls in (("EURUSD", "forex"), ("BTCUSD", "crypto"),
                         ("AAPL", "stock")):
            self.assertEqual(route_of(self.user, _inst(sym, cls)), "", sym)

    def test_stored_credentials_are_a_venue(self):
        from bot_program.models import OANDAAccount
        from dashboard.chart_source import route_of
        acct = OANDAAccount(user=self.user)
        acct.set_credentials("key", "acct")
        acct.save()
        self.assertEqual(route_of(self.user, _inst("EURUSD", "forex")),
                         "oanda")

    def test_the_public_feed_is_never_called_the_venues_price(self):
        from market_data.models import LiveQuote
        inst = _inst("BTCUSD", "crypto", "Bitcoin")
        base = _grid_now(H)
        for k in range(3):
            _bar(inst, "1h", base - timedelta(hours=k), 67000, 67100, 66900,
                 67050, "binance_public")
        LiveQuote.objects.create(instrument=inst, last=Decimal("67400"),
                                 source="binance_ws")
        d = self.client.get("/api/instrument-preview/BTCUSD/").json()
        self.assertIsNone(d["venue"])
        self.assertEqual(d["gap_words"], "")
        body = self.chart("BTCUSD", "1h")
        self.assertNotIn("the venue's own candles", body["source"]["words"])
        self.assertEqual(body["source"]["route"], "")


class CryptoCandlesWeldOnlyTheirOwnFeedTests(_Logged):

    def test_the_source_says_so(self):
        """Binance's BTCUSDT (another exchange, quoted in USDT) is not the
        instrument of eToro's BTC candles: the widget welds only the same
        feed's quote on crypto candles."""
        btc = _inst("BTCUSD", "crypto", "Bitcoin")
        gold = _inst("XAUUSD", "commodity", "Gold Spot")
        base = _grid_now(H)
        for inst in (btc, gold):
            for k in range(3):
                _bar(inst, "1h", base - timedelta(hours=k), 100, 101, 99,
                     100, "etoro")
        with _route("etoro"):
            self.assertIs(self.chart("BTCUSD", "1h")["source"]
                          ["same_feed_only"], True)
            self.assertIs(self.chart("XAUUSD", "1h")["source"]
                          ["same_feed_only"], False)


class TheVenuesLastPriceIsDatedHonestlyTests(TestCase):
    """eToro's 4h and 1h candles opened at 16:00, nothing newer, and it is
    19:39: the hero said the 4h close was '0 s old' (the forming candle's
    close dated at now), and a public-feed answer for the same slot kept
    it so."""

    def setUp(self):
        cache.clear()
        self.inst = _inst("XAUUSD", "commodity", "Gold Spot")
        self.open = datetime(2026, 10, 31, 16, 0, tzinfo=dt_tz.utc)
        self.now = self.open + timedelta(hours=3, minutes=39)
        _bar(self.inst, "4h", self.open, 4000, 4012, 3995, 4010, "etoro")
        _bar(self.inst, "1h", self.open, 4000, 4010, 3995, 4008, "etoro")
        self.open_ms = int(self.open.timestamp() * 1000)

    def _venue(self):
        from dashboard.chart_source import venue_last
        return venue_last(self.inst, "etoro", now=self.now)

    def test_a_forming_candle_with_no_venue_answer_is_not_fresh(self):
        v = self._venue()
        self.assertGreaterEqual(v["age_s"], 3 * H + 39 * 60)

    def test_a_public_feed_answer_never_freshens_it(self):
        from market_data import bot_bars
        cache.set(bot_bars._answer_key("XAUUSD", "4h"),
                  {"at": (self.now - timedelta(seconds=60)).timestamp(),
                   "newest_ms": self.open_ms}, 3600)
        self.assertGreaterEqual(self._venue()["age_s"], 3 * H + 39 * 60)

    def test_the_venues_own_answer_dates_it(self):
        from market_data import bot_bars
        bot_bars._note_venue_answer(
            "etoro", "XAUUSD", "4h",
            [[self.open_ms, "4000", "4012", "3995", "4010", "0"]],
            at=(self.open + timedelta(minutes=5)).timestamp())
        v = self._venue()
        self.assertEqual(v["via"], "4h candle")
        self.assertEqual(v["price"], 4010.0)
        self.assertEqual(v["age_s"], 3 * H + 34 * 60)


class ARefusedBarKeepsItsSlotTests(TestCase):

    def test_a_refused_newest_bar_leaves_the_stand_in_in_its_slot(self):
        """eToro answered 17:00, 18:00 and a 19:00 bar with no low: the
        writer refused the 19:00 bar, the eviction still ran to 20:00 and
        deleted the public stand-in at 19:00, and the window was judged
        fresh from the refused stamp, so nothing filled it."""
        from bot_program.models import AssetBotConfig
        from market_data import bot_bars
        from market_data.models import PriceData

        cache.clear()
        inst = _inst("EURUSD", "forex", "Euro")
        user = User.objects.create_user("refused_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="R", mode="live",
            symbols=["EURUSD"], capital=Decimal("150"), enabled=True)
        step = 3_600_000
        newest = (int(_time.time() * 1000) // step) * step
        newest_dt = datetime.fromtimestamp(newest / 1000, tz=dt_tz.utc)
        _bar(inst, "1h", newest_dt, 1.10, 1.11, 1.09, 1.105,
             "yfinance_public")
        rows = [[newest - 2 * step, "1.10", "1.11", "1.09", "1.105", "0"],
                [newest - step, "1.10", "1.11", "1.09", "1.105", "0"],
                [newest, "1.10", "1.11", None, "1.105", "0"]]
        venue = mock.MagicMock(name="venue")
        venue._sv_public_feed = False
        venue.klines.return_value = rows

        class YFinanceFeed:
            _sv_public_feed = True

            def klines(self, *a, **k):
                return []

        with mock.patch("market_data.bot_bars._client_for",
                        return_value=venue), \
                mock.patch("market_data.bot_bars._public_market_data_client",
                           return_value=YFinanceFeed()):
            bot_bars.refresh_bars_for_config(cfg, intervals=("1h",), limit=3)
        got = dict(PriceData.objects.filter(instrument=inst, timeframe="1h")
                   .values_list("timestamp", "source"))
        self.assertEqual(got.get(newest_dt), "yfinance_public",
                         "the forming slot still holds a bar")
        self.assertEqual(len(got), 3)
        # The venue's own answer note names its newest GOOD bar.
        tag = bot_bars._source_tag(venue)
        self.assertEqual(bot_bars.last_venue_answer(tag, "EURUSD", "1h")
                         ["newest_ms"], newest - step)

    def test_the_window_is_judged_by_the_bars_written(self):
        from market_data import bot_bars
        inst = _inst("EURUSD", "forex", "Euro")
        now = datetime(2026, 10, 31, 19, 30, tzinfo=dt_tz.utc)
        old = int((now - timedelta(days=5)).timestamp() * 1000)
        rows = [[old, "1.10", "1.11", "1.09", "1.105", "0"],
                [int(now.timestamp() * 1000) - 1_800_000, "1.10", "1.11",
                 None, "1.105", "0"]]
        good = bot_bars._possible_rows(rows)
        self.assertEqual(len(good), 1)
        self.assertIsNotNone(bot_bars._venue_window_is_stale(
            inst, "1h", good, now=now))
