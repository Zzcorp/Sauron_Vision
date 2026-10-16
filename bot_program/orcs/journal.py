"""The Orc's journal (spec §1.4): append-only. A fact carries an id (F41)
the model may later cite; the id runs per Orc, kept in `seen["fact_seq"]`
and taken under the Orc's row lock, with the card refreshed in the same
transaction. Nothing here updates or deletes an entry."""
from django.db import transaction
from django.utils import timezone

from bot_program.orcs import notes

#: OrcJournal.headline's column.
HEADLINE_MAX = 200


def append(orc, kind, headline, *, author="code", body=None, fact=False,
           snapshot=None, facts_hash="", wake=None, at=None,
           block_hashes=None, remember=None, fields=None):
    """Write one entry and return it. `remember` merges keys into the Orc's
    `seen` memory and `fields` sets Orc columns, both under the same lock,
    so the memory that decided the entry and the entry land together.
    The in-memory `orc` is updated to what was saved."""
    from bot_program.orcs.models import Orc, OrcJournal
    text = " ".join(str(headline or "").split())
    if len(text) > HEADLINE_MAX:
        text = text[:HEADLINE_MAX - 1].rstrip() + "…"
    with transaction.atomic():
        locked = Orc.objects.select_for_update().get(pk=orc.pk)
        seen = dict(locked.seen or {})
        fact_id = ""
        if fact:
            n = int(seen.get("fact_seq") or 0) + 1
            seen["fact_seq"] = n
            fact_id = f"F{n}"
        if remember:
            seen.update(remember)
        entry = OrcJournal.objects.create(
            orc_id=orc.pk, kind=str(kind), author=str(author),
            fact_id=fact_id, headline=text, body=dict(body or {}),
            snapshot=snapshot, facts_hash=str(facts_hash or ""), wake=wake,
            at=at or timezone.now(), block_hashes=list(block_hashes or []))
        locked.seen = seen
        notes.refresh(locked, entry=entry)
        update = ["seen", "card"]
        for name, value in (fields or {}).items():
            setattr(locked, name, value)
            update.append(name)
        locked.save(update_fields=update)
    orc.seen = locked.seen
    orc.card = locked.card
    for name, value in (fields or {}).items():
        setattr(orc, name, value)
    return entry


def remember(orc, **keys):
    """Merge keys into the Orc's `seen` memory under its lock, with no
    entry: what the observer saw, so the next tick says nothing again."""
    from bot_program.orcs.models import Orc
    with transaction.atomic():
        locked = Orc.objects.select_for_update().get(pk=orc.pk)
        seen = dict(locked.seen or {})
        seen.update(keys)
        locked.seen = seen
        locked.save(update_fields=["seen"])
    orc.seen = locked.seen
