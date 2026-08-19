"""Security middleware and utilities for Sauron Vision."""
from django.http import HttpResponseForbidden, JsonResponse
from django.conf import settings
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter for login attempts
_login_attempts = {}

# Every endpoint that accepts a credential (password or PIN) shares the
# same window. /login/pin/ used to be unthrottled — a 4-digit PIN is only
# 10,000 guesses, so leaving it open made the second gate the weakest one.
RATE_LIMITED_PATHS = ("/login/", "/login/pin/", "/login/pin/forgot/")


class LoginRateLimitMiddleware:
    """Rate limit login attempts to prevent brute force."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in RATE_LIMITED_PATHS and request.method == "POST":
            ip = self._get_ip(request)
            # Keyed per (ip, path) so the normal two-step flow — one POST to
            # /login/ then one to /login/pin/ — never eats into a single
            # shared budget.
            key = f"{ip}:{request.path}"
            now = time.time()

            # Clean old entries
            _login_attempts[key] = [t for t in _login_attempts.get(key, []) if now - t < 300]

            if len(_login_attempts.get(key, [])) >= 5:
                logger.warning(f"Rate limited login from {ip} on {request.path}")
                message = "Too many login attempts. Wait 5 minutes."
                # The gates submit by fetch and read JSON. An HTML refusal
                # parsed as "no message" surfaced as "Invalid PIN" and wiped
                # the pad — the operator then retried a correct PIN forever
                # against a closed gate.
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse(
                        {"status": "error", "message": message}, status=429)
                return HttpResponseForbidden(f"<h3>{message}</h3>")

            _login_attempts.setdefault(key, []).append(now)

        return self.get_response(request)

    def _get_ip(self, request):
        # The shared helper only believes X-Forwarded-For when the connection
        # came from the proxy itself; trusting it blindly let an attacker mint
        # a fresh 5-attempt budget per request against the PIN gate.
        from core.presence import client_ip

        return client_ip(request)


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
