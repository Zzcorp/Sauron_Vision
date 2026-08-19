"""Phase-11 pattern mining — auto-discover OpportunitySetup candidates from
historical multi-modal data.

Pipeline
--------

  1. **Identify interesting moves** — for each instrument, look at daily PriceData
     over the mining window (default 2 years). Compute forward N-day returns
     (default 5d). A date D is an "interesting move" iff |fwd_return(D)| >= Nσ
     (default 1.5σ). Direction = bullish (positive) or bearish.

  2. **Extract precursor features** — at each interesting move date D, query
     a fixed set of binary feature extractors (price patterns, news volume +
     sentiment, calendar events, macro regimes, sentiment snapshots, etc.).
     Each move becomes a "transaction" — a frozenset of feature keys.

  3. **Mine frequent itemsets** — pure-Python Apriori finds itemsets of size
     2-3 that appear in >= MIN_SUPPORT_FRAC of moves AND have lift >= MIN_LIFT
     over a random control sample of non-move days from the same window.

  4. **Persist as DiscoveredSetup** — each surviving itemset becomes a row
     with `state="proposed"`. Admin reviews at /discoveries/, activates the
     promising ones (creates OpportunitySetup), rejects the rest.

The honest limitation: financial data is noisy. With 200 moves and 15 features,
random baseline alone produces apparent patterns. We mitigate via:
  - High lift threshold (≥ 1.8 by default) — must be markedly more frequent
    than the random baseline.
  - Minimum supporting count (≥ 8 moves) — guards against tiny-N pseudo-patterns.
  - Bonferroni-style adjustment by reporting `n_total_moves` so admin can
    eyeball whether the support count is meaningful.
  - Phase-8 promotion gate kicks in once activated — even a "discovered"
    setup must walk RESEARCH → PAPER → LIVE_SMALL → LIVE_FULL on real data.

Public API
----------

    mine_for_instrument(instrument, lookback_days=730) -> list[DiscoveredSetup]
    mine_all_active(asset_classes=None) -> dict
    activate_discovered_setup(id, user, *, name=None) -> OpportunitySetup
    reject_discovered_setup(id, user) -> DiscoveredSetup
    expire_stale_discoveries() -> int
"""
from __future__ import annotations

import logging
import math
import random
import statistics
from collections import Counter
from datetime import datetime, timedelta
from typing import Callable, Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

DEFAULT_LOOKBACK_DAYS = 730           # 2 years
DEFAULT_FORWARD_DAYS = 5
DEFAULT_SIGMA_THRESHOLD = 1.5
DEFAULT_MIN_SUPPORT_FRAC = 0.10       # itemset appears in ≥ 10% of moves
DEFAULT_MIN_SUPPORT_COUNT = 8         # AND ≥ 8 moves (whichever is larger)
DEFAULT_MIN_LIFT = 1.8                # vs random control days
DEFAULT_MAX_ITEMSET_SIZE = 3
DEFAULT_RANDOM_CONTROL_SIZE = 200     # control sample size

DISCOVERY_TTL_DAYS = 30               # auto-expire stale proposed discoveries


# ── Feature extractors (date-dispatching) ───────────────────────────────────

# Each extractor is `(instrument, date) -> bool`. Date is a `datetime` or `date`;
# we coerce to a tz-aware datetime at midnight UTC if needed.

FeatureFn = Callable[..., bool]
FEATURE_EXTRACTORS: dict[str, FeatureFn] = {}


def _to_datetime(date_or_dt):
    if isinstance(date_or_dt, datetime):
        return date_or_dt
    # Treat as `date` → midnight UTC of that day.
    from datetime import time
    return datetime.combine(date_or_dt, time(0, 0), tzinfo=timezone.utc.utcoffset(None) and None or None) \
        if False else datetime.combine(date_or_dt, datetime.min.time())


