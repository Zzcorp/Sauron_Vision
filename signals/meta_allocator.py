"""Phase-7 multi-strategy meta-allocator (non-falling design).

Allocates capital across active signal rules based on Phase-1 realized_r data.
Designed to *not* fail badly when data is sparse, distributions shift, or
correlations break — by ensembling three methods and blending them by data
quality.

Architecture
------------

Three allocators, each producing a {rule_name: weight} dict that sums to 1:

  1. UNIFORM           — 1/N. Always available, robust to anything.
  2. INVERSE_VOL       — proportional to 1/std(realized_r). Penalises noisy rules.
  3. EXPECTANCY        — proportional to max(expectancy_r, 0). Penalises losers.

Final target = blend of the three, with blend factors driven by the *worst*
sample size across rules. Sparse data → heavy uniform. Mature data → mix in
the data-driven methods.

Robustness layers (the "non-falling" design)
-------------------------------------------

  * Per-rule sample floor — rules with n<MIN_RULE_N revert to uniform weight,
    isolating noisy rules from poisoning the math.
  * Hard caps — every rule's final weight clipped to [MIN_RULE_WEIGHT, MAX_RULE_WEIGHT].
  * Renormalisation after caps — sum to 1 even after clipping.
  * Smoothing — apply only SMOOTHING_ALPHA of the delta between current and
    target each rebalance, so a single noisy run can't flip allocations.
  * Shadow mode by default — proposals don't touch RuleControl until admin
    promotes via `apply_allocation` AND `meta_allocator_mode_live` is on.
  * Snapshot per apply — `MetaAllocation.previous_weights` lets rollback
    restore exactly.
  * Decoupled from actuator — writes to `RuleControl.allocator_weight`, never
    touches `weight_multiplier` (admin's lane). Effective sizing = product of
    both, computed in `rule_actuator.rule_size_multiplier`.
  * Skips paused/reduced rules — admin's manual decisions take precedence.

Public API
----------

    propose_allocation(lookback_days=180) -> MetaAllocation
        Compute target weights, save in shadow state. Idempotent in the sense
        that repeated calls just create more shadow rows; existing ones are
        untouched.

    apply_allocation(allocation_id, user) -> MetaAllocation
        Promote a shadow allocation to applied. Snapshots prior weights and
        writes new `RuleControl.allocator_weight` values for active rules.

    rollback_allocation(allocation_id, user) -> MetaAllocation
        Restore the snapshot.

    reject_allocation(allocation_id, user) -> MetaAllocation
        Mark a shadow allocation as rejected without applying.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Minimum closed signals per rule to include it in data-driven methods.
# Below this, the rule contributes only to uniform weight.
MIN_RULE_N = 5

# Sample-tier thresholds (worst rule's n determines the tier; conservative).
TIER1_MIN_N = 30      # mature data — heavy data-driven
TIER2_MIN_N = 10      # medium data — balanced

# Blend factors per tier: (uniform, inverse_vol, expectancy). Sum to 1.
BLEND_TIER1 = (0.30, 0.30, 0.40)
BLEND_TIER2 = (0.50, 0.30, 0.20)
BLEND_TIER3 = (1.00, 0.00, 0.00)  # not enough data — pure uniform

# Hard caps.
MAX_RULE_WEIGHT = 0.30   # no rule above 30%
MIN_RULE_WEIGHT = 0.01   # no rule fully zeroed (avoid noise-induced kill)

# Smoothing: apply only this fraction of (target - current) per rebalance.
SMOOTHING_ALPHA = 0.30

# Convert {rule: target_weight} (sums to 1) into a per-rule allocator multiplier
# centred at 1.0 by dividing by uniform=1/N. Cap to keep values usable.
ALLOCATOR_MULTIPLIER_MIN = 0.10
ALLOCATOR_MULTIPLIER_MAX = 3.00


# ── Data collection ─────────────────────────────────────────────────────────

def _collect_rule_stats(lookback_days: int) -> dict:
    """Per-rule stats from Phase-1 realized_r data, restricted to active rules.

    Returns: {rule_name: {"n": int, "mean": float, "std": float, "rs": list}}
    """
    from signals.models import Signal, RuleControl

    cutoff = timezone.now() - timedelta(days=lookback_days)
    qs = (
        Signal.objects.filter(
            is_active=False, realized_r__isnull=False,
            expired_at__gte=cutoff,
        )
        .exclude(rule_name="")
        .values_list("rule_name", "realized_r")
    )
    by_rule: dict[str, list[float]] = {}
    for rn, r in qs:
        by_rule.setdefault(rn, []).append(float(r))

    # Filter to active rules only — paused/reduced rules are admin-controlled.
    active_rules = set(
        RuleControl.objects.filter(status=RuleControl.STATUS_ACTIVE)
        .values_list("rule_name", flat=True)
    )

    stats = {}
    for rn, rs in by_rule.items():
        if active_rules and rn not in active_rules:
            # Rule has a control entry that's not active. Skip.
            continue
        if not rs:
            continue
        n = len(rs)
        mean = statistics.fmean(rs)
        std = statistics.pstdev(rs) if n >= 2 else 0.0
        stats[rn] = {"n": n, "mean": mean, "std": std, "rs": rs}
    return stats


# ── Three allocator methods ─────────────────────────────────────────────────

def _uniform_weights(rule_names: list[str]) -> dict[str, float]:
    if not rule_names:
        return {}
    w = 1.0 / len(rule_names)
    return {r: w for r in rule_names}


def _inverse_vol_weights(stats: dict) -> dict[str, float]:
    """Weight ∝ 1 / std(realized_r). Adds a tiny epsilon to avoid div-by-zero."""
    if not stats:
        return {}
    EPS = 1e-3
    raw = {r: 1.0 / max(s["std"], EPS) for r, s in stats.items()}
    total = sum(raw.values())
    if total <= 0:
        return _uniform_weights(list(stats.keys()))
    return {r: v / total for r, v in raw.items()}


def _expectancy_weights(stats: dict) -> dict[str, float]:
    """Weight ∝ max(expectancy_r, 0). Loser rules get zero from this method."""
    if not stats:
        return {}
    raw = {r: max(s["mean"], 0.0) for r, s in stats.items()}
    total = sum(raw.values())
    if total <= 0:
        # All rules losing — fall back to uniform from this method's perspective.
        return _uniform_weights(list(stats.keys()))
    return {r: v / total for r, v in raw.items()}


# ── Ensemble blend ──────────────────────────────────────────────────────────

def _choose_tier(stats: dict) -> tuple[str, tuple[float, float, float]]:
    """Pick blend factors based on the *minimum* n across rules (conservative)."""
    if not stats:
        return "tier3", BLEND_TIER3
    min_n = min(s["n"] for s in stats.values())
    if min_n >= TIER1_MIN_N:
        return "tier1", BLEND_TIER1
    if min_n >= TIER2_MIN_N:
        return "tier2", BLEND_TIER2
    return "tier3", BLEND_TIER3


def _blend(uniform: dict, inv_vol: dict, expect: dict,
           factors: tuple[float, float, float]) -> dict[str, float]:
    """Linear blend of three weight vectors. Inputs each sum to 1."""
    fu, fi, fe = factors
    rules = set(uniform) | set(inv_vol) | set(expect)
    out = {}
    for r in rules:
        out[r] = (
            fu * uniform.get(r, 0.0)
            + fi * inv_vol.get(r, 0.0)
            + fe * expect.get(r, 0.0)
        )
    return out


def _apply_caps(weights: dict[str, float]) -> dict[str, float]:
    """Cap each weight to [min_w, max_w] using water-filling, so the result
    is exactly normalised AND no rule violates the caps.

    Naive clip+renorm oscillates (clipped rules pop back above cap on
    renormalisation). Water-filling fixes capped rules at the cap and
    distributes the remaining mass proportionally among the un-capped rules.

    Caps are N-aware so they don't degenerate for small portfolios:
      - max_w = max(MAX_RULE_WEIGHT, 2/N) — a rule can always be ≥2× uniform.
      - min_w = min(MIN_RULE_WEIGHT, 1/(2*N)) — never less than half uniform.
    """
    if not weights:
        return {}
    n = len(weights)
    max_w = max(MAX_RULE_WEIGHT, 2.0 / n)
    min_w = min(MIN_RULE_WEIGHT, 1.0 / (2 * n))

    fixed_max: set[str] = set()
    fixed_min: set[str] = set()

    for _ in range(n + 2):
        free_rules = [r for r in weights if r not in fixed_max and r not in fixed_min]
        fixed_mass = max_w * len(fixed_max) + min_w * len(fixed_min)
        free_mass = 1.0 - fixed_mass
        if not free_rules or free_mass <= 0:
            break

        # Distribute free_mass among free rules in proportion to their input weight.
        proportions = {r: max(0.0, float(weights[r])) for r in free_rules}
        total = sum(proportions.values())
        if total <= 0:
            # All free rules have zero weight — share free_mass evenly.
            share = free_mass / len(free_rules)
            free_w = {r: share for r in free_rules}
        else:
            scale = free_mass / total
            free_w = {r: proportions[r] * scale for r in free_rules}

        new_max = {r for r, w in free_w.items() if w > max_w + 1e-9}
        new_min = {r for r, w in free_w.items() if w < min_w - 1e-9}

        if not new_max and not new_min:
            result = {r: max_w for r in fixed_max}
            result.update({r: min_w for r in fixed_min})
            result.update(free_w)
            return result

        fixed_max |= new_max
        fixed_min |= new_min

    # Fallback (should be unreachable for sane inputs).
    return _uniform_weights(list(weights.keys()))


def _to_allocator_multipliers(target_weights: dict[str, float]) -> dict[str, float]:
    """Convert {rule: w (sums to 1)} into {rule: multiplier centred at 1.0}.

    A rule getting exactly its uniform share (1/N) → multiplier 1.0.
    A rule getting double its uniform share → multiplier 2.0.
    Capped to [ALLOCATOR_MULTIPLIER_MIN, ALLOCATOR_MULTIPLIER_MAX].
    """
    if not target_weights:
        return {}
    n = len(target_weights)
    uniform = 1.0 / n
    out = {}
    for r, w in target_weights.items():
        m = w / uniform if uniform > 0 else 1.0
        out[r] = max(ALLOCATOR_MULTIPLIER_MIN, min(ALLOCATOR_MULTIPLIER_MAX, m))
    return out


def _smooth(current: dict[str, float], target: dict[str, float],
            alpha: float = SMOOTHING_ALPHA) -> dict[str, float]:
    """Move `current` toward `target` by `alpha` of the delta. New rules drop in immediately."""
    smoothed = {}
    for r, t in target.items():
        c = current.get(r, t)  # missing rule → no smoothing needed; use target
        smoothed[r] = c + alpha * (t - c)
    return smoothed


# ── Mode gate ───────────────────────────────────────────────────────────────

def is_live_mode() -> bool:
    """True iff the meta-allocator is in live mode (admin can apply)."""
    from core.platform_control import is_component_enabled
    return is_component_enabled("meta_allocator_mode_live")


# ── Errors ──────────────────────────────────────────────────────────────────

class AllocatorError(Exception):
    pass


# ── Public API ──────────────────────────────────────────────────────────────

def propose_allocation(lookback_days: int = 180) -> "MetaAllocation":
    """Compute ensemble target weights and persist as a shadow MetaAllocation.

    Always succeeds: returns an empty allocation row if no data exists.
    """
    from signals.models import MetaAllocation, RuleControl

    stats = _collect_rule_stats(lookback_days)
    rules = list(stats.keys())

    tier, factors = _choose_tier(stats)
    uniform = _uniform_weights(rules)
    inv_vol = _inverse_vol_weights(stats)
    expect = _expectancy_weights(stats)
    blended = _blend(uniform, inv_vol, expect, factors)

    # Per-rule sample floor: any rule with n < MIN_RULE_N gets pulled to
    # uniform weight specifically (preserves it in the active set without
    # letting noisy data drive its weight).
    if rules:
        u = 1.0 / len(rules)
        for r, s in stats.items():
            if s["n"] < MIN_RULE_N:
                blended[r] = u
        # Renormalise after the floor adjustment.
        total = sum(blended.values())
        if total > 0:
            blended = {r: w / total for r, w in blended.items()}

    target_with_caps = _apply_caps(blended)

    # Smooth from current allocator multipliers.
    current_multipliers = {
        rc.rule_name: rc.allocator_weight
        for rc in RuleControl.objects.filter(rule_name__in=rules)
    }
    target_multipliers = _to_allocator_multipliers(target_with_caps)
    smoothed_multipliers = _smooth(current_multipliers, target_multipliers)

    alloc = MetaAllocation.objects.create(
        state=MetaAllocation.STATE_SHADOW,
        lookback_days=lookback_days,
        sample_tier=tier,
        ensemble_blend={
            "uniform": factors[0], "inverse_vol": factors[1], "expectancy": factors[2],
        },
        per_method_weights={
            "uniform": uniform, "inverse_vol": inv_vol, "expectancy": expect,
        },
        target_weights={
            "weights": target_with_caps,
            "multipliers": smoothed_multipliers,
        },
        rules_considered=len(rules),
        rules_skipped=0,
        notes=f"Sample tier {tier}; {len(rules)} active rule(s) considered.",
    )
    logger.info("[allocator] proposed allocation #%s tier=%s rules=%d",
                alloc.id, tier, len(rules))
    return alloc


@transaction.atomic
def apply_allocation(allocation_id: int, user) -> "MetaAllocation":
    """Promote a shadow allocation. Snapshots previous allocator_weights for rollback."""
    from signals.models import MetaAllocation, RuleControl

    if not is_live_mode():
        raise AllocatorError("Meta-allocator is in shadow mode — apply is disabled.")

    alloc = MetaAllocation.objects.select_for_update().get(id=allocation_id)
    if alloc.state != MetaAllocation.STATE_SHADOW:
        raise AllocatorError(f"Allocation #{allocation_id} is in state {alloc.state} "
                             "— cannot apply.")

    multipliers = (alloc.target_weights or {}).get("multipliers") or {}

    previous = {}
    for rule_name, new_mult in multipliers.items():
        ctrl, _ = RuleControl.objects.select_for_update().get_or_create(
            rule_name=rule_name,
            defaults={"status": RuleControl.STATUS_ACTIVE,
                      "weight_multiplier": 1.0, "allocator_weight": 1.0},
        )
        # Only touch active rules — admin's pause/reduce decisions take precedence.
        if ctrl.status != RuleControl.STATUS_ACTIVE:
            continue
        previous[rule_name] = ctrl.allocator_weight
        ctrl.allocator_weight = float(new_mult)
        ctrl.save(update_fields=["allocator_weight", "updated_at"])

    alloc.previous_weights = previous
    alloc.state = MetaAllocation.STATE_APPLIED
    alloc.applied_at = timezone.now()
    alloc.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    alloc.save()
    logger.info("[allocator] applied allocation #%s — %d rule(s) updated",
                alloc.id, len(previous))
    return alloc


@transaction.atomic
def rollback_allocation(allocation_id: int, user) -> "MetaAllocation":
    """Restore the per-rule allocator_weight snapshot from when it was applied."""
    from signals.models import MetaAllocation, RuleControl

    alloc = MetaAllocation.objects.select_for_update().get(id=allocation_id)
    if alloc.state != MetaAllocation.STATE_APPLIED:
        raise AllocatorError(f"Allocation #{allocation_id} is in state {alloc.state} "
                             "— cannot rollback.")

    for rule_name, prev_w in (alloc.previous_weights or {}).items():
        ctrl = RuleControl.objects.filter(rule_name=rule_name).first()
        if ctrl is None:
            continue
        ctrl.allocator_weight = float(prev_w)
        ctrl.save(update_fields=["allocator_weight", "updated_at"])

    alloc.state = MetaAllocation.STATE_ROLLED_BACK
    alloc.rolled_back_at = timezone.now()
    alloc.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    alloc.save()
    logger.info("[allocator] rolled back allocation #%s", alloc.id)
    return alloc


def reject_allocation(allocation_id: int, user) -> "MetaAllocation":
    from signals.models import MetaAllocation
    alloc = MetaAllocation.objects.get(id=allocation_id)
    if alloc.state != MetaAllocation.STATE_SHADOW:
        raise AllocatorError(f"Allocation #{allocation_id} is in state {alloc.state} "
                             "— cannot reject.")
    alloc.state = MetaAllocation.STATE_REJECTED
    alloc.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    alloc.save()
    return alloc
