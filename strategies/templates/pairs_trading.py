"""Pairs trading strategy template — cointegration spread fade."""
import math


def compute_spread(prices_a, prices_b):
    """Simple log-spread between two price series."""
    if len(prices_a) != len(prices_b) or len(prices_a) < 2:
        return None
    return [math.log(a) - math.log(b) for a, b in zip(prices_a, prices_b) if a > 0 and b > 0]


def spread_zscore(spread_series, lookback=60):
    """Z-score of the most recent spread vs lookback window."""
    if len(spread_series) < lookback + 1:
        return None
    window = spread_series[-lookback:]
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    std = math.sqrt(var)
    if std <= 0:
        return None
    return (spread_series[-1] - mean) / std


def pairs_signal(symbol_a, symbol_b, lookback=60, threshold=2.0):
    """Long-A/short-B when spread is below -threshold; reverse on +threshold."""
    from signals.smc.dataframe import load_ohlcv
    df_a = load_ohlcv(symbol_a, "1d", bars=lookback + 20)
    df_b = load_ohlcv(symbol_b, "1d", bars=lookback + 20)
    if df_a is None or df_b is None:
        return None
    a = [float(x) for x in df_a["close"].tolist()][-(lookback + 5):]
    b = [float(x) for x in df_b["close"].tolist()][-(lookback + 5):]
    spread = compute_spread(a, b)
    if not spread:
        return None
    z = spread_zscore(spread, lookback=min(lookback, len(spread) - 1))
    if z is None or abs(z) < threshold:
        return None
    if z < 0:
        action = (f"long {symbol_a}", f"short {symbol_b}")
    else:
        action = (f"short {symbol_a}", f"long {symbol_b}")
    return {
        "strategy": "pairs_trading",
        "symbol_a": symbol_a, "symbol_b": symbol_b,
        "spread_zscore": round(z, 2),
        "actions": action,
        "thesis": (
            f"{symbol_a}/{symbol_b} spread at {z:+.1f}σ vs {lookback}d baseline. "
            f"Mean-reversion pair trade."
        ),
    }
