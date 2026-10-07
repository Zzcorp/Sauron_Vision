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

  THE FLOOR (expectancy-led): a live rule with ≥20 graded signals all time
  goes straight to PAPER when its expectancy is at or under 0R, or when a
  hit rate under 35% carries an expectancy under +0.10R (a thin edge under
  a low hit rate). A low hit rate alone is a breakout's shape, not a loss.

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

# THE FLOOR (2026-10-05): a MEASURED LOSER at a live stage goes to paper
# whatever its baseline. The degradation rule above compares the recent
# window with the stage's baseline, and returns None when the baseline is
# None or <= 0 — so a rule promoted with no usable baseline (the bulk
# promotion of 2026-10-01) could never be demoted by the nightly sweep, and
# a measured loser kept the live venue until a human acted. The floor reads
# the rule's ALL-TIME graded record: LOSER_MIN_N graded signals and either
# an expectancy at or under zero, or a THIN EDGE under a LOW HIT RATE — a
# hit rate under LOSER_HIT_MAX with an expectancy under LOSER_THIN_EDGE_R.
# The operator's own promotion stands for MANUAL_DWELL_DAYS (the sweep never
# overturns a fresh hand decision); `manage.py bar_losers` reads and
# applies the same floor by hand.
#
# EXPECTANCY-LED (2026-10-06): the first floor barred on a low hit rate
# alone, and so flagged bollinger_squeeze_breakout (43 graded, hit 33%,
# expectancy +0.26R, PROVEN by the proving ground on three classes) — the
# one rule with a measured edge, kept live only by a hand promotion's
# dwell. A low hit rate with a large payoff is a breakout's normal shape;
# the hit rate only bars a rule whose edge is too thin to pay for it.
LOSER_MIN_N = 20
LOSER_HIT_MAX = 0.35
LOSER_THIN_EDGE_R = 0.10
MANUAL_DWELL_DAYS = 7


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


def loser_numbers(hit, exp) -> tuple:
    """("34%", "+0.09R") — the hit rate and the expectancy at the floor's
    own precision, never rounded up onto a floor the raw value is under
    (the review of 2026-10-06: 17 hits of 49 at +0.0951R read "hit 35%,
    expectancy +0.10R — ... expectancy under +0.10R, hit under 35%", a
    sentence that contradicts itself on a real-money demotion)."""
    h = float(hit) if hit is not None else 0.0
    shown_h = round(h, 2)
    if h < LOSER_HIT_MAX <= shown_h:
        shown_h = round(LOSER_HIT_MAX - 0.01, 2)
    shown_e = round(float(exp), 2)
    if float(exp) < LOSER_THIN_EDGE_R <= shown_e:
        shown_e = round(LOSER_THIN_EDGE_R - 0.01, 2)
    return f"{shown_h:.0%}", f"{shown_e:+.2f}R"


def measured_loser(rule_name: str, stats: dict | None = None) -> str:
    """The sentence that makes `rule_name` a MEASURED LOSER on its all-time
    graded record — LOSER_MIN_N signals and an expectancy at or under zero,
    or a hit rate under LOSER_HIT_MAX with an expectancy under
    LOSER_THIN_EDGE_R (a thin edge under a low hit rate) — or "" (healthy,
    or unmeasured). The sentence names the arm that fired. A low hit rate
    alone is not a loser: a breakout that wins a third of the time at a
    large payoff has an edge. Words only; nothing here moves a stage.

    `stats` (2026-10-07): the all-time _stats_since(rule_name) a caller
    already read (proven_record reads it once for the proof and the floor);
    None reads it here, as before."""
    s = stats if stats is not None else _stats_since(rule_name)
    n = int(s.get("n") or 0)
    if n < LOSER_MIN_N:
        return ""
    hit = s.get("hit_rate")
    exp = s.get("expectancy")
    if exp is None:
        return ""
    exp = float(exp)
    low_hit = hit is not None and float(hit) < LOSER_HIT_MAX
    hit_w, exp_w = loser_numbers(hit, exp)
    head = f"{n} graded signals all time: hit {hit_w}, expectancy {exp_w}"
    if exp <= 0:
        return f"{head} — expectancy at or under zero"
    if low_hit and exp < LOSER_THIN_EDGE_R:
        return (f"{head} — a thin edge under a low hit rate (expectancy "
                f"under {LOSER_THIN_EDGE_R:+.2f}R, hit under "
                f"{LOSER_HIT_MAX:.0%})")
    return ""


