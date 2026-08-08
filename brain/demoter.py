"""Phase 42 — Auto-demoter for generated rules.

Runs daily 04:30 UTC. Walks every RuleControl whose `parameters['auto_generated']
== True` (set by Phase-41 generator) and is currently active, then checks
three kill criteria. Any one trigger demotes the rule:

  1. **Hypothesis refuted** — the Hypothesis posted at generation time
     resolved to `OUTCOME_REFUTED`. The generator's bet didn't pay off.
  2. **Sustained negative** — avg_r < `min_avg_r` over `window_days` with
     ≥ `min_n` graded trades. Persistent loser.
  3. **Consecutive losses** — last `consec_threshold` trades on this rule
     were all losses. Even fewer samples needed than #2; this is the kill
     switch.

Demotion =
  - linked OpportunitySetup.is_active = False (scanner stops)
  - RuleControl.status = "paused" (gate respects it)
  - RuleDemotion row written (forensic audit)

Defaults are conservative — auto-generated rules need to fail FAST, but a
1-trade kill is too aggressive. The generator's overall trust score will
adjust naturally if criteria are too tight (lots of false-positive demotions
= refuted hypotheses by the generator).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables (caller can override via demote_now kwargs) ─────────────────

DEFAULT_WINDOW_DAYS = 30
DEFAULT_MIN_N = 5
DEFAULT_MIN_AVG_R = 0.0
DEFAULT_CONSEC_THRESHOLD = 5
DEFAULT_MIN_AGE_DAYS = 14   # don't kill a rule that hasn't had time to perform


# ── Kill criteria ─────────────────────────────────────────────────────────

def _check_hypothesis_refuted(rule_name: str) -> Optional[dict]:
    """Returns metrics dict if the rule's birth-hypothesis was refuted, else None."""
    try:
        from .generator_models import GeneratedSetupProposal
        proposal = (GeneratedSetupProposal.objects
                    .filter(rule_control__rule_name=rule_name)
                    .order_by("-created_at").first())
    except Exception:
        return None
    if proposal is None or proposal.hypothesis_id is None:
        return None
    try:
        hyp = proposal.hypothesis
        # Lazy access — reload.
        hyp.refresh_from_db()
    except Exception:
        return None
    from .knowledge_models import Hypothesis
    if hyp.outcome != Hypothesis.OUTCOME_REFUTED:
        return None
    return {
        "hypothesis_id": hyp.id,
        "claim_text": hyp.claim_text,
        "resolution_notes": hyp.resolution_notes,
        "resolved_at": hyp.resolved_at.isoformat() if hyp.resolved_at else None,
    }


def _check_sustained_negative(rule_name: str, *,
                                window_days: int, min_n: int,
                                min_avg_r: float) -> Optional[dict]:
    """Returns metrics dict if avg_r < min_avg_r over the window with ≥ min_n trades."""
    try:
        from bot_program.bot_grading import bot_performance_summary
    except Exception:
        return None
    rows = bot_performance_summary(rule_name=rule_name,
                                     days=window_days, min_n=1)
    if not rows:
        return None
    row = rows[0]
    n = int(row.get("n") or 0)
    if n < min_n:
        return None
    avg_r = float(row.get("avg_r") or 0)
    if avg_r >= min_avg_r:
        return None
    return {"window_days": window_days, "n": n,
            "avg_r": round(avg_r, 4), "threshold": min_avg_r}


def _check_consecutive_losses(rule_name: str, *,
                                consec_threshold: int) -> Optional[dict]:
    """Returns metrics dict if the most recent `consec_threshold` graded trades
    on this rule were ALL losses (realized_r < 0)."""
    try:
        from bot_program.models import AssetBotTrade
    except Exception:
        return None
    qs = (AssetBotTrade.objects
          .filter(rule_name=rule_name, status="CLOSED",
                   realized_r__isnull=False)
          .order_by("-closed_at")[:consec_threshold])
    rows = list(qs.values("realized_r", "closed_at"))
    if len(rows) < consec_threshold:
        return None
    if all(float(r["realized_r"]) < 0 for r in rows):
        return {"consec_threshold": consec_threshold,
                "last_realized_rs": [round(float(r["realized_r"]), 4) for r in rows]}
    return None


# ── Demotion ──────────────────────────────────────────────────────────────

