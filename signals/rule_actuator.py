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
  propose_from_brain(report, rule_name, action, user) -> RuleAction
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


def stage_policy(rule_name: str) -> dict:
    """What the promotion stage permits, as a VENUE decision.

    The stage lane used to be a size multiplier, and that produced an
    absurdity: SIZE_FACTORS maps both `research` and `paper` to 0.0, the bot
    applied it with `qty *= rule_size_multiplier(...)`, and a qty of 0 exits
    the entry path. So a rule at PAPER stage could not take the paper trade
    the ladder was asking it for, and the evidence required to promote out of
    paper could never be produced. The ladder was closed on itself.

    A stage is not a size. It is a statement about which venue a rule has
    earned:

        research    no orders at all — the rule is being watched, not traded
        paper       trades at full nominal size, forced onto the paper venue
        live_small  live, quarter size
        live_full   live, full size

    A rule with no RuleControl row is treated as PAPER: it may trade, but
    only on the paper venue, whatever the config's mode says. That is fail
    SAFE rather than fail closed. The old default was 1.0 — an unregistered,
    never-evaluated rule placed a live order at full size on its first ever
    firing. Failing all the way closed would be safe too, but it walls off
    the paper evidence the ladder needs to promote anything, so a brand-new
    rule would never be able to earn its way up.

    The distinction that matters is preserved: no rule reaches real money
    without an explicit promotion someone made.

    Returns {stage, may_trade, force_paper, live_size_factor, reason}.
    """
    from signals.promotion_pipeline import STAGE_ORDER

    ctrl = _control_for(rule_name) if rule_name else None
    stage = getattr(ctrl, "promotion_stage", None)
    if ctrl is None or stage not in STAGE_ORDER:
        return {"stage": "paper", "may_trade": True, "force_paper": True,
                "live_size_factor": 0.0,
                "reason": (f"rule {rule_name!r} has no promotion record — "
                           "paper venue only until it is promoted")}
    if stage == "research":
        return {"stage": stage, "may_trade": False, "force_paper": True,
                "live_size_factor": 0.0,
                "reason": "research stage — signals only, no orders"}
    if stage == "paper":
        return {"stage": stage, "may_trade": True, "force_paper": True,
                "live_size_factor": 0.0,
                "reason": "paper stage — full size on the paper venue"}
    if stage == "live_small":
        return {"stage": stage, "may_trade": True, "force_paper": False,
                "live_size_factor": 0.25, "reason": "live_small — quarter size"}
    return {"stage": stage, "may_trade": True, "force_paper": False,
            "live_size_factor": 1.0, "reason": "live_full — full size"}


def admin_allocator_multiplier(rule_name: str) -> float:
    """The admin and allocator lanes only, with the promotion lane removed.

    `rule_size_multiplier` folds all three together, which is right for
    scoring a signal and wrong for sizing a trade — see `stage_policy`.
    Unknown rules return 1.0 here because the stage lane is what fails closed.
    """
    if not rule_name:
        return 1.0
    ctrl = _control_for(rule_name)
    if ctrl is None:
        return 1.0
    admin_w = float(ctrl.weight_multiplier or 1.0) if ctrl.status == "reduced" else 1.0
    alloc_w = float(ctrl.allocator_weight or 1.0)
    return admin_w * alloc_w


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


# The brain's overlay only ever votes for these two. Anything else — monitor,
# investigate_data, retune_params — enforces nothing, and `apply_action`
# would refuse it anyway; refusing here keeps the HQ queue free of rows an
# admin can neither apply nor meaningfully reject.
BRAIN_PROPOSABLE_ACTIONS = ("pause_rule", "reduce_size")