def _aware(dt):
    """Ensure a datetime is timezone-aware (use UTC if naive)."""
    if isinstance(dt, datetime) and dt.tzinfo is None:
        from django.utils.timezone import make_aware
        return make_aware(dt)
    return dt


def _feat_price_above_ma(period: int):
    """Factory: feature = close at date > MA(period) just before."""
    def _fn(instrument, dt) -> bool:
        from market_data.models import PriceData
        dt = _aware(dt)
        cutoff = dt - timedelta(days=period * 2 + 5)
        closes = list(
            PriceData.objects
            .filter(instrument=instrument, timeframe="1d",
                    timestamp__lte=dt, timestamp__gte=cutoff)
            .order_by("timestamp").values_list("close", flat=True)
        )
        if len(closes) < period + 1:
            return False
        last = float(closes[-1])
        ma = sum(float(c) for c in closes[-period:]) / period
        return last > ma
    return _fn


def _feat_price_below_ma(period: int):
    def _fn(instrument, dt) -> bool:
        from market_data.models import PriceData
        dt = _aware(dt)
        cutoff = dt - timedelta(days=period * 2 + 5)
        closes = list(
            PriceData.objects
            .filter(instrument=instrument, timeframe="1d",
                    timestamp__lte=dt, timestamp__gte=cutoff)
            .order_by("timestamp").values_list("close", flat=True)
        )
        if len(closes) < period + 1:
            return False
        last = float(closes[-1])
        ma = sum(float(c) for c in closes[-period:]) / period
        return last < ma
    return _fn


def _feat_volatility_high(period: int = 20, threshold_pct: float = 2.0):
    def _fn(instrument, dt) -> bool:
        from market_data.models import PriceData
        dt = _aware(dt)
        cutoff = dt - timedelta(days=period * 2 + 5)
        closes = list(
            PriceData.objects
            .filter(instrument=instrument, timeframe="1d",
                    timestamp__lte=dt, timestamp__gte=cutoff)
            .order_by("timestamp").values_list("close", flat=True)
        )
        if len(closes) < period + 1:
            return False
        log_returns = []
        for i in range(1, len(closes)):
            a = float(closes[i - 1]); b = float(closes[i])
            if a > 0 and b > 0:
                log_returns.append(math.log(b / a))
        if len(log_returns) < period:
            return False
        std_pct = statistics.pstdev(log_returns[-period:]) * 100.0
        return std_pct >= threshold_pct
    return _fn


def _feat_volatility_low(period: int = 20, threshold_pct: float = 1.0):
    fn_high = _feat_volatility_high(period, threshold_pct)
    def _fn(instrument, dt) -> bool:
        from market_data.models import PriceData
        dt = _aware(dt)
        cutoff = dt - timedelta(days=period * 2 + 5)
        closes = list(
            PriceData.objects
            .filter(instrument=instrument, timeframe="1d",
                    timestamp__lte=dt, timestamp__gte=cutoff)
            .order_by("timestamp").values_list("close", flat=True)
        )
        if len(closes) < period + 1:
            return False
        log_returns = []
        for i in range(1, len(closes)):
            a = float(closes[i - 1]); b = float(closes[i])
            if a > 0 and b > 0:
                log_returns.append(math.log(b / a))
        if len(log_returns) < period:
            return False
        std_pct = statistics.pstdev(log_returns[-period:]) * 100.0
        return std_pct <= threshold_pct
    return _fn


def _feat_news_volume_high(min_count: int = 3, lookback_days: int = 2):
    def _fn(instrument, dt) -> bool:
        try:
            from scraping.models import NewsArticle
        except Exception:
            return False
        dt = _aware(dt)
        from django.db.models import Q
        q = (Q(title__icontains=instrument.symbol)
             | Q(content_summary__icontains=instrument.symbol)
             | Q(ai_summary__icontains=instrument.symbol))
        n = NewsArticle.objects.filter(
            q, published_at__gte=dt - timedelta(days=lookback_days),
            published_at__lte=dt,
        ).count()
        return n >= min_count
    return _fn


