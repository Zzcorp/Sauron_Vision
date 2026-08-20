"""Mitigation blocks — the zone a losing position comes back to escape.

Not a breaker, and the difference is the whole point. A breaker is built from
a swing whose liquidity was *taken*: price ran the stops beyond a high or a
low and then reversed, so the zone works because the orders filled there are
trapped. A mitigation block is built from a swing that was never swept — the
structure shifted from a higher low that price simply turned at, so nobody was
raided. The traders offside from that swing are not trapped, they are waiting
for the chance to get out flat, and their exit is the flow the zone trades on.

Identical rectangles on a chart, different reason each one holds, and here a
different filter: `detect_mitigation_blocks` refuses any origin swing whose
prior counterpart was swept on the way to the structure shift. Zones that fail
that test belong to `zones.find_breakers`, which is why nothing is reported
twice between the two.

The shape, spelled out for the bullish case (the bearish one mirrors it):

    L1 low  ->  H1 high  ->  L2 higher low (L1 never traded through)
             ->  close above H1

The mitigation block is the down-close candle that made L2.
"""
from .displacement import DEFAULT_ATR_PERIOD, atr_at
from .pivots import atr as _atr_series


# How far back from the pivot bar we will look for the candle that made the
# turn. A fractal pivot marks the bar holding the extreme, but the down-close
# candle that produced it is frequently the bar before — one or two at most.
# Wider than that and the zone drifts onto a candle from the previous leg,
# which is a different origin with different orders behind it.
MITIGATION_ZONE_WINDOW = 2

# How far beyond the origin swing the stop sits, in average bars. On this
# pattern the origin swing is usually the zone's own low, so a stop placed on
# the swing is a stop on the zone edge — the level every reader of the pattern
# picks and therefore the level the market reaches for on its way out. A
# quarter of an average bar is the smallest buffer that survives one ordinary
# bar of overshoot, which is the same number and the same reasoning as
# `session_setups.SESSION_STOP_BUFFER_ATR`.
MITIGATION_STOP_BUFFER_ATR = 0.25


def _origin_candle(df, pivot_idx, want_bearish, window=MITIGATION_ZONE_WINDOW):
    """Index of the candle the zone is drawn on.

    The last opposing-close candle at or just before the pivot; the pivot bar
    itself when the turn was made by a single candle of the other colour, since
    that bar is still the origin of the move even if its body points the wrong
    way.
    """
    opens = df["open"].values
    closes = df["close"].values
    for k in range(pivot_idx, max(-1, pivot_idx - window - 1), -1):
        if want_bearish and closes[k] < opens[k]:
            return k
        if not want_bearish and closes[k] > opens[k]:
            return k
    return pivot_idx


def detect_mitigation_blocks(df, swings, breaks, sweeps=None,
                             zone_window=MITIGATION_ZONE_WINDOW):
    """Mitigation blocks in chart order; [] when none qualify.

    `sweeps` is optional. The sweep test that matters is geometric — did any
    bar between the prior swing and the break trade through that swing's price
    — and that is computed from the frame itself so the answer does not depend
    on the caller having run `detect_sweeps` with the same lookback. When a
    sweep list *is* supplied it is used as a second, stricter veto.

    `mitigated` and `invalidated` are independent facts, not two halves of one:
    a block can be tagged and then closed through, and such a block carries both
    a `mitigated_idx` and an `invalidated_idx`. Both are read over the whole
    frame, so a caller answering as of some earlier bar must compare the indices
    against it — `detect_mitigation_retest_setups` does.
    """
    blocks = []
    if not breaks or not swings or len(df) == 0:
        return blocks
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    for b in breaks:
        bullish = b.get("type") == "BOS_UP"
        kind = "L" if bullish else "H"
        prior = [s for s in swings if s["type"] == kind and s["idx"] < b["idx"]]
        if len(prior) < 2:
            continue
        origin_swing, first_swing = prior[-1], prior[-2]

        # The swing that shifted structure has to be a *higher* low (or lower
        # high). Equal to or beyond the earlier one and the market took that
        # liquidity, which makes this a breaker's origin, not a mitigation
        # block's.
        if bullish and origin_swing["price"] <= first_swing["price"]:
            continue
        if not bullish and origin_swing["price"] >= first_swing["price"]:
            continue

        # The broken level must sit between the two swings. That ordering is
        # the pattern: low, high, higher low, break of that high. A break of
        # some older level that merely happens to land after these two swings
        # is a different structure wearing the same swing labels.
        broken_idx = b.get("broken_swing_idx")
        if broken_idx is None or not (first_swing["idx"] < broken_idx < origin_swing["idx"]):
            continue

        span = slice(first_swing["idx"] + 1, b["idx"] + 1)
        if bullish and float(lows[span].min()) <= first_swing["price"]:
            continue  # L1 was traded through: swept, so breaker territory
        if not bullish and float(highs[span].max()) >= first_swing["price"]:
            continue
        if sweeps:
            want = "SWEEP_LOW" if bullish else "SWEEP_HIGH"
            if any(sw.get("type") == want
                   and first_swing["idx"] <= sw["idx"] <= b["idx"]
                   for sw in sweeps):
                continue

        candle_idx = _origin_candle(df, origin_swing["idx"], bullish, zone_window)
        zone_low = float(lows[candle_idx])
        zone_high = float(highs[candle_idx])
        if zone_high <= zone_low:
            continue

        # Both questions are asked over the WHOLE remainder of the frame, and
        # the touch does not end the walk. It used to: the loop stopped at the
        # first bar that tagged the zone, so a block price tapped and then
        # closed straight through came back with `invalidated` False forever,
        # and `detect_mitigation_retest_setups` went on offering it as a live
        # retest of a zone that no longer existed. A close beyond the far edge
        # is the one event that ends a mitigation block — the offside orders it
        # was drawn for have been run over rather than filled — so the walk only
        # stops there.
        #
        # Within a single bar the close wins over the wick: a bar that reaches
        # into the zone and still closes through it is that bar, not a retest.
        mitigated_idx = None
        invalidated_idx = None
        for j in range(b["idx"] + 1, len(df)):
            if closes[j] < zone_low if bullish else closes[j] > zone_high:
                invalidated_idx = j
                break
            if mitigated_idx is None and lows[j] <= zone_high and highs[j] >= zone_low:
                mitigated_idx = j

        blocks.append({
            "type": "MB_BULL" if bullish else "MB_BEAR",
            "idx": candle_idx,
            "low": zone_low,
            "high": zone_high,
            "ts": df.index[candle_idx],
            "origin_swing_idx": origin_swing["idx"],
            "origin_swing_price": float(origin_swing["price"]),
            "prior_swing_idx": first_swing["idx"],
            "prior_swing_price": float(first_swing["price"]),
            "prior_swing_swept": False,
            "created_by_break_idx": b["idx"],
            "broken_swing_idx": broken_idx,
            "mitigated": mitigated_idx is not None,
            "mitigated_idx": mitigated_idx,
            "invalidated": invalidated_idx is not None,
            "invalidated_idx": invalidated_idx,
        })

    blocks.sort(key=lambda z: z["idx"])
    return blocks


