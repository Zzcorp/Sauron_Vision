"""Phase 38.1-38.2 — knowledge graph + hypothesis market models.

Two layers added on top of Phase 37's BrainObservation/BrainReport:

  KnowledgeNode    — append-only versioned typed entities. Agents enrich
                     this graph instead of pinging each other. The current
                     state of `(kind, key)` is the most recent row whose
                     `superseded_by` is NULL. History is recoverable by
                     walking versions.

  Hypothesis       — falsifiable claim with confidence. Source agent posts;
                     other agents vote (co-sign / dissent / refine); a
                     resolver grades the outcome via Phase 6 calibration.

  HypothesisVote   — typed vote by another agent on a hypothesis with
                     reasoning. Critics emit dissents; sanity confirmations
                     emit co-signs.

Why versioned: a node's history is sometimes the signal — "regime flipped
3 times in 24h" is information that matters. A simple `update()` would
hide that. Versioning keeps audit + rollback cheap.

Why decoupled from BrainReport: the knowledge graph is the SHARED layer;
BrainReport is one synthesizer's *instantaneous* read of it. Other agents
can write to the graph too (critics, mutator, decay investigator), so
graph state is wider than any single report.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


# ── Knowledge graph ───────────────────────────────────────────────────────

class KnowledgeNode(models.Model):
    """A typed, versioned entry in the shared world model.

    Lookup the *current* state with:
        KnowledgeNode.current(kind, key)

    Lookup *history* with:
        KnowledgeNode.history(kind, key)
    """

    KIND_REGIME = "regime"                  # global or per-instrument regime label
    KIND_THEME_STATE = "theme_state"        # USD_short, equity_long, etc.
    KIND_RULE_STATE = "rule_state"          # health/status of a rule
    KIND_ANOMALY = "anomaly"                # detected oddity needing attention
    KIND_NARRATIVE_THREAD = "narrative_thread"  # ongoing market narrative
    KIND_CHOICES = [
        (KIND_REGIME, "Regime"),
        (KIND_THEME_STATE, "Theme state"),
        (KIND_RULE_STATE, "Rule state"),
        (KIND_ANOMALY, "Anomaly"),
        (KIND_NARRATIVE_THREAD, "Narrative thread"),
    ]

    kind = models.CharField(max_length=40, db_index=True)
    key = models.CharField(max_length=120, db_index=True)
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField(default=dict)
    confidence = models.FloatField(default=0.5)
    source_agents = models.JSONField(default=list,
                                      help_text="Agents that contributed to this version.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supersedes",
    )

    class Meta:
        indexes = [
            models.Index(fields=["kind", "key", "-version"]),
            models.Index(fields=["kind", "key", "superseded_by"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        s = "" if self.superseded_by_id is None else " (old)"
        return f"<KnowledgeNode {self.kind}:{self.key} v{self.version}{s}>"

    @classmethod
    def current(cls, kind: str, key: str) -> "KnowledgeNode | None":
        return cls.objects.filter(kind=kind, key=key,
                                    superseded_by__isnull=True).first()

    @classmethod
    def history(cls, kind: str, key: str) -> list:
        return list(cls.objects.filter(kind=kind, key=key)
                    .order_by("version"))

    @classmethod
    def upsert(cls, *, kind: str, key: str, payload: dict,
                 confidence: float = 0.5,
                 source: str = "") -> "KnowledgeNode":
        """Create a new version. The previous current version (if any) is
        marked `superseded_by` the new one."""
        prev = cls.current(kind, key)
        version = (prev.version + 1) if prev else 1
        sources = list(prev.source_agents) if prev else []
        if source and source not in sources:
            sources.append(source)
        new = cls.objects.create(
            kind=kind, key=key, version=version,
            payload=dict(payload or {}),
            confidence=max(0.0, min(1.0, float(confidence))),
            source_agents=sources,
        )
        if prev is not None:
            prev.superseded_by = new
            prev.save(update_fields=["superseded_by"])
        return new


# ── Hypothesis market ─────────────────────────────────────────────────────

class Hypothesis(models.Model):
    """A falsifiable claim about the market or system."""

    OUTCOME_PENDING = "pending"
    OUTCOME_CONFIRMED = "confirmed"
    OUTCOME_REFUTED = "refuted"
    OUTCOME_UNRESOLVABLE = "unresolvable"
    OUTCOME_CHOICES = [
        (OUTCOME_PENDING, "Pending"),
        (OUTCOME_CONFIRMED, "Confirmed"),
        (OUTCOME_REFUTED, "Refuted"),
        (OUTCOME_UNRESOLVABLE, "Unresolvable"),
    ]

    claim_text = models.CharField(max_length=400,
                                    help_text="Human-readable claim.")
    claim_payload = models.JSONField(default=dict,
                                      help_text="Structured claim — used by resolver.")
    resolution_criteria = models.JSONField(
        default=dict, help_text="Resolver-readable spec: how to grade.")

    confidence = models.FloatField(default=0.5)
    source_agent = models.CharField(max_length=80, db_index=True)

    resolution_deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES,
                                default=OUTCOME_PENDING, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    # Optional link to the BrainReport that spawned this hypothesis.
    brain_report = models.ForeignKey(
        "brain.BrainReport", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="hypotheses",
    )
    # Optional link to the AgentPrediction this hypothesis grades into.
    agent_prediction = models.ForeignKey(
        "ai_agents.AgentPrediction", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="hypotheses",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_agent", "-created_at"]),
            models.Index(fields=["outcome", "resolution_deadline"]),
        ]

    def __str__(self) -> str:
        return f"<Hypothesis [{self.source_agent}] {self.claim_text[:60]}>"


class HypothesisVote(models.Model):
    """Another agent's stance on a hypothesis."""

    STANCE_CO_SIGN = "co_sign"
    STANCE_DISSENT = "dissent"
    STANCE_REFINE = "refine"
    STANCE_CHOICES = [
        (STANCE_CO_SIGN, "Co-sign"),
        (STANCE_DISSENT, "Dissent"),
        (STANCE_REFINE, "Refine"),
    ]

    hypothesis = models.ForeignKey(
        Hypothesis, on_delete=models.CASCADE, related_name="votes",
    )
    agent = models.CharField(max_length=80, db_index=True)
    stance = models.CharField(max_length=20, choices=STANCE_CHOICES)
    confidence = models.FloatField(default=0.5)
    reasoning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("hypothesis", "agent")]
        indexes = [
            models.Index(fields=["agent", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"<{self.agent} {self.stance} on H#{self.hypothesis_id}>"


# ── Consolidation runs ────────────────────────────────────────────────────

class ConsolidationRun(models.Model):
    """Metadata + counts from one nightly consolidation cycle."""

    n_observations_pruned = models.IntegerField(default=0)
    n_hypotheses_resolved = models.IntegerField(default=0)
    n_nodes_added = models.IntegerField(default=0)
    n_nodes_superseded = models.IntegerField(default=0)
    n_critics_invoked = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"<ConsolidationRun {self.started_at:%Y-%m-%d %H:%M}>"
