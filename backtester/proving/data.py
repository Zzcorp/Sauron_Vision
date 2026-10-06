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
               two that the series comes back from. A bar whose close is
               back on the level but whose open is not is a spike's return
               bar: dropped (a fill at that open is no market's), and the
               level is read again from its close
  a held move  LEVEL_SHIFT_BARS bars in a row past the jump that agree with
               each other: the series is on a new level, read by its cause
               (the review of 2026-10-06 found that leaving every such
               symbol out removed the real crashes with it — the tail a
               fade or carry rule lives or dies by — and blamed a split
               for each):
                 a split   the move matches a split ratio within SPLIT_TOL
                           (stock and ETF: 2:1, 3:2, 1:2 ...) or a re-based
                           feed (forex, index, commodity: x10, x100 ...):
                           every earlier bar is ADJUSTED by that ratio, as
                           a split-adjusted series is, and said
                 a market  any other move up to MAX_HELD_MOVE either way:
                           the bars are kept and the gap is traded as it
                           really was, counted
                 broken    past MAX_HELD_MOVE with no ratio, or a run that
                           never settles on one level in MAX_RUN_BARS: the
                           symbol is left out of the run, said
  the anchor   the median close of the first bars, not the first bar: one
               bad first print is a spike against the series, not the
               whole series a level shift against it

Only the open and the close are read for the jump: the simulator fills at a
bar's open (entries, gaps), its close (the clock), or at a level it set
itself (stop, target, lock) — a wick only decides whether a level was
touched, so a wick cannot write an absurd R. A hole in the stored bars is
read like any other gap: a move across it that holds is a market move.
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
#: that split (stock, etf), under the split ratios read (2:1 is -50%, a
#: 1:3 reverse split +200%), so a split always reads as a held move and is
#: adjusted.
MAX_BAR_JUMP = {"forex": 0.15, "index": 0.20, "commodity": 0.30,
                "etf": 0.30, "stock": 0.30, "crypto": 0.50}
#: An unknown class: the stock bar.
DEFAULT_MAX_BAR_JUMP = 0.30
#: This many bars in a row past the jump, on one level, is a held move.
LEVEL_SHIFT_BARS = 3
#: A run past the jump that finds no level in this many bars is a broken
#: feed, not a market.
MAX_RUN_BARS = 4 * LEVEL_SHIFT_BARS
#: The new price over the old, for a split a stock or an ETF series may
#: carry unadjusted ("2:1" — two new shares for one — halves the price).
#: Not 3:2 nor 1:2: rare as splits, and a -33% earnings gap or a +100%
#: takeover bid that holds is a market a rule must be judged on.
SPLIT_RATIOS = {"2:1": 1 / 2, "3:1": 1 / 3, "4:1": 1 / 4, "5:1": 1 / 5,
                "8:1": 1 / 8, "10:1": 1 / 10, "15:1": 1 / 15,
                "20:1": 1 / 20, "1:3": 3.0, "1:4": 4.0, "1:5": 5.0,
                "1:8": 8.0, "1:10": 10.0, "1:15": 15.0, "1:20": 20.0,
                "1:25": 25.0, "1:30": 30.0, "1:50": 50.0}
#: A feed re-based by a power of ten (a pair quoted per 100, a contract in
#: cents): forex, index and commodity series.
REBASE_RATIOS = {"x10": 10.0, "x100": 100.0, "x1000": 1000.0,
                 "/10": 0.1, "/100": 0.01, "/1000": 0.001}
#: How close the held move must sit to a ratio to be read as one. Tight on
#: purpose: a -35% earnings gap is 2.5% off a 3:2 split and stays a market.
SPLIT_TOL = 0.02
#: A held move past this ratio either way (-75%, +300%) that matches no
#: ratio is past any market move a bar makes: its bars stay dropped, and
#: if the series has not come back in MAX_RUN_BARS it is left out.
MAX_HELD_MOVE = 4.0


def ratios_for(asset_class) -> dict:
    """{name: new over old} — the moves of `asset_class` read as a split or
    a re-based feed. Crypto has none: a -90% bar there is a collapse."""
    cls = str(asset_class or "").lower()
    if cls in ("stock", "etf"):
        return dict(SPLIT_RATIOS)
    if cls in ("forex", "index", "commodity"):
        return dict(REBASE_RATIOS)
    if cls == "crypto":
        return {}
    return {**SPLIT_RATIOS, **REBASE_RATIOS}


def ratio_name(ratio: float, ratios: dict) -> str:
    """The ratio `ratio` is within SPLIT_TOL of, or ""."""
    return next((k for k, v in ratios.items()
                 if abs(ratio / v - 1.0) <= SPLIT_TOL), "")


def max_jump(asset_class) -> float:
    """The bar-to-bar jump past which a bar of `asset_class` is not read."""
    return float(MAX_BAR_JUMP.get(str(asset_class or "").lower(),
                                  DEFAULT_MAX_BAR_JUMP))


def sanitize(df: pd.DataFrame, asset_class=None) -> tuple:
    """(clean df, check) — THE BAR SANITY (module docstring).

    check: {bad, spikes, dropped, broken, adjusted, held}: the bars dropped
    as bad and as spikes, their sum; "" or the sentence that says where the
    series broke (the caller leaves the symbol out of the run); the splits
    and re-based feeds adjusted, in words; and the held moves past the jump
    kept as a market. A clean series comes back unchanged — the same
    object."""
    check = {"bad": 0, "spikes": 0, "dropped": 0, "broken": "",
             "adjusted": [], "held": 0}
    if df is None or df.empty:
        return df, check
    px = df[["open", "high", "low", "close"]].to_numpy(dtype=float,
                                                        copy=True)
    with np.errstate(invalid="ignore"):
        good = (np.isfinite(px).all(axis=1) & (px > 0).all(axis=1)
                & (px[:, 1] >= px[:, 2]))
    check["bad"] = int((~good).sum())
    bound = max_jump(asset_class)
    ratios = ratios_for(asset_class)
    keep = good.copy()
    goods = np.flatnonzero(good)
    if not len(goods):
        check["dropped"] = check["bad"]
        return df[keep], check
    # THE ANCHOR: the median of the first closes, so one bad first print is
    # a spike, not a level the whole series leaves.
    last = float(np.median(px[goods[:2 * LEVEL_SHIFT_BARS - 1], 3]))
    run, adjusted, extreme = [], False, None
    for i in goods:
        o, c = px[i, 0], px[i, 3]
        if abs(c / last - 1.0) <= bound:
            if abs(o / last - 1.0) > bound:
                keep[i] = False      # a spike's return bar: its open is off
            run = []
            last = c
            continue
        keep[i] = False
        run.append(i)
        tail = run[-LEVEL_SHIFT_BARS:]
        ref = px[tail[0], 3]
        if len(tail) == LEVEL_SHIFT_BARS and all(
                abs(px[j, 3] / ref - 1.0) <= bound for j in tail):
            # ONE LEVEL, HELD: read by its cause.
            first = tail[0]
            fo = px[first, 0]
            moved = (fo if abs(fo / last - 1.0) > bound
                     else px[first, 3]) / last
            name = ratio_name(moved, ratios)
            if name or 1.0 / MAX_HELD_MOVE <= moved <= MAX_HELD_MOVE:
                if name:
                    px[:first] *= ratios[name]
                    adjusted = True
                    kind = "split" if name in SPLIT_RATIOS else "re-based feed"
                    check["adjusted"].append(
                        f"a {name} {kind} at {df.index[first]:%Y-%m-%d %H:%M}")
                else:
                    check["held"] += 1
                for j in tail:
                    keep[j] = True
                last = px[tail[-1], 3]
                run = []
                continue
            extreme = (first, moved)
        if len(run) >= MAX_RUN_BARS:
            if extreme is not None and extreme[0] >= run[0]:
                check["broken"] = (
                    f"broken from {df.index[run[0]]:%Y-%m-%d %H:%M}: the "
                    f"close moved {extreme[1] - 1.0:+.0%} from the last good "
                    f"close and held {len(run)} bars — past any market move "
                    f"and no split ratio; left out of this run")
            else:
                check["broken"] = (
                    f"broken from {df.index[run[0]]:%Y-%m-%d %H:%M}: "
                    f"{len(run)} bars in a row past the {bound:.0%} bar "
                    f"that never settle on one level — an erratic feed; "
                    f"left out of this run")
            break
    check["spikes"] = int(good.sum() - keep.sum())
    check["dropped"] = check["bad"] + check["spikes"]
    if not check["dropped"] and not adjusted:
        return df, check
    if adjusted:
        df = df.copy()
        df[["open", "high", "low", "close"]] = px
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
