"""Phase-8 promotion pipeline — strict gates a rule must pass before reaching
full live capital.

Stages (cumulative, low → high risk to capital):
  RESEARCH    no live trade — purely informational
  PAPER       paper-only execution
  LIVE_SMALL  live execution at 25% size
  LIVE_FULL   live execution at full size

Promotion criteria (must ALL be met to promote):

  RESEARCH → PAPER:
    - ≥30 closed signals
    - hit_rate ≥ 0.40
    - expectancy ≥ 0R

  PAPER → LIVE_SMALL:
    - ≥20 closed signals since entering PAPER
    - paper expectancy ≥ 0.7 × research expectancy (no severe regression)
    - ≥30 days in PAPER

  LIVE_SMALL → LIVE_FULL:
    - ≥10 closed signals since entering LIVE_SMALL
    - live_small expectancy ≥ 0.7 × paper expectancy
    - ≥7 days in LIVE_SMALL

Auto-demotion (degradation against the *current stage's baseline*):

  LIVE_FULL  → LIVE_SMALL  if recent expectancy < 0.5 × baseline AND ≥10 closed in window
  LIVE_SMALL → PAPER       if recent expectancy < 0.5 × baseline AND ≥10 closed in window
  PAPER      → RESEARCH    if recent expectancy < 0R AND ≥10 closed in last 30d

Sizing factors:
  RESEARCH    → 0.0  (no trade)
  PAPER       → 0.0  (paper only — `rule_size_multiplier` returns 0)
  LIVE_SMALL  → 0.25
  LIVE_FULL   → 1.0

The Phase-5 admin lane (status: paused/reduced) and Phase-7 allocator lane
remain orthogonal: effective sizing is admin × allocator × promotion. The
promotion factor short-circuits to 0 for PAPER/RESEARCH, ensuring no live
capital touches an under-tested rule.

Public API
----------

    is_eligible_for_promotion(rule_name) -> str | None
        Returns the next stage if criteria are met, else None.

    is_due_for_demotion(rule_name) -> str | None
        Returns the demoted stage if degraded, else None.

    promote_rule(rule_name, target_stage, *, user, reason)
    demote_rule(rule_name, target_stage, *, user, reason)
        Transitions and creates a PromotionEvent.

    auto_evaluate_all_rules() -> dict
        Bulk pass: promote where eligible, demote where degraded.
        Idempotent — re-running on a stable system creates zero events.

    promotion_size_factor(rule_name) -> float
        Read-side helper consumed by `rule_actuator.rule_size_multiplier`.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Stage ordering & sizing factors ────────────────────────────────────────

STAGE_ORDER = ["research", "paper", "live_small", "live_full"]

SIZE_FACTORS: dict[str, float] = {
    "research": 0.0,
    "paper": 0.0,
    "live_small": 0.25,
    "live_full": 1.0,
}


# ── Promotion criteria (tunables at top) ────────────────────────────────────

# RESEARCH → PAPER
PROMO_RESEARCH_TO_PAPER_MIN_N = 30
PROMO_RESEARCH_TO_PAPER_MIN_HIT_RATE = 0.40
PROMO_RESEARCH_TO_PAPER_MIN_EXPECTANCY = 0.0

# PAPER → LIVE_SMALL
PROMO_PAPER_TO_LIVE_SMALL_MIN_N = 20
PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS = 30
PROMO_PAPER_TO_LIVE_SMALL_RETENTION = 0.70  # 70% of research expectancy

# LIVE_SMALL → LIVE_FULL
PROMO_LIVE_SMALL_TO_FULL_MIN_N = 10
PROMO_LIVE_SMALL_TO_FULL_MIN_DAYS = 7
PROMO_LIVE_SMALL_TO_FULL_RETENTION = 0.70

# Auto-demotion
DEMOTE_RECENT_WINDOW_DAYS = 14
DEMOTE_DEGRADATION_RATIO = 0.50  # if recent < 50% of baseline → demote
DEMOTE_MIN_N = 10
DEMOTE_PAPER_WINDOW_DAYS = 30


# ── Helpers ────────────────────────────────────────────────────────────────

def _control(rule_name: str):
    from signals.models import RuleControl
    return RuleControl.objects.filter(rule_name=rule_name).first()


def _stats_since(rule_name: str, since=None, days_window: Optional[int] = None) -> dict:
    """Closed-signal stats for `rule_name` since the given datetime (or by window)."""
    from signals.models import Signal
    from django.db.models import Avg, Count
    qs = Signal.objects.filter(
        rule_name=rule_name, is_active=False,
    ).exclude(outcome="").exclude(realized_r__isnull=True)
    if since is not None:
        qs = qs.filter(expired_at__gte=since)
    elif days_window is not None:
        qs = qs.filter(expired_at__gte=timezone.now() - timedelta(days=days_window))
    n = qs.count()
    if n == 0:
        return {"n": 0, "expectancy": None, "hit_rate": None}
    hits = qs.filter(outcome="hit_target").count()
    expectancy = qs.aggregate(avg=Avg("realized_r"))["avg"]
    return {
        "n": n,
        "expectancy": float(expectancy) if expectancy is not None else None,
        "hit_rate": round(hits / n, 4) if n > 0 else 0,
    }


def _venue_stats(rule_name: str, venue: str, since) -> dict:
    """What the rule actually did ON THAT VENUE, from the TRADE ledger.

    `_stats_since` reads `Signal` and nothing else — no venue, no
    AssetBotTrade, no `paper` flag — and both the paper and the live branch
    called it. The header advertises "paper expectancy >= 0.7x research
    expectancy" and "live_small >= 0.7x paper": three names for ONE
    measurement over three date windows of the same table. An operator
    reading "promoted: paper expectancy retained 0.9x of research"
    reasonably concludes execution was validated on a venue. Nothing had
    been executed anywhere.

    The signal table records what the platform PREDICTED. The trade ledger
    records what a broker FILLED, with slippage, partial fills and the
    spread in it. A stage whose whole purpose is "prove it on a real venue
    before real money" has to read the second one.
    """
    from bot_program.bot_grading import bot_performance_summary
    rows = bot_performance_summary(rule_name=rule_name, since=since,
                                   venue=venue, min_n=1) or []
    n = sum(int(r.get("n") or 0) for r in rows)
    if n <= 0:
        return {"n": 0, "expectancy": None}
    # Trade-weighted across asset classes: a rule that took 40 forex trades
    # and 2 stock trades is mostly a forex rule, and averaging the two rows
    # evenly would let the small one swing the verdict.
    weighted = sum(float(r.get("expectancy") or 0.0) * int(r.get("n") or 0)
                   for r in rows)
    return {"n": n, "expectancy": weighted / n}


def _next_stage(stage: str) -> Optional[str]:
    try:
        i = STAGE_ORDER.index(stage)
    except ValueError:
        return None
    return STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None


def _prev_stage(stage: str) -> Optional[str]:
    try:
        i = STAGE_ORDER.index(stage)
    except ValueError:
        return None
    return STAGE_ORDER[i - 1] if i - 1 >= 0 else None


# ── Read-side: sizing factor ───────────────────────────────────────────────

def promotion_size_factor(rule_name: str) -> float:
    """Sizing factor based on promotion stage. Default 1.0 (LIVE_FULL)."""
    if not rule_name:
        return 1.0
    ctrl = _control(rule_name)
    if ctrl is None:
        # No control row → treat as LIVE_FULL for backwards compat with legacy rules.
        return 1.0
    return SIZE_FACTORS.get(ctrl.promotion_stage, 1.0)


# ── Eligibility checks ─────────────────────────────────────────────────────

def is_eligible_for_promotion(rule_name: str) -> Optional[str]:
    """Return next stage if criteria are met, else None."""
    ctrl = _control(rule_name)
    if ctrl is None:
        return None

    stage = ctrl.promotion_stage
    target = _next_stage(stage)
    if target is None:
        return None  # already at top

    entered = ctrl.stage_entered_at or ctrl.created_at
    days_in_stage = (timezone.now() - entered).days

    if stage == "research":
        s = _stats_since(rule_name)  # all-time
        if (s["n"] >= PROMO_RESEARCH_TO_PAPER_MIN_N
                and (s["hit_rate"] or 0) >= PROMO_RESEARCH_TO_PAPER_MIN_HIT_RATE
                and (s["expectancy"] or -99) >= PROMO_RESEARCH_TO_PAPER_MIN_EXPECTANCY):
            return target

    elif stage == "paper":
        if days_in_stage < PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS:
            return None
        # THE VENUE LEG, asked FIRST. This is the promotion that puts real
        # money behind a rule, and until now nothing in it had ever opened
        # the trade ledger.
        from bot_program.bot_grading import VENUE_PAPER
        fills = _venue_stats(rule_name, VENUE_PAPER, entered)
        if fills["n"] < PROMO_PAPER_TO_LIVE_SMALL_MIN_N:
            logger.info("[promotion] %s stays in paper: %d paper FILLS "
                        "since entering the stage (need %d) — signal-side "
                        "expectancy is not execution evidence",
                        rule_name, fills["n"],
                        PROMO_PAPER_TO_LIVE_SMALL_MIN_N)
            return None
        if fills["expectancy"] is None or fills["expectancy"] < 0:
            logger.info("[promotion] %s stays in paper: paper fills came to "
                        "%s expectancy", rule_name, fills["expectancy"])
            return None

        s = _stats_since(rule_name, since=entered)
        if s["n"] < PROMO_PAPER_TO_LIVE_SMALL_MIN_N:
            return None
        baseline = ctrl.stage_baseline_expectancy
        if baseline is None or baseline <= 0:
            # Without a meaningful baseline, require positive expectancy to advance.
            if (s["expectancy"] or -99) >= 0:
                return target
            return None
        if (s["expectancy"] or -99) >= baseline * PROMO_PAPER_TO_LIVE_SMALL_RETENTION:
            return target

    elif stage == "live_small":
        if days_in_stage < PROMO_LIVE_SMALL_TO_FULL_MIN_DAYS:
            return None
        # Same rule one rung up: full size is earned on LIVE fills, not on
        # the signal table read over a third date window.
        from bot_program.bot_grading import VENUE_LIVE
        fills = _venue_stats(rule_name, VENUE_LIVE, entered)
        if fills["n"] < PROMO_LIVE_SMALL_TO_FULL_MIN_N:
            logger.info("[promotion] %s stays at live_small: %d live FILLS "
                        "since entering the stage (need %d)",
                        rule_name, fills["n"],
                        PROMO_LIVE_SMALL_TO_FULL_MIN_N)
            return None
        if fills["expectancy"] is None or fills["expectancy"] < 0:
            return None

        s = _stats_since(rule_name, since=entered)
        if s["n"] < PROMO_LIVE_SMALL_TO_FULL_MIN_N:
            return None
        baseline = ctrl.stage_baseline_expectancy
        if baseline is None or baseline <= 0:
            if (s["expectancy"] or -99) >= 0:
                return target
            return None
        if (s["expectancy"] or -99) >= baseline * PROMO_LIVE_SMALL_TO_FULL_RETENTION:
            return target

    return None


def is_due_for_demotion(rule_name: str) -> Optional[str]:
    """Return demoted stage if degradation criteria are met, else None."""
    ctrl = _control(rule_name)
    if ctrl is None:
        return None

    stage = ctrl.promotion_stage
    if stage == "research":
        return None  # already at bottom

    target = _prev_stage(stage)
    if target is None:
        return None

    if stage == "paper":
        # Demote PAPER → RESEARCH if expectancy goes negative across last 30d.
        s = _stats_since(rule_name, days_window=DEMOTE_PAPER_WINDOW_DAYS)
        # `or 99` conflated 0.0 with None: a rule sitting at exactly zero
        # expectancy read as "no data" and could never be demoted, which is
        # the one reading that keeps a dead rule on live capital.
        _exp = s["expectancy"]
        if s["n"] >= DEMOTE_MIN_N and _exp is not None and _exp < 0:
            return target
        return None

    # live_small or live_full — degradation against baseline.
    s = _stats_since(rule_name, days_window=DEMOTE_RECENT_WINDOW_DAYS)
    if s["n"] < DEMOTE_MIN_N:
        return None
    baseline = ctrl.stage_baseline_expectancy
    if baseline is None or baseline <= 0:
        return None
    _exp = s["expectancy"]
    if _exp is not None and _exp < baseline * DEMOTE_DEGRADATION_RATIO:
        return target
    return None


# ── Transitions ─────────────────────────────────────────────────────────────

class PipelineError(Exception):
    pass


@transaction.atomic
def _transition(rule_name: str, target_stage: str, *, user, reason: str) -> "PromotionEvent":
    from signals.models import RuleControl, PromotionEvent
    if target_stage not in STAGE_ORDER:
        raise PipelineError(f"Unknown stage: {target_stage}")

    ctrl, _ = RuleControl.objects.select_for_update().get_or_create(
        rule_name=rule_name,
        defaults={"status": RuleControl.STATUS_ACTIVE,
                  "promotion_stage": "research",
                  "stage_entered_at": timezone.now()},
    )

    from_stage = ctrl.promotion_stage

    # Snapshot expectancy as the new stage's baseline (used to detect future
    # degradation). For demotions we still record but don't use it as a forward baseline.
    s = _stats_since(rule_name, days_window=90)
    expectancy = s["expectancy"]

    ctrl.promotion_stage = target_stage
    ctrl.stage_entered_at = timezone.now()
    if reason in ("auto_promote", "manual_promote"):
        # Set baseline at the moment of promotion so future demotions check against this.
        ctrl.stage_baseline_expectancy = expectancy
    ctrl.save(update_fields=[
        "promotion_stage", "stage_entered_at", "stage_baseline_expectancy", "updated_at",
    ])

    event = PromotionEvent.objects.create(
        rule_name=rule_name,
        from_stage=from_stage,
        to_stage=target_stage,
        reason=reason,
        expectancy_at_transition=expectancy,
        n_at_transition=s["n"],
        triggered_by=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
    )
    logger.info("[promotion] %s: %s → %s (reason=%s)",
                rule_name, from_stage, target_stage, reason)
    return event


def promote_rule(rule_name: str, target_stage: Optional[str] = None, *,
                 user=None, reason: str = "manual_promote") -> "PromotionEvent":
    ctrl = _control(rule_name)
    if ctrl is None:
        raise PipelineError(f"No RuleControl for '{rule_name}'")
    if target_stage is None:
        target_stage = _next_stage(ctrl.promotion_stage)
        if target_stage is None:
            raise PipelineError(f"Rule '{rule_name}' is already at the top stage.")
    # Sanity: must be a forward step (no backwards moves through this entry point).
    if STAGE_ORDER.index(target_stage) <= STAGE_ORDER.index(ctrl.promotion_stage):
        raise PipelineError("promote_rule called with a non-forward target_stage.")
    return _transition(rule_name, target_stage, user=user, reason=reason)


def demote_rule(rule_name: str, target_stage: Optional[str] = None, *,
                user=None, reason: str = "manual_demote") -> "PromotionEvent":
    ctrl = _control(rule_name)
    if ctrl is None:
        raise PipelineError(f"No RuleControl for '{rule_name}'")
    if target_stage is None:
        target_stage = _prev_stage(ctrl.promotion_stage)
        if target_stage is None:
            raise PipelineError(f"Rule '{rule_name}' is already at the bottom stage.")
    if STAGE_ORDER.index(target_stage) >= STAGE_ORDER.index(ctrl.promotion_stage):
        raise PipelineError("demote_rule called with a non-backward target_stage.")
    return _transition(rule_name, target_stage, user=user, reason=reason)


# ── Bulk auto-evaluation ───────────────────────────────────────────────────

def auto_evaluate_all_rules() -> dict:
    """Walk every RuleControl, propose promote/demote, apply automatically.

    Idempotent — re-running on a stable system produces zero transitions.
    """
    from signals.models import RuleControl

    promoted: list[str] = []
    demoted: list[str] = []
    blocked: list[dict] = []
    for ctrl in RuleControl.objects.all():
        # Skip rules that are admin-paused; admin lane wins.
        if ctrl.status == "paused":
            continue
        try:
            target = is_due_for_demotion(ctrl.rule_name)
            if target is not None:
                _transition(ctrl.rule_name, target, user=None, reason="auto_demote")
                demoted.append(ctrl.rule_name)
                continue
            target = is_eligible_for_promotion(ctrl.rule_name)
            if target is not None:
                # A good recent live/paper record is a small, recent sample.
                # Before risking real money, require out-of-sample evidence
                # from the backtester that already drives the same decide().
                from signals.promotion_evidence import gate_promotion
                allowed, why = gate_promotion(ctrl.rule_name, target,
                                              caller="auto")
                if not allowed:
                    logger.info("[promotion] %s held at %s — %s",
                                ctrl.rule_name, ctrl.promotion_stage, why)
                    blocked.append({"rule_name": ctrl.rule_name,
                                     "target": target, "reason": why})
                    continue
                _transition(ctrl.rule_name, target, user=None,
                            reason=f"auto_promote ({why})")
                promoted.append(ctrl.rule_name)
        except Exception as e:
            logger.warning("[promotion] auto-evaluation failed for %s: %s",
                           ctrl.rule_name, e)

    return {"promoted": promoted, "demoted": demoted, "blocked": blocked,
            "n_promoted": len(promoted), "n_demoted": len(demoted),
            "n_blocked": len(blocked)}
