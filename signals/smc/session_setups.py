"""Session-scoped ICT setups: the Judas swing and the Silver Bullet.

Both concepts are defined by a New York wall-clock window, so both delegate
every timestamp question to `sessions.py` — read the timezone convention
stated there before changing anything here. The short version: bars are UTC,
sessions are New York, and the conversion is done with a real tz database so
the windows survive the two days a year the offset changes.

Neither detector guesses when the data cannot carry the concept. The Silver
Bullet in particular needs a one-hour window to contain the three consecutive
bars a fair value gap is made of, which means an intraday frame of 15 minutes
or finer; handed 4h bars it returns [] rather than stretching the window.
"""
import math

from .displacement import DEFAULT_ATR_PERIOD, atr_at, measure_displacement
from .pivots import atr as _atr_series
from .sessions import (
    SILVER_BULLET_DEFAULT,
    new_york_index,
    session_windows,
)


# The false move has to clear the session open by half an average bar before we
# will call it a trap. Under that, the excursion is inside a single bar's noise
# and there is nobody positioned in it to be trapped.
JUDAS_MIN_EXCURSION_ATR = 0.5

# And the reversal has to travel half an average bar back *through* the open in
# the other direction. Without this a session that opens, ticks up and drifts
# back to flat would read as a Judas swing; the point of the pattern is that
# the real move goes somewhere.
JUDAS_MIN_REVERSAL_ATR = 0.5

# The trap must be set in the first half of the session window. An extreme
# printed in the closing bars is the session's trend, not the fake-out that
# preceded it, and calling it a Judas would label every trending session one.
JUDAS_EARLY_FRACTION = 0.5

# Fewer bars than this and there is nothing to order: one bar to set the trap,
# one to turn it, one to deliver. With two, the false move and the real move
# are the same candle and nothing distinguishes them.
JUDAS_MIN_SESSION_BARS = 3

# Stops sit a quarter of an average bar beyond the level that invalidates them.
# That is the smallest buffer that survives one ordinary bar of overshoot, and
# on the zones these setups use it adds well under a fifth to the risk leg.
SESSION_STOP_BUFFER_ATR = 0.25

# How long a Silver Bullet gap stays live. 12 bars is the window itself on a
# 5-minute chart and the remainder of the New York AM on a 15-minute one; a gap
# from this morning's 10:00 window is not a Silver Bullet by the afternoon.
SILVER_BULLET_MAX_AGE_BARS = 12


