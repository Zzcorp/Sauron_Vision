"""THE SHARED /search-ID MEMO (2026-10-07, PR50 P5).

Right after the PR49 deploy (2026-10-07 ~12:3x UTC) eToro (live) went SICK
on three /search 429s. A deploy empties the per-process /search memo
(etoro_client._SEARCH_IDS), so the first fleet pass asked /search again for
every unpinned symbol.

  * an id eToro answered with an EXACT spelling is also kept in Django's
    cache (Redis in production), keyed (world, symbol), for 30 days less up
    to 10 (fixed by the key) — counted from the LAST read that used it: a
    shared hit re-arms its key (2026-10-07, review: a life counted from
    the wire write alone expired one pass's ids together about a month
    later, and the next deploy asked /search for most of them at once). It
    is read after the process memo and before the kept "no" and /search. A
    lone result, an unknown spelling, a refusal and a pinned-owner conflict
    are never written.
  * a kept id is served only while its spelling is still VENUE_SPELLING's
    and no other pinned symbol owns it; any cache trouble asks the wire.
    One read on the wire more than 90 days (less up to 10) ago is asked
    again by a BACKGROUND read (klines) and still answers a money read.
  * a shared hit clears a kept "no", and search_no reads "" for it; the
    words a refused entry logs never claim a /search that is not asked.
  * the suite runs with it off (tests/__init__.py); this module turns it on,
    and _clear_eligibility deletes every key it wrote.

Run with:  python manage.py test tests.test_etoro_id_memo
"""
import ast
import contextlib
import inspect
import logging
import types
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from bot_program import venue_health as vh
from bot_program.engine import etoro_client as ec
from tests.test_etoro_client import SEARCH_AAPL, _clear_eligibility, _client

LOGGER = "bot_program.engine.etoro_client"
SEARCH_NONE = ("GET", "/market-data/search", 200, [])
RATES_OK = ("GET", "/rates", 200, {"rates": [
    {"bid": 99.9, "ask": 100.1, "lastExecution": 100.0}]})


def _searches(fake):
    return [c for c in fake.calls if "/market-data/search" in c[1]]


def _asked_as(fake):
    return [c[2].get("params", {}).get("internalSymbolFull")
            for c in _searches(fake)]


def _shared(world, symbol):
    return cache.get(ec._search_shared_key((world, symbol)))


def _seed(world, symbol, value):
    """Another process's entry (or a broken one), registered for
    _clear_eligibility like every key the adapter writes."""
    key = ec._search_shared_key((world, symbol))
    ec._SEARCH_SHARED_KEYS.add(key)
    cache.set(key, value, 600)


def _candles(n=3, iid=1001):
    bars = [{"fromDate": f"2026-10-06T{4 * i:02d}:00:00Z", "open": 1.1,
             "high": 1.2, "low": 1.0, "close": 1.15, "volume": 5}
            for i in range(n)]
    return ("GET", "/history/candles", 200,
            {"candles": [{"instrumentId": iid, "candles": bars}]})


def _today():
    return datetime.now(timezone.utc).date()


class _Counting:
    """The real cache, with every get, set and touch recorded."""

    def __init__(self):
        self.gets, self.sets, self.touches = [], [], []

    def get(self, key, *a, **kw):
        self.gets.append(key)
        return cache.get(key, *a, **kw)

    def set(self, key, value, timeout=None, *a, **kw):
        self.sets.append((key, value, timeout))
        return cache.set(key, value, timeout, *a, **kw)

    def touch(self, key, timeout=None, *a, **kw):
        self.touches.append((key, timeout))
        return cache.touch(key, timeout, *a, **kw)

    def __getattr__(self, name):
        return getattr(cache, name)


def _cache_clock(clock):
    """LocMem's clock (its expiry and the timeout it files) read `clock[0]`
    — only the cache's: nothing else in the process sees it."""
    fake = types.SimpleNamespace(time=lambda: clock[0])
    return (mock.patch("django.core.cache.backends.locmem.time", fake),
            mock.patch("django.core.cache.backends.base.time", fake))


def _days_ago(n):
    return (_today() - timedelta(days=n)).isoformat()


class _Broken:
    """A cache that cannot be reached (Redis down)."""

    def __getattr__(self, name):
        def boom(*a, **kw):
            raise ConnectionError("redis down")
        return boom


def _cache_is(fake):
    return mock.patch("django.core.cache.cache", fake)


