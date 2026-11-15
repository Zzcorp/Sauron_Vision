"""THE TEMPERAMENTS (the O2 spec C.3-C.6, §4 Q14; O2c, 2026-11-15): the one
lead voice an Orc leans on, drawn just after its birth and fixed for life,
so OrcTemperamentGrade measures the temperament, never the situation it was
chosen for.

THE TABLE, version VERSION ("t1"), pure. Six temperaments, one per council
voice that can manage a single position, each with that voice as its one
lead voice, and a control with none (§4 Q14):

  striker      the Striker      the moment
  fixer        the Fixer        the repair
  skeptic      the Skeptic      the evidence
  awakened     the Awakened     the game behind the price
  executioner  the Executioner  why the trade fails
  champion     the Champion     why it works
  control      no lead voice

The Gambler's "all in" and the Opportunist's "elsewhere" fit no single
position's management, the Theorist posts to the hypothesis market and the
Emperor chairs the council (map_army C7). A later table is a new version:
an Orc keeps the version it drew under, and grades of two versions are
never pooled.

THE LANES are COPIED, word for word, from the prompts that hold them:
ai_agents/agents/council.py's Striker, Fixer, Skeptic and Awakened prompts
(their "Your lane is ..." sentence), and ai_agents/agents/trade_debate.py's
Executioner and Champion prompts, which carry no lane sentence: their
"Your only job is ..." stands for it. The package imports nothing of the
platform's agents (only the gateway, mind_gateway.py, may name them), so
tests/orcs/test_orc_o2c_temperaments.py, outside the package, pins each copy
to its prompt, and the voices' names with them. Nothing here reads a voice's
council weight.

THE DRAW (C.4). `draw` is pure: the temperament with the fewest Orcs on the
newborn's seat, the control counted like any other; a tie is broken by
random.Random(the root trade id), so one idea always draws the same.
`draw_quietly` is registered by birth.ensure on the commit of the birth, so
it runs after birth._create's transaction, never under the trade row's
lock (N1.2). It reads the switch `orcs_temperaments` (OFF: it returns and
writes nothing), then takes the Orc's row lock alone, within the entry
path's lock budget (ORC_LOCK_MONEY_MS, N8.3), and writes one `temperament`
entry by code that sets Orc.temperament. Under that lock an Orc whose
temperament is set is never drawn again (fixed for life, idempotent). An
Orc that could not draw (a lock that timed out, a failure) keeps '', as one
born while the switch was OFF does, and is never graded as a temperament.
It never raises. The draw counts the seat's Orcs without a lock: two births
on one seat in the same instant may draw alike, a balance off by one.

PS9 (C.5) shows the lead voice's name and lane as a view
(bot_program/orcs/dossier_position.py), and the grades are kept by
temperament (bot_program/orcs/grading.py, C.6).
"""
import logging
import random

logger = logging.getLogger(__name__)

#: The table's version: the grade's tag reads temperament:<name>:<version>.
VERSION = "t1"
#: The control: no lead voice (§4 Q14).
CONTROL = "control"
#: Each temperament's lead voices, in the draw's order: the six, then the
#: control.
LEADS = {
    "striker": ("striker",),
    "fixer": ("fixer",),
    "skeptic": ("skeptic",),
    "awakened": ("awakened",),
    "executioner": ("executioner",),
    "champion": ("champion",),
    CONTROL: (),
}
NAMES = tuple(LEADS)
#: A temperament's name in words.
LABELS = {"striker": "Striker", "fixer": "Fixer", "skeptic": "Skeptic",
          "awakened": "Awakened", "executioner": "Executioner",
          "champion": "Champion", CONTROL: "control"}
#: The voices' names, as the council writes them (council.VOICE_NAMES).
VOICE_NAMES = {"striker": "the Striker", "fixer": "the Fixer",
               "skeptic": "the Skeptic", "awakened": "the Awakened",
               "executioner": "the Executioner", "champion": "the Champion"}
