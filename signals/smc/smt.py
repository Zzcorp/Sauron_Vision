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
"""
import pandas as pd

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
