"""Phase 52 — Cross-rule correlation audit.

When many rules are active simultaneously, they may unknowingly trade the
same factor. Two detectors that surface this:

  detect_position_overlap()
    Pairs of active rules currently holding the same `(symbol, side)`.
    A "side" overlap means stacked exposure (both long, or both short)
    on the same instrument. Catches accidental concentration.

  detect_evaluator_signature_overlap()
    Pairs of active OpportunitySetups whose evaluator-kind sets have
    Jaccard similarity ≥ DEFAULT_SIGNATURE_THRESHOLD (default 0.8).
    Two rules with nearly the same evaluators behind them are
    structurally duplicative — diversification illusion.

Both feed the existing Phase-51 anomaly pipeline by being registered in
`anomaly_scanner.DETECTORS`. They emit `anomaly_detected` BrainObservations
that the brain reads in its 30-min cycle.

Cost: $0 — pure Python, deterministic.
"""
from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────────────

DEFAULT_SIGNATURE_THRESHOLD = 0.8
DEFAULT_MAX_RULES_TO_AUDIT = 30
DEFAULT_MIN_OVERLAP_RULES = 2  # 2+ rules on the same (symbol, side) is an overlap

# Phase-53 — realized-return correlation defaults
DEFAULT_RETURN_CORR_LOOKBACK_DAYS = 30
DEFAULT_RETURN_CORR_THRESHOLD = 0.7
DEFAULT_RETURN_CORR_MIN_OVERLAP_DAYS = 8


# ── Helpers ───────────────────────────────────────────────────────────────

def _evaluator_signature(conditions) -> frozenset[str]:
    """Return the SET of evaluator `kind`s used by a setup. Dominant
    similarity heuristic — two rules using the same evaluators are likely
    trading the same factor regardless of weight differences."""
    if not isinstance(conditions, list):
        return frozenset()
    kinds = set()
    for c in conditions:
        if isinstance(c, dict):
            k = c.get("kind")
            if k:
                kinds.add(str(k))
    return frozenset(kinds)


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Standard Jaccard similarity on two sets. 0..1. Empty-vs-empty = 0."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _pearson(xs, ys):
    """Pearson product-moment correlation on two equal-length series.

    Returns None when:
      - lengths differ or n < 2 (undefined)
      - either series has zero variance (constant — no correlation defined)
    """
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    den = (var_x * var_y) ** 0.5
    if den <= 0:
        return None
    return max(-1.0, min(1.0, num / den))


def _daily_realized_r_series(rule_name: str, *,
                                lookback_days: int) -> dict:
    """For one rule, return {date: sum(realized_r)} over the lookback window.

    Aggregates trades that CLOSED on a given day. Days with no trades
    have no entry — series is sparse, callers must intersect.
    """
    try:
        from bot_program.models import AssetBotTrade
    except Exception:
        return {}
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    cutoff = _tz.now() - _td(days=max(1, int(lookback_days)))
    rows = (
        AssetBotTrade.objects
        .filter(rule_name=rule_name, status="CLOSED",
                closed_at__gte=cutoff,
                realized_r__isnull=False)
        .values_list("closed_at", "realized_r")
    )
    series: dict = {}
    for closed_at, r in rows:
        if closed_at is None or r is None:
            continue
        d = closed_at.date()
        series[d] = series.get(d, 0.0) + float(r)
    return series


# ── Detector: Position overlap ──────────────────────────────────────────

def detect_position_overlap(*,
                              min_overlap: int = DEFAULT_MIN_OVERLAP_RULES
                              ) -> list[dict]:
    """Walk active AssetBotTrades, group by `(symbol, side, rule_name)`,
    then group by `(symbol, side)` to find cases where multiple rules are
    simultaneously holding the same instrument in the same direction.

    Returns one anomaly per overlapping (symbol, side) group.
    """
    out: list[dict] = []
    try:
        from bot_program.models import AssetBotTrade
    except Exception:
        return out

    rows = list(
        AssetBotTrade.objects.filter(status__in=("OPEN", "CLOSE_PENDING"))
        .exclude(rule_name="")
        .values("symbol", "side", "rule_name")
    )
    # Group: (symbol, side) → set of rule_names
    groups: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        key = (r["symbol"], r["side"])
        groups.setdefault(key, set()).add(r["rule_name"])

    for (symbol, side), rules in groups.items():
        if len(rules) < min_overlap:
            continue
        rules_sorted = sorted(rules)
        out.append({
            "detector": "position_overlap",
            "key": f"{symbol}_{side}_{'_'.join(rules_sorted)}",
            "symbol": symbol,
            "side": side,
            "rule_count": len(rules_sorted),
            "rules": rules_sorted,
            "text": (f"Position overlap: {len(rules_sorted)} rules "
                      f"holding {symbol} {side} simultaneously "
                      f"({', '.join(rules_sorted)})"),
        })
    return out


# ── Detector: Evaluator signature overlap ───────────────────────────────

