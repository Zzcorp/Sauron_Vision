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

    # The "Effective x" column used to render the multiplication as text —
    # "0.50 x 1.00" — rather than its result, so the one number an operator
    # needs (what this rule's size is actually scaled by) was the one number
    # the table did not show. widthratio cannot do it either: it rounds to an
    # integer, which would turn x0.375 into x0.
    for c in rule_states:
        admin_w = float(c.weight_multiplier or 1.0) if c.status == "reduced" else 1.0
        alloc_w = float(c.allocator_weight or 1.0) if c.status == "active" else 0.0
        c.effective_multiplier = round(admin_w * alloc_w, 4)

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
