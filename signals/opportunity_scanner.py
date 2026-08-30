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

  - `price_pattern`     — "above_ma", "below_ma", "breakout_high", "breakout_low"
  - `news_volume`       — count of relevant news in lookback window ≥ threshold
  - `news_sentiment`    — average AI sentiment of relevant news ≥/≤ threshold
  - `calendar_event`    — economic event matching filter occurred in lookback
  - `quote_currency`    — the symbol's quote currency, for universe gating
  - `cross_sectional_rank` — where the instrument sits in its FIELD, not on
                        its own chart: top/bottom slice of the asset class or
                        the whole universe, by momentum, risk-adjusted
                        momentum, acceleration or volatility

Adding a new kind: define an evaluator function and call `register_kind()`,
declaring every param key the function consumes and — where the evaluator
branches on a closed set of strings — the values it accepts.

Universe context
----------------

Every evaluator but the last one above answers an ABSOLUTE question about a
single instrument: is IT above ITS moving average, is ITS vol above 2%. A rank
cannot be asked that way, because "strongest name in its class" is not a
property of an instrument at all — it is a property of an instrument inside a
FIELD, and the three-argument contract has no field in it.

So the contract widens by one optional keyword rather than changing shape.
An evaluator that needs the universe declares a `field` parameter; the kinds
that came before it keep the signature they had and are called exactly as
before. `register_kind` resolves who wants what once, at registration, the
same way it already resolves `as_of` — so the scan loop never introspects a
function per call and no existing kind had to be touched.

`scan_all_setups` is where the field comes from, because that is where the
whole universe is already in hand: the pass materialises the active
instruments once and pins one `now` before it starts, so the field it builds
is exactly the set of instruments the pass evaluated, measured at exactly the
instant it evaluated them. Every rank in the pass is therefore taken against
the same numbers, and the universe cannot move under a long pass. A caller
scanning one pair on its own still gets a field — built lazily, and only if a
condition actually asks for one.

Gates vs. scoring conditions
----------------------------

A condition carrying `"gate": true` says WHERE a setup applies, not how
strongly it fires. A failed gate skips the (setup, instrument) pair outright
and a passed one contributes nothing to the composite score. Weighting a
universe check instead would make "does this setup even apply here" tradeable
against evidence — and would leave the exclusion resting on an arithmetic
balance that the next weight edit silently breaks.

A third answer exists alongside "fired" and "did not fire": an evaluator may
return `measured: False` to say it never got to look. `scan_setup` leaves such
a leg out of the weighted average on both sides, because counting it as a
scored zero puts `weight` into the denominator for a question nobody answered
and drags every other leg's evidence down with it. Only the kinds that mean it
set the key; everything else keeps the arithmetic it always had.

Public API
----------

    register_kind(kind, fn, *, params=(...), choices={...})
    has_kind(kind) -> bool
    param_keys(kind) -> frozenset[str]
    param_choices(kind) -> dict[str, frozenset[str]]
    unknown_param_keys(kind, params) -> list[str]
    invalid_param_values(kind, params) -> list[str]
    unknown_sizing_keys(sizing) -> list[str]
    condition_fingerprint(condition) -> str
    setup_fingerprints(setup) -> frozenset[str]
    setup_overlap(setup_a, setup_b) -> dict
    cot_sign(instrument) -> int
    cot_net_speculative(report, instrument) -> int
    window_return(closes) -> float | None
    CrossSectionalField(instruments=None, *, now)
    scan_setup(setup, instrument, *, now=None, as_of=None, emit=True,
               field=None) -> dict
    scan_all_setups(*, now=None, as_of=None) -> dict
    resolve_pending_flags(*, now=None, as_of=None) -> dict
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
DEFAULT_BREAKOUT_LOOKBACK = 20

# Resolution band: |move| < this fraction × ATR-equivalent → "neutral".
NEUTRAL_BAND_PCT = 0.5  # %, used when ATR is unavailable
ATR_FALLBACK_PCT = 2.0  # default 2% stop when ATR can't be computed

# The only keys `_suggested_levels` reads out of OpportunitySetup.sizing.
# `sizing` never reaches the evaluator registry, so it gets none of the param
# guard's protection: six seeded setups carried a `target_pct` nothing has ever
# read, and their targets silently fell back to target_rr=2.0 — three of them
# were graded against a level the seed never asked for.
SIZING_KEYS = frozenset({"stop_pct", "target_rr"})

# ── Cross-sectional ranking tunables ───────────────────────────────────────

# Bar counts, like every other `lookback` and `period` in this file — never
# calendar days. A rank compares instruments to each other, and two instruments
# given the same number of CALENDAR days hold different numbers of bars (forex
# trades five days a week, crypto seven), so a calendar window would rank a
# 43-bar measurement against a 60-bar one and call the difference momentum.
DEFAULT_RANK_LOOKBACK = 60
DEFAULT_RANK_SHORT_LOOKBACK = 10

# A decile. The fraction of the field a "top slice" strategy takes.
DEFAULT_SELECT_PCT = 0.10

# The smallest field a percentile cut may be taken in. `instruments.services`
# seeds 177 symbols and its SMALLEST asset class holds 13, so a field that
# falls under ten is instruments dropping out for want of bars — a data
# outage — not a genuinely small class, and ranking whatever survived would
# publish the survivors' ordering as the market's. Ten is also exactly where
# the default decile stops naming a whole instrument.
MIN_RANK_FIELD = 10

# A slice that is not a minority of the field is not a selection. Half is the
# generous end of that line: at 0.5 the setup is splitting the universe in two,
# and anything past it would be calling a majority a "top slice".
MAX_SELECT_PCT = 0.5

# How old a member's LAST bar may be and still belong in a field measured at
# `now`, in calendar days. A rank compares instruments to each other at one
# instant, so a member whose feed died three weeks ago is measured over a
# window that ENDS three weeks ago: its number is not wrong, it is about a
# different day, and an ordering that mixes it with instruments measured to
# today is not a cross-section of anything. The window's lower bound does not
# catch this on its own — a member can hold a full window of bars entirely
# inside the OLD half of `need * 2` calendar days and still qualify.
#
# Seven days, because the longest silence a live daily feed produces is a
# weekend flanked by holidays — Wednesday's close to Monday's is five calendar
# days — and a pass pinned before the current day's bar has been written adds
# one more. Anything quieter than that is not a market closure.
MAX_FIELD_STALENESS_DAYS = 7

# The quietest tape that still counts as a measurement, as a daily standard
# deviation in percent. 0.01% a day is 0.16% annualised — quieter than any
# instrument in this universe, pegged pairs included — so a window reading
# under it is a stale feed repeating an interpolated ramp, or float noise off a
# series that never actually varied. Both matter: such a window sorts to the
# bottom of a volatility rank as though it were the calmest real market, and
# dividing a return by it hands risk-adjusted momentum a value near 1e15,
# which tops every table it appears in. Below the floor the window is NOT
# MEASURED and the instrument leaves the field.
MIN_MEASURABLE_VOL_PCT = 0.01


# ── Evaluator registry ──────────────────────────────────────────────────────

# (params, instrument, now) -> dict, plus an optional keyword-only `as_of`.
EvaluatorFn = Callable[..., dict]
EVALUATOR_REGISTRY: dict[str, EvaluatorFn] = {}

# Every evaluator reads its params with `.get(key, default)`, so a seeded key
# the function never reads is invisible: the condition silently runs on
# defaults, or can never match at all. Declaring the accepted keys here gives
# the seeders, the admin form and the AI strategy generator something to be
# checked against — see tests/test_seed_param_integrity.py, which also asserts
# these declarations match what each function actually reads.
PARAM_KEYS: dict[str, frozenset[str]] = {}

# Keys alone are not enough. `{"direction": "long_increasing"}` on cot_report
# and `{"pattern": "rsi_oversold"}` on price_pattern both declare accepted keys
# and are both permanently inert — one falls to `else: matched = False`, the
# other to "unknown pattern". Worse, the two-branch evaluators treat any
# unrecognised value as the ELSE branch, so a typo does not go quiet, it
# inverts the condition. Declaring the closed vocabularies makes both classes
# rejectable at authoring time instead of discoverable months later.
PARAM_CHOICES: dict[str, dict[str, frozenset[str]]] = {}

# An evaluator that needs to know whether it is replaying history declares an
# `as_of` keyword; the rest keep the three-argument signature. Resolved once at
# registration so the scan loop never introspects per call.
ACCEPTS_AS_OF: dict[str, bool] = {}

