"""Pattern-miner / discovered-setup dashboard — Phase 11."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def discoveries_dashboard(request):
    from signals.models import DiscoveredSetup
    from signals.pattern_miner import FEATURE_EXTRACTORS, FEATURE_TO_CONDITION

    proposed = list(
        DiscoveredSetup.objects.filter(state=DiscoveredSetup.STATE_PROPOSED)
        .order_by("-lift", "-support")[:50]
    )
    activated = list(
        DiscoveredSetup.objects.filter(state=DiscoveredSetup.STATE_ACTIVATED)
        .select_related("activated_setup")[:30]
    )
    history = list(
        DiscoveredSetup.objects.exclude(state=DiscoveredSetup.STATE_PROPOSED)
        .order_by("-mined_at")[:50]
    )

    feature_keys = sorted(FEATURE_EXTRACTORS.keys())
    mappable = sorted(FEATURE_TO_CONDITION.keys())

    context = {
        "page_id": "discoveries",
        "proposed": proposed,
        "activated": activated,
        "history": history,
        "feature_keys": feature_keys,
        "mappable": mappable,
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/discoveries.html", context)
