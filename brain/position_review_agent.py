"""Phase 61 — the open-position watcher, layer 2: the budgeted model pass.

Layer 1 (`brain/position_review.py`) measures every open position for free and
names the reasons a human would reconsider it. This layer takes the positions
where at least one of those reasons fired and asks ONE question about each:

    hold, tighten, take part, or exit — with reasoning and a confidence.

It follows the house agent pattern exactly (BaseAgent, the deep/cheap tiers,
`can_spend`, snapshot → call → clamp → persist), and it is deliberately on the
BALANCED tier rather than deep: layer 1 has already done the measurement, so
the model is answering a narrow question over a small, pre-computed snapshot.
Deep tier is reserved for the work that has to reason across the whole
platform, and `ai_agents.spend.DEEP_TIER_SHARE` holds budget back from it.

Three cost bounds, all of them hard:
  * MAX_MODEL_REVIEWS_PER_PASS   — the earnings reviewer's precedent
  * MAX_MODEL_REVIEWS_PER_DAY    — a ceiling the pass cadence cannot exceed
  * SAME_FACTS_TTL_HOURS         — a position already answered on the same
                                    bucketed facts is not asked again

The spend ceiling is checked INSIDE the pass rather than with `@spend_guard`
on the task, for the reason `brain.tasks.answer_research_question` documents:
the decorator's refusal path returns without running the body, and that would
silence the FREE deterministic layer along with the paid one. A day whose AI
budget is gone should still measure its positions and still raise a flag on a
stop 0.1R away — it just does not get prose about it. The refusal is written
onto the row as `skipped_reason` so the card can say why.

What this file cannot do
------------------------
Close anything. There is no import of `execute_close`, `_close_trade`, or the
kill switch anywhere in it, and a test pins that. A verdict is a proposal; the
operator acts from the position card or the notification, through
dashboard/views_close.py — the one close path that grades, audits, notifies and
consumes tax lots identically to a stop-out on the same row.
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


# ── Cost bounds ──────────────────────────────────────────────────────────

# Same precedent as EarningsReviewer.MAX_REVIEWS_PER_PASS, one notch tighter:
# positions are re-measured every half hour and earnings land twice a year.
MAX_MODEL_REVIEWS_PER_PASS = 3
# A ceiling the cadence cannot climb past. At the measured ~$0.01 per call
# this is ~$0.12/day even if every pass finds three new flagged positions.
MAX_MODEL_REVIEWS_PER_DAY = 12
# A position whose bucketed facts have not changed is not a new question.
# This is also what stops the table growing one row per position per cycle.
SAME_FACTS_TTL_HOURS = 6
# Per-call estimate handed to can_spend(). Deliberately generous against the
# ~$0.01 measured cost so the guard trips before the budget does.
ESTIMATED_USD_PER_REVIEW = 0.02

# Grading windows.
GRADE_MAX_WAIT_DAYS = 30      # after this an ungraded row is closed out
GRADE_NOISE_BAND_R = 0.25     # inside a quarter R the call did not decide much

# One notification per position per verdict per this window: a flagged
# position is re-measured every 30 minutes and the bell is not a ticker.
NOTIFY_COOLDOWN_HOURS = 6


# ══════════════════════════════════════════════════════════════════════════
# Snapshot
# ══════════════════════════════════════════════════════════════════════════

def build_snapshot(verdict: dict) -> dict:
    """Everything the model is allowed to see about one flagged position.

    Deliberately narrow. It does NOT include the news corpus or the knowledge
    graph — those are the earnings reviewer's and the strategist's jobs, they
    are where the token cost lives, and this agent's question does not need
    them. What it needs is the position, the thesis it was opened on, the
    measured facts, and what has changed since.
    """
    pos = verdict["position"]
    facts = dict(verdict["facts"])
    return {
        "as_of": timezone.now().isoformat(),
        "position": {
            "key": f"{pos['book']}:{pos['position_id']}",
            "book": ("asset bot trade" if pos["book"] == "bot"
                     else "portfolio position"),
            "symbol": pos["symbol"],
            "side": pos["side"],
            "asset_class": pos.get("asset_class", ""),
            "venue": "paper" if pos.get("paper") else "live",
            "qty": pos.get("qty"),
            "entry": pos.get("entry"),
            "initial_stop": pos.get("initial_stop"),
            "current_stop": pos.get("stop"),
            "target": pos.get("target"),
            "mark": facts.get("mark"),
            "opened_at": facts.get("opened_at"),
        },
        # The thesis: what the engine wrote at entry, plus the sub-scores of
        # the signal that most plausibly produced it (labelled as a heuristic
        # match, because it is one).
        "thesis": {
            "rule_name": pos.get("rule_name", ""),
            "entry_reason": facts.get("entry_reason", ""),
            "origin_signal": facts.get("origin_signal"),
            "suggested_horizon_days": facts.get("horizon_days"),
        },
        "measured": {
            "unrealized_r": facts.get("unrealized_r"),
            "r_still_at_risk_to_stop": facts.get("r_to_stop"),
            "r_left_to_target": facts.get("r_to_target"),
            "worst_excursion_r": facts.get("mae_r"),
            "best_excursion_r": facts.get("mfe_r"),
            "age_hours": facts.get("age_hours"),
            "age_days": facts.get("age_days"),
        },
        "what_changed": {
            "regime_at_entry": facts.get("regime_at_entry"),
            "regime_now": facts.get("regime_now"),
            "regime_confidence_now": facts.get("regime_confidence_now"),
            "brain_trust_band": facts.get("brain_trust_band"),
            "vol_at_entry": facts.get("vol_at_entry"),
            "vol_now": facts.get("vol_now"),
            "vol_ratio": facts.get("vol_ratio"),
            "rule_state": facts.get("rule_state"),
            "imminent_events": facts.get("imminent_events"),
            "concentration": facts.get("concentration"),
            # The opposite-side legs. `concentration` answers "how much of
            # the book says the same thing"; this answers "is the book
            # already flat on this instrument and paying for the privilege",
            # which changes what "exit" costs — closing one leg of a hedge
            # removes cost rather than taking risk off.
            "opposing_positions": facts.get("self_hedge"),
        },
        "triggers_that_fired": verdict["triggers"],
    }


# ══════════════════════════════════════════════════════════════════════════
# The agent
# ══════════════════════════════════════════════════════════════════════════

REVIEW_SCHEMA = """{
  "verdict": "hold | tighten | take_part | exit",
  "reasoning_md": "2-5 sentences. Answer the trigger that fired, in the trade's own numbers. No preamble.",
  "confidence": 0.0..1.0,
  "suggested_stop": number or null,
  "take_part_pct": integer 1..90 or null,
  "falsifiable_claim": "one sentence stating what must be true for this call to have been right, or null"
}"""


class PositionReviewerAgent(BaseAgent):
    """One bounded judgment on one open position."""

    agent_name = "position_reviewer"
    # Balanced, not deep: layer 1 already did the measuring, and this is a
    # narrow question over a small snapshot. See the module docstring.
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Position Reviewer. A position is OPEN "
            "right now and a deterministic pass has flagged it. You receive "
            "the position, the thesis it was opened on, the measured facts, "
            "what has changed since it opened, and the exact triggers that "
            "fired.\n\n"
            "Answer ONE question: should the operator hold, tighten, take "
            "part off, or exit?\n\n"
            "  hold      — the thesis still stands; the mechanical exits are "
            "the right instrument and nothing needs doing.\n"
            "  tighten   — the thesis stands but the risk profile changed; "
            "move the stop closer. Give the price in suggested_stop.\n"
            "  take_part — bank a portion and let the rest run. Give the "
            "percentage of the position to close in take_part_pct.\n"
            "  exit      — the reason the trade was taken no longer holds.\n\n"
            "Rules you must follow:\n"
            "- Reason in R, not in dollars or percentages. R is denominated "
            "by the stop the trade OPENED with. A number given to you as "
            "null is UNKNOWN — never treat it as zero and never invent it.\n"
            "- Answer the triggers that actually fired. Do not invent new "
            "concerns and do not restate the position back at the reader.\n"
            "- 'hold' is a real answer and often the right one. A trigger "
            "firing is a reason to LOOK, not a reason to act.\n"
            "- suggested_stop may only ever TIGHTEN the stop — move it "
            "toward the current mark, never away. A wider stop is more risk "
            "on a live position and will be discarded.\n"
            "- Calibrate the confidence. You will be graded on what the "
            "position actually did after this call.\n"
            "- You are ADVISING. Nothing you say closes anything; a human "
            "presses the button. Say the thing you would want said to you.\n\n"
            f"Respond ONLY with valid JSON in this schema:\n{REVIEW_SCHEMA}\n\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or {}
        return (
            "Open position under review (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "Produce the PositionReview JSON now."
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
            raise ValueError(f"non-JSON position reviewer output: {e}: "
                             f"{text[:200]}")
        if not isinstance(data, dict):
            raise ValueError("position reviewer returned non-dict")
        return data


# ══════════════════════════════════════════════════════════════════════════
# Clamping — what the model is allowed to have said
# ══════════════════════════════════════════════════════════════════════════

def clamp_suggested_stop(raw, *, facts: dict, dir_sign: int) -> Optional[float]:
    """A suggested stop, but only if it TIGHTENS.

    A model that widens the stop on a live position is proposing to take a
    bigger loss than the trade was sized for, and rendering that as advice on
    a card next to a CLOSE button is how a nudge becomes a mistake. It must
    sit between the current stop and the mark, on the correct side of both.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    mark = facts.get("mark")
    stop = facts.get("stop")
    if mark is None or value <= 0:
        return None
    if stop is None:
        # No stop to tighten from — a proposed level here is a NEW stop, and
        # the only safety property we can still check is that it is not
        # already through the mark.
        return value if (value < mark if dir_sign > 0 else value > mark) else None
    if dir_sign > 0:
        return value if (stop < value < mark) else None
    return value if (mark < value < stop) else None


