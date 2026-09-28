"""BROKERS — one page, every broker, what each one can hold (2026-09-17)

Before this page the platform's brokers were configured in three places
(the admin HQ page for OANDA / Alpaca / IBKR, Django admin for the rest) and
described nowhere. An operator could not answer "which broker holds my
stops" without reading `broker_router.py`.

The page answers three things per broker, side by side:

  * Is there an account row, and did its keys ever reach the broker?
    Three states — no row, recorded, connected — because "recorded" and
    "connected" send an operator to different places.
  * Which environment the row opens — demo, paper, practice, testnet, sim.
    On four brokers the flag describes the KEYS. On eToro it does not
    (measured 2026-09-23): one pair opens both worlds and the Demo tick
    alone picks the world, so the untick is guarded — see below.
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

THE DEMO UNTICK IS THE SWITCH TO REAL MONEY (measured 2026-09-23)

`etoro_smoke --user Sauron --other-world`: the pair eToro's portal calls
"virtual", saved here with Demo ticked, answered 200 on the DEMO
aggregate-portfolio (virtual balance 332,449.10 USD) AND 200 on the LIVE
aggregate-portfolio with the SAME pair. There is no demo-only pair. The
`demo/` URL segment alone picks the world (etoro_client._seg), that segment
is EtoroAccount.demo, and this form is the only page that writes it. So the
save that flips demo -> live is refused — nothing written — while any live
AssetBotConfig of the target user is enabled, while any class box is ticked
on that same save, or without the acting superuser's trading PIN (the same
`_pin_ok` that arms a live bot). demo -> demo and live -> live saves are
untouched.

AND THE TICK BACK IS THE SWITCH AWAY FROM THE REAL POSITIONS (2026-09-28)

live -> demo was deliberately left ungated: "the flip that stops real orders
stays frictionless, like disabling a bot". It does stop real ENTRIES. It also
sends every later CLOSE to the `demo/` segment — the router builds the client
from this one flag at call time (broker_router._etoro_client_for) — so a real
position still open at eToro can no longer be closed through the platform:
every close it sends (a manual close, the time stop, EMERGENCY FLATTEN) asks
the virtual portfolio, which honestly holds nothing. And the form made that
flip the default: the Demo box shipped CHECKED whatever the row said, so a
save made on a LIVE row to tick one class box flipped it to demo unless the
operator remembered to untick a box that read as the safe choice. Now the
form shows the row as it is on file, and the flip is refused, nothing
written, without an explicit "Switch world" tick, and — tick or no tick —
while any real eToro position the platform carried is still OPEN or
CLOSE_PENDING (`demo_tick_refusals`).

THE SAXO SAVE HAS THE SAME TRAP AND A RACE (2026-09-28)

The SIM box shipped checked too, so a routing-only save on a LIVE Saxo row
flipped it to SIM, closed the session the operator had just signed in for
and dropped the readings. A flip while the session is alive now needs the
same "Switch world" tick. And a save that does not change the application
writes the four class flags and nothing else: a full-row save wrote back
the token pair as it was loaded, and a refresh landing in between
(saxo_oauth.store_tokens) rotates that pair — the stale refresh token put
back is refused at the next refresh and the session is lost anyway. The
eToro save, which waits up to ETORO_PROBE_TIMEOUT_S on the network before it
writes, names its columns for the same reason: sync_etoro_accounts writes
the margin cells in that window.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .views_admin_hq import _admin_only, _pin_ok

logger = logging.getLogger(__name__)

ETORO_PROBE_TIMEOUT_S = 10


def etoro_probe(api_key: str, user_key: str, demo: bool = True) -> tuple:
    """("ok" | "refused" | "unknown", detail) — three answers, on purpose.

    200 means the keys work. 401 or 403 means eToro saw them and said no.
    Anything else — a 404, a 5xx, a timeout — means this call could not
    decide, and the operator must not be told their keys are wrong on the
    strength of it.

    The endpoint is the adapter's own aggregate-portfolio read, built by
    the adapter's path table, so the probe and the client can never disagree
    about where eToro lives. The first version of this hit a host and path
    taken from an earlier, unverified guess; it would have answered
    "unknown" for every real key. `demo` picks the PATH, not the keys:
    measured 2026-09-23, the same pair answers 200 on both worlds, so a 401
    here is eToro refusing the pair on the world asked — never "these keys
    belong to the other world".

    AND IT EARNED ITS THIRD STATE ON 2026-09-22. The first real key ever
    presented to this platform made this probe answer 404 — not 401 — and
    the three-state reading above is what stopped the operator being told
    their keys were bad. They were not: the paths were, and the 404 was the
    adapter composing /info/real/aggregate-portfolio, which eToro does not
    publish. Measured against the same key: the corrected path answers 200.
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
        # keys or its session. Saxo sat here until SaxoTrader landed
        # (2026-09-19) and every row now has an adapter — the rule stays for
        # the next broker keyed before its client exists, and is held by
        # tests/test_brokers_page on _status itself.
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
    # A tier that is a BELIEF is badged as one: eToro declares
    # fractional_units from the public reference, unmeasured until
    # ETORO_DEPARTURE §4 D2c, and sends fractions only while the
    # fractional_units_live switch is on.
    notes = {"fractional_units": "believed from the public reference until "
                                 "the demo proof D2c; sent only while "
                                 "fractional_units_live is ON"}

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
            "capabilities": ([(c, notes.get(c, "")) for c in declared(key)]
                             if has_adapter else []),
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
        # Adapter landed 2026-09-19 (engine/saxo_client.py) and
        # capabilities.declared("saxo") answers for it. has_adapter=False
        # survived here for three days, so a completed sign-in painted the
        # row as a broker nothing can be asked of — on the page the sign-in
        # returns to.
        row("saxo", "Saxo Bank", saxo,
            _env(saxo, "sim", "sim", "live") if saxo else "—",
            extra=saxo_extra, needs_signin=saxo_needs_signin),
    ]


