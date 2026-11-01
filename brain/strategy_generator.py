"""Phase 41 — Autonomous strategy generator.

Once a week (Sunday 04:00 UTC), the frontier tier's model (Fable 5.1 on
2026-10-31) reads the system's track record + knowledge graph + pattern
history and PROPOSES new OpportunitySetups by composing existing
registered evaluators in novel ways.

Hard safety rails:
  1. Generated setups must reference ONLY registered evaluator kinds —
     the agent can't invent new evaluators (those need code).
  2. Setups land at `is_active=False` AND `RuleControl.promotion_stage="research"` —
     scanner ignores them until an admin approves. No live sizing possible.
  3. Setup names auto-prefixed `generated_<YYYYMMDD>_<slug>` so they're
     visually segregated from human/seeded setups.
  4. Hard cap: at most 3 proposals per generation cycle (cost + signal/noise).
  5. Each proposal posts a Hypothesis (`rule_avg_r ≥ 0` over 30d) so the
     generator's output is graded long-term — bad generators earn lower
     trust → downstream weight goes down automatically.
  6. Pending proposals older than 14 days auto-expire.

Cost target: ~$0.50/cycle × 1/week = **~$0.07/day amortized**.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# ── Snapshot ──────────────────────────────────────────────────────────────

#: Rows per venue in the generator's top-performing table (2026-10-08).
TOP_RULES_PER_VENUE = 5

#: THE BEARISH SHARE (2026-10-31): at least this share of a cycle's slots
#: is held for a bearish proposal. The book had been long by construction
#: (every starter setup bullish); a cycle that proposes only bullish ideas
#: keeps it so.
BEARISH_SHARE = 1 / 3
#: Weeks of past proposals the snapshot's direction balance counts.
BALANCE_WEEKS = 8
#: Each evaluator's bearish reading — {kind: {param: value}} — for the
#: model to build a bearish proposal from. Checked against the registry's
#: closed choices (tests/test_generator_bearish_quota.py).
BEARISH_BRANCHES = {
    "liquidity_sweep": {"direction": "bearish_sweep"},
    "fakeout_pattern": {"direction": "bull_trap"},
    "cot_report": {"direction": "long_extreme"},
    "market_structure_break": {"direction": "bearish"},
    "anchoring_zone": {"mode": "prior_swing_high"},
    "parabolic_exhaustion": {"direction": "exhaustion_up"},
    "crowd_extreme": {"direction": "euphoric"},
    "price_pattern": {"pattern": "breakout_low"},
    "fair_value_gap": {"direction": "bearish"},
    "order_block": {"direction": "bearish"},
    "session_break": {"direction": "below"},
    "anchored_vwap_break": {"direction": "below"},
    "news_price_divergence": {"sentiment_dir": "bullish_news_bearish_price"},
}


def bearish_min(n: int) -> int:
    """The bearish proposals a cycle of `n` slots must hold: ceil(n x
    BEARISH_SHARE), so 1 of 3."""
    import math
    return int(math.ceil(max(0, int(n)) * BEARISH_SHARE - 1e-9))


def _direction_balance() -> dict:
    """{active_setups, proposals_last_8_weeks, graded_by_side}: how long
    the book leans, for the prompt's bearish share."""
    from django.db.models import Avg, Count

    out = {"active_setups": {"bullish": 0, "bearish": 0},
           "proposals_last_8_weeks": {"bullish": 0, "bearish": 0},
           "graded_by_side": {"long": {"n": 0, "avg_r": None},
                              "short": {"n": 0, "avg_r": None}}}
    try:
        from signals.models_opportunity import OpportunitySetup
        for d, n in (OpportunitySetup.objects.filter(is_active=True)
                     .values_list("direction").annotate(n=Count("id"))):
            if d in out["active_setups"]:
                out["active_setups"][d] = int(n)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .generator_models import GeneratedSetupProposal
        since = timezone.now() - timedelta(weeks=BALANCE_WEEKS)
        for d, n in (GeneratedSetupProposal.objects
                     .filter(created_at__gte=since)
                     .values_list("direction").annotate(n=Count("id"))):
            if d in out["proposals_last_8_weeks"]:
                out["proposals_last_8_weeks"][d] = int(n)
    except Exception:  # noqa: BLE001
        pass
    try:
        from signals.models import Signal
        for d, n, avg in (Signal.objects.filter(is_active=False)
                          .exclude(outcome="")
                          .exclude(realized_r__isnull=True)
                          .values_list("direction")
                          .annotate(n=Count("id"), avg=Avg("realized_r"))
                          .values_list("direction", "n", "avg")):
            side = {"bullish": "long", "bearish": "short"}.get(d)
            if side:
                out["graded_by_side"][side] = {
                    "n": int(n), "avg_r": (round(float(avg), 4)
                                           if avg is not None else None)}
    except Exception:  # noqa: BLE001
        pass
    return out


