"""Opening gaps (new day / new week) and turtle soup.

The opening gaps are New York constructs — the New Day Opening Gap is measured
across the New York day boundary and the New Week Opening Gap across the
weekend — so both go through `sessions.new_york_index` and inherit the
timezone convention documented there.

Turtle soup is not session-scoped and is deliberately *not* a rename of
`liquidity.detect_sweeps`. A sweep is defined against a swing pivot; turtle
soup is defined against the N-bar extreme that breakout traders are actually
watching, and it insists that extreme be old. Those two rules pick out
different bars, which is why both are worth having.
"""
from datetime import timedelta

from .displacement import DEFAULT_ATR_PERIOD, atr_at
from .pivots import atr as _atr_series
from .sessions import new_york_index


# A gap smaller than a tenth of an average bar is the spread and the tick, not
# an event. Anything above it survived the reopen as a real price difference.
GAP_MIN_ATR_FRACTION = 0.1

# The Turtle breakout everyone else is trading is the 20-period extreme, so the
# soup — the failure of that breakout — has to be measured against exactly the
# level those traders are using. Changing this number stops describing the same
# pattern.
TURTLE_SOUP_LOOKBACK = 20

# The prior extreme must be at least four bars old, straight from Raschke's
# original rule. A level set two bars ago is the tail of the move currently in
# progress; four bars is where it becomes settled liquidity with orders resting
# on it, which is the thing the failure is supposed to raid.
TURTLE_SOUP_MIN_AGE_BARS = 4

# How long the close is allowed to take to come back inside. One bar of grace
# catches the common case where the raid happens late in a bar and the
# rejection is confirmed on the next open; more than that and the "failure" is
# just a retrace of a breakout that worked.
TURTLE_SOUP_CONFIRM_BARS = 1


def trading_week_start(day):
    """The Sunday that opens the trading week `day` belongs to.

    Not the ISO week: the futures and FX week reopens on Sunday evening in New
    York, so Sunday belongs to the week that *follows* it. ISO would file
    Sunday with the week that just ended, which puts the reopen bar on the far
    side of the boundary and hides the gap it was supposed to reveal.
    """
    if day.weekday() == 6:
        return day
    return day - timedelta(days=day.weekday() + 1)


def opening_gaps(df, scope="day", atr_period=DEFAULT_ATR_PERIOD,
                 min_atr_fraction=GAP_MIN_ATR_FRACTION, current_idx=None):
    """New Day / New Week opening gaps, earliest first.

    A gap is the space between the last close of one session group and the
    first open of the next. `consequent_encroachment` is its midpoint, which is
    the level ICT actually trades these from.

    Returns [] when the tz database is missing, when the frame holds fewer than
    two session groups, or on a 24/7 instrument where the reopen price equals
    the prior close — the last of those is a measured absence of gaps, and the
    others are an inability to look, which is why callers should not read this
    list as a market-structure claim on its own.
    """
    gaps = []
    if df is None or len(df) == 0 or scope not in ("day", "week"):
        return gaps
    ny_index = new_york_index(df)
    if ny_index is None:
        return gaps
    if current_idx is None:
        current_idx = len(df) - 1

    keys = [
        d if scope == "day" else trading_week_start(d)
        for d in ny_index.date
    ]
    atr_values = _atr_series(df, atr_period)
    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for i in range(1, min(current_idx, len(df) - 1) + 1):
        if keys[i] == keys[i - 1]:
            continue
        reference_atr = atr_at(df, i, atr_values, atr_period)
        if reference_atr is None:
            continue
        prev_close = float(closes[i - 1])
        next_open = float(opens[i])
        gap_low, gap_high = min(prev_close, next_open), max(prev_close, next_open)
        if (gap_high - gap_low) < min_atr_fraction * reference_atr:
            continue

        direction = "up" if next_open > prev_close else "down"
        filled_idx = None
        for j in range(i, min(current_idx, len(df) - 1) + 1):
            if direction == "up" and lows[j] <= gap_low:
                filled_idx = j
                break
            if direction == "down" and highs[j] >= gap_high:
                filled_idx = j
                break

        gaps.append({
            "type": "NDOG" if scope == "day" else "NWOG",
            "idx": i,
            "ts": df.index[i],
            "session_key": keys[i],
            "direction": direction,
            "low": gap_low,
            "high": gap_high,
            "consequent_encroachment": (gap_low + gap_high) / 2,
            "prev_close": prev_close,
            "next_open": next_open,
            "size_atr": (gap_high - gap_low) / reference_atr,
            "filled": filled_idx is not None,
            "filled_idx": filled_idx,
        })
    return gaps


def detect_turtle_soup(df, lookback=TURTLE_SOUP_LOOKBACK,
                       min_age_bars=TURTLE_SOUP_MIN_AGE_BARS,
                       confirm_bars=TURTLE_SOUP_CONFIRM_BARS,
                       current_idx=None):
    """Failed breakouts of the N-bar extreme, earliest first.

    TURTLE_SOUP_LONG: price trades below the 20-bar low and closes back above
    it within `confirm_bars`, where that low was already `min_age_bars` old.
    TURTLE_SOUP_SHORT mirrors it.

    Returns [] when the frame is shorter than the lookback plus the age
    requirement — there is no 20-bar extreme to fail against yet, and reporting
    against a shorter one would be answering a different question.
    """
    events = []
    if df is None or len(df) == 0:
        return events
    if current_idx is None:
        current_idx = len(df) - 1
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    last = min(current_idx, len(df) - 1)
    if last < lookback:
        return events

    for i in range(lookback, last + 1):
        window = slice(i - lookback, i)
        prior_low = float(lows[window].min())
        prior_high = float(highs[window].max())
        low_idx = i - lookback + int(lows[window].argmin())
        high_idx = i - lookback + int(highs[window].argmax())

        if lows[i] < prior_low and (i - low_idx) >= min_age_bars:
            confirm_idx = next(
                (j for j in range(i, min(i + confirm_bars, last) + 1)
                 if closes[j] > prior_low),
                None,
            )
            if confirm_idx is not None:
                events.append({
                    "type": "TURTLE_SOUP_LONG",
                    "idx": i,
                    "ts": df.index[i],
                    "confirm_idx": confirm_idx,
                    "level": prior_low,
                    "level_idx": low_idx,
                    "level_age_bars": i - low_idx,
                    "raid_price": float(lows[i]),
                    "close": float(closes[confirm_idx]),
                })

        if highs[i] > prior_high and (i - high_idx) >= min_age_bars:
            confirm_idx = next(
                (j for j in range(i, min(i + confirm_bars, last) + 1)
                 if closes[j] < prior_high),
                None,
            )
            if confirm_idx is not None:
                events.append({
                    "type": "TURTLE_SOUP_SHORT",
                    "idx": i,
                    "ts": df.index[i],
                    "confirm_idx": confirm_idx,
                    "level": prior_high,
                    "level_idx": high_idx,
                    "level_age_bars": i - high_idx,
                    "raid_price": float(highs[i]),
                    "close": float(closes[confirm_idx]),
                })

    events.sort(key=lambda e: e["idx"])
    return events
