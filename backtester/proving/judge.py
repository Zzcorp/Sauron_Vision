"""The verdict on a pool of simulated trades — built to say no.

PROVEN needs every one of these at once:

  enough      MIN_TRADES in all, MIN_OOS_TRADES in the holdout
  holdout     the last HOLDOUT_FRAC of the data's time span is never used
              to choose anything; its expectancy must be > 0
  bound       a bootstrap lower bound on the expectancy (all trades) above
              zero at ALPHA, Sidak-corrected for the number of candidates
              tried to find this one — twenty variants searched means the
              best of twenty must clear a much harder bar
  costs       the expectancy at DOUBLE the round trip still > 0
  stable      at least MIN_POSITIVE_FOLDS of FOLDS equal time folds positive

Anything positive that misses one of them is PROMISING (worth watching on
paper, never on money); a non-positive expectancy or holdout is FAILED;
too few trades or too little data is INSUFFICIENT — said as such, never
read as a pass or a fail.

THE LAST GUARD (2026-10-06), ONE-SIDED so it can never flatter a rule. A
WIN past +PROVING_MAX_TRADE_R is not judged — excluded from every number
and counted by symbol: the engine's target is 2R (3R at most among the
exit policies), so such a win is a fill far beyond its own level, a
broken bar (the ETF class printed +21.829R a trade and a worst run of
+45733R on 2026-10-06); the one honest way past it, the trail-only policy
riding a long trend, is printed in the count. A LOSS past
-PROVING_MAX_TRADE_R is KEPT, capped at it: the simulator fills a gap
through the stop at the open on purpose, and a gap the class's jump bar
accepts can be worth more than twenty quiet stops (a 0.09% forex stop
through a 2.5% Monday gap is -28R). Dropping it, as the first version
did, cut the very tail a carry or fade rule fails on and could print a
false PROVEN (the review of 2026-10-06). When the trades past the bound,
either way, are more than MAX_EXCLUDED_SHARE of the run, the history
itself is broken and the verdict is INSUFFICIENT, with the words naming
the symbols and the count — never PROVEN, PROMISING or FAILED on numbers
that are not a market's.
"""
from __future__ import annotations

import numpy as np

HOLDOUT_FRAC = 0.30
FOLDS = 5
MIN_POSITIVE_FOLDS = 3
MIN_TRADES = 50
MIN_OOS_TRADES = 20
ALPHA = 0.05
BOOTSTRAPS = 2000
#: Fixed so the same trades always get the same verdict.
SEED = 20261002
#: THE LAST GUARD: a win past this many R is excluded, a loss capped at it.
PROVING_MAX_TRADE_R = 20.0
#: Past this share of a run's trades past the bound, the verdict is
#: INSUFFICIENT.
MAX_EXCLUDED_SHARE = 0.02

PROVEN, PROMISING, FAILED, INSUFFICIENT = (
    "proven", "promising", "failed", "insufficient")


def sane_trades(trades) -> tuple:
    """(kept, past) — THE LAST GUARD (module docstring). `kept` is every
    trade the numbers read: the ones within PROVING_MAX_TRADE_R, and each
    loss past it as a copy capped at -PROVING_MAX_TRADE_R (`capped` True,
    the simulated R as `r_raw`). `past` is every trade past the bound
    either way, as simulated, for the count and the share; a win in it is
    in no number."""
    kept, past = [], []
    for t in trades:
        r = float(t["r"])
        if r > PROVING_MAX_TRADE_R:
            past.append(t)
        elif r < -PROVING_MAX_TRADE_R:
            past.append(t)
            cost = float(t.get("cost_r") or 0.0)
            kept.append(dict(t, r=-PROVING_MAX_TRADE_R,
                             gross_r=-PROVING_MAX_TRADE_R + cost,
                             r_raw=r, capped=True))
        else:
            kept.append(t)
    return kept, past


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def by_symbol(trades) -> dict:
    """{symbol: count}, the most first, then by name."""
    counts = {}
    for t in trades:
        sym = str(t.get("symbol") or "?")
        counts[sym] = counts.get(sym, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def named_counts(counts: dict, limit: int = 5) -> str:
    """"XYZ" for one symbol, "XYZ (38), ABC (3)" for several, the rest
    counted past `limit`."""
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(items) == 1:
        return items[0][0]
    words = ", ".join(f"{s} ({n})" for s, n in items[:limit])
    if len(items) > limit:
        words += f" and {len(items) - limit} more"
    return words


def stats(rs) -> dict:
    """n, win rate, average win/loss, payoff, expectancy, total, profit
    factor and the worst peak-to-trough of the cumulative R."""
    rs = np.asarray([float(x) for x in rs], dtype=float)
    n = int(rs.size)
    if not n:
        return {"n": 0, "win_rate": None, "avg_win": None, "avg_loss": None,
                "payoff": None, "expectancy": None, "sum_r": None,
                "profit_factor": None, "max_dd_r": None}
    wins, losses = rs[rs > 0], rs[rs < 0]
    cum = np.cumsum(rs)
    dd = float((np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
                - cum).max())
    avg_win = float(wins.mean()) if wins.size else None
    avg_loss = float(losses.mean()) if losses.size else None
    return {
        "n": n,
        "win_rate": float(wins.size / n),
        "avg_win": avg_win, "avg_loss": avg_loss,
        "payoff": (avg_win / abs(avg_loss)
                   if avg_win is not None and avg_loss else None),
        "expectancy": float(rs.mean()),
        "sum_r": float(rs.sum()),
        "profit_factor": (float(wins.sum() / abs(losses.sum()))
                          if losses.size else None),
        "max_dd_r": dd,
    }


def sidak(alpha: float, k: int) -> float:
    """The per-candidate level that keeps the family-wise error at alpha
    over k candidates."""
    k = max(1, int(k))
    return 1.0 - (1.0 - alpha) ** (1.0 / k)


def bootstrap_lower(rs, alpha: float, *, n=BOOTSTRAPS, seed=SEED):
    """The alpha-quantile of the bootstrapped mean R (one-sided lower
    bound); None under five trades."""
    rs = np.asarray(rs, dtype=float)
    if rs.size < 5:
        return None
    rng = np.random.default_rng(seed)
    means = rng.choice(rs, size=(n, rs.size), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha))


