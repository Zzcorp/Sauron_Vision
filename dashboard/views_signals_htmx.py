"""HTMX endpoints for live signal cards on the dashboard."""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def signal_cards_htmx(request):
    """Render the active SmcSignal feed for HTMX polling."""
    try:
        from signals.models_smc import SmcSignal
        signals = SmcSignal.objects.filter(
            status__in=["ACTIVE", "TRIGGERED"]
        ).order_by("-conviction", "-created_at")[:30]
    except Exception:
        signals = []
    return render(request, "dashboard/_signal_cards.html", {
        "signals": signals,
    })


@login_required
def signal_performance_htmx(request):
    """Render the per-setup hit-rate panel."""
    try:
        from signals.performance import setup_performance_summary
        perf = setup_performance_summary(days=30)
    except Exception:
        perf = {}
    return render(request, "dashboard/_signal_performance.html", {
        "perf": perf,
    })
