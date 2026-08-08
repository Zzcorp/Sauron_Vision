"""Phase-18 BotBacktestRun model — persists each backtest invocation.

Stores params, summary stats, and a serialised trades list as JSON so the
dashboard can render historical runs without re-simulating.
"""
from django.conf import settings
from django.db import models


class BotBacktestRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("complete", "Complete"),
        ("error", "Error"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="bot_backtest_runs",
    )
    # Nullable so deleting a config doesn't cascade-delete runs.
    config = models.ForeignKey(
        "bot_program.AssetBotConfig",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="backtest_runs",
    )
    config_name_snapshot = models.CharField(max_length=80, blank=True,
        help_text="Captured at run time so the run shows context even after config delete.")
    asset_class_snapshot = models.CharField(max_length=12, blank=True)

    params = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    trades_json = models.JSONField(default=list, blank=True,
        help_text="Serialised list of BacktestTrade dicts.")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending", db_index=True)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (f"Backtest {self.id} · {self.config_name_snapshot} · "
                f"{self.status} · {self.created_at:%Y-%m-%d %H:%M}")
