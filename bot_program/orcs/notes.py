"""The Orc's card (spec §9.5): what the Horde and the pages read without a
query per row. O1a keeps the last three journal entries, refreshed at
every append; O1d widens it (notes.for_rows, notes.for_classes and the
Horde's O1 fields).
"""

CARD_VERSION = 1
#: The journal entries the card keeps, newest last.
CARD_JOURNAL = 3


def _line(entry) -> dict:
    at = getattr(entry, "at", None)
    return {"at": at.isoformat() if hasattr(at, "isoformat") else str(at or ""),
            "kind": str(getattr(entry, "kind", "") or ""),
            "author": str(getattr(entry, "author", "") or ""),
            "t": str(getattr(entry, "headline", "") or "")}


def refresh(orc, *, entry=None) -> dict:
    """The Orc's card with `entry` appended (no query), set on `orc.card`
    and returned; the caller saves it in the same transaction as the entry.
    Without an entry the last three are read again (one query)."""
    card = dict(orc.card or {}) if isinstance(orc.card, dict) else {}
    if entry is not None:
        journal = [j for j in (card.get("journal") or [])
                   if isinstance(j, dict)]
        journal.append(_line(entry))
    else:
        from bot_program.orcs.models import OrcJournal
        rows = list(OrcJournal.objects.filter(orc_id=orc.pk)
                    .order_by("-at", "-id")[:CARD_JOURNAL])
        journal = [_line(e) for e in reversed(rows)]
    card["v"] = CARD_VERSION
    card["journal"] = journal[-CARD_JOURNAL:]
    orc.card = card
    return card
