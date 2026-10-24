"""The pages a Telegram button opens (2026-10-24).

The operator, 2026-10-24 (option A): under each Sauron signal a "Prepare
ticket" button, under each alert about one of his positions a "Close
position" button. Each opens a platform page; he reads it, types his
trading PIN on the platform where real money asks for it, and only then
does an order go. Nothing is bought or closed from Telegram, real or
paper.

    GET /signals/<id>/ticket/          the instrument page, its TAKE TRADE
                                       ticket opened for that signal
    GET /positions/<id>/close-dialog/  the positions page, the close
                                       dialog opened for that row

THE LINK CARRIES AN ID AND NOTHING ELSE: never a price, a side, a size, a
stop, a target, an account or a token. Every chat that hears a message
gets the same link, and whoever opens it sees their own data under their
own login: a signal any platform login may see (signals have no owner,
and the investor gate keeps investors out), a trade only when it is the
login's own. Another user's trade and a missing one read the same
neutral note, so the page confirms nothing about a row that is not
yours.

A GET NEVER ACTS. These views read; they write no row, place no order,
close nothing and read no PIN. The page's own scripts then call the
platform's existing doors (window.svTakeTrade, svTakeTradeAsset,
svCloseTrade in templates/base.html): the ticket's preview and the close
preview are POSTs that execute nothing, and the execute POSTs keep their
confirm and their PIN doors (core/trading_pin.py) exactly as a click on
the page itself would. The ticket opens by itself only when the
manual lane already exists (manual_config_if_any, a read): its preview
creates an unarmed paper lane on first use, so without one the note
offers the same click as TAKE TRADE instead.

Not logged in, @login_required sends the visitor to the Wall with the
link as `next`; the Wall and both login steps bring the login back to it
(alerts.links.deep_link_next, dashboard.auth_views.safe_next).
"""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)

#: A signal no longer active, in words: why it stopped.
OUTCOME_WORDS = {"hit_target": "it hit its target",
                 "stopped_out": "it was stopped out",
                 "expired": "it expired",
                 "manual_close": "it was closed by hand"}

#: The one answer for a trade id that is not the reader's own or does
#: not exist: the same words, so the page is no oracle.
NOT_YOURS = "This link does not match a position in your book."


def _link(note, **run) -> dict:
    """{"note": the sentence the page shows, "run": what its script
    opens}. `run` is the page's JSON (#svDeepLink): "open" ("signal",
    "asset", "close" or ""), the ids, or the symbol and side, it needs,
    and "auto" (open at once, or on the note's button). Never a price."""
    run.setdefault("open", "")
    return {"note": note, "run": run}


def ticket_link(user, signal) -> dict:
    """What the ticket page opens for `signal`, read for `user` (_link):
    the signal's own ticket while it is active, the instrument's ticket
    on the same side once it is not, nothing for a signal the platform
    cannot take. Never a price: the ticket's own preview reads the live
    ones."""
    inst = signal.instrument
    n = signal.pk
    side = {"bullish": "BUY", "bearish": "SELL"}.get(
        str(signal.direction or "").lower())
    try:
        from bot_program.manual_trade import (EXECUTABLE_CLASS,
                                              manual_config_if_any)
        cls = EXECUTABLE_CLASS.get(inst.asset_class)
    except Exception:  # noqa: BLE001 — no lane table: no ticket
        logger.warning("[ticket link] the manual lane could not be read",
                       exc_info=True)
        cls = None
    if not (side and inst.is_active and cls):
        return _link(f"Signal #{n} carries no trade the platform can "
                     f"take, so there is no ticket to prepare.")
    # A READ, never manual_config_for: a GET must not create the lane.
    try:
        auto = manual_config_if_any(user, cls) is not None
    except Exception:  # noqa: BLE001 — ask for the click instead
        auto = False
    # The sentence says what the page does: the ticket opens by itself
    # only with `auto`; otherwise the note's button is the click.
    if signal.is_active:
        opens = (f"The TAKE TRADE ticket for signal #{n} opens below."
                 if auto else
                 f"Press OPEN THE TICKET to open the TAKE TRADE ticket for "
                 f"signal #{n}.")
        return _link(f"{opens} Nothing is sent until you press the "
                     f"ticket's own button; a live lane also asks for your "
                     f"trading PIN.",
                     open="signal", signal_id=n, auto=auto)
    why = OUTCOME_WORDS.get(str(signal.outcome or ""), "it was closed")
    ticket = ("The ticket below is built" if auto else
              "Press OPEN THE TICKET for a ticket built")
    return _link(f"Signal #{n} on {inst.symbol} is no longer active "
                 f"({why}). {ticket} from live prices and the platform's "
                 f"own levels, not from the signal's; its notes say "
                 f"whether another active signal backs it.",
                 open="asset", symbol=inst.symbol, side=side, auto=auto)