def _on_file_words(username: str, world: str, carried: list,
                   session: str = "") -> str:
    classes = ", ".join(carried) if carried else "nothing"
    parts = [world] + ([session] if session else []) + [
        f"primary for {classes}"]
    return f"On file for {username}: {' · '.join(parts)}."


def _etoro_on_file(acct, username: str) -> dict:
    """What the eToro form shows ticked for one target: its row as it is
    on file, or a new row's defaults (Demo ticked, every class off).

    THE FORM USED TO SHIP ONE STATE FOR EVERY ROW — Demo ticked, every
    class unticked — and posts every field at once, so a save made to
    change one class box on a LIVE row wrote demo=True unless the operator
    remembered to untick the one box that looks like the safe choice. That
    is the flip that strands the real positions (module docstring). The
    boxes now start where the row is, so a save that changes nothing else
    changes nothing else."""
    if acct is None:
        return {"ticked": ["demo"],
                "words": f"On file for {username}: no eToro row yet — a "
                         f"first save starts it as ticked here."}
    ticked = (["demo"] if acct.demo else []) + [
        box for box, field in _BOX_FIELDS if getattr(acct, field, False)]
    carried = [word for (box, word) in _CLASS_BOXES if box in ticked]
    return {"ticked": ticked,
            "words": _on_file_words(username,
                                    "DEMO" if acct.demo else "LIVE", carried)}


def _saxo_on_file(acct, username: str) -> dict:
    """The Saxo form's twin of _etoro_on_file, plus the redirect URI — not
    a secret (it is printed in the browser's address bar during the sign-in)
    and one of the four things that close the session when they change, so
    a routing-only save should not depend on retyping it to the character.
    The key and the secret are never rendered: they are retyped."""
    if acct is None:
        return {"ticked": ["sim"], "redirect_uri": "",
                "words": f"On file for {username}: no Saxo application yet "
                         f"— a first save starts it as ticked here."}
    ticked = (["sim"] if acct.sim else []) + [
        box for box, field in _BOX_FIELDS if getattr(acct, field, False)]
    carried = [word for (box, word) in _CLASS_BOXES if box in ticked]
    session = ("session open" if acct.session_alive()
               else "no open session")
    return {"ticked": ticked, "redirect_uri": acct.redirect_uri or "",
            "words": _on_file_words(username, "SIM" if acct.sim else "LIVE",
                                    carried, session)}


