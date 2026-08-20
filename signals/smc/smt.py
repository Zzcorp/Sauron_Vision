"""SMT divergence — the one primitive in this package that needs two symbols.

Every other detector here answers a question about a single DataFrame. SMT
cannot: the claim is that two correlated instruments disagree about a high or
a low, so the signature has to take two frames and the two labels to report
them under. That is a deliberate break from the house shape, not an oversight,
and it is why this lives in its own module rather than in `liquidity.py`.

Alignment is the part that makes or breaks it. The two frames are intersected
on their timestamp index before anything is compared, because two bars only
describe the same event if they cover the same wall-clock interval. Comparing
bar 300 of one symbol with bar 300 of another because they share an ordinal is
how you manufacture a divergence that never happened — one missing bar in
either feed and every comparison after it is off by one.

Timestamps follow the house convention: stored UTC. A tz-naive index is taken
to be UTC so a naive frame and an aware frame can still be intersected instead
of silently producing an empty overlap.

`detect_smt_divergence` reports the disagreement between whatever two frames it
is handed and takes the correlation on trust — which is the right contract for
a primitive and a bad one for a trade. `detect_smt_setups` therefore measures it
over the shared history before it will build a card, so nothing here can offer a
"divergence" between two instruments that were never moving together.
"""
import numpy as np
import pandas as pd

from .displacement import DEFAULT_ATR_PERIOD, atr_at
from .pivots import atr as _atr_series
from .pivots import classify_swings, get_swings


# Below this the overlap is not worth reasoning over. 50 bars is the same floor
# `scan_symbol` already applies before it will run any detector at all, so an
# SMT read never claims more history than the rest of the scan is willing to.
SMT_MIN_OVERLAP_BARS = 50

# The leading instrument's new extreme has to clear its own prior extreme by
# 10 bps. Below that, a "higher high" on a liquid instrument is inside the
# spread plus one bar of noise, and the divergence would be a rounding story.
SMT_MIN_LEG_PCT = 0.001

# How far either side of the leader's pivot we look for the laggard's matching
# extreme. 3 bars is the same neighbourhood `get_swings` uses to define a
# pivot, so the two instruments are compared over the same window that made
# the pivot a pivot. Demanding the laggard print its own pivot on exactly the
# same bar would throw away most real divergences: correlated markets turn
# within a bar or two of each other, not on the same tick.
SMT_PIVOT_WINDOW = 3

# How correlated the two instruments have to have actually been before a
# disagreement between them is a divergence rather than two unrelated charts.
# The premise of SMT is that these two move together, and nothing above checks
# it — `detect_smt_divergence` will happily report a "divergence" between gold
# and a biotech. 0.70 is the number this platform already uses to call two
# instruments the same trade: `Portfolio.max_correlation_threshold` defaults to
# it and `portfolio.position_sizing` reads it to taper size on a correlated
# book. Two instruments the risk gate would treat as one position are exactly
# the two whose disagreement is worth reading.
SMT_MIN_CORRELATION = 0.70

# How old the divergence may be when the setup is offered. The pivot behind it
# is found with `right=3`, so it cannot even be confirmed until 3 bars after it
# prints — 3 is the freshest an event can possibly be, and 5 leaves two bars of
# grace for the entry to be taken. Past that, price has left the failed extreme
# and the stop the setup is built on is nowhere near the entry.
SMT_MAX_AGE_BARS = 5

# Stop buffer beyond the extreme that failed, in average bars. Same quarter of
# a bar, and the same reasoning, as `mitigation.MITIGATION_STOP_BUFFER_ATR`: the
# level itself is the one every reader of the pattern marks, so the stop has to
# clear it rather than rest on it.
SMT_STOP_BUFFER_ATR = 0.25


def _as_utc(index):
    """A tz-aware UTC DatetimeIndex, or None if this is not a datetime index."""
    if not isinstance(index, pd.DatetimeIndex):
        return None
    if index.tz is None:
        return index.tz_localize("UTC")
    return index.tz_convert("UTC")


