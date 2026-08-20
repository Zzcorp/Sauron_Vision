"""Displacement — the energy test that separates a real break from a drift.

`structure.detect_market_structure_breaks` calls a break on a single close
beyond a swing, with no size, body or velocity requirement, so a one-tick
drift and a violent expansion arrive at the caller as the same event. ICT's
answer is displacement: an energetic, largely one-directional move that leaves
an imbalance behind it. Displacement is what makes a break worth trading, so
this module measures it and hands it back as a separate fact.

Nothing here mutates its inputs. `qualify_breaks_with_displacement` returns
*copies* of the break dicts with the displacement fields added, so every
existing caller of `detect_market_structure_breaks` keeps receiving exactly
the dicts it received before.

No lookahead anywhere: a leg measured at bar i consults bars at or before i
only. That has one consequence worth knowing about — the imbalance a
displacement leaves is often only visible on the bar *after* the leg closes,
which is why the imbalance is scored but not required by default.
"""
import numpy as np

from .pivots import atr as _atr_series


DEFAULT_ATR_PERIOD = 14

# A leg has to travel at least this many ATRs, measured open-of-leg to
# close-of-leg and signed, before we call it displacement. ATR is the *average*
# bar, so roughly half of all single bars clear 1.0x unaided and a three-bar
# window clears it constantly; 1.5x is the first multiple that a run of
# ordinary bars cannot reach unless they agree on direction, which is precisely
# the property being tested.
DISPLACEMENT_MIN_ATR = 1.5

# Bodies must own at least half of the leg's total range. A move that is more
# wick than body is a level being fought over, not price being delivered one
# way; at 0.5 the opens and closes account for more of the leg than the
# extremes do, which is the cheapest honest statement of "one-directional".
DISPLACEMENT_MIN_BODY_RATIO = 0.5

# ICT's displacement is a one-to-three candle expansion. Three is also the
# minimum a fair value gap needs (the gap is between bar i-1 and bar i+1).
# Past three bars we would be measuring trend, which `current_trend` already
# answers, and the ATR multiple would start clearing on drift alone.
DISPLACEMENT_MAX_BARS = 3

# Where the size component of the score tops out. 3.0 ATR is twice the entry
# threshold: a leg that doubles the minimum has already made its point, and
# letting the score keep climbing would let one outlier candle outrank a leg
# that is strong on all three components.
DISPLACEMENT_SCORE_SATURATION_ATR = 3.0

# Size carries the most weight because it is the only component that scales
# with how far the market actually delivered; body ratio and the imbalance are
# confirmations of *how* it delivered and are close to binary in practice.
DISPLACEMENT_SCORE_WEIGHTS = {"size": 0.5, "body": 0.3, "imbalance": 0.2}


def atr_at(df, idx, atr_values=None, period=DEFAULT_ATR_PERIOD):
    """ATR at bar `idx`, or None when it has not been measured there.

    `pivots.atr` fills the first `period - 1` slots with 0.0 because the
    average has nothing to average yet. A zero there means NOT MEASURED, never
    "no volatility" — treating it as a number would either raise on the divide
    or manufacture an infinite ATR multiple out of a warm-up artefact.
    """
    if atr_values is None:
        atr_values = _atr_series(df, period)
    if idx is None or idx < 0 or idx >= len(atr_values):
        return None
    value = float(atr_values[idx])
    if value <= 0:
        return None
    return value


