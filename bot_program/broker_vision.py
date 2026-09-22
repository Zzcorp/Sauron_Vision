"""Where the money is, what each broker says it holds, and where the
platform and the broker disagree. One computation, two renderers.

WHY THIS EXISTS. capital_truth answers every capital question for ONE
broker — the book, whichever row broker_backed() returns. With three wired
venues that is no longer the operator's question. Theirs is: how much is at
each broker, what does each say is open, what does the PLATFORM think is
open, and where do those two accounts of the world differ. Nothing put
those side by side, so the answer lived in four pages and a shell.

WHAT IT PROMISES, AND WHAT IT REFUSES TO PRETEND

  * Cached columns only. The sync tasks are the only things that talk to a
    broker; a page that opened a socket would be a page that hangs.
  * Three states, never two. A broker never read is an em dash, not a
    zero — and a DIVERGENCE that cannot be computed says so rather than
    reporting "the broker holds nothing", which is the same sentence a
    flat account produces and means something entirely different.
  * Live and paper are never pooled, and never compared: a paper row has
    no broker position by construction, so it is counted apart and
    excluded from every divergence.
  * Attribution is named. A live row records the broker that carried it
    since 2026-09-19 (metadata["broker"]); older rows are attributed by
    TODAY's routing rule, which is a guess when a flag has moved since.
    Each row says which of the two it is.
"""
from __future__ import annotations

from django.utils import timezone

#: (broker key, the user attribute holding the row, the name to print).
#: In VENUE_PRECEDENCE order, so the page reads top-down the way the
#: router decides.
BROKER_ROWS = (
    ("saxo", "saxo_account", "Saxo Bank"),
    ("etoro", "etoro_account", "eToro"),
    ("ibkr", "ibkr_account", "Interactive Brokers"),
)

#: The classes an account row can claim. "etf" rides with "stock" on every
#: row's is_primary_for(), and is listed because an INSTRUMENT can carry it —
#: not a config: AssetBotConfig.ASSET_CLASS_CHOICES has no "etf" entry, and
#: the router keys off the Instrument's class, not the config's
#: (broker_router: `asset_class = inst.asset_class if inst else "crypto"`).
#: "index" rides on the same boolean and is deliberately NOT listed here:
#: `_claims` below skips "etf" for exactly that reason, so adding index would
#: print one column twice in the treasury claims line. The disclosure lives
#: on the checkbox label instead.
ROUTABLE_CLASSES = ("stock", "etf", "forex", "commodity", "crypto")

#: Past this, a reading is old enough that the page says so. Not a limit —
#: the sync runs every 900 s, so anything past two cycles has missed one.
STALE_AFTER_S = 1900


def _age(when) -> "int | None":
    return None if when is None else int(
        (timezone.now() - when).total_seconds())


def _age_text(seconds) -> str:
    """Seconds, minutes, hours — the three the shell twin already prints.

    The page rendered `age_seconds` raw, so a reading eight hours old read
    "28800 s" and the operator divided by 3600 under pressure. `age_seconds`
    stays for anything that compares; this is what a human reads.
    """
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


def _reading(acct) -> "dict | None":
    """The equity reading on a row, in capital_truth.account_equity's exact
    shape — so a template that can render one can render all three. None
    means never measured."""
    value = getattr(acct, "last_equity", None)
    at = getattr(acct, "last_equity_at", None)
    if value is None or at is None:
        return None
    value = float(value)
    return {"value": value, "value_text": f"{value:,.2f}",
            "currency": getattr(acct, "last_equity_currency", "") or "",
            "at": at, "age_seconds": _age(at),
            "age_text": _age_text(_age(at))}


def _held(acct) -> "dict | None":
    """The broker's own holdings snapshot, or None when never read."""
    rows = getattr(acct, "broker_positions", None)
    at = getattr(acct, "broker_positions_at", None)
    if rows is None or at is None:
        return None
    return {"rows": list(rows or []), "at": at, "age_seconds": _age(at),
            "age_text": _age_text(_age(at))}


def _keyed(kind: str, acct) -> bool:
    try:
        if kind == "ibkr":
            return bool(acct.get_account_id() or "")
        return bool(acct.get_credentials()[0])
    except Exception:  # noqa: BLE001 — an unreadable row is not keyed
        return False


def _session_line(kind: str, acct) -> str:
    """One short phrase for "can this broker be reached at all", in the
    words each venue's own failure uses."""
    if kind == "saxo":
        if not _keyed(kind, acct):
            return "no application registered"
        if getattr(acct, "session_lost_at", None) and not acct.has_session:
            return f"session LOST — {acct.session_lost_reason or 'sign in again'}"
        if not acct.has_session:
            return "never signed in"
        if not acct.session_alive():
            return "session EXPIRED — sign in again"
        if not acct.access_token_valid():
            return "renewing at the next cycle"
        return "session live"
    if kind == "etoro":
        if not _keyed(kind, acct):
            return "no keys"
        return "keys recorded" if not getattr(acct, "connected", False) \
            else "keys verified"
    if not _keyed(kind, acct):
        return "no account id"
    # IBKR's `connected` is a boolean with no expiry; the AGE of the
    # reading is the only honest answer about reachability, and the row
    # carries it separately.
    return "gateway session — judge it by the reading's age"