def _feat_news_sentiment(direction: str, threshold: float, lookback_days: int = 2,
                         min_count: int = 3):
    def _fn(instrument, dt) -> bool:
        try:
            from scraping.models import NewsArticle
            from django.db.models import Q, Avg
        except Exception:
            return False
        dt = _aware(dt)
        q = (Q(title__icontains=instrument.symbol)
             | Q(content_summary__icontains=instrument.symbol)
             | Q(ai_summary__icontains=instrument.symbol))
        qs = NewsArticle.objects.filter(
            q, published_at__gte=dt - timedelta(days=lookback_days),
            published_at__lte=dt, ai_sentiment_score__isnull=False,
        )
        if qs.count() < min_count:
            return False
        avg = qs.aggregate(avg=Avg("ai_sentiment_score"))["avg"] or 0.0
        if direction == "above":
            return float(avg) >= threshold
        return float(avg) <= threshold
    return _fn


def _feat_calendar_high_impact(lookback_days: int = 3):
    def _fn(instrument, dt) -> bool:
        try:
            from market_data.models import EconomicEvent
        except Exception:
            return False
        dt = _aware(dt)
        return EconomicEvent.objects.filter(
            datetime__gte=dt - timedelta(days=lookback_days),
            datetime__lte=dt, impact="high",
        ).exists()
    return _fn


def _feat_cot_extreme(side: str, min_ratio: float = 0.4):
    def _fn(instrument, dt) -> bool:
        try:
            from scraping.models import COTReport
        except Exception:
            return False
        dt = _aware(dt)
        report = (COTReport.objects.filter(instrument=instrument, report_date__lte=dt.date())
                  .order_by("-report_date").first())
        if not report:
            return False
        # In the SYMBOL's frame. The CFTC denominates an FX future in the
        # foreign currency, so the raw column is sign-inverted on the pairs the
        # dollar is the base of — see `opportunity_scanner.cot_sign`. Mined
        # features feed DiscoveredSetup proposals, so an inverted feature here
        # becomes a setup someone is asked to approve.
        from signals.opportunity_scanner import cot_net_speculative
        net = cot_net_speculative(report, instrument)
        total = abs(int(report.non_commercial_long or 0)) + abs(int(report.non_commercial_short or 0))
        if total <= 0:
            return False
        ratio = abs(net) / total
        if side == "long":
            return net > 0 and ratio >= min_ratio
        return net < 0 and ratio >= min_ratio
    return _fn


def _feat_options_unusual(sentiment: str, min_count: int = 3, lookback_days: int = 2):
    def _fn(instrument, dt) -> bool:
        try:
            from scraping.models import OptionsFlow
        except Exception:
            return False
        dt = _aware(dt)
        return OptionsFlow.objects.filter(
            instrument=instrument, is_unusual=True, sentiment=sentiment,
            timestamp__gte=dt - timedelta(days=lookback_days), timestamp__lte=dt,
        ).count() >= min_count
    return _fn


# Register features. The keys are stored as DiscoveredSetup.features and
# mapped to OpportunitySetup conditions by FEATURE_TO_CONDITION below.
FEATURE_EXTRACTORS["price_above_ma_50"] = _feat_price_above_ma(50)
FEATURE_EXTRACTORS["price_above_ma_200"] = _feat_price_above_ma(200)
FEATURE_EXTRACTORS["price_below_ma_50"] = _feat_price_below_ma(50)
FEATURE_EXTRACTORS["price_below_ma_200"] = _feat_price_below_ma(200)
FEATURE_EXTRACTORS["vol_high_20d"] = _feat_volatility_high(20, 2.0)
FEATURE_EXTRACTORS["vol_low_20d"] = _feat_volatility_low(20, 1.0)
FEATURE_EXTRACTORS["news_volume_high_2d"] = _feat_news_volume_high(3, 2)
FEATURE_EXTRACTORS["news_sentiment_positive_2d"] = _feat_news_sentiment("above", 0.3, 2, 3)
FEATURE_EXTRACTORS["news_sentiment_negative_2d"] = _feat_news_sentiment("below", -0.3, 2, 3)
FEATURE_EXTRACTORS["calendar_high_impact_3d"] = _feat_calendar_high_impact(3)
FEATURE_EXTRACTORS["cot_long_extreme"] = _feat_cot_extreme("long", 0.4)
FEATURE_EXTRACTORS["cot_short_extreme"] = _feat_cot_extreme("short", 0.4)
FEATURE_EXTRACTORS["options_unusual_bullish_2d"] = _feat_options_unusual("bullish", 3, 2)
FEATURE_EXTRACTORS["options_unusual_bearish_2d"] = _feat_options_unusual("bearish", 3, 2)


