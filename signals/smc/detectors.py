"""Composite SMC/ICT setups built on the primitives."""


def detect_rp_breaker_setups(df, swings, sweeps, breaks, breakers, current_idx=None):
    """RektProof Breaker setup (PDF, 76% historical hit rate per author).

    Sequence:
      1. Swing high forms
      2. Price sweeps above the high (wick + close back inside)
      3. BOS down confirms structure shift
      4. The would-be demand becomes a bearish breaker
      5. Price retests the breaker -> short entry
    """
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 1:
        return setups
    last_high = float(df["high"].iloc[current_idx])
    last_low = float(df["low"].iloc[current_idx])

    for br in breakers:
        if br["type"] != "BREAKER_BEAR":
            continue
        ob = br["origin_ob"]

        related_sweep = None
        for sw in sweeps:
            if (sw["type"] == "SWEEP_HIGH"
                    and ob["idx"] - 30 < sw["idx"] < ob["created_by_break_idx"]):
                related_sweep = sw
                break
        if related_sweep is None:
            continue

        in_zone = (br["low"] <= last_high <= br["high"]
                   or br["low"] <= last_low <= br["high"])
        if not in_zone:
            continue

        entry = (br["low"] + br["high"]) / 2
        stop = br["high"] * 1.005
        target = None
        for s in reversed(swings):
            if s["type"] == "L" and s["price"] < entry:
                target = s["price"]
                break
        if target is None:
            target = entry * 0.97

        denom = stop - entry
        r = (entry - target) / denom if denom > 0 else 0

        setups.append({
            "setup": "RP_BREAKER",
            "direction": "SHORT",
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(r, 2),
            "breaker": br,
            "sweep": related_sweep,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": f"4H close above {stop:.4f}",
            "components": ["sweep_high", "msb_down", "breaker_retest"],
        })
    return setups


def detect_three_tap_setups(df, swings, sweeps, current_idx=None):
    """Three-Tap (PDF): swing low forms -> swept -> retest of swept area.

    Trapping breakout shorts at the prior low.
    """
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 2:
        return setups
    last_low = float(df["low"].iloc[current_idx])

    for sw in sweeps:
        if sw["type"] != "SWEEP_LOW":
            continue
        if sw["idx"] >= current_idx - 1:
            continue
        sweep_low = sw["wick_low"]
        zone_low = sweep_low * 0.999
        zone_high = sweep_low * 1.005
        if not (zone_low <= last_low <= zone_high):
            continue
        entry = sweep_low * 1.002
        stop = sweep_low * 0.995
        target = None
        for s in reversed(swings):
            if s["type"] == "H" and s["idx"] > sw["idx"] and s["price"] > entry:
                target = s["price"]
                break
        if target is None:
            target = entry * 1.03
        denom = entry - stop
        r = (target - entry) / denom if denom > 0 else 0
        setups.append({
            "setup": "THREE_TAP",
            "direction": "LONG",
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(r, 2),
            "sweep": sw,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": f"close below {stop:.4f}",
            "components": ["sweep_low", "retest"],
        })
    return setups


def detect_range_msb_setups(df, swings, sweeps, breaks, ranges, current_idx=None):
    """Range strategy (PDF, 61% hit rate): range -> sweep range high ->
    BOS into range -> retest of formed supply -> short.
    """
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    for rng in ranges:
        sweeps_above = [
            s for s in sweeps
            if s["type"] == "SWEEP_HIGH"
            and s["idx"] > rng["end_idx"]
            and rng["high"] > 0
            and abs(s["swept_price"] - rng["high"]) / rng["high"] < 0.01
        ]
        if not sweeps_above:
            continue
        sweep = sweeps_above[0]
        bos_after = [
            b for b in breaks
            if b["type"] == "BOS_DOWN" and b["idx"] > sweep["idx"]
        ]
        if not bos_after:
            continue
        bos = bos_after[0]
        supply_low = rng["high"]
        supply_high = float(df["high"].iloc[sweep["idx"]])
        last_high = float(df["high"].iloc[current_idx])
        if not (supply_low * 0.998 <= last_high <= supply_high * 1.005):
            continue
        entry = (supply_low + supply_high) / 2
        stop = supply_high * 1.005
        target = rng["low"]
        denom = stop - entry
        r = (entry - target) / denom if denom > 0 else 0
        setups.append({
            "setup": "RANGE_MSB_SD",
            "direction": "SHORT",
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(r, 2),
            "sweep": sweep,
            "bos": bos,
            "range": rng,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": f"close above {stop:.4f}",
            "components": ["range", "sweep_high", "msb_down", "supply_retest"],
        })
    return setups


