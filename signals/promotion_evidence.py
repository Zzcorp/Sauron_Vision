"""Walk-forward evidence as a gate on live promotion.

The promotion ladder (research -> paper -> live_small -> live_full) judged
a rule purely on its recent live/paper record. That is a small, recent,
survivorship-flavoured sample: a rule can look good for three weeks by
luck, get promoted to live, and hand the losses back.

The backtester already drives the same `decide()` the live bot uses and
already does walk-forward train/test splits — it was simply never used as
a gate. Now a rule cannot reach a LIVE stage without out-of-sample
evidence: the held-out window must show positive expectancy, enough
samples, and no collapse versus the training window (which is what
overfitting looks like).

Rules with no registered evaluator cannot be backtested. They are NOT
blocked — that would freeze the whole ladder — but the absence of evidence
is recorded, so "we never checked" is visible rather than implied.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Stages that risk real money and therefore require evidence.
LIVE_STAGES = ("live_small", "live_full")

MIN_TEST_SAMPLES = 20
MIN_TEST_EXPECTANCY = 0.0
# Out-of-sample expectancy may fall this far below in-sample before we call
# it overfitting. 0.5 = the test window must retain half the training edge.
MIN_RETENTION = 0.5


def _evaluator_name(rule_name: str) -> str:
    """Evolved forks (`{parent}_evolved_vN`) reuse the PARENT's evaluator —
    same detector, different constants — with the fork's own parameters.
    Without this resolution every fork hit the exact-name lookup, found
    nothing, and walked into live stages via the fail-open path unbacktested."""
    import re
    return re.sub(r"_evolved_v\d+$", "", rule_name or "")


def evaluate_rule(rule_name: str, *, lookback_days: int = 180) -> dict:
    """Walk-forward result for a rule.

    Returns {available, passed, reason, train, test}. `available` is False
    when the rule has no evaluator to backtest.
    """
    from signals.evolution import _ensure_rules_registered
    from signals.evolution_backtest import (
        backtest_with_params, has_evaluator, resolve_universe,
        walk_forward_window,
    )

    # Registrations are per-process import side effects; the promotion
    # worker has no reason to have imported them. Without this, the gate
    # silently fails open in any process that never ran a proposal task.
    _ensure_rules_registered()

    eval_name = _evaluator_name(rule_name)
    if not has_evaluator(eval_name):
        return {"available": False, "passed": None,
                "reason": "no evaluator registered — cannot backtest",
                "train": None, "test": None}

    try:
        params = _current_params(rule_name)
        train_start, train_end, test_start, test_end = walk_forward_window(
            lookback_days=lookback_days)
        # One universe for BOTH halves, resolved at the train window's
        # start: an instrument eligible only by test time would otherwise
        # appear in one half alone, and the retention ratio would compare
        # different instrument sets — able to pass or block a live
        # promotion on composition alone.
        universe = resolve_universe(eval_name, train_start)
        train = backtest_with_params(eval_name, params, train_start,
                                     train_end, universe=universe)
        test = backtest_with_params(eval_name, params, test_start, test_end,
                                    universe=universe)
    except Exception as e:
        logger.warning("[promotion_evidence] %s backtest failed: %s",
                       rule_name, e)
        return {"available": False, "passed": None,
                "reason": f"backtest failed: {e}", "train": None, "test": None}

    passed, reason = _judge(train, test)
    return {"available": True, "passed": passed, "reason": reason,
            "train": train, "test": test}


def _current_params(rule_name: str) -> dict:
    from signals.models_control import RuleControl
    ctrl = RuleControl.objects.filter(rule_name=rule_name).first()
    return (getattr(ctrl, "parameters", None) or {}) if ctrl else {}


def _judge(train: dict, test: dict) -> tuple:
    """Is the out-of-sample window good enough to risk money on?"""
    n = test.get("n") or 0
    if n < MIN_TEST_SAMPLES:
        return False, (f"only {n} out-of-sample trades "
                       f"(need {MIN_TEST_SAMPLES})")

    test_exp = test.get("expectancy")
    if test_exp is None or test_exp <= MIN_TEST_EXPECTANCY:
        return False, (f"out-of-sample expectancy {test_exp} is not positive")

    train_exp = train.get("expectancy")
    if train_exp and train_exp > 0:
        retention = test_exp / train_exp
        if retention < MIN_RETENTION:
            return False, (f"out-of-sample expectancy kept only "
                           f"{retention:.0%} of in-sample "
                           f"({test_exp:.2f}R vs {train_exp:.2f}R) — "
                           f"looks overfitted")
        return True, (f"out-of-sample {test_exp:.2f}R over {n} trades, "
                      f"{retention:.0%} of in-sample")
    return True, f"out-of-sample {test_exp:.2f}R over {n} trades"


def gate_promotion(rule_name: str, target_stage: str) -> tuple:
    """(allowed, reason) — may this rule advance to `target_stage`?

    Only live stages are gated; research -> paper is how a rule earns the
    record that makes a backtest meaningful in the first place.
    """
    if target_stage not in LIVE_STAGES:
        return True, "no evidence required below live"

    result = evaluate_rule(rule_name)
    if result["available"] is False:
        # Absence of evidence is recorded, not treated as evidence.
        logger.info("[promotion_evidence] %s -> %s without backtest evidence: %s",
                    rule_name, target_stage, result["reason"])
        return True, f"no backtest evidence available ({result['reason']})"
    if not result["passed"]:
        return False, f"walk-forward gate: {result['reason']}"
    return True, f"walk-forward gate passed: {result['reason']}"
