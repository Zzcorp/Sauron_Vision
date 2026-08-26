"""Phase 38 — knowledge graph + hypothesis market dashboards.

Three views:
  /knowledge/     — current state of the graph + per-kind expandable history
  /hypotheses/    — live hypothesis market + votes + per-agent trust leaderboard
  /consolidation/ — recent ConsolidationRun timeline (nightly compaction trace)
"""
from __future__ import annotations

from collections import defaultdict

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST


# ── Knowledge graph ───────────────────────────────────────────────────────

@login_required
def knowledge_dashboard(request):
    """Phase 63 — enriched knowledge graph dashboard.

    Adds: per-kind counts donut, avg confidence, version aggregates,
    last update timestamp, recently superseded count.
    """
    from brain.knowledge_models import KnowledgeNode

    current_qs = (KnowledgeNode.objects
                  .filter(superseded_by__isnull=True)
                  .order_by("kind", "key"))
    grouped = defaultdict(list)
    for node in current_qs:
        grouped[node.kind].append(node)

    n_current = current_qs.count()
    history_count = KnowledgeNode.objects.count()

    # Aggregates over current nodes
    confidences = [float(n.confidence or 0) for n in current_qs]
    avg_conf = round(sum(confidences) / max(len(confidences), 1), 3)
    high_conf = sum(1 for c in confidences if c >= 0.7)
    low_conf = sum(1 for c in confidences if c < 0.3)

    versions = [n.version for n in current_qs]
    avg_version = round(sum(versions) / max(len(versions), 1), 1)
    max_version = max(versions) if versions else 0

    # Recency: nodes whose successor was created in the last 24h
    # (no dedicated superseded_at field — use the FK successor's created_at).
    most_recent = current_qs.order_by("-created_at").first()
    cutoff = timezone.now() - __import__("datetime").timedelta(hours=24)
    superseded_24h = (KnowledgeNode.objects
        .filter(superseded_by__created_at__gte=cutoff).count())

    # Per-kind donut (current nodes)
    kind_donut = []
    for k, nodes in grouped.items():
        kind_donut.append({
            "key": k, "n": len(nodes),
            "pct": round(len(nodes) / max(n_current, 1) * 100, 1),
        })
    kind_donut.sort(key=lambda r: -r["n"])

    return render(request, "dashboard/knowledge.html", {
        "page_id": "knowledge",
        "groups": dict(grouped),
        "n_current": n_current,
        "n_history": history_count,
        "n_kinds": len(grouped),
        "avg_conf": avg_conf,
        "high_conf": high_conf,
        "low_conf": low_conf,
        "avg_version": avg_version,
        "max_version": max_version,
        "most_recent": most_recent,
        "superseded_24h": superseded_24h,
        "kind_donut": kind_donut,
    })


@login_required
def knowledge_node_history(request, kind: str, key: str):
    from brain.knowledge_models import KnowledgeNode
    history = KnowledgeNode.history(kind, key)
    return render(request, "dashboard/knowledge_history.html", {
        "page_id": "knowledge",
        "kind": kind, "key": key,
        "history": history,
    })


# ── Hypothesis market ─────────────────────────────────────────────────────

