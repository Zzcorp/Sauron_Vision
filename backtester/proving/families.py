"""The signal families the proving ground judges — causal, both directions.

Every family answers one question per bar: does it fire on the CLOSE of
bar t, judged only on bars <= t? The simulator enters on the open of
t + 1, so nothing a family returns can see the bar it trades on.

The first four re-express the live rules (signals/rules/technical_rules.py)
bar by bar with their own constants, so a verdict on `rsi_divergence` long
with DEFAULTS is a verdict on `rsi_bull_divergence` as it trades. Each is
mirrored short — the live book has been long-only by construction, and the
decay investigator wrote "the regime turned" every night with nothing in
the rule set able to take the other side.

The rest are base techniques for the generator to search: Donchian
breakout, RSI reversion, EMA pullback, and two ICT reads — the fair value
gap retest and the liquidity sweep reversal — plus the pool sweep
(2026-10-03): the first bar through equal lows or highs of two swings or
more that closes back inside, the claim the positioning map makes
(bot_program/positioning.py) put to the judge; and the Power of Three
(po3, 2026-10-03): the day's Asian range run through one side and the
first bar back inside, the distribution's start the session read names
(bot_program/power_of_three.py).

THE BEARISH PACK (2026-10-31): seven short-only families, each the ONE
detector its live rule (signals/rules/bearish_rules.py) calls on its own
closed bars, so the rule fires where the family fires — bull_trap (a
close above a swing high and back under it), po3_london (London runs the
Asian high, New York closes back under it; judged on 1h bars),
range_breakdown (a tight range's low broken, with follow-through),
trend_rally (a rejected rally to the EMA20 in a downtrend, a lower high),
exhaustion_short (a rejection wick on a relief rally under the SMA200),
vix_term_breakdown (the index under its 10-bar low with VIX/VIX3M at 1 or
more) and crowded_long (the speculators at the top of their COT range and
the top's swing low broken). Each takes `detail=True` for (fires,
{invalidation, quality, ...}), and each fires only when its invalidation
price sits at least CONTAIN_MARGIN_ATR inside the bot's 1.5 ATR stop: a
stop inside the pattern is not this trade. Two read a context column
(backtester/proving/context.py) and fire nothing without it. None of them
joins the weekly generator (Family.in_generate), so its Sidak bar and its
shortlist do not move.

FILTERS, applied on top of any family (the operator's question "and ICT,
fair value gaps?" answered with numbers):
  none      as the rule fires
  trend     with the SMA200 only (long above it, short below)
  discount  ICT premium/discount: long only in the lower half of the last
            DISCOUNT_RANGE bars' range, short only in the upper half
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

LONG, SHORT = "long", "short"
FILTERS = ("none", "trend", "discount", "macro_trend")
DISCOUNT_RANGE = 50
#: The 200-DAY moving average, in bars of each timeframe (crypto trades six
#: 4h bars a day; a stock about two — the daily count is the honest one, so
#: the 4h figure is a compromise between them).
MACRO_TREND_BARS = {"1h": 4800, "4h": 1200, "1d": 200}


# ── indicators (the live rules' own formulas) ───────────────────────────

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """technical_rules._rsi: simple rolling means of gains and losses."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """indicators.calculator.calculate_atr: a simple mean of the true range."""
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ADX — the regime label's trend strength."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    a = 1.0 / period
    atr_w = tr.ewm(alpha=a, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=a, adjust=False).mean() / atr_w.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=a, adjust=False).mean() / atr_w.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(
        0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean()


def _false(n):
    return np.zeros(n, dtype=bool)


def _shift(a, k=1, fill=False):
    out = np.empty_like(a)
    out[:k] = fill
    out[k:] = a[:-k]
    return out


# ── the live rules, mirrored ─────────────────────────────────────────────

def rsi_divergence(df, direction, *, period=14, gate=35.0, window=30):
    """rsi_bull_divergence: RSI under `gate`, price a lower low over the
    last `window` bars than the `window` before, RSI a higher low there.
    Short: RSI over 100 - gate, a higher high with a lower RSI high."""
    n = len(df)
    out = _false(n)
    if n < 2 * window:
        return out
    r = rsi(df["close"], period).to_numpy()
    if direction == LONG:
        px = df["low"].to_numpy()
        win = sliding_window_view(px, window)          # win[k] = px[k:k+w]
        pick = win.argmin(axis=1)
    else:
        px = df["high"].to_numpy()
        win = sliding_window_view(px, window)
        pick = win.argmax(axis=1)
    idx = np.arange(len(pick)) + pick                 # absolute index
    for t in range(2 * window - 1, n):
        rt = r[t]
        if not np.isfinite(rt):
            continue
        if direction == LONG and rt >= gate:
            continue
        if direction == SHORT and rt <= 100 - gate:
            continue
        recent = idx[t - window + 1]                   # window ending at t
        prior = idx[t - 2 * window + 1]                # the window before
        rr, rp = r[recent], r[prior]
        if not (np.isfinite(rr) and np.isfinite(rp)):
            continue
        if direction == LONG:
            out[t] = px[recent] < px[prior] and rr > rp
        else:
            out[t] = px[recent] > px[prior] and rr < rp
    return out


def macd_cross(df, direction, *, fast=12, slow=26, signal=9):
    """macd_bullish_crossover: the line crosses the signal with the
    histogram accelerating. Short: crosses under, histogram falling."""
    line, sig, hist = macd(df["close"], fast, slow, signal)
    line, sig, hist = line.to_numpy(), sig.to_numpy(), hist.to_numpy()
    pl, ps, ph = _shift(line, fill=np.nan), _shift(sig, fill=np.nan), \
        _shift(hist, fill=np.nan)
    if direction == LONG:
        out = (pl <= ps) & (line > sig) & (hist > ph)
    else:
        out = (pl >= ps) & (line < sig) & (hist < ph)
    out[:slow] = False
    return np.nan_to_num(out, nan=False).astype(bool)


def ma_cross(df, direction, *, fast=50, slow=200):
    """golden_cross: SMA fast crosses above SMA slow. Short: the death
    cross."""
    if fast >= slow:
        return _false(len(df))
    c = df["close"]
    f = c.rolling(fast).mean().to_numpy()
    s = c.rolling(slow).mean().to_numpy()
    pf, ps = _shift(f, fill=np.nan), _shift(s, fill=np.nan)
    with np.errstate(invalid="ignore"):
        out = ((pf <= ps) & (f > s)) if direction == LONG \
            else ((pf >= ps) & (f < s))
    return np.nan_to_num(out, nan=False).astype(bool)


def bb_squeeze(df, direction, *, period=20, k=2.0, quantile=0.2,
               lookback=120, expand=1.1):
    """bollinger_squeeze_breakout: width under its `quantile` of the last
    `lookback` bars, then expanding by `expand`, with most of the last 30
    widths under today's — long on an up close, short on a down one."""
    n = len(df)
    out = _false(n)
    if n < lookback:
        return out
    c = df["close"]
    mid = c.rolling(period).mean()
    std = c.rolling(period).std()
    width = ((mid + k * std) - (mid - k * std)) / mid.replace(0, 1e-9)
    w = width.to_numpy()
    cl = c.to_numpy()
    for t in range(lookback, n):
        base = w[t - lookback + 1:t - 1]               # iloc[-120:-2]
        if not np.isfinite(w[t]) or not np.isfinite(w[t - 1]):
            continue
        base = base[np.isfinite(base)]
        if len(base) < 10:
            continue
        squeezed = w[t - 1] < np.quantile(base, quantile)
        expanding = w[t] > w[t - 1] * expand
        recent = w[t - 29:t]                           # iloc[-30:-1]
        recent_pct = np.mean(recent[np.isfinite(recent)] < w[t]) \
            if np.isfinite(recent).any() else 0.0
        if squeezed and expanding and recent_pct > 0.7:
            up = cl[t] > cl[t - 1]
            out[t] = up if direction == LONG else not up
    return out


