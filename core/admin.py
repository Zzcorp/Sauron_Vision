from django.contrib import admin
from .platform_control import PlatformComponent
from .models import FeatureFlag, AuditLog, TradingRestriction


@admin.register(PlatformComponent)
class PlatformComponentAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_enabled", "last_run_at", "last_status", "run_count", "error_count"]
    list_filter = ["category", "is_enabled", "last_status"]
    list_editable = ["is_enabled"]
    search_fields = ["name", "key"]


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ["name", "enabled", "description", "created_at", "updated_at"]
    list_filter = ["enabled"]
    list_editable = ["enabled"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["action", "user", "target_type", "target_id", "ip_address", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = ["user__username", "description", "target_type"]
    readonly_fields = ["user", "action", "target_type", "target_id", "description", "ip_address", "metadata", "created_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TradingRestriction)
class TradingRestrictionAdmin(admin.ModelAdmin):
    list_display = ["restriction_type", "instrument_symbol", "description", "user", "is_active", "created_at"]
    list_filter = ["restriction_type", "is_active"]
    list_editable = ["is_active"]
    search_fields = ["description", "instrument_symbol", "user__username"]
    readonly_fields = ["created_at"]
