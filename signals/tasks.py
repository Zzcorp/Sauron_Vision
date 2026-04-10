"""Celery tasks for signal detection — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


def _create_signals_and_notify(results):
    """
    Shared helper: persist signal results to the DB, notify users, and
    return the count of newly-created signals.

    All imports are lazy to avoid circular-import issues at module load time.
    """
    from signals.models import Signal

    new_count = 0

    for result in results:
        if not result:
            continue

        instrument = result.get("instrument")
        rule_name = result.get("rule_name")

        if not instrument or not rule_name:
            logger.warning("Signal result missing instrument or rule_name — skipping: %s", result)
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
