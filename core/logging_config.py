"""
Sauron Vision — Structured logging configuration.

Provides a LOGGING dict ready to be assigned in Django settings.

Behaviour
---------
* DEBUG=True  → human-readable console output (verbose format).
* DEBUG=False → JSON-formatted output suitable for log-aggregation
                services (Datadog, Papertrail, Render log drains, …).

Every log record is enriched with a ``correlation_id`` by
:class:`core.middleware.CorrelationIdFilter` so requests can be traced
end-to-end across modules.

Usage in settings.py
--------------------
::

    from core.logging_config import build_logging_config
    LOGGING = build_logging_config(debug=DEBUG)
"""
import os


# ─────────────────────────────────────────────────────────────────────────────
# Sauron app list — each gets its own named logger at INFO level
# ─────────────────────────────────────────────────────────────────────────────

SAURON_APPS = [
    "core",
    "dashboard",
    "signals",
    "strategies",
    "portfolio",
    "ai_agents",
    "scraping",
    "market_data",
    "alerts",
    "bot_program",
]


def build_logging_config(debug: bool = True) -> dict:
    """
    Return a Django-compatible LOGGING dict.

    Parameters
    ----------
    debug:
        When *True*, use a coloured/readable console format.
        When *False*, emit newline-delimited JSON.
    """

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------
    formatters: dict = {
        "verbose": {
            "format": (
                "[%(asctime)s] %(levelname)-8s [%(correlation_id)s] "
                "%(name)s:%(lineno)d — %(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "%(levelname)-8s %(name)s — %(message)s",
        },
        "json": {
            "()": "core.logging_config.JsonFormatter",
        },
    }

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    filters: dict = {
        "correlation_id": {
            "()": "core.middleware.CorrelationIdFilter",
        },
    }

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    console_formatter = "verbose" if debug else "json"

    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": console_formatter,
            "filters": ["correlation_id"],
        },
    }

    # ------------------------------------------------------------------
    # Root log level
    # ------------------------------------------------------------------
    root_level = "DEBUG" if debug else "WARNING"

    # ------------------------------------------------------------------
    # Per-logger configuration
    # ------------------------------------------------------------------
    loggers: dict = {
        # Django internals — WARNING in prod, INFO in dev
        "django": {
            "handlers": ["console"],
            "level": "INFO" if debug else "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Celery
        "celery": {
            "handlers": ["console"],
            "level": "INFO" if debug else "WARNING",
            "propagate": False,
        },
    }

    # All Sauron apps stay at INFO regardless of DEBUG flag so that
    # operational events are never silenced in production.
    for app in SAURON_APPS:
        loggers[app] = {
            "handlers": ["console"],
            "level": "DEBUG" if debug else "INFO",
            "propagate": False,
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "filters": filters,
        "handlers": handlers,
        "loggers": loggers,
        "root": {
            "handlers": ["console"],
            "level": root_level,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# JSON formatter
# ─────────────────────────────────────────────────────────────────────────────

import json
import logging
import traceback


class JsonFormatter(logging.Formatter):
    """
    Emit each log record as a single-line JSON object.

    Fields emitted
    --------------
    timestamp, level, logger, message, correlation_id,
    module, funcName, lineno, [exc_info]
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False)
