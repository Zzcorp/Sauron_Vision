"""ICT killzones and session high/low utilities.

Two session models live here. `KILLZONES_UTC` and the two functions under it
are the original fixed-UTC-clock approximation. Everything under the
"New-York-anchored session model" heading converts to America/New_York first
and is the one to build ICT concepts on — see the convention note there for
why the difference is not cosmetic.
"""
import logging
from datetime import time, timedelta

import pandas as pd


logger = logging.getLogger(__name__)

# SUPERSEDED — kept because `session_high_low` below still reads it, and
# because a scan that predates the switch recorded these names on its cards.
# New work wants `ICT_SESSIONS_NY` and `in_ny_session`: these windows are
# nailed to the UTC clock, so they drift an hour against the New York hours
# they are named after every winter. `signals.rules.smc_rules` scored its
# killzone bonus from this table until it moved to `killzone_for`.
KILLZONES_UTC = {
    "asia":         (time(0, 0),  time(4, 0)),
    "london_open":  (time(7, 0),  time(10, 0)),
    "ny_open":      (time(12, 0), time(15, 0)),
    "london_close": (time(15, 0), time(17, 0)),
}


def in_killzone(ts):
    """Return killzone label or None for a UTC timestamp.

    SUPERSEDED by `in_ny_session`, which converts to New York first. This one
    answers with a fixed UTC clock, so from the first Sunday in November to
    the second Sunday in March it names the window an hour early: 12:00 UTC in
    January is 07:00 in New York, nowhere near the New York open, and this
    function calls it "ny_open".
    """
    t = ts.time() if hasattr(ts, "time") else ts
    for name, (start, end) in KILLZONES_UTC.items():
        if start <= t < end:
            return name
    return None


def session_high_low(df, session="asia"):
    """Return (high, low, hi_idx, lo_idx) for the most recent session window.

    Reads `KILLZONES_UTC`, so it inherits that table's winter drift; the
    NY-anchored replacement for this is `session_windows` below.
    """
    if session not in KILLZONES_UTC:
        return None
    start, end = KILLZONES_UTC[session]
    mask = df.index.map(lambda ts: start <= ts.time() < end)
    sub = df[mask]
    if sub.empty:
        return None
    last_day = sub.index[-1].date()
    today = sub[sub.index.map(lambda ts: ts.date() == last_day)]
    if today.empty:
        return None
    hi = float(today["high"].max())
    lo = float(today["low"].min())
    return hi, lo, today["high"].idxmax(), today["low"].idxmin()


# ── New-York-anchored session model ───────────────────────────────────────────
#
# TIMEZONE CONVENTION, stated once here and relied on by every session-scoped
# detector in this package.
#
# Sauron stores every timestamp in UTC (settings.TIME_ZONE = "UTC",
# USE_TZ = True). A DataFrame index arriving here is therefore UTC whether or
# not it carries a tzinfo: a naive index is localised to UTC, never to the
# server's local zone, because the server's zone is an accident of deployment.
#
# ICT's vocabulary is not UTC. Every window it names — the London open, the New
# York AM killzone, the 10:00-11:00 Silver Bullet — is a New York wall-clock
# window, and New York moves an hour twice a year. 10:00 New York is 14:00 UTC
# from March to November and 15:00 UTC from November to March. KILLZONES_UTC
# above is a fixed-clock approximation and is an hour out for roughly half of
# every year; everything below converts to America/New_York first, so a
# Silver Bullet in January and one in July are the same hour of the trading day.

NY_TZ_NAME = "America/New_York"

# ICT's sessions in New York local time. Asian range runs 20:00 to midnight,
# so it is stored as a wrapping window and `_in_ny_window` handles the wrap
# rather than each caller remembering to.
ICT_SESSIONS_NY = {
    "asia":                 (time(20, 0), time(0, 0)),
    "london":               (time(2, 0), time(5, 0)),
    "ny_am":                (time(8, 30), time(11, 0)),
    "ny_lunch":             (time(12, 0), time(13, 0)),
    "ny_pm":                (time(13, 30), time(16, 0)),
    "silver_bullet_london": (time(3, 0), time(4, 0)),
    "silver_bullet_am":     (time(10, 0), time(11, 0)),
    "silver_bullet_pm":     (time(14, 0), time(15, 0)),
}

# ICT teaches three Silver Bullet hours. The AM one is the default because it
# is the only one that sits inside the New York AM killzone, where the day's
# displacement usually already exists to build a gap out of.
SILVER_BULLET_SESSIONS = (
    "silver_bullet_london", "silver_bullet_am", "silver_bullet_pm",
)
SILVER_BULLET_DEFAULT = "silver_bullet_am"

_NY_TZ = None
_NY_TZ_RESOLVED = False


