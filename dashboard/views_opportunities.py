"""Opportunity-scanner dashboard — Phase 10."""
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def opportunities_dashboard(request):
    from signals.models import OpportunitySetup, OpportunityFlag
    from signals.opportunity_scanner import EVALUATOR_REGISTRY

    setups = list(OpportunitySetup.objects.all().order_by("name"))
    open_flags = list(
        OpportunityFlag.objects.filter(outcome="")
        .select_related("setup", "instrument", "signal")
        .order_by("-scanned_at")[:50]
    )
    resolved_flags = list(
        OpportunityFlag.objects.exclude(outcome="")
        .select_related("setup", "instrument")
        .order_by("-resolved_at")[:50]
    )

    # Per-setup hit rates (computed from resolved flags)
    setup_stats = []
    for s in setups:
        flags = OpportunityFlag.objects.filter(setup=s).exclude(outcome="")
        n = flags.count()
        hits = flags.filter(outcome="hit").count() if n else 0
        setup_stats.append({
            "setup": s, "n_resolved": n,
            "n_hit": hits,
            "hit_rate": round(hits / n, 4) if n > 0 else None,
            "n_pending": OpportunityFlag.objects.filter(setup=s, outcome="").count(),
        })

    context = {
        "page_id": "opportunities",
        "setup_stats": setup_stats,
        "open_flags": open_flags,
        "resolved_flags": resolved_flags,
        "evaluator_kinds": sorted(EVALUATOR_REGISTRY.keys()),
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/opportunities.html", context)
