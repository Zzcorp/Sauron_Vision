# -*- coding: utf-8 -*-
"""THE DIGESTS READ THE WHOLE BOOK, THE REAL ACCOUNT FIRST (2026-09-27).

The operator, 2026-09-27: "in morning brief no position open, when 5
are..." and then "shouldn't it reference all portfolio and especially the
live one?". The morning brief counted portfolio.Position rows of the
user's legacy book, empty on the live box, while every position the
platform holds is an AssetBotTrade; the end-of-day "Trades today" read
the same empty table. Neither said a word about the real account.

Both digests now open with the user's whole book: the user it belongs to
("User: Sauron" — a chat several users share gets the digest of the first
user met, so the digest names whose book it is), a summary line, then a
"Real money" section, then a "Simulated" one. Every figure comes from a
reader the platform already has, so a digest cannot quote a number another
surface contradicts:

  * the open positions: dashboard.views_command._open_book on the user's
    own book (get_or_create_default_portfolio(user)), the reader
    /positions/ marks its open tab with (dashboard.views._live_open_book):
    the user's OPEN and CLOSE_PENDING AssetBotTrades plus the book's open
    Position rows, each marked on LiveQuote. The P&L and its percentage
    are the page's numbers, in the page's formats. A legacy row's P&L is
    (mark - entry) x quantity in the instrument's price currency,
    unconverted, and the page prints it with no currency: so does this;
  * simulated or real money: dashboard.position_summary.venue_of on the
    row's own stamps, the position page's words. A paper row is simulated;
    so is a live-mode row stamped in a broker's demo world (the eToro
    demo); a live row is real money. A legacy Position row carries no flag
    and /positions/ shows it as simulated, so it is simulated here too;
  * the real account: bot_program.telegram_eye.read_live_account, the
    Telegram Eye's live read (GET aggregate-portfolio and GET portfolio,
    measured, read-only), with cells=True for the available cash and the
    used margin (EtoroTrader.margin_cells, one more GET of
    aggregate-portfolio). When the read raises or answers no equity, or no
    key is stored, or the stored key does not decrypt: the cells
    sync_etoro_accounts stamped on EtoroAccount, with their time and the
    reason, but only cells stamped in the live world (last_margin_world).
    Cells read in the demo world are the demo account's, never the real
    one's. The sync stamps that world only in a save that wrote a margin
    cell, while it writes the equity whenever the equity read answers, so
    the stamp speaks for the equity only when the same save wrote both
    (last_equity_at == last_margin_at); otherwise the world of the stored
    reading is unknown, and said so. Positions held at eToro beyond the
    real-money rows the platform lists at eToro are counted;
  * the demo account: the stamped equity the Eye's /status prints, when it
    was read in the demo world (same rule);
  * the book value: portfolio.services.live_book_value on the same read,
    unless the book's capital is still the seed nobody entered: then
    "Book value: not set";
  * today's trades: the user's AssetBotTrades opened or closed since the
    UTC day start that the positions page lists (open, closing or closed;
    an ERROR or CANCELED row never held money and the page shows neither),
    plus the legacy book's Position rows when it holds any: two tables,
    each row read once.

Nothing here sends an order, or closes or changes a position. Its one
write is the page's own: get_or_create_default_portfolio creates the
user's empty book the first time, as /positions/ does. Every word is
English; an unknown is said, never printed as 0.
"""
from __future__ import annotations

import logging
from datetime import timezone as dt_tz
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

#: How many positions a section lists before it counts the rest.
MAX_LISTED = 5
#: How many of today's trades the end-of-day summary lists.
MAX_TRADES_LISTED = 10

REAL_MONEY = "Real money"
SIMULATED = "Simulated"
NO_POSITIONS = "No open positions."
DEMO_LINE = ("Sauron trades on the demo account; the real account is read, "
             "not traded.")
READ_FAILED = "the live read did not answer"
NO_KEY = "no key is stored for a live read"
KEY_UNREADABLE = "the stored key could not be read"
WORLD_UNKNOWN = "the stored reading does not say which account it came from"

