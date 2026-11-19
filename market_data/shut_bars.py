"""A VENUE BAR THE MARKET WAS SHUT FOR (2026-11-19).

eToro answers a candle for every slot the bar pass asks it for, the slots
a market was shut for included: on a weekend, a 1h and a 4h candle for each
slot of a currency pair or a commodity, flat at Friday's close or moving.
The bar writer (market_data/bot_bars.py) stored each one as the venue's
bar, and every reader of the bars took it for a traded one: the ATR the
entry stops and sizes are set from, the Orcs' "a bar closed" wake, the
chart, the venue mark.

ONE TEST, for the writer and for whatever prunes the bars already stored:
holds_no_open_time(instrument, timeframe, bar_open_utc) is True when the
bar's WHOLE span [open, open + timeframe) holds no open time AND lies
inside one shut of SHUT_MIN_S or more: a weekend, a weekend a holiday
stretches, or a holiday of a day (SHUT_HOLIDAYS); never a nightly or a
daily break, which a CFD's own hours may not keep (the rates' rule,
bot_program/engine/etoro_rates.SHUT_MIN_SPAN_S). A PriceData timestamp is
the bar's open (bot_bars._upsert_rows writes eToro's `fromDate` there,
etoro_client.EtoroTrader.klines), and the span is the writer's own
INTERVAL_SECONDS. Classes: COVERED_CLASSES only.

  forex      eToro's FX week, Friday 17:00 to Sunday 17:00 New York, read
             on New York's clock (America/New_York, so summer time is its
             own): ForexBot.forex_market_open's rule, the one etoro_rates
             .shut_max_age reads. NOT the FOREX row's UTC hours alone: from
             November to March they shut at 21:00 UTC, half an hour before
             eToro's own Friday close (21:30 UTC), so the 21:00 bar traded.
  commodity  Globex's week, Friday 16:00 to Sunday 17:00 Chicago, for a
             commodity on Globex's clock: metals and energy (COMEX, NYMEX)
             and an exchange no table names ("" from /setup/, "ETORO" from
             the legacy sync), which reads the class's default, CME. Any
             other commodity reads its own market clock (core
             .exchange_status.market_clock: the product session of grains,
             softs and livestock), which keeps no holiday.

HOLIDAYS (SHUT_HOLIDAYS, 2026-11-19): on Christmas Day and New Year's Day
the FX week and Globex hold no session: Globex is closed on both (CME
Group's holiday calendar), and so is the FX market. The trading day that
ends on such a date is shut, so a Friday holiday stretches the weekend back
to Thursday's close (Fri 2026-12-25 and Fri 2027-01-01: a pair is shut from
Thursday 17:00 to Sunday 17:00 New York, copper from Thursday 16:00 to
Sunday 17:00 Chicago), and a Monday one stretches it to Monday's. NOT
modelled: an early close (the hours between it and the regular close read
open), a holiday moved to a weekday because its date is a Saturday or a
Sunday, any other holiday, and eToro's own holiday hours, which are not
read here.

EXCEPT eToro's ALL-WEEK instruments (ALL_WEEK_ETORO_IDS, 2026-11-19):
GOLD, OIL, SILVER and NATGAS trade at eToro on Saturday and Sunday too,
with short breaks only, so a weekend candle of theirs is a price eToro
traded, never a shut slot: it reads False whatever its exchange's clock
says, and is written, noted and stamped as every candle was before this
rule. (The rule's first cut, also 2026-11-19, read gold on Globex and
dropped its weekend candles; eToro's own pages list the regular GOLD, the
instrument Sauron trades, as 24/7.)

NOT JUDGED: a commodity filed under an exchange whose clock the venue does
not keep (UNKEPT_EXCHANGES): it reads False and is never held, as before
the rule. Every other class reads False: crypto never shuts, eToro trades
US shares and index CFDs outside their cash sessions, and an unmodelled
class has no hours to judge by. So does a bar that cannot be judged (an
unknown timeframe, an unreadable open or clock): it is written as before.
Reads no database and no network; never raises.

THE SAME WEEK, NOW (2026-11-19, the guard): shut_for_a_day_now(instrument,
now) answers (closed, reopens) while `instrument` is inside one shut of
SHUT_MIN_S or more, for the classes in HELD_CLASSES, holidays included, on
eToro's own published edges (GUARD_FX_CLOSE, GUARD_FX_OPEN,
GUARD_GLOBEX_CLOSE) where the bar rule reads the wider week; never for an
all-week instrument, nor for one whose weekend hours are unsettled
(UNSETTLED_WEEKEND_ETORO_IDS: EURUSD). bot_program/shut_guard.py holds a
live eToro row's management on it (the switch care_holds_while_shut).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone as dt_tz
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

#: The classes whose shut bars are dropped: the rates' shut-cadence classes
#: (etoro_rates.SHUT_CADENCE_CLASSES), for the same reasons. NOT one more
#: word for another class: _long_shut reads the FX week for forex and the
#: instrument's market clock for any other class, and for an index or a US
#: share that clock is the cash session, not eToro's CFD week (eToro trades
#: them through the cash market's nights: venue_mark.market_shut routes an
#: index onto the FX week for that reason). A class needs its venue's own
#: clock in _long_shut before it is added here.
COVERED_CLASSES = frozenset({"forex", "commodity"})
#: The classes whose live eToro rows the guard holds while their market is
#: shut for SHUT_MIN_S or more (shut_for_a_day_now; bot_program/
#: shut_guard.py): today the bar rule's own, and on the same condition: a
#: class is added only with its venue's own clock in _long_shut.
HELD_CLASSES = frozenset({"forex", "commodity"})
#: The shortest shut whose bars are dropped (etoro_rates.SHUT_MIN_SPAN_S).
SHUT_MIN_S = 24 * 3600
#: eToro's FX week shuts on Friday at FX_SHUT_AT and opens again on Sunday
#: at FX_SHUT_AT, on FX_ZONE's clock.
FX_ZONE = ZoneInfo("America/New_York")
FX_SHUT_AT = time(17, 0)
#: Globex's week: its last session of the week ends on Friday at
#: GLOBEX_CLOSE and the next opens on Sunday at GLOBEX_OPEN, on
#: GLOBEX_ZONE's clock (the CME row of core.exchange_status; its daily
#: 16:00-17:00 break is a shut of one hour, never a long one).
GLOBEX_ZONE = ZoneInfo("America/Chicago")
GLOBEX_CLOSE = time(16, 0)
GLOBEX_OPEN = time(17, 0)

#: THE GUARD'S EDGES (shut_for_a_day_now only, 2026-11-19): eToro's own
#: published hours for what it shuts at weekends (its market-hours page,
#: the English page as indexed about 2026-11-02, read 2026-11-19). A
#: currency pair (GBPUSD, USDJPY): "Market Opens: Sunday 22:05; Market
#: Closes: Friday 21:30" UTC in winter, so from Friday 16:30 to Sunday
#: 17:05 New York. Copper, platinum and palladium: "Market Opens: Sunday
#: 23:00; Market Closes: Friday 21:30", so from 30 minutes before Globex's
#: Friday close to its Sunday reopen. The bar rule keeps the wider week: a
#: bar it keeps between the two is a flat candle at most (the safe side for
#: the bars), while a row held from eToro's own close is never sent an
#: order eToro cannot fill (the safe side for the guard).
GUARD_FX_CLOSE = time(16, 30)
GUARD_FX_OPEN = time(17, 5)
GUARD_GLOBEX_CLOSE = time(15, 30)

#: (month, day) of the holidays on which the FX week and Globex hold no
#: session, every year (the module docstring, HOLIDAYS).
SHUT_HOLIDAYS = frozenset({(12, 25), (1, 1)})

#: Exchanges whose clock the venue does not keep, read as NOT JUDGED (the
#: module docstring). LME: core.exchange_status reads it on LSE's 08:00 to
#: 16:30 London weekday clock (SESSION_ALIASES), while LMEselect trades
#: 01:00 to 19:00 London and eToro's weekday metals trade from Sunday
#: night to Friday evening: that clock would drop bars they traded and
#: hold rows through their hours. Nothing serves an LME row from a venue
#: today (instruments.services files ALUMUSD, ZINCUSD, NICKELUSD, LEADUSD
#: and TINUSD under it; no eToro pin or spelling names them).
UNKEPT_EXCHANGES = frozenset({"LME"})

#: eToro's ALL-WEEK instruments (2026-11-19): eToro instrument id -> eToro's
#: own name. They trade on Saturday and Sunday too, so none is ever shut for
#: SHUT_MIN_S and their weekend candles are kept (trades_all_week).
#: Source: eToro's market-hours page (etoro.com/trading/market-hours-and-
#: events/, the English page as indexed about 2026-11-02, read 2026-11-19)
#: lists "GOLD Gold (Non Expiry)", "OIL Oil (Non Expiry)", "SILVER (Non
#: Expiry)" and "NATGAS (Non Expiry)" as open 24/7, their only breaks daily
#: 22:00-23:00 and Friday 22:00-22:30 UTC (OIL and NATGAS also Saturday
#: 22:00-22:15). eToro's commodities page names "Oil, Gold, Silver, NatGas,
#: S&P 500 and NSDQ100" as its instruments that trade 24/7, and its help
#: centre is "gradually retiring separate .24-7 tickers" for "the 24/7-
#: labelled asset without the .24-7 ticker": these very ids. Keyed by id,
#: never by name: the four commodities are Sauron's own pins (etoro_client
#: .VENUE_ID_PINS), the two indices the ids /search answers for them as
#: spelled (27 and 28: etoro_client's VENUE_SPELLING note). NOT here:
#: copper (21), platinum (40) and palladium (91), which eToro opens on
#: Sunday 23:00 and shuts on Friday 21:30 UTC, and EURUSD
#: (UNSETTLED_WEEKEND_ETORO_IDS).
ALL_WEEK_ETORO_IDS = {18: "GOLD", 17: "OIL", 19: "SILVER", 22: "NATGAS",
                      27: "SPX500", 28: "NSDQ100"}
#: eToro instruments whose WEEKEND HOURS ARE UNSETTLED (2026-11-19): eToro
#: instrument id -> eToro's own name. EURUSD (1, the id instrument_id
#: answered for it: tests/test_etoro_client.py): one eToro page lists the
#: regular EURUSD as 24/7 (breaks daily 22:00-23:00, Friday 22:00-22:30,
#: Sunday 21:00-22:05 UTC), another as weekday-only, and eToro answered
#: weekend EURUSD candles one weekend and none the next. Until a
#: measurement settles it, each reader takes its own safe side:
#:   * the bar rule keeps eToro's FX week for it (holds_no_open_time drops
#:     its weekend candles): a real weekend candle dropped leaves the traded
#:     bars, while a flat one kept deflates the ATR the stops and sizes are
#:     set from;
#:   * the guard never holds it (shut_for_a_day_now answers None, its rows
#:     are managed as before): if eToro trades it at weekends, a held row
#:     would have only eToro's resting stop for two days.
UNSETTLED_WEEKEND_ETORO_IDS = {1: "EURUSD"}


def _listed(instrument, table) -> bool:
    """True when `instrument` (anything with a `symbol`, or the platform
    symbol itself) is one of `table`'s eToro ids. Its eToro id is read as
    etoro_client's instrument_id reads it first, with no network: the
    symbol's pin (VENUE_ID_PINS: XAUUSD is 18); with no pin, the id whose
    eToro name in `table` is the symbol's eToro spelling (VENUE_SPELLING's
    rewrite, else the symbol as spelled: SPX500 is 27, EURUSD 1), never an
    id pinned to another symbol (the catalogue's own GOLD is the Barrick
    Gold stock, never eToro's 18). Raises what it cannot read."""
    symbol = str(getattr(instrument, "symbol", instrument) or "")
    symbol = symbol.strip().upper()
    if not symbol:
        return False
    from bot_program.engine.etoro_client import VENUE_ID_PINS, VENUE_SPELLING
    pinned = VENUE_ID_PINS.get(symbol)
    if pinned is not None:
        return pinned in table
    spelled = VENUE_SPELLING.get(symbol, symbol)
    held = set(VENUE_ID_PINS.values())
    return any(name == spelled and iid not in held
               for iid, name in table.items())


def trades_all_week(instrument) -> bool:
    """True when `instrument` (anything with a `symbol`, or the platform
    symbol itself) is one of eToro's ALL_WEEK_ETORO_IDS (_listed's lookup).
    Never raises."""
    try:
        return _listed(instrument, ALL_WEEK_ETORO_IDS)
    except Exception as e:  # noqa: BLE001 — unread is the clock's rule
        logger.debug("[bars] all-week test unread for %r: %s",
                     getattr(instrument, "symbol", instrument), e)
        return False


def weekend_unsettled(instrument) -> bool:
    """True when `instrument` is one of UNSETTLED_WEEKEND_ETORO_IDS
    (_listed's lookup): the guard never holds it. Never raises; unread is
    False (the guard's own rule then applies)."""
    try:
        return _listed(instrument, UNSETTLED_WEEKEND_ETORO_IDS)
    except Exception as e:  # noqa: BLE001
        logger.debug("[bars] unsettled-weekend test unread for %r: %s",
                     getattr(instrument, "symbol", instrument), e)
        return False


def holds_no_open_time(instrument, timeframe, bar_open_utc) -> bool:
    """True when the bar of `instrument` on `timeframe` that opens at
    `bar_open_utc` holds no open time over its whole span, inside one shut
    of SHUT_MIN_S or more (the module docstring); never for one of eToro's
    all-week instruments (trades_all_week). `instrument` is anything with
    `asset_class`, `exchange` and `symbol` (an Instrument row); a naive
    `bar_open_utc` is read as UTC."""
    try:
        cls = str(getattr(instrument, "asset_class", "") or "").strip().lower()
        if cls not in COVERED_CLASSES or bar_open_utc is None:
            return False
        if trades_all_week(instrument):
            return False                  # eToro trades it all week
        from market_data.bot_bars import INTERVAL_SECONDS
        span_s = INTERVAL_SECONDS.get(str(timeframe or ""))
        if not span_s:
            return False
        start = bar_open_utc
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_tz.utc)
        shut = _long_shut(cls, instrument, start)
        if shut is None:
            return False                  # open, or a nightly/daily break
        return start + timedelta(seconds=span_s) <= shut[1]
    except Exception as e:  # noqa: BLE001 — unjudged is written as before
        logger.debug("[bars] shut test unread for %s %s %s: %s",
                     getattr(instrument, "symbol", "?"), timeframe,
                     bar_open_utc, e)
        return False


