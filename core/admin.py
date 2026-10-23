from django import forms
from django.contrib import admin
from .platform_control import LIVE_MONEY_SWITCHES, PlatformComponent
from .models import FeatureFlag, AuditLog, TradingRestriction


class PlatformComponentAdminForm(forms.ModelForm):
    """The admin never turns a live-money switch ON (2026-10-23,
    core/switch_pin.py): that takes the trading PIN, which this page
    never asks for. Refused here, on the changelist checkbox, the change
    form and the add form alike, including by renaming a row into a
    live-money key. Turning one OFF stays free.

    `clean()` runs before the instance is updated from the POST, so the
    row's stored state is still the database's; it is re-read anyway.
    `_request` is set per request on the form class the admin builds.

    On the changelist a refusal is NOT a form error: Django validates every
    row of the list before it saves any, so one refused ON would also drop
    every OFF ticked in the same save (a stale page, or a mixed save), and
    stopping must never be harder. The refused row keeps its stored state,
    reads as unchanged (has_changed), says why in a message, and the other
    rows save. The change and add forms keep the form error.
    """

    _request = None
    _changelist = False         # set on the class get_changelist_form builds
    _switch_refused = False

    class Meta:
        model = PlatformComponent
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        inst = self.instance
        key = cleaned.get("key", inst.key) if "key" in self.fields \
            else inst.key
        want_on = cleaned.get("is_enabled", inst.is_enabled) \
            if "is_enabled" in self.fields else inst.is_enabled
        if not (key and want_on and key in LIVE_MONEY_SWITCHES):
            return cleaned
        stored = None
        if inst.pk:
            stored = PlatformComponent.objects.filter(pk=inst.pk).values_list(
                "key", "is_enabled").first()
        if stored is not None and stored == (key, True):
            return cleaned      # already ON under this key: nothing armed
        from core.switch_pin import VIA_DJANGO_ADMIN, refuse_here
        user = getattr(self._request, "user", None)
        message = refuse_here(key, via=VIA_DJANGO_ADMIN, user=user)
        if self._changelist and inst.pk:
            # The row stays as stored; the rest of the list still saves.
            cleaned["is_enabled"] = bool(stored[1]) if stored else False
            self._switch_refused = True
            if self._request is not None:
                from django.contrib import messages
                messages.error(self._request, message)
            return cleaned
        self.add_error("is_enabled" if "is_enabled" in self.fields else None,
                       message)
        return cleaned

    def has_changed(self):
        # A refused changelist row is not saved, counted or logged.
        if self._switch_refused:
            return False
        return super().has_changed()


@admin.register(PlatformComponent)
class PlatformComponentAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_enabled", "last_run_at", "last_status", "run_count", "error_count"]
    list_filter = ["category", "is_enabled", "last_status"]
    list_editable = ["is_enabled"]
    search_fields = ["name", "key"]
    form = PlatformComponentAdminForm

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        form._request = request     # a fresh class per call
        return form

    def get_changelist_form(self, request, **kwargs):
        # Django builds the list_editable form apart from `form`: without
        # this the changelist checkbox would be an open door.
        kwargs.setdefault("form", PlatformComponentAdminForm)
        form = super().get_changelist_form(request, **kwargs)
        form._request = request
        form._changelist = True
        return form

    def save_model(self, request, obj, form, change):
        if getattr(form, "_switch_refused", False):
            return      # refused: nothing written, no false "disarmed" row
        super().save_model(request, obj, form, change)
        if change and "is_enabled" in form.changed_data \
                and not obj.is_enabled and obj.key in LIVE_MONEY_SWITCHES:
            from core.switch_pin import VIA_DJANGO_ADMIN, record_disarm
            record_disarm(obj.key, via=VIA_DJANGO_ADMIN, user=request.user)


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
