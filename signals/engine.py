"""Signal scoring engine — evaluates all rules and produces composite signals."""
import logging
from .models import Signal

logger = logging.getLogger(__name__)


class SignalEngine:
    """Main signal detection and scoring engine."""

    def __init__(self):
        self.rules = []
        self._load_rules()

    def _load_rules(self):
        """Load all signal rule definitions."""
        from signals.rules import technical_rules, sentiment_rules, macro_rules
        self.rules.extend(technical_rules.get_rules())
        self.rules.extend(sentiment_rules.get_rules())
        self.rules.extend(macro_rules.get_rules())

    def scan_instrument(self, instrument) -> list:
        """Run all rules against a single instrument."""
        signals = []
        for rule in self.rules:
            try:
                result = rule.evaluate(instrument)
                if result:
                    signals.append(result)
            except Exception as e:
                logger.error(f"Rule {rule.name} failed for {instrument.symbol}: {e}")
        return signals

    def scan_all(self, instruments=None):
        """Run full signal scan across all instruments."""
        from instruments.models import Instrument

        if instruments is None:
            instruments = Instrument.objects.filter(is_active=True)

        all_signals = []
        for instrument in instruments:
            signals = self.scan_instrument(instrument)
            all_signals.extend(signals)

        logger.info(f"Signal scan complete: {len(all_signals)} signals generated")
        return all_signals
