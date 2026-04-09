"""Headline + thesis templates per setup. The 5-second card language."""


HEADLINE_TEMPLATES = {
    "RP_BREAKER":       "{symbol} {direction} · RP Breaker retest · {timeframe}",
    "THREE_TAP":        "{symbol} {direction} · Three-tap on swept low · {timeframe}",
    "RANGE_MSB_SD":     "{symbol} {direction} · Range sweep + MSB · {timeframe}",
    "REVERSAL_PATTERN": "{symbol} {direction} · Reversal pattern · {timeframe}",
    "PO3":              "{symbol} {direction} · Power of 3 · {timeframe}",
    "FVG_TAP":          "{symbol} {direction} · {timeframe} FVG tap",
    "OB_RETEST":        "{symbol} {direction} · Order block retest · {timeframe}",
    "SFP":              "{symbol} {direction} · SFP · {timeframe}",
}


THESIS_TEMPLATES = {
    "RP_BREAKER": (
        "Price swept the {sweep_level:.4f} swing high, broke structure down, "
        "and is now retesting the failed demand at {entry:.4f}, "
        "which has flipped to a bearish breaker."
    ),
    "THREE_TAP": (
        "After sweeping the {sweep_level:.4f} low and reclaiming, "
        "price is retesting the swept area. Liquidity grabbed, "
        "breakout shorts trapped, retest entry."
    ),
    "RANGE_MSB_SD": (
        "Range from {range_low:.4f}-{range_high:.4f} formed. "
        "Price swept the highs, broke structure down through the range mid, "
        "and is now retesting formed supply at {entry:.4f}."
    ),
    "REVERSAL_PATTERN": (
        "Low at {sweep_level:.4f} swept, MSB up confirmed, "
        "price now retesting the formed demand at {entry:.4f}."
    ),
    "PO3": (
        "Accumulation/manipulation/distribution sequence completing: "
        "engineered liquidity has been taken, price reversing through the range. "
        "Entry {entry:.4f}."
    ),
    "FVG_TAP": (
        "Unfilled fair value gap at {entry:.4f} being tagged in the prevailing "
        "trend direction. Imbalance fill + trend continuation."
    ),
    "OB_RETEST": (
        "Unbroken order block at {entry:.4f} being retested. "
        "Origin of the impulsive move; expecting reaction."
    ),
}
