"""Mean reversion strategy template — z-score and Bollinger fade."""


def zscore_reversion(symbol, period=20, threshold=2.0, df=None):
    """Long when price is z<-threshold below its N-period mean, short when z>+threshold."""
    if df is None:
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, "4h", bars=200)
    if df is None or len(df) < period + 5:
        return None
    closes = df["close"]
    mean = closes.rolling(period).mean().iloc[-1]
    std = closes.rolling(period).std().iloc[-1]
    if not std or std <= 0:
        return None
    last = float(closes.iloc[-1])
    z = (last - float(mean)) / float(std)
    if abs(z) < threshold:
        return None
    direction = "LONG" if z < 0 else "SHORT"
    return {
        "symbol": symbol,
        "strategy": "zscore_reversion",
        "direction": direction,
        "z_score": round(z, 2),
        "score": min(1.0, abs(z) / 4),
        "thesis": (
            f"{symbol} at {z:+.1f}σ vs {period}-bar mean. "
            f"Mean reversion {'long' if direction == 'LONG' else 'short'} setup."
        ),
        "entry": last,
        "stop": last * (0.98 if direction == "LONG" else 1.02),
        "target": float(mean),
    }


def bollinger_fade(symbol, period=20, k=2.0, df=None):
    """Fade Bollinger band touches with RSI confirmation."""
    if df is None:
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, "4h", bars=200)
    if df is None or len(df) < period + 14:
        return None
    closes = df["close"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = mid + k * std
    lower = mid - k * std
    last = float(closes.iloc[-1])
    last_upper = float(upper.iloc[-1])
    last_lower = float(lower.iloc[-1])
    last_mid = float(mid.iloc[-1])

    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    last_rsi = float(rsi.iloc[-1])

    if last >= last_upper and last_rsi > 70:
        return {
            "symbol": symbol, "strategy": "bollinger_fade",
            "direction": "SHORT",
            "score": 0.65,
            "thesis": f"Price tagged upper BB with RSI {last_rsi:.0f}. Fade.",
            "entry": last, "stop": last * 1.02, "target": last_mid,
        }
    if last <= last_lower and last_rsi < 30:
        return {
            "symbol": symbol, "strategy": "bollinger_fade",
            "direction": "LONG",
            "score": 0.65,
            "thesis": f"Price tagged lower BB with RSI {last_rsi:.0f}. Fade.",
            "entry": last, "stop": last * 0.98, "target": last_mid,
        }
    return None