class _SharedOn:
    def setUp(self):
        super().setUp()
        p = mock.patch.object(ec, "SEARCH_SHARED_MEMO", True)
        p.start()
        self.addCleanup(p.stop)
        ec._SEARCH_IDS.clear()
        ec._SEARCH_NO.clear()
        self.addCleanup(ec._SEARCH_IDS.clear)
        self.addCleanup(ec._SEARCH_NO.clear)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)


# ── the switch ────────────────────────────────────────────────────────────

class TheSwitchTests(SimpleTestCase):

    def setUp(self):
        super().setUp()
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_the_suite_runs_with_it_off(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_client.SEARCH_SHARED_MEMO = False", src)
        self.assertIs(ec.SEARCH_SHARED_MEMO, False)

    def test_off_means_nothing_is_read_or_written(self):
        self.assertIs(ec.SEARCH_SHARED_MEMO, False)
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL",
                               "read_on": "2026-10-07"})
        counting = _Counting()
        with _cache_is(counting):
            t, fake = _client([SEARCH_AAPL], env="live")
            self.assertEqual(t.instrument_id("AAPL"), 1001)
            self.assertEqual(len(_searches(fake)), 1, "the wire was asked")
            t2, _f = _client([("GET", "/market-data/search", 200, [
                {"instrumentId": 4242, "internalSymbolFull": "NVDA"}])],
                env="live")
            self.assertEqual(t2.instrument_id("NVDA"), 4242)
        self.assertEqual((counting.gets, counting.sets, counting.touches),
                         ([], [], []))
        self.assertIsNone(_shared("live", "NVDA"))

    def test_off_the_re_arm_makes_no_cache_call(self):
        """2026-10-07 (review): the touch a shared hit makes is behind the
        same switch."""
        self.assertIs(ec.SEARCH_SHARED_MEMO, False)
        counting = _Counting()
        with _cache_is(counting):
            self.assertIsNone(ec._search_shared_touch(("live", "AAPL")))
        self.assertEqual((counting.gets, counting.sets, counting.touches),
                         ([], [], []))


# ── the read-through ──────────────────────────────────────────────────────