# Translation: feature key → OpportunitySetup condition dict.
# When a DiscoveredSetup is activated, each of its features is converted via
# this table; the resulting list becomes the OpportunitySetup.conditions JSON.
FEATURE_TO_CONDITION: dict[str, dict] = {
    "price_above_ma_50":  {"kind": "price_pattern",
                            "params": {"pattern": "above_ma", "ma_period": 50}},
    "price_above_ma_200": {"kind": "price_pattern",
                            "params": {"pattern": "above_ma", "ma_period": 200}},
    "price_below_ma_50":  {"kind": "price_pattern",
                            "params": {"pattern": "below_ma", "ma_period": 50}},
    "price_below_ma_200": {"kind": "price_pattern",
                            "params": {"pattern": "below_ma", "ma_period": 200}},
    "vol_high_20d":       {"kind": "volatility_regime",
                            "params": {"period": 20, "direction": "above", "threshold_pct": 2.0}},
    "vol_low_20d":        {"kind": "volatility_regime",
                            "params": {"period": 20, "direction": "below", "threshold_pct": 1.0}},
    "news_volume_high_2d":  {"kind": "news_volume",
                              "params": {"min_count": 3, "lookback_days": 2}},
    "news_sentiment_positive_2d": {"kind": "news_sentiment",
                                    "params": {"direction": "above", "threshold": 0.3,
                                               "lookback_days": 2, "min_count": 3}},
    "news_sentiment_negative_2d": {"kind": "news_sentiment",
                                    "params": {"direction": "below", "threshold": -0.3,
                                               "lookback_days": 2, "min_count": 3}},
    "calendar_high_impact_3d": {"kind": "calendar_event",
                                 "params": {"impact": "high", "lookback_days": 3}},
    "cot_long_extreme": {"kind": "cot_report",
                          "params": {"direction": "long_extreme", "min_ratio": 0.4}},
    "cot_short_extreme": {"kind": "cot_report",
                           "params": {"direction": "short_extreme", "min_ratio": 0.4}},
    "options_unusual_bullish_2d": {"kind": "options_flow",
                                    "params": {"sentiment": "bullish", "is_unusual": True,
                                               "min_count": 3, "lookback_days": 2}},
    "options_unusual_bearish_2d": {"kind": "options_flow",
                                    "params": {"sentiment": "bearish", "is_unusual": True,
                                               "min_count": 3, "lookback_days": 2}},
}


# ── Interesting move detection ──────────────────────────────────────────────