def _build_generation_snapshot() -> dict:
    """Aggregate inputs for the generator: top-performing setups, evaluator
    catalog, current regime, recent successful patterns."""
    snap = {"as_of": timezone.now().isoformat()}

    # 1. Catalog of registered evaluator kinds — agent must pick from this list.
    #
    # Kind names alone are not a vocabulary. Handed only the names, the model
    # invented plausible params (`{"regime": "low"}` on volatility_regime),
    # every one of which the evaluator ignored — the condition then ran on
    # defaults, which for that example is the exact inversion of what was
    # asked for. Ship the accepted keys and the closed value sets so the model
    # is copying a contract rather than guessing at one, and so the validator's
    # rejections are avoidable rather than arbitrary.
    try:
        from signals.opportunity_scanner import (
            EVALUATOR_REGISTRY, SIZING_KEYS, param_choices, param_keys,
        )
        snap["available_evaluators"] = [
            {"kind": kind,
             "params": sorted(param_keys(kind)),
             "choices": {k: sorted(v) for k, v in param_choices(kind).items()}}
            for kind in sorted(EVALUATOR_REGISTRY.keys())
        ]
        snap["accepted_sizing_keys"] = sorted(SIZING_KEYS)
    except Exception:
        snap["available_evaluators"] = []
        snap["accepted_sizing_keys"] = []

    # 2. The best-performing rules (last 60d) — composition signal. PER
    # VENUE (2026-10-08): the top rows of each of live, demo and paper,
    # each naming its venue, never one pooled average of a simulator and
    # real fills.
    try:
        from bot_program.bot_grading import performance_by_venue
        top = []
        for venue, rows in performance_by_venue(days=60, min_n=3).items():
            rows.sort(key=lambda r: float(r.get("avg_r") or 0), reverse=True)
            top.extend(
                {"rule_name": r["rule_name"], "asset_class": r["asset_class"],
                 "venue": venue,
                 "n": r["n"], "win_rate": round(float(r["win_rate"] or 0), 4),
                 "avg_r": round(float(r["avg_r"] or 0), 4)}
                for r in rows[:TOP_RULES_PER_VENUE])
        snap["top_performing_rules"] = top
    except Exception:
        snap["top_performing_rules"] = []

    # 3. Existing active setups so the agent doesn't trivially duplicate.
    try:
        from signals.models_opportunity import OpportunitySetup
        snap["existing_active_setups"] = list(OpportunitySetup.objects
                                                .filter(is_active=True)
                                                .values("name", "direction",
                                                          "asset_classes",
                                                          "conditions")[:30])
    except Exception:
        snap["existing_active_setups"] = []

    # 4. Current knowledge graph — what regime we're in, what's flagged.
    try:
        from .knowledge_models import KnowledgeNode
        snap["knowledge_graph"] = list(
            KnowledgeNode.objects
            .filter(superseded_by__isnull=True)
            .values("kind", "key", "payload", "confidence")[:50]
        )
    except Exception:
        snap["knowledge_graph"] = []

    # 5. Recent confirmed hypotheses — what's been right lately.
    try:
        from .knowledge_models import Hypothesis
        cutoff = timezone.now() - timedelta(days=30)
        snap["recent_confirmed"] = list(
            Hypothesis.objects
            .filter(outcome=Hypothesis.OUTCOME_CONFIRMED,
                     resolved_at__gte=cutoff)
            .values("source_agent", "claim_text", "confidence")[:15]
        )
    except Exception:
        snap["recent_confirmed"] = []
    # 6. The evidence ledger — per rule, what has been GRADED: signals,
    # paper fills, live fills, and the regret (paper R nothing took live).
    # The generator composes from what has proven, and is told so.
    try:
        from bot_program.evidence import rule_rows
        snap["evidence_ledger"] = [
            {k: r[k] for k in ("rule", "stage", "sig_n", "sig_hit",
                               "sig_avg", "sig_r", "paper_n", "paper_r",
                               "live_n", "live_r", "regret_r")}
            for r in rule_rows()[:25]
        ]
    except Exception:
        snap["evidence_ledger"] = []
    # The ledger's lanes are the promotion ladder's own (bot_program/
    # evidence.py), left as they are: its "live" lane is every non-paper
    # fill, the eToro demo included. Said, so no live number is read as
    # real money alone (2026-10-08).
    snap["evidence_ledger_note"] = (
        "live_n/live_r count every broker fill, eToro demo (virtual "
        "account, not money) included; paper_n/paper_r are the platform "
        "simulator. top_performing_rules names each row's venue apart: "
        "live (real money), demo, paper.")
    # 7. THE BEARISH SHARE (2026-10-31): how long the book leans, and each
    # evaluator's bearish reading to build the short side from.
    snap["direction_balance"] = _direction_balance()
    snap["bearish_branches"] = {k: dict(v) for k, v in BEARISH_BRANCHES.items()}

    return snap