@login_required
def hypotheses_dashboard(request):
    """Phase 63 — enriched hypothesis market dashboard.

    Adds: outcome donut, agent counts, 7d/30d aggregates, due-soon flag,
    confirmed-rate stat, votes-volume metric.
    """
    from datetime import timedelta as _td
    from brain.knowledge_models import Hypothesis, HypothesisVote
    from brain.hypotheses import agent_trust_score, agent_combined_trust

    pending = list(Hypothesis.objects
                    .filter(outcome=Hypothesis.OUTCOME_PENDING)
                    .order_by("resolution_deadline")[:30])
    resolved = list(Hypothesis.objects
                     .exclude(outcome=Hypothesis.OUTCOME_PENDING)
                     .order_by("-resolved_at")[:30])

    # Aggregates over the full hypothesis market
    n_pending = Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_PENDING).count()
    n_confirmed = Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_CONFIRMED).count()
    n_refuted = Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_REFUTED).count()
    n_unresolvable = Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_UNRESOLVABLE).count()
    n_total = Hypothesis.objects.count()
    n_resolved_total = n_confirmed + n_refuted + n_unresolvable
    confirmed_rate = round(n_confirmed / max(n_resolved_total, 1) * 100, 1)
    refuted_rate = round(n_refuted / max(n_resolved_total, 1) * 100, 1)

    # Due-soon: pending with deadline in next 24h
    due_soon = Hypothesis.objects.filter(
        outcome=Hypothesis.OUTCOME_PENDING,
        resolution_deadline__lte=timezone.now() + _td(hours=24),
        resolution_deadline__isnull=False,
    ).count()
    overdue = Hypothesis.objects.filter(
        outcome=Hypothesis.OUTCOME_PENDING,
        resolution_deadline__lt=timezone.now(),
        resolution_deadline__isnull=False,
    ).count()

    # 7d activity
    cutoff_7 = timezone.now() - _td(days=7)
    n_new_7d = Hypothesis.objects.filter(created_at__gte=cutoff_7).count()
    n_resolved_7d = Hypothesis.objects.filter(
        resolved_at__gte=cutoff_7,
    ).exclude(outcome=Hypothesis.OUTCOME_PENDING).count()
    n_votes_7d = HypothesisVote.objects.filter(created_at__gte=cutoff_7).count()

    # Outcome donut over resolved hypotheses
    outcome_donut = []
    for k, v in [("confirmed", n_confirmed),
                  ("refuted", n_refuted),
                  ("unresolvable", n_unresolvable)]:
        if v > 0:
            outcome_donut.append({
                "key": k, "n": v,
                "pct": round(v / max(n_resolved_total, 1) * 100, 1),
            })

    # Agents leaderboard — Phase-56 shows BOTH the Brier-only score
    # (objective) and the combined score (Brier + operator override).
    # order_by clears Meta.ordering, which otherwise rides into the
    # DISTINCT projection and duplicates every agent per created_at.
    sources = (Hypothesis.objects.order_by("source_agent")
               .values_list("source_agent", flat=True).distinct())
    leaderboard = []
    for agent in sources:
        if not agent:
            continue
        brier = agent_trust_score(agent)
        combined = agent_combined_trust(agent)
        n_resolved = Hypothesis.objects.filter(
            source_agent=agent,
        ).exclude(outcome=Hypothesis.OUTCOME_PENDING).count()
        # NOT `n_confirmed`: that name already holds the MARKET's
        # all-time confirmations, computed above and rendered on the
        # headline tile. Rebinding it here left the tile showing
        # whichever agent sorted last — the page reported CONFIRMED 0
        # beside a rate of 3.5%, which is arithmetically impossible and
        # read as "the market has never once been right".
        agent_confirmed = Hypothesis.objects.filter(
            source_agent=agent, outcome=Hypothesis.OUTCOME_CONFIRMED).count()
        leaderboard.append({
            "agent": agent,
            "trust": combined,                       # primary sort key
            "brier_only_trust": brier,
            "combined_trust": combined,
            "n_resolved": n_resolved,
            "n_confirmed": agent_confirmed,
            "n_total": Hypothesis.objects.filter(source_agent=agent).count(),
        })
    leaderboard.sort(key=lambda r: (r["trust"] or 0), reverse=True)

    # Recent votes.
    recent_votes = list(HypothesisVote.objects
                         .select_related("hypothesis")
                         .order_by("-created_at")[:20])

    return render(request, "dashboard/hypotheses.html", {
        "page_id": "hypotheses",
        "pending": pending,
        "resolved": resolved,
        "leaderboard": leaderboard,
        "recent_votes": recent_votes,
        "n_total": n_total,
        "n_pending": n_pending,
        "n_confirmed": n_confirmed,
        "n_refuted": n_refuted,
        "n_unresolvable": n_unresolvable,
        "n_resolved_total": n_resolved_total,
        "confirmed_rate": confirmed_rate,
        "refuted_rate": refuted_rate,
        "due_soon": due_soon,
        "overdue": overdue,
        "n_new_7d": n_new_7d,
        "n_resolved_7d": n_resolved_7d,
        "n_votes_7d": n_votes_7d,
        "outcome_donut": outcome_donut,
    })


# ── Consolidation runs ────────────────────────────────────────────────────

@login_required
def consolidation_dashboard(request):
    """Phase 63 — enriched consolidation runs dashboard.

    Adds: 7d/30d aggregates of nodes added/superseded/hyp resolved/obs
    pruned, last-run timestamp, error rate, latest run callout.
    """
    from datetime import timedelta as _td
    from brain.knowledge_models import ConsolidationRun

    runs = list(ConsolidationRun.objects.all()[:30])
    runs_30d = list(ConsolidationRun.objects.filter(
        started_at__gte=timezone.now() - _td(days=30)
    ))
    runs_7d = [r for r in runs_30d
               if r.started_at >= timezone.now() - _td(days=7)]

    n_30d = len(runs_30d)
    n_errors_30d = sum(1 for r in runs_30d if r.error)
    success_rate_30d = round(
        (n_30d - n_errors_30d) / max(n_30d, 1) * 100, 1)

    sum_nodes_added_7d = sum(r.n_nodes_added for r in runs_7d)
    sum_nodes_superseded_7d = sum(r.n_nodes_superseded for r in runs_7d)
    sum_hyp_resolved_7d = sum(r.n_hypotheses_resolved for r in runs_7d)
    sum_obs_pruned_7d = sum(r.n_observations_pruned for r in runs_7d)

    latest_run = runs[0] if runs else None
    last_ok = next((r for r in runs if not r.error), None)

    return render(request, "dashboard/consolidation.html", {
        "page_id": "consolidation",
        "runs": runs,
        "n_7d": len(runs_7d),
        "n_30d": n_30d,
        "n_errors_30d": n_errors_30d,
        "success_rate_30d": success_rate_30d,
        "sum_nodes_added_7d": sum_nodes_added_7d,
        "sum_nodes_superseded_7d": sum_nodes_superseded_7d,
        "sum_hyp_resolved_7d": sum_hyp_resolved_7d,
        "sum_obs_pruned_7d": sum_obs_pruned_7d,
        "latest_run": latest_run,
        "last_ok": last_ok,
    })


# ── Admin actions ─────────────────────────────────────────────────────────

