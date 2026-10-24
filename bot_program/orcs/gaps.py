"""THE GAP MODEL (spec §3.6, §2.2 I3 h): how far a price can jump past a
stop through a print, a weekend or a session shut, MEASURED on the venue's
own 1h bars (bot_program/orcs/bars.py), never assumed.

  print       the p90 of the 1h bar's range at this event title's past
              prints, on the currencies the care reads for this row
              (position_care.event_for: either leg of a pair; the home
              currency, USD, for every other class)
  weekend     the p90 of |Monday's first open - Friday's last close|, the
              shuts found by the session clock (market_clock)
  overnight   stock, ETF and index: the p90 of |open - previous close|
              across a session shut that is not a weekend
  range       a class that never shuts (crypto): the p90 of the 1h range
              over GAP_RANGE_DAYS days

A gap with fewer than GAP_MIN_SAMPLES samples (CORSAIR_GAP_MIN_SAMPLES for
the Corsairs) is UNMEASURED, and an unmeasured gap refuses what leans on
it: a lock waiver, an add. In O1 nothing binds on it: the army type reads
the next shut's gap at birth, and the playbook lists P-HOLD only when the
waiver check clears. Memoised for the day in the Django cache. Reads only.
"""
import logging
import math
from dataclasses import dataclass
from datetime import timedelta

from bot_program.orcs.constants import (EVENT_WAIVER_FLOOR_R,
                                        GAP_LOOKBACK_DAYS, GAP_MAX_BARS,
                                        GAP_MIN_SAMPLES, GAP_RANGE_DAYS)

logger = logging.getLogger(__name__)

KIND_PRINT, KIND_WEEKEND, KIND_OVERNIGHT, KIND_RANGE = (
    "print", "weekend", "overnight", "range")
#: Classes whose session closes every night (an overnight gap).
OVERNIGHT_CLASSES = ("stock", "etf", "index")
MEMO_S = 24 * 3600
#: A pause between two 1h bars longer than this is a shut, not a hole.
SHUT_MIN = timedelta(hours=2)


@dataclass(frozen=True)
class Gap:
    kind: str
    key: str
    n: int
    p90: object          # a price distance, or None with no sample
    source: str = ""


def p90(values):
    """The nearest-rank 90th percentile, or None for no value."""
    xs = sorted(float(v) for v in values if v is not None)
    if not xs:
        return None
    return xs[max(0, math.ceil(0.9 * len(xs)) - 1)]


def measured(gap, min_n=GAP_MIN_SAMPLES) -> bool:
    return gap is not None and gap.p90 is not None and gap.n >= int(min_n)


def in_r(gap, risk_per_unit):
    """The gap's p90 in R, or None when unmeasured or without an R."""
    try:
        rpu = float(risk_per_unit)
    except (TypeError, ValueError):
        return None
    if gap is None or gap.p90 is None or rpu <= 0:
        return None
    return float(gap.p90) / rpu


def waiver_check(wc_r, gap, risk_per_unit, floor=EVENT_WAIVER_FLOOR_R, *,
                 min_n=GAP_MIN_SAMPLES) -> tuple:
    """(ok, why, gap_r): the worst case at the stop less the measured gap
    must stay at or above `floor` (§3.6). An unmeasured gap is refused."""
    if not measured(gap, min_n):
        n = gap.n if gap is not None else 0
        return False, (f"the gap is unmeasured ({n} of {int(min_n)} "
                       f"samples)"), None
    gap_r = in_r(gap, risk_per_unit)
    if gap_r is None or wc_r is None:
        return False, "no R to measure the gap against", gap_r
    after = float(wc_r) - gap_r
    if after < float(floor):
        return False, (f"the worst case at the stop less the gap reads "
                       f"{after:+.2f}R, under the {float(floor):+.1f}R "
                       f"floor"), gap_r
    return True, (f"the worst case at the stop less the gap reads "
                  f"{after:+.2f}R"), gap_r


# ── the measurements ─────────────────────────────────────────────────────

def _memo(key, build):
    from django.core.cache import cache
    try:
        hit = cache.get(key)
    except Exception:  # noqa: BLE001 — a dead cache measures again
        hit = None
    if hit is not None:
        return Gap(*hit)
    gap = build()
    try:
        cache.set(key, (gap.kind, gap.key, gap.n, gap.p90, gap.source),
                  MEMO_S)
    except Exception:  # noqa: BLE001
        pass
    return gap


def _key(kind, symbol, key, now):
    import hashlib
    digest = hashlib.sha1(f"{symbol}|{key}".encode()).hexdigest()[:20]
    return f"orcs:gap:{kind}:{digest}:{now:%Y-%m-%d}"


def _hourly(symbol, since, now):
    """The window's 1h venue bars, its NEWEST GAP_MAX_BARS
    (2026-10-22: the oldest 2,200 of a 400-day window measured every
    weekend gap on bars that ended ten months ago)."""
    from bot_program.orcs.bars import complete_bars_after
    return complete_bars_after(symbol, "1h", since, now, limit=GAP_MAX_BARS,
                               newest=True)


def _currencies(symbol, asset_class):
    sym = str(symbol or "").upper()
    if str(asset_class) == "forex" and len(sym) == 6:
        return [sym[:3], sym[3:]]
    from bot_program.position_care import EVENT_HOME_CURRENCY
    return [EVENT_HOME_CURRENCY]


