"""The Lore's rows (2026-10-14).

Five content tables and one ledger. No numeric field exists on any content
row other than `version` and `position`: nothing here can be read by code
as a stop, a size, a threshold, a leverage, a limit or a parameter, and
tests/test_lore_library.py scans the field names to keep it so. Flat lists
are `"|a|b|"` strings because Django's JSONField `contains` lookup is
unsupported on SQLite, where the suite and CI run.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from . import constants as C


class LoreEntry(models.Model):
    slug = models.SlugField(max_length=60, unique=True)
    kind = models.CharField(max_length=16, choices=C.KINDS, db_index=True)
    title = models.CharField(max_length=120)
    summary = models.TextField(
        help_text="Four to eight sentences, in our own words.")
    mechanism = models.TextField(help_text="How it works, in our own words.")
    works_when = models.TextField(help_text="The regimes it needs, in words.")
    markets_text = models.CharField(
        max_length=400, blank=True,
        help_text="The markets named by the source, for display only.")
    small_account_can = models.TextField(
        blank=True, help_text="What a small retail account can do with it; "
                              "generic, never our own account.")
    small_account_cannot = models.TextField(blank=True)
    evidence_grade = models.CharField(max_length=10, choices=C.EVIDENCE_GRADES)

    tags_flat = models.CharField(max_length=400, blank=True)
    classes_flat = models.CharField(max_length=120, blank=True)
    regimes_works_flat = models.CharField(max_length=80, blank=True)
    regimes_breaks_flat = models.CharField(max_length=80, blank=True)
    horizons_flat = models.CharField(max_length=60, blank=True)
    families_flat = models.CharField(max_length=200, blank=True)
    #: [{ref, note}] — page and card only; `lore check --refs` reports drift.
    code_refs = models.JSONField(default=list, blank=True)

    origin = models.CharField(max_length=8, choices=C.ORIGINS, default="world",
                              db_index=True)
    status = models.CharField(max_length=10, choices=C.STATUSES,
                              default="draft", db_index=True)
    audience = models.CharField(max_length=10, choices=C.AUDIENCES,
                                default="staff")
    proposed_by = models.CharField(max_length=16, choices=C.PROPOSERS,
                                   default="seed")
    review_note = models.CharField(max_length=300, blank=True)
    version = models.PositiveIntegerField(default=1)
    content_sha = models.CharField(max_length=64, blank=True)
    imported_sha = models.CharField(max_length=64, blank=True)
    reviewed_sha = models.CharField(max_length=64, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                    blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    first_accessed = models.DateField(null=True, blank=True)
    search_text = models.TextField(editable=False, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]
        verbose_name = "library entry"
        verbose_name_plural = "library entries"
        indexes = [models.Index(fields=["status", "kind"]),
                   models.Index(fields=["origin", "status"])]
        permissions = [("review_loreentry",
                        "Can mark a library entry reviewed")]

    def __str__(self):
        return f"{self.slug} ({self.get_status_display().lower()})"

    # Flat columns as lists, for pages and prompts.
    @property
    def tags(self):
        return C.unflat(self.tags_flat)

    @property
    def classes(self):
        return C.unflat(self.classes_flat)

    @property
    def regimes_works(self):
        return C.unflat(self.regimes_works_flat)

    @property
    def regimes_breaks(self):
        return C.unflat(self.regimes_breaks_flat)

    @property
    def horizons(self):
        return C.unflat(self.horizons_flat)

    @property
    def families(self):
        return C.unflat(self.families_flat)

    #: The `"|a|b|"` columns, normalised on every save: the admin edits them
    #: as raw text, and search filters with `__contains="|x|"`, which needs
    #: the outer pipes and lowercase on PostgreSQL (case-sensitive LIKE),
    #: not only on SQLite (where ASCII LIKE ignores case).
    FLAT_FIELDS = ("tags_flat", "classes_flat", "regimes_works_flat",
                   "regimes_breaks_flat", "horizons_flat", "families_flat")

    def save(self, *args, **kwargs):
        # Own fields and the related rows already saved; the full rebuild
        # after sources and claims land is curate.refresh().
        from .curate import build_search_text
        for name in self.FLAT_FIELDS:
            setattr(self, name, C.flat(C.unflat(getattr(self, name))))
        self.search_text = build_search_text(self)
        super().save(*args, **kwargs)


class LoreSource(models.Model):
    entry = models.ForeignKey(LoreEntry, on_delete=models.CASCADE,
                              related_name="sources")
    position = models.PositiveIntegerField(help_text="1-based; label S{n}.")
    title = models.CharField(max_length=300)
    by = models.CharField(max_length=300, help_text="Author or publisher.")
    url = models.URLField(max_length=600)
    date_text = models.CharField(max_length=10,
                                 help_text="YYYY, YYYY-MM or YYYY-MM-DD.")
    date_kind = models.CharField(max_length=12, choices=C.DATE_KINDS,
                                 default="published")
    kind = models.CharField(max_length=12, choices=C.SOURCE_KINDS)
    note = models.TextField(blank=True, help_text="Our words on the source.")
    quote = models.CharField(
        max_length=300, blank=True,
        help_text="Verbatim, at most 300 characters, attributed. The only "
                  "words here that are not ours.")
    found_via = models.CharField(max_length=16, choices=C.FOUND_VIA,
                                 default="search_summary")
    checked_on = models.DateField(null=True, blank=True)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                   blank=True, on_delete=models.SET_NULL,
                                   related_name="+")

    class Meta:
        ordering = ["entry", "position"]
        constraints = [models.UniqueConstraint(
            fields=["entry", "position"], name="lore_source_position")]

    @property
    def label(self):
        return f"S{self.position}"

    def __str__(self):
        return f"{self.entry_id}:S{self.position} {self.title[:40]}"


class LoreClaim(models.Model):
    entry = models.ForeignKey(LoreEntry, on_delete=models.CASCADE,
                              related_name="claims")
    side = models.CharField(max_length=12, choices=C.CLAIM_SIDES)
    position = models.PositiveIntegerField()
    text = models.TextField()
    basis = models.TextField(
        blank=True, help_text="Believed but not proven; say why.")
    episode = models.TextField(blank=True, help_text='"Seen in", for breaks.')
    #: 1-based positions of the sources this claim rests on.
    sources = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["entry", "side", "position"]
        constraints = [models.UniqueConstraint(
            fields=["entry", "side", "position"], name="lore_claim_position")]

    def __str__(self):
        return f"{self.entry_id}:{self.side}:{self.position}"


class LoreLink(models.Model):
    from_entry = models.ForeignKey(LoreEntry, on_delete=models.CASCADE,
                                   related_name="links_out")
    to_entry = models.ForeignKey(LoreEntry, on_delete=models.CASCADE,
                                 related_name="links_in")
    kind = models.CharField(max_length=12, choices=C.LINK_KINDS,
                            default="related")

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["from_entry", "to_entry", "kind"], name="lore_link_once")]

    def __str__(self):
        return f"{self.from_entry_id} {self.kind} {self.to_entry_id}"


class LoreRevision(models.Model):
    """Append-only: every content change keeps its predecessor, the stance
    the knowledge graph takes (supersede, never edit)."""
    entry = models.ForeignKey(LoreEntry, on_delete=models.CASCADE,
                              related_name="revisions")
    version = models.PositiveIntegerField()
    content = models.JSONField(default=dict)
    content_sha = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=C.STATUSES)
    saved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                 blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    via = models.CharField(max_length=10, choices=C.REVISION_VIAS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entry", "-version", "-created_at"]

    def __str__(self):
        return f"{self.entry_id} v{self.version} via {self.via}"


class LoreRead(models.Model):
    """The ledger: one row per non-empty block an agent received. Carries
    the search terms after stopwords and a digest of the question, never
    the question itself."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    agent = models.CharField(max_length=30, db_index=True)
    source_ref = models.CharField(max_length=80, blank=True)
    terms = models.CharField(max_length=200, blank=True)
    query_digest = models.CharField(max_length=40, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    slugs = models.JSONField(default=list, blank=True)
    n_matched = models.PositiveIntegerField(default=0)
    n_shown = models.PositiveIntegerField(default=0)
    n_full = models.PositiveIntegerField(default=0)
    tokens_est = models.PositiveIntegerField(default=0)
    corpus_version = models.CharField(max_length=8, blank=True)
    search_mode = models.CharField(max_length=12, blank=True)
    scrubbed = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["agent", "-created_at"])]

    def __str__(self):
        return f"{self.agent} read {self.n_shown} at {self.created_at:%Y-%m-%d %H:%M}"
