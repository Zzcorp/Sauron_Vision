"""WEEKEND BARS (2026-11-19): a venue candle for a slot the market was shut
for is not a bar.

The bar pass asks eToro for candles every ten minutes and reads no market
clock (market_data/bot_bars.py, refresh_bars_for_config). eToro answered a
1h and a 4h candle for every slot of a weekend, and the writer stored each
one as the venue's bar: a commodity Orc woke on W2 ("a 4h bar closed") every
four hours all weekend, each candle re-dated the venue mark to "now", and the
ATR the entry stops and sizes are read from (bot_program/asset_engine/
risk_levels.atr_for) took the weekend's candles for traded ones until the
traded bars after the reopen had pushed them out of its window.

Now a candle whose WHOLE span holds no open time, inside a shut of 24 hours
or more, is dropped before the write (market_data.shut_bars
.holds_no_open_time): a currency pair on eToro's own week (Friday 17:00 to
Sunday 17:00 New York), a commodity on its instrument's market clock. What
still trades is written as before: the Friday hour eToro trades after the
FOREX row's 21:00 UTC close in winter, the bar that holds the reopen, the
CME daily break (a shut shorter than a day), crypto and stocks. An answer
made of nothing else is "not now": it writes, stamps and mutes nothing.

Money, per case. Where the weekend candles were flat, the ATR at the reopen
rises back to the traded bars' value: stops wider, sizes smaller than with
them. Where they moved, it returns to the traded bars' value too, which is
lower than with wide weekend candles (stops tighter, sizes larger) and
higher than with narrow ones.

Fakes only (an eToro candle endpoint, a keyless feed), sqlite, no network.
Every price here is invented.

Run with:  python manage.py test tests.test_weekend_bars
"""
import math
from collections import namedtuple
from contextlib import ExitStack
from datetime import datetime, time, timedelta, timezone as dt_tz
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

UTC = dt_tz.utc
H = timedelta(hours=1)
M = timedelta(minutes=1)
SPAN = {"1h": H, "4h": 4 * H}

NEW_YORK = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")

#: The weekend shut each kind of market keeps, written here from the venues'
#: published hours and NOT read from the platform's clock (core.
#: exchange_status), so the fakes below never share a mistake with the code
#: under test: (zone, Friday close, Sunday reopen). "fx" is eToro's FX week,
#: "cme" Globex, which eToro's regular metals and energy keep.
WEEKEND = {"fx": (NEW_YORK, time(17, 0), time(17, 0)),
           "cme": (CHICAGO, time(16, 0), time(17, 0))}

#: symbol -> (class, exchange, weekend kind, invented base, invented 4h range)
SYMBOLS = {
    "XAUUSD": ("commodity", "COMEX", "cme", 2000.0, 6.0),
    "EURUSD": ("forex", "FOREX", "fx", 1.1000, 0.0012),
    "BTCUSD": ("crypto", "CRYPTO", None, 50000.0, 300.0),
    "AAPL": ("stock", "NASDAQ", None, 150.0, 1.0),
}

#: A moving weekend candle's range, as a multiple of the week's.
MOVING = {"wide": 3.0, "narrow": 0.25}

HISTORY_FROM = datetime(2026, 10, 26, tzinfo=UTC)      # a Monday
HISTORY_TO = datetime(2026, 11, 16, 8, tzinfo=UTC)     # the Monday after

FRI_21 = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)     # winter: eToro's FX
FRI_22 = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)     # week and Globex
SAT_00 = datetime(2026, 11, 14, 0, 0, tzinfo=UTC)      # shut at 22:00 UTC
SAT_11 = datetime(2026, 11, 14, 11, 0, tzinfo=UTC)
SAT_12 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
SAT_16 = datetime(2026, 11, 14, 16, 0, tzinfo=UTC)
SUN_0930 = datetime(2026, 11, 15, 9, 30, tzinfo=UTC)
SUN_16 = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)
SUN_20 = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)     # holds both reopens:
SUN_2315 = datetime(2026, 11, 15, 23, 15, tzinfo=UTC)  # FX 22:00, CME 23:00
TUE_22 = datetime(2026, 11, 10, 22, 0, tzinfo=UTC)     # the CME daily break

Candle = namedtuple("Candle", "open o h l c v")


def _r(x):
    return round(x, 6)


def _weekend_shut(kind, start, end):
    """True when [start, end) lies inside the weekend shut of `kind`
    (WEEKEND); never for a market with none (crypto, the stock fixture)."""
    if kind not in WEEKEND:
        return False
    zone, close_at, open_at = WEEKEND[kind]
    local = start.astimezone(zone)
    friday = local.date() - timedelta(days=(local.weekday() - 4) % 7)
    shut = datetime.combine(friday, close_at, tzinfo=zone)
    if shut > start:
        friday -= timedelta(days=7)
        shut = datetime.combine(friday, close_at, tzinfo=zone)
    reopen = datetime.combine(friday + timedelta(days=2), open_at, tzinfo=zone)
    return shut <= start and end <= reopen


