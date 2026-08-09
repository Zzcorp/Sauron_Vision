"""Outcome-weighted signal aggregation.

The original `decide()` entered when N rules agreed above a score threshold
and none disagreed, scoring by a plain average. That treats a rule with a
measured 60% hit rate and one with a measured 45% hit rate identically —
the system collected evidence about which rules work and then ignored it at
the moment of decision. (The meta-allocator did use it, but only to adjust
SIZE after the entry had already been chosen.)

Here each rule's vote is weighted by its own realised expectancy, and the
opposing side is subtracted rather than acting as a veto, so one stale
counter-signal cannot block a strongly-evidenced setup.

Weights come from closed Signal rows (signals.performance) and closed bot
trades (bot_program.bot_grading), both of which already exist. A rule with
too little history gets weight 1.0 — neutral, neither rewarded nor punished.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Below this many closed outcomes a rule has no measured edge — stay neutral.
MIN_SAMPLES = 10
# Clamp so one lucky streak cannot dominate the book.
MIN_WEIGHT = 0.25
MAX_WEIGHT = 2.0
# Net evidence a side must carry before we act on it. Callers normally pass
# min_signals_for_entry × entry_score_min so the weighted path demands the
# same evidence the old headcount path did.
DEFAULT_MIN_NET_WEIGHT = 0.6


def rule_weight(rule_name: str, asset_class: str = "",
                *, signal_stats: dict | None = None) -> float:
    """Evidence weight for a rule, centred on 1.0.

    >1 means the rule has demonstrated positive expectancy; <1 means it has
    demonstrated the opposite. Absent evidence, exactly 1.0.

    `signal_stats` is the already-computed output of
    `calculate_signal_stats(days=180, group_by="rule_name")`. Pass it when
    weighting several rules at once: that call aggregates six months of
    signals, and running it per rule turned one decision into thousands of
    queries. Omitted, it is computed here for the single-rule case.
    """
    if not rule_name:
        return 1.0
    weight = 1.0
    matched = False

    # Bot-trade record first: same execution path, so the most relevant.
    if asset_class:
        try:
            from bot_program.bot_grading import bot_trade_track_record
            multiplier = bot_trade_track_record(rule_name, asset_class,
                                                 min_n=MIN_SAMPLES)
            if multiplier != 1.0:
                weight *= float(multiplier)
                matched = True
        except Exception as e:
            logger.debug("[aggregation] bot track record failed for %s: %s",
                         rule_name, e)

    # Signal record as a fallback/complement — a much larger sample.
    try:
        if signal_stats is None:
            signal_stats = _signal_stats()
        row = (signal_stats or {}).get(rule_name)
        if row and (row.get("n_closed") or 0) >= MIN_SAMPLES:
            expectancy = row.get("expectancy_r")
            if expectancy is not None:
                # +0.5R expectancy -> 1.25x, -0.5R -> 0.75x.
                weight *= max(0.5, min(1.5, 1.0 + float(expectancy) * 0.5))
                matched = True
    except Exception as e:
        logger.debug("[aggregation] signal stats failed for %s: %s",
                     rule_name, e)

    if not matched:
        return 1.0
    return max(MIN_WEIGHT, min(MAX_WEIGHT, weight))


def _signal_stats() -> dict:
    try:
        from signals.performance import calculate_signal_stats
        return calculate_signal_stats(days=180, group_by="rule_name") or {}
    except Exception as e:
        logger.debug("[aggregation] calculate_signal_stats failed: %s", e)
        return {}


def weighted_consensus(bullish, bearish, *, asset_class: str = "",
                       min_net_weight: float = DEFAULT_MIN_NET_WEIGHT,
                       min_signals: int = 1) -> dict:
    """Weigh both sides by evidence and return the net verdict.

    `bullish` / `bearish` are Signal-like objects exposing `score` and
    `rule_name`. Returns a dict with the direction, the net weight, the
    winning side's weighted score and its top rule.

    `min_signals` is a hard floor on how many distinct rules must agree,
    mirroring the config's min_signals_for_entry. Without it a single rule
    that has earned a 2.0 weight can clear a threshold meant to represent
    two independent confirmations — the config would read as "2 signals"
    while the bot traded on one.
    """
    # One stats aggregation for the whole decision, shared by every rule.
    stats = _signal_stats()
    weights: dict[str, float] = {}

    def weight_for(rule: str) -> float:
        if rule not in weights:
            weights[rule] = rule_weight(rule, asset_class, signal_stats=stats)
        return weights[rule]

    def side_weight(signals):
        total, best, best_rule = 0.0, 0.0, ""
        rules = set()
        for s in signals:
            rule = getattr(s, "rule_name", "")
            contribution = float(getattr(s, "score", 0) or 0) * weight_for(rule)
            total += contribution
            rules.add(rule)
            if contribution > best:
                best, best_rule = contribution, rule
        return total, best_rule, len(rules)

    bull_weight, bull_rule, bull_rules = side_weight(bullish)
    bear_weight, bear_rule, bear_rules = side_weight(bearish)
    net = bull_weight - bear_weight

    if net >= min_net_weight:
        if bull_rules < min_signals:
            return {"direction": "HOLD", "net_weight": round(net, 4),
                    "score": 0.0, "rule_name": "",
                    "detail": (f"bull evidence {net:+.2f} clears "
                               f"{min_net_weight:.2f} but only {bull_rules} "
                               f"rule(s) agree, need {min_signals}")}
        weighted_score = bull_weight / max(len(bullish), 1)
        return {"direction": "BUY", "net_weight": round(net, 4),
                "score": min(1.0, round(weighted_score, 4)),
                "rule_name": bull_rule,
                "detail": f"bull {bull_weight:.2f} vs bear {bear_weight:.2f}"}
    if -net >= min_net_weight:
        if bear_rules < min_signals:
            return {"direction": "HOLD", "net_weight": round(-net, 4),
                    "score": 0.0, "rule_name": "",
                    "detail": (f"bear evidence {-net:+.2f} clears "
                               f"{min_net_weight:.2f} but only {bear_rules} "
                               f"rule(s) agree, need {min_signals}")}
        weighted_score = bear_weight / max(len(bearish), 1)
        return {"direction": "SELL", "net_weight": round(-net, 4),
                "score": min(1.0, round(weighted_score, 4)),
                "rule_name": bear_rule,
                "detail": f"bear {bear_weight:.2f} vs bull {bull_weight:.2f}"}
    return {"direction": "HOLD", "net_weight": round(abs(net), 4),
            "score": 0.0, "rule_name": "",
            "detail": f"net evidence {net:+.2f} below {min_net_weight:.2f}"}
