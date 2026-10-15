"""The Lore's vocabularies, taken from the platform's own registries.

Regimes are the Mind's (brain/models.py BrainReport.REGIME_CHOICES without
`unknown`), asset classes are core.constants.AssetClass, proving families
are backtester/proving/families.py FAMILIES. Nothing here is a number any
code could read as a stop, a size, a threshold or a limit.
"""
from __future__ import annotations

import re

from core.constants import AssetClass

KINDS = (
    ("strategy", "Strategy"),
    ("fund_playbook", "Fund playbook"),
    ("episode", "Episode"),
    ("concept", "Concept"),
    ("lesson", "Sauron's lesson"),
)
KIND_KEYS = tuple(k for k, _ in KINDS)
#: Kinds an import may create; `lesson` is written only by the distiller.
IMPORTABLE_KINDS = ("strategy", "fund_playbook", "episode", "concept")

ORIGINS = (("world", "The world"), ("sauron", "Sauron's own record"))
STATUSES = (
    ("draft", "Draft"),
    ("reviewed", "Reviewed"),
    ("retired", "Retired"),
    ("rejected", "Rejected"),
)
STATUS_KEYS = tuple(k for k, _ in STATUSES)
AUDIENCES = (("staff", "Staff only"),)
PROPOSERS = (
    ("seed", "the seed"),
    ("staff", "staff"),
    ("distiller", "the distiller"),
    ("keeper", "the keeper"),
)
EVIDENCE_GRADES = (
    ("strong", "Strong"),
    ("moderate", "Moderate"),
    ("weak", "Weak"),
    ("none", "None"),
)
GRADE_KEYS = tuple(k for k, _ in EVIDENCE_GRADES)
#: For the search ranker's evidence boost (strong 1, moderate 0.66, ...).
GRADE_WEIGHT = {"strong": 1.0, "moderate": 0.66, "weak": 0.33, "none": 0.0}

SOURCE_KINDS = (
    ("paper", "Paper"),
    ("reporting", "Reporting"),
    ("regulator", "Regulator"),
    ("data", "Data"),
    ("practitioner", "Practitioner"),
    ("letter", "Fund letter"),
    ("filing", "Filing"),
    ("book", "Book"),
    ("court", "Court record"),
    ("record", "Internal record"),
)
SOURCE_KIND_KEYS = tuple(k for k, _ in SOURCE_KINDS)
DATE_KINDS = (
    ("published", "Published"),
    ("approximate", "Approximate"),
    ("accessed", "Accessed"),
)
DATE_KIND_KEYS = tuple(k for k, _ in DATE_KINDS)
FOUND_VIA = (("search_summary", "Search summary only"), ("opened", "Opened"))

CLAIM_SIDES = (
    ("documented", "Documented"),
    ("reputed", "Reputed, not proven"),
    ("breaks", "Breaks when"),
)
LINK_KINDS = (
    ("related", "Related"),
    ("illustrates", "Illustrates"),
    ("contradicts", "Contradicts"),
)
REVISION_VIAS = (
    ("import", "import"), ("admin", "admin"), ("review", "review"),
    ("draft", "draft"), ("retire", "retire"), ("restore", "restore"),
    ("reject", "reject"), ("distill", "distill"), ("keeper", "keeper"),
)

HORIZONS = (
    ("intraday", "Intraday"),
    ("days", "Days"),
    ("weeks", "Weeks"),
    ("months", "Months"),
    ("years", "Years"),
)
HORIZON_KEYS = tuple(k for k, _ in HORIZONS)

ASSET_CLASS_KEYS = tuple(k for k, _ in AssetClass.CHOICES)
ASSET_CLASS_LABELS = dict(AssetClass.CHOICES)

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED_SLUGS = frozenset(
    {"review", "search", "new", "export", "reads", "notes", "admin"})

#: Length caps on the text fields (the seed's longest summary is 1,215).
CAPS = {
    "title": 120,
    "summary": 1400,
    "mechanism": 1500,
    "works_when": 600,
    "markets_text": 400,
    "small_account_can": 600,
    "small_account_cannot": 600,
    "review_note": 300,
    "source_note": 600,
    "quote": 300,
}


def regime_choices():
    """The Mind's regimes without `unknown`."""
    from brain.models import BrainReport
    return [(k, v) for k, v in BrainReport.REGIME_CHOICES
            if k != BrainReport.REGIME_UNKNOWN]


def regime_keys():
    return tuple(k for k, _ in regime_choices())


def regime_labels():
    return dict(regime_choices())


def family_keys():
    from backtester.proving.families import FAMILIES
    return tuple(FAMILIES.keys())


def flat(values) -> str:
    """A list as the `"|a|b|"` string the flat columns hold (JSONField
    `contains` is unsupported on SQLite, where the suite runs)."""
    items = [str(v).strip().lower() for v in (values or []) if str(v).strip()]
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return "|" + "|".join(seen) + "|" if seen else ""


def unflat(text) -> list:
    return [p for p in (text or "").split("|") if p]
