"""Phase 50 — Research conversational agent.

Read-only RAG chat over Sauron's accumulated state. Inspired by Anthropic's
May-2026 Market Researcher template (which assumes data-provider MCP
connectors); ours reads our own DB so the operator can ask:

  - "What's your current read on USD?"
  - "Why did you pause rule starter_stock_momentum?"
  - "What's your view on AAPL into earnings?"
  - "Where did our recent dissents come from?"

Architecture:
  _build_research_snapshot()  → aggregates 6h-7d of brain/graph/hypotheses
  ResearchAgent               → BaseAgent subclass, deep tier (Opus 4.7)
  begin_ask(conv, question)   → persists the question + a PENDING answer
  complete_ask(pending_id)    → fills that pending row in place (worker)
  ask(conversation, question) → both halves, synchronously (fallback path)

Safety:
  - Read-only — agent has NO tools to mutate state. Pure question/answer.
  - Conversation history is the last 8 messages (4 turns) so multi-turn works
    without runaway context cost.
  - Per-question cost target ~$0.10-0.30 (Opus, ~3-6K input + ~1K output).
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from ai_agents.base_agent import BaseAgent
from ai_agents.spend import can_spend

logger = logging.getLogger(__name__)


# ── Snapshot builder ─────────────────────────────────────────────────────

def _build_research_snapshot() -> dict:
    """Aggregate Sauron state for the research agent. Compact — meant for
    a Q&A turn, not a synthesis cycle."""
    snap: dict = {"as_of": timezone.now().isoformat()}

    # Latest 6 brain reports (≈3h history at 30-min cadence).
    try:
        from .models import BrainReport
        reports = list(
            BrainReport.objects.filter(error="")
            .order_by("-created_at")[:6]
            .values("regime_label", "regime_confidence",
                     "portfolio_health_score", "top_concerns",
                     "theme_pressures", "rule_status_overlay",
                     "narrative_md", "created_at")
        )
        for r in reports:
            r["created_at"] = r["created_at"].isoformat()
        snap["recent_brain_reports"] = reports
    except Exception:
        snap["recent_brain_reports"] = []

    # Current knowledge graph.
    try:
        from .knowledge_models import KnowledgeNode
        snap["knowledge_graph"] = list(
            KnowledgeNode.objects.filter(superseded_by__isnull=True)
            .order_by("-created_at")[:30]
            .values("kind", "key", "version", "payload",
                     "confidence", "source_agents", "created_at")
        )
        for n in snap["knowledge_graph"]:
            n["created_at"] = n["created_at"].isoformat()
    except Exception:
        snap["knowledge_graph"] = []

    # Recent resolved hypotheses (track record of past calls).
    try:
        from .knowledge_models import Hypothesis
        cutoff = timezone.now() - timedelta(days=14)
        snap["recent_resolved_hypotheses"] = list(
            Hypothesis.objects.filter(resolved_at__gte=cutoff)
            .exclude(outcome=Hypothesis.OUTCOME_PENDING)
            .order_by("-resolved_at")[:20]
            .values("source_agent", "claim_text", "outcome",
                     "confidence", "resolution_notes")
        )
        snap["pending_hypotheses"] = list(
            Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_PENDING)
            .order_by("-created_at")[:10]
            .values("source_agent", "claim_text", "confidence",
                     "resolution_deadline")
        )
        for h in snap["pending_hypotheses"]:
            h["resolution_deadline"] = (
                h["resolution_deadline"].isoformat()
                if h["resolution_deadline"] else None)
    except Exception:
        snap["recent_resolved_hypotheses"] = []
        snap["pending_hypotheses"] = []

    # Latest strategist briefing.
    try:
        from .briefing_models import StrategistBriefing
        b = StrategistBriefing.objects.first()
        if b is not None:
            snap["latest_briefing"] = {
                "posture": b.posture,
                "outlook_md": b.outlook_md,
                "watchlist": b.watchlist,
                "ideas": b.ideas,
                "created_at": b.created_at.isoformat(),
            }
    except Exception:
        pass

    # Recent earnings reviews.
    try:
        from .earnings_models import EarningsReview
        snap["recent_earnings_reviews"] = list(
            EarningsReview.objects.select_related("instrument")
            .filter(error="")
            .order_by("-created_at")[:5]
            .values("instrument__symbol", "event_title", "event_datetime",
                     "summary_md", "implied_direction",
                     "implied_confidence", "suggested_action")
        )
        for er in snap["recent_earnings_reviews"]:
            er["event_datetime"] = (
                er["event_datetime"].isoformat()
                if er["event_datetime"] else None)
    except Exception:
        snap["recent_earnings_reviews"] = []

    # Phase-58 — recent decision events from the audit chain so the agent
    # can answer "why was X soft-blocked?" / "why did the gate reject Y?"
    # questions. We pull the last 25 of the AI-driven event kinds — trade
    # opens/closes are excluded because they're high-volume + low-relevance
    # for "why did Sauron decide this" questions.
    try:
        from bot_program.audit_models import AuditLogEntry
        decision_kinds = (
            "gate_reject", "brain_soft_block",
            "proposal_approved", "proposal_rejected",
            "rule_demoted", "rule_restored",
            "hypothesis_resolved",
        )
        cutoff_aud = timezone.now() - timedelta(days=14)
        snap["recent_audit_decisions"] = list(
            AuditLogEntry.objects.filter(
                kind__in=decision_kinds, created_at__gte=cutoff_aud,
            ).order_by("-created_at")[:25]
            .values("id", "kind", "data", "created_at")
        )
        for a in snap["recent_audit_decisions"]:
            a["created_at"] = a["created_at"].isoformat()
    except Exception:
        snap["recent_audit_decisions"] = []

    # Open auto-demotions.
    try:
        from .demoter_models import RuleDemotion
        snap["open_demotions"] = list(
            RuleDemotion.objects.filter(restored_at__isnull=True)
            .order_by("-demoted_at")[:10]
            .values("rule_name", "criterion", "metrics", "demoted_at")
        )
        for d in snap["open_demotions"]:
            d["demoted_at"] = d["demoted_at"].isoformat()
    except Exception:
        snap["open_demotions"] = []

    return snap


# ── Conversation history compression ─────────────────────────────────────

MAX_HISTORY_MESSAGES = 8


def _conversation_history_for_prompt(conversation) -> list[dict]:
    """Last N messages of the conversation, oldest-first. Used so the agent
    can answer follow-ups without losing context.

    Pending rows are excluded: an unanswered placeholder has empty content,
    and feeding an empty ASSISTANT turn into the prompt teaches the model
    that saying nothing is an acceptable answer.
    """
    from .research_models import ResearchMessage
    msgs = list(
        conversation.messages
        .exclude(status=ResearchMessage.STATUS_PENDING)
        .order_by("-created_at")[:MAX_HISTORY_MESSAGES]
        .values("role", "content")
    )
    msgs.reverse()
    return msgs


# ── The agent ────────────────────────────────────────────────────────────

class ResearchAgent(BaseAgent):
    """Conversational Q&A over Sauron state."""

    agent_name = "research"
    default_tier = "deep"  # Opus 4.7

    def get_system_prompt(self) -> str:
        return (
            "You are Sauron's Research Agent — the user-facing voice that "
            "answers questions about the platform's view of the markets, "
            "its rules, its trades, and its reasoning. You have READ-ONLY "
            "access to a snapshot of Sauron state injected at every turn.\n\n"
            "What you see in the snapshot:\n"
            "- recent_brain_reports: last 6 outputs of the central "
            "synthesizer (regime · concerns · theme pressures · rule overlay)\n"
            "- knowledge_graph: typed entities (regime / theme_state / "
            "rule_state / anomaly / narrative_thread) with versions\n"
            "- recent_resolved_hypotheses: how Sauron's past calls graded\n"
            "- pending_hypotheses: open bets the system has placed\n"
            "- latest_briefing: today's strategist outlook + posture\n"
            "- recent_earnings_reviews: deep-dive AI analysis of held names\n"
            "- open_demotions: auto-killed rules awaiting admin review\n"
            "- recent_audit_decisions: the immutable audit trail for the "
            "last 14 days of AI-driven decisions (gate_reject, "
            "brain_soft_block, proposal_approved/rejected, rule_demoted/"
            "restored, hypothesis_resolved). Use this when the operator "
            "asks 'why did X happen?' — it's the source of truth.\n\n"
            "Your job:\n"
            "1. Answer the user's question CONCRETELY using the snapshot. "
            "Cite specific data points (e.g. 'regime has been mean-reverting "
            "since Tuesday per BrainReport, confidence 0.72').\n"
            "2. If the snapshot doesn't contain the answer, say so plainly. "
            "Do NOT invent data. 'Sauron hasn't formed a view on that yet' "
            "is a perfectly valid answer.\n"
            "3. If the user asks about a rule's status, look up its "
            "knowledge_graph rule_state node + recent hypothesis market "
            "results. Tell them WHY a rule is paused, not just THAT it is.\n"
            "4. When citing the brain's track record, be honest about its "
            "trust score. A brain that's been wrong recently shouldn't be "
            "presented as authoritative.\n"
            "5. For 'why' questions about specific decisions, walk the "
            "recent_audit_decisions array and cite the entry's `data` field. "
            "Example: 'AAPL was soft-blocked at 14:32 because the brain's "
            "rule_state for momentum_alpha said pause_recommended (audit "
            "id 1234, advisory_source: brain_report regime=risk_off).'\n\n"
            "Tone: terse, direct, second-person ('you', 'your portfolio'). "
            "Markdown for structure when it helps. NO hedge-words "
            "('may', 'could', 'might') unless genuinely uncertain. NO "
            "preambles ('Looking at the data...').\n\n"
            "Hard rule: you cannot take actions yourself. You can "
            "REFERENCE things and PROPOSE things — both via inline markers "
            "the UI will render as clickable links/buttons.\n\n"
            "Markers (use whenever you cite data — they become links):\n"
            "  <<RULE:rule_name>>     a rule by name (e.g. starter_stock_momentum)\n"
            "  <<HYP:id>>             a hypothesis by id\n"
            "  <<REPORT:id>>          a BrainReport by id\n"
            "  <<AUDIT:id>>           an audit log entry by id\n"
            "  <<BRIEFING:id>>        a strategist briefing\n"
            "  <<EARNINGS:id>>        an earnings review\n"
            "  <<KNOWLEDGE:key>>      a knowledge graph node\n\n"
            "Action markers (Phase 60 — render as inline buttons for STAFF "
            "users only). The agent never acts; the human clicks.\n"
            "  <<APPROVE:proposal_id>>   approve a pending generator proposal\n"
            "  <<REJECT:proposal_id>>    reject a pending generator proposal\n"
            "  <<RESTORE:rule_name>>     restore an auto-demoted rule\n\n"
            "Use action markers ONLY when your answer concretely "
            "recommends a specific admin action. Examples:\n"
            "  - 'I'd approve proposal #42 — it cites top-performing rule "
            "data and the evaluator combination is novel. <<APPROVE:42>>'\n"
            "  - 'Reject proposal #51 — same evaluators as starter_momentum, "
            "no novelty. <<REJECT:51>>'\n"
            "  - 'Rule fast_breakout was demoted on noise — consider "
            "restoring. <<RESTORE:fast_breakout>>'\n"
            "Don't litter every response with action buttons. Reserve them "
            "for concrete recommendations.\n\n"
            "Strategy proposal block (Phase 59):\n"
            "When the user is exploring a NEW strategy idea AND you can "
            "concretely express it as a composition of REGISTERED evaluator "
            "kinds, OPTIONALLY emit a fenced ```strategy-draft block at "
            "the very END of your response. The UI will show a 'Save as "
            "draft' button next to it. The draft will land in the Phase-41 "
            "review queue at is_active=False — admin must approve before "
            "it scans live.\n\n"
            "Strategy draft format (valid JSON inside the fence):\n"
            "```strategy-draft\n"
            "{\n"
            '  "name_slug": "lowercase_underscores_30char_max",\n'
            '  "rationale_md": "1-3 sentences citing the data inspiration",\n'
            '  "direction": "bullish | bearish",\n'
            '  "asset_classes": ["stock"|"etf"|"forex"|"crypto"|"commodity"],\n'
            '  "conditions": [\n'
            '    {"kind": "MUST_BE_REGISTERED_EVALUATOR_KIND",\n'
            '     "params": {...}, "weight": 0.5..2.0}\n'
            "  ],\n"
            '  "min_match_score": 0.5..0.85,\n'
            '  "suggested_horizon_days": 1..30,\n'
            '  "sizing": {"stop_pct": float, "target_rr": float},\n'
            '  "confidence": 0.0..1.0\n'
            "}\n"
            "```\n"
            "Only emit a draft when the user explicitly asks for one OR "
            "when you have a HIGH-confidence concrete idea. Don't "
            "volunteer drafts on every turn.\n\n"
            "If the user says 'pause this rule' or 'place this trade', "
            "explain you can't act directly — but you CAN reference items "
            "via markers and propose drafts so admin actions are one "
            "click away.\n\n"
            "Respond as plain markdown text (markers are inline). No "
            "JSON wrapper around the whole response."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or _build_research_snapshot()
        history = kwargs.get("history") or []
        question = kwargs.get("question", "")

        history_md = "\n\n".join(
            f"**{m['role'].upper()}**: {m['content']}" for m in history
        ) if history else "(first message)"

        return (
            "Conversation history (oldest first):\n\n"
            f"{history_md}\n\n"
            "---\n"
            "Current Sauron snapshot (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "---\n"
            f"User's current question:\n\n{question}\n"
        )

    def parse_response(self, raw_response: str) -> dict:
        # Plain markdown — no JSON parsing needed.
        return {"answer_md": (raw_response or "").strip()[:8000]}


# ── Top-level ask() ───────────────────────────────────────────────────────

def get_or_create_active_conversation(user) -> "ResearchConversation":
    from .research_models import ResearchConversation
    conv = ResearchConversation.objects.filter(
        user=user, is_active=True).order_by("-last_message_at").first()
    if conv is not None:
        return conv
    return ResearchConversation.objects.create(user=user, is_active=True)


def archive_active_conversation(user) -> None:
    """Mark the user's active conversation inactive (closes the thread)."""
    from .research_models import ResearchConversation
    ResearchConversation.objects.filter(user=user, is_active=True).update(
        is_active=False)