def _identify_interesting_moves(instrument, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                                 forward_days: int = DEFAULT_FORWARD_DAYS,
                                 sigma_threshold: float = DEFAULT_SIGMA_THRESHOLD,
                                 now: Optional[datetime] = None) -> list[tuple]:
    """Return list of (datetime, direction, fwd_return) for interesting moves.

    For each daily close at date D in [now - lookback_days, now - forward_days],
    compute fwd_return = close(D + forward_days) / close(D) - 1. If
    |fwd_return| >= sigma_threshold × stdev(all fwd_returns), it's interesting.
    """
    from market_data.models import PriceData
    now = now or timezone.now()

    cutoff = now - timedelta(days=lookback_days + forward_days + 5)
    rows = list(
        PriceData.objects
        .filter(instrument=instrument, timeframe="1d",
                timestamp__gte=cutoff, timestamp__lte=now)
        .order_by("timestamp").values_list("timestamp", "close")
    )
    if len(rows) < forward_days + 30:
        return []

    timestamps = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]

    # Compute forward returns at each index where forward window exists.
    fwd_returns = []
    for i in range(len(closes) - forward_days):
        if closes[i] <= 0:
            continue
        fwd = closes[i + forward_days] / closes[i] - 1
        fwd_returns.append((i, fwd))

    if len(fwd_returns) < 30:
        return []

    values = [v for _, v in fwd_returns]
    sigma = statistics.pstdev(values)
    threshold = sigma_threshold * sigma if sigma > 0 else 0
    if threshold == 0:
        return []

    moves = []
    for i, fwd in fwd_returns:
        if abs(fwd) >= threshold:
            moves.append((timestamps[i], "bullish" if fwd > 0 else "bearish", fwd))
    return moves


def _extract_features(instrument, dt: datetime) -> set[str]:
    """Run all feature extractors at `dt`; return the set of features that fire."""
    fired = set()
    for key, fn in FEATURE_EXTRACTORS.items():
        try:
            if fn(instrument, dt):
                fired.add(key)
        except Exception as e:
            logger.debug("[mine] feature %s failed at %s: %s", key, dt, e)
    return fired


def _sample_random_dates(start_dt: datetime, end_dt: datetime,
                          exclude: set[datetime], n: int = DEFAULT_RANDOM_CONTROL_SIZE,
                          rng: Optional[random.Random] = None) -> list[datetime]:
    """Sample `n` random dates between start and end, excluding the given set.

    Deterministic with `rng=random.Random(seed)`.
    """
    rng = rng or random.Random()
    span_days = max((end_dt - start_dt).days, 1)
    out = []
    attempts = 0
    while len(out) < n and attempts < n * 3:
        offset = rng.randint(0, span_days - 1)
        d = start_dt + timedelta(days=offset)
        if d not in exclude:
            out.append(d)
        attempts += 1
    return out


# ── Apriori (pure Python, capped at MAX_ITEMSET_SIZE) ──────────────────────

def _frequent_itemsets(transactions: list[set], min_count: int,
                        max_size: int = DEFAULT_MAX_ITEMSET_SIZE) -> list[frozenset]:
    """Return all frequent itemsets (size 1..max_size) with count >= min_count."""
    item_counts = Counter()
    for t in transactions:
        for item in t:
            item_counts[item] += 1

    L1 = {frozenset([i]) for i, c in item_counts.items() if c >= min_count}
    if not L1:
        return []

    frequent = list(L1)
    current = L1
    for k in range(2, max_size + 1):
        # Build candidate k-sets by joining current (k-1)-sets sharing k-2 items.
        candidates = set()
        cur_list = list(current)
        for i in range(len(cur_list)):
            for j in range(i + 1, len(cur_list)):
                u = cur_list[i] | cur_list[j]
                if len(u) == k:
                    candidates.add(u)
        new_freq = set()
        for c in candidates:
            count = sum(1 for t in transactions if c.issubset(t))
            if count >= min_count:
                new_freq.add(c)
        frequent.extend(new_freq)
        current = new_freq
        if not current:
            break
    return frequent


# ── Mining pipeline ─────────────────────────────────────────────────────────

class MiningError(Exception):
    pass


