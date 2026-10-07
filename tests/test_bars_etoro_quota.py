"""The bar refresh and eToro's candle quota (PR50, 2026-10-07).

On 2026-10-06 at 23:38:31-35 UTC the bar refresh asked eToro for 4h and 1h
candles of every enabled (config, symbol), paper configs included, back to
back, and kept asking after the first 429: at least seventeen refused
klines in four seconds, at least ten of them /candles 429s. The seven
/search 429s noted on the venue's health in those seconds were most likely
the pass's own cold ids, and they made eToro (live) sick and held real
entries until 23:48.

Now the pass asks each (source, symbol, interval) once, from eToro's own
newest stored bar, real rows no enabled live config covers first, then
live configs, paced per wire request, never after its first 429, while
eToro is sick or once the trading lane met a 429; its reads are background
reads (never noted, never pausing), and one pass runs at a time.

Run with:  python manage.py test tests.test_bars_etoro_quota
"""
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase

from bot_program.engine.etoro_client import EtoroTrader

H = 3_600_000
FOUR_H = 4 * H


def _grid(ms, step):
    return (ms // step) * step


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = ""
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error",
                                     response=self)


class _Wire:
    """/search answers an id per symbol; /history/candles answers the
    newest `n` bars of the URL ending at the current grid, or a status."""

    ENUM = {"FourHours": FOUR_H, "OneHour": H}

    def __init__(self, ids, refuse=(), search_refuse=(), headers=None,
                 now_ms=None):
        self.ids = dict(ids)
        self.sym_of = {v: k for k, v in self.ids.items()}
        self.refuse = set(refuse)              # (symbol, enum)
        self.search_refuse = set(search_refuse)
        self.headers = headers or {}
        self.now_ms = now_ms
        self.calls = []

    def candle_calls(self):
        return [u for u in self.calls if "/history/candles" in u]

    def get(self, url, **kw):
        params = kw.get("params") or {}
        self.calls.append(url + (f"?{params}" if params else ""))
        if "/market-data/search" in url:
            sym = params.get("internalSymbolFull")
            if sym in self.search_refuse:
                return _Resp(429, headers=self.headers)
            return _Resp(200, [{"instrumentId": self.ids[sym],
                                "internalSymbolFull": sym}])
        m = re.search(r"/instruments/(\d+)/history/candles/asc/(\w+)/(\d+)",
                      url)
        iid, enum, n = int(m.group(1)), m.group(2), int(m.group(3))
        if (self.sym_of[iid], enum) in self.refuse:
            return _Resp(429, headers=self.headers)
        step = self.ENUM[enum]
        now_ms = self.now_ms or int(datetime.now(dt_tz.utc).timestamp() * 1000)
        last = _grid(now_ms, step)
        bars = [{"fromDate": datetime.fromtimestamp(
                    (last - (n - 1 - i) * step) / 1000, tz=dt_tz.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
                 "volume": 5} for i in range(n)]
        return _Resp(200, {"candles": [{"instrumentId": iid,
                                        "candles": bars}]},
                     headers=self.headers)


class _Feed:
    """The keyless feed, named like the real one."""
    _sv_public_feed = True

    def __init__(self):
        self.calls = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval))
        return []