# ── The agent ─────────────────────────────────────────────────────────────

GENERATOR_SCHEMA = """{
  "proposals": [
    {
      "name_slug": "lowercase_underscores_only_30char_max",
      "rationale_md": "2-4 sentences. Cite the data point that inspired this — 'top performing rule X uses evaluator Y at high weight, so we propose...'.",
      "inspiration": "one phrase, e.g. 'top_rule:starter_stock_momentum + regime:trending'",
      "direction": "bullish | bearish",
      "asset_classes": ["stock", "etf", "forex", "crypto", "commodity"],
      "conditions": [
        {"kind": "MUST_BE_FROM_AVAILABLE_EVALUATORS",
         "params": {"ONLY_KEYS_LISTED_FOR_THAT_KIND": "ONLY_LISTED_CHOICES"},
         "weight": 0.5..2.0}
      ],
      "min_match_score": 0.5..0.85,
      "suggested_horizon_days": 1..30,
      "sizing": {"stop_pct": float, "target_rr": float},
      "confidence": 0.0..1.0
    }
  ]
}"""


class StrategyGeneratorAgent(BaseAgent):
    """Generates new OpportunitySetup proposals from learned patterns."""

    agent_name = "strategy_generator"
    # The weekly imagination pass runs on the frontier tier — the most
    # capable model, once a week, for at most three proposals. Every other
    # agent on the platform stays on its tier; this is the one call where
    # imagination is the product. Override per agent on /ai-models/.
    default_tier = "frontier"

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Strategy Generator. Once a week, you "
            "read what the platform has learned and propose 1-3 *new* "
            "OpportunitySetups by composing existing evaluators in novel "
            "ways.\n\n"
            "Hard rules:\n"
            "1. You may ONLY use evaluator `kind` values from the "
            "`available_evaluators` list in the snapshot. Inventing a new "
            "evaluator kind is forbidden — those require code. Each entry "
            "lists the `params` keys that evaluator reads and, for the params "
            "with a closed vocabulary, the `choices` it accepts. A key or a "
            "value outside those lists is not a variation, it is a dead "
            "condition: the evaluator never reads it and silently runs on its "
            "defaults. Proposals carrying one are rejected outright. Use only "
            "`accepted_sizing_keys` in `sizing` for the same reason.\n"
            "2. Do NOT trivially duplicate `existing_active_setups`. Your "
            "value is in NOVEL combinations, not me-toos. Read existing "
            "setups; propose something materially different.\n"
            "3. Each proposal MUST cite a specific data point from the "
            "snapshot in `rationale_md`. 'Trend-following looks good' is "
            "rejected; 'top-performing rule starter_stock_momentum has "
            "avg_r=0.42, propose adding RVOL filter to tighten entries' "
            "is good.\n"
            "4. Propose AT MOST 3 setups. Quality > quantity.\n"
            "5. Stay within the schema. min_match_score should be at most "
            "the sum of weights × 0.85.\n"
            "6. `name_slug` is short (≤30 chars), lowercase, underscores. "
            "The platform will prefix it with `generated_<date>_`.\n"
            "7. `evidence_ledger` is what the platform has GRADED per rule "
            "— signals (n, hit rate, avg R), paper fills and their R, live "
            "fills and their R, and `regret_r`, paper R nothing has taken "
            "live. Build on rules with proven paper R; do not re-propose "
            "what has already failed there; when you cite the ledger, cite "
            "its numbers.\n"
            f"8. At least {bearish_min(3)} of your proposals MUST have "
            "direction `bearish`: a setup that profits when the instrument "
            "falls. The book has been long-only by construction "
            "(`direction_balance` counts it). Build bearish proposals from "
            "`bearish_branches`. If the snapshot holds no honest bearish "
            "idea, do not invent one: propose fewer bullish setups instead. "
            "The platform holds that slot for the short side and drops any "
            "bullish proposal past it.\n\n"
            "Inspirations to look for:\n"
            "- Pair a top-performing rule's evaluators with a regime filter "
            "(hurst_regime / volatility_regime).\n"
            "- Add a behavioral filter (crowd_extreme / news_price_divergence) "
            "to a momentum setup to avoid late entries.\n"
            "- Compose a microstructure pattern (liquidity_sweep / "
            "fair_value_gap) with a relative_volume filter.\n"
            "- Build a contrarian setup if the brain says regime is "
            "blow_off (parabolic_exhaustion + crowd_extreme:euphoric).\n"
            "- A failed breakout at resistance: fakeout_pattern:bull_trap "
            "with liquidity_sweep:bearish_sweep and "
            "anchoring_zone:prior_swing_high.\n"
            "- A crowded long turning: cot_report:long_extreme with "
            "market_structure_break:bearish. long_extreme is the "
            "contrarian read here; a seeded bullish setup reads the same "
            "value the other way, so cite which one you build.\n\n"
            f"Respond ONLY with valid JSON:\n{GENERATOR_SCHEMA}\n\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or _build_generation_snapshot()
        return (
            "Snapshot for strategy generation (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "Propose new setups now."
        )

    def parse_response(self, raw_response: str) -> dict:
        text = (raw_response or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"non-JSON generator output: {e}: {text[:200]}")
        if not isinstance(data, dict):
            raise ValueError("generator returned non-dict")
        return data


