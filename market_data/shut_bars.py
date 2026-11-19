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
inside one shut of SHUT_MIN_S or more: a weekend or a holiday, never a
nightly or a daily break, which a CFD's own hours may not keep (the rates'
rule, bot_program/engine/etoro_rates.SHUT_MIN_SPAN_S). A PriceData
timestamp is the bar's open (bot_bars._upsert_rows writes eToro's
`fromDate` there, etoro_client.EtoroTrader.klines), and the span is the
writer's own INTERVAL_SECONDS. Classes: COVERED_CLASSES only.

  forex      eToro's own week, Friday 17:00 to Sunday 17:00 New York, read
             on New York's clock (America/New_York, so summer time is its
             own): ForexBot.forex_market_open's rule, the one etoro_rates
             .shut_max_age reads. NOT the FOREX row's UTC hours alone: from
             November to March they shut at 21:00 UTC, an hour eToro still
             trades.
  commodity  the instrument's own market clock (core.exchange_status
             .market_clock with its exchange: Globex for metals and energy,
             the product session for grains, softs and livestock); an
             exchange no table names ("" from /setup/, "ETORO" from the
             legacy sync) reads the class's default clock, CME.

EXCEPT eToro's ALL-WEEK instruments (ALL_WEEK_ETORO_IDS, 2026-11-19):
GOLD, OIL, SILVER and NATGAS trade at eToro on Saturday and Sunday too,
with short breaks only, so a weekend candle of theirs is a price eToro
traded, never a shut slot: it reads False whatever its exchange's clock
says, and is written, noted and stamped as every candle was before this
rule. (The rule's first cut, also 2026-11-19, read gold on Globex and
dropped its weekend candles; eToro's own pages list the regular GOLD, the
instrument Sauron trades, as 24/7.)

Every other class reads False: crypto never shuts, eToro trades US shares
and index CFDs outside their cash sessions, and an unmodelled class has no
hours to judge by. So does a bar that cannot be judged (an unknown
timeframe, an unreadable open or clock): it is written as before. Reads no
database and no network; never raises.

THE SAME CLOCKS, NOW (2026-11-19, the guard): shut_for_a_day_now(instrument,
now) answers (closed, reopens) while `instrument` is inside one shut of
SHUT_MIN_S or more, for the classes in HELD_CLASSES, never for an all-week
instrument. bot_program/shut_guard.py holds a live eToro row's management
on it (the switch care_holds_while_shut).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone as dt_tz
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

#: The classes whose shut bars are dropped: the rates' shut-cadence classes
#: (etoro_rates.SHUT_CADENCE_CLASSES), for the same reasons. Another class
#: is one more word here.
COVERED_CLASSES = frozenset({"forex", "commodity"})
#: The classes whose live eToro rows the guard holds while their market is
#: shut for SHUT_MIN_S or more (shut_for_a_day_now; bot_program/
#: shut_guard.py): today the bar rule's own. Another class is one more word
#: here, read on its instrument's market clock.
HELD_CLASSES = frozenset({"forex", "commodity"})
#: The shortest shut whose bars are dropped (etoro_rates.SHUT_MIN_SPAN_S).
SHUT_MIN_S = 24 * 3600
#: eToro's FX week shuts on Friday at FX_SHUT_AT and opens again on Sunday
#: at FX_SHUT_AT, on FX_ZONE's clock.
FX_ZONE = ZoneInfo("America/New_York")
FX_SHUT_AT = time(17, 0)

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
#: Sunday 23:00 and shuts on Friday 21:30 UTC, and EURUSD, which one eToro
#: page lists as 24/7 and another as weekday-only: it keeps eToro's FX week
#: until a measurement settles it (a real weekend candle dropped leaves the
#: traded bars; a flat one kept deflates the ATR the stops and sizes are
#: set from).
ALL_WEEK_ETORO_IDS = {18: "GOLD", 17: "OIL", 19: "SILVER", 22: "NATGAS",
                      27: "SPX500", 28: "NSDQ100"}


