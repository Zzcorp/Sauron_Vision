"""Adapter that exposes SMC scanning as a BaseRule the existing
SignalEngine can call. The engine sees this as a single rule that returns
a list of detected setups for an instrument.
"""
from signals.rules.technical_rules import BaseRule


class SmcCompositeRule(BaseRule):
    name = "smc_composite"
    signal_type = "composite"

    def __init__(self, timeframe="4h", persist=True):
        self.timeframe = timeframe
        self.persist = persist

    def evaluate(self, instrument):
        """Run SMC scan on this instrument; optionally persist cards.

        Returns a list of cards (the SignalEngine treats truthy returns
        as detections to extend its results with).
        """
        try:
            from signals.rules.smc_rules import scan_symbol, persist_cards
        except Exception:
            return []
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return []
        try:
            cards = scan_symbol(symbol, timeframe=self.timeframe)
        except Exception:
            return []
        if cards and self.persist:
            try:
                persist_cards(cards, symbol, self.timeframe)
            except Exception:
                pass
        return cards


def get_rules():
    """Return SMC rule instance(s) for the engine to load."""
    return [SmcCompositeRule(timeframe="4h", persist=True)]