def _leg_imbalance(df, start_idx, end_idx, direction):
    """First fair value gap a bar of the leg closed, or None.

    Same three-bar rule as `zones.detect_fvgs`, and kept strictly causal: the
    gap is credited to the leg when the bar that *completed* it — the third of
    the three — belongs to [start_idx, end_idx], so the middle bar runs from
    `start_idx - 1` to `end_idx - 1` and nothing past `end_idx` is ever read.

    Requiring all three bars inside the leg looked tidier and was wrong: a
    one-bar leg spans two bars once its left neighbour is counted, a gap needs
    three, and the loop simply never ran. Every single-bar displacement — the
    violent expansion candle this module exists to find — therefore scored zero
    on the imbalance component no matter what it had actually left behind.

    Only a gap that points the same way as the leg counts: a bearish gap inside
    an up leg is a leftover from the move before, not this leg's imbalance.
    """
    highs = df["high"].values
    lows = df["low"].values
    for i in range(max(start_idx - 1, 1), end_idx):
        if direction != "down" and highs[i - 1] < lows[i + 1]:
            return {
                "type": "FVG_BULL", "idx": i,
                "low": float(highs[i - 1]), "high": float(lows[i + 1]),
            }
        if direction != "up" and lows[i - 1] > highs[i + 1]:
            return {
                "type": "FVG_BEAR", "idx": i,
                "low": float(highs[i + 1]), "high": float(lows[i - 1]),
            }
    return None


def measure_displacement(df, end_idx, direction=None,
                         max_bars=DISPLACEMENT_MAX_BARS,
                         atr_values=None, atr_period=DEFAULT_ATR_PERIOD,
                         min_atr_multiple=DISPLACEMENT_MIN_ATR,
                         min_body_ratio=DISPLACEMENT_MIN_BODY_RATIO,
                         require_imbalance=False):
    """Measure the strongest displacement leg ending on bar `end_idx`.

    Windows of 1..`max_bars` bars ending at `end_idx` are measured, and the
    best *qualifying* one is returned — the one that clears both gates, not
    merely the one that scores highest. The distinction is the whole answer:
    score and qualification are separate axes, a longer window can outscore a
    shorter one on size while failing the body-ratio gate, and picking by score
    first made such a window overwrite a shorter window that genuinely passed.
    The leg then came back reported as "not displacement" with a displacement
    sitting inside it. Only when no window qualifies does the highest-scoring
    one stand in, so the caller still gets a measured "no" rather than a None
    it has to interpret.

    Pass `direction` ("up"/"down") to ask about travel one specific way — the
    ATR multiple is then signed in that direction and goes negative for a leg
    that ran the other way, so a BOS_UP can never be qualified by a down leg
    that happened to be large.

    Returns None when the question cannot be answered: index out of range, an
    ATR that has not warmed up, or bars with no range at all. Returns a dict
    with ``is_displacement`` False when it *was* measured and simply did not
    qualify — those two outcomes are different answers and are kept distinct.
    """
    n = len(df)
    if n == 0 or end_idx is None or end_idx < 0 or end_idx >= n:
        return None
    atr_here = atr_at(df, end_idx, atr_values, atr_period)
    if atr_here is None:
        return None

    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    candidates = []
    for bars in range(1, max_bars + 1):
        start_idx = end_idx - bars + 1
        if start_idx < 0:
            break
        window = slice(start_idx, end_idx + 1)
        total_range = float(highs[window].sum() - lows[window].sum())
        if total_range <= 0:
            continue
        body_ratio = float(np.abs(closes[window] - opens[window]).sum()) / total_range

        net_move = float(closes[end_idx] - opens[start_idx])
        if direction is None:
            leg_dir = "up" if net_move > 0 else ("down" if net_move < 0 else None)
            signed_move = abs(net_move)
        else:
            leg_dir = direction
            signed_move = net_move if direction == "up" else -net_move
        atr_multiple = signed_move / atr_here

        imbalance = _leg_imbalance(df, start_idx, end_idx, leg_dir)
        size_part = max(0.0, min(atr_multiple / DISPLACEMENT_SCORE_SATURATION_ATR, 1.0))
        score = (
            DISPLACEMENT_SCORE_WEIGHTS["size"] * size_part
            + DISPLACEMENT_SCORE_WEIGHTS["body"] * max(0.0, min(body_ratio, 1.0))
            + DISPLACEMENT_SCORE_WEIGHTS["imbalance"] * (1.0 if imbalance else 0.0)
        )
        qualifies = (
            leg_dir is not None
            and atr_multiple >= min_atr_multiple
            and body_ratio >= min_body_ratio
            and (imbalance is not None or not require_imbalance)
        )
        candidate = {
            "start_idx": start_idx,
            "end_idx": end_idx,
            "bars": bars,
            "direction": leg_dir,
            "net_move": net_move,
            "atr": atr_here,
            "atr_multiple": atr_multiple,
            "body_ratio": body_ratio,
            "imbalance": imbalance,
            "has_imbalance": imbalance is not None,
            "score": score,
            "is_displacement": qualifies,
            "ts_start": df.index[start_idx],
            "ts_end": df.index[end_idx],
        }
        candidates.append(candidate)
    if not candidates:
        return None

    # Ties go to the shorter window: the same energy delivered in fewer bars is
    # the more violent leg, and the tighter one to draw a zone on.
    def rank(leg):
        return (leg["score"], -leg["bars"])

    qualifying = [c for c in candidates if c["is_displacement"]]
    return max(qualifying or candidates, key=rank)


