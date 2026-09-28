"""Saxo OpenAPI OAuth 2.0 — authorization-code grant with rotating refresh.

Read off Saxo's developer documentation on 2026-09-17, and pinned by
tests/test_saxo_oauth.py. Two facts shape everything here:

  * The ACCESS token lives 1 200 s. The REFRESH token lives 2 400 s and
    ROTATES: every refresh returns a new refresh token, and the old one is
    dead. So a session stays alive only while this platform keeps
    refreshing inside a forty-minute window. Inside it, no human is
    needed — that is the property IBKR's retail API withholds and the
    reason Saxo was chosen. Past it, one browser sign-in again. Not
    "never touch it", but a bounded rule, stated.

  * SIM and LIVE are different WORLDS with different app keys, different
    auth hosts and different API bases. `SaxoAccount.sim` picks all three
    at once, so a SIM key can never be presented to the live host.

The one-day "OpenAPI token" from the developer portal is SIM-only and
needs no browser; it is how the SIM adapter can be exercised before any
sign-in exists. It is not stored here — it is a testing convenience, not
a session.
"""
from __future__ import annotations

import base64
import logging
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.utils import timezone

log = logging.getLogger(__name__)


class SaxoTokenError(RuntimeError):
    """A refused token request, carrying Saxo's own `error` and
    `error_description` — the only words that tell invalid_client (wrong
    secret) from invalid_grant (dead code or token) from a redirect-URI
    mismatch. Never carries request data or any token."""

AUTH_HOST = {
    "sim": "https://sim.logonvalidation.net",
    "live": "https://live.logonvalidation.net",
}
API_BASE = {
    "sim": "https://gateway.saxobank.com/sim/openapi",
    "live": "https://gateway.saxobank.com/openapi",
}
STREAM_BASE = {
    "sim": "https://sim-streaming.saxobank.com/sim/oapi/streaming/ws",
    "live": "https://live-streaming.saxobank.com/oapi/streaming/ws",
}

#: The lifetimes Saxo's documentation SHOWS in its example responses, in
#: seconds. The response's own `expires_in` / `refresh_token_expires_in`
#: are authoritative and always preferred; these stand in only when Saxo
#: omits them. The refresh task's cadence is derived from the second one
#: and a test holds the margin.
ACCESS_TOKEN_SECONDS = 1200
REFRESH_TOKEN_SECONDS = 2400
#: Refresh unconditionally at this cadence: rotation is one POST, and
#: every refresh restarts the forty-minute clock. Four refreshes fit in one
#: refresh-token lifetime, so a single missed cycle costs nothing.
REFRESH_EVERY_S = 600

TIMEOUT_S = 15


def env_of(acct) -> str:
    return "sim" if getattr(acct, "sim", True) else "live"


def authorize_url(acct, state: str) -> str:
    """Where the operator's browser goes to sign in once.

    `redirect_uri` is the one registered on the portal for THIS app — the
    row carries it — and it must match to the character or Saxo answers
    "Redirect URI mismatch" and nothing else.
    """
    app_key, _secret = acct.get_credentials()
    if not (app_key and acct.redirect_uri):
        raise ValueError("Saxo application is not registered on this row")
    query = urlencode({
        "response_type": "code",
        "client_id": app_key,
        "redirect_uri": acct.redirect_uri,
        "state": state,
    })
    return f"{AUTH_HOST[env_of(acct)]}/authorize?{query}"


def _token_post(acct, data: dict, session=None) -> dict:
    """POST /token with HTTP Basic client credentials, form-encoded.

    Raises on a non-2xx — the caller decides whether that is transient or
    a dead session; this function does not guess.
    """
    app_key, app_secret = acct.get_credentials()
    if not (app_key and app_secret):
        raise ValueError("Saxo application key/secret missing")
    basic = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    sess = session or requests
    r = sess.post(
        f"{AUTH_HOST[env_of(acct)]}/token",
        data=data,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT_S)
    if r.status_code >= 400:
        try:
            body = r.json() or {}
        except Exception:  # noqa: BLE001 — a non-JSON refusal is still a refusal
            body = {}
        code = str(body.get("error") or getattr(r, "reason", "") or "").strip()
        desc = str(body.get("error_description") or "").strip()
        raise SaxoTokenError(
            f"HTTP {r.status_code} {code}: {desc}".rstrip(": ").strip())
    return r.json() or {}


def exchange_code(acct, code: str, session=None) -> dict:
    """The callback's half of the code grant: code -> tokens."""
    return _token_post(acct, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": acct.redirect_uri,
    }, session=session)


def refresh(acct, session=None) -> dict:
    """Rotate: the current refresh token -> a new access AND refresh token."""
    token = acct.get_refresh_token()
    if not token:
        raise ValueError("no refresh token on this row — sign in first")
    return _token_post(acct, {
        "grant_type": "refresh_token",
        "refresh_token": token,
    }, session=session)


def store_tokens(acct, payload: dict, now=None) -> None:
    """Persist a token response with BOTH deadlines, and mark connected.

    `refresh_token_expires_in` is the number that matters operationally;
    when Saxo omits it the documented lifetime stands in, so the row is
    never left without a deadline the refresh task can read.
    """
    now = now or timezone.now()
    access = str(payload.get("access_token") or "")
    refresh_token = str(payload.get("refresh_token") or "")
    if not (access and refresh_token):
        raise ValueError("token response carried no access/refresh pair")
    expires_in = int(payload.get("expires_in") or ACCESS_TOKEN_SECONDS)
    refresh_in = int(payload.get("refresh_token_expires_in")
                     or REFRESH_TOKEN_SECONDS)
    acct.set_tokens(access, refresh_token,
                    now + timedelta(seconds=expires_in),
                    refresh_expires_at=now + timedelta(seconds=refresh_in))
    acct.connected = True
    acct.last_sync = now
    acct.session_lost_at = None
    acct.session_lost_reason = ""
    acct.save(update_fields=["access_token_enc", "refresh_token_enc",
                             "token_expires_at", "refresh_expires_at",
                             "connected", "last_sync",
                             "session_lost_at", "session_lost_reason"])


def ensure_access_token(acct, now=None, margin_s: int = 60, session=None) -> str:
    """The bearer the adapter presents: rotated on demand when it is about
    to die, refused outright when the session is gone.

    The keeper renews every ten minutes; this is for the gap — a request
    that lands right after an outage, or a beat that missed a cycle. It
    raises SaxoTokenError rather than returning a token Saxo will 401.
    """
    now = now or timezone.now()
    if acct.access_token_valid(now, margin_s):
        return acct.get_access_token()
    if not acct.session_alive(now):
        raise SaxoTokenError(
            "Saxo session is not alive — sign in again at /brokers/")
    store_tokens(acct, refresh(acct, session=session), now=now)
    return acct.get_access_token()