# The same opt-in, for the universe a cross-sectional condition ranks inside.
# Widening the contract by a keyword nobody has to name is what let the rank
# kind land without editing a single one of the kinds that predate it: a
# function that does not declare `field` is still called with three arguments,
# so there is no shim, no **kwargs sink swallowing typos, and no default field
# quietly constructed for evaluators that would ignore it anyway.
ACCEPTS_FIELD: dict[str, bool] = {}


def register_kind(kind: str, fn: EvaluatorFn, *, params=(), choices=None) -> None:
    if not callable(fn):
        raise TypeError("evaluator must be callable(params, instrument, now) -> dict")
    import inspect
    EVALUATOR_REGISTRY[kind] = fn
    PARAM_KEYS[kind] = frozenset(params)
    PARAM_CHOICES[kind] = {k: frozenset(v) for k, v in (choices or {}).items()}
    try:
        accepted = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        # A callable whose signature cannot be read gets the narrow contract:
        # calling it with a keyword it may not accept would turn an
        # introspection failure into a TypeError on every scan.
        accepted = ()
    ACCEPTS_AS_OF[kind] = "as_of" in accepted
    ACCEPTS_FIELD[kind] = "field" in accepted


def has_kind(kind: str) -> bool:
    return kind in EVALUATOR_REGISTRY


def param_keys(kind: str) -> frozenset:
    """The param keys `kind`'s evaluator consumes. Empty set for unknown kinds."""
    return PARAM_KEYS.get(kind, frozenset())


def param_choices(kind: str) -> dict:
    """{param_key: accepted values} for the params `kind` branches on by name.

    A key absent from this mapping takes free values (numbers, symbols, keyword
    lists); only closed vocabularies are declared.
    """
    return PARAM_CHOICES.get(kind, {})


def unknown_param_keys(kind: str, params: dict) -> list:
    """Keys in `params` that `kind`'s evaluator will never read — i.e. keys
    whose value has no effect on whether the condition fires."""
    accepted = PARAM_KEYS.get(kind)
    if accepted is None:
        return sorted(params or {})
    return sorted(set(params or {}) - accepted)


def invalid_param_values(kind: str, params: dict) -> list:
    """Human-readable complaints about values outside a declared vocabulary.

    Empty for an unknown kind — `unknown_param_keys` is what reports that; this
    function only speaks about vocabularies it has.
    """
    declared = PARAM_CHOICES.get(kind) or {}
    out = []
    for key, accepted in sorted(declared.items()):
        if key not in (params or {}):
            continue
        value = params[key]
        if value in accepted:
            continue
        out.append(f"{key}={value!r} (accepted: {sorted(accepted)})")
    return out


def unknown_sizing_keys(sizing: dict) -> list:
    """Keys in an OpportunitySetup's `sizing` that `_suggested_levels` ignores."""
    return sorted(set(sizing or {}) - SIZING_KEYS)


# ── Are two setups the same detector twice? ────────────────────────────────

def condition_fingerprint(condition: dict) -> str:
    """A condition's identity INCLUDING the params that decide which way it
    points: `liquidity_sweep[direction=bullish_sweep]`, not `liquidity_sweep`.

    Comparing setups on `kind` alone reports advanced_smc_long and
    advanced_smc_short as the same rule twice — three shared kinds, Jaccard
    1.0 — when they are mirror images: the same three detectors, each on the
    opposite branch. Acting on that number would retire one half of a
    long/short pair as a duplicate of the other.

    `PARAM_CHOICES` already names exactly the params an evaluator BRANCHES
    on, and a branch param is precisely the one whose value changes what the
    condition MEANS, so kind + those params is the honest identity.
    Thresholds, lookbacks and periods are deliberately excluded: they are
    tuning, and folding them in would make every pair look distinct — which
    is the opposite failure and just as useless to an operator.
    """
    kind = (condition or {}).get("kind", "")
    params = (condition or {}).get("params") or {}
    declared = PARAM_CHOICES.get(kind) or {}
    tags = [f"{k}={params[k]}" for k in sorted(declared) if k in params]
    return f"{kind}[{','.join(tags)}]" if tags else kind


def setup_fingerprints(setup) -> frozenset:
    """`setup`'s SCORING conditions as fingerprints.

    Gates are left out: a gate says where a setup applies, not what it looks
    for, so two setups sharing only `quote_currency: USD` have nothing in
    common but a universe.
    """
    return frozenset(
        condition_fingerprint(c)
        for c in (getattr(setup, "conditions", None) or [])
        if not (c or {}).get("gate")
    )


def setup_overlap(setup_a, setup_b) -> dict:
    """How much two setups actually look for the same thing.

    `jaccard` is over direction-aware fingerprints; `kind_jaccard` is over
    bare kinds — the number a naive audit produces. The GAP between them is
    the finding: on the advanced_smc long/short pair it is 0.20 vs 1.00, and
    on starter_commodity_vol_compression vs starter_stock_mean_reversion it
    is 0.00 vs 1.00. `shares_universe` completes the picture, because two
    setups whose asset_classes are disjoint are never scored against the same
    instrument however much their conditions rhyme.

    Both Jaccards are None — not 0.0 — when there is nothing to compare, so a
    setup with no scoring conditions reads as unknown rather than as
    "measured, and they share nothing".
    """
    fp_a, fp_b = setup_fingerprints(setup_a), setup_fingerprints(setup_b)
    kinds_a = frozenset(f.split("[", 1)[0] for f in fp_a)
    kinds_b = frozenset(f.split("[", 1)[0] for f in fp_b)

    def _jaccard(a, b):
        union = a | b
        return round(len(a & b) / len(union), 4) if union else None

    classes_a = set(getattr(setup_a, "asset_classes", None) or [])
    classes_b = set(getattr(setup_b, "asset_classes", None) or [])
    directions = {getattr(setup_a, "direction", ""),
                  getattr(setup_b, "direction", "")}
    return {
        "jaccard": _jaccard(fp_a, fp_b),
        "kind_jaccard": _jaccard(kinds_a, kinds_b),
        "shared": sorted(fp_a & fp_b),
        "only_a": sorted(fp_a - fp_b),
        "only_b": sorted(fp_b - fp_a),
        # Empty asset_classes means "every class", so it overlaps everything.
        "shares_universe": (not classes_a) or (not classes_b)
                           or bool(classes_a & classes_b),
        "opposite_direction": directions == {"bullish", "bearish"},
    }


# How much of a setup's authored scoring weight must actually answer before
# its composite is treated as a reading of that setup.
#
# An evaluator that reports `measured: False` is dropped from BOTH sides of
# the average, which is correct — an unmeasured leg is not a zero, and
# weighting it as one would dilute every leg that did answer. But the same
# drop renormalises the composite over the survivors, so a two-leg setup
# whose second leg cannot answer silently becomes a one-leg setup scoring the
# first at full confidence.
#
# A MAJORITY of the authored weight, which is strictly more than half — the
# comparison below is `>`, not `>=`, and the difference is the whole point.
# The motivating case is a two-leg setup whose second leg cannot answer: at
# `>=` that lands exactly on the line and passes, which is the renormalisation
# this constant exists to stop. One of two legs is not a majority of the case.
#
# It is deliberately not "all": a setup that needs every leg every time goes
# dark on the first quiet data source, and refusing to publish is its own kind
# of wrong.
MEASURED_WEIGHT_QUORUM = 0.5


def _is_replay(now: datetime) -> bool:
    """Calendar fallback for a caller that did not say whether it is replaying.

    Only used when `as_of` is left unset — a direct call that named a past day
    means a past day. The scan loop always passes an explicit flag instead,
    because any clock-derived answer makes the result depend on when the pass
    happened to run: this one flips mid-sweep across UTC midnight, the
    five-minute rule it replaces flipped on every slow pass.
    """
    return now.date() < timezone.now().date()


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
    lookback = int((params or {}).get("lookback", DEFAULT_BREAKOUT_LOOKBACK))
    # The window has to cover `lookback` too. Sizing it from `ma_period` alone
    # capped the fetch at 55 bars, so every breakout asking for more than a
    # 54-bar range failed the "need lookback+1 closes" check forever, however
    # much price history the instrument had.
    closes = _recent_closes(instrument, max(period, lookback, DEFAULT_BREAKOUT_LOOKBACK) + 5, now)
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
        if len(closes) < lookback + 1:
            return {"matched": False, "score": 0.0, "details": {"reason": f"need {lookback+1} closes"}}
        prior_high = max(closes[-(lookback + 1):-1])
        matched = last > prior_high
        score = 1.0 if matched else 0.0
        return {"matched": matched, "score": score,
                "details": {"last": last, "prior_high": prior_high, "lookback": lookback}}

    if pattern == "breakout_low":
        if len(closes) < lookback + 1:
            return {"matched": False, "score": 0.0, "details": {"reason": f"need {lookback+1} closes"}}
        prior_low = min(closes[-(lookback + 1):-1])
        matched = last < prior_low
        score = 1.0 if matched else 0.0
        return {"matched": matched, "score": score,
                "details": {"last": last, "prior_low": prior_low, "lookback": lookback}}

    return {"matched": False, "score": 0.0,
            "details": {"reason": f"unknown pattern '{pattern}'"}}


