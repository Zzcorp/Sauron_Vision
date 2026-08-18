"""Phase 37 — Sauron's Mind dashboard.

A single page that surfaces the latest BrainReport, the timeline of recent
reports, the brain's calibration curve, and the observation queue stats.
"""
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST


@login_required
def brain_dashboard(request):
    from brain.models import BrainReport, BrainObservation
    from brain.context import _brain_trust_score

    latest = BrainReport.objects.first()
    timeline = list(BrainReport.objects.all()[:20])

    # Observation queue stats by kind.
    from django.db.models import Count
    obs_unconsumed = (BrainObservation.objects
                       .filter(consumed_by_brain_at__isnull=True)
                       .values("kind").annotate(n=Count("id"))
                       .order_by("-n"))
    obs_total = BrainObservation.objects.count()

    # Brain prediction calibration (last 50 resolved).
    try:
        from ai_agents.models import AgentPrediction
        pred_qs = AgentPrediction.objects.filter(
            agent="sauron_mind", was_correct__isnull=False,
        ).order_by("-evaluated_at")[:50]
        n_resolved = pred_qs.count()
        n_correct = sum(1 for p in pred_qs if p.was_correct)
        accuracy = (n_correct / n_resolved) if n_resolved else None
    except Exception:
        n_resolved = 0
        n_correct = 0
        accuracy = None

    # Pending predictions.
    try:
        from ai_agents.models import AgentPrediction
        n_pending = AgentPrediction.objects.filter(
            agent="sauron_mind", was_correct__isnull=True,
        ).count()
    except Exception:
        n_pending = 0

    context = {
        "page_id": "brain",
        "latest": latest,
        "timeline": timeline,
        "obs_unconsumed": list(obs_unconsumed),
        "obs_total": obs_total,
        "trust_score": _brain_trust_score(),
        "n_resolved": n_resolved,
        "n_correct": n_correct,
        "accuracy": accuracy,
        "n_pending": n_pending,
    }
    return render(request, "dashboard/brain.html", context)


@staff_member_required
@require_POST
def brain_run_now(request):
    """Admin-only — run one synthesis cycle. XHR clicks enqueue the real
    beat task (announced live on completion); plain form POSTs keep the
    synchronous path."""
    from brain.synthesizer import synthesize_now
    from brain.tasks import run_sauron_mind as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Brain synthesis",
                                reverse("brain_dashboard"))
    if resp is not None:
        return resp
    result = synthesize_now()
    request.session["brain_run_result"] = result
    return HttpResponseRedirect(reverse("brain_dashboard"))
