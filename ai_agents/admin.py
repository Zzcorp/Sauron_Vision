from django.contrib import admin
from .models import AgentTask


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display = ["agent", "provider", "model", "success", "duration_seconds", "cost_usd", "created_at"]
    list_filter = ["agent", "provider", "success"]
