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

Every other class reads False: crypto never shuts, eToro trades US shares
and index CFDs outside their cash sessions, and an unmodelled class has no
hours to judge by. So does a bar that cannot be judged (an unknown
timeframe, an unreadable open or clock): it is written as before. Reads no
database; never raises.
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
#: The shortest shut whose bars are dropped (etoro_rates.SHUT_MIN_SPAN_S).
SHUT_MIN_S = 24 * 3600
#: eToro's FX week shuts on Friday at FX_SHUT_AT and opens again on Sunday
#: at FX_SHUT_AT, on FX_ZONE's clock.
FX_ZONE = ZoneInfo("America/New_York")
FX_SHUT_AT = time(17, 0)


def holds_no_open_time(instrument, timeframe, bar_open_utc) -> bool:
    """True when the bar of `instrument` on `timeframe` that opens at
    `bar_open_utc` holds no open time over its whole span, inside one shut
    of SHUT_MIN_S or more (the module docstring). `instrument` is anything
    with `asset_class`, `exchange` and `symbol` (an Instrument row); a naive
    `bar_open_utc` is read as UTC."""
    try:
        cls = str(getattr(instrument, "asset_class", "") or "").strip().lower()
        if cls not in COVERED_CLASSES or bar_open_utc is None:
            return False
        from market_data.bot_bars import INTERVAL_SECONDS
        span_s = INTERVAL_SECONDS.get(str(timeframe or ""))
        if not span_s:
            return False
        start = bar_open_utc
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_tz.utc)
        shut = (_fx_shut(start) if cls == "forex"
                else _clock_shut(cls, instrument, start))
        if shut is None:
            return False
        closed, reopens = shut
        if (reopens - closed).total_seconds() < SHUT_MIN_S:
            return False                  # a nightly or a daily break
        return start + timedelta(seconds=span_s) <= reopens
    except Exception as e:  # noqa: BLE001 — unjudged is written as before
        logger.debug("[bars] shut test unread for %s %s %s: %s",
                     getattr(instrument, "symbol", "?"), timeframe,
                     bar_open_utc, e)
        return False


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
