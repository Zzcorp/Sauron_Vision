"""ICT killzones and session high/low utilities."""
from datetime import time


KILLZONES_UTC = {
    "asia":         (time(0, 0),  time(4, 0)),
    "london_open":  (time(7, 0),  time(10, 0)),
    "ny_open":      (time(12, 0), time(15, 0)),
    "london_close": (time(15, 0), time(17, 0)),
}


def in_killzone(ts):
    """Return killzone label or None for a UTC timestamp."""
    t = ts.time() if hasattr(ts, "time") else ts
    for name, (start, end) in KILLZONES_UTC.items():
        if start <= t < end:
            return name
    return None


def session_high_low(df, session="asia"):
    """Return (high, low, hi_idx, lo_idx) for the most recent session window."""
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
