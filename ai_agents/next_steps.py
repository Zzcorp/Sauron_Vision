"""THE NEXT STEPS (2026-10-03): Sauron reads its own reports.

The operator: "Weekly Review — couldn't we make Sauron get it, so that he
can arrange the situation and get ready for the next steps? Same for the
morning and end-of-day brief." Until now every scheduled report — the
morning briefing, the weekly review, the Monday plan, the end-of-day
digest — went to the bell, Telegram and a page, and nothing on the
platform read a word of it back (the survey of 2026-10-02: only the
fenced `calls` block was machine-read, and only to grade predictions).

Now a second, cheap pass (NextStepsAgent, the fast tier) turns each
report's prose into at most MAX_STEPS structured steps, each one of:

  pause_rule    a rule the report says should stop firing
  reduce_size   a rule the report says should trade smaller
  watch         an instrument the report says to keep an eye on
  note          anything else worth carrying forward

Every ref is checked against what the platform knows — a rule name in
rule_actuator.governed_rule_names(), an active Instrument symbol — and a
step naming anything else is dropped and logged, never invented into the
book. One standing step per (kind, ref): a report repeating last week's
advice does not stack it.

NOTHING ACTS ON ITS OWN. A step is a PROPOSAL the operator approves on
/briefing/#next-steps (or `manage.py next_steps approve ID`). Approving a
pause or a size cut creates a RuleAction proposal — the same row the
decay investigator and the brain page create — which an admin then
applies at HQ under the actuator's own switch and daily caps. Approving a
watch stars the instrument. A note is acknowledged. A step nobody answers
expires after EXPIRE_DAYS. The staff group hears once per report that
steps were proposed, with the count, never the money.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

COMPONENT_KEY = "agent_next_steps"
KINDS = ("pause_rule", "reduce_size", "watch", "note")
REPORTS = {
    "daily_briefing": "the morning briefing",
    "weekly_review": "the weekly review",
    "monday_plan": "the Monday plan",
    "eod_digest": "the end-of-day digest",
}
MAX_STEPS = 7
MAX_TEXT = 12000
MAX_SYMBOLS = 400
EXPIRE_DAYS = 7
PAGE_PATH = "/briefing/#next-steps"
KIND_WORDS = {"pause_rule": "pause the rule", "reduce_size": "trade smaller",
              "watch": "watch", "note": "note"}

SCHEMA = (
    '{"steps": [{"kind": "pause_rule|reduce_size|watch|note", '
    '"ref": "<rule name or instrument symbol, or \\"\\" for a note>", '
    '"why": "<one sentence, the report\'s own reason>", '
    '"confidence": 0.0}]}'
)


class NextStepsAgent(BaseAgent):
    """The cheap reader: a report in, at most MAX_STEPS structured steps
    out. Strict JSON, no fences, nothing invented."""
    agent_name = "next_steps"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return (
            "You read one of Sauron's own trading reports and extract the "
            "NEXT STEPS it recommends, as data for an operator to approve. "
            f"Return at most {MAX_STEPS} steps. Each step has a kind: "
            "pause_rule (a trading rule the report says should stop), "
            "reduce_size (a rule the report says should trade smaller), "
            "watch (an instrument the report says to keep an eye on), or "
            "note (anything else worth carrying into the next session). "
            "The ref of a pause_rule or reduce_size step MUST be one of the "
            "rule names given; the ref of a watch step MUST be one of the "
            "symbols given; a note has ref \"\". Never invent a rule or a "
            "symbol: if the report names none, return fewer steps or none. "
            "Confidence is how plainly the report says it (0 to 1). "
            f"Respond ONLY with valid JSON in this schema:\n{SCHEMA}\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, report_kind="", text="", rules=(), symbols=(),
                      **_kw) -> str:
        return (
            f"REPORT: {REPORTS.get(report_kind, report_kind)}\n\n"
            f"RULE NAMES (the only refs a pause_rule or reduce_size step may "
            f"carry): {', '.join(rules) or 'none'}\n\n"
            f"SYMBOLS (the only refs a watch step may carry): "
            f"{', '.join(symbols) or 'none'}\n\n"
            f"--- the report ---\n{(text or '')[:MAX_TEXT]}\n--- end ---"
        )

    def parse_response(self, raw: str) -> dict:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"non-JSON next_steps output: {e}: {text[:200]}")
        if not isinstance(data, dict) or not isinstance(data.get("steps"),
                                                         list):
            raise ValueError("next_steps returned no steps list")
        return data


def validate(steps, rules, symbols) -> list:
    """The steps the platform can stand behind: known kinds, known refs,
    a why, at most MAX_STEPS; the rest dropped and logged."""
    rules, symbols = set(rules), set(symbols)
    out, seen = [], set()
    for raw in (steps or [])[:MAX_STEPS * 2]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip()
        ref = str(raw.get("ref") or "").strip()
        why = str(raw.get("why") or "").strip()[:500]
        if kind not in KINDS or not why:
            continue
        if kind in ("pause_rule", "reduce_size") and ref not in rules:
            logger.info("[next-steps] dropped %s on unknown rule %r", kind, ref)
            continue
        if kind == "watch":
            ref = ref.upper()
            if ref not in symbols:
                logger.info("[next-steps] dropped watch on unknown %r", ref)
                continue
        if kind == "note":
            ref = ""
        try:
            conf = min(max(float(raw.get("confidence") or 0.0), 0.0), 1.0)
        except (TypeError, ValueError):
            conf = 0.0
        key = (kind, ref, why.lower()[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "ref": ref, "why": why, "confidence": conf})
        if len(out) >= MAX_STEPS:
            break
    return out


def expire(now=None) -> int:
    """Pending steps older than EXPIRE_DAYS are expired: an unanswered
    proposal is not a standing one."""
    from ai_agents.models import ReportNextStep
    now = now or timezone.now()
    return ReportNextStep.objects.filter(
        status=ReportNextStep.PENDING,
        created_at__lt=now - timedelta(days=EXPIRE_DAYS)
    ).update(status=ReportNextStep.EXPIRED)


def extract(report_kind: str, text: str, *, source_ref: str = "",
            now=None) -> list:
    """Read one report and propose its steps. Never raises: a reader that
    fails must not fail the report it was reading. Returns the rows made."""
    try:
        from core.platform_control import is_component_enabled
        if not is_component_enabled(COMPONENT_KEY):
            return []
        if report_kind not in REPORTS or not (text or "").strip():
            return []
        from ai_agents.models import ReportNextStep
        from instruments.models import Instrument
        from signals.rule_actuator import governed_rule_names
        now = now or timezone.now()
        expire(now)
        rules = sorted(governed_rule_names())
        symbols = list(Instrument.objects.filter(is_active=True)
                       .order_by("symbol")
                       .values_list("symbol", flat=True)[:MAX_SYMBOLS])
        result = NextStepsAgent().run(report_kind=report_kind, text=text,
                                      rules=rules, symbols=symbols)
        steps = validate(result.get("steps"), rules, symbols)
        standing = set(ReportNextStep.objects.filter(
            status=ReportNextStep.PENDING).values_list("kind", "ref"))
        made = []
        for s in steps:
            if s["kind"] != "note" and (s["kind"], s["ref"]) in standing:
                continue
            made.append(ReportNextStep.objects.create(
                report_kind=report_kind, source_ref=str(source_ref or "")[:64],
                kind=s["kind"], ref=s["ref"], why=s["why"],
                confidence=s["confidence"]))
            standing.add((s["kind"], s["ref"]))
        if made:
            _announce(report_kind, made)
        return made
    except Exception as e:  # noqa: BLE001 — the report stands
        logger.warning("[next-steps] %s: extraction failed: %s", report_kind, e)
        return []


def _announce(report_kind, made) -> None:
    from bot_program.notifications import notify_staff
    kinds = {}
    for s in made:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    words = ", ".join(f"{n} {KIND_WORDS[k]}" for k, n in kinds.items())
    try:
        notify_staff(title="Next steps proposed",
                     body=(f"{len(made)} from {REPORTS[report_kind]}: {words}. "
                           f"Nothing is applied until you approve it — open "
                           f"{PAGE_PATH}"),
                     url=PAGE_PATH, cooldown_hours=1)
    except Exception as e:  # noqa: BLE001
        logger.warning("[next-steps] could not announce: %s", e)


def pending():
    from ai_agents.models import ReportNextStep
    return (ReportNextStep.objects.filter(status=ReportNextStep.PENDING)
            .order_by("-created_at"))


def approve(step, user=None):
    """The operator's yes. A pause or a size cut becomes a RuleAction
    PROPOSAL for HQ (never applied here); a watch stars the instrument;
    a note is acknowledged."""
    from ai_agents.models import ReportNextStep
    if step.status != ReportNextStep.PENDING:
        return step
    if step.kind in ("pause_rule", "reduce_size"):
        from signals.models_control import RuleAction
        ra = RuleAction.objects.create(
            rule_name=step.ref, action=step.kind,
            state=RuleAction.STATE_PROPOSED,
            rationale=(f"Next step from {REPORTS[step.report_kind]} "
                       f"({step.created_at:%Y-%m-%d}), approved by "
                       f"{getattr(user, 'username', 'the operator')}: "
                       f"{step.why}"))
        step.rule_action = ra
    elif step.kind == "watch":
        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol=step.ref).first()
        if inst is not None and not inst.is_watchlist:
            inst.is_watchlist = True
            inst.save(update_fields=["is_watchlist"])
            try:
                from dashboard.consumers import push_watchlist_update
                push_watchlist_update(inst.symbol, True)
            except Exception as e:  # noqa: BLE001 — the star is set
                logger.debug("[next-steps] watchlist push failed: %s", e)
    step.status = ReportNextStep.APPROVED
    step.reviewed_at = timezone.now()
    step.reviewed_by = user if getattr(user, "pk", None) else None
    step.save(update_fields=["status", "reviewed_at", "reviewed_by",
                             "rule_action"])
    return step


def reject(step, user=None):
    from ai_agents.models import ReportNextStep
    if step.status != ReportNextStep.PENDING:
        return step
    step.status = ReportNextStep.REJECTED
    step.reviewed_at = timezone.now()
    step.reviewed_by = user if getattr(user, "pk", None) else None
    step.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    return step


def for_page(limit=20) -> list:
    """The pending steps as the page prints them."""
    from django.utils.timesince import timesince
    now = timezone.now()
    out = []
    for s in pending()[:limit]:
        out.append({
            "id": s.pk, "kind": s.kind, "kind_words": KIND_WORDS[s.kind],
            "ref": s.ref, "why": s.why,
            "report_words": REPORTS.get(s.report_kind, s.report_kind),
            "age_words": timesince(s.created_at, now).split(",")[0] + " ago",
            "confidence_pct": int(round((s.confidence or 0.0) * 100)),
            "consequence": {
                "pause_rule": "creates a pause proposal for HQ to apply",
                "reduce_size": "creates a size-cut proposal for HQ to apply",
                "watch": "stars the instrument",
                "note": "is acknowledged",
            }[s.kind],
        })
    return out
