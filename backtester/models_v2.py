"""BacktestRunV2 with config hash for run comparison."""
import hashlib
import json
from django.db import models
from django.utils import timezone


def hash_config(cfg_dict):
    """Deterministic short hash of a config dict for run comparison."""
    blob = json.dumps(cfg_dict, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


class BacktestRunV2(models.Model):
    """A single backtest run, with config hash so identical configs collide."""

    name = models.CharField(max_length=120, blank=True)
    config_hash = models.CharField(max_length=16, db_index=True)
    config = models.JSONField(default=dict)

    symbols = models.JSONField(default=list)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    initial_capital = models.FloatField(default=10_000)
    final_capital = models.FloatField(default=0)
    total_return_pct = models.FloatField(default=0)
    max_drawdown_pct = models.FloatField(default=0)
    sharpe = models.FloatField(null=True, blank=True)
    sortino = models.FloatField(null=True, blank=True)
    calmar = models.FloatField(null=True, blank=True)
    profit_factor = models.FloatField(null=True, blank=True)
    win_rate = models.FloatField(default=0)
    n_trades = models.IntegerField(default=0)
    expectancy_r = models.FloatField(default=0)

    metrics = models.JSONField(default=dict)
    trades = models.JSONField(default=list)
    equity_curve = models.JSONField(default=list)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["config_hash", "-created_at"]),
        ]

    def __str__(self):
        return f"BT {self.config_hash} {self.total_return_pct:+.1f}% ({self.n_trades} tr)"
