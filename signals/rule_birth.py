"""BORN AT RESEARCH (2026-10-31): a new rule is watched and graded, never
traded, until the promotion ladder moves it.

A rule with no RuleControl row reads PAPER in stage_policy, with
may_trade True, and decide() lets paper rules vote. A new rule shipped
without a row would therefore net its weight against the live book on its
first scan — and a migration may not create the row
(tests/test_dead_names.py). So the names listed here read RESEARCH with no
row, and their first stored signal writes the row at research
(signals/tasks.py), where the nightly ladder sweep and Aragorn's research
step can walk it.

Who reads this module:
  signals/rule_actuator.stage_policy   no row: research, not paper
  signals/tasks._create_signals_and_notify
                                       the first stored signal writes the
                                       row (ensure_research_row)
  signals/rule_actuator, signals/meta_allocator,
  signals/management/commands/rule_scope
                                       every other row creator spreads
                                       birth_defaults into its defaults, so
                                       a born name is never created at
                                       live_full (the model default) or paper
  bot_program/asset_engine/base.decide the candidate query leaves out
                                       voteless(live=...) before its slice
  bot_program/engine/strategy          the legacy crypto blend, the same
  signals/announce                     a born name still at research is
                                       stored, banner and bell; no Telegram
  brain/close_advice.fresh_signals     a born name still at research is not
                                       advice against a position
  brain/correlation_audit              a born name still at research takes
                                       no slot in the realized-return
                                       audit's window (rule_clusters'
                                       quorum keeps today's pairs)
  signals/opportunity_density          a born name still at research is no
                                       opportunity for a share plan
  bot_program/manual_trade             nor backing for an instrument-view
                                       ticket
  bot_program/backtest_asset           the config backtest replays only
                                       what decide() lets vote
  signals/meta_allocator               no allocation (it would move every
                                       trading rule's 1/N share and the
                                       sample tier)

A fork of a born name (`death_cross_evolved_v2`) is born with it: the
evolution layer already creates forks at research, and the exclusions
here read the fork's own row.
"""
from __future__ import annotations

import logging

from core.fork_names import base_family

logger = logging.getLogger(__name__)

#: The bearish pack (2026-11): three short mirrors of the long-only rules
#: and eight bearish-by-definition rules (signals/rules/technical_rules.py,
#: signals/rules/bearish_rules.py).
BORN_AT_RESEARCH = frozenset({
    "rsi_bear_divergence",
    "macd_bearish_crossover",
    "death_cross",
    "bull_trap_swing_high",
    "po3_london_sweep_short",
    "range_breakdown_short",
    "trend_continuation_short",
    "risk_off_exhaustion_short",
    "vix_inversion_index_short",
    "crowded_long_reversal_short",
    "positioning_crowd_reversal_short",
})

#: The stages at which a born name may vote on a LIVE config. A paper-stage
#: born rule votes on paper configs only: on a live config its vote would
#: count toward a live-stage rule's real order (aggregation nets the sides
#: and counts independent sources across stages), and the stage gate after
#: decide() reads only the winner's name.
LIVE_STAGES = ("live_small", "live_full")

BIRTH_NOTE = ("Born at research by the bearish pack (2026-11): watched and "
              "graded, never traded until the ladder promotes it.")

#: Fork depth walked back to the root name; a fork of a fork of a fork is
#: already more than evolution makes.
_MAX_FORK_DEPTH = 8


def root_name(rule_name: str) -> str:
    """The name with every `_evolved_vN` peeled (core.fork_names peels one
    level a call)."""
    name = str(rule_name or "")
    for _ in range(_MAX_FORK_DEPTH):
        parent = base_family(name)
        if parent == name:
            break
        name = parent
    return name


def born_at_research(rule_name: str) -> bool:
    """True for a listed name and for any fork of one."""
    name = str(rule_name or "")
    if not name:
        return False
    return name in BORN_AT_RESEARCH or root_name(name) in BORN_AT_RESEARCH


def birth_defaults(rule_name: str, now=None) -> dict:
    """The RuleControl defaults a row creator spreads in: research, from
    now, for a born name; {} for any other name, so nothing changes for
    the existing rules."""
    if not born_at_research(rule_name):
        return {}
    from django.utils import timezone
    return {"promotion_stage": "research",
            "stage_entered_at": now or timezone.now()}


def ensure_research_row(rule_name: str):
    """The rule's RuleControl row, created at research when it has none.
    Never touches an existing row. For a name that is not born here it
    only reads (None when there is no row)."""
    from signals.models_control import RuleControl
    if not born_at_research(rule_name):
        return RuleControl.objects.filter(rule_name=rule_name).first()
    ctrl, created = RuleControl.objects.get_or_create(
        rule_name=rule_name,
        defaults={"status": RuleControl.STATUS_ACTIVE,
                  "weight_multiplier": 1.0, "allocator_weight": 1.0,
                  "notes": BIRTH_NOTE, **birth_defaults(rule_name)})
    if created:
        logger.info("[birth] %s: RuleControl row written at research", rule_name)
    return ctrl


def _born_rows() -> dict:
    """{rule_name: promotion_stage} of every row of a born name or a fork
    of one."""
    from django.db.models import Q

    from signals.models_control import RuleControl
    q = Q(rule_name__in=sorted(BORN_AT_RESEARCH))
    for name in sorted(BORN_AT_RESEARCH):
        q |= Q(rule_name__startswith=f"{name}_evolved_v")
    return {name: str(stage or "")
            for name, stage in RuleControl.objects.filter(q)
            .values_list("rule_name", "promotion_stage")
            if born_at_research(name)}


def voteless(*, live: bool) -> set:
    """The born names (and forks) that may not vote nor take a slot in
    decide()'s window: every born name with no row (research); every row
    at research; and, for a LIVE config (`live` True), every row whose
    stage is not a live stage. Fail closed: a read that raises returns
    every listed name."""
    try:
        rows = _born_rows()
    except Exception as e:  # noqa: BLE001
        logger.warning("[birth] born rows unread (%s): every born name is "
                       "kept out of the vote", e)
        return set(BORN_AT_RESEARCH)
    out = {name for name in BORN_AT_RESEARCH if name not in rows}
    for name, stage in rows.items():
        if stage == "research" or (live and stage not in LIVE_STAGES):
            out.add(name)
    return out


def still_at_research() -> set:
    """The born names (and forks) still watched, not traded: no row, or a
    row at research."""
    return voteless(live=False)


def is_still_at_research(rule_name: str) -> bool:
    """One name: born here, and its row is missing or at research."""
    if not born_at_research(rule_name):
        return False
    try:
        from signals.models_control import RuleControl
        stage = (RuleControl.objects.filter(rule_name=rule_name)
                 .values_list("promotion_stage", flat=True).first())
    except Exception:  # noqa: BLE001 — unread is watched, not traded
        return True
    return stage is None or stage == "research"
