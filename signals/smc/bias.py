"""Daily bias and draw on liquidity — the piece that makes the rest coherent.

Every other detector in this package is happy to fire in both directions on
the same chart. That is the correct behaviour for a primitive and the wrong
behaviour for a trading day: a sweep-and-reverse long and an order-block short
cannot both be the plan. Bias is the filter that resolves it — a direction
taken from higher-timeframe structure and the liquidity the market has left
unclaimed, against which setups can be kept or dropped.

Draw on liquidity is the other half of the same answer. A bias with no
destination is an opinion; a bias plus the nearest unswept pool in that
direction is a target you can measure a trade against.

The honest-failure rule this module leans on hardest: `bias` is None when the
evidence does not support a direction, and `filter_setups_to_bias` treats a
None bias as no filter at all. An unmeasured bias is not evidence against
either side, and letting it veto every setup would turn a missing measurement
into a silent kill switch.
"""
from .displacement import (
    DEFAULT_ATR_PERIOD,
    atr_at,
    qualify_breaks_with_displacement,
)
from .ipda import dealing_range, ipda_dealing_ranges
from .liquidity import find_equal_levels
from .pivots import atr as _atr_series
from .structure import current_trend, detect_market_structure_breaks


# Confidence weights. Structure carries the most because a bias that disagrees
# with the higher-timeframe sequence is a counter-trend trade wearing a bias's
# clothes. Location is next: it decides whether the direction is being taken at
# a discount or chased at a premium, which changes the trade's arithmetic more
# than anything else on the list. Pool strength and room to run are
# refinements — real, but neither is a thesis on its own.
BIAS_W_STRUCTURE = 0.4
BIAS_W_LOCATION = 0.3
BIAS_W_POOL_STRENGTH = 0.2
BIAS_W_ROOM = 0.1

# The draw has to be at least one average bar away. Closer than that and the
# market can reach it inside the next candle, so there is nothing left to be
# paid for the trip and the bias is describing something already delivered.
BIAS_MIN_ROOM_ATR = 1.0

# Two touches is what separates a pool from a swing. A single swing high is one
# trader's stop; equal highs are a shelf of them, and shelves are what get run.
BIAS_POOL_MIN_TOUCHES = 2

# Fallback dealing range when the index spacing cannot be read and the IPDA
# day-based lookbacks are therefore unavailable. 60 bars is a quarter of the
# 240-bar frame `scan_symbol` typically works with — long enough to hold a
# structure, short enough that the equilibrium still describes where price is
# working now rather than last quarter.
BIAS_FALLBACK_RANGE_BARS = 60


def unswept_pools(df, swings, current_idx=None, tolerance_pct=0.001):
    """Swing highs never traded above and swing lows never traded below.

    Each pool carries `touches`: how many swings sit within `tolerance_pct` of
    it, via `liquidity.find_equal_levels`. One touch is a swing, two or more is
    a shelf, and the difference matters to how hard the market pulls toward it.

    Returns [] when there are no swings — no swings means no pools have been
    identified, which is not the same as the market having no liquidity, and no
    caller should read the empty list as the latter.
    """
    if df is None or len(df) == 0 or not swings:
        return []
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 0 or current_idx >= len(df):
        return []

    highs = df["high"].values
    lows = df["low"].values

    # Clip before clustering, not just before the pool loop. `find_equal_levels`
    # counts touches across the whole list it is handed, so a swing printed
    # after `current_idx` sitting at the same price would raise a pool's
    # `touches` — and `daily_bias` pays BIAS_W_POOL_STRENGTH for that count. The
    # loop below already refuses those swings as pools; they must not count as
    # evidence about the pools either.
    visible = [s for s in swings if s["idx"] < current_idx]
    touches_by_position = {}
    for cluster in find_equal_levels(visible, tolerance_pct=tolerance_pct):
        for position in cluster["swing_indices"]:
            touches_by_position[position] = cluster["count"]

    pools = []
    for position, swing in enumerate(visible):
        after = slice(swing["idx"] + 1, current_idx + 1)
        if swing["type"] == "H":
            if float(highs[after].max()) > swing["price"]:
                continue
            side = "buy_side"
        else:
            if float(lows[after].min()) < swing["price"]:
                continue
            side = "sell_side"
        pools.append({
            "side": side,
            "price": float(swing["price"]),
            "swing_idx": swing["idx"],
            "ts": df.index[swing["idx"]],
            "label": swing.get("label"),
            "touches": touches_by_position.get(position, 1),
        })
    return pools


