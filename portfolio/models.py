"""Portfolio tracking models."""
from django.db import models
from instruments.models import Instrument
from strategies.models import Strategy


class Portfolio(models.Model):
    name = models.CharField(max_length=100, default="Main")
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2)
    current_value = models.DecimalField(max_digits=20, decimal_places=2)
    cash_available = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=10, default="EUR")

    max_total_exposure_pct = models.FloatField(default=100)
    max_single_position_pct = models.FloatField(default=10)
    max_sector_exposure_pct = models.FloatField(default=30)
    max_correlation_threshold = models.FloatField(default=0.7)
    max_daily_loss_pct = models.FloatField(default=3.0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.currency} {self.current_value})"


class Position(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="positions")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    strategy = models.ForeignKey(Strategy, on_delete=models.SET_NULL, null=True, blank=True, related_name="positions")

    direction = models.CharField(max_length=10)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    entry_price = models.DecimalField(max_digits=20, decimal_places=8)
    current_price = models.DecimalField(max_digits=20, decimal_places=8)
    stop_loss = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    take_profit = models.DecimalField(max_digits=20, decimal_places=8, null=True)

    unrealized_pnl = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    unrealized_pnl_pct = models.FloatField(default=0)

    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-opened_at"]


class PortfolioSnapshot(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField()
    total_value = models.DecimalField(max_digits=20, decimal_places=2)
    cash = models.DecimalField(max_digits=20, decimal_places=2)
    daily_pnl = models.DecimalField(max_digits=20, decimal_places=2)
    daily_pnl_pct = models.FloatField()
    cumulative_pnl_pct = models.FloatField()
    max_drawdown = models.FloatField()
    sharpe_ratio = models.FloatField(null=True)

    exposure_by_asset_class = models.JSONField(default=dict)
    exposure_by_sector = models.JSONField(default=dict)
    exposure_by_currency = models.JSONField(default=dict)
    correlation_matrix = models.JSONField(default=dict)

    class Meta:
        unique_together = ["portfolio", "date"]
        ordering = ["-date"]
