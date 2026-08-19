"""Phase 38.2 — hypothesis market helpers.

Lifecycle:
  post_hypothesis(...)             # any agent claims something
  vote(hypothesis, agent, stance)  # other agents weigh in (often a critic)
  resolve_due()                    # nightly: grade hypotheses past deadline

Resolved hypotheses feed Phase 6 calibration via the linked AgentPrediction —
that's how *trust* per agent is measured. An agent that's right wins weight;
one that's wrong loses weight in downstream context-injection consumers.

Grading contract (a resolver returns one of three things):
  True / False  — we measured reality and the claim held / didn't
  None          — we CANNOT grade this claim, ever (→ OUTCOME_UNRESOLVABLE,
                  excluded from the Brier maths)
  DEFER         — we cannot grade it YET; leave PENDING and retry next pass

The distinction is the whole point. A measurement failure ("the regime was
never classified", "the rule has one closed trade", "no report exists for
that moment") is not a refutation. Collapsing it to False charges the agent
for the platform's own blind spot and silently drags every downstream trust
score — and the rule demoter that kills rules on OUTCOME_REFUTED — with it.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


class _Defer:
    """Sentinel: not gradeable *yet*, unlike None which means never.

    Without it a resolver pass that fires in the gap between a claim's
    deadline and the next synthesis would burn a perfectly gradeable claim
    as UNRESOLVABLE. DEFER keeps the row PENDING so the next pass can try.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "DEFER"


DEFER = _Defer()

# BrainReport.REGIME_UNKNOWN is the "we could not classify it" sentinel, not
# an observed market state. It can only grade a claim that itself predicted
# "unknown"; against any other claim it is an absence of evidence.
REGIME_NOT_MEASURED = "unknown"

# How long past a claim's deadline we still accept a BrainReport as the
# witness of that moment. Synthesis runs every 30min, so this is generous
# slack for a stalled beat — past it, nothing observed the deadline.
REPORT_GRACE_HOURS = 12

# An average R over one or two trades is noise, not a measurement of a rule's
# expectancy. Grading against it scores the sample size, not the agent.
MIN_TRADES_FOR_RULE_R = 3


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

def _report_for_deadline(hyp, *, grace_hours: int = REPORT_GRACE_HOURS):
    """Return `(report, status)` — the BrainReport that witnessed the claim
    coming due, not merely the newest row on the table.

    Why the deadline and not `latest`: a claim is written against a horizon
    ("regime stays trending for the next 12h"). The resolver runs nightly, so
    the newest report can be a day younger and describe a different market —
    grading against it scores the agent on a question it never answered. We
    take the FIRST clean report at or after the deadline: the platform's own
    reading at the moment the claim came due.

    status ∈ {"ok", "defer", "missing"}:
      ok      — a witnessing report exists
      defer   — the grace window is still open, one may yet be synthesised
      missing — grace elapsed with nothing to grade against
    """
    from .models import BrainReport
    clean = BrainReport.objects.filter(error="")
    deadline = hyp.resolution_deadline
    if deadline is None:
        # No horizon was recorded — the latest reading is all we have.
        report = clean.order_by("-created_at").first()
        return report, ("ok" if report is not None else "missing")
    report = (clean.filter(created_at__gte=deadline)
              .order_by("created_at").first())
    if report is not None:
        return report, "ok"
    if timezone.now() < deadline + timedelta(hours=grace_hours):
        return None, "defer"
    return None, "missing"


def _resolve_regime_holds(hyp):
    """`resolution_criteria = {"kind": "regime_holds", "regime": "trending"}` —
    True iff the regime the platform read at the deadline matches the claim.

    An actual of REGIME_UNKNOWN is the not-measured sentinel: it grades a
    claim that predicted "unknown" (that claim was about our own blindness
    and it came true) and NOTHING else. Any other claim comes back None so a
    failed classification never lands on an agent's record as a wrong call.
    """
    expected = (hyp.resolution_criteria or {}).get("regime")
    if not expected:
        return None, "ungradeable: no regime in resolution_criteria"
    report, status = _report_for_deadline(hyp)
    if status == "defer":
        return DEFER, "no brain report at the deadline yet — retrying"
    if report is None:
        return None, (f"ungradeable: no brain report within "
                      f"{REPORT_GRACE_HOURS}h of the deadline to grade against")
    actual = report.regime_label
    if actual == REGIME_NOT_MEASURED and expected != REGIME_NOT_MEASURED:
        return None, (f"ungradeable: the regime was never classified at the "
                      f"deadline (actual={actual}) — a measurement failure "
                      f"cannot refute a claim of '{expected}'")
    return (actual == expected), f"actual={actual} expected={expected}"


