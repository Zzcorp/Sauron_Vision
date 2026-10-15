"""The Lore in the admin: edit the text, never delete; review is on the
library page, with its five checks, and deliberately not a bulk action."""
from __future__ import annotations

from django.contrib import admin, messages

from . import curate
from .models import LoreClaim, LoreEntry, LoreLink, LoreRead, LoreRevision, LoreSource
from .validate import check, problems_text


class LoreSourceInline(admin.TabularInline):
    model = LoreSource
    extra = 0
    fields = ("position", "title", "by", "url", "date_text", "date_kind",
              "kind", "note", "quote", "found_via", "checked_on")
    #: "Opened" is set on the library page only, with who and when
    #: (curate.mark_source_opened).
    readonly_fields = ("found_via", "checked_on")
    ordering = ("position",)


class LoreClaimInline(admin.TabularInline):
    model = LoreClaim
    extra = 0
    fields = ("side", "position", "text", "basis", "episode", "sources")
    ordering = ("side", "position")


class LoreLinkInline(admin.TabularInline):
    model = LoreLink
    fk_name = "from_entry"
    extra = 0
    fields = ("to_entry", "kind")
    raw_id_fields = ("to_entry",)


@admin.register(LoreEntry)
class LoreEntryAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "kind", "status", "evidence_grade",
                    "origin", "proposed_by", "updated_at")
    list_filter = ("kind", "status", "evidence_grade", "origin", "proposed_by")
    search_fields = ("slug", "title", "tags_flat")
    ordering = ("slug",)
    inlines = (LoreSourceInline, LoreClaimInline, LoreLinkInline)
    readonly_fields = ("status", "version", "content_sha", "imported_sha",
                       "reviewed_sha", "reviewed_by", "reviewed_at",
                       "retired_at", "review_note", "search_text")
    fieldsets = (
        ("Identity", {"fields": ("slug", "kind", "title", "origin",
                                 "proposed_by", "first_accessed")}),
        ("Text (in our own words)", {"fields": (
            "summary", "mechanism", "works_when", "markets_text",
            "small_account_can", "small_account_cannot")}),
        ("Facets", {"fields": ("tags_flat", "classes_flat",
                               "regimes_works_flat", "regimes_breaks_flat",
                               "horizons_flat", "families_flat",
                               "code_refs")}),
        ("Evidence", {"fields": ("evidence_grade",)}),
        ("State", {"fields": ("status", "audience", "version", "content_sha",
                              "imported_sha", "reviewed_sha", "reviewed_by",
                              "reviewed_at", "retired_at", "review_note",
                              "search_text")}),
    )

    def has_delete_permission(self, request, obj=None):
        return False  # retire, never delete

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        entry = form.instance
        outcome = curate.content_changed_in_admin(entry, user=request.user)
        d = curate.export_dict(entry)
        d["origin"] = entry.origin
        errors, _ = check(d, mode="admin")
        if errors:
            messages.warning(request, "Saved as a draft with problems to fix "
                                      "before review: " + problems_text(errors))
            if entry.status == "reviewed":
                curate.set_status(entry, "draft", request.user, via="draft")
        elif outcome["back_to_draft"]:
            messages.info(request, "Saved. The text changed, so this entry is "
                                   "a draft again and no agent reads it. "
                                   "Review it on its library page.")
        else:
            messages.info(request, "Saved.")


@admin.register(LoreRevision)
class LoreRevisionAdmin(admin.ModelAdmin):
    list_display = ("entry", "version", "via", "status", "saved_by",
                    "created_at")
    list_filter = ("via", "status")
    readonly_fields = ("entry", "version", "content", "content_sha", "status",
                       "saved_by", "via", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoreRead)
class LoreReadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "agent", "source_ref", "n_shown",
                    "n_matched", "tokens_est", "scrubbed")
    list_filter = ("agent", "search_mode")
    readonly_fields = [f.name for f in LoreRead._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
