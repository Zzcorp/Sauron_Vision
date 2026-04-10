"""Feature-flag helpers for Sauron Vision.

Public API
----------
    is_enabled(flag_name, default=False) -> bool
    set_flag(name, enabled, description="") -> FeatureFlag
    get_all_flags() -> dict[str, bool]

All reads go through Django's cache (TTL = 60 s) so hot paths never hit the
database on every request.  Cache keys are invalidated automatically by
``set_flag``.
"""

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cache TTL in seconds.
_CACHE_TTL = 60
_CACHE_PREFIX = "feature_flag:"
_ALL_FLAGS_KEY = "feature_flags:all"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flag_cache_key(name: str) -> str:
    return f"{_CACHE_PREFIX}{name}"


def _invalidate(name: str) -> None:
    """Remove the per-flag and the aggregate cache entries."""
    cache.delete(_flag_cache_key(name))
    cache.delete(_ALL_FLAGS_KEY)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled(flag_name: str, default: bool = False) -> bool:
    """Return whether *flag_name* is enabled.

    Lookup order:
    1. Django cache (TTL 60 s)
    2. Database (``FeatureFlag`` model)
    3. *default* — used when the flag does not exist in the DB yet

    The result is cached regardless of origin so subsequent calls within the
    TTL window are free.
    """
    cache_key = _flag_cache_key(flag_name)
    cached = cache.get(cache_key)
    if cached is not None:
        # Cache stores True/False; sentinel None means "not cached"
        return cached

    try:
        # Lazy import to avoid issues during Django setup / migrations.
        from core.models import FeatureFlag  # noqa: PLC0415

        flag = FeatureFlag.objects.get(name=flag_name)
        result = flag.enabled
    except Exception:  # pragma: no cover — DB unavailable or flag missing
        result = default

    cache.set(cache_key, result, _CACHE_TTL)
    return result


def set_flag(name: str, enabled: bool, description: str = "") -> "FeatureFlag":
    """Create or update a feature flag and invalidate the cache.

    Returns the saved ``FeatureFlag`` instance.
    """
    from core.models import FeatureFlag  # noqa: PLC0415

    defaults: dict = {"enabled": enabled}
    if description:
        defaults["description"] = description

    flag, created = FeatureFlag.objects.update_or_create(
        name=name,
        defaults=defaults,
    )

    _invalidate(name)

    action = "created" if created else "updated"
    logger.info("Feature flag '%s' %s (enabled=%s)", name, action, enabled)
    return flag


def get_all_flags() -> dict[str, bool]:
    """Return a mapping of ``{flag_name: enabled}`` for every flag in the DB.

    The result is cached for ``_CACHE_TTL`` seconds.
    """
    cached = cache.get(_ALL_FLAGS_KEY)
    if cached is not None:
        return cached

    try:
        from core.models import FeatureFlag  # noqa: PLC0415

        result = {f.name: f.enabled for f in FeatureFlag.objects.all()}
    except Exception:
        logger.warning("feature_flags.get_all_flags: could not read DB, returning {}")
        result = {}

    cache.set(_ALL_FLAGS_KEY, result, _CACHE_TTL)
    return result