#: The rows the positions page lists: its open tab, then its history tab.
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")
CLOSED = "CLOSED"
#: EtoroAccount.last_margin_world, as sync_etoro_accounts stamps it.
LIVE_WORLD = "live"
DEMO_WORLD = "demo"
#: venue_of's broker words that need no mention beside the money words.
_QUIET_BROKERS = ("", "Paper trading")


# ── words ─────────────────────────────────────────────────────────────────

def money_label(words: str, broker: str = "") -> str:
    """"Simulated", "Simulated (eToro demo)", "Real money (eToro)"."""
    broker = str(broker or "")
    if broker in _QUIET_BROKERS:
        return words
    if broker == "Broker not recorded":
        broker = "broker not recorded"
    return f"{words} ({broker})"


def _side(value) -> str:
    """long or short, from a row's direction or a trade's side."""
    return ("short" if str(value or "").strip().lower() in ("short", "sell")
            else "long")


def _more(n: int) -> str:
    return f"+{n} more on the positions page"


def _float(value):
    from dashboard.position_summary import _num
    return _num(value)


def _stamp_world(acct) -> str:
    """The world the stamped equity and cells were read in, or "" when it
    is not known.

    sync_etoro_accounts writes last_equity whenever the equity read
    answers, but stamps last_margin_world only in a save that also wrote a
    margin cell. A sync that read the equity and no cell leaves an older
    world beside a newer equity: right after the demo-to-live flip, a
    "demo" stamp beside the real account's equity. So the stamp speaks for
    the equity only when the same save wrote both (last_equity_at ==
    last_margin_at, the sync's one `now`). The row's own `demo` flag is
    not the answer either: it can have flipped since the reading."""
    world = str(acct.last_margin_world or "").strip().lower()
    if (world in (LIVE_WORLD, DEMO_WORLD) and acct.last_equity_at is not None
            and acct.last_equity_at == acct.last_margin_at):
        return world
    return ""


def _stored_reading(acct) -> bool:
    """True when the row holds an equity or a margin reading at all."""
    return acct.last_equity_at is not None or acct.last_margin_at is not None


# ── the open positions ────────────────────────────────────────────────────

def position_item(row, trade=None) -> dict:
    """One open position as the digests say it.

    The P&L and its percentage are the row's own, marked by _open_book:
    the positions page's numbers. A working entry (an order not filled
    yet) has none. The currency is the one the position page labels the
    same figure with: the config's, or an older forex row's quote
    currency (position_summary._unconverted_ccy). A legacy row has none:
    _open_book marks it (mark - entry) x quantity in the instrument's
    price currency, unconverted, and the page prints it bare.
    """
    from bot_program.asset_engine.base import is_entry_working
    from dashboard import position_summary as ps

    symbol = getattr(getattr(row, "instrument", None), "symbol", "") or ps.DASH
    side = _side(getattr(row, "direction", ""))
    working = False
    if trade is not None:
        words, real, broker = ps.venue_of(trade)
        ccy = (getattr(trade.config, "base_currency", "") or "USD").strip()
        ccy = ps._unconverted_ccy(trade, ccy) or ccy
        working = trade.status == "OPEN" and is_entry_working(trade)
    elif getattr(row, "source", "") == "bot":
        # the row's trade went between the two reads: the row's own flag
        real = not getattr(row, "paper", True)
        words, broker, ccy = (REAL_MONEY if real else SIMULATED), "", ""
    else:
        # a legacy Position row: no money flag, and /positions/ shows it
        # as simulated (dashboard.views._live_row); its P&L carries no
        # currency there, so none here (never the book's, which it is not)
        words, real, broker, ccy = SIMULATED, False, "", ""
    pnl = None if working else _float(getattr(row, "unrealized_pnl", None))
    pct = (None if working
           else _float(getattr(row, "unrealized_pnl_pct", None)))
    if working:
        middle = "order waiting to fill"
    elif pnl is None:
        middle = "no live price yet"
    else:
        middle = f"{ps.percent(pct)} · {ps.money(pnl, ccy, signed=True)}"
    if getattr(row, "status", "") == "CLOSE_PENDING":
        middle += " · closing"
    return {"symbol": symbol, "side": side, "money": words, "real": real,
            "broker": broker, "pnl": pnl, "pnl_pct": pct, "currency": ccy,
            "working": working, "trade_id": getattr(row, "trade_id", None),
            "line": (f"• {symbol} {side} · {middle} · "
                     f"{money_label(words, broker)}")}