def detect_evaluator_signature_overlap(*,
                                          threshold: float = DEFAULT_SIGNATURE_THRESHOLD,
                                          max_rules: int = DEFAULT_MAX_RULES_TO_AUDIT
                                          ) -> list[dict]:
    """Pairs of active OpportunitySetups whose evaluator-kind sets overlap
    above `threshold` (Jaccard). Bounded at `max_rules` to keep cost O(N²)
    manageable.

    Skips pairs where either setup has fewer than 2 evaluators (single-
    evaluator rules trivially overlap on any single shared kind).
    """
    out: list[dict] = []
    try:
        from signals.models_opportunity import OpportunitySetup
    except Exception:
        return out

    setups = list(
        OpportunitySetup.objects.filter(is_active=True)
        .order_by("name")[:max_rules]
        .values("id", "name", "direction", "conditions")
    )
    # Pre-compute signatures so we don't re-derive in the inner loop.
    sigs = []
    for s in setups:
        sig = _evaluator_signature(s["conditions"])
        if len(sig) < 2:
            continue  # single-evaluator rules are too noisy for this audit
        sigs.append((s, sig))

    seen_pairs: set[tuple[str, str]] = set()
    for i, (sa, sig_a) in enumerate(sigs):
        for sb, sig_b in sigs[i + 1:]:
            sim = _jaccard(sig_a, sig_b)
            if sim < threshold:
                continue
            # Stable pair key (alphabetic order so dedupe works).
            names = tuple(sorted([sa["name"], sb["name"]]))
            if names in seen_pairs:
                continue
            seen_pairs.add(names)
            common = sorted(sig_a & sig_b)
            out.append({
                "detector": "signature_overlap",
                "key": f"{names[0]}__VS__{names[1]}",
                "rule_a": names[0],
                "rule_b": names[1],
                "jaccard": round(sim, 4),
                "shared_evaluators": common,
                "text": (
                    f"Signature overlap {sim:.0%} between {names[0]} "
                    f"and {names[1]} ({len(common)} shared evaluators: "
                    f"{', '.join(common[:5])}"
                    f"{'...' if len(common) > 5 else ''})"
                ),
            })
    return out


# ── Phase-53 Detector: Realized-return correlation ──────────────────────

def detect_realized_return_correlation(*,
                                          lookback_days: int = DEFAULT_RETURN_CORR_LOOKBACK_DAYS,
                                          threshold: float = DEFAULT_RETURN_CORR_THRESHOLD,
                                          min_overlap_days: int = DEFAULT_RETURN_CORR_MIN_OVERLAP_DAYS,
                                          max_rules: int = DEFAULT_MAX_RULES_TO_AUDIT
                                          ) -> list[dict]:
    """Pairs of active rules whose daily realized-R series correlate ≥ threshold
    over the lookback window with at least `min_overlap_days` shared trading days.

    Stronger signal than `signature_overlap` — catches rules that LOOK
    different (different evaluators) but TRADE the same factor in practice.

    Cost: bounded by `max_rules` (default 30), O(N²) pairs, but the inner
    work is trivial — sum of products on series of size ≤ lookback_days.
    """
    out: list[dict] = []
    try:
        from signals.models_control import RuleControl
    except Exception:
        return out

    # Active rules with a registered RuleControl entry.
    rules = list(
        RuleControl.objects
        .filter(status="active")
        .order_by("rule_name")[:max_rules]
        .values_list("rule_name", flat=True)
    )

    # Pre-build series so we don't requery for the inner loop.
    series_by_rule: dict[str, dict] = {}
    for r in rules:
        s = _daily_realized_r_series(r, lookback_days=lookback_days)
        if len(s) >= min_overlap_days:
            series_by_rule[r] = s
    eligible = sorted(series_by_rule.keys())

    seen_pairs: set[tuple[str, str]] = set()
    for i, ra in enumerate(eligible):
        sa = series_by_rule[ra]
        for rb in eligible[i + 1:]:
            sb = series_by_rule[rb]
            shared_dates = sorted(set(sa.keys()) & set(sb.keys()))
            if len(shared_dates) < min_overlap_days:
                continue
            xs = [sa[d] for d in shared_dates]
            ys = [sb[d] for d in shared_dates]
            corr = _pearson(xs, ys)
            if corr is None or corr < threshold:
                continue
            names = tuple(sorted([ra, rb]))
            if names in seen_pairs:
                continue
            seen_pairs.add(names)
            out.append({
                "detector": "realized_return_correlation",
                "key": f"{names[0]}__VS__{names[1]}",
                "rule_a": names[0],
                "rule_b": names[1],
                "correlation": round(corr, 4),
                "n_overlap_days": len(shared_dates),
                "lookback_days": lookback_days,
                "text": (
                    f"Realized-return correlation {corr:.2f} between "
                    f"{names[0]} and {names[1]} over {len(shared_dates)} "
                    f"shared trading days — these rules are trading the "
                    f"same factor."
                ),
            })
    return out