def _claims(acct) -> list:
    fn = getattr(acct, "is_primary_for", None)
    if not callable(fn):
        return []
    out = []
    for cls in ROUTABLE_CLASSES:
        if cls == "etf":
            continue          # rides with stock on every row
        try:
            if fn(cls):
                out.append(cls)
        except Exception:  # noqa: BLE001
            continue
    return out


def brokers(user) -> list:
    """One dict per account row that EXISTS, in precedence order.

    A row that does not exist is not listed: the operator has not created
    it, and an empty line would read as a broker that failed.
    """
    from bot_program.capital_truth import broker_backed

    from bot_program.capital_truth import broker_env

    book = broker_backed(user)
    out = []
    for kind, attr, name in BROKER_ROWS:
        acct = getattr(user, attr, None)
        if acct is None:
            continue
        reading, held = _reading(acct), _held(acct)
        env = getattr(acct, "env_label", None)
        if env is None:
            env = ("sim" if getattr(acct, "sim", False) else
                   "demo" if getattr(acct, "demo", False) else "live")
        out.append({
            "kind": kind, "name": name, "label": getattr(acct, "label", ""),
            "env": env,
            # THE WORD THE TEMPLATE COMPARES, beside the label a human reads.
            # env_label is uppercase and venue-shaped ("SIM", "LIVE · 4003"),
            # so every `env == 'live'` test on the page was false and painted
            # a real account in the simulator's colour. broker_env is the
            # function the readings are already filed under, and it has three
            # answers: live, paper, and "" for a row that cannot say.
            "world": broker_env(acct) or "unknown",
            "keyed": _keyed(kind, acct),
            "session": _session_line(kind, acct),
            "equity": reading,
            "equity_stale": bool(reading and reading["age_seconds"] is not None
                                 and reading["age_seconds"] > STALE_AFTER_S),
            "held": held,
            "held_n": None if held is None else len(held["rows"]),
            "claims": _claims(acct),
            "is_book": book is not None and acct.pk == book.pk
            and type(acct) is type(book),
            "last_sync": getattr(acct, "last_sync", None),
        })
    return out


def routing(user) -> list:
    """Per asset class: where a NEW trade would go, and who else claimed it.

    Read through the router's own helpers, so this cannot drift from what
    actually happens when a bot fires.
    """
    from bot_program.engine import broker_router as router

    checks = (("saxo", router._saxo_overrides),
              ("etoro", router._etoro_overrides),
              ("ibkr", router._ibkr_overrides))
    out = []
    for cls in ROUTABLE_CLASSES:
        claimants = [kind for kind, fn in checks if fn(user, cls)]
        winner = claimants[0] if claimants else router._broker_for_asset_class(cls)
        out.append({"asset_class": cls, "winner": winner,
                    "claimants": claimants,
                    "contested": len(claimants) > 1,
                    "by_default": not claimants})
    return out


def _broker_for_row(user, trade, routes: dict) -> tuple:
    """(broker key, how we know) for one platform row.

    "recorded" when the row itself says which broker carried it, "routing"
    when it is inferred from today's rule — which is a guess if a flag has
    moved since the row opened, and the page says so.
    """
    meta = trade.metadata or {}
    named = str(meta.get("broker") or "")
    if named:
        return named, "recorded"
    return routes.get(trade.asset_class, "paper"), "routing"


def platform_positions(user) -> dict:
    """What the PLATFORM believes is open, live and paper counted apart.

    {"live": [...], "paper_n": int} — paper rows are counted, not listed:
    they are the campaign's business and they have no broker to disagree
    with.
    """
    from bot_program.asset_models import AssetBotTrade

    routes = {r["asset_class"]: r["winner"] for r in routing(user)}
    qs = (AssetBotTrade.objects
          .filter(config__user=user, status="OPEN")
          .select_related("config").order_by("symbol"))
    live, paper_n = [], 0
    for t in qs:
        if t.paper:
            paper_n += 1
            continue
        kind, how = _broker_for_row(user, t, routes)
        live.append({
            "symbol": (t.symbol or "").upper(), "side": t.side,
            "qty": float(t.qty or 0), "entry": float(t.entry_price or 0),
            "asset_class": t.asset_class, "config": t.config.name,
            "broker": kind, "attribution": how,
            "opened_at": t.opened_at,
            "protected": bool((t.metadata or {}).get("protected")),
            "working": bool((t.metadata or {}).get("entry_working")),
        })
    return {"live": live, "paper_n": paper_n}