def _candles(symbol, interval, weekend=None):
    """eToro's candles of (symbol, interval), HISTORY_FROM to HISTORY_TO. The
    slots the market traded carry one deterministic wave, the same whatever
    `weekend` says, each opening at the previous TRADED close. The slots it
    was shut for (_weekend_shut) carry what `weekend` says eToro answers:
      None      nothing: a venue that answers traded slots only;
      "flat"    Friday's close repeated (open = high = low = close, no volume);
      "wide"    a print that moves, its range MOVING["wide"] times the week's;
      "narrow"  one that moves, its range MOVING["narrow"] times the week's.
    A moving weekend drifts away from Friday's close."""
    _cls, _exch, kind, base, rng = SYMBOLS[symbol]
    if interval == "1h":
        rng = rng / 2
    span = SPAN[interval]
    out, last, wk, i, t = [], None, None, 0, HISTORY_FROM
    while t < HISTORY_TO:
        if not _weekend_shut(kind, t, t + span):
            c = _r(base + 2 * rng * math.sin(i / 5.0))
            o = c if last is None else last
            out.append(Candle(t, o, _r(max(o, c) + rng / 2),
                              _r(min(o, c) - rng / 2), c, 100))
            last, wk = c, None
        elif weekend and last is not None:
            if weekend == "flat":
                out.append(Candle(t, last, last, last, last, 0))
            else:
                wk = last if wk is None else wk
                mult = MOVING[weekend]
                c = _r(wk + 0.4 * mult * rng)
                out.append(Candle(t, wk, _r(max(wk, c) + mult * rng / 2),
                                  _r(min(wk, c) - mult * rng / 2), c, 7))
                wk = c
        t += span
        i += 1
    return out


class EtoroTrader:
    """eToro's candle endpoint as the adapter's klines answers it: Binance-
    shaped rows, oldest first, the newest `limit` whose open is at or before
    the pass's clock `t`. Named like the adapter, so the writer tags its bars
    "etoro" (bot_bars._source_tag) and the venue mark reads its carrier off
    the class (capabilities.adapter_key)."""

    wire_reads = 0

    def __init__(self, weekend=None, symbols=("XAUUSD", "EURUSD")):
        self.t = None
        self.series = {(s, iv): _candles(s, iv, weekend)
                       for s in symbols for iv in SPAN}
        self.answered = {}

    def candle(self, symbol, interval, at):
        return next(c for c in self.series[(symbol, interval)]
                    if c.open == at)

    def flatten(self, symbol, interval, at):
        """The candle at `at` made flat at its open (a slot nothing printed
        in, eToro still answering a candle for it)."""
        rows = self.series[(symbol, interval)]
        for n, c in enumerate(rows):
            if c.open == at:
                rows[n] = Candle(at, c.o, c.o, c.o, c.o, 0)

    def klines(self, symbol, interval="15m", limit=200):
        span_ms = int(SPAN[interval].total_seconds() * 1000)
        have = [c for c in self.series.get((symbol, interval), ())
                if c.open <= self.t][-int(limit):]
        self.answered[(symbol, interval)] = have
        out = []
        for c in have:
            ms = int(c.open.timestamp() * 1000)
            out.append([ms, str(c.o), str(c.h), str(c.l), str(c.c), str(c.v),
                        ms + span_ms, "0", 0, "0", "0", "0"])
        return out


class YFinanceFeed:
    """The keyless fallback, named like the real one (its tag ends
    "_public"): the traded slots only, as Yahoo's resampled frames hold."""

    _sv_public_feed = True

    def __init__(self, t):
        self.t = t
        self.asked = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.asked.append((symbol, interval))
        span_ms = int(SPAN[interval].total_seconds() * 1000)
        have = [c for c in _candles(symbol, interval) if c.open <= self.t]
        return [[int(c.open.timestamp() * 1000), str(c.o), str(c.h),
                 str(c.l), str(c.c), "0",
                 int(c.open.timestamp() * 1000) + span_ms]
                for c in have[-int(limit):]]


_MISSING = object()


def _drop_on(test):
    """The writer's switch for shut candles (bot_bars.DROP_SHUT_CANDLES), on
    for this test whatever the suite's default."""
    from market_data import bot_bars
    was = getattr(bot_bars, "DROP_SHUT_CANDLES", _MISSING)
    bot_bars.DROP_SHUT_CANDLES = True

    def back():
        if was is _MISSING:
            if hasattr(bot_bars, "DROP_SHUT_CANDLES"):
                del bot_bars.DROP_SHUT_CANDLES
        else:
            bot_bars.DROP_SHUT_CANDLES = was
    test.addCleanup(back)