def governed_rule_names() -> set:
    """Rule names the actuator can really enforce.

    The overlay's keys are LLM-typed. A lever for a rule no RuleControl,
    signal or trade has ever heard of enforces nothing — it just files a
    ticket at HQ that can never be applied to anything.
    """
    from signals.models import RuleControl, Signal
    names = set()
    try:
        names |= set(RuleControl.objects.values_list("rule_name", flat=True))
        names |= set(Signal.objects.exclude(rule_name="")
                     .values_list("rule_name", flat=True).distinct())
    except Exception:  # noqa: BLE001 — an unreadable table gates nothing
        return names
    try:
        from bot_program.models import AssetBotTrade
        names |= set(AssetBotTrade.objects.exclude(rule_name="")
                     .values_list("rule_name", flat=True).distinct())
    except Exception:  # noqa: BLE001
        pass
    try:
        # The manual lane reads the brain's advisory, never RuleControl —
        # a control row for it would enforce nothing at all.
        from bot_program.manual_trade import MANUAL_RULE
        names.discard(MANUAL_RULE)
    except Exception:  # noqa: BLE001
        pass
    names.discard("")
    return names


def propose_from_brain(report, rule_name: str, action: str, user=None):
    """One press on the brain page becomes one RuleAction proposal.

    The operator cannot move the live account from here and the platform
    will not pretend to: this queues a proposal that an admin still has to
    apply at HQ, under the same live-mode gate and daily caps as every
    decay proposal. Idempotent per (report, rule_name, action) — the same
    concern pressed twice returns the row it already made, in whatever
    state it has reached since, rather than a second one for the admin to
    wade through.
    """
    from signals.models import RuleAction

    if action not in BRAIN_PROPOSABLE_ACTIONS:
        raise ActuatorError(
            f"Action {action!r} is informational; the brain can only propose "
            f"{' or '.join(BRAIN_PROPOSABLE_ACTIONS)}.")
    rule_name = (rule_name or "").strip()
    if not rule_name:
        raise ActuatorError("A proposal needs a rule name.")
    if report is None:
        raise ActuatorError("A brain proposal needs the report it came from.")
    governed = governed_rule_names()
    if governed and rule_name not in governed:
        raise ActuatorError(
            f"'{rule_name}' is not a rule this platform governs — the "
            f"overlay named it, but nothing here would enforce a pause.")

    # STANDING rows only: a proposal the admin rejected is a decision,
    # and the brain re-raising the same concern tomorrow deserves a fresh
    # ticket rather than the corpse of the old one.
    standing = (RuleAction.STATE_PROPOSED, RuleAction.STATE_APPLIED)
    existing = RuleAction.objects.filter(
        source_brain_report=report, rule_name=rule_name, action=action,
        state__in=standing,
    ).order_by("-proposed_at").first()
    if existing is not None:
        return existing

    overlay = report.rule_status_overlay or {}
    status = overlay.get(rule_name) or "unlisted"
    # The overlay names the rule; the concern text explains it. Carry the
    # matching concern into the rationale so the admin at HQ reads the
    # brain's reason, not just its verdict.
    concern_text = ""
    for c in (report.top_concerns or []):
        if not isinstance(c, dict):
            continue
        blob = f"{c.get('ref', '')} {c.get('text', '')}"
        if rule_name in blob:
            concern_text = str(c.get("text") or "")
            break
    rationale = (f"Proposed from brain synthesis #{report.id} "
                 f"({report.created_at:%Y-%m-%d %H:%M} UTC): overlay {status}")
    if concern_text:
        rationale += f" — {concern_text[:400]}"
    else:
        rationale += " — no matching concern text in the synthesis"
    if user is not None and getattr(user, "is_authenticated", False):
        rationale += f" (pressed by {user.get_username()})"

    # Two presses land in two requests; a filter-then-create between them
    # queues the same concern twice. The DB decides.
    rule_action = RuleAction.objects.create(
        rule_name=rule_name,
        action=action,
        state=RuleAction.STATE_PROPOSED,
        source_brain_report=report,
        rationale=rationale,
    )
    logger.info("[actuator] brain proposal %s on rule=%s from report #%s by %s",
                action, rule_name, report.id, user)
    return rule_action


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
