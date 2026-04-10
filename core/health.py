"""Comprehensive health-check view for Sauron Vision.

Endpoint: GET /healthz/

Returns a JSON document describing the state of every subsystem.  The top-level
``status`` field is one of:

  "healthy"   — all critical checks passed
  "degraded"  — non-critical checks failed (e.g. Celery workers offline)
  "unhealthy" — a critical check failed (database unreachable)
"""

import datetime
import logging
import os
import shutil
import time

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

# Record the module-load time as the process start time.
_START_TIME: float = time.monotonic()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_database() -> dict:
    """Run a trivial query and measure round-trip latency."""
    try:
        from django.db import connection  # noqa: PLC0415

        t0 = time.monotonic()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        logger.warning("health_check: database error — %s", exc)
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> dict:
    """Attempt to ping the default Django cache backend."""
    try:
        from django.core.cache import cache  # noqa: PLC0415

        probe_key = "_healthz_ping"
        cache.set(probe_key, "pong", timeout=5)
        result = cache.get(probe_key)
        if result == "pong":
            return {"status": "ok"}
        return {"status": "unavailable", "detail": "ping/pong mismatch"}
    except Exception as exc:
        logger.warning("health_check: redis/cache error — %s", exc)
        return {"status": "unavailable", "detail": str(exc)}


def _check_celery() -> dict:
    """Inspect running Celery workers with a short timeout."""
    try:
        from config.celery import app as celery_app  # noqa: PLC0415

        inspector = celery_app.control.inspect(timeout=2.0)
        ping_result = inspector.ping()
        if ping_result:
            worker_count = len(ping_result)
            return {"status": "ok", "workers": worker_count}
        return {"status": "unavailable", "workers": 0}
    except Exception as exc:
        logger.warning("health_check: celery error — %s", exc)
        return {"status": "unavailable", "detail": str(exc)}


def _check_external_apis() -> dict:
    """Check whether API keys are present in the environment (no network calls)."""
    api_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "fmp": "FMP_API_KEY",
        "fred": "FRED_API_KEY",
        "reddit": "REDDIT_CLIENT_ID",
    }
    return {
        name: ("ok" if os.getenv(env_var) else "unconfigured")
        for name, env_var in api_keys.items()
    }


def _check_circuit_breakers() -> dict:
    """Return the current state of all circuit breakers (if the module exists)."""
    try:
        from core.circuit_breaker import CircuitBreaker  # noqa: PLC0415

        return CircuitBreaker.get_all_states()
    except ImportError:
        return {}
    except Exception as exc:
        logger.warning("health_check: circuit_breaker error — %s", exc)
        return {"error": str(exc)}


def _check_disk_space() -> int:
    """Return free disk space on the project root (in MB)."""
    try:
        usage = shutil.disk_usage("/")
        return round(usage.free / (1024 * 1024))
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

@never_cache
@require_GET
def health_check(request) -> JsonResponse:
    """Return a comprehensive health-check document."""

    db = _check_database()
    redis = _check_redis()
    celery = _check_celery()
    external_apis = _check_external_apis()
    circuit_breakers = _check_circuit_breakers()
    disk_space_mb = _check_disk_space()
    uptime_seconds = round(time.monotonic() - _START_TIME)

    checks = {
        "database": db,
        "redis": redis,
        "celery": celery,
        "external_apis": external_apis,
        "circuit_breakers": circuit_breakers,
        "disk_space_mb": disk_space_mb,
        "uptime_seconds": uptime_seconds,
    }

    # Derive overall status.
    if db["status"] != "ok":
        overall = "unhealthy"
    elif redis["status"] != "ok" or celery["status"] != "ok":
        overall = "degraded"
    else:
        overall = "healthy"

    payload = {
        "status": overall,
        "checks": checks,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }

    http_status = 200 if overall in ("healthy", "degraded") else 503
    return JsonResponse(payload, status=http_status)