def proven_record(rule_name: str, *, cache: dict | None = None) -> dict:
    """{"proven", "n", "hit_rate", "expectancy", "loser"}: whether the
    rule's own ALL-TIME graded record (rule level, both sides, every class)
    proves it — SIZE BY PROOF (2026-10-07, backtester/proving/proof.py)
    lets a live entry the proving ground has not proven keep full size on
    it.

    This is the floor's own measure read from above, not a parallel
    statistic: LOSER_MIN_N graded signals, an expectancy at or above
    LOSER_THIN_EDGE_R (an edge the floor calls thin under a low hit rate is
    not proof) and not a measured loser. Read once per tick through
    `cache` (key ("proof_record", rule)). A failed read is not proof:
    proven False, n 0, and a warning."""
    key = ("proof_record", rule_name)
    if isinstance(cache, dict) and isinstance(cache.get(key), dict):
        return dict(cache[key])
    try:
        out = _record_of(rule_name, _stats_since(rule_name))
    except Exception as e:  # noqa: BLE001 — unread is unproven
        logger.warning("[promotion] %s: graded record unread (%s) — not "
                       "proof", rule_name, e)
        return dict(_UNREAD_RECORD)
    if isinstance(cache, dict):
        cache[key] = dict(out)
    return out


#: proven_record of a graded record that could not be read: no proof.
_UNREAD_RECORD = {"proven": False, "n": 0, "hit_rate": None,
                  "expectancy": None, "loser": ""}
#: _stats_since of a rule with no graded signal.
_NO_STATS = {"n": 0, "expectancy": None, "hit_rate": None}


def _record_of(rule_name: str, s: dict) -> dict:
    """proven_record's verdict on the ALL-TIME stats `s` (_stats_since's
    shape) already read: one spelling for the per-rule read and the page's
    batch (provenance_notes, 2026-10-07), so the two cannot disagree."""
    n = int(s.get("n") or 0)
    exp = s.get("expectancy")
    exp = float(exp) if exp is not None else None
    loser = measured_loser(rule_name, stats=s)
    proven = (n >= LOSER_MIN_N and exp is not None
              and exp >= LOSER_THIN_EDGE_R and not loser)
    return {"proven": bool(proven), "n": n, "hit_rate": s.get("hit_rate"),
            "expectancy": exp, "loser": loser}


def _stats_by_rule(rule_names) -> dict:
    """{rule: _stats_since(rule)} for every rule of `rule_names` in ONE
    grouped query (2026-10-07, the review): the same all-time window (no
    `since`, no `days_window` — proven_record's), the same exclusions, the
    same hit and the same rounding; a rule with no graded signal reads
    _NO_STATS. Raises on a failed read, as _stats_since does."""
    from django.db.models import Avg, Count, Q
    from signals.models import Signal
    names = sorted(set(rule_names or ()))
    out = {name: dict(_NO_STATS) for name in names}
    if not names:
        return out
    # order_by on the grouped column, never Signal's own -created_at
    rows = (Signal.objects.filter(rule_name__in=names, is_active=False)
            .exclude(outcome="").exclude(realized_r__isnull=True)
            .values("rule_name").order_by("rule_name")
            .annotate(n=Count("id"),
                      hits=Count("id", filter=Q(outcome="hit_target")),
                      avg=Avg("realized_r")))
    for r in rows:
        n = int(r["n"] or 0)
        if n <= 0:
            continue
        out[r["rule_name"]] = {
            "n": n,
            "expectancy": (float(r["avg"]) if r["avg"] is not None
                           else None),
            "hit_rate": round(int(r["hits"] or 0) / n, 4),
        }
    return out