@staff_member_required
@require_POST
def consolidation_run_now(request):
    from brain.consolidation import consolidate_now
    from brain.tasks import run_consolidation as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Consolidation",
                                reverse("consolidation_dashboard"))
    if resp is not None:
        return resp
    request.session["consolidation_result"] = consolidate_now()
    return HttpResponseRedirect(reverse("consolidation_dashboard"))


@staff_member_required
@require_POST
def critic_run_now(request):
    """Admin-only — run a critic pass. XHR clicks enqueue the real beat
    task (the single most expensive recurring LLM call on the platform —
    it must not run inside a web request), announced on completion; a
    plain form POST keeps the old synchronous path."""
    from brain.critic import run_critic_pass
    from brain.tasks import run_critic_pass as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Critic pass",
                                reverse("hypotheses_dashboard"))
    if resp is not None:
        return resp
    request.session["critic_result"] = run_critic_pass(max_n=5)
    return HttpResponseRedirect(reverse("hypotheses_dashboard"))


# ── Phase 40 Strategist Briefing ──────────────────────────────────────────

@login_required
def briefing_dashboard(request):
    """Phase 63 — enriched Strategist briefing dashboard.

    Adds: 14d posture distribution, total cost / token aggregates,
    avg ideas per briefing, success/error rate, recent posture trend.
    """
    from collections import Counter
    from brain.briefing_models import StrategistBriefing

    latest = StrategistBriefing.objects.first()
    history = list(StrategistBriefing.objects.all()[:14])
    all_recent = list(StrategistBriefing.objects.all()[:30])

    # ?id= opens ANY briefing, not only the latest — the history rows
    # are links now. Bad or missing id falls back to the latest.
    selected = latest
    sel_id = request.GET.get("id")
    if sel_id:
        try:
            found = StrategistBriefing.objects.filter(pk=int(sel_id)).first()
            if found:
                selected = found
        except (TypeError, ValueError):
            pass

    n_total = StrategistBriefing.objects.count()
    n_history = len(history)
    n_errors = sum(1 for b in history if b.error)
    success_rate = round(
        (n_history - n_errors) / max(n_history, 1) * 100, 1)

    # Posture mix (last 14).
    posture_counter: Counter = Counter()
    for b in history:
        if b.posture and not b.error:
            posture_counter[b.posture] += 1
    posture_donut = []
    for k, v in posture_counter.most_common():
        posture_donut.append({
            "key": k, "n": v,
            "pct": round(v / max(n_history - n_errors, 1) * 100, 1),
        })

    # Aggregate cost/tokens (history window).
    cost_14d = sum(float(b.cost_usd or 0) for b in history)
    in_tok_14d = sum(b.tokens_in or 0 for b in history)
    out_tok_14d = sum(b.tokens_out or 0 for b in history)

    # Avg ideas + watchlist per successful briefing.
    succeeded = [b for b in history if not b.error]
    avg_ideas = round(
        sum(len(b.ideas or []) for b in succeeded) / max(len(succeeded), 1), 1)
    avg_watchlist = round(
        sum(len(b.watchlist or []) for b in succeeded) / max(len(succeeded), 1), 1)

    # Latest model used (from the most recent successful briefing).
    latest_ok = next((b for b in history if not b.error), None)

    return render(request, "dashboard/briefing.html", {
        "page_id": "briefing",
        "latest": latest,
        "selected": selected,
        "is_latest": selected is not None and latest is not None
                     and selected.pk == latest.pk,
        "history": history,
        "n_total": n_total,
        "n_history": n_history,
        "n_errors": n_errors,
        "success_rate": success_rate,
        "posture_donut": posture_donut,
        "cost_14d": "{:.4f}".format(cost_14d),
        "in_tok_14d": in_tok_14d,
        "out_tok_14d": out_tok_14d,
        "avg_ideas": avg_ideas,
        "avg_watchlist": avg_watchlist,
        "latest_ok": latest_ok,
    })


@staff_member_required
@require_POST
def briefing_run_now(request):
    """XHR clicks enqueue the real beat task — which also restores the
    @spend_guard budget check the synchronous path quietly bypassed."""
    from brain.strategist import run_strategist_now
    from brain.tasks import run_strategist as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Strategist briefing",
                                reverse("briefing_dashboard"))
    if resp is not None:
        return resp
    request.session["briefing_result"] = run_strategist_now()
    return HttpResponseRedirect(reverse("briefing_dashboard"))


# ── Phase 41 Strategy Generator ───────────────────────────────────────────

