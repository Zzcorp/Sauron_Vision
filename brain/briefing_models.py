"""Phase 40 — StrategistBriefing model."""
from __future__ import annotations

from django.db import models


class StrategistBriefing(models.Model):
    POSTURE_CHOICES = [
        ("defensive", "Defensive"),
        ("balanced", "Balanced"),
        ("aggressive", "Aggressive"),
    ]

    outlook_md = models.TextField(blank=True)
    posture = models.CharField(max_length=20, choices=POSTURE_CHOICES,
                                default="balanced")
    posture_rationale = models.CharField(max_length=500, blank=True)
    watchlist = models.JSONField(default=list)
    ideas = models.JSONField(default=list)

    model_used = models.CharField(max_length=80, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return f"<StrategistBriefing {self.posture} {self.created_at:%Y-%m-%d}>"
