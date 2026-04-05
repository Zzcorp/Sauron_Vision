"""Signal performance tracking — did the signal make money?"""
from django.utils import timezone
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


def evaluate_signal_outcome(signal):
    """Check if a signal hit its target, stop, or expired."""
    from market_data.models import LiveQuote

    if not signal.is_active:
        return

    try:
        quote = signal.instrument.live_quote
        current_price = quote.last
    except Exception:
        return

    if signal.suggested_target and signal.direction == "bullish":
        if current_price >= signal.suggested_target:
            signal.outcome = "hit_target"
            signal.is_active = False
            signal.expired_at = timezone.now()
            signal.save()
            return "hit_target"

    if signal.suggested_target and signal.direction == "bearish":
        if current_price <= signal.suggested_target:
            signal.outcome = "hit_target"
            signal.is_active = False
            signal.expired_at = timezone.now()
            signal.save()
            return "hit_target"

    if signal.suggested_stop:
        if signal.direction == "bullish" and current_price <= signal.suggested_stop:
            signal.outcome = "stopped_out"
            signal.is_active = False
            signal.expired_at = timezone.now()
            signal.save()
            return "stopped_out"
        if signal.direction == "bearish" and current_price >= signal.suggested_stop:
            signal.outcome = "stopped_out"
            signal.is_active = False
            signal.expired_at = timezone.now()
            signal.save()
            return "stopped_out"

    # Check age — expire after 7 days
    age = (timezone.now() - signal.created_at).days
    if age > 7:
        signal.outcome = "expired"
        signal.is_active = False
        signal.expired_at = timezone.now()
        signal.save()
        return "expired"

    return "active"


def calculate_signal_stats():
    """Calculate overall signal performance statistics."""
    from signals.models import Signal

    closed = Signal.objects.filter(is_active=False).exclude(outcome="")
    total = closed.count()
    if total == 0:
        return {"total": 0}

    hits = closed.filter(outcome="hit_target").count()
    stops = closed.filter(outcome="stopped_out").count()
    expired = closed.filter(outcome="expired").count()

    return {
        "total": total,
        "hit_target": hits,
        "stopped_out": stops,
        "expired": expired,
        "hit_rate": round(hits / total * 100, 1) if total > 0 else 0,
        "stop_rate": round(stops / total * 100, 1) if total > 0 else 0,
    }