def shut_for_a_day_now(instrument, now=None):
    """(closed, reopens), as aware UTC datetimes, while `instrument` is
    inside one shut of SHUT_MIN_S or more at `now` (the wall clock when
    None; a naive `now` is read as UTC): the bar rule's week and holidays,
    on eToro's own published edges (the module's GUARD_* constants): a pair
    from Friday 16:30 to Sunday 17:05 New York, a commodity on Globex's
    clock from 30 minutes before its Friday close to its Sunday reopen, any
    other commodity on its market clock. None while its market runs, in a
    nightly or a daily break, for a class outside HELD_CLASSES, for one of
    eToro's all-week instruments (trades_all_week), for one whose weekend
    hours are unsettled (weekend_unsettled: EURUSD), for an exchange the
    venue does not keep (UNKEPT_EXCHANGES), and when the clock cannot be
    read. `instrument` is anything with `asset_class`, `exchange` and
    `symbol` (an Instrument row). Reads no database; never raises."""
    try:
        cls = str(getattr(instrument, "asset_class", "") or "").strip().lower()
        if cls not in HELD_CLASSES or trades_all_week(instrument):
            return None
        if weekend_unsettled(instrument):
            return None
        if now is None:
            now = datetime.now(dt_tz.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt_tz.utc)
        return _long_shut(cls, instrument, now, guard=True)
    except Exception as e:  # noqa: BLE001 — unread is never held
        logger.debug("[bars] shut-now test unread for %s at %s: %s",
                     getattr(instrument, "symbol", "?"), now, e)
        return None