def divergence(user, rows=None, platform=None) -> list:
    """Per broker: what only the broker holds, what only the platform has,
    and what both agree on.

    UNKNOWN is a first-class answer. A broker whose holdings have never
    been read cannot be compared, and saying "nothing only at the broker"
    there would be the same sentence a genuinely flat account produces.

    Symbols are compared upper-cased and stripped. That is the whole
    comparison, and it is stated because a broker that spells an
    instrument differently from the catalogue would show as a divergence
    that is really a spelling — the adapters map their symbols back on the
    way in, so this holds today and would break loudly rather than
    silently if one stopped.
    """
    rows = brokers(user) if rows is None else rows
    platform = platform_positions(user) if platform is None else platform
    out = []
    for row in rows:
        mine = [p for p in platform["live"] if p["broker"] == row["kind"]]
        if row["held"] is None:
            out.append({"kind": row["kind"], "name": row["name"],
                        "known": False,
                        "reason": ("never read — the sync has not stored a "
                                   "holdings snapshot for this broker"),
                        "only_broker": [], "only_platform": [],
                        "agree": [], "platform_n": len(mine)})
            continue
        held = {}
        for h in row["held"]["rows"]:
            sym = str(h.get("symbol") or "").strip().upper()
            if sym:
                held[sym] = h
        ours = {p["symbol"]: p for p in mine}
        both = sorted(set(held) & set(ours))
        out.append({
            "kind": row["kind"], "name": row["name"], "known": True,
            "reason": "",
            "age_seconds": row["held"]["age_seconds"],
            "age_text": row["held"]["age_text"],
            "only_broker": [held[s] for s in sorted(set(held) - set(ours))],
            "only_platform": [ours[s] for s in sorted(set(ours) - set(held))],
            "agree": [{"symbol": s, "broker": held[s], "platform": ours[s]}
                      for s in both],
            "platform_n": len(mine),
        })
    return out


def vision(user) -> dict:
    """Everything, measured once. Never raises: a view that can fail is one
    more thing that can go quiet."""
    from bot_program.capital_truth import (broker_backed, equity_drawdown,
                                           equity_high_water)

    rows = brokers(user)
    plat = platform_positions(user)
    div = divergence(user, rows, plat)
    book = broker_backed(user)
    book_row = next((r for r in rows if r["is_book"]), None)

    high = draw = None
    try:
        high = equity_high_water(user)
        draw = equity_drawdown(user)
    except Exception:  # noqa: BLE001 — the governor's numbers are not this page
        high = draw = None

    notes, blockers = [], []
    if not rows:
        blockers.append("No broker row exists at all. Nothing can be read "
                        "and nothing can be routed: add keys on /brokers/.")
    if book is None and rows:
        blockers.append("No broker row is the book: every row is either "
                        "unkeyed or claims no asset class, so capital_truth "
                        "has nothing to read and the preflight will refuse "
                        "to arm money.")
    for r in rows:
        if r["keyed"] and r["equity"] is None:
            notes.append(f"{r['name']}: keyed, and its equity has NEVER been "
                         f"read — an em dash, not a zero. "
                         f"{r['session']}.")
        elif r["equity_stale"]:
            notes.append(f"{r['name']}: the equity reading is "
                         f"{r['equity']['age_seconds'] // 60} minutes old; "
                         f"the sync runs every 15.")
    for d in div:
        if not d["known"] and d["platform_n"]:
            blockers.append(
                f"{d['name']}: {d['platform_n']} live position(s) are "
                f"attributed to it and its holdings have never been read — "
                f"the platform cannot tell whether they are really there.")
        elif d["known"] and d["only_platform"]:
            blockers.append(
                f"{d['name']}: the platform holds "
                f"{len(d['only_platform'])} open row(s) the broker does NOT "
                f"report — "
                f"{', '.join(p['symbol'] for p in d['only_platform'][:6])}. "
                f"Either the position was closed at the broker and the row "
                f"was never finalised, or it never opened.")
        elif d["known"] and d["only_broker"]:
            notes.append(
                f"{d['name']}: holds "
                f"{len(d['only_broker'])} position(s) no open platform row "
                f"claims — "
                f"{', '.join(str(h.get('symbol')) for h in d['only_broker'][:6])}"
                f". Hand-placed, or a row that closed while the broker's "
                f"leg stayed.")
    contested = [r for r in routing(user) if r["contested"]]
    for r in contested:
        notes.append(f"{r['asset_class']}: claimed by "
                     f"{', '.join(r['claimants'])} — {r['winner']} carries "
                     f"it. Two brokers claiming one class is a "
                     f"configuration mistake, not a strategy.")

    return {
        "brokers": rows,
        "book": book_row,
        "book_kind": None if book is None else type(book).__name__,
        "high_water": high, "drawdown": draw,
        "routing": routing(user),
        "platform": plat,
        "divergence": div,
        "notes": notes, "blockers": blockers,
        "at": timezone.now(),
    }