@login_required
def generated_dashboard(request):
    """Phase 63 — enriched generated-strategies dashboard.

    Adds: 30d aggregates, status donut, approval rate, oldest pending,
    auto-demotion count, total cost.
    """
    from collections import Counter
    from datetime import timedelta as _td
    from brain.generator_models import GeneratedSetupProposal
    from brain.demoter_models import RuleDemotion

    pending = list(GeneratedSetupProposal.objects
                    .filter(status="pending")
                    .select_related("setup", "rule_control", "hypothesis")
                    .order_by("-created_at"))
    history = list(GeneratedSetupProposal.objects
                    .exclude(status="pending")
                    .select_related("setup")
                    .order_by("-created_at")[:30])
    demotions = list(RuleDemotion.objects
                      .filter(restored_at__isnull=True)
                      .order_by("-demoted_at")[:20])

    n_pending = len(pending)
    n_approved = GeneratedSetupProposal.objects.filter(status="approved").count()
    n_rejected = GeneratedSetupProposal.objects.filter(status="rejected").count()
    n_expired = GeneratedSetupProposal.objects.filter(status="expired").count()
    n_total = GeneratedSetupProposal.objects.count()
    n_resolved = n_approved + n_rejected + n_expired
    approval_rate = round(n_approved / max(n_resolved, 1) * 100, 1)

    # 30d activity
    cutoff_30 = timezone.now() - _td(days=30)
    n_new_30d = GeneratedSetupProposal.objects.filter(
        created_at__gte=cutoff_30).count()
    cost_30d = sum(float(p.cost_usd or 0) for p in
                    GeneratedSetupProposal.objects.filter(created_at__gte=cutoff_30))

    # Oldest pending — the proposal that has been waiting longest for review
    oldest_pending = (GeneratedSetupProposal.objects
                       .filter(status="pending")
                       .order_by("created_at").first())

    # Auto-demotion stats
    n_demotions_open = RuleDemotion.objects.filter(restored_at__isnull=True).count()
    n_demotions_30d = RuleDemotion.objects.filter(demoted_at__gte=cutoff_30).count()

    # Status donut
    status_donut = []
    for k, v in [("pending", n_pending), ("approved", n_approved),
                  ("rejected", n_rejected), ("expired", n_expired)]:
        if v > 0:
            status_donut.append({
                "key": k, "n": v,
                "pct": round(v / max(n_total, 1) * 100, 1),
            })

    return render(request, "dashboard/generated.html", {
        "page_id": "generated",
        "pending": pending,
        "history": history,
        "demotions": demotions,
        "n_total": n_total,
        "n_pending": n_pending,
        "n_approved": n_approved,
        "n_rejected": n_rejected,
        "n_expired": n_expired,
        "approval_rate": approval_rate,
        "n_new_30d": n_new_30d,
        "cost_30d": "{:.4f}".format(cost_30d),
        "oldest_pending": oldest_pending,
        "n_demotions_open": n_demotions_open,
        "n_demotions_30d": n_demotions_30d,
        "status_donut": status_donut,
    })


@staff_member_required
@require_POST
def generated_run_now(request):
    from brain.strategy_generator import generate_strategies_now
    from brain.tasks import run_strategy_generator as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Strategy generation",
                                reverse("generated_dashboard"))
    if resp is not None:
        return resp
    request.session["generated_result"] = generate_strategies_now(max_proposals=3)
    return HttpResponseRedirect(reverse("generated_dashboard"))


@staff_member_required
@require_POST
def generated_approve(request, pk: int):
    """Arm a pending proposal's draft setup, and SAY SO either way.

    Approval can now be refused — `approve_proposal` re-validates the stored
    conditions before arming — and the refusal used to be a silent no-op here:
    the boolean was discarded and the operator was redirected to a page that
    still showed the proposal pending, with the reason only in the worker log.
    Every proposal written before the validator was widened refuses on the
    first click, so this was the common path, not the edge case.
    """
    from django.contrib import messages
    from brain.generator_models import GeneratedSetupProposal
    from brain.strategy_generator import approval_blocker, approve_proposal
    proposal = GeneratedSetupProposal.objects.filter(pk=pk).first()
    if proposal is None:
        messages.error(request, f"Proposal #{pk} not found.")
    else:
        # The blocker is read BEFORE approving: a successful approve moves the
        # row out of PENDING, so asking afterwards would answer about the state
        # the approval itself created.
        blocker = approval_blocker(proposal)
        if approve_proposal(proposal,
                            reviewed_by=request.user.username,
                            notes=request.POST.get("notes", "")):
            messages.success(
                request, f"Armed '{proposal.proposed_name}' — the scanner picks "
                         f"it up on the next pass.")
        else:
            messages.error(
                request, f"Not armed: '{proposal.proposed_name}' — {blocker}")
    return HttpResponseRedirect(reverse("generated_dashboard"))


@staff_member_required
@require_POST
def generated_reject(request, pk: int):
    from brain.generator_models import GeneratedSetupProposal
    from brain.strategy_generator import reject_proposal
    proposal = GeneratedSetupProposal.objects.filter(pk=pk).first()
    if proposal is not None:
        reject_proposal(proposal,
                         reviewed_by=request.user.username,
                         notes=request.POST.get("notes", ""))
    return HttpResponseRedirect(reverse("generated_dashboard"))


@staff_member_required
@require_POST
def demoter_run_now(request):
    from brain.demoter import scan_generated_rules_now
    from brain.tasks import run_auto_demoter as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Auto-demoter scan",
                                reverse("generated_dashboard"))
    if resp is not None:
        return resp
    request.session["demoter_result"] = scan_generated_rules_now()
    return HttpResponseRedirect(reverse("generated_dashboard"))


@staff_member_required
@require_POST
def restore_rule_now(request, rule_name: str):
    from brain.demoter import restore_rule
    restore_rule(rule_name, restored_by=request.user.username)
    return HttpResponseRedirect(reverse("generated_dashboard"))


# ── Phase 48: Intelligence hub — single-screen overview ──────────────────

# ── Phase 50: Research conversational tab ────────────────────────────────