def demote_rule(rule_name: str, criterion: str, *,
                 metrics: Optional[dict] = None,
                 notes: str = "") -> Optional[object]:
    """Flip the linked setup to is_active=False, mark RuleControl paused,
    write a RuleDemotion row. Returns the demotion row, or None on failure
    or no-op (already demoted).
    """
    try:
        from signals.models_control import RuleControl
        from signals.models_opportunity import OpportunitySetup
        from .demoter_models import RuleDemotion
    except Exception as e:
        logger.warning("[demoter] models unavailable: %s", e)
        return None

    rule = RuleControl.objects.filter(rule_name=rule_name).first()
    if rule is None:
        return None
    # No-op if rule already paused.
    if rule.status == "paused":
        return None

    setup = OpportunitySetup.objects.filter(name=rule_name).first()
    if setup is not None and setup.is_active:
        setup.is_active = False
        setup.save(update_fields=["is_active", "updated_at"])

    rule.status = "paused"
    rule.notes = (rule.notes or "")[:300] + (
        f" | auto-demoted {timezone.now():%Y-%m-%d} ({criterion})"
    )
    rule.save(update_fields=["status", "notes"])

    row = RuleDemotion.objects.create(
        rule_name=rule_name,
        criterion=criterion,
        notes=notes[:2000],
        metrics=dict(metrics or {}),
    )
    try:
        from bot_program.audit import record_rule_demoted
        record_rule_demoted(
            rule_name=rule_name, criterion=criterion,
            metrics=metrics or {}, notes=notes,
        )
    except Exception:
        pass
    return row


def restore_rule(rule_name: str, *, restored_by: str = "") -> bool:
    """Manual restore — admin re-enables a demoted rule."""
    try:
        from signals.models_control import RuleControl
        from signals.models_opportunity import OpportunitySetup
        from .demoter_models import RuleDemotion
    except Exception:
        return False

    rule = RuleControl.objects.filter(rule_name=rule_name).first()
    setup = OpportunitySetup.objects.filter(name=rule_name).first()
    if rule is None:
        return False

    if setup is not None:
        setup.is_active = True
        setup.save(update_fields=["is_active", "updated_at"])
    rule.status = "active"
    rule.save(update_fields=["status"])

    # Stamp the most recent open demotion as restored.
    last = (RuleDemotion.objects
            .filter(rule_name=rule_name, restored_at__isnull=True)
            .order_by("-demoted_at").first())
    if last is not None:
        last.restored_at = timezone.now()
        last.restored_by = restored_by[:80]
        last.save(update_fields=["restored_at", "restored_by"])
    try:
        from bot_program.audit import record_rule_restored
        record_rule_restored(rule_name=rule_name, restored_by=restored_by)
    except Exception:
        pass
    return True


# ── Top-level scan ────────────────────────────────────────────────────────

def scan_generated_rules_now(*,
                                window_days: int = DEFAULT_WINDOW_DAYS,
                                min_n: int = DEFAULT_MIN_N,
                                min_avg_r: float = DEFAULT_MIN_AVG_R,
                                consec_threshold: int = DEFAULT_CONSEC_THRESHOLD,
                                min_age_days: int = DEFAULT_MIN_AGE_DAYS) -> dict:
    """Walk every active auto-generated rule; demote those meeting any kill
    criterion. Always returns a summary dict; never raises.
    """
    try:
        from signals.models_control import RuleControl
    except Exception as e:
        return {"ok": False, "error": str(e), "n_demoted": 0}

    cutoff_age = timezone.now() - timedelta(days=min_age_days)
    candidates = list(RuleControl.objects
                       .filter(status="active",
                                parameters__auto_generated=True)
                       .filter(created_at__lte=cutoff_age))

    n_demoted = 0
    n_skipped_too_young = 0
    n_no_kill_criteria = 0
    breakdown = {
        "hypothesis_refuted": 0,
        "sustained_negative": 0,
        "consecutive_losses": 0,
    }

    # Inspect age separately so tests can verify min_age_days short-circuits.
    young = (RuleControl.objects
             .filter(status="active", parameters__auto_generated=True,
                      created_at__gt=cutoff_age).count())
    n_skipped_too_young = young

    for rule in candidates:
        rule_name = rule.rule_name
        # Order: cheapest check first.
        criterion = None
        metrics = None

        m = _check_hypothesis_refuted(rule_name)
        if m:
            criterion = "hypothesis_refuted"
            metrics = m

        if not criterion:
            m = _check_consecutive_losses(rule_name,
                                            consec_threshold=consec_threshold)
            if m:
                criterion = "consecutive_losses"
                metrics = m

        if not criterion:
            m = _check_sustained_negative(rule_name,
                                            window_days=window_days,
                                            min_n=min_n,
                                            min_avg_r=min_avg_r)
            if m:
                criterion = "sustained_negative"
                metrics = m

        if not criterion:
            n_no_kill_criteria += 1
            continue

        row = demote_rule(rule_name, criterion, metrics=metrics)
        if row is not None:
            n_demoted += 1
            breakdown[criterion] = breakdown.get(criterion, 0) + 1
            logger.info("[demoter] auto-demoted %s (%s): %s",
                         rule_name, criterion, metrics)

    return {
        "ok": True,
        "n_candidates": len(candidates),
        "n_demoted": n_demoted,
        "n_skipped_too_young": n_skipped_too_young,
        "n_no_kill_criteria": n_no_kill_criteria,
        "breakdown": breakdown,
    }
