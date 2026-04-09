"""Multi-timeframe resampling helpers."""
import pandas as pd


TF_TO_PANDAS = {
    "1m": "1T", "5m": "5T", "15m": "15T", "30m": "30T",
    "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W",
}


def resample_ohlcv(df, target_tf):
    """Resample OHLCV DataFrame to a higher timeframe."""
    rule = TF_TO_PANDAS.get(target_tf)
    if rule is None:
        return df
    return df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
