"""Phase-9 strategy evolution — generate new rule candidates by mutating
the parameters of existing rules.

Sauron's first generative layer. Architecture:

  1. Rules opt in by registering a parameter schema with `register_schema()`.
     Hand-coded rules without a schema are NOT evolved — Phase 9 is dormant
     for them, by design.
  2. The proposer scans for *decaying* rules (per Phase-1) and generates N
     candidate mutations per rule. Each mutation perturbs 1–3 parameters
     within the declared bounds.
  3. Each mutation is scored by a pluggable scorer. Default: a heuristic
     bootstrap that samples from the parent's realized_r distribution with
     a small drift proportional to the parameter delta. This is HONEST
     about being a placeholder — the real scorer requires the rule to be
     parameter-aware so a backtest can actually run with the new params.
  4. Top-K mutants per parent are saved as `RuleMutation` rows in PROPOSED
     state. Admin reviews each.
  5. On apply, a NEW RuleControl is created with `rule_name` =
     `{parent}_evolved_v{N}`, parameters set, promotion_stage=RESEARCH.
     Phase 8 then walks the fork through the staged trial-by-fire.
  6. Original parent rule is NEVER mutated. May the better one win on the
     promotion ladder.

Schema format
-------------

A parameter schema is a dict of {param_name: spec} where spec has:
    type:    "float" | "int"
    min:     numeric lower bound
    max:     numeric upper bound
    default: starting value (used if RuleControl.parameters is empty)
    step:    rounding increment (optional)

Public API
----------

    register_schema(rule_name, schema)
    has_schema(rule_name) -> bool
    current_params(rule_name) -> dict
    generate_mutant(rule_name, n_params_to_mutate=None, rng=None) -> dict
    score_mutant_heuristic(rule_name, mutant_params) -> float
    propose_evolution(rule_name, n_mutants=20, top_k=3) -> list[RuleMutation]
    propose_for_decaying_rules() -> dict  (Celery entry point)
    apply_evolution(mutation_id, user) -> RuleControl  (the new fork)
    reject_evolution(mutation_id, user) -> RuleMutation
"""
from __future__ import annotations

import logging
import random
import statistics
from datetime import timedelta
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Standard deviation of the mutation, as a fraction of (max - min).
MUTATION_STD_FRAC = 0.15

# Default proposal sweep config.
DEFAULT_N_MUTANTS = 20
DEFAULT_TOP_K = 3
MAX_PARAMS_TO_MUTATE = 3
MIN_PARAMS_TO_MUTATE = 1

# Heuristic scorer drift: per-unit-of-normalized-param-delta, the mutant's
# expectancy is shifted by a Gaussian centered on 0 with this std. Smaller =
# less optimistic about the mutation; larger = more variance in the score.
HEURISTIC_DRIFT_STD = 0.30  # in R-units

# Lookback for parent expectancy (used as the heuristic score's mean).
PARENT_LOOKBACK_DAYS = 90


# ── Schema registry (in-process, populated by `register_schema` calls at
# import time from rule definitions; survives only while the process lives) ─

SCHEMA_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {}


def register_schema(rule_name: str, schema: dict[str, dict[str, Any]]) -> None:
    """Declare a rule's parameter schema. Idempotent — re-registering overrides."""
    _validate_schema(schema)
    SCHEMA_REGISTRY[rule_name] = schema


def _ensure_rules_registered() -> None:
    """Populate the registries before any proposal work.

    Registrations live in `signals.evolution_rules`; nothing guarantees a
    worker imported it before proposing. For its first months this layer
    was dormant for exactly that class of reason. And a bare import is not
    enough: import side effects fire once per process, so a registry
    cleared afterwards (test isolation does this) stayed empty forever —
    hence the explicit, idempotent `register()` call."""
    try:
        import signals.evolution_rules as _rules
        _rules.register()
    except Exception as e:  # noqa: BLE001
        logger.warning("[evolution] rule registrations failed to load: %s", e)


def has_schema(rule_name: str) -> bool:
    return rule_name in SCHEMA_REGISTRY


