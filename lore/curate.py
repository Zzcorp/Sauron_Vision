"""Curation: the canonical export dict, the content sha, the search text,
revisions, and the review transitions a staff member makes on the page.

Everything that changes a row's text passes through `refresh()` so the
search text and the sha are never stale; everything that changes its
state writes a LoreRevision, append-only.
"""
from __future__ import annotations

import hashlib
import json
import re

from django.db import transaction
from django.utils import timezone

from . import constants as C
from .models import LoreClaim, LoreEntry, LoreLink, LoreRevision, LoreSource

WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


# ── The canonical dict ────────────────────────────────────────────────────

def _sources_of(entry):
    return list(entry.sources.all().order_by("position"))


def _claims_of(entry, side):
    return list(entry.claims.filter(side=side).order_by("position"))


def export_dict(entry: LoreEntry, *, sources=None, claims=None,
                related=None) -> dict:
    """The entry in the catalogue schema (plus the overlay keys). Status
    and the review fields are NOT here: the sha below is of content."""
    sources = _sources_of(entry) if sources is None else sources
    if claims is None:
        claims = {side: _claims_of(entry, side)
                  for side in ("documented", "reputed", "breaks")}
    if related is None:
        related = sorted(
            LoreLink.objects.filter(from_entry=entry, kind="related")
            .values_list("to_entry__slug", flat=True))

    def _src(c):
        return [int(k) - 1 for k in (c.sources or [])]

    evidence = []
    for s in sources:
        item = {"title": s.title, "by": s.by, "url": s.url,
                "date": s.date_text, "type": s.kind, "note": s.note,
                "date_kind": s.date_kind}
        if s.quote:
            item["quote"] = s.quote
        evidence.append(item)
    return {
        "slug": entry.slug,
        "kind": entry.kind,
        "title": entry.title,
        "summary": entry.summary,
        "mechanism": entry.mechanism,
        "works_when": {
            "regimes": entry.works_when,
            "asset_classes": [a for a in entry.markets_text.split("; ") if a],
        },
        "fails_when": [{"how": c.text, "episode": c.episode, "src": _src(c)}
                       for c in claims["breaks"]],
        "evidence": evidence,
        "documented": [{"claim": c.text, "src": _src(c)}
                       for c in claims["documented"]],
        "reputed": [{"claim": c.text, "basis": c.basis, "src": _src(c)}
                    for c in claims["reputed"]],
        "evidence_grade": entry.evidence_grade,
        "related": list(related),
        "small_account": {"can": entry.small_account_can,
                          "cannot": entry.small_account_cannot},
        "sauron_code": list(entry.code_refs or []),
        "tags": entry.tags,
        "accessed": (entry.first_accessed.isoformat()
                     if entry.first_accessed else ""),
        "asset_classes": entry.classes,
        "regimes_works": entry.regimes_works,
        "regimes_breaks": entry.regimes_breaks,
        "horizons": entry.horizons,
        "families": entry.families,
    }


def canonical(d: dict) -> dict:
    """A raw catalogue dict in exactly the shape export_dict() produces, so
    the sha of a file entry and the sha of its row agree."""
    ww = d.get("works_when") if isinstance(d.get("works_when"), dict) else {}
    sa = d.get("small_account") if isinstance(d.get("small_account"), dict) else {}

    def _s(v):
        return v if isinstance(v, str) else ("" if v is None else str(v))

    def _src(item):
        src = item.get("src") if isinstance(item, dict) else None
        return [int(k) for k in (src or []) if isinstance(k, int)]

    def _items(key):
        return [x for x in (d.get(key) or []) if isinstance(x, dict)]

    evidence = []
    for s in _items("evidence"):
        item = {"title": _s(s.get("title")), "by": _s(s.get("by")),
                "url": _s(s.get("url")), "date": _s(s.get("date")),
                "type": _s(s.get("type")), "note": _s(s.get("note")),
                "date_kind": _s(s.get("date_kind")) or "published"}
        if _s(s.get("quote")):
            item["quote"] = _s(s.get("quote"))
        evidence.append(item)
    return {
        "slug": _s(d.get("slug")),
        "kind": _s(d.get("kind")),
        "title": _s(d.get("title")),
        "summary": _s(d.get("summary")),
        "mechanism": _s(d.get("mechanism")),
        "works_when": {"regimes": _s(ww.get("regimes")),
                       "asset_classes": [_s(a) for a in ww.get("asset_classes") or []]},
        "fails_when": [{"how": _s(c.get("how")), "episode": _s(c.get("episode")),
                        "src": _src(c)} for c in _items("fails_when")],
        "evidence": evidence,
        "documented": [{"claim": _s(c.get("claim")), "src": _src(c)}
                       for c in _items("documented")],
        "reputed": [{"claim": _s(c.get("claim")), "basis": _s(c.get("basis")),
                     "src": _src(c)} for c in _items("reputed")],
        "evidence_grade": _s(d.get("evidence_grade")),
        "related": sorted({_s(r) for r in (d.get("related") or []) if _s(r)}),
        "small_account": {"can": _s(sa.get("can")), "cannot": _s(sa.get("cannot"))},
        "sauron_code": [{"ref": _s(x.get("ref")), "note": _s(x.get("note"))}
                        for x in _items("sauron_code")],
        "tags": C.unflat(C.flat(d.get("tags") or [])),
        "accessed": _s(d.get("accessed")),
        "asset_classes": C.unflat(C.flat(d.get("asset_classes") or [])),
        "regimes_works": C.unflat(C.flat(d.get("regimes_works") or [])),
        "regimes_breaks": C.unflat(C.flat(d.get("regimes_breaks") or [])),
        "horizons": C.unflat(C.flat(d.get("horizons") or [])),
        "families": C.unflat(C.flat(d.get("families") or [])),
    }


