"""Phase 37.4 — brain prediction resolver.

Sauron's Mind emits AgentPredictions with `prediction_type` strings that we
self-grade by querying current state. Three resolver strategies:

  - regime_persistence  — current regime label still matches predicted_value
  - rule_decay_continues — recent_avg_r still negative (decay continued)
  - rule_recovers       — recent_avg_r ≥ baseline_avg_r (decay reversed)

Anything we can't auto-grade is left pending; manual review remains an option.

Why this is light-touch: the brain's value isn't in being a perfect oracle —
it's in providing CONSISTENT shared context to other agents. The calibration
score governs how much downstream agents weight the brain's input via
`brain.context._brain_trust_score`.

Grading contract, same as `brain.hypotheses`: a resolver returns True/False
only when it actually measured reality, and None when it could not. None
leaves `was_correct` NULL so the Brier maths skips the row entirely. Marking
a prediction wrong because *we* had no reading is not calibration — it is the
platform scoring its own outages against the agent.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


def _resolve_regime_persistence(pred) -> tuple[Optional[bool], str]:
    """Was the predicted regime still the actual regime at deadline?

    None when no report witnessed the deadline, or when the report that did
    stored REGIME_UNKNOWN — the not-measured sentinel, which can only grade a
    claim that itself predicted "unknown".
    """
    from .models import BrainReport
    # First report at or after the deadline — the reading that witnessed it.
    cutoff = pred.expected_resolution_at
    if cutoff is None:
        return None, "ungradeable_no_deadline"
    report = (BrainReport.objects.filter(created_at__gte=cutoff, error="")
              .order_by("created_at").first())
    if report is None:
        return None, "ungradeable_no_report_yet"
    actual = report.regime_label
    if (actual == BrainReport.REGIME_UNKNOWN
            and pred.predicted_value != BrainReport.REGIME_UNKNOWN):
        return None, "ungradeable_regime_unclassified"
    correct = (actual == pred.predicted_value)
    return correct, actual


def _rule_avg_r_measurement(rule_name: str) -> tuple[Optional[float], str]:
    """Shared measurement for the two rule resolvers.

    Returns `(avg_r, note)`; avg_r is None when there is nothing to measure —
    no grading module, no closed trades, or too thin a sample for an average
    to say anything about the rule.
    """
    from .hypotheses import MIN_TRADES_FOR_RULE_R
    try:
        from bot_program.bot_grading import bot_performance_summary
    except Exception:
        return None, "ungradeable_summary_unavailable"
    rows = bot_performance_summary(rule_name=rule_name, days=7, min_n=1)
    if not rows:
        return None, "ungradeable_no_recent_data"
    # Pool the per-asset-class buckets n-weighted; rows[0] alone would score
    # whichever bucket happened to be built first.
    n = sum(int(r.get("n") or 0) for r in rows)
    if n < MIN_TRADES_FOR_RULE_R:
        return None, f"ungradeable_thin_sample_n={n}"
    avg_r = sum(float(r.get("avg_r") or 0) * int(r.get("n") or 0)
                for r in rows) / n
    return avg_r, f"avg_r={avg_r:.3f} n={n}"


def _resolve_rule_decay_continues(pred) -> tuple[Optional[bool], str]:
    """Did the rule named in `predicted_value` still have negative recent
    avg_r at deadline?"""
    avg_r, note = _rule_avg_r_measurement(pred.predicted_value)
    if avg_r is None:
        return None, note
    return (avg_r < 0), note


def _resolve_rule_recovers(pred) -> tuple[Optional[bool], str]:
    """Mirror of decay_continues: rule's recent avg_r ≥ 0."""
    avg_r, note = _rule_avg_r_measurement(pred.predicted_value)
    if avg_r is None:
        return None, note
    return (avg_r >= 0), note


RESOLVERS = {
    "regime_persistence": _resolve_regime_persistence,
    "rule_decay_continues": _resolve_rule_decay_continues,
    "rule_recovers": _resolve_rule_recovers,
}


def resolve_due_brain_predictions() -> dict:
    """Walk Sauron Mind predictions past deadline; grade those we can.

    Ungradeable rows keep `was_correct` NULL and stay in the queue: the
    measurement that was missing this hour (no report yet, too few closed
    trades) often exists by the next pass, and until it does the row must not
    reach the Brier maths in either direction.
    """
    try:
        from ai_agents.models import AgentPrediction
    except Exception:
        return {"resolved": 0, "skipped": 0, "ungradeable": 0}

    now = timezone.now()
    qs = AgentPrediction.objects.filter(
        agent="sauron_mind", was_correct__isnull=True,
        expected_resolution_at__lte=now,
    )
    resolved = 0
    skipped = 0
    ungradeable = 0
    for pred in qs:
        resolver = RESOLVERS.get(pred.prediction_type)
        if resolver is None:
            skipped += 1
            continue
        try:
            correct, note = resolver(pred)
            if correct is None:
                # Record WHY it couldn't be graded, leave it unevaluated.
                pred.actual_value = note[:100]
                pred.save(update_fields=["actual_value"])
                ungradeable += 1
                continue
            pred.was_correct = bool(correct)
            pred.actual_value = note[:100]
            pred.evaluated_at = now
            pred.save(update_fields=["was_correct", "actual_value", "evaluated_at"])
            resolved += 1
        except Exception as e:  # pragma: no cover
            logger.warning("[brain] resolver %s failed: %s", pred.prediction_type, e)
            skipped += 1
    return {"resolved": resolved, "skipped": skipped, "ungradeable": ungradeable}