register_kind("price_pattern", _eval_price_pattern,
                params=("pattern", "ma_period", "lookback"),
                choices={"pattern": ("above_ma", "below_ma", "breakout_high",
                                     "breakout_low")})


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


register_kind("news_volume", _eval_news_volume,
                params=("lookback_days", "min_count", "keywords", "sources"))


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


register_kind("news_sentiment", _eval_news_sentiment,
                params=("lookback_days", "keywords", "direction", "threshold",
                        "min_count", "sources"),
                choices={"direction": ("above", "below")})


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


register_kind("institutional_filings", _eval_institutional_filings,
                params=("change_type", "filing_type", "min_count", "lookback_days",
                        "min_value_usd"))


# EconomicEvent has no FK to Instrument, so "does this event concern this
# symbol" is a string question. `source="fmp"` is the earnings calendar's
# stamp, and that writer is issuer-scoped by construction: one row per US
# issuer per print, every one of them impact="high", ticker in
# `currency_affected`. Macro rows (FOMC, CPI) carry another source and do
# concern everybody.
_ISSUER_SCOPED_SOURCE = "fmp"


def _eval_calendar_event(params: dict, instrument, now: datetime) -> dict:
    """An EconomicEvent matching the title-filter occurred in the lookback window.

    Issuer-scoped rows only count for their own issuer. Without that link a
    setup asking "was there a high-impact event in the last three days" was
    TRUE for every instrument on nearly every day of earnings season, because
    the earnings calendar stamps every issuer's print impact="high" — a
    condition that is always on is not a condition, and pattern_miner mines
    exactly this feature into DiscoveredSetups people are asked to approve.
    The link is spelled the way bot_program/asset_engine/stock_bot.py spells
    it, so the scanner and the earnings blackout agree on what "AAPL's
    earnings" means.
    """
    lookback_days = int((params or {}).get("lookback_days", 3))
    title_contains = (params or {}).get("title_contains", "")
    impact = (params or {}).get("impact")  # optional: "high" | "medium" | "low"

    try:
        from django.db.models import Q
        from market_data.models import EconomicEvent
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "EconomicEvent model unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    qs = EconomicEvent.objects.filter(datetime__gte=cutoff, datetime__lte=now)
    if title_contains:
        qs = qs.filter(title__icontains=title_contains)
    if impact:
        qs = qs.filter(impact=impact)

    symbol = (getattr(instrument, "symbol", "") or "").strip().upper()
    # A one-character symbol is a substring of almost every headline, so it
    # gets the exact column only — a title match there would re-create the
    # always-true condition this link exists to remove.
    names_this = Q(currency_affected__iexact=symbol) if symbol else Q(pk__in=[])
    if len(symbol) >= 2:
        names_this = names_this | Q(title__icontains=symbol)
    qs = qs.filter(names_this | ~Q(source__iexact=_ISSUER_SCOPED_SOURCE))

    n = qs.count()
    matched = n > 0
    return {"matched": matched, "score": 1.0 if matched else 0.0,
            "details": {"n": n, "title_contains": title_contains,
                        "impact": impact, "symbol": symbol}}


register_kind("calendar_event", _eval_calendar_event,
                params=("lookback_days", "title_contains", "impact"))


def _eval_macro_regime(params: dict, instrument, now: datetime, *,
                       as_of: Optional[bool] = None) -> dict:
    """A FRED-style macro indicator's value as of `now` is above/below a threshold.

    Params:
      series_id   — e.g. "DGS10", "VIXCLS", "FEDFUNDS"
      direction   — "above" | "below"
      threshold   — numeric

    `as_of` is the scan loop's statement that this is a replay; left None it
    falls back to the calendar.
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
        from market_data.models import MacroIndicator, MacroObservation
    except Exception:
        return {"matched": False, "score": 0.0, "details": {"reason": "MacroIndicator unavailable"}}

    indicator = MacroIndicator.objects.filter(series_id=series_id).first()
    if indicator is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"no indicator data for {series_id}"}}

    # `last_value` is a mutable current-value column with no history: reading it
    # alone would answer "what is the rate today", not "what was it at `now`",
    # which silently turns any as-of replay into lookahead. MacroObservation is
    # the history, so the as-of read has to come from there.
    obs = (MacroObservation.objects
           .filter(indicator=indicator, date__lte=now.date())
           .order_by("-date").values_list("date", "value").first())
    if obs is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"no observation for {series_id} on or before {now.date()}"}}
    obs_date, obs_value = obs

    val = float(obs_value)
    revised = False
    # The history is NOT self-updating: the FRED ingest writes observation rows
    # with get_or_create, so a re-fetched date keeps its first print forever
    # while `last_value` is reassigned unconditionally. GDP advance -> second ->
    # third estimate, CPI seasonal-factor revisions and M2 benchmark revisions
    # therefore leave the two columns disagreeing about the SAME date, with the
    # newer number only in last_value. A live read wants that number; a replay
    # must not have it, because last_value carries no date of its own beyond
    # `last_date`. Comparing the dates is what separates the two cases.
    replaying = _is_replay(now) if as_of is None else as_of
    if (not replaying and indicator.last_value is not None
            and indicator.last_date == obs_date):
        revised_val = float(indicator.last_value)
        revised = revised_val != val
        val = revised_val
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
                        "last_date": str(obs_date), "revised": revised}}


register_kind("macro_regime", _eval_macro_regime,
                params=("series_id", "direction", "threshold"),
                choices={"direction": ("above", "below")})


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

    # Both bounds, on purpose. Without the upper one this reads whatever the
    # ingest has written by wall-clock time rather than what was knowable at
    # `now` — a no-op while scanning live (no observation is dated ahead of
    # today) and lookahead in any replay.
    #
    # It is not full point-in-time correctness, and must not be described as
    # such: MacroObservation rows are keyed by OBSERVATION PERIOD, not by
    # publication date. For a daily series the two coincide; for a quarterly or
    # monthly one they do not, so a replay at 2026-04-15 still sees the
    # Q1-dated GDP row that BEA did not publish until late April. Closing that
    # needs a publication-date column on the model, not a tighter bound here.
    #
    # Both endpoints are read straight from the history, first prints and all.
    # Overlaying the revised `last_value` onto the newest endpoint (as
    # macro_regime does for its level read) would pair a revised endpoint with
    # an unrevised start and distort the very delta this measures — a mixed
    # vintage is a worse answer than a consistent stale one.
    cutoff_date = (now - timedelta(days=lookback_days)).date()
    obs = list(
        MacroObservation.objects.filter(
            indicator=indicator, date__gte=cutoff_date, date__lte=now.date(),
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


register_kind("macro_trend", _eval_macro_trend,
                params=("series_id", "direction", "lookback_days", "min_change",
                        "min_change_pct"),
                choices={"direction": ("rising", "falling")})


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


register_kind("sentiment_snapshot", _eval_sentiment_snapshot,
                params=("direction", "threshold", "lookback_days", "min_count",
                        "source"),
                choices={"direction": ("above", "below")})


def cot_sign(instrument) -> int:
    """+1 if COT positioning already reads in the symbol's own frame, -1 if it
    is expressed in the pair's QUOTE currency and has to be flipped.

    The CFTC quotes an FX future in the FOREIGN currency: the contract unit of
    'JAPANESE YEN' is the yen, so `MARKET_NAME_MAP` in
    scraping/scrapers/cot_reports.py maps it onto USDJPY and the ingest writes
    `net_speculative = nc_long - nc_short` through verbatim. Net LONG the yen
    contract is net SHORT USDJPY. Every reader that took the column at face
    value therefore inverted its own test on the four pairs the dollar is the
    BASE of (USDJPY, USDCHF, USDCAD, USDMXN) — manufacturing divergences where
    positioning and price agreed and scoring the genuine ones at zero.

    A sign, not a universe cut. XAUUSD, LUMBER, BTCUSD and the two real
    cross contracts (EURGBP from 'EURO FX/BRITISH POUND XRATE', EURJPY from
    'EURO FX/JAPANESE YEN XRATE') are all quoted with the contract's unit as the
    BASE, so their column already reads in the symbol's frame. Gating those out
    to fix four symbols would throw away twelve correct ones.

    Read off the symbol for the same reason `_eval_quote_currency` is:
    `Instrument.currency` is seeded to the literal "USD" for every forex pair
    and every commodity, so it carries no quote information at all. The
    asset-class guard keeps a six-letter commodity ticker from ever being
    decomposed as a currency pair.
    """
    symbol = (getattr(instrument, "symbol", "") or "").upper()
    asset_class = (getattr(instrument, "asset_class", "") or "").lower()
    if asset_class == "forex" and len(symbol) == 6 and symbol.startswith("USD"):
        return -1
    return 1


def cot_net_speculative(report, instrument) -> int:
    """`COTReport.net_speculative` re-expressed in `instrument`'s own frame."""
    return cot_sign(instrument) * int(getattr(report, "net_speculative", 0) or 0)


