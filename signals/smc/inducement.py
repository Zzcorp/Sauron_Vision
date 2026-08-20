"""Inducement — the liquidity a zone is allowed to keep in front of it.

Between an order block and the impulse that broke structure there is almost
always a minor swing. It is not noise: it is the pool of stops the market
needs before it can afford to trade the zone. Price comes back, takes that
pool first, and only then delivers from the order block — which is why an
entry placed at the zone without waiting for the inducement to be swept is
routinely stopped out by the very move it was trying to catch.

Which minor swing counts is a judgement call and this module makes it
explicitly: the pool *closest to the zone*, i.e. the lowest minor low above a
bullish order block, the highest minor high below a bearish one. That is the
last liquidity price has to clear before it reaches the zone, so its sweep is
the event that actually gates the entry. Taking the first pullback instead
would flag a level price clears long before the zone is in play.

`swept` is the trigger, not the invalidation: an inducement that has been
taken is a zone that is now armed.
"""
from .displacement import DEFAULT_ATR_PERIOD, atr_at
from .pivots import atr as _atr_series


# The pool has to sit at least a quarter of an average bar clear of the zone
# edge. Any closer and the bar that sweeps the pool is the same bar that taps
# the zone, so there is no "take the liquidity, then deliver" sequence left to
# wait for — and waiting for it is the entire point of tracking inducement.
INDUCEMENT_MIN_SEPARATION_ATR = 0.25


def find_inducement(df, swings, zone_low, zone_high, zone_idx, break_idx,
                    direction, atr_values=None, atr_period=DEFAULT_ATR_PERIOD,
                    min_separation_atr=INDUCEMENT_MIN_SEPARATION_ATR,
                    current_idx=None):
    """The inducement pool guarding one zone, or None if there isn't one.

    `direction` is the direction of the *setup* the zone serves: "LONG" for a
    demand zone (the pool is sell-side liquidity above it), "SHORT" for supply
    (buy-side liquidity below it).

    None covers three different "no": no minor swing formed between the zone
    and the break, none of the ones that did formed on the near side of the
    zone far enough clear of it to be tradeable as a separate event, or ATR has
    not warmed up far enough to judge the separation. Not one of those three is
    a measured zero.
    """
    if not swings or zone_idx is None or break_idx is None:
        return None
    if direction not in ("LONG", "SHORT"):
        return None
    if current_idx is None:
        current_idx = len(df) - 1

    reference_atr = atr_at(df, break_idx, atr_values, atr_period)
    if reference_atr is None:
        return None
    separation_floor = min_separation_atr * reference_atr

    between = [
        s for s in swings
        if zone_idx < s["idx"] <= break_idx
        and s["type"] == ("L" if direction == "LONG" else "H")
    ]
    if not between:
        return None

    above = direction == "LONG"
    edge = zone_high if above else zone_low

    # Both filters run before the pool is picked, and both had to. A minor low
    # *below* a demand zone is on the far side of it — it is liquidity the zone
    # sits above, not liquidity guarding the approach — and the type filter
    # alone let one in. Such a swing then won min()/max() outright, produced a
    # negative separation, and returned None for a chart that had a perfectly
    # good pool a few ticks higher. Selecting on separation rather than testing
    # it afterwards fixes both: a candidate is only a candidate if it is on the
    # near side and far enough clear to be a separate event.
    qualifying = [
        s for s in between
        if (s["price"] - edge if above else edge - s["price"]) >= separation_floor
    ]
    if not qualifying:
        return None

    # Closest to the zone among those. That is the last liquidity price has to
    # clear before it reaches the zone, so its sweep is the event that gates the
    # entry; a pool further out is cleared long before the zone is in play.
    pool = (min(qualifying, key=lambda s: s["price"]) if above
            else max(qualifying, key=lambda s: s["price"]))
    separation = pool["price"] - zone_high if above else zone_low - pool["price"]
    side = "sell_side" if above else "buy_side"

    lows = df["low"].values
    highs = df["high"].values
    swept_idx = None
    for j in range(break_idx + 1, min(current_idx, len(df) - 1) + 1):
        if direction == "LONG" and lows[j] < pool["price"]:
            swept_idx = j
            break
        if direction == "SHORT" and highs[j] > pool["price"]:
            swept_idx = j
            break

    return {
        "type": "INDUCEMENT",
        "side": side,
        "serves": direction,
        "price": float(pool["price"]),
        "swing_idx": pool["idx"],
        "ts": df.index[pool["idx"]],
        "zone_low": float(zone_low),
        "zone_high": float(zone_high),
        "zone_idx": zone_idx,
        "break_idx": break_idx,
        "separation": float(separation),
        "separation_atr": float(separation / reference_atr),
        "swept": swept_idx is not None,
        "swept_idx": swept_idx,
    }


def detect_inducements(df, swings, order_blocks, atr_period=DEFAULT_ATR_PERIOD,
                       min_separation_atr=INDUCEMENT_MIN_SEPARATION_ATR,
                       current_idx=None):
    """One inducement per order block that has one, in chart order.

    Order blocks with no qualifying pool are simply absent from the result —
    they are zones with nothing standing in front of them, which is a real and
    tradeable state, not a missing measurement.
    """
    if not order_blocks or not swings or len(df) == 0:
        return []
    atr_values = _atr_series(df, atr_period)
    found = []
    for ob in order_blocks:
        pool = find_inducement(
            df, swings, ob["low"], ob["high"], ob["idx"],
            ob.get("created_by_break_idx"),
            "LONG" if ob["type"] == "OB_BULL" else "SHORT",
            atr_values=atr_values, atr_period=atr_period,
            min_separation_atr=min_separation_atr, current_idx=current_idx,
        )
        if pool is None:
            continue
        pool["order_block"] = ob
        found.append(pool)
    found.sort(key=lambda p: p["swing_idx"])
    return found


def zone_is_armed(inducement):
    """True once the pool in front of a zone has been taken.

    Returns None when there is no inducement to reason about — a zone with no
    pool in front of it is not "armed" or "unarmed", the question does not
    apply, and answering False would hold back a perfectly valid entry forever.
    """
    if inducement is None:
        return None
    return bool(inducement.get("swept"))
