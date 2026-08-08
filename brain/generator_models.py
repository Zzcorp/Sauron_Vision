"""Phase 41 — GeneratedSetupProposal model.

Stores autonomous strategy proposals from the StrategyGeneratorAgent. Every
proposal goes through three states:

  pending  → just created, awaiting admin review
  approved → admin clicked "approve" — the linked OpportunitySetup gets
             flipped to is_active=True; RuleControl moves through the
             promotion ladder normally
  rejected → admin clicked "reject" — the linked OpportunitySetup stays
             is_active=False (effectively dormant)

Why we keep BOTH the proposal row AND a draft OpportunitySetup at
is_active=False: the OpportunitySetup is the canonical schema the rest of
the platform consumes (scanner, dashboards, RuleControl, promotion). The
proposal is the audit + review layer on top.
"""
from __future__ import annotations

from django.db import models


class GeneratedSetupProposal(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED, "Expired"),
    ]

    proposed_name = models.CharField(max_length=120, db_index=True)
    rationale_md = models.TextField(blank=True,
                                     help_text="Markdown rationale from the generator agent.")
    inspiration_summary = models.CharField(
        max_length=300, blank=True,
        help_text="What in the graph/track-record inspired this proposal.")
    direction = models.CharField(max_length=10, default="bullish")
    asset_classes = models.JSONField(default=list)
    conditions = models.JSONField(default=list)
    min_match_score = models.FloatField(default=0.6)
    suggested_horizon_days = models.IntegerField(default=5)
    sizing = models.JSONField(default=dict)
    confidence = models.FloatField(default=0.5)

    # Linked draft setup (created in is_active=False state) + RuleControl.
    setup = models.ForeignKey(
        "signals.OpportunitySetup", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="generation_proposals",
    )
    rule_control = models.ForeignKey(
        "signals.RuleControl", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="generation_proposals",
    )
    hypothesis = models.ForeignKey(
        "brain.Hypothesis", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="generation_proposals",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                default=STATUS_PENDING, db_index=True)
    reviewed_by = models.CharField(max_length=80, blank=True,
                                     help_text="Username of admin who decided.")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    # Generation metadata.
    model_used = models.CharField(max_length=80, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"<GeneratedSetupProposal {self.proposed_name} [{self.status}]>"