def _clamp(parsed: dict, *, facts: dict, dir_sign: int) -> dict:
    from .position_review_models import PositionReview

    allowed = {PositionReview.VERDICT_HOLD, PositionReview.VERDICT_TIGHTEN,
               PositionReview.VERDICT_TAKE_PART, PositionReview.VERDICT_EXIT}
    verdict = str(parsed.get("verdict") or "").strip().lower()
    if verdict not in allowed:
        # A garbled answer must never read as "exit". Hold is the only safe
        # default: it is what happens if nobody does anything.
        verdict = PositionReview.VERDICT_HOLD

    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    take_part = parsed.get("take_part_pct")
    try:
        take_part = int(take_part)
        take_part = max(1, min(90, take_part))
    except (TypeError, ValueError):
        take_part = None
    if verdict != PositionReview.VERDICT_TAKE_PART:
        take_part = None

    stop = clamp_suggested_stop(parsed.get("suggested_stop"),
                                facts=facts, dir_sign=dir_sign)

    reasoning = parsed.get("reasoning_md")
    if not isinstance(reasoning, str):
        reasoning = ""

    claim = parsed.get("falsifiable_claim")
    if not isinstance(claim, str):
        claim = ""

    return {"verdict": verdict, "confidence": confidence,
            "take_part_pct": take_part, "suggested_stop": stop,
            "reasoning_md": reasoning[:4000], "falsifiable_claim": claim[:400]}


