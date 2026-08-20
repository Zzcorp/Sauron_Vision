"""Multi-timeframe SMC scanning with confluence boost.

A signal that fires on the trader timeframe AND has higher-timeframe trend
agreement is more reliable. This module wraps scan_symbol to compute that.

Everything this pass changes about a card, it writes into the card's `reasons`
trail too. That is not tidiness: `_signal_cards.html` renders the trail under
"How this scored {{ conviction }}/100" and `persist_cards` stores it, and this
is the path the 1800s universe scan actually runs — so a boost applied here
and recorded nowhere left every production card explaining a conviction its
own listed terms did not add up to, with a MACRO chip lit that the trail never
mentioned. See `smc_rules.apply_conviction_term`, which this module used to
keep a private copy of and now shares with the scan's own post-build terms.
"""
from signals.rules.smc_rules import apply_conviction_term, scan_symbol
from signals.smc.dataframe import load_ohlcv
from signals.smc.pivots import get_swings, classify_swings
from signals.smc.structure import current_trend


# Conventional pairings: each frame takes the next one along as its context, so
# 1h is read against 4h and 4h against 1d. The last frame in the list has no
# context available and is scanned without one.
DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]

# Agreement with the timeframe above is worth a little more than one
# confluence chip (10 in `explain.formatter`): a chip is one more feature of
# the same bar, while the higher timeframe is a second opinion on the whole
# idea. Held under the 20 that 3R geometry pays, because a trend label is a
# read and the R is arithmetic the trader can check on the chart.
HTF_AGREE_BONUS = 12

# Conflict costs more than agreement pays, for the reason
# `smc_rules.PD_WRONG_SIDE_PENALTY` is also 15: trading into the higher
# timeframe is a defect in the setup, not merely a missing confluence.
HTF_CONFLICT_PENALTY = 15


def htf_trend(symbol, timeframe):
    """Cheap trend label ('up'/'down'/'range') for context confirmation."""
    df = load_ohlcv(symbol, timeframe, bars=200)
    if df is None or len(df) < 30:
        return "unknown"
    swings = classify_swings(get_swings(df, left=3, right=3))
    return current_trend(swings)


def scan_symbol_mtf(symbol, timeframes=None, bars=500):
    """Scan multiple timeframes and boost cards with HTF trend agreement.

    For each card on TF X, check the trend on the frame listed above it. If it
    agrees with the card's direction, boost conviction and tag the card.

    Cards on the highest timeframe in the list have no frame above them, so
    they are neither boosted nor penalised and carry None for all three
    `htf_*` fields — the question was not asked of them.
    """
    timeframes = timeframes or DEFAULT_TIMEFRAMES
    # Every frame except the first serves as context for the one below it, and
    # the first serves as context for nothing. Reading it too would cost a
    # 200-bar load per scan for a label no card can use.
    htf_trends = {tf: htf_trend(symbol, tf) for tf in timeframes[1:]}

    all_cards = []
    for i, tf in enumerate(timeframes):
        cards = scan_symbol(symbol, timeframe=tf, bars=bars)
        # The frame above this one, and nothing at all for the top of the list.
        # Clamping the index to the last frame instead made the top frame its
        # own context, so every card up there scored a bonus for agreeing with
        # itself and said so on its trail — a self-comparison dressed as a
        # second opinion, which is the one thing this whole pass exists to give.
        htf_tf = timeframes[i + 1] if i + 1 < len(timeframes) else None
        htf_dir = htf_trends.get(htf_tf, "unknown") if htf_tf else None

        for card in cards:
            if htf_tf is None:
                card["htf_timeframe"] = None
                card["htf_trend"] = None
                card["htf_agrees"] = None
                card["reasons"] = list(card.get("reasons", [])) + [
                    "%s is the highest timeframe scanned — no higher-timeframe "
                    "verdict +0" % tf
                ]
                continue

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
                # Add macro chip lift representing HTF context. The trail line
                # names the chip because the confluence count above it was
                # scored before this chip existed.
                card.setdefault("chips", {})["macro"] = 1
                apply_conviction_term(
                    card, HTF_AGREE_BONUS,
                    "%s trend %s agrees with the %s — macro chip on"
                    % (htf_tf, htf_dir, card["direction"]))
                card["components"] = list(card.get("components", [])) + [
                    f"htf_{htf_tf}_aligned"
                ]
            elif disagrees:
                card.setdefault("chips", {})["macro"] = -1
                apply_conviction_term(
                    card, -HTF_CONFLICT_PENALTY,
                    "%s trend %s conflicts with the %s — macro chip against"
                    % (htf_tf, htf_dir, card["direction"]))
                card["components"] = list(card.get("components", [])) + [
                    f"htf_{htf_tf}_conflict"
                ]
            else:
                # 'range', or 'unknown' when the higher timeframe had too few
                # bars to read. Neither is agreement, and neither is conflict —
                # but the card should still say the check happened, so a reader
                # can tell a neutral HTF from an MTF pass that never ran.
                card["reasons"] = list(card.get("reasons", [])) + [
                    "%s trend %s — no higher-timeframe verdict +0"
                    % (htf_tf, htf_dir)
                ]
        all_cards.extend(cards)
    return all_cards
