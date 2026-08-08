"""Celery tasks for Phase 37 — brain synthesizer + calibration resolver."""
from __future__ import annotations

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="brain.tasks.run_sauron_mind")
def run_sauron_mind() -> dict:
    """Beat task — every 30min. Runs one synthesis cycle."""
    from .synthesizer import synthesize_now
    return synthesize_now()


@shared_task(name="brain.tasks.resolve_brain_predictions")
def resolve_brain_predictions() -> dict:
    """Beat task — every hour. Resolves Sauron Mind predictions whose
    deadline has passed by checking ground truth in the database."""
    from .calibration import resolve_due_brain_predictions
    return resolve_due_brain_predictions()


@shared_task(name="brain.tasks.run_critic_pass")
def run_critic_pass(*, max_n: int = 5) -> dict:
    """Beat task — every 30 min. Audits up to `max_n` pending hypotheses
    via the Opus 4.7 critic agent. Bounded cost ($0.50-1.50/day target)."""
    from .critic import run_critic_pass as run
    return run(max_n=max_n)


@shared_task(name="brain.tasks.run_consolidation")
def run_consolidation() -> dict:
    """Beat task — nightly 03:00 UTC. Promotes settled facts into the
    knowledge graph, prunes stale observations, resolves due hypotheses."""
    from .consolidation import consolidate_now
    return consolidate_now()


@shared_task(name="brain.tasks.run_strategist")
def run_strategist() -> dict:
    """Beat task — daily 06:00 UTC. Produces a user-facing briefing using
    the full Sauron stack (brain + knowledge graph + hypothesis market)."""
    from .strategist import run_strategist_now
    return run_strategist_now()


@shared_task(name="brain.tasks.run_strategy_generator")
def run_strategy_generator(*, max_proposals: int = 3) -> dict:
    """Beat task — weekly Sun 04:00 UTC. Proposes 1-3 new OpportunitySetups
    by composing existing evaluators in novel ways. Land at is_active=False
    pending admin approval."""
    from .strategy_generator import generate_strategies_now
    return generate_strategies_now(max_proposals=max_proposals)


@shared_task(name="brain.tasks.run_auto_demoter")
def run_auto_demoter() -> dict:
    """Beat task — daily 04:30 UTC. Walks active auto-generated rules and
    demotes those meeting kill criteria (hypothesis refuted / sustained
    negative / consecutive losses)."""
    from .demoter import scan_generated_rules_now
    return scan_generated_rules_now()


@shared_task(name="brain.tasks.run_earnings_reviewer")
def run_earnings_reviewer() -> dict:
    """Beat task — every 4h. Walks recent earnings events for held symbols
    and dispatches the EarningsReviewerAgent (Opus 4.7) to produce a deep
    AI review per (instrument, event)."""
    from .earnings_reviewer import scan_due_earnings_now
    return scan_due_earnings_now()


@shared_task(name="brain.tasks.run_anomaly_scanner")
def run_anomaly_scanner() -> dict:
    """Beat task — every 30 min, paired with brain synthesis. Pure-Python
    detectors emit `anomaly_detected` BrainObservations; the brain consumes
    them in its next snapshot and consolidation promotes recurring ones."""
    from .anomaly_scanner import scan_anomalies_now
    return scan_anomalies_now()
