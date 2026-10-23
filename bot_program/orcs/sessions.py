"""The session calendar the Orcs read (spec §1.6, O1): when does this
instrument's market next shut, for how long, and what kind of shut it is.

Pure over core/exchange_status.py: market_clock (is it open now, when does
it reopen, when did the running shut begin) and next_close_utc (when the
running session ends). It models what that module models: the session
closes of every listed venue, the FX week, CME Globex's daily break, the
product sessions, and the US equity holidays and early closes. No other
venue's holidays are modelled (exchange_status.market_clock's docstring),
so a shut on a non-US holiday is missed until that calendar grows.

The care's Friday-hour check answers another question ("is it the last
hour before this class shuts for the weekend") and is not read here.
"""
from datetime import timedelta

from django.utils import timezone

from core.exchange_status import (US_EQUITY_HOLIDAYS, market_clock,
                                  next_close_utc, utc_words)

#: The classes that never shut (position_care.NEVER_SHUTS, copied: this
#: module reads the clock and nothing of the care).
NEVER_SHUTS = frozenset({"crypto"})
#: A shut shorter than this is a break inside the trading day (CME's hour,
#: a grain or soft product's midday gap); longer is an overnight.
BREAK_MAX_HOURS = 8.0
#: shuts_within walks at most this many shuts (30 days of a US equity
#: session is about 44).
MAX_SHUTS = 64


def _kind(at, reopens, session) -> str:
    """weekend | holiday | break | overnight, from the shut's own span."""
    if at is None or reopens is None:
        return "weekend"
    day = at.date()
    last = (reopens - timedelta(microseconds=1)).date()
    while day <= last:
        if day.weekday() == 5:
            return "weekend"
        day += timedelta(days=1)
    hours = (reopens - at).total_seconds() / 3600.0
    if session in ("NYSE", "NASDAQ"):
        import pytz
        ny = pytz.timezone("America/New_York")
        day = at.astimezone(ny).date()
        last = reopens.astimezone(ny).date()
        while day <= last:
            if day in US_EQUITY_HOLIDAYS:
                return "holiday"
            day += timedelta(days=1)
    if hours >= 24.0:
        return "holiday"
    if hours < BREAK_MAX_HOURS:
        return "break"
    return "overnight"


def next_shut(asset_class, symbol="", now=None, *, exchange=""):
    """The next shut of this instrument's market, or the running one:

        {"at", "reopens", "kind": weekend|overnight|holiday|break, "hours",
         "words", "session", "now_shut", "modelled": True}

    `at` and `reopens` are aware UTC datetimes; `words` is "Friday 20:00
    UTC". None for a class that never shuts (crypto); {"modelled": False}
    for a class with no modelled hours (cfd, "", unknown)."""
    cls = (asset_class or "").strip().lower()
    if cls in NEVER_SHUTS:
        return None
    now = now or timezone.now()
    clock = market_clock(cls, exchange or "", symbol or "", now_utc=now)
    if not clock.get("modelled"):
        return {"modelled": False}
    session = clock.get("session") or ""
    if not clock.get("is_open"):
        at, reopens, now_shut = clock.get("closed"), clock.get("reopens"), True
    else:
        at = next_close_utc(cls, exchange or "", symbol or "", now)
        if at is None:
            return None
        after = market_clock(cls, exchange or "", symbol or "", now_utc=at)
        reopens, now_shut = after.get("reopens"), False
    hours = (round((reopens - at).total_seconds() / 3600.0, 2)
             if at is not None and reopens is not None else None)
    return {"at": at, "reopens": reopens, "kind": _kind(at, reopens, session),
            "hours": hours, "words": utc_words(at) if at is not None else "",
            "session": session, "now_shut": now_shut, "modelled": True}


def shuts_within(asset_class, symbol="", now=None, *, hours, exchange=""):
    """Every shut that begins (or is running) within `hours` of `now`, in
    order. [] for a class that never shuts or is not modelled."""
    now = now or timezone.now()
    end = now + timedelta(hours=float(hours or 0))
    out, t = [], now
    for _ in range(MAX_SHUTS):
        s = next_shut(asset_class, symbol, t, exchange=exchange)
        if not s or not s.get("modelled") or s.get("at") is None:
            break
        if s["at"] >= end:
            break
        out.append(s)
        if s.get("reopens") is None or s["reopens"] <= t:
            break
        t = s["reopens"]
    return out


# ── O1c: the trading day and its sessions (spec §5.2a MK, §7.5.3) ────────
#
# The trading day rolls at 17:00 New York (TRADING_DAY_ROLL_NY_HOUR) and is
# named after the date it ends on, as power_of_three names it ("the Asian
# date + 1"). Its sessions are ICT's New York windows
# (signals/smc/sessions.py ICT_SESSIONS_NY), in the order the day runs
# them; Asia is 20:00 to midnight New York of the roll evening. zoneinfo
# carries the clock change: the day that holds it is 23 or 25 hours long.

#: The sessions MK writes one block for, in the day's order.
SESSION_NAMES = ("asia", "london", "ny_am", "ny_lunch", "ny_pm")


def _ny():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def trading_day(now):
    """The trading day `now` falls in (a date): New York's date, plus one
    from 17:00 New York on."""
    from bot_program.orcs.constants import TRADING_DAY_ROLL_NY_HOUR
    local = now.astimezone(_ny())
    day = local.date()
    if local.hour >= TRADING_DAY_ROLL_NY_HOUR:
        day += timedelta(days=1)
    return day


def _at_ny(day, hour, minute=0):
    from datetime import datetime, time
    from datetime import timezone as dt_tz
    return datetime.combine(day, time(hour, minute), tzinfo=_ny()) \
        .astimezone(dt_tz.utc)


def day_bounds(td) -> tuple:
    """(start, end) of trading day `td` in UTC: 17:00 New York the evening
    before, to 17:00 New York on `td`."""
    from bot_program.orcs.constants import TRADING_DAY_ROLL_NY_HOUR
    return (_at_ny(td - timedelta(days=1), TRADING_DAY_ROLL_NY_HOUR),
            _at_ny(td, TRADING_DAY_ROLL_NY_HOUR))


def session_windows(td) -> list:
    """[(name, start_utc, end_utc)] of trading day `td`, in SESSION_NAMES
    order. Asia runs 20:00 to 24:00 New York of the evening before."""
    from signals.smc.sessions import ICT_SESSIONS_NY
    out = []
    for name in SESSION_NAMES:
        first, last = ICT_SESSIONS_NY[name]
        if name == "asia":
            start = _at_ny(td - timedelta(days=1), first.hour, first.minute)
            end = _at_ny(td, last.hour, last.minute)
        else:
            start = _at_ny(td, first.hour, first.minute)
            end = _at_ny(td, last.hour, last.minute)
        out.append((name, start, end))
    return out


def closed_sessions(now) -> list:
    """The sessions of `now`'s trading day that have ended, in order."""
    return [name for name, _s, end in session_windows(trading_day(now))
            if end <= now]


def current_session(now):
    """The session running at `now`, or None between sessions."""
    for name, start, end in session_windows(trading_day(now)):
        if start <= now < end:
            return name
    return None