class _Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def mono(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class _Base(TestCase):
    SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")

    def setUp(self):
        from django.core.cache import cache

        from bot_program import venue_health
        from bot_program.engine import etoro_client as ec
        # venue_health's memory lives in the cache and outlives a test
        # (risk R-C7): every test starts and ends with none.
        cache.clear()
        venue_health.reset()
        self.addCleanup(venue_health.reset)
        self.addCleanup(cache.clear)
        for memo in (ec._SEARCH_IDS, ec._SEARCH_NO, ec._RATE_PAUSE):
            memo.clear()
            self.addCleanup(memo.clear)
        from instruments.models import Instrument
        for s in self.SYMBOLS:
            Instrument.objects.get_or_create(
                symbol=s, defaults={"name": s, "asset_class": "forex"})
        self.user = User.objects.create_user("quota_u", password="x")
        self.wire = _Wire({s: 1000 + i for i, s in enumerate(self.SYMBOLS)})
        self.feed = _Feed()
        self.clock = _Clock()
        self.wl = None

    def _cfg(self, symbols, mode="paper", name="Q", asset_class="forex",
             enabled=True):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=self.user, asset_class=asset_class, name=name, mode=mode,
            symbols=list(symbols), capital=Decimal("1000"), enabled=enabled)

    def _held(self, symbol="XAGUSD", *, enabled=False, paper=False,
              name="manual"):
        """A real (or paper) OPEN row on a config whose symbols do not
        name it: the manual lane's `symbols=[]`, or a braked config."""
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol,
                                     "asset_class": "commodity"})
        manual = self._cfg([], mode="live", name=name,
                           asset_class="commodity", enabled=enabled)
        return AssetBotTrade.objects.create(
            config=manual, asset_class="commodity", symbol=symbol,
            side="BUY", status="OPEN", qty=Decimal("1"),
            entry_price=Decimal("61"), stop_loss=Decimal("59"),
            take_profit=Decimal("65"), paper=paper)

    def _pin_silver(self):
        # XAGUSD is pinned to eToro's id 19 (VENUE_ID_PINS): no /search.
        self.wire.ids["XAGUSD"] = 19
        self.wire.sym_of[19] = "XAGUSD"

    def _client(self, *_a, **_k):
        t = EtoroTrader("k", "u", env="live")
        t._session = self.wire
        return t

    def _run(self, client_for=None, **kw):
        from market_data import bot_bars
        with patch.object(bot_bars, "_client_for",
                          side_effect=client_for or self._client), \
                patch.object(bot_bars, "_public_market_data_client",
                             return_value=self.feed), \
                patch.object(bot_bars, "_mono", self.clock.mono), \
                patch.object(bot_bars, "_candle_sleep", self.clock.sleep), \
                patch.object(bot_bars, "refresh_watchlist_bars",
                             return_value={}) as wl:
            out = bot_bars.refresh_bot_bars(**kw)
        self.wl = wl
        return out


class TheDedupTests(_Base):

    def test_a_symbol_on_two_configs_is_fetched_once_per_pass(self):
        self._cfg(["EURUSD"], name="A")
        self._cfg(["EURUSD"], name="B")
        out = self._run()
        self.assertEqual(len(self.wire.candle_calls()), 2)
        self.assertEqual(out["deduped"], 2)


class TheLiveFirstTests(_Base):

    def test_the_live_config_is_asked_first(self):
        # Meta orders configs by (asset_class, name): the paper one first.
        self._cfg(["EURUSD"], name="A paper")
        self._cfg(["USDJPY"], mode="live", name="Z live")
        self._run()
        self.assertIn("/instruments/1002/", self.wire.candle_calls()[0])


