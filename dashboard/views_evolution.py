"""Strategy evolution dashboard — Phase 9."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def evolution_dashboard(request):
    from signals.models import RuleMutation
    from signals.evolution import SCHEMA_REGISTRY, _ensure_rules_registered

    # Registration is a lazy per-process side effect; a fresh web worker
    # has never run a proposal task, so without this the panel renders
    # "no schemas registered" while celery is actively proposing.
    _ensure_rules_registered()

    proposed = list(
        RuleMutation.objects.filter(state=RuleMutation.STATE_PROPOSED)
        .order_by("-proposed_at")[:30]
    )
    applied = list(
        RuleMutation.objects.filter(state=RuleMutation.STATE_APPLIED)
        .order_by("-applied_at")[:30]
    )
    history = list(
        RuleMutation.objects.exclude(state=RuleMutation.STATE_PROPOSED)
        .order_by("-proposed_at")[:30]
    )

    schemas = []
    for rule_name, schema in SCHEMA_REGISTRY.items():
        schemas.append({
            "rule_name": rule_name,
            "params": list(schema.keys()),
            "n_params": len(schema),
        })

    # ── Rule families: parent → evolved forks, with the evidence ──────
    # Every applied RuleMutation is a parent→fork edge; the walk-forward
    # breakdown was persisted at proposal time in score_details and had
    # never been rendered anywhere. No backtests run here — this page
    # must stay cheap enough for every registered user to keep open.
    from signals.models_control import RuleControl, RuleMutation
    from signals.promotion_pipeline import _stats_since

    controls = {c.rule_name: c for c in RuleControl.objects.all()}
    edges = list(RuleMutation.objects.filter(
        state=RuleMutation.STATE_APPLIED).order_by("parent_rule", "applied_at"))

    def _node(name):
        ctrl = controls.get(name)
        stats = _stats_since(name, days_window=90)
        hit = stats.get("hit_rate")
        return {
            "name": name,
            "stage": getattr(ctrl, "promotion_stage", "") or "",
            "status": getattr(ctrl, "status", "") or "",
            "params": getattr(ctrl, "parameters", None) or {},
            "stage_entered_at": getattr(ctrl, "stage_entered_at", None),
            "n_90d": stats.get("n") or 0,
            "expectancy_90d": stats.get("expectancy"),
            # _stats_since returns a 0..1 FRACTION; the template renders
            # "N%" — unscaled, a healthy 55% rule displayed as "1%".
            "hit_rate_90d": None if hit is None else hit * 100,
        }

    families = []
    by_parent: dict = {}
    for mut in edges:
        fork = _node(mut.forked_rule)
        fork["changed"] = mut.parameters_changed
        fork["mutated_params"] = mut.mutated_params
        fork["score"] = mut.proposed_score
        fork["score_method"] = mut.score_method
        fork["details"] = mut.score_details or {}
        fork["applied_at"] = mut.applied_at
        by_parent.setdefault(mut.parent_rule, []).append(fork)
    for parent_name in sorted(by_parent):
        families.append({
            "parent": _node(parent_name),
            "forks": by_parent[parent_name],
        })

    context = {
        "page_id": "evolution",
        "proposed": proposed,
        "applied": applied,
        "history": history,
        "schemas": schemas,
        "families": families,
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/evolution.html", context)
