"""Phase 37 — Sauron's Mind models.

Two tables that together form the central coordination layer:

  BrainObservation  — append-only event log written by agents and system
                      hooks. Cheap, sync, never blocks. The synthesizer
                      consumes batches of these every 30min to build a
                      coherent world-view.

  BrainReport       — the structured output of one synthesis run. Other
                      agents read the latest one (via
                      `brain.context.get_brain_context`) so every decision
                      shares the same regime/exposure/concern context.

Why this design:
  - Append-only: no agent writes to BrainReport directly; only the brain.
  - Structured-first: regime_label, theme_pressures, rule_overlay, concerns
    are typed JSON — downstream agents consume them programmatically.
    `narrative_md` is for humans on the dashboard.
  - Calibration-ready: each BrainReport links to AgentPredictions (Phase 6)
    for falsifiable claims. Trust score derates downstream weight.
  - Failure-safe: a missing/stale BrainReport returns None upstream, so
    every consumer must degrade gracefully.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


# ── Observation queue ─────────────────────────────────────────────────────

class BrainObservation(models.Model):
    """One typed event recorded by an agent or system hook.

    Kept intentionally permissive: `kind` is a free-form string with the
    documented kinds available as constants, so new event types don't
    require a migration.
    """

    # Documented kinds — agents may use others; these are just constants.
    KIND_GATE_REJECT = "gate_reject"
    KIND_FILL_CLOSED = "fill_closed"
    KIND_RULE_DECAYED = "rule_decayed"
    KIND_REGIME_SHIFT = "regime_shift"
    KIND_ANOMALY_DETECTED = "anomaly_detected"
    KIND_MUTATION_PROPOSED = "mutation_proposed"
    KIND_CORRELATION_SPIKE = "correlation_spike"
    KIND_NARRATIVE_CONSENSUS = "narrative_consensus"
    KIND_AUDIT_EVENT = "audit_event"

    kind = models.CharField(max_length=40, db_index=True)
    payload = models.JSONField(default=dict)
    source_agent = models.CharField(max_length=80, default="")
    instrument = models.ForeignKey(
        "instruments.Instrument", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="brain_observations",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    consumed_by_brain_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["kind", "-created_at"]),
            models.Index(fields=["consumed_by_brain_at", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"<BrainObservation {self.kind} {self.created_at:%Y-%m-%d %H:%M}>"


# ── Brain reports ─────────────────────────────────────────────────────────

class BrainReport(models.Model):
    """Structured output of one SauronMind synthesis run.

    Read by downstream agents via `brain.context.get_brain_context()`,
    which returns a compact dict of just the fields agents need so we
    don't pay token cost to inject the full narrative.
    """

    REGIME_RISK_ON = "risk_on"
    REGIME_RISK_OFF = "risk_off"
    REGIME_MEAN_REVERTING = "mean_reverting"
    REGIME_TRENDING = "trending"
    REGIME_BLOW_OFF = "blow_off"
    REGIME_UNKNOWN = "unknown"
    REGIME_CHOICES = [
        (REGIME_RISK_ON, "Risk-on"),
        (REGIME_RISK_OFF, "Risk-off"),
        (REGIME_MEAN_REVERTING, "Mean-reverting"),
        (REGIME_TRENDING, "Trending"),
        (REGIME_BLOW_OFF, "Blow-off"),
        (REGIME_UNKNOWN, "Unknown"),
    ]

    regime_label = models.CharField(max_length=20, choices=REGIME_CHOICES,
                                     default=REGIME_UNKNOWN)
    regime_confidence = models.FloatField(default=0.0)  # 0..1

    portfolio_health_score = models.FloatField(default=0.5)  # 0..1
    # JSON: list of {"kind": str, "severity": float, "ref": str, "text": str}
    top_concerns = models.JSONField(default=list)
    # JSON: {theme_name: 0..1 saturation}
    theme_pressures = models.JSONField(default=dict)
    # JSON: {rule_name: "active" | "watch" | "pause_recommended"}
    rule_status_overlay = models.JSONField(default=dict)
    # Free-form markdown for humans on the dashboard.
    narrative_md = models.TextField(blank=True)

    # Synthesis metadata.
    model_used = models.CharField(max_length=80, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    n_observations_consumed = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return (f"<BrainReport {self.regime_label}@{self.regime_confidence:.2f} "
                f"{self.created_at:%Y-%m-%d %H:%M}>")

    @property
    def is_fresh(self) -> bool:
        """True if valid_until is in the future (or unset and < 1h old)."""
        now = timezone.now()
        if self.valid_until:
            return now <= self.valid_until
        return (now - self.created_at).total_seconds() < 3600


# Phase 38 models — re-exported so makemigrations picks them up.
from .knowledge_models import (  # noqa: E402, F401
    KnowledgeNode, Hypothesis, HypothesisVote, ConsolidationRun,
)
from .briefing_models import StrategistBriefing  # noqa: E402, F401
from .generator_models import GeneratedSetupProposal  # noqa: E402, F401
from .demoter_models import RuleDemotion  # noqa: E402, F401
from .earnings_models import EarningsReview  # noqa: E402, F401
from .research_models import ResearchConversation, ResearchMessage  # noqa: E402, F401