def _rows(symbol, interval=None, source=None):
    from market_data.models import PriceData
    qs = PriceData.objects.filter(instrument__symbol=symbol)
    if interval:
        qs = qs.filter(timeframe=interval)
    if source:
        qs = qs.filter(source=source)
    return list(qs.order_by("timeframe", "timestamp"))


def _when(s):
    return datetime.fromisoformat(str(s))


class _Writer(TestCase):
    """The REAL bar writer (bot_bars.refresh_bars_for_config) on the fake
    eToro, its own clock pinned at each pass (it reads datetime.now for the
    window it asks and for staleness)."""

    def setUp(self):
        from instruments.models import Instrument
        cache.clear()
        self.addCleanup(cache.clear)
        _drop_on(self)
        self.user = get_user_model().objects.create_user("wkbars", password="x")
        for sym, (cls, exch, *_rest) in SYMBOLS.items():
            Instrument.objects.update_or_create(
                symbol=sym, defaults={"name": sym, "asset_class": cls,
                                      "exchange": exch})
        from tests.orcs.helpers import _manual_config
        self.manual = _manual_config(self.user, asset_class="commodity")

    def pass_at(self, venue, t, symbols, *, intervals=("4h", "1h"),
                limit=200, stamp_marks=False):
        from market_data import bot_bars
        venue.t = t
        held = SimpleNamespace(id=self.manual.id, user=self.user, mode="live",
                               asset_class=SYMBOLS[symbols[0]][0],
                               symbols=list(symbols))
        window, stale = bot_bars._etoro_window, bot_bars._venue_window_is_stale
        with ExitStack() as st:
            st.enter_context(patch("django.utils.timezone.now",
                                   return_value=t))
            for name, value in (("_client_for", venue),
                                ("_etoro_world", "live"),
                                ("_etoro_refusing", ""),
                                ("_public_market_data_client",
                                 YFinanceFeed(t))):
                st.enter_context(patch.object(bot_bars, name,
                                              return_value=value))
            st.enter_context(patch.object(bot_bars, "_candle_sleep",
                                          lambda s: None))
            st.enter_context(patch.object(
                bot_bars, "_etoro_window",
                lambda inst, iv, src, lim, now=None:
                    window(inst, iv, src, lim, now=t)))
            st.enter_context(patch.object(
                bot_bars, "_venue_window_is_stale",
                lambda inst, iv, rows, now=None: stale(inst, iv, rows, now=t)))
            return bot_bars.refresh_bars_for_config(
                held, intervals=intervals, limit=limit,
                pass_state=bot_bars._CandlePass(), cut=False,
                stamp_marks=stamp_marks)

    def held_row(self, symbol="XAUUSD"):
        """An open REAL row eToro carries: the candle stamp's target."""
        from tests.orcs.helpers import _manual_row
        return _manual_row(self.manual, symbol=symbol, cls=SYMBOLS[symbol][0],
                           entry="2000", stop="1980", target="2050",
                           paper=False, meta={"broker": "etoro"})

    def assertNoShutRow(self, symbol):
        kind = SYMBOLS[symbol][2]
        for r in _rows(symbol, source="etoro"):
            span = SPAN[r.timeframe]
            self.assertFalse(
                _weekend_shut(kind, r.timestamp, r.timestamp + span),
                f"{symbol} {r.timeframe} {r.timestamp:%a %d %H:%M} is a "
                f"stored eToro bar whose whole span the market was shut for")


# ── the predicate ────────────────────────────────────────────────────────

def _inst(cls, exchange="", symbol="X"):
    return SimpleNamespace(asset_class=cls, exchange=exchange, symbol=symbol)


def _at(*a):
    return datetime(*a, tzinfo=UTC)