# ══════════════════════════════════════════════════════════════════════════
# Persistence
# ══════════════════════════════════════════════════════════════════════════

def persist_layer_one(verdict: dict):
    """Write the deterministic verdict and its evidence. Returns the row.

    Written BEFORE any model call so a provider outage still leaves the
    measurement on the record — the evidence is the durable half.
    """
    from .position_review_models import PositionReview
    from .position_review import _instrument_for

    pos = verdict["position"]
    facts = verdict["facts"]
    stale = bool(verdict["stale_quote"])
    return PositionReview.objects.create(
        book=pos["book"],
        position_id=pos["position_id"],
        symbol=pos["symbol"][:40],
        side=pos["side"][:4],
        user=pos.get("user"),
        instrument=_instrument_for(pos["symbol"]),
        triggers=verdict["triggers"],
        facts=facts,
        facts_hash=verdict["facts_hash"],
        severity=verdict["severity"],
        stale_quote=stale,
        mark=(Decimal(str(facts["mark"])) if facts.get("mark") is not None
              else None),
        unrealized_r=facts.get("unrealized_r"),
        r_to_stop=facts.get("r_to_stop"),
        r_to_target=facts.get("r_to_target"),
        mae_r=facts.get("mae_r"),
        mfe_r=facts.get("mfe_r"),
        age_hours=facts.get("age_hours") or 0.0,
        r_at_review=facts.get("unrealized_r"),
        verdict=(PositionReview.VERDICT_NO_QUOTE if stale
                 else PositionReview.VERDICT_NONE),
        skipped_reason=(facts.get("no_verdict_reason", "")[:200] if stale
                        else ""),
    )


