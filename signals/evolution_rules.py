"""Parameter schemas + walk-forward evaluators for evolvable rules.

Phase 9 shipped complete machinery — schema registry, mutation proposer,
walk-forward scorer, promotion-ladder forking — and NOTHING ever called
`register_schema` or `register_evaluator`, so the entire evolution layer
was structurally dormant: `propose_for_decaying_rules` skipped every rule
at the `has_schema` check, weekly, forever.

This module is where rules opt in. Importing it populates both
registries; `signals.evolution` imports it lazily before any proposal
work so the worker that proposes is always the worker that registered.

First (and so far only) resident: the golden-cross family. It is the
cleanest possible candidate — every one of its constants is a real
parameter, and its logic re-runs exactly from bars, which makes its
walk-forward evaluator honest rather than a proxy.
"""
from __future__ import annotations

import logging

from signals.evolution import register_schema
from signals.evolution_backtest import register_evaluator, register_universe

logger = logging.getLogger(__name__)

# The timeframe the rule actually trades — the evaluator must test on the
# same bars or the score describes a different strategy.
GC_TIMEFRAME = "4h"

# How many instruments one evaluation may touch. The evaluator runs once
# per candidate mutation; an unbounded universe would turn one proposal
# sweep into thousands of bar queries.
GC_UNIVERSE_CAP = 20

GOLDEN_CROSS_SCHEMA = {
    # Disjoint bounds ON PURPOSE: fast's max sits below slow's min, so no
    # mutation can produce fast >= slow — a cross that can never happen.
    # The rule and evaluator still guard for it (parameters can also come
    # from hand-edited RuleControl rows), but the mutation space itself
    # must not contain structurally dead candidates.
    "fast":       {"type": "int",   "min": 10,   "max": 90,   "default": 50},
    "slow":       {"type": "int",   "min": 120,  "max": 300,  "default": 200},
    "stop_pct":   {"type": "float", "min": 0.02, "max": 0.10, "default": 0.05,
                   "step": 0.005},
    "target_pct": {"type": "float", "min": 0.04, "max": 0.20, "default": 0.10,
                   "step": 0.005},
}


def _gc_universe() -> list[int]:
    """Instrument ids to backtest on: the symbols this rule historically
    fired for, topped up with the watchlist. Capped.

    The explicit order_by matters: Signal's Meta.ordering (-created_at)
    would otherwise ride into the DISTINCT and make it a no-op over
    (instrument_id, created_at) pairs — one hot instrument with several
    recent signals then occupies several of the capped slots, its
    R-multiples double-counted and the watchlist top-up starved."""
    from instruments.models import Instrument
    from signals.models import Signal

    ids: list[int] = list(
        Signal.objects.filter(rule_name__startswith="golden_cross")
        .values_list("instrument_id", flat=True)
        .distinct().order_by("instrument_id")[:GC_UNIVERSE_CAP])
    if len(ids) < GC_UNIVERSE_CAP:
        extra = (Instrument.objects.filter(is_watchlist=True, is_active=True)
                 .exclude(id__in=ids).order_by("id")
                 .values_list("id", flat=True)[:GC_UNIVERSE_CAP - len(ids)])
        ids.extend(extra)
    return ids


# Eligibility for walk-forward scoring is measured at the SCHEMA's maximum
# `slow`, not any one candidate's: a per-candidate warm-up requirement made
# the instrument set a function of the parameter under test — a slow=120
# mutant traded instruments a slow=200 parent never saw, so their delta
# measured instrument mix, not the parameter change.
GC_WARMUP_BARS = GOLDEN_CROSS_SCHEMA["slow"]["max"]


def _gc_universe_at(start) -> list[int]:
    """Universe resolver for walk-forward scoring (see
    `evolution_backtest.register_universe`): the candidate set filtered to
    instruments with full warm-up before `start`. Resolved ONCE per score
    at the full window's start and pinned into the context, so every leg —
    train/test, parent/mutant — runs the identical instrument set even when
    signal scans or watchlist edits land mid-sweep."""
    from market_data.models import PriceData
    return [iid for iid in _gc_universe()
            if PriceData.objects.filter(
                instrument_id=iid, timeframe=GC_TIMEFRAME,
                timestamp__lt=start).count() >= GC_WARMUP_BARS]