class TheShutPredicateTests(SimpleTestCase):
    """holds_no_open_time(instrument, timeframe, bar_open_utc): True when the
    bar's whole span [open, open + timeframe) holds no open time and lies
    inside one shut of 24 hours or more. The instants are worked by hand."""

    def _is(self, inst, tf, at, want):
        from market_data.shut_bars import holds_no_open_time
        self.assertIs(holds_no_open_time(inst, tf, at), want,
                      f"{inst.asset_class} {inst.exchange!r} {tf} "
                      f"{at:%a %d %b %Y %H:%M} UTC")

    def test_forex_winter_week_is_etoros_new_york_week(self):
        """New York on EST: eToro's week shuts at Friday 22:00 UTC and
        reopens at Sunday 22:00 UTC; the FOREX row's 21:00 UTC is not it."""
        fx = _inst("forex", "FOREX", "EURUSD")
        for tf, at, want in (
                ("1h", _at(2026, 11, 13, 20), False),
                ("1h", _at(2026, 11, 13, 21), False),   # eToro still trades
                ("1h", _at(2026, 11, 13, 22), True),
                ("4h", _at(2026, 11, 13, 20), False),   # holds 20:00-22:00
                ("4h", _at(2026, 11, 14, 0), True),
                ("4h", _at(2026, 11, 14, 12), True),
                ("4h", _at(2026, 11, 15, 16), True),
                ("1h", _at(2026, 11, 15, 21), True),
                ("1h", _at(2026, 11, 15, 22), False),   # the reopen
                ("4h", _at(2026, 11, 15, 20), False)):  # holds the reopen
            self._is(fx, tf, at, want)

    def test_forex_summer_week(self):
        """New York on EDT: Friday 21:00 to Sunday 21:00 UTC."""
        fx = _inst("forex", "FOREX", "EURUSD")
        for tf, at, want in (
                ("1h", _at(2026, 7, 10, 20), False),
                ("1h", _at(2026, 7, 10, 21), True),
                ("4h", _at(2026, 7, 10, 20), False),    # holds 20:00-21:00
                ("4h", _at(2026, 7, 11, 8), True),
                ("4h", _at(2026, 7, 12, 16), True),
                ("1h", _at(2026, 7, 12, 20), True),
                ("1h", _at(2026, 7, 12, 21), False),
                ("4h", _at(2026, 7, 12, 20), False)):
            self._is(fx, tf, at, want)

    def test_us_and_eu_dst_mismatch_weeks_follow_new_york(self):
        """In the weeks one side of the Atlantic has changed its clocks and
        the other has not, the week keeps New York's hour, never London's:
        March 9-27 2026 (New York on EDT, Europe still on winter time) and
        October 26-30 2026 (Europe back on winter time, New York not yet).
        The two weekends New York itself changes are a 47 h and a 49 h
        shut."""
        fx = _inst("forex", "FOREX", "EURUSD")
        for tf, at, want in (
                # Mar 6-8: EST at Friday's close, EDT at Sunday's reopen
                ("1h", _at(2026, 3, 6, 21), False),
                ("1h", _at(2026, 3, 6, 22), True),
                ("1h", _at(2026, 3, 8, 20), True),
                ("1h", _at(2026, 3, 8, 21), False),
                # Mar 13-15: New York on EDT, London on GMT
                ("1h", _at(2026, 3, 13, 20), False),
                ("1h", _at(2026, 3, 13, 21), True),
                ("1h", _at(2026, 3, 15, 20), True),
                ("1h", _at(2026, 3, 15, 21), False),
                # Oct 30 - Nov 1: EDT at Friday's close, EST at the reopen
                ("1h", _at(2026, 10, 30, 20), False),
                ("1h", _at(2026, 10, 30, 21), True),
                ("1h", _at(2026, 11, 1, 21), True),
                ("1h", _at(2026, 11, 1, 22), False),
                ("4h", _at(2026, 11, 1, 20), False)):
            self._is(fx, tf, at, want)

    def test_the_fx_week_is_forex_market_open_at_every_quarter_hour(self):
        """The same week ForexBot.forex_market_open keeps (the rule etoro_
        rates.shut_max_age reads), at every quarter hour of a winter, a
        summer and a mismatch week: a 15m bar holds no open time exactly
        when that week is shut at its open and at its last minute."""
        from bot_program.asset_engine.forex_bot import forex_market_open
        from market_data.shut_bars import holds_no_open_time
        fx = _inst("forex", "FOREX", "EURUSD")
        for monday in (_at(2026, 11, 9), _at(2026, 7, 6), _at(2026, 3, 9),
                       _at(2026, 10, 26)):
            t = monday
            while t < monday + timedelta(days=7):
                shut = (not forex_market_open(t)
                        and not forex_market_open(t + timedelta(minutes=14)))
                self.assertIs(holds_no_open_time(fx, "15m", t), shut, t)
                t += timedelta(minutes=15)

    def test_a_commodity_reads_its_exchange_clock(self):
        """Gold on COMEX keeps Globex (CME): shut from Friday 16:00 to Sunday
        17:00 Chicago, 22:00 to 23:00 UTC in winter; the daily 16:00-17:00
        break is a shut of one hour, never dropped."""
        gold = _inst("commodity", "COMEX", "XAUUSD")
        for tf, at, want in (
                ("1h", _at(2026, 11, 13, 21), False),
                ("1h", _at(2026, 11, 13, 22), True),
                ("4h", _at(2026, 11, 13, 20), False),
                ("4h", _at(2026, 11, 14, 12), True),
                ("1h", _at(2026, 11, 15, 22), True),
                ("1h", _at(2026, 11, 15, 23), False),
                ("4h", _at(2026, 11, 15, 20), False),
                ("1h", _at(2026, 11, 10, 22), False)):  # the daily break
            self._is(gold, tf, at, want)

    def test_an_unknown_exchange_falls_back_to_the_class_clock(self):
        """"" (/setup/) and "ETORO" (the legacy sync) name no table: the
        class's default clock, CME, answers exactly as COMEX does."""
        from market_data.shut_bars import holds_no_open_time
        comex = _inst("commodity", "COMEX", "XAUUSD")
        for exch in ("", "ETORO"):
            other = _inst("commodity", exch, "XAUUSD")
            t = _at(2026, 11, 9)
            while t < _at(2026, 11, 16, 6):
                for tf in ("1h", "4h"):
                    self.assertIs(holds_no_open_time(other, tf, t),
                                  holds_no_open_time(comex, tf, t),
                                  (exch, tf, t))
                t += H
            self._is(other, "4h", _at(2026, 11, 14, 12), True)
            self._is(other, "1h", _at(2026, 11, 10, 22), False)

    def test_every_class_it_does_not_cover_returns_false(self):
        """Crypto never shuts; eToro trades US shares and index CFDs outside
        their cash sessions; an unmodelled class has no hours to judge."""
        sat = _at(2026, 11, 14, 12)
        for cls, exch in (("crypto", "CRYPTO"), ("stock", "NYSE"),
                          ("stock", ""), ("etf", "NYSE"), ("index", ""),
                          ("cfd", ""), ("", ""), ("options", ""),
                          ("bond", "")):
            self._is(_inst(cls, exch), "4h", sat, False)
            self._is(_inst(cls, exch), "1h", sat, False)

    def test_what_cannot_be_judged_is_kept(self):
        from market_data.shut_bars import holds_no_open_time
        fx = _inst("forex", "FOREX", "EURUSD")
        sat = _at(2026, 11, 14, 12)
        self.assertFalse(holds_no_open_time(fx, "3h", sat))
        self.assertFalse(holds_no_open_time(fx, "", sat))
        self.assertFalse(holds_no_open_time(fx, "4h", None))
        self.assertFalse(holds_no_open_time(None, "4h", sat))
        self.assertTrue(holds_no_open_time(fx, "4h", sat.replace(tzinfo=None)))
        self.assertTrue(holds_no_open_time(_inst(" Forex "), "4h", sat))