# The CFTC publishes weekly. Three weeks is generous — it absorbs a holiday
# week, a shutdown-delayed release and a slipped Saturday beat — and still
# stops a read from crossing into "the scraper died a month ago".
COT_MAX_AGE_DAYS = 21


def latest_fresh_cot_report(instrument, now, max_age_days: int = COT_MAX_AGE_DAYS):
    """The newest COT report at or before `now`, and a reason when it cannot
    be scored. Returns `(report, None)` or `(None, reason)`.

    One helper for all three readers — the scanner's cot_report leg,
    smart_money_divergence and the pattern miner's cot_* features — because
    each of them used to take the newest row with no upper bound on its age.
    That is silent while the scraper runs and poisonous the moment it stops:
    price keeps moving, positioning freezes, and a divergence test comparing a
    live slope against months-old positioning MANUFACTURES divergences that
    never happened. A missing report is honest starvation; a stale one is a
    confident wrong answer, so it has to be refused by name rather than
    scored.

    Bounded by `now` and not by wall clock for the same reason as the rest of
    the as-of machinery: COT is backfilled weekly, so an unbounded "latest"
    hands a replay positioning that was still unpublished on the date being
    evaluated.
    """
    try:
        from scraping.models import COTReport
    except Exception:
        return None, "COTReport unavailable"

    as_of = now.date() if hasattr(now, "date") else now
    report = (COTReport.objects.filter(instrument=instrument,
                                       report_date__lte=as_of)
              .order_by("-report_date").first())
    if report is None:
        return None, "no COT report"

    age_days = (as_of - report.report_date).days
    if age_days > max_age_days:
        return None, f"COT report stale ({age_days} days)"
    return report, None


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

    report, reason = latest_fresh_cot_report(instrument, now)
    if report is None:
        return {"matched": False, "score": 0.0, "details": {"reason": reason}}

    net = cot_net_speculative(report, instrument)
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
                        "contract_frame_flipped": cot_sign(instrument) < 0,
                        "report_date": str(report.report_date)}}


register_kind("cot_report", _eval_cot_report, params=("direction", "min_ratio"),
                choices={"direction": ("long", "short", "long_extreme",
                                       "short_extreme")})


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


register_kind("options_flow", _eval_options_flow,
                params=("sentiment", "is_unusual", "min_count", "lookback_days"))


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


register_kind("volatility_regime", _eval_volatility_regime,
                params=("period", "direction", "threshold_pct"),
                choices={"direction": ("above", "below")})


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


register_kind("correlation_pair", _eval_correlation_pair,
                params=("reference_symbol", "period", "direction", "threshold"),
                choices={"direction": ("above", "below")})


def _eval_quote_currency(params: dict, instrument, now: datetime) -> dict:
    """The instrument's QUOTE currency — what one unit of the base buys.

    A setup whose thesis is about a CURRENCY rather than about the symbol has
    to say so, because the platform's symbols mix quote conventions: "USD is
    weak" means EURUSD rises and USDJPY falls, and a setup carrying one fixed
    `direction` is right about exactly one of them. Gate on this and the fixed
    direction becomes honest for every symbol left in the universe.

    The convention is read off the symbol, because `Instrument.currency` is
    seeded to the literal "USD" for every forex pair AND every commodity and
    so carries no quote information at all.

    The test is a suffix match, deliberately not "the last three characters are
    a currency code": nothing distinguishes a currency suffix from the tail of
    a ticker, so decomposing LUMBER into LUM/BER would be an invention. A
    symbol that does not end in the wanted code is simply unmatched — which,
    used as a gate, is the fail-closed answer.

    Params:
      currency — ISO code the symbol must be QUOTED in, e.g. "USD"
    """
    wanted = str((params or {}).get("currency", "USD")).upper()
    symbol = (getattr(instrument, "symbol", "") or "").upper()

    # Strictly longer, so the bare code ("USD") is not read as quoted in itself.
    matched = len(symbol) > len(wanted) and symbol.endswith(wanted)
    return {"matched": matched, "score": 1.0 if matched else 0.0,
            "details": {"symbol": symbol, "wanted": wanted,
                        "suffix": symbol[-len(wanted):] if wanted else ""}}


register_kind("quote_currency", _eval_quote_currency, params=("currency",))


# ── Cross-sectional ranking ────────────────────────────────────────────────
#
# The measurements a rank is taken on, and the field they are taken across.
# Everything here obeys one rule the absolute evaluators never had to state:
# an instrument that cannot be measured is ABSENT from the field, never zero.
# A zero-filled member would land mid-table on a momentum rank and at the calm
# end of a volatility one, in both cases asserting something about a market
# nobody looked at — and worse, it would keep the field's size up, which is the
# number the thin-field refusal below is watching.

def window_return(closes) -> Optional[float]:
    """Simple return from the first close in the window to the last.

    None means NOT MEASURED: a window holding fewer than two bars, or opening
    at a non-positive price, has no return to report. Shared with
    `signals.sector_rotation` so a sector's return and an instrument's are the
    same arithmetic over the same rule about missing data.
    """
    if len(closes) < 2 or closes[0] <= 0:
        return None
    return closes[-1] / closes[0] - 1.0


def _rank_vol_pct(closes) -> Optional[float]:
    """Daily standard deviation of log returns across the window, in percent.

    None below `MIN_MEASURABLE_VOL_PCT`, where the number stops describing a
    market. A series compounding at a fixed rate every bar has a log-return
    variance of exactly zero, and `pstdev` returns not 0 but ~1e-16 of float
    residue — enough to pass a `> 0` test and produce a risk-adjusted momentum
    of 7e15, which would sit at the top of every ranking it entered.
    """
    import math
    import statistics
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0 and closes[i] > 0]
    if len(rets) < 2:
        return None
    vol_pct = statistics.pstdev(rets) * 100.0
    return vol_pct if vol_pct >= MIN_MEASURABLE_VOL_PCT else None


def _measure_momentum(closes, short_lookback: int) -> Optional[float]:
    """Trailing return over the whole window — the classic ranking metric."""
    return window_return(closes)


def _measure_volatility(closes, short_lookback: int) -> Optional[float]:
    """Realized daily volatility. `side` decides which end of it is wanted."""
    return _rank_vol_pct(closes)


def _measure_risk_adjusted_momentum(closes, short_lookback: int) -> Optional[float]:
    """The window's return expressed in units of one day's volatility.

    A decile taken on raw return is mostly a high-beta decile wearing a
    momentum label: +40% on a name that moves 6% a day is a quieter event than
    +15% on one that moves 1%, and a raw rank puts the first above the second
    every time. Dividing by the same window's realized vol is what separates
    "moved furthest" from "moved furthest for its risk".
    """
    ret = window_return(closes)
    # `_rank_vol_pct` already refuses a window with no measurable risk in it,
    # which is what keeps this division away from a denominator of float noise.
    vol_pct = _rank_vol_pct(closes)
    if ret is None or vol_pct is None:
        return None
    return (ret * 100.0) / vol_pct


def _measure_acceleration(closes, short_lookback: int) -> Optional[float]:
    """Recent per-bar drift minus whole-window per-bar drift.

    Comparing the two windows' TOTAL returns is the trap, and it is the one
    `sector_rotation._momentum_analysis` fell into: a longer window wins on
    total return by construction in any trend, so a name running +0.4% a day
    for ten bars read as slowing against its own +0.3%-a-day sixty-bar figure.

    Dividing each total by its own bar count is not quite the fix either.
    Simple returns compound, so `((1+r)**n - 1) / n` grows with `n` — a tape
    advancing by exactly the same percentage every single bar still scores as
    decelerating, and the size of that artefact depends on how far the
    instrument moved, so it does not even cancel across the field. Log returns
    are additive across bars, so dividing one by its bar count is a true pace
    and a steady tape scores exactly zero.
    """
    import math
    if short_lookback < 2 or short_lookback >= len(closes):
        return None
    recent_start = closes[-(short_lookback + 1)]
    if closes[0] <= 0 or recent_start <= 0 or closes[-1] <= 0:
        return None
    recent = math.log(closes[-1] / recent_start) / short_lookback
    whole = math.log(closes[-1] / closes[0]) / (len(closes) - 1)
    return recent - whole


