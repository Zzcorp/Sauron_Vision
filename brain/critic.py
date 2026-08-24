"""Phase 38.3 — Critic / Red-team agent.

Reviews a hypothesis from another agent. Runs Opus 4.7 (the user explicitly
asked for quality on dissent — this is exactly where reasoning depth pays).

Output: structured vote (`co_sign | dissent | refine`) + reasoning. The
vote is persisted via `brain.hypotheses.vote()`; if the critic's
confidence in dissent is high (≥0.7), it ALSO emits a counter-hypothesis
of its own, which is itself graded — so dissent quality is measurable.

Trigger policy (consumed by `brain.tasks.critic_review_due`):
  1. Any hypothesis from a low-trust agent (trust_score < 0.4 OR null).
  2. Any high-confidence hypothesis (claim confidence ≥ 0.75) — sanity check.
  3. Sample 10% of routine hypotheses (random).

Bounded to ~5-10 invocations/day to control Opus cost.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Optional

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


CRITIC_SCHEMA = """{
  "stance": "co_sign|dissent|refine",
  "confidence": 0.0..1.0,
  "reasoning": "2-4 sentences, concrete. Cite the data point that contradicts (or confirms) the claim.",
  "counter_hypothesis": {           // Required iff stance == "dissent" AND confidence >= 0.7
    "claim_text": "string",
    "claim_payload": {},
    "resolution_criteria": {"kind": "regime_holds|rule_avg_r|anomaly_persists", ...},
    "horizon_hours": int,
    "confidence": 0.0..1.0
  }
}"""


class CriticAgent(BaseAgent):
    """Red-team agent that audits another agent's hypothesis."""

    agent_name = "critic"
    default_tier = "deep"  # Opus 4.7 — dissent quality matters most here.

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Critic — a red-team agent whose job "
            "is to audit hypotheses produced by other agents. You DO NOT "
            "default to agreement. Disagreement, when calibrated, is your "
            "highest-value output.\n\n"
            "Three stances:\n"
            "- co_sign: claim is supported by independent evidence in the "
            "  context. Add ONE novel supporting data point you found.\n"
            "- dissent: the claim contradicts a fact in the context, or "
            "  the reasoning has a gap. Cite the specific contradiction.\n"
            "- refine: claim direction is right but the resolution "
            "  criteria, scope, or confidence is mis-set. Suggest a fix.\n\n"
            "Hard rules:\n"
            "1. NEVER produce vacuous agreement (\"good claim\"). If you "
            "co-sign, add a novel supporting data point.\n"
            "2. If you dissent with confidence ≥ 0.7, you MUST emit a "
            "counter_hypothesis with concrete resolution_criteria.\n"
            "3. Be terse. 2-4 sentences max in reasoning.\n\n"
            f"Respond ONLY with valid JSON:\n{CRITIC_SCHEMA}\n\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, **kwargs) -> str:
        hyp = kwargs.get("hypothesis")
        snapshot = kwargs.get("snapshot") or {}
        agent_trust = kwargs.get("source_agent_trust", "n/a")
        return (
            f"Hypothesis under review:\n"
            f"  source_agent: {hyp.source_agent} (trust score: {agent_trust})\n"
            f"  confidence:   {hyp.confidence:.2f}\n"
            f"  claim:        {hyp.claim_text}\n"
            f"  payload:      {json.dumps(hyp.claim_payload, default=str)}\n"
            f"  criteria:     {json.dumps(hyp.resolution_criteria, default=str)}\n"
            f"  deadline:     {hyp.resolution_deadline}\n\n"
            f"Current world snapshot (JSON):\n{json.dumps(snapshot, indent=2, default=str)}\n\n"
            "Audit this hypothesis."
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
            raise ValueError(f"non-JSON critic output: {e}: {text[:200]}")
        if not isinstance(data, dict):
            raise ValueError(f"critic returned non-dict: {type(data).__name__}")
        stance = data.get("stance")
        if stance not in ("co_sign", "dissent", "refine"):
            raise ValueError(f"bad stance: {stance!r}")
        return data


# ── Selection policy ──────────────────────────────────────────────────────

ALLOW_RESOLVERS = {"regime_holds", "rule_avg_r", "anomaly_persists"}


def select_hypotheses_for_review(*, max_n: int = 5,
                                   sample_pct: float = 0.10) -> list:
    """Pick hypotheses worth a critic call right now.

    Caps total selections at `max_n` to bound Opus cost.
    """
    from .knowledge_models import Hypothesis, HypothesisVote
    from .hypotheses import agent_trust_score

    # Candidates: pending, not yet voted on by the critic.
    pending = list(Hypothesis.objects
                    .filter(outcome=Hypothesis.OUTCOME_PENDING)
                    .order_by("-created_at")[:max_n * 5])
    already_critiqued = set(HypothesisVote.objects
                              .filter(agent="critic",
                                      hypothesis__in=pending)
                              .values_list("hypothesis_id", flat=True))
    pending = [h for h in pending if h.id not in already_critiqued]

    # Score each: low source-agent trust + high claim confidence → priority.
    scored = []
    for h in pending:
        trust = agent_trust_score(h.source_agent)
        score = 0.0
        if trust is None or trust < 0.4:
            score += 1.0
        if h.confidence >= 0.75:
            score += 1.0
        # Random sample for the rest.
        if random.random() < sample_pct:
            score += 0.5
        scored.append((score, h))

    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [h for s, h in scored[:max_n] if s > 0]


# ── Top-level entry point ─────────────────────────────────────────────────

def review_hypothesis(hypothesis) -> Optional[dict]:
    """Run the critic on a single hypothesis. Persists a HypothesisVote and
    (on confident dissent) emits a counter-hypothesis. Returns a summary
    dict, or None on irrecoverable error.
    """
    from .hypotheses import agent_trust_score, vote, post_hypothesis
    from .synthesizer import _build_world_snapshot

    snap = _build_world_snapshot(max_obs=40)
    trust = agent_trust_score(hypothesis.source_agent)

    try:
        agent = CriticAgent()
        system_prompt = agent.get_system_prompt()
        context = agent.build_context(hypothesis=hypothesis, snapshot=snap,
                                        source_agent_trust=trust)
        raw, usage = agent.provider.complete(
            system_prompt=system_prompt, user_message=context,
            model=agent.model,
            agent_name=agent.agent_name,
        )
        parsed = agent.parse_response(raw)
    except Exception as e:
        logger.warning("[critic] review failed for hyp %s: %s", hypothesis.id, e)
        return None

    stance = parsed["stance"]
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    reasoning = (parsed.get("reasoning") or "")[:2000]
    vote(hypothesis, agent="critic", stance=stance,
         confidence=confidence, reasoning=reasoning)

    counter_id = None
    if stance == "dissent" and confidence >= 0.7:
        cc = parsed.get("counter_hypothesis") or {}
        if isinstance(cc, dict) and cc.get("claim_text"):
            criteria = cc.get("resolution_criteria") or {}
            if isinstance(criteria, dict) and criteria.get("kind") in ALLOW_RESOLVERS:
                try:
                    counter = post_hypothesis(
                        claim_text=cc["claim_text"],
                        source_agent="critic",
                        claim_payload=cc.get("claim_payload") or {},
                        resolution_criteria=criteria,
                        confidence=float(cc.get("confidence", confidence)),
                        horizon_hours=int(cc.get("horizon_hours", 24)),
                    )
                    counter_id = counter.id
                except Exception:  # pragma: no cover
                    counter_id = None

    return {
        "ok": True,
        "hypothesis_id": hypothesis.id,
        "stance": stance,
        "confidence": confidence,
        "counter_hypothesis_id": counter_id,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "cost_usd": float(usage.get("cost_usd", 0)),
    }


def run_critic_pass(*, max_n: int = 5) -> dict:
    """One pass: pick hypotheses + run critic on each. Bounded by `max_n`."""
    targets = select_hypotheses_for_review(max_n=max_n)
    results = []
    for h in targets:
        out = review_hypothesis(h)
        if out:
            results.append(out)
    return {
        "n_targets": len(targets),
        "n_reviewed": len(results),
        "n_dissents": sum(1 for r in results if r["stance"] == "dissent"),
        "n_co_signs": sum(1 for r in results if r["stance"] == "co_sign"),
        "n_refines": sum(1 for r in results if r["stance"] == "refine"),
        "n_counters_emitted": sum(1 for r in results
                                    if r.get("counter_hypothesis_id")),
    }