# ── base techniques for the generator ───────────────────────────────────

def donchian(df, direction, *, n=20):
    """A close beyond the last `n` bars' extreme (excluding this bar)."""
    if direction == LONG:
        level = df["high"].rolling(n).max().shift(1)
        out = df["close"] > level
    else:
        level = df["low"].rolling(n).min().shift(1)
        out = df["close"] < level
    return out.fillna(False).to_numpy(dtype=bool)


def rsi_reversion(df, direction, *, period=14, low=30.0):
    """RSI crossing back up through `low` (long) or down through
    100 - low (short): the stretched move turning."""
    r = rsi(df["close"], period)
    pr = r.shift(1)
    if direction == LONG:
        out = (pr < low) & (r >= low)
    else:
        out = (pr > 100 - low) & (r <= 100 - low)
    return out.fillna(False).to_numpy(dtype=bool)


def ema_pullback(df, direction, *, fast=20, mid=50, slow=200):
    """In a stacked trend (EMA fast beyond mid, price beyond slow), a bar
    that dips to the fast EMA and closes back beyond it."""
    c = df["close"]
    ef = c.ewm(span=fast, adjust=False).mean()
    em = c.ewm(span=mid, adjust=False).mean()
    es = c.ewm(span=slow, adjust=False).mean()
    if direction == LONG:
        out = (ef > em) & (c > es) & (df["low"] <= ef) & (c > ef)
    else:
        out = (ef < em) & (c < es) & (df["high"] >= ef) & (c < ef)
    out = np.array(out.to_numpy(dtype=bool), copy=True)
    out[:slow] = False
    return out


def fvg_retest(df, direction, *, max_age=20, min_gap_atr=0.1):
    """ICT fair value gap: a bullish gap at bar j (low[j] > high[j-2]) of at
    least `min_gap_atr` ATR; within `max_age` bars price trades back into
    it (low <= low[j]) and closes above its floor (high[j-2]) — the retest
    holding. One entry per gap. Short: the bearish mirror."""
    n = len(df)
    out = _false(n)
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    a = atr(df).to_numpy()
    open_gaps = []                                     # (j, top, floor)
    for t in range(2, n):
        # retests first: a gap formed on bar t is not retested on bar t
        keep = []
        for j, top, floor in open_gaps:
            if t - j > max_age:
                continue
            if direction == LONG:
                if l[t] <= top and c[t] > floor:
                    out[t] = True
                    continue                           # used
                if c[t] < floor:
                    continue                           # filled through
            else:
                if h[t] >= top and c[t] < floor:
                    out[t] = True
                    continue
                if c[t] > floor:
                    continue
            keep.append((j, top, floor))
        open_gaps = keep
        at = a[t]
        if not np.isfinite(at) or at <= 0:
            continue
        if direction == LONG and l[t] > h[t - 2] \
                and (l[t] - h[t - 2]) >= min_gap_atr * at:
            open_gaps.append((t, l[t], h[t - 2]))
        if direction == SHORT and h[t] < l[t - 2] \
                and (l[t - 2] - h[t]) >= min_gap_atr * at:
            open_gaps.append((t, h[t], l[t - 2]))
    return out


