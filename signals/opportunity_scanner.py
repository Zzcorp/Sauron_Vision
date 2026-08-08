"""Phase-10 multi-modal opportunity scanner.

Scans every active OpportunitySetup against every active Instrument, evaluating
each setup's conditions across price/news/calendar/macro/sentiment data sources.
Matches above the setup's `min_match_score` create:

  1. an OpportunityFlag (dashboard-friendly view with conditions breakdown)
  2. a Signal row tagged with the setup's name as `rule_name` — so the match
     flows through every Phase-1-9 lane automatically (grading, decay
     investigation, allocation, promotion gate, evolution).

After `setup.suggested_horizon_days`, a resolver task evaluates whether the
implied move played out, marking the flag hit/miss/neutral. The Signal row's
own outcome flow runs in parallel via Phase-1.

Architecture
-----------

Conditions are tagged by `kind`. Each kind maps to a Python evaluator function
in `EVALUATOR_REGISTRY`. Built-in kinds (this module ships with):

  - `price_pattern`     — "above_ma", "below_ma", "breakout_high",
                          "breakout_low", "rsi_oversold", "rsi_overbought"
  - `news_volume`       — count of relevant news in lookback window ≥ threshold
  - `news_sentiment`    — average AI sentiment of relevant news ≥/≤ threshold
  - `calendar_event`    — economic event matching filter occurred in lookback

Adding a new kind: define an evaluator function and call `register_kind()`.

Public API
----------

    register_kind(kind, fn)
    has_kind(kind) -> bool
    scan_setup(setup, instrument, *, now=None) -> dict
    scan_all_setups(*, now=None) -> dict
    resolve_pending_flags(*, now=None) -> dict
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from django.db.models import Avg
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

DEFAULT_MA_PERIOD = 50
DEFAULT_RSI_PERIOD = 14
DEFAULT_BREAKOUT_LOOKBACK = 20

# Resolution band: |move| < this fraction × ATR-equivalent → "neutral".
NEUTRAL_BAND_PCT = 0.5  # %, used when ATR is unavailable
ATR_FALLBACK_PCT = 2.0  # default 2% stop when ATR can't be computed


# ── Evaluator registry ──────────────────────────────────────────────────────

EvaluatorFn = Callable[[dict, "Instrument", datetime], dict]
EVALUATOR_REGISTRY: dict[str, EvaluatorFn] = {}


def register_kind(kind: str, fn: EvaluatorFn) -> None:
    if not callable(fn):
        raise TypeError("evaluator must be callable(params, instrument, now) -> dict")
    EVALUATOR_REGISTRY[kind] = fn


def has_kind(kind: str) -> bool:
    return kind in EVALUATOR_REGISTRY


# ── Built-in evaluators ─────────────────────────────────────────────────────

def _recent_closes(instrument, lookback: int, now: datetime, timeframe: str = "1d"):
    """Helper: return the last `lookback` closes (oldest first) up to `now`."""
    from market_data.models import PriceData
    cutoff = now - timedelta(days=lookback * 2)  # wide net for daily bars
    qs = (PriceData.objects
          .filter(instrument=instrument, timeframe=timeframe, timestamp__lte=now,
                  timestamp__gte=cutoff)
          .order_by("timestamp")
          .values_list("close", flat=True))
    closes = [float(c) for c in qs]
    return closes[-lookback:] if len(closes) >= lookback else closes


def _eval_price_pattern(params: dict, instrument, now: datetime) -> dict:
    """Detect simple price patterns relative to a moving average / breakout level."""
    pattern = (params or {}).get("pattern", "above_ma")
    period = int((params or {}).get("ma_period", DEFAULT_MA_PERIOD))
    closes = _recent_closes(instrument, max(period, DEFAULT_BREAKOUT_LOOKBACK) + 5, now)
    if len(closes) < 5:
        return {"matched": False, "score": 0.0, "details": {"reason": "insufficient price data"}}

    last = closes[-1]
    if pattern == "above_ma":
        if len(closes) < period:
            return {"matched": False, "score": 0.0, "details": {"reason": f"need {period} closes"}}
        ma = sum(closes[-period:]) / period
        matched = last > ma
        score = min(1.0, max(0.0, (last - ma) / ma * 5)) if matched else 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"last": last, "ma": ma, "period": period}}

    if pattern == "below_ma":
        if len(closes) < period:
            return {"matched": False, "score": 0.0, "details": {"reason": f"need {period} closes"}}
        ma = sum(closes[-period:]) / period
        matched = last < ma
        score = min(1.0, max(0.0, (ma - last) / ma * 5)) if matched else 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"last": last, "ma": ma, "period": period}}

    if pattern == "breakout_high":
        lookback = int((params or {}).get("lookback", DEFAULT_BREAKOUT_LOOKBACK))
        if len(closes) < lookback + 1:
            return {"matched": False, "score": 0.0, "details": {"reason": f"need {lookback+1} closes"}}
        prior_high = max(closes[-(lookback + 1):-1])
        matched = last > prior_high
        score = 1.0 if matched else 0.0
        return {"matched": matched, "score": score,
                "details": {"last": last, "prior_high": prior_high, "lookback": lookback}}

    if pattern == "breakout_low":
        lookback = int((params or {}).get("lookback", DEFAULT_BREAKOUT_LOOKBACK))
        if len(closes) < lookback + 1:
            return {"matched": False, "score": 0.0, "details": {"reason": f"need {lookback+1} closes"}}
        prior_low = min(closes[-(lookback + 1):-1])
        matched = last < prior_low
        score = 1.0 if matched else 0.0
        return {"matched": matched, "score": score,
                "details": {"last": last, "prior_low": prior_low, "lookback": lookback}}

    return {"matched": False, "score": 0.0,
            "details": {"reason": f"unknown pattern '{pattern}'"}}


register_kind("price_pattern", _eval_price_pattern)


def _eval_news_volume(params: dict, instrument, now: datetime) -> dict:
    """Count of news articles mentioning the symbol/keyword in the lookback.

    Optional `sources` filter: list of NewsArticle.source values.
    """
    lookback_days = int((params or {}).get("lookback_days", 2))
    min_count = int((params or {}).get("min_count", 1))
    keywords = (params or {}).get("keywords") or [instrument.symbol]
    sources = (params or {}).get("sources")

    try:
        from scraping.models import NewsArticle
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "NewsArticle model unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    from django.db.models import Q
    q = Q()
    for kw in keywords:
        q |= (Q(title__icontains=kw) | Q(content_summary__icontains=kw)
              | Q(ai_summary__icontains=kw))
    qs = NewsArticle.objects.filter(q, published_at__gte=cutoff, published_at__lte=now)
    if sources:
        qs = qs.filter(source__in=list(sources))
    n = qs.count()
    matched = n >= min_count
    score = min(1.0, n / max(min_count, 1)) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"n": n, "min_count": min_count, "keywords": keywords,
                        "sources": list(sources) if sources else "any"}}


register_kind("news_volume", _eval_news_volume)


def _eval_news_sentiment(params: dict, instrument, now: datetime) -> dict:
    """Average AI sentiment score of relevant news in the lookback ≥/≤ threshold.

    Optional `sources` filter: list of NewsArticle.source values.
    """
    lookback_days = int((params or {}).get("lookback_days", 2))
    keywords = (params or {}).get("keywords") or [instrument.symbol]
    direction = (params or {}).get("direction", "above")  # "above" | "below"
    threshold = float((params or {}).get("threshold", 0.3))
    min_count = int((params or {}).get("min_count", 3))
    sources = (params or {}).get("sources")

    try:
        from scraping.models import NewsArticle
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "NewsArticle model unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    from django.db.models import Q
    q = Q()
    for kw in keywords:
        q |= (Q(title__icontains=kw) | Q(content_summary__icontains=kw)
              | Q(ai_summary__icontains=kw))
    qs = NewsArticle.objects.filter(q, published_at__gte=cutoff, published_at__lte=now,
                                     ai_sentiment_score__isnull=False)
    if sources:
        qs = qs.filter(source__in=list(sources))
    n = qs.count()
    if n < min_count:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"only {n} sentiment-tagged articles", "min_count": min_count}}

    avg = qs.aggregate(avg=Avg("ai_sentiment_score"))["avg"]
    avg = float(avg) if avg is not None else 0.0
    if direction == "above":
        matched = avg >= threshold
        score = min(1.0, max(0.0, (avg - threshold) / max(1.0 - threshold, 1e-6))) if matched else 0.0
    else:
        matched = avg <= threshold
        score = min(1.0, max(0.0, (threshold - avg) / max(threshold + 1.0, 1e-6))) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"avg_sentiment": round(avg, 4), "n": n,
                        "direction": direction, "threshold": threshold,
                        "sources": list(sources) if sources else "any"}}


register_kind("news_sentiment", _eval_news_sentiment)


def _eval_institutional_filings(params: dict, instrument, now: datetime) -> dict:
    """Count of institutional filings (13F-style) for this instrument in the
    lookback window, filterable by change type / filing type / value.

    Params:
      change_type     — "new" | "increase" | "decrease" | "exit" (optional; any if absent)
      filing_type     — e.g. "13F" (optional)
      min_count       — default 1
      lookback_days   — default 30
      min_value_usd   — optional minimum $ value per filing
    """
    change_type = (params or {}).get("change_type")
    filing_type = (params or {}).get("filing_type")
    min_count = int((params or {}).get("min_count", 1))
    lookback_days = int((params or {}).get("lookback_days", 30))
    min_value_usd = (params or {}).get("min_value_usd")

    try:
        from scraping.models import InstitutionalFiling
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "InstitutionalFiling unavailable"}}

    # Lower bound is the lookback cutoff. Skip an upper bound to avoid TZ
    # edge cases where local-today is UTC-tomorrow (which would exclude
    # legitimately recent filings near midnight UTC).
    cutoff = (now - timedelta(days=lookback_days)).date()
    qs = InstitutionalFiling.objects.filter(
        instrument=instrument, filing_date__gte=cutoff,
    )
    if change_type:
        qs = qs.filter(change_type=change_type)
    if filing_type:
        qs = qs.filter(filing_type=filing_type)
    if min_value_usd is not None:
        try:
            mv = float(min_value_usd)
        except (TypeError, ValueError):
            return {"matched": False, "score": 0.0, "details": {"reason": "invalid min_value_usd"}}
        qs = qs.filter(value__gte=mv)

    n = qs.count()
    matched = n >= min_count
    score = min(1.0, n / max(min_count, 1)) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"n": n, "min_count": min_count,
                        "change_type": change_type, "filing_type": filing_type,
                        "min_value_usd": min_value_usd}}


register_kind("institutional_filings", _eval_institutional_filings)


def _eval_calendar_event(params: dict, instrument, now: datetime) -> dict:
    """An EconomicEvent matching the title-filter occurred in the lookback window."""
    lookback_days = int((params or {}).get("lookback_days", 3))
    title_contains = (params or {}).get("title_contains", "")
    impact = (params or {}).get("impact")  # optional: "high" | "medium" | "low"

    try:
        from market_data.models import EconomicEvent
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "EconomicEvent model unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    qs = EconomicEvent.objects.filter(datetime__gte=cutoff, datetime__lte=now)
    if title_contains:
        qs = qs.filter(title__icontains=title_contains)
    if impact:
        qs = qs.filter(impact=impact)
    n = qs.count()
    matched = n > 0
    return {"matched": matched, "score": 1.0 if matched else 0.0,
            "details": {"n": n, "title_contains": title_contains, "impact": impact}}


register_kind("calendar_event", _eval_calendar_event)


def _eval_macro_regime(params: dict, instrument, now: datetime) -> dict:
    """A FRED-style macro indicator's `last_value` is above/below a threshold.

    Params:
      series_id   — e.g. "DGS10", "VIXCLS", "FEDFUNDS"
      direction   — "above" | "below"
      threshold   — numeric
    """
    series_id = (params or {}).get("series_id", "")
    direction = (params or {}).get("direction", "above")
    try:
        threshold = float((params or {}).get("threshold", 0.0))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "invalid threshold"}}

    if not series_id:
        return {"matched": False, "score": 0.0, "details": {"reason": "missing series_id"}}

    try:
        from market_data.models import MacroIndicator
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "MacroIndicator unavailable"}}

    indicator = MacroIndicator.objects.filter(series_id=series_id).first()
    if indicator is None or indicator.last_value is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"no indicator data for {series_id}"}}

    val = float(indicator.last_value)
    if direction == "above":
        matched = val >= threshold
        # Score scales with how far above threshold (cap at 1.0).
        spread = abs(threshold) if threshold else max(abs(val), 1.0)
        score = min(1.0, max(0.0, (val - threshold) / spread)) if matched else 0.0
    else:
        matched = val <= threshold
        spread = abs(threshold) if threshold else max(abs(val), 1.0)
        score = min(1.0, max(0.0, (threshold - val) / spread)) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"series_id": series_id, "value": val,
                        "direction": direction, "threshold": threshold,
                        "last_date": str(indicator.last_date) if indicator.last_date else None}}


register_kind("macro_regime", _eval_macro_regime)


def _eval_macro_trend(params: dict, instrument, now: datetime) -> dict:
    """Rate-of-change of a macro indicator over a lookback window.

    Reads MacroObservation rows ordered by date; compares first vs last value
    in the window. Supports absolute or percentage change thresholds.

    Params:
      series_id        — required
      lookback_days    — default 30
      direction        — "rising" | "falling"
      min_change       — minimum |Δvalue| (same units as the series); OR
      min_change_pct   — minimum |Δ%| (e.g. 5.0 = 5%); use one or the other
    """
    series_id = (params or {}).get("series_id", "")
    direction = (params or {}).get("direction", "rising")
    lookback_days = int((params or {}).get("lookback_days", 30))
    min_change = (params or {}).get("min_change")
    min_change_pct = (params or {}).get("min_change_pct")

    if not series_id:
        return {"matched": False, "score": 0.0, "details": {"reason": "missing series_id"}}

    try:
        from market_data.models import MacroIndicator, MacroObservation
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "MacroObservation unavailable"}}

    indicator = MacroIndicator.objects.filter(series_id=series_id).first()
    if indicator is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"no indicator for {series_id}"}}

    # Same TZ-boundary safety: skip the upper bound. Future-dated macro
    # observations shouldn't exist; the lookback is what matters.
    cutoff_date = (now - timedelta(days=lookback_days)).date()
    obs = list(
        MacroObservation.objects.filter(
            indicator=indicator, date__gte=cutoff_date,
        ).order_by("date").values_list("date", "value")
    )
    if len(obs) < 2:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need >=2 observations, got {len(obs)}"}}

    first_date, first_val = obs[0]
    last_date, last_val = obs[-1]
    first_val = float(first_val)
    last_val = float(last_val)
    delta = last_val - first_val
    pct = (delta / first_val * 100.0) if first_val != 0 else 0.0

    direction_ok = (delta > 0 and direction == "rising") or (delta < 0 and direction == "falling")
    if not direction_ok:
        return {"matched": False, "score": 0.0,
                "details": {"first_value": first_val, "last_value": last_val,
                            "delta": delta, "pct": round(pct, 4),
                            "direction": direction, "reason": "wrong direction"}}

    matched = True
    score_basis = 0.0
    if min_change is not None:
        try:
            mc = float(min_change)
        except (TypeError, ValueError):
            return {"matched": False, "score": 0.0, "details": {"reason": "invalid min_change"}}
        matched = matched and abs(delta) >= mc
        score_basis = abs(delta) / max(mc, 1e-9)
    if min_change_pct is not None:
        try:
            mcp = float(min_change_pct)
        except (TypeError, ValueError):
            return {"matched": False, "score": 0.0, "details": {"reason": "invalid min_change_pct"}}
        matched = matched and abs(pct) >= mcp
        score_basis = max(score_basis, abs(pct) / max(mcp, 1e-9))
    if min_change is None and min_change_pct is None:
        # Direction-only match — a small score so the caller can still weight it.
        score_basis = 0.5

    score = min(1.0, score_basis) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"series_id": series_id, "first_value": first_val,
                        "last_value": last_val, "delta": round(delta, 6),
                        "pct": round(pct, 4), "direction": direction,
                        "from": str(first_date), "to": str(last_date),
                        "n_observations": len(obs)}}


register_kind("macro_trend", _eval_macro_trend)


def _eval_sentiment_snapshot(params: dict, instrument, now: datetime) -> dict:
    """Average SentimentSnapshot.composite_score for this instrument in the
    lookback window, vs threshold.

    Params:
      direction      — "above" | "below"
      threshold      — composite_score cutoff
      lookback_days  — default 3
      min_count      — default 2 snapshots required
      source         — optional filter ("reddit", "stocktwits", ...)
    """
    direction = (params or {}).get("direction", "above")
    try:
        threshold = float((params or {}).get("threshold", 0.3))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "invalid threshold"}}
    lookback_days = int((params or {}).get("lookback_days", 3))
    min_count = int((params or {}).get("min_count", 2))
    source = (params or {}).get("source")

    try:
        from scraping.models import SentimentSnapshot
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "SentimentSnapshot unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    qs = SentimentSnapshot.objects.filter(
        instrument=instrument, timestamp__gte=cutoff, timestamp__lte=now,
    )
    if source:
        qs = qs.filter(source=source)
    n = qs.count()
    if n < min_count:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"only {n} snapshots", "min_count": min_count}}

    avg = qs.aggregate(avg=Avg("composite_score"))["avg"]
    avg = float(avg) if avg is not None else 0.0
    if direction == "above":
        matched = avg >= threshold
        score = min(1.0, max(0.0, (avg - threshold) / max(1.0 - threshold, 1e-6))) if matched else 0.0
    else:
        matched = avg <= threshold
        score = min(1.0, max(0.0, (threshold - avg) / max(threshold + 1.0, 1e-6))) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"avg_score": round(avg, 4), "n": n,
                        "direction": direction, "threshold": threshold,
                        "source": source or "any"}}


register_kind("sentiment_snapshot", _eval_sentiment_snapshot)


def _eval_cot_report(params: dict, instrument, now: datetime) -> dict:
    """COT positioning extreme: |net_speculative| / total_speculative ratio.

    A ratio > 0.4 means non-commercials are heavily skewed in one direction —
    often a contrarian signal at extremes, or a momentum confirmation depending
    on the setup. Params control which direction and how extreme.

    Params:
      direction — "long" | "short" | "long_extreme" | "short_extreme"
                  Plain "long"/"short": net speculative side; matched if
                  net_spec > 0 (long) or < 0 (short).
                  "long_extreme"/"short_extreme": same direction AND |ratio| ≥ min_ratio.
      min_ratio — default 0.4 for the *_extreme variants
    """
    direction = (params or {}).get("direction", "long")
    try:
        min_ratio = float((params or {}).get("min_ratio", 0.4))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "invalid min_ratio"}}

    try:
        from scraping.models import COTReport
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "COTReport unavailable"}}

    report = (COTReport.objects.filter(instrument=instrument)
              .order_by("-report_date").first())
    if report is None:
        return {"matched": False, "score": 0.0, "details": {"reason": "no COT report"}}

    net = int(report.net_speculative or 0)
    total = abs(int(report.non_commercial_long or 0)) + abs(int(report.non_commercial_short or 0))
    ratio = (abs(net) / total) if total > 0 else 0.0

    long_side = net > 0
    if direction == "long":
        matched = long_side
    elif direction == "short":
        matched = not long_side and net < 0
    elif direction == "long_extreme":
        matched = long_side and ratio >= min_ratio
    elif direction == "short_extreme":
        matched = (not long_side) and net < 0 and ratio >= min_ratio
    else:
        matched = False

    score = min(1.0, ratio / max(min_ratio, 1e-6)) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"net_speculative": net, "ratio": round(ratio, 4),
                        "direction": direction, "min_ratio": min_ratio,
                        "report_date": str(report.report_date)}}


register_kind("cot_report", _eval_cot_report)


def _eval_options_flow(params: dict, instrument, now: datetime) -> dict:
    """Count of unusual options flows for the instrument in the lookback window.

    Params:
      sentiment      — "bullish" | "bearish" | None (any)
      is_unusual     — bool, default True
      min_count      — default 3
      lookback_days  — default 2
    """
    sentiment = (params or {}).get("sentiment")
    is_unusual = bool((params or {}).get("is_unusual", True))
    min_count = int((params or {}).get("min_count", 3))
    lookback_days = int((params or {}).get("lookback_days", 2))

    try:
        from scraping.models import OptionsFlow
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "OptionsFlow unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    qs = OptionsFlow.objects.filter(
        instrument=instrument, timestamp__gte=cutoff, timestamp__lte=now,
    )
    if is_unusual:
        qs = qs.filter(is_unusual=True)
    if sentiment:
        qs = qs.filter(sentiment=sentiment)

    n = qs.count()
    matched = n >= min_count
    score = min(1.0, n / max(min_count, 1)) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"n": n, "min_count": min_count,
                        "sentiment": sentiment, "is_unusual": is_unusual}}


register_kind("options_flow", _eval_options_flow)


def _eval_volatility_regime(params: dict, instrument, now: datetime) -> dict:
    """Realized daily volatility (std of log returns) over `period` days vs threshold.

    Params:
      period         — default 20 daily bars
      direction      — "above" | "below"
      threshold_pct  — daily vol threshold expressed as a percent (e.g. 2.0 = 2% daily std)
    """
    period = int((params or {}).get("period", 20))
    direction = (params or {}).get("direction", "above")
    try:
        threshold_pct = float((params or {}).get("threshold_pct", 2.0))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "invalid threshold_pct"}}

    closes = _recent_closes(instrument, period + 5, now)
    if len(closes) < period + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {period + 1} closes"}}

    import math
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))
    if len(log_returns) < period:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"only {len(log_returns)} log returns"}}

    import statistics
    sample = log_returns[-period:]
    std = statistics.pstdev(sample) if len(sample) >= 2 else 0.0
    daily_vol_pct = std * 100.0  # convert to %

    if direction == "above":
        matched = daily_vol_pct >= threshold_pct
        score = min(1.0, max(0.0, (daily_vol_pct - threshold_pct) / max(threshold_pct, 1e-6))) if matched else 0.0
    else:
        matched = daily_vol_pct <= threshold_pct
        score = min(1.0, max(0.0, (threshold_pct - daily_vol_pct) / max(threshold_pct, 1e-6))) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"daily_vol_pct": round(daily_vol_pct, 4), "period": period,
                        "direction": direction, "threshold_pct": threshold_pct}}


register_kind("volatility_regime", _eval_volatility_regime)


def _eval_correlation_pair(params: dict, instrument, now: datetime) -> dict:
    """Rolling correlation between this instrument's returns and a reference's.

    Params:
      reference_symbol — symbol of the reference instrument
      period           — default 30 trading days
      direction        — "above" | "below"
      threshold        — correlation threshold in [-1, 1]
    """
    ref_symbol = (params or {}).get("reference_symbol", "")
    period = int((params or {}).get("period", 30))
    direction = (params or {}).get("direction", "above")
    try:
        threshold = float((params or {}).get("threshold", 0.7))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "invalid threshold"}}

    if not ref_symbol:
        return {"matched": False, "score": 0.0, "details": {"reason": "missing reference_symbol"}}

    try:
        from instruments.models import Instrument
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "Instrument unavailable"}}

    if instrument.symbol == ref_symbol:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "self-reference"}}

    ref = Instrument.objects.filter(symbol=ref_symbol).first()
    if ref is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"reference '{ref_symbol}' not found"}}

    a = _recent_closes(instrument, period + 1, now)
    b = _recent_closes(ref, period + 1, now)
    if len(a) < period + 1 or len(b) < period + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient price overlap"}}

    # Returns
    ar = [a[i] / a[i - 1] - 1 for i in range(1, len(a)) if a[i - 1] > 0]
    br = [b[i] / b[i - 1] - 1 for i in range(1, len(b)) if b[i - 1] > 0]
    n = min(len(ar), len(br), period)
    if n < 5:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient overlapping returns"}}
    ar = ar[-n:]; br = br[-n:]

    import statistics
    mean_a = statistics.fmean(ar)
    mean_b = statistics.fmean(br)
    cov = sum((ar[i] - mean_a) * (br[i] - mean_b) for i in range(n)) / n
    std_a = statistics.pstdev(ar)
    std_b = statistics.pstdev(br)
    if std_a == 0 or std_b == 0:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "zero variance"}}
    corr = cov / (std_a * std_b)
    corr = max(-1.0, min(1.0, corr))

    if direction == "above":
        matched = corr >= threshold
        score = min(1.0, max(0.0, (corr - threshold) / max(1.0 - threshold, 1e-6))) if matched else 0.0
    else:
        matched = corr <= threshold
        score = min(1.0, max(0.0, (threshold - corr) / max(threshold + 1.0, 1e-6))) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"correlation": round(corr, 4), "n": n,
                        "reference_symbol": ref_symbol,
                        "direction": direction, "threshold": threshold}}


register_kind("correlation_pair", _eval_correlation_pair)


# ── Scoring + flagging ─────────────────────────────────────────────────────

def _suggested_levels(direction: str, last_price: float, sizing: dict) -> tuple:
    """Return (entry, stop, target). Falls back to percentage stops when sizing
    has no atr_mult and no ATR is available."""
    sizing = sizing or {}
    stop_pct = float(sizing.get("stop_pct", ATR_FALLBACK_PCT)) / 100.0
    target_rr = float(sizing.get("target_rr", 2.0))

    entry = last_price
    if direction == "bullish":
        stop = entry * (1 - stop_pct)
        target = entry + (entry - stop) * target_rr
    elif direction == "bearish":
        stop = entry * (1 + stop_pct)
        target = entry - (stop - entry) * target_rr
    else:
        stop = entry * (1 - stop_pct)
        target = entry
    return entry, stop, target


def _last_price(instrument, now: datetime) -> Optional[float]:
    """Most recent close ≤ now."""
    from market_data.models import PriceData, LiveQuote
    p = (PriceData.objects
         .filter(instrument=instrument, timestamp__lte=now)
         .order_by("-timestamp").values_list("close", flat=True).first())
    if p is not None:
        return float(p)
    try:
        lq = instrument.live_quote
        return float(lq.last) if lq.last is not None else None
    except Exception:
        return None


def scan_setup(setup, instrument, *, now: Optional[datetime] = None) -> dict:
    """Run one setup against one instrument. Returns a dict and creates an
    OpportunityFlag (+ linked Signal) if the composite score meets `min_match_score`.
    """
    from signals.models import OpportunityFlag, Signal

    now = now or timezone.now()

    # Asset-class gate.
    if setup.asset_classes:
        if instrument.asset_class not in setup.asset_classes:
            return {"matched": False, "skipped": True, "reason": "asset_class_filter"}

    conditions_out = []
    weighted_score_sum = 0.0
    weight_sum = 0.0
    for cond in (setup.conditions or []):
        kind = cond.get("kind", "")
        params = cond.get("params") or {}
        weight = float(cond.get("weight", 1.0))
        if not has_kind(kind):
            conditions_out.append({"kind": kind, "matched": False, "score": 0.0,
                                    "details": {"reason": "unknown kind"}, "weight": weight})
            weight_sum += weight
            continue
        try:
            res = EVALUATOR_REGISTRY[kind](params, instrument, now)
        except Exception as e:
            logger.warning("[opportunity] evaluator %s raised: %s", kind, e)
            res = {"matched": False, "score": 0.0, "details": {"error": str(e)}}
        conditions_out.append({"kind": kind, "weight": weight, **res})
        weighted_score_sum += float(res.get("score", 0.0)) * weight
        weight_sum += weight

    composite = (weighted_score_sum / weight_sum) if weight_sum > 0 else 0.0
    matched = composite >= float(setup.min_match_score or 0.0)

    if not matched:
        return {"matched": False, "score": round(composite, 4),
                "conditions": conditions_out}

    # Build the levels + Signal + Flag.
    last_price = _last_price(instrument, now)
    if last_price is None or last_price <= 0:
        return {"matched": False, "skipped": True, "reason": "no_price_data",
                "score": round(composite, 4), "conditions": conditions_out}

    entry, stop, target = _suggested_levels(setup.direction, last_price, setup.sizing or {})
    risk_per = abs(entry - stop)
    rr = abs((target - entry) / risk_per) if risk_per > 0 else None

    signal = Signal.objects.create(
        instrument=instrument,
        signal_type="composite",
        direction=setup.direction,
        urgency="medium",
        title=f"{setup.name} matched on {instrument.symbol}",
        description=setup.description or f"Setup '{setup.name}' triggered with score {composite:.2f}.",
        rule_name=setup.name,
        score=round(composite, 4),
        sub_scores={"opportunity_setup": setup.name},
        price_at_signal=Decimal(str(last_price)),
        suggested_entry=Decimal(str(round(entry, 8))),
        suggested_stop=Decimal(str(round(stop, 8))),
        suggested_target=Decimal(str(round(target, 8))),
        risk_reward_ratio=rr,
    )

    flag = OpportunityFlag.objects.create(
        setup=setup, instrument=instrument, signal=signal,
        direction=setup.direction, score=round(composite, 4),
        conditions_evaluated=conditions_out,
        price_at_flag=Decimal(str(last_price)),
        suggested_entry=Decimal(str(round(entry, 8))),
        suggested_stop=Decimal(str(round(stop, 8))),
        suggested_target=Decimal(str(round(target, 8))),
        horizon_days=setup.suggested_horizon_days,
    )
    logger.info("[opportunity] flag %s created for %s × %s (score=%.2f)",
                flag.id, setup.name, instrument.symbol, composite)
    return {"matched": True, "score": round(composite, 4), "flag_id": flag.id,
            "signal_id": signal.id, "conditions": conditions_out}


def scan_all_setups(*, now: Optional[datetime] = None) -> dict:
    """Walk every active setup × every active instrument; create flags for matches."""
    from signals.models import OpportunitySetup
    from instruments.models import Instrument

    now = now or timezone.now()
    setups = list(OpportunitySetup.objects.filter(is_active=True))
    instruments = list(Instrument.objects.filter(is_active=True))

    n_matches = 0
    n_evaluations = 0
    for setup in setups:
        for inst in instruments:
            n_evaluations += 1
            try:
                result = scan_setup(setup, inst, now=now)
                if result.get("matched"):
                    n_matches += 1
            except Exception as e:
                logger.warning("[opportunity] scan failed setup=%s inst=%s: %s",
                               setup.name, inst.symbol, e)

    return {
        "setups_scanned": len(setups),
        "instruments_scanned": len(instruments),
        "evaluations": n_evaluations,
        "matches": n_matches,
    }


# ── Phase 34-36 advanced evaluators (registered via side-effect import) ────
# Importing here (after register_kind / has_kind / EVALUATOR_REGISTRY are
# defined) registers the quant + tradecraft + behavioral evaluators. We keep
# the import at the bottom to avoid a circular dependency since the advanced
# module imports `register_kind` from this file.
try:  # pragma: no cover — import side-effects exercised by test suite
    from . import evaluators_advanced  # noqa: F401
except Exception as _exc:
    logger.warning("[opportunity] failed to load evaluators_advanced: %s", _exc)


# ── Resolution (after horizon) ──────────────────────────────────────────────

def resolve_pending_flags(*, now: Optional[datetime] = None) -> dict:
    """Walk OpportunityFlags whose horizon has passed; mark hit/miss/neutral.

    A flag is hit if:
      - bullish: resolved_price ≥ suggested_target
      - bearish: resolved_price ≤ suggested_target
    Miss if:
      - bullish: resolved_price ≤ suggested_stop
      - bearish: resolved_price ≥ suggested_stop
    Otherwise neutral.
    """
    from signals.models import OpportunityFlag

    now = now or timezone.now()
    qs = OpportunityFlag.objects.filter(outcome="").select_related("instrument", "signal")

    resolved = {"hit": 0, "miss": 0, "neutral": 0, "expired": 0, "skipped": 0}

    for flag in qs:
        deadline = flag.scanned_at + timedelta(days=flag.horizon_days)
        if now < deadline:
            resolved["skipped"] += 1
            continue

        last = _last_price(flag.instrument, now)
        if last is None:
            flag.outcome = "expired"
            flag.resolved_at = now
            flag.resolution_notes = "No price data at resolution time."
            flag.save()
            resolved["expired"] += 1
            continue

        target = float(flag.suggested_target or 0)
        stop = float(flag.suggested_stop or 0)

        if flag.direction == "bullish":
            if last >= target:
                outcome = "hit"
            elif last <= stop:
                outcome = "miss"
            else:
                outcome = "neutral"
        else:  # bearish
            if last <= target:
                outcome = "hit"
            elif last >= stop:
                outcome = "miss"
            else:
                outcome = "neutral"

        flag.outcome = outcome
        flag.resolved_price = Decimal(str(last))
        flag.resolved_at = now
        flag.resolution_notes = (
            f"price={last:.6f}, target={target:.6f}, stop={stop:.6f}"
        )
        flag.save()
        resolved[outcome] += 1

    return resolved