def _validate_schema(schema: dict) -> None:
    for name, spec in schema.items():
        if not isinstance(spec, dict):
            raise ValueError(f"schema[{name!r}] must be a dict")
        for required in ("type", "min", "max"):
            if required not in spec:
                raise ValueError(f"schema[{name!r}] missing required key {required!r}")
        if spec["type"] not in ("float", "int"):
            raise ValueError(f"schema[{name!r}].type must be 'float' or 'int'")
        if spec["min"] >= spec["max"]:
            raise ValueError(f"schema[{name!r}].min must be < max")


# ── Current parameters ─────────────────────────────────────────────────────

def current_params(rule_name: str) -> dict:
    """Return the rule's current parameter dict — from RuleControl.parameters
    if set, else schema defaults, else empty."""
    from signals.models import RuleControl
    ctrl = RuleControl.objects.filter(rule_name=rule_name).first()
    if ctrl and ctrl.parameters:
        return dict(ctrl.parameters)
    schema = SCHEMA_REGISTRY.get(rule_name, {})
    return {name: spec.get("default", (spec["min"] + spec["max"]) / 2)
            for name, spec in schema.items()}


# ── Mutation generation ────────────────────────────────────────────────────

def _coerce(value, spec) -> Any:
    """Clamp + round per the spec's type and step."""
    value = max(spec["min"], min(spec["max"], value))
    if spec.get("type") == "int":
        return int(round(value))
    step = spec.get("step")
    if step:
        value = round(value / step) * step
    return float(round(value, 6))


def generate_mutant(rule_name: str, *,
                    n_params_to_mutate: Optional[int] = None,
                    rng: Optional[random.Random] = None) -> dict:
    """Generate one candidate parameter dict by perturbing a random subset
    of the rule's parameters. Mutated values are clamped to the schema bounds."""
    if not has_schema(rule_name):
        raise ValueError(f"No schema registered for rule '{rule_name}'")
    rng = rng or random.Random()
    schema = SCHEMA_REGISTRY[rule_name]
    params = current_params(rule_name)

    # How many params to mutate (random subset, at least one).
    n_total = len(schema)
    if n_total == 0:
        return params
    if n_params_to_mutate is None:
        upper = min(MAX_PARAMS_TO_MUTATE, n_total)
        n_params_to_mutate = rng.randint(MIN_PARAMS_TO_MUTATE, upper)
    n_params_to_mutate = max(1, min(n_params_to_mutate, n_total))

    targets = rng.sample(list(schema.keys()), n_params_to_mutate)
    mutated = dict(params)
    for name in targets:
        spec = schema[name]
        current_val = mutated.get(name, spec.get("default", (spec["min"] + spec["max"]) / 2))
        std = (spec["max"] - spec["min"]) * MUTATION_STD_FRAC
        new_val = rng.gauss(current_val, std)
        mutated[name] = _coerce(new_val, spec)
    return mutated


def _params_changed(parent: dict, mutant: dict) -> list[str]:
    return [k for k in mutant if mutant.get(k) != parent.get(k)]


# ── Scoring (heuristic stub — pluggable) ────────────────────────────────────

def _parent_expectancy(rule_name: str, lookback_days: int = PARENT_LOOKBACK_DAYS) -> Optional[float]:
    from signals.models import Signal
    from django.db.models import Avg
    cutoff = timezone.now() - timedelta(days=lookback_days)
    qs = Signal.objects.filter(
        rule_name=rule_name, is_active=False,
        expired_at__gte=cutoff, realized_r__isnull=False,
    ).exclude(outcome="")
    if qs.count() == 0:
        return None
    avg = qs.aggregate(avg=Avg("realized_r"))["avg"]
    return float(avg) if avg is not None else None


def _normalized_param_delta(rule_name: str, mutant: dict) -> float:
    """Sum of |mutant - parent| / (max - min) across changed params."""
    schema = SCHEMA_REGISTRY.get(rule_name, {})
    parent = current_params(rule_name)
    total = 0.0
    for name, spec in schema.items():
        rng_size = max(spec["max"] - spec["min"], 1e-9)
        delta = abs(mutant.get(name, parent.get(name, 0)) - parent.get(name, 0))
        total += delta / rng_size
    return total


