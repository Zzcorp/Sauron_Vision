from django.contrib import admin
from .models import BacktestRun

@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ["name", "strategy_type", "status", "total_return_pct", "sharpe_ratio", "win_rate", "total_trades", "created_at"]
    list_filter = ["status", "strategy_type"]