def _form_targets(users, me) -> list:
    """One entry per account the two forms can target, each carrying what
    is on file for it, with `me` preselected.

    The template cannot look a row up by the dropdown's value, so every
    option carries its own row's state (data attributes) and a few lines of
    script move the boxes when the dropdown moves. Without script the page
    still renders the preselected account's row, which is the one a
    superuser edits most."""
    from bot_program.models import EtoroAccount, SaxoAccount
    users = list(users)
    ids = [u.pk for u in users]
    etoro = {a.user_id: a for a in EtoroAccount.objects.filter(user_id__in=ids)}
    saxo = {a.user_id: a for a in SaxoAccount.objects.filter(user_id__in=ids)}
    return [{"username": u.username, "is_superuser": u.is_superuser,
             "selected": u.pk == me.pk,
             "etoro": _etoro_on_file(etoro.get(u.pk), u.username),
             "saxo": _saxo_on_file(saxo.get(u.pk), u.username)}
            for u in users]


@login_required
def brokers_page(request):
    from bot_program.engine.capabilities import CAPABILITIES
    context = {
        "page_id": "brokers",
        "rows": _rows(request.user),
        "capabilities": list(CAPABILITIES.keys()),
        "can_edit": request.user.is_superuser,
        # GAP 4 (2026-09-26): the proof state printed beside each eToro box.
        "etoro_proof": etoro_proof_states(),
    }
    if request.user.is_superuser:
        from django.contrib.auth.models import User
        context["users"] = User.objects.filter(is_active=True).order_by(
            "username")
        targets = _form_targets(context["users"], request.user)
        mine = next((t for t in targets if t["selected"]), None)
        context["form_targets"] = targets
        # What the boxes render ticked before any script runs: the
        # preselected account's row, or a new row's defaults.
        context["etoro_on_file"] = (mine["etoro"] if mine else
                                    _etoro_on_file(None, request.user.username))
        context["saxo_on_file"] = (mine["saxo"] if mine else
                                   _saxo_on_file(None, request.user.username))
    return render(request, "dashboard/brokers.html", context)


#: The measurement, in the words the flash prints. One eToro pair opens
#: both worlds (etoro_smoke --user Sauron --other-world, 2026-09-23: demo
#: aggregate-portfolio 200 AND live aggregate-portfolio 200, same pair).
DEMO_UNTICK_MEASURED = (
    "measured 2026-09-23: the same eToro pair answered 200 on the demo AND "
    "the live aggregate-portfolio, so unticking Demo is the one click "
    "between a virtual order and a real one — the keys do not change")

#: The four class boxes the form posts, and the word the flash uses.
_CLASS_BOXES = (("primary_stocks", "stocks"), ("primary_forex", "forex"),
                ("primary_commodity", "commodities"),
                ("primary_crypto", "crypto"))

#: The column behind each box — the same four on the eToro and the Saxo row.
#: On Saxo they are ALL a save that leaves the application alone may write.
_BOX_FIELDS = (("primary_stocks", "is_primary_for_stocks"),
               ("primary_forex", "is_primary_for_forex"),
               ("primary_commodity", "is_primary_for_commodity"),
               ("primary_crypto", "is_primary_for_crypto"))
_FLAG_FIELDS = tuple(field for _box, field in _BOX_FIELDS)

#: The reading cells an environment flip drops, on both rows: they describe
#: the world the row no longer points at.
_WORLD_CELLS = ("last_equity", "last_equity_currency", "last_equity_at",
                "broker_positions", "broker_positions_at")

#: The box that says "yes, I mean to change this row's world". Unticked by
#: default and never pre-filled: it is the one box that must be a decision
#: made on this save.
CONFIRM_WORLD_CHANGE = "confirm_world_change"