def _by_move(items) -> list:
    """The biggest moves first (by the page's percentage), unpriced last."""
    return sorted(items, key=lambda it: (it["pnl"] is None,
                                         -abs(it["pnl_pct"] or 0.0)))


def _listed(items, limit: int = MAX_LISTED) -> list:
    ordered = _by_move(items)
    lines = [it["line"] for it in ordered[:limit]]
    if len(ordered) > limit:
        lines.append(_more(len(ordered) - limit))
    return lines


# ── the real account ──────────────────────────────────────────────────────

def _held(count) -> str:
    from bot_program.telegram_eye import DASH, _plural
    if count is None:
        return DASH
    return "none" if int(count) == 0 else _plural(int(count), "position")


def real_account(acct, now) -> tuple:
    """(lines, facts) for the user's eToro REAL account.

    The Eye's live read first. When it raises or answers no equity, or no
    key is stored, or the stored key does not decrypt: the cells stamped
    in the LIVE world, with their time and the reason. Cells stamped in the
    demo world describe the demo account and are never printed here: the
    reason is said instead. A reading whose world is unknown (_stamp_world)
    is not printed either, and that is said.
    """
    from bot_program import telegram_eye as eye

    why, reading = READ_FAILED, None
    try:
        api_key, user_key = acct.get_credentials()
    except Exception:  # noqa: BLE001 — said below, never a crash
        api_key = user_key = None
    if not (api_key and user_key):
        # get_credentials answers (None, None) both when nothing is stored
        # and when a stored key does not decrypt (models._decrypt swallows
        # the error): only an empty cell is "no key"
        why = KEY_UNREADABLE if acct.api_key_enc else NO_KEY
    else:
        try:
            reading = eye.read_live_account(api_key, user_key, cells=True)
        except Exception as e:  # noqa: BLE001 — the digest goes out anyway
            logger.warning("digest: the live eToro read for user %s did not "
                           "answer (%s)", acct.user_id, type(e).__name__)
            reading = None
    equity = (reading or {}).get("equity")
    if equity:
        value, code = equity
        cells = reading.get("cells") or {}
        facts = {"source": "live read", "at": now.isoformat(),
                 "equity": _float(value),
                 "currency": str(code or cells.get("currency") or ""),
                 "available_cash": _float(cells.get("available_cash")),
                 "used_margin": _float(cells.get("used_margin")),
                 "held": reading.get("positions")}
        head = f"eToro real account, read at {eye.when(now)}"
    else:
        world = _stamp_world(acct)
        if world != LIVE_WORLD:
            tail = (WORLD_UNKNOWN if not world and _stored_reading(acct)
                    else "no earlier reading of it is stored")
            return ([f"eToro real account: {why}, and {tail}"],
                    {"source": None, "why": why})
        # the live world: the equity and the cells of one save (one time)
        at = acct.last_equity_at
        held = acct.broker_positions
        facts = {"source": "stamped", "at": at.isoformat(), "why": why,
                 "equity": _float(acct.last_equity),
                 "currency": str(acct.last_equity_currency or ""),
                 "available_cash": _float(acct.last_available_cash),
                 "used_margin": _float(acct.last_used_margin),
                 # the holdings only when that same save read them too
                 "held": (len(held) if acct.broker_positions_at == at
                          and isinstance(held, list) else None)}
        head = f"eToro real account, as of {eye.when(at)} ({why})"
    code = facts["currency"]
    return ([head,
             f"Equity: {eye.money(facts['equity'], code)}",
             f"Available cash: {eye.money(facts['available_cash'], code)}",
             f"Used margin: {eye.money(facts['used_margin'], code)}",
             f"Held at eToro: {_held(facts['held'])}"], facts)


