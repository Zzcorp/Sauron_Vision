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

    context = {
        "page_id": "evolution",
        "proposed": proposed,
        "applied": applied,
        "history": history,
        "schemas": schemas,
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/evolution.html", context)