#: THE PROOF TOKENS EACH eToro BOX NEEDS (2026-09-26, GAP 4). The gate
#: (asset_engine/base.py AssetBot._etoro_entry_refusal, step 1) keys on
#: the INSTRUMENT's class, so the stocks box needs three tokens — an ETF
#: or an index in a stock config needs "etf" or "index", not "stock" —
#: and a SELL needs "short" as well, on every box.
ETORO_BOX_TOKENS = (("stock", ("stock", "etf", "index")),
                    ("forex", ("forex",)),
                    ("commodity", ("commodity",)),
                    ("crypto", ("crypto",)))


def _etoro_proven() -> frozenset:
    """ETORO_PROVEN read at CALL time, off the module — the gate's own
    rule, so a test states a token by patching that one name."""
    from bot_program.asset_engine import base
    return frozenset(base.ETORO_PROVEN)


def etoro_proof_states() -> dict:
    """What the page prints beside each eToro box: box -> words, and
    "short". Three states per box: every token pinned ("proof pinned"),
    none ("no proof pinned — entries refused"), or some — the stocks box
    only — naming what is still refused."""
    proven = _etoro_proven()
    out = {}
    for box, tokens in ETORO_BOX_TOKENS:
        pinned = [t for t in tokens if t in proven]
        missing = [t for t in tokens if t not in proven]
        if not missing:
            out[box] = "proof pinned"
        elif not pinned:
            out[box] = "no proof pinned — entries refused"
        else:
            out[box] = (f"proof pinned for {', '.join(pinned)} only — "
                        f"{', '.join(missing)} entries refused")
    out["short"] = ("shorts proven" if "short" in proven
                    else "no short proven")
    return out


def unproven_note(carried) -> str:
    """The save flash's words for the classes this save ticked whose
    proof is not pinned — "" when every one is, or nothing is ticked.
    Printed on every branch, the verified one included: a verified save
    used to say nothing while every entry of an unproven class was
    refused at the tick."""
    if not carried:
        return ""
    proven = _etoro_proven()
    missing = [t for box, tokens in ETORO_BOX_TOKENS if box in carried
               for t in tokens if t not in proven]
    note = ""
    if missing:
        which, until = (("that class", "until its proof lands")
                        if len(missing) == 1 else
                        ("those classes", "each until its own proof lands"))
        note = (f" No demo fill-and-close proof is pinned for "
                f"{', '.join(missing)} (ETORO_PROVEN; "
                f"deploy/ETORO_DEPARTURE.md §7, bullet 0): every eToro "
                f"entry of {which} is refused (gate_blocked), by the bots "
                f"and by TAKE TRADE, {until}; nothing is sent in the "
                f"meantime.")
    if "short" not in proven:
        note += (" Every short is refused as well until the short proof "
                 "is pinned." if missing else
                 " Every short is refused until the short proof is "
                 "pinned.")
    return note


def demo_untick_refusals(request, user) -> list:
    """Why THIS save may not flip the target user's row from demo to live —
    every reason that applies, in order, or [] when the flip may proceed.

    Three checks, all of them, so the operator reads the whole list once:

      * an ENABLED live AssetBotConfig of the target user — the router
        would send its next entry to the live world on the next beat,
        with the pair that was placing virtual orders a minute ago;
      * a class box ticked on the SAME save — a tick makes the live row
        the book and the venue (broker_backed) in the click that made it
        live; the flip and the tick are two saves, in that order;
      * the acting superuser's trading PIN, checked by the same `_pin_ok`
        that arms a live bot and flattens the book. A superuser with no
        PIN set cannot untick Demo at all, which is the intended reading.

    The caller is the only writer of EtoroAccount.demo (the row is not in
    Django admin); a shell bypasses this, and every demo write snippet in
    deploy/ETORO_DEPARTURE.md asserts the world for that reason.
    """
    from bot_program.models import AssetBotConfig

    reasons = []
    live = list(AssetBotConfig.objects.filter(
        user=user, enabled=True, mode="live").order_by("id")
        .values_list("id", "name"))
    if live:
        named = ", ".join(f"[{i}] {n}" for i, n in live)
        reasons.append(f"live config(s) ENABLED for {user.username}: {named} "
                       f"— the next beat would place a real order; disable "
                       f"them first (bot off <id>)")
    ticked = [word for field, word in _CLASS_BOXES
              if request.POST.get(field) == "on"]
    if ticked:
        reasons.append(f"class box(es) ticked on the same save "
                       f"({', '.join(ticked)}) — a tick makes the live row "
                       f"the book and the venue in this click; untick Demo "
                       f"with every box OFF, then tick one class on a "
                       f"second save")
    if not _pin_ok(request):
        reasons.append("the trading PIN was not supplied or is wrong — the "
                       "same PIN that arms a live bot")
    return reasons


