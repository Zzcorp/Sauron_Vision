"""Phase-12 event-engine audit log.

`FastEvent` records every dispatched event — what came in, which rules fired,
which signals were produced. Bounded retention recommended (a daily cleanup
should prune entries older than ~30d) since streamers can produce thousands
of events per minute.
"""
from django.db import models


class FastEvent(models.Model):
    """One dispatched event in the real-time engine."""

    event_type = models.CharField(max_length=40, db_index=True,
                                   help_text="e.g. 'price_tick', 'news', 'funding_rate'")
    symbol = models.CharField(max_length=40, blank=True, db_index=True,
                               help_text="Optional — extracted from payload for display.")
    payload = models.JSONField(default=dict)

    # Dispatch outcome.
    rules_evaluated = models.IntegerField(default=0)
    rules_fired = models.IntegerField(default=0)
    fired_rule_names = models.JSONField(default=list)
    signal_ids = models.JSONField(default=list,
                                   help_text="IDs of Signal rows created from this event.")

    # Timing.
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    dispatch_ms = models.FloatField(default=0,
                                     help_text="Wall-clock time spent in dispatch_event (ms).")

    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["-received_at"]),
            models.Index(fields=["event_type", "-received_at"]),
        ]

    def __str__(self):
        return (f"FastEvent[{self.event_type} {self.symbol or ''} "
                f"fired={self.rules_fired}/{self.rules_evaluated}]")
