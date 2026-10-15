"""The library pages: staff only, never cached, nothing an investor or a
non-staff operator can reach (staff_member_required redirects them to the
admin login; the investor gate holds investors before this)."""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_POST

from . import constants as C
from . import curate
from .models import LoreEntry, LoreLink, LoreRead, LoreSource
from .policy import POLICY
from .render import is_inference
from .replay import replay_lines
from .search import base_queryset, search

PAGE_SIZE = 24
DEFAULT_STATUSES = ("draft", "reviewed")


def _private(response):
    patch_cache_control(response, private=True, no_store=True)
    return response


def _switch_state(key: str) -> str:
    from core.platform_control import is_component_enabled
    return "on" if is_component_enabled(key) else "off"


def _regime_now() -> str:
    try:
        from brain.models import BrainReport
        latest = BrainReport.objects.filter(error="").order_by("-created_at").first()
        label = latest.regime_label if latest else ""
        return label if label in C.regime_keys() else ""
    except Exception:  # noqa: BLE001
        return ""


@staff_member_required
def index(request):
    q = (request.GET.get("q") or "").strip()[:200]
    kind = request.GET.get("kind") or ""
    regime = request.GET.get("regime") or ""
    klass = request.GET.get("class") or ""
    horizon = request.GET.get("horizon") or ""
    grade = request.GET.get("evidence") or ""
    status = request.GET.get("status") or ""
    tag = (request.GET.get("tag") or "").strip().lower()
    regime_now = _regime_now()
    use_now = bool(request.GET.get("now")) and bool(regime_now)

    kinds = (kind,) if kind in C.KIND_KEYS else ()
    regimes = (regime,) if regime in C.regime_keys() else ()
    if use_now:
        regimes = (regime_now,)
    classes = (klass,) if klass in C.ASSET_CLASS_KEYS else ()
    horizons = (horizon,) if horizon in C.HORIZON_KEYS else ()
    grades = (grade,) if grade in C.GRADE_KEYS else ()
    statuses = (status,) if status in C.STATUS_KEYS else DEFAULT_STATUSES
    tags = (tag,) if tag else ()

    filtered = bool(kinds or regimes or classes or horizons or grades or tags
                    or status)
    if q or regimes or classes or tags:
        result = search(q, kinds=kinds, classes=classes, regimes=regimes,
                        horizons=horizons, grades=grades, tags=tags,
                        statuses=statuses, regime_now=regime_now, limit=500)
        rows = list(result.entries)
        n_matched = result.n_matched
    else:
        rows = list(base_queryset(kinds=kinds, horizons=horizons,
                                  grades=grades, statuses=statuses)
                    .order_by("slug"))
        n_matched = len(rows)
    paginator = Paginator(rows, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page") or 1)

    counts = {s: LoreEntry.objects.filter(status=s).count() for s in C.STATUS_KEYS}
    n_entries = sum(counts.values())
    n_sources = LoreSource.objects.count()
    n_opened = LoreSource.objects.filter(found_via="opened").count()
    last_read = LoreRead.objects.order_by("-created_at").first()
    recent_reads = list(LoreRead.objects.order_by("-created_at")[:6])
    cards = []
    for e in page.object_list:
        cards.append({
            "entry": e,
            "lead": " ".join(curate_sentences(e.summary)[:2]),
            "n_sources": e.sources.count(),
            "n_reputed": e.claims.filter(side="reputed").count(),
            "works": ", ".join(C.regime_labels().get(r, r) for r in e.regimes_works),
            "breaks": ", ".join(C.regime_labels().get(r, r) for r in e.regimes_breaks),
        })
    query_string = request.GET.copy()
    query_string.pop("page", None)
    context = {
        "page_id": "lore",
        "q": q, "kind": kind, "regime": regime, "klass": klass,
        "horizon": horizon, "grade": grade, "status": status, "tag": tag,
        "use_now": use_now, "regime_now": regime_now,
        "regime_now_label": C.regime_labels().get(regime_now, regime_now),
        "kinds": C.KINDS, "regimes": C.regime_choices(),
        "classes": [(k, C.ASSET_CLASS_LABELS[k]) for k in C.ASSET_CLASS_KEYS],
        "horizons": C.HORIZONS, "grades": C.EVIDENCE_GRADES,
        "statuses": C.STATUSES,
        "cards": cards, "page": page, "n_matched": n_matched,
        "filtered": bool(q) or filtered,
        "n_entries": n_entries, "counts": counts,
        "n_sources": n_sources, "n_opened": n_opened,
        "n_summary_only": n_sources - n_opened,
        "switch_staff": _switch_state(POLICY["research"].switch),
        "switch_background": _switch_state(POLICY["strategist"].switch),
        "last_read": last_read, "recent_reads": recent_reads,
        "n_drafts": counts.get("draft", 0),
        "base_query": query_string.urlencode(),
    }
    return _private(render(request, "lore/index.html", context))


def curate_sentences(text: str) -> list:
    from .validate import sentences
    return sentences(text)


@staff_member_required
def entry(request, slug):
    e = get_object_or_404(LoreEntry, slug=slug)
    sources = list(e.sources.all().order_by("position"))
    kind_labels = dict(C.SOURCE_KINDS)
    for s in sources:
        s.kind_label = kind_labels.get(s.kind, s.kind)
    claims = {side: list(e.claims.filter(side=side).order_by("position"))
              for side in ("documented", "reputed", "breaks")}
    src_by_pos = {s.position: s for s in sources}
    for side, side_rows in claims.items():
        for c in side_rows:
            # A failure mode marked as an inference is ours: no source
            # badge vouches for it (lore/render.py OUR_INFERENCE).
            if side == "breaks" and is_inference(c.episode):
                c.labels = ["our inference"]
            else:
                c.labels = [f"S{k}" for k in (c.sources or [])]
    links = {"related": [], "illustrates": [], "illustrated_by": [],
             "contradicts": []}
    for link in LoreLink.objects.filter(from_entry=e).select_related("to_entry"):
        links.setdefault(link.kind, []).append(link.to_entry)
    for link in LoreLink.objects.filter(to_entry=e, kind="illustrates").select_related("from_entry"):
        links["illustrated_by"].append(link.from_entry)
    revisions = list(e.revisions.select_related("saved_by").order_by("-version", "-created_at")[:20])
    since = timezone.now() - timedelta(days=30)
    reads = [r for r in LoreRead.objects.filter(created_at__gte=since)
             .order_by("-created_at")[:200] if slug in (r.slugs or [])]
    replay = replay_lines(e.families) if e.families else []
    can_review = request.user.has_perm("lore.review_loreentry")
    context = {
        "page_id": "lore",
        "entry": e, "sources": sources, "claims": claims,
        "src_by_pos": src_by_pos, "links": links, "revisions": revisions,
        "reads": reads, "n_reads": len(reads),
        "replay": replay,
        "checks": curate.REVIEW_CHECKS, "can_review": can_review,
        "regime_labels": C.regime_labels(),
        "works_labels": [C.regime_labels().get(r, r) for r in e.regimes_works],
        "breaks_labels": [C.regime_labels().get(r, r) for r in e.regimes_breaks],
        "class_labels": [C.ASSET_CLASS_LABELS.get(c, c) for c in e.classes],
        "horizon_labels": [dict(C.HORIZONS).get(h, h) for h in e.horizons],
        "source_kind_labels": dict(C.SOURCE_KINDS),
        "proposer_label": dict(C.PROPOSERS).get(e.proposed_by, e.proposed_by),
    }
    return _private(render(request, "lore/entry.html", context))


@staff_member_required
@require_POST
def review(request, slug):
    e = get_object_or_404(LoreEntry, slug=slug)
    target = reverse("lore:entry", args=[e.slug])
    if not request.user.has_perm("lore.review_loreentry"):
        messages.error(request, "You do not have permission to review "
                                "library entries.")
        return _private(HttpResponseRedirect(target))
    action = request.POST.get("action") or ""
    note = (request.POST.get("note") or "").strip()[:300]
    expected = (request.POST.get("content_sha") or "").strip()
    if action == "opened":
        n = 0
        for raw in request.POST.getlist("opened"):
            try:
                if curate.mark_source_opened(e, int(raw), request.user):
                    n += 1
            except (TypeError, ValueError):
                continue
        messages.success(request, f"Marked {n} source{'' if n == 1 else 's'} "
                                  f"as opened.")
        return _private(HttpResponseRedirect(target))
    if action == "reviewed":
        if not expected:
            # The page always sends the sha it showed; a POST without it
            # cannot prove the entry is the one the reviewer read.
            messages.error(request, "This entry changed since you opened it. "
                                    "Reload and review again.")
            return _private(HttpResponseRedirect(target))
        checks = {key: bool(request.POST.get(f"check_{key}"))
                  for key, _ in curate.REVIEW_CHECKS}
        try:
            curate.mark_reviewed(e, request.user, checks=checks, note=note,
                                 expected_sha=expected)
        except curate.ReviewRefused as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, "Reviewed. Agents cleared for the "
                                      "library may now read this entry.")
        return _private(HttpResponseRedirect(target))
    transitions = {
        "draft": ("draft", "draft", "Back to draft. No agent reads this "
                                    "entry now."),
        "retire": ("retired", "retire", "Retired. No agent reads this entry "
                                        "now."),
        "reject": ("rejected", "reject", "Rejected. It stays in the history."),
        "restore": ("draft", "restore", "Restored as a draft."),
    }
    if action not in transitions:
        raise Http404
    status, via, said = transitions[action]
    curate.set_status(e, status, request.user, note=note, via=via)
    messages.success(request, said)
    return _private(HttpResponseRedirect(target))
