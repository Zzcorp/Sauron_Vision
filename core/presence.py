"""Who is on the platform right now — presence, address and location.

Django answers "who has an account"; nothing answered "who is HERE".
The middleware stamps one UserPresence row per authenticated user —
throttled through the cache to at most one write a minute, so the hot
path stays effectively read-only — and the admin Eye reads it back:
connected-now counts, last address, best-effort geolocation, the last
page touched and the device it was touched from.

Geolocation is deliberately NOT done in the middleware: it is a network
call to a third party, and nothing a request is waiting on may ever
depend on one. Only the admin Eye view resolves locations, one cheap
cached lookup per distinct address per day.
"""
from __future__ import annotations

import ipaddress
import logging

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

# Seconds between presence writes per user. One write a minute is enough
# resolution for "who is on the site" and keeps the table cold.
PRESENCE_WRITE_INTERVAL = 60

# "Connected now" means seen inside this window.
ONLINE_WINDOW_SECONDS = 5 * 60


class UserPresence(models.Model):
    """The last place each user was seen, one row per user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="presence")
    last_seen = models.DateTimeField(db_index=True)
    last_ip = models.CharField(max_length=64, blank=True, default="")
    last_path = models.CharField(max_length=200, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        verbose_name_plural = "user presences"

    def __str__(self) -> str:
        return f"{self.user} @ {self.last_seen:%Y-%m-%d %H:%M:%S}"


def client_ip(request) -> str:
    """The caller's address, without believing attacker-typed headers.

    X-Forwarded-For is only consulted when the CONNECTION came from a
    private address — i.e. from Caddy inside the compose network, which
    REPLACES the header with the address it observed (deploy/Caddyfile
    `header_up X-Forwarded-For {remote_host}`). When Django faces the
    client directly (dev runserver, or a deployment without the proxy),
    REMOTE_ADDR is public and the header is whatever the client typed —
    so it is ignored. Within the trusted case we still take the LAST hop:
    each proxy appends the address it was called from, so the last entry
    is what the proxy itself observed."""
    remote = (request.META.get("REMOTE_ADDR") or "")[:64]
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff and remote and _is_private(remote):
        return xff.split(",")[-1].strip()[:64]
    return remote


class PresenceMiddleware:
    """Stamp presence after each authenticated page view — never in the
    request's way, never able to break a page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._stamp(request)
        except Exception as e:  # noqa: BLE001 — presence must never 500 a page
            logger.debug("presence stamp failed: %s", e)
        return response

    def _stamp(self, request):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return
        path = request.path or ""
        if path.startswith(("/static/", "/media/", "/favicon")):
            return
        from django.core.cache import cache
        throttle_key = f"presence:{user.pk}"
        if cache.get(throttle_key):
            return
        cache.set(throttle_key, 1, PRESENCE_WRITE_INTERVAL)
        UserPresence.objects.update_or_create(
            user=user,
            defaults={
                "last_seen": timezone.now(),
                "last_ip": client_ip(request),
                "last_path": path[:200],
                "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:300],
            },
        )


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback


def geo_for_ip(ip: str, cached_only: bool = False) -> str:
    """Best-effort "City, Country" for an address, cached for a day.

    Keyless (ipapi.co), fully fenced — INCLUDING the cache calls: the
    production cache is Redis, and the monitoring page must not 500
    during the exact Redis outage it would be used to observe. EMPTY
    results are cached too, so a dead geo service costs one probe per
    address per day.

    cached_only=True never touches the network — the Eye page renders
    with whatever is already known and warms the rest asynchronously.
    """
    if not ip:
        return ""
    if _is_private(ip):
        return "local network"
    from django.core.cache import cache
    cache_key = f"geoip:{ip}"
    try:
        cached = cache.get(cache_key)
    except Exception as e:  # noqa: BLE001 — cache down ≠ page down
        logger.debug("geoip cache read failed: %s", e)
        cached = ""
    if cached is not None:
        return cached
    if cached_only:
        return ""
    out = ""
    try:
        import requests
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=4,
                         headers={"User-Agent": "sauron-vision/1.0"})
        if r.ok:
            d = r.json()
            if not d.get("error"):
                out = ", ".join(
                    p for p in (d.get("city"), d.get("country_name")) if p)
    except Exception as e:  # noqa: BLE001
        logger.debug("geoip lookup failed for %s: %s", ip, e)
    try:
        cache.set(cache_key, out, 24 * 3600)
    except Exception as e:  # noqa: BLE001
        logger.debug("geoip cache write failed: %s", e)
    return out


def device_label(user_agent: str) -> str:
    """A human-sized device summary — 'Chrome · Windows', not 300 bytes
    of UA string."""
    ua = user_agent or ""
    browser = next((name for probe, name in (
        ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"), ("Safari/", "Safari"),
    ) if probe in ua), "")
    system = next((name for probe, name in (
        ("Windows", "Windows"), ("Android", "Android"),
        ("iPhone", "iPhone"), ("iPad", "iPad"),
        ("Mac OS X", "macOS"), ("Linux", "Linux"),
    ) if probe in ua), "")
    if browser and system:
        return f"{browser} · {system}"
    return browser or system or "—"