def live_etoro_positions(user) -> list:
    """The target user's REAL positions at eToro that the platform still
    has to close: AssetBotTrade rows, OPEN or CLOSE_PENDING, not paper,
    stamped as carried by eToro (metadata["broker"], AssetBot.venue_stamps)
    and not stamped as filled in the virtual world (broker_env "paper").

    A row with NO world stamp counts. The question here is "could this
    switch strand a real position", the row being switched is LIVE today,
    and an unknown world may be the real one; counting it costs one
    refusal the operator can read, missing it costs a position nothing can
    close. (reconcile_asset reads an unknown world the other way, and for
    its own reason: there a guess would book a close.)

    Filtered in Python, as etoro_smoke._unstamped_open_rows explains: a
    JSON-key filter in the ORM drops rows whose metadata lacks the key."""
    from bot_program.models import AssetBotTrade
    out = []
    for tr in (AssetBotTrade.objects
               .filter(config__user=user, paper=False,
                       status__in=("OPEN", "CLOSE_PENDING"))
               .only("pk", "symbol", "metadata").order_by("pk")):
        meta = tr.metadata if isinstance(tr.metadata, dict) else {}
        if str(meta.get("broker") or "") != "etoro":
            continue
        if str(meta.get("broker_env") or "").lower() == "paper":
            continue
        out.append(tr)
    return out


