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
