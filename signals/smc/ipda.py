"""IPDA dealing ranges and standard-deviation projections.

ICT's Interbank Price Delivery Algorithm is a claim about *where* price is
working: between a high and a low it has already set, on a lookback of 20, 40
or 60 days. Everything inside that range is premium or discount relative to
its equilibrium, and every objective outside it is a multiple of the leg that
left it.

Two things this module refuses to do. It will not invent a bars-per-day when
the index spacing cannot be read — a "20 day" lookback measured in the wrong
unit is worse than no lookback at all. And it will not project from a leg it
cannot find: a sweep that produced no measurable displacement has no leg to
take multiples of, so `project_from_swept_leg` returns None rather than
projecting off the sweep bar's own range.
"""
import numpy as np

from .displacement import (
    DEFAULT_ATR_PERIOD,
    DISPLACEMENT_MIN_ATR,
    detect_displacement_legs,
)
from .structure import premium_discount


# ICT's three IPDA lookbacks, in days. They are the lookbacks he quotes; the
# reason all three are kept is that they disagree, and the disagreement is the
# information — a high that is the 20-day extreme but not the 60-day one is a
# different level from one that is both.
IPDA_LOOKBACK_DAYS = (20, 40, 60)

# Standard deviations of the swept leg, ICT's objective ladder. 1.0 is the leg
# mirrored once past its own end, which is where symmetrical price projection
# puts the first objective; 4.0 is where he stops quoting them.
IPDA_PROJECTION_MULTIPLES = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)

# Fewer bars than this and the "range" is one move with a top and a bottom, not
# an area price has been delivered inside. Ten bars is the smallest window that
# can hold a high, a low, and a return to either.
MIN_RANGE_BARS = 10


def bars_per_day(df):
    """Bars per calendar day from the index spacing, or None if unreadable.

    The *median* gap is used, not the mean, so weekends and holidays — which
    are genuine multi-day gaps in an equities or futures feed — do not drag a
    4h frame into claiming six-hour bars.
    """
    if df is None or len(df) < 3:
        return None
    try:
        deltas = df.index.to_series().diff().dropna()
        if deltas.empty:
            return None
        seconds = float(deltas.median().total_seconds())
    except (AttributeError, TypeError, ValueError):
        # A non-datetime index (a RangeIndex from a hand-built frame, say) has
        # no spacing in time. That is a legitimate frame to hold OHLC in, so it
        # is not an error — it just means the day-based lookbacks cannot be
        # expressed in bars, and every caller here degrades to bar counts.
        return None
    if seconds <= 0:
        return None
    return 86400.0 / seconds


def dealing_range(df, lookback_bars, end_idx=None, label=None, require_full=False):
    """The high/low/equilibrium of the last `lookback_bars` bars, or None.

    With `require_full` the frame must actually hold the whole lookback. That
    is on for the day-labelled IPDA ranges and off for a plain bar count: a
    range labelled "20 day" that quietly turned out to be eight hours of data
    is a lie about what was measured, whereas "the last 60 bars, of which the
    frame had 26" is reported honestly through the `bars` field.

    None when the window is shorter than `MIN_RANGE_BARS` or has no height —
    both are "cannot answer", and a range of zero width would make every
    premium/discount reading downstream a coin flip dressed as a measurement.
    """
    if df is None or len(df) == 0 or not lookback_bars:
        return None
    if end_idx is None:
        end_idx = len(df) - 1
    if end_idx < 0 or end_idx >= len(df):
        return None
    start_idx = end_idx - int(lookback_bars) + 1
    if require_full and start_idx < 0:
        return None
    start_idx = max(0, start_idx)
    if end_idx - start_idx + 1 < MIN_RANGE_BARS:
        return None

    highs = df["high"].values[start_idx:end_idx + 1]
    lows = df["low"].values[start_idx:end_idx + 1]
    high = float(highs.max())
    low = float(lows.min())
    if high <= low:
        return None

    high_idx = start_idx + int(np.argmax(highs))
    low_idx = start_idx + int(np.argmin(lows))
    close = float(df["close"].iloc[end_idx])
    zone, position = premium_discount(high, low, close)
    return {
        "label": label,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "bars": end_idx - start_idx + 1,
        "high": high,
        "low": low,
        "high_idx": high_idx,
        "low_idx": low_idx,
        "equilibrium": (high + low) / 2,
        "range": high - low,
        "close": close,
        "zone": zone,
        "position": position,
        "ts_start": df.index[start_idx],
        "ts_end": df.index[end_idx],
    }