# ── the writer ───────────────────────────────────────────────────────────

class TheWriterDropsShutCandlesTests(_Writer):

    def _weekend_pass(self, weekend):
        """One pass at Sunday 23:15 UTC, after both reopens, its windows
        reaching back over the whole weekend (and the ones before it)."""
        venue = EtoroTrader(weekend=weekend)
        self.pass_at(venue, SUN_2315, ("XAUUSD", "EURUSD"))
        return venue

    def test_no_stored_etoro_bar_lies_wholly_inside_a_weekend(self):
        for weekend in ("flat", "wide", "narrow"):
            with self.subTest(weekend=weekend):
                from market_data.models import PriceData
                PriceData.objects.all().delete()
                venue = self._weekend_pass(weekend)
                for sym in ("XAUUSD", "EURUSD"):
                    kind = SYMBOLS[sym][2]
                    self.assertNoShutRow(sym)
                    for iv in SPAN:
                        answered = venue.answered[(sym, iv)]
                        traded = {c.open for c in answered if not
                                  _weekend_shut(kind, c.open,
                                                c.open + SPAN[iv])}
                        self.assertTrue(len(traded) < len(answered),
                                        "the fixture answered no weekend")
                        self.assertEqual(
                            {r.timestamp for r in _rows(sym, iv)}, traded,
                            f"{sym} {iv}: every traded candle, nothing else")

    def test_the_friday_fx_hour_after_the_forex_row_closes_is_kept(self):
        """Winter: the FOREX row says shut from 21:00 UTC, eToro's week runs
        to 22:00 UTC. The 21:00-22:00 bar traded."""
        for weekend in ("flat", "wide"):
            with self.subTest(weekend=weekend):
                venue = self._weekend_pass(weekend)
                kept = _rows("EURUSD", "1h")
                stamps = {r.timestamp for r in kept}
                self.assertIn(FRI_21, stamps)
                self.assertNotIn(FRI_22, stamps)
                bar = next(r for r in kept if r.timestamp == FRI_21)
                self.assertEqual(
                    bar.close,
                    Decimal(str(venue.candle("EURUSD", "1h", FRI_21).c)))

    def test_the_sunday_bar_that_holds_the_reopen_is_kept(self):
        """The Sunday 20:00 UTC 4h bar holds the FX reopen (22:00) and the
        Globex reopen (23:00): it traded, for gold and for EURUSD."""
        for weekend in ("flat", "wide"):
            with self.subTest(weekend=weekend):
                self._weekend_pass(weekend)
                for sym in ("XAUUSD", "EURUSD"):
                    stamps = {r.timestamp for r in _rows(sym, "4h")}
                    self.assertIn(SUN_20, stamps, sym)
                    self.assertNotIn(SUN_16, stamps, sym)

    def test_the_cme_daily_break_bar_is_kept(self):
        """A weekday's 22:00-23:00 UTC (16:00-17:00 Chicago) is Globex's
        daily break: a shut of one hour, shorter than a day. Its candle,
        flat or not, is written as before."""
        venue = EtoroTrader(weekend="flat")
        venue.flatten("XAUUSD", "1h", TUE_22)
        self.pass_at(venue, datetime(2026, 11, 11, 0, 15, tzinfo=UTC),
                     ("XAUUSD",), intervals=("1h",))
        bar = next((r for r in _rows("XAUUSD", "1h")
                    if r.timestamp == TUE_22), None)
        self.assertIsNotNone(bar)
        self.assertEqual(bar.high, bar.low)
        self.assertEqual(bar.source, "etoro")

    def test_crypto_and_stocks_are_unchanged(self):
        """Every candle eToro answers for BTCUSD and AAPL, the weekend's
        included, is stored exactly as it was before."""
        venue = EtoroTrader(weekend="wide", symbols=("BTCUSD", "AAPL"))
        self.pass_at(venue, SUN_2315, ("BTCUSD", "AAPL"))
        for sym in ("BTCUSD", "AAPL"):
            for iv in SPAN:
                answered = venue.answered[(sym, iv)]
                self.assertTrue(any(c.open.weekday() == 5 for c in answered))
                stored = {r.timestamp: r for r in _rows(sym, iv)}
                self.assertEqual(set(stored), {c.open for c in answered})
                for c in answered:
                    r = stored[c.open]
                    self.assertEqual(
                        (r.open, r.high, r.low, r.close, r.source),
                        (Decimal(str(c.o)), Decimal(str(c.h)),
                         Decimal(str(c.l)), Decimal(str(c.c)), "etoro"))

    def test_an_answer_of_weekend_candles_only_writes_stamps_and_mutes_nothing(
            self):
        """The first weekend after the deploy: the weekend candles stored
        before it are still in the table, so the window eToro is asked for
        starts at one of them and its whole answer is weekend candles. It is
        "not now": nothing is written, the venue mark and the venue's answer
        note stay Friday's, and eToro is not muted (a mute would last six
        hours, past Sunday's reopen)."""
        from bot_program import venue_mark
        from market_data import bot_bars
        from market_data.models import PriceData
        venue = EtoroTrader(weekend="wide", symbols=("XAUUSD",))
        row = self.held_row()
        fri = FRI_21 + M
        self.pass_at(venue, fri, ("XAUUSD",), stamp_marks=True)
        row.refresh_from_db()
        mark = dict(row.metadata["venue_mark"])
        self.assertEqual(_when(mark["at"]), fri)
        notes = {iv: bot_bars.last_venue_answer("etoro", "XAUUSD", iv)
                 for iv in SPAN}
        self.assertTrue(all(notes.values()))
        # what the old writer stored from the weekend, up to Saturday 12:00
        from instruments.models import Instrument
        inst = Instrument.objects.get(symbol="XAUUSD")
        for iv in SPAN:
            for c in venue.series[("XAUUSD", iv)]:
                if FRI_22 <= c.open <= SAT_12 and _weekend_shut(
                        "cme", c.open, c.open + SPAN[iv]):
                    PriceData.objects.create(
                        instrument=inst, timeframe=iv, timestamp=c.open,
                        open=Decimal(str(c.o)), high=Decimal(str(c.h)),
                        low=Decimal(str(c.l)), close=Decimal(str(c.c)),
                        volume=c.v, source="etoro")
        before =[(r.timeframe, r.timestamp, r.close, r.source)
                  for r in _rows("XAUUSD")]

        sat = SAT_16 + M
        self.pass_at(venue, sat, ("XAUUSD",), stamp_marks=True)
        for iv in SPAN:
            answered = venue.answered[("XAUUSD", iv)]
            self.assertTrue(answered)
            self.assertTrue(all(_weekend_shut("cme", c.open, c.open + SPAN[iv])
                                for c in answered),
                            f"{iv}: the fixture's answer is weekend only")
        self.assertEqual([(r.timeframe, r.timestamp, r.close, r.source)
                          for r in _rows("XAUUSD")], before)
        row.refresh_from_db()
        self.assertEqual(row.metadata["venue_mark"], mark)
        self.assertEqual(venue_mark.last(row, now=sat)["at"], fri)
        for iv in SPAN:
            self.assertFalse(bot_bars._venue_is_mute("etoro", "XAUUSD", iv),
                             iv)
            self.assertEqual(
                bot_bars.last_venue_answer("etoro", "XAUUSD", iv)["newest_ms"],
                notes[iv]["newest_ms"], iv)

    def test_a_moving_weekend_candle_is_dropped_like_a_flat_one(self):
        """eToro's weekend candles for gold MOVE (high above low, the close
        drifting away from Friday's). Moving or flat, none is stored, and
        none stamps the venue mark: the Saturday pass leaves it on the last
        traded candle's close, dated no later than that candle's end."""
        from market_data.models import PriceData
        from bot_program.models import AssetBotTrade
        for weekend in ("wide", "flat"):
            with self.subTest(weekend=weekend):
                PriceData.objects.all().delete()
                AssetBotTrade.objects.all().delete()
                venue = EtoroTrader(weekend=weekend, symbols=("XAUUSD",))
                sat12 = venue.candle("XAUUSD", "4h", SAT_12)
                fri20 = venue.candle("XAUUSD", "4h", SAT_00 - 4 * H)
                if weekend == "wide":
                    self.assertGreater(sat12.h, sat12.l)
                    self.assertNotEqual(sat12.c, fri20.c)
                row = self.held_row()
                self.pass_at(venue, FRI_21 + M, ("XAUUSD",), stamp_marks=True)
                self.pass_at(venue, SAT_12 + M, ("XAUUSD",), stamp_marks=True)
                self.assertNoShutRow("XAUUSD")
                self.assertFalse(PriceData.objects.filter(
                    instrument__symbol="XAUUSD",
                    timestamp__gte=FRI_22, timestamp__lt=SUN_20).exists())
                row.refresh_from_db()
                vm = row.metadata["venue_mark"]
                self.assertLessEqual(_when(vm["at"]), SAT_00)
                self.assertEqual(Decimal(str(vm["price"])),
                                 Decimal(str(fri20.c)))
                if weekend == "wide":
                    self.assertNotEqual(Decimal(str(vm["price"])),
                                        Decimal(str(sat12.c)))