def align_frames(df_a, df_b, min_bars=SMT_MIN_OVERLAP_BARS):
    """Both frames restricted to the timestamps they share, or None.

    None means the comparison cannot be made honestly: a missing frame, an
    index that is not time-based, or an overlap too thin to hold pivots.
    """
    if df_a is None or df_b is None or len(df_a) == 0 or len(df_b) == 0:
        return None
    idx_a = _as_utc(df_a.index)
    idx_b = _as_utc(df_b.index)
    if idx_a is None or idx_b is None:
        return None

    a = df_a.copy()
    b = df_b.copy()
    a.index = idx_a
    b.index = idx_b
    a = a[~a.index.duplicated(keep="last")]
    b = b[~b.index.duplicated(keep="last")]

    shared = a.index.intersection(b.index).sort_values()
    if len(shared) < min_bars:
        return None
    return a.loc[shared], b.loc[shared]


def measured_correlation(df_a, df_b):
    """Pearson correlation of the two frames' close-to-close returns, or None.

    Both frames must already sit on the same index — `align_frames` is what
    produces that — because a correlation taken over two different histories is
    not a correlation between the instruments, it is one between two schedules.

    None means NOT MEASURED: too few bars to correlate, a zero price the returns
    cannot be taken against, or a flat series with no variance. It is never 0.0,
    which would read as a measured absence of any relationship and let a caller
    treat "we could not check" as "we checked and they are unrelated".
    """
    if df_a is None or df_b is None:
        return None
    if len(df_a) != len(df_b) or len(df_a) < 3:
        return None
    a = np.asarray(df_a["close"].values, dtype=float)
    b = np.asarray(df_b["close"].values, dtype=float)
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return None
    if (a[:-1] == 0).any() or (b[:-1] == 0).any():
        return None
    returns_a = np.diff(a) / a[:-1]
    returns_b = np.diff(b) / b[:-1]
    if returns_a.std() == 0 or returns_b.std() == 0:
        return None
    value = float(np.corrcoef(returns_a, returns_b)[0, 1])
    return None if np.isnan(value) else value


def _window_extreme(df, idx, kind, window=SMT_PIVOT_WINDOW):
    """Highest high / lowest low within `window` bars either side of `idx`."""
    lo = max(0, idx - window)
    hi = min(len(df), idx + window + 1)
    if lo >= hi:
        return None
    column = "high" if kind == "H" else "low"
    values = df[column].values[lo:hi]
    return float(values.max() if kind == "H" else values.min())


def _dedupe_nearby(events, window=SMT_PIVOT_WINDOW):
    """Collapse same-type events sitting within `window` bars of each other.

    Scanning both instruments finds the same disagreement twice with the roles
    swapped, and the two pivots are rarely on the identical bar. The survivor
    is the one whose laggard fell furthest short, because that is the reading a
    trader would quote.
    """
    events.sort(key=lambda e: (e["idx"], -e["divergence_pct"]))
    kept = []
    for event in events:
        clash = next(
            (k for k in kept
             if k["type"] == event["type"] and abs(k["idx"] - event["idx"]) <= window),
            None,
        )
        if clash is None:
            kept.append(event)
        elif event["divergence_pct"] > clash["divergence_pct"]:
            kept[kept.index(clash)] = event
    kept.sort(key=lambda e: e["idx"])
    return kept


def _scan_one_side(leader_df, laggard_df, leader_label, laggard_label,
                   left, right, min_leg_pct, window):
    """Divergences where `leader_df` makes the new extreme and the other fails."""
    swings = classify_swings(get_swings(leader_df, left, right))
    events = []
    for kind, label_new, event_type in (("H", "HH", "SMT_BEAR"), ("L", "LL", "SMT_BULL")):
        same_type = [s for s in swings if s["type"] == kind]
        for prev, curr in zip(same_type, same_type[1:]):
            if curr.get("label") != label_new:
                continue
            if prev["price"] <= 0:
                continue
            leg_pct = abs(curr["price"] - prev["price"]) / prev["price"]
            if leg_pct < min_leg_pct:
                continue

            lag_prev = _window_extreme(laggard_df, prev["idx"], kind, window)
            lag_curr = _window_extreme(laggard_df, curr["idx"], kind, window)
            if lag_prev is None or lag_curr is None or lag_prev <= 0:
                continue
            # Asymmetric on purpose. The leader needs a margin so the new
            # extreme is a real one; the laggard gets no tolerance at all,
            # because "failed to make a higher high" is a statement about a
            # level being exceeded or not, and loosening it invents divergences
            # out of instruments that in fact agreed.
            if kind == "H" and lag_curr > lag_prev:
                continue
            if kind == "L" and lag_curr < lag_prev:
                continue

            shortfall = abs(lag_prev - lag_curr) / lag_prev
            events.append({
                "type": event_type,
                "idx": curr["idx"],
                "ts": leader_df.index[curr["idx"]],
                "prev_idx": prev["idx"],
                "prev_ts": leader_df.index[prev["idx"]],
                "leader": leader_label,
                "laggard": laggard_label,
                "leader_prev": float(prev["price"]),
                "leader_curr": float(curr["price"]),
                "laggard_prev": lag_prev,
                "laggard_curr": lag_curr,
                "leader_leg_pct": leg_pct,
                "divergence_pct": shortfall,
            })
    return events


