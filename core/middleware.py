"""
Sauron Vision — Core middleware.

CorrelationIdMiddleware
    Attaches a unique UUID4 to every HTTP request so that all log lines
    emitted during that request share the same ``correlation_id``.

CorrelationIdFilter
    ``logging.Filter`` subclass that injects the current request's
    correlation ID into every log record, enabling structured log queries.
"""
import logging
import threading
import uuid

# ─────────────────────────────────────────────────────────────────────────────
# Thread-local storage — holds the correlation ID for the current thread
# ─────────────────────────────────────────────────────────────────────────────

_local = threading.local()

CORRELATION_ID_HEADER = "X-Correlation-ID"
_FALLBACK_ID = "-"


def get_correlation_id() -> str:
    """Return the correlation ID for the active request, or '-' if none."""
    return getattr(_local, "correlation_id", _FALLBACK_ID)


def set_correlation_id(value: str) -> None:
    """Set the correlation ID for the current thread."""
    _local.correlation_id = value


def clear_correlation_id() -> None:
    """Remove the correlation ID from thread-local storage."""
    _local.correlation_id = _FALLBACK_ID


# ─────────────────────────────────────────────────────────────────────────────
# Django middleware
# ─────────────────────────────────────────────────────────────────────────────

class CorrelationIdMiddleware:
    """
    Django middleware that generates a unique request ID per HTTP request.

    * Reads an incoming ``X-Correlation-ID`` header if present (useful when
      a reverse-proxy or upstream service already set one).
    * Otherwise generates a fresh UUID4.
    * Stores the ID in ``threading.local()`` so logging filters can access it.
    * Adds ``X-Correlation-ID`` to every response.

    Add to MIDDLEWARE in settings **after** ``SessionMiddleware``::

        MIDDLEWARE = [
            ...
            "django.contrib.sessions.middleware.SessionMiddleware",
            "core.middleware.CorrelationIdMiddleware",
            ...
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Honour an upstream-provided ID, otherwise generate a fresh one.
        incoming = request.META.get(
            "HTTP_X_CORRELATION_ID",
            request.META.get("HTTP_X_REQUEST_ID", ""),
        )
        correlation_id = incoming.strip() if incoming.strip() else str(uuid.uuid4())

        set_correlation_id(correlation_id)
        # Expose on the request object for views/serializers that need it.
        request.correlation_id = correlation_id

        try:
            response = self.get_response(request)
        finally:
            # Always clean up — even if an exception propagates.
            clear_correlation_id()

        response[CORRELATION_ID_HEADER] = correlation_id
        return response


# ─────────────────────────────────────────────────────────────────────────────
# Logging filter
# ─────────────────────────────────────────────────────────────────────────────

class CorrelationIdFilter(logging.Filter):
    """
    Logging filter that adds ``correlation_id`` to every :class:`logging.LogRecord`.

    Register in the ``filters`` section of the LOGGING dict::

        "filters": {
            "correlation_id": {
                "()": "core.middleware.CorrelationIdFilter",
            },
        },

    Then reference it from any handler::

        "handlers": {
            "console": {
                ...
                "filters": ["correlation_id"],
            },
        },

    Formatters can then use ``%(correlation_id)s`` in their format string.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.correlation_id = get_correlation_id()
        return True  # Never suppress — only enrich.
