"""Phase 41 — Autonomous strategy generator.

Once a week (Sunday 04:00 UTC), Opus 4.7 reads the system's track record +
knowledge graph + pattern history and PROPOSES new OpportunitySetups by
composing existing registered evaluators in novel ways.

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

def _build_generation_snapshot() -> dict:
    """Aggregate inputs for the generator: top-performing setups, evaluator
    catalog, current regime, recent successful patterns."""
    snap = {"as_of": timezone.now().isoformat()}

    # 1. Catalog of registered evaluator kinds — agent must pick from this list.
    try:
        from signals.opportunity_scanner import EVALUATOR_REGISTRY
        snap["available_evaluators"] = sorted(EVALUATOR_REGISTRY.keys())
    except Exception:
        snap["available_evaluators"] = []

    # 2. Top 10 currently best-performing rules (last 60d) — composition signal.
    try:
        from bot_program.bot_grading import bot_performance_summary
        rows = bot_performance_summary(days=60, min_n=3)
        rows.sort(key=lambda r: float(r.get("avg_r") or 0), reverse=True)
        snap["top_performing_rules"] = [
            {"rule_name": r["rule_name"], "asset_class": r["asset_class"],
             "n": r["n"], "win_rate": round(float(r["win_rate"] or 0), 4),
             "avg_r": round(float(r["avg_r"] or 0), 4)}
            for r in rows[:10]
        ]
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
         "params": {...},
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
    default_tier = "deep"  # Opus 4.7

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Strategy Generator. Once a week, you "
            "read what the platform has learned and propose 1-3 *new* "
            "OpportunitySetups by composing existing evaluators in novel "
            "ways.\n\n"
            "Hard rules:\n"
            "1. You may ONLY use evaluator `kind` values from the "
            "`available_evaluators` list in the snapshot. Inventing a new "
            "evaluator kind is forbidden — those require code.\n"
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
            "The platform will prefix it with `generated_<date>_`.\n\n"
            "Inspirations to look for:\n"
            "- Pair a top-performing rule's evaluators with a regime filter "
            "(hurst_regime / volatility_regime).\n"
            "- Add a behavioral filter (crowd_extreme / news_price_divergence) "
            "to a momentum setup to avoid late entries.\n"
            "- Compose a microstructure pattern (liquidity_sweep / "
            "fair_value_gap) with a relative_volume filter.\n"
            "- Build a contrarian setup if the brain says regime is "
            "blow_off (parabolic_exhaustion + crowd_extreme:euphoric).\n\n"
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

    conds = proposal.get("conditions")
    if not isinstance(conds, list) or not conds:
        return False, "conditions must be a non-empty list"

    try:
        from signals.opportunity_scanner import EVALUATOR_REGISTRY
        registered = set(EVALUATOR_REGISTRY)
    except Exception:
        return False, "evaluator registry unavailable"

    for c in conds:
        if not isinstance(c, dict):
            return False, "condition is not a dict"
        kind = c.get("kind")
        if kind not in registered:
            return False, f"unknown evaluator kind {kind!r}"
        try:
            w = float(c.get("weight", 1.0))
        except (TypeError, ValueError):
            return False, f"bad weight on {kind!r}"
        if not (0.1 <= w <= 5.0):
            return False, f"weight {w} out of [0.1, 5.0] on {kind!r}"

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

def approve_proposal(proposal, *, reviewed_by: str = "",
                     notes: str = "") -> bool:
    """Flip the linked OpportunitySetup to is_active=True. Returns success."""
    if proposal.status != proposal.STATUS_PENDING:
        return False
    if proposal.setup is None:
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
    rejected_count = 0
    for p in proposals[:max_proposals]:
        row = _persist_proposal(
            p, model=agent.model,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            cost_usd=float(usage.get("cost_usd", 0)),
        )
        if row:
            persisted_ids.append(row.id)
        else:
            rejected_count += 1

    # Auto-expire stale pending proposals while we're at it.
    n_expired = expire_old_proposals()

    return {
        "ok": True,
        "n_persisted": len(persisted_ids),
        "n_validation_rejected": rejected_count,
        "n_expired": n_expired,
        "proposal_ids": persisted_ids,
    }
