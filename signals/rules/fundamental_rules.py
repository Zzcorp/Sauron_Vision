"""Fundamental rules: earnings surprise, valuation extremes.

Stays minimal because most installs are crypto-focused, but exposes a
working callable the engine can register without erroring.
"""


class EarningsSurpriseRule:
    name = "earnings_surprise"
    signal_type = "fundamental"

    def evaluate(self, instrument):
        try:
            from scraping.models import EarningsEvent
        except Exception:
            return None
        symbol = getattr(instrument, "symbol", None)
        if not symbol:
            return None
        try:
            ev = EarningsEvent.objects.filter(
                symbol__iexact=symbol,
                actual_eps__isnull=False,
                estimate_eps__isnull=False,
            ).order_by("-event_date").first()
        except Exception:
            return None
        if not ev or not ev.estimate_eps:
            return None
        try:
            surprise_pct = (float(ev.actual_eps) - float(ev.estimate_eps)) / abs(float(ev.estimate_eps))
        except Exception:
            return None
        if abs(surprise_pct) < 0.10:
            return None
        direction = "LONG" if surprise_pct > 0 else "SHORT"
        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": direction,
            "score": min(0.7, 0.4 + abs(surprise_pct)),
            "headline": f"{symbol} {direction} · Earnings {surprise_pct:+.0%} surprise",
            "thesis": (
                f"Reported EPS of {ev.actual_eps} vs {ev.estimate_eps} estimate "
                f"({surprise_pct:+.0%} surprise)."
            ),
        }


def get_rules():
    return [EarningsSurpriseRule()]