def ipda_dealing_ranges(df, days=IPDA_LOOKBACK_DAYS, end_idx=None):
    """One dealing range per IPDA lookback, shortest first.

    Returns [] when the index spacing cannot be read, and silently omits any
    lookback the frame is too short to cover — a 20-day range asked of 5 days
    of bars would just be the whole frame wearing a 20-day label.
    """
    per_day = bars_per_day(df)
    if per_day is None:
        return []
    ranges = []
    for day_count in days:
        lookback = int(round(day_count * per_day))
        found = dealing_range(df, lookback, end_idx=end_idx,
                              label=f"ipda_{day_count}d", require_full=True)
        if found is not None:
            found["lookback_days"] = day_count
            ranges.append(found)
    return ranges


def std_dev_projections(anchor, leg_end, multiples=IPDA_PROJECTION_MULTIPLES):
    """Prices at multiples of the leg measured from `anchor` to `leg_end`.

    The leg is one standard deviation by definition, so multiple 1.0 lands
    exactly on `leg_end` and everything above it projects onward in the same
    direction. Returns None when the leg has no length to multiply.
    """
    if anchor is None or leg_end is None:
        return None
    span = float(leg_end) - float(anchor)
    if span == 0:
        return None
    return [
        {"multiple": float(m), "price": float(anchor) + float(m) * span}
        for m in multiples
    ]


def project_from_swept_leg(df, sweep, multiples=IPDA_PROJECTION_MULTIPLES,
                           atr_period=DEFAULT_ATR_PERIOD,
                           min_atr_multiple=DISPLACEMENT_MIN_ATR,
                           search_bars=20, displacement_legs=None):
    """Projections measured from a sweep and the displacement that followed it.

    The anchor is the sweep's wick — the price at which the liquidity was
    taken, which is where the algorithm started delivering from. The first
    standard deviation runs to the far end of the first displacement leg after
    the sweep, and the ladder projects onward from there.

    Returns None when no displacement followed the sweep within `search_bars`.
    A sweep with no leg behind it is a sweep that has not been paid for yet;
    projecting off the sweep bar alone would put targets on the chart that
    nothing has been delivered toward.
    """
    if df is None or len(df) == 0 or not sweep:
        return None
    sweep_idx = sweep.get("idx")
    if sweep_idx is None or sweep_idx >= len(df) - 1:
        return None

    if sweep.get("type") == "SWEEP_HIGH":
        anchor = float(sweep.get("wick_high", df["high"].iloc[sweep_idx]))
        direction = "down"
    elif sweep.get("type") == "SWEEP_LOW":
        anchor = float(sweep.get("wick_low", df["low"].iloc[sweep_idx]))
        direction = "up"
    else:
        return None

    horizon = min(len(df) - 1, sweep_idx + search_bars)
    if displacement_legs is None:
        displacement_legs = detect_displacement_legs(
            df, atr_period=atr_period, min_atr_multiple=min_atr_multiple,
            start_idx=sweep_idx + 1, end_idx=horizon,
        )
    leg = next(
        (d for d in displacement_legs
         if d["direction"] == direction
         and d["start_idx"] > sweep_idx and d["end_idx"] <= horizon),
        None,
    )
    if leg is None:
        return None

    window = slice(leg["start_idx"], leg["end_idx"] + 1)
    if direction == "down":
        leg_end = float(df["low"].values[window].min())
    else:
        leg_end = float(df["high"].values[window].max())

    levels = std_dev_projections(anchor, leg_end, multiples)
    if levels is None:
        return None
    return {
        "anchor": anchor,
        "anchor_idx": sweep_idx,
        "anchor_ts": df.index[sweep_idx],
        "leg_end": leg_end,
        "leg_end_idx": leg["end_idx"],
        "direction": direction,
        "displacement": leg,
        "levels": levels,
    }
