"""Phase 9.5 — real backtest scorer for strategy evolution.

Replaces the heuristic placeholder with walk-forward validation:

    1. The lookback window is split into TRAIN (first 70%) and TEST (last 30%).
    2. The mutant's parameters are evaluated on BOTH windows.
    3. The parent's parameters are evaluated on BOTH windows (for relative comparison).
    4. Final score = parent_expectancy + min(train_delta, test_delta).
       The mutant must beat the parent on BOTH halves to score above parent.
       Overfit mutants (good train, bad test) are penalised by the min().

Evaluators
----------

A rule that wants real walk-forward scoring registers an evaluator:

    register_evaluator("my_rule", evaluator_fn)

where `evaluator_fn(params, start_date, end_date) -> list[float]` returns the
realized R-multiples produced by running the rule with the given params over
the given window. The evaluator owns its own data fetch — the scorer just
delegates window boundaries.

If no evaluator is registered for a rule, the scorer falls back to the
heuristic from `signals.evolution`. Same opt-in pattern as the schema registry.

Public API
----------

    register_evaluator(rule_name, fn)
    has_evaluator(rule_name) -> bool
    walk_forward_window(lookback_days=180, train_frac=0.7) -> (train_start, train_end, test_start, test_end)
    backtest_with_params(rule_name, params, start, end) -> dict
    score_mutant_walkforward(rule_name, mutant_params, parent_params,
                             lookback_days=180) -> dict
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import Callable, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_TRAIN_FRAC = 0.7

# Minimum trades each side of the split needs to count as a real test.
MIN_TRADES_PER_SPLIT = 5

# Penalty applied when one of the splits has insufficient data — pushes
# the mutant's score down so undertested mutants don't beat the parent.
INSUFFICIENT_DATA_PENALTY = -1.0  # in R-units


# ── Evaluator registry ──────────────────────────────────────────────────────

EvaluatorFn = Callable[[dict, datetime, datetime], list[float]]
EVALUATOR_REGISTRY: dict[str, EvaluatorFn] = {}


def register_evaluator(rule_name: str, fn: EvaluatorFn) -> None:
    """Register a backtest evaluator for `rule_name`. Idempotent — re-registering overrides."""
    if not callable(fn):
        raise TypeError("evaluator must be callable(params, start, end) -> list[float]")
    EVALUATOR_REGISTRY[rule_name] = fn


def has_evaluator(rule_name: str) -> bool:
    return rule_name in EVALUATOR_REGISTRY


# ── Window split ────────────────────────────────────────────────────────────

def walk_forward_window(lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                        train_frac: float = DEFAULT_TRAIN_FRAC,
                        now=None):
    """Return (train_start, train_end, test_start, test_end) for a walk-forward split.

    train_end == test_start to make the split contiguous. The whole window
    spans `lookback_days` ending at `now`.
    """
    if not (0.0 < train_frac < 1.0):
        raise ValueError("train_frac must be in (0, 1)")
    now = now or timezone.now()
    end = now
    start = now - timedelta(days=lookback_days)
    split_at = start + timedelta(days=int(lookback_days * train_frac))
    return start, split_at, split_at, end


# ── Backtest invocation ─────────────────────────────────────────────────────

def backtest_with_params(rule_name: str, params: dict,
                          start: datetime, end: datetime) -> dict:
    """Invoke the registered evaluator and return summary stats.

    Returns dict: {n, expectancy, hit_rate, std, realized_r_list}.
    Raises LookupError if no evaluator is registered.
    """
    if not has_evaluator(rule_name):
        raise LookupError(f"No evaluator registered for '{rule_name}'.")

    fn = EVALUATOR_REGISTRY[rule_name]
    try:
        rs = list(fn(params, start, end))
    except Exception as e:
        logger.warning("[evolution_backtest] evaluator(%s) raised: %s", rule_name, e)
        rs = []

    rs = [float(r) for r in rs]
    n = len(rs)
    if n == 0:
        return {"n": 0, "expectancy": None, "hit_rate": None, "std": None,
                "realized_r_list": []}
    mean = statistics.fmean(rs)
    std = statistics.pstdev(rs) if n >= 2 else 0.0
    hits = sum(1 for r in rs if r > 0)
    return {
        "n": n,
        "expectancy": float(round(mean, 4)),
        "hit_rate": round(hits / n, 4),
        "std": float(round(std, 4)),
        "realized_r_list": rs,
    }


# ── Walk-forward scoring ────────────────────────────────────────────────────

def score_mutant_walkforward(rule_name: str, mutant_params: dict,
                              parent_params: dict,
                              *, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                              now=None) -> dict:
    """Score a mutant via walk-forward backtesting against the parent.

    Returns a dict with:
        score                — composite, used as the proposed_score
        method               — always "walk_forward"
        train_mutant         — backtest summary on train window with mutant_params
        test_mutant          — backtest summary on test window with mutant_params
        train_parent         — backtest summary on train window with parent_params
        test_parent          — backtest summary on test window with parent_params
        train_delta          — mutant_train.expectancy - parent_train.expectancy
        test_delta           — mutant_test.expectancy  - parent_test.expectancy
        worst_delta          — min(train_delta, test_delta)
        sufficient_data      — True iff both splits have >= MIN_TRADES_PER_SPLIT
        notes                — short string, helpful in the UI
    """
    if not has_evaluator(rule_name):
        raise LookupError(f"No evaluator registered for '{rule_name}'.")

    tr_s, tr_e, te_s, te_e = walk_forward_window(lookback_days, now=now)

    train_mutant = backtest_with_params(rule_name, mutant_params, tr_s, tr_e)
    test_mutant = backtest_with_params(rule_name, mutant_params, te_s, te_e)
    train_parent = backtest_with_params(rule_name, parent_params, tr_s, tr_e)
    test_parent = backtest_with_params(rule_name, parent_params, te_s, te_e)

    # Insufficient data on either side → mutant is heavily penalised.
    sufficient = (
        train_mutant["n"] >= MIN_TRADES_PER_SPLIT
        and test_mutant["n"] >= MIN_TRADES_PER_SPLIT
        and train_parent["n"] >= MIN_TRADES_PER_SPLIT
        and test_parent["n"] >= MIN_TRADES_PER_SPLIT
    )
    if not sufficient:
        parent_mean = (
            (train_parent["expectancy"] or 0) + (test_parent["expectancy"] or 0)
        ) / 2.0
        return {
            "score": round(parent_mean + INSUFFICIENT_DATA_PENALTY, 4),
            "method": "walk_forward",
            "train_mutant": train_mutant, "test_mutant": test_mutant,
            "train_parent": train_parent, "test_parent": test_parent,
            "train_delta": None, "test_delta": None, "worst_delta": None,
            "sufficient_data": False,
            "notes": "Insufficient data in one or both splits — mutant penalised.",
        }

    train_delta = (train_mutant["expectancy"] or 0) - (train_parent["expectancy"] or 0)
    test_delta = (test_mutant["expectancy"] or 0) - (test_parent["expectancy"] or 0)
    worst = min(train_delta, test_delta)
    parent_combined = ((train_parent["expectancy"] or 0) + (test_parent["expectancy"] or 0)) / 2.0
    score = parent_combined + worst

    notes = (
        f"train Δ={train_delta:+.2f}R · test Δ={test_delta:+.2f}R · "
        f"worst={worst:+.2f}R"
    )
    if train_delta > 0 and test_delta < 0:
        notes += " · OVERFIT (train good, test bad)"
    elif train_delta > 0 and test_delta > 0:
        notes += " · ROBUST (both halves improve)"

    return {
        "score": float(round(score, 4)),
        "method": "walk_forward",
        "train_mutant": train_mutant, "test_mutant": test_mutant,
        "train_parent": train_parent, "test_parent": test_parent,
        "train_delta": round(train_delta, 4),
        "test_delta": round(test_delta, 4),
        "worst_delta": round(worst, 4),
        "sufficient_data": True,
        "notes": notes,
    }