def score_mutant_heuristic(rule_name: str, mutant_params: dict, *,
                           rng: Optional[random.Random] = None) -> float:
    """Heuristic score — placeholder until rules are parameter-aware.

    Returns parent_expectancy + Gaussian(0, drift_std × delta_norm). The bigger
    the parameter change, the more uncertain (and potentially higher OR lower)
    the score. Honest about being a stand-in for a real backtest.
    """
    rng = rng or random.Random()
    parent_exp = _parent_expectancy(rule_name)
    if parent_exp is None:
        # No data → can't score. Caller decides how to handle.
        return 0.0
    delta = _normalized_param_delta(rule_name, mutant_params)
    drift = rng.gauss(0.0, HEURISTIC_DRIFT_STD * max(0.5, delta))
    return float(round(parent_exp + drift, 4))


def score_mutant(rule_name: str, mutant_params: dict, parent_params: dict,
                 *, rng: Optional[random.Random] = None,
                 wf_context: Optional[dict] = None) -> dict:
    """Phase 9.5: dispatch to the best available scorer for this rule.

    Picks walk-forward backtest scoring when an evaluator is registered for
    the rule (via `evolution_backtest.register_evaluator`); otherwise falls
    back to the heuristic placeholder. `wf_context` (from
    `walkforward_context`) freezes the windows and parent baselines so a
    sweep scores every mutant against the same data instead of recomputing
    the parent per mutant on a drifting clock.

    Returns dict: {method, score, details}.
    """
    from signals.evolution_backtest import has_evaluator, score_mutant_walkforward
    if has_evaluator(rule_name):
        try:
            wf = score_mutant_walkforward(rule_name, mutant_params,
                                          parent_params, context=wf_context)
            return {
                "method": wf["method"],
                "score": wf["score"],
                "details": {
                    "train_mutant": wf["train_mutant"],
                    "test_mutant": wf["test_mutant"],
                    "train_parent": wf["train_parent"],
                    "test_parent": wf["test_parent"],
                    "train_delta": wf["train_delta"],
                    "test_delta": wf["test_delta"],
                    "worst_delta": wf["worst_delta"],
                    "sufficient_data": wf["sufficient_data"],
                    "notes": wf["notes"],
                },
            }
        except Exception as e:
            logger.warning(
                "[evolution] walk_forward scorer failed for %s: %s — falling back to heuristic",
                rule_name, e,
            )
            # Fall through.
    score = score_mutant_heuristic(rule_name, mutant_params, rng=rng)
    return {"method": "heuristic", "score": score, "details": {}}


# ── Proposing & applying ───────────────────────────────────────────────────

class EvolutionError(Exception):
    pass


# How long an undecided proposal batch may block re-proposing. Every
# sibling proposal pipeline expires (RuleAction 7d, brain proposals 14d,
# DiscoveredSetup TTL); without this, one ignored batch silenced evolution
# for that rule indefinitely — and its walk-forward scores, frozen at
# proposal time, only grew staler.
PROPOSAL_TTL_DAYS = 14


def expire_stale_mutations() -> int:
    """Move PROPOSED RuleMutations past their TTL to EXPIRED. Returns the
    count. After an expiry, the next sweep may ask the question again with
    freshly scored candidates."""
    from signals.models import RuleMutation
    cutoff = timezone.now() - timedelta(days=PROPOSAL_TTL_DAYS)
    n = RuleMutation.objects.filter(
        state=RuleMutation.STATE_PROPOSED,
        proposed_at__lt=cutoff).update(state=RuleMutation.STATE_EXPIRED)
    if n:
        logger.info("[evolution] expired %d stale proposal(s) past %dd TTL",
                    n, PROPOSAL_TTL_DAYS)
    return n


def has_open_proposal(rule_name: str) -> bool:
    """An undecided proposal is a question already on the operator's desk —
    asking it again with three more rows is noise, not diligence."""
    from signals.models import RuleMutation
    return RuleMutation.objects.filter(
        parent_rule=rule_name, state=RuleMutation.STATE_PROPOSED).exists()


