"""Phase 38.2 — hypothesis market helpers.

Lifecycle:
  post_hypothesis(...)             # any agent claims something
  vote(hypothesis, agent, stance)  # other agents weigh in (often a critic)
  resolve_due()                    # nightly: grade hypotheses past deadline

Resolved hypotheses feed Phase 6 calibration via the linked AgentPrediction —
that's how *trust* per agent is measured. An agent that's right wins weight;
one that's wrong loses weight in downstream context-injection consumers.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Posting + voting ──────────────────────────────────────────────────────

def post_hypothesis(*,
                    claim_text: str,
                    source_agent: str,
                    claim_payload: Optional[dict] = None,
                    resolution_criteria: Optional[dict] = None,
                    confidence: float = 0.5,
                    horizon_hours: int = 24,
                    brain_report=None,
                    agent_prediction=None) -> "Hypothesis":
    """Append a hypothesis. Returns the row.

    `resolution_criteria` is a free-form dict the resolver consumes —
    callers should match it to one of the keys in `RESOLVERS` below.
    """
    from .knowledge_models import Hypothesis
    deadline = timezone.now() + timedelta(hours=max(1, int(horizon_hours)))
    return Hypothesis.objects.create(
        claim_text=str(claim_text or "")[:400],
        claim_payload=dict(claim_payload or {}),
        resolution_criteria=dict(resolution_criteria or {}),
        confidence=max(0.0, min(1.0, float(confidence))),
        source_agent=str(source_agent or "")[:80],
        resolution_deadline=deadline,
        brain_report=brain_report,
        agent_prediction=agent_prediction,
    )


def vote(hypothesis, *, agent: str, stance: str,
         confidence: float = 0.5, reasoning: str = "") -> "HypothesisVote":
    """Add or update an agent's stance on a hypothesis. One vote per agent."""
    from .knowledge_models import HypothesisVote
    obj, _ = HypothesisVote.objects.update_or_create(
        hypothesis=hypothesis, agent=str(agent or "")[:80],
        defaults={
            "stance": stance,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "reasoning": (reasoning or "")[:2000],
        },
    )
    return obj


# ── Resolvers ─────────────────────────────────────────────────────────────

def _resolve_regime_holds(hyp) -> tuple[Optional[bool], str]:
    """`resolution_criteria = {"kind": "regime_holds", "regime": "trending"}` —
    True iff the most recent BrainReport's regime matches."""
    from .models import BrainReport
    expected = (hyp.resolution_criteria or {}).get("regime")
    if not expected:
        return None, "missing_regime_in_criteria"
    report = (BrainReport.objects
              .filter(error="").order_by("-created_at").first())
    if report is None:
        return None, "no_report"
    return (report.regime_label == expected), f"actual={report.regime_label}"


def _resolve_rule_avg_r_threshold(hyp) -> tuple[Optional[bool], str]:
    """`resolution_criteria = {"kind": "rule_avg_r", "rule_name": "X",
    "comparator": ">=" or "<", "threshold": 0.0, "window_days": 7}`"""
    from bot_program.bot_grading import bot_performance_summary
    crit = hyp.resolution_criteria or {}
    rule = crit.get("rule_name")
    cmp_ = crit.get("comparator", ">=")
    threshold = float(crit.get("threshold", 0.0))
    window = int(crit.get("window_days", 7))
    if not rule:
        return None, "missing_rule_name"
    rows = bot_performance_summary(rule_name=rule, days=window, min_n=1)
    if not rows:
        return None, "no_data"
    avg_r = float(rows[0].get("avg_r") or 0)
    if cmp_ == ">=":
        return avg_r >= threshold, f"avg_r={avg_r:.3f}"
    if cmp_ == "<=":
        return avg_r <= threshold, f"avg_r={avg_r:.3f}"
    if cmp_ == "<":
        return avg_r < threshold, f"avg_r={avg_r:.3f}"
    if cmp_ == ">":
        return avg_r > threshold, f"avg_r={avg_r:.3f}"
    return None, f"unknown_comparator={cmp_}"


def _resolve_anomaly_persists(hyp) -> tuple[Optional[bool], str]:
    """`resolution_criteria = {"kind": "anomaly_persists", "anomaly_key": "X"}`
    True if the anomaly node is still the current state (not superseded)
    AND has confidence ≥ 0.4."""
    from .knowledge_models import KnowledgeNode
    key = (hyp.resolution_criteria or {}).get("anomaly_key")
    if not key:
        return None, "missing_anomaly_key"
    node = KnowledgeNode.current(KnowledgeNode.KIND_ANOMALY, key)
    if node is None:
        return False, "no_node"
    return node.confidence >= 0.4, f"confidence={node.confidence:.2f}"


RESOLVERS = {
    "regime_holds": _resolve_regime_holds,
    "rule_avg_r": _resolve_rule_avg_r_threshold,
    "anomaly_persists": _resolve_anomaly_persists,
}


