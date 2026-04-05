from django.contrib import admin
from .platform_control import PlatformComponent


@admin.register(PlatformComponent)
class PlatformComponentAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_enabled", "last_run_at", "last_status", "run_count", "error_count"]
    list_filter = ["category", "is_enabled", "last_status"]
    list_editable = ["is_enabled"]
    search_fields = ["name", "key"]
