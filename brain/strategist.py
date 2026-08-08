"""Phase 40 — Strategist Briefing Agent.

Daily 06:00 UTC, Opus 4.7. Reads everything Sauron has learned in the last
24-72h and produces a human-readable briefing:

  - **Outlook**     — 1-3 paragraphs of plain English
  - **Posture**     — defensive | balanced | aggressive
  - **Watchlist**   — top 5 things to monitor
  - **Ideas**       — top 3 actionable observations

This is the user-facing "lecture and analysis" the user originally asked
for: rather than make them piece together Brain + Knowledge + Hypotheses
+ Eye dashboards, the Strategist tells them what's going on in one paragraph.

Each Idea is *also* posted as a Hypothesis so the Strategist's
recommendations get graded over time (Phase-6 calibration applies).
Bad strategists earn lower trust and get weighted down.

Cost target: ~$0.30/day (1 run × ~10K input + ~2K output Opus 4.7).
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# ── Snapshot for the strategist ──────────────────────────────────────────

def _build_strategist_snapshot() -> dict:
    """Aggregate the last 72h across all sources into a single dict."""
    from .models import BrainReport
    from .knowledge_models import KnowledgeNode, Hypothesis
    from .hypotheses import agent_trust_score

    now = timezone.now()
    snap: dict = {"as_of": now.isoformat()}

    # Latest 6 BrainReports (≈ 3h of brain history at 30-min cadence).
    recent_reports = list(BrainReport.objects.filter(error="")
                           .order_by("-created_at")[:6]
                           .values("regime_label", "regime_confidence",
                                    "portfolio_health_score", "top_concerns",
                                    "theme_pressures", "rule_status_overlay",
                                    "narrative_md", "created_at"))
    for r in recent_reports:
        r["created_at"] = r["created_at"].isoformat()
    snap["recent_brain_reports"] = recent_reports

    # Current knowledge graph.
    current_nodes = list(KnowledgeNode.objects
                          .filter(superseded_by__isnull=True)
                          .values("kind", "key", "version", "payload",
                                   "confidence", "source_agents",
                                   "created_at"))
    for n in current_nodes:
        n["created_at"] = n["created_at"].isoformat()
    snap["knowledge_graph"] = current_nodes

    # Hypotheses resolved in last 72h (the system's track record).
    cutoff = now - timedelta(hours=72)
    resolved = list(Hypothesis.objects.filter(resolved_at__gte=cutoff)
                     .values("source_agent", "claim_text", "outcome",
                              "confidence", "resolution_notes", "resolved_at")
                     [:30])
    for r in resolved:
        r["resolved_at"] = r["resolved_at"].isoformat() if r["resolved_at"] else None
    snap["recent_resolved_hypotheses"] = resolved

    # Per-agent trust scores so the Strategist can weight the graph properly.
    agents = (Hypothesis.objects.values_list("source_agent", flat=True)
              .distinct())
    trust = {}
    for a in agents:
        if not a:
            continue
        score = agent_trust_score(a)
        if score is not None:
            trust[a] = score
    snap["agent_trust_scores"] = trust

    # Active pending hypotheses (the open bets).
    pending = list(Hypothesis.objects
                    .filter(outcome=Hypothesis.OUTCOME_PENDING)
                    .values("source_agent", "claim_text", "confidence",
                             "resolution_deadline")[:15])
    for h in pending:
        h["resolution_deadline"] = (
            h["resolution_deadline"].isoformat() if h["resolution_deadline"] else None)
    snap["pending_hypotheses"] = pending

    return snap


# ── The agent ─────────────────────────────────────────────────────────────

STRATEGIST_SCHEMA = """{
  "outlook_md": "1-3 short paragraphs in markdown. Plain English, no jargon. Tell, don't lecture. What's happening, what changed, what to expect.",
  "posture": "defensive | balanced | aggressive",
  "posture_rationale": "one sentence",
  "watchlist": [
    {"kind": "string", "ref": "string (symbol/rule/theme)", "what_to_watch": "string"}
  ],
  "ideas": [
    {"summary": "actionable observation in one sentence",
     "horizon_hours": int,
     "confidence": 0.0..1.0,
     "hypothesis_kind": "regime_holds|rule_avg_r|null",
     "hypothesis_payload": {}
    }
  ]
}"""


class StrategistAgent(BaseAgent):
    """Daily synthesis & user-facing briefing."""

    agent_name = "strategist"
    default_tier = "deep"  # Opus 4.7

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Strategist — the platform's daily "
            "user-facing voice. You read everything Sauron has learned in "
            "the last 72h and produce a single tight briefing the operator "
            "can read in 90 seconds.\n\n"
            "Inputs you receive:\n"
            "- Recent BrainReports (regime + concerns + theme pressures)\n"
            "- Current knowledge graph (regime/theme/rule/anomaly nodes)\n"
            "- Recently resolved hypotheses (what we got right or wrong)\n"
            "- Per-agent trust scores (which agents to weight)\n"
            "- Pending hypotheses (open bets the system has placed)\n\n"
            "Your job:\n"
            "1. Outlook — narrate the *current* read in plain English. If "
            "regime shifted, say so. If the brain has been wrong (low trust "
            "on sauron_mind), acknowledge that. If there's tension between "
            "agents (e.g. mutator co-signing, critic dissenting), surface it.\n"
            "2. Posture — concrete recommendation: defensive (reduce size, "
            "skip aggressive entries), balanced (run as configured), or "
            "aggressive (lean into edges). Posture should match outlook.\n"
            "3. Watchlist — top 5 things the operator should monitor today. "
            "Concrete, NOT generic ('vol' is bad; 'VIX divergence vs SPX' is good).\n"
            "4. Ideas — top 3 actionable observations. Where it's "
            "auto-gradeable (regime_holds or rule_avg_r), include hypothesis_kind "
            "and payload so we can grade you over time. Otherwise leave them null.\n\n"
            "Tone: terse, concrete, second-person ('you should…'). NO "
            "hedge-words like 'may' / 'could' / 'might' unless genuinely "
            "uncertain. NO preambles ('In today's briefing...'). Open with "
            "the most important sentence.\n\n"
            f"Respond ONLY with valid JSON in this schema:\n{STRATEGIST_SCHEMA}\n\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or _build_strategist_snapshot()
        return (
            "72h Sauron snapshot (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "Produce the briefing JSON now."
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
            raise ValueError(f"non-JSON strategist output: {e}: {text[:200]}")
        if not isinstance(data, dict):
            raise ValueError("strategist returned non-dict")
        return data


ALLOWED_POSTURES = {"defensive", "balanced", "aggressive"}


def _persist_briefing(parsed: dict, *, model: str,
                       tokens_in: int, tokens_out: int, cost_usd: float,
                       error: str = "") -> "StrategistBriefing":
    from .briefing_models import StrategistBriefing

    posture = parsed.get("posture") or "balanced"
    if posture not in ALLOWED_POSTURES:
        posture = "balanced"

    outlook = parsed.get("outlook_md") or ""
    if not isinstance(outlook, str):
        outlook = ""
    rationale = (parsed.get("posture_rationale") or "")[:500]

    watchlist = parsed.get("watchlist")
    if not isinstance(watchlist, list):
        watchlist = []
    watchlist = [w for w in watchlist if isinstance(w, dict)][:5]

    ideas = parsed.get("ideas")
    if not isinstance(ideas, list):
        ideas = []
    ideas = [i for i in ideas if isinstance(i, dict)][:5]

    return StrategistBriefing.objects.create(
        outlook_md=outlook[:8000],
        posture=posture,
        posture_rationale=rationale,
        watchlist=watchlist,
        ideas=ideas,
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=Decimal(str(round(cost_usd, 6))),
        error=error,
    )


def _emit_idea_hypotheses(briefing, ideas: list) -> int:
    """For each idea with `hypothesis_kind` set, post a Hypothesis so the
    Strategist's calls are graded by the market. Returns count posted."""
    from .hypotheses import post_hypothesis

    n = 0
    for idea in ideas:
        kind = (idea or {}).get("hypothesis_kind")
        if kind not in ("regime_holds", "rule_avg_r"):
            continue
        payload = idea.get("hypothesis_payload") or {}
        if not isinstance(payload, dict) or not payload:
            continue
        criteria = {"kind": kind, **payload}
        try:
            try:
                conf = max(0.0, min(1.0, float(idea.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            try:
                horizon = max(1, int(idea.get("horizon_hours", 24)))
            except (TypeError, ValueError):
                horizon = 24
            post_hypothesis(
                claim_text=str(idea.get("summary") or "strategist idea")[:400],
                source_agent="strategist",
                claim_payload={"idea": idea, "briefing_id": briefing.id},
                resolution_criteria=criteria,
                confidence=conf, horizon_hours=horizon,
            )
            n += 1
        except Exception:  # pragma: no cover
            continue
    return n


# ── Top-level ─────────────────────────────────────────────────────────────

def run_strategist_now() -> dict:
    """Run one strategist briefing. Always returns a dict; never raises."""
    snapshot = _build_strategist_snapshot()
    try:
        agent = StrategistAgent()
        system_prompt = agent.get_system_prompt()
        context = agent.build_context(snapshot=snapshot)
        raw, usage = agent.provider.complete(
            system_prompt=system_prompt, user_message=context,
            model=agent.model,
        )
        parsed = agent.parse_response(raw)
    except Exception as e:
        logger.warning("[strategist] failed: %s", e)
        briefing = _persist_briefing(parsed={}, model="error",
                                       tokens_in=0, tokens_out=0,
                                       cost_usd=0.0, error=str(e)[:1000])
        return {"ok": False, "error": str(e), "briefing_id": briefing.id}

    briefing = _persist_briefing(
        parsed=parsed, model=agent.model,
        tokens_in=usage.get("input_tokens", 0),
        tokens_out=usage.get("output_tokens", 0),
        cost_usd=float(usage.get("cost_usd", 0)),
    )
    n_ideas = _emit_idea_hypotheses(briefing, briefing.ideas)

    # Phase-43 — fan-out push to opted-in users (in-app + telegram/email/discord
    # depending on each user's TraderProfile.notify_channel + prefs).
    delivery = {"n_eligible": 0, "n_delivered": 0, "n_skipped": 0}
    try:
        from bot_program.notifications import notify_strategist_briefing_to_all
        delivery = notify_strategist_briefing_to_all(briefing)
    except Exception as e:  # pragma: no cover
        logger.warning("[strategist] briefing dispatch failed: %s", e)

    return {
        "ok": True, "briefing_id": briefing.id,
        "posture": briefing.posture,
        "n_ideas_posted_as_hypotheses": n_ideas,
        "tokens_in": briefing.tokens_in,
        "tokens_out": briefing.tokens_out,
        "cost_usd": float(briefing.cost_usd),
        "n_delivered": delivery.get("n_delivered", 0),
        "n_eligible": delivery.get("n_eligible", 0),
    }
