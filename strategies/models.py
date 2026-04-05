"""Strategy models — complete trading plans beyond signals."""
from django.db import models
from instruments.models import Instrument
from signals.models import Signal


class Strategy(models.Model):
    STATUS_CHOICES = [
        ("proposed", "Proposed"),
        ("approved", "Approved"),
        ("active", "Active"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("rejected", "Rejected"),
    ]

    HORIZON_CHOICES = [
        ("scalp", "Scalp (minutes-hours)"),
        ("intraday", "Intraday"),
        ("swing", "Swing (days-weeks)"),
        ("position", "Position (weeks-months)"),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField()
    time_horizon = models.CharField(max_length=20, choices=HORIZON_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="proposed")

    source_signals = models.ManyToManyField(Signal, blank=True, related_name="strategies")
    ai_reasoning = models.TextField(blank=True)

    instruments = models.ManyToManyField(Instrument, through="StrategyLeg")

    max_portfolio_allocation_pct = models.FloatField(default=10.0)
    max_loss_pct = models.FloatField(default=2.0)
    correlation_constraint = models.TextField(blank=True)

    pnl = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    pnl_pct = models.FloatField(default=0)
    max_drawdown = models.FloatField(default=0)
    sharpe_ratio = models.FloatField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True)

    class Meta:
        verbose_name_plural = "strategies"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.status.upper()}] {self.name}"


class StrategyLeg(models.Model):
    ACTION_CHOICES = [
        ("long", "Long"),
        ("short", "Short"),
        ("hedge", "Hedge"),
    ]

    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="legs")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    weight = models.FloatField(default=1.0)

    entry_price = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    stop_loss = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    take_profit = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    current_price = models.DecimalField(max_digits=20, decimal_places=8, null=True)

    entry_conditions = models.JSONField(default=dict)
    exit_conditions = models.JSONField(default=dict)
    is_entered = models.BooleanField(default=False)
    entered_at = models.DateTimeField(null=True)

    def __str__(self):
        return f"{self.action.upper()} {self.instrument.symbol} ({self.weight:.0%})"


class StrategyAdjustment(models.Model):
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="adjustments")
    timestamp = models.DateTimeField(auto_now_add=True)
    adjustment_type = models.CharField(max_length=50)
    reason = models.TextField()
    details = models.JSONField(default=dict)
    applied = models.BooleanField(default=False)
    applied_by = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["-timestamp"]