def _long_shut(cls, instrument, t, *, guard=False):
    """(closed, reopens) of the shut of SHUT_MIN_S or more that holds `t`,
    or None: open, a nightly or a daily break, or an exchange the venue
    does not keep. Forex reads eToro's FX week, a commodity on Globex's
    clock reads Globex's week, both with SHUT_HOLIDAYS (_week_shut); any
    other commodity its market clock (_clock_shut). `guard`: the guard's
    edges, eToro's published ones, in place of the bar rule's."""
    if cls == "forex":
        shut = _week_shut(t, FX_ZONE,
                          GUARD_FX_CLOSE if guard else FX_SHUT_AT,
                          GUARD_FX_OPEN if guard else FX_SHUT_AT)
    else:
        exchange = str(getattr(instrument, "exchange", "") or "")
        if exchange.strip().upper() in UNKEPT_EXCHANGES:
            return None
        from core.exchange_status import session_code_for
        code = session_code_for(cls, exchange,
                                str(getattr(instrument, "symbol", "") or ""))
        if code == "CME":
            shut = _week_shut(t, GLOBEX_ZONE,
                              GUARD_GLOBEX_CLOSE if guard else GLOBEX_CLOSE,
                              GLOBEX_OPEN)
        else:
            shut = _clock_shut(cls, instrument, t)
    if shut is None:
        return None
    closed, reopens = shut
    if (reopens - closed).total_seconds() < SHUT_MIN_S:
        return None
    return closed, reopens


