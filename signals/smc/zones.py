"""FVG, order block, breaker, and range detection."""


def detect_fvgs(df):
    """Three-candle imbalance.

    Bullish FVG: bar[i-1].high < bar[i+1].low  ->  gap (high[i-1], low[i+1])
    Bearish FVG: bar[i-1].low  > bar[i+1].high ->  gap (high[i+1], low[i-1])
    Marks .filled if price subsequently traded back into the gap.
    """
    fvgs = []
    highs = df["high"].values
    lows = df["low"].values
    for i in range(1, len(df) - 1):
        if highs[i - 1] < lows[i + 1]:
            fvgs.append({
                "idx": i,
                "type": "FVG_BULL",
                "low": float(highs[i - 1]),
                "high": float(lows[i + 1]),
                "ts": df.index[i],
                "filled": False,
            })
        elif lows[i - 1] > highs[i + 1]:
            fvgs.append({
                "idx": i,
                "type": "FVG_BEAR",
                "low": float(highs[i + 1]),
                "high": float(lows[i - 1]),
                "ts": df.index[i],
                "filled": False,
            })
    for fvg in fvgs:
        for j in range(fvg["idx"] + 2, len(df)):
            if fvg["type"] == "FVG_BULL" and lows[j] <= fvg["low"]:
                fvg["filled"] = True
                fvg["filled_idx"] = j
                break
            if fvg["type"] == "FVG_BEAR" and highs[j] >= fvg["high"]:
                fvg["filled"] = True
                fvg["filled_idx"] = j
                break
    return fvgs


def detect_order_blocks(df, breaks, lookback=20):
    """An order block: the last opposing-color candle before an impulse
    that caused a BOS. For BOS_UP, scan back for the last bearish (close<open)
    candle. Marks .broken if price later closed through it the wrong way.
    """
    obs = []
    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for b in breaks:
        idx = b["idx"]
        if b["type"] == "BOS_UP":
            for k in range(idx - 1, max(0, idx - lookback), -1):
                if closes[k] < opens[k]:
                    obs.append({
                        "type": "OB_BULL",
                        "idx": k,
                        "low": float(lows[k]),
                        "high": float(highs[k]),
                        "created_by_break_idx": idx,
                        "ts": df.index[k],
                        "broken": False,
                    })
                    break
        else:
            for k in range(idx - 1, max(0, idx - lookback), -1):
                if closes[k] > opens[k]:
                    obs.append({
                        "type": "OB_BEAR",
                        "idx": k,
                        "low": float(lows[k]),
                        "high": float(highs[k]),
                        "created_by_break_idx": idx,
                        "ts": df.index[k],
                        "broken": False,
                    })
                    break

    for ob in obs:
        for j in range(ob["created_by_break_idx"] + 1, len(df)):
            if ob["type"] == "OB_BULL" and closes[j] < ob["low"]:
                ob["broken"] = True
                ob["broken_idx"] = j
                break
            if ob["type"] == "OB_BEAR" and closes[j] > ob["high"]:
                ob["broken"] = True
                ob["broken_idx"] = j
                break
    return obs


def find_breakers(order_blocks):
    """A breaker = an OB that broke. Bullish OB that failed = bearish breaker
    (it now acts as resistance). And vice versa.
    """
    breakers = []
    for ob in order_blocks:
        if not ob.get("broken"):
            continue
        breakers.append({
            "type": "BREAKER_BEAR" if ob["type"] == "OB_BULL" else "BREAKER_BULL",
            "low": ob["low"],
            "high": ob["high"],
            "origin_ob": ob,
            "broken_idx": ob.get("broken_idx"),
        })
    return breakers


def detect_ranges(swings, min_pivots=4, tolerance_pct=0.01):
    """Detect rectangular ranges from clusters of similar swing prices.

    Slides a window of size min_pivots over the swing list and checks
    that highs and lows in the window cluster within tolerance.
    """
    ranges = []
    if len(swings) < min_pivots:
        return ranges
    for end in range(min_pivots, len(swings) + 1):
        window = swings[end - min_pivots:end]
        highs_w = [s["price"] for s in window if s["type"] == "H"]
        lows_w = [s["price"] for s in window if s["type"] == "L"]
        if len(highs_w) < 2 or len(lows_w) < 2:
            continue
        if max(highs_w) == 0 or max(lows_w) == 0:
            continue
        if (max(highs_w) - min(highs_w)) / max(highs_w) > tolerance_pct:
            continue
        if (max(lows_w) - min(lows_w)) / max(lows_w) > tolerance_pct:
            continue
        ranges.append({
            "high": sum(highs_w) / len(highs_w),
            "low": sum(lows_w) / len(lows_w),
            "start_idx": window[0]["idx"],
            "end_idx": window[-1]["idx"],
            "swings": window,
        })
    # Deduplicate overlapping ranges by keeping the largest
    if not ranges:
        return ranges
    ranges.sort(key=lambda r: r["end_idx"] - r["start_idx"], reverse=True)
    kept = []
    for r in ranges:
        overlap = any(
            not (r["end_idx"] < k["start_idx"] or r["start_idx"] > k["end_idx"])
            for k in kept
        )
        if not overlap:
            kept.append(r)
    kept.sort(key=lambda r: r["start_idx"])
    return kept
