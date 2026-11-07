"""THE SESSION RULE FOR eTORO'S PRICES (the eToro feed spec, F1, §5.5;
2026-11-07).

Whether an instrument's market is open, for protection and for entries,
from three things:

  * core.exchange_status.market_clock, which knows daylight saving and the
    US holidays (its FX week already follows New York 17:00). It is read,
    never changed: paper, Morgul and venue_mark read it today. An index
    CFD keeps its venue's week (the FX week's edges), as venue_mark's
    market_shut reads it: eToro's index CFDs trade through the cash
    market's nights and shut for the weekend;
  * eToro's forex daily break, five minutes from New York 17:00 (22:00 UTC
    in winter, 21:00 UTC in summer). The published hours conflict and move
    with daylight saving, so until M2 measures a regime (MEASURED_BREAKS),
    entries refuse in EVERY candidate window of that regime — New York
    17:00 and the fixed 22:00 UTC of the first tables — and protection is
    never touched;
  * the snapshot's IsMarketOpen, once M2 proves it flips at the real close
    (ETORO_OPEN_PROVEN). Until then it is ignored.

THE RULE IS ASYMMETRIC. Protection treats a market as open when either
source says so; entries only when both do, the reopen settle period has
passed (THRESHOLDS[class].settle_s) and no unmeasured break window holds.
A disagreement can therefore only hold back an entry, never protection;
the words say which source disagreed ("eToro says open"). Pure: `now` is
an argument, nothing is read but the clock function.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo

from core.exchange_status import market_clock

#: M2 proves eToro's IsMarketOpen flips at the real close.
ETORO_OPEN_PROVEN = False
#: The measured break per regime ("winter" | "summer"): (hour, minute) UTC.
#: Empty until M2 (this winter) and its re-run after the March change.
MEASURED_BREAKS: dict = {}
#: The daily break's length.
BREAK_MINUTES = 5
#: The fixed UTC start the first tables gave the break (22:00 GMT).
TABLE_BREAK_UTC = (22, 0)
#: Classes with eToro's forex daily break.
BREAK_CLASSES = frozenset({"forex"})

_NEW_YORK = ZoneInfo("America/New_York")


class Session(NamedTuple):
    protection_open: bool
    entries_open: bool
    clock_open: bool
    etoro_open: Optional[bool]       # None while unproven or unknown
    in_break_window: bool
    settling: bool
    words: str


def regime(now) -> str:
    """"summer" while New York keeps daylight saving, else "winter"."""
    local = now.astimezone(_NEW_YORK)
    return "summer" if local.dst() else "winter"


def break_windows(now) -> list:
    """The [start, end) UTC windows of the forex daily break on `now`'s UTC
    day and the day before (a window may straddle midnight): the measured
    one for the regime, else every candidate."""
    out = []
    for back in (1, 0):
        day = (now - timedelta(days=back)).date()
        ny_close = datetime(day.year, day.month, day.day, 17, 0,
                            tzinfo=_NEW_YORK).astimezone(dt_tz.utc)
        measured = MEASURED_BREAKS.get(regime(ny_close))
        if measured is not None:
            starts = [datetime(day.year, day.month, day.day, *measured,
                               tzinfo=dt_tz.utc)]
        else:
            starts = [ny_close,
                      datetime(day.year, day.month, day.day,
                               *TABLE_BREAK_UTC, tzinfo=dt_tz.utc)]
        for start in sorted(set(starts)):
            out.append((start, start + timedelta(minutes=BREAK_MINUTES)))
    return out


def _clock(asset_class, symbol, exchange, now) -> dict:
    cls = str(asset_class or "").strip().lower()
    if cls == "index":
        from core.exchange_status import _forex_week
        is_open, reopens, opened = _forex_week(now)
        return {"is_open": is_open, "opened": opened, "modelled": True}
    return market_clock(cls, exchange or "", symbol=symbol or "",
                        now_utc=now)


def session(asset_class, symbol="", *, now, exchange="",
            etoro_open=None) -> Session:
    """The session for `symbol` at `now`, for protection and for entries."""
    from market_data.venue_quotes import thresholds
    cls = str(asset_class or "").strip().lower()
    clock = _clock(cls, symbol, exchange, now)
    clock_open = bool(clock.get("is_open", True))
    venue = etoro_open if (ETORO_OPEN_PROVEN and etoro_open is not None) \
        else None
    protection = clock_open or venue is True
    in_break = cls in BREAK_CLASSES and any(
        start <= now < end for start, end in break_windows(now))
    settle_s = thresholds(cls).settle_s
    opened = clock.get("opened")
    settling = bool(clock_open and settle_s and opened is not None
                    and (now - opened).total_seconds() < settle_s)
    entries = (clock_open and venue is not False and not in_break
               and not settling)
    words = ""
    if venue is not None and venue != clock_open:
        words = "eToro says open" if venue else "eToro says closed"
    elif in_break and clock_open:
        words = "forex daily break (window not yet measured)" \
            if regime(now) not in MEASURED_BREAKS else "forex daily break"
    elif settling:
        words = "settling after the reopen"
    return Session(protection, entries, clock_open, venue, in_break,
                   settling, words)
