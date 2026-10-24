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

ONE GRADER PER ROW (2026-10-24). A prediction the market took (a linked
Hypothesis) is graded by the market alone, at its nightly mirror
(brain.hypotheses.resolve_due): this hourly pass never touches it, so the
bots' number (brain.context._brain_trust_score) and the briefing's
(brain.hypotheses.agent_trust_score) rest on one grade per claim. This pass
grades only the orphans, on the market's own evidence rules: a regime in
the classifier's words (canonical_regime), a rule from the claim on
(claim_window_since) and on the venue it names, never the pooled record.
A row that can never be graded (NEVER_GRADEABLE), or is still ungradeable
REPORT_GRACE_HOURS past its deadline, is closed ungraded: `evaluated_at`
stamped, `was_correct` NULL. Ungraded, never wrong.
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
    from .hypotheses import canonical_regime
    from .models import BrainReport
    # The claim in the classifier's words, as the market reads it
    # (synthesizer._other_criteria): "Risk-On" is risk_on, not a miss. A
    # token that maps to nothing is the market's own refusal.
    expected = canonical_regime(pred.predicted_value)
    if expected is None:
        return None, "ungradeable_off_vocabulary"
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
            and expected != BrainReport.REGIME_UNKNOWN):
        return None, "ungradeable_regime_unclassified"
    correct = (actual == expected)
    return correct, actual


def _split_rule_venue(value: str) -> tuple[str, str]:
    """("rule", "venue") from a stored predicted_value (2026-10-08): the Mind
    writes "rule@venue" for a rule prediction that names its venue
    (synthesizer._emit_predictions); a bare rule, or an unknown suffix,
    is the pooled record every earlier prediction was graded on."""
    from .hypotheses import RULE_VENUES
    rule, sep, venue = str(value or "").rpartition("@")
    if sep and rule and venue in RULE_VENUES:
        return rule, venue
    return str(value or ""), ""


def _rule_avg_r_measurement(rule_name: str, *, since=None
                            ) -> tuple[Optional[float], str]:
    """Shared measurement for the two rule resolvers.

    Returns `(avg_r, note)`; avg_r is None when there is nothing to measure —
    no grading module, no closed trades, or too thin a sample for an average
    to say anything about the rule. `rule_name` may carry its venue,
    "rule@live" (2026-10-08): graded on that venue's trades alone. `since`
    (2026-10-24) measures only the trades closed after it, the claim's own
    window (hypotheses.claim_window_since); without it, the last 7 days.
    """
    from .hypotheses import MIN_TRADES_FOR_RULE_R, rule_rows_for
    rule_name, venue = _split_rule_venue(rule_name)
    window = {"since": since} if since is not None else {"days": 7}
    try:
        rows = rule_rows_for(rule_name, venue=venue, min_n=1, **window)
    except ImportError:
        return None, "ungradeable_summary_unavailable"
    if not rows:
        return None, "ungradeable_no_recent_data"
    # Pool the per-asset-class buckets n-weighted; rows[0] alone would score
    # whichever bucket happened to be built first.
    n = sum(int(r.get("n") or 0) for r in rows)
    if n < MIN_TRADES_FOR_RULE_R:
        return None, f"ungradeable_thin_sample_n={n}"
    avg_r = sum(float(r.get("avg_r") or 0) * int(r.get("n") or 0)
                for r in rows) / n
    return avg_r, (f"avg_r={avg_r:.3f} n={n}"
                   + (f" {venue}" if venue else ""))


#: RULE_DAYS: the window a rule claim is measured over, as the market's
#: rule_avg_r criteria carry it (synthesizer._rule_criteria).
RULE_DAYS = 7


def _rule_claim_measurement(pred) -> tuple[Optional[float], str]:
    """A Mind rule claim measured the market's way (2026-10-24): on the
    venue it names, from the claim on. A claim naming no venue is never
    graded on the pooled record of real money, demo and the simulator: the
    market refuses it at posting (hypotheses.VENUE_REQUIRED_FROM)."""
    from .hypotheses import claim_window_since
    _rule, venue = _split_rule_venue(pred.predicted_value)
    if not venue:
        return None, "ungradeable_no_venue"
    return _rule_avg_r_measurement(
        pred.predicted_value,
        since=claim_window_since(pred.created_at, RULE_DAYS))


