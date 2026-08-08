"""Celery tasks for signal detection — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


def _create_signals_and_notify(results):
    """
    Shared helper: persist signal results to the DB, notify users, and
    return the count of newly-created signals.

    Phase-5: consults `signals.rule_actuator` so paused rules don't produce
    new signals, and reduced rules carry their multiplier in `sub_scores`
    for downstream sizing to honour.

    All imports are lazy to avoid circular-import issues at module load time.
    """
    from signals.models import Signal
    from signals.rule_actuator import is_rule_active, rule_size_multiplier

    new_count = 0
    blocked_paused = 0

    for result in results:
        if not result:
            continue

        instrument = result.get("instrument")
        rule_name = result.get("rule_name")

        if not instrument or not rule_name:
            logger.warning("Signal result missing instrument or rule_name — skipping: %s", result)
            continue

        # Phase-5: skip rules paused by the actuator.
        if not is_rule_active(rule_name):
            logger.info("Rule %s is paused by actuator — dropping signal for %s.",
                        rule_name, instrument)
            blocked_paused += 1
            continue

        # Deduplicate: skip if an active signal for this rule+instrument already exists.
        already_exists = Signal.objects.filter(
            instrument=instrument,
            rule_name=rule_name,
            is_active=True,
        ).exists()

        if already_exists:
            logger.debug(
                "Active signal for rule=%s instrument=%s already exists — skipping.",
                rule_name,
                instrument,
            )
            continue

        # Attach the actuator multiplier — sizing layer reads this via sub_scores.
        sub_scores = dict(result.get("sub_scores") or {})
        rule_mult = rule_size_multiplier(rule_name)
        if rule_mult < 1.0:
            sub_scores["actuator_multiplier"] = rule_mult
        result = {**result, "sub_scores": sub_scores}

        signal = Signal.objects.create(
            instrument=instrument,
            signal_type=result.get("signal_type", ""),
            direction=result.get("direction", ""),
            urgency=result.get("urgency", ""),
            title=result.get("title", ""),
            description=result.get("description", ""),
            rule_name=rule_name,
            score=result.get("score"),
            sub_scores=result.get("sub_scores"),
            price_at_signal=result.get("price_at_signal"),
            suggested_entry=result.get("suggested_entry"),
            suggested_stop=result.get("suggested_stop"),
            suggested_target=result.get("suggested_target"),
            risk_reward_ratio=result.get("risk_reward_ratio"),
            is_active=True,
        )

        new_count += 1
        logger.info("Created signal pk=%s rule=%s instrument=%s", signal.pk, rule_name, instrument)

        # Notify — wrapped individually so a broken notifier never aborts the scan.
        try:
            from alerts.notify import notify_new_signal
            notify_new_signal(signal)
        except Exception:
            logger.exception("notify_new_signal failed for signal pk=%s", signal.pk)

        try:
            from alerts.dispatch import dispatch_signal_alert
            dispatch_signal_alert(signal)
        except Exception:
            logger.exception("dispatch_signal_alert failed for signal pk=%s", signal.pk)

    if blocked_paused:
        logger.info("Actuator blocked %d signal(s) for paused rules.", blocked_paused)
    return new_count


@shared_task
@guarded_task("pipeline_signals")
def run_signal_scan():
    """Tier 2: Run signal scan on watchlist."""
    from instruments.models import Instrument
    from signals.engine import SignalEngine

    logger.info("Running signal scan on watchlist")

    instruments = Instrument.objects.filter(is_watchlist=True, is_active=True)
    results = SignalEngine().scan_all(instruments=instruments)

    new_count = _create_signals_and_notify(results)
    logger.info("Watchlist scan complete — %d new signal(s) created.", new_count)
    return {"status": "ok", "new_signals": new_count}


@shared_task
@guarded_task("pipeline_signals")
def run_full_universe_scan():
    """Tier 5: Daily full universe signal scan."""
    from signals.engine import SignalEngine

    logger.info("Running full universe signal scan")

    results = SignalEngine().scan_all(instruments=None)

    new_count = _create_signals_and_notify(results)
    logger.info("Full universe scan complete — %d new signal(s) created.", new_count)
    return {"status": "ok", "new_signals": new_count}


# ─── Phase 5: rule actuator — closed-loop self-adjustment ─────────────────

@shared_task
@guarded_task("pipeline_evolution")
def propose_strategy_evolutions():
    """Phase 9: scan decaying rules with a parameter schema, propose mutations.

    Idempotent — proposals accumulate as PROPOSED RuleMutation rows. Admin
    decides which to apply.
    """
    from signals.evolution import propose_for_decaying_rules
    result = propose_for_decaying_rules()
    logger.info("Evolution proposer: %d rules decaying with schema, %d proposals",
                result.get("rules_decaying_evolved", 0),
                result.get("total_proposals", 0))
    return {"status": "ok", **result}


@shared_task
@guarded_task("pipeline_promotion")
def auto_evaluate_promotions():
    """Phase 8: walk every RuleControl, auto-promote eligible rules and
    auto-demote degrading ones. Idempotent."""
    from signals.promotion_pipeline import auto_evaluate_all_rules
    result = auto_evaluate_all_rules()
    logger.info("Promotion pipeline: %d promoted, %d demoted",
                result.get("n_promoted", 0), result.get("n_demoted", 0))
    return {"status": "ok", **result}


@shared_task
@guarded_task("pipeline_meta_allocator")
def propose_meta_allocation(lookback_days: int = 180):
    """Phase 7: ensemble meta-allocator. Always proposes in shadow state."""
    from signals.meta_allocator import propose_allocation
    alloc = propose_allocation(lookback_days=lookback_days)
    return {
        "status": "ok",
        "allocation_id": alloc.id,
        "tier": alloc.sample_tier,
        "rules_considered": alloc.rules_considered,
    }


@shared_task
@guarded_task("pipeline_actuator")
def propose_rule_actions():
    """Read recent DecayInvestigations, create RuleAction proposals, expire stale ones.

    Does NOT apply anything — only proposes. Admin must confirm via the HQ
    console (or the actuator must be in live mode AND auto-apply explicitly
    enabled, which it is not by default).
    """
    from signals.rule_actuator import propose_actions_from_decay, expire_stale_proposals

    expired = expire_stale_proposals()
    proposals = propose_actions_from_decay(lookback_days=2)
    logger.info("Actuator: %d new proposal(s), %d stale expired.", proposals, expired)
    return {"status": "ok", "new_proposals": proposals, "expired_proposals": expired}


@shared_task
@guarded_task("pipeline_opportunity_scanner")
def scan_opportunities():
    """Phase 10 — match every active OpportunitySetup against every active
    instrument, creating OpportunityFlags for matches (daily 09:00 UTC)."""
    from signals.opportunity_scanner import scan_all_setups

    result = scan_all_setups()
    logger.info("Opportunity scan: %s", result)
    return result


@shared_task
@guarded_task("pipeline_opportunity_scanner")
def resolve_opportunity_flags():
    """Phase 10 — resolve OpportunityFlags whose evaluation horizon has
    passed, grading each setup's hit/miss record (nightly 23:15 UTC)."""
    from signals.opportunity_scanner import resolve_pending_flags

    result = resolve_pending_flags()
    logger.info("Opportunity flag resolution: %s", result)
    return result


@shared_task
@guarded_task("pipeline_pattern_miner")
def mine_patterns():
    """Phase 11 — mine historical multi-modal data for candidate setups
    (DiscoveredSetup rows, weekly Sunday 06:00 UTC)."""
    from signals.pattern_miner import mine_all_active

    result = mine_all_active()
    logger.info("Pattern mining: %s", result)
    return result
