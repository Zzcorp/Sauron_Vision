"""Phase 42 — RuleDemotion audit model.

When the auto-demoter kills a generated rule, it stamps a RuleDemotion row
so we have a permanent record of why and when. Useful for:
  - Calibrating the kill criteria (false positives = good rules killed)
  - Computing the generator's effective trust score (proposals that survive
    vs proposals that get demoted within N days)
  - Letting an admin restore a demoted rule if they disagree
"""
from __future__ import annotations

from django.db import models


class RuleDemotion(models.Model):
    CRITERION_HYPOTHESIS_REFUTED = "hypothesis_refuted"
    CRITERION_SUSTAINED_NEGATIVE = "sustained_negative"
    CRITERION_CONSECUTIVE_LOSSES = "consecutive_losses"
    CRITERION_MANUAL = "manual"
    CRITERION_CHOICES = [
        (CRITERION_HYPOTHESIS_REFUTED, "Hypothesis refuted"),
        (CRITERION_SUSTAINED_NEGATIVE, "Sustained negative avg_r"),
        (CRITERION_CONSECUTIVE_LOSSES, "Consecutive losses"),
        (CRITERION_MANUAL, "Manual"),
    ]

    rule_name = models.CharField(max_length=120, db_index=True)
    criterion = models.CharField(max_length=40, choices=CRITERION_CHOICES)
    notes = models.TextField(blank=True)

    # Snapshot of the metrics at demotion time — for forensics.
    metrics = models.JSONField(default=dict)

    demoted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    restored_at = models.DateTimeField(null=True, blank=True,
                                        help_text="If admin re-enabled the rule.")
    restored_by = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-demoted_at"]
        indexes = [
            models.Index(fields=["rule_name", "-demoted_at"]),
            models.Index(fields=["restored_at", "-demoted_at"]),
        ]

    def __str__(self) -> str:
        s = " (restored)" if self.restored_at else ""
        return f"<RuleDemotion {self.rule_name} [{self.criterion}]{s}>"
