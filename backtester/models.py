"""Backtesting models — store test results."""
from django.db import models
from django.contrib.auth.models import User


class BacktestRun(models.Model):
    """A single backtest execution."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="backtests")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Configuration
    strategy_type = models.CharField(max_length=50)  # "rsi_oversold", "macd_cross", etc.
    parameters = models.JSONField(default=dict)  # Strategy parameters
    symbols = models.JSONField(default=list)  # List of symbols tested
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2, default=10000)

    # Results
    final_value = models.DecimalField(max_digits=20, decimal_places=2, null=True)
    total_return_pct = models.FloatField(null=True)
    max_drawdown_pct = models.FloatField(null=True)
    sharpe_ratio = models.FloatField(null=True)
    win_rate = models.FloatField(null=True)
    total_trades = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    avg_win_pct = models.FloatField(null=True)
    avg_loss_pct = models.FloatField(null=True)
    profit_factor = models.FloatField(null=True)

    # Equity curve (JSON array of {date, value})
    equity_curve = models.JSONField(default=list)
    trades_log = models.JSONField(default=list)  # [{date, symbol, action, price, pnl}]

    status = models.CharField(max_length=20, default="pending")  # pending, running, completed, failed
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.status}] {self.name} — {self.total_return_pct or 0:.1f}%"
