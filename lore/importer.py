"""Loading the catalogue: a command, not a data migration.

The seed is staff-only and lives outside git (private/lore/, or LORE_DIR),
as the Book's staff chapter does. Every imported row is a DRAFT: no agent
reads anything until a staff member reviews it on /lore/. Per entry, in
its own transaction: the validator in import mode, then create, update,
keep, same or refuse. After every file, the `related` links are made both
ways; an unknown related slug and a drifted code reference are warnings.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction

from . import curate
from .models import LoreEntry, LoreLink
from .validate import OVERLAY_KEYS, check, code_ref_exists

logger = logging.getLogger(__name__)

OVERLAY_FILE = "seed_overlay.json"


@dataclass
class ImportReport:
    path: str = ""
    read: int = 0
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    same: list = field(default_factory=list)
    refused: list = field(default_factory=list)   # (slug, code, reason)
    warnings: list = field(default_factory=list)  # (slug, message)
    dry_run: bool = False

    @property
    def n_refused(self):
        return len({slug for slug, _, _ in self.refused})

    def lines(self) -> list:
        out = [f"Read {self.read} entries from {self.path}."]
        for slug in self.created:
            out.append(f"  created  {slug} (draft)")
        for slug in self.updated:
            out.append(f"  updated  {slug} (untouched since the last import)")
        for slug in self.kept:
            out.append(f"  kept     {slug}: edited here since the last "
                       f"import; the file's version was not applied (use "
                       f"--force-slug to replace it)")
        for slug in self.same:
            out.append(f"  same     {slug}")
        for slug, code, reason in self.refused:
            out.append(f"  refused  {slug}: {code} {reason}")
        for slug, message in self.warnings:
            out.append(f"  warning  {slug}: {message}")
        out.append(f"Done: {len(self.created)} created, {len(self.updated)} "
                   f"updated, {len(self.kept)} kept, {len(self.same)} "
                   f"unchanged, {self.n_refused} refused.")
        if self.dry_run:
            out.append("Nothing written (dry run).")
        return out


def read_catalogue(path) -> tuple:
    """(entries, overlay) from a file or a directory of *.json files."""
    path = Path(path)
    files = []
    overlay: dict = {}
    if path.is_dir():
        for f in sorted(path.glob("*.json")):
            if f.name == OVERLAY_FILE:
                overlay = json.loads(f.read_text(encoding="utf-8")) or {}
            elif not f.name.startswith("export-"):
                files.append(f)
    elif path.is_file():
        files.append(path)
        beside = path.parent / OVERLAY_FILE
        if beside.is_file() and beside != path:
            overlay = json.loads(beside.read_text(encoding="utf-8")) or {}
    else:
        raise FileNotFoundError(str(path))
    entries = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "entries" in data:
            data = data["entries"]
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"{f}: not a list of entries")
        entries.extend(x for x in data if isinstance(x, dict))
    return entries, overlay if isinstance(overlay, dict) else {}


def apply_overlay(entry: dict, overlay: dict) -> dict:
    """The overlay's keys for this slug, applied unless the entry already
    carries them inline."""
    d = dict(entry)
    extra = overlay.get(d.get("slug", ""), {}) if overlay else {}
    if isinstance(extra, dict):
        for key in OVERLAY_KEYS:
            if key in extra and key not in d:
                d[key] = extra[key]
    return d


def import_entries(entries: list, overlay: dict | None = None, *,
                   dry_run: bool = False, only=(), force_slugs=(),
                   path: str = "") -> ImportReport:
    report = ImportReport(path=path, dry_run=dry_run)
    only = set(only or ())
    force_slugs = set(force_slugs or ())
    todo = []
    for raw in entries:
        slug = str(raw.get("slug", "")) if isinstance(raw, dict) else ""
        if only and slug not in only:
            continue
        todo.append((slug, apply_overlay(raw, overlay or {})))
    report.read = len(todo)
    landed: list = []
    for slug, d in todo:
        errors, warnings = check(d, mode="import")
        for _, message in warnings:
            report.warnings.append((slug, message))
        if errors:
            for code, reason in errors:
                report.refused.append((slug or "(no slug)", code, reason))
            continue
        if dry_run:
            existing = LoreEntry.objects.filter(slug=slug).first()
            sha = curate.content_sha(d)
            if existing is None:
                report.created.append(slug)
            elif existing.content_sha == sha:
                report.same.append(slug)
            elif (existing.content_sha != existing.imported_sha
                  and slug not in force_slugs):
                report.kept.append(slug)
            else:
                report.updated.append(slug)
            continue
        try:
            with transaction.atomic():
                outcome = _land(slug, d, force=slug in force_slugs)
        except Exception as e:  # noqa: BLE001 — the row is refused, not the run
            logger.warning("[lore import] %s refused: %s", slug, e)
            report.refused.append((slug, "V00", f"could not be written: "
                                               f"{type(e).__name__}"))
            continue
        getattr(report, outcome).append(slug)
        if outcome != "kept":
            landed.append((slug, d))
    if not dry_run:
        _link(landed, report)
    return report


def _land(slug: str, d: dict, *, force: bool) -> str:
    sha = curate.content_sha(d)
    existing = LoreEntry.objects.filter(slug=slug).first()
    if existing is None:
        entry = LoreEntry(slug=slug, origin="world", status="draft",
                          proposed_by="seed", version=1)
        curate.apply_dict(entry, d)
        entry.save()
        curate.write_rows(entry, d)
        _seal(entry, sha)
        curate.write_revision(entry, via="import",
                              content=curate.canonical(d))
        return "created"
    if existing.content_sha == sha:
        return "same"
    if existing.content_sha != existing.imported_sha and not force:
        return "kept"
    curate.apply_dict(existing, d)
    existing.version += 1
    if existing.status == "reviewed":
        # The text changed under a review: the review no longer stands.
        existing.status = "draft"
    existing.save()
    curate.write_rows(existing, d)
    _seal(existing, sha)
    curate.write_revision(existing, via="import",
                          content=curate.canonical(d))
    return "updated"


def _seal(entry: LoreEntry, file_sha: str) -> None:
    """The row's sha, computed from the rows as written, is the import's
    sha: "untouched since import" is content_sha == imported_sha."""
    curate.refresh(entry)
    if entry.content_sha != file_sha:  # pragma: no cover — a shape drift
        logger.warning("[lore import] %s: the row's sha differs from the "
                       "file's; the row's is kept", entry.slug)
    LoreEntry.objects.filter(pk=entry.pk).update(imported_sha=entry.content_sha)
    entry.imported_sha = entry.content_sha


def _link(landed: list, report: ImportReport) -> None:
    by_slug = {e.slug: e for e in LoreEntry.objects.filter(
        slug__in=[slug for slug, _ in landed])}
    # Two passes: first every landed entry's own related links come off,
    # then both directions are written, so one entry's pass never erases
    # what another's just wrote.
    LoreLink.objects.filter(from_entry__in=list(by_slug.values()),
                            kind="related").delete()
    for slug, d in landed:
        entry = by_slug.get(slug)
        if entry is None:
            continue
        for other_slug in d.get("related") or []:
            other = LoreEntry.objects.filter(slug=other_slug).first()
            if other is None:
                report.warnings.append(
                    (slug, f"related entry {other_slug} not found"))
                continue
            if other.pk == entry.pk:
                continue
            LoreLink.objects.get_or_create(from_entry=entry, to_entry=other,
                                           kind="related")
            LoreLink.objects.get_or_create(from_entry=other, to_entry=entry,
                                           kind="related")
        for ref in (x.get("ref", "") for x in d.get("sauron_code") or []):
            if ref and not code_ref_exists(ref):
                report.warnings.append(
                    (slug, f"code reference {ref} no longer exists"))


def import_path(path, **kw) -> ImportReport:
    entries, overlay = read_catalogue(path)
    return import_entries(entries, overlay, path=str(path), **kw)


def export_all() -> list:
    """Every entry in the import schema plus status, reviewed_at and
    proposed_by. Re-importing an export creates drafts."""
    out = []
    for entry in LoreEntry.objects.all().order_by("slug"):
        d = curate.export_dict(entry)
        d["status"] = entry.status
        d["reviewed_at"] = (entry.reviewed_at.isoformat()
                            if entry.reviewed_at else None)
        d["proposed_by"] = entry.proposed_by
        out.append(d)
    return out