def _resolve_rule_decay_continues(pred) -> tuple[Optional[bool], str]:
    """Did the rule named in `predicted_value` still have negative recent
    avg_r at deadline?"""
    avg_r, note = _rule_claim_measurement(pred)
    if avg_r is None:
        return None, note
    return (avg_r < 0), note


def _resolve_rule_recovers(pred) -> tuple[Optional[bool], str]:
    """Mirror of decay_continues: rule's recent avg_r ≥ 0."""
    avg_r, note = _rule_claim_measurement(pred)
    if avg_r is None:
        return None, note
    return (avg_r >= 0), note


RESOLVERS = {
    "regime_persistence": _resolve_regime_persistence,
    "rule_decay_continues": _resolve_rule_decay_continues,
    "rule_recovers": _resolve_rule_recovers,
}


#: Notes no later pass can turn into a grade: the row is closed ungraded at
#: once (2026-10-24), not walked every hour for ever.
NEVER_GRADEABLE = ("ungradeable_off_vocabulary", "ungradeable_no_venue",
                   "ungradeable_no_resolver")


def _close_ungraded(pred, note: str, now) -> None:
    pred.was_correct = None
    pred.actual_value = note[:100]
    pred.evaluated_at = now
    pred.save(update_fields=["was_correct", "actual_value", "evaluated_at"])


def resolve_due_brain_predictions() -> dict:
    """Walk the Mind's ORPHAN predictions past deadline; grade those we can.

    A row the market took (a linked Hypothesis) is the market's alone,
    graded at its nightly mirror (module docstring). A row already closed
    (`evaluated_at` set) is never walked again.

    An orphan that is only temporarily ungradeable (no report yet, too few
    closed trades) keeps `was_correct` NULL and stays in the queue: the
    measurement missing this hour often exists by the next pass. It is
    closed ungraded once it is still ungradeable REPORT_GRACE_HOURS past
    its deadline (the market's own grace), and at once when its note can
    never change (NEVER_GRADEABLE: no resolver, a regime the classifier
    does not speak, a rule claim naming no venue).
    """
    from datetime import timedelta
    try:
        from ai_agents.models import AgentPrediction
    except Exception:
        return {"resolved": 0, "skipped": 0, "ungradeable": 0, "closed": 0}
    from .hypotheses import REPORT_GRACE_HOURS

    now = timezone.now()
    grace = timedelta(hours=REPORT_GRACE_HOURS)
    qs = AgentPrediction.objects.filter(
        agent="sauron_mind", was_correct__isnull=True,
        evaluated_at__isnull=True, hypotheses__isnull=True,
        expected_resolution_at__lte=now,
    )
    resolved = 0
    skipped = 0
    ungradeable = 0
    closed = 0
    for pred in qs:
        resolver = RESOLVERS.get(pred.prediction_type)
        if resolver is None:
            _close_ungraded(pred, "ungradeable_no_resolver", now)
            skipped += 1
            closed += 1
            continue
        try:
            correct, note = resolver(pred)
            if correct is None:
                # Record WHY it couldn't be graded.
                ungradeable += 1
                past_grace = (pred.expected_resolution_at is not None
                              and now >= pred.expected_resolution_at + grace)
                if note in NEVER_GRADEABLE or past_grace:
                    _close_ungraded(pred, note, now)
                    closed += 1
                else:
                    pred.actual_value = note[:100]
                    pred.save(update_fields=["actual_value"])
                continue
            pred.was_correct = bool(correct)
            pred.actual_value = note[:100]
            pred.evaluated_at = now
            pred.save(update_fields=["was_correct", "actual_value", "evaluated_at"])
            resolved += 1
        except Exception as e:  # pragma: no cover
            logger.warning("[brain] resolver %s failed: %s", pred.prediction_type, e)
            skipped += 1
    return {"resolved": resolved, "skipped": skipped,
            "ungradeable": ungradeable, "closed": closed}


