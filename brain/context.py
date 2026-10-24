"""Phase 37.3 — read-only access to the latest brain state.

Other agents call `get_brain_context()` and weave the returned dict into
their own prompts / decisions. The returned object is INTENTIONALLY small
(~10 keys, ~200 tokens worth) so injection cost stays trivial.

Every consumer must handle `None` — the brain may have failed, or the
report may be stale. No fresh report → agents work as today.

THE MIND'S CONTRACT (2026-10-24). "The Mind says X about rule R" means
exactly this, wherever it is read:

1. The report. The newest error-free BrainReport younger than
   `mind_fresh_minutes()` (the synthesis beat's widest gap plus
   MIND_GRACE_MINUTES: 75 minutes on the hourly beat) is the Mind's
   current word. A "low" trust band softens its pause to watch.
2. The memory. The current `rule_state` KnowledgeNode is the Mind's
   memory of a pause or a watch (brain/consolidation.py). Written by the
   consolidation from a fresh report (the scheduled 03:00 pass, or the
   staff "Run consolidation now" button, which only adds and
   re-affirms); when no report is fresh, from the Mind's last report of
   the past day, adding or tightening only; and by a superuser's clear.
   It binds until it is released, and only these release it, each one a
   written version with an audit row and a staff notice: the scheduled
   pass seeing "active", or "watch" for a paused rule, in a fresh report;
   the scheduled pass seeing three fresh reports on three nights in a row
   (one miss a night, once per report) that no longer name the rule; a
   superuser's clear with the trading PIN on /knowledge/. A releasing pass
   runs at most once in 20 hours: any other run (the staff button, the
   admin's "Run selected tasks") never releases or counts. A night with no
   fresh report releases nothing, and the reader never ages a node out on
   its own: a Mind that is down keeps its pauses. The node is not softened
   by trust.
3. Both. When the node and a fresh report both speak, the stricter one
   wins (allow < watch < pause_recommended), the node on a tie. So a fresh
   "active" does not release a node's pause before the next scheduled
   pass, up to a day later: conservative on purpose.
4. Failure. Each source is read on its own; a read that fails says
   "allow" for that source alone, and nothing here ever raises.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

#: What each venue a concern or an overlay entry names is (2026-10-15).
VENUE_LEGEND_LINE = ("Venues: live = real money, demo = eToro virtual "
                     "account, paper = platform simulator; a paper or demo "
                     "loss is never a live failure")

#: The Mind's beat entry (config/celery.py) and the grace past its widest
#: gap during which its last report is still its word (2026-10-24).
MIND_BEAT_KEY = "sauron-mind-synthesize"
MIND_GRACE_MINUTES = 15
_FALLBACK_BEAT_MINUTES = 60


def mind_fresh_minutes() -> int:
    """How long a clean BrainReport stays the Mind's current word: the
    beat's widest gap, read from the loaded Celery app the way the
    component digest reads it (core.day_of_sauron.widest_gap), plus
    MIND_GRACE_MINUTES. 75 on today's hourly beat. An unreadable beat, or
    one with no period, counts as an hour. Not cached: two dict reads.

    The window used to be a literal 45 in two places, left from a
    30-minute cadence, so from minute 45 until the next report landed a
    live-evidence pause stopped blocking bot entries."""
    beat_minutes = _FALLBACK_BEAT_MINUTES
    try:
        from config.celery import app
        from core.day_of_sauron import widest_gap
        seconds = widest_gap(app.conf.beat_schedule[MIND_BEAT_KEY]["schedule"])
        if seconds is not None and seconds > 0:
            beat_minutes = int(math.ceil(float(seconds) / 60.0))
    except Exception:  # noqa: BLE001 — an unreadable beat is an hour
        beat_minutes = _FALLBACK_BEAT_MINUTES
    return beat_minutes + MIND_GRACE_MINUTES


def get_brain_context(*, max_age_minutes: Optional[int] = None) -> Optional[dict]:
    """Return a compact dict from the latest fresh BrainReport.

    Fresh means younger than `max_age_minutes`; None (the default) is the
    contract's window, `mind_fresh_minutes()`. A caller that passes its own
    window keeps it (the share allocator's regime read, the horizon).

    Shape:
      {
        "regime_label": str,
        "regime_confidence": float,
        "portfolio_health_score": float,
        "top_concerns": [{"kind","severity","ref","text"}],   # up to 3
        "theme_pressures": {theme_name: float},               # at most 5 highest
        "rule_status_overlay": {rule_name: status},           # only non-active
        "rule_status_venue": {rule_name: venue},              # its evidence's
        "as_of_iso": str,
        "trust_score": float | None,                          # Phase-6 derived
      }
    Returns None if no recent report exists or DB is down.
    """
    try:
        from .models import BrainReport
    except Exception:
        return None

    if max_age_minutes is None:
        max_age_minutes = mind_fresh_minutes()
    cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
    report = (BrainReport.objects.filter(created_at__gte=cutoff, error="")
              .order_by("-created_at").first())
    if report is None:
        return None

    # Top 3 concerns by severity.
    concerns = sorted(
        [c for c in (report.top_concerns or []) if isinstance(c, dict)],
        key=lambda c: float(c.get("severity") or 0), reverse=True,
    )[:3]

    # Top 5 themes by pressure.
    pressures = sorted(
        [(k, float(v)) for k, v in (report.theme_pressures or {}).items()],
        key=lambda kv: kv[1], reverse=True,
    )[:5]
    pressures_dict = {k: round(v, 4) for k, v in pressures}

    # Only show overlay for non-active rules — agents only care about exceptions.
    overlay = {
        k: v for k, v in (report.rule_status_overlay or {}).items()
        if v in ("watch", "pause_recommended")
    }
    # the venue each entry's evidence rests on (2026-10-15)
    venues = getattr(report, "rule_status_venue", None) or {}
    overlay_venue = {k: str(venues.get(k) or "") for k in overlay
                     if isinstance(venues, dict)}

    return {
        "regime_label": report.regime_label,
        "regime_confidence": round(report.regime_confidence, 4),
        "portfolio_health_score": round(report.portfolio_health_score, 4),
        "top_concerns": concerns,
        "theme_pressures": pressures_dict,
        "rule_status_overlay": overlay,
        "rule_status_venue": overlay_venue,
        "as_of_iso": report.created_at.isoformat(),
        "trust_score": _brain_trust_score(),
    }


def _brain_trust_score() -> Optional[float]:
    """Returns the rolling Brier-derived trust score for the brain agent
    (from Phase-6 calibration). None if calibration data unavailable.

    THE NUMBER THE BOTS ACT ON (2026-10-24): its band softens a report
    pause (brain_rule_advisory, so the bot entry gate in
    bot_program/asset_engine/base.py and the review trigger on open
    positions in brain/position_review.py), scales the theme squeeze
    (brain_theme_pressure_multiplier: the orchestrator caps and the share
    allocator), sets the share allocator's risk-off cut and the prompt
    block (context_for_prompt). Each row has one grader (brain/
    calibration.py's module docstring), so over linked rows it equals the
    briefing's brain.hypotheses.agent_trust_score("sauron_mind")."""
    try:
        from ai_agents.models import AgentPrediction
    except Exception:
        return None
    try:
        recent = AgentPrediction.objects.filter(
            agent="sauron_mind", was_correct__isnull=False,
        ).order_by("-evaluated_at")[:50]
        rows = list(recent.values("was_correct", "confidence"))
        if not rows:
            return None
        # Brier proxy: mean( (confidence - was_correct)^2 ) → invert to "trust".
        s = 0.0
        for r in rows:
            outcome = 1.0 if r["was_correct"] else 0.0
            conf = float(r["confidence"] or 0.5)
            s += (conf - outcome) ** 2
        brier = s / len(rows)
        return round(max(0.0, 1.0 - 2 * brier), 4)  # roughly 1.0 = perfect
    except Exception:
        return None


# ── Phase 47 — trust-band-aware actuation ───────────────────────────────

# When the brain is uncalibrated or wrong, downstream consumers should
# weigh its outputs less. We expose three simple bands so consumers don't
# have to reinvent thresholds.
TRUST_BAND_HIGH = 0.6
TRUST_BAND_LOW = 0.4


def brain_trust_band(score=None) -> str:
    """Return 'high' | 'medium' | 'low' | 'unknown' for a given trust score.

    Resolution: pass `score` explicitly to skip the DB lookup. None → uses
    `_brain_trust_score()`. None-after-resolve → 'unknown' (calibration
    is bootstrapping; treat as neutral).
    """
    if score is None:
        score = _brain_trust_score()
    if score is None:
        return "unknown"
    if score >= TRUST_BAND_HIGH:
        return "high"
    if score >= TRUST_BAND_LOW:
        return "medium"
    return "low"


#: allow < watch < pause_recommended: the order "the stricter one wins"
#: reads (2026-10-24). Anything else is allow.
STATUS_RANK = {"allow": 0, "watch": 1, "pause_recommended": 2}
BINDING_STATUSES = ("watch", "pause_recommended")

#: What each status does to a bot entry (bot_program/asset_engine/base.py
#: skips on pause_recommended alone, on every config, paper and live).
EFFECT_WORDS = {
    "pause_recommended": "blocks bot entries (paper and live)",
    "watch": "watch only (blocks nothing)",
    "allow": "allow",
}


def _rank(status) -> int:
    return STATUS_RANK.get(str(status or ""), 0)


def _parse_iso(value):
    """An aware datetime from an ISO string, or None."""
    from datetime import datetime, timezone as dt_timezone
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def rule_state_view(node, *, now=None) -> dict:
    """What one rule_state node says and does, for the readers, the
    /knowledge/ page and `manage.py mind_contract` alike.

    {status, effect, reason, version, affirmed_at, age_hours, misses,
     venue, source}: `affirmed_at` is the last fresh report that named the
    rule at this status (the payload's, else the version's own time), and
    `misses` how many scheduled passes in a row have since seen a fresh
    report that no longer names it (the third releases it,
    brain/consolidation.py). A node never ages out here: the release is a
    written version, or nothing."""
    from .consolidation import RELEASE_AFTER_MISSES
    now = now or timezone.now()
    payload = getattr(node, "payload", None) or {}
    if not isinstance(payload, dict):
        payload = {}
    status = str(payload.get("status") or "allow")
    if status not in STATUS_RANK:
        status = "allow"
    affirmed = (_parse_iso(payload.get("affirmed_at"))
                or _parse_iso(payload.get("as_of"))
                or getattr(node, "created_at", None))
    age_hours = (round((now - affirmed).total_seconds() / 3600.0, 1)
                 if affirmed else None)
    try:
        misses = max(0, int(payload.get("misses") or 0))
    except (TypeError, ValueError):
        misses = 0
    return {
        "status": status,
        "effect": EFFECT_WORDS[status],
        "reason": f"knowledge_graph rule_state v{getattr(node, 'version', '?')}",
        "version": getattr(node, "version", None),
        "affirmed_at": affirmed,
        "age_hours": age_hours,
        "misses": misses,
        "misses_to_release": RELEASE_AFTER_MISSES,
        "venue": str(payload.get("venue") or ""),
        "source": ", ".join(getattr(node, "source_agents", None) or []),
    }


def _node_advisory(rule_name: str) -> tuple[str, str]:
    """The memory's word: the current rule_state node, at any age."""
    from .knowledge_models import KnowledgeNode
    node = KnowledgeNode.current(KnowledgeNode.KIND_RULE_STATE, rule_name)
    if node is None:
        return "allow", ""
    view = rule_state_view(node)
    if view["status"] not in BINDING_STATUSES:
        return "allow", ""
    return view["status"], view["reason"]


def _report_advisory(rule_name: str, ctx) -> tuple[str, str]:
    """The report's word: the fresh report's overlay entry for the rule,
    a pause softened to watch when the trust band is low (Phase-47 — a
    low-trust brain can't hard-pause via a report-only signal)."""
    if not ctx or rule_name not in (ctx.get("rule_status_overlay") or {}):
        return "allow", ""
    status = ctx["rule_status_overlay"][rule_name]
    if status not in BINDING_STATUSES:
        return "allow", ""
    band = brain_trust_band(ctx.get("trust_score"))
    if band == "low" and status == "pause_recommended":
        return "watch", (f"brain_report softened (trust=low, "
                          f"regime={ctx.get('regime_label')})")
    return status, f"brain_report (regime={ctx.get('regime_label')})"


def brain_rule_advisory(rule_name: str) -> tuple[str, str]:
    """Return (status, reason) for a rule based on brain state.

    Status is one of:
      - "allow"               — no advisory; act normally
      - "watch"               — proceed but be conservative
      - "pause_recommended"   — strong soft-pause advice from brain

    The two sources (the module docstring is the contract):
      1. the KnowledgeNode `rule_state:<name>`: the nightly copy of a
         fresh report's word, kept until a written release; never
         softened by trust;
      2. the fresh BrainReport's overlay entry, its pause softened to
         watch when the trust band is "low".
    The stricter one wins (allow < watch < pause_recommended), the node on
    a tie; when both pause, the reason names both, so clearing the node
    is not mistaken for a release while the report still pauses.

    Always returns gracefully: each source read in its own fence, a
    failed read is that source's "allow", DB / brain down → "allow".
    """
    if not rule_name:
        return "allow", ""
    node = ("allow", "")
    try:
        node = _node_advisory(rule_name)
    except Exception:  # noqa: BLE001 — the memory unreadable: the report decides
        node = ("allow", "")
    report = ("allow", "")
    try:
        report = _report_advisory(rule_name, get_brain_context())
    except Exception:  # noqa: BLE001 — the report unreadable: the node decides
        report = ("allow", "")
    if _rank(report[0]) > _rank(node[0]):
        return report
    if node[0] == "allow":
        return "allow", ""
    if node[0] == report[0] == "pause_recommended":
        return node[0], f"{node[1]}; also {report[1]}"
    return node


def brain_theme_pressure_multiplier(theme: str, *, max_squeeze: float = 0.5) -> float:
    """Return a 0..1 multiplier on a theme cap given brain pressure.

    pressure=0   → 1.0 (full cap)
    pressure=1.0 → (1 - max_squeeze × trust_factor) (cap squeezed)

    Phase-47: max_squeeze is itself scaled by brain trust:
      band=high     → factor 1.0 (full power)
      band=medium   → factor 0.6
      band=low      → factor 0.2 (brain barely tightens the cap)
      band=unknown  → factor 1.0 (calibration bootstrap; default trust)

    No brain context → 1.0 (no change).
    """
    ctx = get_brain_context()
    if not ctx:
        return 1.0
    pressures = ctx.get("theme_pressures") or {}
    p = float(pressures.get(theme, 0.0) or 0.0)
    p = max(0.0, min(1.0, p))

    band = brain_trust_band(ctx.get("trust_score"))
    trust_factor = {
        "high": 1.0, "unknown": 1.0,
        "medium": 0.6, "low": 0.2,
    }.get(band, 1.0)

    return round(1.0 - p * max_squeeze * trust_factor, 4)


def context_for_prompt() -> str:
    """Render the brain context as a markdown block to inject into other
    agents' user prompts.

    Phase-47: output adapts to the brain's trust band:
      - high (≥0.6) or unknown — full block, present as authoritative
      - medium (0.4-0.6)       — full block prefixed with "preliminary read"
      - low (<0.4)             — minimal block + explicit "low-trust signal"
                                  warning so downstream agents don't
                                  over-weight a brain that's been wrong

    Returns empty string when no fresh report.
    """
    ctx = get_brain_context()
    if not ctx:
        return ""

    band = brain_trust_band(ctx.get("trust_score"))
    trust_str = (f"{ctx.get('trust_score'):.2f}"
                  if ctx.get("trust_score") is not None else "n/a")

    # ── Low-trust path: heavily softened block ─────────────────────
    if band == "low":
        return (
            "## Sauron's Mind context (LOW-TRUST signal)\n"
            f"- Regime: {ctx['regime_label']} (confidence "
            f"{ctx['regime_confidence']:.2f})\n"
            f"- ▲ Brain trust score is {trust_str} — calibration is poor "
            "lately. Use this only as a weak prior; do NOT let it "
            "override your direct evidence."
        )

    # ── High / medium / unknown ────────────────────────────────────
    header = "## Sauron's Mind context (latest synthesis)"
    if band == "medium":
        header = ("## Sauron's Mind context (preliminary read — "
                   f"trust {trust_str})")
    lines = [
        header,
        f"- Regime: **{ctx['regime_label']}** "
        f"(confidence {ctx['regime_confidence']:.2f}, "
        f"trust {trust_str})",
        f"- Portfolio health: {ctx['portfolio_health_score']:.2f}",
    ]
    if ctx["theme_pressures"]:
        pressures = ", ".join(f"{k}={v:.2f}" for k, v in ctx["theme_pressures"].items())
        lines.append(f"- Theme pressures: {pressures}")
    # THE VENUE TRAVELS WITH EVERY NUMBER (2026-10-15). This block reaches
    # the trade debate that gates live entries, pretrade_sanity, the
    # mutator and the decay investigator; a concern's R with no venue on it
    # read a paper -8.12R as a live failure.
    venues = ctx.get("rule_status_venue") or {}
    if ctx["rule_status_overlay"]:
        rules = ", ".join(
            f"{k}: {v}" + (f" ({venues[k]})" if venues.get(k) else "")
            for k, v in ctx["rule_status_overlay"].items())
        lines.append(f"- Rule overlay (exceptions): {rules}")
    if ctx["top_concerns"]:
        lines.append("- Top concerns:")
        for c in ctx["top_concerns"]:
            venue = f" / {c['venue']}" if c.get("venue") else ""
            lines.append(f"    - [{c.get('kind','')}{venue}] "
                         f"{c.get('text','')}")
    if ctx["top_concerns"] or ctx["rule_status_overlay"]:
        lines.append(f"- {VENUE_LEGEND_LINE}")
    return "\n".join(lines)
