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

#: The authenticated read used to prove a key pair reaches eToro. Taken from
#: the public API reference; if it 404s the probe reports "unknown" rather
#: than "refused", because a wrong PATH is not a wrong KEY.
ETORO_PROBE_URL = "https://api.etoro.com/API/User/V1/user"
ETORO_PROBE_TIMEOUT_S = 10


def etoro_probe(api_key: str, user_key: str) -> tuple:
    """("ok" | "refused" | "unknown", detail) — three answers, on purpose.

    200 means the keys work. 401 or 403 means eToro saw them and said no.
    Anything else — a 404 on the probe path, a 5xx, a timeout — means this
    call could not decide, and the operator must not be told their keys are
    wrong on the strength of it.
    """
    try:
        import requests
        r = requests.get(
            ETORO_PROBE_URL,
            headers={"x-api-key": api_key, "x-user-key": user_key},
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
        return "connected"
    if not has_adapter:
        return "recorded — adapter pending"
    return "recorded — never verified"


def _rows(user) -> list:
    from bot_program.engine.capabilities import declared

    def row(key, name, acct, env, has_adapter=True, extra=""):
        return {
            "key": key, "name": name, "account": acct,
            "env": env if acct is not None else "—",
            "status": _status(acct, has_adapter=has_adapter),
            "connected": bool(acct is not None
                              and getattr(acct, "connected", False)),
            "last_sync": getattr(acct, "last_sync", None),
            "capabilities": declared(key) if has_adapter else (),
            "has_adapter": has_adapter,
            "extra": extra,
        }

    ibkr = getattr(user, "ibkr_account", None)
    alpaca = getattr(user, "alpaca_account", None)
    oanda = getattr(user, "oanda_account", None)
    binance = getattr(user, "binance_account", None)
    etoro = getattr(user, "etoro_account", None)
    saxo = getattr(user, "saxo_account", None)

    saxo_extra = ""
    if saxo is not None:
        saxo_extra = ("session: renewable" if saxo.has_session
                      else "session: none — OAuth sign-in not yet done")

    return [
        row("ibkr", "Interactive Brokers", ibkr,
            _env(ibkr, "paper", "paper", "live") if ibkr else "—"),
        row("alpaca", "Alpaca", alpaca,
            _env(alpaca, "paper", "paper", "live") if alpaca else "—"),
        row("oanda", "OANDA", oanda,
            _env(oanda, "practice", "practice", "live") if oanda else "—"),
        row("binance", "Binance", binance,
            _env(binance, "testnet", "testnet", "live") if binance else "—"),
        row("etoro", "eToro", etoro,
            _env(etoro, "demo", "demo", "live") if etoro else "—",
            has_adapter=False),
        row("saxo", "Saxo Bank", saxo,
            _env(saxo, "sim", "sim", "live") if saxo else "—",
            has_adapter=False, extra=saxo_extra),
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

    verdict, detail = etoro_probe(api_key, user_key)
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

    acct, _ = SaxoAccount.objects.get_or_create(user=user)
    acct.set_credentials(app_key, app_secret)
    acct.redirect_uri = redirect_uri
    acct.sim = sim
    # An app key cannot be verified on its own: Saxo answers only after the
    # OAuth sign-in, which does not exist yet. Recorded, honestly not
    # connected.
    acct.connected = False
    acct.save()
    messages.warning(request, f"Saxo application saved for {target_username} "
                              f"({'sim' if sim else 'live'}). Not yet "
                              f"connected: the OAuth sign-in that opens a "
                              f"session arrives with the Saxo adapter.")
    return redirect("brokers_page")