def draw_on_liquidity(df, swings, current_idx=None, pools=None):
    """The nearest unswept pool on each side of current price.

    Returns None when the question cannot be asked at all (no frame, no
    swings). A side whose value is None means no unswept pool was found there —
    the market has already taken everything on that side, which is itself a
    reason to expect the draw to be the other way.
    """
    if df is None or len(df) == 0 or not swings:
        return None
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 0 or current_idx >= len(df):
        return None
    if pools is None:
        pools = unswept_pools(df, swings, current_idx)

    price = float(df["close"].iloc[current_idx])
    above = [p for p in pools if p["side"] == "buy_side" and p["price"] > price]
    below = [p for p in pools if p["side"] == "sell_side" and p["price"] < price]
    return {
        "price": price,
        "buy_side": min(above, key=lambda p: p["price"] - price) if above else None,
        "sell_side": min(below, key=lambda p: price - p["price"]) if below else None,
    }


def _reference_dealing_range(df, current_idx):
    """Shortest available IPDA range, or a bar-count fallback, or None."""
    ranges = ipda_dealing_ranges(df, end_idx=current_idx)
    if ranges:
        return ranges[0]
    return dealing_range(df, BIAS_FALLBACK_RANGE_BARS, end_idx=current_idx,
                         label="fallback")


