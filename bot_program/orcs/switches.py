"""The Orcs' switch (spec §10.4): `orcs`, System, OFF on arrival. It is not
a live-money switch (nothing here moves money) and the System group's
"all on" may turn it on. An unreadable switch reads OFF.

THE MINDS' FOUR GATES (the O2 spec A.1, A.2; O2a, 2026-11-05). A model
call needs all four: the platform master, `orcs`, `orcs_minds` and the
Orcs budget line above 0 (read through bot_program/orcs/mind_gateway.py,
the one module that names the budget). `gate_code` names the first one
that is OFF, `minds_on` says whether all four are ON. The tick never reads
them, and nothing here imports the gateway until it is asked: the tick's
import path never loads it.

THE ROUTER'S SWITCH (O2b, 2026-11-06): `orcs_router`, read by `router_on`,
decides which rung answers a wake the four gates let a model read: OFF r0,
ON the rung the router chose.

THE PROBES' SWITCH (O2b's probes, 2026-11-06): `orcs_probes`, read by
`probes_on`, is a model caller's own switch (N2, A.2): a probe needs it
beside the four gates. `caller_code` names a caller's own switch while it
is OFF, read before each probe, at its reservation and at the gateway."""
import logging

logger = logging.getLogger(__name__)

SWITCH = "orcs"
#: The key the switch is cached under in the tick's per-pass dict
#: (AssetBot._tick_broker_cache, reset at every manage_positions pass).
CACHE_KEY = "orcs:on"


def orcs_on(cache=None) -> bool:
    """True when the `orcs` component is ON. With the tick's per-pass dict,
    read once per pass. A missing row, or one that cannot be read, is OFF
    (core.platform_control.is_component_enabled)."""
    if isinstance(cache, dict) and CACHE_KEY in cache:
        return bool(cache[CACHE_KEY])
    try:
        from core.platform_control import is_component_enabled
        on = bool(is_component_enabled(SWITCH))
    except Exception as e:  # noqa: BLE001 — an unreadable switch is OFF
        logger.info("[orcs] the switch could not be read: %s", e)
        on = False
    if isinstance(cache, dict):
        cache[CACHE_KEY] = on
    return on


def _component_on(key) -> bool:
    """A component's row ON; a missing or unreadable one is OFF."""
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled(key))
    except Exception as e:  # noqa: BLE001 — an unreadable switch is OFF
        logger.info("[orcs] the switch %s could not be read: %s", key, e)
        return False


def gate_code() -> str:
    """The first of A.2's four gates that is OFF, as its code, in the
    order admission reads them (A.11): the platform master
    (`platform_off`), the minds (`minds_off`), the Orcs line
    (`line_off`, its cap at or under 0), `orcs` (`orcs_off`). "" when all
    four are ON. Read anew at every call: the platform master is read only
    when a guarded task starts (core/task_gate.py), so every step that may
    lead to a call reads it again."""
    from bot_program.orcs.constants import (CODE_LINE_OFF, CODE_MINDS_OFF,
                                            CODE_ORCS_OFF, CODE_PLATFORM_OFF,
                                            MINDS_SWITCH, PLATFORM_MASTER)
    if not _component_on(PLATFORM_MASTER):
        return CODE_PLATFORM_OFF
    if not _component_on(MINDS_SWITCH):
        return CODE_MINDS_OFF
    try:
        from bot_program.orcs import mind_gateway
        line_on = mind_gateway.line_cap() > 0
    except Exception as e:  # noqa: BLE001 — an unread line is off
        logger.info("[orcs] the Orcs line could not be read: %s", e)
        line_on = False
    if not line_on:
        return CODE_LINE_OFF
    if not orcs_on():
        return CODE_ORCS_OFF
    return ""


def minds_on() -> bool:
    """True when all four gates of A.2 are ON."""
    return gate_code() == ""


def minds_switch_on() -> bool:
    """The minds switch alone (`orcs_minds`), OFF when unreadable: a code
    answer is journaled while it is on (A.5), F6 reads the last validated
    answer's hash while it is on (A.9), and orc_think closes the pending
    wakes while it is off (A.17). (O2a's queue, 2026-11-05.)"""
    from bot_program.orcs.constants import MINDS_SWITCH
    return _component_on(MINDS_SWITCH)


def router_on() -> bool:
    """The router's switch (`orcs_router`; O2b, 2026-11-06, the O2 spec
    B.2b, N2), OFF when unreadable. Read once per render (the dossier's
    family, B.4), at admission and at each claim (frictionless off: a wake
    claimed once it is OFF is answered on r0), and by `orcs smoke` for a
    rung above r0. It is no fifth gate: OFF, the minds still answer every
    wake a model reads, on r0. The tick never reads it."""
    from bot_program.orcs.constants import ROUTER_SWITCH
    return _component_on(ROUTER_SWITCH)


def probes_on() -> bool:
    """The probes' switch (`orcs_probes`; O2b's probes, 2026-11-06, the O2
    spec B.11, N2), OFF when unreadable. Read before each probe
    (probes.run), at its reservation and again at the gateway, so a probe
    is sent only while it is ON (frictionless off). The tick never reads
    it."""
    from bot_program.orcs.constants import PROBES_SWITCH
    return _component_on(PROBES_SWITCH)


def caller_code(caller) -> str:
    """A model caller's OWN switch (N2, A.2: a caller needs its own switch
    beside the four gates), as its code while it is OFF; "" while it is ON
    and for a caller with none of its own: the wake (the minds switch is
    its own) and the smoke (its `--yes`). O2b's probes (2026-11-06): the
    probe's is `orcs_probes` (`probes_off`). Unreadable is OFF."""
    from bot_program.orcs.constants import CODE_PROBES_OFF, PROBE_CALLER
    if caller == PROBE_CALLER and not probes_on():
        return CODE_PROBES_OFF
    return ""