_RANK_MEASURES = {
    "momentum": _measure_momentum,
    "risk_adjusted_momentum": _measure_risk_adjusted_momentum,
    "acceleration": _measure_acceleration,
    "volatility": _measure_volatility,
}


def _field_closes(instruments, lookback: int, now: datetime,
                  timeframe: str = "1d") -> tuple:
    """({instrument_id: [closes]}, {instrument_id: last bar}) at `now`.

    The first map holds every member with a FULL and CURRENT window. The second
    names the members dropped because their last bar is too old to belong in a
    field measured at `now`, so the rank can say WHY one of them is unranked
    instead of reporting it the same way as a symbol that has no history at all.

    One query for the entire field rather than one per member: the field is
    priced once per scan pass, and a per-instrument fetch would put 177 round
    trips behind every (setup, instrument) pair that carries a rank condition.

    `timestamp__lte=now` is the universe-wide form of this file's cardinal
    rule. A per-instrument evaluator that reads one bar too far corrupts one
    score; a field that does it corrupts an ORDERING, so every instrument the
    winner was chosen over is wrong too, and the flag still looks perfectly
    well-formed afterwards.

    LiveQuote is deliberately not consulted, on either the live or the replay
    path. A field where some members are marked at their last close and others
    at a live tick is not a cross-section at one instant, and the members that
    happen to carry a quote would be ranked on newer information than the rest.

    Members with fewer than `lookback + 1` closes inside the window are
    dropped rather than measured short — a sixty-bar return computed from four
    bars is a different measurement, not a noisier version of the same one.

    The window is bounded at BOTH ends. Its lower bound keeps a member whose
    sixty bars are spread across two years out of a field of three-month
    windows; `MAX_FIELD_STALENESS_DAYS` keeps out the member whose sixty bars
    are dense and complete and simply stop weeks before `now`. Only the second
    bound catches that one, because it is a full window by every count — it is
    just a window ending on a different day from everybody else's, and a rank
    taken across two different days is not a rank.
    """
    from market_data.models import PriceData
    ids = [i.id for i in instruments]
    if not ids:
        return {}, {}
    need = lookback + 1
    # The same widening `_recent_closes` uses to turn a bar count into a date
    # range for daily bars: twice the bars, in calendar days, comfortably spans
    # weekends and holidays without admitting a series from another era.
    cutoff = now - timedelta(days=need * 2)
    freshest_allowed = now - timedelta(days=MAX_FIELD_STALENESS_DAYS)
    # The order_by is load-bearing, not tidiness: PriceData.Meta.ordering is
    # "-timestamp", so inheriting it would hand every measurement its window
    # backwards — `closes[-need:]` would keep the OLDEST bars and every return
    # in the field would come out with its sign flipped. Ascending order is
    # also what makes the last row seen per instrument its newest bar.
    rows = (PriceData.objects
            .filter(instrument_id__in=ids, timeframe=timeframe,
                    timestamp__lte=now, timestamp__gte=cutoff)
            .order_by("instrument_id", "timestamp")
            .values_list("instrument_id", "timestamp", "close"))
    series: dict = {}
    newest: dict = {}
    for instrument_id, timestamp, close in rows.iterator():
        series.setdefault(instrument_id, []).append(float(close))
        newest[instrument_id] = timestamp

    closes_out: dict = {}
    stale_out: dict = {}
    for instrument_id, closes in series.items():
        last_bar = newest[instrument_id]
        if last_bar < freshest_allowed:
            # Reported rather than merely absent: a feed that stopped is an
            # operator's problem, and an instrument that quietly leaves a field
            # looks exactly like one that was never in it.
            stale_out[instrument_id] = last_bar
            continue
        if len(closes) < need:
            continue
        closes_out[instrument_id] = closes[-need:]
    if stale_out:
        logger.info("[opportunity] %d of %d field members dropped as stale "
                    "(last bar older than %dd before %s)",
                    len(stale_out), len(ids), MAX_FIELD_STALENESS_DAYS, now)
    return closes_out, stale_out


class CrossSectionalField:
    """The universe a rank is taken inside, priced once at one pinned instant.

    Construct it with the instrument list a pass has already materialised, so
    the field is the pass's own universe rather than a second query that could
    answer differently. Left empty it resolves the active instruments itself,
    lazily, for a caller scanning a single pair.

    It takes no `as_of`, and that is not an oversight: the field reads bars and
    nothing else, and a bar carries its own vintage in its timestamp. The
    `as_of` flag exists for the sources that have a mutable present-day column
    with no history behind it — MacroIndicator.last_value, LiveQuote — and this
    class touches neither.

    Measurements are memoised per (metric, lookback, short_lookback), so a pass
    in which eight setups all rank sixty-bar momentum prices the universe once.
    """

    def __init__(self, instruments=None, *, now: datetime):
        self._instruments = None if instruments is None else list(instruments)
        self.now = now
        self._closes: dict = {}
        self._values: dict = {}

    @property
    def instruments(self) -> list:
        if self._instruments is None:
            from instruments.models import Instrument
            self._instruments = list(Instrument.objects.filter(is_active=True))
        return self._instruments

    def _priced(self, lookback: int) -> tuple:
        key = int(lookback)
        cached = self._closes.get(key)
        # `is None`, not falsiness: an empty field is a measured answer and
        # must not be re-queried once per condition for the rest of the pass.
        if cached is None:
            cached = self._closes[key] = _field_closes(
                self.instruments, key, self.now)
        return cached

    def stale(self, lookback: int) -> dict:
        """{instrument_id: last bar} for the members dropped as too old to be
        ranked at `self.now`. Read by the evaluator so an unranked instrument
        can be told why, rather than sharing one reason with every other kind
        of absence."""
        return self._priced(lookback)[1]

    def values(self, metric: str, *, lookback: int,
               short_lookback: int = DEFAULT_RANK_SHORT_LOOKBACK) -> dict:
        """{instrument_id: metric value} over the members it could be measured
        for. Members it could not are absent — the caller counts what is here,
        and that count is the field size the thin-field refusal tests."""
        key = (metric, int(lookback), int(short_lookback))
        cached = self._values.get(key)
        if cached is None:
            measure = _RANK_MEASURES[metric]
            measured = {}
            for instrument_id, closes in self._priced(lookback)[0].items():
                value = measure(closes, int(short_lookback))
                if value is not None:
                    measured[instrument_id] = value
            cached = self._values[key] = measured
        return cached


def _rank_refusal(details: dict, reason: str, *, authoring: bool = False,
                  **extra) -> dict:
    """A rank that was not taken, in the shape `scan_setup` can act on.

    `measured: False` is the whole point of the helper. Every path through the
    evaluator that produces no ordering goes through here, so none of them can
    be mistaken for a measured zero by the scan loop, and none can be added
    later without carrying the flag.

    `authoring=True` marks the OTHER kind of refusal: a parameter this setup
    was written with is not one the evaluator understands — an unknown metric,
    an unknown side, a select_pct outside its range. Those are not markets
    declining to answer, they are typos, and the scan loop treats the two
    oppositely for good reason. A market that could not answer is dropped
    from the average so it cannot dilute the legs that did; a typo is KEPT in
    the denominator, exactly as an unknown `kind` already is, so a broken
    condition holds its setup back instead of being carried over the line by
    the legs that still work. Silently excusing an authoring mistake is how a
    setup ends up firing on half the case its author wrote.
    """
    # `measured` is the scan loop's DROP flag, so the mapping reads backwards
    # at a glance and is worth stating: a data refusal is measured=False and
    # leaves the average, an authoring error is measured=True and stays in the
    # denominator to hold its setup back.
    return {"matched": False, "score": 0.0, "measured": bool(authoring),
            "authoring_error": bool(authoring),
            "details": {**details, "reason": reason, **extra}}


