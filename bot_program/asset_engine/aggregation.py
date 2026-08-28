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

Bot-trade evidence is VENUE-SPECIFIC. A paper fill is charged a modelled
half-spread on both sides and rests no stop at a broker; a live fill books
the raw mark against a real bracket. Weighting a live entry with the pooled
number lets simulated fills choose the direction and the score of a real
order, and the pooled average is not even a compromise between the two — it
estimates neither venue. So `rule_weight` takes the venue the entry is
headed for and asks the ledger only about that venue.
"""
from __future__ import annotations

import logging

from bot_program.bot_grading import VENUE_LIVE, VENUE_PAPER

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

# The venues a decision may honestly be weighed on. VENUE_ALL is absent on
# purpose: pooled paper+live is the exact number this module exists to keep
# out of an order, so naming it here is a caller bug rather than a request.
_DECISION_VENUES = (VENUE_LIVE, VENUE_PAPER)


def _check_decision_venue(venue: str | None) -> None:
    """Raise on a venue the decision path cannot weigh with.

    `None` is legal and means "the caller did not say" — the bot-trade lane
    is then skipped, which is a stated, logged choice. Any OTHER unrecognised
    value is a typo or a request for the pooled record, and both used to land
    in exactly the same silent 1.0 as "no evidence": the caller believed it
    had asked for live fills and got a neutral weight from nothing.

    `bot_grading._venue_filter` raises for the same reason, but its ValueError
    could not reach the decision path: the membership guard in `rule_weight`
    skipped the query before it ran, and the broad `except` around that query
    logged away whatever the guard let through. Two suppressions, so the raise
    protected nothing where it mattered. The authoritative check therefore
    lives here, next to where the venue is chosen and outside any try block;
    `rule_weight` re-raises ValueError from the ledger as a second line.
    """
    if venue is not None and venue not in _DECISION_VENUES:
        raise ValueError(
            f"venue must be one of {_DECISION_VENUES} or None on the decision "
            f"path, got {venue!r} — pooled paper+live evidence must never "
            f"weight an order")


def rule_weight(rule_name: str, asset_class: str = "",
                *, signal_stats: dict | None = None,
                venue: str | None = None) -> float:
    """Evidence weight for a rule, centred on 1.0.

    >1 means the rule has demonstrated positive expectancy; <1 means it has
    demonstrated the opposite. Absent evidence, exactly 1.0.

    `venue` is the venue the entry being weighed will actually be filled on
    — VENUE_LIVE or VENUE_PAPER. The bot-trade lane then asks the ledger for
    that venue's closes only. A rule that has never traded live carries no
    live evidence and so weighs 1.0 on a live entry, which is the whole
    point: a research- or paper-stage rule may still cast a vote toward a
    live order (its signals are real), but it may no longer lend that order
    the expectancy of fills that never had to clear a real book.

    `venue=None` means the caller did not say, and the bot-trade lane is
    then SKIPPED rather than falling back to the pooled record. Pooled is
    the wrong number for both venues, and a wrong number applied to money is
    worse than a missing one; the signal lane, which grades forecasts rather
    than executions and so has no venue, still applies. Callers on the
    decision path must pass the venue.

    Any venue that is neither None nor live/paper raises ValueError — see
    `_check_decision_venue`. Silently treating it as "unstated" would hand a
    caller that asked for live evidence the same neutral 1.0 as a rule with
    no history, and it would do so without a line in the log.

    `signal_stats` is the already-computed output of
    `calculate_signal_stats(days=180, group_by="rule_name")`. Pass it when
    weighting several rules at once: that call aggregates six months of
    signals, and running it per rule turned one decision into thousands of
    queries. Omitted, it is computed here for the single-rule case.
    """
    # Before the cheap exits: a bad venue is a caller bug on the money path
    # and must surface on the first tick, not on the first tick that happens
    # to carry a named rule.
    _check_decision_venue(venue)
    if not rule_name:
        return 1.0
    weight = 1.0
    matched = False

    # Bot-trade record first: same execution path, so the most relevant —
    # but only when we know WHICH execution path, hence the venue guard.
    # `venue` is already known to be live or paper by this point; the guard
    # here separates "stated" from "unstated", nothing else.
    if asset_class and venue is not None:
        try:
            from bot_program.bot_grading import bot_track_record_detail
            record = bot_track_record_detail(rule_name, asset_class,
                                              min_n=MIN_SAMPLES, venue=venue)
            multiplier = record["multiplier"]
            if multiplier != 1.0:
                weight *= float(multiplier)
                matched = True
            elif not record["measured"]:
                # Cold start, and it is worth saying out loud: a rule fresh
                # off promotion has a full paper record and no live one, and
                # this is the line that shows the live entry was weighed
                # without it rather than silently inheriting it.
                logger.debug("[aggregation] %s neutral on %s: %s",
                             rule_name, venue, record["reason"])
        except ValueError:
            # The ledger rejecting a venue is a programming error, not a data
            # gap. Logging it away here is what made `_venue_filter`'s loud
            # failure unreachable from the one call site that spends money —
            # so it goes back out, unswallowed.
            raise
        except Exception as e:
            logger.debug("[aggregation] bot track record failed for %s: %s",
                         rule_name, e)
    elif asset_class:
        logger.debug(
            "[aggregation] no venue given for %s on %s — bot-trade evidence "
            "skipped (pooled paper+live would misweigh either venue)",
            rule_name, asset_class)

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
                       min_signals: int = 1,
                       venue: str | None = None) -> dict:
    """Weigh both sides by evidence and return the net verdict.

    `bullish` / `bearish` are Signal-like objects exposing `score` and
    `rule_name`. Returns a dict with the direction, the net weight, the
    winning side's weighted score and its top rule.

    `min_signals` is a hard floor on how many distinct rules must agree,
    mirroring the config's min_signals_for_entry. Without it a single rule
    that has earned a 2.0 weight can clear a threshold meant to represent
    two independent confirmations — the config would read as "2 signals"
    while the bot traded on one.

    `venue` is the venue the resulting entry would be filled on, forwarded
    to `rule_weight` so live orders are weighed with live fills. The caller
    knows it before the vote (it follows the config's mode); a stage policy
    can still force the winning rule's order onto paper afterwards, and that
    only ever moves a live entry toward paper — the direction in which a
    rule's live evidence is empty and its weight neutral anyway.

    An unrecognised venue raises ValueError here, on the tick it is passed,
    rather than on the first tick that happens to have a signal to weigh: a
    quiet tick returning HOLD would otherwise hide the typo until the day
    the bot had a reason to trade.
    """
    _check_decision_venue(venue)

    # One stats aggregation for the whole decision, shared by every rule —
    # and computed only if some rule actually needs weighing. Most ticks
    # find nothing above entry_score_min on either side, and a decision
    # with no votes to weigh should not pay for six months of history.
    stats_cache: list = []
    weights: dict[str, float] = {}

    def weight_for(rule: str) -> float:
        if rule not in weights:
            if not stats_cache:
                stats_cache.append(_signal_stats())
            weights[rule] = rule_weight(rule, asset_class,
                                        signal_stats=stats_cache[0],
                                        venue=venue)
        return weights[rule]

    # WHICH RULES ARE THE SAME THING. The platform already measures this —
    # Pearson on daily realized R, "rules that LOOK different but TRADE the
    # same factor in practice" — and routed the answer only to an LLM
    # narrator. It never reached the moment the money moves.
    #
    # Read once per call, not per side: it is a cached map, and asking
    # twice would only make the two sides disagree if the cache turned over
    # between them.
    try:
        from bot_program.asset_engine.rule_clusters import (
            cluster_map, independent_sources,
        )
        _cluster_map, _cluster_stale = cluster_map()
    except Exception:  # noqa: BLE001 — an unknown must not veto an entry
        _cluster_map, _cluster_stale = {}, True

        def independent_sources(names, **kw):
            return len({str(n) for n in names if n})

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
        # `len(rules)` counted NAMES. An operator who raises
        # min_signals_for_entry to 2 is buying independent confirmation,
        # and two readings of one dataset satisfied that quorum between
        # them — while the reason string on the trade reported the
        # headcount as though it were evidence count.
        sources = independent_sources(rules, mapping=_cluster_map,
                                      stale=_cluster_stale)
        return total, best_rule, sources, len(rules)

    bull_weight, bull_rule, bull_rules, bull_names = side_weight(bullish)
    bear_weight, bear_rule, bear_rules, bear_names = side_weight(bearish)
    net = bull_weight - bear_weight

    if net >= min_net_weight:
        if bull_rules < min_signals:
            return {"direction": "HOLD", "net_weight": round(net, 4),
                    "score": 0.0, "rule_name": "",
                    "detail": (f"bull evidence {net:+.2f} clears "
                               f"{min_net_weight:.2f} but only {bull_rules} "
                               f"independent source(s) agree, need "
                               f"{min_signals}"
                               + (f" ({bull_names} rules, some reading the "
                                  f"same data)"
                                  if bull_names > bull_rules else ""))}
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
                               f"independent source(s) agree, need "
                               f"{min_signals}"
                               + (f" ({bear_names} rules, some reading the "
                                  f"same data)"
                                  if bear_names > bear_rules else ""))}
        weighted_score = bear_weight / max(len(bearish), 1)
        return {"direction": "SELL", "net_weight": round(-net, 4),
                "score": min(1.0, round(weighted_score, 4)),
                "rule_name": bear_rule,
                "detail": f"bear {bear_weight:.2f} vs bull {bull_weight:.2f}"}
    return {"direction": "HOLD", "net_weight": round(abs(net), 4),
            "score": 0.0, "rule_name": "",
            "detail": f"net evidence {net:+.2f} below {min_net_weight:.2f}"}
