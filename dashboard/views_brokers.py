"""LES COURTIERS — one page, every broker, what each one can hold (2026-09-17)

Before this page the platform's brokers were configured in three places
(the admin HQ page for OANDA / Alpaca / IBKR, Django admin for the rest) and
described nowhere. An operator could not answer "which broker holds my
stops" without reading `broker_router.py`.

The page answers three things per broker, side by side:

  * Is there an account row, and did its keys ever reach the broker?
    Three states — no row, recorded, connected — because "recorded" and
    "connected" send an operator to different places.
  * Which environment the keys open — demo, paper, practice, testnet, sim.
    The flag is a property of the KEYS, never a switch on a live account.
  * What the adapter can be asked for, read from
    `bot_program.engine.capabilities` — the same table the conformance test
    holds — so the page cannot describe a broker the engine does not have.

It also holds the two new forms, eToro and Saxo, added before their adapters
exist so the operator obtaining keys today has somewhere to put them. Both
say so plainly: a key saved for a broker with no adapter is recorded, not
connected, and the row shows that.

SAVING IS SUPERUSER + POST, LIKE THE OTHER THREE

`_admin_only` is reused rather than copied. The eToro save PROBES the key —
a real credential check — and reports three outcomes, not two: verified,
refused, or could-not-verify. The last exists because the probe endpoint was
taken from public documentation and not yet exercised against a live key; a
404 there is this author's error, not the operator's, and must not be shown
as "your keys are wrong".
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .views_admin_hq import _admin_only

logger = logging.getLogger(__name__)

ETORO_PROBE_TIMEOUT_S = 10


def etoro_probe(api_key: str, user_key: str, demo: bool = True) -> tuple:
    """("ok" | "refused" | "unknown", detail) — three answers, on purpose.

    200 means the keys work. 401 or 403 means eToro saw them and said no.
    Anything else — a 404, a 5xx, a timeout — means this call could not
    decide, and the operator must not be told their keys are wrong on the
    strength of it.

    The endpoint is the adapter's own aggregate-portfolio read, built by
    the adapter's path rule, so the probe and the client can never disagree
    about where eToro lives. The first version of this hit a host and path
    taken from an earlier, unverified guess; it would have answered
    "unknown" for every real key. `demo` matters: a demo key against the
    real path is a 401 that reads as "your keys are wrong".
    """
    from bot_program.engine.etoro_client import EtoroTrader
    url = EtoroTrader(api_key, user_key,
                      env="demo" if demo else "live")._v1_info(
        "aggregate-portfolio")
    try:
        import requests
        r = requests.get(
            url,
            headers={"x-api-key": api_key, "x-user-key": user_key,
                     "x-request-id": EtoroTrader._rid()},
            timeout=ETORO_PROBE_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 — a network error is "unknown"
        return "unknown", f"{type(e).__name__}: {e}"
    if r.status_code == 200:
        return "ok", "200"
    if r.status_code in (401, 403):
        return "refused", str(r.status_code)
    return "unknown", str(r.status_code)


def _env(acct, flag: str, on: str, off: str) -> str:
    return on if getattr(acct, flag, False) else off


def _status(acct, *, has_adapter: bool) -> str:
    """no row / recorded / connected — never a bool."""
    if acct is None:
        return "no row"
    if getattr(acct, "connected", False):
        # A session is not an adapter: the page's rule is that a broker
        # nothing can be asked of is never painted green, however good its
        # keys or its session. Saxo sits here until SaxoTrader lands.
        return "connected" if has_adapter else "session open — adapter pending"
    if not has_adapter:
        return "recorded — adapter pending"
    return "recorded — never verified"


ROUTABLE_CLASSES = ("stock", "forex", "commodity", "crypto")


def _primary_classes(acct) -> list:
    """The asset classes this account is the primary broker for, read off
    its own is_primary_for() — the same method the router consults — or []
    for a row that has no routing flags at all."""
    fn = getattr(acct, "is_primary_for", None)
    if acct is None or not callable(fn):
        return []
    return [c for c in ROUTABLE_CLASSES if fn(c)]


def _redirect_uri_problem(uri: str):
    """Why a registered redirect URI cannot work, or None.

    The callback PATH is fixed by urls.py; only the host is the operator's.
    A URI that lands anywhere else makes the sign-in a silent no-op — Saxo
    accepts it (it matches the portal), the browser comes back to a page
    that ignores ?code=, and the armed state is left dangling. And an
    http:// URI would carry the authorization code in clear text.
    """
    from urllib.parse import urlparse

    from django.urls import reverse

    p = urlparse((uri or "").strip())
    if p.scheme not in ("https", "http"):
        return "must start with https://"
    host = (p.hostname or "").lower()
    if p.scheme == "http" and host not in ("localhost", "127.0.0.1"):
        return "must be https (http is allowed only for localhost)"
    expected = reverse("saxo_callback")
    if p.path != expected:
        return f"path must be exactly {expected}"
    return None


def _saxo_session_line(saxo, now=None):
    """(the session line for the row, whether a sign-in is what it needs).

    Five states, not two — the page the lost-session log sends the
    operator to must be able to say "lost" and "again"."""
    now = now or timezone.now()
    registered = bool(saxo.app_key_enc)
    if not saxo.has_session:
        if saxo.session_lost_at:
            when = saxo.session_lost_at.strftime("%Y-%m-%d %H:%M")
            why = saxo.session_lost_reason or "refresh refused"
            return (f"session: LOST {when} UTC — {why} — sign in again",
                    registered)
        return "session: none — OAuth sign-in not yet done", registered
    if not saxo.session_alive(now):
        return ("session: EXPIRED — refresh token past its life — sign in "
                "again", registered)
    if not saxo.access_token_valid(now):
        return ("session: renewable — access token expired, renewing at the "
                "next cycle", False)
    return "session: renewable", False


def _class_conflicts(user) -> dict:
    """{asset_class: [broker keys that claim it]} for every class claimed
    more than once.

    The router picks one (VENUE_PRECEDENCE: saxo, etoro, ibkr) and that is
    deterministic, but silence about it is how an operator's stock orders
    move venue without anyone deciding to move them.
    """
    claims: dict = {}
    for key, attr in (("saxo", "saxo_account"), ("etoro", "etoro_account"),
                      ("ibkr", "ibkr_account")):
        acct = getattr(user, attr, None)
        fn = getattr(acct, "is_primary_for", None)
        if acct is None or not callable(fn):
            continue
        for cls in ROUTABLE_CLASSES:
            try:
                if fn(cls):
                    claims.setdefault(cls, []).append(key)
            except Exception:  # noqa: BLE001 — an unreadable row claims nothing
                continue
    return {cls: who for cls, who in claims.items() if len(who) > 1}


def _rows(user) -> list:
    from bot_program.engine.capabilities import declared

    def row(key, name, acct, env, has_adapter=True, extra="",
            needs_signin=False):
        return {
            "key": key, "name": name, "account": acct,
            "env": env if acct is not None else "—",
            "status": _status(acct, has_adapter=has_adapter),
            # Green means "can be asked of": a session on a broker with no
            # adapter is real and is NOT green — see _status.
            "connected": bool(acct is not None and has_adapter
                              and getattr(acct, "connected", False)),
            "needs_signin": needs_signin,
            "last_sync": getattr(acct, "last_sync", None),
            "capabilities": declared(key) if has_adapter else (),
            "has_adapter": has_adapter,
            "extra": extra,
            "primary_for": _primary_classes(acct),
            "loses": loses.get(key, []),
        }

    ibkr = getattr(user, "ibkr_account", None)
    alpaca = getattr(user, "alpaca_account", None)
    oanda = getattr(user, "oanda_account", None)
    binance = getattr(user, "binance_account", None)
    etoro = getattr(user, "etoro_account", None)
    saxo = getattr(user, "saxo_account", None)

    saxo_extra, saxo_needs_signin = "", False
    if saxo is not None:
        saxo_extra, saxo_needs_signin = _saxo_session_line(saxo)

    # Who loses a contested asset class, named on the losing row.
    from bot_program.engine.broker_router import VENUE_PRECEDENCE
    conflicts = _class_conflicts(user)
    loses: dict = {}
    for cls, who in conflicts.items():
        ranked = sorted(who, key=lambda k: VENUE_PRECEDENCE.index(k)
                        if k in VENUE_PRECEDENCE else 99)
        winner = ranked[0]
        for key in ranked[1:]:
            loses.setdefault(key, []).append(f"{cls} → {winner}")

    return [
        row("ibkr", "Interactive Brokers", ibkr,
            _env(ibkr, "paper", "paper", "live") if ibkr else "—"),
        row("alpaca", "Alpaca", alpaca,
            _env(alpaca, "paper", "paper", "live") if alpaca else "—"),
        row("oanda", "OANDA", oanda,
            _env(oanda, "practice", "practice", "live") if oanda else "—"),
        row("binance", "Binance", binance,
            _env(binance, "testnet", "testnet", "live") if binance else "—"),
        # Adapter landed 2026-09-17 (engine/etoro_client.py); the
        # capabilities column now reads the enforced table for it.
        row("etoro", "eToro", etoro,
            _env(etoro, "demo", "demo", "live") if etoro else "—"),
        row("saxo", "Saxo Bank", saxo,
            _env(saxo, "sim", "sim", "live") if saxo else "—",
            has_adapter=False, extra=saxo_extra,
            needs_signin=saxo_needs_signin),
    ]


@login_required
def brokers_page(request):
    from bot_program.engine.capabilities import CAPABILITIES
    context = {
        "page_id": "brokers",
        "rows": _rows(request.user),
        "capabilities": list(CAPABILITIES.keys()),
        "can_edit": request.user.is_superuser,
    }
    if request.user.is_superuser:
        from django.contrib.auth.models import User
        context["users"] = User.objects.filter(is_active=True).order_by(
            "username")
    return render(request, "dashboard/brokers.html", context)


@_admin_only
def save_etoro_credentials(request):
    from django.contrib.auth.models import User

    from bot_program.models import EtoroAccount

    target_username = request.POST.get("target_username", "").strip()
    api_key = request.POST.get("etoro_api_key", "").strip()
    user_key = request.POST.get("etoro_user_key", "").strip()
    # Same convention as the other three: unchecked = absent = live.
    demo = request.POST.get("demo") == "on"

    if not (target_username and api_key and user_key):
        messages.error(request, "eToro: target_username, api_key and "
                                "user_key are all required.")
        return redirect("brokers_page")
    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"eToro: user '{target_username}' not found.")
        return redirect("brokers_page")

    acct, _ = EtoroAccount.objects.get_or_create(user=user)
    acct.set_credentials(api_key, user_key)
    acct.demo = demo
    env = "demo" if demo else "live"
    # Routing opt-ins. Unchecked = absent = off, so a save that omits them
    # leaves eToro carrying nothing — the safe default when keys are new.
    acct.is_primary_for_stocks = request.POST.get("primary_stocks") == "on"
    acct.is_primary_for_forex = request.POST.get("primary_forex") == "on"
    acct.is_primary_for_commodity = (
        request.POST.get("primary_commodity") == "on")
    acct.is_primary_for_crypto = request.POST.get("primary_crypto") == "on"

    verdict, detail = etoro_probe(api_key, user_key, demo=demo)
    acct.connected = verdict == "ok"
    if acct.connected:
        acct.last_sync = timezone.now()
    acct.save()

    if verdict == "ok":
        messages.success(request, f"eToro keys saved and verified for "
                                  f"{target_username} ({env}).")
    elif verdict == "refused":
        messages.error(request, f"eToro keys saved for {target_username} "
                                f"({env}) but REFUSED by eToro ({detail}). "
                                f"Check both keys, and that the account is "
                                f"verified.")
    else:
        messages.warning(request, f"eToro keys saved for {target_username} "
                                  f"({env}) but could not be verified — the "
                                  f"probe answered {detail}. That may be the "
                                  f"probe, not your keys. They are recorded, "
                                  f"not connected.")
    return redirect("brokers_page")


@_admin_only
def save_saxo_credentials(request):
    from django.contrib.auth.models import User

    from bot_program.models import SaxoAccount

    target_username = request.POST.get("target_username", "").strip()
    app_key = request.POST.get("saxo_app_key", "").strip()
    app_secret = request.POST.get("saxo_app_secret", "").strip()
    redirect_uri = request.POST.get("saxo_redirect_uri", "").strip()
    sim = request.POST.get("sim") == "on"

    if not (target_username and app_key and app_secret and redirect_uri):
        messages.error(request, "Saxo: target_username, app_key, app_secret "
                                "and redirect_uri are all required.")
        return redirect("brokers_page")
    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"Saxo: user '{target_username}' not found.")
        return redirect("brokers_page")

    problem = _redirect_uri_problem(redirect_uri)
    if problem:
        messages.error(request, f"Saxo: the redirect URI {problem}. Nothing "
                                f"was saved.")
        return redirect("brokers_page")

    acct, _created = SaxoAccount.objects.get_or_create(user=user)
    was_sim = None if _created else acct.sim
    acct.set_credentials(app_key, app_secret)
    acct.redirect_uri = redirect_uri
    acct.sim = sim
    # Which asset classes this account carries. Default off, and off is
    # what an unchecked box means: a keyed Saxo row nobody has claimed a
    # class for is read and traded on by nothing.
    acct.is_primary_for_stocks = request.POST.get("primary_stocks") == "on"
    acct.is_primary_for_forex = request.POST.get("primary_forex") == "on"
    acct.is_primary_for_commodity = (
        request.POST.get("primary_commodity") == "on")
    acct.is_primary_for_crypto = request.POST.get("primary_crypto") == "on"
    # A session belongs to ONE application on ONE environment: a re-saved
    # key, secret, URI or sim flag closes whatever session was open, or the
    # keeper would present a SIM token to the live host (or an old app's
    # token under the new app's credentials) every ten minutes. An app key
    # cannot be verified on its own — Saxo answers only after the sign-in.
    acct.clear_session()
    acct.session_lost_at = None
    acct.session_lost_reason = ""
    # A reading taken on SIM describes a different account from the one a
    # LIVE key reaches. Keeping it would put a simulated balance in a real
    # book's cells — so the cells are dropped and the next sync refills
    # them. The HISTORY rows stay and carry their own `env`.
    if was_sim is not None and was_sim != sim:
        acct.last_equity = None
        acct.last_equity_currency = ""
        acct.last_equity_at = None
        acct.broker_positions = []
        acct.broker_positions_at = None
        env_note = (" The environment changed, so the stored equity and "
                    "holdings were dropped: they described the other one.")
    else:
        env_note = ""
    acct.save()
    messages.warning(request, f"Saxo application saved for {target_username} "
                              f"({'sim' if sim else 'live'}). Not yet "
                              f"connected: press 'Connect Saxo — sign in "
                              f"once' on the row to open the session. Any "
                              f"session that was open is closed.{env_note}")
    return redirect("brokers_page")


# ── Saxo: the one browser sign-in ────────────────────────────────────────

SAXO_STATE_KEY = "saxo_oauth_state"


@login_required
def saxo_connect(request):
    """Send the operator's browser to Saxo to sign in once.

    Own row only. A random `state` goes into the session and must come back
    unchanged, or the callback stores nothing — the standard defence
    against a forged callback landing tokens on someone else's row.
    """
    import secrets

    from bot_program.engine import saxo_oauth

    acct = getattr(request.user, "saxo_account", None)
    if acct is None or not acct.get_credentials()[0] or not acct.redirect_uri:
        messages.error(request, "Saxo: register the application (app key, "
                                "secret, redirect URI) before connecting.")
        return redirect("brokers_page")
    problem = _redirect_uri_problem(acct.redirect_uri)
    if problem:
        messages.error(request, f"Saxo: the registered redirect URI {problem} "
                                f"— fix it under Register Saxo Application "
                                f"before connecting.")
        return redirect("brokers_page")
    state = secrets.token_urlsafe(32)
    request.session[SAXO_STATE_KEY] = state
    return redirect(saxo_oauth.authorize_url(acct, state))


@login_required
def saxo_callback(request):
    """Saxo sends the browser back here with ?code=&state=.

    The path is fixed — /brokers/saxo/callback/ — and the host is whatever
    the operator registered; the row carries that full URI and it is the
    one presented to Saxo in the code exchange, so a mismatch is Saxo's
    error message and never a silent partial success.
    """
    from bot_program.engine import saxo_oauth

    acct = getattr(request.user, "saxo_account", None)
    expected = request.session.pop(SAXO_STATE_KEY, None)
    state = request.GET.get("state", "")
    code = request.GET.get("code", "")
    if acct is None:
        messages.error(request, "Saxo: no application registered on your "
                                "account.")
        return redirect("brokers_page")
    if not expected or state != expected:
        if expected is None and acct.session_alive():
            # A replayed callback (F5, back button, a prefetch) after a
            # successful exchange: the state was consumed by the hit that
            # opened the session. Nothing to redeem, nothing to apologise
            # for.
            messages.info(request, "Saxo: session already open — nothing to "
                                   "do.")
            return redirect("brokers_page")
        messages.error(request, "Saxo: sign-in state did not match — nothing "
                                "was stored. Start again from Connect.")
        return redirect("brokers_page")
    if not code:
        messages.error(request, "Saxo: no authorization code came back — "
                                f"{request.GET.get('error', 'no error given')}.")
        return redirect("brokers_page")
    try:
        payload = saxo_oauth.exchange_code(acct, code)
        saxo_oauth.store_tokens(acct, payload)
    except Exception as e:  # noqa: BLE001 — the message is the point
        # The hint is shown only when Saxo's own words name the redirect:
        # a wrong secret or a 503 has nothing to do with the portal.
        hint = (" The registered redirect URI must match the portal to the "
                "character." if "redirect" in str(e).lower() else "")
        messages.error(request, f"Saxo: the code exchange failed — {e}.{hint}")
        return redirect("brokers_page")
    messages.success(request, "Saxo session opened. It renews itself every "
                              "ten minutes while the platform is up; an "
                              "outage longer than forty minutes needs this "
                              "sign-in again.")
    return redirect("brokers_page")


# ── Forgetting a broker: the house pattern for pulling secrets ───────────

@_admin_only
def disconnect_saxo(request):
    """Forget the Saxo application AND its session for one account.

    The keeper renews any session it finds every ten minutes, so "remove
    the row in Django admin" was the only way to stop a session an
    operator no longer wants (wrong account signed in, laptop lost). Now
    it is a button, superuser + POST like every other secret-pulling view.
    """
    from bot_program.models import SaxoAccount

    target = request.POST.get("target_username", "").strip()
    try:
        acct = SaxoAccount.objects.get(user__username=target)
    except SaxoAccount.DoesNotExist:
        messages.error(request, f"Saxo: no application registered for "
                                f"'{target}'.")
        return redirect("brokers_page")
    acct.clear_session()
    acct.app_key_enc = ""
    acct.app_secret_enc = ""
    acct.session_lost_at = None
    acct.session_lost_reason = ""
    acct.save()
    messages.success(request, f"Saxo: keys and session forgotten for {target}. "
                              f"The keeper has nothing left to renew; register "
                              f"the application again to reconnect.")
    return redirect("brokers_page")


@_admin_only
def disconnect_etoro(request):
    """Forget the eToro keys for one account. Its routing flags stay — a
    flag with no key routes nowhere, and the router reads (None, None)."""
    from bot_program.models import EtoroAccount

    target = request.POST.get("target_username", "").strip()
    try:
        acct = EtoroAccount.objects.get(user__username=target)
    except EtoroAccount.DoesNotExist:
        messages.error(request, f"eToro: no keys recorded for '{target}'.")
        return redirect("brokers_page")
    acct.api_key_enc = ""
    acct.user_key_enc = ""
    acct.connected = False
    acct.save()
    messages.success(request, f"eToro: keys forgotten for {target}. Nothing "
                              f"routes to eToro until new keys pass the probe.")
    return redirect("brokers_page")