def pool_sweep(df, direction, *, touches=2, left=3, right=3, lookback=120,
               tolerance_pct=0.001):
    """The liquidity-pool sweep (the positioning map's path, bot_program/
    positioning.py): equal lows (long) or equal highs (short) of `touches`
    swings or more within `tolerance_pct`, and the FIRST bar to trade
    through the pool closes back inside it — the stops under it were
    taken and the market turned. A bar that closes through it is a break,
    not a sweep; the pool is spent either way, one fire at most. The pool
    counts from the bar its last swing is confirmed on (`right` bars
    later), never before, and only for `lookback` bars: an old pool is not
    where today's stops are."""
    from signals.smc.liquidity import find_equal_levels
    from signals.smc.pivots import get_swings
    n = len(df)
    out = np.zeros(n, dtype=bool)
    if n < left + right + 2:
        return out
    want = "L" if direction == LONG else "H"
    swings = [s for s in get_swings(df, left, right) if s["type"] == want]
    if len(swings) < touches:
        return out
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    for c in find_equal_levels(swings, tolerance_pct=tolerance_pct):
        if c["count"] < touches:
            continue
        formed = max(swings[i]["idx"] for i in c["swing_indices"]) + right
        level = float(c["price"])
        for j in range(formed + 1, min(n, formed + 1 + lookback)):
            if direction == LONG:
                if lows[j] < level:
                    out[j] = closes[j] > level
                    break
            elif highs[j] > level:
                out[j] = closes[j] < level
                break
    return out


def po3(df, direction, *, session="asia"):
    """The Power of Three (bot_program/power_of_three.py): the day's Asian
    range (accumulation), a run through ONE side of it (the manipulation),
    and the first bar back inside — the distribution's start, the fire,
    in the direction away from the run: long after the lows were run,
    short after the highs. One fire per day at most; a day whose range
    both sides were run never fires. Needs a New-York-anchored session
    read (signals/smc/sessions.session_windows): no tz database, no
    fires. Honest on 1h bars; on 4h the range is one bar."""
    from signals.smc.sessions import session_windows
    n = len(df)
    out = np.zeros(n, dtype=bool)
    windows = session_windows(df, session)
    if not windows:
        return out
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    for k, w in enumerate(windows):
        pos = w["positions"]
        lo, hi = float(lows[pos].min()), float(highs[pos].max())
        start = pos[-1] + 1
        stop = windows[k + 1]["positions"][0] if k + 1 < len(windows) else n
        ran_low = ran_high = False
        for j in range(start, stop):
            if lows[j] < lo:
                ran_low = True
            if highs[j] > hi:
                ran_high = True
            if ran_low and ran_high:
                break
            if direction == LONG and ran_low and closes[j] > lo:
                out[j] = True
                break
            if direction == SHORT and ran_high and closes[j] < hi:
                out[j] = True
                break
    return out


def sweep_reversal(df, direction, *, n=20):
    """ICT liquidity sweep: the bar runs the stops under the last `n` bars'
    low and closes back above it (long) — or over the high and back under
    (short)."""
    if direction == LONG:
        level = df["low"].rolling(n).min().shift(1)
        out = (df["low"] < level) & (df["close"] > level)
    else:
        level = df["high"].rolling(n).max().shift(1)
        out = (df["high"] > level) & (df["close"] < level)
    return out.fillna(False).to_numpy(dtype=bool)


# ── the borrowed approaches (2026-10-02) ────────────────────────────────

def tsmom(df, direction, *, n=1000, trigger=20):
    """Time-series momentum, the CTA's trend following: with the close
    above where it stood `n` bars ago (long), a close over the last
    `trigger` bars' high is an entry — on the turn and again after every
    exit, as long as the momentum holds. Short: the mirror."""
    c = df["close"]
    mom = c / c.shift(n) - 1.0
    if direction == LONG:
        level = df["high"].rolling(trigger).max().shift(1)
        out = (mom > 0) & (c > level)
    else:
        level = df["low"].rolling(trigger).min().shift(1)
        out = (mom < 0) & (c < level)
    return out.fillna(False).to_numpy(dtype=bool)


def rsi2_pullback(df, direction, *, period=2, low=10.0, trend=200):
    """The short-term pullback in a trend (Connors' RSI(2)): RSI(`period`)
    under `low` with the close above its `trend` SMA — long; the mirror
    short. The mean reversion the decay investigator kept asking for in a
    ranging tape, with the trend deciding the side."""
    r = rsi(df["close"], period)
    s = df["close"].rolling(trend).mean()
    if direction == LONG:
        out = (r < low) & (df["close"] > s)
    else:
        out = (r > 100 - low) & (df["close"] < s)
    return out.fillna(False).to_numpy(dtype=bool)


# ── the bearish pack (2026-10-31) ───────────────────────────────────────

