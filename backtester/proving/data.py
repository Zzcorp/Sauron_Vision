"""History for the proving ground: every stored bar, oldest first, and an
honest answer to "is there enough of it to judge anything?"."""
from __future__ import annotations

import pandas as pd

#: The least history, in calendar days, a verdict may rest on. Yahoo serves
#: two years of hourly bars (the 4h are resampled from them), Binance years.
MIN_SPAN_DAYS = {"1h": 365, "4h": 540, "1d": 1825}
#: And the least bars, whatever the span.
MIN_BARS = {"1h": 2000, "4h": 800, "1d": 750}
#: A spacing this many times the median is a hole in the data.
GAP_FACTOR = 5.0
#: Hours one bar of each timeframe stands for (care's clocks run on them).
BAR_HOURS = {"1h": 1.0, "4h": 4.0, "1d": 24.0}


def load_history(symbol: str, timeframe: str = "4h") -> pd.DataFrame:
    """Every stored bar for `symbol` at `timeframe`, oldest first, as floats
    (open, high, low, close, volume) on a UTC DatetimeIndex. Empty when
    nothing is stored."""
    from market_data.models import PriceData
    rows = list(PriceData.objects
                .filter(instrument__symbol=symbol, timeframe=timeframe)
                .order_by("timestamp")
                .values_list("timestamp", "open", "high", "low", "close",
                             "volume"))
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close",
                                     "volume"])
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close",
                                     "volume"])
    df = df.drop_duplicates("ts").set_index("ts")
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.astype(float)
    # A bar whose high is under its low is a bad row, not a market.
    return df[(df["high"] >= df["low"]) & (df["close"] > 0)]


def sufficiency(df: pd.DataFrame, timeframe: str = "4h") -> dict:
    """{ok, reason, bars, span_days, first, last, gaps} — whether this
    history is long and whole enough to be judged."""
    bars = int(len(df))
    out = {"ok": False, "reason": "", "bars": bars, "span_days": 0.0,
           "first": None, "last": None, "gaps": 0}
    if bars < 2:
        out["reason"] = "no history"
        return out
    first, last = df.index[0], df.index[-1]
    span = (last - first).total_seconds() / 86400.0
    spacing = df.index.to_series().diff().dropna().dt.total_seconds()
    median = float(spacing.median()) if len(spacing) else 0.0
    gaps = int((spacing > GAP_FACTOR * median).sum()) if median > 0 else 0
    out.update(span_days=round(span, 1), first=first, last=last, gaps=gaps)
    need_days = MIN_SPAN_DAYS.get(timeframe, 365)
    need_bars = MIN_BARS.get(timeframe, 750)
    if span < need_days:
        out["reason"] = (f"{span:.0f} days of {timeframe} history, "
                         f"{need_days} needed")
    elif bars < need_bars:
        out["reason"] = f"{bars} {timeframe} bars, {need_bars} needed"
    else:
        out["ok"] = True
    return out