def _eval_cross_sectional_rank(params: dict, instrument, now: datetime, *,
                               field: Optional[CrossSectionalField] = None) -> dict:
    """Is this instrument inside the selected slice of its field on `metric`?

    Params:
      metric         — "momentum" | "risk_adjusted_momentum" | "acceleration"
                       | "volatility"
      lookback       — bars in the ranking window (default 60)
      short_lookback — bars in the recent window, "acceleration" only (default 10)
      side           — "top" (highest metric) | "bottom" (lowest)
      scope          — "asset_class" (rank against the same class only) or
                       "universe" (rank against every active instrument)
      select_pct     — fraction of the field the slice takes (default 0.10)
      min_field      — a floor on field size ABOVE the platform's own

    `scope` defaults to the asset class because a mixed field does not rank
    momentum, it ranks volatility: a sixty-bar return puts crypto above every
    equity and every equity above every major pair, so a "top decile of the
    universe" would be a list of whatever asset class moves most, restated
    daily. There is deliberately no "sector" scope — `Instrument.sector` is
    written by nothing in this codebase, so a sector-scoped condition would be
    a rule that can never fire.

    Refusing a thin field is the point of half this function. A "top decile" of
    four instruments is not a decile — the fraction rounds up to one name, and
    the cut that was supposed to exclude nine tenths of the field excludes
    three symbols. The setup gets no flag and a reason, because a rank that
    cannot be taken honestly is not a weaker signal, it is no signal.

    Every path out of here that produces no ordering — a thin field, a fraction
    naming nobody, an instrument outside the field or without a window of its
    own, a param outside its vocabulary — carries `measured: False`, and that
    key is what keeps the refusal out of `scan_setup`'s weighted average
    entirely. Returned as a plain zero it was indistinguishable from "the rank
    was taken and this instrument missed the cut", so the composite gained
    `0.0 * weight` in its numerator and `weight` in its denominator: a leg that
    declined to answer halved a two-leg setup's evidence. An instrument the
    rank actually placed below the cut is a real measurement and keeps both its
    zero and its weight — the distinction is between "we looked and the answer
    is no" and "we could not look", which is the same distinction this file
    already draws for a field member with no window.
    """
    metric = (params or {}).get("metric", "momentum")
    side = (params or {}).get("side", "top")
    scope = (params or {}).get("scope", "asset_class")
    try:
        lookback = int((params or {}).get("lookback", DEFAULT_RANK_LOOKBACK))
        short_lookback = int((params or {}).get(
            "short_lookback", DEFAULT_RANK_SHORT_LOOKBACK))
        select_pct = float((params or {}).get("select_pct", DEFAULT_SELECT_PCT))
        # A setup may demand a DEEPER field than the platform floor; it may not
        # ask for a shallower one. The floor is the whole defence against a
        # rank published over a handful of survivors, and a defence a caller
        # can dial down is not one.
        min_field = max(MIN_RANK_FIELD,
                        int((params or {}).get("min_field", MIN_RANK_FIELD)))
    except (TypeError, ValueError):
        return _rank_refusal({}, "non-numeric lookback/select_pct/min_field",
                             authoring=True)

    # Each vocabulary is checked before it is used, because the failure mode of
    # an unrecognised value here is not silence. Fall through to a default and
    # a typo'd `side` would rank the WEAKEST names as the strongest, and the
    # flag it published would look exactly like a correct one.
    if metric not in ("momentum", "risk_adjusted_momentum", "acceleration",
                      "volatility"):
        return _rank_refusal({}, f"unknown metric '{metric}'", authoring=True)
    if side not in ("top", "bottom"):
        return _rank_refusal({}, f"unknown side '{side}'", authoring=True)
    if scope not in ("asset_class", "universe"):
        return _rank_refusal({}, f"unknown scope '{scope}'", authoring=True)
    if not 0.0 < select_pct <= MAX_SELECT_PCT:
        return _rank_refusal(
            {}, f"select_pct must be in (0, {MAX_SELECT_PCT}]",
            authoring=True)
    if lookback < 2:
        return _rank_refusal({}, "lookback must cover at least 2 bars",
                             authoring=True)

    if field is None:
        field = CrossSectionalField(now=now)
    measured = field.values(metric, lookback=lookback,
                            short_lookback=short_lookback)

    if scope == "asset_class":
        wanted = getattr(instrument, "asset_class", "")
        members = [i for i in field.instruments
                   if getattr(i, "asset_class", "") == wanted]
    else:
        members = field.instruments
    values = {i.id: measured[i.id] for i in members if i.id in measured}

    n = len(values)
    # Floor, never round up. Rounding is exactly how a four-name field produces
    # a "decile" of one, and `n_select < 1` below is the refusal that catches
    # the fields too thin for the fraction to name anybody at all.
    n_select = int(n * select_pct)
    details = {"metric": metric, "lookback": lookback, "scope": scope,
               "side": side, "select_pct": select_pct, "field_size": n,
               "selected": n_select, "min_field": min_field}
    if metric == "acceleration":
        details["short_lookback"] = short_lookback

    if not any(i.id == instrument.id for i in members):
        # Not in the field being ranked at all — an inactive instrument, or one
        # a caller passed that the pass never walked. Unranked is a different
        # answer from ranked last, and this is the one that is true.
        return _rank_refusal(details, "outside the ranked field")
    if n < min_field:
        return _rank_refusal(
            details, f"field of {n} is under the {min_field}-instrument floor")
    if n_select < 1:
        return _rank_refusal(
            details,
            f"{select_pct:.1%} of {n} does not name a whole instrument")

    mine = values.get(instrument.id)
    if mine is None:
        # In the field, but NOT MEASURED at `now`. It is unranked, not worst: a
        # zero here would have put a symbol whose feed went quiet into the
        # middle of a momentum table. A dead feed and a short history are told
        # apart, because they are different problems for whoever reads the
        # flag — one is an ingest to restart, the other is a symbol that has
        # not traded long enough to rank yet.
        stale_at = field.stale(lookback).get(instrument.id)
        if stale_at is not None:
            return _rank_refusal(
                details,
                f"last bar {(now - stale_at).days}d before the field's instant,"
                f" past the {MAX_FIELD_STALENESS_DAYS}d staleness cut",
                last_bar=str(stale_at))
        return _rank_refusal(details, "no full window for this instrument")

    if side == "top":
        better = sum(1 for v in values.values() if v > mine)
        worse = sum(1 for v in values.values() if v < mine)
    else:
        better = sum(1 for v in values.values() if v < mine)
        worse = sum(1 for v in values.values() if v > mine)

    # Ranked by how many of the field beat it, so tied instruments SHARE a rank
    # and either both clear the cut or neither does. Sorting and slicing would
    # have handed the last place in the slice to whichever of two identical
    # numbers the database returned first — a flag decided by row order.
    rank = better + 1
    matched = rank <= n_select
    # The score is the fraction of the field this instrument beats, which is
    # precisely the claim the condition makes: at a decile cut the marginal
    # name scores ~0.9 and the extreme scores 1.0. Depth WITHIN the slice was
    # the alternative and collapses as the slice widens — the marginal name of
    # a forty-name quintile would score 0.125 for being in exactly the group it
    # was selected into. Zero when unmatched, like every other evaluator here,
    # because `scan_setup` weights `score` whether or not `matched` is set —
    # and it should, on this path: the rank WAS taken and this instrument came
    # out below the cut, which is evidence, not an absence of it.
    score = (worse / (n - 1)) if matched and n > 1 else 0.0
    return {"matched": matched, "score": round(min(1.0, max(0.0, score)), 4),
            "measured": True,
            "details": {**details, "value": round(mine, 6), "rank": rank}}


register_kind("cross_sectional_rank", _eval_cross_sectional_rank,
                params=("metric", "lookback", "short_lookback", "side",
                        "select_pct", "min_field", "scope"),
                choices={"metric": ("momentum", "risk_adjusted_momentum",
                                    "acceleration", "volatility"),
                         "side": ("top", "bottom"),
                         "scope": ("asset_class", "universe")})


# ── Scoring + flagging ─────────────────────────────────────────────────────

def _suggested_levels(direction: str, last_price: float, sizing: dict) -> tuple:
    """Return (entry, stop, target) from `stop_pct` and `target_rr`.

    Percentage stop and an R-multiple target are the only two knobs there are —
    there is no ATR branch and no absolute-target branch, so `stop_atr_mult`
    and `target_pct` are silently ignored wherever they appear. `SIZING_KEYS`
    is the declaration of that; `unknown_sizing_keys` is how a caller checks.
    """
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


