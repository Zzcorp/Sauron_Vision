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

PROVEN, PROMISING, FAILED, INSUFFICIENT = (
    "proven", "promising", "failed", "insufficient")


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
    data span [start, end] (Timestamps)."""
    trades = sorted(trades, key=lambda t: t["entry_ts"])
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
    out["verdict"], out["why"] = verdict, why
    return out