def _resolve_rule_avg_r_threshold(hyp):
    """`resolution_criteria = {"kind": "rule_avg_r", "rule_name": "X",
    "comparator": ">=" or "<", "threshold": 0.0, "window_days": 7,
    "min_n": 3}`

    Ungradeable (None) when the window holds fewer than `min_n` graded trades:
    an average over one trade measures that trade, not the rule, and the agent
    shouldn't be marked wrong because the rule barely fired.
    """
    from bot_program.bot_grading import bot_performance_summary
    crit = hyp.resolution_criteria or {}
    rule = crit.get("rule_name")
    cmp_ = crit.get("comparator", ">=")
    threshold = float(crit.get("threshold", 0.0))
    window = int(crit.get("window_days", 7))
    min_n = max(1, int(crit.get("min_n", MIN_TRADES_FOR_RULE_R)))
    if not rule:
        return None, "ungradeable: no rule_name in resolution_criteria"
    rows = bot_performance_summary(rule_name=rule, days=window, min_n=1)
    if not rows:
        return None, (f"ungradeable: no graded trades for '{rule}' in the "
                      f"last {window}d")
    # bot_performance_summary buckets per (rule, asset_class); a rule that
    # trades two classes returns two rows. Pool them n-weighted — grading off
    # rows[0] would score whichever bucket happened to be built first.
    n = sum(int(r.get("n") or 0) for r in rows)
    if n < min_n:
        return None, (f"ungradeable: only {n} graded trade(s) for '{rule}' in "
                      f"{window}d, need {min_n} before an average means anything")
    avg_r = sum(float(r.get("avg_r") or 0) * int(r.get("n") or 0)
                for r in rows) / n
    note = f"avg_r={avg_r:.3f} n={n}"
    if cmp_ == ">=":
        return avg_r >= threshold, note
    if cmp_ == "<=":
        return avg_r <= threshold, note
    if cmp_ == "<":
        return avg_r < threshold, note
    if cmp_ == ">":
        return avg_r > threshold, note
    return None, f"ungradeable: unknown comparator '{cmp_}'"


def _resolve_anomaly_persists(hyp):
    """`resolution_criteria = {"kind": "anomaly_persists", "anomaly_key": "X"}`
    True if the anomaly node is still the current state (not superseded)
    AND has confidence ≥ 0.4.

    No node at all means consolidation never promoted this anomaly into the
    graph, so we never watched it — a hole in the record, not evidence the
    anomaly faded. `KnowledgeNode.current` only returns None when NO version
    of the key exists (superseded rows always leave a current one behind), so
    this test is unambiguous.
    """
    from .knowledge_models import KnowledgeNode
    key = (hyp.resolution_criteria or {}).get("anomaly_key")
    if not key:
        return None, "ungradeable: no anomaly_key in resolution_criteria"
    node = KnowledgeNode.current(KnowledgeNode.KIND_ANOMALY, key)
    if node is None:
        return None, (f"ungradeable: anomaly '{key}' was never recorded in the "
                      f"knowledge graph — nothing was watching it")
    return node.confidence >= 0.4, f"confidence={node.confidence:.2f}"


RESOLVERS = {
    "regime_holds": _resolve_regime_holds,
    "rule_avg_r": _resolve_rule_avg_r_threshold,
    "anomaly_persists": _resolve_anomaly_persists,
}


def resolve_due() -> dict:
    """Walk pending hypotheses past deadline; grade those whose criteria
    map to a known resolver.

    Counts returned: confirmed / refuted / unresolvable / deferred / skipped.
    `deferred` rows stay PENDING — the evidence hasn't landed yet.
    """
    from .knowledge_models import Hypothesis

    now = timezone.now()
    qs = Hypothesis.objects.filter(
        outcome=Hypothesis.OUTCOME_PENDING,
        resolution_deadline__lte=now,
    )
    confirmed = refuted = unresolvable = skipped = deferred = 0
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

        if result is DEFER:
            # Gradeable evidence may still arrive — leave the row PENDING
            # rather than burning the claim as unresolvable.
            deferred += 1
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
        #
        # An UNRESOLVABLE outcome MUST leave `was_correct` NULL. Both Brier
        # consumers — ai_agents.calibration.brier_score and
        # brain.context._brain_trust_score — select on
        # `was_correct__isnull=False` and score False as a miss, so stamping
        # an ungraded claim False charges the agent for our measurement
        # failure. That is the same bug as marking the hypothesis refuted,
        # just one table over.
        if hyp.agent_prediction_id:
            try:
                pred = hyp.agent_prediction
                graded = hyp.outcome in (Hypothesis.OUTCOME_CONFIRMED,
                                         Hypothesis.OUTCOME_REFUTED)
                pred.was_correct = (
                    (hyp.outcome == Hypothesis.OUTCOME_CONFIRMED)
                    if graded else None)
                pred.actual_value = note[:100]
                pred.evaluated_at = now if graded else None
                pred.save(update_fields=[
                    "was_correct", "actual_value", "evaluated_at",
                ])
            except Exception:
                pass

    return {
        "confirmed": confirmed, "refuted": refuted,
        "unresolvable": unresolvable, "deferred": deferred,
        "skipped": skipped,
    }


# ── Per-agent trust score ─────────────────────────────────────────────────

def agent_trust_score(agent: str, *, lookback_n: int = 50) -> Optional[float]:
    """1 - 2 * Brier over the last `lookback_n` resolved hypotheses by `agent`.
    None if no resolved data.

    This is the OBJECTIVE trust signal — pure calibration. For the blended
    score (objective + operator override), use `agent_combined_trust`.

    UNRESOLVABLE is excluded, not scored as a miss: those are claims the
    platform failed to measure, and an agent's trust must not move on our
    blind spots. Same reason PENDING is excluded.
    """
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