class TheReadThroughTests(_SharedOn, SimpleTestCase):

    def test_a_shared_hit_asks_no_search_from_a_fresh_process_memo(self):
        with mock.patch.object(ec, "SEARCH_MEMO", True):
            t1, f1 = _client([SEARCH_AAPL], env="live")
            self.assertEqual(t1.instrument_id("AAPL"), 1001)
            self.assertEqual(len(_searches(f1)), 1)
            ec._SEARCH_IDS.clear()            # a deploy: a fresh process
            t2, f2 = _client([SEARCH_AAPL], env="live")
            with self.assertLogs(LOGGER, "INFO") as logs:
                self.assertEqual(t2.instrument_id("aapl"), 1001)
            self.assertEqual(f2.calls, [], "the shared memo answered")
            self.assertEqual(t2.wire_reads, 0)
            self.assertEqual(t2._ids["AAPL"], 1001)
            self.assertEqual(t2._symbols[1001], "AAPL")
            self.assertEqual(t2._venue_spelling[1001], "AAPL")
            self.assertEqual(ec._SEARCH_IDS[("live", "AAPL")],
                             (_today(), 1001, "AAPL"),
                             "this process's memo is filled")
        self.assertIn("from the shared /search memo", "\n".join(logs.output))

    def test_a_shared_hit_with_the_process_memo_off(self):
        self.assertIs(ec.SEARCH_MEMO, False)
        t1, _f1 = _client([SEARCH_AAPL], env="live")
        t1.instrument_id("AAPL")
        t2, f2 = _client([SEARCH_AAPL], env="live")
        self.assertEqual(t2.instrument_id("AAPL"), 1001)
        self.assertEqual(_searches(f2), [])
        self.assertEqual(ec._SEARCH_IDS, {}, "SEARCH_MEMO off fills none")

    def test_the_date_it_was_read_travels_with_it(self):
        _seed("live", "NVDA", {"iid": 4242, "spelled": "NVDA",
                               "read_on": "2026-09-01"})
        with mock.patch.object(ec, "SEARCH_MEMO", True):
            t, fake = _client([], env="live")
            self.assertEqual(t.instrument_id("NVDA"), 4242)
        self.assertEqual(fake.calls, [])
        self.assertEqual(ec._SEARCH_IDS[("live", "NVDA")],
                         (date(2026, 9, 1), 4242, "NVDA"))

    def test_the_read_order(self):
        """_ids, the pins, _SEARCH_IDS, then the shared memo: none of the
        first three costs a cache read."""
        counting = _Counting()
        with _cache_is(counting), mock.patch.object(ec, "SEARCH_MEMO", True):
            t, fake = _client([], env="live")
            sym, iid = next(iter(ec.VENUE_ID_PINS.items()))
            self.assertEqual(t.instrument_id(sym), iid)
            t._ids["AAPL"] = 1001
            self.assertEqual(t.instrument_id("AAPL"), 1001)
            ec._SEARCH_IDS[("live", "MSFT")] = (_today(), 2002, "MSFT")
            self.assertEqual(t.instrument_id("MSFT"), 2002)
            self.assertEqual(counting.gets, [])
            self.assertEqual(fake.calls, [])
            _seed("live", "NVDA", {"iid": 4242, "spelled": "NVDA"})
            self.assertEqual(t.instrument_id("NVDA"), 4242)
            self.assertEqual(counting.gets,
                             [ec._search_shared_key(("live", "NVDA"))])
            self.assertEqual(fake.calls, [])

    def test_a_shared_hit_inside_klines_costs_one_wire_read(self):
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL"})
        t, fake = _client([_candles()], env="live")
        rows = t.klines("AAPL", interval="4h", limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(_searches(fake), [])
        self.assertEqual((t.wire_reads, t.last_read), (1, "candles"))
        self.assertFalse(t._background)

    def test_a_shared_hit_prices_a_mark(self):
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL"})
        t, fake = _client([RATES_OK], env="live")
        self.assertEqual(float(t.ticker("AAPL")["lastPrice"]), 100.0)
        self.assertEqual(_searches(fake), [])
        self.assertEqual(fake.calls[0][2]["params"],
                         {"instrumentIds": "1001"})


# ── the write ─────────────────────────────────────────────────────────────

class TheWriteTests(_SharedOn, SimpleTestCase):

    def test_only_an_exact_hit_is_written(self):
        t, _f = _client([("GET", "/market-data/search", 200, [
            {"instrumentId": 999, "internalSymbolFull": "AAPL.RTH"},
            {"instrumentId": 1001, "internalSymbolFull": "AAPL"}])],
            env="live")
        self.assertEqual(t.instrument_id("AAPL"), 1001)
        self.assertEqual(ec._search_shared_key(("live", "AAPL")),
                         "etoro_search_id:live:AAPL")
        self.assertEqual(_shared("live", "AAPL"),
                         {"iid": 1001, "spelled": "AAPL",
                          "read_on": _today().isoformat()})
        self.assertEqual(ec._SEARCH_SHARED_KEYS,
                         {"etoro_search_id:live:AAPL"})

    def test_a_mapped_spelling_is_kept_under_the_platform_symbol(self):
        t, fake = _client([("GET", "/market-data/search", 200, [
            {"instrumentId": 100000, "internalSymbolFull": "BTC"}])],
            env="live")
        self.assertEqual(t.instrument_id("BTCUSD"), 100000)
        self.assertEqual(_asked_as(fake), ["BTC"])
        self.assertEqual(_shared("live", "BTCUSD")["spelled"], "BTC")
        self.assertIsNone(_shared("live", "BTC"))
        t2, f2 = _client([], env="live")
        self.assertEqual(t2.instrument_id("BTCUSD"), 100000)
        self.assertEqual(f2.calls, [])
        self.assertEqual(t2._venue_spelling[100000], "BTC")

    def test_a_refusal_a_lone_result_or_an_unknown_spelling_is_never_written(
            self):
        cases = (
            ("AAPL", ("GET", "/market-data/search", 429, {})),
            ("AAPL", ("GET", "/market-data/search", 500, {})),
            ("AAPL", ("GET", "/market-data/search", 404, {})),
            ("AAPL", "transport"),
            ("WHEAT", ("GET", "/market-data/search", 200, [
                {"instrumentId": 97, "internalSymbolFull": "WHEAT.FUT"}])),
            ("NOPE", SEARCH_NONE),
            ("NOPE", ("GET", "/market-data/search", 200, {"what": 1})),
            ("BRNUSD", SEARCH_NONE),
        )
        for symbol, route in cases:
            with self.subTest(symbol=symbol, route=route):
                _clear_eligibility()
                t, fake = _client([] if route == "transport" else [route],
                                  env="live")
                if route == "transport":
                    fake.get = mock.Mock(side_effect=(
                        requests.exceptions.ConnectionError("down")))
                with mock.patch("time.sleep"), \
                        self.assertRaises(Exception):
                    t.instrument_id(symbol)
                self.assertIsNone(_shared("live", symbol))
                self.assertEqual(ec._SEARCH_SHARED_KEYS, set())

    def test_a_pinned_owner_conflict_is_never_written(self):
        """The catalogue's GOLD is Barrick, a stock; eToro's GOLD is id 18,
        the metal, pinned to XAUUSD."""
        t, _f = _client([("GET", "/market-data/search", 200, [
            {"instrumentId": 18, "internalSymbolFull": "GOLD"}])],
            env="live")
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("GOLD")
        self.assertIn("pinned to 'XAUUSD'", str(cm.exception))
        self.assertIsNone(_shared("live", "GOLD"))
        self.assertEqual(ec._SEARCH_SHARED_KEYS, set())

    def test_the_life_is_thirty_days_at_most_spread_by_key(self):
        self.assertEqual(ec.SEARCH_SHARED_TTL_S, 30 * 86400)
        self.assertEqual(ec.SEARCH_SHARED_SPREAD_S, 10 * 86400)
        lives = set()
        for world in ("live", "demo"):
            for sym in ("AAPL", "NVDA", "EURUSD", "USDCNH", "EURNOK", "PG",
                        "XOM", "MSFT", "SPX500", "BTCUSD"):
                key = ec._search_shared_key((world, sym))
                life = ec._search_shared_life_s(key)
                self.assertEqual(life, ec._search_shared_life_s(key),
                                 "fixed by the key")
                self.assertGreater(life, 20 * 86400)
                self.assertLessEqual(life, 30 * 86400)
                lives.add(life)
        self.assertGreater(len(lives), 10, "not one minute for all")
        counting = _Counting()
        with _cache_is(counting):
            t, _f = _client([SEARCH_AAPL], env="live")
            t.instrument_id("AAPL")
        [(key, _value, timeout)] = counting.sets
        self.assertEqual(timeout, ec._search_shared_life_s(key))

    def test_a_shared_hit_re_arms_its_key_for_its_life(self):
        """2026-10-07 (review): a read alone used to leave the key's life
        untouched (the only cache call on a shared hit was the get)."""
        t1, _f1 = _client([SEARCH_AAPL], env="live")
        t1.instrument_id("AAPL")
        key = ec._search_shared_key(("live", "AAPL"))
        counting = _Counting()
        with _cache_is(counting):
            t2, f2 = _client([], env="live")
            self.assertEqual(t2.instrument_id("AAPL"), 1001)
        self.assertEqual(f2.calls, [])
        self.assertEqual(counting.gets, [key])
        self.assertEqual(counting.sets, [], "a hit is no write")
        self.assertEqual(counting.touches,
                         [(key, ec._search_shared_life_s(key))])

    def test_a_key_lives_from_the_last_cold_read_not_from_its_write(self):
        """The failing state of the review: ids written by P5's first pass
        on day 0, read by a deploy every few days, all expired 20-30 days
        after day 0 — and the next deploy asked /search for most of them at
        once. Re-armed by every shared hit, a key outlives its first life
        for as long as cold processes keep reading it."""
        clock = [1_000_000.0]
        a, b = _cache_clock(clock)
        with a, b:
            t1, _f1 = _client([SEARCH_AAPL], env="live")
            t1.instrument_id("AAPL")                       # day 0: the wire
            key = ec._search_shared_key(("live", "AAPL"))
            life = ec._search_shared_life_s(key)
            for _deploy in range(3):                       # a deploy a day
                clock[0] += life - 86400                   # before it dies
                t, fake = _client([], env="live")
                self.assertEqual(t.instrument_id("AAPL"), 1001)
                self.assertEqual(fake.calls, [], "served from the memo")
            self.assertGreater(clock[0] - 1_000_000.0, 2 * life)
            self.assertIsNotNone(_shared("live", "AAPL"))
            clock[0] += life + 1                           # unread a life
            self.assertIsNone(_shared("live", "AAPL"))

    def test_the_write_sits_in_adopt_alone(self):
        cls = inspect.getsource(ec.EtoroTrader)
        self.assertEqual(cls.count("_search_shared_put("), 1)
        adopt = inspect.getsource(ec.EtoroTrader._adopt)
        self.assertLess(adopt.index("_SEARCH_IDS[memo_key] = (today, iid, "
                                    "sym)"),
                        adopt.index("_search_shared_put(memo_key, iid, sym, "
                                    "today)"))
        self.assertLess(adopt.index("if owner is not None and owner != key"),
                        adopt.index("_search_shared_put("),
                        "the owner check comes first")
        self.assertLess(adopt.index("if iid and sym == wire:"),
                        adopt.index("_search_shared_put("),
                        "inside the exact-spelling branch")
        self.assertLess(adopt.index("_search_shared_put("),
                        adopt.index("if len(items) == 1 and iid:"),
                        "never on the lone-result path")


# ── the age cap: a wrong id is bounded by the day it was read ────────────

class TheAgeCapTests(_SharedOn, SimpleTestCase):
    """Re-armed on every hit, a key could serve a wrong id (a spelling eToro
    gave to another instrument) for ever. The day it was read on the wire
    bounds that: past SEARCH_SHARED_MAX_AGE_S (90 days less the key's cut)
    a BACKGROUND read (klines) asks the wire again — paced, never noted,
    never pausing — and a money read is still served, never paying a
    /search for it."""

    def test_the_cap_is_ninety_days_at_most_spread_by_key(self):
        self.assertEqual(ec.SEARCH_SHARED_MAX_AGE_S, 90 * 86400)
        caps = set()
        for world in ("live", "demo"):
            for sym in ("AAPL", "NVDA", "EURUSD", "USDCNH", "PG", "XOM"):
                key = ec._search_shared_key((world, sym))
                cap = ec._search_shared_max_age_s(key)
                self.assertGreater(cap, 80 * 86400)
                self.assertLessEqual(cap, 90 * 86400)
                self.assertEqual(
                    ec.SEARCH_SHARED_MAX_AGE_S - cap,
                    ec.SEARCH_SHARED_TTL_S - ec._search_shared_life_s(key),
                    "the same cut as the life")
                caps.add(cap)
        self.assertGreater(len(caps), 6, "not one day for all")

    def test_an_entry_inside_its_cap_is_served_to_klines(self):
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL",
                               "read_on": _days_ago(79)})
        t, fake = _client([_candles()], env="live")
        self.assertEqual(len(t.klines("AAPL", interval="4h", limit=3)), 3)
        self.assertEqual(_searches(fake), [])

    def test_a_date_that_cannot_be_read_is_today(self):
        for read_on in (None, "garbage", 7):
            with self.subTest(read_on=read_on):
                _clear_eligibility()
                _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL",
                                       "read_on": read_on})
                t, fake = _client([_candles()], env="live")
                t.klines("AAPL", interval="4h", limit=3)
                self.assertEqual(_searches(fake), [])

    def test_past_its_cap_klines_asks_the_wire_again(self):
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL",
                               "read_on": _days_ago(91)})
        t, fake = _client([SEARCH_AAPL, _candles()], env="live")
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.assertEqual(len(t.klines("AAPL", interval="4h", limit=3)),
                             3)
        self.assertEqual(_asked_as(fake), ["AAPL"])
        self.assertEqual(t.wire_reads, 2)
        self.assertEqual(_shared("live", "AAPL")["read_on"],
                         _today().isoformat(), "the wire's answer rewrote it")
        self.assertIn("past its age cap — asking the wire",
                      "\n".join(logs.output))
        self.assertEqual(vh._load(vh._key("etoro", "live")).get("failures")
                         or [], [], "a background read notes nothing")

    def test_a_refused_re_ask_keeps_the_old_entry(self):
        """A 429 on the background re-ask: the bars stop for this symbol,
        nothing is noted, and the entry still answers the money reads."""
        old = {"iid": 1001, "spelled": "AAPL", "read_on": _days_ago(91)}
        _seed("live", "AAPL", old)
        t, _f = _client([("GET", "/market-data/search", 429, {})],
                        env="live")
        with mock.patch("time.sleep"), self.assertRaises(Exception):
            t.klines("AAPL", interval="4h", limit=3)
        self.assertEqual(_shared("live", "AAPL"), old)
        self.assertEqual(vh._load(vh._key("etoro", "live")).get("failures")
                         or [], [])
        t2, f2 = _client([RATES_OK], env="live")
        self.assertEqual(float(t2.ticker("AAPL")["lastPrice"]), 100.0)
        self.assertEqual(_searches(f2), [])

    def test_past_its_cap_a_money_read_is_served_and_klines_asks_after(self):
        """A mark never pays a /search for an old entry: it is served and
        re-armed, but stays out of this process's memo, so this process's
        next klines reaches the shared entry and asks the wire itself."""
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL",
                               "read_on": _days_ago(91)})
        key = ec._search_shared_key(("live", "AAPL"))
        counting = _Counting()
        with mock.patch.object(ec, "SEARCH_MEMO", True):
            with _cache_is(counting):
                t, fake = _client([RATES_OK], env="live")
                self.assertEqual(float(t.ticker("AAPL")["lastPrice"]), 100.0)
            self.assertEqual(_searches(fake), [])
            self.assertEqual(counting.touches,
                             [(key, ec._search_shared_life_s(key))])
            self.assertNotIn(("live", "AAPL"), ec._SEARCH_IDS)
            t2, f2 = _client([SEARCH_AAPL, _candles()], env="live")
            t2.klines("AAPL", interval="4h", limit=3)
            self.assertEqual(_asked_as(f2), ["AAPL"])
            self.assertEqual(ec._SEARCH_IDS[("live", "AAPL")],
                             (_today(), 1001, "AAPL"))

    def test_a_fresh_entry_still_fills_the_process_memo(self):
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL",
                               "read_on": _days_ago(10)})
        with mock.patch.object(ec, "SEARCH_MEMO", True):
            t, _f = _client([], env="live")
            t.instrument_id("AAPL")
        self.assertEqual(ec._SEARCH_IDS[("live", "AAPL")],
                         (_today() - timedelta(days=10), 1001, "AAPL"))