# ── Validation ────────────────────────────────────────────────────────────

ALLOWED_DIRECTIONS = {"bullish", "bearish"}
ALLOWED_ASSET_CLASSES = {"stock", "etf", "forex", "crypto", "commodity",
                          "options", "index"}
SLUG_RE = re.compile(r"^[a-z0-9_]{1,30}$")


def validate_conditions(conds) -> tuple[bool, str]:
    """Return (ok, error_reason) for a list of `{kind, params, weight}` dicts.

    Checking the `kind` alone was never enough. An unregistered kind is loud —
    the scanner reports "unknown kind" — but a REGISTERED kind carrying a param
    the evaluator never reads is silent: the condition runs on defaults for the
    life of the setup, and on the two-branch evaluators an unrecognised
    `direction` value does not go quiet, it selects the opposite branch. That
    is the whole bug class the starter pack was just repaired for.

    Every path that writes a setup a model or a human composed passes through
    here: `validate_proposal` on the generated path, `approval_blocker` again at
    arming time, and `dashboard.views_admin_hq.hq_create_opportunity_setup` on
    the operator's own form. That last one is named explicitly because it used
    to be the exception this docstring claimed did not exist — it wrote raw
    `json.loads` output straight into `objects.create(..., is_active=True)`.
    There is no backstop under any of them: `OpportunitySetup` defines no
    `clean()`, and `.objects.create()` never calls `full_clean()`.
    """
    if not isinstance(conds, list) or not conds:
        return False, "conditions must be a non-empty list"

    try:
        from signals.opportunity_scanner import (
            EVALUATOR_REGISTRY, invalid_param_values, param_keys,
            unknown_param_keys,
        )
        registered = set(EVALUATOR_REGISTRY)
    except Exception:
        return False, "evaluator registry unavailable"

    for c in conds:
        if not isinstance(c, dict):
            return False, "condition is not a dict"
        kind = c.get("kind")
        if kind not in registered:
            return False, f"unknown evaluator kind {kind!r}"
        params = c.get("params") or {}
        if not isinstance(params, dict):
            return False, f"params on {kind!r} is not an object"
        unknown = unknown_param_keys(kind, params)
        if unknown:
            return False, (f"{kind!r} params {unknown} are never read by that "
                           f"evaluator (accepted: {sorted(param_keys(kind))})")
        bad_values = invalid_param_values(kind, params)
        if bad_values:
            return False, f"{kind!r} params out of vocabulary: {bad_values}"
        try:
            w = float(c.get("weight", 1.0))
        except (TypeError, ValueError):
            return False, f"bad weight on {kind!r}"
        if not (0.1 <= w <= 5.0):
            return False, f"weight {w} out of [0.1, 5.0] on {kind!r}"

    return True, ""


