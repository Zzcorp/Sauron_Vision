"""AI insights dashboard — Phase 3.

Surfaces:
  - Recent SignalJournalAgent journal entries (grades, lessons, tags)
  - Recent DecayInvestigatorAgent investigations
  - Recent agent task log (tokens, cost, duration, success)
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone


@login_required
def ai_insights_dashboard(request):
    """Render /ai-insights/."""
    from ai_agents.models import AgentTask, TradeJournalEntry, DecayInvestigation

    journal_entries = list(
        TradeJournalEntry.objects
        .select_related("signal", "signal__instrument", "agent_task")
        .order_by("-created_at")[:30]
    )

    investigations = list(
        DecayInvestigation.objects
        .select_related("agent_task")
        .order_by("-created_at")[:30]
    )

    since = timezone.now() - timedelta(days=7)
    tasks_7d = AgentTask.objects.filter(created_at__gte=since)
    cost_breakdown = list(
        tasks_7d.values("agent")
        .annotate(
            n=Count("id"),
            total_cost=Sum("cost_usd"),
            avg_dur=Avg("duration_seconds"),
            fail_count=Count("id", filter=Q(success=False)),
        )
        .order_by("-n")
    )

    grade_dist = list(
        TradeJournalEntry.objects.values("grade").annotate(n=Count("id")).order_by("grade")
    )

    context = {
        "page_id": "ai_insights",
        "journal_entries": journal_entries,
        "investigations": investigations,
        "tasks_7d_count": tasks_7d.count(),
        "tasks_7d_cost": tasks_7d.aggregate(total=Sum("cost_usd"))["total"] or 0,
        "tasks_7d_failures": tasks_7d.filter(success=False).count(),
        "cost_breakdown": cost_breakdown,
        "grade_dist": grade_dist,
    }
    return render(request, "dashboard/ai_journal.html", context)