def trades_all_week(instrument) -> bool:
    """True when `instrument` (anything with a `symbol`, or the platform
    symbol itself) is one of eToro's ALL_WEEK_ETORO_IDS. Its eToro id is
    read as etoro_client's instrument_id reads it first, with no network:
    the symbol's pin (VENUE_ID_PINS: XAUUSD is 18); with no pin, the
    all-week id whose eToro name is the symbol's eToro spelling
    (VENUE_SPELLING's rewrite, else the symbol as spelled: SPX500 is 27),
    never an id pinned to another symbol (the catalogue's own GOLD is the
    Barrick Gold stock, never eToro's 18). Never raises."""
    try:
        symbol = str(getattr(instrument, "symbol", instrument) or "")
        symbol = symbol.strip().upper()
        if not symbol:
            return False
        from bot_program.engine.etoro_client import (VENUE_ID_PINS,
                                                     VENUE_SPELLING)
        pinned = VENUE_ID_PINS.get(symbol)
        if pinned is not None:
            return pinned in ALL_WEEK_ETORO_IDS
        spelled = VENUE_SPELLING.get(symbol, symbol)
        held = set(VENUE_ID_PINS.values())
        return any(name == spelled and iid not in held
                   for iid, name in ALL_WEEK_ETORO_IDS.items())
    except Exception as e:  # noqa: BLE001 — unread is the clock's rule
        logger.debug("[bars] all-week test unread for %r: %s",
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
    None; a naive `now` is read as UTC), on the very clocks
    holds_no_open_time reads: eToro's FX week for a pair, the instrument's
    market clock for a commodity. None while its market runs, in a nightly
    or a daily break, for a class outside HELD_CLASSES, for one of eToro's
    all-week instruments (trades_all_week), and when the clock cannot be
    read. `instrument` is anything with `asset_class`, `exchange` and
    `symbol` (an Instrument row). Reads no database; never raises."""
    try:
        cls = str(getattr(instrument, "asset_class", "") or "").strip().lower()
        if cls not in HELD_CLASSES or trades_all_week(instrument):
            return None
        if now is None:
            now = datetime.now(dt_tz.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt_tz.utc)
        return _long_shut(cls, instrument, now)
    except Exception as e:  # noqa: BLE001 — unread is never held
        logger.debug("[bars] shut-now test unread for %s at %s: %s",
                     getattr(instrument, "symbol", "?"), now, e)
        return None


def _long_shut(cls, instrument, t):
    """(closed, reopens) of the shut of SHUT_MIN_S or more that holds `t`
    on the class's clock (_fx_shut for forex, the instrument's market clock
    for any other class), or None: open, or a nightly or a daily break."""
    shut = (_fx_shut(t) if cls == "forex"
            else _clock_shut(cls, instrument, t))
    if shut is None:
        return None
    closed, reopens = shut
    if (reopens - closed).total_seconds() < SHUT_MIN_S:
        return None
    return closed, reopens


def _fx_shut(t):
    """(closed, reopens) of eToro's FX weekend shut that holds `t`, as aware
    UTC datetimes, or None while the week runs: the last Friday FX_SHUT_AT
    at or before `t`, and the Sunday FX_SHUT_AT after it, on FX_ZONE's
    clock (a 47 h or a 49 h shut on the weekends New York changes its)."""
    local = t.astimezone(FX_ZONE)
    friday = local.date() - timedelta(days=(local.weekday() - 4) % 7)
    closed = datetime.combine(friday, FX_SHUT_AT, tzinfo=FX_ZONE)
    if closed > local:
        friday -= timedelta(days=7)
        closed = datetime.combine(friday, FX_SHUT_AT, tzinfo=FX_ZONE)
    reopens = datetime.combine(friday + timedelta(days=2), FX_SHUT_AT,
                               tzinfo=FX_ZONE)
    if not closed <= local < reopens:
        return None
    return closed.astimezone(dt_tz.utc), reopens.astimezone(dt_tz.utc)


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
