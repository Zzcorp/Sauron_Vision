"""Rule actuator — Phase-5 closed-loop self-adjustment.

Reads `DecayInvestigation` rows, proposes `RuleAction` enforcements, and
applies them on admin confirmation. Provides the read-side helpers
(`is_rule_active`, `rule_size_multiplier`) that the signal engine consults
before persisting new signals.

Design properties:
  - **Reversible.** Every applied action snapshots the previous RuleControl.
  - **Rate-limited.** Hard caps per action type per day.
  - **Safe-by-default.** Proposals require explicit admin confirmation; the
    `actuator_mode_live` PlatformComponent gates whether `apply_action` even
    runs (off = shadow mode = preview-only).
  - **Auto-expiring.** Proposals not acted on within 7 days expire.
  - **Time-bounded enforcement.** Pauses default to 30 days; the read-side
    helpers honour `paused_until` so old pauses self-clear.

Public API:
  is_rule_active(rule_name)       -> bool
  rule_size_multiplier(rule_name) -> float

  propose_actions_from_decay()    -> int (count of new proposals)
  apply_action(action_id, user)   -> RuleAction
  rollback_action(action_id, user)-> RuleAction
  reject_action(action_id, user)  -> RuleAction
  expire_stale_proposals()        -> int
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# How long a `pause_rule` lasts before auto-reactivating.
PAUSE_DURATION_DAYS = 30

# Reduce-size weight multiplier applied when action="reduce_size".
REDUCED_WEIGHT = 0.5

# Hard daily caps so a misfiring actuator can't cripple the system.
MAX_PAUSES_PER_DAY = 3
MAX_REDUCTIONS_PER_DAY = 5

# Auto-expire proposals not acted on within this many days.
PROPOSAL_TTL_DAYS = 7


# ── Read-side helpers (consulted by signal engine + sizing) ─────────────────

def _control_for(rule_name: str):
    from signals.models import RuleControl
    return RuleControl.objects.filter(rule_name=rule_name).first()


def is_rule_active(rule_name: str) -> bool:
    """Whether new signals should be persisted for this rule. Default True."""
    if not rule_name:
        return True
    ctrl = _control_for(rule_name)
    if ctrl is None:
        return True
    return ctrl.is_effectively_active()


def rule_size_multiplier(rule_name: str) -> float:
    """Multiplicative scaling for sizing/score.

    Composes three independent lanes:
      - admin (Phase 5)      : `weight_multiplier`, honoured only when status=reduced
      - allocator (Phase 7)  : `allocator_weight`, math-driven
      - promotion (Phase 8)  : factor based on `promotion_stage`
                                research/paper → 0 (no live), live_small → 0.25, live_full → 1.0

    Effective = admin × allocator × promotion. A rule in PAPER stage returns
    0 regardless of allocator/admin lanes — paper-stage rules don't trade live.
    """
    if not rule_name:
        return 1.0
    ctrl = _control_for(rule_name)
    if ctrl is None:
        return 1.0
    admin_w = float(ctrl.weight_multiplier or 1.0) if ctrl.status == "reduced" else 1.0
    alloc_w = float(ctrl.allocator_weight or 1.0)
    # Phase-8 promotion lane.
    from signals.promotion_pipeline import SIZE_FACTORS
    promo_w = SIZE_FACTORS.get(ctrl.promotion_stage, 1.0)
    return admin_w * alloc_w * promo_w


# ── Mode gate ───────────────────────────────────────────────────────────────

def is_live_mode() -> bool:
    """True iff the actuator is in live mode (admin can apply). Default False."""
    from core.platform_control import is_component_enabled
    return is_component_enabled("actuator_mode_live")


# ── Rate limits ─────────────────────────────────────────────────────────────

def _daily_count(action: str) -> int:
    """Number of *applied* actions of this type in the last 24h."""
    from signals.models import RuleAction
    since = timezone.now() - timedelta(hours=24)
    return RuleAction.objects.filter(
        action=action, state="applied", applied_at__gte=since,
    ).count()


def _daily_cap(action: str) -> int:
    return {
        "pause_rule": MAX_PAUSES_PER_DAY,
        "reduce_size": MAX_REDUCTIONS_PER_DAY,
    }.get(action, 999)


# ── Proposal generation ─────────────────────────────────────────────────────

def propose_actions_from_decay(lookback_days: int = 1) -> int:
    """Read recent DecayInvestigations; create RuleAction proposals.

    Idempotent at the (investigation_id, action) granularity — the same
    investigation never produces two proposals.
    """
    from ai_agents.models import DecayInvestigation
    from signals.models import RuleAction

    cutoff = timezone.now() - timedelta(days=lookback_days)
    investigations = DecayInvestigation.objects.filter(created_at__gte=cutoff)

    n_created = 0
    for inv in investigations:
        action = inv.recommended_action or "monitor"

        # Skip purely informational actions — they don't enforce anything.
        if action in ("monitor", "investigate_data", "retune_params"):
            continue

        already = RuleAction.objects.filter(
            source_investigation=inv, action=action,
        ).exists()
        if already:
            continue

        rationale = (
            f"Auto-proposed from decay investigation #{inv.id}. "
            f"Recent expectancy {inv.recent_expectancy} vs baseline "
            f"{inv.baseline_expectancy} (n_recent={inv.recent_n}, "
            f"n_baseline={inv.baseline_n}). Hypothesis: {inv.hypothesis[:300]}"
        )

        rule_action = RuleAction.objects.create(
            rule_name=inv.rule_name,
            action=action,
            state=RuleAction.STATE_PROPOSED,
            source_investigation=inv,
            rationale=rationale,
        )

        # Phase-6 calibration: log a 30d prediction so we can grade the
        # decay investigator's reliability over time.
        try:
            from ai_agents.calibration import log_decay_prediction
            log_decay_prediction(
                agent="decay_investigator",
                rule_action=rule_action,
                predicted_continues=True,  # the agent is staking a claim that decay continues
                confidence=0.6,
            )
        except Exception as e:
            logger.warning("[actuator] could not log decay prediction: %s", e)

        n_created += 1

    return n_created


# ── Apply / rollback / reject ───────────────────────────────────────────────

class ActuatorError(Exception):
    """Raised when an action cannot be applied (e.g., rate limit, mode off)."""


@transaction.atomic
def apply_action(action_id: int, user) -> "RuleAction":
    """Apply a proposed action. Snapshots the previous RuleControl state for rollback."""
    from signals.models import RuleAction, RuleControl

    if not is_live_mode():
        raise ActuatorError("Actuator is in shadow mode — apply is disabled.")

    action = RuleAction.objects.select_for_update().get(id=action_id)
    if action.state != RuleAction.STATE_PROPOSED:
        raise ActuatorError(f"Action #{action_id} is in state {action.state} — cannot apply.")

    cap = _daily_cap(action.action)
    if _daily_count(action.action) >= cap:
        raise ActuatorError(
            f"Daily cap reached for {action.action} ({cap}/day). "
            f"Try again later or raise the cap."
        )

    ctrl, _ = RuleControl.objects.select_for_update().get_or_create(
        rule_name=action.rule_name,
        defaults={"status": RuleControl.STATUS_ACTIVE, "weight_multiplier": 1.0},
    )

    # Snapshot before mutating
    action.previous_status = ctrl.status
    action.previous_weight = ctrl.weight_multiplier
    action.previous_paused_until = ctrl.paused_until

    now = timezone.now()
    if action.action == RuleAction.ACTION_PAUSE:
        ctrl.status = RuleControl.STATUS_PAUSED
        ctrl.weight_multiplier = 0.0
        ctrl.paused_until = now + timedelta(days=PAUSE_DURATION_DAYS)
        ctrl.notes = f"Paused by RuleAction #{action.id} on {now:%Y-%m-%d}"
    elif action.action == RuleAction.ACTION_REDUCE:
        ctrl.status = RuleControl.STATUS_REDUCED
        ctrl.weight_multiplier = REDUCED_WEIGHT
        ctrl.paused_until = None
        ctrl.notes = f"Size reduced by RuleAction #{action.id} on {now:%Y-%m-%d}"
    else:
        # Defensive — proposals shouldn't be created for non-enforcing actions.
        raise ActuatorError(f"Action {action.action} is informational; nothing to apply.")

    ctrl.save()

    action.state = RuleAction.STATE_APPLIED
    action.applied_at = now
    action.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    action.save()

    logger.info(
        "[actuator] applied %s on rule=%s by user=%s",
        action.action, action.rule_name, user,
    )
    return action


@transaction.atomic
def rollback_action(action_id: int, user) -> "RuleAction":
    """Restore the RuleControl snapshot taken at apply-time."""
    from signals.models import RuleAction, RuleControl

    action = RuleAction.objects.select_for_update().get(id=action_id)
    if action.state != RuleAction.STATE_APPLIED:
        raise ActuatorError(f"Action #{action_id} is in state {action.state} — cannot rollback.")

    ctrl, _ = RuleControl.objects.select_for_update().get_or_create(
        rule_name=action.rule_name,
        defaults={"status": RuleControl.STATUS_ACTIVE, "weight_multiplier": 1.0},
    )
    ctrl.status = action.previous_status or RuleControl.STATUS_ACTIVE
    ctrl.weight_multiplier = action.previous_weight if action.previous_weight is not None else 1.0
    ctrl.paused_until = action.previous_paused_until
    ctrl.notes = (ctrl.notes or "") + f"\nRolled back by action #{action.id}"
    ctrl.save()

    action.state = RuleAction.STATE_ROLLED_BACK
    action.rolled_back_at = timezone.now()
    action.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    action.save()

    logger.info("[actuator] rolled back %s on rule=%s", action.action, action.rule_name)
    return action


def reject_action(action_id: int, user) -> "RuleAction":
    """Reject a proposed action without applying it."""
    from signals.models import RuleAction
    action = RuleAction.objects.get(id=action_id)
    if action.state != RuleAction.STATE_PROPOSED:
        raise ActuatorError(f"Action #{action_id} is in state {action.state} — cannot reject.")
    action.state = RuleAction.STATE_REJECTED
    action.rejected_at = timezone.now()
    action.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    action.save()
    return action


def expire_stale_proposals() -> int:
    """Mark proposals older than PROPOSAL_TTL_DAYS as expired. Idempotent."""
    from signals.models import RuleAction
    cutoff = timezone.now() - timedelta(days=PROPOSAL_TTL_DAYS)
    qs = RuleAction.objects.filter(state=RuleAction.STATE_PROPOSED, proposed_at__lt=cutoff)
    n = qs.count()
    qs.update(state=RuleAction.STATE_EXPIRED)
    return n