def real_money_section(acct, items, now) -> dict:
    """The eToro real account, the positions held there that the platform
    does not list, every real-money position the platform holds with its
    P&L, and the demo line while the row is in demo."""
    from bot_program.telegram_eye import _plural
    if acct is None:
        lines, facts = ["eToro real account: not connected"], {"source": None}
    else:
        lines, facts = real_account(acct, now)
    real = [it for it in items if it["real"]]
    # eToro's /portfolio row carries no P&L and the Eye's read keeps only
    # the count: a real position opened outside the platform (a
    # measurement, a hand order) shows only there. Say how many the
    # platform does not list, against its filled real-money rows at eToro.
    held = facts.get("held")
    listed = sum(1 for it in real
                 if it["broker"] == "eToro" and not it["working"])
    if isinstance(held, int) and held > listed:
        extra = held - listed
        lines.append(f"{_plural(extra, 'position')} held at eToro "
                     f"{'is' if extra == 1 else 'are'} not on the platform")
    if real:
        lines.append(f"Real-money positions on the platform: {len(real)}")
        lines.extend(_listed(real))
    else:
        lines.append("No real-money position on the platform.")
    if acct is not None and acct.demo:
        lines.append(DEMO_LINE)
    return {"account": facts, "positions": real, "lines": lines}


# ── the simulated book ────────────────────────────────────────────────────

def book_is_seed(book) -> bool:
    """True while the book's capital is the seed the platform wrote when it
    created the book (PORTFOLIO_CONFIG["initial_capital"] in both
    initial_capital and cash_available): nobody entered it. cash_available
    is written only by the /setup/ form, the eToro balance import and the
    seeder; current_value is re-valued every hour
    (portfolio.tasks.store_book_value), so it is not the test."""
    try:
        seed = Decimal(str(settings.PORTFOLIO_CONFIG["initial_capital"]))
        return (Decimal(str(book.initial_capital)) == seed
                and Decimal(str(book.cash_available)) == seed)
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def demo_account_line(acct, now) -> str:
    """The eToro demo account's equity as the Eye's /status prints it: the
    stamped cell, when it was read in the demo world (_stamp_world). While
    the platform trades the demo, a reading whose world is unknown is said
    so, and a row never read says that. "" otherwise."""
    from bot_program import telegram_eye as eye
    if acct is None:
        return ""
    world = _stamp_world(acct)
    if world == DEMO_WORLD and acct.last_equity is not None:
        synced = acct.last_equity_at
        return (f"eToro demo account equity: "
                f"{eye.money(acct.last_equity, acct.last_equity_currency)} "
                f"(synced {eye.ago(synced, now)})")
    if not acct.demo:
        return ""
    if not _stored_reading(acct):
        return "eToro demo account: not read yet"
    return f"eToro demo account: {WORLD_UNKNOWN}" if not world else ""


def simulated_section(user, acct, items, book, page_read, now) -> dict:
    """The simulated positions (the biggest moves first), their open P&L,
    the demo account's equity, the book value."""
    from bot_program import telegram_eye as eye
    from dashboard import position_summary as ps

    sim = [it for it in items if not it["real"]]
    lines = []
    if sim:
        lines.append(f"{eye._plural(len(sim), 'position')} open"
                     + (", the biggest moves first" if len(sim) > 1 else ""))
        lines.extend(_listed(sim))
        priced = [it for it in sim if it["pnl"] is not None]
        codes = {it["currency"] for it in priced}
        if priced and len(codes) == 1:
            total = round(sum(it["pnl"] for it in priced), 2)
            note = ("" if len(priced) == len(sim) else
                    f" ({len(priced)} of {len(sim)} with a live price)")
            lines.append(f"Open P&L: "
                         f"{ps.money(total, codes.pop(), signed=True)}{note}")
    else:
        lines.append("No simulated position.")
    demo = demo_account_line(acct, now)
    if demo:
        lines.append(demo)
    seeded = book_is_seed(book)
    value = None
    if seeded:
        lines.append("Book value: not set")
    else:
        try:
            from portfolio.services import live_book_value
            bv = live_book_value(user, book, book=page_read)
            value = bv.value
            lines.append(f"Book value: {eye.money(bv.value, bv.currency)} · "
                         f"cash {eye.money(bv.cash, bv.currency)}")
        except Exception as e:  # noqa: BLE001 — said, never a crash
            logger.warning("digest: the book value could not be read: %s", e)
            lines.append(f"Book value: unreadable ({type(e).__name__})")
    return {"positions": sim, "seeded": seeded, "book_value": value,
            "lines": lines}


