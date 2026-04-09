"""SmcSignal lifecycle tracker.

State machine:
    ACTIVE       -> TRIGGERED   when entry zone touched
    ACTIVE       -> EXPIRED     when too old without trigger
    ACTIVE       -> INVALIDATED when stop-side level breached before trigger
    TRIGGERED    -> TARGET_HIT  when target reached
    TRIGGERED    -> STOPPED     when stop reached
    TRIGGERED    -> EXPIRED     when held too long without resolution

Realized R is computed at close.
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


# Time-to-live for ACTIVE signals (no trigger): cancel after this many bars-equivalent
TTL_HOURS_BY_TIMEFRAME = {
    "1m": 2, "5m": 6, "15m": 12, "1h": 48, "4h": 168, "1d": 720,
}
# Time-to-live for TRIGGERED signals (no resolution)
TRIGGERED_TTL_HOURS_BY_TIMEFRAME = {
    "1m": 4, "5m": 12, "15m": 24, "1h": 96, "4h": 336, "1d": 1440,
}


def _latest_price(symbol):
    """Best-effort recent price from LiveQuote / PriceData. Returns float or None."""
    try:
        from market_data.models import LiveQuote
        lq = LiveQuote.objects.filter(symbol__iexact=symbol).order_by("-timestamp").first()
        if lq and getattr(lq, "price", None):
            return float(lq.price)
    except Exception:
        pass
    try:
        from market_data.models import PriceData
        from instruments.models import Instrument
        for field in ("symbol", "ticker", "code"):
            try:
                inst = Instrument.objects.get(**{field: symbol})
                break
            except Exception:
                inst = None
        if inst:
            pd = PriceData.objects.filter(instrument=inst).order_by("-timestamp").first()
            if pd:
                return float(pd.close)
    except Exception:
        pass
    return None


def _bar_extremes_since(symbol, since_ts):
    """Return (max_high, min_low) of bars since since_ts. Tolerant to schema."""
    try:
        from market_data.models import PriceData
        from instruments.models import Instrument
        inst = None
        for field in ("symbol", "ticker", "code"):
            try:
                inst = Instrument.objects.get(**{field: symbol})
                break
            except Exception:
                continue
        if inst is None:
            return None, None
        qs = PriceData.objects.filter(instrument=inst, timestamp__gte=since_ts)
        rows = list(qs)
        if not rows:
            return None, None
        return (
            max(float(r.high) for r in rows),
            min(float(r.low) for r in rows),
        )
    except Exception:
        return None, None


def transition_signal(sig, now=None):
    """Evaluate one SmcSignal and transition state if warranted.

    Returns the new status string (may be unchanged).
    """
    from signals.models_smc import SmcSignal
    now = now or timezone.now()

    if sig.status not in ("ACTIVE", "TRIGGERED"):
        return sig.status

    price = _latest_price(sig.symbol)
    if price is None:
        return sig.status

    is_long = sig.direction == "LONG"

    # ---- ACTIVE branch ---------------------------------------------------
    if sig.status == "ACTIVE":
        ttl_hours = TTL_HOURS_BY_TIMEFRAME.get(sig.timeframe, 168)
        if (now - sig.created_at) > timedelta(hours=ttl_hours):
            sig.status = "EXPIRED"
            sig.closed_at = now
            sig.save(update_fields=["status", "closed_at"])
            return sig.status

        # Invalidation: stop-side breached before entry was tagged
        if is_long and price <= sig.stop:
            sig.status = "INVALIDATED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
            return sig.status
        if not is_long and price >= sig.stop:
            sig.status = "INVALIDATED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
            return sig.status

        # Trigger: did price tag the entry zone since signal creation?
        hi, lo = _bar_extremes_since(sig.symbol, sig.created_at)
        if hi is not None and lo is not None:
            entry_band_low = min(sig.entry, sig.entry * 0.999)
            entry_band_high = max(sig.entry, sig.entry * 1.001)
            tagged = lo <= entry_band_high and hi >= entry_band_low
            if tagged:
                sig.status = "TRIGGERED"
                sig.triggered_at = now
                sig.save(update_fields=["status", "triggered_at"])
        return sig.status

    # ---- TRIGGERED branch ------------------------------------------------
    triggered_ttl = TRIGGERED_TTL_HOURS_BY_TIMEFRAME.get(sig.timeframe, 336)
    trig_ts = sig.triggered_at or sig.created_at
    if (now - trig_ts) > timedelta(hours=triggered_ttl):
        sig.status = "EXPIRED"
        sig.closed_at = now
        sig.realized_r = _compute_r(sig, price)
        sig.save(update_fields=["status", "closed_at", "realized_r"])
        return sig.status

    hi, lo = _bar_extremes_since(sig.symbol, trig_ts)
    if hi is None or lo is None:
        return sig.status

    if is_long:
        if lo <= sig.stop:
            sig.status = "STOPPED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
        elif hi >= sig.target:
            sig.status = "TARGET_HIT"
            sig.closed_at = now
            sig.realized_r = sig.r_multiple if sig.r_multiple else 1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
    else:
        if hi >= sig.stop:
            sig.status = "STOPPED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
        elif lo <= sig.target:
            sig.status = "TARGET_HIT"
            sig.closed_at = now
            sig.realized_r = sig.r_multiple if sig.r_multiple else 1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])

    return sig.status


def _compute_r(sig, current_price):
    """Realized R-multiple from current price for a partial/expired signal."""
    is_long = sig.direction == "LONG"
    risk = abs(sig.entry - sig.stop)
    if risk <= 0:
        return 0.0
    if is_long:
        return round((current_price - sig.entry) / risk, 2)
    return round((sig.entry - current_price) / risk, 2)


def run_lifecycle_pass():
    """Run one full lifecycle pass over all open SmcSignals."""
    from signals.models_smc import SmcSignal
    qs = SmcSignal.objects.filter(status__in=["ACTIVE", "TRIGGERED"])
    transitions = {"ACTIVE": 0, "TRIGGERED": 0, "TARGET_HIT": 0,
                   "STOPPED": 0, "EXPIRED": 0, "INVALIDATED": 0}
    for sig in qs.iterator():
        try:
            new_status = transition_signal(sig)
            transitions[new_status] = transitions.get(new_status, 0) + 1
        except Exception as e:
            logger.exception("lifecycle transition failed for %s: %s", sig, e)
    return transitions