def golden_cross_evaluator(params: dict, start, end,
                           universe=None) -> list[float]:
    """Realized R-multiples from running a golden cross with `params` over
    [start, end] — the contract `evolution_backtest` expects. `universe`
    is the pinned instrument set a walk-forward score resolves once; a
    direct call without one self-resolves per invocation.

    Mechanics mirror the live rule exactly: a fast-SMA-over-slow-SMA
    cross-up opens a LONG at that bar's close with stop entry*(1-stop_pct)
    and target entry*(1+target_pct); subsequent bars resolve it — stop
    first when a bar spans both (pessimistic, the standard convention) —
    and a position still open at the window end is marked to the last
    close. R is denominated by the planned risk, matching bot grading.
    """
    import pandas as pd
    from market_data.models import PriceData

    fast = int(params.get("fast", 50))
    slow = int(params.get("slow", 200))
    stop_pct = float(params.get("stop_pct", 0.05))
    target_pct = float(params.get("target_pct", 0.10))
    if fast >= slow or stop_pct <= 0:
        return []

    rs: list[float] = []
    for inst_id in (universe if universe is not None else _gc_universe()):
        # Warm-up counted in BARS, not calendar days: the slow SMA needs
        # `slow` bars BEFORE the window so a cross at the window's first bar
        # is computable. A day-based budget assumed 24/7 markets (6×4h/day),
        # which only crypto delivers — stocks yield ~2 resampled 4h bars per
        # trading day, so their warm-up fell short and the scan silently
        # started deep inside the window, at a depth that depended on each
        # candidate's own `slow`. Fetching the last `slow` bars strictly
        # before `start` makes bar density irrelevant, and an instrument
        # without full warm-up is skipped outright rather than evaluated on
        # a truncated slice nobody asked for.
        warm = list(PriceData.objects.filter(
            instrument_id=inst_id, timeframe=GC_TIMEFRAME,
            timestamp__lt=start)
            .order_by("-timestamp")
            .values_list("timestamp", "high", "low", "close")[:slow])
        if len(warm) < slow:
            continue
        warm.reverse()
        window = list(PriceData.objects.filter(
            instrument_id=inst_id, timeframe=GC_TIMEFRAME,
            timestamp__gte=start, timestamp__lte=end)
            .order_by("timestamp")
            .values_list("timestamp", "high", "low", "close"))
        if len(window) < 2:
            continue
        rows = warm + window
        highs = [float(r[1]) for r in rows]
        lows = [float(r[2]) for r in rows]
        closes = pd.Series([float(r[3]) for r in rows])
        sma_f = closes.rolling(fast).mean()
        sma_s = closes.rolling(slow).mean()

        # Every bar from index len(warm) on is inside [start, end], and both
        # SMAs are fully valid there — the scan covers the whole window.
        i = len(warm)
        n = len(rows)
        while i < n:
            crossed = (sma_f.iloc[i - 1] <= sma_s.iloc[i - 1]
                       and sma_f.iloc[i] > sma_s.iloc[i])
            if not crossed:
                i += 1
                continue
            entry = closes.iloc[i]
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            risk = entry - stop
            r = None
            j = i + 1
            while j < n:
                if lows[j] <= stop:
                    r = -1.0
                    break
                if highs[j] >= target:
                    r = target_pct / stop_pct
                    break
                j += 1
            if r is None:
                # Window ended with the position open — honest mark.
                r = (closes.iloc[n - 1] - entry) / risk
            rs.append(float(r))
            # One position at a time per instrument, like the live bot.
            i = (j + 1) if j < n else n
    return rs


def register() -> None:
    """Fill any registry gaps. Callable any number of times:
    `_ensure_rules_registered` invokes THIS, not just the import — import
    side effects fire once per process, so a registry cleared afterwards
    (test isolation does exactly that) would otherwise leave the evolution
    layer dormant again with no way back. Gaps only, never overwrite: an
    entry that is already present was put there on purpose — by this
    function earlier, or by someone deliberately overriding it."""
    from signals.evolution import has_schema
    from signals.evolution_backtest import EVALUATOR_REGISTRY, UNIVERSE_REGISTRY
    if not has_schema("golden_cross"):
        register_schema("golden_cross", GOLDEN_CROSS_SCHEMA)
    if "golden_cross" not in EVALUATOR_REGISTRY:
        register_evaluator("golden_cross", golden_cross_evaluator)
    if "golden_cross" not in UNIVERSE_REGISTRY:
        register_universe("golden_cross", _gc_universe_at)


register()
