"""History for the proving ground: every stored bar, oldest first, and an
honest answer to "is there enough of it to judge anything?".

THE BAR SANITY (2026-10-06). `prove rules --save` printed, for the ETF
class alone, +21.829R a trade, a payoff of 43, a regime at +178.836R and a
short mirror whose worst run was +45733R — every other class under 0.5R a
trade. One or more ETF series carried broken bars (an unadjusted split, a
zero or near-zero print, a spike), and a single trade entered or gapped
out on one of them read hundreds of R. A false PROVEN is the dangerous
outcome. `sanitize` reads each series before any simulation:

  bad bars     a non-positive or non-finite open/high/low/close, or a high
               under the low: dropped and counted
  spikes       an open or a close more than MAX_BAR_JUMP (by class) away
               from the last accepted close: dropped and counted — a bar or
               two that the series comes back from
  level shift  LEVEL_SHIFT_BARS such bars in a row: the series has left
               its own level (an unadjusted split, a re-based feed). It is
               broken from the first of them, and the symbol is left out of
               the run with the sentence that says so.

Only the open and the close are read for the jump: the simulator fills at a
bar's open (entries, gaps), its close (the clock), or at a level it set
itself (stop, target, lock) — a wick only decides whether a level was
touched, so a wick cannot write an absurd R.
"""
from __future__ import annotations

import numpy as np
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

#: The farthest a bar's open or close may sit from the last accepted close,
#: as a fraction of it, by class. Not bot_program.mark_sanity's JUMP_PCT:
#: that bar is tick to tick inside fifteen minutes (3% on an ETF), and a 4h
#: bar on IBIT or ARKK passes it in ordinary trade. These sit past the
#: moves a bar of the class makes in ordinary trade and, for the classes
#: that split (stock, etf), under the common split ratios (3:2 is -33%, 2:1
#: is -50%, a 1:2 reverse split +100%). A rarer real move that holds (a
#: -35% earnings gap) reads as a level shift and leaves that symbol out of
#: the run, said — the error on the side that cannot print a false PROVEN.
MAX_BAR_JUMP = {"forex": 0.15, "index": 0.20, "commodity": 0.30,
                "etf": 0.30, "stock": 0.30, "crypto": 0.50}
#: An unknown class: the stock bar.
DEFAULT_MAX_BAR_JUMP = 0.30
#: This many bars in a row past the jump is a new level, not a spike.
LEVEL_SHIFT_BARS = 3


def max_jump(asset_class) -> float:
    """The bar-to-bar jump past which a bar of `asset_class` is not read."""
    return float(MAX_BAR_JUMP.get(str(asset_class or "").lower(),
                                  DEFAULT_MAX_BAR_JUMP))


def sanitize(df: pd.DataFrame, asset_class=None) -> tuple:
    """(clean df, check) — THE BAR SANITY (module docstring).

    check: {bad, spikes, dropped, broken}: the bars dropped as bad and as
    spikes, their sum, and "" or the sentence that says where the series
    broke (an unadjusted split or a re-based feed — the caller leaves the
    symbol out of the run). A clean series comes back unchanged."""
    check = {"bad": 0, "spikes": 0, "dropped": 0, "broken": ""}
    if df is None or df.empty:
        return df, check
    px = df[["open", "high", "low", "close"]].to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        good = (np.isfinite(px).all(axis=1) & (px > 0).all(axis=1)
                & (px[:, 1] >= px[:, 2]))
    check["bad"] = int((~good).sum())
    bound = max_jump(asset_class)
    keep = good.copy()
    last, run = None, []
    for i in np.flatnonzero(good):
        o, c = px[i, 0], px[i, 3]
        if last is None:
            last = c
            continue
        if abs(c / last - 1.0) > bound or abs(o / last - 1.0) > bound:
            keep[i] = False
            run.append(i)
            if len(run) >= LEVEL_SHIFT_BARS:
                first = run[0]
                check["broken"] = (
                    f"broken from {df.index[first]:%Y-%m-%d %H:%M}: the "
                    f"close moved {px[first, 3] / last - 1.0:+.0%} from the "
                    f"last good close and {LEVEL_SHIFT_BARS} bars in a row "
                    f"stayed past the {bound:.0%} bar — an unadjusted split "
                    f"or a re-based feed; left out of this run")
                break
            continue
        run = []
        last = c
    check["spikes"] = int(good.sum() - keep.sum())
    check["dropped"] = check["bad"] + check["spikes"]
    if not check["dropped"]:
        return df, check
    return df[keep], check


def load_history(symbol: str, timeframe: str = "4h", *,
                 raw: bool = False) -> pd.DataFrame:
    """Every stored bar for `symbol` at `timeframe`, oldest first, as floats
    (open, high, low, close, volume) on a UTC DatetimeIndex. Empty when
    nothing is stored. `raw=True` keeps the bad rows, for `sanitize` to
    count."""
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
    if raw:
        return df
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