def detect_smt_divergence(df_a, df_b, label_a="A", label_b="B",
                          left=3, right=3, min_leg_pct=SMT_MIN_LEG_PCT,
                          window=SMT_PIVOT_WINDOW,
                          min_bars=SMT_MIN_OVERLAP_BARS):
    """SMT divergences between two correlated instruments.

    SMT_BEAR: one instrument makes a higher high, the other does not — the
    failing one is the honest one, so the read is down.
    SMT_BULL: one makes a lower low, the other does not — the read is up.

    Both instruments are scanned as the leader, so a divergence is found
    whichever side printed the new extreme, then near-duplicates are collapsed.
    Indices and timestamps in the returned dicts refer to the *aligned* frames,
    which is why the aligned pair is worth keeping if you intend to plot them:
    call `align_frames` yourself for that.

    Returns [] when the two frames cannot be aligned onto a shared history long
    enough to hold pivots — an empty list here means "not answerable", and the
    caller should not read it as "the instruments agree".
    """
    aligned = align_frames(df_a, df_b, min_bars=min_bars)
    if aligned is None:
        return []
    a, b = aligned
    events = _scan_one_side(a, b, label_a, label_b, left, right, min_leg_pct, window)
    events += _scan_one_side(b, a, label_b, label_a, left, right, min_leg_pct, window)
    return _dedupe_nearby(events, window)


