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

    from signals.rule_adapter import flatten, normalise

    new_count = 0
    blocked_paused = 0
    unstorable = 0

    # flatten() first: SmcCompositeRule returns a LIST of setups while every
    # other rule returns a dict, and scan_instrument appends whichever it got.
    for raw in flatten(results):
        # normalise() is the translation between the shape rules emit
        # ({symbol, rule, direction: "LONG", headline, thesis, entry, ...})
        # and the shape this table stores ({instrument, rule_name,
        # direction: "bullish", title, description, suggested_entry, ...}).
        # Without it every rule hit was dropped here with a warning.
        fields = normalise(raw)
        if fields is None:
            unstorable += 1
            continue

        instrument = fields["instrument"]
        rule_name = fields["rule_name"]
        result = {**raw, **fields}

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

        signal = Signal.objects.create(is_active=True, **{
            **fields, "sub_scores": result.get("sub_scores") or {},
        })

        new_count += 1
        logger.info("Created signal pk=%s rule=%s instrument=%s", signal.pk, rule_name, instrument)

        # Live banner. Signals were the one thing the operator most wants to
        # know about the moment it happens, and the only events on the socket
        # were fills — so a new setup appeared silently and was discovered
        # later, if at all. Best-effort: a broken socket must never abort a
        # scan that has already persisted its row.
        try:
            from dashboard.consumers import push_eye_event
            from django.contrib.auth.models import User
            payload = {
                "signal_id": signal.pk,
                "symbol": instrument.symbol,
                "title": signal.title,
                "direction": signal.direction,
                "score": round(float(signal.score or 0), 2),
                "rule_name": rule_name,
                "entry": str(signal.suggested_entry or signal.price_at_signal or ""),
                "stop": str(signal.suggested_stop or ""),
                "target": str(signal.suggested_target or ""),
                "rr": signal.risk_reward_ratio,
                "url": "/signals/",
            }
            for u in User.objects.filter(is_active=True, is_staff=True):
                push_eye_event(u, "new_signal", payload)
        except Exception as e:
            logger.debug("new_signal push failed for pk=%s: %s", signal.pk, e)

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

    if unstorable:
        # Loud, because a silent version of exactly this counter is how a bug
        # that discarded 100% of rule output survived the life of the project.
        logger.warning("%d rule result(s) could not be stored as signals — "
                       "see the [rule_adapter] warnings above for each", unstorable)

    if blocked_paused:
        logger.info("Actuator blocked %d signal(s) for paused rules.", blocked_paused)
    return new_count


@shared_task
@guarded_task("pipeline_signals")
def run_signal_scan():
    """Tier 2: signal scan over the watchlist AND every enabled bot's symbols.

    Scanning only the watchlist starved the bots: their symbols got bars but
    never got Signal rows, so decide() could only ever return HOLD.
    """
    from signals.engine import SignalEngine
    from signals.universe import scan_universe

    instruments = scan_universe()
    logger.info("Running signal scan on %d instruments (watchlist + bot symbols)",
                instruments.count())
    results = SignalEngine().scan_all(instruments=instruments)

    new_count = _create_signals_and_notify(results)
    logger.info("Scan complete — %d new signal(s) created.", new_count)
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

# Evidence-adaptive cadence: below this many closed trades in the last
# seven days, the mid-week sweeps skip — there is no new information
# between runs to react to, and extra runs would only chase noise. The
# Sunday run is unconditional so the weekly rhythm is guaranteed.
EVOLUTION_DENSE_MIN_CLOSED_7D = 50


@shared_task
@guarded_task("pipeline_evolution")
def propose_strategy_evolutions(force: bool = False):
    """Phase 9: scan decaying rules with a parameter schema, propose mutations.

    Beat fires this DAILY; the task decides whether today deserves a run.
    Sundays always run. Other days run only when the fleet closed at least
    EVOLUTION_DENSE_MIN_CLOSED_7D trades in the last week — cadence scales
    with the evidence rate instead of the calendar. (Decay-triggered
    proposals bypass this entirely: confirmed decay fires propose_if_fresh
    from the nightly investigator regardless of the day — with or without
    an AI key, since the decay scan and trigger sit before that task's
    key gate. Only the pipeline_ai_decay component switch governs it.)

    Idempotent — proposals accumulate as PROPOSED RuleMutation rows, one
    open set per rule. Admin decides which to apply.
    """
    from datetime import timedelta
    from django.utils import timezone

    # force=True is the operator's "Propose Now" click routed async —
    # a human asking IS the evidence; the cadence gate is for the beat.
    if not force and timezone.now().weekday() != 6:  # 6 = Sunday
        from bot_program.models import AssetBotTrade
        closed_7d = AssetBotTrade.objects.filter(
            status="CLOSED",
            closed_at__gte=timezone.now() - timedelta(days=7)).count()
        if closed_7d < EVOLUTION_DENSE_MIN_CLOSED_7D:
            return {"status": "skipped",
                    "reason": (f"cadence gate: {closed_7d}/"
                               f"{EVOLUTION_DENSE_MIN_CLOSED_7D} closed trades "
                               f"in 7d — weekly rhythm until evidence "
                               f"densifies")}

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
    from signals.pattern_miner import expire_stale_discoveries, mine_all_active

    # This task is the expiry sweep's only production caller — without it,
    # PROPOSED discoveries past DISCOVERY_TTL_DAYS accumulate forever.
    n_expired = expire_stale_discoveries()
    result = mine_all_active()
    logger.info("Pattern mining: %s (expired %s stale)", result, n_expired)
    return result


@shared_task
@guarded_task("pipeline_event_engine")
def dispatch_event_task(event_type, payload=None, source="api"):
    """Async twin of signals.fast_rules.dispatch_event - Phase 12.

    The component registry described this wrapper for as long as the
    component has existed, but it was never written: the switch gated
    nothing, and toggling it changed nothing. It exists now, so anything
    that wants sub-second dispatch without blocking the caller has a real
    path - and switching the component OFF short-circuits here while
    direct synchronous calls to dispatch_event() keep working, exactly as
    the component description promises.
    """
    from signals.fast_rules import dispatch_event

    result = dispatch_event(event_type, payload or {}, source=source)
    return {"status": "success", **result}
