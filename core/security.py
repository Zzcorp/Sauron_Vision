"""Security middleware and utilities for Sauron Vision."""
from django.http import HttpResponseForbidden
from django.conf import settings
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter for login attempts
_login_attempts = {}


class LoginRateLimitMiddleware:
    """Rate limit login attempts to prevent brute force."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/login/" and request.method == "POST":
            ip = self._get_ip(request)
            now = time.time()

            # Clean old entries
            _login_attempts[ip] = [t for t in _login_attempts.get(ip, []) if now - t < 300]

            if len(_login_attempts.get(ip, [])) >= 5:
                logger.warning(f"Rate limited login from {ip}")
                return HttpResponseForbidden(
                    "<h3>Too many login attempts. Wait 5 minutes.</h3>"
                )

            _login_attempts.setdefault(ip, []).append(now)

        return self.get_response(request)

    def _get_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")


class SecurityHeadersMiddleware:
    """Add security headers to all responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-XSS-Protection"] = "1; mode=block"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.DEBUG:
            response["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