def promotion_provenance(rule_name: str, *, ctrl=None,
                         cache: dict | None = None) -> dict:
    """{"stage", "label", "note", "by_hand", "unproven", "words"}: how the
    rule came to its live stage, and whether it was proven (2026-10-07).

    The order of 2026-10-01 put 36 rules at live_full by hand, most with 0
    graded signals, and every display then read a plain "live_full" — the
    same word a rule that climbed the ladder on its fills earns. The label
    says the difference wherever the stage is shown:

      "by hand, unproven"               promoted by hand without proof,
                                        and not proven since;
      "by hand, proven since"           promoted by hand without proof,
                                        proven since;
      "no promotion recorded, unproven" a live stage no event explains,
                                        and no proof;
      ""                                an automatic promotion (Aragorn's
                                        included), or a hand promotion
                                        proven at the time.

    The promotion read is the newest PromotionEvent that put money behind
    the rule (manual_promote or auto_promote, to live_small or live_full):
    a later demotion does not launder it. Proof today is the operator's own
    two kinds: the rule's graded record (proven_record) or the proving
    ground's newest PROVEN verdict on any class and side
    (proof.proven_cases). A stage other than live_small/live_full is its
    own label. Never raises: on a failed read the label is the stage.
    Cached per tick under ("proof_provenance", rule)."""
    key = ("proof_provenance", rule_name)
    if isinstance(cache, dict) and isinstance(cache.get(key), dict):
        return dict(cache[key])
    stage = ""
    try:
        if ctrl is None:
            ctrl = _control(rule_name)
        stage = str(getattr(ctrl, "promotion_stage", "") or "")
        out = _plain_provenance(stage)
        if stage in _LIVE_STAGES:
            from backtester.proving import proof
            ev = (_money_promotions().filter(rule_name=rule_name)
                  .order_by("-created_at").first())
            rec = proven_record(rule_name, cache=cache)
            cases = proof.proven_cases(rule_name, cache=cache)
            out = _provenance_of(stage, ev, rec, cases)
    except Exception as e:  # noqa: BLE001 — a label never breaks a page
        logger.warning("[promotion] %s: provenance unread (%s)",
                       rule_name, e)
        return _plain_provenance(stage)
    if isinstance(cache, dict):
        cache[key] = dict(out)
    return out


#: The stages that put money behind a rule; the provenance reads only them.
_LIVE_STAGES = ("live_small", "live_full")


def _money_promotions():
    """The PromotionEvents that put money behind a rule: manual_promote or
    auto_promote, to live_small or live_full. A demotion is not one, so it
    never launders a hand promotion."""
    from signals.models import PromotionEvent
    return PromotionEvent.objects.filter(
        reason__in=("manual_promote", "auto_promote"),
        to_stage__in=_LIVE_STAGES)


def _plain_provenance(stage: str) -> dict:
    return {"stage": stage, "label": stage, "note": "", "by_hand": False,
            "unproven": False, "words": ""}