@login_required
def research_view(request):
    from brain.research_agent import get_or_create_active_conversation
    from brain.research_renderer import (
        render_markers, has_strategy_draft, extract_action_markers,
    )
    # ── Phase 64.5 — merged Mind pane: pull latest brain context so the
    # operator can see what Sauron believes WHILE chatting with it.
    from brain.models import BrainReport, BrainObservation
    from brain.context import _brain_trust_score, brain_trust_band
    mind_latest = BrainReport.objects.filter(error="").first()
    mind_trust = _brain_trust_score()
    mind_trust_band = brain_trust_band(mind_trust) if mind_trust is not None else "unknown"
    mind_obs_unconsumed = (BrainObservation.objects
                            .filter(consumed_by_brain_at__isnull=True).count())
    mind_top_concerns = (mind_latest.top_concerns
                          if mind_latest else []) or []

    conv = get_or_create_active_conversation(request.user)
    raw_messages = list(conv.messages.order_by("created_at"))

    # Phase-59 + 60 pipeline:
    #  1. Strip action markers from the body, capture the action specs (P60)
    #  2. Render link markers to clickable links on the cleaned body (P59)
    #  3. Flag draft-block presence for the inline save button (P59)
    messages_list = []
    is_staff = bool(request.user.is_staff)
    for m in raw_messages:
        if m.is_pending:
            # A question a worker is still answering. Rendered as a sentence
            # rather than an empty bubble: this page is reached by opening
            # /research/ mid-answer, and a blank assistant turn reads as
            # Sauron having ignored the question.
            cleaned = rendered = PENDING_BODY_TEXT
            actions = []
        elif m.role == "assistant":
            cleaned, actions = extract_action_markers(m.content)
            rendered = render_markers(cleaned)
        else:
            cleaned = m.content
            rendered = m.content
            actions = []
        messages_list.append({
            "id": m.id,
            "role": m.role,
            "content": rendered if m.is_pending else m.content,
            "rendered_content": rendered,
            "pending": m.is_pending,
            "has_draft": (m.role == "assistant" and not m.is_pending
                           and has_strategy_draft(m.content)),
            # Action buttons only visible to staff who can actually click.
            "actions": actions if is_staff else [],
            "model_used": m.model_used,
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "cost_usd": m.cost_usd,
            "error": m.error,
            "created_at": m.created_at,
        })

    past_conversations = (
        request.user.research_conversations
        .filter(is_active=False).order_by("-last_message_at")[:10]
    )
    return render(request, "dashboard/research.html", {
        "page_id": "research",
        "conversation": conv,
        "messages_list": messages_list,
        "past_conversations": past_conversations,
        "mind_latest": mind_latest,
        "mind_trust": mind_trust,
        "mind_trust_band": mind_trust_band,
        "mind_obs_unconsumed": mind_obs_unconsumed,
        "mind_top_concerns": mind_top_concerns[:4],
    })


@login_required
@require_POST
def research_ask(request):
    """POST endpoint to ask Sauron a question. Returns 302 → /research/ so
    the new exchange is visible. (HTMX-friendly: same response works for a
    plain form submit.)"""
    from brain.research_agent import (
        get_or_create_active_conversation, ask,
    )
    question = (request.POST.get("question") or "").strip()
    if question:
        conv = get_or_create_active_conversation(request.user)
        ask(conv, question)
    return HttpResponseRedirect(reverse("research_view"))


@login_required
@require_POST
def research_new_conversation(request):
    from brain.research_agent import archive_active_conversation
    archive_active_conversation(request.user)
    return HttpResponseRedirect(reverse("research_view"))


@login_required
@require_POST
def research_delete_message(request, message_id: int):
    """Delete one message from the operator's own conversation.

    A chat you cannot prune is a chat that accumulates every mistyped question
    and every failed answer forever, and here those failures are stored as
    error-stamped assistant messages that stay in the thread.

    Scoped to conversation__user, so a message id from someone else's thread
    is a 404 rather than a deletion.
    """
    from django.http import JsonResponse
    from brain.research_models import ResearchMessage

    msg = ResearchMessage.objects.filter(
        pk=message_id, conversation__user=request.user).first()
    if msg is None:
        return JsonResponse({"ok": False, "error": "not found"}, status=404)

    # A question and the answer it produced are one exchange; deleting the
    # question and leaving the reply orphaned reads as the assistant talking
    # to itself.
    #
    # Paired by the explicit `replies_to` link, falling back to "the next
    # assistant row" only for exchanges written before that link existed:
    # two tabs asking at the same moment interleave their rows, and the
    # positional guess would then delete the OTHER tab's answer.
    removed = [msg.pk]
    if msg.role == ResearchMessage.ROLE_USER:
        reply = msg.replies.first()
        if reply is None:
            reply = (ResearchMessage.objects
                     .filter(conversation=msg.conversation,
                             role=ResearchMessage.ROLE_ASSISTANT,
                             replies_to__isnull=True,
                             created_at__gt=msg.created_at)
                     .order_by("created_at").first())
        if reply is not None:
            removed.append(reply.pk)
            reply.delete()
    msg.delete()
    return JsonResponse({"ok": True, "deleted": removed})