def detect_reversal_pattern_setups(df, swings, sweeps, breaks, current_idx=None):
    """Reversal Pattern (PDF): low forms -> sweep below -> MSB up ->
    retest of formed breaker/demand -> long.
    """
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    last_low = float(df["low"].iloc[current_idx])
    for sw in sweeps:
        if sw["type"] != "SWEEP_LOW":
            continue
        msb_after = [
            b for b in breaks
            if b["type"] == "BOS_UP" and b["idx"] > sw["idx"]
        ]
        if not msb_after:
            continue
        bos = msb_after[0]
        demand_low = sw["wick_low"]
        demand_high = float(df["high"].iloc[sw["idx"]])
        if not (demand_low * 0.995 <= last_low <= demand_high * 1.002):
            continue
        entry = (demand_low + demand_high) / 2
        stop = demand_low * 0.995
        target = None
        for s in reversed(swings):
            if s["type"] == "H" and s["price"] > entry and s["idx"] > sw["idx"]:
                target = s["price"]
                break
        if target is None:
            target = entry * 1.03
        denom = entry - stop
        r = (target - entry) / denom if denom > 0 else 0
        setups.append({
            "setup": "REVERSAL_PATTERN",
            "direction": "LONG",
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(r, 2),
            "sweep": sw,
            "bos": bos,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": f"close below {stop:.4f}",
            "components": ["sweep_low", "msb_up", "demand_retest"],
        })
    return setups


def detect_fvg_tap_setups(df, fvgs, swings, current_idx=None):
    """FVG tap: price returns into an unfilled FVG aligned with the
    prevailing trend. Long on bullish FVG tap during uptrend, etc.
    """
    from .structure import current_trend
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    last_high = float(df["high"].iloc[current_idx])
    last_low = float(df["low"].iloc[current_idx])
    trend = current_trend(swings)

    for fvg in fvgs:
        if fvg.get("filled"):
            continue
        if fvg["idx"] >= current_idx:
            continue
        if fvg["type"] == "FVG_BULL" and trend == "up":
            if fvg["low"] <= last_low <= fvg["high"]:
                entry = (fvg["low"] + fvg["high"]) / 2
                stop = fvg["low"] * 0.997
                target = None
                for s in reversed(swings):
                    if s["type"] == "H" and s["price"] > entry and s["idx"] > fvg["idx"]:
                        target = s["price"]
                        break
                if target is None:
                    target = entry * 1.02
                denom = entry - stop
                r = (target - entry) / denom if denom > 0 else 0
                setups.append({
                    "setup": "FVG_TAP",
                    "direction": "LONG",
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "r_multiple": round(r, 2),
                    "fvg": fvg,
                    "trigger_idx": current_idx,
                    "trigger_ts": df.index[current_idx],
                    "invalidation": f"close below {stop:.4f}",
                    "components": ["fvg", "trend_aligned"],
                })
        elif fvg["type"] == "FVG_BEAR" and trend == "down":
            if fvg["low"] <= last_high <= fvg["high"]:
                entry = (fvg["low"] + fvg["high"]) / 2
                stop = fvg["high"] * 1.003
                target = None
                for s in reversed(swings):
                    if s["type"] == "L" and s["price"] < entry and s["idx"] > fvg["idx"]:
                        target = s["price"]
                        break
                if target is None:
                    target = entry * 0.98
                denom = stop - entry
                r = (entry - target) / denom if denom > 0 else 0
                setups.append({
                    "setup": "FVG_TAP",
                    "direction": "SHORT",
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "r_multiple": round(r, 2),
                    "fvg": fvg,
                    "trigger_idx": current_idx,
                    "trigger_ts": df.index[current_idx],
                    "invalidation": f"close above {stop:.4f}",
                    "components": ["fvg", "trend_aligned"],
                })
    return setups