class TheHeldRowsTests(_Base):

    def test_a_real_row_no_enabled_config_covers_is_asked_of_its_venue_first(
            self):
        self._pin_silver()
        # The manual lane: an enabled live config with symbols=[].
        self._held(enabled=True)
        self._cfg(["EURUSD"], mode="live", name="A")
        out = self._run()
        calls = self.wire.candle_calls()
        self.assertIn("/instruments/19/", calls[0])
        self.assertIn("/instruments/19/", calls[1])
        self.assertEqual(len(calls), 4)
        self.assertEqual(out["symbols"], 2)
        self.assertIn("XAGUSD", self.wl.call_args.kwargs["covered"])

    def test_a_real_row_covered_only_by_a_paper_config_is_asked_first_and_once(
            self):
        self._pin_silver()
        self._held()
        self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["XAGUSD"], name="B paper", asset_class="commodity")
        out = self._run()
        calls = self.wire.candle_calls()
        self.assertIn("/instruments/19/", calls[0])
        self.assertEqual(sum("/instruments/19/" in u for u in calls), 2)
        self.assertEqual(len(calls), 4)
        self.assertEqual(out["deduped"], 2)

    def test_held_rows_survive_the_deadline(self):
        from market_data import bot_bars
        self._pin_silver()
        self._held()
        self._cfg(["EURUSD"], name="A")
        self._cfg(["GBPUSD"], name="B")
        clock = self.clock
        n = {"c": 0}

        def late(*a, **k):
            n["c"] += 1
            if n["c"] == 2:                 # after the held row
                clock.t += bot_bars.BARS_PASS_MAX_S
            return self._client()
        out = self._run(client_for=late)
        self.assertTrue(any("/instruments/19/" in u
                            for u in self.wire.candle_calls()))
        self.assertEqual(out["not_reached"], 1)
        self.assertFalse(self.wl.call_args.kwargs["starred"])
        self.assertIn("XAGUSD", self.wl.call_args.kwargs["covered"])

        # (b) The pass is already past its deadline when the held rows
        # are walked: the held symbol is still refreshed (from the public
        # feed: eToro stopped at CANDLE_PASS_MAX_S), every config symbol
        # is not reached.
        from django.core.cache import cache
        cache.clear()
        self.wire.calls.clear()
        self.feed.calls.clear()
        self.clock = clock = type(self.clock)()
        real = bot_bars._held_real_rows

        def listed(live_covered):
            rows = real(live_covered)
            clock.t += bot_bars.BARS_PASS_MAX_S
            return rows
        with patch.object(bot_bars, "_held_real_rows", side_effect=listed):
            out = self._run()
        self.assertGreaterEqual(out["symbols"], 1)
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(self.feed.calls, [("XAGUSD", "4h"),
                                           ("XAGUSD", "1h")])
        self.assertIn("420s", out["etoro_stopped"])
        self.assertEqual(out["not_reached"], 2)
        self.assertFalse(self.wl.call_args.kwargs["starred"])
        self.assertIn("XAGUSD", self.wl.call_args.kwargs["covered"])

    def test_a_paper_row_is_not_in_the_held_group(self):
        from market_data.bot_bars import _held_real_rows
        self._pin_silver()
        self._held(paper=True)
        self.assertEqual(_held_real_rows(set()), [])
        self._run()
        self.assertFalse(any("/instruments/19/" in u
                             for u in self.wire.candle_calls()))