def detect_mitigation_retest_setups(df, mitigation_blocks, swings, current_idx=None,
                                    atr_period=DEFAULT_ATR_PERIOD,
                                    stop_buffer_atr=MITIGATION_STOP_BUFFER_ATR):
    """Setups where the current bar is tagging a live mitigation block.

    A block is live until price closes through it. Entry is the middle of the
    zone, the stop sits `stop_buffer_atr` average bars *past* the origin swing —
    the swing is the level that unwinds the thesis, the zone edge is only where
    it starts to hurt, and on this pattern those two are usually the same price,
    so the stop has to clear it rather than rest on it — and the objective is
    the next swing beyond the entry.

    Setups with no swing left to aim at are dropped, and so are setups on a
    frame where ATR has not warmed up: the buffer is unmeasurable there, and a
    stop parked on the swing is the one thing this setup is built to avoid.
    Inventing a percentage instead would put a number on the card that nothing
    in the chart supports.
    """
    setups = []
    if not mitigation_blocks or len(df) == 0:
        return setups
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 1 or current_idx >= len(df):
        return setups
    reference_atr = atr_at(df, current_idx, _atr_series(df, atr_period), atr_period)
    if reference_atr is None:
        return setups
    buffer_amount = stop_buffer_atr * reference_atr
    bar_high = float(df["high"].iloc[current_idx])
    bar_low = float(df["low"].iloc[current_idx])

    for block in mitigation_blocks:
        if block["invalidated"] and block["invalidated_idx"] <= current_idx:
            continue
        if block["created_by_break_idx"] >= current_idx:
            continue
        bullish = block["type"] == "MB_BULL"
        touching = (
            block["low"] <= bar_low <= block["high"] if bullish
            else block["low"] <= bar_high <= block["high"]
        )
        if not touching:
            continue

        entry = (block["low"] + block["high"]) / 2
        stop = (block["origin_swing_price"] - buffer_amount if bullish
                else block["origin_swing_price"] + buffer_amount)
        # Targets are drawn only from swings this structure has already
        # printed, and never from bars past `current_idx`. Reaching further
        # forward would let a backtest aim at a high the market had not made
        # yet at the moment the entry filled.
        kind = "H" if bullish else "L"
        target = next(
            (s["price"] for s in reversed(swings)
             if s["type"] == kind
             and block["prior_swing_idx"] < s["idx"] <= current_idx
             and (s["price"] > entry if bullish else s["price"] < entry)),
            None,
        )
        has_target = target is not None
        if bullish:
            risk, reward = entry - stop, (target - entry) if has_target else None
            side, invalidation = "LONG", f"close below {stop:.4f}"
        else:
            risk, reward = stop - entry, (entry - target) if has_target else None
            side, invalidation = "SHORT", f"close above {stop:.4f}"
        if target is None or risk <= 0 or reward is None or reward <= 0:
            continue

        setups.append({
            "setup": "MITIGATION_BLOCK",
            "direction": side,
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": round(reward / risk, 2),
            "mitigation_block": block,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": invalidation,
            "components": ["unswept_origin", "msb", "mitigation_retest"],
            # Written here rather than in `explain.templates` because the
            # sentence quotes numbers only this function measured. See
            # `smc_rules._apply_detector_language` for which one a card shows.
            "thesis": (
                "Structure shifted from the %.4f swing without the market ever "
                "sweeping it, so the traders offside from it are waiting to get "
                "out flat rather than trapped. Entry %.4f is the block that exit "
                "flows through."
                % (block["origin_swing_price"], entry)
            ),
            "why_now": (
                "Mitigation block %.4f-%.4f tagged; its %.4f origin swing was "
                "never swept."
                % (block["low"], block["high"], block["origin_swing_price"])
            ),
        })
    return setups