def daily_bias(df, swings, breaks=None, current_idx=None,
               atr_period=DEFAULT_ATR_PERIOD):
    """A directional bias for the session, or None when there isn't one.

    Direction is taken from the most recent break of structure that carried
    displacement behind it, and falls back to the higher-timeframe swing
    sequence when no break has been confirmed that way. A break with no
    measurable displacement is not evidence — that is the whole reason
    `displacement.py` exists — and a swing sequence reading "range" is not
    evidence either, so a chart offering neither returns bias None with the
    reason recorded.

    Confidence is a weighted sum of four checks, each named in `reasons`.
    A check that could not be measured contributes nothing rather than being
    assumed favourable, so an unmeasurable chart produces a low confidence
    instead of a confident guess.

    Every input is clipped to `current_idx`: the breaks, the pools and the
    touch counts behind them, the dealing range, and the swing sequence the
    structure is read from. Answering this question at a bar in the middle of a
    frame is the only reason the parameter exists, and a single unclipped input
    would hand a backtest tomorrow's chart.
    """
    if df is None or len(df) == 0 or not swings:
        return None
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 0 or current_idx >= len(df):
        return None

    if breaks is None:
        breaks = detect_market_structure_breaks(df, swings)
    qualified = qualify_breaks_with_displacement(df, breaks, atr_period=atr_period)
    recent = [b for b in qualified if b["idx"] <= current_idx and b["displaced"]]
    last_break = recent[-1] if recent else None

    # `current_trend` reads the last six labelled swings of whatever list it is
    # given, so it has to be given the swings that had printed by `current_idx`
    # and no others. Handing it the full list let a swing from after the bar
    # under test set the structure — and structure is what decides the bias when
    # no displaced break exists, and carries BIAS_W_STRUCTURE of the confidence
    # when one does. Every other input here is already clipped this way; this
    # was the one that read forward, which made `current_idx` a lie in exactly
    # the point-in-time and backtest calls it exists to serve.
    visible_swings = [s for s in swings if s["idx"] <= current_idx]
    structure = current_trend(visible_swings)

    reasons = []
    if last_break is not None:
        bias = "long" if last_break["type"] == "BOS_UP" else "short"
        reasons.append(
            f"last displaced {last_break['type']} at bar {last_break['idx']} "
            f"(score {last_break['displacement_score']:.2f})"
        )
    elif structure in ("up", "down"):
        bias = "long" if structure == "up" else "short"
        reasons.append(f"no displaced break; swing sequence reads {structure}")
    else:
        bias = None
        reasons.append("no displaced break and the swing sequence is ranging")

    pools = unswept_pools(df, swings, current_idx)
    draw_sides = draw_on_liquidity(df, swings, current_idx, pools=pools)
    reference = _reference_dealing_range(df, current_idx)
    price = float(df["close"].iloc[current_idx])

    if bias is None:
        return {
            "bias": None,
            "confidence": None,
            "structure": structure,
            "draw": None,
            "opposing": None,
            "dealing_range": reference,
            "location": (reference["zone"], reference["position"]) if reference else None,
            "price": price,
            "last_break": last_break,
            "reasons": reasons,
        }

    draw = opposing = None
    if draw_sides:
        draw = draw_sides["buy_side"] if bias == "long" else draw_sides["sell_side"]
        opposing = draw_sides["sell_side"] if bias == "long" else draw_sides["buy_side"]

    confidence = 0.0
    if (bias == "long" and structure == "up") or (bias == "short" and structure == "down"):
        confidence += BIAS_W_STRUCTURE
        reasons.append(f"htf structure agrees ({structure})")
    else:
        reasons.append(f"htf structure does not agree ({structure})")

    if reference is None:
        reasons.append("dealing range not measurable — location unscored")
    elif (bias == "long" and reference["zone"] == "discount") or \
         (bias == "short" and reference["zone"] == "premium"):
        confidence += BIAS_W_LOCATION
        reasons.append(f"price is in {reference['zone']} of the dealing range")
    else:
        reasons.append(f"price is in {reference['zone']} — poor location for {bias}")

    if draw is None:
        reasons.append("no unswept pool left in the bias direction")
    else:
        if draw["touches"] >= BIAS_POOL_MIN_TOUCHES:
            confidence += BIAS_W_POOL_STRENGTH
            reasons.append(f"draw is a {draw['touches']}-touch pool at {draw['price']:.4f}")
        else:
            reasons.append(f"draw is a single swing at {draw['price']:.4f}")

        reference_atr = atr_at(df, current_idx, _atr_series(df, atr_period), atr_period)
        if reference_atr is None:
            reasons.append("atr not warmed up — room to the draw unscored")
        elif abs(draw["price"] - price) >= BIAS_MIN_ROOM_ATR * reference_atr:
            confidence += BIAS_W_ROOM
            reasons.append("at least one atr of room to the draw")
        else:
            reasons.append("draw is inside one atr — little left to be paid")

    return {
        "bias": bias,
        "confidence": round(confidence, 2),
        "structure": structure,
        "draw": draw,
        "opposing": opposing,
        "dealing_range": reference,
        "location": (reference["zone"], reference["position"]) if reference else None,
        "price": price,
        "last_break": last_break,
        "reasons": reasons,
    }


def filter_setups_to_bias(setups, bias, min_confidence=None):
    """Keep the setups that agree with a measured bias.

    `bias` may be the dict `daily_bias` returns or a bare "long"/"short".
    A None bias — or a confidence below `min_confidence` — filters nothing:
    the setups come back untouched, because refusing to answer a question is
    not the same as answering it against every trade on the list.
    """
    if not setups:
        return []
    direction = bias.get("bias") if isinstance(bias, dict) else bias
    if direction not in ("long", "short"):
        return list(setups)
    if min_confidence is not None and isinstance(bias, dict):
        confidence = bias.get("confidence")
        if confidence is None or confidence < min_confidence:
            return list(setups)
    wanted = "LONG" if direction == "long" else "SHORT"
    return [s for s in setups if s.get("direction") == wanted]
