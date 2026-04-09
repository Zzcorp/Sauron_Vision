"""Market structure: BOS/CHoCH detection and premium/discount tagging."""


def detect_market_structure_breaks(df, swings):
    """Detect Break of Structure (BOS) and Change of Character (CHoCH).

    BOS_UP: a bar closes above a prior swing high.
    BOS_DOWN: a bar closes below a prior swing low.
    CHoCH: the first BOS that flips the direction of the prior BOS.
    """
    closes = df["close"].values
    breaks = []

    for s in swings:
        ref_idx = s["idx"]
        ref_price = s["price"]
        for j in range(ref_idx + 1, len(df)):
            if s["type"] == "H" and closes[j] > ref_price:
                breaks.append({
                    "idx": j,
                    "type": "BOS_UP",
                    "broken_swing_idx": ref_idx,
                    "broken_swing_price": ref_price,
                    "trigger_price": float(closes[j]),
                    "ts": df.index[j],
                })
                break
            if s["type"] == "L" and closes[j] < ref_price:
                breaks.append({
                    "idx": j,
                    "type": "BOS_DOWN",
                    "broken_swing_idx": ref_idx,
                    "broken_swing_price": ref_price,
                    "trigger_price": float(closes[j]),
                    "ts": df.index[j],
                })
                break

    # Deduplicate: keep only one break per (type, broken_swing_idx)
    seen = set()
    unique = []
    for b in breaks:
        key = (b["type"], b["broken_swing_idx"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)
    unique.sort(key=lambda b: b["idx"])

    # Tag CHoCHs: a BOS that contradicts the prior BOS direction
    last_dir = None
    for b in unique:
        b["choch"] = bool(last_dir and b["type"] != last_dir)
        last_dir = b["type"]

    return unique


def premium_discount(swing_high_price, swing_low_price, current_price):
    """Tag current price as premium / equilibrium / discount of a leg.

    Returns (zone_label, normalized_position_0_to_1).
    """
    rng = swing_high_price - swing_low_price
    if rng <= 0:
        return "equilibrium", 0.5
    pos = (current_price - swing_low_price) / rng
    if pos > 0.55:
        return "premium", pos
    if pos < 0.45:
        return "discount", pos
    return "equilibrium", pos


def current_trend(swings, lookback=6):
    """Return 'up'/'down'/'range' from the last lookback swing labels."""
    recent = [s for s in swings if "label" in s][-lookback:]
    hh = sum(1 for s in recent if s.get("label") == "HH")
    hl = sum(1 for s in recent if s.get("label") == "HL")
    lh = sum(1 for s in recent if s.get("label") == "LH")
    ll = sum(1 for s in recent if s.get("label") == "LL")
    bull = hh + hl
    bear = lh + ll
    if bull >= bear + 2:
        return "up"
    if bear >= bull + 2:
        return "down"
    return "range"
