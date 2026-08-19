"""Celery tasks for Phase 37 — brain synthesizer + calibration resolver."""
from __future__ import annotations

import logging
from celery import shared_task

from ai_agents.spend import guard as spend_guard

logger = logging.getLogger(__name__)


@shared_task(name="brain.tasks.run_sauron_mind")
@spend_guard(tier="balanced", estimated_usd=0.15)
def run_sauron_mind() -> dict:
    """Beat task — every 30min. Runs one synthesis cycle."""
    from .synthesizer import synthesize_now
    return synthesize_now()


@shared_task(name="brain.tasks.resolve_brain_predictions")
def resolve_brain_predictions() -> dict:
    """Beat task — every hour. Resolves Sauron Mind predictions whose
    deadline has passed by checking ground truth in the database."""
    from .calibration import resolve_due_brain_predictions
    return resolve_due_brain_predictions()


@shared_task(name="brain.tasks.run_critic_pass")
@spend_guard(tier="deep", estimated_usd=0.4)
def run_critic_pass(*, max_n: int = 5) -> dict:
    """Beat task — every 30 min. Audits up to `max_n` pending hypotheses
    via the Opus 4.7 critic agent. Bounded cost ($0.50-1.50/day target)."""
    from .critic import run_critic_pass as run
    return run(max_n=max_n)


@shared_task(name="brain.tasks.run_consolidation")
def run_consolidation() -> dict:
    """Beat task — nightly 03:00 UTC. Promotes settled facts into the
    knowledge graph, prunes stale observations, resolves due hypotheses."""
    from .consolidation import consolidate_now
    return consolidate_now()


@shared_task(name="brain.tasks.run_strategist")
@spend_guard(tier="deep", estimated_usd=0.3)
def run_strategist() -> dict:
    """Beat task — daily 06:00 UTC. Produces a user-facing briefing using
    the full Sauron stack (brain + knowledge graph + hypothesis market)."""
    from .strategist import run_strategist_now
    return run_strategist_now()


@shared_task(name="brain.tasks.run_strategy_generator")
@spend_guard(tier="deep", estimated_usd=0.3)
def run_strategy_generator(*, max_proposals: int = 3) -> dict:
    """Beat task — weekly Sun 04:00 UTC. Proposes 1-3 new OpportunitySetups
    by composing existing evaluators in novel ways. Land at is_active=False
    pending admin approval."""
    from .strategy_generator import generate_strategies_now
    return generate_strategies_now(max_proposals=max_proposals)


@shared_task(name="brain.tasks.run_auto_demoter")
def run_auto_demoter() -> dict:
    """Beat task — daily 04:30 UTC. Walks active auto-generated rules and
    demotes those meeting kill criteria (hypothesis refuted / sustained
    negative / consecutive losses)."""
    from .demoter import scan_generated_rules_now
    return scan_generated_rules_now()


@shared_task(name="brain.tasks.run_earnings_reviewer")
@spend_guard(tier="balanced", estimated_usd=0.2)
def run_earnings_reviewer() -> dict:
    """Beat task — every 4h. Walks recent earnings events for held symbols
    and dispatches the EarningsReviewerAgent (Opus 4.7) to produce a deep
    AI review per (instrument, event)."""
    from .earnings_reviewer import scan_due_earnings_now
    return scan_due_earnings_now()


@shared_task(name="brain.tasks.run_anomaly_scanner")
def run_anomaly_scanner() -> dict:
    """Beat task — every 30 min, paired with brain synthesis. Pure-Python
    detectors emit `anomaly_detected` BrainObservations; the brain consumes
    them in its next snapshot and consolidation promotes recurring ones."""
    from .anomaly_scanner import scan_anomalies_now
    return scan_anomalies_now()


# ── Ask Sauron — the chat's async lane ───────────────────────────────────
#
# Not a beat task: dispatched by the operator asking a question. It exists
# so the answer outlives the request that asked for it. The panel used to
# call the agent synchronously inside the view, so changing page aborted
# the fetch and the finished answer was never shown to anyone.

@shared_task(name="brain.tasks.answer_research_question")
def answer_research_question(*, message_id: int) -> dict:
    """Produce one chat answer off the request thread.

    Deliberately NOT wrapped in @spend_guard: that decorator's refusal path
    returns a dict without running the body, which would leave the pending
    bubble spinning forever with no explanation. The same ceiling is
    enforced inside complete_ask(), where the refusal is written into the
    bubble the operator is actually watching.
    """
    from .research_agent import complete_ask
    return complete_ask(message_id)


def _answer_payload(message_id: int, *, ok: bool, fallback: str) -> dict:
    """The socket payload for one settled answer, read back from the DB.

    Read from the row rather than trusted from the task's return value:
    the row is what every page will render, so the banner must quote the
    same text or the two disagree.
    """
    from .research_models import ResearchMessage
    from .research_renderer import extract_action_markers, render_markers

    msg = (ResearchMessage.objects.select_related("replies_to")
           .filter(pk=message_id).first())
    question, preview = "", fallback
    if msg is not None:
        if msg.replies_to is not None:
            question = msg.replies_to.content
        cleaned, _actions = extract_action_markers(msg.content or "")
        text = " ".join(render_markers(cleaned).split())
        if text:
            preview = text[:180] + ("…" if len(text) > 180 else "")
        ok = ok and not msg.error
    return {"message_id": message_id, "question": question,
            "preview": preview, "ok": bool(ok)}


@shared_task(name="brain.tasks.announce_research_answer")
def announce_research_answer(result, user_id, message_id) -> dict:
    """Celery `link=` — the answer landed; say so wherever the operator is.

    This is the whole point of the async lane: the banner is raised by the
    SERVER on the user's own /ws/eye/ socket, so it reaches the page they
    are on now rather than the page they asked from. No Notification row —
    the conversation is already the durable record, and a second copy in
    the bell would double every question.
    """
    from django.contrib.auth.models import User
    from dashboard.consumers import push_eye_event

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return {"status": "no_user"}
    data = _answer_payload(message_id, ok=True, fallback="Answer ready.")
    push_eye_event(user, "sauron_answer", data)
    return {"status": "announced", "message_id": message_id}


@shared_task(name="brain.tasks.announce_research_failed")
def announce_research_failed(request, exc, traceback, user_id,
                             message_id) -> dict:
    """Celery `link_error=` — the worker died before it answered.

    Signature contract: an errback whose header takes more than one
    argument is invoked INLINE as errback(request, exc, traceback), with
    those three args merged BEFORE the partials from .s(...). Getting it
    wrong raises TypeError inside Celery's own failure handling and no
    announcement ever fires — see dashboard.tasks.announce_run_failed.

    Settling the row here is the important half: an unsettled placeholder
    would spin on every page forever.
    """
    from django.contrib.auth.models import User
    from dashboard.consumers import push_eye_event
    from .research_agent import fail_pending

    detail = str(exc)[:140] if exc else "the worker died"
    fail_pending(message_id, detail)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return {"status": "no_user"}
    data = _answer_payload(message_id, ok=False,
                           fallback=f"Sauron could not answer — {detail}")
    push_eye_event(user, "sauron_answer", data)
    return {"status": "announced_failure", "message_id": message_id}