def validate_proposal(proposal: dict) -> tuple[bool, str]:
    """Return (ok, error_reason). Lightweight schema/sanity check."""
    if not isinstance(proposal, dict):
        return False, "not a dict"

    name_slug = proposal.get("name_slug", "")
    if not isinstance(name_slug, str) or not SLUG_RE.match(name_slug):
        return False, f"bad name_slug {name_slug!r}"

    if proposal.get("direction") not in ALLOWED_DIRECTIONS:
        return False, f"bad direction {proposal.get('direction')!r}"

    asset_classes = proposal.get("asset_classes")
    if not isinstance(asset_classes, list) or not asset_classes:
        return False, "asset_classes must be a non-empty list"
    bad = [a for a in asset_classes if a not in ALLOWED_ASSET_CLASSES]
    if bad:
        return False, f"unknown asset_classes: {bad}"

    ok, reason = validate_conditions(proposal.get("conditions"))
    if not ok:
        return False, reason

    sizing = proposal.get("sizing")
    if sizing is not None:
        if not isinstance(sizing, dict):
            return False, "sizing is not an object"
        try:
            from signals.opportunity_scanner import (
                SIZING_KEYS, unknown_sizing_keys,
            )
        except Exception:
            return False, "evaluator registry unavailable"
        dead = unknown_sizing_keys(sizing)
        if dead:
            return False, (f"sizing keys {dead} are never read; accepted: "
                           f"{sorted(SIZING_KEYS)}")

    try:
        mms = float(proposal.get("min_match_score", 0.6))
    except (TypeError, ValueError):
        return False, "bad min_match_score"
    if not (0.0 < mms < 1.0):
        return False, f"min_match_score {mms} out of (0, 1)"

    try:
        horizon = int(proposal.get("suggested_horizon_days", 5))
    except (TypeError, ValueError):
        return False, "bad horizon"
    if not (1 <= horizon <= 60):
        return False, f"horizon {horizon} out of [1, 60]"

    return True, ""


