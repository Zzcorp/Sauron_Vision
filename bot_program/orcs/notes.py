"""The Orc's card (spec §9.5): what the Horde and the pages read without a
query per row. O1a keeps the last three journal entries, refreshed at
every append; O1c adds the last wake's `intellect` (its score, band, the
day's class and "no model (O1: code only)"), the `integrity` flag, the
next metronome (`next_wake_due`) and the last three `drums` heard; O1d
reads them (notes.for_rows, notes.for_classes and the Horde's O1 fields).
"""

CARD_VERSION = 1
#: The journal entries the card keeps, newest last.
CARD_JOURNAL = 3
#: The drums heard the card keeps, newest last.
CARD_DRUMS = 3
#: Journal kinds kept off the card's lines (O1c: a detected wake is a
#: record for replay; its numbers ride the card's `intellect`).
OFF_CARD_KINDS = ("wake",)
#: A drum's kind in the card's words.
DRUM_WORDS = {"stop_hit": "a stop hit", "sweep": "a sweep",
              "thesis_turned": "a thesis turned", "level_break":
              "a level break", "news_shock": "a news shock",
              "print_surprise": "a print surprise", "fill": "a fill",
              "lock": "a lock"}


def _line(entry) -> dict:
    at = getattr(entry, "at", None)
    return {"at": at.isoformat() if hasattr(at, "isoformat") else str(at or ""),
            "kind": str(getattr(entry, "kind", "") or ""),
            "author": str(getattr(entry, "author", "") or ""),
            "t": str(getattr(entry, "headline", "") or "")}


def _drum(entry) -> dict:
    body = getattr(entry, "body", None) or {}
    at = getattr(entry, "at", None)
    return {"kind_t": DRUM_WORDS.get(str(body.get("drum_kind") or ""),
                                     "a drum"),
            "from_symbol": str(body.get("symbol") or ""),
            "relation": str(body.get("relation") or ""),
            "at": at.isoformat() if hasattr(at, "isoformat") else str(
                at or "")}


def refresh(orc, *, entry=None, journal_entry=True, extra=None) -> dict:
    """The Orc's card with `entry` appended (no query), set on `orc.card`
    and returned; the caller saves it in the same transaction as the entry.
    Without an entry the last three are read again (one query).
    `journal_entry` False keeps `entry` off the lines; `extra` merges keys
    into the card (O1c's intellect, integrity, next_wake_due)."""
    card = dict(orc.card or {}) if isinstance(orc.card, dict) else {}
    journal = [j for j in (card.get("journal") or []) if isinstance(j, dict)]
    if entry is not None:
        if journal_entry and getattr(entry, "kind", "") not in OFF_CARD_KINDS:
            journal.append(_line(entry))
        if getattr(entry, "kind", "") == "drum":
            drums = [d for d in (card.get("drums") or [])
                     if isinstance(d, dict)]
            drums.append(_drum(entry))
            card["drums"] = drums[-CARD_DRUMS:]
    elif journal_entry:
        from bot_program.orcs.models import OrcJournal
        rows = list(OrcJournal.objects.filter(orc_id=orc.pk)
                    .exclude(kind__in=OFF_CARD_KINDS)
                    .order_by("-at", "-id")[:CARD_JOURNAL])
        journal = [_line(e) for e in reversed(rows)]
    if isinstance(extra, dict):
        card.update(extra)
    card["v"] = CARD_VERSION
    card["journal"] = journal[-CARD_JOURNAL:]
    orc.card = card
    return card
