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
import math
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


def canonical_regime(value) -> "Optional[str]":
    """Map a free-text regime token onto the classifier's vocabulary.

    The synthesizer and strategist feed LLM output into regime_holds
    criteria; the model writes "Risk-On" or "mean-reversion" where the
    classifier says risk_on and mean_reverting, and an unmapped token
    would either be refused by the gate (silently dropping a
    near-canonical claim) or die UNRESOLVABLE at grading. Returns None
    when nothing matches — the caller then posts no bet at all.
    """
    from .models import BrainReport
    allowed = {v for v, _ in BrainReport.REGIME_CHOICES}
    token = str(value or "").strip().lower().replace("-", "_")
    token = "_".join(token.split())
    if token in allowed:
        return token
    aliases = {
        "riskon": "risk_on", "riskoff": "risk_off",
        "risk_on_regime": "risk_on", "risk_off_regime": "risk_off",
        "mean_reversion": "mean_reverting",
        "meanreverting": "mean_reverting",
        "mean_reverting_regime": "mean_reverting",
        "trend": "trending", "trending_regime": "trending",
        "blowoff": "blow_off", "blow_off_regime": "blow_off",
    }
    return aliases.get(token)


class UnmeasurableClaim(ValueError):
    """The claim's resolution_criteria can never be graded by any
    registered resolver — refused at creation, not buried at grading.

    65% of graded hypotheses were dying UNRESOLVABLE, and every one of
    them spent its whole horizon polluting the pending count and the
    briefing's market stats first. A claim that names no measurable
    resolver is not a bet, it is noise wearing a deadline."""


def _validate_criteria(criteria: dict, horizon_hours: int = 24) -> None:
    """Raise UnmeasurableClaim unless a registered resolver could, given
    evidence, actually grade these criteria.

    This checks only what is knowable AT CREATION — the kind and its
    required fields. Whether the evidence later arrives (a witnessing
    report, enough graded trades) stays the resolver's judgment; the
    gate's job is claims that could NEVER be graded, however the world
    turns out.
    """
    kind = criteria.get("kind")
    if kind not in RESOLVERS:
        raise UnmeasurableClaim(
            f"no resolver registered for kind {kind!r} — this claim "
            f"could never be graded (known: {sorted(RESOLVERS)})")

    if kind == "regime_holds":
        from .models import BrainReport
        allowed = {value for value, _ in BrainReport.REGIME_CHOICES}
        regime = criteria.get("regime")
        if regime not in allowed:
            raise UnmeasurableClaim(
                f"regime_holds needs a classifiable regime, got "
                f"{regime!r} (known: {sorted(allowed)})")

    elif kind == "rule_avg_r":
        if not criteria.get("rule_name"):
            raise UnmeasurableClaim("rule_avg_r needs a rule_name")
        cmp_ = criteria.get("comparator", ">=")
        if cmp_ not in (">=", "<=", "<", ">"):
            raise UnmeasurableClaim(
                f"rule_avg_r comparator {cmp_!r} is not one the resolver "
                f"understands")
        try:
            threshold = float(criteria.get("threshold", 0.0))
        except (TypeError, ValueError):
            raise UnmeasurableClaim(
                f"rule_avg_r threshold {criteria.get('threshold')!r} "
                f"is not a number")
        if not math.isfinite(threshold):
            raise UnmeasurableClaim(
                f"rule_avg_r threshold {criteria.get('threshold')!r} is "
                f"not finite — every comparison against it is decided at "
                f"creation, not by evidence")
        for field in ("window_days", "min_n"):
            if field in criteria:
                try:
                    int(criteria[field])
                except (TypeError, ValueError):
                    raise UnmeasurableClaim(
                        f"rule_avg_r {field} {criteria[field]!r} is not "
                        f"an integer — the resolver would crash on it "
                        f"every pass, forever")

        # SHAPE IS NOT MEASURABILITY. Every check above asks whether the
        # resolver could PARSE this claim. None of them asks whether the
        # named rule can produce a trade to grade it against — and a claim
        # about a rule that cannot trade before its own deadline is
        # unresolvable at birth.
        #
        # The cost is not the trust score: `agent_trust_score` excludes
        # UNRESOLVABLE deliberately and correctly, because those are OUR
        # blind spots rather than the agent's misses. The cost is that the
        # agent spends its whole forecasting budget on claims that can
        # never grade, and so never builds a record at all — thirty-plus
        # of them is how sauron_mind reached a fortnight of decay
        # forecasts about golden_cross while golden_cross emitted zero
        # signals and zero trades.
        _refuse_if_the_rule_cannot_trade(criteria, horizon_hours)

    elif kind == "anomaly_persists":
        if not criteria.get("anomaly_key"):
            raise UnmeasurableClaim("anomaly_persists needs an anomaly_key")


