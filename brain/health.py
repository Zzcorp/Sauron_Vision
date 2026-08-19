"""Phase 46 — operational health checks for the brain stack.

Two checks:

  check_brain_failure_rate()
    Inspects the most recent BrainReports. If the last N (default 3)
    consecutive reports have non-empty `error` fields, the synthesizer is
    stuck. Fires a staff-only system_health notification (cooldown-deduped).

  check_critic_dissent_rate()
    Compares the count of critic dissent votes to total critic votes over
    the last 30 days. A healthy critic dissents on roughly 15-30% of
    hypotheses. If outside [5%, 50%] band, something's miscalibrated.

Both are best-effort — failures inside the checks don't propagate.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Brain failure rate ────────────────────────────────────────────────────

DEFAULT_FAILURE_STREAK = 3
DEFAULT_FAILURE_LOOKBACK_HOURS = 3


def check_brain_failure_rate(*,
                                streak: int = DEFAULT_FAILURE_STREAK,
                                lookback_hours: int = DEFAULT_FAILURE_LOOKBACK_HOURS
                                ) -> dict:
    """Inspect the most recent `streak` BrainReports.

    Returns:
      {
        "alert": bool,                    # True iff all `streak` are errored
        "consecutive_failures": int,
        "last_error": str,                # most recent error message (truncated)
        "n_examined": int,
      }
    """
    try:
        from .models import BrainReport
    except Exception:
        return {"alert": False, "consecutive_failures": 0,
                "last_error": "", "n_examined": 0}

    cutoff = timezone.now() - timedelta(hours=lookback_hours)
    recent = list(BrainReport.objects.filter(created_at__gte=cutoff)
                   .order_by("-created_at")[:streak])
    if len(recent) < streak:
        # Not enough data yet (system warming up) — don't false-positive.
        return {"alert": False, "consecutive_failures": 0,
                "last_error": "",
                "n_examined": len(recent)}

    n_failed = sum(1 for r in recent if r.error)
    alert = n_failed == streak
    return {
        "alert": alert,
        "consecutive_failures": n_failed,
        "last_error": (recent[0].error or "")[:300],
        "n_examined": len(recent),
    }


def maybe_alert_brain_failures() -> dict:
    """Run the check and dispatch a staff alert if triggered. Idempotent
    via the cooldown in `notify_staff`."""
    result = check_brain_failure_rate()
    if not result.get("alert"):
        return {"alerted": False, **result}

    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title=(f"▲ Sauron's Mind: {result['consecutive_failures']} "
                   f"consecutive synthesis failures"),
            body=(f"Last error: {result['last_error']}\n\n"
                  f"Investigate the brain synthesizer — agents are "
                  f"running without fresh shared context."),
            url="/brain/",
            cooldown_hours=3,
        )
        return {"alerted": True, **result}
    except Exception as e:  # pragma: no cover
        logger.warning("[brain-health] notify_staff failed: %s", e)
        return {"alerted": False, **result}


# ── Critic dissent rate ──────────────────────────────────────────────────

DEFAULT_DISSENT_LOOKBACK_DAYS = 30
DEFAULT_DISSENT_MIN_VOTES = 10
DEFAULT_DISSENT_LOWER_BAND = 0.05  # 5%
DEFAULT_DISSENT_UPPER_BAND = 0.50  # 50%


def check_critic_dissent_rate(*,
                                  lookback_days: int = DEFAULT_DISSENT_LOOKBACK_DAYS,
                                  min_votes: int = DEFAULT_DISSENT_MIN_VOTES,
                                  lower: float = DEFAULT_DISSENT_LOWER_BAND,
                                  upper: float = DEFAULT_DISSENT_UPPER_BAND
                                  ) -> dict:
    """Compute the critic's dissent rate over the lookback window.

    Returns:
      {
        "alert": bool,                       # True iff outside [lower, upper]
        "dissent_rate": float | None,
        "n_dissents": int,
        "n_votes": int,
        "direction": "too_low" | "too_high" | "ok" | "insufficient_data"
      }

    Healthy band default: 5%-50%. Below 5% suggests the critic is
    rubber-stamping; above 50% suggests it's defaulting to dissent (or
    the source agents have catastrophically degraded).
    """
    try:
        from .knowledge_models import HypothesisVote
    except Exception:
        return {"alert": False, "dissent_rate": None,
                "n_dissents": 0, "n_votes": 0, "direction": "insufficient_data"}

    cutoff = timezone.now() - timedelta(days=lookback_days)
    votes = HypothesisVote.objects.filter(
        agent="critic", created_at__gte=cutoff,
    )
    n_votes = votes.count()
    if n_votes < min_votes:
        return {"alert": False, "dissent_rate": None,
                "n_dissents": 0, "n_votes": n_votes,
                "direction": "insufficient_data"}

    n_dissents = votes.filter(stance="dissent").count()
    rate = n_dissents / n_votes
    if rate < lower:
        direction = "too_low"
    elif rate > upper:
        direction = "too_high"
    else:
        direction = "ok"
    return {
        "alert": direction in ("too_low", "too_high"),
        "dissent_rate": round(rate, 4),
        "n_dissents": n_dissents,
        "n_votes": n_votes,
        "direction": direction,
    }


def maybe_alert_critic_dissent_rate() -> dict:
    """Run the check and dispatch a staff alert if triggered."""
    result = check_critic_dissent_rate()
    if not result.get("alert"):
        return {"alerted": False, **result}

    rate = result["dissent_rate"]
    direction = result["direction"]
    title_suffix = ("rubber-stamping (too low)" if direction == "too_low"
                     else "over-dissenting (too high)")
    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title=(f"▲ Critic dissent rate {rate:.0%} — {title_suffix}"),
            body=(f"Last 30d: {result['n_dissents']} dissents / "
                   f"{result['n_votes']} votes. Healthy band 5-50%. "
                   "If too low: the critic isn't catching bad hypotheses "
                   "— review its system prompt. If too high: agents may "
                   "be producing low-quality hypotheses that warrant "
                   "investigation rather than the critic itself."),
            url="/hypotheses/",
            cooldown_hours=24,  # daily during nightly consolidation
        )
        return {"alerted": True, **result}
    except Exception as e:  # pragma: no cover
        logger.warning("[critic-health] notify_staff failed: %s", e)
        return {"alerted": False, **result}


# ── Phase-57 — operator override-rate threshold alert ───────────────────

DEFAULT_OVERRIDE_ALERT_THRESHOLD = 0.7
DEFAULT_OVERRIDE_ALERT_LOOKBACK_DAYS = 7
DEFAULT_OVERRIDE_ALERT_MIN_DECISIONS = 5

# Agents whose override rate is meaningful (have admin approve/reject flow).
TRACKED_OVERRIDE_AGENTS = ("strategy_generator", "demoter")


def check_override_rate(agent: str, *,
                          threshold: float = DEFAULT_OVERRIDE_ALERT_THRESHOLD,
                          lookback_days: int = DEFAULT_OVERRIDE_ALERT_LOOKBACK_DAYS,
                          min_decisions: int = DEFAULT_OVERRIDE_ALERT_MIN_DECISIONS,
                          ) -> dict:
    """Returns:
      {
        "alert": bool,
        "agent": str,
        "rate": float | None,
        "n_decisions": int,
        "direction": "too_high" | "ok" | "insufficient_data",
      }

    Alerts when the agent's override rate over `lookback_days` exceeds
    `threshold` AND there are enough decisions (`min_decisions`) to call
    it a real signal vs noise.
    """
    try:
        from bot_program.audit_models import AuditLogEntry
        from bot_program.audit_queries import _agent_decision_kinds
    except Exception:
        return {"alert": False, "agent": agent, "rate": None,
                "n_decisions": 0, "direction": "insufficient_data"}

    affirm_kind, override_kind = _agent_decision_kinds(agent)
    if affirm_kind is None or override_kind is None:
        return {"alert": False, "agent": agent, "rate": None,
                "n_decisions": 0, "direction": "insufficient_data"}

    cutoff = timezone.now() - timedelta(days=max(1, int(lookback_days)))
    base = AuditLogEntry.objects.filter(created_at__gte=cutoff)
    n_affirm = base.filter(kind=affirm_kind).count()
    n_override = base.filter(kind=override_kind).count()
    n_decisions = n_affirm + n_override
    if n_decisions < min_decisions:
        return {"alert": False, "agent": agent, "rate": None,
                "n_decisions": n_decisions, "direction": "insufficient_data"}

    rate = round(n_override / n_decisions, 4)
    direction = "too_high" if rate > threshold else "ok"
    return {
        "alert": rate > threshold,
        "agent": agent, "rate": rate, "n_decisions": n_decisions,
        "n_overrides": n_override, "direction": direction,
        "threshold": threshold, "lookback_days": lookback_days,
    }


def maybe_alert_override_rates(agents=TRACKED_OVERRIDE_AGENTS) -> list[dict]:
    """Run override-rate check on each tracked agent; dispatch a staff alert
    when an agent exceeds the threshold. Returns a list of result dicts
    (one per agent checked), each with `alerted` flag added."""
    out = []
    try:
        from bot_program.notifications import notify_staff
    except Exception:
        notify_staff = None

    for agent in agents:
        result = check_override_rate(agent)
        if not result.get("alert"):
            out.append({"alerted": False, **result})
            continue
        if notify_staff is None:
            out.append({"alerted": False, **result})
            continue
        try:
            rate = result["rate"]
            n_dec = result["n_decisions"]
            n_ov = result["n_overrides"]
            notify_staff(
                title=(f"▲ Operator override rate {rate:.0%} on {agent} "
                       f"(last {result['lookback_days']}d)"),
                body=(f"{n_ov} overrides / {n_dec} decisions over the last "
                       f"{result['lookback_days']} days. Threshold "
                       f"{result['threshold']:.0%}. "
                       "The operator is consistently disagreeing with this "
                       "agent — review its prompt or pause it pending "
                       "iteration."),
                url="/intelligence/",
                cooldown_hours=24,  # daily during consolidation
            )
            out.append({"alerted": True, **result})
        except Exception as e:  # pragma: no cover
            logger.warning("[override-health] notify_staff failed for %s: %s",
                            agent, e)
            out.append({"alerted": False, **result})
    return out