def detect_displacement_legs(df, max_bars=DISPLACEMENT_MAX_BARS,
                             atr_period=DEFAULT_ATR_PERIOD,
                             min_atr_multiple=DISPLACEMENT_MIN_ATR,
                             min_body_ratio=DISPLACEMENT_MIN_BODY_RATIO,
                             require_imbalance=False,
                             start_idx=None, end_idx=None):
    """All qualifying displacement legs in the frame, earliest first.

    Overlapping legs are collapsed to the highest-scoring one, the same way
    `zones.detect_ranges` keeps the largest of a set of overlapping ranges: a
    three-bar expansion would otherwise be reported once per bar it covers.
    Returns [] when nothing qualifies or the frame is too short to measure.
    """
    n = len(df)
    if n == 0:
        return []
    atr_values = _atr_series(df, atr_period)
    lo = 0 if start_idx is None else max(0, start_idx)
    hi = n - 1 if end_idx is None else min(n - 1, end_idx)

    found = []
    for i in range(lo, hi + 1):
        leg = measure_displacement(
            df, i, max_bars=max_bars, atr_values=atr_values,
            atr_period=atr_period, min_atr_multiple=min_atr_multiple,
            min_body_ratio=min_body_ratio, require_imbalance=require_imbalance,
        )
        if leg and leg["is_displacement"]:
            found.append(leg)
    if not found:
        return []

    found.sort(key=lambda leg: leg["score"], reverse=True)
    kept = []
    for leg in found:
        overlaps = any(
            not (leg["end_idx"] < k["start_idx"] or leg["start_idx"] > k["end_idx"])
            for k in kept
        )
        if not overlaps:
            kept.append(leg)
    kept.sort(key=lambda leg: leg["start_idx"])
    return kept


def qualify_breaks_with_displacement(df, breaks, max_bars=DISPLACEMENT_MAX_BARS,
                                     atr_period=DEFAULT_ATR_PERIOD,
                                     min_atr_multiple=DISPLACEMENT_MIN_ATR,
                                     min_body_ratio=DISPLACEMENT_MIN_BODY_RATIO,
                                     require_imbalance=False):
    """Copies of `breaks` carrying the displacement that produced each one.

    Added keys:
      ``displacement``       the leg dict, or None when it was not measurable
      ``displaced``          True/False, or None when it was not measurable
      ``displacement_score`` 0..1, or None when it was not measurable

    `displaced` is deliberately tri-state. A break sitting inside the ATR
    warm-up cannot be judged, and answering False there would quietly retire
    every early break in the frame as a drift.

    The input dicts are never touched, so callers already consuming
    `detect_market_structure_breaks` are unaffected.
    """
    if not breaks:
        return []
    atr_values = _atr_series(df, atr_period)
    out = []
    for b in breaks:
        direction = "up" if b.get("type") == "BOS_UP" else "down"
        leg = measure_displacement(
            df, b.get("idx"), direction=direction, max_bars=max_bars,
            atr_values=atr_values, atr_period=atr_period,
            min_atr_multiple=min_atr_multiple, min_body_ratio=min_body_ratio,
            require_imbalance=require_imbalance,
        )
        qualified = dict(b)
        qualified["displacement"] = leg
        qualified["displaced"] = None if leg is None else leg["is_displacement"]
        qualified["displacement_score"] = None if leg is None else leg["score"]
        out.append(qualified)
    return out