def _provenance_of(stage: str, ev, rec: dict, cases: list) -> dict:
    """promotion_provenance's words from what it read: the `stage`, the
    newest money-putting PromotionEvent `ev` (or None), the graded record
    `rec` (proven_record's shape) and the proving ground's proven `cases`.
    A stage below the live ones is its own label. One spelling for the
    per-rule read and the page's batch (provenance_notes, 2026-10-07), so
    the two can never say different things."""
    out = _plain_provenance(stage)
    if stage not in _LIVE_STAGES:
        return out
    by_hand = ev is not None and ev.reason == "manual_promote"
    # _transition's 90-DAY snapshot at the promotion; the expectancy is
    # nullable (no graded signal in the window), and None is no proof.
    proven_then = (
        ev is not None
        and int(ev.n_at_transition or 0) >= LOSER_MIN_N
        and ev.expectancy_at_transition is not None
        and float(ev.expectancy_at_transition) >= LOSER_THIN_EDGE_R)
    proven_now = bool(rec.get("proven")) or bool(cases)
    note = ""
    if by_hand and not proven_then and not proven_now:
        note = "by hand, unproven"
    elif by_hand and not proven_then and proven_now:
        note = "by hand, proven since"
    elif ev is None and not proven_now:
        note = "no promotion recorded, unproven"
    words = ""
    if by_hand:
        words = (f"promoted to {ev.to_stage} by hand on "
                 f"{ev.created_at:%Y-%m-%d} with "
                 f"{ev.n_at_transition} graded signals (proof needs "
                 f"{LOSER_MIN_N} at {LOSER_THIN_EDGE_R:+.2f}R)")
        if not proven_now:
            words += "; not proven since"
        else:
            if rec.get("proven"):
                _h, _e = loser_numbers(rec.get("hit_rate"),
                                       rec["expectancy"])
                words += (f"; proven since: {rec['n']} graded "
                          f"signals all time, expectancy {_e}")
            if cases:
                words += (f"; the proving ground proves it on "
                          f"{', '.join(cases)}")
    out.update(note=note, by_hand=by_hand,
               unproven=note in ("by hand, unproven",
                                 "no promotion recorded, unproven"),
               label=f"{stage} ({note})" if note else stage,
               words=words)
    return out


def provenance_notes(rule_names, *, controls=None, stats=None) -> dict:
    """{rule: note} for a page (2026-10-07): the promotion_provenance note
    of every rule. `controls` is {rule: RuleControl} when the page already
    holds them: a rule absent from it has no control row and no note. A
    rule below the live stages costs no query. Never raises; {} on
    failure.

    BATCHED (2026-10-07, the review): a fixed number of queries whatever
    the rule count, where promotion_provenance per rule cost three to five
    per live rule (/strategies/ read 151 queries for 36 live rules, half
    of them graded, against 7 without them). The controls
    when `controls` is None; then, only when a rule is live, one
    PromotionEvent read (the newest per rule taken in Python), one graded
    read (_stats_by_rule — none when the caller hands its own ALL-TIME
    {rule: stats} map in _stats_since's shape as `stats`) and one
    ProvingVerdict read (proof.proven_cases_for). The words are
    promotion_provenance's own (_provenance_of), and so are its failures:
    an unread graded record is no proof, unread verdicts prove nothing,
    and a rule whose provenance cannot be read has no note."""
    try:
        names = list(rule_names or ())
        out = {}
        given = controls is not None
        if not given:
            from signals.models import RuleControl
            controls = {c.rule_name: c for c in
                        RuleControl.objects.filter(rule_name__in=set(names))}
        stages, live = {}, []
        for name in names:
            ctrl = controls.get(name)
            if ctrl is None:
                # a page's controls lack it: no control row and no note; a
                # read of its own has none either, and says so ("")
                if not given:
                    out[name] = ""
                continue
            stage = str(getattr(ctrl, "promotion_stage", "") or "")
            if stage not in _LIVE_STAGES:
                out[name] = ""
                continue
            stages[name] = stage
            live.append(name)
        if not live:
            return out
        live_names = sorted(set(live))

        try:
            events = {}
            for ev in (_money_promotions().filter(rule_name__in=live_names)
                       .order_by("rule_name", "-created_at")):
                events.setdefault(ev.rule_name, ev)
        except Exception as e:  # noqa: BLE001 — a label never breaks a page
            logger.warning("[promotion] provenance unread for %d live "
                           "rule(s) (%s)", len(live_names), e)
            out.update({name: "" for name in live})
            return out
        try:
            graded = (stats if stats is not None
                      else _stats_by_rule(live_names))
        except Exception as e:  # noqa: BLE001 — unread is unproven
            logger.warning("[promotion] graded record unread for %d live "
                           "rule(s) (%s) — not proof", len(live_names), e)
            graded = None
        from backtester.proving import proof
        cases = proof.proven_cases_for(live_names)

        for name in live:
            try:
                if graded is None:
                    rec = dict(_UNREAD_RECORD)
                else:
                    try:
                        rec = _record_of(name, graded.get(name) or _NO_STATS)
                    except Exception as e:  # noqa: BLE001 — not proof
                        logger.warning("[promotion] %s: graded record "
                                       "unread (%s) — not proof", name, e)
                        rec = dict(_UNREAD_RECORD)
                out[name] = _provenance_of(stages[name], events.get(name),
                                           rec, cases.get(name) or [])["note"]
            except Exception as e:  # noqa: BLE001 — a label never breaks it
                logger.warning("[promotion] %s: provenance unread (%s)",
                               name, e)
                out[name] = ""
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[promotion] provenance notes unread (%s)", e)
        return {}