def mine_for_instrument(instrument, *,
                         lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                         forward_days: int = DEFAULT_FORWARD_DAYS,
                         sigma_threshold: float = DEFAULT_SIGMA_THRESHOLD,
                         min_support_frac: float = DEFAULT_MIN_SUPPORT_FRAC,
                         min_support_count: int = DEFAULT_MIN_SUPPORT_COUNT,
                         min_lift: float = DEFAULT_MIN_LIFT,
                         max_itemset_size: int = DEFAULT_MAX_ITEMSET_SIZE,
                         random_control_size: int = DEFAULT_RANDOM_CONTROL_SIZE,
                         now: Optional[datetime] = None,
                         seed: Optional[int] = None) -> list:
    """Mine an instrument's history; persist DiscoveredSetup rows. Returns saved list."""
    from signals.models import DiscoveredSetup

    now = now or timezone.now()
    moves = _identify_interesting_moves(
        instrument, lookback_days=lookback_days,
        forward_days=forward_days, sigma_threshold=sigma_threshold, now=now,
    )
    if not moves:
        return []

    # Split by direction.
    by_direction: dict[str, list[datetime]] = {"bullish": [], "bearish": []}
    for ts, direction, _r in moves:
        by_direction[direction].append(ts)

    rng = random.Random(seed) if seed is not None else random.Random()
    saved: list = []

    for direction, dates in by_direction.items():
        if len(dates) < min_support_count:
            continue

        # Build move transactions.
        move_txns: list[set] = []
        for d in dates:
            feats = _extract_features(instrument, d)
            if feats:
                move_txns.append(feats)

        if len(move_txns) < min_support_count:
            continue

        # Build random control transactions for lift baseline.
        control_dates = _sample_random_dates(
            now - timedelta(days=lookback_days), now,
            exclude=set(dates), n=random_control_size, rng=rng,
        )
        control_txns: list[set] = []
        for d in control_dates:
            feats = _extract_features(instrument, d)
            control_txns.append(feats)

        if not control_txns:
            continue

        min_count = max(min_support_count, int(len(move_txns) * min_support_frac))
        frequent = _frequent_itemsets(move_txns, min_count, max_size=max_itemset_size)
        if not frequent:
            continue

        # Skip size-1 itemsets — too noisy on their own to be useful setups.
        frequent = [fs for fs in frequent if len(fs) >= 2]
        if not frequent:
            continue

        for itemset in frequent:
            move_count = sum(1 for t in move_txns if itemset.issubset(t))
            ctrl_count = sum(1 for t in control_txns if itemset.issubset(t))
            move_p = move_count / len(move_txns)
            ctrl_p = (ctrl_count / len(control_txns)) if control_txns else 0
            if ctrl_p <= 0:
                lift = float("inf") if move_p > 0 else 1.0
            else:
                lift = move_p / ctrl_p
            if lift < min_lift:
                continue

            # Direction "hit_rate" — by construction every supporting move had
            # this direction (we filtered by direction above), so this is 1.0
            # against the same-direction set. The figure is more useful when
            # later cross-validated; for now we report 1.0 as a placeholder for
            # the in-direction supporting count.
            ds = DiscoveredSetup.objects.create(
                asset_class=instrument.asset_class or "",
                direction=direction,
                features=sorted(itemset),
                n_supporting_moves=move_count,
                n_total_moves=len(move_txns),
                support=round(move_p, 4),
                lift=round(min(lift, 999.0), 4),
                hit_rate=round(move_count / len(move_txns), 4),
                lookback_days=lookback_days,
                forward_horizon_days=forward_days,
                rationale=(
                    f"Mined from {instrument.symbol}: itemset appears in "
                    f"{move_count}/{len(move_txns)} {direction} moves "
                    f"(p={move_p:.2f}) vs {ctrl_count}/{len(control_txns)} control "
                    f"days (p={ctrl_p:.2f}); lift={lift:.2f}."
                ),
            )
            saved.append(ds)
    return saved