class TheIncrementTests(_Base):

    def _seed(self, symbol, interval, ms, source="etoro"):
        from instruments.models import Instrument
        from market_data.models import PriceData
        PriceData.objects.create(
            instrument=Instrument.objects.get(symbol=symbol),
            timeframe=interval,
            timestamp=datetime.fromtimestamp(ms / 1000, tz=dt_tz.utc),
            open=1, high=1, low=1, close=1, volume=0, source=source)

    def test_no_etoro_bar_asks_the_full_window(self):
        self._cfg(["EURUSD"])
        self._run()
        self.assertTrue(self.wire.candle_calls()[0].endswith("/FourHours/200"))

    def test_a_stored_forming_bar_asks_from_it(self):
        now = int(datetime.now(dt_tz.utc).timestamp() * 1000)
        self._seed("EURUSD", "4h", _grid(now, FOUR_H))
        self._seed("EURUSD", "1h", _grid(now, H))
        self._cfg(["EURUSD"])
        self._run()
        calls = self.wire.candle_calls()
        self.assertTrue(calls[0].endswith("/FourHours/3"), calls)
        self.assertTrue(calls[1].endswith("/OneHour/3"), calls)

    def test_the_forming_bar_is_rewritten(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        now = int(datetime.now(dt_tz.utc).timestamp() * 1000)
        self._seed("EURUSD", "4h", _grid(now, FOUR_H))
        self._cfg(["EURUSD"])
        self._run(intervals=("4h",))
        row = PriceData.objects.get(
            instrument=Instrument.objects.get(symbol="EURUSD"), timeframe="4h",
            timestamp=datetime.fromtimestamp(_grid(now, FOUR_H) / 1000,
                                             tz=dt_tz.utc))
        self.assertEqual(row.close, Decimal("1.15"))

    def test_the_window_arithmetic(self):
        from instruments.models import Instrument
        from market_data.bot_bars import _etoro_window
        inst = Instrument.objects.get(symbol="GBPUSD")
        t0 = datetime(2026, 10, 6, 8, 0, tzinfo=dt_tz.utc)
        self.assertEqual(_etoro_window(inst, "4h", "etoro", 200, now=t0), 200)
        self._seed("GBPUSD", "4h", int(t0.timestamp() * 1000))
        # another source's newer bar does not move eToro's window
        self._seed("GBPUSD", "4h", int(t0.timestamp() * 1000) + 2 * FOUR_H,
                   source="yfinance_public")
        w = lambda **d: _etoro_window(inst, "4h", "etoro", 200,  # noqa: E731
                                      now=t0 + timedelta(**d))
        self.assertEqual(w(minutes=10), 3)
        self.assertEqual(w(hours=4, seconds=30), 4)
        self.assertEqual(w(hours=50), 15)
        self.assertEqual(w(days=40), 200)


class ThePacingTests(_Base):

    def test_candle_reads_are_spaced_by_the_gap(self):
        from market_data.bot_bars import CANDLE_GAP_S
        self._cfg(list(self.SYMBOLS))
        self._run()
        self.assertEqual(len(self.wire.candle_calls()), 6)
        # A cold 4h is /search + /candles (two gaps before the next GET);
        # the 1h is warm on the same client (one gap).
        g = CANDLE_GAP_S
        self.assertEqual(self.clock.slept, [2 * g, g, 2 * g, g, 2 * g])

    def test_a_cold_symbol_spends_two_gaps(self):
        from market_data.bot_bars import CANDLE_GAP_S
        self._cfg(["EURUSD"])
        self._run()
        self.assertEqual(self.clock.slept, [2 * CANDLE_GAP_S])

    def test_no_candle_after_the_window(self):
        from market_data import bot_bars
        self._cfg(list(self.SYMBOLS))
        orig = self.clock.sleep

        def slow(s):
            orig(s + bot_bars.CANDLE_PASS_MAX_S)
        self.clock.sleep = slow
        out = self._run()
        self.assertEqual(len(self.wire.candle_calls()), 1)
        self.assertIn("420s", out["etoro_stopped"])
        self.assertEqual(out["etoro_left"], 5)

    def test_another_venue_is_neither_paced_nor_windowed(self):
        from market_data import bot_bars
        self._cfg(["EURUSD", "GBPUSD"])
        venue = MagicMock()
        venue._sv_public_feed = False
        venue.klines.return_value = []
        with patch.object(bot_bars, "_client_for", return_value=venue), \
                patch.object(bot_bars, "_public_market_data_client",
                             return_value=self.feed), \
                patch.object(bot_bars, "_candle_sleep") as sleep, \
                patch.object(bot_bars, "refresh_watchlist_bars",
                             return_value={}):
            out = bot_bars.refresh_bot_bars()
        sleep.assert_not_called()
        self.assertEqual(venue.klines.call_count, 4)
        self.assertEqual({c.kwargs["limit"] for c in
                          venue.klines.call_args_list}, {200})
        self.assertEqual(out["etoro_asked"], 0)
        self.assertEqual(out["etoro_stopped"], "")


class TheFirst429Tests(_Base):

    def test_the_first_429_stops_etoro_and_the_feed_is_asked_for_the_rest(
            self):
        self.wire.refuse = {("GBPUSD", "FourHours")}
        self._cfg(list(self.SYMBOLS))
        with self.assertLogs("market_data.bot_bars", level="WARNING") as logs:
            out = self._run()
        self.assertEqual(len(self.wire.candle_calls()), 3)
        self.assertEqual(out["etoro_asked"], 3)
        self.assertEqual(out["etoro_left"], 3)
        self.assertIn("HTTP 429 at /candles in klines(GBPUSD, 4h)",
                      out["etoro_stopped"])
        self.assertEqual(self.feed.calls, [("GBPUSD", "4h"), ("GBPUSD", "1h"),
                                           ("USDJPY", "4h"), ("USDJPY", "1h")])
        self.assertTrue(any("3 candle read(s) not asked, sent to the public "
                            "feed instead" in m for m in logs.output),
                        logs.output)
        # the grep line is kept
        self.assertTrue(any("klines(GBPUSD, 4h) failed" in m
                            for m in logs.output), logs.output)

    def test_a_refused_search_inside_klines_stops_it_too(self):
        self.wire.search_refuse = {"EURUSD"}
        self._cfg(list(self.SYMBOLS))
        out = self._run()
        self.assertEqual(self.wire.candle_calls(), [])
        self.assertEqual(sum("/search" in u for u in self.wire.calls), 1)
        self.assertEqual(out["etoro_left"], 5)
        self.assertIn("HTTP 429 at /search in klines(EURUSD, 4h)",
                      out["etoro_stopped"])

    def test_a_429_is_not_a_mute_venue(self):
        from market_data.bot_bars import _venue_is_mute
        self.wire.refuse = {("EURUSD", "FourHours")}
        self.feed.klines = lambda *a, **k: [[1, "1", "1", "1", "1", "0"]]
        self._cfg(["EURUSD"])
        out = self._run()
        self.assertGreaterEqual(out["fallback"], 1)
        self.assertFalse(_venue_is_mute("etoro", "EURUSD", "4h"))
        self.assertFalse(_venue_is_mute("etoro", "EURUSD", "1h"))

    def test_bar_refusals_are_never_noted_on_the_venues_health(self):
        from bot_program import venue_health
        self.wire.search_refuse = {"EURUSD"}
        self.wire.refuse = {("GBPUSD", "FourHours")}
        self._cfg(["EURUSD"], name="A")
        self._cfg(["GBPUSD"], name="B")
        self._run()
        self._run()
        self.assertEqual(venue_health._load(
            venue_health._key("etoro", "live")), {})
        self.assertIsNone(venue_health.sick("etoro", "live"))


class TheYieldTests(_Base):

    def test_a_live_429_keeps_the_bars_off_etoro(self):
        from bot_program import venue_health
        venue_health.note("etoro", "live", "ticker", code=429)
        self._cfg(["EURUSD"])
        out = self._run()
        self.assertEqual(self.wire.calls, [])
        self.assertIn("trading lane met eToro's HTTP 429", out["etoro_stopped"])
        self.assertEqual(len(self.feed.calls), 2)

    def test_an_older_live_429_is_ignored(self):
        from django.utils import timezone

        from bot_program import venue_health
        venue_health.note("etoro", "live", "ticker", code=429,
                          now=timezone.now() - timedelta(seconds=121))
        self._cfg(["EURUSD"])
        self._run()
        self.assertEqual(len(self.wire.candle_calls()), 2)

    def test_a_sick_venue_keeps_the_bars_off_etoro(self):
        from bot_program import venue_health
        for _ in range(3):
            venue_health.note("etoro", "live", "account", code=503)
        self._cfg(["EURUSD"])
        out = self._run()
        self.assertEqual(self.wire.calls, [])
        self.assertIn("is sick", out["etoro_stopped"])


class TheQuotaHeadersTests(_Base):

    def test_they_are_said_once_per_pass(self):
        self.wire.headers = {"X-RateLimit-Remaining": "17",
                             "Content-Type": "application/json"}
        self._cfg(["EURUSD", "GBPUSD"])
        with self.assertLogs("market_data.bot_bars", level="INFO") as logs:
            self._run()
        said = [m for m in logs.output if "quota headers on a candle" in m]
        self.assertEqual(len(said), 1)
        self.assertIn("X-RateLimit-Remaining", said[0])
        self.assertNotIn("Content-Type", said[0])


class _TickingFeed(_Feed):
    """The watchlist's keyless feed: each read costs `cost` seconds on the
    pass's clock, and answers `rows`."""

    def __init__(self, clock, cost=1.0, rows=()):
        super().__init__()
        self.clock, self.cost, self.rows = clock, cost, list(rows)

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval))
        self.clock.t += self.cost
        return list(self.rows)


