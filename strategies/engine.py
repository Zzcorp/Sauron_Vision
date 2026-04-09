"""Strategy engine — builds strategies from signals + portfolio context."""
import logging

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Builds and manages trading strategies from signals + portfolio state."""

    def build_strategy_from_signals(self, signals, portfolio=None):
        """Group signals by direction + asset class, propose a strategy.

        Returns a dict suitable for creating a Strategy row.
        """
        if not signals:
            return None
        long_signals = [s for s in signals if getattr(s, "direction", "") in ("LONG", "long")]
        short_signals = [s for s in signals if getattr(s, "direction", "") in ("SHORT", "short")]

        if len(long_signals) > len(short_signals):
            primary_dir = "long"
            primary = long_signals
        elif short_signals:
            primary_dir = "short"
            primary = short_signals
        else:
            return None

        avg_score = sum(float(getattr(s, "score", 0) or 0) for s in primary) / len(primary)
        symbols = list({getattr(s, "instrument", None) and s.instrument.symbol for s in primary if getattr(s, "instrument", None)})

        return {
            "name": f"Composite {primary_dir} on {', '.join(symbols[:3]) or 'mixed'}",
            "description": f"Built from {len(primary)} aligned signals.",
            "direction": primary_dir,
            "instruments": symbols,
            "confidence": round(avg_score, 3),
            "n_signals": len(primary),
            "time_horizon": "swing",
        }

    def evaluate_strategy_risk(self, strategy, portfolio=None):
        """Check exposure budget vs proposed allocation."""
        try:
            allocation = float(getattr(strategy, "max_portfolio_allocation_pct", 0))
        except (ValueError, TypeError):
            allocation = 0.0
        if allocation > 25:
            return False, "allocation exceeds 25% single-strategy cap"
        return True, "ok"

    def suggest_adjustments(self, strategy, current_data=None):
        """Suggest stop tightening / partial exits based on current data."""
        return {"adjustments": [], "note": "no adjustments computed"}
