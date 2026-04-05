from django.contrib import admin
from .models import Strategy, StrategyLeg, StrategyAdjustment


class StrategyLegInline(admin.TabularInline):
    model = StrategyLeg
    extra = 0


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "time_horizon", "pnl", "pnl_pct", "created_at"]
    list_filter = ["status", "time_horizon"]
    inlines = [StrategyLegInline]