def _post_hypothesis_for(review, verdict_row: dict, parsed: dict):
    """Post the falsifiable half of the claim into the hypothesis market.

    Only claims that map onto a resolver `brain.hypotheses` already owns are
    posted, because a hypothesis nothing can grade is exactly the opinion this
    module exists to stop producing:

      rule_decayed fired → "this rule keeps losing"      → rule_avg_r
      regime_flip  fired → "the new regime holds"        → regime_holds

    The recommendation ITSELF (was closing better than holding) is graded by
    `grade_due_reviews` below, against the R the position actually booked.
    """
    from .hypotheses import post_hypothesis
    from .position_review_models import PositionReview

    if review.verdict not in PositionReview.ACTIONABLE_VERDICTS:
        return None
    codes = set(review.trigger_codes)
    facts = review.facts or {}
    confidence = float(review.confidence or 0.5)
    claim_text = (parsed.get("falsifiable_claim")
                  or f"{review.symbol}: {review.verdict}")

    criteria = None
    horizon_hours = 24
    rule = (facts.get("rule_state") or {}).get("rule_name") or ""
    if "rule_decayed" in codes and rule:
        # 14 days and min_n 3 mirror the resolver's own sample-size guard —
        # an average over one trade would score the sample, not the rule.
        criteria = {"kind": "rule_avg_r", "rule_name": rule,
                    "comparator": "<", "threshold": 0.0,
                    "window_days": 14, "min_n": 3}
        horizon_hours = 14 * 24
        claim_text = (f"{rule} keeps losing money over the next 14 days — "
                      f"the reason {review.symbol} was told to "
                      f"{review.verdict}.")
    elif "regime_flip" in codes and facts.get("regime_now"):
        criteria = {"kind": "regime_holds", "regime": facts["regime_now"]}
        horizon_hours = 24
        claim_text = (f"The {facts['regime_now']} regime that turned against "
                      f"{review.symbol} still reads the same in 24h.")
    if criteria is None:
        return None

    try:
        hyp = post_hypothesis(
            claim_text=claim_text,
            source_agent=PositionReviewerAgent.agent_name,
            claim_payload={"review_id": review.id,
                           "position_key": review.position_key,
                           "verdict": review.verdict,
                           "triggers": sorted(codes)},
            resolution_criteria=criteria,
            confidence=confidence, horizon_hours=horizon_hours,
        )
    except Exception as e:  # noqa: BLE001 — a failed post must not lose the row
        logger.warning("[position-review] hypothesis post failed for #%s: %s",
                       review.id, e)
        return None
    review.hypothesis = hyp
    review.save(update_fields=["hypothesis"])
    return hyp