# ── money: the ATR at the reopen ─────────────────────────────────────────

Measure = namedtuple("Measure", "atr stop qty levels")


class TheReopenATRTests(_Writer):
    """V2: the first entry after the reopen sets its stop and its size from
    ATR(4h) (risk_levels.stop_and_target, sizing.size_position), the bots'
    and the TAKE TRADE ticket's when a signal carries no levels. At Sunday
    23:15 UTC that ATR must be the traded week's, whatever eToro answered
    for the weekend."""

    def _measure(self, symbol):
        from bot_program.asset_engine import risk_levels, sizing
        cls = SYMBOLS[symbol][0]
        cfg = SimpleNamespace(asset_class=cls, extras={}, stop_loss_pct=1.0,
                              take_profit_pct=2.0, capital=10000.0)
        price = float(_rows(symbol, "4h")[-1].close)
        atr = risk_levels.atr_for(symbol, "4h")
        stop, _target, meta = risk_levels.stop_and_target(cfg, symbol, price,
                                                          "BUY")
        size = sizing.size_position(cfg, asset_class=cls, entry=price,
                                    stop=stop, direction="BUY")
        return Measure(atr, stop, size["qty"], meta.get("levels_source"))

    def _reopen(self, symbol, weekend):
        from indicators.models import TechnicalIndicator
        from market_data.models import PriceData
        PriceData.objects.filter(instrument__symbol=symbol).delete()
        TechnicalIndicator.objects.filter(instrument__symbol=symbol).delete()
        venue = EtoroTrader(weekend=weekend, symbols=(symbol,))
        self.pass_at(venue, SUN_2315, (symbol,), intervals=("4h",))
        return self._measure(symbol), venue

    def test_the_weekend_candles_would_move_the_atr(self):
        """The fixture, and the money direction per case: stored, flat
        weekend candles deflate ATR(4h) at the reopen; wide moving ones
        inflate it; narrow moving ones deflate it. So, the weekend candles
        out, a flat weekend's stops come back wider and its sizes smaller,
        a wide one's tighter and larger, a narrow one's wider and smaller."""
        from indicators.calculator import calculate_atr
        import pandas as pd

        def atr_of(candles):
            have = [c for c in candles if c.open <= SUN_2315][-56:]
            df = pd.DataFrame([{"high": c.h, "low": c.l, "close": c.c}
                               for c in have])
            return float(calculate_atr(df["high"], df["low"],
                                       df["close"]).iloc[-1])
        for symbol in ("XAUUSD", "EURUSD"):
            traded = atr_of(_candles(symbol, "4h"))
            flat = atr_of(_candles(symbol, "4h", "flat"))
            wide = atr_of(_candles(symbol, "4h", "wide"))
            narrow = atr_of(_candles(symbol, "4h", "narrow"))
            self.assertLess(flat, 0.5 * traded, symbol)
            self.assertGreater(wide, 1.5 * traded, symbol)
            self.assertLess(narrow, traded, symbol)

    def test_the_reopen_atr_stop_and_size_are_the_traded_weeks(self):
        for symbol in ("XAUUSD", "EURUSD"):
            traded, _v = self._reopen(symbol, None)
            self.assertEqual(traded.levels, "atr", symbol)
            for weekend in ("flat", "wide", "narrow"):
                with self.subTest(symbol=symbol, weekend=weekend):
                    got, venue = self._reopen(symbol, weekend)
                    self.assertTrue(any(
                        _weekend_shut(SYMBOLS[symbol][2], c.open,
                                      c.open + SPAN["4h"])
                        for c in venue.answered[(symbol, "4h")]))
                    self.assertAlmostEqual(got.atr, traded.atr, places=9)
                    self.assertAlmostEqual(got.stop, traded.stop, places=9)
                    self.assertAlmostEqual(got.qty, traded.qty, places=6)
                    self.assertEqual(got.levels, "atr")

    def test_the_stored_indicator_reads_the_same_atr(self):
        """The indicator task's stored atr_14, which atr_for reads first,
        is the traded week's too."""
        from indicators.tasks import recalculate_for_instruments
        from instruments.models import Instrument
        traded, _v = self._reopen("XAUUSD", None)
        got, _v = self._reopen("XAUUSD", "flat")
        with patch("django.utils.timezone.now", return_value=SUN_2315):
            recalculate_for_instruments(
                [Instrument.objects.get(symbol="XAUUSD")], timeframes=("4h",))
        from bot_program.asset_engine import risk_levels
        self.assertAlmostEqual(risk_levels.atr_for("XAUUSD", "4h"),
                               traded.atr, places=6)
        self.assertAlmostEqual(got.atr, traded.atr, places=9)