def judge(trades, *, start, end, n_candidates: int = 1,
          data_ok: bool = True, data_reason: str = "") -> dict:
    """The verdict and every number behind it, for trades pooled over the
    data span [start, end] (Timestamps). A win past PROVING_MAX_TRADE_R
    is excluded and a loss past it capped, each counted (`excluded`), THE
    LAST GUARD."""
    raw = sorted(trades, key=lambda t: t["entry_ts"])
    trades, absurd = sane_trades(raw)
    total = len(raw)
    wins = [t for t in absurd if float(t["r"]) > 0]
    losses = [t for t in absurd if float(t["r"]) < 0]
    excluded = {"n": len(absurd), "of": total,
                "share": (len(absurd) / total) if total else 0.0,
                "by_symbol": by_symbol(absurd),
                "wins": len(wins), "wins_by_symbol": by_symbol(wins),
                "capped": len(losses), "capped_by_symbol": by_symbol(losses),
                "max_trade_r": PROVING_MAX_TRADE_R}
    rs = [t["r"] for t in trades]
    split = start + (end - start) * (1.0 - HOLDOUT_FRAC)
    ins = [t["r"] for t in trades if t["entry_ts"] < split]
    oos = [t["r"] for t in trades if t["entry_ts"] >= split]
    stressed = [t["r"] - t["cost_r"] for t in trades]   # double the costs
    fold_len = (end - start) / FOLDS
    folds = []
    for i in range(FOLDS):
        a, b = start + fold_len * i, start + fold_len * (i + 1)
        fr = [t["r"] for t in trades
              if a <= t["entry_ts"] < b or (i == FOLDS - 1
                                            and t["entry_ts"] == end)]
        folds.append(float(np.mean(fr)) if fr else None)
    positive_folds = sum(1 for f in folds if f is not None and f > 0)
    level = sidak(ALPHA, n_candidates)
    lower = bootstrap_lower(rs, level)
    regimes = {}
    for t in trades:
        regimes.setdefault(t["regime"], []).append(t["r"])
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    out = {
        "all": stats(rs), "in_sample": stats(ins), "holdout": stats(oos),
        "stressed": stats(stressed),
        "folds": folds, "positive_folds": positive_folds,
        "lower_bound": lower, "alpha": level, "n_candidates": n_candidates,
        "regimes": {k: stats(v) for k, v in sorted(regimes.items())},
        "exits": reasons,
        "split": split,
        "trades": trades,
        "excluded": excluded,
    }
    e, oe = out["all"]["expectancy"], out["holdout"]["expectancy"]
    if not data_ok:
        verdict, why = INSUFFICIENT, data_reason or "not enough history"
    elif len(rs) < MIN_TRADES or len(oos) < MIN_OOS_TRADES:
        verdict = INSUFFICIENT
        why = (f"{len(rs)} trades ({len(oos)} in the holdout); "
               f"{MIN_TRADES} ({MIN_OOS_TRADES}) needed")
    elif e is None or e <= 0:
        verdict, why = FAILED, f"expectancy {e:+.3f}R"
    elif oe is None or oe <= 0:
        verdict, why = FAILED, (f"positive in sample, {oe:+.3f}R on the "
                                f"holdout it never saw")
    else:
        misses = []
        if lower is None or lower <= 0:
            misses.append(f"lower bound {lower if lower is None else round(lower, 3)}R "
                          f"at {level:.4f} over {n_candidates} candidate(s)")
        if out["stressed"]["expectancy"] <= 0:
            misses.append(f"{out['stressed']['expectancy']:+.3f}R at double "
                          f"costs")
        if positive_folds < MIN_POSITIVE_FOLDS:
            misses.append(f"{positive_folds} of {FOLDS} time folds positive")
        if misses:
            verdict, why = PROMISING, "; ".join(misses)
        else:
            verdict = PROVEN
            why = (f"{e:+.3f}R a trade, {oe:+.3f}R on the holdout, lower "
                   f"bound {lower:+.3f}R, {positive_folds}/{FOLDS} folds")
    if absurd and data_ok:
        what = []
        if wins:
            what.append(_plural(len(wins), "win", "wins") + " excluded")
        if losses:
            what.append(_plural(len(losses), "loss", "losses")
                        + f" capped at -{PROVING_MAX_TRADE_R:.0f}R")
        said = (f"{len(absurd)} of {total} trades past "
                f"{PROVING_MAX_TRADE_R:.0f}R ({excluded['share']:.1%}) on "
                f"{named_counts(excluded['by_symbol'])}: "
                + ", ".join(what))
        if excluded["share"] > MAX_EXCLUDED_SHARE:
            verdict = INSUFFICIENT
            why = (f"{said} — over the {MAX_EXCLUDED_SHARE:.0%} a verdict "
                   f"may lose: the history is broken, not judged")
        else:
            why = f"{why}; {said}"
    out["verdict"], out["why"] = verdict, why
    return out
