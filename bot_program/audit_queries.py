"""Phase 55 — Read-side helpers over the Phase-28/54 audit chain.

When the operator manually overrides Sauron (rejects a proposal, restores
a demoted rule, etc.), those events are already in the hash-chained audit
log. This module is the structured READ side: aggregate them so the
intelligence hub + strategist briefing can show "the operator overrode
the generator 4 times this week" — a useful signal of which agent is
being mistrusted in practice.

All helpers are pure-Python, query-only, and never mutate state. Cost: $0.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Override event kinds ──────────────────────────────────────────────────

OVERRIDE_KINDS = (
    "proposal_rejected",   # admin rejected a generator proposal
    "rule_restored",       # admin overruled an auto-demotion
)
"""Kinds in the audit log that represent the operator overriding an
AI-driven decision. `proposal_approved` and `rule_demoted` are the
AI-affirming counterparts and are NOT counted as overrides."""


def recent_overrides(*, days: int = 7, limit: int = 30) -> list:
    """Return the most recent OperatorOverride-type audit entries within
    the lookback window.

    Each entry has `kind`, `data` (jsonable payload), `created_at`.
    """
    try:
        from .audit_models import AuditLogEntry
    except Exception:
        return []
    cutoff = timezone.now() - timedelta(days=max(1, int(days)))
    return list(
        AuditLogEntry.objects
        .filter(kind__in=OVERRIDE_KINDS, created_at__gte=cutoff)
        .order_by("-created_at")[:limit]
    )


def override_counts_by_target_agent(*, days: int = 7) -> dict:
    """Aggregate overrides by which AGENT was overridden:
      - proposal_rejected → strategy_generator
      - rule_restored      → demoter (the auto-demoter that killed the rule)

    Returns: {agent_name: count}. Useful to spot which agent is losing
    operator trust over the lookback window.
    """
    rows = recent_overrides(days=days, limit=500)
    counts: dict[str, int] = {}
    for r in rows:
        agent = _agent_for_kind(r.kind)
        if agent:
            counts[agent] = counts.get(agent, 0) + 1
    return counts


def _agent_for_kind(kind: str) -> Optional[str]:
    """Map an override kind to the agent it overrules."""
    return {
        "proposal_rejected": "strategy_generator",
        "rule_restored": "demoter",
    }.get(kind)


def agent_override_rate(agent: str, *, days: int = 30) -> Optional[float]:
    """Return overrides / total-decisions for one agent over the window.

    A rate near 0 means the operator agrees with the agent. Near 1 means
    they disagree consistently — feed this into trust derating.

    Returns None if the agent made no decisions in the window (no signal
    yet) or if the agent is unknown.
    """
    try:
        from .audit_models import AuditLogEntry
    except Exception:
        return None

    affirm_kind, override_kind = _agent_decision_kinds(agent)
    if affirm_kind is None or override_kind is None:
        return None

    cutoff = timezone.now() - timedelta(days=max(1, int(days)))
    base = AuditLogEntry.objects.filter(created_at__gte=cutoff)
    n_affirm = base.filter(kind=affirm_kind).count()
    n_override = base.filter(kind=override_kind).count()
    total = n_affirm + n_override
    if total == 0:
        return None
    return round(n_override / total, 4)


def _agent_decision_kinds(agent: str) -> tuple[Optional[str], Optional[str]]:
    """For an agent name, return (affirm_kind, override_kind)."""
    return {
        "strategy_generator": ("proposal_approved", "proposal_rejected"),
        "demoter": ("rule_demoted", "rule_restored"),
    }.get(agent, (None, None))