def _record_rejection(proposal, reason: str, *, model: str = "") -> None:
    """Write the idea the platform refused, and why, as a REJECTED row —
    no setup, no rule, no hypothesis — so the brain page shows it.

    Before this, a proposal the validator refused vanished with one INFO
    line (silenced in production, where the brain logger sat at WARNING).
    The operator had paid for three ideas and could see two. The row
    carries no cost: the run's cost already sits on the rows that were
    persisted. Never raises — a trace must not fail the run.
    """
    try:
        from .generator_models import GeneratedSetupProposal

        def _text(key, cap):
            v = proposal.get(key, "") if isinstance(proposal, dict) else ""
            return (v if isinstance(v, str) else repr(v))[:cap]

        def _list(key):
            v = proposal.get(key) if isinstance(proposal, dict) else None
            return list(v) if isinstance(v, list) else []

        GeneratedSetupProposal.objects.create(
            proposed_name=_text("name_slug", 120) or "(unnamed)",
            rationale_md=_text("rationale_md", 5000),
            inspiration_summary=_text("inspiration", 300),
            direction=_text("direction", 10) or "bullish",
            asset_classes=_list("asset_classes"),
            conditions=_list("conditions"),
            status=GeneratedSetupProposal.STATUS_REJECTED,
            reviewed_by="validator",
            reviewed_at=timezone.now(),
            review_notes=reason[:2000],
            error=reason[:2000],
            model_used=(model or "")[:80],
        )
    except Exception:  # noqa: BLE001 — a trace never fails the run
        logger.warning("[generator] could not record the rejection: %s",
                       reason[:200])


def _final_setup_name(name_slug: str, *, today=None) -> str:
    today = today or timezone.now()
    return f"generated_{today:%Y%m%d}_{name_slug}"


# ── Persistence ───────────────────────────────────────────────────────────

