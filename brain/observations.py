"""Phase 37 — observation recording helper.

A single function used by every system hook + agent to append a typed
event to the brain's observation queue. The cardinal rule: this MUST
NEVER raise or block the caller. If the DB is down, an observation
is dropped, not propagated.

Usage:
    from brain.observations import record_observation
    record_observation(
        kind=BrainObservation.KIND_GATE_REJECT,
        payload={"reason": "theme_cap", "theme": "USD_short"},
        source="orchestrator",
        instrument=instrument,
    )
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def record_observation(
    *,
    kind: str,
    payload: Optional[dict[str, Any]] = None,
    source: str = "",
    instrument=None,
) -> Optional[int]:
    """Append a BrainObservation. Returns the observation id, or None on error.

    Never raises — observation recording must not block the caller.
    """
    try:
        from .models import BrainObservation
        obs = BrainObservation.objects.create(
            kind=kind or "unknown",
            payload=payload or {},
            source_agent=source or "",
            instrument=instrument,
        )
        return obs.id
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("[brain] record_observation(%s) failed: %s", kind, exc)
        return None


def unconsumed_count(kind: Optional[str] = None) -> int:
    """How many observations are queued for the next brain run."""
    try:
        from .models import BrainObservation
        qs = BrainObservation.objects.filter(consumed_by_brain_at__isnull=True)
        if kind:
            qs = qs.filter(kind=kind)
        return qs.count()
    except Exception:
        return 0