# ── the Orcs: his window at production cadence ───────────────────────────

class TheOperatorsWindowTests(_Writer):
    """V1: two manual commodity Orcs on gold, born Friday 21:02 UTC; a bar
    pass hourly to Saturday 11:00, then at the production cadence (a bar
    pass every 10 minutes at :01, the manage tick every 5 minutes at :03)
    to Sunday 09:30, eToro answering a MOVING candle for every weekend slot.
    Before, W2 ("a 4h bar closed") woke both at Sat 12:03, 16:03, 20:03,
    Sun 00:03, 04:03 and 08:03. Now no weekend bar is stored, so no bar
    closes and no W2 fires in that window; the Friday bar's own close still
    wakes them once."""

    def setUp(self):
        super().setUp()
        from tests.orcs.helpers import _on, _switch
        _switch("aragorn")
        _on()

    def _tick(self, row, orc, t):
        from bot_program.orcs.observe import after_care
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.manual,
                              _last_ticks={})
        row._care_tick = {"now": t}
        with ExitStack() as st:
            st.enter_context(patch("django.utils.timezone.now",
                                   return_value=t))
            st.enter_context(self.captureOnCommitCallbacks(execute=True))
            after_care(bot, row, "2000.5", "")
        orc.refresh_from_db()

    def _w2(self, orc):
        from bot_program.orcs.models import OrcWake
        return [(w.created_at, r.get("key"))
                for w in OrcWake.objects.filter(orc=orc).order_by("id")
                for r in (w.reasons or [])
                if isinstance(r, dict) and r.get("code") == "W2"]

    def test_no_w2_in_his_window_when_etoro_answers_weekend_candles(self):
        from tests.orcs.helpers import _manual_row, born
        venue = EtoroTrader(weekend="wide", symbols=("XAUUSD",))
        self.pass_at(venue, FRI_21 + M, ("XAUUSD",))
        rows, orcs = [], []
        for _ in range(2):
            r = _manual_row(self.manual, symbol="XAUUSD", cls="commodity",
                            entry="2000", stop="1980", target="2050")
            orcs.append(born(self, r, at=FRI_21 + 2 * M))
            r.refresh_from_db()
            rows.append(r)
        t = FRI_21
        while t < SAT_11:                       # warm-up, hourly
            self.pass_at(venue, t + M, ("XAUUSD",))
            for r, o in zip(rows, orcs):
                self._tick(r, o, t + 3 * M)
            t += H
        t = SAT_11
        while t <= SUN_0930:                    # his window
            if t.minute % 10 == 0:
                self.pass_at(venue, t + M, ("XAUUSD",))
            for r, o in zip(rows, orcs):
                self._tick(r, o, t + 3 * M)
            t += 5 * M
        for o in orcs:
            w2 = self._w2(o)
            self.assertTrue([k for at, k in w2 if at < SAT_11],
                            "the harness saw no W2 at all: the Friday bar's "
                            "close should wake the Orc")
            self.assertEqual(
                [f"{at:%a %H:%M} {k}" for at, k in w2 if at >= SAT_11], [])
        self.assertNoShutRow("XAUUSD")