def _persist_proposal(proposal: dict, *, model: str, tokens_in: int,
                      tokens_out: int, cost_usd: float) -> Optional[object]:
    """Validate → create draft OpportunitySetup (is_active=False) +
    RuleControl (research stage) + Hypothesis + GeneratedSetupProposal.

    Returns the GeneratedSetupProposal row, or None on validation failure.
    """
    ok, reason = validate_proposal(proposal)
    if not ok:
        logger.info("[generator] proposal rejected by validator: %s", reason)
        _record_rejection(proposal, reason, model=model)
        return None

    from signals.models_opportunity import OpportunitySetup
    from signals.models_control import RuleControl
    from .generator_models import GeneratedSetupProposal
    from .hypotheses import post_hypothesis

    final_name = _final_setup_name(proposal["name_slug"])

    # If a setup with this exact name already exists (rare — same day same
    # slug), bail out cleanly.
    if OpportunitySetup.objects.filter(name=final_name).exists():
        logger.info("[generator] setup name collision: %s — skipping", final_name)
        _record_rejection(proposal, f"setup name collision: {final_name}",
                          model=model)
        return None

    setup = OpportunitySetup.objects.create(
        name=final_name,
        description=proposal.get("rationale_md", "")[:1500],
        direction=proposal["direction"],
        asset_classes=list(proposal["asset_classes"]),
        conditions=list(proposal["conditions"]),
        min_match_score=float(proposal["min_match_score"]),
        suggested_horizon_days=int(proposal["suggested_horizon_days"]),
        sizing=dict(proposal.get("sizing") or {}),
        is_active=False,  # ← admin must approve before scanner picks it up
    )

    rule = RuleControl.objects.create(
        rule_name=final_name,
        status="active",
        weight_multiplier=1.0,
        allocator_weight=1.0,
        promotion_stage="research",
        notes=(f"Auto-generated by Sauron Vision Strategy Generator. "
                f"{proposal.get('inspiration', '')}")[:500],
        parameters={
            "asset_classes": list(proposal["asset_classes"]),
            "min_match_score": float(proposal["min_match_score"]),
            "horizon_days": int(proposal["suggested_horizon_days"]),
            "auto_generated": True,
        },
    )

    # Hypothesis: this rule will produce non-negative avg_r over 30 days.
    try:
        try:
            conf = max(0.0, min(1.0, float(proposal.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        hyp = post_hypothesis(
            claim_text=f"generated rule '{final_name}' produces avg_r ≥ 0 over 30d",
            source_agent="strategy_generator",
            claim_payload={"rule_name": final_name,
                            "inspiration": proposal.get("inspiration", "")},
            resolution_criteria={
                "kind": "rule_avg_r", "rule_name": final_name,
                "comparator": ">=", "threshold": 0.0, "window_days": 30,
            },
            confidence=conf,
            horizon_hours=30 * 24,
        )
    except Exception:
        hyp = None

    proposal_row = GeneratedSetupProposal.objects.create(
        proposed_name=final_name,
        rationale_md=proposal.get("rationale_md", "")[:5000],
        inspiration_summary=proposal.get("inspiration", "")[:300],
        direction=proposal["direction"],
        asset_classes=list(proposal["asset_classes"]),
        conditions=list(proposal["conditions"]),
        min_match_score=float(proposal["min_match_score"]),
        suggested_horizon_days=int(proposal["suggested_horizon_days"]),
        sizing=dict(proposal.get("sizing") or {}),
        confidence=float(proposal.get("confidence", 0.5)),
        setup=setup, rule_control=rule, hypothesis=hyp,
        model_used=model, tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=Decimal(str(round(cost_usd, 6))),
    )
    return proposal_row


# ── Approve / Reject / Expire ─────────────────────────────────────────────

def approval_blocker(proposal) -> str:
    """Why `approve_proposal` would refuse to arm this proposal, or "" if it
    would arm it.

    Split out of `approve_proposal` because the refusal reason is the only part
    of it an operator can act on, and a bool cannot carry one. The approve view
    clicks a button and gets back False; without this, the reason it was False
    exists only in the web worker's log.
    """
    if proposal.status != proposal.STATUS_PENDING:
        return f"already {proposal.status} — only a pending proposal can be armed"
    if proposal.setup is None:
        return "the draft setup this proposal pointed at no longer exists"
    # Re-checked at the moment of arming, not only at proposal time. A pending
    # proposal can sit for two weeks, and approval is the step that makes it
    # scan; the reviewer is shown a rationale, not a param audit, so an
    # evaluator whose accepted keys changed underneath the row must not be
    # waved through on the strength of a validation that ran a fortnight ago.
    #
    # This fires TODAY, not at some future tightening: `validate_conditions` was
    # widened from kind-only to kind + unknown keys + out-of-vocabulary values,
    # and every proposal already sitting at PENDING was written under the old
    # rule. The first click on one carrying an invented param key lands here.
    ok, reason = validate_conditions(proposal.setup.conditions)
    if not ok:
        return reason
    return ""


def approve_proposal(proposal, *, reviewed_by: str = "",
                     notes: str = "") -> bool:
    """Flip the linked OpportunitySetup to is_active=True. Returns success.

    Callers that can show a human a message should ask `approval_blocker` for
    the reason on a False return rather than swallowing it.
    """
    blocker = approval_blocker(proposal)
    if blocker:
        logger.warning("[generator] refusing to arm %s: %s",
                       proposal.proposed_name, blocker)
        return False
    proposal.setup.is_active = True
    proposal.setup.save(update_fields=["is_active", "updated_at"])
    proposal.status = proposal.STATUS_APPROVED
    proposal.reviewed_by = reviewed_by[:80]
    proposal.reviewed_at = timezone.now()
    proposal.review_notes = notes[:2000]
    proposal.save(update_fields=[
        "status", "reviewed_by", "reviewed_at", "review_notes",
    ])
    try:
        from bot_program.audit import record_proposal_decision
        record_proposal_decision(
            proposal=proposal, decision="approved",
            reviewed_by=reviewed_by, notes=notes,
        )
    except Exception:
        pass
    return True


def reject_proposal(proposal, *, reviewed_by: str = "",
                     notes: str = "") -> bool:
    """Mark rejected — linked OpportunitySetup stays is_active=False."""
    if proposal.status != proposal.STATUS_PENDING:
        return False
    proposal.status = proposal.STATUS_REJECTED
    proposal.reviewed_by = reviewed_by[:80]
    proposal.reviewed_at = timezone.now()
    proposal.review_notes = notes[:2000]
    proposal.save(update_fields=[
        "status", "reviewed_by", "reviewed_at", "review_notes",
    ])
    try:
        from bot_program.audit import record_proposal_decision
        record_proposal_decision(
            proposal=proposal, decision="rejected",
            reviewed_by=reviewed_by, notes=notes,
        )
    except Exception:
        pass
    return True


def expire_old_proposals(*, days: int = 14) -> int:
    """Auto-expire pending proposals older than `days`."""
    from .generator_models import GeneratedSetupProposal
    cutoff = timezone.now() - timedelta(days=days)
    n = GeneratedSetupProposal.objects.filter(
        status=GeneratedSetupProposal.STATUS_PENDING,
        created_at__lt=cutoff,
    ).update(status=GeneratedSetupProposal.STATUS_EXPIRED,
              reviewed_at=timezone.now())
    return n


# ── Top-level entry ───────────────────────────────────────────────────────

def generate_strategies_now(*, max_proposals: int = 3) -> dict:
    """Run one generation cycle. Always returns a dict; never raises."""
    snapshot = _build_generation_snapshot()
    try:
        agent = StrategyGeneratorAgent()
        system_prompt = agent.get_system_prompt()
        context = agent.build_context(snapshot=snapshot)
        raw, usage = agent.provider.complete(
            system_prompt=system_prompt, user_message=context,
            model=agent.model,
            agent_name=agent.agent_name,
            effort=getattr(agent, "effort", None),
        )
        parsed = agent.parse_response(raw)
    except Exception as e:
        logger.warning("[generator] failed: %s", e)
        return {"ok": False, "error": str(e), "n_persisted": 0}

    proposals = parsed.get("proposals")
    if not isinstance(proposals, list):
        return {"ok": False, "error": "no proposals array",
                "n_persisted": 0}

    persisted_ids = []
    armed_ids = []
    rejected_count = 0
    auto_research = _auto_research_enabled()
    # THE BEARISH SHARE (2026-10-31): the cap slices first, then the quota
    # applies to that slice — bearish_min(max_proposals) slots are held for
    # bearish proposals. The valid bearish ones are persisted first; the
    # bullish ones fill what is left, in the model's order, and each one
    # past it is recorded as rejected with the quota's reason.
    batch = [p for p in proposals[:max_proposals]]
    k = bearish_min(max_proposals)

    def _is_bearish(p):
        return isinstance(p, dict) and p.get("direction") == "bearish"

    valid_bearish = sum(1 for p in batch
                        if _is_bearish(p) and validate_proposal(p)[0])
    bullish_room = max(0, max_proposals - max(k, valid_bearish))
    ordered = ([p for p in batch if _is_bearish(p)]
               + [p for p in batch if not _is_bearish(p)])
    quota_dropped = 0
    bullish_kept = 0
    for p in ordered:
        bearish = _is_bearish(p)
        if not bearish and validate_proposal(p)[0]:
            if bullish_kept >= bullish_room:
                quota_dropped += 1
                _record_rejection(
                    p, (f"bearish quota: {valid_bearish} of {k} bearish "
                        f"proposals this cycle — a slot is held for the "
                        f"short side"), model=agent.model)
                continue
            bullish_kept += 1
        row = _persist_proposal(
            p, model=agent.model,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            cost_usd=float(usage.get("cost_usd", 0)),
        )
        if row:
            persisted_ids.append(row.id)
            # A BEARISH proposal is never armed automatically: an armed
            # research bearish setup can silence a bullish setup that
            # trades on the same instrument in the same scan pass (the
            # scanner's contradiction guard ignores the stage). It waits
            # for the operator's approve.
            if auto_research and not bearish and approve_proposal(
                    row, reviewed_by="auto:research",
                    notes="armed automatically in research stage — the "
                          "scanner grades it, no bot trades it"):
                armed_ids.append(row.id)
        else:
            rejected_count += 1

    # Auto-expire stale pending proposals while we're at it.
    n_expired = expire_old_proposals()

    return {
        "ok": True,
        "n_persisted": len(persisted_ids),
        "n_armed_research": len(armed_ids),
        "n_validation_rejected": rejected_count,
        "n_quota_dropped": quota_dropped,
        "n_expired": n_expired,
        "proposal_ids": persisted_ids,
        "proposal_ids_armed": armed_ids,
    }


def _auto_research_enabled() -> bool:
    """Does the operator let the generator arm its own proposals in
    RESEARCH stage? Armed means the scanner produces graded signals for
    the setup; the stage gate keeps every bot from trading it; the admin
    can still reject. Off by default, like every component."""
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled("generator_auto_research"))
    except Exception:  # noqa: BLE001 — no registry, no arming
        return False