@login_required
@require_POST
def research_delete_conversation(request, conversation_id: int):
    """Delete a whole thread. Messages cascade."""
    from django.http import JsonResponse
    from brain.research_models import ResearchConversation

    conv = ResearchConversation.objects.filter(
        pk=conversation_id, user=request.user).first()
    if conv is None:
        return JsonResponse({"ok": False, "error": "not found"}, status=404)
    was_active = conv.is_active
    conv.delete()
    # Deleting the open thread must leave one to type into, or the page comes
    # back with no conversation at all.
    if was_active:
        from brain.research_agent import get_or_create_active_conversation
        get_or_create_active_conversation(request.user)
    return JsonResponse({"ok": True, "was_active": was_active})


@login_required
@require_POST
def research_open_conversation(request, conversation_id: int):
    """Resume an archived thread.

    Past conversations were listed in a table with no way to open one, so the
    history was visible and unreachable — the only thing you could do with a
    conversation was start a new one on top of it.
    """
    from brain.research_models import ResearchConversation

    conv = ResearchConversation.objects.filter(
        pk=conversation_id, user=request.user).first()
    if conv is not None:
        # Exactly one active thread per user is the invariant the rest of this
        # module relies on.
        ResearchConversation.objects.filter(
            user=request.user, is_active=True).update(is_active=False)
        conv.is_active = True
        conv.save(update_fields=["is_active"])
    return HttpResponseRedirect(reverse("research_view"))


@login_required
@require_POST
def research_save_as_draft(request, message_id: int):
    """Phase-59: extract a strategy-draft block from an assistant message
    and persist it as a Phase-41 GeneratedSetupProposal (is_active=False,
    research-stage RuleControl).

    Validation reuses Phase-41's `validate_proposal()` so the schema rules
    are identical to the autonomous generator. Source agent is recorded
    as `research:<username>` so the audit chain shows it came from chat
    + which user proposed it.
    """
    from brain.research_models import ResearchMessage
    from brain.research_renderer import extract_strategy_draft
    from brain.strategy_generator import _persist_proposal

    msg = ResearchMessage.objects.filter(
        pk=message_id,
        conversation__user=request.user,
        role=ResearchMessage.ROLE_ASSISTANT,
    ).first()
    if msg is None:
        request.session["research_save_result"] = {
            "ok": False, "error": "message not found or not yours",
        }
        return HttpResponseRedirect(reverse("research_view"))

    draft = extract_strategy_draft(msg.content)
    if draft is None:
        request.session["research_save_result"] = {
            "ok": False, "error": "no strategy-draft block in this message",
        }
        return HttpResponseRedirect(reverse("research_view"))

    row = _persist_proposal(
        draft, model=f"research:{request.user.username}",
        tokens_in=msg.tokens_in, tokens_out=msg.tokens_out,
        cost_usd=float(msg.cost_usd or 0),
    )
    if row is None:
        request.session["research_save_result"] = {
            "ok": False,
            "error": "draft failed validation — check evaluator kinds + schema",
        }
    else:
        request.session["research_save_result"] = {
            "ok": True,
            "proposal_id": row.id,
            "proposed_name": row.proposed_name,
        }
    return HttpResponseRedirect(reverse("research_view"))


# ── Phase 64: floating chat shortcut (JSON) ──────────────────────────────

# What the panel and the /research/ page show where the answer will go
# while a worker is still producing it.
PENDING_BODY_TEXT = "Sauron is still answering — the reply lands here."

# How much of the thread the panel restores. The panel is a shortcut, not
# the archive; /research/ holds the whole conversation.
THREAD_LIMIT = 40


def _dispatch_answer(request, pending):
    """Hand one pending answer to a worker, following the run-now precedent.

    Returns a 202 JsonResponse when the work was enqueued; None means
    "answer inside this request instead" — either because the caller is a
    plain form POST with no way to hear a later announcement, or because
    the broker is down. A dead worker must degrade to the old synchronous
    behaviour, never to a lost question.

    Deliberately WITHOUT run_async's one-in-flight-per-job cache lock: that
    lock stops a second click launching a duplicate of the same expensive
    beat job, but every question is its own job, and two tabs (or two
    operators) asking at the same moment is ordinary use — a shared lock
    here would 409 the second question.
    """
    from django.http import JsonResponse
    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or ""))
    if not wants_json:
        return None
    from brain.tasks import (answer_research_question,
                             announce_research_answer,
                             announce_research_failed)
    try:
        async_result = answer_research_question.apply_async(
            kwargs={"message_id": pending.pk},
            link=announce_research_answer.s(request.user.pk, pending.pk),
            link_error=announce_research_failed.s(request.user.pk,
                                                  pending.pk),
        )
    except Exception as e:  # noqa: BLE001 — broker down: answer here instead
        import logging
        logging.getLogger(__name__).warning(
            "[ask-sauron] async dispatch failed for message %s: %s — "
            "answering inside the request", pending.pk, e)
        return None
    return JsonResponse({
        "ok": True,
        "pending": True,
        "user_message_id": pending.replies_to_id,
        "pending_message_id": pending.pk,
        "task_id": async_result.id,
    }, status=202)


