"""The operator's yes or no on a next step (ai_agents/next_steps.py).

Staff only — a 403, not a redirect, so a non-staff POST is refused rather
than quietly bounced to the page. Idempotent: a step already answered is
left as it is and the page is shown again.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect, \
    JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ai_agents import next_steps as ns
from ai_agents.models import ReportNextStep


def _answer(request, step, verb):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff access required.")
    step = (ns.approve if verb == "approve" else ns.reject)(step, request.user)
    wants_json = (request.headers.get("x-requested-with") == "XMLHttpRequest"
                  or "application/json" in request.headers.get("accept", ""))
    if wants_json:
        return JsonResponse({"ok": True, "id": step.pk, "status": step.status,
                             "rule_action_id": step.rule_action_id})
    return HttpResponseRedirect(ns.PAGE_PATH)


@login_required
@require_POST
def next_step_approve(request, pk):
    return _answer(request, get_object_or_404(ReportNextStep, pk=pk),
                   "approve")


@login_required
@require_POST
def next_step_reject(request, pk):
    return _answer(request, get_object_or_404(ReportNextStep, pk=pk),
                   "reject")
