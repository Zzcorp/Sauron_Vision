"""Technical analysis signal rules — real implementations.

Each rule operates on a pandas DataFrame loaded via signals.smc.dataframe.
Returns a dict matching the signal "card" shape, or None.
"""
import logging

logger = logging.getLogger(__name__)


class BaseRule:
    """Base class for signal rules."""
    name = "base_rule"
    signal_type = "technical"

    def evaluate(self, instrument):
        raise NotImplementedError


def _load_df(instrument, timeframe="4h", bars=300):
    from signals.smc.dataframe import load_ohlcv
    symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
    if not symbol:
        return None, None
    df = load_ohlcv(symbol, timeframe, bars)
    return symbol, df


def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def _bollinger(close, period=20, k=2.0):
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return mid + k * std, mid, mid - k * std


def _bb_width(close, period=20, k=2.0):
    upper, mid, lower = _bollinger(close, period, k)
    return (upper - lower) / mid.replace(0, 1e-9)


class RSIDivergenceRule(BaseRule):
    """RSI bullish divergence: price lower-low, RSI higher-low, RSI < 35."""
    name = "rsi_bull_divergence"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        if df is None or len(df) < 60:
            return None
        rsi = _rsi(df["close"])
        last_rsi = float(rsi.iloc[-1])
        if last_rsi >= 35:
            return None
        recent_low_idx = df["low"].iloc[-30:].idxmin()
        prior_low_idx = df["low"].iloc[-60:-30].idxmin()
        if df["low"].loc[recent_low_idx] < df["low"].loc[prior_low_idx] and \
           rsi.loc[recent_low_idx] > rsi.loc[prior_low_idx]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.7,
                "headline": f"{symbol} LONG · RSI bullish divergence",
                "thesis": (
                    f"Price made a lower low while RSI made a higher low "
                    f"(RSI={last_rsi:.0f}). Momentum exhaustion."
                ),
                "entry": close,
                "stop": close * 0.985,
                "target": close * 1.03,
            }
        return None


class MACDCrossoverRule(BaseRule):
    """MACD bullish crossover (line crosses above signal) with hist accel."""
    name = "macd_bullish_crossover"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        if df is None or len(df) < 40:
            return None
        line, sig, hist = _macd(df["close"])
        if line.iloc[-2] <= sig.iloc[-2] and line.iloc[-1] > sig.iloc[-1] \
                and hist.iloc[-1] > hist.iloc[-2]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.55,
                "headline": f"{symbol} LONG · MACD bullish crossover",
                "thesis": "MACD line crossed above signal with histogram accelerating.",
                "entry": close,
                "stop": close * 0.98,
                "target": close * 1.04,
            }
        return None


class GoldenCrossRule(BaseRule):
    """SMA50 crosses above SMA200."""
    name = "golden_cross"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument, bars=300)
        if df is None or len(df) < 210:
            return None
        sma50 = df["close"].rolling(50).mean()
        sma200 = df["close"].rolling(200).mean()
        if sma50.iloc[-2] <= sma200.iloc[-2] and sma50.iloc[-1] > sma200.iloc[-1]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.6,
                "headline": f"{symbol} LONG · Golden cross",
                "thesis": "SMA50 crossed above SMA200 — long-term trend flip up.",
                "entry": close,
                "stop": close * 0.95,
                "target": close * 1.10,
            }
        return None


class BollingerSqueezeRule(BaseRule):
    """BB width in bottom percentile then expansion bar."""
    name = "bollinger_squeeze_breakout"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument, bars=200)
        if df is None or len(df) < 120:
            return None
        width = _bb_width(df["close"])
        recent_pct = (width.iloc[-30:-1] < width.iloc[-1]).mean()
        squeezed = width.iloc[-2] < width.iloc[-120:-2].quantile(0.2)
        expanding = width.iloc[-1] > width.iloc[-2] * 1.1
        if squeezed and expanding and recent_pct > 0.7:
            close = float(df["close"].iloc[-1])
            prev_close = float(df["close"].iloc[-2])
            direction = "LONG" if close > prev_close else "SHORT"
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": direction,
                "score": 0.6,
                "headline": f"{symbol} {direction} · BB squeeze breakout",
                "thesis": "Bollinger Band width compressed to 20th percentile, now expanding.",
                "entry": close,
                "stop": close * (0.98 if direction == "LONG" else 1.02),
                "target": close * (1.04 if direction == "LONG" else 0.96),
            }
        return None


def get_rules():
    """Return all technical rules."""
    return [
        RSIDivergenceRule(),
        MACDCrossoverRule(),
        GoldenCrossRule(),
        BollingerSqueezeRule(),
    ]