def print_gap(symbol, asset_class, title, ccy=None, *, now,
              lookback_days=GAP_LOOKBACK_DAYS) -> Gap:
    """The p90 of the 1h venue bar's range at this title's past prints."""
    def build():
        try:
            from market_data.models import EconomicEvent
            ccys = [str(ccy).upper()] if ccy else _currencies(symbol,
                                                              asset_class)
            at = list(EconomicEvent.objects
                      .filter(title__iexact=str(title),
                              datetime__lt=now,
                              datetime__gte=now - timedelta(
                                  days=lookback_days),
                              currency_affected__in=ccys)
                      .values_list("datetime", flat=True))
            if not at:
                return Gap(KIND_PRINT, str(title), 0, None, "")
            bars, source = _hourly(symbol, min(at) - timedelta(hours=1), now)
            ranges = []
            for t in at:
                bar = next((b for b in bars if b["ts"] <= t < b["end"]), None)
                if bar is not None:
                    ranges.append(bar["high"] - bar["low"])
            return Gap(KIND_PRINT, str(title), len(ranges), p90(ranges),
                       source)
        except Exception as e:  # noqa: BLE001 — unread is unmeasured
            logger.info("[orcs] %s: print gap unread: %s", symbol, e)
            return Gap(KIND_PRINT, str(title), 0, None, "")
    return _memo(_key(KIND_PRINT, symbol, f"{title}|{ccy or ''}", now),
                 build)


def _shut_pairs(symbol, asset_class, now, days):
    """[(bar before, bar after, weekend?)] across every shut of the 1h
    venue bars in the window, the shut confirmed by the session clock."""
    bars, source = _hourly(symbol, now - timedelta(days=days), now)
    out = []
    from core.exchange_status import market_clock
    for a, b in zip(bars, bars[1:]):
        if b["ts"] - a["end"] < SHUT_MIN:
            continue
        try:
            clock = market_clock(str(asset_class), "", str(symbol),
                                 now_utc=a["end"] + timedelta(minutes=1))
        except Exception:  # noqa: BLE001
            clock = {}
        if clock.get("modelled") and clock.get("is_open"):
            continue                       # a hole in the bars, not a shut
        day, weekend = a["end"].date(), False
        while day <= b["ts"].date():
            if day.weekday() == 5:
                weekend = True
                break
            day += timedelta(days=1)
        out.append((a, b, weekend))
    return out, source


def weekend_gap(symbol, asset_class, *, now,
                days=GAP_LOOKBACK_DAYS) -> Gap:
    def build():
        try:
            pairs, source = _shut_pairs(symbol, asset_class, now, days)
            xs = [abs(b["open"] - a["close"]) for a, b, wk in pairs if wk]
            return Gap(KIND_WEEKEND, "weekend", len(xs), p90(xs), source)
        except Exception as e:  # noqa: BLE001
            logger.info("[orcs] %s: weekend gap unread: %s", symbol, e)
            return Gap(KIND_WEEKEND, "weekend", 0, None, "")
    return _memo(_key(KIND_WEEKEND, symbol, "weekend", now), build)


def overnight_gap(symbol, asset_class, *, now,
                  days=GAP_LOOKBACK_DAYS) -> Gap:
    def build():
        if str(asset_class) not in OVERNIGHT_CLASSES:
            return Gap(KIND_OVERNIGHT, "overnight", 0, None, "")
        try:
            pairs, source = _shut_pairs(symbol, asset_class, now, days)
            xs = [abs(b["open"] - a["close"]) for a, b, wk in pairs
                  if not wk]
            return Gap(KIND_OVERNIGHT, "overnight", len(xs), p90(xs), source)
        except Exception as e:  # noqa: BLE001
            logger.info("[orcs] %s: overnight gap unread: %s", symbol, e)
            return Gap(KIND_OVERNIGHT, "overnight", 0, None, "")
    return _memo(_key(KIND_OVERNIGHT, symbol, "overnight", now), build)


def range_gap(symbol, asset_class, *, now, days=GAP_RANGE_DAYS) -> Gap:
    def build():
        try:
            bars, source = _hourly(symbol, now - timedelta(days=days), now)
            xs = [b["high"] - b["low"] for b in bars]
            return Gap(KIND_RANGE, "range", len(xs), p90(xs), source)
        except Exception as e:  # noqa: BLE001
            logger.info("[orcs] %s: range gap unread: %s", symbol, e)
            return Gap(KIND_RANGE, "range", 0, None, "")
    return _memo(_key(KIND_RANGE, symbol, "range", now), build)


def next_shut_gap(symbol, asset_class, *, now) -> Gap:
    """The gap that stands between now and the next reopen: the weekend's
    or the overnight's by the next shut's kind, the 1h range for a class
    that never shuts."""
    from bot_program.orcs.sessions import NEVER_SHUTS, next_shut
    if str(asset_class) in NEVER_SHUTS:
        return range_gap(symbol, asset_class, now=now)
    try:
        shut = next_shut(asset_class, symbol, now) or {}
    except Exception:  # noqa: BLE001
        shut = {}
    if shut.get("kind") in ("overnight", "break") \
            and str(asset_class) in OVERNIGHT_CLASSES:
        return overnight_gap(symbol, asset_class, now=now)
    return weekend_gap(symbol, asset_class, now=now)
