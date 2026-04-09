"""Bridge that lets the bot read SmcSignal as a composite score.

Used by bot_program/engine/strategy.py instead of (or in addition to)
the legacy Signal table read.
"""
from datetime import timedelta


def smc_score_for_symbol(symbol, hours=6, max_signals=10):
    """Return (score, reasons) summarizing recent SmcSignals for a symbol.

    Score is in [-1, +1] where +1 = strong long bias, -1 = strong short.
    Computed as average (direction-signed conviction/100) over recent
    ACTIVE/TRIGGERED signals, weighted by rule hit rate.
    """
    try:
        from signals.models_smc import SmcSignal
        from signals.performance import get_hit_rate
        from django.utils import timezone
    except Exception:
        return (0.0, [])

    cutoff = timezone.now() - timedelta(hours=hours)
    try:
        recent = list(
            SmcSignal.objects.filter(
                symbol__iexact=symbol,
                created_at__gte=cutoff,
                status__in=["ACTIVE", "TRIGGERED"],
            ).order_by("-created_at")[:max_signals]
        )
    except Exception:
        return (0.0, [])

    if not recent:
        return (0.0, [])

    weighted_sum = 0.0
    weight_total = 0.0
    setups_seen = {}
    for s in recent:
        sign = 1.0 if s.direction == "LONG" else -1.0
        conv = (s.conviction or 0) / 100.0
        weight = get_hit_rate(s.setup) or 0.5
        weighted_sum += sign * conv * weight
        weight_total += weight
        setups_seen[s.setup] = setups_seen.get(s.setup, 0) + 1

    if weight_total == 0:
        return (0.0, [])

    score = max(-1.0, min(1.0, weighted_sum / weight_total))
    reasons = [
        f"smc {score:+.2f} from {len(recent)} signals: "
        + ", ".join(f"{k}x{v}" for k, v in setups_seen.items())
    ]
    return (score, reasons)