# ── the whole book ────────────────────────────────────────────────────────

def book_sections(user, now=None) -> dict:
    """The summary line, the counts and the two sections, from ONE read of
    the book the positions page reads."""
    from bot_program.models import AssetBotTrade, EtoroAccount
    from dashboard.views_command import _open_book
    from portfolio.services import get_or_create_default_portfolio

    now = now or timezone.now()
    book = get_or_create_default_portfolio(user=user)
    page_read = _open_book(user, book)
    rows = list(page_read[0])
    ids = [r.trade_id for r in rows
           if getattr(r, "source", "") == "bot" and getattr(r, "trade_id", None)]
    trades = ({t.pk: t for t in AssetBotTrade.objects.filter(pk__in=ids)
               .select_related("config")} if ids else {})
    items = [position_item(
        r, trades.get(r.trade_id) if getattr(r, "source", "") == "bot"
        else None) for r in rows]
    acct = (EtoroAccount.objects.filter(user=user).first()
            if user is not None else None)
    real = sum(1 for it in items if it["real"])
    summary = (NO_POSITIONS if not items else
               f"Open positions: {len(items)} ({len(items) - real} "
               f"simulated · {real} real money)")
    simulated = simulated_section(user, acct, items, book, page_read, now)
    return {"summary": [summary],
            "counts": {"open": len(items), "simulated": len(items) - real,
                       "real_money": real},
            "seeded": simulated["seeded"],
            "real_money": real_money_section(acct, items, now),
            "simulated": simulated}


def owner_line(user) -> list:
    """["User: Sauron"]: whose book the digest reads. A chat several users
    share gets the digest of the first user met (send_digest's
    chats_done), so the reader must be able to see which one. [] for the
    digest with no user."""
    try:
        name = str(user.get_username() or "").strip() if user else ""
    except Exception:  # noqa: BLE001 — a name is a courtesy, never a crash
        name = ""
    return [f"User: {name}"] if name else []


def add_book(digest, user, now=None, label: str = "Digest") -> bool:
    """Put the book at the head of `digest`: the user it belongs to, the
    summary line, then the Real money section, then the Simulated one,
    before any other section. True while the book's capital is the seed
    nobody entered. Never raises: a book that cannot be read is said, and
    the digest goes out."""
    now = now or timezone.now()
    try:
        book = book_sections(user, now)
    except Exception as e:  # noqa: BLE001
        logger.error("%s book section failed: %s", label, e)
        digest["summary"] = owner_line(user) + [
            f"The open positions could not be read ({type(e).__name__})."]
        return False
    rest = {k: v for k, v in (digest.get("sections") or {}).items()
            if k not in ("real_money", "simulated")}
    digest["summary"] = owner_line(user) + book["summary"]
    digest["book"] = book["counts"]
    digest["sections"] = {"real_money": book["real_money"],
                          "simulated": book["simulated"], **rest}
    return bool(book["seeded"])


# ── today's trades ────────────────────────────────────────────────────────

