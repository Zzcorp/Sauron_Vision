"""Who may read the library, and how much: deny by default.

An agent absent from POLICY receives nothing. Each reader has a cap, the
kinds and origins it may see, a PlatformComponent switch (a missing row
reads OFF, core/platform_control.py), whether the asker must be staff, and
whether its words reach people who cannot see the library (then no
quotes, no names, no markers, and its output is scrubbed).

Never readers (tests/test_lore_fences.py): the Mind, the horizon, the
binding trade debate, the weekly reviewer, the news analyst, the next
steps, the consensus, anything under bot_program/ or portfolio/.
"""
from __future__ import annotations

from dataclasses import dataclass

ALL_KINDS = ("strategy", "fund_playbook", "episode", "concept", "lesson")
WORLD_KINDS = ("strategy", "concept", "episode", "fund_playbook")


@dataclass(frozen=True)
class Reader:
    cap_tokens: int
    max_cards: int          # compact cards before switching to short forms
    max_entries: int
    kinds: tuple
    origins: tuple
    switch: str             # PlatformComponent key
    needs_staff_viewer: bool
    background_only: bool   # its words reach non-staff: scrubbed output


POLICY = {
    "research": Reader(3000, 3, 8, ALL_KINDS, ("world", "sauron"),
                       "lore_staff", True, False),
    "strategist": Reader(1500, 0, 6, WORLD_KINDS, ("world",),
                         "lore_background", False, True),
}

SWITCHES = tuple(sorted({r.switch for r in POLICY.values()}))