def mine_all_active(*, asset_classes: Optional[list[str]] = None,
                     lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                     now: Optional[datetime] = None,
                     seed: Optional[int] = None) -> dict:
    """Mine across every active instrument, optionally filtered by asset_classes."""
    from instruments.models import Instrument
    qs = Instrument.objects.filter(is_active=True)
    if asset_classes:
        qs = qs.filter(asset_class__in=asset_classes)

    n_instruments = 0
    n_discoveries = 0
    for inst in qs:
        try:
            saved = mine_for_instrument(
                inst, lookback_days=lookback_days, now=now, seed=seed,
            )
            n_discoveries += len(saved)
            n_instruments += 1
        except Exception as e:
            logger.warning("[mine] failed for %s: %s", inst.symbol, e)

    return {"instruments_scanned": n_instruments,
            "discoveries_created": n_discoveries}


# ── Activation / rejection ─────────────────────────────────────────────────

@transaction.atomic
def activate_discovered_setup(discovery_id: int, user, *,
                               name: Optional[str] = None,
                               min_match_score: float = 0.65,
                               horizon_days: int = 5,
                               sizing: Optional[dict] = None) -> "OpportunitySetup":
    """Promote a DiscoveredSetup to a live OpportunitySetup.

    The new OpportunitySetup starts with `is_active=False` so admin can
    review the mapped conditions before the scanner picks it up.
    """
    from signals.models import DiscoveredSetup, OpportunitySetup

    ds = DiscoveredSetup.objects.select_for_update().get(id=discovery_id)
    if ds.state != DiscoveredSetup.STATE_PROPOSED:
        raise MiningError(f"DiscoveredSetup #{discovery_id} is in state {ds.state}.")

    conditions = []
    for feature in ds.features or []:
        cond = FEATURE_TO_CONDITION.get(feature)
        if cond is None:
            logger.warning("[mine] feature %s has no condition mapping; skipping", feature)
            continue
        conditions.append({**cond, "weight": 1.0})

    if not conditions:
        raise MiningError(f"DiscoveredSetup #{discovery_id} has no mappable features.")

    setup_name = name or f"discovered_v{ds.id}_{ds.direction}"
    if OpportunitySetup.objects.filter(name=setup_name).exists():
        n = 1
        while OpportunitySetup.objects.filter(name=f"{setup_name}_{n}").exists():
            n += 1
        setup_name = f"{setup_name}_{n}"

    setup = OpportunitySetup.objects.create(
        name=setup_name,
        description=ds.rationale[:1000],
        direction=ds.direction,
        asset_classes=[ds.asset_class] if ds.asset_class else [],
        conditions=conditions,
        min_match_score=min_match_score,
        suggested_horizon_days=horizon_days,
        sizing=sizing or {"stop_pct": 2.0, "target_rr": 2.0},
        is_active=False,  # admin must enable explicitly
        created_by=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
    )

    ds.state = DiscoveredSetup.STATE_ACTIVATED
    ds.activated_setup = setup
    ds.decided_at = timezone.now()
    ds.decided_by = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    ds.save()

    logger.info("[mine] activated discovery #%s -> setup '%s'", ds.id, setup.name)
    return setup


def reject_discovered_setup(discovery_id: int, user) -> "DiscoveredSetup":
    from signals.models import DiscoveredSetup
    ds = DiscoveredSetup.objects.get(id=discovery_id)
    if ds.state != DiscoveredSetup.STATE_PROPOSED:
        raise MiningError(f"DiscoveredSetup #{discovery_id} is in state {ds.state}.")
    ds.state = DiscoveredSetup.STATE_REJECTED
    ds.decided_at = timezone.now()
    ds.decided_by = user if (user is not None and getattr(user, "is_authenticated", False)) else None
    ds.save()
    return ds


def expire_stale_discoveries(*, now: Optional[datetime] = None) -> int:
    from signals.models import DiscoveredSetup
    now = now or timezone.now()
    cutoff = now - timedelta(days=DISCOVERY_TTL_DAYS)
    qs = DiscoveredSetup.objects.filter(
        state=DiscoveredSetup.STATE_PROPOSED, mined_at__lt=cutoff,
    )
    n = qs.count()
    qs.update(state=DiscoveredSetup.STATE_EXPIRED)
    return n
