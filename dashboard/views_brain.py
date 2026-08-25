"""Phase 37 — Sauron's Mind dashboard.

A single page that surfaces the latest BrainReport, the timeline of recent
reports, the brain's calibration curve, and the observation queue stats.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST


# ── Concerns become actions ───────────────────────────────────────────────
#
# The brain writes verdicts; the operator asked to act on them. Nothing on
# this page can move the live account, so the honest shape of "act" is: every
# concern is paired with the ONE press the platform already knows how to
# take — a RuleAction proposal for the HQ queue, a manual-config kill
# switch, or a link to the page where the exposure is actually managed. Any
# concern kind with no real lever gets no button; a fabricated one would be
# worse than none.

# Overlay verdict → the proposal it asks for. `active` asks for nothing.
OVERLAY_ACTIONS = {
    "pause_recommended": ("pause_rule", "Propose pause"),
    "watch": ("reduce_size", "Propose size cut"),
}

# Which states of an existing proposal replace the button with a chip. A
# rejected/expired/rolled-back row is history, and the concern may be worth
# re-raising — `propose_from_brain` will hand that older row back anyway, so
# the button stays and the press is still harmless.
STANDING_STATES = ("proposed", "applied")


def _severity_tone(sev) -> str:
    try:
        sev = float(sev)
    except (TypeError, ValueError):
        return "low"
    if sev >= 0.75:
        return "critical"
    if sev >= 0.55:
        return "high"
    if sev >= 0.35:
        return "medium"
    return "low"


def _overlay_rows(report, user):
    """One row per rule in the overlay, with its proposal button or chip."""
    from signals.models import RuleAction

    overlay = report.rule_status_overlay or {}
    if not isinstance(overlay, dict) or not overlay:
        return []
    standing = {}
    for ra in RuleAction.objects.filter(source_brain_report=report):
        # First standing row per (rule, action) wins; ordering is newest
        # first, so a re-proposal after a rejection shows the live one.
        standing.setdefault((ra.rule_name, ra.action), ra)
    rows = []
    for rule_name, status in overlay.items():
        status = str(status or "")
        action_key, label = OVERLAY_ACTIONS.get(status, (None, None))
        existing = standing.get((rule_name, action_key)) if action_key else None
        if existing is not None and existing.state not in STANDING_STATES:
            existing = None
        rows.append({
            "rule": rule_name,
            "status": status,
            "action": action_key,
            "label": f"{label} · {rule_name}" if label else "",
            "existing": existing,
            "can_propose": bool(action_key) and bool(getattr(user, "is_staff", False)),
        })
    return rows


def _manual_configs_outside_commodities(user):
    """The operator's enabled manual configs in classes the brain says the
    discretionary hand should stay out of. Reads the exact name the manual
    path keys on so a renamed constant cannot silently empty this list."""
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    from bot_program.models import AssetBotConfig

    if not getattr(user, "is_authenticated", False):
        return []
    return list(AssetBotConfig.objects.filter(
        user=user, name=MANUAL_CONFIG_NAME, enabled=True,
    ).exclude(asset_class="commodity").order_by("asset_class"))


def build_concern_actions(report, user):
    """The latest synthesis, concern by concern, each with its levers.

    Returns (concern_rows, overlay_rows). Rule levers attach to the concern
    that names the rule (by ref or text) and always appear in the overlay
    table, so a concern the brain phrased without a rule name still leaves
    the rule reachable one line lower.
    """
    if report is None:
        return [], []
    overlay_rows = _overlay_rows(report, user)
    is_super = bool(getattr(user, "is_superuser", False))
    concerns = []
    for c in (report.top_concerns or []):
        if not isinstance(c, dict):
            continue
        kind = str(c.get("kind") or "concern")
        text = str(c.get("text") or "")
        ref = str(c.get("ref") or "")
        blob = f"{ref} {text}"
        row = {
            "kind": kind,
            "text": text,
            "severity": c.get("severity"),
            "tone": _severity_tone(c.get("severity")),
            "rules": [r for r in overlay_rows if r["action"] and r["rule"] in blob],
            "links": [],
            "manual_configs": [],
            "note": "",
        }
        if kind == "theme_saturation":
            if is_super:
                row["links"].append({"label": "Open cross-book concentration",
                                     "url": reverse("hq_books")})
            row["links"].append({"label": "Open positions",
                                 "url": reverse("positions_list")})
        elif kind == "discretionary_drift":
            cfgs = _manual_configs_outside_commodities(user)
            if not cfgs:
                row["note"] = "No enabled manual config outside commodities on this account."
            elif is_super:
                row["manual_configs"] = cfgs
            else:
                row["note"] = ("Manual configs outside commodities: "
                               + ", ".join(cfg.asset_class for cfg in cfgs)
                               + " — disabling them is a superuser press at HQ.")
        if not (row["rules"] or row["links"] or row["manual_configs"] or row["note"]):
            row["note"] = "No platform lever for this concern — read it, do not click it."
        concerns.append(row)
    return concerns, overlay_rows


@login_required
def brain_dashboard(request):  # noqa: C901
    from brain.models import BrainReport, BrainObservation
    from brain.context import _brain_trust_score

    latest = BrainReport.objects.first()
    timeline = list(BrainReport.objects.all()[:20])
    concern_rows, overlay_rows = build_concern_actions(latest, request.user)

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
        "concern_rows": concern_rows,
        "overlay_rows": overlay_rows,
    }
    # Popped, so a result is read once and does not haunt the next visit.
    context["brain_propose_result"] = request.session.pop(
        "brain_propose_result", None)
    return render(request, "dashboard/brain.html", context)


def _wants_json(request) -> bool:
    return (request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", ""))


@login_required
@require_POST
def _brain_result(request, ok: bool, msg: str) -> None:
    """Stash a result for the brain page alone.

    The page used to render the whole `messages` queue, so a flash left
    by any view whose target never displays one surfaced here dressed as
    a brain-action result.
    """
    request.session["brain_propose_result"] = {"ok": bool(ok), "msg": msg}


def brain_propose(request):
    """One press: a brain concern becomes a RuleAction proposal for HQ.

    Staff only — a 403, not a redirect, so a non-staff POST is refused
    rather than quietly bounced to the page. Idempotent through
    `propose_from_brain`: pressing again names the row that already exists.
    """
    from brain.models import BrainReport
    from signals.rule_actuator import propose_from_brain, ActuatorError

    if not request.user.is_staff:
        return HttpResponseForbidden("Staff access required.")

    try:
        report_id = int(request.POST.get("report_id") or 0)
    except (TypeError, ValueError):
        report_id = 0
    report = BrainReport.objects.filter(pk=report_id).first()
    rule_name = (request.POST.get("rule_name") or "").strip()
    action = (request.POST.get("action") or "").strip()
    back = reverse("brain_dashboard")

    if report is None:
        msg = "That brain report no longer exists."
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": msg}, status=404)
        _brain_result(request, False, msg)
        return HttpResponseRedirect(back)

    try:
        ra = propose_from_brain(report, rule_name, action, request.user)
    except ActuatorError as e:
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        _brain_result(request, False, f"Actuator: {e}")
        return HttpResponseRedirect(back)

    msg = (f"RuleAction #{ra.id} — {ra.action} on '{ra.rule_name}' is {ra.state}; "
           f"an admin applies it at HQ.")
    if _wants_json(request):
        return JsonResponse({"ok": True, "action_id": ra.id, "state": ra.state,
                             "rule_name": ra.rule_name, "action": ra.action,
                             "redirect": back})
    _brain_result(request, True, msg)
    return HttpResponseRedirect(back)


@login_required
@require_POST
def brain_disable_manual(request):
    """Quiet ONE manual config — a disable, never a toggle.

    hq_toggle_asset_bot flips whatever it finds, so a stale page or a
    double submit would re-arm the very config the brain asked to quiet.
    This says what it means: already disabled is a no-op that reports
    itself. Superuser only, and only a MANUAL config the presser owns —
    the brain's advice is not a lever onto other people's bots.
    """
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    from bot_program.models import AssetBotConfig

    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")

    back = reverse("brain_dashboard")
    try:
        cfg_id = int(request.POST.get("config_id") or 0)
    except (TypeError, ValueError):
        cfg_id = 0
    cfg = AssetBotConfig.objects.filter(
        pk=cfg_id, user=request.user, name=MANUAL_CONFIG_NAME).first()
    if cfg is None:
        _brain_result(request, False,
                      "That manual config is not one of yours.")
        return HttpResponseRedirect(back)

    if cfg.enabled:
        cfg.enabled = False
        cfg.save(update_fields=["enabled", "updated_at"])
        _brain_result(request, True,
                      f"Manual {cfg.asset_class} is DISABLED — it manages "
                      f"what is open and opens nothing new.")
    else:
        _brain_result(request, True,
                      f"Manual {cfg.asset_class} was already disabled.")
    return HttpResponseRedirect(back)


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
