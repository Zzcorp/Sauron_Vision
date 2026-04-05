"""Technical analysis signal rules."""


class BaseRule:
    """Base class for signal rules."""
    name = "base_rule"
    signal_type = "technical"

    def evaluate(self, instrument):
        """Override: return a Signal dict if triggered, else None."""
        raise NotImplementedError


class RSIOversoldRule(BaseRule):
    name = "rsi_oversold_bounce"

    def evaluate(self, instrument):
        # TODO: Check if RSI < 30 with bullish divergence
        return None


class MACDCrossoverRule(BaseRule):
    name = "macd_bullish_crossover"

    def evaluate(self, instrument):
        # TODO: Check for MACD line crossing above signal line
        return None


class GoldenCrossRule(BaseRule):
    name = "golden_cross"

    def evaluate(self, instrument):
        # TODO: Check for SMA50 crossing above SMA200
        return None


class BollingerSqueezeRule(BaseRule):
    name = "bollinger_squeeze_breakout"

    def evaluate(self, instrument):
        # TODO: Detect Bollinger Band squeeze followed by expansion
        return None


def get_rules():
    """Return all technical rules."""
    return [
        RSIOversoldRule(),
        MACDCrossoverRule(),
        GoldenCrossRule(),
        BollingerSqueezeRule(),
    ]