UNAVAILABLE_TEXT = ("(Sauron's research agent is temporarily unavailable. "
                     "Try again in a few minutes.)")


def begin_ask(conversation, question: str):
    """Persist the question AND an empty pending answer, and return both.

    Split out of ask() so the durable record of the exchange exists before
    anything slow happens. One LLM turn takes tens of seconds; while that
    ran inside the web request, navigating away aborted the fetch and the
    answer existed nowhere the UI could ever find it again. Now the
    exchange is two rows from the first millisecond, and whoever produces
    the answer fills the second one IN PLACE.

    Returns (user_message, pending_assistant_message), or (None, None) for
    an empty question.
    """
    from django.db import transaction
    from .research_models import ResearchMessage

    question = (question or "").strip()
    if not question:
        return None, None

    # One transaction: a question with no placeholder would render as a
    # turn Sauron simply ignored, with nothing for a worker to fill.
    with transaction.atomic():
        user_msg = ResearchMessage.objects.create(
            conversation=conversation,
            role=ResearchMessage.ROLE_USER,
            content=question[:8000],
        )
        pending = ResearchMessage.objects.create(
            conversation=conversation,
            role=ResearchMessage.ROLE_ASSISTANT,
            content="",
            status=ResearchMessage.STATUS_PENDING,
            replies_to=user_msg,
        )
        # Auto-title the conversation from the first message.
        if not conversation.title:
            conversation.title = question[:120]
            conversation.save(update_fields=["title"])
    return user_msg, pending


