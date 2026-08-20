"""Institutional flow rules: funding z-score, OI delta, liquidations."""
from datetime import timedelta
from django.utils import timezone


def _zscore(values):
    import statistics
    if len(values) < 5:
        return 0
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) or 1e-9
    return (values[-1] - mean) / stdev


class FundingExtremeRule:
    name = "funding_rate_extreme"
    signal_type = "flow"

    def evaluate(self, instrument):
        """Funding rate at 2.5+ sigma vs 30-day mean -> contrarian signal."""
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return None
        try:
            from market_data.models import FundingRate
        except Exception:
            return None
        # NEWEST 1000, then flipped back into time order. This used to slice
        # `.order_by("timestamp")[:1000]` — the OLDEST thousand rows of the
        # 30-day window — and then read `rates[-1]` as "the latest print".
        # The futures stream writes a row every 30 seconds, so on any
        # actively streamed symbol the thousand oldest rows are the first
        # eight hours of the month and the "current" funding rate the
        # z-score was measured against was weeks stale.
        try:
            rows = list(FundingRate.objects.filter(
                symbol__iexact=symbol,
                timestamp__gte=timezone.now() - timedelta(days=30),
            ).order_by("-timestamp")[:1000])
        except Exception:
            return None
        rows.reverse()
        if len(rows) < 30:
            return None
        # `.funding_rate`, not `.rate`. There has never been a `rate` field on
        # this model, so every evaluation that got past the 30-row floor
        # raised AttributeError into the caller's except and returned None —
        # this rule has not produced a single signal since it was written,
        # and it failed silently because the caller swallows the exception.
        rates = [float(r.funding_rate) for r in rows]
        z = _zscore(rates)
        if abs(z) < 2.5:
            return None
        direction = "SHORT" if z > 0 else "LONG"
        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": direction,
            "score": min(0.75, 0.4 + abs(z) * 0.1),
            "headline": f"{symbol} {direction} · Funding {z:+.1f}σ extreme",
            "thesis": (
                f"Funding rate at {z:+.1f}σ vs 30d baseline. "
                f"Crowded {'longs' if z > 0 else 'shorts'} — squeeze risk."
            ),
        }


class LiquidationClusterRule:
    name = "liquidation_cluster_bounce"
    signal_type = "flow"

    def evaluate(self, instrument):
        """Large one-sided liquidation cluster in last 15 min -> reversal bias."""
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return None
        try:
            from market_data.models import LiquidationEvent
        except Exception:
            return None
        try:
            recent = LiquidationEvent.objects.filter(
                symbol__iexact=symbol,
                timestamp__gte=timezone.now() - timedelta(minutes=15),
            )
            if not recent.exists():
                return None
            long_liq = sum(float(e.value_usd) for e in recent if e.side == "LONG")
            short_liq = sum(float(e.value_usd) for e in recent if e.side == "SHORT")
        except Exception:
            return None
        total = long_liq + short_liq
        if total < 5_000_000:
            return None
        if long_liq > short_liq * 3:
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.65,
                "headline": f"{symbol} LONG · ${long_liq/1e6:.1f}M long liq cluster",
                "thesis": "Heavy long liquidation flush — local capitulation, bounce setup.",
            }
        if short_liq > long_liq * 3:
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.65,
                "headline": f"{symbol} SHORT · ${short_liq/1e6:.1f}M short liq cluster",
                "thesis": "Heavy short liquidation cascade — squeeze exhaustion, fade.",
            }
        return None


def get_rules():
    return [FundingExtremeRule(), LiquidationClusterRule()]
