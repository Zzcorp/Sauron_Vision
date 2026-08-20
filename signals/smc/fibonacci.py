"""Fibonacci retracement geometry and ICT's Optimal Trade Entry band.

Convention used everywhere in this module: a leg is described by its two
extremes plus the direction the *impulse* travelled, and `ratio` is always the
fraction of that leg retraced back toward its origin. 0.0 sits at the end of
the impulse, 1.0 back at its origin, and negative ratios project beyond the
impulse. That single convention holds for up legs and down legs alike, so a
caller never has to remember which extreme "0" means today.

Every function returns None rather than a number when the leg has no range —
a leg whose high equals its low has no retracement geometry, and answering
0.5 or 0.0 there would be a fabricated level a trader could act on.
"""
from .displacement import (
    DEFAULT_ATR_PERIOD,
    DISPLACEMENT_MIN_ATR,
    detect_displacement_legs,
)
from .pivots import atr as _atr_series


# ICT quotes the Optimal Trade Entry band as 62%-79%, not the textbook
# 61.8%-78.6%. The rounding is deliberate and in the trader's favour: it means
# a wick that stops one tick short of 61.8 is not scored as a miss.
OTE_MIN_RATIO = 0.62
OTE_MAX_RATIO = 0.79

# 70.5% is exactly the arithmetic midpoint of 62 and 79. That is the whole
# claim behind the "sweet spot" — it is the deepest point of the band that is
# still equidistant from both edges, so a fill there is the one least likely
# to be missed by a shallow retrace or run over by a deep one.
OTE_SWEET_SPOT = 0.705

# The levels a trader actually marks up. 0.618/0.786 are the Fibonacci
# numbers; 0.62/0.705/0.79 are ICT's band. Both are listed because they answer
# different questions and are only a few basis points apart on most legs.
RETRACEMENT_LEVELS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.62, 0.705, 0.786, 0.79, 1.0)

# ICT's symmetrical price projections, expressed in the same ratio convention:
# negative means beyond the end of the impulse. -1.0 is the leg mirrored past
# its own extreme, which is the standard first objective.
EXTENSION_LEVELS = (-0.27, -0.5, -0.62, -1.0, -2.0)

# The stop sits this fraction of the leg beyond the origin. A stop exactly on
# the origin is the level every other retracement trader has chosen, so it is
# the level the market reaches for; 5% of the leg puts it past that shelf. The
# cost is honest and small: from the 70.5% sweet spot to the 0% objective, R
# falls from 2.4 to 2.0.
OTE_STOP_BUFFER_RATIO = 0.05

# An impulse smaller than this is not worth measuring an OTE on. The band
# spans 17% of the leg (79 - 62), so a 2 ATR leg yields a zone about a third of
# an average bar wide — already the narrowest zone a single bar can tag without
# swallowing it whole. Below 2 ATR the entry and the stop stop being distinct.
OTE_MIN_LEG_ATR = 2.0


def _leg_range(leg_low, leg_high):
    """Leg height, or None when the leg is degenerate or inverted."""
    if leg_low is None or leg_high is None:
        return None
    span = float(leg_high) - float(leg_low)
    if span <= 0:
        return None
    return span


def retracement_price(leg_low, leg_high, direction, ratio):
    """Price at `ratio` of the leg retraced, or None if the leg has no range."""
    span = _leg_range(leg_low, leg_high)
    if span is None or direction not in ("up", "down"):
        return None
    if direction == "up":
        return float(leg_high) - ratio * span
    return float(leg_low) + ratio * span


def retracement_levels(leg_low, leg_high, direction, ratios=RETRACEMENT_LEVELS):
    """{ratio: price} for the requested ratios, or None if the leg is flat."""
    span = _leg_range(leg_low, leg_high)
    if span is None or direction not in ("up", "down"):
        return None
    return {r: retracement_price(leg_low, leg_high, direction, r) for r in ratios}


def retracement_ratio(leg_low, leg_high, direction, price):
    """How far `price` has retraced the leg, or None if the leg is flat.

    0.0 = still at the impulse extreme, 1.0 = all the way back at the origin,
    above 1.0 = the leg has been undone, below 0.0 = the impulse extended.
    """
    span = _leg_range(leg_low, leg_high)
    if span is None or direction not in ("up", "down") or price is None:
        return None
    if direction == "up":
        return (float(leg_high) - float(price)) / span
    return (float(price) - float(leg_low)) / span


def ote_zone(leg_low, leg_high, direction):
    """The 62-79% band with its 70.5% sweet spot, or None if the leg is flat.

    `low`/`high` are always ordered as prices, not as ratios, so the caller can
    range-test without knowing which way the impulse ran.
    """
    span = _leg_range(leg_low, leg_high)
    if span is None or direction not in ("up", "down"):
        return None
    edge_a = retracement_price(leg_low, leg_high, direction, OTE_MIN_RATIO)
    edge_b = retracement_price(leg_low, leg_high, direction, OTE_MAX_RATIO)
    return {
        "direction": direction,
        "low": min(edge_a, edge_b),
        "high": max(edge_a, edge_b),
        "sweet_spot": retracement_price(leg_low, leg_high, direction, OTE_SWEET_SPOT),
        "leg_low": float(leg_low),
        "leg_high": float(leg_high),
        "leg_range": span,
    }


def in_ote(leg_low, leg_high, direction, price):
    """True/False, or None when the leg has no range to measure against."""
    ratio = retracement_ratio(leg_low, leg_high, direction, price)
    if ratio is None:
        return None
    return OTE_MIN_RATIO <= ratio <= OTE_MAX_RATIO


