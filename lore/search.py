"""Search over the library, portable (SQLite and PostgreSQL alike).

Filters run in SQL on the flat columns; the ranking is a BM25-lite over
the search text with field boosts and context boosts, then a relevance
floor so an unrelated question matches nothing and costs nothing. Fully
deterministic: score, then evidence grade, then slug. PostgreSQL full-text
waits for a later PR behind the same signature.

BM25's usual parameters, k1 about 1.2 and b = 0.75, follow Robertson and
Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond" (2009).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from django.db.models import Q

from . import constants as C
from .models import LoreEntry

TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_TERMS = 8
PREFILTER_CAP = 500
K1 = 1.2
B = 0.75
#: Field boosts: title or slug, tags, summary, the rest of the body.
BOOST_TITLE = 3.0
BOOST_TAGS = 2.0
BOOST_SUMMARY = 1.0
BOOST_BODY = 0.5
SLUG_EXACT_BONUS = 100.0
#: Context boosts, in score units; tune them with `manage.py lore show`.
CLASS_BOOST = 2.0
REGIME_BOOST = 2.0
FAMILY_BOOST = 3.0
GRADE_BOOST = 0.5
#: The relevance floor: shown only at this share of the top score or more.
FLOOR_SHARE = 0.25

STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does doing for from had
has have he her here hers him his how i if in into is it its just me my of
on or our ours she so some such than that the their theirs them then there
these they this those to too us was we were what when where which who whom
why will with would you your yours about after again against all am any
because before being below between both down during each few further more
most no nor not off once only other out over own same should through under
until up very while
sauron today now please tell explain think
""".split())

GRADE_RANK = {"strong": 0, "moderate": 1, "weak": 2, "none": 3}


@dataclass(frozen=True)
class SearchResult:
    entries: tuple
    n_matched: int
    mode: str
    terms: tuple
    note: str


