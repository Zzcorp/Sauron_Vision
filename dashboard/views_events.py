"""Real-time event-engine dashboard — Phase 12."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import render
from django.utils import timezone


@login_required
def events_dashboard(request):
    from signals.models import FastEvent
    from signals.fast_rules import FAST_RULE_REGISTRY

    since = timezone.now() - timedelta(hours=24)
    recent = list(
        FastEvent.objects.filter(received_at__gte=since)
        .order_by("-received_at")[:50]
    )

    by_type = list(
        FastEvent.objects.filter(received_at__gte=since)
        .values("event_type")
        .annotate(n=Count("id"), avg_ms=Avg("dispatch_ms"),
                  total_fired=Count("fired_rule_names"))
        .order_by("-n")
    )

    rules_summary = []
    for rule_name, rule in sorted(FAST_RULE_REGISTRY.items()):
        rules_summary.append({
            "rule_name": rule_name,
            "event_types": rule.event_types,
            "cooldown_seconds": rule.cooldown_seconds,
            "class_name": rule.__class__.__name__,
        })

    context = {
        "page_id": "events",
        "recent": recent,
        "by_type": by_type,
        "rules_summary": rules_summary,
        "events_24h": FastEvent.objects.filter(received_at__gte=since).count(),
        "fired_24h": FastEvent.objects.filter(received_at__gte=since,
                                                rules_fired__gt=0).count(),
    }
    return render(request, "dashboard/events.html", context)
