"""Phase 37.3 — read-only access to the latest brain state.

Other agents call `get_brain_context()` and weave the returned dict into
their own prompts / decisions. The returned object is INTENTIONALLY small
(~10 keys, ~200 tokens worth) so injection cost stays trivial.

Every consumer must handle `None` — the brain may have failed, or the
report may be stale. No fresh report → agents work as today.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


def get_brain_context(*, max_age_minutes: int = 45) -> Optional[dict]:
    """Return a compact dict from the latest fresh BrainReport.

    Shape:
      {
        "regime_label": str,
        "regime_confidence": float,
        "portfolio_health_score": float,
        "top_concerns": [{"kind","severity","ref","text"}],   # up to 3
        "theme_pressures": {theme_name: float},               # at most 5 highest
        "rule_status_overlay": {rule_name: status},           # only non-active
        "as_of_iso": str,
        "trust_score": float | None,                          # Phase-6 derived
      }
    Returns None if no recent report exists or DB is down.
    """
    try:
        from .models import BrainReport
    except Exception:
        return None

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

    return {
        "regime_label": report.regime_label,
        "regime_confidence": round(report.regime_confidence, 4),
        "portfolio_health_score": round(report.portfolio_health_score, 4),
        "top_concerns": concerns,
        "theme_pressures": pressures_dict,
        "rule_status_overlay": overlay,
        "as_of_iso": report.created_at.isoformat(),
        "trust_score": _brain_trust_score(),
    }


def _brain_trust_score() -> Optional[float]:
    """Returns the rolling Brier-derived trust score for the brain agent
    (from Phase-6 calibration). None if calibration data unavailable."""
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


def brain_rule_advisory(rule_name: str) -> tuple[str, str]:
    """Return (status, reason) for a rule based on brain state.

    Status is one of:
      - "allow"               — no advisory; act normally
      - "watch"               — proceed but be conservative
      - "pause_recommended"   — strong soft-pause advice from brain

    Resolution order (most authoritative first):
      1. KnowledgeNode `rule_state:<name>` (consolidation-promoted, persistent)
      2. BrainReport.rule_status_overlay[<name>] (latest, recency-weighted)
      3. otherwise → "allow"

    Phase-47: when the brain's trust band is "low", `pause_recommended`
    is downgraded to `watch` — a low-trust brain shouldn't have full
    actuation power. KnowledgeNode-sourced advisories are NOT softened
    because they came from consolidation (multi-source agreement).

    Always returns gracefully — DB / brain-down → "allow".
    """
    if not rule_name:
        return "allow", ""
    try:
        from .knowledge_models import KnowledgeNode
        node = KnowledgeNode.current(KnowledgeNode.KIND_RULE_STATE, rule_name)
        if node is not None:
            status = (node.payload or {}).get("status", "allow")
            if status in ("watch", "pause_recommended"):
                return status, f"knowledge_graph rule_state v{node.version}"
    except Exception:
        pass

    ctx = get_brain_context()
    if ctx and rule_name in (ctx.get("rule_status_overlay") or {}):
        status = ctx["rule_status_overlay"][rule_name]
        if status not in ("watch", "pause_recommended"):
            return "allow", ""
        # Phase-47 — low-trust brain can't hard-pause via report-only signal.
        band = brain_trust_band(ctx.get("trust_score"))
        if band == "low" and status == "pause_recommended":
            return "watch", (f"brain_report softened (trust=low, "
                              f"regime={ctx.get('regime_label')})")
        return status, f"brain_report (regime={ctx.get('regime_label')})"
    return "allow", ""


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
    if ctx["rule_status_overlay"]:
        rules = ", ".join(f"{k}: {v}" for k, v in ctx["rule_status_overlay"].items())
        lines.append(f"- Rule overlay (exceptions): {rules}")
    if ctx["top_concerns"]:
        lines.append("- Top concerns:")
        for c in ctx["top_concerns"]:
            lines.append(f"    - [{c.get('kind','')}] {c.get('text','')}")
    return "\n".join(lines)
