"""Signal models — detected trading opportunities."""
from django.db import models
from instruments.models import Instrument
from core.constants import Direction, Urgency


class Signal(models.Model):
    SIGNAL_TYPES = [
        ("technical", "Technical"),
        ("fundamental", "Fundamental"),
        ("sentiment", "Sentiment"),
        ("macro", "Macro"),
        ("flow", "Institutional Flow"),
        ("ai_generated", "AI Generated"),
        ("composite", "Composite"),
    ]

    OUTCOME_CHOICES = [
        ("hit_target", "Hit Target"),
        ("stopped_out", "Stopped Out"),
        ("expired", "Expired"),
        ("manual_close", "Manually Closed"),
    ]

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="signals")
    signal_type = models.CharField(max_length=20, choices=SIGNAL_TYPES)
    direction = models.CharField(max_length=10, choices=Direction.CHOICES)
    urgency = models.CharField(max_length=10, choices=Urgency.CHOICES)

    title = models.CharField(max_length=300)
    description = models.TextField()
    rule_name = models.CharField(max_length=100)

    score = models.FloatField()
    sub_scores = models.JSONField(default=dict)

    price_at_signal = models.DecimalField(max_digits=20, decimal_places=8)
    suggested_entry = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    suggested_stop = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    suggested_target = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    risk_reward_ratio = models.FloatField(null=True)

    portfolio_impact = models.TextField(blank=True)
    conflicts_with = models.ManyToManyField("self", blank=True, symmetrical=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expired_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["instrument", "is_active"]),
        ]

    def __str__(self):
        return f"[{self.direction.upper()}] {self.title} (score: {self.score:.2f})"
