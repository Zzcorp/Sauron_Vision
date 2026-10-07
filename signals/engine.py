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
        from signals.rules import (
            technical_rules, macro_rules, flow_rules, smc_engine_rule,
        )
        # NO RULE WITHOUT A SOURCE (2026-10-07). sentiment_velocity_spike
        # and earnings_surprise were loaded here from 2026-04-09 (a10b2c9)
        # and never fired: each imported a model that has never existed
        # (scraping.models.SocialPost, scraping.models.EarningsEvent) inside
        # an `except: return None`, so every pass "scanned" them and the
        # /evolution/ registry listed them as families the engine runs.
        # Both modules are deleted (git history keeps them). No stored
        # source can feed the first: SentimentSnapshot.volume is the size of
        # one StockTwits page, not a count per hour. The second has one
        # (market_data.EconomicEvent, read by the `pead` evaluator), but a
        # rule with no RuleControl row votes as paper in decide(), so it
        # comes back only in its own change, born at research.
        # tests/test_dead_names.py checks that every import in a rule module
        # names something real.
        self.rules.extend(technical_rules.get_rules())
        self.rules.extend(macro_rules.get_rules())
        self.rules.extend(flow_rules.get_rules())
        self.rules.extend(smc_engine_rule.get_rules())

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
