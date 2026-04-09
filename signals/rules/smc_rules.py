"""scan_symbol() and persist_cards() — the entry points the rest of
Sauron Vision should call into for SMC/ICT setup detection.
"""


def scan_symbol(symbol, timeframe="4h", bars=500, df=None):
    """Run all SMC detectors on a symbol/timeframe and return list of cards.

    If `df` is provided, uses it directly (for tests). Otherwise loads
    OHLCV via signals.smc.dataframe.load_ohlcv.
    """
    from signals.smc.dataframe import load_ohlcv
    from signals.smc.pivots import get_swings, classify_swings
    from signals.smc.structure import detect_market_structure_breaks
    from signals.smc.liquidity import detect_sweeps
    from signals.smc.zones import (
        detect_fvgs, detect_order_blocks, find_breakers, detect_ranges,
    )
    from signals.smc.detectors import (
        detect_rp_breaker_setups,
        detect_three_tap_setups,
        detect_range_msb_setups,
        detect_reversal_pattern_setups,
        detect_fvg_tap_setups,
        detect_ob_retest_setups,
        detect_po3_setups,
    )
    from signals.explain.formatter import build_card

    if df is None:
        df = load_ohlcv(symbol, timeframe, bars)
    if df is None or len(df) < 50:
        return []

    swings = classify_swings(get_swings(df, left=3, right=3))
    breaks = detect_market_structure_breaks(df, swings)
    sweeps = detect_sweeps(df, swings)
    fvgs = detect_fvgs(df)
    obs = detect_order_blocks(df, breaks)
    breakers = find_breakers(obs)
    ranges = detect_ranges(swings)

    setups = []
    setups.extend(detect_rp_breaker_setups(df, swings, sweeps, breaks, breakers))
    setups.extend(detect_three_tap_setups(df, swings, sweeps))
    setups.extend(detect_range_msb_setups(df, swings, sweeps, breaks, ranges))
    setups.extend(detect_reversal_pattern_setups(df, swings, sweeps, breaks))
    setups.extend(detect_fvg_tap_setups(df, fvgs, swings))
    setups.extend(detect_ob_retest_setups(df, obs, swings))
    setups.extend(detect_po3_setups(df, swings))

    hit_rates = {
        "RP_BREAKER":       0.76,
        "RANGE_MSB_SD":     0.61,
        "REVERSAL_PATTERN": 0.59,
        "OB_RETEST":        0.59,
        "THREE_TAP":        0.55,
        "FVG_TAP":          0.50,
        "PO3":              0.50,
    }
    return [
        build_card(s, symbol, timeframe, hit_rate=hit_rates.get(s["setup"]))
        for s in setups
    ]


def persist_cards(cards, symbol, timeframe):
    """Save cards into the SmcSignal table. Returns the created instances."""
    from signals.models_smc import SmcSignal
    created = []
    for c in cards:
        chips = c.get("chips", {})
        sig = SmcSignal.objects.create(
            symbol=symbol,
            timeframe=timeframe,
            setup=c["setup"],
            direction=c["direction"],
            headline=c["headline"],
            thesis=c["thesis"],
            why_now=c["why_now"],
            invalidation=c["invalidation"],
            entry=c["entry"],
            stop=c["stop"],
            target=c["target"],
            r_multiple=c["r_multiple"],
            chip_structure=chips.get("structure", 0),
            chip_momentum=chips.get("momentum", 0),
            chip_flow=chips.get("flow", 0),
            chip_macro=chips.get("macro", 0),
            chip_sentiment=chips.get("sentiment", 0),
            conviction=c.get("conviction", 0),
            components=c.get("components", []),
            reasons=[],
            rule_hit_rate_30d=c.get("hit_rate_30d"),
            trigger_ts=c.get("trigger_ts"),
        )
        created.append(sig)
    return created