def find_impulse_legs(df, swings, require_displacement=True,
                      min_leg_atr=OTE_MIN_LEG_ATR, atr_period=DEFAULT_ATR_PERIOD,
                      min_atr_multiple=DISPLACEMENT_MIN_ATR):
    """Impulse legs built from consecutive opposite-type swings.

    A leg runs low -> high (direction "up") or high -> low ("down"). With
    `require_displacement` on — the ICT reading — a leg only counts if a
    displacement leg sits inside its span; a slow drift between two pivots is a
    range being traversed, not an impulse anyone is retracing.

    Returns [] when there are no swings, or when ATR has not warmed up far
    enough to say whether any leg is large enough to matter.
    """
    if not swings or len(swings) < 2 or len(df) == 0:
        return []
    atr_values = _atr_series(df, atr_period)
    displacements = (
        detect_displacement_legs(df, atr_period=atr_period,
                                 min_atr_multiple=min_atr_multiple)
        if require_displacement else []
    )

    legs = []
    for prev, curr in zip(swings, swings[1:]):
        if prev["type"] == curr["type"] or curr["idx"] <= prev["idx"]:
            continue
        direction = "up" if prev["type"] == "L" else "down"
        leg_low = min(prev["price"], curr["price"])
        leg_high = max(prev["price"], curr["price"])
        span = _leg_range(leg_low, leg_high)
        if span is None:
            continue

        # ATR at the leg's end is the volatility the leg was delivered into.
        # A zero there is the warm-up sentinel, so the leg is unmeasurable and
        # is dropped rather than waved through on an assumed volatility.
        atr_end = float(atr_values[curr["idx"]]) if curr["idx"] < len(atr_values) else 0.0
        if atr_end <= 0 or span / atr_end < min_leg_atr:
            continue

        inner = [
            d for d in displacements
            if d["direction"] == direction
            and d["start_idx"] >= prev["idx"] and d["end_idx"] <= curr["idx"]
        ]
        if require_displacement and not inner:
            continue

        legs.append({
            "start_idx": prev["idx"],
            "end_idx": curr["idx"],
            "direction": direction,
            "origin": float(prev["price"]),
            "extreme": float(curr["price"]),
            "low": leg_low,
            "high": leg_high,
            "range": span,
            "atr_multiple": span / atr_end,
            "displacement": max(inner, key=lambda d: d["score"]) if inner else None,
            "ts_start": df.index[prev["idx"]],
            "ts_end": df.index[curr["idx"]],
        })
    return legs


def detect_ote_entries(df, swings, current_idx=None, require_displacement=True,
                       atr_period=DEFAULT_ATR_PERIOD):
    """Setups where the current bar is trading inside a live OTE band.

    A leg is live until price closes back through its origin — at that point
    the retracement is a reversal and the band means nothing. Entry is the
    70.5% sweet spot, the stop sits `OTE_STOP_BUFFER_RATIO` of the leg beyond
    the origin, and the objective is the leg's own extreme.

    Returns [] when nothing qualifies. Setups whose geometry does not produce a
    positive risk leg are dropped rather than shipped with a zero R.
    """
    setups = []
    n = len(df)
    if n == 0 or not swings:
        return setups
    if current_idx is None:
        current_idx = n - 1
    if current_idx < 1 or current_idx >= n:
        return setups

    lows = df["low"].values
    highs = df["high"].values
    bar_low = float(lows[current_idx])
    bar_high = float(highs[current_idx])

    for leg in find_impulse_legs(df, swings, require_displacement=require_displacement,
                                 atr_period=atr_period):
        if leg["end_idx"] >= current_idx:
            continue
        after = slice(leg["end_idx"] + 1, current_idx + 1)
        if leg["direction"] == "up":
            if float(lows[after].min()) <= leg["origin"]:
                continue  # origin taken out: the leg is undone, not retracing
        else:
            if float(highs[after].max()) >= leg["origin"]:
                continue

        zone = ote_zone(leg["low"], leg["high"], leg["direction"])
        if zone is None:
            continue
        # Overlap, not containment: an OTE tap is a wick reaching into the
        # band, and demanding the whole bar sit inside it would reject exactly
        # the fast tap-and-reject bars the band exists to catch.
        if bar_low > zone["high"] or bar_high < zone["low"]:
            continue

        entry = zone["sweet_spot"]
        buffer_amount = OTE_STOP_BUFFER_RATIO * leg["range"]
        if leg["direction"] == "up":
            stop = leg["origin"] - buffer_amount
            target = leg["extreme"]
            risk = entry - stop
            reward = target - entry
            side = "LONG"
            invalidation = f"close below {stop:.4f}"
            deepest = retracement_ratio(leg["low"], leg["high"], "up", bar_low)
        else:
            stop = leg["origin"] + buffer_amount
            target = leg["extreme"]
            risk = stop - entry
            reward = entry - target
            side = "SHORT"
            invalidation = f"close above {stop:.4f}"
            deepest = retracement_ratio(leg["low"], leg["high"], "down", bar_high)
        if risk <= 0 or reward <= 0:
            continue

        setups.append({
            "setup": "OTE",
            "direction": side,
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(reward / risk, 2),
            "ote": zone,
            "leg": leg,
            "deepest_retracement": deepest,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": invalidation,
            "components": ["impulse_leg", "displacement", "ote_62_79"]
            if leg["displacement"] else ["impulse_leg", "ote_62_79"],
        })
    return setups
