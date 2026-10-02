"""What the bot would have done with every signal — bar by bar, with costs.

The live engine's own numbers, imported rather than copied, so a change to
the bot is a change to its backtest:

  levels    ATR(14) x DEFAULT_ATR_STOP_MULT for the stop and
            x DEFAULT_ATR_TARGET_MULT for the target (risk_levels), the stop
            fraction clamped to the class's stop_band with the target kept
            at the same reward:risk
  costs     DEFAULT_COST_BPS of the class as the round trip, in R: a
            trade's net R is its gross move less cost x entry / risk
  care      position_care's break-even (BREAKEVEN_AT_R -> lock
            BREAKEVEN_LOCK_R) and trail (TRAIL_AT_R, TRAIL_GAP_R, wide past
            TRAIL_WIDE_FROM_R), and its no-progress clock (NO_PROGRESS_HOURS
            of the class, best under BREAKEVEN_AT_R, now under
            NO_PROGRESS_MAX_R)

and the backtester's own discipline:

  entry     the OPEN of the bar after the signal — never the signal bar's
            close, which no order could have filled at
  gaps      a bar opening beyond the stop fills at its open (worse than the
            stop); one opening beyond the target fills at its open
  ties      a bar touching both stop and target is a stop (the safe side)
  care      a lock moves at a bar's close and binds from the next bar: the
            bar that made the new high is not assumed to have done so
            before it touched the old stop
  one at a time per rule and symbol; a position still open at the end of
            the data is reported, not counted
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtester.proving.data import BAR_HOURS
from backtester.proving.families import LONG, adx, atr

#: A trade's regime at entry: ADX at or over this is a trend.
TREND_ADX = 25.0
#: ATR% over this multiple of its trailing median is a high-volatility tape.
HIGH_VOL = 1.25
VOL_LOOKBACK = 250


def _engine_constants(asset_class):
    from bot_program.asset_engine.risk_levels import (
        DEFAULT_ATR_STOP_MULT, DEFAULT_ATR_TARGET_MULT, DEFAULT_COST_BPS,
        stop_band)
    from bot_program.position_care import (
        BREAKEVEN_AT_R, BREAKEVEN_LOCK_R, NO_PROGRESS_DEFAULT_HOURS,
        NO_PROGRESS_HOURS, NO_PROGRESS_MAX_R, TRAIL_AT_R, TRAIL_GAP_R,
        TRAIL_GAP_WIDE_R, TRAIL_WIDE_FROM_R)
    return {
        "stop_mult": DEFAULT_ATR_STOP_MULT,
        "target_mult": DEFAULT_ATR_TARGET_MULT,
        "cost": DEFAULT_COST_BPS.get(asset_class, 8.0) / 10000.0,
        "band": stop_band(asset_class),
        "be_at": BREAKEVEN_AT_R, "be_lock": BREAKEVEN_LOCK_R,
        "trail_at": TRAIL_AT_R, "trail_gap": TRAIL_GAP_R,
        "trail_wide_from": TRAIL_WIDE_FROM_R,
        "trail_gap_wide": TRAIL_GAP_WIDE_R,
        "no_progress_h": NO_PROGRESS_HOURS.get(asset_class,
                                               NO_PROGRESS_DEFAULT_HOURS),
        "no_progress_max": NO_PROGRESS_MAX_R,
    }


def regimes(df: pd.DataFrame) -> list:
    """The regime label of each bar: 'trend' or 'range', '+hi_vol' when ATR%
    runs over HIGH_VOL x its trailing median."""
    a = adx(df).to_numpy()
    atr_pct = (atr(df) / df["close"]).to_numpy()
    med = pd.Series(atr_pct).rolling(VOL_LOOKBACK, min_periods=50).median() \
        .to_numpy()
    out = []
    for i in range(len(df)):
        lab = "trend" if np.isfinite(a[i]) and a[i] >= TREND_ADX else "range"
        if np.isfinite(med[i]) and med[i] > 0 \
                and atr_pct[i] > HIGH_VOL * med[i]:
            lab += "+hi_vol"
        out.append(lab)
    return out


def simulate(df: pd.DataFrame, fires, direction: str, *, asset_class: str,
             timeframe: str = "4h", care: bool = True,
             cost_mult: float = 1.0, max_hold_bars: int | None = None,
             labels=None, symbol: str = "") -> dict:
    """{trades, open} for one symbol and one signal array.

    Each trade: {symbol, entry_ts, exit_ts, entry, exit, r (net of costs),
    gross_r, cost_r, mfe, reason, bars, regime}."""
    k = _engine_constants(asset_class)
    d = 1.0 if direction == LONG else -1.0
    o, h, l, c = (df[x].to_numpy(dtype=float)
                  for x in ("open", "high", "low", "close"))
    a = atr(df).to_numpy()
    idx = df.index
    n = len(df)
    labels = labels if labels is not None else regimes(df)
    lo, hi = k["band"]
    ratio = k["target_mult"] / k["stop_mult"]
    bar_h = BAR_HOURS.get(timeframe, 4.0)
    cost = k["cost"] * cost_mult
    trades, still_open = [], None
    free_from = 0
    for t in np.flatnonzero(np.asarray(fires, dtype=bool)):
        if t < free_from or t + 1 >= n:
            continue
        at = a[t]
        e_i = t + 1
        entry = o[e_i]
        if not (np.isfinite(at) and at > 0 and entry > 0):
            continue
        dist = at * k["stop_mult"]
        frac = min(max(dist / entry, lo), hi)
        risk = frac * entry
        stop = entry - d * risk
        target = entry + d * ratio * risk
        soft, soft_why = stop, "stop"
        mfe = 0.0
        exit_px = exit_j = None
        reason = ""
        for j in range(e_i, n):
            if j > e_i:
                if d * (o[j] - soft) <= 0:
                    exit_px, exit_j, reason = o[j], j, f"gap {soft_why}"
                    break
                if d * (o[j] - target) >= 0:
                    exit_px, exit_j, reason = o[j], j, "gap target"
                    break
            adverse = l[j] if d > 0 else h[j]
            favour = h[j] if d > 0 else l[j]
            if d * (adverse - soft) <= 0:
                exit_px, exit_j, reason = soft, j, soft_why
                break
            if d * (favour - target) >= 0:
                exit_px, exit_j, reason = target, j, "target"
                break
            mfe = max(mfe, d * (favour - entry) / risk)
            held = j - e_i + 1
            if care:
                r_now = d * (c[j] - entry) / risk
                if held * bar_h >= k["no_progress_h"] \
                        and mfe < k["be_at"] and r_now < k["no_progress_max"]:
                    exit_px, exit_j, reason = c[j], j, "no progress"
                    break
                cands = []
                if mfe >= k["be_at"]:
                    cands.append((entry + d * k["be_lock"] * risk,
                                  "breakeven"))
                if mfe >= k["trail_at"]:
                    gap = (k["trail_gap_wide"] if mfe >= k["trail_wide_from"]
                           else k["trail_gap"])
                    cands.append((entry + d * (mfe - gap) * risk, "trail"))
                for lvl, why in cands:
                    if d * (lvl - soft) > 0:
                        soft, soft_why = lvl, why
            if max_hold_bars and held >= max_hold_bars:
                exit_px, exit_j, reason = c[j], j, "max hold"
                break
        if exit_px is None:
            still_open = {"symbol": symbol, "entry_ts": idx[e_i],
                          "entry": entry,
                          "r_now": d * (c[-1] - entry) / risk}
            break
        gross = d * (exit_px - entry) / risk
        cost_r = cost * entry / risk
        trades.append({
            "symbol": symbol, "entry_ts": idx[e_i], "exit_ts": idx[exit_j],
            "entry": float(entry), "exit": float(exit_px),
            "r": float(gross - cost_r), "gross_r": float(gross),
            "cost_r": float(cost_r), "mfe": float(mfe), "reason": reason,
            "bars": int(exit_j - e_i + 1), "regime": labels[t],
        })
        free_from = exit_j + 1
    return {"trades": trades, "open": still_open}
