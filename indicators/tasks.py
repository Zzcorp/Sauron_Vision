"""Celery tasks for technical indicators — gated.

These were stubs returning {"status": "pending_implementation"} while beat
ran them every 15 minutes and nightly, so `TechnicalIndicator` rows were
never written and anything reading them saw an empty table.
"""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)

# Timeframes worth persisting: 4h is what the rule layer reads, 1d is what
# the dashboards and longer-horizon rules use.
DEFAULT_TIMEFRAMES = ("4h", "1d")
MIN_BARS = 30


def _to_decimal(value):
    """Indicator values arrive as numpy floats; NaN must become NULL."""
    from decimal import Decimal, InvalidOperation
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    try:
        return Decimal(str(round(f, 8)))
    except (InvalidOperation, ValueError):
        return None


def _to_float(value):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def recalculate_for_instruments(instruments, timeframes=DEFAULT_TIMEFRAMES) -> dict:
    """Compute and upsert indicators for each instrument/timeframe.

    Uses the latest bar's timestamp as the row key, so re-running inside the
    same bar updates in place instead of accumulating duplicates.
    """
    from indicators.calculator import compute_all_indicators
    from indicators.models import TechnicalIndicator
    from signals.smc.dataframe import load_ohlcv

    out = {"instruments": 0, "written": 0, "skipped_no_data": 0, "errors": 0}
    for inst in instruments:
        out["instruments"] += 1
        for timeframe in timeframes:
            try:
                df = load_ohlcv(inst.symbol, timeframe, bars=250)
                if df is None or len(df) < MIN_BARS:
                    out["skipped_no_data"] += 1
                    continue
                values = compute_all_indicators(df)
                decimals = {"sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
                            "bollinger_upper", "bollinger_lower", "atr_14"}
                defaults = {}
                for key, raw in values.items():
                    if key == "obv":
                        f = _to_float(raw)
                        defaults[key] = int(f) if f is not None else None
                    elif key in decimals:
                        defaults[key] = _to_decimal(raw)
                    else:
                        defaults[key] = _to_float(raw)
                TechnicalIndicator.objects.update_or_create(
                    instrument=inst, timeframe=timeframe,
                    timestamp=df.index[-1].to_pydatetime(),
                    defaults=defaults,
                )
                out["written"] += 1
            except Exception as e:
                logger.warning("[indicators] %s %s failed: %s",
                               inst.symbol, timeframe, e)
                out["errors"] += 1
    return out


@shared_task
@guarded_task("pipeline_indicators")
def recalculate_watchlist_indicators():
    """Tier 2: recalculate indicators for the watchlist AND bot symbols."""
    from signals.universe import scan_universe

    result = recalculate_for_instruments(scan_universe())
    logger.info("Indicator refresh: %s", result)
    return result


@shared_task
@guarded_task("pipeline_indicators")
def recalculate_all_indicators():
    """Tier 5: nightly full recalculation across every active instrument."""
    from instruments.models import Instrument

    result = recalculate_for_instruments(
        Instrument.objects.filter(is_active=True))
    logger.info("Full indicator recalculation: %s", result)
    return result
