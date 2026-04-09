"""Market regime detection: vol percentile, ADX, Hurst, regime label."""
import math
import numpy as np


def realized_vol(close, window=20):
    """Annualized realized volatility from log returns."""
    import pandas as pd
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window).std() * math.sqrt(365)


def vol_percentile(close, window=20, lookback=120):
    """Current realized vol's percentile vs lookback distribution (0..1)."""
    rv = realized_vol(close, window).dropna()
    if len(rv) < lookback:
        return None
    recent = rv.iloc[-lookback:]
    last = rv.iloc[-1]
    return float((recent < last).mean())


def adx(df, period=14):
    """ADX trend strength (0..100). Higher = stronger trend."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    if n < period * 2:
        return None
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    atr = np.zeros(n)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    if n >= period:
        atr[period] = tr[1:period + 1].mean()
        plus_di[period] = 100 * plus_dm[1:period + 1].sum() / max(atr[period] * period, 1e-9)
        minus_di[period] = 100 * minus_dm[1:period + 1].sum() / max(atr[period] * period, 1e-9)
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            plus_di[i] = 100 * (plus_di[i - 1] * (period - 1) + plus_dm[i]) / period / max(atr[i], 1e-9) if False else plus_di[i - 1]
            minus_di[i] = minus_di[i - 1]
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    return float(dx[-period:].mean()) if n > period else None


def hurst_exponent(series, max_lag=20):
    """Hurst exponent. <0.5 mean-reverting, ~0.5 random, >0.5 trending."""
    series = np.asarray(series, dtype=float)
    if len(series) < max_lag * 2:
        return None
    lags = range(2, max_lag)
    tau = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]
        std = np.std(diff)
        tau.append(max(std, 1e-9))
    poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(poly[0] * 2)


def regime_label(df):
    """Composite regime: returns one of
    'trending_high_vol', 'trending_low_vol',
    'ranging_high_vol', 'ranging_low_vol', 'unknown'.
    """
    if df is None or len(df) < 60:
        return "unknown"
    vp = vol_percentile(df["close"])
    h = hurst_exponent(df["close"].values)
    if vp is None or h is None:
        return "unknown"
    high_vol = vp > 0.6
    trending = h > 0.55
    if trending and high_vol:
        return "trending_high_vol"
    if trending and not high_vol:
        return "trending_low_vol"
    if not trending and high_vol:
        return "ranging_high_vol"
    return "ranging_low_vol"
