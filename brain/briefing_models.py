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
    # THE MEASURED POSTURE beside the brief's own word (2026-10-08). The
    # brief's `posture` is advice and sizes nothing; what sizes a real-money
    # order is the crisis posture (bot_program/market_stress.current() ->
    # posture.entry_posture) while the crisis_mode switch is ON. Both words
    # are stored so the title can say both ("DEFENSIVE · measured: calm")
    # and the operator never mistakes one for the other. "" on a briefing
    # written before this field. Never a bare "calm" nothing measured
    # (brain.strategist.measured_posture): "unmeasured", "stressed, 5h
    # old", "calm (override)", led by "crisis mode OFF: " while the switch
    # is off — 40 wide for the longest of them.
    measured_posture = models.CharField(max_length=40, blank=True,
                                        default="")
    measured_posture_note = models.CharField(max_length=300, blank=True,
                                             default="")
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
