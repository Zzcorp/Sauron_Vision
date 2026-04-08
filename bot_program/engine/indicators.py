"""Lightweight TA indicators — zero third-party deps."""
from __future__ import annotations
from statistics import mean, pstdev

def ema(values, period):
    if len(values) < period: return []
    k = 2 / (period + 1)
    out = [mean(values[:period])]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def rsi(values, period: int = 14) -> float:
    if len(values) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        d = values[-i] - values[-i-1]
        (gains if d >= 0 else losses).append(abs(d))
    avg_g = sum(gains)/period if gains else 0
    avg_l = sum(losses)/period if losses else 1e-9
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))

def macd(values, fast=12, slow=26, sig=9):
    if len(values) < slow + sig: return (0.0, 0.0, 0.0)
    ef, es = ema(values, fast), ema(values, slow)
    n = min(len(ef), len(es))
    macd_line = [ef[-n+i] - es[-n+i] for i in range(n)]
    signal = ema(macd_line, sig) if len(macd_line) >= sig else [0]
    return (macd_line[-1], signal[-1], macd_line[-1] - signal[-1])

def vwap(ohlcv) -> float:
    num = den = 0
    for o,h,l,c,v in ohlcv:
        tp = (h + l + c) / 3
        num += tp * v; den += v
    return num/den if den else 0

def atr(ohlc, period: int = 14) -> float:
    if len(ohlc) < period + 1: return 0
    trs = []
    for i in range(1, len(ohlc)):
        h, l, c_prev = ohlc[i][1], ohlc[i][2], ohlc[i-1][3]
        trs.append(max(h-l, abs(h-c_prev), abs(l-c_prev)))
    return mean(trs[-period:])

def volatility(values, period: int = 20) -> float:
    if len(values) < period: return 0
    return pstdev(values[-period:])