def demo_tick_refusals(request, user) -> list:
    """Why THIS save may not flip the target user's row from LIVE to demo —
    every reason that applies, in order, or [] when the flip may proceed.

    Two checks, both printed at once like demo_untick_refusals:

      * the "Switch world" box (CONFIRM_WORLD_CHANGE) was not ticked. The
        Demo box now shows the row as it is on file, so a tick there is
        the operator's own; this box is what tells the tick apart from a
        page left over from before, or a habit from the demo weeks.
      * a real position eToro carried is still OPEN or CLOSE_PENDING. The
        router builds the client from this flag at call time, so from this
        save on every close the platform sends goes to the `demo/` segment,
        which honestly holds nothing, and the real position stays open with
        nothing on the platform able to reach it. Refused even with the box
        ticked: no tick makes that safe. Close them first (or let them
        close), then switch.

    No PIN: this direction places no real order. What it can do is stop
    the platform from closing one, and that is what the checks are about.
    """
    reasons = []
    if request.POST.get(CONFIRM_WORLD_CHANGE) != "on":
        reasons.append("the 'Switch world' box was not ticked — this row "
                       "is LIVE, and a save with Demo ticked sends every "
                       "later order AND every close to eToro's virtual "
                       "portfolio; if you only meant to change the class "
                       "boxes, leave Demo unticked and save again")
    real = live_etoro_positions(user)
    if real:
        n = len(real)
        named = ", ".join(f"[{t.pk}] {t.symbol}" for t in real)
        if n == 1:
            reasons.append(f"1 real position is still open at eToro; "
                           f"switching to demo would cut the platform off "
                           f"from closing it ({named}) — close it first, "
                           f"then switch")
        else:
            reasons.append(f"{n} real positions are still open at eToro; "
                           f"switching to demo would cut the platform off "
                           f"from closing them ({named}) — close them "
                           f"first, then switch")
    return reasons


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

    acct, _created = EtoroAccount.objects.get_or_create(user=user)
    was_demo = None if _created else acct.demo
    # THE UNTICK. A demo -> live flip is the one click between a virtual
    # order and a real one with the SAME pair (module docstring, measured
    # 2026-09-23). Refused before anything is written — the keys are not
    # re-encrypted, the flags are not read, the probe is not sent.
    if was_demo is True and not demo:
        refusals = demo_untick_refusals(request, user)
        if refusals:
            why = " ".join(f"({i}) {r}." for i, r in enumerate(refusals, 1))
            messages.error(request, f"eToro: REFUSED to untick Demo for "
                                    f"{target_username} — nothing was saved. "
                                    f"{DEMO_UNTICK_MEASURED}. Refused because: "
                                    f"{why}")
            return redirect("brokers_page")
    # THE TICK BACK. A live -> demo flip points every later close at the
    # virtual portfolio (module docstring). Refused on the same terms as
    # the untick — before anything is written, the probe not sent — without
    # the "Switch world" tick, and while a real eToro position is open.
    if was_demo is False and demo:
        refusals = demo_tick_refusals(request, user)
        if refusals:
            why = " ".join(f"({i}) {r}." for i, r in enumerate(refusals, 1))
            messages.error(request, f"eToro: REFUSED to tick Demo for "
                                    f"{target_username} — nothing was saved. "
                                    f"The row is LIVE: the same pair opens "
                                    f"both worlds and the Demo tick alone "
                                    f"picks where every order and every "
                                    f"close goes. Refused because: {why}")
            return redirect("brokers_page")
    acct.set_credentials(api_key, user_key)
    acct.demo = demo
    env = "demo" if demo else "live"
    # THE COLUMNS THIS SAVE WRITES, AND NO OTHER. The probe below waits up
    # to ETORO_PROBE_TIMEOUT_S on the network between this row's read and
    # its write, and sync_etoro_accounts writes the equity, holdings and
    # margin cells (update_fields) in exactly that kind of window: a
    # full-row save put back the cells as they were read, and
    # _leverage_headroom sizes the next order against a used margin that
    # is no longer true.
    fields = ["api_key_enc", "user_key_enc", "demo", *_FLAG_FIELDS,
              "connected"]
    # A reading taken on the VIRTUAL portfolio describes a different account
    # from the one the same pair reaches on the live world. The demo box
    # used to ship checked whatever the row said, so the ordinary sequence
    # — save as demo, notice the env column, re-save as live — would leave
    # a virtual balance on a row now flagged LIVE, with a timestamp minutes
    # old: fresh enough for tracking_freeze_reason to pass it and for every
    # follower pool to be sized against it. The same drop the Saxo save
    # does. The HISTORY rows stay and carry their own `env`.
    env_note = ""
    if was_demo is not None and was_demo != demo:
        acct.last_equity = None
        acct.last_equity_currency = ""
        acct.last_equity_at = None
        acct.broker_positions = []
        acct.broker_positions_at = None
        fields += list(_WORLD_CELLS)
        env_note = (" The environment changed, so the stored equity and "
                    "holdings were dropped: they described the other one.")
        if not demo:
            env_note += (" Demo UNTICKED: from this save the same pair "
                         "places REAL orders.")
        else:
            env_note += (" Demo TICKED: from this save every order and "
                         "every close goes to the virtual portfolio.")
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
        fields.append("last_sync")
    acct.save(update_fields=fields)

    # BEING THE BOOK IS NOT THE PROBE'S VERDICT. broker_backed asks only
    # "keyed AND primary for something" — deliberately, because `connected`
    # is a flag with no expiry — so a row eToro has just refused becomes the
    # account every pool and every limit is measured against, and its equity
    # reads as an em dash everywhere the real book used to show a number.
    # Saying "saved but REFUSED" did not say that.
    carried = [c for c in ("stock", "forex", "commodity", "crypto")
               if acct.is_primary_for(c)]
    book_note = ""
    if carried and not acct.connected:
        book_note = (f" It is flagged primary for {', '.join(carried)}, so it "
                     f"is now the book: every pool and every limit is "
                     f"measured against an account that just refused us. "
                     f"Untick those boxes or fix the keys.")
    # GAP 4 (2026-09-26): a ticked class whose demo proof is not pinned
    # saves, and every entry of it is refused at the tick — said here, on
    # every branch below, the verified one included.
    book_note += unproven_note(carried)

    if verdict == "ok":
        messages.success(request, f"eToro keys saved and verified for "
                                  f"{target_username} ({env}).{book_note}"
                                  f"{env_note}")
    elif verdict == "refused":
        messages.error(request, f"eToro keys saved for {target_username} "
                                f"({env}) but REFUSED by eToro ({detail}). "
                                f"Check both keys, and that the account is "
                                f"verified.{book_note}{env_note}")
    else:
        messages.warning(request, f"eToro keys saved for {target_username} "
                                  f"({env}) but could not be verified — the "
                                  f"probe answered {detail}. That may be the "
                                  f"probe, not your keys. They are recorded, "
                                  f"not connected.{book_note}{env_note}")
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
    # THE WORLD FLIP, WHILE A SESSION IS OPEN. The SIM box used to ship
    # checked whatever the row said, so a save made on a LIVE row to tick
    # one class box flipped it to SIM: the session the operator had just
    # signed in for closed, the readings were dropped, and live keys sat on
    # a row flagged SIM. The form now shows the row as it is on file; a flip
    # that would close an open session also needs the "Switch world" tick
    # on the same save. Refused before anything is written. A row with no
    # open session has nothing to lose to the flip, and is not asked.
    if (was_sim is not None and was_sim != sim and acct.session_alive()
            and request.POST.get(CONFIRM_WORLD_CHANGE) != "on"):
        on_file, asked = ("SIM", "LIVE") if was_sim else ("LIVE", "SIM")
        messages.error(request,
                       f"Saxo: REFUSED to switch {target_username} from "
                       f"{on_file} to {asked} — nothing was saved. The row "
                       f"has an open session, and changing the SIM box "
                       f"closes it and drops the stored equity and "
                       f"holdings. If you only meant to change the class "
                       f"boxes, leave SIM {'ticked' if was_sim else 'unticked'}"
                       f" as it is on file and save again; if you mean to "
                       f"switch, tick 'Switch world' on the same save.")
        return redirect("brokers_page")
    # WHAT ACTUALLY CHANGED, compared DECRYPTED: Fernet returns a different
    # ciphertext for the same plaintext every time, so comparing the stored
    # columns would answer "changed" on every single save.
    try:
        old_key, old_secret = acct.get_credentials()
    except Exception:  # noqa: BLE001 — an unreadable row counts as changed
        old_key, old_secret = "", ""
    app_changed = bool(
        _created or old_key != app_key or old_secret != app_secret
        or (acct.redirect_uri or "") != redirect_uri or acct.sim != sim)
    if app_changed:
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
    #
    # ONLY when one of those four actually changed. This view is also the
    # ONLY writer of the primary-for flags anywhere in the platform, and the
    # form posts every field at once, so clearing unconditionally meant
    # "tick a routing box, lose the session you just signed in for" — with
    # no other way to tick it, and nothing able to recover the session: the
    # keeper skips rows with no refresh token, and saxo_smoke stops at "no
    # live Saxo session".
    if app_changed:
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
    if app_changed:
        acct.save()
    else:
        # THE FOUR FLAGS AND NOTHING ELSE. Everything else on this row was
        # read when the view started, and the token pair is not the view's
        # to write: the keeper (refresh_saxo_sessions) and ensure_access_token
        # rotate it through saxo_oauth.store_tokens, and Saxo's refresh token
        # changes on every refresh. A full save landing after a rotation put
        # the OLD pair back — the next refresh presents a token Saxo has
        # already retired, is refused, and the session this branch exists
        # to keep is marked lost ten minutes later. sync_saxo_accounts'
        # cells ride on the same rule. A sim flip is always app_changed,
        # so nothing this branch skips could have changed.
        acct.save(update_fields=list(_FLAG_FIELDS))
    if app_changed:
        messages.warning(request,
                         f"Saxo application saved for {target_username} "
                         f"({'sim' if sim else 'live'}). Not yet connected: "
                         f"press 'Connect Saxo — sign in once' on the row to "
                         f"open the session. Any session that was open is "
                         f"closed.{env_note}")
    else:
        messages.success(request,
                         f"Saxo routing saved for {target_username}: the "
                         f"application itself is unchanged, so the open "
                         f"session was left alone.")
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

