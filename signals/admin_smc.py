"""Django admin registration for SmcSignal."""
from django.contrib import admin
from .models_smc import SmcSignal


@admin.register(SmcSignal)
class SmcSignalAdmin(admin.ModelAdmin):
    list_display = (
        "created_at", "symbol", "timeframe", "setup", "direction",
        "entry", "stop", "target", "r_multiple", "conviction", "status",
    )
    list_filter = ("setup", "direction", "status", "timeframe", "symbol")
    search_fields = ("symbol", "headline", "thesis")
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Identity", {"fields": ("symbol", "timeframe", "setup", "direction")}),
        ("5-second card", {
            "fields": ("headline", "thesis", "why_now", "invalidation"),
        }),
        ("Levels", {
            "fields": ("entry", "stop", "target", "r_multiple"),
        }),
        ("Confluence", {
            "fields": (
                "chip_structure", "chip_momentum", "chip_flow",
                "chip_macro", "chip_sentiment", "conviction",
            ),
        }),
        ("Lifecycle", {
            "fields": (
                "status", "triggered_at", "closed_at", "realized_r",
                "rule_hit_rate_30d",
            ),
        }),
        ("Raw", {
            "classes": ("collapse",),
            "fields": ("components", "reasons", "raw", "trigger_ts", "created_at"),
        }),
    )
