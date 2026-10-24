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
    of the fact id it is given. The defaults are O1a's.

    A `remember` value may be a callable of the LOCKED memory's current
    value for its key (O1c): a list or a pending wake another writer may
    have grown since this caller read the Orc is then merged under the
    lock, never overwritten from a stale copy (merge_seen)."""
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
            _merge(seen, remember)
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


def _merge(seen, keys) -> None:
    """seen[k] = v, or v(seen.get(k)) for a callable v (read under the
    lock the caller holds)."""
    for key, value in (keys or {}).items():
        seen[key] = value(seen.get(key)) if callable(value) else value


def remember(orc, *, fields=None, card_extra=None, **keys):
    """Merge keys into the Orc's `seen` memory under its lock, with no
    entry: what the observer saw, so the next tick says nothing again. A
    callable value is applied to the locked memory's value (_merge).
    `fields` sets Orc columns and `card_extra` merges keys into the card,
    in the same save (O1c: a wake recorded in the tick)."""
    from bot_program.orcs.models import Orc
    with transaction.atomic():
        locked = Orc.objects.select_for_update().get(pk=orc.pk)
        seen = dict(locked.seen or {})
        _merge(seen, keys)
        locked.seen = seen
        update = ["seen"]
        if card_extra:
            card = dict(locked.card or {}) if isinstance(locked.card,
                                                        dict) else {}
            card.update(card_extra)
            locked.card = card
            update.append("card")
        for name, value in (fields or {}).items():
            setattr(locked, name, value)
            update.append(name)
        locked.save(update_fields=update)
    orc.seen = locked.seen
    if card_extra:
        orc.card = locked.card
    for name, value in (fields or {}).items():
        setattr(orc, name, value)


# ── merging the wake memory under the lock (O1c) ─────────────────────────
# The tick (`default`) and the census (`fast`) run in separate processes
# and each loads the Orc at its own start. The wake memory's lists are
# therefore never written from the copy in hand: each writer names what it
# ADDS or CONSUMES, and the merge runs on the locked row.

def add_keys(cap=None, keys=()):
    """A `remember` value: the locked list with `keys` appended once each,
    the newest `cap` kept (None: never trimmed)."""
    keys = [str(k) for k in keys or ()]

    def merge(cur):
        out = [k for k in (cur or []) if isinstance(k, str)]
        have = set(out)
        for k in keys:
            if k not in have:
                out.append(k)
                have.add(k)
        return out[-int(cap):] if cap else out
    return merge


def add_reasons(reasons=(), *, since=None, skip_keys=()):
    """A `remember` value for `wake_pending`: the locked pending wake with
    `reasons` appended once per key, none whose key is in `skip_keys` (the
    caller passes the locked memory's recorded keys through
    merge_seen)."""
    reasons = [r for r in reasons or () if isinstance(r, dict)]

    def merge(cur):
        pend = dict(cur) if isinstance(cur, dict) else {}
        have = {r.get("key") for r in pend.get("reasons") or []
                if isinstance(r, dict)}
        out = [r for r in pend.get("reasons") or [] if isinstance(r, dict)]
        skip = set(skip_keys or ())
        for r in reasons:
            if r.get("key") in have or r.get("key") in skip:
                continue
            have.add(r.get("key"))
            out.append(r)
        if not out:
            return None
        pend["reasons"] = out
        if since is not None:
            pend.setdefault("since", since)
        return pend
    return merge


def consume_reasons(keys=()):
    """A `remember` value for `wake_pending`: the locked pending wake less
    the reasons whose keys a recorded wake carried; None once empty. A
    reason another writer queued since stays for the next tick."""
    gone = set(keys or ())

    def merge(cur):
        if not isinstance(cur, dict):
            return None
        left = [r for r in cur.get("reasons") or []
                if isinstance(r, dict) and r.get("key") not in gone]
        if not left:
            return None
        return {**cur, "reasons": left}
    return merge


def merge_seen(orc, fn):
    """Run `fn(seen)` on the LOCKED memory (a dict copy it may change in
    place) and save it when it changed; return what `fn` returned. The
    in-memory `orc` is updated to the locked memory."""
    import copy

    from bot_program.orcs.models import Orc
    with transaction.atomic():
        locked = Orc.objects.select_for_update().get(pk=orc.pk)
        before = copy.deepcopy(locked.seen or {})
        seen = copy.deepcopy(before)
        out = fn(seen)
        if seen != before:
            locked.seen = seen
            locked.save(update_fields=["seen"])
    orc.seen = locked.seen
    return out
