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
