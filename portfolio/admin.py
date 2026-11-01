from django import forms
from django.contrib import admin
from .models import Portfolio, Position, PortfolioSnapshot


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ["name", "current_value", "cash_available", "currency"]


class PositionAdminForm(forms.ModelForm):
    """A stop and a target are optional here, as the columns are (null).

    (2026-10-31, review) The duplicate rule's words send the operator to
    this page to close a legacy row ("set Closed at"). The chat trader
    writes no stop or target, nor does a /setup/ 'add position' left
    blank, and the default form required both, so the save failed with
    "This field is required" and the row stayed open, blocking the bots
    on its symbol and side. A blank field saves as no level, the state
    those writers leave the row in."""

    class Meta:
        model = Position
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("stop_loss", "take_profit"):
            if name in self.fields:
                self.fields[name].required = False


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    form = PositionAdminForm
    list_display = ["instrument", "direction", "quantity", "entry_price", "current_price", "unrealized_pnl_pct"]
    list_filter = ["direction"]


from .trader_profile import TraderProfile

@admin.register(TraderProfile)
class TraderProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "display_name", "experience_level", "trading_style", "risk_appetite"]
    list_filter = ["experience_level", "trading_style", "risk_appetite"]
