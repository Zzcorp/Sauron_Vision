"""Performance dashboard — Sauron grades itself.

Single page that surfaces the entire Phase-1.0 measurement layer:
  - Headline numbers (closed, hit rate, expectancy, decay watch).
  - Per-grouping expectancy tables (signal_type, asset_class, urgency, rule_name).
  - SmcSignal setup performance.
  - Decay-watch table — rules where recent expectancy is materially below baseline.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def performance_dashboard(request):
    """Render /dashboard/performance/ — comprehensive self-grading view."""
    from signals.models import Signal
    from signals.performance import (
        calculate_signal_stats, setup_performance_summary, decay_flag,
    )

    try:
        window = max(int(request.GET.get("window", 30)), 1)
    except (TypeError, ValueError):
        window = 30

    overall = calculate_signal_stats(days=window)
    groupings = {
        "signal_type": calculate_signal_stats(days=window, group_by="signal_type"),
        "asset_class": calculate_signal_stats(days=window, group_by="asset_class"),
        "urgency": calculate_signal_stats(days=window, group_by="urgency"),
        "rule_name": calculate_signal_stats(days=window, group_by="rule_name"),
    }
    setups = setup_performance_summary(days=window)

    # Decay scan — only rules with at least one closed signal in the baseline window.
    # order_by("rule_name") clears Signal's -created_at Meta ordering — otherwise
    # created_at joins the DISTINCT projection and every rule comes back N times.
    rules = (
        Signal.objects
        .filter(is_active=False).exclude(outcome="")
        .order_by("rule_name")
        .values_list("rule_name", flat=True).distinct()
    )
    decay_rows = [decay_flag(r, recent_days=14, baseline_days=90) for r in rules if r]
    decay_rows.sort(key=lambda d: (not d["is_decaying"], -(d["recent_n"] or 0)))
    decaying_count = sum(1 for d in decay_rows if d["is_decaying"])

    grouping_views = []
    for label, data in groupings.items():
        rows = sorted(
            ({"key": k, **stats} for k, stats in data.items()),
            key=lambda r: -(r["n_closed"] or 0),
        )
        grouping_views.append({"label": label, "rows": rows})

    setup_rows = sorted(
        ({"name": k, **v} for k, v in setups.items()),
        key=lambda r: -(r["n_closed"] or 0),
    )

    context = {
        "page_id": "performance",
        "window": window,
        "overall": overall,
        "groupings": grouping_views,
        "setups": setup_rows,
        "decay_rows": decay_rows,
        "decaying_count": decaying_count,
    }
    return render(request, "dashboard/performance.html", context)
