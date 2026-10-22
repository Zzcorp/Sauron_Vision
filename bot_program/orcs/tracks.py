"""The arms of the grade (spec §6.1), seeded at birth. O1a seeds the care
ghost; O1b adds the playbook and the multi-ghost policies to the arms born
here (ARMS_AT_BIRTH, SEEDERS) and steps them.

THE CARE GHOST RUNS ON ITS OWN STATE (§3.3). It is seeded ONCE, here, from
the row's metadata["care"] (or from the entry when the care has not met
the row yet) — the one time it reads the row — before any Orc candidate
can exist. From then on it is stepped on its own state, never reseeded, so
an Orc's tightening can never leak into the counterfactual it is graded
against.

Its venue stop is the stop the VENUE holds at birth, the row's
`stop_loss` (§2.1; the mirror itself writes care["venue_stop"] from it,
position_care.py:776), never only the mirror's record: a hand edit or the
engine's own break-even moves the venue's stop without touching that
record, and a ghost seeded on the initial stop would run looser than the
position ever was. The mirror's last accepted level is kept beside it as
`mirror_venue_stop`.
"""

ARMS_AT_BIRTH = ("care",)
#: The care's own keys the ghost carries (position_care.plan's state).
CARE_KEYS = ("peak", "worst", "since", "soft_stop", "soft_why", "venue_stop",
             "scaled_out")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def seed_care(orc, trade) -> dict:
    from bot_program.orcs.facts import initial_stop
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    so = meta.get("scale_out") if isinstance(meta.get("scale_out"),
                                             dict) else {}
    entry = _f(trade.entry_price)
    state = {k: care.get(k) for k in CARE_KEYS}
    state["scaled_out"] = bool(care.get("scaled_out"))
    # the stop the venue holds now, else the mirror's record of it
    state["mirror_venue_stop"] = _f(care.get("venue_stop"))
    state["venue_stop"] = (_f(trade.stop_loss)
                           if trade.stop_loss is not None
                           else state["mirror_venue_stop"])
    if state["peak"] is None:
        state["peak"] = entry
    if state["worst"] is None:
        state["worst"] = entry
    qty_open = _f(trade.qty)
    state.update({
        # the root's BIRTH size: a scaled-out row's original, else its own
        "qty": _f(so.get("original_qty")) or qty_open,
        "qty_open": qty_open,
        "entry": entry,
        "initial_stop": initial_stop(trade),
        "side": str(trade.side or "").upper(),
        "banked": ([{"qty": _f(so.get("qty")), "price": _f(so.get("price")),
                     "r": _f(so.get("r"))}] if care.get("scaled_out") and so
                   else []),
        "seeded_from": "care" if care else "entry",
        "last_tick_at": None,
    })
    return state


SEEDERS = {"care": seed_care}


def seed_at_birth(orc, trade) -> list:
    """One OrcTrack per arm born with the idea, created once: a second call
    finds them and writes nothing."""
    from bot_program.orcs.models import OrcTrack
    out = []
    for arm in ARMS_AT_BIRTH:
        track, created = OrcTrack.objects.get_or_create(
            orc=orc, arm=arm,
            defaults={"state": SEEDERS[arm](orc, trade), "open": True})
        out.append(track)
    return out