def close_link(trade) -> dict:
    """What the close page opens for `trade`, the reader's own row or
    None (_link): its close dialog while it is open, a sentence
    otherwise. For an order still waiting at the broker the dialog is
    the same close dialog (closeFlow draws no withdraw dialog of its
    own) and its confirm withdraws the order (manual_close.
    execute_close): the note says so, so the page and the dialog never
    describe two different acts."""
    if trade is None:
        return _link(NOT_YOURS)
    name = f"{trade.symbol} #{trade.pk}"
    if trade.status in ("OPEN", "CLOSE_PENDING"):
        from bot_program.asset_engine.base import is_entry_working
        if is_entry_working(trade):
            note = (f"The order for {name} has not filled yet, so there is "
                    f"no position at the broker. The close dialog opens "
                    f"below; for this order, confirming it withdraws the "
                    f"order. Nothing is withdrawn until you confirm; a live "
                    f"order also asks for your trading PIN.")
        else:
            note = (f"The close dialog for {name} opens below. Nothing "
                    f"closes until you confirm; a live position also asks "
                    f"for your trading PIN.")
        # the close preview is a read (manual_close.preview_close): the
        # dialog may open at once
        return _link(note, open="close", trade_id=trade.pk, auto=True)
    if trade.status == "CLOSED":
        return _link(f"{name} is already closed.")
    if trade.status == "CANCELED":
        return _link(f"{name} never filled; there is nothing to close.")
    if trade.status == "ERROR":
        return _link(f"The platform stopped retrying the close of {name}; "
                     f"the position may still be open at the broker: check "
                     f"it there.")
    return _link(f"{name} is not open; there is nothing to close.")


@login_required
@require_safe
@never_cache
def signal_ticket(request, signal_id):
    """GET /signals/<id>/ticket/ — the signal's instrument page with its
    TAKE TRADE ticket prepared (ticket_link). 404 for a signal that does
    not exist or whose symbol has no page. Reads only."""
    from alerts.links import instrument_url
    from dashboard.views import _instrument_page
    from signals.models import Signal

    signal = get_object_or_404(Signal.objects.select_related("instrument"),
                               pk=signal_id)
    if not instrument_url(signal.instrument.symbol):
        raise Http404("This signal has no instrument page.")
    return _instrument_page(request, signal.instrument,
                            deep_link=ticket_link(request.user, signal))


@login_required
@require_safe
@never_cache
def close_dialog(request, trade_id):
    """GET /positions/<id>/close-dialog/ — the positions page with the
    close dialog of the reader's own row prepared (close_link); any
    other id reads the positions page with the one neutral note. Reads
    only: the dialog's preview and the close stay the existing POSTs."""
    from bot_program.models import AssetBotTrade
    from dashboard.views import _render_positions

    trade = (AssetBotTrade.objects
             .filter(pk=trade_id, config__user=request.user).first())
    return _render_positions(request, live_only=False,
                             deep_link=close_link(trade))
