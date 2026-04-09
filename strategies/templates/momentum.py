"""Momentum strategy template — time-series and cross-sectional."""
from datetime import timedelta


def time_series_momentum(symbol, lookback_days=90, df=None):
    """Returns +1 (long bias) if 12-1 month return is positive, else -1.

    Classic Moskowitz/Asness time-series momentum: skip the most recent
    period to avoid 1-month reversal.
    """
    if df is None:
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, "1d", bars=400)
    if df is None or len(df) < lookback_days + 30:
        return None
    end_idx = len(df) - 21          # skip last ~1 month
    start_idx = end_idx - lookback_days
    if start_idx < 0:
        return None
    p_start = float(df["close"].iloc[start_idx])
    p_end = float(df["close"].iloc[end_idx])
    if p_start <= 0:
        return None
    ret = (p_end - p_start) / p_start
    return {
        "symbol": symbol,
        "strategy": "time_series_momentum",
        "direction": "LONG" if ret > 0 else "SHORT",
        "score": min(1.0, abs(ret) * 4),
        "lookback_return_pct": round(ret * 100, 2),
        "thesis": (
            f"{symbol} 12-1 month return: {ret*100:+.1f}%. "
            f"{'Long' if ret > 0 else 'Short'} bias by classical TSMOM."
        ),
    }


def cross_sectional_momentum(symbols, lookback_days=90, top_pct=0.2):
    """Rank a universe of symbols by lookback return; long the top decile."""
    from signals.smc.dataframe import load_ohlcv
    scored = []
    for sym in symbols:
        df = load_ohlcv(sym, "1d", bars=lookback_days + 40)
        if df is None or len(df) < lookback_days + 5:
            continue
        end = len(df) - 1
        start = end - lookback_days
        p0 = float(df["close"].iloc[start])
        p1 = float(df["close"].iloc[end])
        if p0 <= 0:
            continue
        ret = (p1 - p0) / p0
        scored.append((sym, ret))
    scored.sort(key=lambda x: x[1], reverse=True)
    n_top = max(1, int(len(scored) * top_pct))
    n_bot = max(1, int(len(scored) * top_pct))
    longs = scored[:n_top]
    shorts = scored[-n_bot:]
    return {
        "strategy": "cross_sectional_momentum",
        "longs": [{"symbol": s, "ret_pct": round(r * 100, 2)} for s, r in longs],
        "shorts": [{"symbol": s, "ret_pct": round(r * 100, 2)} for s, r in shorts],
        "universe_size": len(scored),
    }