# ── what a kept id must still pass, and a cache that fails ───────────────

class TheGuardTests(_SharedOn, SimpleTestCase):

    def test_the_worlds_are_kept_apart(self):
        t1, _f1 = _client([SEARCH_AAPL], env="live")
        t1.instrument_id("AAPL")
        t2, f2 = _client([SEARCH_AAPL], env="demo")
        self.assertEqual(t2.instrument_id("AAPL"), 1001)
        self.assertEqual(len(_searches(f2)), 1, "demo read none of live's")
        self.assertIsNotNone(_shared("demo", "AAPL"))
        _seed("demo", "NVDA", {"iid": 4242, "spelled": "NVDA"})
        t3, f3 = _client([("GET", "/market-data/search", 200, [
            {"instrumentId": 4242, "internalSymbolFull": "NVDA"}])],
            env="live")
        t3.instrument_id("NVDA")
        self.assertEqual(len(_searches(f3)), 1, "live read none of demo's")

    def test_a_raising_cache_falls_back_to_the_wire(self):
        with _cache_is(_Broken()), \
                self.assertLogs(LOGGER, "WARNING") as logs:
            t, fake = _client([SEARCH_AAPL, RATES_OK], env="live")
            self.assertEqual(t.instrument_id("AAPL"), 1001)
            self.assertEqual(len(_searches(fake)), 1)
            t2, f2 = _client([SEARCH_AAPL, RATES_OK], env="live")
            self.assertEqual(float(t2.ticker("AAPL")["lastPrice"]), 100.0)
            self.assertEqual(len(_searches(f2)), 1)
        words = "\n".join(logs.output)
        self.assertIn("shared /search memo unreadable", words)
        self.assertIn("shared /search memo not written", words)
        self.assertNotIn("redis down", words, "the type, not the words")

    def test_a_cached_id_another_pin_owns_is_refused(self):
        _seed("live", "GOLD", {"iid": 18, "spelled": "GOLD"})
        t, fake = _client([("GET", "/market-data/search", 200, [
            {"instrumentId": 2345, "internalSymbolFull": "GOLD"}])],
            env="live")
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.assertEqual(t.instrument_id("GOLD"), 2345)
        self.assertEqual(len(_searches(fake)), 1, "the wire was asked")
        self.assertNotIn(18, t._symbols)
        self.assertIn("pinned to XAUUSD", "\n".join(logs.output))
        self.assertEqual(_shared("live", "GOLD")["iid"], 2345,
                         "the wire's exact answer replaced it")

    def test_a_cached_id_read_under_another_spelling_is_refused(self):
        """VENUE_SPELLING may change between deploys; Redis outlives one."""
        _seed("live", "BTCUSD", {"iid": 555, "spelled": "BTCUSD"})
        t, fake = _client([("GET", "/market-data/search", 200, [
            {"instrumentId": 100000, "internalSymbolFull": "BTC"}])],
            env="live")
        self.assertEqual(t.instrument_id("BTCUSD"), 100000)
        self.assertEqual(_asked_as(fake), ["BTC"])

    def test_a_value_of_another_shape_is_a_miss(self):
        for value in ("1001", 1001, [1001, "AAPL"],
                      {"iid": True, "spelled": "AAPL"},
                      {"iid": 0, "spelled": "AAPL"},
                      {"iid": -5, "spelled": "AAPL"},
                      {"iid": "1001", "spelled": "AAPL"},
                      {"iid": 1001.0, "spelled": "AAPL"},
                      {"iid": 1001},
                      {"iid": 1001, "spelled": 7}):
            with self.subTest(value=value):
                _clear_eligibility()
                _seed("live", "AAPL", value)
                t, fake = _client([SEARCH_AAPL], env="live")
                self.assertEqual(t.instrument_id("AAPL"), 1001)
                self.assertEqual(len(_searches(fake)), 1)

    def test_clear_eligibility_deletes_every_key_it_wrote(self):
        t, _f = _client([SEARCH_AAPL], env="live")
        t.instrument_id("AAPL")
        _seed("demo", "NVDA", {"iid": 4242, "spelled": "NVDA"})
        self.assertIsNotNone(_shared("live", "AAPL"))
        _clear_eligibility()
        self.assertIsNone(_shared("live", "AAPL"))
        self.assertIsNone(_shared("demo", "NVDA"))
        self.assertEqual(ec._SEARCH_SHARED_KEYS, set())


