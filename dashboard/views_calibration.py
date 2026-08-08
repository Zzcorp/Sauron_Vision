"""Calibration dashboard — Phase 6.

One page that surfaces every agent's reliability over time:
  - Per-agent table: total predictions, accuracy, Brier score, trust adjustment.
  - Reliability diagram: predicted-confidence buckets vs actual-accuracy.
  - Pending vs resolved breakdown.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def calibration_dashboard(request):
    from ai_agents.models import AgentPrediction
    from ai_agents.calibration import CalibrationTracker, brier_score, trust_adjustment_for

    tracker = CalibrationTracker()
    all_agents = sorted(set(AgentPrediction.objects.values_list("agent", flat=True).distinct()))

    rows = []
    reliability_by_agent = {}
    for agent in all_agents:
        m = tracker.get_agent_accuracy(agent)
        if m.get("total", 0) == 0 and m.get("total_predictions", 0) == 0:
            # Pure pending — still useful to surface.
            pending = AgentPrediction.objects.filter(agent=agent, was_correct__isnull=True).count()
            rows.append({
                "agent": agent, "total": 0, "correct": 0,
                "accuracy": None, "brier": None, "trust": 1.0, "pending": pending,
            })
            continue
        rows.append({
            "agent": agent,
            "total": m.get("total_predictions", 0),
            "correct": m.get("correct", 0),
            "accuracy": m.get("accuracy"),
            "brier": m.get("brier_score"),
            "trust": m.get("trust_adjustment", 1.0),
            "pending": AgentPrediction.objects.filter(agent=agent, was_correct__isnull=True).count(),
        })
        # Reliability buckets for the diagram.
        reliability_by_agent[agent] = []
        for bucket_key, bucket in (m.get("calibration") or {}).items():
            reliability_by_agent[agent].append({
                "predicted": bucket["predicted_confidence"],
                "actual": bucket["actual_accuracy"],
                "n": bucket["n"],
            })

    rows.sort(key=lambda r: -(r["total"] or 0))

    pending_total = AgentPrediction.objects.filter(was_correct__isnull=True).count()
    resolved_total = AgentPrediction.objects.filter(was_correct__isnull=False).count()

    recent_resolved = list(
        AgentPrediction.objects.filter(was_correct__isnull=False)
        .select_related("linked_signal", "linked_signal__instrument")
        .order_by("-evaluated_at")[:30]
    )
    recent_pending = list(
        AgentPrediction.objects.filter(was_correct__isnull=True)
        .order_by("expected_resolution_at")[:30]
    )

    context = {
        "page_id": "calibration",
        "rows": rows,
        "reliability_by_agent": reliability_by_agent,
        "pending_total": pending_total,
        "resolved_total": resolved_total,
        "recent_resolved": recent_resolved,
        "recent_pending": recent_pending,
    }
    return render(request, "dashboard/calibration.html", context)