class TheDeadlineTests(_Base):

    def _row(self, cfg, symbol, *, paper):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=cfg, asset_class=cfg.asset_class, symbol=symbol,
            side="BUY", status="OPEN", qty=Decimal("1"),
            entry_price=Decimal("1.25"), stop_loss=Decimal("1.2"),
            take_profit=Decimal("1.3"), paper=paper)

    def _late_on_the_first_client(self, past=None):
        """`_client_for` that moves the pass's clock on its first call:
        past BARS_PASS_MAX_S by default, or to `past` seconds in."""
        from market_data import bot_bars
        clock, n = self.clock, {"c": 0}
        start = clock.t

        def late(*a, **k):
            n["c"] += 1
            if n["c"] == 1:
                clock.t = start + (bot_bars.BARS_PASS_MAX_S
                                   if past is None else past)
            return self._client()
        return late

    def _run_with_the_watchlist(self, feed, client_for=None):
        """The pass with the REAL watchlist, its keyless feed `feed`."""
        from market_data import bot_bars
        real = bot_bars.refresh_watchlist_bars
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed), \
                patch.object(bot_bars, "_pace"), \
                patch.object(bot_bars, "refresh_watchlist_bars",
                             side_effect=real) as wl:
            out = self._run_unmocked(client_for)
        self.wl = wl
        return out

    def _run_unmocked(self, client_for=None):
        from market_data import bot_bars
        with patch.object(bot_bars, "_client_for",
                          side_effect=client_for or self._client), \
                patch.object(bot_bars, "_public_market_data_client",
                             return_value=self.feed), \
                patch.object(bot_bars, "_mono", self.clock.mono), \
                patch.object(bot_bars, "_candle_sleep", self.clock.sleep):
            return bot_bars.refresh_bot_bars()

    def test_the_pass_stops_at_its_deadline(self):
        from market_data import bot_bars
        self._cfg(["EURUSD"], name="A")
        self._cfg(["GBPUSD", "USDJPY"], name="B")
        clock = self.clock

        def late(*a, **k):
            clock.t += bot_bars.BARS_PASS_MAX_S
            return self._client()
        out = self._run(client_for=late)
        self.assertEqual(out["not_reached"], 2)
        self.wl.assert_called_once()
        self.assertFalse(self.wl.call_args.kwargs["starred"])

    # A HELD SYMBOL ON A CONFIG THE DEADLINE CUT (review, 2026-10-07).
    # `covered` was every enabled config's symbols, reached or not: the
    # watchlist's held part skipped them, so an OPEN row on a config the
    # deadline cut got no bar from any path in that pass, while the
    # WARNING said "held symbols are still refreshed".

    def test_a_paper_row_on_a_cut_config_is_refreshed_by_the_watchlist(self):
        self._cfg(["EURUSD"], mode="live", name="A")
        b = self._cfg(["GBPUSD"], name="B")
        self._row(b, "GBPUSD", paper=True)
        feed = _TickingFeed(self.clock, cost=0.0)
        with self.assertLogs("market_data.bot_bars", level="WARNING") as logs:
            out = self._run_with_the_watchlist(
                feed, self._late_on_the_first_client())
        self.assertEqual(out["not_reached"], 1)
        kw = self.wl.call_args.kwargs
        self.assertNotIn("GBPUSD", kw["covered"])
        self.assertIn("EURUSD", kw["covered"])
        self.assertEqual(kw["unreached"], {"GBPUSD"})
        self.assertFalse(kw["starred"])
        self.assertEqual(feed.calls, [("GBPUSD", "4h"), ("GBPUSD", "1h")])
        self.assertTrue(any("held symbols are still refreshed" in m
                            for m in logs.output), logs.output)

    def test_a_real_row_on_a_cut_live_config_is_refreshed_by_the_watchlist(
            self):
        self._cfg(["EURUSD"], mode="live", name="A")
        b = self._cfg(["GBPUSD"], mode="live", name="B")
        self._row(b, "GBPUSD", paper=False)
        feed = _TickingFeed(self.clock, cost=0.0)
        out = self._run_with_the_watchlist(
            feed, self._late_on_the_first_client())
        self.assertEqual(out["not_reached"], 1)
        # A live config covers it, so it is no D8 row: eToro never asked.
        self.assertFalse(any("/instruments/1001/" in u
                             for u in self.wire.calls))
        self.assertNotIn("GBPUSD", self.wl.call_args.kwargs["covered"])
        self.assertEqual(feed.calls, [("GBPUSD", "4h"), ("GBPUSD", "1h")])

    def test_a_cut_symbol_another_config_reached_stays_covered(self):
        a = self._cfg(["EURUSD"], mode="live", name="A")
        self._cfg(["EURUSD"], name="B")
        self._row(a, "EURUSD", paper=True)
        feed = _TickingFeed(self.clock, cost=0.0)
        out = self._run_with_the_watchlist(
            feed, self._late_on_the_first_client())
        self.assertEqual(out["not_reached"], 1)
        self.assertIn("EURUSD", self.wl.call_args.kwargs["covered"])
        self.assertEqual(self.wl.call_args.kwargs["unreached"], set())
        self.assertEqual(feed.calls, [])

    def test_the_watchlist_fills_a_cut_symbol_after_the_venues_last_bar(
            self):
        """As for a mute venue: the keyless rows go AFTER the venue's newest
        bar, never across its window (Yahoo's 4h grid is not eToro's, so a
        stand-in written across it sits beside the venue's bars)."""
        from instruments.models import Instrument
        from market_data.models import PriceData
        self._cfg(["EURUSD"], mode="live", name="A")
        b = self._cfg(["GBPUSD"], name="B")
        self._row(b, "GBPUSD", paper=True)
        inst = Instrument.objects.get(symbol="GBPUSD")
        t = _grid(int(datetime.now(dt_tz.utc).timestamp() * 1000), FOUR_H)
        PriceData.objects.create(
            instrument=inst, timeframe="4h",
            timestamp=datetime.fromtimestamp(t / 1000, tz=dt_tz.utc),
            open=1, high=1, low=1, close=1, volume=0, source="etoro")
        before, after = t - 2 * H, t + 2 * H
        feed = _TickingFeed(self.clock, cost=0.0, rows=[
            [before, "1.2", "1.3", "1.1", "1.25", "0"],
            [after, "1.2", "1.3", "1.1", "1.25", "0"]])
        self._run_with_the_watchlist(feed, self._late_on_the_first_client())
        got = {int(ts.timestamp() * 1000): src for ts, src in
               PriceData.objects.filter(instrument=inst, timeframe="4h")
               .values_list("timestamp", "source")}
        self.assertEqual(got, {t: "etoro", after: "_ticking_public"})

    # THE STARRED PART STOPS SYMBOL BY SYMBOL, AND eTORO'S SUMMARY IS SAID
    # BEFORE IT (review, 2026-10-07). `late` was read once before the
    # watchlist: configs ending just under BARS_PASS_MAX_S let the whole
    # starred part run past the task's hard limit, and the summary the
    # operator checks grep for was logged only after it.

    def test_the_starred_part_stops_at_the_deadline_symbol_by_symbol(self):
        from instruments.models import Instrument
        from market_data import bot_bars
        stars = ("AUDUSD", "EURGBP", "NZDUSD", "USDCAD")
        for s in stars:
            Instrument.objects.create(symbol=s, name=s, asset_class="forex",
                                      is_watchlist=True, is_active=True)
        self._cfg(["EURUSD"], mode="live", name="A")
        feed = _TickingFeed(self.clock, cost=1.0)
        said_first = []
        real = bot_bars.refresh_watchlist_bars

        def entered(**kw):
            said_first.append(sum("was asked no more candles" in m
                                  for m in logs.output))
            return real(**kw)
        with self.assertLogs("market_data.bot_bars",
                             level="WARNING") as logs, \
                patch("market_data.public_feed.public_feed_for",
                      return_value=feed), \
                patch.object(bot_bars, "_pace"), \
                patch.object(bot_bars, "refresh_watchlist_bars",
                             side_effect=entered) as wl:
            out = self._run_unmocked(self._late_on_the_first_client(
                past=bot_bars.BARS_PASS_MAX_S - 1))
        self.assertTrue(wl.call_args.kwargs["starred"])
        # 539 s: the first star is read (540 s, 541 s), then it stops.
        self.assertEqual(feed.calls, [("AUDUSD", "4h"), ("AUDUSD", "1h")])
        self.assertTrue(any("3 starred symbol(s) not reached" in m
                            for m in logs.output), logs.output)
        # eToro's summary was said before the watchlist was entered.
        self.assertEqual(said_first, [1])
        self.assertIn("420s", out["etoro_stopped"])
        self.assertEqual(out["etoro_left"], 2)