def _last_price(instrument, now: datetime, *, as_of: bool = False) -> Optional[float]:
    """Most recent close ≤ now, falling back to the live quote unless `as_of`.

    `as_of` is the CALLER's statement that it is replaying history, and nothing
    else may stand in for it. Deriving it from elapsed wall clock — "now is
    more than five minutes old, so this must be a replay" — made a live sweep's
    output a function of how long the sweep took: `scan_all_setups` pins one
    `now` for the whole pass, so every instrument reached after minute five
    silently lost its LiveQuote fallback and its matches went unflagged.
    """
    from market_data.models import PriceData, LiveQuote
    p = (PriceData.objects
         .filter(instrument=instrument, timestamp__lte=now)
         .order_by("-timestamp").values_list("close", flat=True).first())
    if p is not None:
        return float(p)
    # LiveQuote holds one row per instrument with no history, so it only ever
    # answers "the price right now". Handing it to a replay would price a
    # historical scan at today's quote; that caller gets None instead.
    if as_of:
        return None
    try:
        lq = instrument.live_quote
        return float(lq.last) if lq.last is not None else None
    except Exception:
        return None


def _emit_match(setup, instrument, composite: float, conditions_out: list,
                last_price: float) -> dict:
    """Write the Signal + OpportunityFlag for a match that has cleared every
    check, and return the pair's result dict.

    Split out of `scan_setup` so a pass can hold a match back. Whether two
    setups contradict each other is a property of the PAIR, and it is only
    knowable once both have been scored — a function that scores and writes in
    one breath can never suppress more than whichever one it reached second.
    """
    from signals.models import OpportunityFlag, Signal

    entry, stop, target = _suggested_levels(setup.direction, last_price,
                                            setup.sizing or {})
    risk_per = abs(entry - stop)
    rr = abs((target - entry) / risk_per) if risk_per > 0 else None

    # ONE active Signal per (instrument, rule) — the same dedupe the rule
    # engine has always applied (signals/tasks.py). Without it a setup that
    # still matched on a later pass — the 09:00 beat, then an admin's Run Now
    # — wrote a second identical row, and the bot's consensus sums evidence
    # PER ROW: `aggregation.side_weight` adds each row's contribution while
    # `rules` is a SET of names, so one setup's 0.80 counted twice for a net
    # weight of 1.60 against a rule count of 1. A single setup could outvote
    # a genuine opposing rule and turn a HOLD into a live BUY. decide()'s
    # top-32 cut assumes the same invariant in as many words: "per-rule
    # dedupe keeps the real row count near the rule count".
    #
    # The existing row is REUSED, not refreshed: price_at_signal and the
    # levels are the basis grading measures R against, and rewriting them
    # mid-life would re-anchor an outcome already in flight.
    #
    # `signal_type` is part of the lookup, not decoration. Setup names and
    # rule names live in the same `rule_name` column, so a setup that shares
    # a name with a rule-engine rule would otherwise adopt the rule engine's
    # Signal and hang its OpportunityFlag on a row it did not write.
    signal = (Signal.objects
              .filter(instrument=instrument, rule_name=setup.name,
                      signal_type="composite", is_active=True)
              .order_by("-created_at").first())
    if signal is None:
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
    else:
        logger.debug("[opportunity] %s x %s already has active signal %s — "
                     "flagging against it instead of writing a duplicate",
                     setup.name, instrument.symbol, signal.pk)

    # The FLAG is still written every pass. A flag is a moment — it records
    # that the setup matched on this date at this price, and
    # `resolve_pending_flags` grades flags, not signals.
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


def scan_setup(setup, instrument, *, now: Optional[datetime] = None,
               as_of: Optional[bool] = None, emit: bool = True,
               field: Optional[CrossSectionalField] = None) -> dict:
    """Run one setup against one instrument. Returns a dict and creates an
    OpportunityFlag (+ linked Signal) if the composite score meets `min_match_score`.

    `as_of=True` says the caller is replaying history and must not be handed
    present-day state. Left at None it defaults to `now is not None`, which is
    the honest reading of a caller that named its own instant — batch callers
    that pin one `now` for a whole live pass pass `as_of=False` explicitly.

    `emit=False` scores the pair and writes nothing, returning the match with
    `pending: True` plus the `last_price` the rows would have been built from.
    `scan_all_setups` uses it to see a whole instrument's matches before any
    of them is published; a direct caller wanting the flag keeps the default.

    `field` is the universe a cross-sectional condition ranks this instrument
    inside. A pass hands the SAME field to every pair, so every rank it
    publishes was taken against one set of measurements at one instant; a
    caller scanning a single pair leaves it unset and gets a field built here,
    lazily, and only if one of the setup's conditions actually asks for one.

    An evaluator may answer `measured: False` to say it did not measure at all.
    Such a leg is left out of the weighted average entirely — numerator AND
    denominator — because a zero in the denominator is an assertion about the
    market, and the composite would fall by half for a leg that never looked.
    """
    if as_of is None:
        as_of = now is not None
    now = now or timezone.now()

    # Asset-class gate.
    if setup.asset_classes:
        if instrument.asset_class not in setup.asset_classes:
            return {"matched": False, "skipped": True, "reason": "asset_class_filter"}

    conditions_out = []
    weighted_score_sum = 0.0
    weight_sum = 0.0
    weight_authored = 0.0
    scoring_legs = 0
    measured_legs = 0
    for cond in (setup.conditions or []):
        kind = cond.get("kind", "")
        params = cond.get("params") or {}
        weight = float(cond.get("weight", 1.0))
        # A gate answers "does this setup apply to this symbol at all", so it
        # contributes no score and no denominator: a universe check that can be
        # outvoted by evidence is not a universe check.
        is_gate = bool(cond.get("gate"))
        if not has_kind(kind):
            conditions_out.append({"kind": kind, "matched": False, "score": 0.0,
                                    "details": {"reason": "unknown kind"},
                                    "weight": weight, "gate": is_gate})
            if is_gate:
                return {"matched": False, "skipped": True, "reason": "gate_failed",
                        "conditions": conditions_out}
            # Kept in the denominator on purpose. An unknown kind is an
            # authoring mistake, not a market that would not answer, and
            # dropping it would let a typo'd condition be carried over the line
            # by the legs that still work instead of holding the setup back.
            scoring_legs += 1
            measured_legs += 1
            weight_sum += weight
            weight_authored += weight
            continue
        try:
            # Both keywords are opt-in and were resolved at registration, so a
            # kind that declares neither is still called with exactly the three
            # arguments it was written for.
            extra = {}
            if ACCEPTS_AS_OF.get(kind):
                extra["as_of"] = as_of
            if ACCEPTS_FIELD.get(kind):
                # Built on first demand and reused for the rest of this pair's
                # conditions, so a setup with no rank condition never queries
                # the universe and one with three ranks queries it once.
                if field is None:
                    field = CrossSectionalField(now=now)
                extra["field"] = field
            res = EVALUATOR_REGISTRY[kind](params, instrument, now, **extra)
        except Exception as e:
            logger.warning("[opportunity] evaluator %s raised: %s", kind, e)
            res = {"matched": False, "score": 0.0, "details": {"error": str(e)}}
        conditions_out.append({"kind": kind, "weight": weight, "gate": is_gate, **res})
        if is_gate:
            # Fails closed: an unknown kind or a raising evaluator leaves the
            # gate shut, because the alternative is a setup quietly firing on
            # the symbols it was written to exclude.
            if not res.get("matched"):
                return {"matched": False, "skipped": True, "reason": "gate_failed",
                        "conditions": conditions_out}
            continue
        scoring_legs += 1
        # A top-level `measured: False` on the result is the evaluator saying it
        # never answered the question it was asked — no field to rank in, no
        # window to rank on. Weighted at zero it would be indistinguishable from
        # an evaluator that looked and found nothing, and it would take `weight`
        # into the denominator with it, so a refusal to measure one leg would
        # quietly dilute every other leg's evidence. Strictly opt-in: a kind
        # that never sets the key keeps exactly the arithmetic it had, and an
        # evaluator that RAISES is still scored zero and still weighted, because
        # one broken data source must not void a whole composite.
        weight_authored += weight
        if res.get("measured") is False:
            continue
        measured_legs += 1
        weighted_score_sum += float(res.get("score", 0.0)) * weight
        weight_sum += weight

    composite = (weighted_score_sum / weight_sum) if weight_sum > 0 else 0.0
    # A setup that carries scoring conditions and measured none of them has no
    # composite — not a composite of zero. Reading the hole as a score would
    # publish a flag on nothing at all for any setup whose `min_match_score`
    # sits at zero. A setup built entirely out of gates is untouched: it has no
    # scoring conditions to have failed to measure, and its threshold decides
    # as it always did.
    #
    # And a QUORUM, because dropping an unmeasured leg renormalises the
    # composite over the survivors: a two-leg setup whose second leg could not
    # answer becomes a one-leg setup scoring the first leg at full confidence,
    # and fires on evidence its author never authorised alone. A MAJORITY of
    # the authored weight has to answer — strictly more than half, so one of
    # two equal legs does not clear it, which is the case this exists for. The
    # counts ride out on the result so a reader can see the composite rests on
    # less than the whole setup.
    enough = (weight_authored <= 0
              or weight_sum > weight_authored * MEASURED_WEIGHT_QUORUM)
    matched = ((scoring_legs == 0 or measured_legs > 0)
               and enough
               and composite >= float(setup.min_match_score or 0.0))

    if not matched:
        out = {"matched": False, "score": round(composite, 4),
               "conditions": conditions_out,
               "measured_weight": round(weight_sum, 4),
               "authored_weight": round(weight_authored, 4)}
        if not enough:
            out["skipped"] = True
            out["reason"] = "not_enough_measured"
        return out

    # Build the levels + Signal + Flag.
    last_price = _last_price(instrument, now, as_of=as_of)
    if last_price is None or last_price <= 0:
        return {"matched": False, "skipped": True, "reason": "no_price_data",
                "score": round(composite, 4), "conditions": conditions_out}

    if not emit:
        return {"matched": True, "pending": True, "score": round(composite, 4),
                "last_price": last_price, "conditions": conditions_out}

    return _emit_match(setup, instrument, composite, conditions_out, last_price)


