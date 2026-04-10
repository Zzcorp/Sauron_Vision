"""Sauron Vision — Core system monitoring API views."""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from core.rate_limiter import rate_limiter


@login_required
@require_GET
def rate_limiter_stats(request):
    """Return current rate limiter statistics per provider."""
    stats = rate_limiter.get_stats()
    return JsonResponse({"rate_limits": stats})


@login_required
@require_GET
def system_status(request):
    """Return a combined system health snapshot.

    Includes:
    - Rate limiter stats (per provider)
    - Circuit breaker states (if core.circuit_breaker is available)
    - Feature flag states (if core.feature_flags is available)
    - Celery queue lengths (if Celery / Redis is available)
    """
    payload = {}

    # ── Rate limiter ────────────────────────────────────────────────────────
    payload["rate_limits"] = rate_limiter.get_stats()

    # ── Circuit breaker states ───────────────────────────────────────────────
    try:
        from core.circuit_breaker import CircuitBreaker
        payload["circuit_breakers"] = CircuitBreaker.get_all_states()
    except Exception as exc:
        payload["circuit_breakers"] = {"error": str(exc)}

    # ── Feature flag states ──────────────────────────────────────────────────
    try:
        from core.feature_flags import get_all_flags
        payload["feature_flags"] = get_all_flags()
    except ImportError:
        payload["feature_flags"] = {}
    except Exception as exc:
        payload["feature_flags"] = {"error": str(exc)}

    # ── Celery queue lengths ─────────────────────────────────────────────────
    try:
        from django.conf import settings
        import redis

        redis_url = getattr(settings, "CELERY_BROKER_URL", None) or getattr(
            settings, "BROKER_URL", None
        )
        if redis_url and redis_url.startswith("redis"):
            r = redis.from_url(redis_url)
            queue_names = getattr(settings, "CELERY_TASK_QUEUES_NAMES", ["celery"])
            queue_lengths = {q: r.llen(q) for q in queue_names}
            payload["celery_queues"] = queue_lengths
        else:
            payload["celery_queues"] = {}
    except Exception as exc:
        payload["celery_queues"] = {"error": str(exc)}

    return JsonResponse(payload)
