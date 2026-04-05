from django.contrib import admin
from .models import Portfolio, Position, PortfolioSnapshot


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ["name", "current_value", "cash_available", "currency"]


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ["instrument", "direction", "quantity", "entry_price", "current_price", "unrealized_pnl_pct"]
    list_filter = ["direction"]


from .trader_profile import TraderProfile

@admin.register(TraderProfile)
class TraderProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "display_name", "experience_level", "trading_style", "risk_appetite"]
    list_filter = ["experience_level", "trading_style", "risk_appetite"]
