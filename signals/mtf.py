"""Multi-timeframe SMC scanning with confluence boost.

A signal that fires on the trader timeframe AND has higher-timeframe trend
agreement is more reliable. This module wraps scan_symbol to compute that.
"""
from signals.rules.smc_rules import scan_symbol
from signals.smc.dataframe import load_ohlcv
from signals.smc.pivots import get_swings, classify_swings
from signals.smc.structure import current_trend


# Conventional pairings: (entry timeframe, htf used for context)
DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]


def htf_trend(symbol, timeframe):
    """Cheap trend label ('up'/'down'/'range') for context confirmation."""
    df = load_ohlcv(symbol, timeframe, bars=200)
    if df is None or len(df) < 30:
        return "unknown"
    swings = classify_swings(get_swings(df, left=3, right=3))
    return current_trend(swings)


def scan_symbol_mtf(symbol, timeframes=None, bars=500):
    """Scan multiple timeframes and boost cards with HTF trend agreement.

    For each card on TF X, check the next-higher TF's trend. If it agrees
    with the card's direction, boost conviction and tag the card.
    """
    timeframes = timeframes or DEFAULT_TIMEFRAMES
    htf_trends = {tf: htf_trend(symbol, tf) for tf in timeframes}

    all_cards = []
    for i, tf in enumerate(timeframes):
        cards = scan_symbol(symbol, timeframe=tf, bars=bars)
        # Use the next-higher TF (or same TF for the highest one)
        htf_idx = min(i + 1, len(timeframes) - 1)
        htf_tf = timeframes[htf_idx]
        htf_dir = htf_trends.get(htf_tf, "unknown")

        for card in cards:
            agrees = (
                (card["direction"] == "LONG" and htf_dir == "up")
                or (card["direction"] == "SHORT" and htf_dir == "down")
            )
            disagrees = (
                (card["direction"] == "LONG" and htf_dir == "down")
                or (card["direction"] == "SHORT" and htf_dir == "up")
            )
            card["htf_timeframe"] = htf_tf
            card["htf_trend"] = htf_dir
            card["htf_agrees"] = agrees

            if agrees:
                # Add macro chip lift representing HTF context
                card.setdefault("chips", {})
                card["chips"]["macro"] = 1
                card["conviction"] = min(100, card.get("conviction", 0) + 12)
                card["components"] = list(card.get("components", [])) + [
                    f"htf_{htf_tf}_aligned"
                ]
            elif disagrees:
                card.setdefault("chips", {})
                card["chips"]["macro"] = -1
                card["conviction"] = max(0, card.get("conviction", 0) - 15)
                card["components"] = list(card.get("components", [])) + [
                    f"htf_{htf_tf}_conflict"
                ]
        all_cards.extend(cards)
    return all_cards
