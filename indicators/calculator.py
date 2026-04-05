"""Technical indicator computation engine."""
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD — returns (macd_line, signal_line, histogram)."""
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands — returns (upper, middle, lower)."""
    middle = calculate_sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return upper, middle, lower


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                         k_period: int = 14, d_period: int = 3):
    """Stochastic Oscillator — returns (K, D)."""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    return k, d


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff())
    return (volume * direction).cumsum()


def compute_all_indicators(df: pd.DataFrame) -> dict:
    """
    Compute all technical indicators from an OHLCV DataFrame.
    Expects columns: open, high, low, close, volume.
    Returns dict of indicator values for the latest row.
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    rsi = calculate_rsi(close)
    macd_line, macd_signal, macd_hist = calculate_macd(close)
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(close)
    stoch_k, stoch_d = calculate_stochastic(high, low, close)
    atr = calculate_atr(high, low, close)
    obv = calculate_obv(close, volume)

    latest = len(df) - 1
    return {
        "sma_20": calculate_sma(close, 20).iloc[latest],
        "sma_50": calculate_sma(close, 50).iloc[latest] if len(df) >= 50 else None,
        "sma_200": calculate_sma(close, 200).iloc[latest] if len(df) >= 200 else None,
        "ema_12": calculate_ema(close, 12).iloc[latest],
        "ema_26": calculate_ema(close, 26).iloc[latest],
        "rsi_14": rsi.iloc[latest],
        "macd_line": macd_line.iloc[latest],
        "macd_signal": macd_signal.iloc[latest],
        "macd_histogram": macd_hist.iloc[latest],
        "stoch_k": stoch_k.iloc[latest],
        "stoch_d": stoch_d.iloc[latest],
        "bollinger_upper": bb_upper.iloc[latest],
        "bollinger_lower": bb_lower.iloc[latest],
        "atr_14": atr.iloc[latest],
        "obv": obv.iloc[latest],
    }
