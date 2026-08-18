"""Signal performance — Phase 1.0: the system grades itself.

Two model lifecycles live side-by-side:
  - Signal           (signals.models.Signal)        — multi-asset signal feed
  - SmcSignal        (signals.models_smc.SmcSignal) — SMC setup cards

Both produce a closed outcome with a realized R-multiple. This module is the
single source of truth for grading either, exposing:

  evaluate_signal_outcome(signal, current_price=None)
        Per-tick update for Signal: maintains MFE/MAE, closes on stop/target/expiry,
        and stamps realized_r + time_to_outcome_seconds on close.

  signal_performance_summary(days=30, group_by="signal_type")
        Grouped expectancy for closed Signals — slice by signal_type, asset_class,
        instrument, urgency, or rule_name.

  setup_performance_summary(days=30)
        Per-setup expectancy for closed SmcSignals. Fixes a previously-missing
        callsite — the dashboard widget, lifecycle command, and metrics view all
        import this name.

  decay_flag(rule_name, recent_days=14, baseline_days=90)
        Cheap rolling-window decay detector: True if recent expectancy is materially
        below the baseline.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Q
from django.utils import timezone

import logging
logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Sample size below which a stat is reported as non-empirical (a fallback only).
MIN_EMPIRICAL_N = 5

# Decay flag fires when recent_expectancy < baseline_expectancy * DECAY_RATIO.
DECAY_RATIO = 0.5

# Maximum lifetime for an open Signal before forced expiry.
SIGNAL_TTL_DAYS = 7

# A quote older than this is not a mark-to-market price any more.
MAX_QUOTE_AGE_SECONDS = 900

# A recent bar close is a real traded price too — the same bound the paper
# venue uses for its own marks. LiveQuote pollers cover the watchlist;
# instruments outside it still get 1h/4h bars, and without this fallback
# their signals stayed active FOREVER: the quote path returned None every
# tick, so crossed levels sat in the rail for days and even the 7-day TTL
# could never fire.
MAX_BAR_AGE_SECONDS = 6 * 3600


# ── Helpers ─────────────────────────────────────────────────────────────────

def _compute_realized_r(signal, close_price):
    """R-multiple realized at close, direction-aware.

    R = (close - entry) / risk   for bullish
    R = (entry - close) / risk   for bearish
    where risk = abs(entry - stop). Returns 0.0 if risk is undefined.
    """
    entry = signal.suggested_entry if signal.suggested_entry is not None else signal.price_at_signal
    stop = signal.suggested_stop
    if entry is None or stop is None:
        return 0.0
    risk = abs(Decimal(entry) - Decimal(stop))
    if risk == 0:
        return 0.0
    move = Decimal(close_price) - Decimal(entry)
    if signal.direction == "bearish":
        move = -move
    return float(round(move / risk, 4))


def _update_extremes(signal, current_price):
    """Update MFE (peak favorable) and MAE (peak adverse) in direction-normalized terms.

    For bullish: MFE = highest price seen; MAE = lowest price seen.
    For bearish: MFE = lowest price seen; MAE = highest price seen.

    Returns True if any field was updated (caller should save).
    """
    cp = Decimal(current_price)
    changed = False
    if signal.direction == "bullish":
        if signal.mfe is None or cp > signal.mfe:
            signal.mfe = cp
            changed = True
        if signal.mae is None or cp < signal.mae:
            signal.mae = cp
            changed = True
    elif signal.direction == "bearish":
        if signal.mfe is None or cp < signal.mfe:
            signal.mfe = cp
            changed = True
        if signal.mae is None or cp > signal.mae:
            signal.mae = cp
            changed = True
    return changed


def _bar_close_fallback(instrument):
    """Newest 1h/4h bar close within MAX_BAR_AGE_SECONDS, or None.

    Mirrors PaperTrader.ticker's quote→bar degradation, so a signal is
    graded against the same mark the paper venue would trade it at.
    """
    try:
        from market_data.models import PriceData
        cutoff = timezone.now() - timedelta(seconds=MAX_BAR_AGE_SECONDS)
        return (PriceData.objects.filter(
            instrument=instrument, timeframe__in=("1h", "4h"),
            timestamp__gte=cutoff)
            .order_by("-timestamp")
            .values_list("close", flat=True).first())
    except Exception:
        return None


def _close_signal(signal, outcome, close_price, now):
    """Stamp the final fields and persist.

    Realized R uses the project convention (matches SmcSignal lifecycle):
      - stopped_out          → canonical -1.0R (the planned risk)
      - hit_target           → canonical +RR  (the planned reward, or computed from levels)
      - expired/manual_close → actual close-price-based R (honest mark-to-market)
    """
    signal.outcome = outcome
    signal.is_active = False
    signal.expired_at = now
    if outcome == "stopped_out":
        signal.realized_r = -1.0
    elif outcome == "hit_target":
        signal.realized_r = float(signal.risk_reward_ratio) if signal.risk_reward_ratio \
            else _compute_realized_r(signal, close_price)
    else:
        signal.realized_r = _compute_realized_r(signal, close_price)
    signal.time_to_outcome_seconds = int((now - signal.created_at).total_seconds())
    signal.save(update_fields=[
        "outcome", "is_active", "expired_at",
        "realized_r", "mfe", "mae", "time_to_outcome_seconds",
    ])

    # Phase-3: best-effort auto-journal. The task itself short-circuits when
    # there's no ANTHROPIC_API_KEY, when |R| is below threshold, or when the
    # gate component is off.
    try:
        from ai_agents.tasks import journal_closed_signal_task
        journal_closed_signal_task.delay(signal.id)
    except Exception as e:
        logger.debug("journal_closed_signal_task dispatch failed (continuing): %s", e)


# ── Original Signal lifecycle ───────────────────────────────────────────────

def evaluate_signal_outcome(signal, current_price=None):
    """Per-tick evaluation for an active Signal.

    Updates MFE/MAE on every call, then checks stop/target/expiry. On close,
    records realized_r and time_to_outcome_seconds.

    Returns the outcome string ("hit_target" | "stopped_out" | "expired" | "active")
    or None if the price could not be fetched.
    """
    if not signal.is_active:
        return signal.outcome or None

    if current_price is None:
        # A stale quote here is not harmless: this function stamps
        # realized_r, which feeds decay -> actuator -> allocator and
        # ultimately multiplies live position size. Marking outcomes
        # against a frozen feed silently corrupts sizing.
        try:
            quote = signal.instrument.live_quote
            age = (timezone.now() - quote.updated_at).total_seconds()
            if age <= MAX_QUOTE_AGE_SECONDS:
                current_price = quote.last
            else:
                logger.debug("signal %s: quote %.0fs old — trying bars",
                             signal.pk, age)
        except Exception:
            pass

    if current_price is None:
        current_price = _bar_close_fallback(signal.instrument)

    if current_price is None:
        return None

    now = timezone.now()
    extremes_changed = _update_extremes(signal, current_price)

    cp = Decimal(current_price)

    # Target/stop checks
    if signal.suggested_target is not None:
        target = Decimal(signal.suggested_target)
        if signal.direction == "bullish" and cp >= target:
            _close_signal(signal, "hit_target", current_price, now)
            return "hit_target"
        if signal.direction == "bearish" and cp <= target:
            _close_signal(signal, "hit_target", current_price, now)
            return "hit_target"

    if signal.suggested_stop is not None:
        stop = Decimal(signal.suggested_stop)
        if signal.direction == "bullish" and cp <= stop:
            _close_signal(signal, "stopped_out", current_price, now)
            return "stopped_out"
        if signal.direction == "bearish" and cp >= stop:
            _close_signal(signal, "stopped_out", current_price, now)
            return "stopped_out"

    # Age-based expiry
    if (now - signal.created_at).days > SIGNAL_TTL_DAYS:
        _close_signal(signal, "expired", current_price, now)
        return "expired"

    if extremes_changed:
        signal.save(update_fields=["mfe", "mae"])

    return "active"


# ── Aggregation ─────────────────────────────────────────────────────────────

def _aggregate(qs):
    """Compute hit_rate / expectancy / n / avg duration for a closed-Signal queryset."""
    n = qs.count()
    if n == 0:
        return {
            "n_closed": 0, "hit_rate": None, "expectancy_r": None,
            "avg_duration_h": None, "is_empirical": False,
        }
    hits = qs.filter(outcome="hit_target").count()
    expectancy = qs.exclude(realized_r__isnull=True).aggregate(avg=Avg("realized_r"))["avg"]
    avg_dur_s = qs.exclude(time_to_outcome_seconds__isnull=True).aggregate(
        avg=Avg("time_to_outcome_seconds")
    )["avg"]
    return {
        "n_closed": n,
        "hit_rate": round(hits / n, 4),
        "expectancy_r": round(float(expectancy), 4) if expectancy is not None else None,
        "avg_duration_h": round(avg_dur_s / 3600, 2) if avg_dur_s else None,
        "is_empirical": n >= MIN_EMPIRICAL_N,
    }


def _closed_signal_qs(days):
    """Closed Signals within the given lookback (None = all-time)."""
    from signals.models import Signal
    qs = Signal.objects.filter(is_active=False).exclude(outcome="")
    if days is not None:
        cutoff = timezone.now() - timedelta(days=days)
        qs = qs.filter(expired_at__gte=cutoff)
    return qs


def calculate_signal_stats(days=None, group_by=None):
    """Performance stats for the Signal model.

    days       — lookback window (None = all-time).
    group_by   — None for overall, or one of:
                   "signal_type", "asset_class", "instrument", "urgency", "rule_name".

    Returns a single stats dict (group_by=None) or {group_key: stats_dict, ...}.
    """
    qs = _closed_signal_qs(days)

    if group_by is None:
        return _aggregate(qs)

    # Map group_by → ORM filter key. For asset_class we hop through Instrument.
    keymap = {
        "signal_type": "signal_type",
        "urgency": "urgency",
        "rule_name": "rule_name",
        "instrument": "instrument__symbol",
        "asset_class": "instrument__asset_class",
    }
    if group_by not in keymap:
        raise ValueError(f"Unsupported group_by: {group_by!r}")

    field = keymap[group_by]
    keys = qs.values_list(field, flat=True).distinct()
    return {k: _aggregate(qs.filter(**{field: k})) for k in keys if k}


# ── SmcSignal: setup_performance_summary (the previously-missing function) ──

def setup_performance_summary(days=30):
    """Per-setup expectancy for closed SmcSignals.

    Used by:
      - dashboard.views_signals_htmx.signal_performance_htmx
      - dashboard.views_metrics.signals_metrics
      - signals.management.commands.track_smc_lifecycle
      - upgrade_sauron_14_finish_ui

    Returned shape (matches existing template + caller expectations):
        {
          "RP_BREAKER": {
              "hit_rate": 0..1 | None,
              "expectancy_r": float | None,
              "n_closed": int,
              "is_empirical": bool,
          },
          ...
        }
    Setups with zero closed signals in the window are omitted.
    """
    from signals.models_smc import SmcSignal

    cutoff = timezone.now() - timedelta(days=days)
    closed = SmcSignal.objects.filter(
        status__in=["TARGET_HIT", "STOPPED", "EXPIRED", "INVALIDATED"],
        closed_at__gte=cutoff,
        realized_r__isnull=False,
    )

    out = {}
    for setup in closed.values_list("setup", flat=True).distinct():
        setup_qs = closed.filter(setup=setup)
        n = setup_qs.count()
        if n == 0:
            continue
        hits = setup_qs.filter(status="TARGET_HIT").count()
        expectancy = setup_qs.aggregate(avg=Avg("realized_r"))["avg"]
        out[setup] = {
            "n_closed": n,
            "hit_rate": round(hits / n, 4),
            "expectancy_r": round(float(expectancy), 4) if expectancy is not None else None,
            "is_empirical": n >= MIN_EMPIRICAL_N,
        }
    return out


# ── Decay detection ─────────────────────────────────────────────────────────

def decay_flag(rule_name, recent_days=14, baseline_days=90):
    """Strategy-decay indicator for a given rule_name on the Signal model.

    Returns dict:
        {
          "rule_name": str,
          "recent_expectancy": float | None,
          "baseline_expectancy": float | None,
          "recent_n": int,
          "baseline_n": int,
          "is_decaying": bool,   # True iff both windows are empirical and
                                 # recent_expectancy < baseline_expectancy * DECAY_RATIO
        }
    """
    recent = calculate_signal_stats(days=recent_days)
    baseline = calculate_signal_stats(days=baseline_days)

    # Re-scope to this rule_name specifically.
    from signals.models import Signal
    now = timezone.now()
    base_qs = Signal.objects.filter(
        is_active=False, rule_name=rule_name,
        expired_at__gte=now - timedelta(days=baseline_days),
    ).exclude(outcome="")
    recent_qs = base_qs.filter(expired_at__gte=now - timedelta(days=recent_days))

    r = _aggregate(recent_qs)
    b = _aggregate(base_qs)

    is_decaying = (
        r["is_empirical"] and b["is_empirical"]
        and r["expectancy_r"] is not None and b["expectancy_r"] is not None
        and b["expectancy_r"] > 0
        and r["expectancy_r"] < b["expectancy_r"] * DECAY_RATIO
    )
    return {
        "rule_name": rule_name,
        "recent_expectancy": r["expectancy_r"],
        "baseline_expectancy": b["expectancy_r"],
        "recent_n": r["n_closed"],
        "baseline_n": b["n_closed"],
        "is_decaying": bool(is_decaying),
    }
