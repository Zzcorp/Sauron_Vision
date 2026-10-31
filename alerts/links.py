"""Deep links a notification producer can hand to the bell.

A notification that names one object and then links to the list of every
object makes its reader repeat the lookup the producer had already done:
"Market Anomaly Alert (7 severe)" knew all seven symbols by name and still
landed on /quotes/. These turn an object a producer already holds into the
page that shows it.

Both helpers answer "" when there is no such page, and "" is a real answer
here rather than a failure: Notification treats an empty url as "open the
notification's own detail card", which beats a link into a 404 that looks
plausible enough to be clicked twice.
"""
from __future__ import annotations

import re


def page_url(route: str, arg) -> str:
    """The stored url for a one-argument route, or "" if it has none.

    Everything goes through `Notification.safe_url` for the reason every
    other producer does: one gate decides what a notification is allowed
    to link to, so a route that is renamed or dropped costs the bell an
    inert row instead of a 404.
    """
    if arg in (None, ""):
        return ""
    from django.urls import NoReverseMatch, reverse

    from alerts.models import Notification
    try:
        return Notification.safe_url(reverse(route, args=[arg]))
    except NoReverseMatch:
        return ""


def instrument_url(symbol: str) -> str:
    """The asset page for `symbol`, or "" when that asset has no page.

    `symbol` is free text on the way in — an LLM's answer, a funding feed,
    whatever a scan echoed back — so it is matched case-insensitively and
    the link is built from the row's OWN symbol, which is what the route
    matches. A symbol we do not track answers "" rather than a
    confident-looking /instruments/XYZ/ that 404s, and so does one the
    route cannot express (the slash in a pair like BTC/USD ends the path
    segment). Callers keep their list page for those.
    """
    sym = (symbol or "").strip()
    if not sym:
        return ""
    from instruments.models import Instrument

    known = (Instrument.objects.filter(symbol__iexact=sym)
             .values_list("symbol", flat=True).first())
    if not known:
        return ""
    return page_url("instrument_detail", known)


# ── The Telegram buttons that prepare an act (2026-10-24) ────────────────
# "Prepare ticket" under a signal and "Close position" under an alert
# about one position open a platform page that READS: the TAKE TRADE
# ticket filled from the signal, the close dialog of the position. The
# link carries the row's id and nothing else (never a price, a side, a
# size or a token): the page reads every fact from the database for the
# login that opens it, and the platform's own confirm, with its trading
# PIN for real money, stays the only way to act
# (dashboard/views_links.py).

def ticket_path(signal_id) -> str:
    """/signals/<id>/ticket/: the TAKE TRADE ticket of one signal, or ""."""
    return page_url("signal_ticket", signal_id)


def close_path(trade_id) -> str:
    """/positions/<id>/close-dialog/: the close dialog of one
    AssetBotTrade, or "". Never a legacy BotTrade's or a portfolio
    Position's id: the same integer names a different row there."""
    return page_url("close_dialog", trade_id)


#: The only shapes a login may come back to from the Wall: ids, no
#: query, no free text (the Wall is public and echoes it in its form).
DEEP_LINK_PATHS = (re.compile(r"^/signals/\d{1,12}/ticket/$"),
                   re.compile(r"^/positions/\d{1,12}/close-dialog/$"))


def deep_link_next(value) -> str:
    """`value` when it is exactly one of DEEP_LINK_PATHS, else ""."""
    text = str(value or "")
    return text if any(p.fullmatch(text) for p in DEEP_LINK_PATHS) else ""