def detect_ob_retest_setups(df, order_blocks, swings, current_idx=None):
    """Order block retest: unbroken OB is being tagged by current price."""
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    last_high = float(df["high"].iloc[current_idx])
    last_low = float(df["low"].iloc[current_idx])
    for ob in order_blocks:
        if ob.get("broken"):
            continue
        if ob["idx"] >= current_idx - 1:
            continue
        if ob["type"] == "OB_BULL" and ob["low"] <= last_low <= ob["high"]:
            entry = (ob["low"] + ob["high"]) / 2
            stop = ob["low"] * 0.997
            target = None
            for s in reversed(swings):
                if s["type"] == "H" and s["price"] > entry and s["idx"] > ob["idx"]:
                    target = s["price"]
                    break
            if target is None:
                target = entry * 1.02
            denom = entry - stop
            r = (target - entry) / denom if denom > 0 else 0
            setups.append({
                "setup": "OB_RETEST",
                "direction": "LONG",
                "entry": entry,
                "stop": stop,
                "target": target,
                "r_multiple": round(r, 2),
                "order_block": ob,
                "trigger_idx": current_idx,
                "trigger_ts": df.index[current_idx],
                "invalidation": f"close below {stop:.4f}",
                "components": ["order_block", "retest"],
            })
        elif ob["type"] == "OB_BEAR" and ob["low"] <= last_high <= ob["high"]:
            entry = (ob["low"] + ob["high"]) / 2
            stop = ob["high"] * 1.003
            target = None
            for s in reversed(swings):
                if s["type"] == "L" and s["price"] < entry and s["idx"] > ob["idx"]:
                    target = s["price"]
                    break
            if target is None:
                target = entry * 0.98
            denom = stop - entry
            r = (entry - target) / denom if denom > 0 else 0
            setups.append({
                "setup": "OB_RETEST",
                "direction": "SHORT",
                "entry": entry,
                "stop": stop,
                "target": target,
                "r_multiple": round(r, 2),
                "order_block": ob,
                "trigger_idx": current_idx,
                "trigger_ts": df.index[current_idx],
                "invalidation": f"close above {stop:.4f}",
                "components": ["order_block", "retest"],
            })
    return setups


def detect_po3_setups(df, swings, current_idx=None, window_bars=24):
    """Power of Three (Wyckoff/ICT): accumulation -> manipulation -> distribution.

    On the most recent window: identify a small initial range, a thrust out,
    and a reversal back through the range. Trigger when the reversal-through
    happens (the distribution leg starts).
    """
    setups = []
    n = len(df)
    if current_idx is None:
        current_idx = n - 1
    if current_idx < window_bars:
        return setups
    win = df.iloc[current_idx - window_bars:current_idx + 1]
    if len(win) < window_bars:
        return setups

    accum_bars = max(4, window_bars // 4)
    accum = win.iloc[:accum_bars]
    rest = win.iloc[accum_bars:]
    acc_hi = float(accum["high"].max())
    acc_lo = float(accum["low"].min())

    pushed_below = (rest["low"] < acc_lo).any()
    pushed_above = (rest["high"] > acc_hi).any()
    last_close = float(win["close"].iloc[-1])

    if pushed_below and not pushed_above and last_close > acc_lo:
        entry = last_close
        stop = float(rest["low"].min()) * 0.997
        target = acc_hi + (acc_hi - acc_lo)
        denom = entry - stop
        r = (target - entry) / denom if denom > 0 else 0
        setups.append({
            "setup": "PO3",
            "direction": "LONG",
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(r, 2),
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": f"close below {stop:.4f}",
            "components": ["accumulation", "manipulation_low", "distribution_up"],
        })
    if pushed_above and not pushed_below and last_close < acc_hi:
        entry = last_close
        stop = float(rest["high"].max()) * 1.003
        target = acc_lo - (acc_hi - acc_lo)
        denom = stop - entry
        r = (entry - target) / denom if denom > 0 else 0
        setups.append({
            "setup": "PO3",
            "direction": "SHORT",
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(r, 2),
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": f"close above {stop:.4f}",
            "components": ["accumulation", "manipulation_high", "distribution_down"],
        })
    return setups
