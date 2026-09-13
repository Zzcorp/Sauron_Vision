"""Which commit is this, and when was it built? (2026-09-13)

`.dockerignore` excludes `.git` — correctly; a 200 MB object store has no
place in a runtime image. The consequence nobody had accounted for is
that the running application could not answer the simplest question about
itself, and on 2026-09-13 that cost a day: the box served the previous
commit, `/personas/` and `/setups/` answered 404, the operator reported
"il manque beaucoup de choses", and the only way to find out was probing
the public site route by route from outside. Nothing on the platform
could say "I am stale".

`deploy/dc` now reads the sha from the checkout and passes it as a build
arg, so the image carries it. This module is the read side.

WHAT IT REFUSES TO DO
---------------------

It never guesses. An unstamped build reports None, which the page renders
as an em dash — the same rule the whole Oculus runs on, because "unknown
commit" and "commit abc1234" are different answers and an operator acts
differently on each. A plausible-looking sha that nobody can check is
exactly the species of fabrication `core/wall_facts.py` exists to abolish.

It also cannot tell you whether the commit is CURRENT. The image has no
git and no guaranteed network; it knows what it was built from and
nothing else. That is still the whole of what was missing — a stamp and a
timestamp would have made the 2026-09-13 gap visible in five seconds.
"""
import logging
import os

logger = logging.getLogger(__name__)

#: What the Dockerfile writes when nobody passed a value.
UNSTAMPED = {"", "unknown", "none", "null"}


def _clean(value):
    value = (value or "").strip()
    return None if value.lower() in UNSTAMPED else value


def git_sha():
    """The commit this image was built from, or None if unstamped."""
    return _clean(os.environ.get("SAURON_GIT_SHA"))


def built_at():
    """The UTC instant the image was built, ISO-8601, or None."""
    return _clean(os.environ.get("SAURON_BUILT_AT"))


def build_age_hours():
    """Hours since the build, or None when it cannot be known.

    Age is the fact that matters operationally: a sha means nothing to a
    human reading a page, while "built 31 hours ago" against a branch
    that moved this morning is immediately actionable.
    """
    stamp = built_at()
    if not stamp:
        return None
    try:
        from datetime import datetime, timezone as dt_tz
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt_tz.utc)
        delta = datetime.now(dt_tz.utc) - when
        return round(delta.total_seconds() / 3600.0, 1)
    except Exception as exc:  # noqa: BLE001 — a bad stamp is not a crash
        logger.debug("build_stamp: unreadable BUILT_AT %r (%s)", stamp, exc)
        return None


def stamp() -> dict:
    """{"sha", "built_at", "age_hours", "stamped"} — never raises."""
    sha, when = git_sha(), built_at()
    return {"sha": sha, "built_at": when, "age_hours": build_age_hours(),
            "stamped": bool(sha)}