def new_york_timezone():
    """The America/New_York tzinfo, or None if this machine has no tz database.

    Resolved once and remembered. A missing tz database is a real failure and
    is logged as one — the alternative, quietly substituting a fixed UTC-5,
    would make every session concept in this package wrong for eight months of
    the year while still returning confident-looking answers.
    """
    global _NY_TZ, _NY_TZ_RESOLVED
    if _NY_TZ_RESOLVED:
        return _NY_TZ
    _NY_TZ_RESOLVED = True
    try:
        from zoneinfo import ZoneInfo
        _NY_TZ = ZoneInfo(NY_TZ_NAME)
    except Exception as exc:
        logger.warning(
            "No %s time zone available (%s); session-scoped ICT detectors "
            "will return empty rather than guess an offset.", NY_TZ_NAME, exc,
        )
        _NY_TZ = None
    return _NY_TZ


def new_york_index(df):
    """The frame's index converted to New York local time, or None.

    None means the question cannot be asked of this frame: the index is not
    time-based, or the tz database is missing.
    """
    if df is None or len(df) == 0:
        return None
    tz = new_york_timezone()
    if tz is None:
        return None
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return None
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx.tz_convert(tz)


def _in_ny_window(t, start, end):
    """Half-open [start, end) membership, wrapping past midnight when needed."""
    if start < end:
        return start <= t < end
    if start > end:
        return t >= start or t < end
    return False


def in_ny_session(ts, session):
    """Whether a UTC timestamp falls in a named ICT session, or None.

    None means unanswerable — unknown session name or no tz database — and is
    deliberately distinct from False.
    """
    if session not in ICT_SESSIONS_NY:
        return None
    tz = new_york_timezone()
    if tz is None:
        return None
    stamp = pd.Timestamp(ts)
    if stamp.tz is None:
        stamp = stamp.tz_localize("UTC")
    start, end = ICT_SESSIONS_NY[session]
    return _in_ny_window(stamp.tz_convert(tz).time(), start, end)


def session_windows(df, session, ny_index=None):
    """One entry per calendar occurrence of a session in the frame.

    Each entry is {session, date, positions, start_ts, end_ts} where
    `positions` are positional row indices into `df`, ascending, and `date` is
    the New York date the session *opened* on — so a window that wraps past
    midnight stays one session instead of being split across two days.

    Returns [] when the session is unknown, the tz database is missing, or no
    bar in the frame falls inside the window.
    """
    if session not in ICT_SESSIONS_NY:
        return []
    if ny_index is None:
        ny_index = new_york_index(df)
    if ny_index is None or len(ny_index) == 0:
        return []

    start, end = ICT_SESSIONS_NY[session]
    wraps = start > end
    buckets = {}
    for position, (stamp_time, stamp_date) in enumerate(zip(ny_index.time, ny_index.date)):
        if not _in_ny_window(stamp_time, start, end):
            continue
        # After a wrap, the bars past midnight still belong to the session that
        # opened the previous evening.
        if wraps and stamp_time < end:
            stamp_date = stamp_date - timedelta(days=1)
        buckets.setdefault(stamp_date, []).append(position)

    return [
        {
            "session": session,
            "date": day,
            "positions": positions,
            "start_ts": df.index[positions[0]],
            "end_ts": df.index[positions[-1]],
        }
        for day, positions in sorted(buckets.items())
    ]


def _median_bar_minutes(ny_index):
    """Median spacing of the index in minutes, or None if it cannot be read."""
    if ny_index is None or len(ny_index) < 3:
        return None
    deltas = ny_index.to_series().diff().dropna()
    if deltas.empty:
        return None
    minutes = float(deltas.median().total_seconds()) / 60.0
    return minutes if minutes > 0 else None


def ny_midnight_open(df, ny_index=None, day=None):
    """The New York midnight opening price — ICT's daily reference level.

    Tolerance is the frame's own bar interval: the first bar of the New York
    day counts as the midnight open only if it starts within one bar of
    midnight. That self-calibrates instead of hard-coding a window — on a 4h
    UTC frame the bar that opens the New York day sits 0-3 hours after
    midnight depending on the season, and a fixed tolerance would either accept
    that in July and reject it in January or accept an 09:30 equity open as
    "midnight".

    Returns None when the reference cannot be observed in this frame.
    """
    if ny_index is None:
        ny_index = new_york_index(df)
    if ny_index is None or len(ny_index) == 0:
        return None
    tolerance = _median_bar_minutes(ny_index)
    if tolerance is None:
        return None

    dates = list(ny_index.date)
    target = day if day is not None else dates[-1]
    positions = [i for i, d in enumerate(dates) if d == target]
    if not positions:
        return None
    first = positions[0]
    stamp = ny_index[first]
    offset_minutes = stamp.hour * 60 + stamp.minute
    if offset_minutes > tolerance:
        return None
    return {
        "price": float(df["open"].iloc[first]),
        "idx": first,
        "ts": df.index[first],
        "ny_ts": stamp,
        "date": target,
    }
