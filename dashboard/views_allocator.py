"""Meta-allocator dashboard — Phase 7."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def allocator_dashboard(request):
    from signals.models import MetaAllocation, RuleControl
    from signals.meta_allocator import is_live_mode

    shadows = list(MetaAllocation.objects.filter(state=MetaAllocation.STATE_SHADOW)
                   .order_by("-proposed_at")[:10])
    applied = list(MetaAllocation.objects.filter(state=MetaAllocation.STATE_APPLIED)
                   .order_by("-applied_at")[:10])
    history = list(MetaAllocation.objects.exclude(state=MetaAllocation.STATE_SHADOW)
                   .order_by("-proposed_at")[:30])
    rule_states = list(RuleControl.objects.all().order_by("rule_name"))

    context = {
        "page_id": "allocator",
        "shadows": shadows,
        "applied": applied,
        "history": history,
        "rule_states": rule_states,
        "live_mode": is_live_mode(),
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/allocator.html", context)
