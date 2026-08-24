from django.contrib import admin
from .models import AgentTask


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display = ["agent", "provider", "model", "success", "duration_seconds", "cost_usd", "created_at"]
    # AllValues: the agent column is free-form now, so the sidebar lists
    # the names that actually occur instead of a stale choices roster.
    list_filter = [("agent", admin.AllValuesFieldListFilter), "provider",
                   "success"]
