"""Phase-16 orchestrator audit log.

Every time the cross-asset orchestrator gate is consulted with a non-trivial
decision (a rejection, or a sampled allow when sampling is on), we drop an
`OrchestratorEvent` row so the Sauron's-Eye dashboard can replay what
happened. It's also a basic audit trail — useful when a user asks "why
didn't my bot enter that AAPL trade?"
"""
from django.conf import settings
from django.db import models


class OrchestratorEvent(models.Model):
    """One gate decision."""

    DECISION_CHOICES = [
        ("allow", "Allow"),
        ("reject", "Reject"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="orchestrator_events",
    )
    asset_class = models.CharField(max_length=12, db_index=True)
    symbol = models.CharField(max_length=40)
    side = models.CharField(max_length=4)  # BUY | SELL
    right = models.CharField(max_length=1, blank=True,
        help_text="C / P for options, blank otherwise.")
    decision = models.CharField(max_length=8, choices=DECISION_CHOICES, db_index=True)
    reason = models.CharField(max_length=300, blank=True)

    # Snapshot of theme exposure at the moment of decision.
    exposure_before = models.JSONField(default=dict, blank=True)
    exposure_after = models.JSONField(default=dict, blank=True)
    caps = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["decision", "-created_at"]),
        ]

    def __str__(self):
        return (f"{self.created_at:%Y-%m-%d %H:%M} {self.decision.upper()} "
                f"{self.asset_class}/{self.symbol} {self.side}")
