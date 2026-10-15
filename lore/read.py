"""The read API: `block_for(agent, ...)` never raises and denies by default.

Order of checks: the agent is in POLICY; its switch is on; a staff viewer
when the policy needs one; the search over REVIEWED rows of the policy's
origins and kinds; fit to the cap; a LoreRead row (`ledger=False` skips
it: the show command and the tests tune caps without writing). The whole function
sits in one try: any exception returns an empty block with its reason,
the contract brain/context.py context_for_prompt keeps. Lore is data for
agents, never instructions: the block is fenced, and no lore text can
change a gate, a size, a limit or an order.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from . import render
from .policy import POLICY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoreBlock:
    text: str
    slugs: tuple
    n_matched: int
    n_shown: int
    n_full: int
    tokens_est: int
    cap_tokens: int
    corpus_version: str
    search_mode: str
    reason: str
    read_id: int | None
    shingles: frozenset = field(default=frozenset(), repr=False)


def empty(reason: str, cap: int = 0) -> LoreBlock:
    return LoreBlock("", (), 0, 0, 0, 0, cap, "", "simple", reason, None,
                     frozenset())


def corpus_version() -> str:
    """sha1 of (count, newest updated_at, highest id) of the reviewed rows,
    8 hex: the same database gives the same digest."""
    from django.db.models import Count, Max
    from .models import LoreEntry
    agg = LoreEntry.objects.filter(status="reviewed").aggregate(
        n=Count("id"), newest=Max("updated_at"), top=Max("id"))
    blob = f"{agg['n'] or 0}|{agg['newest'].isoformat() if agg['newest'] else ''}|{agg['top'] or 0}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


def payload_for(entry, *, with_replay: bool = True, origins=None,
                kinds=None) -> dict:
    """The plain dict render.py works on, read once from the rows.

    `related` names REVIEWED entries only (and, when a reader's policy is
    passed, only its origins and kinds): the importer links entries in any
    status, and a card must never point an agent at a draft, a rejected or
    a retired entry it is not cleared to read."""
    from .models import LoreLink
    from .replay import replay_lines
    sources = list(entry.sources.all().order_by("position"))
    claims = list(entry.claims.all().order_by("side", "position"))
    links = LoreLink.objects.filter(from_entry=entry, kind="related",
                                    to_entry__status="reviewed")
    if origins is not None:
        links = links.filter(to_entry__origin__in=list(origins))
    if kinds is not None:
        links = links.filter(to_entry__kind__in=list(kinds))
    related = list(links.order_by("to_entry__slug")
                   .values_list("to_entry__slug", flat=True))

    def _side(side):
        return [{"text": c.text, "basis": c.basis, "episode": c.episode,
                 "sources": list(c.sources or [])}
                for c in claims if c.side == side]

    return {
        "slug": entry.slug,
        "kind": entry.kind,
        "evidence_grade": entry.evidence_grade,
        "reviewed": (entry.reviewed_at.date().isoformat()
                     if entry.reviewed_at else ""),
        "title": entry.title,
        "summary": entry.summary,
        "mechanism": entry.mechanism,
        "works_when": entry.works_when,
        "regimes_works": entry.regimes_works,
        "regimes_breaks": entry.regimes_breaks,
        "markets": entry.classes,
        "horizons": entry.horizons,
        "breaks": _side("breaks"),
        "documented": _side("documented"),
        "reputed": _side("reputed"),
        "small_can": entry.small_account_can,
        "small_cannot": entry.small_account_cannot,
        "code_refs": list(entry.code_refs or []),
        "replay": replay_lines(entry.families) if with_replay else [],
        "sources": [{"position": s.position, "by": s.by, "title": s.title,
                     "kind": s.kind, "date": s.date_text, "url": s.url,
                     "found_via": s.found_via} for s in sources],
        "related": related,
        "n_sources": len(sources),
        "n_documented": sum(1 for c in claims if c.side == "documented"),
        "n_reputed": sum(1 for c in claims if c.side == "reputed"),
    }


def block_for(agent: str, *, query: str = "", kinds=(), classes=(),
              regimes=(), horizons=(), families=(), regime_now: str = "",
              viewer=None, source_ref: str = "", ledger: bool = True
              ) -> LoreBlock:
    policy = POLICY.get(agent)
    if policy is None:
        return empty("agent not cleared")
    try:
        from core.platform_control import is_component_enabled
        from core.views_book import is_staff
        from .models import LoreRead
        from .search import search

        if not is_component_enabled(policy.switch):
            return empty("switch off", policy.cap_tokens)
        if policy.needs_staff_viewer and not is_staff(viewer):
            return empty("viewer is not staff", policy.cap_tokens)
        kinds_eff = tuple(k for k in policy.kinds
                          if not kinds or k in set(kinds))
        regime_now = regime_now if regime_now in _regimes() else ""
        result = search(query, kinds=kinds_eff, classes=classes,
                        regimes=regimes, horizons=horizons,
                        families=families, statuses=("reviewed",),
                        origins=policy.origins, audience="staff",
                        regime_now=regime_now,
                        limit=max(policy.max_entries * 2, 10))
        if not result.entries:
            return empty("nothing matched", policy.cap_tokens)
        corpus = corpus_version()
        payloads = [payload_for(e, origins=policy.origins,
                                kinds=policy.kinds) for e in result.entries]
        text, slugs, n_full, tokens = render.fit(
            payloads, cap_tokens=policy.cap_tokens,
            max_cards=policy.max_cards, max_entries=policy.max_entries,
            corpus=corpus, n_matched=result.n_matched,
            regime_now=regime_now)
        if not slugs:
            return empty("nothing fits the cap", policy.cap_tokens)
        read_id = None
        if ledger:
            row = LoreRead.objects.create(
                agent=agent[:30], source_ref=(source_ref or "")[:80],
                terms=" ".join(result.terms)[:200],
                query_digest=(hashlib.sha1(query.encode("utf-8")).hexdigest()
                              if query else ""),
                filters={"kinds": list(kinds_eff), "classes": list(classes),
                         "regimes": list(regimes), "horizons": list(horizons),
                         "families": list(families),
                         "regime_now": regime_now},
                slugs=list(slugs), n_matched=result.n_matched,
                n_shown=len(slugs), n_full=n_full, tokens_est=tokens,
                corpus_version=corpus, search_mode=result.mode)
            read_id = row.pk
        return LoreBlock(text, slugs, result.n_matched, len(slugs), n_full,
                         tokens, policy.cap_tokens, corpus, result.mode, "",
                         read_id, render.shingles(text))
    except Exception as e:  # noqa: BLE001 — the contract: never raise
        logger.warning("[lore] block for %s unavailable: %s", agent,
                       type(e).__name__)
        return empty(f"library unavailable: {type(e).__name__}",
                     policy.cap_tokens)


def _regimes() -> tuple:
    try:
        from .constants import regime_keys
        return regime_keys()
    except Exception:  # noqa: BLE001
        return ()


def for_prompt(agent: str, **kw) -> str:
    return block_for(agent, **kw).text


def get(slug: str):
    """One reviewed entry, or None."""
    try:
        from .models import LoreEntry
        return LoreEntry.objects.filter(slug=slug, status="reviewed").first()
    except Exception:  # noqa: BLE001
        return None


def note_read(read_id, *, source_ref: str = "", scrubbed: int | None = None
              ) -> None:
    """Complete a ledger row once its domain row exists (the briefing id)
    and the scrub has counted."""
    if not read_id:
        return
    try:
        from .models import LoreRead
        fields = {}
        if source_ref:
            fields["source_ref"] = source_ref[:80]
        if scrubbed is not None:
            fields["scrubbed"] = int(scrubbed)
        if fields:
            LoreRead.objects.filter(pk=read_id).update(**fields)
    except Exception as e:  # noqa: BLE001
        logger.debug("[lore] ledger note failed: %s", type(e).__name__)