def trade_event(trade, closing: bool) -> dict:
    """One of today's trades: an open, or a close with the P&L and the R
    the row booked (AssetBotTrade.pnl and realized_r; a close nothing
    could price says so)."""
    from bot_program.asset_engine.base import is_entry_working
    from dashboard import position_summary as ps

    words, real, broker = ps.venue_of(trade)
    label = money_label(words, broker)
    side = _side(trade.side)
    event = {"symbol": trade.symbol, "side": side, "money": words,
             "real": real, "trade_id": trade.pk}
    if not closing:
        if trade.status == "OPEN" and is_entry_working(trade):
            event["line"] = (f"• Order placed: {trade.symbol} {side}, "
                             f"waiting to fill · {label}")
        else:
            event["line"] = f"• Opened {trade.symbol} {side} · {label}"
        return event
    ccy = (getattr(trade.config, "base_currency", "") or "USD").strip()
    pnl, r = _float(trade.pnl), _float(trade.realized_r)
    parts = [f"• Closed {trade.symbol} {side}"]
    ending = ps.ending_words(trade)
    if ending != "Closed":
        parts.append(ending)
    parts.append(ps.money(pnl, ccy, signed=True) if pnl is not None
                 else "result not priced")
    if r is not None:
        parts.append(f"{r:+.2f}R")
    parts.append(label)
    event.update(pnl=pnl, r=r, currency=ccy, line=" · ".join(parts))
    return event


def legacy_event(position, closing: bool) -> dict:
    """A legacy Position row of today: simulated (the page's reading), and
    for a close the only P&L that model has (unrealized_pnl, as
    unified_closed_positions reads it), with no currency: it is the
    instrument's price currency, unconverted, never the book's."""
    from dashboard import position_summary as ps
    symbol = getattr(position.instrument, "symbol", "") or ps.DASH
    side = _side(position.direction)
    event = {"symbol": symbol, "side": side, "money": SIMULATED,
             "real": False, "trade_id": None}
    if not closing:
        event["line"] = f"• Opened {symbol} {side} · {SIMULATED}"
        return event
    pnl = _float(position.unrealized_pnl)
    event.update(pnl=pnl, r=None, currency="", line=(
        f"• Closed {symbol} {side} · "
        + (ps.money(pnl, signed=True) if pnl is not None
           else "result not priced") + f" · {SIMULATED}"))
    return event


def trades_today(user, now=None) -> dict:
    """The end-of-day "Trades today": what the positions page lists as
    opened or closed since the UTC day start, each row once per event."""
    from bot_program.models import AssetBotTrade
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio

    now = now or timezone.now()
    start = now.astimezone(dt_tz.utc).replace(hour=0, minute=0, second=0,
                                              microsecond=0)
    opened, closed = [], []
    if user is not None:
        mine = (AssetBotTrade.objects.filter(config__user=user)
                .select_related("config"))
        for t in (mine.filter(opened_at__gte=start,
                              status__in=OPEN_STATUSES + (CLOSED,))
                  .order_by("opened_at", "pk")):
            opened.append(trade_event(t, closing=False))
        for t in (mine.filter(status=CLOSED, closed_at__gte=start)
                  .order_by("closed_at", "pk")):
            closed.append(trade_event(t, closing=True))
    # The legacy book, only when it holds rows of today (none on the live
    # box): a second table, so no row is ever read twice.
    book = get_or_create_default_portfolio(user=user)
    legacy = Position.objects.filter(portfolio=book).select_related(
        "instrument")
    for p in legacy.filter(opened_at__gte=start).order_by("opened_at", "pk"):
        opened.append(legacy_event(p, closing=False))
    for p in legacy.filter(closed_at__gte=start).order_by("closed_at", "pk"):
        closed.append(legacy_event(p, closing=True))
    if not (opened or closed):
        lines = ["No trade opened or closed today."]
    else:
        events = opened + closed
        lines = [f"Opened: {len(opened)} · Closed: {len(closed)}"]
        lines.extend(ev["line"] for ev in events[:MAX_TRADES_LISTED])
        if len(events) > MAX_TRADES_LISTED:
            lines.append(_more(len(events) - MAX_TRADES_LISTED))
    return {"since": start.isoformat(), "opened": opened, "closed": closed,
            "lines": lines}