#: A short fires only when its invalidation price X sits at least this many
#: ATRs inside the bot's stop: X <= close + (DEFAULT_ATR_STOP_MULT -
#: CONTAIN_MARGIN_ATR) x ATR, so the 1.5 ATR stop (risk_levels) sits beyond
#: the pattern. A stop inside the pattern is not this trade.
CONTAIN_MARGIN_ATR = 0.1
#: A COT index this high is the speculators at the top of their range
#: (bot_program.smart_money.COT_EXTREME, which the rule imports).
COT_EXTREME = 90.0


def contain_atr() -> float:
    """The containment multiple: the bot's stop multiple less the margin
    (1.5 - 0.1 = 1.4), read from risk_levels, never typed."""
    from bot_program.asset_engine.risk_levels import DEFAULT_ATR_STOP_MULT
    return float(DEFAULT_ATR_STOP_MULT) - CONTAIN_MARGIN_ATR


def _nan(n):
    return np.full(n, np.nan)


def _done(out, info, detail):
    return (out, info) if detail else out


def _clip01(x):
    return float(min(1.0, max(0.0, x)))


def bull_trap(df, direction, *, left=3, right=3, lookback=60, recovery=3,
              detail=False):
    """The failed breakout at a swing high. At closed bar t: L is the high
    of the most recent fractal swing high confirmed before t (idx + right
    <= t - 1) and formed within `lookback` bars; k is the FIRST close above
    L after it (an accepted close, not a wick), 1 to `recovery` bars ago;
    every close from k to t - 1 held above L and bar t closes back under
    it — the buyers above are trapped. Invalid above X, the high of k..t.
    One fire per level by construction. Short only."""
    n = len(df)
    out = _false(n)
    info = {"invalidation": _nan(n), "quality": _nan(n), "level": _nan(n),
            "bars_above": _nan(n)}
    if direction != SHORT or n < left + right + 3:
        return _done(out, info, detail)
    from signals.smc.pivots import get_swings
    swings = [sw for sw in get_swings(df, left, right) if sw["type"] == "H"]
    if not swings:
        return _done(out, info, detail)
    h = df["high"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    a = atr(df).to_numpy()
    lim = contain_atr()
    first_above = {}
    for sw in swings:
        i = sw["idx"]
        above = np.flatnonzero(c[i + 1:] > h[i])
        first_above[i] = (i + 1 + int(above[0])) if len(above) else None
    ptr, cur = 0, None
    for t in range(n):
        while ptr < len(swings) and swings[ptr]["idx"] + right <= t - 1:
            cur = swings[ptr]
            ptr += 1
        if cur is None or cur["idx"] < t - lookback:
            continue
        si = cur["idx"]
        k = first_above[si]
        if k is None or not 1 <= t - k <= recovery:
            continue
        lvl = h[si]
        if not c[t] < lvl or not np.all(c[k:t] >= lvl):
            continue
        at = a[t]
        if not (np.isfinite(at) and at > 0):
            continue
        x = float(h[k:t + 1].max())
        if x > c[t] + lim * at:
            continue
        out[t] = True
        info["invalidation"][t] = x
        info["quality"][t] = _clip01((lvl - c[t]) / (0.5 * at))
        info["level"][t] = lvl
        info["bars_above"][t] = t - k
    return _done(out, info, detail)


def po3_london(df, direction, *, detail=False):
    """London sweeps the Asian high, New York distributes lower. Per New
    York trading day D (the Asian window opened at 20:00 NY on D - 1): AH
    and AL are the high and low of the Asian window's bars (three or more);
    the FIRST bar to trade over AH must open inside London (02:00-05:00
    NY), and no bar from the Asian close on may trade under AL (both sides
    run is no clean day); the fire is the first bar at or after that run to
    close back under AH, opening no later than 10:00 NY on D (the last 1h
    bar of NY AM's window). Invalid above X, the high from the run to the
    fire. One fire per day; no tz database, no fires. Honest on 1h bars
    only (Family.timeframes). Short only."""
    from datetime import time as dtime
    from datetime import timedelta
    n = len(df)
    out = _false(n)
    info = {"invalidation": _nan(n), "quality": _nan(n),
            "asian_high": _nan(n), "asian_low": _nan(n)}
    if direction != SHORT or n < 5:
        return _done(out, info, detail)
    from signals.smc.sessions import (ICT_SESSIONS_NY, new_york_index,
                                      session_windows)
    ny = new_york_index(df)
    if ny is None:
        return _done(out, info, detail)
    windows = session_windows(df, "asia", ny_index=ny)
    if not windows:
        return _done(out, info, detail)
    lon_start, lon_end = ICT_SESSIONS_NY["london"]
    last_open = dtime(10, 0)
    times, dates = ny.time, ny.date
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    a = atr(df).to_numpy()
    lim = contain_atr()
    for k, w in enumerate(windows):
        pos = w["positions"]
        if len(pos) < 3:
            continue
        day = w["date"] + timedelta(days=1)
        ah, al = float(highs[pos].max()), float(lows[pos].min())
        if not ah > al:
            continue
        start = pos[-1] + 1
        stop = windows[k + 1]["positions"][0] if k + 1 < len(windows) else n
        r = None
        for j in range(start, stop):
            if dates[j] != day or times[j] > last_open:
                break
            if lows[j] < al:
                break                       # the lows were run: unclear
            if r is None:
                if not highs[j] > ah:
                    continue
                if not lon_start <= times[j] < lon_end:
                    break                   # the highs run outside London
                r = j
            if closes[j] < ah:
                at = a[j]
                x = float(highs[r:j + 1].max())
                if np.isfinite(at) and at > 0 and x <= closes[j] + lim * at:
                    out[j] = True
                    info["invalidation"][j] = x
                    info["quality"][j] = _clip01((ah - closes[j]) / (ah - al))
                    info["asian_high"][j] = ah
                    info["asian_low"][j] = al
                break                       # one candidate a day
    return _done(out, info, detail)


def range_breakdown(df, direction, *, n=30, max_width_atr=4.0,
                    min_break_atr=0.25, detail=False):
    """The low of a tight range broken, with follow-through. At closed bar
    t: RH and RL are the high and low of the `n` bars [t-n-1, t-2], no
    wider than `max_width_atr` ATR (a consolidation, not a trend leg); bar
    t-1 closes `min_break_atr` ATR or more under RL; bar t closes under
    t-1's close with a lower low. Invalid above X, the higher of the last
    two highs. One fire per range: none within `n` bars of the last.
    Short only."""
    size = len(df)
    out = _false(size)
    info = {"invalidation": _nan(size), "quality": _nan(size),
            "range_high": _nan(size), "range_low": _nan(size)}
    if direction != SHORT or size < n + 3:
        return _done(out, info, detail)
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    rh = df["high"].rolling(n).max().to_numpy()
    rl = df["low"].rolling(n).min().to_numpy()
    a = atr(df).to_numpy()
    lim = contain_atr()
    last = None
    for t in range(n + 1, size):
        if last is not None and t - last <= n:
            continue
        top, bottom = rh[t - 2], rl[t - 2]
        a2, a1, at = a[t - 2], a[t - 1], a[t]
        if not (np.isfinite(top) and np.isfinite(bottom)
                and np.isfinite(a2) and np.isfinite(a1) and np.isfinite(at)
                and a2 > 0 and a1 > 0 and at > 0):
            continue
        if top - bottom > max_width_atr * a2:
            continue
        if not c[t - 1] < bottom - min_break_atr * a1:
            continue
        if not (c[t] < c[t - 1] and lo[t] < lo[t - 1]):
            continue
        x = float(max(h[t - 1], h[t]))
        if x > c[t] + lim * at:
            continue
        out[t] = True
        last = t
        info["invalidation"][t] = x
        info["quality"][t] = _clip01((bottom - c[t]) / at)
        info["range_high"][t] = top
        info["range_low"][t] = bottom
    return _done(out, info, detail)


def trend_rally(df, direction, *, fast=20, mid=50, slow=200, left=3,
                right=3, rally=5, detail=False):
    """The trend's continuation short: below the long average, a rally to
    the short EMA rejected under the last swing high. At closed bar t:
    EMA`fast` < EMA`mid` < SMA`slow` and the close under SMA`slow` (the
    slow line is a SIMPLE mean, exact on any window of `slow` bars, so the
    live rule's 600 bars read what the whole history reads); the bar's high
    reaches the EMA`fast` and it closes under it, red; the high of the last
    `rally` bars stays under P1, the most recent fractal swing high
    confirmed by t — a lower high. Invalid above that rally high. One fire
    per swing high P1. Short only."""
    size = len(df)
    out = _false(size)
    info = {"invalidation": _nan(size), "quality": _nan(size),
            "swing_high": _nan(size)}
    if direction != SHORT or size < slow + 1:
        return _done(out, info, detail)
    from signals.smc.pivots import get_swings
    swings = [sw for sw in get_swings(df, left, right) if sw["type"] == "H"]
    c = df["close"]
    ef = c.ewm(span=fast, adjust=False).mean().to_numpy()
    em = c.ewm(span=mid, adjust=False).mean().to_numpy()
    ss = c.rolling(slow).mean().to_numpy()
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    cl = c.to_numpy(dtype=float)
    a = atr(df).to_numpy()
    lim = contain_atr()
    used = set()
    ptr, cur = 0, None
    for t in range(size):
        while ptr < len(swings) and swings[ptr]["idx"] + right <= t:
            cur = swings[ptr]
            ptr += 1
        if t < slow or cur is None or cur["idx"] in used:
            continue
        if not (np.isfinite(ss[t]) and ef[t] < em[t] < ss[t]
                and cl[t] < ss[t]):
            continue
        if not (h[t] >= ef[t] and cl[t] < ef[t] and cl[t] < o[t]):
            continue
        p1 = h[cur["idx"]]
        xr = float(h[max(0, t - rally + 1):t + 1].max())
        if not xr < p1:
            continue
        at = a[t]
        if not (np.isfinite(at) and at > 0) or xr > cl[t] + lim * at:
            continue
        out[t] = True
        used.add(cur["idx"])
        info["invalidation"][t] = xr
        info["quality"][t] = _clip01((p1 - xr) / at)
        info["swing_high"][t] = p1
    return _done(out, info, detail)


def exhaustion_short(df, direction, *, trend=200, rally=10,
                     min_rally_atr=2.5, wick=0.5, rsi_min=55.0,
                     detail=False):
    """The exhaustion short on a relief rally in a down tape. At closed bar
    t: the close under its SMA`trend`; the bar's high is the high of the
    last `rally` bars, `min_rally_atr` ATR or more over their low; an upper
    wick of `wick` of the bar's range or more, a red bar, RSI14 at
    `rsi_min` or more. Invalid above the bar's high. The live rule adds a
    regime gate (the Mind's risk_off, or the stress level) that this
    replay does not read: the Mind's labels and the stress readings have
    no multi-year history, so every live fire is a subset of the judged
    fires. Short only."""
    size = len(df)
    out = _false(size)
    info = {"invalidation": _nan(size), "quality": _nan(size),
            "wick_share": _nan(size), "rally_atr": _nan(size)}
    if direction != SHORT or size < max(trend, rally) + 1:
        return _done(out, info, detail)
    o, h, lo, c = (df[k] for k in ("open", "high", "low", "close"))
    a = atr(df)
    sma = c.rolling(trend).mean()
    hh = h.rolling(rally).max()
    ll = lo.rolling(rally).min()
    r = rsi(c, 14)
    rng = (h - lo).replace(0, np.nan)
    upper = h - np.maximum(o, c)
    share = upper / rng
    lim = contain_atr()
    cond = ((c < sma) & (h >= hh) & ((h - ll) >= min_rally_atr * a)
            & (share >= wick) & (c < o) & (r >= rsi_min)
            & (h <= c + lim * a) & (a > 0))
    out = cond.fillna(False).to_numpy(dtype=bool)
    info["invalidation"] = np.where(out, h.to_numpy(dtype=float), np.nan)
    info["quality"] = np.where(
        out, np.clip((share.to_numpy() - wick) / 0.3, 0.0, 1.0), np.nan)
    info["wick_share"] = np.where(out, share.to_numpy(), np.nan)
    info["rally_atr"] = np.where(out, ((h - ll) / a).to_numpy(), np.nan)
    return _done(out, info, detail)


def vix_term_breakdown(df, direction, *, inverted=1.0, n=10, detail=False):
    """The index risk-off short: VIX/VIX3M at `inverted` or more on the
    bar's context (the `vix_term` column, the PREVIOUS New York day's
    published ratio — backtester/proving/context.py) and the FIRST close
    under the low of the last `n` bars. Invalid above the bar's high. No
    column, no fires. Short only."""
    size = len(df)
    out = _false(size)
    info = {"invalidation": _nan(size), "quality": _nan(size),
            "vix_term": _nan(size)}
    if direction != SHORT or "vix_term" not in df.columns or size < n + 2:
        return _done(out, info, detail)
    h, c = df["high"], df["close"]
    v = pd.to_numeric(df["vix_term"], errors="coerce")
    low_n = df["low"].rolling(n).min().shift(1)
    a = atr(df)
    lim = contain_atr()
    cond = ((v >= inverted) & (c < low_n) & (c.shift(1) >= low_n.shift(1))
            & (h <= c + lim * a) & (a > 0))
    out = cond.fillna(False).to_numpy(dtype=bool)
    info["invalidation"] = np.where(out, h.to_numpy(dtype=float), np.nan)
    info["quality"] = np.where(
        out, np.clip((v.to_numpy(dtype=float) - inverted) / 0.10, 0.0, 1.0),
        np.nan)
    info["vix_term"] = np.where(out, v.to_numpy(dtype=float), np.nan)
    return _done(out, info, detail)


def crowded_long_trigger(df, *, left=3, right=3, top=60, near=30):
    """The price half of crowded_long, without the crowd: (fires, detail).
    At closed bar t: HH is the high of the last `top` bars, made at bar h
    within `near` bars; s is the most recent fractal swing low after h,
    confirmed before t; bar t is the FIRST close under its low — the top's
    structure breaks. Invalid above X, the high from s to t."""
    size = len(df)
    out = _false(size)
    info = {"invalidation": _nan(size), "swing_low": _nan(size),
            "top": _nan(size)}
    if size < max(top, left + right + 3):
        return out, info
    from signals.smc.pivots import get_swings
    swings = [sw for sw in get_swings(df, left, right) if sw["type"] == "L"]
    if not swings:
        return out, info
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    a = atr(df).to_numpy()
    lim = contain_atr()
    ptr, cur = 0, None
    for t in range(1, size):
        while ptr < len(swings) and swings[ptr]["idx"] + right <= t - 1:
            cur = swings[ptr]
            ptr += 1
        if cur is None or t < top - 1:
            continue
        win = h[t - top + 1:t + 1]
        hi_at = t - top + 1 + (len(win) - 1 - int(np.argmax(win[::-1])))
        if t - hi_at > near or not cur["idx"] > hi_at:
            continue
        sl = lo[cur["idx"]]
        if not (c[t] < sl and c[t - 1] >= sl):
            continue
        at = a[t]
        x = float(h[cur["idx"]:t + 1].max())
        if not (np.isfinite(at) and at > 0) or x > c[t] + lim * at:
            continue
        out[t] = True
        info["invalidation"][t] = x
        info["swing_low"][t] = sl
        info["top"][t] = h[hi_at]
    return out, info


def crowded_long(df, direction, *, left=3, right=3, top=60, near=30,
                 cot_extreme=COT_EXTREME, detail=False):
    """The contrarian short at an extreme crowded long: the speculators'
    COT index at `cot_extreme` or more on the bar (the `cot_spec_index`
    column, each report read from its publication — backtester/proving/
    context.cot_released_at) and crowded_long_trigger's break of the
    top's swing low. A market no COT report maps is
    positioning_crowd_reversal_short's, a rule of its own: no history
    replays the positioning map's crowd score, so no family judges it. No
    column, no fires. Short only."""
    size = len(df)
    out = _false(size)
    info = {"invalidation": _nan(size), "quality": _nan(size),
            "spec_index": _nan(size)}
    if direction != SHORT or "cot_spec_index" not in df.columns:
        return _done(out, info, detail)
    fires, trig = crowded_long_trigger(df, left=left, right=right, top=top,
                                       near=near)
    spec = pd.to_numeric(df["cot_spec_index"],
                         errors="coerce").to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        gate = np.nan_to_num(spec >= cot_extreme, nan=False).astype(bool)
    out = fires & gate
    info["invalidation"] = np.where(out, trig["invalidation"], np.nan)
    info["quality"] = np.where(
        out, np.clip((spec - cot_extreme) / 10.0, 0.0, 1.0), np.nan)
    info["spec_index"] = np.where(out, spec, np.nan)
    return _done(out, info, detail)


# ── which markets a bearish family's live rule fires on ─────────────────

def session_markets(symbol, asset_class) -> bool:
    """po3_london: the markets with 1h bars inside the Asian and London
    windows. Stocks and ETFs have none."""
    return str(asset_class or "").lower() in ("forex", "commodity", "index",
                                              "crypto")


def risk_on_short_market(symbol, asset_class) -> bool:
    """A SELL of a risk asset (bot_program.posture.classify): stocks,
    non-haven ETFs, indices, crypto, non-haven commodities. Never gold,
    silver, treasuries, the dollar index, nor forex."""
    from bot_program.posture import RISK_ON_SHORT, classify
    return classify(symbol, asset_class, "SELL") == RISK_ON_SHORT


def index_market(symbol, asset_class) -> bool:
    """An index, or a US index ETF (bearish_rules.INDEX_ETFS), as a risk
    asset."""
    from signals.rules.bearish_rules import INDEX_ETFS
    cls = str(asset_class or "").lower()
    sym = str(symbol or "").upper()
    if cls == "index" or (cls == "etf" and sym in INDEX_ETFS):
        return risk_on_short_market(symbol, asset_class)
    return False


def cot_market(symbol, asset_class) -> bool:
    """A market a COT report maps (scraping.COTReport rows): the only
    markets whose crowd the proving ground can replay."""
    from scraping.models import COTReport
    return COTReport.objects.filter(instrument__symbol=symbol).exists()


# ── filters ──────────────────────────────────────────────────────────────

def apply_filter(df, fires, direction, flt, timeframe="4h"):
    if flt == "none" or flt is None:
        return fires
    c = df["close"]
    if flt == "trend":
        s = c.rolling(200).mean()
        ok = (c > s) if direction == LONG else (c < s)
    elif flt == "macro_trend":
        s = c.rolling(MACRO_TREND_BARS.get(timeframe, 1200)).mean()
        ok = (c > s) if direction == LONG else (c < s)
    elif flt == "discount":
        hi = df["high"].rolling(DISCOUNT_RANGE).max()
        lo = df["low"].rolling(DISCOUNT_RANGE).min()
        eq = (hi + lo) / 2
        ok = (c < eq) if direction == LONG else (c > eq)
    else:
        raise ValueError(f"unknown filter {flt!r}")
    return fires & ok.fillna(False).to_numpy(dtype=bool)


# ── the registry ─────────────────────────────────────────────────────────

class Family:
    def __init__(self, key, fn, defaults, grid, *, live_rules=None,
                 directions=(LONG, SHORT), timeframes=None, eligible=None,
                 in_generate=True):
        self.key = key
        self.fn = fn
        self.defaults = dict(defaults)
        self.grid = [dict(g) for g in grid]
        #: {direction: the live rule this family IS at its defaults}
        self.live_rules = dict(live_rules or {})
        self.directions = tuple(directions)
        #: The timeframes its live rule trades: None is every run's own
        #: (today's meaning); ("1h",) is judged by the 1h pass only.
        self.timeframes = tuple(timeframes) if timeframes else None
        #: callable(symbol, asset_class) -> bool: the markets its live rule
        #: can fire on. A class verdict pools only those (run.eligible_view).
        self.eligible = eligible
        #: False keeps the family out of the weekly generator's default
        #: grid (its Sidak bar and shortlist); `--families` still asks.
        self.in_generate = bool(in_generate)

    def judged_on(self, timeframe) -> bool:
        return self.timeframes is None or timeframe in self.timeframes

    def is_eligible(self, symbol, asset_class) -> bool:
        if self.eligible is None:
            return True
        try:
            return bool(self.eligible(symbol, asset_class))
        except Exception:  # noqa: BLE001 — unread is not a market it fires on
            return False

    def fires(self, df, direction, params=None, flt="none", timeframe="4h"):
        p = dict(self.defaults, **(params or {}))
        return apply_filter(df, self.fn(df, direction, **p), direction, flt,
                            timeframe)


FAMILIES = {f.key: f for f in (
    Family("rsi_divergence", rsi_divergence,
           {"period": 14, "gate": 35.0, "window": 30},
           [{"window": 20}, {"window": 30}, {"window": 30, "gate": 30.0},
            {"window": 45}],
           live_rules={LONG: "rsi_bull_divergence",
                       SHORT: "rsi_bear_divergence"}),
    Family("macd_cross", macd_cross,
           {"fast": 12, "slow": 26, "signal": 9},
           [{"fast": 8, "slow": 21, "signal": 5}, {},
            {"fast": 19, "slow": 39, "signal": 9}],
           live_rules={LONG: "macd_bullish_crossover",
                       SHORT: "macd_bearish_crossover"}),
    Family("ma_cross", ma_cross, {"fast": 50, "slow": 200},
           [{"fast": 10, "slow": 50}, {"fast": 20, "slow": 100}, {}],
           live_rules={LONG: "golden_cross", SHORT: "death_cross"}),
    Family("bb_squeeze", bb_squeeze,
           {"period": 20, "k": 2.0, "quantile": 0.2, "lookback": 120,
            "expand": 1.1},
           [{}, {"quantile": 0.1}, {"expand": 1.2}],
           live_rules={LONG: "bollinger_squeeze_breakout",
                       SHORT: "bollinger_squeeze_breakout"}),
    Family("donchian", donchian, {"n": 20}, [{"n": 20}, {"n": 55}]),
    Family("rsi_reversion", rsi_reversion, {"period": 14, "low": 30.0},
           [{"low": 30.0}, {"low": 25.0}, {"period": 7, "low": 20.0}]),
    Family("ema_pullback", ema_pullback, {"fast": 20, "mid": 50, "slow": 200},
           [{}, {"fast": 10, "mid": 30}]),
    Family("fvg_retest", fvg_retest, {"max_age": 20, "min_gap_atr": 0.1},
           [{"max_age": 10}, {}, {"min_gap_atr": 0.3}]),
    Family("sweep_reversal", sweep_reversal, {"n": 20},
           [{"n": 20}, {"n": 50}]),
    Family("pool_sweep", pool_sweep, {"touches": 2},
           [{"touches": 2}, {"touches": 3}]),
    Family("po3", po3, {"session": "asia"}, [{"session": "asia"}]),
    Family("tsmom", tsmom, {"n": 1000, "trigger": 20},
           [{"n": 500}, {"n": 1000}, {"n": 1500}, {"n": 1000, "trigger": 55}]),
    Family("rsi2_pullback", rsi2_pullback,
           {"period": 2, "low": 10.0, "trend": 200},
           [{}, {"low": 5.0}, {"period": 3, "low": 15.0}]),
    # the bearish pack (2026-10-31): short only, born at research, out of
    # the weekly generator
    Family("bull_trap", bull_trap,
           {"left": 3, "right": 3, "lookback": 60, "recovery": 3}, [{}],
           live_rules={SHORT: "bull_trap_swing_high"}, directions=(SHORT,),
           in_generate=False),
    Family("po3_london", po3_london, {}, [{}],
           live_rules={SHORT: "po3_london_sweep_short"}, directions=(SHORT,),
           timeframes=("1h",), eligible=session_markets, in_generate=False),
    Family("range_breakdown", range_breakdown,
           {"n": 30, "max_width_atr": 4.0, "min_break_atr": 0.25}, [{}],
           live_rules={SHORT: "range_breakdown_short"}, directions=(SHORT,),
           in_generate=False),
    Family("trend_rally", trend_rally,
           {"fast": 20, "mid": 50, "slow": 200, "left": 3, "right": 3,
            "rally": 5}, [{}],
           live_rules={SHORT: "trend_continuation_short"},
           directions=(SHORT,), in_generate=False),
    Family("exhaustion_short", exhaustion_short,
           {"trend": 200, "rally": 10, "min_rally_atr": 2.5, "wick": 0.5,
            "rsi_min": 55.0}, [{}],
           live_rules={SHORT: "risk_off_exhaustion_short"},
           directions=(SHORT,), eligible=risk_on_short_market,
           in_generate=False),
    Family("vix_term_breakdown", vix_term_breakdown,
           {"inverted": 1.0, "n": 10}, [{}],
           live_rules={SHORT: "vix_inversion_index_short"},
           directions=(SHORT,), eligible=index_market, in_generate=False),
    Family("crowded_long", crowded_long,
           {"left": 3, "right": 3, "top": 60, "near": 30,
            "cot_extreme": 90.0}, [{}],
           live_rules={SHORT: "crowded_long_reversal_short"},
           directions=(SHORT,), eligible=cot_market, in_generate=False),
)}


def live_rule_cases(timeframe="4h", *, pinned_only=False):
    """[(family, direction)] — every live rule as it trades today, and the
    short mirror of a family that maps no short rule, at the family's
    defaults with no filter: the families judged on `timeframe` (a family
    with no `timeframes` is judged on every run's own). `pinned_only`
    keeps only the families that NAME `timeframe` — the nightly 1h pass,
    which must not re-judge the 4h rules on 1h bars."""
    out = []
    for fam in FAMILIES.values():
        if not fam.live_rules:
            continue
        if pinned_only and not (fam.timeframes and timeframe in fam.timeframes):
            continue
        if not fam.judged_on(timeframe):
            continue
        for d in fam.directions:
            out.append((fam, d))
    return out


def family_of(rule_name):
    """(family, direction) whose live rule is `rule_name` (a fork reads its
    root's), or None."""
    name = str(rule_name or "")
    try:
        from signals.rule_birth import root_name
        root = root_name(name)
    except Exception:  # noqa: BLE001
        root = name
    for fam in FAMILIES.values():
        for d, live in fam.live_rules.items():
            if live in (name, root):
                return fam, d
    return None
