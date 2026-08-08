"""Phase-28 append-only, hash-chained audit log.

Every critical trading decision (trade open, trade close, gate reject) is
recorded here as an immutable row. Each row carries:

  prev_hash    = the previous row's payload_hash  (genesis = '0'*64)
  payload_hash = sha256(prev_hash || kind || canonical(data))

Mutating an old row breaks the chain — any subsequent verify call exposes
the tamper. Useful for regulatory audit trails and incident forensics.

In-Python enforcement:
  - `save()` refuses to update an existing row (`pk is not None` raises)
  - `delete()` raises

Production deployments should ALSO add a database-level write-only role and
DDL triggers to prevent admin-side tampering. The Python layer alone protects
against accidents, not against motivated bad actors with DB credentials.
"""
from django.conf import settings
from django.db import IntegrityError, models


GENESIS_HASH = "0" * 64


class AuditLogEntry(models.Model):
    """One immutable audit row."""

    KIND_CHOICES = [
        ("trade_open", "Trade Opened"),
        ("trade_close", "Trade Closed"),
        ("gate_reject", "Orchestrator Reject"),
        ("rule_action", "Rule Control Action"),
        ("promotion", "Stage Promotion"),
        ("admin_action", "Admin Action"),
        ("system", "System Event"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_log_entries",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    data = models.JSONField(default=dict, blank=True)
    prev_hash = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"#{self.id} {self.created_at:%Y-%m-%d %H:%M:%S} {self.kind}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise IntegrityError(
                "AuditLogEntry rows are immutable; create a new row instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise IntegrityError("AuditLogEntry rows cannot be deleted.")