# ── the kept "no" ─────────────────────────────────────────────────────────

class TheKeptNoTests(_SharedOn, SimpleTestCase):

    def setUp(self):
        super().setUp()
        p = mock.patch.object(ec, "SEARCH_NO_MEMO", True)
        p.start()
        self.addCleanup(p.stop)
        self.now = [1000.0]
        p = mock.patch.object(ec, "_mono", lambda: self.now[0])
        p.start()
        self.addCleanup(p.stop)

    def _keep_no(self, symbol="AAPL", env="live"):
        for _ in range(2):
            t, _f = _client([SEARCH_NONE], env=env)
            with self.assertRaises(LookupError):
                t.instrument_id(symbol, trust_no=True)
            self.now[0] += 61
        world = "demo" if env == "demo" else "live"
        self.assertIsNotNone(ec._SEARCH_NO[(world, symbol)]["kept"])

    def test_a_shared_hit_clears_a_kept_no_and_search_no_reads_empty(self):
        self._keep_no()
        t, fake = _client([], env="live")
        self.assertTrue(t.search_no("AAPL").startswith(
            "eToro knows no instrument spelled 'AAPL'"))
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL"})
        self.assertEqual(t.search_no("AAPL"), "")
        self.assertEqual(vh.kept_no(t, "AAPL"), "")
        self.assertEqual(t.instrument_id("AAPL", trust_no=True), 1001)
        self.assertEqual(fake.calls, [])
        self.assertNotIn(("live", "AAPL"), ec._SEARCH_NO)

    def test_klines_read_the_shared_memo_before_the_kept_no(self):
        self._keep_no()
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL"})
        t, fake = _client([_candles()], env="live")
        self.assertEqual(len(t.klines("AAPL", interval="4h", limit=3)), 3)
        self.assertEqual(_searches(fake), [])
        self.assertNotIn(("live", "AAPL"), ec._SEARCH_NO)

    def test_search_no_reads_the_cache_only_when_a_no_is_kept(self):
        counting = _Counting()
        with _cache_is(counting):
            t, _f = _client([], env="live")
            self.assertEqual(t.search_no("AAPL"), "")
        self.assertEqual(counting.gets, [])

    def test_a_refused_shared_id_leaves_the_kept_no(self):
        self._keep_no(symbol="GOLD")
        _seed("live", "GOLD", {"iid": 18, "spelled": "GOLD"})
        t, fake = _client([], env="live")
        self.assertTrue(t.search_no("GOLD").startswith(
            "eToro knows no instrument spelled 'GOLD'"))
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("GOLD", trust_no=True)
        self.assertIn("eToro's answer twice", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_a_raising_cache_never_breaks_search_no(self):
        self._keep_no()
        with _cache_is(_Broken()), self.assertLogs(LOGGER, "WARNING"):
            t, _f = _client([], env="live")
            self.assertTrue(t.search_no("AAPL").startswith(
                "eToro knows no instrument spelled 'AAPL'"))

    def test_the_worlds_are_kept_apart(self):
        self._keep_no(env="demo")
        _seed("live", "AAPL", {"iid": 1001, "spelled": "AAPL"})
        t, _f = _client([], env="demo")
        self.assertTrue(t.search_no("AAPL"), "live's id clears no demo no")

    # The words (2026-10-07, review): a refused or unreadable shared entry
    # used to log "asking the wire" on every propose that read a kept "no"
    # through search_no, where nothing asks /search.

    def test_search_no_never_says_it_asks_the_wire(self):
        self._keep_no()
        for name, seed, cache_fake in (
                ("respelled", {"iid": 1001, "spelled": "OLDSPELL"}, None),
                ("pinned", {"iid": 18, "spelled": "AAPL"}, None),
                ("unreadable", None, _Broken())):
            with self.subTest(name):
                if seed is not None:
                    _seed("live", "AAPL", seed)
                patch = (_cache_is(cache_fake) if cache_fake is not None
                         else contextlib.nullcontext())
                with patch, self.assertLogs(LOGGER, "INFO") as logs:
                    t, fake = _client([], env="live")
                    self.assertTrue(t.search_no("AAPL").startswith(
                        "eToro knows no instrument spelled 'AAPL'"))
                words = "\n".join(logs.output)
                self.assertNotIn("asking the wire", words)
                self.assertIn('the kept "no" stands', words)
                self.assertEqual(fake.calls, [])

    def test_klines_on_a_kept_no_never_says_it_asks_the_wire(self):
        self._keep_no()
        _seed("live", "AAPL", {"iid": 1001, "spelled": "OLDSPELL"})
        t, fake = _client([], env="live")
        with self.assertLogs(LOGGER, "INFO") as logs, \
                self.assertRaises(LookupError):
            t.klines("AAPL", interval="4h", limit=3)
        self.assertEqual(fake.calls, [])
        words = "\n".join(logs.output)
        self.assertNotIn("asking the wire", words)
        self.assertIn('refused, the kept "no" stands', words)

    def test_a_read_that_asks_still_says_so(self):
        self._keep_no()
        _seed("live", "AAPL", {"iid": 1001, "spelled": "OLDSPELL"})
        t, fake = _client([SEARCH_AAPL], env="live")
        with self.assertLogs(LOGGER, "INFO") as logs:
            self.assertEqual(t.instrument_id("AAPL"), 1001)
        self.assertEqual(len(_searches(fake)), 1)
        self.assertIn("refused, asking the wire", "\n".join(logs.output))


# ── the source ────────────────────────────────────────────────────────────

class TheSourceTests(SimpleTestCase):

    def _src(self):
        return inspect.getsource(ec)

    def test_django_is_imported_lazily_and_never_its_timezone(self):
        tree = ast.parse(self._src())
        top = [n for n in tree.body
               if isinstance(n, (ast.Import, ast.ImportFrom))]
        for n in top:
            names = ([a.name for a in n.names] if isinstance(n, ast.Import)
                     else [n.module or ""])
            self.assertFalse(any(x.startswith("django") for x in names),
                             ast.unparse(n))
        self.assertNotIn("django.utils", self._src())
        for fn in (ec._search_shared_get, ec._search_shared_put,
                   ec._search_shared_touch):
            self.assertIn("from django.core.cache import cache",
                          inspect.getsource(fn))

    def test_the_stale_caches_comment_is_gone(self):
        src = self._src()
        self.assertNotIn("config/settings.py defines no CACHES,", src)
        self.assertIn("production's cache IS Redis", src)

    def test_instrument_id_reads_in_the_contract_order(self):
        src = inspect.getsource(ec.EtoroTrader.instrument_id)
        order = [src.index(s) for s in (
            "if key in self._ids:",
            "pinned = VENUE_ID_PINS.get(key)",
            "hit = _SEARCH_IDS.get(memo_key)",
            "shared = _search_shared_get(memo_key, key, wire, then=then)",
            "kept_no = _search_no_replay(memo_key)",
            "/api/v1/market-data/search")]
        self.assertEqual(order, sorted(order))
        self.assertIn("_SEARCH_NO.pop(memo_key, None)",
                      src[order[3]:order[4]])
        self.assertIn("_search_shared_touch(memo_key)",
                      src[order[3]:order[4]], "a shared hit re-arms its key")

    def test_the_helpers_never_raise(self):
        with _cache_is(_Broken()), \
                self.assertLogs(LOGGER, logging.WARNING) as logs, \
                mock.patch.object(ec, "SEARCH_SHARED_MEMO", True):
            self.assertIsNone(ec._search_shared_get(("live", "X"), "X", "X"))
            self.assertIsNone(ec._search_shared_put(("live", "X"), 1, "X",
                                                    _today()))
            self.assertIsNone(ec._search_shared_touch(("live", "X")))
        ec._SEARCH_SHARED_KEYS.discard(ec._search_shared_key(("live", "X")))
        self.assertIn("shared /search memo not re-armed",
                      "\n".join(logs.output))
        for read_on in (None, "x", object(), "2026-10-07"):
            self.assertIn(ec._search_shared_stale(("live", "X"), read_on),
                          (True, False))
