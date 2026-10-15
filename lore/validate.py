"""One validator for every way into the Lore (import, review, admin).

`check(entry_dict, mode)` returns `(errors, warnings)`, each a list of
`(code, message)`. The dict is the catalogue schema (lore/importer.py):
the importer hands it the file's entry, the admin and the review page hand
it `curate.export_dict(entry)`. Codes V01-V27 and W01-W03 are the spec's
(scratchpad lore/spec.md §6); messages are English.

Rules that keep the hard rules:
  V11  no quotation run of 200+ characters (own words)
  V12  no fence, marker or tag an agent's reader would parse (data, never
       instructions)
  V13  English only
  V14  nothing about our own account or book
  V24  no private term (the list lives outside git, on purpose)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from django.conf import settings

from . import constants as C

SCHEMA_KEYS = frozenset({
    "slug", "kind", "title", "summary", "mechanism", "works_when",
    "fails_when", "evidence", "documented", "reputed", "evidence_grade",
    "related", "small_account", "sauron_code", "tags", "accessed",
})
OVERLAY_KEYS = frozenset({"asset_classes", "regimes_works", "regimes_breaks",
                          "horizons", "families"})
#: Keys the export adds and an import accepts back without complaint.
EXPORT_KEYS = frozenset({"status", "reviewed_at", "proposed_by", "origin"})
SOURCE_KEYS = frozenset({"title", "by", "url", "date", "type", "note",
                         "date_kind", "quote", "found_via"})

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
DATE_RE = re.compile(r"^\d{4}(-\d{2}){0,2}$")
QUOTE_RUN_RE = re.compile("[\"“”«»]([^\"“”«»]{200,})[\"“”«»]")
FENCE_TOKENS = ("```", "<<", ">>", "lore_library")
ANGLE_RE = re.compile(r"<[A-Za-z/!?]")
#: Two or more DISTINCT of these in one text and it is not English. A local
#: copy of the house list (tests/test_telegram_house_style.py), because
#: production code does not import tests.
FRENCH_WORDS = ("le", "la", "les", "des", "du", "une", "est", "pour",
                "avec", "sur", "vous", "dans", "mais", "sont")
NON_ASCII_LETTER_SHARE = 0.01
ACCOUNT_RE = re.compile(
    r"\b(our|my|your|the operator's)\s+"
    r"(account|balance|equity|book|portfolio|positions|trades)\b", re.I)
MONEY_RE = re.compile(r"(?:[$€£]\s?\d|\d\s?(?:usd|eur|gbp|dollars?|euros?)\b)",
                      re.I)
LONG_DIGITS_RE = re.compile(r"\d{8,}")
HTTP_RE = re.compile(r"^https?://\S+$")

TEXT_FIELDS = ("title", "summary", "mechanism")


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def sentences(text: str) -> list:
    return [s for s in SENTENCE_SPLIT.split((text or "").strip()) if s]


def private_terms() -> list:
    """The private terms: LORE_PRIVATE_TERMS (comma separated) in the
    environment, else private/lore/private_terms.txt, one a line. Never in
    git: a list of such terms in public code would itself leak them."""
    raw = os.environ.get("LORE_PRIVATE_TERMS", "")
    terms = [t.strip().lower() for t in raw.split(",") if t.strip()]
    if terms:
        return terms
    lore_dir = getattr(settings, "LORE_DIR", None)
    if not lore_dir:
        return []
    path = Path(lore_dir) / "private_terms.txt"
    try:
        if path.is_file():
            return [line.strip().lower() for line in
                    path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")]
    except OSError:
        return []
    return []


def all_texts(d: dict):
    """Every free-text value of the entry, with the field it sits in."""
    for f in TEXT_FIELDS:
        yield f, _text(d.get(f))
    ww = d.get("works_when") or {}
    if isinstance(ww, dict):
        yield "works_when", _text(ww.get("regimes"))
        for a in ww.get("asset_classes") or []:
            yield "markets", _text(a)
    for i, item in enumerate(d.get("fails_when") or [], 1):
        if isinstance(item, dict):
            yield f"fails_when[{i}]", _text(item.get("how"))
            yield f"fails_when[{i}].episode", _text(item.get("episode"))
    for i, item in enumerate(d.get("evidence") or [], 1):
        if isinstance(item, dict):
            yield f"S{i}.title", _text(item.get("title"))
            yield f"S{i}.by", _text(item.get("by"))
            yield f"S{i}.note", _text(item.get("note"))
            yield f"S{i}.quote", _text(item.get("quote"))
    for side in ("documented", "reputed"):
        for i, item in enumerate(d.get(side) or [], 1):
            if isinstance(item, dict):
                yield f"{side}[{i}]", _text(item.get("claim"))
                yield f"{side}[{i}].basis", _text(item.get("basis"))
    sa = d.get("small_account") or {}
    if isinstance(sa, dict):
        yield "small_account.can", _text(sa.get("can"))
        yield "small_account.cannot", _text(sa.get("cannot"))
    for i, item in enumerate(d.get("sauron_code") or [], 1):
        if isinstance(item, dict):
            yield f"sauron_code[{i}]", _text(item.get("note"))
    for t in d.get("tags") or []:
        yield "tags", _text(t)


def looks_french(text: str) -> bool:
    low = " " + re.sub(r"[^a-zà-ÿ]+", " ", (text or "").lower()) + " "
    hits = {w for w in FRENCH_WORDS if f" {w} " in low}
    return len(hits) >= 2


NAME_RE = re.compile(r"\b[A-ZÀ-Þ][\wÀ-ÿ'-]*")


def too_many_non_ascii_letters(text: str) -> bool:
    """More than 1% of the letters outside ASCII, names excepted: a word
    opening with a capital is a name ("López", "Martín-Utrera") and its
    accents are not a language."""
    rest = NAME_RE.sub(" ", text or "")
    letters = [c for c in rest if c.isalpha()]
    if not letters:
        return False
    foreign = sum(1 for c in letters if ord(c) > 127)
    return foreign / len(letters) > NON_ASCII_LETTER_SHARE


def check(d: dict, mode: str = "import") -> tuple:
    """(errors, warnings) for one entry dict. `mode` is `import`, `review`
    or `admin`; review adds V27, import adds V25 and V26."""
    errors: list = []
    warnings: list = []
    err = errors.append
    if not isinstance(d, dict):
        return [("V25", "The entry is not an object.")], warnings

    # V25 unknown keys (import only: an export carries a few more).
    if mode == "import":
        for key in sorted(set(d) - SCHEMA_KEYS - OVERLAY_KEYS - EXPORT_KEYS):
            err(("V25", f'Unknown field "{key}"; the catalogue schema has '
                        f"no such field."))
        if d.get("origin") == "sauron":
            err(("V26", "Imports cannot create Sauron lessons."))

    origin = d.get("origin") or "world"
    kind = d.get("kind")
    if kind not in C.KIND_KEYS:
        err(("V01", f"Unknown kind: {kind}."))
    slug = _text(d.get("slug"))
    if (not C.SLUG_RE.match(slug) or not 3 <= len(slug) <= 60
            or slug in C.RESERVED_SLUGS):
        err(("V02", "Slug must be 3 to 60 lowercase letters, digits or "
                    "hyphens, and not a reserved word."))

    title = _text(d.get("title")).strip()
    if not 3 <= len(title) <= C.CAPS["title"]:
        err(("V04", '"title" is required.'))
    summary = _text(d.get("summary")).strip()
    n_sent = len(sentences(summary))
    if not 4 <= n_sent <= 8:
        err(("V03", f"The summary must be 4 to 8 sentences (it has {n_sent})."))
    if not _text(d.get("mechanism")).strip():
        err(("V04", '"mechanism" is required.'))
    ww = d.get("works_when") if isinstance(d.get("works_when"), dict) else {}
    if not _text(ww.get("regimes")).strip():
        err(("V04", '"works_when" is required.'))

    # V20 caps.
    sa = d.get("small_account") if isinstance(d.get("small_account"), dict) else {}
    for field, value, cap in (
            ("summary", summary, C.CAPS["summary"]),
            ("mechanism", _text(d.get("mechanism")), C.CAPS["mechanism"]),
            ("works_when", _text(ww.get("regimes")), C.CAPS["works_when"]),
            ("markets", "; ".join(_text(a) for a in ww.get("asset_classes") or []),
             C.CAPS["markets_text"]),
            ("small_account.can", _text(sa.get("can")), C.CAPS["small_account_can"]),
            ("small_account.cannot", _text(sa.get("cannot")),
             C.CAPS["small_account_cannot"])):
        if len(value) > cap:
            err(("V20", f'"{field}" is {len(value)} characters; the limit is '
                        f"{cap}."))

    # Sources.
    evidence = d.get("evidence") if isinstance(d.get("evidence"), list) else []
    if origin == "world" and not evidence:
        err(("V05", "Every entry needs at least one source."))
    n_src = len(evidence)
    for i, s in enumerate(evidence, 1):
        if not isinstance(s, dict):
            err(("V06", f"Source S{i} has no link."))
            continue
        for key in sorted(set(s) - SOURCE_KEYS):
            if mode == "import":
                err(("V25", f'Unknown field "{key}" on source S{i}; the '
                            f"catalogue schema has no such field."))
        if mode == "import" and "found_via" in s:
            # Only a person on the library page marks a source opened
            # (curate.mark_source_opened); a file never vouches for it.
            err(("V25", f'Source S{i} carries "found_via"; an import cannot '
                        f"say a source was opened. Mark it opened on the "
                        f"library page."))
        url = _text(s.get("url")).strip()
        skind = s.get("type")
        if skind not in C.SOURCE_KIND_KEYS:
            err(("V22", f"Unknown source kind for S{i}: {skind}."))
        if skind == "record":
            if origin != "sauron":
                err(("V23", "Only a Sauron lesson may cite an internal "
                            "record as its source."))
            if not url.startswith("/"):
                err(("V06", f"Source S{i} has no link."))
        elif not HTTP_RE.match(url):
            err(("V06", f"Source S{i} has no link."))
        if not _text(s.get("title")).strip():
            err(("V06", f"Source S{i} has no title."))
        if not _text(s.get("by")).strip():
            err(("V06", f"Source S{i} names no author or publisher."))
        date = _text(s.get("date")).strip()
        if not date or s.get("date_kind") not in C.DATE_KIND_KEYS:
            err(("V06", f"Source S{i} has no usable date."))
        elif not DATE_RE.match(date):
            err(("V07", f"Source S{i}: the date must read YYYY, YYYY-MM or "
                        f"YYYY-MM-DD."))
        quote = _text(s.get("quote"))
        if len(quote) > C.CAPS["quote"]:
            err(("V10", "A quote must be 300 characters or fewer."))
        if quote.strip() and not _text(s.get("by")).strip():
            err(("V10", "A quote must name who said it."))
        if len(_text(s.get("note"))) > C.CAPS["source_note"]:
            err(("V20", f'"S{i}.note" is {len(_text(s.get("note")))} '
                        f'characters; the limit is {C.CAPS["source_note"]}.'))

    # Claims.
    def _cites(item):
        src = item.get("src") if isinstance(item, dict) else None
        return src if isinstance(src, list) else []

    documented = d.get("documented") if isinstance(d.get("documented"), list) else []
    reputed = d.get("reputed") if isinstance(d.get("reputed"), list) else []
    fails = d.get("fails_when") if isinstance(d.get("fails_when"), list) else []
    if not documented:
        err(("V08", "An entry needs at least one documented claim."))
    for i, c in enumerate(documented, 1):
        if not _cites(c):
            err(("V08", f"Documented claim {i} cites no source."))
        for k in _cites(c):
            if not isinstance(k, int) or not 0 <= k < n_src:
                err(("V08", f"Claim {i} cites S{k + 1 if isinstance(k, int) else k}, "
                            f"which does not exist."))
    for i, c in enumerate(reputed, 1):
        if not isinstance(c, dict) or not _text(c.get("basis")).strip():
            err(("V09", f"Reputed claim {i} must say why it is only reputed."))
        for k in _cites(c):
            if not isinstance(k, int) or not 0 <= k < n_src:
                err(("V08", f"Claim {i} cites S{k + 1 if isinstance(k, int) else k}, "
                            f"which does not exist."))
    for i, c in enumerate(fails, 1):
        for k in _cites(c):
            if not isinstance(k, int) or not 0 <= k < n_src:
                err(("V08", f"Claim {i} cites S{k + 1 if isinstance(k, int) else k}, "
                            f"which does not exist."))

    # Vocabularies.
    grade = d.get("evidence_grade")
    if grade not in C.GRADE_KEYS:
        err(("V21", f"Evidence grade {grade} is not one of strong, moderate, "
                    f"weak, none."))
    fams = C.family_keys()
    for x in d.get("families") or []:
        if x not in fams:
            err(("V16", f"Unknown proving family: {x}."))
    regs = C.regime_keys()
    for key in ("regimes_works", "regimes_breaks"):
        for x in d.get(key) or []:
            if x not in regs:
                err(("V17", f"Unknown regime: {x}."))
    for x in d.get("asset_classes") or []:
        if x not in C.ASSET_CLASS_KEYS:
            err(("V18", f"Unknown asset class: {x}."))
    for x in d.get("horizons") or []:
        if x not in C.HORIZON_KEYS:
            err(("V19", f"Unknown horizon: {x}."))
    if mode == "review":
        if not d.get("asset_classes") or (kind == "strategy"
                                          and not d.get("horizons")):
            err(("V27", "Tag the asset classes and the horizon before "
                        "review."))

    # Text rules, over every text.
    terms = private_terms()
    seen_codes = set()
    for field, text in all_texts(d):
        if not text:
            continue
        m = QUOTE_RUN_RE.search(text)
        if m:
            err(("V11", f"This text quotes {len(m.group(1))} characters; "
                        f"write it in our own words and keep any quote "
                        f"short and attributed."))
        token = next((t for t in FENCE_TOKENS if t in text), None)
        if token is None:
            am = ANGLE_RE.search(text)
            token = am.group(0) if am else None
        if token is not None:
            err(("V12", f'This text contains "{token}", which agents\' '
                        f"readers would parse. Rephrase it."))
        if looks_french(text):
            err(("V13", "This text looks French; the platform is English "
                        "only."))
        elif too_many_non_ascii_letters(text):
            err(("V13", "This text has too many non-English letters."))
        if ACCOUNT_RE.search(text):
            err(("V14", "This text names our own account or book; the "
                        "library is about the world."))
        if origin == "sauron" and (MONEY_RE.search(text)
                                   or LONG_DIGITS_RE.search(text)):
            err(("V15", "A lesson cannot carry a money amount or a long "
                        "identifier; say it in R, rates and counts."))
        low = text.lower()
        for term in terms:
            if term and term in low and "V24" not in seen_codes:
                seen_codes.add("V24")
                err(("V24", "This text names a private term; the library is "
                            "about the world."))

    # Warnings.
    if kind == "fund_playbook" and evidence:
        practitioner_only = all(isinstance(s, dict)
                                and s.get("type") == "practitioner"
                                for s in evidence)
        if practitioner_only:
            for i, c in enumerate(documented, 1):
                if re.search(r"\d", _text(c.get("claim"))):
                    warnings.append(("W03", f"Documented claim {i} about a "
                                            f"fund rests only on "
                                            f"practitioner sources; consider "
                                            f"moving it to reputed."))
    return errors, warnings


def code_ref_exists(ref: str) -> bool:
    """`path:line` names a file in this tree and a line it has."""
    m = re.match(r"^([\w./-]+):(\d+)$", str(ref or ""))
    if not m:
        return False
    path = Path(settings.BASE_DIR) / m.group(1)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            n = sum(1 for _ in fh)
    except OSError:
        return False
    return int(m.group(2)) <= n


def problems_text(errors) -> str:
    return "; ".join(f"{code} {msg}" for code, msg in errors)
