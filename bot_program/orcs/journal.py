"""The Orc's journal (spec §1.4): append-only. A fact carries an id (F41)
the model may later cite; the id runs per Orc, kept in `seen["fact_seq"]`
and taken under the Orc's row lock, with the card refreshed in the same
transaction. A drum heard (O1c, §4.7) is a fact with its own series
(DR3, `seen["drum_seq"]`). Nothing here updates or deletes an entry."""
from django.db import transaction
from django.utils import timezone

from bot_program.orcs import notes

#: OrcJournal.headline's column.
HEADLINE_MAX = 200
#: Each fact id series and the memory key its counter lives under.
SEQ_KEYS = {"F": "fact_seq", "DR": "drum_seq"}


def append(orc, kind, headline, *, author="code", body=None, fact=False,
           snapshot=None, facts_hash="", wake=None, at=None,
           block_hashes=None, remember=None, fields=None, id_prefix="F",
           card=True, card_extra=None):
    """Write one entry and return it. `remember` merges keys into the Orc's
    `seen` memory and `fields` sets Orc columns, both under the same lock,
    so the memory that decided the entry and the entry land together.
    The in-memory `orc` is updated to what was saved. `id_prefix` names
    the fact's series (F, or DR for a drum heard); `card` False keeps the
    entry off the card's journal lines (a detected wake, O1c), and
    `card_extra` merges keys into the card. `headline` may be a callable
    of the fact id it is given. The defaults are O1a's."""
    from bot_program.orcs.models import Orc, OrcJournal
    with transaction.atomic():
        locked = Orc.objects.select_for_update().get(pk=orc.pk)
        seen = dict(locked.seen or {})
        fact_id = ""
        if fact:
            prefix = str(id_prefix or "F")
            seq = SEQ_KEYS.get(prefix, f"{prefix.lower()}_seq")
            n = int(seen.get(seq) or 0) + 1
            seen[seq] = n
            fact_id = f"{prefix}{n}"
        if remember:
            seen.update(remember)
        # a headline that names its own id (a drum's "DR3: ...") is
        # written once the id is taken, under the same lock
        text = headline(fact_id) if callable(headline) else headline
        text = " ".join(str(text or "").split())
        if len(text) > HEADLINE_MAX:
            text = text[:HEADLINE_MAX - 1].rstrip() + "…"
        entry = OrcJournal.objects.create(
            orc_id=orc.pk, kind=str(kind), author=str(author),
            fact_id=fact_id, headline=text, body=dict(body or {}),
            snapshot=snapshot, facts_hash=str(facts_hash or ""), wake=wake,
            at=at or timezone.now(), block_hashes=list(block_hashes or []))
        locked.seen = seen
        notes.refresh(locked, entry=entry, journal_entry=card,
                      extra=card_extra)
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
