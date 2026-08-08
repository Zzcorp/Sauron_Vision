"""Phase-26 track-record decay alert log.

Each row is a moment in time when a rule × asset_class combo's recent bot-
trade performance fell off vs its longer-term baseline. Used both for:
  - dedupe (don't re-alert the same decay within a cooldown window)
  - audit history (when did this rule start to break?)
  - resolution tracking (mark resolved_at when performance recovers)
"""
from django.conf import settings
from django.db import models


class RuleTrackRecordAlert(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="track_record_alerts",
    )
    rule_name = models.CharField(max_length=100, db_index=True)
    asset_class = models.CharField(max_length=12, db_index=True)

    # Snapshot of the comparison at detection time.
    recent_n = models.IntegerField(default=0)
    recent_avg_r = models.FloatField(default=0)
    recent_win_rate = models.FloatField(default=0)
    baseline_n = models.IntegerField(default=0)
    baseline_avg_r = models.FloatField(default=0)
    baseline_win_rate = models.FloatField(default=0)

    # Why the alert fired (one or more of: avg_r_drop, win_rate_drop, gone_negative).
    triggers = models.JSONField(default=list, blank=True)

    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    alerted_at = models.DateTimeField(null=True, blank=True,
        help_text="When the notification dispatch fired (None on dispatch failure).")
    resolved_at = models.DateTimeField(null=True, blank=True,
        help_text="When subsequent checks showed the rule had recovered.")

    class Meta:
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["user", "rule_name", "asset_class", "-detected_at"]),
            models.Index(fields=["resolved_at"]),
        ]

    def __str__(self):
        return (f"{self.rule_name}/{self.asset_class} "
                f"recent {self.recent_avg_r:+.2f}R vs baseline "
                f"{self.baseline_avg_r:+.2f}R "
                f"({'resolved' if self.resolved_at else 'open'})")