def _settle(pending, *, content: str, error: str = "", model_used: str = "",
            tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0):
    """Fill a pending row in place and mark it settled.

    Every exit from the answering path goes through here. A placeholder
    left PENDING is worse than an error message: the panel would spin on
    it forever, on every page, in every tab.
    """
    from .research_models import ResearchMessage
    pending.content = content
    pending.error = (error or "")[:1000]
    pending.model_used = model_used
    pending.tokens_in = tokens_in
    pending.tokens_out = tokens_out
    pending.cost_usd = Decimal(str(round(float(cost_usd or 0), 6)))
    pending.status = ResearchMessage.STATUS_DONE
    pending.save(update_fields=[
        "content", "error", "model_used", "tokens_in", "tokens_out",
        "cost_usd", "status"])
    return pending


def fail_pending(pending_message_id: int, reason: str) -> dict:
    """Settle a pending row the worker never finished (hard task failure).

    Celery's link_error lands here. Without it a worker that dies between
    picking the job up and writing the answer leaves the operator watching
    a bubble that will never resolve.
    """
    from .research_models import ResearchMessage
    pending = ResearchMessage.objects.filter(
        pk=pending_message_id, status=ResearchMessage.STATUS_PENDING).first()
    if pending is None:
        return {"ok": False, "error": "not pending"}
    _settle(pending, content=UNAVAILABLE_TEXT, error=str(reason)[:1000])
    return {"ok": False, "error": str(reason),
            "assistant_message_id": pending.pk,
            "user_message_id": pending.replies_to_id}