def _no_session(day) -> bool:
    """True when no trading day ends on `day` (a date on the week's own
    clock): a Saturday, a Sunday or one of SHUT_HOLIDAYS."""
    return day.weekday() >= 5 or (day.month, day.day) in SHUT_HOLIDAYS


def _week_shut(t, zone, close_at, open_at):
    """(closed, reopens), as aware UTC datetimes, of the run of shut trading
    days that holds `t`, or None while a session runs or in a daily break.

    A trading day is named by the date it ends on, on `zone`'s clock: it
    opens the evening before at `open_at` and ends at `close_at`. One that
    is shut (_no_session) shuts the market from the close of the day before
    it to its own `open_at`; a run of them, from the close before the first
    to the open after the last. The FX week (17:00 to 17:00 New York) and
    Globex (17:00 to 16:00 Chicago) are two such weeks; a holiday is a shut
    trading day like a Saturday."""
    local = t.astimezone(zone)

    def at(day, moment):
        return datetime.combine(day, moment, tzinfo=zone).astimezone(dt_tz.utc)

    one = timedelta(days=1)
    for day in (local.date(), local.date() + one):
        if not _no_session(day):
            continue
        if not at(day - one, close_at) <= t < at(day, open_at):
            continue
        first = last = day
        for _ in range(14):           # a run is a few days long at most
            if not _no_session(first - one):
                break
            first -= one
        for _ in range(14):
            if not _no_session(last + one):
                break
            last += one
        return at(first - one, close_at), at(last, open_at)
    return None


def _clock_shut(cls, instrument, t):
    """(closed, reopens) of the shut the instrument's market clock says
    holds `t`, or None while it is open, for a clock with no modelled
    hours, and for a shut whose start or end it cannot name."""
    from core.exchange_status import market_clock
    clock = market_clock(cls, getattr(instrument, "exchange", "") or "",
                         symbol=getattr(instrument, "symbol", "") or "",
                         now_utc=t)
    if not clock.get("modelled") or clock.get("is_open", True):
        return None
    closed, reopens = clock.get("closed"), clock.get("reopens")
    if closed is None or reopens is None:
        return None
    return closed, reopens