def resolve_due() -> dict:
    """Walk pending hypotheses past deadline; grade those whose criteria
    map to a known resolver."""
    from .knowledge_models import Hypothesis
    from ai_agents.models import AgentPrediction

    now = timezone.now()
    qs = Hypothesis.objects.filter(
        outcome=Hypothesis.OUTCOME_PENDING,
        resolution_deadline__lte=now,
    )
    confirmed = refuted = unresolvable = skipped = 0
    for hyp in qs:
        kind = (hyp.resolution_criteria or {}).get("kind")
        resolver = RESOLVERS.get(kind)
        if resolver is None:
            skipped += 1
            continue
        try:
            result, note = resolver(hyp)
        except Exception as e:  # pragma: no cover
            logger.warning("[hypothesis] resolver %s raised: %s", kind, e)
            skipped += 1
            continue

        if result is None:
            hyp.outcome = Hypothesis.OUTCOME_UNRESOLVABLE
            unresolvable += 1
        elif result:
            hyp.outcome = Hypothesis.OUTCOME_CONFIRMED
            confirmed += 1
        else:
            hyp.outcome = Hypothesis.OUTCOME_REFUTED
            refuted += 1
        hyp.resolved_at = now
        hyp.resolution_notes = note[:500]
        hyp.save(update_fields=["outcome", "resolved_at", "resolution_notes"])

        # Phase-54 — chain the resolution into the immutable audit log so
        # per-agent calibration history can be reconstructed forensically.
        try:
            from bot_program.audit import record_hypothesis_resolved
            record_hypothesis_resolved(
                hypothesis=hyp, outcome=hyp.outcome,
                resolution_notes=note,
            )
        except Exception:
            pass

        # Mirror into Phase-6 AgentPrediction if linked.
        if hyp.agent_prediction_id:
            try:
                pred = hyp.agent_prediction
                pred.was_correct = (hyp.outcome == Hypothesis.OUTCOME_CONFIRMED)
                pred.actual_value = note[:100]
                pred.evaluated_at = now
                pred.save(update_fields=[
                    "was_correct", "actual_value", "evaluated_at",
                ])
            except Exception:
                pass

    return {
        "confirmed": confirmed, "refuted": refuted,
        "unresolvable": unresolvable, "skipped": skipped,
    }


# ── Per-agent trust score ─────────────────────────────────────────────────

def agent_trust_score(agent: str, *, lookback_n: int = 50) -> Optional[float]:
    """1 - 2 * Brier over the last `lookback_n` resolved hypotheses by `agent`.
    None if no resolved data.

    This is the OBJECTIVE trust signal — pure calibration. For the blended
    score (objective + operator override), use `agent_combined_trust`."""
    from .knowledge_models import Hypothesis
    qs = (Hypothesis.objects
          .filter(source_agent=agent)
          .exclude(outcome=Hypothesis.OUTCOME_PENDING)
          .exclude(outcome=Hypothesis.OUTCOME_UNRESOLVABLE)
          .order_by("-resolved_at")[:lookback_n])
    rows = list(qs.values("outcome", "confidence"))
    if not rows:
        return None
    s = 0.0
    for r in rows:
        outcome = 1.0 if r["outcome"] == Hypothesis.OUTCOME_CONFIRMED else 0.0
        conf = float(r["confidence"] or 0.5)
        s += (conf - outcome) ** 2
    brier = s / len(rows)
    return round(max(0.0, 1.0 - 2 * brier), 4)


def agent_combined_trust(agent: str, *,
                            brier_weight: float = 0.7,
                            override_weight: float = 0.3,
                            lookback_n: int = 50,
                            override_days: int = 30) -> Optional[float]:
    """Phase-56 blended trust: weighted average of Brier-derived calibration
    (Phase 6) and 1-minus-operator-override-rate (Phase 55).

    Behaviors by signal availability:
      - both available     → weighted avg (defaults: 70% Brier, 30% override)
      - only Brier         → returns Brier (operator hasn't decided yet)
      - only override rate → returns 1 - override_rate (calibration bootstrap)
      - neither            → None

    Why blend: Brier measures whether predictions came true (objective).
    Operator override rate measures whether the operator agrees with the
    agent's judgment (subjective). They're complementary — an agent can
    technically resolve hypotheses correctly while making decisions the
    operator finds bad, or vice versa.
    """
    brier_trust = agent_trust_score(agent, lookback_n=lookback_n)

    override_rate = None
    try:
        from bot_program.audit_queries import agent_override_rate
        override_rate = agent_override_rate(agent, days=override_days)
    except Exception:
        pass

    if brier_trust is None and override_rate is None:
        return None
    if brier_trust is not None and override_rate is None:
        return brier_trust
    if brier_trust is None and override_rate is not None:
        return round(1.0 - override_rate, 4)

    operator_trust = 1.0 - override_rate
    blended = brier_weight * brier_trust + override_weight * operator_trust
    return round(max(0.0, min(1.0, blended)), 4)
