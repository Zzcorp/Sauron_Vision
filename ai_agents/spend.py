"""A hard daily ceiling on LLM spend.

The brain runs synthesis, a critic, a strategist, a generator, an earnings
reviewer and an anomaly scanner on schedules, each calling a frontier
model. That is the largest recurring variable cost in the platform and the
least validated component — it can quietly become the dominant expense of
running a system whose trading edge is not yet measured.

`AgentTask` already records `cost_usd` per call, so the budget is computed
from real spend rather than an estimate. Agents check `can_spend()` before
calling out and skip cleanly when the day's budget is gone: a skipped
briefing is an inconvenience, an unbounded bill is not.

Set AI_DAILY_BUDGET_USD=0 to disable the ceiling entirely.
"""
from __future__ import annotations

import logging
import os

from django.utils import timezone

logger = logging.getLogger(__name__)

# 15, not the original 5 — and the two changes travel together. The ledger
# this budget reads used to miss every direct-provider caller (all seven
# brain modules), so "5" was really governing about half of true spend: the
# Anthropic console read ~2x what /ai-models/ admitted to. With the ledger
# complete, a 5 would suddenly halt the platform's cognition mid-afternoon
# — not a policy anyone chose, just yesterday's blind spot becoming today's
# throttle. 15 covers the measured full burn (~4/day) with honest headroom;
# the env var remains the operator's knob.
DEFAULT_DAILY_BUDGET_USD = float(os.getenv("AI_DAILY_BUDGET_USD", "15.0"))
# Reserve a slice for the cheap, operationally useful agents (journals,
# pre-trade checks) so an expensive deep-tier run can't consume the lot.
DEEP_TIER_SHARE = 0.7


def daily_budget() -> float:
    from django.conf import settings
    configured = getattr(settings, "AI_CONFIG", {}).get("daily_budget_usd")
    if configured is not None:
        try:
            return float(configured)
        except (TypeError, ValueError):
            pass
    return DEFAULT_DAILY_BUDGET_USD


def spent_today() -> float:
    """Actual USD spent today, from the AgentTask ledger."""
    from django.db.models import Sum
    from ai_agents.models import AgentTask

    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (AgentTask.objects
             .filter(created_at__gte=start)
             .aggregate(s=Sum("cost_usd"))["s"])
    return float(total or 0)


def remaining_today() -> float:
    budget = daily_budget()
    if budget <= 0:
        return float("inf")
    return max(0.0, budget - spent_today())


def can_spend(*, tier: str = "balanced", estimated_usd: float = 0.05) -> tuple:
    """(allowed, reason) — may an agent on `tier` make a call now?"""
    budget = daily_budget()
    if budget <= 0:
        return True, "no budget configured"

    spent = spent_today()
    remaining = budget - spent
    if remaining <= 0:
        return False, (f"daily AI budget spent (${spent:.2f} of ${budget:.2f})")

    # Deep-tier work is the expensive kind; hold back a slice of the budget
    # so the cheap operational agents still run late in the day.
    if tier == "deep" and spent > budget * DEEP_TIER_SHARE:
        return False, (f"deep-tier reserve reached (${spent:.2f} of "
                       f"${budget:.2f}; deep tier capped at "
                       f"{DEEP_TIER_SHARE:.0%})")
    if estimated_usd > remaining:
        return False, (f"call would exceed the daily budget "
                       f"(${remaining:.2f} left)")
    return True, f"${remaining:.2f} of ${budget:.2f} remaining"


def guard(tier: str = "balanced", estimated_usd: float = 0.05):
    """Decorator: skip an agent task when the day's budget is exhausted."""
    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            allowed, reason = can_spend(tier=tier, estimated_usd=estimated_usd)
            if not allowed:
                logger.warning("[spend] skipping %s — %s", fn.__name__, reason)
                return {"status": "skipped", "reason": reason}
            return fn(*args, **kwargs)
        return wrapper
    return decorator
