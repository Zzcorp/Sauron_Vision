"""THE SETUP MEMORY (2026-10-03): what followed, the last times this fired.

The operator: "Sauron, like every good trader, should truly understand the
chart, its history... so that he can predict more". The honest version of
that is a conditional expectancy: the last N times this rule fired on
this asset class, in the kind of tape the market is in now, what happened?
Win rate, average R, the best R seen, how often the target was reached,
how long it took. Not an opinion — the proving ground's own simulated
trades (ProvingTrade, kept with each saved verdict), under the engine's
levels, costs and care.

`memory_for(rule_name, symbol, asset_class)` answers for a live rule name
(the families that ARE the live rules, backtester.proving.families) and
says "no memory" for anything else — never a number for a rule nobody
replayed. The regime is read off the symbol's own latest bars
(simulate.regimes); with fewer than MIN_IN_REGIME analogs in that regime
the memory falls back to every regime and says so.
"""
from __future__ import annotations

import logging

from backtester.proving.families import FAMILIES

logger = logging.getLogger(__name__)

#: How many of the most recent analogs the memory quotes.
ANALOGS_N = 60
#: Fewer than this in the current regime: quote every regime instead.
MIN_IN_REGIME = 20
#: Fewer than this at all: the memory says it is thin.
MIN_ANALOGS = 10
#: Bars the regime read needs (ADX, ATR median over VOL_LOOKBACK).
REGIME_BARS = 400


def rule_case(rule_name: str):
    """(family, direction) the live rule is, or None."""
    for fam in FAMILIES.values():
        for direction, live in fam.live_rules.items():
            if live == rule_name:
                return fam, direction
    return None


def regime_now(symbol: str, timeframe: str = "4h"):
    """The regime label of the symbol's newest bar, or None."""
    try:
        from backtester.proving.data import load_history
        from backtester.proving.simulate import regimes
        df = load_history(symbol, timeframe).tail(REGIME_BARS)
        if len(df) < 60:
            return None
        return regimes(df)[-1]
    except Exception as e:  # noqa: BLE001 — a memory without a regime
        logger.debug("[memory] no regime for %s: %s", symbol, e)
        return None


def _summary(rows) -> dict:
    from backtester.proving.judge import stats
    rs = [r.r for r in rows]
    s = stats(rs)
    n = s["n"]
    return {
        "n": n,
        "win_rate": s["win_rate"],
        "avg_r": s["expectancy"],
        "best_r": (sum(r.mfe for r in rows) / n) if n else None,
        "target_pct": (sum(1 for r in rows if r.reason in ("target",
                                                           "gap target"))
                       / n) if n else None,
        "stop_pct": (sum(1 for r in rows if r.reason in ("stop", "gap stop"))
                     / n) if n else None,
        "avg_bars": (sum(r.bars for r in rows) / n) if n else None,
    }


def analogs(family_key: str, direction: str, asset_class: str, *,
            regime=None, n: int = ANALOGS_N, timeframe: str = "4h") -> dict:
    """The newest verdict's trades for this case, the last `n` in `regime`
    (or all regimes when None), summarized."""
    from backtester.models_proving import ProvingTrade, ProvingVerdict
    verdict = (ProvingVerdict.objects
               .filter(family=family_key, direction=direction,
                       asset_class=asset_class, timeframe=timeframe,
                       policy="care", generated=False, filter="none")
               .order_by("-created_at").first())
    out = {"verdict": None, "regime": regime, "fell_back": False}
    if verdict is None:
        out.update(_summary([]))
        return out
    qs = ProvingTrade.objects.filter(verdict=verdict).order_by("-entry_ts")
    rows = list(qs.filter(regime=regime)[:n]) if regime else []
    if regime and len(rows) < MIN_IN_REGIME:
        rows = list(qs[:n])
        out["fell_back"] = bool(regime)
    elif not regime:
        rows = list(qs[:n])
    out["verdict"] = verdict
    out.update(_summary(rows))
    return out


def memory_for(rule_name: str, symbol: str, asset_class: str, *,
               timeframe: str = "4h") -> dict:
    """{ok, words, ...} — the memory a ticket or a debate can quote."""
    case = rule_case(rule_name or "")
    if case is None:
        return {"ok": False, "reason": f"no replay of {rule_name or '—'}: "
                                       f"the proving ground has no family "
                                       f"for it", "words": ""}
    fam, direction = case
    regime = regime_now(symbol, timeframe)
    mem = analogs(fam.key, direction, asset_class, regime=regime,
                  timeframe=timeframe)
    if mem["verdict"] is None:
        return {"ok": False, "regime": regime, "words": "",
                "reason": (f"no saved verdict for {fam.key} {direction} on "
                           f"{asset_class} — run `manage.py prove rules "
                           f"--save`")}
    n = mem["n"]
    v = mem["verdict"]
    thin = n < MIN_ANALOGS
    tape = (f"in a {regime.replace('+hi_vol', ', high-volatility')} tape"
            if regime and not mem["fell_back"] else "across every tape")
    if n:
        words = (f"The last {n} times {rule_name} fired on {asset_class} "
                 f"{tape}: {mem['win_rate'] * 100:.0f}% won, "
                 f"{mem['avg_r']:+.2f}R a trade, best {mem['best_r']:+.2f}R "
                 f"on average, target reached {mem['target_pct'] * 100:.0f}% "
                 f"of the time, about {mem['avg_bars']:.0f} bars held"
                 + (f" (fewer than {MIN_IN_REGIME} in the current {regime} "
                    f"tape, so every tape is counted)" if mem["fell_back"]
                    else "")
                 + (" — a thin sample" if thin else "")
                 + f". Verdict {v.verdict}: {v.why}")
    else:
        words = (f"No analog of {rule_name} on {asset_class} in the saved "
                 f"run {v.run_id}")
    return {"ok": bool(n), "thin": thin, "regime": regime,
            "fell_back": mem["fell_back"], "n": n,
            "win_rate": mem["win_rate"], "avg_r": mem["avg_r"],
            "best_r": mem["best_r"], "target_pct": mem["target_pct"],
            "stop_pct": mem["stop_pct"], "avg_bars": mem["avg_bars"],
            "verdict": v.verdict, "run_id": v.run_id,
            "family": fam.key, "direction": direction, "words": words,
            "reason": ""}