#: Each voice's lane, word for word (council.py: StrikerAgent, FixerAgent,
#: SkepticAgent and AwakenedAgent's PROMPT; trade_debate.py: the
#: Executioner's and the Champion's system prompt).
LANES = {
    "striker": ("Your lane is the moment; how much to commit is the "
                "Emperor's, and what to repair is the Fixer's."),
    "fixer": ("Your lane is the repair: whether to act now is the "
              "Striker's, how much to commit is the Emperor's."),
    "skeptic": ("Your lane is the evidence: whether the trade fails is the "
                "Executioner's question, never yours, and you give no "
                "probability for the trade itself."),
    "awakened": ("Your lane is the game behind the price; whether a better "
                 "trade exists elsewhere is the Opportunist's question."),
    "executioner": ("Your only job is to find why it will FAIL: a regime it "
                    "fights, news against it, a rule whose real record is "
                    "thin or decaying, a stop that sits where the market "
                    "routinely reaches, a target that needs a move the "
                    "instrument rarely makes, costs that eat the edge, a "
                    "crowded side, a correlated book."),
    "champion": ("Your only job is to make the strongest honest case that "
                 "it will WORK: the rule's measured edge, the regime behind "
                 "it, the levels, the reward against the risk, the "
                 "timing."),
}


# ── the table's words (pure) ─────────────────────────────────────────────

def lanes_text(name) -> str:
    """PS9's words for temperament `name` (C.5): its name and version, then
    each lead voice's name and lane; "" for the control, for none and for
    a name of no table (PS9 then says so in its own words)."""
    name = str(name or "")
    leads = LEADS.get(name) or ()
    if not leads:
        return ""
    head = "Lead voice" if len(leads) == 1 else "Lead voices"
    voices = " ".join(f"{VOICE_NAMES[v]}. Its lane: {LANES[v]}"
                      for v in leads)
    return (f"Temperament {LABELS[name]} ({VERSION}), fixed for life. "
            f"{head}: {voices}")


def entry_line(name) -> str:
    """The draw's journal line (C.4): "Temperament: Striker (lead voices:
    the Striker)."; the control's "(lead voices: none)"."""
    name = str(name or "")
    voices = ", ".join(VOICE_NAMES[v] for v in LEADS.get(name) or ())
    return (f"Temperament: {LABELS.get(name, name)} "
            f"(lead voices: {voices or 'none'}).")


def page_line(name) -> str:
    """The Orc page's line (§1.3.7): "Striker: lead voice the Striker;
    drawn at birth, fixed for life (t1)"; "" for an Orc that drew none."""
    name = str(name or "")
    if not name:
        return ""
    voices = ", ".join(VOICE_NAMES[v] for v in LEADS.get(name) or ())
    lead = f"lead voice {voices}" if voices else "no lead voice"
    return (f"{LABELS.get(name, name)}: {lead}; drawn at birth, fixed for "
            f"life ({VERSION})")


def draw(counts, seed) -> str:
    """C.4, pure: the temperament with the fewest Orcs in `counts` ({name:
    Orcs on the seat}; a name of no table counts for nothing), the control
    included; a tie broken by random.Random(`seed`, the root trade id)."""
    counts = counts if isinstance(counts, dict) else {}
    have = {n: int(counts.get(n) or 0) for n in NAMES}
    low = min(have.values())
    tied = [n for n in NAMES if have[n] == low]
    return random.Random(int(seed or 0)).choice(tied)


# ── the draw, just after the birth ───────────────────────────────────────

def _seat_counts(locked) -> dict:
    """{name: the seat's other Orcs that drew it}, every name of the table
    (one read, no lock)."""
    from bot_program.orcs.models import Orc
    out = {n: 0 for n in NAMES}
    for name in (Orc.objects.filter(seat_id=locked.seat_id)
                 .exclude(pk=locked.pk).exclude(temperament="")
                 .values_list("temperament", flat=True)):
        if name in out:
            out[name] += 1
    return out


def draw_quietly(orc_pk) -> None:
    """The birth's on-commit step (C.4; birth.ensure registers it after
    _create): with `orcs_temperaments` ON, the newborn's one draw, written
    under its own row's lock within the entry path's budget; OFF, nothing.
    Never raises: an Orc that could not draw keeps ''."""
    try:
        from bot_program.orcs.switches import temperaments_on
        if not temperaments_on():
            return
        from django.db import transaction

        from bot_program.orcs import journal
        from bot_program.orcs.constants import ORC_LOCK_MONEY_MS
        with journal.lock_budget(ORC_LOCK_MONEY_MS), transaction.atomic():
            locked = journal.orc_lock(orc_pk)
            if locked.temperament:
                return
            counts = _seat_counts(locked)
            name = draw(counts, locked.root_trade_id)
            journal.append(locked, "temperament", entry_line(name),
                           author="code",
                           body={"temperament": name, "version": VERSION,
                                 "lead": list(LEADS[name]),
                                 "counts": counts},
                           fields={"temperament": name})
    except Exception as e:  # noqa: BLE001 — never stops a birth
        logger.warning("[orcs] Orc %s drew no temperament: %s", orc_pk, e)