def propose_if_fresh(rule_name: str) -> dict:
    """Event-driven entry point — called the moment decay is CONFIRMED for
    a rule (by the nightly investigator), instead of waiting for the next
    weekly sweep. Creation becomes a reflex to evidence, not a calendar
    appointment.

    Every gate the weekly path enforces applies here too: the component
    switches, a registered schema, and the open-proposal dedupe. Returns
    {"proposed": n, "reason": ...} and never raises — decay investigation
    must not fail because a proposal could not be made.
    """
    _ensure_rules_registered()
    try:
        from core.platform_control import is_component_enabled
        if not (is_component_enabled("platform_master")
                and is_component_enabled("pipeline_evolution")):
            return {"proposed": 0, "reason": "pipeline_evolution is off"}
        if not has_schema(rule_name):
            return {"proposed": 0, "reason": "no parameter schema"}
        expire_stale_mutations()
        if has_open_proposal(rule_name):
            return {"proposed": 0, "reason": "open proposal awaiting review"}
        saved = propose_evolution(rule_name)
        logger.info("[evolution] decay-triggered: %d proposal(s) for %s",
                    len(saved), rule_name)
        return {"proposed": len(saved), "reason": "decay-triggered"}
    except Exception as e:  # noqa: BLE001
        logger.warning("[evolution] decay-triggered proposal failed for %s: %s",
                       rule_name, e)
        return {"proposed": 0, "reason": f"error: {e}"}


def propose_evolution(rule_name: str, *, n_mutants: int = DEFAULT_N_MUTANTS,
                      top_k: int = DEFAULT_TOP_K,
                      seed: Optional[int] = None) -> list:
    """Generate `n_mutants` candidates, score them, persist the top-K as
    RuleMutation rows in PROPOSED state. Returns the persisted rows."""
    from signals.models import RuleMutation

    _ensure_rules_registered()
    if not has_schema(rule_name):
        raise EvolutionError(f"No parameter schema registered for '{rule_name}'.")

    parent_params = current_params(rule_name)
    parent_exp = _parent_expectancy(rule_name)
    rng = random.Random(seed) if seed is not None else random.Random()

    # Phase 32 — opt-in AI mutator. Rules with `use_ai_mutator=True` in
    # RuleControl.parameters get one AI-generated proposal alongside the
    # heuristic ones. Failures fall back to heuristic, never block.
    use_ai = False
    try:
        from ai_agents.agents.strategy_mutator import use_ai_mutator, generate_ai_mutant
        use_ai = use_ai_mutator(rule_name)
    except Exception:
        use_ai = False

    # One frozen context for the whole sweep: the parent's train/test
    # baselines are computed once here instead of once per mutant, and every
    # candidate is scored on the same windows.
    wf_context = None
    try:
        from signals.evolution_backtest import has_evaluator, walkforward_context
        if has_evaluator(rule_name):
            wf_context = walkforward_context(rule_name, parent_params)
    except Exception as e:  # noqa: BLE001
        logger.warning("[evolution] walkforward context failed for %s: %s",
                       rule_name, e)

    candidates = []
    for i in range(n_mutants):
        if use_ai and i == 0:
            try:
                m = generate_ai_mutant(rule_name, rng=rng)
            except Exception:
                m = generate_mutant(rule_name, rng=rng)
        else:
            m = generate_mutant(rule_name, rng=rng)
        # Skip identical candidates (perturbation rounded to step landed
        # back on the original).
        if m == parent_params:
            continue
        scored = score_mutant(rule_name, m, parent_params, rng=rng,
                              wf_context=wf_context)
        candidates.append((m, scored))

    # Top-K by score (deterministic tiebreak by insertion order).
    candidates.sort(key=lambda t: -t[1]["score"])
    top = candidates[:top_k]

    saved = []
    for mutant_params, scored in top:
        score = scored["score"]
        method = scored["method"]
        details = scored["details"]
        rationale = (
            f"Auto-proposed via {method} scoring. Parent expectancy "
            f"{parent_exp if parent_exp is not None else 'n/a'}R; "
            f"mutant score {score:+.2f}R "
            f"(changed: {', '.join(_params_changed(parent_params, mutant_params)) or 'none'})."
        )
        if method == "walk_forward" and details.get("notes"):
            rationale += f" {details['notes']}"

        mut = RuleMutation.objects.create(
            parent_rule=rule_name,
            parent_params=parent_params,
            mutated_params=mutant_params,
            parameters_changed=_params_changed(parent_params, mutant_params),
            parent_expectancy=parent_exp,
            proposed_score=score,
            score_method=method,
            score_details=details,
            state=RuleMutation.STATE_PROPOSED,
            rationale=rationale,
        )
        saved.append(mut)
    return saved