def hand_promoted_recently(rule_name: str, now=None) -> bool:
    """True while the operator's own promotion of `rule_name` is younger
    than MANUAL_DWELL_DAYS: their last word stands against the floor."""
    from signals.models import PromotionEvent
    now = now or timezone.now()
    return PromotionEvent.objects.filter(
        rule_name=rule_name, reason="manual_promote",
        created_at__gte=now - timedelta(days=MANUAL_DWELL_DAYS)).exists()


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

    if stage in ("live_small", "live_full"):
        # THE FLOOR (2026-10-05): a measured loser leaves real money for
        # paper at once — not one rung a night — whatever its baseline,
        # unless the operator promoted it by hand within the dwell.
        why = measured_loser(rule_name)
        if why and not hand_promoted_recently(rule_name):
            logger.info("[promotion] %s: measured loser at %s — to paper "
                        "(%s)", rule_name, stage, why)
            return "paper"

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
def _transition(rule_name: str, target_stage: str, *, user, reason: str,
                notes: str = "") -> "PromotionEvent":
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
        notes=notes,
        triggered_by=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
    )
    logger.info("[promotion] %s: %s → %s (reason=%s%s)",
                rule_name, from_stage, target_stage, reason,
                f", {notes}" if notes else "")
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
                user=None, reason: str = "manual_demote",
                notes: str = "") -> "PromotionEvent":
    ctrl = _control(rule_name)
    if ctrl is None:
        raise PipelineError(f"No RuleControl for '{rule_name}'")
    if target_stage is None:
        target_stage = _prev_stage(ctrl.promotion_stage)
        if target_stage is None:
            raise PipelineError(f"Rule '{rule_name}' is already at the bottom stage.")
    if STAGE_ORDER.index(target_stage) >= STAGE_ORDER.index(ctrl.promotion_stage):
        raise PipelineError("demote_rule called with a non-backward target_stage.")
    return _transition(rule_name, target_stage, user=user, reason=reason,
                       notes=notes)


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
                # the floor's sentence rides the event (2026-10-05); the
                # degradation rule's event keeps its empty note
                why = (measured_loser(ctrl.rule_name)
                       if target == "paper" and ctrl.promotion_stage
                       in ("live_small", "live_full") else "")
                _transition(ctrl.rule_name, target, user=None,
                            reason="auto_demote",
                            notes=f"measured loser: {why}" if why else "")
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
                # The reason is one of PromotionEvent.REASON_CHOICES (a
                # varchar(24) on Postgres): "auto_promote (<why>)" was
                # refused there and rolled every automatic promotion back,
                # and it skipped the baseline snapshot _transition takes on
                # "auto_promote". The evidence gate's sentence is the note.
                _transition(ctrl.rule_name, target, user=None,
                            reason="auto_promote", notes=why or "")
                promoted.append(ctrl.rule_name)
        except Exception as e:
            logger.warning("[promotion] auto-evaluation failed for %s: %s",
                           ctrl.rule_name, e)

    return {"promoted": promoted, "demoted": demoted, "blocked": blocked,
            "n_promoted": len(promoted), "n_demoted": len(demoted),
            "n_blocked": len(blocked)}