def _notify(review) -> bool:
    """Raise the recommendation where the operator already looks.

    Creating the `Notification` row is all three surfaces at once: the bell,
    and — through the post_save receiver in alerts.models — the live banner
    stack on the socket the operator's current page is holding. `data` carries
    the same card payload the position hover card reads, so the bell card and
    the position card cannot disagree about what was recommended.

    Only actionable verdicts notify. "Hold" is the status quo and pushing it
    would train the operator to dismiss the bell.
    """
    from .position_review_models import PositionReview

    if review.user_id is None:
        # portfolio.Portfolio has no user FK — nobody to push at. The verdict
        # is still on the card; see _portfolio_positions().
        return False
    if review.verdict not in PositionReview.ACTIONABLE_VERDICTS:
        return False

    from alerts.models import Notification
    icons = {PositionReview.VERDICT_EXIT: "⊟",
             PositionReview.VERDICT_TAKE_PART: "⊕",
             PositionReview.VERDICT_TIGHTEN: "▲"}
    label = {PositionReview.VERDICT_EXIT: "exit",
             PositionReview.VERDICT_TAKE_PART: "take part off",
             PositionReview.VERDICT_TIGHTEN: "tighten the stop"}
    r_text = ("—" if review.unrealized_r is None
              else f"{review.unrealized_r:+.2f}R")
    title = (f"{icons.get(review.verdict, '◉')} {review.symbol} "
             f"{review.side} · {label.get(review.verdict, review.verdict)}")

    try:
        cutoff = timezone.now() - timedelta(hours=NOTIFY_COOLDOWN_HOURS)
        if Notification.objects.filter(user_id=review.user_id, title=title[:200],
                                        created_at__gte=cutoff).exists():
            return False
    except Exception as e:  # noqa: BLE001 — dedupe failure must not mute it
        logger.warning("[position-review] notification dedupe failed: %s", e)

    reasons = "; ".join(t.get("text", "") for t in (review.triggers or [])[:2])
    body = (f"{r_text} open. {reasons}\n\n"
            f"{(review.reasoning_md or '').strip()[:600]}\n\n"
            f"This is a proposal — nothing has been closed. Use CLOSE on the "
            f"position card if you agree.")

    url = ""
    if review.book == PositionReview.BOOK_BOT:
        try:
            from alerts.links import page_url
            url = page_url("forensics_detail", review.position_id)
        except Exception:  # pragma: no cover
            url = ""
    try:
        Notification.objects.create(
            user_id=review.user_id, notification_type="portfolio",
            title=title[:200], body=body,
            url=Notification.safe_url(url),
            data={"kind": "position_review", **review.card_payload()},
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[position-review] notification failed for #%s: %s",
                       review.id, e)
        return False


# ══════════════════════════════════════════════════════════════════════════
# The model pass
# ══════════════════════════════════════════════════════════════════════════

def _reviews_today() -> int:
    """Model-backed reviews already paid for today."""
    from .position_review_models import PositionReview
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (PositionReview.objects
            .filter(created_at__gte=start, error="")
            .exclude(model_used="")
            .count())


def _same_facts_recently(facts_hash: str) -> bool:
    """Has this exact bucketed picture already been ANSWERED lately?

    Answered is the operative word, and it was the bug. The row is written
    before the per-pass cap, the daily cap and the budget check run — so a
    position that was measured and then REFUSED a model pass left behind a
    row carrying this hash, and the next pass could not tell that row from
    one that had actually been reasoned about. The refusal muted the
    position for the whole six-hour TTL, while the row's own
    `skipped_reason` read "re-queued next pass".

    The fingerprint is bucketed by design — quarter-R, whole days — so a
    position that is genuinely sitting still hashes identically pass after
    pass, and the lockout landed hardest on exactly the positions flagged
    for structural reasons that do not move: a decayed rule, a regime flip,
    a self-hedge, a horizon already exceeded.

    So: a row only suppresses re-asking if a model actually answered it.
    `skipped_reason` is set on every refusal path and empty on every
    answered one, which makes it the honest test.
    """
    from .position_review_models import PositionReview
    if not facts_hash:
        return False
    cutoff = timezone.now() - timedelta(hours=SAME_FACTS_TTL_HOURS)
    # A stale-mark row (VERDICT_NO_QUOTE) DOES suppress, deliberately: it
    # already says the only thing there is to say, and if the mark comes
    # back the facts change and the hash with them. An errored row keeps
    # VERDICT_NONE and so does not suppress — a failed API call should be
    # retried on the next beat, not treated as an answer.
    return PositionReview.objects.filter(
        facts_hash=facts_hash, created_at__gte=cutoff, skipped_reason=""
    ).exclude(verdict=PositionReview.VERDICT_NONE).exists()


