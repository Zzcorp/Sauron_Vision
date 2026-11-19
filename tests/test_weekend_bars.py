"""WEEKEND BARS (2026-11-19): a venue candle for a slot the market was shut
for is not a bar; eToro's all-week instruments are never shut.

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
CME daily break (a shut shorter than a day), crypto, stocks and indices. An
answer made of nothing else is "not now": it writes, stamps and mutes
nothing.

eToro's ALL-WEEK instruments are never shut (shut_bars.ALL_WEEK_ETORO_IDS:
GOLD, OIL, SILVER, NATGAS, SPX500 and NSDQ100, which eToro's market-hours
page lists as trading 24/7). Their weekend candles are prices eToro traded,
moving or not, and they are written, noted and stamped exactly as before
the rule. Gold's and silver's are the cases here; copper (HGUSD) keeps
weekday hours at eToro and stands for the commodities whose weekend
candles go.

Money, per case. Where a weekday market's weekend candles were flat, the
ATR at the reopen rises back to the traded bars' value: stops wider, sizes
smaller than with them. Where they moved, it returns to the traded bars'
value too, which is lower than with wide weekend candles (stops tighter,
sizes larger) and higher than with narrow ones. An all-week instrument's
ATR reads its weekend market as it always did.

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
#: "cme" Globex, which eToro's weekday-only metals keep. An all-week
#: instrument's fixture uses it for the slots eToro's 24/7 market answers
#: while Globex is shut.
WEEKEND = {"fx": (NEW_YORK, time(17, 0), time(17, 0)),
           "cme": (CHICAGO, time(16, 0), time(17, 0))}

#: symbol -> (class, exchange, weekend kind, invented base, invented 4h range)
SYMBOLS = {
    "XAUUSD": ("commodity", "COMEX", "cme", 2000.0, 6.0),
    "XAGUSD": ("commodity", "COMEX", "cme", 25.0, 0.15),
    "HGUSD": ("commodity", "COMEX", "cme", 4.0, 0.02),
    "EURUSD": ("forex", "FOREX", "fx", 1.1000, 0.0012),
    "GBPUSD": ("forex", "FOREX", "fx", 1.3000, 0.0014),
    "BTCUSD": ("crypto", "CRYPTO", None, 50000.0, 300.0),
    "AAPL": ("stock", "NASDAQ", None, 150.0, 1.0),
    "SPX500": ("index", "CME", "cme", 5000.0, 12.0),
}

#: The symbols here whose eToro instrument trades all week, written from
#: eToro's own list (its market-hours page, about 2026-11-02: GOLD, SILVER
#: and the S&P 500 open 24/7), never read from shut_bars.
ALL_WEEK = frozenset({"XAUUSD", "XAGUSD", "SPX500"})

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


def _shut_bar(symbol, start, end):
    """The writer must drop `symbol`'s candle spanning [start, end): a
    currency pair or a commodity that keeps weekday hours at eToro, the
    span wholly inside its weekend shut. Never an all-week instrument's,
    never another class's."""
    cls, _exch, kind, *_rest = SYMBOLS[symbol]
    return (cls in ("forex", "commodity") and symbol not in ALL_WEEK
            and _weekend_shut(kind, start, end))


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


def _pinned(iid):
    """(label, platform symbol) of eToro's instrument `iid`: the symbol
    read from its pin (etoro_client.VENUE_ID_PINS: OIL is 17, NATGAS 22,
    COPPER.FUT 21, PALLADIUM.FUT 91), the label what a failure names."""
    from bot_program.engine.etoro_client import PINNED_SYMBOL
    return f"eToro id {iid}", PINNED_SYMBOL[iid]


def _named(*symbols):
    """(label, symbol) pairs for symbols written out here."""
    return tuple((s, s) for s in symbols)


