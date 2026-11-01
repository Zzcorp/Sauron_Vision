"""A BAR THAT CANNOT HAVE TRADED (2026-10-31).

The bar writer refused only a non-positive timestamp or close
(bot_bars._upsert_rows), so a bar of open 100, high 99, low 0, close 100.5
was stored, and eToro's adapter turned a missing open, high or low into the
text "0". One such bar draws a wick to zero that squashes the whole
autoscaled chart flat, and the bots read it: an ATR stop, a swing, a range.

Every bar that traded holds 0 < low <= min(open, close) <= max(open, close)
<= high with four finite numbers, so refusing the rest drops no real move,
however violent. `possible` is that one test, for the writers and for the
chart; `mark_suspects` is the chart's half (the bar is drawn hollow and
named, never hidden: hiding could hide a real flash move).
"""
import math
from decimal import Decimal, InvalidOperation

#: A bar whose range is this many times its neighbours' median range, and
#: whose feed is not the series' own, is suspect on the chart.
SPIKE_X = 8.0
#: Neighbours each side read for that median.
SPIKE_NEIGHBOURS = 5


def _num(value):
    """A finite float, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def possible(o, h, l, c) -> bool:
    """Whether open, high, low and close can be one traded bar: four finite
    numbers with 0 < low <= min(open, close) <= max(open, close) <= high."""
    o, h, l, c = _num(o), _num(h), _num(l), _num(c)
    if None in (o, h, l, c):
        return False
    return 0 < l <= min(o, c) and max(o, c) <= h


def why_impossible(o, h, l, c) -> str:
    """The words for a bar `possible` refuses ("" when it is possible)."""
    vals = [_num(v) for v in (o, h, l, c)]
    if None in vals:
        return "a price on it is not a number"
    o, h, l, c = vals
    if l <= 0:
        return "its low is at or under zero"
    if not (l <= min(o, c) and max(o, c) <= h):
        return "its low and high do not hold its open and close"
    return ""


def parse(row):
    """(open_ms, open, high, low, close) as Decimals from a Binance-shaped
    kline row, or None when the row is unreadable or cannot have traded."""
    try:
        if not row or len(row) < 6:
            return None
        ts_ms = int(row[0])
        vals = [Decimal(str(row[i])) for i in (1, 2, 3, 4)]
    except (TypeError, ValueError, InvalidOperation, IndexError):
        return None
    if ts_ms <= 0 or not all(v.is_finite() for v in vals):
        return None
    if not possible(*vals):
        return None
    return (ts_ms, *vals)


def finite(bars):
    """(kept, dropped): chart bars whose four prices are finite numbers.
    A NaN cannot be drawn, and one in a JSON reply makes the whole reply
    unreadable to the browser."""
    kept, dropped = [], 0
    for b in bars:
        if all(_num(b.get(k)) is not None
               for k in ("open", "high", "low", "close")):
            kept.append(b)
        else:
            dropped += 1
    return kept, dropped


def _median(values):
    vals = sorted(values)
    n = len(vals)
    if not n:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def mark_suspects(bars, label) -> int:
    """Mark, in place, the chart bars that are suspect: `suspect` holds the
    words ("suspect bar from <feed>: <why>"). A bar is suspect when it
    cannot have traded, or when its range is SPIKE_X times its neighbours'
    median AND its feed (`src`, when a bar carries one) is not the series'
    own (`label`): a real flash move on the series' own feed is never
    marked. Returns how many were marked."""
    marked = 0
    ranges = []
    for b in bars:
        h, l = _num(b.get("high")), _num(b.get("low"))
        ranges.append(h - l if h is not None and l is not None else None)
    for i, b in enumerate(bars):
        src = b.get("src") or label
        why = why_impossible(b.get("open"), b.get("high"), b.get("low"),
                             b.get("close"))
        if not why and src != label and ranges[i] is not None:
            lo, hi = max(0, i - SPIKE_NEIGHBOURS), i + SPIKE_NEIGHBOURS + 1
            near = [r for j, r in enumerate(ranges[lo:hi], start=lo)
                    if j != i and r is not None and r > 0]
            med = _median(near)
            if med and ranges[i] > SPIKE_X * med:
                why = (f"its range is {ranges[i] / med:.0f} times its "
                       f"neighbours'")
        if why:
            b["suspect"] = f"suspect bar from {src}: {why}"
            marked += 1
    return marked
