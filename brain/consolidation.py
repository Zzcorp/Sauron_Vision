"""Phase 38.4 — nightly consolidation.

Once per day (03:00 UTC), this task:

  1. Reads the day's BrainObservations + new Hypotheses + resolved Hypotheses
     + most recent BrainReport.
  2. Promotes settled facts into KnowledgeNodes (regime, theme states,
     rule states, persistent anomalies, narrative threads).
  3. Prunes BrainObservations older than 7 days that didn't lead to a
     hypothesis or knowledge update.
  4. Writes a ConsolidationRun summary row.

Why this matters: it's the *forgetting* mechanism. Without compaction, the
observation queue grows unboundedly and agents drown in noise. The graph
keeps the *signal* (load-bearing facts) and discards the rest.

This is pure-Python — no Claude calls. Cheap and deterministic.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


PRUNE_OBSERVATIONS_OLDER_THAN_DAYS = 7
PRUNE_RESOLVED_HYPOTHESES_OLDER_THAN_DAYS = 30


def _consolidate_regime() -> tuple[bool, bool]:
    """Update the global regime KnowledgeNode from the most recent BrainReport.

    Returns (added, superseded) — each True iff the corresponding action ran.
    """
    from .models import BrainReport
    from .knowledge_models import KnowledgeNode

    report = (BrainReport.objects.filter(error="")
              .order_by("-created_at").first())
    if report is None:
        return False, False

    current = KnowledgeNode.current(KnowledgeNode.KIND_REGIME, "portfolio")
    new_payload = {
        "label": report.regime_label,
        "confidence": report.regime_confidence,
        "as_of": report.created_at.isoformat(),
        "source_report_id": report.id,
    }
    # No-op if state hasn't changed (same label + within ε on confidence).
    if (current and current.payload.get("label") == report.regime_label
            and abs(current.payload.get("confidence", 0)
                     - report.regime_confidence) < 0.05):
        return False, False
    KnowledgeNode.upsert(
        kind=KnowledgeNode.KIND_REGIME, key="portfolio",
        payload=new_payload, confidence=report.regime_confidence,
        source="sauron_mind",
    )
    return True, current is not None


def _consolidate_theme_states() -> tuple[int, int]:
    """For each theme in the most recent BrainReport's theme_pressures, upsert
    a KnowledgeNode `theme_state:<theme>` whose payload tracks the pressure."""
    from .models import BrainReport
    from .knowledge_models import KnowledgeNode

    report = (BrainReport.objects.filter(error="")
              .order_by("-created_at").first())
    if report is None or not report.theme_pressures:
        return 0, 0

    added = superseded = 0
    for theme, pressure in (report.theme_pressures or {}).items():
        try:
            p = float(pressure)
        except (TypeError, ValueError):
            continue
        current = KnowledgeNode.current(KnowledgeNode.KIND_THEME_STATE, theme)
        if current and abs(current.payload.get("pressure", 0) - p) < 0.1:
            continue
        KnowledgeNode.upsert(
            kind=KnowledgeNode.KIND_THEME_STATE, key=str(theme),
            payload={"pressure": p, "as_of": report.created_at.isoformat()},
            confidence=p, source="sauron_mind",
        )
        added += 1
        if current is not None:
            superseded += 1
    return added, superseded


def _consolidate_rule_states() -> tuple[int, int]:
    """For each rule in `rule_status_overlay` of the latest report, upsert
    a `rule_state:<rule_name>` node with the recommended status."""
    from .models import BrainReport
    from .knowledge_models import KnowledgeNode

    report = (BrainReport.objects.filter(error="")
              .order_by("-created_at").first())
    if report is None or not report.rule_status_overlay:
        return 0, 0

    added = superseded = 0
    for rule_name, status in (report.rule_status_overlay or {}).items():
        if status not in ("watch", "pause_recommended"):
            # Only persist exception states; "active" is the default.
            continue
        current = KnowledgeNode.current(
            KnowledgeNode.KIND_RULE_STATE, str(rule_name))
        if current and current.payload.get("status") == status:
            continue
        KnowledgeNode.upsert(
            kind=KnowledgeNode.KIND_RULE_STATE, key=str(rule_name),
            payload={"status": status,
                     "as_of": report.created_at.isoformat(),
                     "source_report_id": report.id},
            confidence=0.7, source="sauron_mind",
        )
        added += 1
        if current is not None:
            superseded += 1
    return added, superseded


def _consolidate_anomalies(min_count: int = 3) -> tuple[int, int]:
    """If the same `anomaly_detected` observation kind has fired ≥ `min_count`
    times in the last 24h with the same `payload['key']`, promote to a
    KnowledgeNode `anomaly:<key>`. Otherwise let it fade."""
    from .models import BrainObservation
    from .knowledge_models import KnowledgeNode

    cutoff = timezone.now() - timedelta(hours=24)
    obs = list(BrainObservation.objects
               .filter(kind="anomaly_detected", created_at__gte=cutoff)
               .values_list("payload", flat=True))
    counter = Counter()
    for p in obs:
        key = (p or {}).get("key") if isinstance(p, dict) else None
        if key:
            counter[key] += 1

    added = superseded = 0
    for key, count in counter.items():
        if count < min_count:
            continue
        current = KnowledgeNode.current(KnowledgeNode.KIND_ANOMALY, key)
        new_payload = {
            "key": key, "occurrences_24h": count,
            "promoted_at": timezone.now().isoformat(),
        }
        if current and current.payload.get("occurrences_24h") == count:
            continue
        KnowledgeNode.upsert(
            kind=KnowledgeNode.KIND_ANOMALY, key=str(key),
            payload=new_payload, confidence=min(1.0, count / 10),
            source="consolidation",
        )
        added += 1
        if current is not None:
            superseded += 1
    return added, superseded


def _prune_observations() -> int:
    """Delete BrainObservations older than the cutoff that have already been
    consumed by the brain (so we don't drop unconsumed events)."""
    from .models import BrainObservation
    cutoff = timezone.now() - timedelta(days=PRUNE_OBSERVATIONS_OLDER_THAN_DAYS)
    deleted, _ = (BrainObservation.objects
                  .filter(created_at__lt=cutoff,
                           consumed_by_brain_at__isnull=False)
                  .delete())
    return deleted


def consolidate_now() -> dict:
    """Run one consolidation cycle. Always returns a summary dict; on
    irrecoverable error the ConsolidationRun gets an `error` field stamped."""
    from .knowledge_models import ConsolidationRun

    run = ConsolidationRun.objects.create()

    # Grading runs FIRST and outside the consolidation block. It used to
    # sit after five graph steps inside their shared `try`, so any one of
    # them raising meant not a single hypothesis was graded that night —
    # silently, and the market's own dashboard would look exactly as it
    # does on a healthy day. Grading owes nothing to the graph.
    resolution = {}
    try:
        from .hypotheses import resolve_due
        resolution = resolve_due()
    except Exception as e:  # pragma: no cover
        logger.warning("[consolidation] resolve_due failed: %s", e)
    n_resolved = (resolution.get("confirmed", 0)
                  + resolution.get("refuted", 0))

    try:
        regime_added, regime_superseded = _consolidate_regime()
        theme_added, theme_superseded = _consolidate_theme_states()
        rule_added, rule_superseded = _consolidate_rule_states()
        anomaly_added, anomaly_superseded = _consolidate_anomalies()
        pruned = _prune_observations()

        run.n_observations_pruned = pruned
        run.n_hypotheses_resolved = n_resolved
        run.n_nodes_added = (
            int(regime_added) + theme_added + rule_added + anomaly_added)
        run.n_nodes_superseded = (
            int(regime_superseded) + theme_superseded
            + rule_superseded + anomaly_superseded)

        # Phase-46 — critic dissent-rate sanity check (best-effort).
        critic_check = {}
        try:
            from .health import maybe_alert_critic_dissent_rate
            critic_check = maybe_alert_critic_dissent_rate()
        except Exception as e:  # pragma: no cover
            logger.warning("[consolidation] critic health check failed: %s", e)

        # Phase-57 — operator override-rate sanity check across tracked agents.
        try:
            from .health import maybe_alert_override_rates
            maybe_alert_override_rates()
        except Exception as e:  # pragma: no cover
            logger.warning("[consolidation] override health check failed: %s", e)

        run.notes = (
            f"regime: +{int(regime_added)}/sup {int(regime_superseded)}; "
            f"themes: +{theme_added}/sup {theme_superseded}; "
            f"rules: +{rule_added}/sup {rule_superseded}; "
            f"anomalies: +{anomaly_added}/sup {anomaly_superseded}; "
            f"pruned: {pruned} obs; "
            f"critic_dissent={critic_check.get('dissent_rate')}"
            f" ({critic_check.get('direction', 'n/a')}); "
            # The counters the run used to throw away. A resolver that
            # crashes deterministically reports `skipped` on every pass
            # forever, and with only confirmed+refuted recorded that
            # stuck row was invisible — the night grading breaks looks
            # identical to a quiet night.
            f"graded: {n_resolved} decided, "
            f"{resolution.get('unresolvable', 0)} unresolvable, "
            f"{resolution.get('deferred', 0)} deferred, "
            f"{resolution.get('skipped', 0)} skipped"
        )
    except Exception as e:
        logger.warning("[consolidation] failed: %s", e)
        run.error = str(e)[:1000]
    finally:
        run.finished_at = timezone.now()
        run.save()

    return {
        "ok": not bool(run.error),
        "run_id": run.id,
        "n_nodes_added": run.n_nodes_added,
        "n_nodes_superseded": run.n_nodes_superseded,
        "n_hypotheses_resolved": run.n_hypotheses_resolved,
        "n_observations_pruned": run.n_observations_pruned,
        "notes": run.notes,
        "error": run.error,
    }