#: Left out of the content sha: the state and review fields, and `related`,
#: which is a link to other rows rather than this row's text (a related
#: slug missing from the database would otherwise make a file entry read
#: as changed on every import).
SHA_EXCLUDED = ("status", "reviewed_at", "proposed_by", "origin", "related")


def content_sha(d: dict) -> str:
    """sha256 of the canonical dict, review and status fields left out."""
    clean = {k: v for k, v in canonical(d).items() if k not in SHA_EXCLUDED}
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Search text ───────────────────────────────────────────────────────────

def build_search_text(entry: LoreEntry, *, sources=None, claims=None) -> str:
    parts = [entry.title, entry.slug, entry.slug.replace("-", " "),
             " ".join(entry.tags), " ".join(entry.classes),
             " ".join(entry.regimes_works), " ".join(entry.regimes_breaks),
             " ".join(entry.horizons), " ".join(entry.families),
             entry.summary, entry.mechanism, entry.works_when,
             entry.markets_text, entry.small_account_can,
             entry.small_account_cannot]
    if entry.pk:
        if sources is None:
            sources = list(entry.sources.all())
        if claims is None:
            claims = list(entry.claims.all())
        parts += [f"{s.title} {s.by}" for s in sources]
        parts += [f"{c.text} {c.basis} {c.episode}" for c in claims]
    else:
        parts += [f"{s.title} {s.by}" for s in (sources or [])]
        parts += [f"{c.text} {c.basis} {c.episode}" for c in (claims or [])]
    text = " ".join(p for p in parts if p).lower()
    return re.sub(r"\s+", " ", text).strip()


def refresh(entry: LoreEntry, *, save=True) -> LoreEntry:
    """Rebuild search_text and content_sha from the rows as they stand."""
    d = export_dict(entry)
    entry.content_sha = content_sha(d)
    entry.search_text = build_search_text(entry)
    if save:
        LoreEntry.objects.filter(pk=entry.pk).update(
            content_sha=entry.content_sha, search_text=entry.search_text,
            updated_at=timezone.now())
    return entry


# ── Revisions ─────────────────────────────────────────────────────────────

def write_revision(entry: LoreEntry, *, via: str, user=None,
                   content: dict | None = None) -> LoreRevision:
    content = content if content is not None else export_dict(entry)
    return LoreRevision.objects.create(
        entry=entry, version=entry.version, content=content,
        content_sha=entry.content_sha or content_sha(content),
        status=entry.status, saved_by=user, via=via)


# ── Writing an entry from a dict ──────────────────────────────────────────

def write_rows(entry: LoreEntry, d: dict) -> None:
    """Replace the entry's sources and claims with the dict's. Links are
    the importer's job (they need every slug in place). Every source lands
    as "search summary only": a file cannot say a person opened it; only
    mark_source_opened, with the person and the day, can."""
    entry.sources.all().delete()
    entry.claims.all().delete()
    for i, s in enumerate(d.get("evidence") or [], 1):
        LoreSource.objects.create(
            entry=entry, position=i, title=s.get("title", ""),
            by=s.get("by", ""), url=s.get("url", ""),
            date_text=s.get("date", ""),
            date_kind=s.get("date_kind") or "published",
            kind=s.get("type", ""), note=s.get("note", "") or "",
            quote=s.get("quote", "") or "",
            found_via="search_summary")
    for i, c in enumerate(d.get("documented") or [], 1):
        LoreClaim.objects.create(
            entry=entry, side="documented", position=i, text=c.get("claim", ""),
            sources=[int(k) + 1 for k in c.get("src", [])])
    for i, c in enumerate(d.get("reputed") or [], 1):
        LoreClaim.objects.create(
            entry=entry, side="reputed", position=i, text=c.get("claim", ""),
            basis=c.get("basis", "") or "",
            sources=[int(k) + 1 for k in c.get("src", [])])
    for i, c in enumerate(d.get("fails_when") or [], 1):
        LoreClaim.objects.create(
            entry=entry, side="breaks", position=i, text=c.get("how", ""),
            episode=c.get("episode", "") or "",
            sources=[int(k) + 1 for k in c.get("src", [])])