def propose_for_decaying_rules() -> dict:
    """Celery entry point: scan decaying rules WITH a registered schema,
    propose evolution candidates for each. Skips rules whose previous
    proposal is still awaiting the operator's decision — repeated sweeps
    used to stack three more rows per pass onto an unanswered question."""
    from signals.performance import decay_flag
    from signals.models import Signal

    _ensure_rules_registered()
    expired = expire_stale_mutations()
    # order_by clears Signal's Meta.ordering, which would otherwise ride
    # into the DISTINCT and return one row per (rule_name, created_at) pair.
    rule_names = list(
        Signal.objects.exclude(rule_name="")
        .values_list("rule_name", flat=True)
        .distinct().order_by("rule_name")
    )

    proposals_per_rule: dict[str, int] = {}
    for rn in rule_names:
        if not has_schema(rn):
            continue
        try:
            flag = decay_flag(rn)
        except Exception:
            continue
        if not flag.get("is_decaying"):
            continue
        if has_open_proposal(rn):
            logger.info("[evolution] %s: open proposal pending — not stacking",
                        rn)
            continue
        try:
            saved = propose_evolution(rn)
            proposals_per_rule[rn] = len(saved)
        except Exception as e:
            logger.warning("[evolution] failed for %s: %s", rn, e)

    return {
        "rules_scanned": len(rule_names),
        "rules_with_schema": sum(1 for r in rule_names if has_schema(r)),
        "rules_decaying_evolved": len(proposals_per_rule),
        "total_proposals": sum(proposals_per_rule.values()),
        "proposals": proposals_per_rule,
        "proposals_expired": expired,
    }


@transaction.atomic
def apply_evolution(mutation_id: int, user) -> "RuleControl":
    """Promote a mutation: create a new RuleControl forked from the parent
    with the mutated parameters, in RESEARCH stage. Original is untouched.

    Returns the new (forked) RuleControl.
    """
    from signals.models import RuleControl, RuleMutation

    mut = RuleMutation.objects.select_for_update().get(id=mutation_id)
    if mut.state != RuleMutation.STATE_PROPOSED:
        raise EvolutionError(f"Mutation #{mutation_id} is in state {mut.state}; cannot apply.")

    # Pick a unique forked name: {parent}_evolved_v{N}.
    n = 1
    while True:
        candidate = f"{mut.parent_rule}_evolved_v{n}"
        if not RuleControl.objects.filter(rule_name=candidate).exists():
            break
        n += 1
    forked_name = candidate

    new_ctrl = RuleControl.objects.create(
        rule_name=forked_name,
        status=RuleControl.STATUS_ACTIVE,
        promotion_stage=RuleControl.STAGE_RESEARCH,
        stage_entered_at=timezone.now(),
        parameters=mut.mutated_params,
        notes=(f"Forked from '{mut.parent_rule}' via RuleMutation #{mut.id}. "
               f"Changed: {', '.join(mut.parameters_changed)}"),
    )

    mut.forked_rule = forked_name
    mut.state = RuleMutation.STATE_APPLIED
    mut.applied_at = timezone.now()
    mut.decided_by = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    mut.save()

    logger.info("[evolution] applied mutation #%s — new rule %s in RESEARCH",
                mut.id, forked_name)
    return new_ctrl


def reject_evolution(mutation_id: int, user) -> "RuleMutation":
    from signals.models import RuleMutation
    mut = RuleMutation.objects.get(id=mutation_id)
    if mut.state != RuleMutation.STATE_PROPOSED:
        raise EvolutionError(f"Mutation #{mutation_id} in state {mut.state}; cannot reject.")
    mut.state = RuleMutation.STATE_REJECTED
    mut.decided_by = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    mut.save()
    return mut
