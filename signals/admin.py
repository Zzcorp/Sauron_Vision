from django.contrib import admin
from .models import Signal


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ["title", "instrument", "signal_type", "direction", "urgency", "score", "is_active", "created_at"]
    list_filter = ["signal_type", "direction", "urgency", "is_active"]
    search_fields = ["title", "instrument__symbol"]
from . import admin_smc  # noqa: F401
