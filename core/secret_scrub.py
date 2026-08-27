"""Keep credentials out of the places errors are read.

`requests.Response.raise_for_status()` builds its message from the FULL
url, query string included — so an upstream 403 on a call authenticated
by `?apikey=...` raises an exception whose text carries the key. That
text is stored on the component row and rendered on the health page, so
one forbidden response put a live API key on a dashboard, in the
database, and in every log line that echoed it.

Nothing here tries to be a general secret detector. It removes two
specific things: the value of any query parameter whose NAME looks like
a credential, and any value the deployment itself declares secret. The
first catches the case above for every vendor at once; the second
catches a key pasted into a body or a header dump.
"""
import os
import re

# Query parameters whose value is a credential. Matched case-insensitively
# on the whole name, so `apikey`, `api_key`, `token`, `access_token`,
# `secret`, `signature`, `password`, `auth` are covered without also
# redacting something innocent like `keyword`.
_SECRET_PARAM = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|"
    r"client[_-]?secret|signature|password|passwd|pwd|auth|sig)"
    r"(=|%3D|\"?\s*:\s*\"?)"
    r"([^&\s\"'<>]{4,})")

# `Authorization: Bearer <token>` and friends. In production the token
# is usually also an env value and would be caught below, but a header
# dumped from a library that built it from a literal would not be.
_BEARER = re.compile(r"(?i)\b(Bearer|Basic|Token)\s+([A-Za-z0-9._~+/=-]{8,})")

# Environment variables whose VALUE must never appear in a message, even
# somewhere this module cannot recognise structurally.
_SECRET_ENV_SUFFIXES = ("_API_KEY", "_SECRET", "_TOKEN", "_PASSWORD",
                        "_CLIENT_SECRET", "_DSN", "_KEY")

REDACTION = "***"


def _declared_secrets():
    """Values the deployment itself says are secret, longest first.

    Longest first so a key that contains a shorter one is redacted whole
    rather than leaving a fragment behind.
    """
    out = []
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if name.endswith(_SECRET_ENV_SUFFIXES) or name == "SECRET_KEY":
            out.append(value)
    return sorted(set(out), key=len, reverse=True)


def scrub(text) -> str:
    """Return `text` with credentials replaced by ***.

    Never raises: this runs on the error path, and a scrubber that throws
    while recording a failure loses the failure as well as leaking it.
    """
    try:
        s = str(text or "")
    except Exception:  # pragma: no cover - defensive
        return ""
    try:
        s = _SECRET_PARAM.sub(lambda m: m.group(1) + m.group(2) + REDACTION, s)
        s = _BEARER.sub(lambda m: m.group(1) + " " + REDACTION, s)
        for value in _declared_secrets():
            if value in s:
                s = s.replace(value, REDACTION)
    except Exception:  # pragma: no cover - never lose the message
        return s
    return s
