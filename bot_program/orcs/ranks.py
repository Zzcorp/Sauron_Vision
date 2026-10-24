"""THE RANKS (spec §6.9), pure: the authority ladder made visible. A rank
belongs to the lineage (the OrcSeat), is earned and lost by the record,
and never changes risk by itself.

In O1 every seat is L0, so every Orc reads "L0 · Snaga": it watches and
writes, in shadow. O2 adds the record a rank is earned on (n of 20, the
provisional and coin-toss qualifiers) and the White Hand mark.
"""

#: level -> (rank, badge), §6.9's table.
RANKS = {0: ("Snaga", "○"), 1: ("Tracker", "◔"), 2: ("Warg-rider", "◑"),
         3: ("Standard-bearer", "◕"), 4: ("Chieftain", "●")}
#: What each rank holds (§6.9), in the words the pages and /orc print.
HOLDS = {0: "watches and writes: shadow only",
         1: "reduces: plan-clause exits, 4h tightens",
         2: "rides the trail: trail ownership, lock waivers",
         3: "presses a winner: adds, the one re-entry",
         4: "widens with a cut; reverses"}


def _level(level) -> int:
    try:
        n = int(level)
    except (TypeError, ValueError):
        return 0
    return n if n in RANKS else 0


def name(level) -> str:
    """The rank's name: "Snaga" for L0 (and for any level unread)."""
    return RANKS[_level(level)][0]


def badge(level) -> str:
    return RANKS[_level(level)][1]


def holds(level) -> str:
    return HOLDS[_level(level)]


def level_t(level) -> str:
    """"L0 · Snaga"."""
    n = _level(level)
    return f"L{n} · {RANKS[n][0]}"
