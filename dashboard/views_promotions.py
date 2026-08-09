"""Promotion-pipeline dashboard — Phase 8."""
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def promotions_dashboard(request):
    from signals.models import RuleControl, PromotionEvent
    from signals.promotion_pipeline import (
        is_eligible_for_promotion, is_due_for_demotion, _stats_since,
    )

    rules = list(RuleControl.objects.all().order_by("rule_name"))
    rows = []
    for ctrl in rules:
        s = _stats_since(ctrl.rule_name, days_window=90)

        # Recent live/paper stats say a rule *may* advance; walk-forward
        # evidence says whether it has earned real money exposure.
        eligible = is_eligible_for_promotion(ctrl.rule_name)
        evidence_ok, evidence_reason = (None, "")
        if eligible:
            from signals.promotion_evidence import gate_promotion
            evidence_ok, evidence_reason = gate_promotion(ctrl.rule_name, eligible)

        rows.append({
            "rule": ctrl.rule_name,
            "stage": ctrl.promotion_stage,
            "stage_display": ctrl.get_promotion_stage_display(),
            "stage_entered": ctrl.stage_entered_at,
            "baseline": ctrl.stage_baseline_expectancy,
            "n_recent": s["n"],
            "expectancy_recent": s["expectancy"],
            "hit_rate_recent": s["hit_rate"],
            "eligible_promote": eligible,
            "due_demote": is_due_for_demotion(ctrl.rule_name),
            # Why a rule that looks eligible is still not going live.
            "evidence_ok": evidence_ok,
            "evidence_reason": evidence_reason,
        })

    stage_counts = Counter(r["stage"] for r in rows)

    history = list(PromotionEvent.objects.all().order_by("-created_at")[:50])

    context = {
        "page_id": "promotions",
        "rows": rows,
        "stage_counts": dict(stage_counts),
        "history": history,
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/promotions.html", context)
