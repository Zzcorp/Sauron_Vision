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
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def _resolve_regime_persistence(pred) -> tuple[bool, str]:
    """Was the predicted regime still the actual regime at deadline?"""
    from .models import BrainReport
    # Most recent report whose timestamp ≤ pred.expected_resolution_at + 30min.
    cutoff = pred.expected_resolution_at
    report = (BrainReport.objects.filter(created_at__gte=cutoff, error="")
              .order_by("created_at").first())
    if report is None:
        return False, "no_report_after_deadline"
    actual = report.regime_label
    correct = (actual == pred.predicted_value)
    return correct, actual


def _resolve_rule_decay_continues(pred) -> tuple[bool, str]:
    """Did the rule named in `predicted_value` still have negative recent
    avg_r at deadline?"""
    try:
        from bot_program.bot_grading import bot_performance_summary
    except Exception:
        return False, "summary_unavailable"
    rows = bot_performance_summary(rule_name=pred.predicted_value, days=7, min_n=1)
    if not rows:
        return False, "no_recent_data"
    avg_r = float(rows[0].get("avg_r") or 0)
    return (avg_r < 0), f"avg_r={avg_r:.3f}"


def _resolve_rule_recovers(pred) -> tuple[bool, str]:
    """Mirror of decay_continues: rule's recent avg_r ≥ 0."""
    try:
        from bot_program.bot_grading import bot_performance_summary
    except Exception:
        return False, "summary_unavailable"
    rows = bot_performance_summary(rule_name=pred.predicted_value, days=7, min_n=1)
    if not rows:
        return False, "no_recent_data"
    avg_r = float(rows[0].get("avg_r") or 0)
    return (avg_r >= 0), f"avg_r={avg_r:.3f}"


RESOLVERS = {
    "regime_persistence": _resolve_regime_persistence,
    "rule_decay_continues": _resolve_rule_decay_continues,
    "rule_recovers": _resolve_rule_recovers,
}


def resolve_due_brain_predictions() -> dict:
    """Walk Sauron Mind predictions past deadline; grade those we can."""
    try:
        from ai_agents.models import AgentPrediction
    except Exception:
        return {"resolved": 0, "skipped": 0}

    now = timezone.now()
    qs = AgentPrediction.objects.filter(
        agent="sauron_mind", was_correct__isnull=True,
        expected_resolution_at__lte=now,
    )
    resolved = 0
    skipped = 0
    for pred in qs:
        resolver = RESOLVERS.get(pred.prediction_type)
        if resolver is None:
            skipped += 1
            continue
        try:
            correct, note = resolver(pred)
            pred.was_correct = bool(correct)
            pred.actual_value = note[:100]
            pred.evaluated_at = now
            pred.save(update_fields=["was_correct", "actual_value", "evaluated_at"])
            resolved += 1
        except Exception as e:  # pragma: no cover
            logger.warning("[brain] resolver %s failed: %s", pred.prediction_type, e)
            skipped += 1
    return {"resolved": resolved, "skipped": skipped}
