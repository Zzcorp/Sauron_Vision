"""AI model selection — pick the model and effort per tier, or per agent.

Superuser-only: changing a tier repoints every agent on it, which changes
both cost and quality platform-wide.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone


# Agents worth exposing individually, grouped for the UI. Anything not
# listed still resolves through its tier.
AGENT_GROUPS = [
    ("Market analysis", [
        ("news_analyst", "News Analyst", "fast"),
        ("anomaly_detector", "Anomaly Detector", "fast"),
        ("market_commentator", "Market Commentator", "fast"),
        ("speech_analyst", "Speech Analyst", "fast"),
        ("macro_interpreter", "Macro Interpreter", "balanced"),
        ("earnings_analyst", "Earnings Analyst", "balanced"),
    ]),
    ("Trading loop", [
        ("pretrade_sanity", "Pre-Trade Sanity Gate", "fast"),
        ("signal_journal", "Signal Journal", "fast"),
        ("trade_journal", "Trade Journal", "fast"),
        ("decay_investigator", "Decay Investigator", "balanced"),
        ("strategy_advisor", "Strategy Advisor", "balanced"),
        ("strategy_mutator", "Strategy Mutator", "balanced"),
        ("weekly_reviewer", "Weekly Reviewer", "deep"),
    ]),
    # Keys MUST equal each agent's runtime agent_name — the resolver looks
    # up overrides by that value, so a friendly-but-wrong key writes a row
    # nothing ever reads.
    ("Sauron's Mind", [
        ("sauron_mind", "Synthesizer", "balanced"),
        ("critic", "Critic", "deep"),
        ("strategist", "Strategist", "deep"),
        ("strategy_generator", "Strategy Generator", "deep"),
        ("earnings_reviewer", "Earnings Reviewer", "balanced"),
        ("research", "Research Chat", "balanced"),
    ]),
]

# Every key the UI may write, so a typo can't create a dead override row.
KNOWN_AGENT_KEYS = {name for _, rows in AGENT_GROUPS for name, _, _ in rows}


@staff_member_required
def ai_models_dashboard(request):
    from ai_agents.catalog import (
        MODELS, TIERS, EFFORT_LEVELS, TIER_DEFAULTS, TIER_EFFORT_DEFAULTS,
        resolve_tier, resolve_agent, resolve_effort, known_model,
    )
    from ai_agents.models import AIModelSetting, AgentTask

    if request.method == "POST":
        scope = request.POST.get("scope", "")
        key = (request.POST.get("key") or "").strip()
        model_id = (request.POST.get("model_id") or "").strip()
        effort = (request.POST.get("effort") or "").strip()

        if scope not in ("tier", "agent") or not key:
            messages.error(request, "Invalid selection.")
        elif scope == "tier" and key not in TIERS:
            messages.error(request, f"Unknown tier: {key}")
        elif scope == "agent" and key not in KNOWN_AGENT_KEYS:
            # Guards against a row that persists but resolves for nobody.
            messages.error(request, f"Unknown agent: {key}")
        elif model_id and not known_model(model_id):
            messages.error(request, f"Unknown model id: {model_id}")
        elif effort and effort not in EFFORT_LEVELS:
            messages.error(request, f"Unknown effort level: {effort}")
        elif not model_id and not effort:
            # Both blank = clear the override entirely.
            AIModelSetting.objects.filter(scope=scope, key=key).delete()
            messages.success(request, f"Reset {scope} '{key}' to default.")
        else:
            AIModelSetting.objects.update_or_create(
                scope=scope, key=key,
                defaults={"model_id": model_id, "effort": effort,
                          "updated_by": request.user},
            )
            messages.success(
                request,
                f"{scope.title()} '{key}' → {model_id or 'default'}"
                + (f" (effort {effort})" if effort else ""))
        return redirect("ai_models_dashboard")

    overrides = {
        (s.scope, s.key): s for s in AIModelSetting.objects.all()
    }

    tier_rows = []
    for tier in TIERS:
        row = overrides.get(("tier", tier))
        resolved = resolve_tier(tier)
        tier_rows.append({
            "tier": tier,
            "resolved": resolved,
            "label": MODELS.get(resolved, {}).get("label", resolved),
            "effort": resolve_effort(resolved, tier) or "—",
            "override": row,
            "code_default": TIER_DEFAULTS[tier],
            "default_effort": TIER_EFFORT_DEFAULTS[tier],
            "unknown": not known_model(resolved),
        })

    agent_groups = []
    for group_name, agents in AGENT_GROUPS:
        rows = []
        for name, label, tier in agents:
            row = overrides.get(("agent", name))
            resolved = resolve_agent(name, tier)
            rows.append({
                "name": name, "label": label, "tier": tier,
                "resolved": resolved,
                "model_label": MODELS.get(resolved, {}).get("label", resolved),
                "effort": resolve_effort(resolved, tier, name) or "—",
                "override": row,
                "unknown": not known_model(resolved),
            })
        agent_groups.append({"name": group_name, "rows": rows})

    # 30-day spend per model, so the cost of a choice is visible next to it.
    cutoff = timezone.now() - timedelta(days=30)
    usage = list(
        AgentTask.objects.filter(created_at__gte=cutoff)
        .values("model")
        .annotate(calls=Count("id"), cost=Sum("cost_usd"),
                  avg_secs=Avg("duration_seconds"))
        .order_by("-cost")
    )
    for u in usage:
        u["label"] = MODELS.get(u["model"], {}).get("label", u["model"])
        u["known"] = known_model(u["model"])
    total_cost = sum(float(u["cost"] or 0) for u in usage)

    return render(request, "dashboard/ai_models.html", {
        "page_id": "ai_models",
        "tier_rows": tier_rows,
        "agent_groups": agent_groups,
        "catalog": [
            {"id": mid, **meta} for mid, meta in MODELS.items()
        ],
        "effort_levels": EFFORT_LEVELS,
        "usage": usage,
        "total_cost_30d": round(total_cost, 4),
    })