def review_one(verdict: dict, review) -> dict:
    """Run the agent on one flagged position and fold the answer into `review`."""
    snapshot = build_snapshot(verdict)
    try:
        agent = PositionReviewerAgent()
        raw, usage = agent.provider.complete(
            system_prompt=agent.get_system_prompt(),
            user_message=agent.build_context(snapshot=snapshot),
            model=agent.model,
            agent_name=agent.agent_name,
            # Layer 1 wrote `review` BEFORE this call — the ref keeps a
            # timestamp-cut backfill from booking this cost twice.
            source_ref=f"PositionReview:{review.pk}",
        )
        parsed = agent.parse_response(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("[position-review] model pass failed for %s: %s",
                       review.position_key, e)
        review.error = str(e)[:1000]
        review.model_used = "error"
        review.save(update_fields=["error", "model_used"])
        return {"ok": False, "review_id": review.id, "error": str(e)}

    cleaned = _clamp(parsed, facts=verdict["facts"],
                      dir_sign=verdict["position"]["dir_sign"])
    review.verdict = cleaned["verdict"]
    review.reasoning_md = cleaned["reasoning_md"]
    review.confidence = cleaned["confidence"]
    review.take_part_pct = cleaned["take_part_pct"]
    review.suggested_stop = (Decimal(str(cleaned["suggested_stop"]))
                              if cleaned["suggested_stop"] is not None else None)
    review.model_used = agent.model
    review.tokens_in = int(usage.get("input_tokens", 0) or 0)
    review.tokens_out = int(usage.get("output_tokens", 0) or 0)
    review.cost_usd = Decimal(str(round(float(usage.get("cost_usd", 0) or 0), 6)))
    review.save(update_fields=[
        "verdict", "reasoning_md", "confidence", "take_part_pct",
        "suggested_stop", "model_used", "tokens_in", "tokens_out", "cost_usd",
    ])

    _post_hypothesis_for(review, verdict, cleaned)
    notified = _notify(review)
    return {"ok": True, "review_id": review.id,
            "position": review.position_key, "symbol": review.symbol,
            "verdict": review.verdict, "confidence": review.confidence,
            "notified": notified,
            "cost_usd": float(review.cost_usd)}


def review_open_positions_now(*,
                                max_reviews: int = MAX_MODEL_REVIEWS_PER_PASS,
                                daily_cap: int = MAX_MODEL_REVIEWS_PER_DAY
                                ) -> dict:
    """One full pass. Always returns a dict; never raises.

    Layer 1 runs for every open position unconditionally — it is free, and it
    is the half that answers "is anything watching my positions". Layer 2 runs
    only for positions layer 1 flagged, worst-first, inside three caps and the
    daily AI budget.
    """
    from ai_agents.spend import can_spend
    from .position_review import deterministic_pass

    verdicts = deterministic_pass()
    n_flagged = sum(1 for v in verdicts if v["triggers"])
    n_stale = sum(1 for v in verdicts if v["stale_quote"])

    reviewed: list[dict] = []
    n_rows = 0
    n_same_facts = 0
    n_capped = 0
    budget_note = ""
    spent_today = _reviews_today()

    for v in verdicts:
        # Nothing fired and the mark was fine: there is nothing to record.
        # A row per position per cycle would be a table full of the word "fine".
        if not v["triggers"] and not v["stale_quote"]:
            continue
        if _same_facts_recently(v["facts_hash"]):
            n_same_facts += 1
            continue

        review = persist_layer_one(v)
        n_rows += 1

        if not v["triggers"]:
            # Stale mark. No verdict is computed and none is paid for — the
            # row exists precisely to say the mark was unusable.
            continue

        if len(reviewed) >= max_reviews:
            n_capped += 1
            review.skipped_reason = (
                f"per-pass cap reached ({max_reviews}) — re-queued next pass")
            review.save(update_fields=["skipped_reason"])
            continue
        if spent_today + len(reviewed) >= daily_cap:
            n_capped += 1
            review.skipped_reason = f"daily model-review cap reached ({daily_cap})"
            review.save(update_fields=["skipped_reason"])
            continue

        allowed, reason = can_spend(tier=PositionReviewerAgent.default_tier,
                                     estimated_usd=ESTIMATED_USD_PER_REVIEW)
        if not allowed:
            budget_note = reason
            review.skipped_reason = f"AI budget: {reason}"[:200]
            review.save(update_fields=["skipped_reason"])
            continue

        result = review_one(v, review)
        reviewed.append(result)

    return {
        "ok": True,
        "n_positions": len(verdicts),
        "n_flagged": n_flagged,
        "n_stale_quote": n_stale,
        "n_rows_written": n_rows,
        "n_skipped_same_facts": n_same_facts,
        "n_skipped_capped": n_capped,
        "n_model_reviews": len(reviewed),
        "budget_note": budget_note,
        "reviews": reviewed,
    }


# ══════════════════════════════════════════════════════════════════════════
# Grading — the recommendation's own track record
# ══════════════════════════════════════════════════════════════════════════

def _closed_bot_trade(position_id: int):
    try:
        from bot_program.models import AssetBotTrade
        return (AssetBotTrade.objects
                .filter(pk=position_id, status="CLOSED")
                .values("realized_r", "closed_at", "outcome").first())
    except Exception:  # pragma: no cover
        return None


def grade_due_reviews(*, max_wait_days: int = GRADE_MAX_WAIT_DAYS) -> dict:
    """Score every actionable recommendation against what the position did.

    The claim an actionable verdict makes is exactly: "the rest of this hold
    was not worth having". So it is graded by comparing the R the operator
    could have had at the moment of the call (`r_at_review`) against the R the
    position actually booked. `hold` makes the opposite claim and is graded
    the other way round.

    Three honest non-answers, all of which stay OUT of the score:
      * the position is still open — nothing to compare against yet
      * the difference is inside GRADE_NOISE_BAND_R — the call did not decide
        enough to be credited or charged for it
      * the book records no realized R (portfolio.Position has no such field,
        and a bot row with no initial stop has no denominator)

    Grading a measurement failure as "wrong" is the same defect
    brain.hypotheses documents at length, one table over.
    """
    from .position_review_models import PositionReview

    now = timezone.now()
    give_up = now - timedelta(days=max(1, int(max_wait_days)))
    qs = PositionReview.objects.filter(
        graded_at__isnull=True,
        verdict__in=(PositionReview.ACTIONABLE_VERDICTS
                     + (PositionReview.VERDICT_HOLD,)),
    ).exclude(model_used="").exclude(model_used="error")

    right = wrong = unresolvable = pending = 0
    for review in qs:
        r_close = None
        note = ""
        if review.book == PositionReview.BOOK_BOT:
            row = _closed_bot_trade(review.position_id)
            if row is None:
                if review.created_at and review.created_at < give_up:
                    note = (f"still open {max_wait_days}d after the call — "
                            f"nothing to compare against")
                else:
                    pending += 1
                    continue
            else:
                r_close = row.get("realized_r")
                if r_close is None:
                    note = "the closed trade booked no R (no initial stop)"
        else:
            note = ("portfolio.Position records no realized R — this book "
                    "cannot grade a recommendation")

        if r_close is None or review.r_at_review is None:
            review.graded_outcome = PositionReview.OUTCOME_UNRESOLVABLE
            review.grading_notes = (note or "no R at the time of the call")[:300]
            unresolvable += 1
        else:
            delta = float(r_close) - float(review.r_at_review)
            review.r_at_close = float(r_close)
            if abs(delta) <= GRADE_NOISE_BAND_R:
                review.graded_outcome = PositionReview.OUTCOME_UNRESOLVABLE
                review.grading_notes = (
                    f"closed {delta:+.2f}R from the call — inside the "
                    f"{GRADE_NOISE_BAND_R}R noise band")[:300]
                unresolvable += 1
            else:
                # Actionable = "stop holding". Right when holding cost R.
                claimed_worse = review.verdict in PositionReview.ACTIONABLE_VERDICTS
                was_worse = delta < 0
                correct = (claimed_worse == was_worse)
                review.graded_outcome = (PositionReview.OUTCOME_RIGHT if correct
                                          else PositionReview.OUTCOME_WRONG)
                review.grading_notes = (
                    f"called {review.verdict} at {review.r_at_review:+.2f}R; "
                    f"closed at {r_close:+.2f}R ({delta:+.2f}R)")[:300]
                if correct:
                    right += 1
                else:
                    wrong += 1
        review.graded_at = now
        review.save(update_fields=["graded_at", "graded_outcome",
                                    "grading_notes", "r_at_close"])

    return {"ok": True, "graded_right": right, "graded_wrong": wrong,
            "unresolvable": unresolvable, "still_pending": pending}
