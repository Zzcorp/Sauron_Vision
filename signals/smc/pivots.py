"""Fractal-based swing pivot detection with HH/HL/LH/LL classification."""
import numpy as np


def find_pivots(df, left=3, right=3):
    """Return arrays (pivot_high, pivot_low) marking fractal swing points.

    A bar i is a swing high if its high is the strict max within
    [i-left, i+right]. Symmetric for swing lows.
    """
    n = len(df)
    highs = df["high"].values
    lows = df["low"].values
    pivot_high = np.zeros(n, dtype=bool)
    pivot_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        wh = highs[i - left:i + right + 1]
        wl = lows[i - left:i + right + 1]
        if highs[i] == wh.max() and wh.argmax() == left:
            pivot_high[i] = True
        if lows[i] == wl.min() and wl.argmin() == left:
            pivot_low[i] = True
    return pivot_high, pivot_low


def get_swings(df, left=3, right=3):
    """Return list of swing dicts: {idx, type 'H'/'L', price, ts}."""
    ph, pl = find_pivots(df, left, right)
    swings = []
    for i in range(len(df)):
        if ph[i]:
            swings.append({
                "idx": i, "type": "H",
                "price": float(df["high"].iloc[i]),
                "ts": df.index[i],
            })
        if pl[i]:
            swings.append({
                "idx": i, "type": "L",
                "price": float(df["low"].iloc[i]),
                "ts": df.index[i],
            })
    swings.sort(key=lambda s: s["idx"])
    return swings


def classify_swings(swings):
    """Tag each swing with its label relative to the previous same-type swing.

    Labels: H/L for the first, then HH/LH for highs and HL/LL for lows.
    """
    last_h = None
    last_l = None
    for s in swings:
        if s["type"] == "H":
            if last_h is None:
                s["label"] = "H"
            elif s["price"] > last_h["price"]:
                s["label"] = "HH"
            else:
                s["label"] = "LH"
            last_h = s
        else:
            if last_l is None:
                s["label"] = "L"
            elif s["price"] > last_l["price"]:
                s["label"] = "HL"
            else:
                s["label"] = "LL"
            last_l = s
    return swings


def atr(df, period=14):
    """Average True Range as a numpy array."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    out = np.zeros(n)
    if n >= period:
        out[period - 1] = tr[:period].mean()
        for i in range(period, n):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out
