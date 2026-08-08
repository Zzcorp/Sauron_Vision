"""Rule-control dashboard — Phase 5.

Shows the current enforcement state of every rule + the audit log of every
action ever proposed/applied/rejected/rolled-back. Read-only for non-admin;
admin gets the apply / reject / rollback buttons.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def rule_control_dashboard(request):
    from signals.models import RuleControl, RuleAction
    from signals.rule_actuator import is_live_mode

    controls = list(RuleControl.objects.all())
    proposed = list(
        RuleAction.objects.filter(state=RuleAction.STATE_PROPOSED)
        .select_related("source_investigation").order_by("-proposed_at")[:50]
    )
    applied = list(
        RuleAction.objects.filter(state=RuleAction.STATE_APPLIED)
        .select_related("confirmed_by").order_by("-applied_at")[:30]
    )
    history = list(
        RuleAction.objects.exclude(state=RuleAction.STATE_PROPOSED)
        .select_related("confirmed_by").order_by("-proposed_at")[:50]
    )

    context = {
        "page_id": "rule_control",
        "controls": controls,
        "proposed": proposed,
        "applied": applied,
        "history": history,
        "live_mode": is_live_mode(),
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/rule_control.html", context)