class TheWatchlistTests(TestCase):

    def test_the_starred_part_can_be_skipped_the_held_part_cannot(self):
        from instruments.models import Instrument
        from market_data import bot_bars
        Instrument.objects.create(symbol="XAGUSD", name="Silver",
                                  asset_class="commodity")
        Instrument.objects.create(symbol="EURGBP", name="EURGBP",
                                  asset_class="forex", is_watchlist=True)
        feed = _Feed()

        def run(**kw):
            feed.calls.clear()
            with patch("brain.synthesizer._held_symbols",
                       return_value={"XAGUSD"}), \
                    patch("market_data.public_feed.public_feed_for",
                          return_value=feed), \
                    patch.object(bot_bars, "_pace"):
                bot_bars.refresh_watchlist_bars(intervals=("4h",), **kw)
            return [s for s, _i in feed.calls]
        self.assertEqual(run(), ["XAGUSD", "EURGBP"])
        self.assertEqual(run(starred=False), ["XAGUSD"])
        # `stop` (2026-10-07) cuts the starred part, never the held part.
        self.assertEqual(run(stop=lambda: True), ["XAGUSD"])
        self.assertEqual(run(stop=lambda: False), ["XAGUSD", "EURGBP"])


class TheTaskTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)

    def test_one_pass_at_a_time(self):
        from django.core.cache import cache

        from market_data import tasks
        cache.add(tasks.BARS_LOCK_KEY, "x", 60)
        with patch("market_data.bot_bars.refresh_bot_bars") as run:
            out = tasks.refresh_bot_bars_task()
        run.assert_not_called()
        self.assertEqual(out["status"], "skipped")

    def test_the_lock_is_released_even_when_the_pass_raises(self):
        from django.core.cache import cache

        from market_data import tasks
        with patch("market_data.bot_bars.refresh_bot_bars",
                   side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                tasks.refresh_bot_bars_task()
        self.assertIsNone(cache.get(tasks.BARS_LOCK_KEY))

    def test_the_bounds_fit_inside_the_beat(self):
        from django_celery_beat.schedulers import ModelEntry

        from bot_program.engine import etoro_client
        from config.celery import app
        from market_data import bot_bars, tasks
        entry = app.conf.beat_schedule["refresh-bot-bars"]
        beat = entry["schedule"]
        kept = ModelEntry._unpack_options(**entry["options"])
        self.assertEqual(kept["expire_seconds"], 540)
        limit = tasks.refresh_bot_bars_task.time_limit
        self.assertEqual(bot_bars.CANDLE_PASS_MAX_S + 120,
                         bot_bars.BARS_PASS_MAX_S)
        self.assertLess(bot_bars.BARS_PASS_MAX_S, limit)
        self.assertLess(limit, beat)
        self.assertEqual(beat, 600.0)
        self.assertEqual(tasks.BARS_LOCK_S, limit)
        self.assertEqual(bot_bars.YIELD_AFTER_LIVE_429_S,
                         etoro_client.RATE_PAUSE_MAX_S)

    def test_the_paced_pass_leaves_the_tick_two_slots(self):
        """The paced bar pass holds one worker-fast slot for most of every
        beat (2026-10-07): the worker that runs the bot tick (the default
        queue) keeps at least two more, so the tick never waits behind the
        bars and a poller."""
        from pathlib import Path

        from django.conf import settings
        compose = (Path(settings.BASE_DIR) / "deploy" / "docker-compose.yml"
                   ).read_text(encoding="utf-8")
        command = next(line for line in compose.splitlines()
                       if "-Q fast,default" in line)
        slots = int(re.search(r"\s-c\s+(\d+)", command).group(1))
        self.assertGreaterEqual(slots, 3, command)