def apply_dict(entry: LoreEntry, d: dict) -> LoreEntry:
    """Set the entry's own columns from the dict (not saved)."""
    ww = d.get("works_when") if isinstance(d.get("works_when"), dict) else {}
    sa = d.get("small_account") if isinstance(d.get("small_account"), dict) else {}
    entry.kind = d.get("kind", entry.kind)
    entry.title = d.get("title", "")
    entry.summary = d.get("summary", "")
    entry.mechanism = d.get("mechanism", "")
    entry.works_when = ww.get("regimes", "") or ""
    entry.markets_text = "; ".join(str(a) for a in ww.get("asset_classes") or [])
    entry.small_account_can = sa.get("can", "") or ""
    entry.small_account_cannot = sa.get("cannot", "") or ""
    entry.evidence_grade = d.get("evidence_grade", "none")
    entry.tags_flat = C.flat(d.get("tags") or [])
    entry.classes_flat = C.flat(d.get("asset_classes") or [])
    entry.regimes_works_flat = C.flat(d.get("regimes_works") or [])
    entry.regimes_breaks_flat = C.flat(d.get("regimes_breaks") or [])
    entry.horizons_flat = C.flat(d.get("horizons") or [])
    entry.families_flat = C.flat(d.get("families") or [])
    entry.code_refs = [{"ref": str(x.get("ref", "")), "note": str(x.get("note", ""))}
                       for x in (d.get("sauron_code") or [])
                       if isinstance(x, dict)]
    accessed = d.get("accessed") or ""
    try:
        from datetime import date
        entry.first_accessed = (date.fromisoformat(accessed)
                                if accessed else None)
    except ValueError:
        entry.first_accessed = None
    return entry


# ── Review transitions ────────────────────────────────────────────────────

class ReviewRefused(Exception):
    pass


REVIEW_CHECKS = (
    ("opened", 'I opened the sources I could, and they say what the entry '
               'says. Sources I did not open stay marked "search summary '
               'only".'),
    ("own_words", "The text is in our own words. Any quote is short and "
                  "attributed."),
    ("sides", "Documented and reputed claims are on the right side, and "
              "each reputed claim says why."),
    ("tags", "The tags are right: kind, asset classes, regimes, horizon."),
    ("account", "Nothing in it concerns our own account."),
)


def mark_reviewed(entry: LoreEntry, user, *, checks: dict, note: str = "",
                  expected_sha: str = "") -> LoreEntry:
    from .validate import check, problems_text
    if expected_sha and expected_sha != entry.content_sha:
        raise ReviewRefused("This entry changed since you opened it. Reload "
                            "and review again.")
    if not all(checks.get(key) for key, _ in REVIEW_CHECKS):
        raise ReviewRefused("Tick all five checks to mark this entry "
                            "reviewed.")
    d = export_dict(entry)
    d["origin"] = entry.origin
    errors, _ = check(d, mode="review")
    if errors:
        raise ReviewRefused("This entry cannot be reviewed yet: "
                            + problems_text(errors))
    with transaction.atomic():
        entry.status = "reviewed"
        entry.reviewed_by = user
        entry.reviewed_at = timezone.now()
        entry.reviewed_sha = entry.content_sha
        entry.review_note = (note or "")[:300]
        entry.retired_at = None
        entry.save()
        write_revision(entry, via="review", user=user, content=d)
    return entry


def set_status(entry: LoreEntry, status: str, user, *, note: str = "",
               via: str) -> LoreEntry:
    with transaction.atomic():
        entry.status = status
        if status == "retired":
            entry.retired_at = timezone.now()
        if status == "draft":
            entry.retired_at = None
        if note:
            entry.review_note = note[:300]
        entry.save()
        write_revision(entry, via=via, user=user)
    return entry


def mark_source_opened(entry: LoreEntry, position: int, user) -> bool:
    src = entry.sources.filter(position=position).first()
    if src is None:
        return False
    src.found_via = "opened"
    src.checked_on = timezone.now().date()
    src.checked_by = user
    src.save(update_fields=["found_via", "checked_on", "checked_by"])
    return True


def content_changed_in_admin(entry: LoreEntry, user=None) -> dict:
    """After an admin save: rebuild, bump the version when the content
    moved, send a reviewed entry back to draft. Returns what happened."""
    before = entry.content_sha
    refresh(entry, save=False)
    changed = entry.content_sha != before
    back_to_draft = False
    if changed:
        entry.version += 1
        if entry.status == "reviewed":
            entry.status = "draft"
            back_to_draft = True
    entry.save()
    if changed:
        write_revision(entry, via="admin", user=user)
    return {"changed": changed, "back_to_draft": back_to_draft}