@login_required
@require_POST
def research_ask_ajax(request):
    """JSON twin of `research_ask` for the global floating chat widget.

    An XHR ask persists the exchange, hands the answer to a worker and
    returns 202 at once with the pending message's id. The answer announces
    itself later on the operator's own socket, so it reaches whatever page
    they are on by then — before this, the agent ran inside the request and
    changing page aborted the fetch, discarding an answer that had already
    been paid for.

    A caller that does not identify as XHR (the /research/ page's own form)
    keeps the synchronous contract: it has no socket handler to hear a later
    announcement, so it must be answered in the response.
    """
    from django.http import JsonResponse
    from brain.research_agent import (
        get_or_create_active_conversation, begin_ask, complete_ask,
    )
    from brain.research_renderer import (
        render_markers, extract_action_markers, has_strategy_draft,
    )

    question = (request.POST.get("question") or "").strip()
    if not question:
        return JsonResponse({"ok": False, "error": "empty question"},
                             status=400)

    conv = get_or_create_active_conversation(request.user)
    _user_msg, pending = begin_ask(conv, question)

    resp = _dispatch_answer(request, pending)
    if resp is not None:
        return resp

    result = complete_ask(pending.pk)

    from core.templatetags.sauron_tags import research_md

    asst_id = result.get("assistant_message_id")
    asst_html = asst_text = ""
    has_draft = False
    if asst_id:
        from brain.research_models import ResearchMessage
        msg = ResearchMessage.objects.filter(pk=asst_id).first()
        if msg is not None:
            cleaned, _actions = extract_action_markers(msg.content)
            asst_text = render_markers(cleaned)
            # The same filter the page template applies to a stored turn,
            # so an answer painted in place looks like the same answer
            # after a reload. The plain twin feeds the banner preview,
            # which quotes text and would otherwise show the tags.
            asst_html = str(research_md(asst_text))
            has_draft = has_strategy_draft(msg.content)

    return JsonResponse({
        "ok": bool(result.get("ok")),
        "pending": False,
        "error": result.get("error"),
        "user_message_id": result.get("user_message_id"),
        "assistant_message_id": asst_id,
        "assistant_html": asst_html,
        "assistant_text": asst_text,
        "has_draft": has_draft,
        "tokens_in": result.get("tokens_in"),
        "tokens_out": result.get("tokens_out"),
        "cost_usd": result.get("cost_usd"),
    })


@login_required
def research_thread(request):
    """The operator's live conversation, as JSON — the panel's load path.

    The floating panel had no load path at all: it painted only what the
    page in front of you had itself typed, so every navigation emptied it
    while the conversation carried on existing in the database. This serves
    that thread to any page, including a question still being answered,
    which is what lets a pending bubble resolve in place after a page
    change.

    Read-only on purpose — it is called on every page load, so it must not
    create an empty conversation row for a user who has never chatted.
    """
    from django.http import JsonResponse
    from brain.research_models import ResearchConversation
    from brain.research_renderer import (
        render_markers, extract_action_markers, has_strategy_draft,
    )

    conv = (ResearchConversation.objects
            .filter(user=request.user, is_active=True)
            .order_by("-last_message_at").first())
    if conv is None:
        return JsonResponse({"ok": True, "conversation_id": None,
                             "pending": False, "messages": []})

    rows = list(conv.messages.order_by("-created_at")[:THREAD_LIMIT])
    rows.reverse()

    messages = []
    n_pending = 0
    for m in rows:
        if m.is_pending:
            n_pending += 1
            text = PENDING_BODY_TEXT
            draft = False
        elif m.role == "assistant":
            cleaned, _actions = extract_action_markers(m.content)
            text = render_markers(cleaned)
            draft = has_strategy_draft(m.content)
        else:
            text = m.content
            draft = False
        messages.append({
            "id": m.id,
            "role": m.role,
            "text": text,
            "pending": m.is_pending,
            "error": bool(m.error),
            "has_draft": draft,
        })

    return JsonResponse({
        "ok": True,
        "conversation_id": conv.id,
        "pending": n_pending > 0,
        "messages": messages,
    })


# ── Phase 49: Earnings Reviewer dashboard ────────────────────────────────

@login_required
def earnings_reviews_dashboard(request):
    """Phase 63 — enriched earnings-reviewer dashboard.

    Adds: 7d/30d aggregates, direction donut, total cost+tokens,
    by-symbol counts, error rate, latest model.
    """
    from collections import Counter
    from datetime import timedelta as _td
    from brain.earnings_models import EarningsReview

    reviews = list(
        EarningsReview.objects.select_related("instrument")
        .order_by("-created_at")[:30]
    )
    n_total = EarningsReview.objects.count()

    cutoff_30 = timezone.now() - _td(days=30)
    cutoff_7 = timezone.now() - _td(days=7)
    n_30d = EarningsReview.objects.filter(created_at__gte=cutoff_30).count()
    n_7d = EarningsReview.objects.filter(created_at__gte=cutoff_7).count()

    # Direction mix donut over last 30d
    dir_counter: Counter = Counter()
    cost_30d = 0.0
    in_tok_30d = 0
    out_tok_30d = 0
    n_errors_30d = 0
    for r in EarningsReview.objects.filter(created_at__gte=cutoff_30):
        if r.error:
            n_errors_30d += 1
        elif r.implied_direction:
            dir_counter[r.implied_direction] += 1
        cost_30d += float(r.cost_usd or 0)
        in_tok_30d += r.tokens_in or 0
        out_tok_30d += r.tokens_out or 0

    success_rate_30d = round(
        (n_30d - n_errors_30d) / max(n_30d, 1) * 100, 1)

    direction_donut = []
    n_dirs_total = sum(dir_counter.values())
    for k in ("bullish", "bearish", "neutral"):
        v = dir_counter.get(k, 0)
        if v > 0:
            direction_donut.append({
                "key": k, "n": v,
                "pct": round(v / max(n_dirs_total, 1) * 100, 1),
            })

    # By-symbol counts (top 8 in last 30d)
    sym_counter: Counter = Counter()
    for r in EarningsReview.objects.filter(created_at__gte=cutoff_30).select_related("instrument"):
        if r.instrument and r.instrument.symbol:
            sym_counter[r.instrument.symbol] += 1
    top_symbols = [{"symbol": s, "n": n}
                    for s, n in sym_counter.most_common(8)]

    return render(request, "dashboard/earnings_reviews.html", {
        "page_id": "earnings_reviews",
        "reviews": reviews,
        "n_total": n_total,
        "n_30d": n_30d,
        "n_7d": n_7d,
        "n_errors_30d": n_errors_30d,
        "success_rate_30d": success_rate_30d,
        "cost_30d": "{:.4f}".format(cost_30d),
        "in_tok_30d": in_tok_30d,
        "out_tok_30d": out_tok_30d,
        "direction_donut": direction_donut,
        "top_symbols": top_symbols,
    })


