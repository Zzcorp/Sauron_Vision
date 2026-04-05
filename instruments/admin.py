from django.contrib import admin
from .models import Instrument


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ["symbol", "name", "asset_class", "exchange", "is_active", "is_watchlist"]
    list_filter = ["asset_class", "is_active", "is_watchlist", "exchange"]
    search_fields = ["symbol", "name"]
    list_editable = ["is_active", "is_watchlist"]
