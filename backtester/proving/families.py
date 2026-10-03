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
                 directions=(LONG, SHORT)):
        self.key = key
        self.fn = fn
        self.defaults = dict(defaults)
        self.grid = [dict(g) for g in grid]
        #: {direction: the live rule this family IS at its defaults}
        self.live_rules = dict(live_rules or {})
        self.directions = tuple(directions)

    def fires(self, df, direction, params=None, flt="none", timeframe="4h"):
        p = dict(self.defaults, **(params or {}))
        return apply_filter(df, self.fn(df, direction, **p), direction, flt,
                            timeframe)


FAMILIES = {f.key: f for f in (
    Family("rsi_divergence", rsi_divergence,
           {"period": 14, "gate": 35.0, "window": 30},
           [{"window": 20}, {"window": 30}, {"window": 30, "gate": 30.0},
            {"window": 45}],
           live_rules={LONG: "rsi_bull_divergence"}),
    Family("macd_cross", macd_cross,
           {"fast": 12, "slow": 26, "signal": 9},
           [{"fast": 8, "slow": 21, "signal": 5}, {},
            {"fast": 19, "slow": 39, "signal": 9}],
           live_rules={LONG: "macd_bullish_crossover"}),
    Family("ma_cross", ma_cross, {"fast": 50, "slow": 200},
           [{"fast": 10, "slow": 50}, {"fast": 20, "slow": 100}, {}],
           live_rules={LONG: "golden_cross"}),
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
)}


def live_rule_cases():
    """[(family, direction)] — every live rule as it trades today, and its
    short mirror, at the family's defaults with no filter."""
    out = []
    for fam in FAMILIES.values():
        if fam.live_rules:
            for d in fam.directions:
                out.append((fam, d))
    return out