def stem(word: str) -> str:
    """A light prefix stemmer: the stem is a substring of every inflected
    form, which is what a `contains` prefilter and a prefix count need.
    "es" comes off after a sibilant only (crashes, boxes); elsewhere the
    "s" alone (trades, funds)."""
    if len(word) < 4:
        return word
    if word.endswith("ies") and len(word) >= 6:
        return word[:-3]
    if word.endswith("ing") and len(word) >= 7:
        return word[:-3]
    if word.endswith("ed") and len(word) >= 5:
        return word[:-2]
    if word.endswith("es") and len(word) >= 5 and (
            word[-3] in "sxz" or word[-4:-2] in ("ch", "sh")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms_of(query: str) -> tuple:
    out = []
    for tok in TOKEN_RE.findall((query or "").lower()):
        if tok in STOPWORDS or len(tok) < 2:
            continue
        st = stem(tok)
        if st and st not in out:
            out.append(st)
        if len(out) >= MAX_TERMS:
            break
    return tuple(out)


def _tokens(text: str) -> list:
    return TOKEN_RE.findall((text or "").lower())


def _tf(tokens: list, term: str) -> int:
    return sum(1 for t in tokens if t.startswith(term))


def _or(field: str, values) -> Q:
    q = Q()
    for v in values:
        q |= Q(**{f"{field}__contains": f"|{str(v).lower()}|"})
    return q


def base_queryset(*, kinds=(), classes=(), regimes=(), horizons=(),
                  families=(), grades=(), tags=(), statuses=("reviewed",),
                  origins=(), audience="staff"):
    qs = LoreEntry.objects.all()
    if statuses:
        qs = qs.filter(status__in=list(statuses))
    if kinds:
        qs = qs.filter(kind__in=list(kinds))
    if origins:
        qs = qs.filter(origin__in=list(origins))
    if audience and audience != "staff":
        qs = qs.filter(audience=audience)
    if grades:
        qs = qs.filter(evidence_grade__in=list(grades))
    if classes:
        qs = qs.filter(_or("classes_flat", classes))
    if regimes:
        # An entry that breaks in this regime is as relevant as one that
        # works in it.
        qs = qs.filter(_or("regimes_works_flat", regimes)
                       | _or("regimes_breaks_flat", regimes))
    if horizons:
        qs = qs.filter(_or("horizons_flat", horizons))
    if families:
        qs = qs.filter(_or("families_flat", families))
    if tags:
        qs = qs.filter(_or("tags_flat", tags))
    return qs


def _context_boost(entry, *, classes, families, regime_now) -> float:
    boost = GRADE_BOOST * C.GRADE_WEIGHT.get(entry.evidence_grade, 0.0)
    if classes and set(entry.classes) & {c.lower() for c in classes}:
        boost += CLASS_BOOST
    if families and set(entry.families) & {f.lower() for f in families}:
        boost += FAMILY_BOOST
    if regime_now and (regime_now in entry.regimes_works
                       or regime_now in entry.regimes_breaks):
        boost += REGIME_BOOST
    return boost


def search(query: str = "", *, kinds=(), classes=(), regimes=(), horizons=(),
           families=(), grades=(), tags=(), statuses=("reviewed",),
           origins=(), audience="staff", regime_now="", limit=50
           ) -> SearchResult:
    qs = base_queryset(kinds=kinds, classes=classes, regimes=regimes,
                       horizons=horizons, families=families, grades=grades,
                       tags=tags, statuses=statuses, origins=origins,
                       audience=audience)
    terms = terms_of(query)
    raw = (query or "").strip().lower()

    if not terms:
        if not (regimes or classes or families or tags):
            return SearchResult((), 0, "simple", (), "no query and no regime, "
                                                     "class or family filter")
        rows = sorted(qs, key=lambda e: (GRADE_RANK.get(e.evidence_grade, 9),
                                         e.slug))
        return SearchResult(tuple(rows[:limit]), len(rows), "simple", (),
                            "filters only")

    prefilter = Q()
    for t in terms:
        prefilter |= Q(search_text__contains=t)
    if C.SLUG_RE.match(raw):
        prefilter |= Q(slug=raw)
    candidates = list(qs.filter(prefilter).order_by("slug")[:PREFILTER_CAP])
    if not candidates:
        return SearchResult((), 0, "simple", terms, "nothing matched")

    n_total = max(qs.count(), 1)
    bodies = {e.pk: _tokens(e.search_text) for e in candidates}
    avgdl = max(1.0, sum(len(b) for b in bodies.values()) / len(candidates))
    df = {t: sum(1 for b in bodies.values() if _tf(b, t)) for t in terms}
    idf = {t: math.log(1.0 + (n_total - df[t] + 0.5) / (df[t] + 0.5))
           for t in terms}

    scored = []
    for e in candidates:
        body = bodies[e.pk]
        title_toks = _tokens(f"{e.title} {e.slug.replace('-', ' ')} {e.slug}")
        tag_toks = _tokens(" ".join(e.tags))
        summary_toks = _tokens(e.summary)
        norm = K1 * (1.0 - B + B * len(body) / avgdl)
        score = 0.0
        head_hit = False
        body_hits = 0
        for t in terms:
            parts = 0.0
            for toks, boost in ((title_toks, BOOST_TITLE), (tag_toks, BOOST_TAGS),
                                (summary_toks, BOOST_SUMMARY), (body, BOOST_BODY)):
                tf = _tf(toks, t)
                if tf:
                    parts += boost * tf * (K1 + 1.0) / (tf + norm)
            if _tf(title_toks, t) or _tf(tag_toks, t):
                head_hit = True
            if _tf(body, t):
                body_hits += 1
            score += idf[t] * parts
        if raw == e.slug:
            score += SLUG_EXACT_BONUS
            head_hit = True
        score += _context_boost(e, classes=classes, families=families,
                                regime_now=regime_now)
        qualifies = head_hit or (2 * body_hits >= len(terms))
        if qualifies and score > 0:
            scored.append((score, e))
    if not scored:
        return SearchResult((), 0, "simple", terms, "nothing matched")
    top = max(s for s, _ in scored)
    kept = [(s, e) for s, e in scored if s >= FLOOR_SHARE * top]
    kept.sort(key=lambda se: (-se[0], GRADE_RANK.get(se[1].evidence_grade, 9),
                              se[1].slug))
    return SearchResult(tuple(e for _, e in kept[:limit]), len(kept),
                        "simple", terms, "")
