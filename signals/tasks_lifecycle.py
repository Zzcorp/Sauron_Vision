"""Celery tasks for SmcSignal lifecycle and hit-rate maintenance."""
from celery import shared_task


@shared_task(name="signals.tasks_lifecycle.run_smc_lifecycle")
def run_smc_lifecycle():
    """Run one lifecycle pass over all open SmcSignals."""
    from signals.lifecycle import run_lifecycle_pass
    return run_lifecycle_pass()


@shared_task(name="signals.tasks_lifecycle.scan_smc_universe")
def scan_smc_universe(symbols=None, timeframes=None):
    """Scan a list of symbols across timeframes, persist new cards."""
    from signals.mtf import scan_symbol_mtf
    from signals.rules.smc_rules import persist_cards

    if symbols is None:
        try:
            from instruments.models import Instrument
            symbols = list(
                Instrument.objects.filter(is_active=True).values_list("symbol", flat=True)[:50]
            )
        except Exception:
            symbols = []
    timeframes = timeframes or ["1h", "4h", "1d"]
    total = 0
    for sym in symbols:
        try:
            cards = scan_symbol_mtf(sym, timeframes=timeframes)
            for tf in timeframes:
                tf_cards = [c for c in cards if c["timeframe"] == tf]
                if tf_cards:
                    persist_cards(tf_cards, sym, tf)
                    total += len(tf_cards)
        except Exception:
            continue
    return {"scanned_symbols": len(symbols), "persisted_cards": total}


@shared_task(name="signals.tasks_lifecycle.run_signal_lifecycle")
def run_signal_lifecycle():
    """One evaluation pass over every active plain Signal row (Phase 1).

    Stamps MFE/MAE and closes stop/target/expiry outcomes so realized_r is
    populated in production — the decay detector, actuator, meta-allocator,
    promotion pipeline and evolution all read from it. Mirrors the SmcSignal
    lifecycle pass above.
    """
    import logging

    from signals.models import Signal
    from signals.performance import evaluate_signal_outcome

    logger = logging.getLogger(__name__)

    counts = {"evaluated": 0, "closed": 0, "no_price": 0, "errors": 0}
    qs = (Signal.objects.filter(is_active=True)
          .select_related("instrument", "instrument__live_quote"))
    for sig in qs:
        # One bad row must not starve the rest of the pass.
        try:
            outcome = evaluate_signal_outcome(sig)
        except Exception:
            logger.exception("signal lifecycle failed for Signal pk=%s", sig.pk)
            counts["errors"] += 1
            continue
        counts["evaluated"] += 1
        if outcome is None:
            counts["no_price"] += 1
        elif outcome != "active":
            counts["closed"] += 1
    return counts
