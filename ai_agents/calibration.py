"""Agent calibration — Phase 6.

Closes the loop: every agent prediction is logged with a resolution deadline
and a link to the source object (Signal, RuleAction, etc.). A nightly resolver
fetches ground truth and stamps the prediction. The risk gate consults
`trust_adjustment_for(agent)` before honouring an AI scale, so an agent that's
been wrong a lot has its influence dampened.

Public API:
  log_trade_prediction(agent, signal, predicted_outcome, confidence)
        Log a prediction tied to a Signal — resolves when the signal closes.

  log_decay_prediction(agent, rule_action, predicted_continues, confidence)
        Log a prediction tied to a RuleAction — resolves 30 days later.

  resolve_pending_predictions()
        Nightly: walk every unresolved prediction past its deadline, look up
        ground truth, stamp it. Returns count resolved.

  trust_adjustment_for(agent_name) -> float
        0.5 .. 1.3 multiplier for risk-gate consumption. <1 = damped trust.

  CalibrationTracker.* (legacy API preserved)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Default lookback when computing trust scores.
DEFAULT_LOOKBACK_DAYS = 90

# A rule expectancy delta (recent_after - recent_before) below this means the
# decay-investigation prediction was correct (the rule did continue to decay).
DECAY_CONFIRMATION_THRESHOLD = -0.5  # R-units

# Minimum sample size before trust_adjustment_for moves away from 1.0.
MIN_SAMPLE_FOR_TRUST = 10


# ── Helpers ─────────────────────────────────────────────────────────────────

def _AgentPrediction():
    from ai_agents.models import AgentPrediction
    return AgentPrediction


# ── Logging entry points ────────────────────────────────────────────────────

def log_prediction(agent, prediction_type, predicted_value,
                   instrument_symbol="", confidence=0.5,
                   expected_resolution_at=None,
                   linked_signal=None, linked_rule_action=None):
    """Generic logger — preferred to use the typed helpers below."""
    return _AgentPrediction().objects.create(
        agent=agent,
        prediction_type=prediction_type,
        predicted_value=str(predicted_value),
        instrument_symbol=instrument_symbol,
        confidence=float(confidence),
        expected_resolution_at=expected_resolution_at,
        linked_signal=linked_signal,
        linked_rule_action=linked_rule_action,
    )


def log_trade_prediction(agent: str, signal, *, predicted_outcome="hit_target",
                         confidence: float = 0.5):
    """Predict a Signal's eventual outcome.

    `predicted_outcome` should be one of "hit_target" or "stopped_out".
    Resolves when `Signal.is_active = False`. Confidence = the agent's
    self-reported probability that the trade will hit target.
    """
    return log_prediction(
        agent=agent,
        prediction_type="trade_outcome",
        predicted_value=predicted_outcome,
        instrument_symbol=signal.instrument.symbol if signal.instrument else "",
        confidence=confidence,
        # Trade signals expire by SIGNAL_TTL_DAYS=7 if nothing happens.
        expected_resolution_at=timezone.now() + timedelta(days=8),
        linked_signal=signal,
    )


def log_decay_prediction(agent: str, rule_action, *,
                         predicted_continues: bool = True, confidence: float = 0.6):
    """Predict whether a rule's decay will continue.

    Resolves 30 days after creation by comparing rule expectancy then vs now.
    If the agent recommended pause/reduce, it's predicting decay continues.
    """
    return log_prediction(
        agent=agent,
        prediction_type="decay_continues",
        predicted_value="continues" if predicted_continues else "recovers",
        instrument_symbol="",
        confidence=confidence,
        expected_resolution_at=timezone.now() + timedelta(days=30),
        linked_rule_action=rule_action,
    )


# ── Auto-resolver ───────────────────────────────────────────────────────────

def _resolve_trade_prediction(pred) -> bool:
    """Return True if successfully resolved (and stamped)."""
    sig = pred.linked_signal
    if sig is None or sig.is_active:
        return False
    actual_outcome = sig.outcome or ""
    realized_r = sig.realized_r if sig.realized_r is not None else 0.0

    # was_correct = predicted == actual (binary), reduced from outcome string.
    was_correct = (pred.predicted_value == actual_outcome)
    pred.actual_value = actual_outcome
    pred.was_correct = bool(was_correct)
    pred.score = float(realized_r)
    pred.evaluated_at = timezone.now()
    pred.evaluation_notes = f"signal #{sig.id} closed as {actual_outcome} at R={realized_r}"
    pred.save()
    return True


def _resolve_decay_prediction(pred) -> bool:
    """Resolve a decay prediction by comparing rule expectancy then vs now."""
    from signals.performance import calculate_signal_stats

    action = pred.linked_rule_action
    if action is None:
        return False

    rule_name = action.rule_name
    # Window: 30 days starting from prediction time.
    # Compute current expectancy over the resolution window for this rule.
    from signals.models import Signal
    cutoff_recent = pred.created_at
    qs = Signal.objects.filter(
        rule_name=rule_name, is_active=False,
        expired_at__gte=cutoff_recent,
    ).exclude(outcome="")
    n_recent = qs.count()
    if n_recent < 3:
        # Not enough resolved trades to judge; give it more time.
        # Push expected_resolution_at out by 14d so we'll retry later.
        pred.expected_resolution_at = timezone.now() + timedelta(days=14)
        pred.save(update_fields=["expected_resolution_at"])
        return False

    from django.db.models import Avg
    expectancy = qs.aggregate(avg=Avg("realized_r"))["avg"] or 0.0

    # If predicted "continues" and recent expectancy is below threshold → correct.
    predicted_continues = (pred.predicted_value == "continues")
    actually_continues = expectancy < DECAY_CONFIRMATION_THRESHOLD
    was_correct = (predicted_continues == actually_continues)

    pred.actual_value = f"expectancy_{expectancy:.2f}R"
    pred.was_correct = bool(was_correct)
    pred.score = float(expectancy)  # negative = bad rule, positive = good
    pred.evaluated_at = timezone.now()
    pred.evaluation_notes = (
        f"30d expectancy on rule={rule_name} is {expectancy:+.2f}R (n={n_recent}). "
        f"Predicted continues={predicted_continues}, actually continues={actually_continues}."
    )
    pred.save()
    return True


def resolve_pending_predictions(now=None) -> dict:
    """Resolve every prediction whose deadline has passed and ground truth is available.

    Idempotent: skips already-resolved (was_correct__isnull=False).
    """
    AgentPrediction = _AgentPrediction()
    now = now or timezone.now()
    pending = AgentPrediction.objects.filter(
        was_correct__isnull=True,
        expected_resolution_at__lte=now,
    )
    resolved = 0
    failed = 0
    by_type = {}
    for pred in pending:
        try:
            if pred.prediction_type == "trade_outcome":
                ok = _resolve_trade_prediction(pred)
            elif pred.prediction_type == "decay_continues":
                ok = _resolve_decay_prediction(pred)
            else:
                ok = False  # unknown type — leave for human inspection
            if ok:
                resolved += 1
                by_type[pred.prediction_type] = by_type.get(pred.prediction_type, 0) + 1
            else:
                failed += 1
        except Exception as e:
            logger.warning("calibration: failed to resolve pred #%s: %s", pred.id, e)
            failed += 1

    return {"resolved": resolved, "failed": failed, "by_type": by_type}


# ── Trust-score consumer ────────────────────────────────────────────────────

def brier_score(agent: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> Optional[float]:
    """Mean Brier score (lower = better) for resolved predictions in window.

    For each prediction: bs = (confidence - actual_outcome)^2, where
    actual_outcome is 1 if was_correct else 0. Returns None if no data.
    """
    AgentPrediction = _AgentPrediction()
    cutoff = timezone.now() - timedelta(days=lookback_days)
    qs = AgentPrediction.objects.filter(
        agent=agent, was_correct__isnull=False, evaluated_at__gte=cutoff,
    )
    n = qs.count()
    if n == 0:
        return None
    total = 0.0
    for p in qs:
        actual = 1.0 if p.was_correct else 0.0
        total += (float(p.confidence) - actual) ** 2
    return round(total / n, 4)


def trust_adjustment_for(agent: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> float:
    """Multiplier in [0.5, 1.3] reflecting the agent's historical reliability.

    Default 1.0 when sample size is too small. Brier-score-based:
      - bs ≤ 0.10 → 1.30 (well-calibrated, confident, correct often)
      - bs ≤ 0.20 → 1.15
      - bs ≤ 0.25 → 1.00 (around random; no boost, no damp)
      - bs ≤ 0.35 → 0.80
      - bs >  0.35 → 0.50 (markedly poor — heavily damped)
    """
    AgentPrediction = _AgentPrediction()
    qs = AgentPrediction.objects.filter(
        agent=agent, was_correct__isnull=False,
        evaluated_at__gte=timezone.now() - timedelta(days=lookback_days),
    )
    if qs.count() < MIN_SAMPLE_FOR_TRUST:
        return 1.0

    bs = brier_score(agent, lookback_days)
    if bs is None:
        return 1.0
    if bs <= 0.10:
        return 1.30
    if bs <= 0.20:
        return 1.15
    if bs <= 0.25:
        return 1.00
    if bs <= 0.35:
        return 0.80
    return 0.50


# ── Legacy API (kept for backwards compat with views.agent_calibration_api) ─

class CalibrationTracker:
    """Track and report agent calibration metrics."""

    def get_agent_accuracy(self, agent_name, lookback_days=DEFAULT_LOOKBACK_DAYS):
        AgentPrediction = _AgentPrediction()
        cutoff = timezone.now() - timedelta(days=lookback_days)
        predictions = AgentPrediction.objects.filter(
            agent=agent_name, created_at__gte=cutoff, was_correct__isnull=False,
        )
        total = predictions.count()
        if total == 0:
            return {"agent": agent_name, "total": 0, "note": "no evaluated predictions"}

        correct = predictions.filter(was_correct=True).count()
        accuracy = correct / total

        by_type = {}
        for pt in predictions.values_list("prediction_type", flat=True).distinct():
            tp = predictions.filter(prediction_type=pt)
            t_total = tp.count()
            t_correct = tp.filter(was_correct=True).count()
            by_type[pt] = {
                "total": t_total, "correct": t_correct,
                "accuracy": round(t_correct / t_total, 4) if t_total else 0,
            }

        # Reliability buckets — predicted-confidence vs actual-accuracy.
        calibration = {}
        for bucket in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            bp = predictions.filter(confidence__gte=bucket - 0.05,
                                    confidence__lt=bucket + 0.05)
            bn = bp.count()
            if bn:
                calibration[str(bucket)] = {
                    "predicted_confidence": bucket,
                    "actual_accuracy": round(bp.filter(was_correct=True).count() / bn, 4),
                    "n": bn,
                }

        return {
            "agent": agent_name,
            "total_predictions": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "brier_score": brier_score(agent_name, lookback_days),
            "trust_adjustment": trust_adjustment_for(agent_name, lookback_days),
            "by_type": by_type,
            "calibration": calibration,
            "lookback_days": lookback_days,
        }

    def get_all_agents_accuracy(self):
        AgentPrediction = _AgentPrediction()
        agents = AgentPrediction.objects.values_list("agent", flat=True).distinct()
        return {a: self.get_agent_accuracy(a) for a in agents}

    def suggest_confidence_adjustment(self, agent_name):
        adj = trust_adjustment_for(agent_name)
        return {"adjustment": adj,
                "reason": f"Brier-derived trust adjustment ({adj:.2f}×)"}


# Legacy single-shot helper.
def evaluate_prediction(prediction_id, actual_value, was_correct):
    AgentPrediction = _AgentPrediction()
    pred = AgentPrediction.objects.get(id=prediction_id)
    pred.actual_value = str(actual_value)
    pred.was_correct = was_correct
    pred.evaluated_at = timezone.now()
    pred.save()
    return pred
