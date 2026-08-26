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


# A quote older than this is a fossil, not a price — same convention as
# PaperTrader.MAX_QUOTE_AGE_SECONDS. Signal outcomes graded against a dead
# poller's last print would corrupt the evidence the promotion ladder reads.
MAX_QUOTE_AGE_SECONDS = 900

# How old the newest BAR may be and still count as a price, per timeframe.
# The quote bound above was enforced and the bar fallback right underneath it
# had none at all, which defeated the whole point: a symbol whose ingestion
# had stopped returned the same fossil close on every pass, and every ACTIVE
# card whose stop sat on the wrong side of it was stamped INVALIDATED at
# -1.0R — losses that never happened, fed to get_hit_rate as measurement and
# from there into the composite that sizes live entries. Scaled by timeframe
# because a 1d card's newest bar is legitimately a day old (and four days
# over a long weekend), while a 5m card's is stale within the hour.
MAX_BAR_AGE_SECONDS_BY_TIMEFRAME = {
    "1m": 15 * 60,
    "5m": 60 * 60,
    "15m": 3 * 3600,
    "1h": 6 * 3600,
    "4h": 24 * 3600,
    "1d": 4 * 86400,
}
DEFAULT_MAX_BAR_AGE_SECONDS = 6 * 3600


def _latest_price(symbol, timeframe=None):
    """Best-effort recent price from LiveQuote / PriceData. Returns float or None.

    The LiveQuote branch was dead for the model's whole life: it queried
    `symbol`, `timestamp` and `price` — three fields LiveQuote has never had
    (it is one row per instrument: `instrument`, `last`, `updated_at`) — so
    every call raised FieldError into the bare except and outcome grading
    silently ran on bar closes alone, hours stale on the 4h timeframe.

    Both branches are now age-bounded. None means "no price", and every
    caller must treat that as "do not grade", never as "the price has not
    moved".
    """
    try:
        from django.utils import timezone as tz
        from market_data.models import LiveQuote
        lq = LiveQuote.objects.filter(instrument__symbol__iexact=symbol).first()
        if lq and lq.last:
            age = (tz.now() - lq.updated_at).total_seconds()
            if age <= MAX_QUOTE_AGE_SECONDS:
                return float(lq.last)
    except Exception:
        pass
    try:
        from market_data.models import PriceData
        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol__iexact=symbol).first()
        if inst:
            max_age = MAX_BAR_AGE_SECONDS_BY_TIMEFRAME.get(
                timeframe, DEFAULT_MAX_BAR_AGE_SECONDS)
            cutoff = timezone.now() - timedelta(seconds=max_age)
            pd = (PriceData.objects
                  .filter(instrument=inst, timestamp__gte=cutoff)
                  .order_by("-timestamp").first())
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

    price = _latest_price(sig.symbol, sig.timeframe)

    # Age is answerable without a price, and it has to be answered here or
    # bounding the price lookup above just moves the damage: a symbol whose
    # feed has died would sit ACTIVE forever instead of being graded against
    # a fossil, still occupying the rail and still absent from the sample
    # setup_performance_summary reads.
    if price is None:
        if sig.status == "ACTIVE":
            ttl_hours = TTL_HOURS_BY_TIMEFRAME.get(sig.timeframe, 168)
            if (now - sig.created_at) > timedelta(hours=ttl_hours):
                sig.status = "EXPIRED"
                sig.closed_at = now
                sig.save(update_fields=["status", "closed_at"])
                return sig.status
        else:
            triggered_ttl = TRIGGERED_TTL_HOURS_BY_TIMEFRAME.get(
                sig.timeframe, 336)
            trig_ts = sig.triggered_at or sig.created_at
            if (now - trig_ts) > timedelta(hours=triggered_ttl):
                # realized_r stays NULL: there was no price to mark against,
                # and a fabricated 0.0 would enter the hit-rate evidence as a
                # measurement nobody made.
                sig.status = "EXPIRED"
                sig.closed_at = now
                sig.save(update_fields=["status", "closed_at"])
                return sig.status
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
