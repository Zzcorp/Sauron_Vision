"""Load OHLCV from PriceData into a pandas DataFrame for SMC detectors."""
import pandas as pd


def load_ohlcv(symbol, timeframe="4h", bars=500):
    """Return a DataFrame indexed by timestamp with open/high/low/close/volume.

    Returns None if the instrument or data is missing. Tolerant to schema
    differences in PriceData/Instrument across the project's history.
    """
    try:
        from market_data.models import PriceData
        from instruments.models import Instrument
    except Exception:
        return None

    instrument = None
    for field in ("symbol", "ticker", "code"):
        try:
            instrument = Instrument.objects.get(**{field: symbol})
            break
        except Exception:
            continue
    if instrument is None:
        return None

    qs = PriceData.objects.filter(instrument=instrument)
    # timeframe column might be called timeframe, interval, or tf
    for field in ("timeframe", "interval", "tf"):
        if field in [f.name for f in PriceData._meta.get_fields()]:
            qs = qs.filter(**{field: timeframe})
            break

    rows = list(qs.order_by("-timestamp")[:bars])
    if not rows:
        return None
    rows.reverse()

    df = pd.DataFrame([{
        "timestamp": r.timestamp,
        "open": float(getattr(r, "open", 0) or 0),
        "high": float(getattr(r, "high", 0) or 0),
        "low": float(getattr(r, "low", 0) or 0),
        "close": float(getattr(r, "close", 0) or 0),
        "volume": float(getattr(r, "volume", 0) or 0),
    } for r in rows])
    df.set_index("timestamp", inplace=True)
    return df


def synthetic_ohlcv(bars=300, seed=42, start_price=50000.0):
    """Generate synthetic OHLCV for testing detectors without DB access."""
    import numpy as np
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.01, bars).cumsum()
    closes = start_price * (1 + rets / 10)
    highs = closes * (1 + np.abs(rng.normal(0, 0.005, bars)))
    lows = closes * (1 - np.abs(rng.normal(0, 0.005, bars)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    vols = rng.uniform(100, 1000, bars)
    idx = pd.date_range("2024-01-01", periods=bars, freq="4h")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols,
    }, index=idx)