def _nearest_swing_beyond(swings, price, above, before_idx=None):
    """Closest swing high above / swing low below `price`, or None.

    None is a real answer here: it means there is no charted level to aim at,
    and every caller treats that as a reason to skip the setup rather than to
    invent a percentage target.
    """
    kind = "H" if above else "L"
    candidates = [
        s for s in swings
        if s["type"] == kind
        and (before_idx is None or s["idx"] < before_idx)
        and (s["price"] > price if above else s["price"] < price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: abs(s["price"] - price))


def _displacement_objective(swings, leg_extreme, entry, above, before_idx):
    """Where a displacement entry is aiming.

    The floor objective needs no hindsight at all: the extreme of the move that
    opened the gap, which by construction sits beyond the gap. If an older
    swing rests beyond *that*, it is the better destination — there are orders
    on it, and a leg extreme is only a price. Returns None when there is
    neither, and the caller drops the setup instead of inventing a percentage.
    """
    reference = leg_extreme if leg_extreme is not None else entry
    pool = _nearest_swing_beyond(swings, reference, above=above, before_idx=before_idx)
    if pool is not None:
        return float(pool["price"])
    return leg_extreme


def detect_judas_swings(df, swings, session="london", atr_period=DEFAULT_ATR_PERIOD,
                        min_excursion_atr=JUDAS_MIN_EXCURSION_ATR,
                        min_reversal_atr=JUDAS_MIN_REVERSAL_ATR,
                        early_fraction=JUDAS_EARLY_FRACTION,
                        current_idx=None):
    """Judas swings: the session opens, fakes one way, then goes the other.

    The reference price is the open of the session's first bar. A session
    qualifies when the extreme against the eventual direction is printed in the
    first `early_fraction` of the window, clears the reference by
    `min_excursion_atr`, and price then trades back through the reference by
    `min_reversal_atr` the other way.

    The setup returned is the retrace entry: the midpoint of the trap leg, stop
    beyond the false extreme, objective the nearest swing on the other side.
    Sessions with no such swing to aim at are skipped.

    Returns [] when the tz database is missing, the session never appears in
    the frame, or ATR has not warmed up over it — never a fabricated neutral.
    """
    setups = []
    if df is None or len(df) == 0 or not swings:
        return setups
    windows = session_windows(df, session)
    if not windows:
        return setups
    if current_idx is None:
        current_idx = len(df) - 1

    atr_values = _atr_series(df, atr_period)
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values

    for window in windows:
        positions = [p for p in window["positions"] if p <= current_idx]
        if len(positions) < JUDAS_MIN_SESSION_BARS:
            continue
        reference_atr = atr_at(df, positions[0], atr_values, atr_period)
        if reference_atr is None:
            continue
        reference = float(opens[positions[0]])

        high_rank = max(range(len(positions)), key=lambda r: highs[positions[r]])
        low_rank = min(range(len(positions)), key=lambda r: lows[positions[r]])
        # A single bar holding both extremes cannot be ordered from OHLC alone,
        # so the "which came first" question the pattern rests on is
        # unanswerable and the session is left alone.
        if high_rank == low_rank:
            continue
        early_cutoff = max(1, math.ceil(len(positions) * early_fraction))

        high_price = float(highs[positions[high_rank]])
        low_price = float(lows[positions[low_rank]])
        excursion_floor = min_excursion_atr * reference_atr
        reversal_floor = min_reversal_atr * reference_atr

        if high_rank < low_rank:
            if high_rank >= early_cutoff:
                continue
            if (high_price - reference) < excursion_floor:
                continue
            if (reference - low_price) < reversal_floor:
                continue
            side = "SHORT"
            trap_idx = positions[high_rank]
            trap_price = high_price
            entry = (reference + high_price) / 2
            stop = high_price + SESSION_STOP_BUFFER_ATR * reference_atr
            objective = _nearest_swing_beyond(swings, entry, above=False,
                                              before_idx=positions[0])
            risk = stop - entry
            reward = (entry - objective["price"]) if objective else None
            invalidation = f"close above {stop:.4f}"
        else:
            if low_rank >= early_cutoff:
                continue
            if (reference - low_price) < excursion_floor:
                continue
            if (high_price - reference) < reversal_floor:
                continue
            side = "LONG"
            trap_idx = positions[low_rank]
            trap_price = low_price
            entry = (reference + low_price) / 2
            stop = low_price - SESSION_STOP_BUFFER_ATR * reference_atr
            objective = _nearest_swing_beyond(swings, entry, above=True,
                                              before_idx=positions[0])
            risk = entry - stop
            reward = (objective["price"] - entry) if objective else None
            invalidation = f"close below {stop:.4f}"

        if objective is None or risk <= 0 or reward is None or reward <= 0:
            continue

        setups.append({
            "setup": "JUDAS_SWING",
            "direction": side,
            "entry": entry,
            "stop": stop,
            "target": float(objective["price"]),
            "r_multiple": round(reward / risk, 2),
            "session": window["session"],
            "session_date": window["date"],
            "session_open": reference,
            "judas_idx": trap_idx,
            "judas_price": trap_price,
            "judas_ts": df.index[trap_idx],
            "trigger_idx": positions[-1],
            "trigger_ts": df.index[positions[-1]],
            "invalidation": invalidation,
            "components": ["session_open", "false_move", "reversal_through_open"],
            # Written here rather than in `explain.templates` because the
            # sentence quotes numbers only this function measured. See
            # `smc_rules._apply_detector_language` for which one a card shows.
            "thesis": (
                "The %s session opened at %.4f, ran to %.4f against the eventual "
                "direction to take the stops resting there, then traded back "
                "through its own open. Entry %.4f is the middle of that false leg."
                % (window["session"].replace("_", " "), reference, trap_price,
                   entry)
            ),
            "why_now": (
                "%s opened %.4f, faked to %.4f early in the window, reversed "
                "back through the open."
                % (window["session"].replace("_", " ").capitalize(), reference,
                   trap_price)
            ),
        })
    return setups


def detect_silver_bullet_fvgs(df, session=SILVER_BULLET_DEFAULT,
                              require_displacement=True,
                              atr_period=DEFAULT_ATR_PERIOD, current_idx=None):
    """Fair value gaps created inside a Silver Bullet window.

    All three bars of the gap must fall inside the window and be adjacent in
    the frame — a gap straddling the window's edge was not created by the
    Silver Bullet hour, it was created by whatever was already running.

    Returns [] on a timeframe too coarse for the one-hour window to hold three
    bars. That is the honest answer, not a defect: on 4h bars there is no such
    thing as a Silver Bullet gap.
    """
    found = []
    if df is None or len(df) == 0:
        return found
    ny_index = new_york_index(df)
    if ny_index is None:
        return found
    windows = session_windows(df, session, ny_index=ny_index)
    if not windows:
        return found
    if current_idx is None:
        current_idx = len(df) - 1

    atr_values = _atr_series(df, atr_period)
    highs = df["high"].values
    lows = df["low"].values

    for window in windows:
        positions = [p for p in window["positions"] if p <= current_idx]
        for a, b, c in zip(positions, positions[1:], positions[2:]):
            if b != a + 1 or c != b + 1:
                continue  # a data gap inside the window: not three real bars
            if highs[a] < lows[c]:
                gap = {"type": "FVG_BULL", "low": float(highs[a]), "high": float(lows[c])}
                direction = "up"
            elif lows[a] > highs[c]:
                gap = {"type": "FVG_BEAR", "low": float(highs[c]), "high": float(lows[a])}
                direction = "down"
            else:
                continue

            leg = measure_displacement(df, c, direction=direction,
                                       atr_values=atr_values, atr_period=atr_period)
            if require_displacement and not (leg and leg["is_displacement"]):
                continue

            gap.update({
                "idx": b,
                "ts": df.index[b],
                "session": window["session"],
                "session_date": window["date"],
                "direction": direction,
                "displacement": leg,
            })
            found.append(gap)
    return found


def detect_silver_bullet_setups(df, swings, session=SILVER_BULLET_DEFAULT,
                                bias=None, require_displacement=True,
                                atr_period=DEFAULT_ATR_PERIOD,
                                max_age_bars=SILVER_BULLET_MAX_AGE_BARS,
                                current_idx=None):
    """Setups where the current bar is trading back into a Silver Bullet gap.

    `bias` is optional and is applied only when it is a measured direction
    ("long"/"short"). A None bias filters nothing: an unmeasured bias is not
    evidence against either side, and dropping every setup on it would turn a
    missing measurement into a silent veto.
    """
    setups = []
    if df is None or len(df) == 0:
        return setups
    # Unlike the Judas swing, this setup does not need swings to exist: the
    # displacement leg that opened the gap is its own objective. Swings only
    # upgrade that objective when the chart happens to hold a pool beyond it.
    swings = swings or []
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 1 or current_idx >= len(df):
        return setups

    atr_values = _atr_series(df, atr_period)
    bar_high = float(df["high"].iloc[current_idx])
    bar_low = float(df["low"].iloc[current_idx])

    for gap in detect_silver_bullet_fvgs(df, session=session,
                                         require_displacement=require_displacement,
                                         atr_period=atr_period,
                                         current_idx=current_idx):
        # `gap["idx"]` is b, the MIDDLE bar of (a, b, c) — the gap is not
        # complete until c = b + 1. So age 1 is not a retest, it is the gap's
        # own closing bar, and the touch test passes there by definition: for
        # a bull gap the zone is [highs[a], lows[c]] and bar_low IS lows[c],
        # which the inequality highs[a] < lows[c] already guaranteed. Every
        # qualifying gap therefore emitted a setup on its creation bar, one
        # bar before any retracement could exist — and because persistence
        # dedupes, that premature card then blocked the real retest when it
        # came. The current bar must be strictly past the gap to retest it.
        age = current_idx - gap["idx"]
        if age <= 1 or age > max_age_bars:
            continue
        side = "LONG" if gap["type"] == "FVG_BULL" else "SHORT"
        if bias in ("long", "short") and bias.upper() != side:
            continue

        reference_atr = atr_at(df, gap["idx"], atr_values, atr_period)
        if reference_atr is None:
            continue
        buffer_amount = SESSION_STOP_BUFFER_ATR * reference_atr
        entry = (gap["low"] + gap["high"]) / 2  # consequent encroachment

        leg = gap.get("displacement")
        leg_extreme = None
        if leg:
            leg_window = slice(leg["start_idx"], leg["end_idx"] + 1)
            leg_extreme = float(
                df["high"].values[leg_window].max() if side == "LONG"
                else df["low"].values[leg_window].min()
            )

        if side == "LONG":
            if not (gap["low"] <= bar_low <= gap["high"]):
                continue
            stop = gap["low"] - buffer_amount
            target = _displacement_objective(swings, leg_extreme, entry,
                                             above=True, before_idx=gap["idx"])
            risk = entry - stop
            reward = (target - entry) if target is not None else None
            invalidation = f"close below {stop:.4f}"
        else:
            if not (gap["low"] <= bar_high <= gap["high"]):
                continue
            stop = gap["high"] + buffer_amount
            target = _displacement_objective(swings, leg_extreme, entry,
                                             above=False, before_idx=gap["idx"])
            risk = stop - entry
            reward = (entry - target) if target is not None else None
            invalidation = f"close above {stop:.4f}"

        if target is None or risk <= 0 or reward is None or reward <= 0:
            continue

        setups.append({
            "setup": "SILVER_BULLET",
            "direction": side,
            "entry": entry,
            "stop": stop,
            "target": float(target),
            "r_multiple": round(reward / risk, 2),
            "fvg": gap,
            "session": gap["session"],
            "session_date": gap["session_date"],
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": invalidation,
            "components": ["silver_bullet_window", "displacement", "fvg_entry"],
            # Written here rather than in `explain.templates` because the
            # sentence quotes numbers only this function measured. See
            # `smc_rules._apply_detector_language` for which one a card shows.
            "thesis": (
                "Displacement inside the %s window left the %.4f-%.4f gap "
                "unfilled. Entry %.4f is its consequent encroachment, aiming at "
                "%.4f — where the leg that opened it ran to."
                % (gap["session"].replace("_", " "), gap["low"], gap["high"],
                   entry, float(target))
            ),
            # The gap's own range is left out: `explain.formatter.build_why_now`
            # already prints it off the `fvg` key, and the fact it cannot read
            # is which window opened the gap.
            "why_now": (
                "Opened inside the %s window %d bar(s) ago."
                % (gap["session"].replace("_", " "), age)
            ),
        })
    return setups
