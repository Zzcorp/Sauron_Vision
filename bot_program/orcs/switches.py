"""The Orcs' switch (spec §10.4): `orcs`, System, OFF on arrival. It is not
a live-money switch (nothing here moves money) and the System group's
"all on" may turn it on. An unreadable switch reads OFF."""
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
