from django.contrib import admin
from .models import PriceData, LiveQuote, EconomicEvent, MacroIndicator


@admin.register(LiveQuote)
class LiveQuoteAdmin(admin.ModelAdmin):
    list_display = ["instrument", "last", "change_pct", "updated_at", "source"]
    list_filter = ["source"]


@admin.register(EconomicEvent)
class EconomicEventAdmin(admin.ModelAdmin):
    list_display = ["title", "country", "datetime", "impact", "actual", "forecast"]
    list_filter = ["impact", "country"]


@admin.register(MacroIndicator)
class MacroIndicatorAdmin(admin.ModelAdmin):
    list_display = ["series_id", "name", "category", "last_value", "last_date"]
    list_filter = ["category"]