def scan_all_setups(*, now: Optional[datetime] = None,
                    as_of: Optional[bool] = None) -> dict:
    """Walk every active setup × every active instrument; create flags for matches.

    The pass pins one `now` and hands the SAME `as_of` to every pair, so a pass
    that takes an hour produces the same flags as one that takes a minute.

    The returned dict accounts for every pair it counted in `evaluations`.
    It used to report only (setups, instruments, evaluations, matches), and
    `evaluations` counts every pair ATTEMPTED while `matches` counts only the
    ones that produced a flag — so the whole middle of the funnel was invisible.
    A gate is the sharp case: `starter_usd_weakness_macro` gates ~53 of the 79
    symbols in its asset classes before any evidence is read, and that is by
    design, but on this dict it looked exactly like an evaluator that had
    started raising or a macro leg that had gone inert. The counters below name
    each drop so a falling flag count can be attributed instead of guessed at:

        asset_class_skipped  pair outside the setup's asset_classes
        gate_skipped         a gate condition said the setup does not apply here
        no_price_data        scored a match but had no price to build levels from
        contradiction_skipped  matched, but another setup matched the SAME
                             instrument this pass pointing the other way
        emit_errors          cleared everything and then failed to write the rows
        scored               reached the composite (the honest denominator for
                             `matches`)
        evaluator_errors     conditions whose evaluator raised — already logged
                             per occurrence, now countable
        errors               the pair itself raised out of `scan_setup`

    Only the first three of those and `errors` partition `evaluations`:
    `no_price_data`, `contradiction_skipped` and `emit_errors` all describe
    pairs that reached the composite, so they are sub-counts of `scored` and
    the identity stays
        scored + asset_class_skipped + gate_skipped + errors == evaluations

    Deliberately none of these keys is named `skipped`, `attempted`, `parsed`,
    `stored` or `fetched`: `core.task_gate.judge_result` reads a top-level
    `skipped` as "not configured" and treats the other four as work/done counts,
    so either would restate a healthy scan that legitimately matched nothing as
    a warning on the component's health record.

    Publication is deferred to the end of the pass. Two setups can point
    opposite ways at the same instrument on the same bar — advanced_smc_long
    and advanced_smc_short both fire on one outside bar that sweeps both sides
    of a coil and closes back inside it — and each is individually correct by
    its own conditions. Published, that pair is a bullish and a bearish Signal
    on one instrument at one instant: two rules both graded on a coin flip,
    feeding expectancy back into the very weights that decide the next entry.
    Nothing downstream can reconstruct which bar caused it. So the pass
    publishes NEITHER side, which is the fail-towards-not-trading answer and
    the only symmetric one — suppressing whichever arrived second would just
    hand the trade to the setup that sorted first.

    The pass also owns the FIELD that cross-sectional conditions rank inside,
    for the same reason it owns `now`: it is the only place that holds the
    whole universe at one instant. Building the field from the very list this
    loop walks means a rank is taken against exactly the instruments this pass
    evaluated — a second query could return a different universe — and sharing
    one field across every pair means the universe is priced once instead of
    once per (setup, instrument) pair, and that two setups ranking the same
    window can never be handed two different orderings of it.
    """
    from signals.models import OpportunitySetup
    from instruments.models import Instrument

    if as_of is None:
        as_of = now is not None
    now = now or timezone.now()
    setups = list(OpportunitySetup.objects.filter(is_active=True))
    instruments = list(Instrument.objects.filter(is_active=True))
    field = CrossSectionalField(instruments, now=now)

    n_matches = 0
    n_evaluations = 0
    n_scored = 0
    n_errors = 0
    n_evaluator_errors = 0
    n_emit_errors = 0
    n_contradiction = 0
    skips = {"asset_class_filter": 0, "gate_failed": 0, "no_price_data": 0}
    # instrument.id -> [(setup, instrument, result), ...] held back until the
    # whole pass has been scored. Only matches land here, so this stays tiny.
    pending: dict = {}
    for setup in setups:
        for inst in instruments:
            n_evaluations += 1
            try:
                result = scan_setup(setup, inst, now=now, as_of=as_of,
                                    emit=False, field=field)
            except Exception as e:
                n_errors += 1
                logger.warning("[opportunity] scan failed setup=%s inst=%s: %s",
                               setup.name, inst.symbol, e)
                continue
            # An evaluator that raises is caught inside scan_setup and scored 0,
            # which is right — one broken data source must not void a whole
            # composite — but it leaves the score quietly understated. The
            # detail it writes is the only record, so count it here.
            for cond in (result.get("conditions") or []):
                if "error" in (cond.get("details") or {}):
                    n_evaluator_errors += 1
            reason = result.get("reason")
            if reason in ("asset_class_filter", "gate_failed"):
                # Dropped before the composite — these are universe decisions.
                skips[reason] += 1
                continue
            # Everything past here reached the composite, so `scored` is the
            # denominator `matches` is honestly a numerator of:
            #   scored + asset_class_skipped + gate_skipped + errors == evaluations
            n_scored += 1
            if reason == "no_price_data":
                # Cleared the bar and then had nothing to price the levels from.
                skips[reason] += 1
            elif result.get("matched"):
                pending.setdefault(inst.id, []).append((setup, inst, result))

    # ── Publish, one instrument at a time ────────────────────────────────
    for matches in pending.values():
        directions = {m[0].direction for m in matches}
        if "bullish" in directions and "bearish" in directions:
            n_contradiction += len(matches)
            logger.warning(
                "[opportunity] %s: %d setups disagree on direction this pass "
                "(%s) — publishing none of them",
                matches[0][1].symbol, len(matches),
                ", ".join(f"{s.name}={s.direction}" for s, _, _ in matches))
            continue
        for setup, inst, result in matches:
            try:
                _emit_match(setup, inst, result["score"], result["conditions"],
                            result["last_price"])
            except Exception as e:
                # Counted separately from `errors`: the pair already reached
                # the composite and is already inside `scored`, so folding it
                # into `errors` would break the partition of `evaluations`.
                n_emit_errors += 1
                logger.warning("[opportunity] could not publish %s × %s: %s",
                               setup.name, inst.symbol, e)
                continue
            n_matches += 1

    return {
        "setups_scanned": len(setups),
        "instruments_scanned": len(instruments),
        "evaluations": n_evaluations,
        "scored": n_scored,
        "matches": n_matches,
        "asset_class_skipped": skips["asset_class_filter"],
        "gate_skipped": skips["gate_failed"],
        "no_price_data": skips["no_price_data"],
        "contradiction_skipped": n_contradiction,
        "evaluator_errors": n_evaluator_errors,
        "emit_errors": n_emit_errors,
        "errors": n_errors,
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

def resolve_pending_flags(*, now: Optional[datetime] = None,
                          as_of: Optional[bool] = None) -> dict:
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

    if as_of is None:
        as_of = now is not None
    now = now or timezone.now()
    qs = OpportunityFlag.objects.filter(outcome="").select_related("instrument", "signal")

    resolved = {"hit": 0, "miss": 0, "neutral": 0, "expired": 0, "skipped": 0}

    for flag in qs:
        deadline = flag.scanned_at + timedelta(days=flag.horizon_days)
        if now < deadline:
            resolved["skipped"] += 1
            continue

        last = _last_price(flag.instrument, now, as_of=as_of)
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