def _refuse_if_the_rule_cannot_trade(criteria: dict,
                                     horizon_hours: int) -> None:
    """Refuse a rule_avg_r claim whose rule is silenced past its deadline.

    Read from the platform's OWN ENFORCEMENT STATE, never from a guess
    about the market. A quiet rule may fire tomorrow and a forecast about
    it is legitimate; a rule the platform has switched off cannot, and
    saying so is a fact we already hold rather than a prediction.

    TWO conditions, and BOTH must hold, because either alone has a
    legitimate counterexample:

      1. PAUSED with no return before the deadline — so no NEW entry can
         open inside the window. A `paused_until` in the future but
         BEFORE the deadline is fine: the rule resumes in time.
      2. NO OPEN POSITION on the rule — because a pause stops entries,
         NOT EXITS. A paused rule holding an open trade will produce a
         closed trade when that trade closes, and the resolver counts
         trades closed since the claim was posted. The position reviewer
         posts precisely into this case: it flags `rule_decayed` on an
         open position and bets on that rule's forward R, which is a
         perfectly gradeable claim about a paused rule.

    Together they are an impossibility proof rather than a forecast: no
    entry can open and nothing is open to close, so the window holds zero
    closed trades by construction. Either half on its own is a guess.

    RESEARCH STAGE IS DELIBERATELY NOT REFUSED, and the reason is worth
    keeping. `stage_policy` does define research as "no orders at all",
    so a research rule genuinely cannot produce a trade — but research is
    the ENTRY RUNG OF A LADDER the platform expects to climb, not a
    decision to stop. Every RuleControl is created at that stage
    (`promotion_pipeline` seeds `promotion_stage: "research"`), and the
    generator posts a BIRTH HYPOTHESIS for each new rule immediately
    after. Refusing those would mean no rule ever gets a birth
    hypothesis, and `demoter` kills generated rules whose birth
    hypothesis is REFUTED — so the gate would have quietly disabled the
    only thing that culls bad generated rules. A pause is a decision; a
    stage is a position on a ladder.

    Fails OPEN in both unknown cases. A control layer we cannot read is
    our outage, and blocking an agent's forecast on our own outage is the
    same mistake in the other direction; and a rule with no RuleControl
    row is unknown to the control layer, which is not the same thing as
    known-and-silenced — refusing there would reject every claim about a
    newly registered rule.
    """
    rule = criteria.get("rule_name")
    try:
        from signals.models_control import RuleControl  # noqa: F401
        rc = RuleControl.objects.filter(rule_name=rule).first()
    except Exception:  # noqa: BLE001 — see the docstring: fail open
        return
    if rc is None:
        return

    try:
        still_paused = not rc.is_effectively_active()
    except Exception:  # noqa: BLE001 — fail open
        return
    if not still_paused:
        return

    deadline = timezone.now() + timedelta(hours=max(1, int(horizon_hours)))
    returns_in_time = (rc.paused_until is not None
                       and rc.paused_until < deadline)
    if returns_in_time:
        return

    # A PAUSE STOPS ENTRIES, NOT EXITS. An open position on this rule will
    # close, and the resolver counts trades closed since the claim was
    # posted — so a paused rule holding one is entirely gradeable. The
    # position reviewer posts exactly here: it flags `rule_decayed` on an
    # open position and bets on that rule's forward R.
    try:
        from bot_program.models import AssetBotTrade
        has_open = AssetBotTrade.objects.filter(
            rule_name=rule, status__in=("OPEN", "CLOSE_PENDING")).exists()
    except Exception:  # noqa: BLE001 — fail open
        return
    if has_open:
        return

    when = ("with no scheduled return" if rc.paused_until is None
            else f"until {rc.paused_until:%Y-%m-%d %H:%M}, after the deadline")
    raise UnmeasurableClaim(
        f"rule_avg_r names '{rule}', which is PAUSED {when} and holds no "
        f"open position — no entry can open and nothing is open to close, "
        f"so the window holds zero closed trades by construction and the "
        f"claim is unresolvable at birth")


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

    `resolution_criteria` must name a resolver in `RESOLVERS` and carry
    that resolver's required fields, or the claim is refused with
    UnmeasurableClaim before it ever reaches the market. Every posting
    site wraps this call in try/except, so a refused claim costs its
    author a warning line, never a crash.
    """
    from .knowledge_models import Hypothesis

    criteria = dict(resolution_criteria or {})
    try:
        _validate_criteria(criteria, horizon_hours=horizon_hours)
    except UnmeasurableClaim as exc:
        logger.warning("[hypothesis] refused unmeasurable claim from "
                       "%s: %s (claim: %.120s)",
                       source_agent, exc, claim_text)
        raise

    deadline = timezone.now() + timedelta(hours=max(1, int(horizon_hours)))
    return Hypothesis.objects.create(
        claim_text=str(claim_text or "")[:400],
        claim_payload=dict(claim_payload or {}),
        resolution_criteria=criteria,
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
    # Legacy rows predate the creation gate; a poisoned numeric here used
    # to raise, land in `skipped`, and re-crash on every pass forever —
    # the pending-pollution loop one field to the left of the gated ones.
    try:
        threshold = float(crit.get("threshold", 0.0))
        window = int(crit.get("window_days", 7))
        min_n = max(1, int(crit.get("min_n", MIN_TRADES_FOR_RULE_R)))
    except (TypeError, ValueError):
        return None, ("ungradeable: non-numeric threshold/window_days/"
                      "min_n in resolution_criteria")
    if not math.isfinite(threshold):
        return None, ("ungradeable: non-finite threshold — the comparison "
                      "was decided at creation, not by evidence")
    if not rule:
        return None, "ungradeable: no rule_name in resolution_criteria"
    # ONLY TRADES THAT CLOSED AFTER THE CLAIM WAS POSTED can grade it.
    # Passing `days=window` alone measured a 7-day window of which ~156 of
    # 168 hours were data the model had already read in its own snapshot
    # BEFORE writing the hypothesis — so agent_trust_score, the platform's
    # only objective number about its own brain, was scoring "did the agent
    # restate the last fortnight" and reporting it as "did the agent
    # predict". The harm ran the flattering way: a decay claim minted after
    # reading a negative record resolved true on that same record.
    #
    # `since` already exists in the signature; nothing needed building.
    since = max(hyp.created_at, timezone.now() - timedelta(days=window))
    rows = bot_performance_summary(rule_name=rule, since=since, min_n=1)
    if not rows:
        return None, (f"ungradeable: no trades for '{rule}' closed since the "
                      f"claim was posted — a forecast cannot be graded on "
                      f"the record that produced it")
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
    # A node the claim's own deadline never saw cannot answer for it.
    # `KnowledgeNode.current` never expires, and consolidation only
    # touches keys that fired in the last 24h — so a long-silent anomaly
    # kept grading True on the confidence it had the last time anyone
    # looked. That measures "was it hot once", not "is it hot now".
    seen_at = getattr(node, "updated_at", None) or getattr(node, "created_at", None)
    if seen_at is not None and hyp.resolution_deadline is not None \
            and seen_at < hyp.resolution_deadline:
        return None, (f"ungradeable: the anomaly node for '{key}' has not "
                      f"been refreshed since before the deadline — nothing "
                      f"measured it at the moment the claim came due")
    # The floor the WRITER uses, not a rounder number: consolidation
    # promotes at >=3 fires in 24h and stores confidence count/10, so the
    # cheapest node that can exist scores 0.30. Judging against 0.4 made
    # a freshly promoted anomaly grade REFUTED for existing at exactly
    # the strength its own promotion rule requires.
    return node.confidence >= 0.3, f"confidence={node.confidence:.2f}"


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
        crit = hyp.resolution_criteria
        kind = crit.get("kind") if isinstance(crit, dict) else None
        resolver = RESOLVERS.get(kind)
        zombie = resolver is None
        if resolver is None:
            # Rows posted before the creation gate existed. Skipping left
            # them PENDING forever, quietly inflating the market stats —
            # past their deadline with no resolver, they are unresolvable
            # and should say so. (`skipped` still counts resolver crashes,
            # which are transient and retried.)
            result, note = None, (
                f"ungradeable: no resolver registered for kind {kind!r}")
        else:
            try:
                result, note = resolver(hyp)
            except Exception as e:  # pragma: no cover
                logger.warning("[hypothesis] resolver %s raised: %s",
                               kind, e)
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
        # A back-graded zombie is dated when it CAME DUE, not when the
        # cleanup ran: stamping the whole legacy backlog "now" would
        # flood every recent-resolved window — the research agent's
        # snapshot, the dashboard's resolved list — with ungradeable
        # rows the night this deploys.
        hyp.resolved_at = hyp.resolution_deadline if zombie else now
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
