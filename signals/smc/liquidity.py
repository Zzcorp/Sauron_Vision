"""Equal-highs/lows clustering, liquidity sweeps, and SFP detection."""


def find_equal_levels(swings, tolerance_pct=0.001):
    """Cluster swings whose prices are within tolerance_pct of each other.

    Returns list of {type EQH/EQL, price (avg), swing_indices, count}.
    """
    clusters = []
    used = set()
    for i, s in enumerate(swings):
        if i in used:
            continue
        cluster = [i]
        for j in range(i + 1, len(swings)):
            if j in used or swings[j]["type"] != s["type"]:
                continue
            if s["price"] == 0:
                continue
            if abs(swings[j]["price"] - s["price"]) / s["price"] <= tolerance_pct:
                cluster.append(j)
        if len(cluster) >= 2:
            for c in cluster:
                used.add(c)
            avg = sum(swings[c]["price"] for c in cluster) / len(cluster)
            clusters.append({
                "type": "EQH" if s["type"] == "H" else "EQL",
                "price": avg,
                "swing_indices": cluster,
                "count": len(cluster),
            })
    return clusters


def detect_sweeps(df, swings, lookback=80, wick_ratio=0.5):
    """A sweep: bar wicks beyond a recent swing AND closes back inside.

    Wick must be at least wick_ratio of the bar's total range.
    """
    sweeps = []
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    opens = df["open"].values

    for i in range(lookback, len(df)):
        bar_h = highs[i]
        bar_l = lows[i]
        bar_c = closes[i]
        bar_o = opens[i]
        rng = bar_h - bar_l
        if rng <= 0:
            continue
        recent = [s for s in swings if i - lookback <= s["idx"] < i]
        for s in recent:
            if s["type"] == "H":
                if bar_h > s["price"] and bar_c < s["price"]:
                    upper_wick = bar_h - max(bar_o, bar_c)
                    if upper_wick / rng >= wick_ratio:
                        sweeps.append({
                            "idx": i,
                            "type": "SWEEP_HIGH",
                            "swept_swing_idx": s["idx"],
                            "swept_price": s["price"],
                            "wick_high": float(bar_h),
                            "close": float(bar_c),
                            "ts": df.index[i],
                        })
            else:
                if bar_l < s["price"] and bar_c > s["price"]:
                    lower_wick = min(bar_o, bar_c) - bar_l
                    if lower_wick / rng >= wick_ratio:
                        sweeps.append({
                            "idx": i,
                            "type": "SWEEP_LOW",
                            "swept_swing_idx": s["idx"],
                            "swept_price": s["price"],
                            "wick_low": float(bar_l),
                            "close": float(bar_c),
                            "ts": df.index[i],
                        })
    return sweeps


def detect_sfp(df, swings, lookback=80):
    """Swing Failure Pattern is the same shape as a sweep but emphasizes
    the close-back-inside requirement strictly. Alias for detect_sweeps with
    a stricter wick ratio.
    """
    return detect_sweeps(df, swings, lookback=lookback, wick_ratio=0.6)
