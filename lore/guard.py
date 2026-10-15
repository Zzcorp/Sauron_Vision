"""The background scrub: for readers whose words reach people who cannot
see the library. Removes LORE markers and any library tag fragment,
hyphenated shown slugs (single-word slugs are ordinary words), and every
sentence that shares an eight-word run with the shown text. The count of
removals goes to LoreRead.scrubbed.
"""
from __future__ import annotations

import re

from .render import shingles

LORE_MARKER_RE = re.compile(r"<<\s*LORE\s*:[^>]*>>", re.I)
TAG_RE = re.compile(r"</?\s*(?:lore_library|entry)\b[^>\n]*>?", re.I)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def scrub(text, block) -> tuple:
    """(text, n): the text with what the library could be recognised by
    taken out, and how many removals were made."""
    text = str(text or "")
    if not text or block is None or not getattr(block, "text", ""):
        return text, 0
    n = 0
    text, k = LORE_MARKER_RE.subn("", text)
    n += k
    text, k = TAG_RE.subn("", text)
    n += k
    for slug in getattr(block, "slugs", ()) or ():
        if "-" not in slug:
            continue
        text, k = re.subn(r"(?<![\w-])" + re.escape(slug) + r"(?![\w-])", "",
                          text, flags=re.I)
        n += k
    known = getattr(block, "shingles", None) or frozenset()
    if known:
        kept = []
        for para in text.split("\n"):
            parts = []
            for sentence in SENTENCE_SPLIT.split(para):
                if sentence and shingles(sentence) & known:
                    n += 1
                    continue
                parts.append(sentence)
            kept.append(" ".join(p for p in parts if p))
        text = "\n".join(kept)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(), n


def _deep(value, block) -> tuple:
    """(value, n): every string inside a dict or list scrubbed, recursively;
    keys and other values are left as they are."""
    if isinstance(value, str):
        return scrub(value, block)
    if isinstance(value, dict):
        n = 0
        for key in list(value):
            value[key], k = _deep(value[key], block)
            n += k
        return value, n
    if isinstance(value, list):
        n = 0
        for i, item in enumerate(value):
            value[i], k = _deep(item, block)
            n += k
        return value, n
    return value, 0


def scrub_briefing(parsed: dict, block) -> tuple:
    """The strategist's parsed JSON with its prose fields scrubbed:
    outlook_md and posture_rationale, and EVERY string inside the watchlist
    and the ideas (kind, ref, what_to_watch, summary, hypothesis_payload and
    any key the model adds), because _persist_briefing keeps those dicts
    whole and non-staff readers see them on /briefing/, in the email and in
    every research snapshot. A watchlist or ideas value that is not a list
    is left for _persist_briefing to drop. Returns (parsed, n)."""
    if not isinstance(parsed, dict) or block is None or not getattr(block, "text", ""):
        return parsed, 0
    total = 0
    for key in ("outlook_md", "posture_rationale"):
        if isinstance(parsed.get(key), str):
            parsed[key], n = scrub(parsed[key], block)
            total += n
    for key in ("watchlist", "ideas"):
        items = parsed.get(key)
        if isinstance(items, list):
            parsed[key], n = _deep(items, block)
            total += n
    return parsed, total