def _nearest_swing_beyond(swings, price, above, before_idx):
    """Closest already-printed swing high above / swing low below `price`.

    `before_idx` is inclusive and is the whole point: a target drawn from a
    swing the chart had not printed yet is a backtest aiming at a level that
    did not exist when the entry filled. None means there is no charted level
    to aim at, and the caller drops the setup rather than inventing a percentage.
    """
    kind = "H" if above else "L"
    candidates = [
        s for s in swings
        if s["type"] == kind and s["idx"] <= before_idx
        and (s["price"] > price if above else s["price"] < price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: abs(s["price"] - price))


def detect_smt_setups(df, swings, partner_df, label="A", partner_label="B",
                      current_idx=None, max_age_bars=SMT_MAX_AGE_BARS,
                      min_correlation=SMT_MIN_CORRELATION,
                      stop_buffer_atr=SMT_STOP_BUFFER_ATR,
                      atr_period=DEFAULT_ATR_PERIOD, left=3, right=3,
                      min_leg_pct=SMT_MIN_LEG_PCT, window=SMT_PIVOT_WINDOW,
                      min_bars=SMT_MIN_OVERLAP_BARS):
    """Tradeable setups on `df` from a fresh divergence against `partner_df`.

    Everything above this function answers a question about two charts; this one
    turns the answer into a trade on the FIRST of them, which is why the levels
    are all read from `df` and never from the partner. The partner's only job is
    to disagree.

    Two refusals worth stating plainly, because both look like absences of
    signal and neither is:

      * The correlation is measured over the shared history and the read is
        refused below `min_correlation`. SMT's entire claim is "these two move
        together, and today one of them did not" — between instruments that
        never moved together there is no claim left to make. A correlation that
        could not be measured at all is refused for the same reason: the premise
        is unverified, not verified-as-weak.

      * Everything is clipped to `current_idx` before any of it runs — the
        frame, the partner's history, the pivot windows and the target swings.
        The divergence pivot is `right` bars behind the current bar by
        construction, and a scan that read the bars confirming it would be
        scoring a shape it could not have seen.

    Returns [] whenever the question cannot be answered honestly: no partner
    frame, no shared history, an unmeasured or weak correlation, an ATR that has
    not warmed up enough to buffer the stop, or no charted level to aim at.
    """
    setups = []
    if df is None or partner_df is None or len(df) == 0 or len(partner_df) == 0:
        return setups
    if not swings:
        return setups
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 1 or current_idx >= len(df):
        return setups

    stamps = _as_utc(df.index)
    partner_stamps = _as_utc(partner_df.index)
    if stamps is None or partner_stamps is None:
        return setups

    own = df.iloc[:current_idx + 1].copy()
    own.index = stamps[:current_idx + 1]
    peer = partner_df.copy()
    peer.index = partner_stamps
    # By timestamp, not by row count: the partner feed can hold a different
    # number of bars over the same wall-clock stretch, and slicing it
    # positionally would hand back bars from after the scan's own bar.
    peer = peer[peer.index <= own.index[-1]]

    aligned = align_frames(own, peer, min_bars=min_bars)
    if aligned is None:
        return setups
    correlation = measured_correlation(*aligned)
    if correlation is None or correlation < min_correlation:
        return setups

    events = detect_smt_divergence(
        aligned[0], aligned[1], label, partner_label, left=left, right=right,
        min_leg_pct=min_leg_pct, window=window, min_bars=min_bars,
    )
    if not events:
        return setups

    # Events are dated on the aligned frame, whose rows are the intersection of
    # the two histories — so its bar 240 is not this frame's bar 240. The
    # timestamp is the only thing that carries across, and a bar the partner
    # feed was missing simply has no position here and is skipped.
    position_of = {stamp: i for i, stamp in enumerate(own.index)}
    atr_values = _atr_series(df, atr_period)
    reference_atr = atr_at(df, current_idx, atr_values, atr_period)
    if reference_atr is None:
        return setups
    buffer_amount = stop_buffer_atr * reference_atr
    entry = float(df["close"].iloc[current_idx])

    for event in events:
        idx = position_of.get(event["ts"])
        if idx is None:
            continue
        age = current_idx - idx
        if age < 0 or age > max_age_bars:
            continue

        short = event["type"] == "SMT_BEAR"
        kind = "H" if short else "L"
        # Read off THIS frame, not off the event: the event's prices belong to
        # whichever instrument led, and half the time that is the partner.
        extreme = _window_extreme(own, idx, kind, window)
        if extreme is None:
            continue

        if short:
            stop = extreme + buffer_amount
            objective = _nearest_swing_beyond(swings, entry, above=False,
                                              before_idx=current_idx)
            risk = stop - entry
            reward = (entry - objective["price"]) if objective else None
            invalidation = "close above %.4f" % stop
        else:
            stop = extreme - buffer_amount
            objective = _nearest_swing_beyond(swings, entry, above=True,
                                              before_idx=current_idx)
            risk = entry - stop
            reward = (objective["price"] - entry) if objective else None
            invalidation = "close below %.4f" % stop
        if objective is None or risk <= 0 or reward is None or reward <= 0:
            continue

        setups.append({
            "setup": "SMT_DIVERGENCE",
            "direction": "SHORT" if short else "LONG",
            "entry": entry,
            "stop": stop,
            "target": float(objective["price"]),
            "r_multiple": round(reward / risk, 2),
            "smt": dict(event, correlation=correlation,
                        correlation_bars=len(aligned[0]),
                        local_extreme=extreme, age_bars=age),
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": invalidation,
            "components": ["smt_divergence", "correlated_pair",
                           "failed_%s" % ("high" if short else "low")],
            # Written here rather than in `explain.templates` because the
            # sentence quotes numbers only this function measured. See
            # `smc_rules._apply_detector_language` for which one a card shows.
            "thesis": (
                "%s took its %.4f %s and %s did not follow, on two instruments "
                "whose returns correlated %.2f over %d shared bars. Entry %.4f "
                "fades the one that failed."
                % (event["leader"], event["leader_prev"],
                   "high" if short else "low", event["laggard"], correlation,
                   len(aligned[0]), entry)
            ),
            "why_now": (
                "%s made a new %s at %.4f %d bar(s) ago; %s did not."
                % (event["leader"], "high" if short else "low",
                   event["leader_curr"], age, event["laggard"])
            ),
        })
    return setups