def awaiting_grade(qs):
    """The rows of `qs` (AgentPredictions) still waiting for a grade: not
    graded, not closed ungraded, and not linked to a hypothesis the market
    has already settled (an UNRESOLVABLE one leaves its row NULL for good).
    /brain/'s pending tile, which counted every NULL row for ever."""
    from brain.knowledge_models import Hypothesis
    settled = (Hypothesis.OUTCOME_CONFIRMED, Hypothesis.OUTCOME_REFUTED,
               Hypothesis.OUTCOME_UNRESOLVABLE)
    return (qs.filter(was_correct__isnull=True, evaluated_at__isnull=True)
            .exclude(hypotheses__outcome__in=settled).distinct())


def _brier_trust(rows) -> Optional[float]:
    """1 - 2*Brier over (was_correct, confidence) pairs, the bots' formula
    (brain.context._brain_trust_score); None for no rows."""
    if not rows:
        return None
    s = 0.0
    for correct, conf in rows:
        outcome = 1.0 if correct else 0.0
        s += (float(conf if conf is not None else 0.5) - outcome) ** 2
    return round(max(0.0, 1.0 - 2 * (s / len(rows))), 4)


def trust_disagreements() -> int:
    """How many Mind rows linked to a SETTLED hypothesis carry a grade the
    hypothesis does not (the two graders wrote over each other before
    2026-10-24). Read-only: no repair, the 50-row window turns over."""
    from ai_agents.models import AgentPrediction
    from brain.knowledge_models import Hypothesis
    want = {Hypothesis.OUTCOME_CONFIRMED: True,
            Hypothesis.OUTCOME_REFUTED: False,
            Hypothesis.OUTCOME_UNRESOLVABLE: None}
    n = 0
    rows = (Hypothesis.objects
            .filter(source_agent="sauron_mind",
                    agent_prediction__isnull=False)
            .exclude(outcome=Hypothesis.OUTCOME_PENDING)
            .values_list("outcome", "agent_prediction__was_correct"))
    for outcome, graded in rows:
        if want.get(outcome) != graded:
            n += 1
    return n


def projected_mind_trust(lookback_n: int = 50) -> dict:
    """The bots' number as one grader per row would give it, read-only
    (2026-10-24): a linked row takes its hypothesis's outcome (UNRESOLVABLE
    and PENDING none), an orphan keeps its grade unless it can never be
    graded now (a regime off the classifier's words, a rule naming no
    venue). Newest first by when it was graded, the last `lookback_n`.

    {score, band, n, current_n, newest_graded_hours}: the projection, and
    the number of rows the current score stands on with its newest age."""
    from ai_agents.models import AgentPrediction
    from brain.knowledge_models import Hypothesis
    from .context import brain_trust_band
    from .hypotheses import canonical_regime
    now = timezone.now()
    current = list(AgentPrediction.objects
                   .filter(agent="sauron_mind", was_correct__isnull=False)
                   .order_by("-evaluated_at")
                   .values_list("evaluated_at", flat=True)[:lookback_n])
    newest = (round((now - current[0]).total_seconds() / 3600.0, 1)
              if current and current[0] else None)
    graded = []
    for h in (Hypothesis.objects
              .filter(source_agent="sauron_mind",
                      agent_prediction__isnull=False,
                      outcome__in=(Hypothesis.OUTCOME_CONFIRMED,
                                   Hypothesis.OUTCOME_REFUTED))
              .select_related("agent_prediction")):
        graded.append((h.resolved_at or now,
                       h.outcome == Hypothesis.OUTCOME_CONFIRMED,
                       h.agent_prediction.confidence))
    for p in (AgentPrediction.objects
              .filter(agent="sauron_mind", was_correct__isnull=False,
                      hypotheses__isnull=True)):
        if (p.prediction_type == "regime_persistence"
                and canonical_regime(p.predicted_value) is None):
            continue
        if (p.prediction_type in ("rule_decay_continues", "rule_recovers")
                and not _split_rule_venue(p.predicted_value)[1]):
            continue
        graded.append((p.evaluated_at or now, bool(p.was_correct),
                       p.confidence))
    graded.sort(key=lambda r: r[0], reverse=True)
    rows = [(c, conf) for _, c, conf in graded[:lookback_n]]
    score = _brier_trust(rows)
    # brain_trust_band(None) would read the LIVE score: say unknown here
    return {"score": score, "band": brain_trust_band(score)
            if score is not None else "unknown",
            "n": len(rows), "current_n": len(current),
            "newest_graded_hours": newest}