@staff_member_required
@require_POST
def earnings_reviewer_run_now(request):
    from brain.earnings_reviewer import scan_due_earnings_now
    from brain.tasks import run_earnings_reviewer as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Earnings reviews",
                                reverse("earnings_reviews_dashboard"))
    if resp is not None:
        return resp
    request.session["earnings_reviewer_result"] = scan_due_earnings_now()
    return HttpResponseRedirect(reverse("earnings_reviews_dashboard"))


@login_required
def intelligence_hub(request):
    """Aggregates the most actionable info from across the brain stack so
    the operator gets the big picture in 30 seconds without clicking
    through 6 dashboards."""
    from brain.models import BrainReport, BrainObservation
    from brain.briefing_models import StrategistBriefing
    from brain.knowledge_models import (
        KnowledgeNode, Hypothesis, ConsolidationRun,
    )
    from brain.generator_models import GeneratedSetupProposal
    from brain.demoter_models import RuleDemotion
    from brain.context import _brain_trust_score, brain_trust_band

    latest_report = BrainReport.objects.first()
    latest_briefing = StrategistBriefing.objects.first()

    # Trust + band for the header strip.
    trust = _brain_trust_score()
    band = brain_trust_band(trust)

    # Pending hypotheses (in progress) + recently confirmed/refuted (last 24h).
    pending_hypotheses = list(
        Hypothesis.objects.filter(outcome=Hypothesis.OUTCOME_PENDING)
        .order_by("resolution_deadline")[:8]
    )
    recent_resolved = list(
        Hypothesis.objects.exclude(outcome=Hypothesis.OUTCOME_PENDING)
        .order_by("-resolved_at")[:8]
    )

    # Pending generated proposals + open auto-demotions.
    pending_proposals = list(
        GeneratedSetupProposal.objects.filter(status="pending")
        .select_related("setup")
        .order_by("-created_at")[:5]
    )
    open_demotions = list(
        RuleDemotion.objects.filter(restored_at__isnull=True)
        .order_by("-demoted_at")[:5]
    )

    # Knowledge graph: count current nodes by kind.
    from django.db.models import Count
    node_counts = list(
        KnowledgeNode.objects.filter(superseded_by__isnull=True)
        .values("kind").annotate(n=Count("id")).order_by("-n")
    )

    # Observations queued for next synthesis.
    n_unconsumed_obs = (BrainObservation.objects
                         .filter(consumed_by_brain_at__isnull=True).count())

    # Phase-51 — recent anomalies (last 24h, deduped by detector+key).
    from datetime import timedelta as _td
    cutoff = timezone.now() - _td(hours=24)
    recent_anomaly_obs = list(
        BrainObservation.objects.filter(
            kind="anomaly_detected", created_at__gte=cutoff,
        ).order_by("-created_at")[:10]
    )

    # Phase-55 — operator overrides + per-agent override rates.
    try:
        from bot_program.audit_queries import (
            recent_overrides, override_counts_by_target_agent,
            agent_override_rate,
        )
        recent_overrides_list = recent_overrides(days=7, limit=10)
        override_counts = override_counts_by_target_agent(days=7)
        agent_override_rates = {
            agent: agent_override_rate(agent, days=30)
            for agent in ("strategy_generator", "demoter")
        }
    except Exception:
        recent_overrides_list = []
        override_counts = {}
        agent_override_rates = {}

    # Last consolidation run for the "system pulse" line.
    last_consolidation = ConsolidationRun.objects.first()

    return render(request, "dashboard/intelligence.html", {
        "page_id": "intelligence",
        "latest_report": latest_report,
        "latest_briefing": latest_briefing,
        "trust": trust,
        "band": band,
        "pending_hypotheses": pending_hypotheses,
        "recent_resolved": recent_resolved,
        "pending_proposals": pending_proposals,
        "open_demotions": open_demotions,
        "node_counts": node_counts,
        "n_unconsumed_obs": n_unconsumed_obs,
        "last_consolidation": last_consolidation,
        "recent_anomaly_obs": recent_anomaly_obs,
        "recent_overrides_list": recent_overrides_list,
        "override_counts": override_counts,
        "agent_override_rates": agent_override_rates,
    })