def complete_ask(pending_message_id: int) -> dict:
    """Produce the answer for one pending row and fill it in place.

    Runs on the Celery worker, or inline in the request when the broker is
    down. Safe to call twice: an already-settled row is left alone, so a
    task retry cannot bill a second LLM call or overwrite a good answer.
    """
    from .research_models import ResearchMessage

    pending = (ResearchMessage.objects
               .select_related("conversation", "replies_to")
               .filter(pk=pending_message_id).first())
    if pending is None:
        return {"ok": False, "error": "message not found"}
    if pending.status != ResearchMessage.STATUS_PENDING:
        return {"ok": True, "already_settled": True,
                "assistant_message_id": pending.pk,
                "user_message_id": pending.replies_to_id}

    conversation = pending.conversation
    question = pending.replies_to.content if pending.replies_to else ""

    # The daily AI ceiling now covers chat. It never did before: the panel
    # called the agent straight from the view, so every question was
    # un-budgeted spend while every scheduled agent was capped. Checked here
    # rather than with @spend_guard because that decorator's skip path
    # returns a dict without running the body — which would leave this row
    # PENDING forever. Here the refusal lands in the bubble instead.
    allowed, reason = can_spend(tier="deep", estimated_usd=0.3)
    if not allowed:
        logger.warning("[research-agent] refused — %s", reason)
        _settle(pending,
                content=f"(Not answered — the daily AI budget is spent: "
                        f"{reason}.)",
                error=f"budget: {reason}")
        return {"ok": False, "error": reason,
                "assistant_message_id": pending.pk,
                "user_message_id": pending.replies_to_id}

    history = _conversation_history_for_prompt(conversation)
    snapshot = _build_research_snapshot()

    try:
        agent = ResearchAgent()
        system_prompt = agent.get_system_prompt()
        context = agent.build_context(
            snapshot=snapshot, history=history, question=question)
        raw, usage = agent.provider.complete(
            system_prompt=system_prompt, user_message=context,
            model=agent.model,
            agent_name=agent.agent_name,
            # The pending row exists BEFORE this call, so its created_at
            # predates the ledger row this call writes — a backfill that
            # cut on timestamps alone would copy the cost twice. The ref
            # ties the live ledger row to its domain row explicitly.
            source_ref=f"ResearchMessage:{pending.pk}",
        )
        parsed = agent.parse_response(raw)
        answer = parsed.get("answer_md", "")
    except Exception as e:
        logger.warning("[research-agent] failed: %s", e)
        _settle(pending, content=UNAVAILABLE_TEXT, error=str(e))
        return {"ok": False, "error": str(e),
                "assistant_message_id": pending.pk,
                "user_message_id": pending.replies_to_id}

    _settle(pending, content=answer, model_used=agent.model,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            cost_usd=usage.get("cost_usd", 0))
    return {
        "ok": True,
        "user_message_id": pending.replies_to_id,
        "assistant_message_id": pending.pk,
        "tokens_in": pending.tokens_in,
        "tokens_out": pending.tokens_out,
        "cost_usd": float(pending.cost_usd),
    }


def ask(conversation, question: str) -> dict:
    """Run one Q&A turn start to finish, synchronously.

    Kept as the whole turn for the plain-form endpoint and for the
    fallback the view takes when the broker is down — a dead worker must
    degrade to the old behaviour, not lose the question.
    """
    user_msg, pending = begin_ask(conversation, question)
    if pending is None:
        return {"ok": False, "error": "empty question"}
    return complete_ask(pending.pk)