def _prices(symbol):
    """An invented entry, stop and target around `symbol`'s base."""
    base = SYMBOLS[symbol][3]
    return {"entry": f"{base:.4f}", "stop": f"{base * 0.99:.4f}",
            "target": f"{base * 1.025:.4f}"}


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

    def held_row(self, symbol):
        """An open REAL row eToro carries: the candle stamp's target."""
        from tests.orcs.helpers import _manual_row
        return _manual_row(self.manual, symbol=symbol, cls=SYMBOLS[symbol][0],
                           paper=False, meta={"broker": "etoro"},
                           **_prices(symbol))

    def assertNoShutRow(self, symbol):
        for r in _rows(symbol, source="etoro"):
            span = SPAN[r.timeframe]
            self.assertFalse(
                _shut_bar(symbol, r.timestamp, r.timestamp + span),
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
        for sym in ("EURUSD", "GBPUSD"):
            fx = _inst("forex", "FOREX", sym)
            for tf, at, want in (
                    ("1h", _at(2026, 11, 13, 20), False),
                    ("1h", _at(2026, 11, 13, 21), False),   # eToro trades
                    ("1h", _at(2026, 11, 13, 22), True),
                    ("4h", _at(2026, 11, 13, 20), False),   # 20:00-22:00
                    ("4h", _at(2026, 11, 14, 0), True),
                    ("4h", _at(2026, 11, 14, 12), True),
                    ("4h", _at(2026, 11, 15, 16), True),
                    ("1h", _at(2026, 11, 15, 21), True),
                    ("1h", _at(2026, 11, 15, 22), False),   # the reopen
                    ("4h", _at(2026, 11, 15, 20), False)):  # holds it
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

    def test_a_weekday_commodity_reads_its_exchange_clock(self):
        """Copper on COMEX keeps Globex (CME) at eToro too: shut from Friday
        16:00 to Sunday 17:00 Chicago, 22:00 to 23:00 UTC in winter; the
        daily 16:00-17:00 break is a shut of one hour, never dropped."""
        copper = _inst("commodity", "COMEX", "HGUSD")
        for tf, at, want in (
                ("1h", _at(2026, 11, 13, 21), False),
                ("1h", _at(2026, 11, 13, 22), True),
                ("4h", _at(2026, 11, 13, 20), False),
                ("4h", _at(2026, 11, 14, 12), True),
                ("1h", _at(2026, 11, 15, 22), True),
                ("1h", _at(2026, 11, 15, 23), False),
                ("4h", _at(2026, 11, 15, 20), False),
                ("1h", _at(2026, 11, 10, 22), False)):  # the daily break
            self._is(copper, tf, at, want)

    def test_an_unknown_exchange_falls_back_to_the_class_clock(self):
        """"" (/setup/) and "ETORO" (the legacy sync) name no table: the
        class's default clock, CME, answers exactly as COMEX does."""
        from market_data.shut_bars import holds_no_open_time
        comex = _inst("commodity", "COMEX", "HGUSD")
        for exch in ("", "ETORO"):
            other = _inst("commodity", exch, "HGUSD")
            t = _at(2026, 11, 9)
            while t < _at(2026, 11, 16, 6):
                for tf in ("1h", "4h"):
                    self.assertIs(holds_no_open_time(other, tf, t),
                                  holds_no_open_time(comex, tf, t),
                                  (exch, tf, t))
                t += H
            self._is(other, "4h", _at(2026, 11, 14, 12), True)
            self._is(other, "1h", _at(2026, 11, 10, 22), False)

    def test_etoros_all_week_instruments_are_never_shut(self):
        """eToro trades GOLD (18), OIL (17), SILVER (19) and NATGAS (22) on
        Saturday and Sunday too (its market-hours page: 24/7, short breaks
        only). No bar of theirs is a shut bar, whatever exchange their row
        names and whatever that exchange's clock says; copper, on the same
        clock, is shut over the same slots."""
        from market_data.shut_bars import holds_no_open_time
        copper = _inst("commodity", "COMEX", "HGUSD")
        all_week = _named("XAUUSD", "XAGUSD") + (_pinned(17), _pinned(22))
        for monday in (_at(2026, 11, 9), _at(2026, 7, 6)):
            shut = 0
            t = monday + timedelta(days=4, hours=12)     # Friday noon
            while t < monday + timedelta(days=7, hours=6):
                for tf in ("1h", "4h"):
                    shut += holds_no_open_time(copper, tf, t)
                    for label, sym in all_week:
                        for exch in ("COMEX", "NYMEX", "", "ETORO"):
                            self.assertFalse(holds_no_open_time(
                                _inst("commodity", exch, sym), tf, t),
                                (label, exch, tf, t))
                t += H
            self.assertGreater(shut, 40, "the slots hold no weekend")

    def test_the_all_week_list_is_keyed_by_etoros_instrument_id(self):
        """eToro's list, by eToro's id: a platform symbol reaches it through
        its pin (etoro_client.VENUE_ID_PINS: XAUUSD is 18, GOLD) or, with no
        pin, as eToro spells it (SPX500 is 27); never through a name: the
        catalogue's own GOLD is the Barrick Gold stock, not eToro's 18."""
        from market_data.shut_bars import ALL_WEEK_ETORO_IDS, trades_all_week
        self.assertEqual(set(ALL_WEEK_ETORO_IDS), {17, 18, 19, 22, 27, 28})
        for label, sym in (_named("XAUUSD", "XAGUSD", "SPX500")
                           + (_pinned(17), _pinned(22))):
            self.assertTrue(trades_all_week(_inst("commodity", "", sym)),
                            label)
            self.assertTrue(trades_all_week(f" {sym.lower()} "), label)
        for label, sym in (_named("HGUSD", "EURUSD", "GBPUSD", "BTCUSD",
                                  "AAPL", "GOLD", "", None)
                           + (_pinned(21), _pinned(91))):
            self.assertFalse(trades_all_week(_inst("commodity", "", sym)),
                             label)

    def test_every_class_it_does_not_cover_returns_false(self):
        """Crypto never shuts; eToro trades US shares and index CFDs outside
        their cash sessions; an unmodelled class has no hours to judge."""
        sat = _at(2026, 11, 14, 12)
        for cls, exch, sym in (
                ("crypto", "CRYPTO", "X"), ("stock", "NYSE", "X"),
                ("stock", "", "X"), ("etf", "NYSE", "X"),
                ("index", "", "X"), ("index", "CME", "SPX500"),
                ("cfd", "", "X"), ("", "", "X"), ("options", "", "X"),
                ("bond", "", "X")):
            self._is(_inst(cls, exch, sym), "4h", sat, False)
            self._is(_inst(cls, exch, sym), "1h", sat, False)

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

WEEKDAY_MARKETS = ("HGUSD", "EURUSD", "GBPUSD")


class TheWriterDropsShutCandlesTests(_Writer):

    def _weekend_pass(self, weekend, symbols=WEEKDAY_MARKETS):
        """One pass at Sunday 23:15 UTC, after both reopens, its windows
        reaching back over the whole weekend (and the ones before it)."""
        venue = EtoroTrader(weekend=weekend, symbols=symbols)
        self.pass_at(venue, SUN_2315, symbols)
        return venue

    def test_no_stored_etoro_bar_of_a_weekday_market_lies_inside_a_weekend(
            self):
        for weekend in ("flat", "wide", "narrow"):
            with self.subTest(weekend=weekend):
                from market_data.models import PriceData
                PriceData.objects.all().delete()
                venue = self._weekend_pass(weekend)
                for sym in WEEKDAY_MARKETS:
                    self.assertNoShutRow(sym)
                    for iv in SPAN:
                        answered = venue.answered[(sym, iv)]
                        traded = {c.open for c in answered if not
                                  _shut_bar(sym, c.open, c.open + SPAN[iv])}
                        self.assertTrue(len(traded) < len(answered),
                                        "the fixture answered no weekend")
                        self.assertEqual(
                            {r.timestamp for r in _rows(sym, iv)}, traded,
                            f"{sym} {iv}: every traded candle, nothing else")

    def test_etoros_all_week_instruments_keep_every_weekend_candle(self):
        """Gold moving, silver flat or moving: every candle eToro answered,
        the weekend's included, is stored with eToro's own values, as the
        writer stored it before the rule."""
        from market_data.models import PriceData
        for sym, weekend in (("XAUUSD", "wide"), ("XAUUSD", "narrow"),
                             ("XAGUSD", "flat"), ("XAGUSD", "wide")):
            with self.subTest(symbol=sym, weekend=weekend):
                PriceData.objects.all().delete()
                venue = self._weekend_pass(weekend, symbols=(sym,))
                for iv in SPAN:
                    answered = venue.answered[(sym, iv)]
                    weekend_candles = [
                        c for c in answered
                        if _weekend_shut("cme", c.open, c.open + SPAN[iv])]
                    self.assertGreater(len(weekend_candles), 8, iv)
                    if weekend != "flat":
                        self.assertTrue(all(c.h > c.l
                                            for c in weekend_candles))
                    stored = {r.timestamp: r for r in _rows(sym, iv)}
                    self.assertEqual(set(stored), {c.open for c in answered})
                    for c in weekend_candles:
                        r = stored[c.open]
                        self.assertEqual(
                            (r.open, r.high, r.low, r.close, r.source),
                            (Decimal(str(c.o)), Decimal(str(c.h)),
                             Decimal(str(c.l)), Decimal(str(c.c)), "etoro"))

    def test_no_bar_of_an_all_week_instrument_is_offered_to_the_prune(self):
        """The prune of the rows stored before the rule deletes what the
        predicate calls a shut bar: no candle eToro answers for gold or
        silver, Saturday's and Sunday's included, ever is one; copper's
        weekend candles are."""
        from instruments.models import Instrument
        from market_data.shut_bars import holds_no_open_time
        venue = self._weekend_pass("wide", symbols=("XAUUSD", "XAGUSD",
                                                    "HGUSD"))
        for sym in ("XAUUSD", "XAGUSD", "HGUSD"):
            inst = Instrument.objects.get(symbol=sym)
            for iv in SPAN:
                shut = [c.open for c in venue.answered[(sym, iv)]
                        if holds_no_open_time(inst, iv, c.open)]
                if sym == "HGUSD":
                    self.assertGreater(len(shut), 8, iv)
                else:
                    self.assertEqual(shut, [], f"{sym} {iv}")

    def test_the_friday_fx_hour_after_the_forex_row_closes_is_kept(self):
        """Winter: the FOREX row says shut from 21:00 UTC, eToro's week runs
        to 22:00 UTC. The 21:00-22:00 bar traded."""
        for weekend in ("flat", "wide"):
            with self.subTest(weekend=weekend):
                venue = self._weekend_pass(weekend)
                for sym in ("EURUSD", "GBPUSD"):
                    kept = _rows(sym, "1h")
                    stamps = {r.timestamp for r in kept}
                    self.assertIn(FRI_21, stamps)
                    self.assertNotIn(FRI_22, stamps)
                    bar = next(r for r in kept if r.timestamp == FRI_21)
                    self.assertEqual(
                        bar.close,
                        Decimal(str(venue.candle(sym, "1h", FRI_21).c)))

    def test_the_sunday_bar_that_holds_the_reopen_is_kept(self):
        """The Sunday 20:00 UTC 4h bar holds the FX reopen (22:00) and the
        Globex reopen (23:00): it traded, for copper and for the pairs."""
        for weekend in ("flat", "wide"):
            with self.subTest(weekend=weekend):
                self._weekend_pass(weekend)
                for sym in WEEKDAY_MARKETS:
                    stamps = {r.timestamp for r in _rows(sym, "4h")}
                    self.assertIn(SUN_20, stamps, sym)
                    self.assertNotIn(SUN_16, stamps, sym)

    def test_the_cme_daily_break_bar_is_kept(self):
        """A weekday's 22:00-23:00 UTC (16:00-17:00 Chicago) is Globex's
        daily break: a shut of one hour, shorter than a day. Its candle,
        flat or not, is written as before."""
        venue = EtoroTrader(weekend="flat", symbols=("HGUSD",))
        venue.flatten("HGUSD", "1h", TUE_22)
        self.pass_at(venue, datetime(2026, 11, 11, 0, 15, tzinfo=UTC),
                     ("HGUSD",), intervals=("1h",))
        bar = next((r for r in _rows("HGUSD", "1h")
                    if r.timestamp == TUE_22), None)
        self.assertIsNotNone(bar)
        self.assertEqual(bar.high, bar.low)
        self.assertEqual(bar.source, "etoro")

    def test_crypto_stocks_and_indices_are_unchanged(self):
        """Every candle eToro answers for BTCUSD, AAPL and SPX500, the
        weekend's included, is stored exactly as it was before."""
        symbols = ("BTCUSD", "AAPL", "SPX500")
        venue = EtoroTrader(weekend="wide", symbols=symbols)
        self.pass_at(venue, SUN_2315, symbols)
        for sym in symbols:
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
        venue = EtoroTrader(weekend="wide", symbols=("HGUSD",))
        row = self.held_row("HGUSD")
        fri = FRI_21 + M
        self.pass_at(venue, fri, ("HGUSD",), stamp_marks=True)
        row.refresh_from_db()
        mark = dict(row.metadata["venue_mark"])
        self.assertEqual(_when(mark["at"]), fri)
        notes = {iv: bot_bars.last_venue_answer("etoro", "HGUSD", iv)
                 for iv in SPAN}
        self.assertTrue(all(notes.values()))
        # what the old writer stored from the weekend, up to Saturday 12:00
        from instruments.models import Instrument
        inst = Instrument.objects.get(symbol="HGUSD")
        for iv in SPAN:
            for c in venue.series[("HGUSD", iv)]:
                if FRI_22 <= c.open <= SAT_12 and _weekend_shut(
                        "cme", c.open, c.open + SPAN[iv]):
                    PriceData.objects.create(
                        instrument=inst, timeframe=iv, timestamp=c.open,
                        open=Decimal(str(c.o)), high=Decimal(str(c.h)),
                        low=Decimal(str(c.l)), close=Decimal(str(c.c)),
                        volume=c.v, source="etoro")
        before = [(r.timeframe, r.timestamp, r.close, r.source)
                  for r in _rows("HGUSD")]

        sat = SAT_16 + M
        self.pass_at(venue, sat, ("HGUSD",), stamp_marks=True)
        for iv in SPAN:
            answered = venue.answered[("HGUSD", iv)]
            self.assertTrue(answered)
            self.assertTrue(all(_weekend_shut("cme", c.open, c.open + SPAN[iv])
                                for c in answered),
                            f"{iv}: the fixture's answer is weekend only")
        self.assertEqual([(r.timeframe, r.timestamp, r.close, r.source)
                          for r in _rows("HGUSD")], before)
        row.refresh_from_db()
        self.assertEqual(row.metadata["venue_mark"], mark)
        self.assertEqual(venue_mark.last(row, now=sat)["at"], fri)
        for iv in SPAN:
            self.assertFalse(bot_bars._venue_is_mute("etoro", "HGUSD", iv),
                             iv)
            self.assertEqual(
                bot_bars.last_venue_answer("etoro", "HGUSD", iv)["newest_ms"],
                notes[iv]["newest_ms"], iv)

    def _saturday(self, symbol, weekend):
        """A held real row, a pass on Friday 21:01 and one on Saturday
        12:01 UTC, both stamping the venue mark: (venue, row)."""
        from bot_program.models import AssetBotTrade
        from market_data.models import PriceData
        PriceData.objects.all().delete()
        AssetBotTrade.objects.all().delete()
        venue = EtoroTrader(weekend=weekend, symbols=(symbol,))
        row = self.held_row(symbol)
        self.pass_at(venue, FRI_21 + M, (symbol,), stamp_marks=True)
        self.pass_at(venue, SAT_12 + M, (symbol,), stamp_marks=True)
        row.refresh_from_db()
        return venue, row

    def test_a_moving_weekend_candle_of_a_weekday_market_goes_like_a_flat_one(
            self):
        """Copper's weekend candles, moving (high above low, the close
        drifting away from Friday's) or flat: none is stored, and none
        stamps the venue mark: the Saturday pass leaves it on the last
        traded candle's close, dated no later than that candle's end."""
        from market_data.models import PriceData
        for weekend in ("wide", "flat"):
            with self.subTest(weekend=weekend):
                probe = EtoroTrader(weekend=weekend, symbols=("HGUSD",))
                sat12 = probe.candle("HGUSD", "4h", SAT_12)
                fri20 = probe.candle("HGUSD", "4h", SAT_00 - 4 * H)
                if weekend == "wide":
                    self.assertGreater(sat12.h, sat12.l)
                    self.assertNotEqual(sat12.c, fri20.c)
                _venue, row = self._saturday("HGUSD", weekend)
                self.assertNoShutRow("HGUSD")
                self.assertFalse(PriceData.objects.filter(
                    instrument__symbol="HGUSD",
                    timestamp__gte=FRI_22, timestamp__lt=SUN_20).exists())
                vm = row.metadata["venue_mark"]
                self.assertLessEqual(_when(vm["at"]), SAT_00)
                self.assertEqual(Decimal(str(vm["price"])),
                                 Decimal(str(fri20.c)))
                if weekend == "wide":
                    self.assertNotEqual(Decimal(str(vm["price"])),
                                        Decimal(str(sat12.c)))

    def test_a_moving_weekend_gold_candle_is_kept_and_read_as_before(self):
        """Gold's weekend candles are eToro's 24/7 market for the very
        instrument a gold row holds (GOLD, 18): the Saturday pass stores
        them and stamps the venue mark from the newest, dated on Saturday,
        exactly as the writer did before the rule."""
        from market_data.models import PriceData
        venue, row = self._saturday("XAUUSD", "wide")
        for iv in SPAN:
            weekend = [c for c in venue.answered[("XAUUSD", iv)]
                       if c.open >= FRI_22]
            self.assertTrue(weekend, iv)
            stored = {r.timestamp: r.close for r in _rows("XAUUSD", iv)}
            for c in weekend:
                self.assertEqual(stored.get(c.open), Decimal(str(c.c)),
                                 f"{iv} {c.open:%a %H:%M}")
        self.assertTrue(PriceData.objects.filter(
            instrument__symbol="XAUUSD", timeframe="4h",
            timestamp=SAT_12).exists())
        vm = row.metadata["venue_mark"]
        self.assertGreater(_when(vm["at"]), SAT_00)
        self.assertIn(Decimal(str(vm["price"])),
                      {Decimal(str(venue.candle("XAUUSD", iv, SAT_12).c))
                       for iv in SPAN})


# ── money: the ATR at the reopen ─────────────────────────────────────────

Measure = namedtuple("Measure", "atr stop qty levels")


def _atr_of(candles, until=SUN_2315):
    """ATR(14) of the newest 56 `candles` opening at or before `until`, as
    the indicator calculator computes it: the fixture's own measure."""
    import pandas as pd

    from indicators.calculator import calculate_atr
    have = [c for c in candles if c.open <= until][-56:]
    df = pd.DataFrame([{"high": c.h, "low": c.l, "close": c.c}
                       for c in have])
    return float(calculate_atr(df["high"], df["low"], df["close"]).iloc[-1])


class TheReopenATRTests(_Writer):
    """V2: the first entry after the reopen sets its stop and its size from
    ATR(4h) (risk_levels.stop_and_target, sizing.size_position), the bots'
    and the TAKE TRADE ticket's when a signal carries no levels. At Sunday
    23:15 UTC that ATR must be the traded week's for a market that shut,
    whatever eToro answered for the weekend; an all-week instrument's reads
    its weekend market, as it always did."""

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
        for symbol in ("HGUSD", "EURUSD", "XAUUSD"):
            traded = _atr_of(_candles(symbol, "4h"))
            flat = _atr_of(_candles(symbol, "4h", "flat"))
            wide = _atr_of(_candles(symbol, "4h", "wide"))
            narrow = _atr_of(_candles(symbol, "4h", "narrow"))
            self.assertLess(flat, 0.5 * traded, symbol)
            self.assertGreater(wide, 1.5 * traded, symbol)
            self.assertLess(narrow, traded, symbol)

    def test_the_reopen_atr_stop_and_size_are_the_traded_weeks(self):
        for symbol in ("HGUSD", "EURUSD"):
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

    def test_golds_reopen_atr_reads_its_weekend_market_as_before(self):
        """Gold's weekend candles are kept, so its ATR(4h) at the reopen is
        the ATR of every candle eToro answered, the weekend's included,
        exactly as before the rule: above the traded week's after a wide
        weekend (a wider stop, a smaller size), below it after a narrow
        one (a tighter stop, a larger size)."""
        traded, _v = self._reopen("XAUUSD", None)
        for weekend, wider in (("wide", True), ("narrow", False)):
            with self.subTest(weekend=weekend):
                got, venue = self._reopen("XAUUSD", weekend)
                self.assertAlmostEqual(
                    got.atr, _atr_of(venue.series[("XAUUSD", "4h")]),
                    places=9)
                self.assertEqual(got.levels, "atr")
                if wider:
                    self.assertGreater(got.atr, 1.2 * traded.atr)
                    self.assertLess(got.stop, traded.stop)
                    self.assertLess(got.qty, traded.qty)
                else:
                    self.assertLess(got.atr, traded.atr)
                    self.assertGreater(got.stop, traded.stop)
                    self.assertGreater(got.qty, traded.qty)

    def test_the_stored_indicator_reads_the_same_atr(self):
        """The indicator task's stored atr_14, which atr_for reads first,
        is the traded week's too."""
        from indicators.tasks import recalculate_for_instruments
        from instruments.models import Instrument
        traded, _v = self._reopen("HGUSD", None)
        got, _v = self._reopen("HGUSD", "flat")
        with patch("django.utils.timezone.now", return_value=SUN_2315):
            recalculate_for_instruments(
                [Instrument.objects.get(symbol="HGUSD")], timeframes=("4h",))
        from bot_program.asset_engine import risk_levels
        self.assertAlmostEqual(risk_levels.atr_for("HGUSD", "4h"),
                               traded.atr, places=6)
        self.assertAlmostEqual(got.atr, traded.atr, places=9)


# ── the Orcs: the production cadence ─────────────────────────────────────

class TheOperatorsWindowTests(_Writer):
    """V1: two manual commodity Orcs on copper, born Friday 21:02 UTC; a bar
    pass hourly to Saturday 11:00, then at the production cadence (a bar
    pass every 10 minutes at :01, the manage tick every 5 minutes at :03)
    to Sunday 09:30, eToro answering a MOVING candle for every weekend slot.
    Before, W2 ("a 4h bar closed") woke both at Sat 12:03, 16:03, 20:03,
    Sun 00:03, 04:03 and 08:03. Now no weekend bar of a market that shut
    is stored, so no bar closes and no W2 fires in that window; the Friday
    bar's own close still wakes them once. (Gold's weekend bars are eToro's
    24/7 market and are stored: whether its Orcs wake on them is the Orcs'
    own rule, not the writer's.)"""

    def setUp(self):
        super().setUp()
        from tests.orcs.helpers import _on, _switch
        _switch("aragorn")
        _on()

    def _tick(self, row, orc, t, price):
        from bot_program.orcs.observe import after_care
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.manual,
                              _last_ticks={})
        row._care_tick = {"now": t}
        with ExitStack() as st:
            st.enter_context(patch("django.utils.timezone.now",
                                   return_value=t))
            st.enter_context(self.captureOnCommitCallbacks(execute=True))
            after_care(bot, row, price, "")
        orc.refresh_from_db()

    def _w2(self, orc):
        from bot_program.orcs.models import OrcWake
        return [(w.created_at, r.get("key"))
                for w in OrcWake.objects.filter(orc=orc).order_by("id")
                for r in (w.reasons or [])
                if isinstance(r, dict) and r.get("code") == "W2"]

    def test_no_w2_in_his_window_when_etoro_answers_weekend_candles(self):
        from tests.orcs.helpers import _manual_row, born
        sym = "HGUSD"
        price = f"{SYMBOLS[sym][3] + 0.001:.4f}"
        venue = EtoroTrader(weekend="wide", symbols=(sym,))
        self.pass_at(venue, FRI_21 + M, (sym,))
        rows, orcs = [], []
        for _ in range(2):
            r = _manual_row(self.manual, symbol=sym, cls="commodity",
                            **_prices(sym))
            orcs.append(born(self, r, at=FRI_21 + 2 * M))
            r.refresh_from_db()
            rows.append(r)
        t = FRI_21
        while t < SAT_11:                       # warm-up, hourly
            self.pass_at(venue, t + M, (sym,))
            for r, o in zip(rows, orcs):
                self._tick(r, o, t + 3 * M, price)
            t += H
        t = SAT_11
        while t <= SUN_0930:                    # his window
            if t.minute % 10 == 0:
                self.pass_at(venue, t + M, (sym,))
            for r, o in zip(rows, orcs):
                self._tick(r, o, t + 3 * M, price)
            t += 5 * M
        for o in orcs:
            w2 = self._w2(o)
            self.assertTrue([k for at, k in w2 if at < SAT_11],
                            "the harness saw no W2 at all: the Friday bar's "
                            "close should wake the Orc")
            self.assertEqual(
                [f"{at:%a %H:%M} {k}" for at, k in w2 if at >= SAT_11], [])
        self.assertNoShutRow(sym)
