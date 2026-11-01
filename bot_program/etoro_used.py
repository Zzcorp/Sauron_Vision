"""Used and free as eToro states them, beside what Sauron's own eToro rows
account for (2026-10-31).

THE OPERATOR'S REPORT. eToro's screen showed most of the account used;
every Sauron page showed a smaller "used" and called the rest "free". Both
were true, and no page said what it measured:

  * Sauron's used was its own rows, entry value over their leverage
    (portfolio.services.capital_summary). A position opened in the eToro
    app, a second position on a symbol Sauron holds, a close Sauron gave
    up on, a pending order and the open P&L are in eToro's figures and in
    no Sauron row.
  * Sauron's free was its pool's arithmetic, and a pool that follows the
    account is eToro's TOTAL value, P&L included: what eToro holds outside
    Sauron's rows read as free.

The order gate already judges every eToro order on eToro's own cells
(AssetBot._cash_gate: the available cash less what was pledged since and
any withdrawal hold, and, below 100%, the pledge ceiling over the used
margin; at exactly 100% the free cash decides alone, 2026-11-01). This
module makes the pages say the same thing: eToro's figures headline, read
from the sync's cells with their age, and the split says how much of
eToro's used Sauron's rows account for.

WHAT IT PROMISES

  * Cached columns only: the sync's and the re-read's cells
    (tasks.sync_etoro_accounts, tasks.refresh_etoro_cells) and the
    holdings snapshot. No broker call, safe on any render path.
  * Three states. Never read is an em dash, never 0. Cells stamped in the
    other world (the same key pair answers both, EtoroAccount.demo picks)
    are not this world's figures and are not shown as them.
  * The split is AT THAT READ: eToro's used is as of its read, so the rows
    it is compared with are the rows open then (a row booked since is not
    in eToro's figure; one closed since was). Only eToro-stamped rows of
    the account's own world count; a live row that names no broker is
    counted apart, never guessed. A close Sauron stopped trying counts
    only while eToro's holdings still list it (the operator may have
    closed it in the eToro app, as the close-abandoned alert asks), or
    cannot say it is gone: since 2026-11-01 the gates' own predicate,
    portfolio.services.abandoned_still_held, decides it.
  * Display only. Nothing on an order path reads this module: no gate,
    limit or size moves with it (tests.test_used_is_etoros pins that).

WHAT eTORO HOLDS WITH NO SAURON ROW (2026-11-01). An order eToro holds
(WaitingForMarket) sits in its used margin and its frozen cash and in no
/portfolio row (MEASURED, doc §4 D2b-i). When no Sauron row owns it (an
order placed in the eToro app, or one of Sauron's whose answer did not
come back) it is in "outside Sauron" with nothing to say so. The split now
carves "held at eToro, no Sauron row" out of it, with its age: eToro's
frozen cash less what Sauron's own WORKING rows explain
(asset_engine.base.frozen_explained). Those rows are under "opened by
Sauron" already and are never counted twice. An outside position, or the
held part, on a symbol with a fresh in-doubt note on any of the user's
configs says "may be Sauron's order of <time> that did not come back"
(in_doubt_times); Sauron never adopts it, and no number moves between the
split's parts. Only what could carry the order is named (review,
2026-11-01): a read stamped no earlier than LIST_LAG_S before the note,
and never a position whose own open time eToro dates before then
(doubt_at).
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

DASH = "—"
#: The account's world, as the pages say it (position_summary.WORLD_WORDS
#: says REAL MONEY / DEMO for a row; a head line is shorter).
WORLD_WORDS = {"live": "REAL", "demo": "DEMO"}
#: eToro lists a closed position for up to about a minute after the close
#: and a fresh fill only after a second or two (MEASURED 2026-09-23,
#: etoro_client.PORTFOLIO_LAG_S): a snapshot is judged with this much give.
LIST_LAG_S = 60
#: How much older than the cells the total may be before it carries its
#: own age (the re-read after an order moves the cells, never the total).
TOTAL_OWN_AGE_S = 90

# ── the words ────────────────────────────────────────────────────────────
HEAD = ("eToro {world}{ccy} · used {used} · available {available} · "
        "P&L {pnl} · total {total} · read {age} ago")
HEAD_NEVER = ("eToro {world} · never read: the sync has not stored eToro's "
              "own figures yet")
HEAD_OTHER_WORLD = ("eToro {world} · the stored figures were read in the "
                    "{stamped} world; the next sync reads this one")
#: The total's own age, said where the cells' age is (2026-10-31): the
#: re-read after an order moves the cells and never the total.
TOTAL_AGE = " (read {age} ago)"
#: A strip cell's line under eToro's used (the positions and portfolio
#: strips, the Ops Center).
CELL = "{available} available · {total} total{total_age} · read {age} ago"
SPLIT = ("At that read: opened by Sauron {sauron}{unconverted} · "
         "{stopped}{outside} · P&L {pnl}")
SPLIT_UNREAD = ("Opened by Sauron {sauron}{unconverted} · {stopped}outside "
                "Sauron {dash} (eToro's used is not read)")
OUTSIDE = "outside Sauron {outside}"
#: The part of it eToro holds as frozen cash that no Sauron row explains,
#: with the read's age, then the rest (2026-11-01). Below zero the rest is
#: said the other way round, as OVER is.
HELD = "held at eToro, no Sauron row {held}, read {age} ago{doubt}"
OUTSIDE_HELD = "outside Sauron {outside} ({held}; positions {rest})"
OUTSIDE_HELD_OVER = ("outside Sauron {outside} ({held}; Sauron's rows count "
                     "{over} more than eToro's positions)")
#: A fresh in-doubt note on the symbol, on any of the user's configs: the
#: order may be Sauron's own (2026-11-01). Words only.
DOUBT = "may be Sauron's order of {time} that did not come back"
DOUBT_HELD = "; {symbol}: " + DOUBT
#: Sauron's rows count more than eToro holds (2026-10-31): a stop or a
#: close eToro filled that Sauron has not booked yet, a close Sauron
#: stopped that the operator closed by hand since the holdings were read,
#: a stock quoted in a currency worth less than the account's. "outside
#: Sauron -650.00" said nothing of what it meant.
OVER = ("Sauron's rows count {over} more than eToro's used (a row eToro no "
        "longer holds, or an unconverted currency)")
STOPPED = "Sauron stopped closing, still open at eToro {stopped} · "
STOPPED_UNREAD = ("Sauron stopped closing, may still be open at eToro "
                  "{stopped} · ")
STOPPED_GONE = ("; {n} position{s} Sauron stopped closing {are} no longer "
                "listed at eToro and {are} not counted")
SINCE = "; {n} eToro row{s} opened since that read"
UNSTAMPED = "; {n} live row{s} record{verb_s} no broker and {are} not counted"
UNCONVERTED = " ({n} unconverted: {names})"
TITLE = ("eToro's own figures, from the sync's cells (the account is read "
         "again a few seconds after every order and close). Opened by "
         "Sauron is what its own eToro rows of this world tie up, entry "
         "value over their leverage, at that read. Outside Sauron is "
         "eToro's used minus those rows and minus the closes Sauron stopped "
         "trying that eToro still lists: positions opened in the eToro app, "
         "a second position on a symbol Sauron holds, pending orders, a fill "
         "whose answer was lost. /treasury/ lists them position by position. "
         "Held at eToro, no Sauron row is the part of it eToro holds as "
         "frozen cash for orders beyond what Sauron's own WORKING rows "
         "explain: an order placed in the eToro app, or one of Sauron's whose "
         "answer did not come back. "
         "The order gate judges every eToro order on these same cells.")


def _f(value):
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def money(value, signed=False):
    """'6,000.00' / '+500.00', or the em dash for unmeasured."""
    v = _f(value)
    if v is None:
        return DASH
    return ("{:+,.2f}" if signed else "{:,.2f}").format(v)


def _age(at, now):
    return None if at is None else max(0.0, (now - at).total_seconds())


def _age_words(seconds) -> str:
    from bot_program.venue_mark import age_words
    return age_words(seconds) or "?"


# ── matching the broker's positions with the platform's rows ─────────────

def side_key(side) -> str:
    """"BUY", "SELL" or "" from any spelling of a side."""
    s = str(side or "").strip().upper()
    if s in ("BUY", "LONG"):
        return "BUY"
    if s in ("SELL", "SHORT"):
        return "SELL"
    return ""


def _pid(row) -> str:
    raw = row.get("position_id") if isinstance(row, dict) else None
    if isinstance(raw, bool) or raw is None:
        return ""
    if isinstance(raw, (int, str)):
        return str(raw).strip()
    return ""


def _sym(row) -> str:
    return str((row or {}).get("symbol") or "").strip().upper()


def _qty(row):
    return _f((row or {}).get("qty"))


def _plural(n) -> dict:
    """The words that agree with a count of rows: "1 row ... is", "2 rows
    ... are" (2026-10-31: the split read "1 live row record no broker")."""
    one = n == 1
    return {"n": n, "s": "" if one else "s", "are": "is" if one else "are",
            "verb_s": "s" if one else ""}


def match_positions(held, ours):
    """Pair the broker's positions with the platform's rows, one with one
    (2026-10-31). Returns (pairs [(held_row, our_row)], only_held,
    only_ours), each in its input order.

    1. By the venue's position id: a row's handle (broker_position_id /
       protective_trade_id, venue_close.position_id_for) that is a broker
       row's position_id.
    2. Then by symbol and side, the closest units first, between rows of
       which at most one carries an id: two different ids are two
       different positions, never one. A row that states no side meets
       either side. A row marked "by_id_only" (booked after the list was
       read: only its own id can be in it) is never paired this way.

    Symbols compared alone (a set) read a second position on a held symbol
    as agreement: eToro holds every position apart, so here each one is
    counted. A row of `held` or `ours` is a dict with "symbol", "side",
    "qty" and "position_id"."""
    held = list(held or [])
    ours = list(ours or [])
    h_left = list(range(len(held)))
    o_left = list(range(len(ours)))
    pairs = []
    by_id = {}
    for i in h_left:
        pid = _pid(held[i])
        if pid and pid not in by_id:
            by_id[pid] = i
    for j in list(o_left):
        pid = _pid(ours[j])
        i = by_id.pop(pid, None) if pid else None
        if i is not None and i in h_left:
            pairs.append((i, j))
            h_left.remove(i)
            o_left.remove(j)
    for j in list(o_left):
        mine = ours[j]
        sym, side, pid = _sym(mine), side_key(mine.get("side")), _pid(mine)
        if not sym or mine.get("by_id_only"):
            continue
        cands = [i for i in h_left
                 if _sym(held[i]) == sym
                 and (not side or not side_key(held[i].get("side"))
                      or side_key(held[i].get("side")) == side)
                 and not (pid and _pid(held[i]))]
        if not cands:
            continue
        q = _qty(mine) or 0.0
        i = min(cands, key=lambda k: (abs((_qty(held[k]) or 0.0) - q), k))
        pairs.append((i, j))
        h_left.remove(i)
        o_left.remove(j)
    pairs.sort(key=lambda p: p[0])
    return ([(held[i], ours[j]) for i, j in pairs],
            [held[i] for i in h_left], [ours[j] for j in o_left])


def row_handle(trade) -> str:
    """The venue's position id a row records, or "" (venue_close's rule)."""
    try:
        from bot_program.engine.venue_close import position_id_for
        return position_id_for(trade)
    except Exception:  # noqa: BLE001 — no handle is a state, not a failure
        return ""


def claim_row(trade) -> dict:
    """One platform row in match_positions' shape."""
    return {"symbol": str(trade.symbol or "").upper(), "side": trade.side,
            "qty": _f(trade.qty), "position_id": row_handle(trade),
            "trade": trade}


def outside_margin(row) -> tuple:
    """(margin, estimated) of one holdings row: eToro's own invested
    `amount` when the row carries it, else units × open rate over the
    row's leverage, and said to be an estimate (at 2x the list's amount is
    unmeasured, doc §4 D2b-ii). Full notional when no leverage is stated:
    at 1x eToro's margin IS the notional (MEASURED 2026-09-23)."""
    amount = _f(row.get("amount"))
    if amount is not None:
        return amount, False
    qty, avg = _f(row.get("qty")), _f(row.get("avg_cost"))
    if qty is None or avg is None:
        return None, True
    lev = _f(row.get("leverage"))
    notional = abs(qty * avg)
    return (notional / lev if lev and lev >= 1 else notional), True


# ── the account ─────────────────────────────────────────────────────────

def _account(user):
    from bot_program.models import EtoroAccount
    try:
        return EtoroAccount.objects.filter(user_id=user.pk).first()
    except Exception:  # noqa: BLE001 — a page renders without it
        logger.warning("etoro_used: the eToro row could not be read",
                       exc_info=True)
        return None


def _world_of_trade(trade) -> str:
    from dashboard.position_summary import world_of
    return world_of(trade)


def in_doubt_times(user, *, now=None) -> dict:
    """{SYMBOL: [the times of the fresh in-doubt notes on it, oldest
    first]}, over every config of this user (2026-11-01): an order Sauron
    sent whose answer did not come back, noted on either lane
    (AssetBot._order_in_doubt) and fresh for IN_DOUBT_QUIET_HOURS, as the
    note itself is. Each reader keeps the ones its own read can carry
    (doubt_at). Words only: nothing here counts it. Never raises: a page
    renders without it."""
    from datetime import datetime as _dt
    now = now or timezone.now()
    out = {}
    try:
        from bot_program.asset_engine.base import AssetBot
        from bot_program.models import AssetBotConfig
        quiet_s = float(AssetBot.IN_DOUBT_QUIET_HOURS) * 3600.0
        books = [(e or {}).get("entry_in_doubt") if isinstance(e, dict)
                 else None for e in AssetBotConfig.objects.filter(
                     user_id=getattr(user, "pk", None))
                 .values_list("extras", flat=True)]
    except Exception:  # noqa: BLE001 — the label is left out
        logger.warning("etoro_used: the in-doubt notes could not be read",
                       exc_info=True)
        return out
    for book in books:
        if not isinstance(book, dict):
            continue
        for symbol, note in book.items():
            try:
                at = _dt.fromisoformat(str((note or {}).get("at")))
                if (now - at).total_seconds() >= quiet_s:
                    continue
            except (TypeError, ValueError, AttributeError):
                continue
            out.setdefault(str(symbol).upper(), []).append(at)
    return {k: sorted(v) for k, v in out.items()}


def doubt_at(times, read_at):
    """The latest of `times` (in_doubt_times' list for one symbol) whose
    order a read of eToro taken at `read_at` could carry, or None
    (2026-11-01).

    The label was chosen by symbol and freshness alone, so a holdings list
    or a frozen-cash read taken before Sauron's order left — or a position
    eToro opened before then — was named "may be Sauron's order", and an
    operator acting on the page could close the wrong real position. An
    order leaves at most its POST's timeout before its note, and the sync
    stamps a read before it reads: a read stamped no earlier than
    LIST_LAG_S before the note may carry it, and a position eToro dates no
    earlier than that may be it (pass its open time). `read_at` None
    carries nothing."""
    from datetime import timedelta
    if read_at is None:
        return None
    try:
        edge = read_at + timedelta(seconds=LIST_LAG_S)
        fits = [t for t in (times or []) if t <= edge]
    except TypeError:
        return None
    return max(fits) if fits else None


def _opened_at(row):
    """eToro's own open time of a holdings row (broker_portfolio's
    "opened_at", 2026-11-01), or None: a row stored before it, or one
    that did not carry it."""
    from datetime import datetime as _dt
    raw = (row or {}).get("opened_at") if isinstance(row, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        at = _dt.fromisoformat(raw)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def _utc_minute(at) -> str:
    """'2026-11-01 13:42 UTC'."""
    from datetime import timezone as dt_timezone
    return at.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def doubt_words(at) -> str:
    """DOUBT for a note written at `at`."""
    return DOUBT.format(time=_utc_minute(at))


def _rows(user, at):
    """This user's non-paper rows that can be part of the split: open or
    closing now, a close given up on (status ERROR with no close time:
    pending_closes._give_up, the one writer of ERROR), and — when `at` is
    a read time — a row closed or withdrawn after it (open at that read;
    a working order eToro holds margin for, measured: used margin and
    frozen cash 42.5 for a held order, doc §4 D2b-i)."""
    from django.db.models import Q

    from bot_program.models import AssetBotTrade
    q = (Q(status__in=("OPEN", "CLOSE_PENDING"))
         | Q(status="ERROR", closed_at__isnull=True))
    if at is not None:
        q = q | Q(status__in=("CLOSED", "CANCELED"), closed_at__gt=at)
    return list(AssetBotTrade.objects.filter(config__user=user, paper=False)
                .filter(q).select_related("config"))


def _at_work(trade) -> float:
    """What one eToro row ties up: entry value over its own leverage
    (risk_gate.capital_at_work, carrier etoro: the venue's measured
    notional / L, the full notional at 1) — the capital summary's rule."""
    from portfolio.risk_gate import capital_at_work
    from portfolio.services import value_per_unit
    meta = trade.metadata or {}
    notional = abs(float(trade.entry_price or 0) * float(trade.qty or 0)
                   * value_per_unit(trade))
    return capital_at_work(trade.asset_class, notional,
                           leverage=meta.get("leverage"), carrier="etoro")


def _currencies(symbols) -> dict:
    """{symbol: quote currency} for the instruments the catalogue knows."""
    if not symbols:
        return {}
    try:
        from instruments.models import Instrument
        return {str(s).upper(): str(c or "").upper()
                for s, c in Instrument.objects.filter(symbol__in=symbols)
                .values_list("symbol", "currency")}
    except Exception:  # noqa: BLE001 — an unknown currency is not marked
        return {}


def account_used(user, *, now=None, positions=False) -> "dict | None":
    """eToro's own used / available / P&L / total for the world the
    account trades in, with the split; None when the user has no eToro row
    (or an unkeyed one never read). Never raises a read error: a page must
    render without it.

    {"name", "label", "world" ("live"/"demo"), "world_word", "env",
    "currency", "read" (cells stored, of this world), "reason",
    "used", "available", "pnl", "total", "frozen", "balance" (None =
    unmeasured), "used_t", "available_t", "pnl_t", "total_t", "frozen_t",
    "at", "age_s", "age_t", "total_at", "total_age_s", "total_age_t",
    "total_own_age_t" (the total's age when it is more than
    TOTAL_OWN_AGE_S older than the cells, else ""), "sauron", "sauron_n",
    "stopped", "stopped_n" (a close given up on that eToro still lists, or
    may: its holdings cannot say, portfolio.services.abandoned_still_held),
    "stopped_gone_n" (one a fresh list no longer shows, not counted),
    "outside" (None unread; below zero when Sauron's
    rows count more than eToro holds), "since_n", "unstamped_n",
    "unconverted" [{"symbol", "currency"}], "held" (2026-11-01: the part
    of "outside" eToro holds as frozen cash that Sauron's WORKING rows do
    not explain; None when the frozen cash is not read), "positions_part"
    (the rest of "outside"; None with "held"), "held_t",
    "positions_part_t", "held_doubt_t" (the in-doubt notes the held part
    may be, in words, or "": only one whose order these cells could
    carry, doubt_at), "t" (the head line), "cell_t"
    (a strip cell's line under the used figure), "split_t", "title"} and,
    with `positions`, "positions": the holdings no Sauron row accounts for
    (outside_positions)."""
    now = now or timezone.now()
    acct = _account(user)
    if acct is None:
        return None
    at = getattr(acct, "last_margin_at", None)
    if not getattr(acct, "api_key_enc", "") and at is None:
        return None
    world = "demo" if acct.demo else "live"
    word = WORLD_WORDS[world]
    stamped = str(getattr(acct, "last_margin_world", "") or "")
    ccy = str(getattr(acct, "last_equity_currency", "") or "").upper()
    read = at is not None and stamped == world

    used = available = pnl = total = frozen = balance = None
    total_at = None
    reason = ""
    if at is None:
        reason = "never read"
    elif stamped != world:
        reason = (f"read in the {stamped or 'unstamped'} world; this row "
                  f"trades {world}")
    else:
        used = _f(acct.last_used_margin)
        available = _f(acct.last_available_cash)
        pnl = _f(getattr(acct, "last_pnl", None))
        frozen = _f(getattr(acct, "last_frozen_cash", None))
        balance = _f(getattr(acct, "last_balance", None))
        total = _f(acct.last_equity)
        total_at = acct.last_equity_at if total is not None else None
    age_s, total_age_s = _age(at if read else None, now), _age(total_at, now)

    split = _split(user, world, ccy or "USD", at if read else None, acct)
    outside = (round(used - split["sauron"] - split["stopped"], 2)
               if used is not None else None)

    # WHAT eTORO HOLDS WITH NO SAURON ROW (2026-11-01): its frozen cash
    # less what Sauron's own WORKING rows explain at that read — those rows
    # are under "opened by Sauron" already and are not counted twice. A
    # remainder inside their fees is no order (frozen_explained). None
    # when the frozen cash is not read: unread is not zero.
    held = positions_part = None
    if read and frozen is not None:
        try:
            from bot_program.asset_engine.base import frozen_explained
            fx = frozen_explained(user, world, at)
            raw = frozen - fx["margin"]
            held = round(raw, 2) if raw > fx["tolerance"] + 0.005 else 0.0
        except Exception:  # noqa: BLE001 — the split renders without it
            logger.warning("etoro_used: the WORKING rows could not be read",
                           exc_info=True)
            held = None
    if held is not None and outside is not None:
        positions_part = round(outside - held, 2)
    doubts = in_doubt_times(user, now=now) if (held or positions) else {}
    # Only a note whose order these cells could carry (2026-11-01,
    # doubt_at): cash read before an order left is not that order.
    held_doubt = ""
    if held:
        for s, times in sorted(doubts.items()):
            t = doubt_at(times, at)
            if t is not None:
                held_doubt += DOUBT_HELD.format(symbol=s, time=_utc_minute(t))

    # THE TOTAL'S OWN AGE, WHEREVER THE CELLS' AGE IS SAID (2026-10-31).
    # The re-read after an order and a close moves the cells and never the
    # total, so a stalled sync left an equity hours old under "read 20 s
    # ago" on the strips, the Ops Center and the header dropdown; only this
    # head line dated it. One rule, one word, for all of them.
    own_age = ""
    if (read and total_age_s is not None and age_s is not None
            and total_age_s - age_s > TOTAL_OWN_AGE_S):
        own_age = _age_words(total_age_s)
    total_aged = TOTAL_AGE.format(age=own_age) if own_age else ""
    if read:
        head = HEAD.format(world=word, ccy=f", {ccy}" if ccy else "",
                           used=money(used), available=money(available),
                           pnl=money(pnl, signed=True),
                           total=money(total) + total_aged,
                           age=_age_words(age_s))
        cell = CELL.format(available=money(available), total=money(total),
                           total_age=total_aged, age=_age_words(age_s))
    elif at is None:
        head = cell = HEAD_NEVER.format(world=word)
    else:
        head = cell = HEAD_OTHER_WORLD.format(world=word,
                                              stamped=stamped or "unstamped")

    unconverted = ""
    if split["unconverted"]:
        names = ", ".join(f"{u['symbol']} {u['currency']}"
                          for u in split["unconverted"])
        unconverted = UNCONVERTED.format(n=len(split["unconverted"]),
                                         names=names)
    stopped = ((STOPPED_UNREAD if split["stopped_unread"] else STOPPED)
               .format(stopped=money(split["stopped"]))
               if split["stopped_n"] else "")
    if outside is not None:
        # Below zero, said the other way round (2026-10-31).
        piece = (OVER.format(over=money(-outside)) if outside < 0
                 else OUTSIDE.format(outside=money(outside)))
        if held:
            # The part eToro holds with no Sauron row, carved out with its
            # age (2026-11-01); nothing is said when there is none.
            held_piece = HELD.format(held=money(held), age=_age_words(age_s),
                                     doubt=held_doubt)
            if outside < 0:
                piece = f"{piece}; {held_piece}"
            elif positions_part >= 0:
                piece = OUTSIDE_HELD.format(outside=money(outside),
                                            held=held_piece,
                                            rest=money(positions_part))
            else:
                piece = OUTSIDE_HELD_OVER.format(
                    outside=money(outside), held=held_piece,
                    over=money(-positions_part))
        split_t = SPLIT.format(sauron=money(split["sauron"]),
                               unconverted=unconverted, stopped=stopped,
                               outside=piece, pnl=money(pnl, signed=True))
    else:
        split_t = SPLIT_UNREAD.format(sauron=money(split["sauron"]),
                                      unconverted=unconverted,
                                      stopped=stopped, dash=DASH)
    if split["stopped_gone_n"]:
        split_t += STOPPED_GONE.format(**_plural(split["stopped_gone_n"]))
    if split["since_n"]:
        split_t += SINCE.format(**_plural(split["since_n"]))
    if split["unstamped_n"]:
        split_t += UNSTAMPED.format(**_plural(split["unstamped_n"]))

    out = {
        "name": "eToro", "label": acct.label, "world": world,
        "world_word": word, "env": acct.env_label,
        "venue_class": ("sv-venue--live" if world == "live"
                        else "sv-venue--demo"),
        "currency": ccy, "read": read, "reason": reason,
        "used": used, "available": available, "pnl": pnl, "total": total,
        "frozen": frozen, "balance": balance,
        "used_t": money(used), "available_t": money(available),
        "pnl_t": money(pnl, signed=True), "total_t": money(total),
        "frozen_t": money(frozen),
        "at": at if read else None, "age_s": age_s,
        "age_t": _age_words(age_s) if age_s is not None else "",
        "total_at": total_at, "total_age_s": total_age_s,
        "total_age_t": (_age_words(total_age_s) if total_age_s is not None
                        else ""),
        "total_own_age_t": own_age,
        "sauron": split["sauron"], "sauron_n": split["sauron_n"],
        "stopped": split["stopped"], "stopped_n": split["stopped_n"],
        "stopped_gone_n": split["stopped_gone_n"],
        "outside": outside, "since_n": split["since_n"],
        "unstamped_n": split["unstamped_n"],
        "unconverted": split["unconverted"],
        "held": held, "held_t": money(held),
        "positions_part": positions_part,
        "positions_part_t": money(positions_part),
        "held_doubt_t": held_doubt.lstrip("; "),
        "t": head, "cell_t": cell, "split_t": split_t, "title": TITLE,
    }
    if positions:
        out["positions"] = outside_positions(user, acct, now=now,
                                             claims=split["claims"],
                                             doubts=doubts)
    return out


def _split(user, world, ccy, at, acct=None) -> dict:
    """Sauron's eToro rows of `world` at the read `at` (now when None):
    opened by Sauron, a close given up on, rows booked since, rows that
    name no broker, and the non-USD stock rows nothing here converts.

    A CLOSE GIVEN UP ON IS STILL OPEN AT eTORO ONLY WHILE eTORO LISTS IT
    (2026-10-31). pending_closes._give_up says the position "may still be
    open at the broker", and its alert asks the operator to close it
    there; once he has, it is in none of eToro's figures. It was said
    "still open at eToro" and taken off eToro's used whatever the
    holdings said, which understated what is outside Sauron by exactly
    the margin the split exists to show, and the Treasury contradicted
    itself (its divergence said "the broker no longer lists it"). Now it
    is matched against the holdings snapshot: listed, it is subtracted;
    not listed, it is counted apart and not subtracted; holdings that
    cannot say, it is subtracted and said "may still be open".

    THE GATES' OWN PREDICATE (2026-11-01). Since that date the exposure
    and open-risk gates, the capital summary and the TAKE TRADE pool count
    such a row too, through portfolio.services.abandoned_still_held, and
    this part reads that one predicate: listed by its position id (else by
    symbol and side), or a snapshot that cannot say (never read, older than
    capital_truth.TRACKING_FRESH_SECONDS, of the demo world for a live
    row; a demo row while the account trades live is no money), so the
    split, the pages and the gates agree on every row. A stale snapshot
    said "no longer listed" here while the gates kept counting; it says
    "may still be open" now. Opened by Sauron is this walk's open rows
    only, never capital_summary's used, so no row is counted in both."""
    out = {"sauron": 0.0, "sauron_n": 0, "stopped": 0.0, "stopped_n": 0,
           "stopped_gone_n": 0, "stopped_unread": False, "since_n": 0,
           "unstamped_n": 0, "unconverted": [], "claims": None}
    try:
        rows = _rows(user, at)
    except Exception:  # noqa: BLE001 — the head line still says eToro's
        logger.warning("etoro_used: the rows could not be read",
                       exc_info=True)
        return out
    # The predicate's rows, read once and only when a close given up on
    # needs them.
    still_held = None
    counted = []
    for t in rows:
        meta = t.metadata or {}
        carrier = str(meta.get("broker") or "").strip().lower()
        if _world_of_trade(t) != world:
            continue
        open_now = t.status in ("OPEN", "CLOSE_PENDING")
        given_up = t.status == "ERROR" and t.closed_at is None
        if at is not None and t.opened_at is not None and t.opened_at > at:
            if carrier == "etoro" and (open_now or given_up):
                out["since_n"] += 1
            continue
        if not carrier:
            if open_now:
                out["unstamped_n"] += 1
            continue
        if carrier != "etoro":
            continue
        try:
            work = _at_work(t)
        except Exception:  # noqa: BLE001 — one row is not the split
            continue
        if given_up:
            if still_held is None:
                still_held = _still_held(user)      # {pk: row}, or False
            if still_held is False:
                kept, listed = t, False             # unreadable: cannot say
            else:
                kept = still_held.get(t.pk)
                listed = bool(getattr(kept, "held_listed", False))
            if kept is None:
                out["stopped_gone_n"] += 1
                continue
            out["stopped_unread"] = out["stopped_unread"] or not listed
            out["stopped"] += work
            out["stopped_n"] += 1
        else:
            out["sauron"] += work
            out["sauron_n"] += 1
        counted.append(t)
    out["sauron"] = round(out["sauron"], 2)
    out["stopped"] = round(out["stopped"], 2)
    # NON-USD NOTIONAL IS NOT CONVERTED (2026-10-31). services.value_per_unit
    # is 1 for every class but forex, so a stock quoted in EUR is counted
    # in EUR as if it were the account's currency; the gates share that
    # rule and it is left alone. The split says which rows it is.
    cands = [t for t in counted if t.asset_class != "forex"]
    ccys = _currencies(sorted({str(t.symbol or "").upper() for t in cands}))
    seen = set()
    for t in cands:
        sym = str(t.symbol or "").upper()
        quote = ccys.get(sym, "")
        if quote and quote != ccy and sym not in seen:
            seen.add(sym)
            out["unconverted"].append({"symbol": sym, "currency": quote})
    return out


def _still_held(user):
    """{pk: row} of the closes given up on that the venue may still hold,
    each carrying `held_listed` (2026-11-01): the gates' own predicate,
    portfolio.services.abandoned_still_held, imported from there so no gate
    module ever reads this one. False when it cannot be read: every such
    row then "may still be open", never "no longer listed"."""
    try:
        from portfolio.services import abandoned_still_held
        return {t.pk: t for t in abandoned_still_held(user)}
    except Exception:  # noqa: BLE001 — the split renders without it
        logger.warning("etoro_used: the given-up rows could not be judged",
                       exc_info=True)
        return False


def _claim_order(trade, s_at) -> int:
    """Who claims first when two rows could take one leg: a row open at
    the read (one closed after it was open then), then a close given up
    on, then a row closed inside the list's lag."""
    if trade.status == "ERROR":
        return 1
    if trade.status in ("OPEN", "CLOSE_PENDING") or (
            trade.closed_at is not None and trade.closed_at > s_at):
        return 0
    return 2


def _claimants(user, world, s_at) -> list:
    """Sauron's eToro rows of `world` that eToro's holdings, read at
    `s_at`, can list, in claim_row's shape and in the order they claim
    (_claim_order): open when the list was read (a working order too: its
    fill may be listed before the poll books it), a close given up on, a
    row closed less than LIST_LAG_S before the read (eToro still lists
    it).

    A ROW BOOKED AFTER THE READ CLAIMS BY ITS OWN ID ONLY (2026-10-31).
    The sync dates the holdings before its reads (tasks.sync_etoro_accounts
    takes the stamp before the aggregate GET, the names and the /portfolio
    GET), and a row is booked a second or more after eToro's fill: a fill
    booked between the stamp and the /portfolio GET is in the list, and
    its row, dropped as "booked after the read", left Sauron's own managed
    position listed as outside for a whole sync while the divergence on
    the same page paired it. The position id the row records is that
    position's own, so it claims it whenever the row was booked; a late
    row with no id, or an id the list does not hold, claims nothing
    (by_id_only: never by symbol and units, which could take the leg of
    another position)."""
    from datetime import timedelta

    out = []
    for t in _rows(user, s_at - timedelta(seconds=LIST_LAG_S)):
        meta = t.metadata or {}
        if str(meta.get("broker") or "").strip().lower() != "etoro":
            continue
        if _world_of_trade(t) != world:
            continue
        claim = claim_row(t)
        if t.opened_at is not None and t.opened_at > s_at:
            if not claim["position_id"]:
                continue
            claim["by_id_only"] = True
        out.append(claim)
    out.sort(key=lambda c: _claim_order(c["trade"], s_at))
    return out


def claim_holdings(user, held, s_at, world) -> dict:
    """eToro's holdings snapshot `held` (read at `s_at`) matched with
    Sauron's rows that can account for it (2026-10-31): {"pairs":
    [(holding, claimant)], "left": [holdings no row accounts for],
    "claimed": {the pks of the rows that took a leg}}. The holdings are
    the caller's own dicts, kept as given (a page marks them); the outside
    list, the split's stopped closes and the positions page's panel all
    read this one match."""
    rows = [r for r in (held or []) if isinstance(r, dict)]
    pairs, left, _ours = match_positions(rows, _claimants(user, world, s_at))
    return {"pairs": pairs, "left": left,
            "claimed": {c["trade"].pk for _h, c in pairs}}


def _holdings_claims(user, acct) -> "dict | None":
    """claim_holdings over the account's own snapshot; None when it was
    never read, or the rows could not be (an unread claim is not
    "outside", and not "no longer listed")."""
    if acct is None:
        return None
    held = getattr(acct, "broker_positions", None)
    s_at = getattr(acct, "broker_positions_at", None)
    if held is None or s_at is None:
        return None
    try:
        return claim_holdings(user, held, s_at,
                              "demo" if acct.demo else "live")
    except Exception:  # noqa: BLE001 — a page renders without it
        logger.warning("etoro_used: the claimants could not be read",
                       exc_info=True)
        return None


#: The positions page's words for a holding's claim (2026-10-31).
CLAIMED, STOPPED_CLAIM, NO_BROKER = "claimed", "stopped", "no_broker"


def mark_holdings(user, rows, s_at) -> None:
    """Marks each eToro holding the positions page's "At the broker" panel
    shows with what accounts for it (2026-10-31): row["claim"] is
    "claimed" (a Sauron row of the account's world), "stopped" (a close
    Sauron gave up on: still open at eToro), "no_broker" (a live row on
    it records no broker: it may be this position, and the split counts
    it apart) or "" (nothing: outside Sauron); row["claimed"] says
    whether anything does.

    The panel claimed with its own rule, open and closing rows of any
    world only, so a stopped close and a leg closed inside eToro's list
    lag read UNCLAIMED while the split and the Treasury on the same page
    called them Sauron's. It now reads the outside list's own match
    (claim_holdings)."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    for r in rows:
        r["claim"], r["claimed"] = "", False
    if s_at is None or not rows:
        return
    acct = _account(user)
    world = "demo" if (acct is not None and acct.demo) else "live"
    claims = claim_holdings(user, rows, s_at, world)
    for h, c in claims["pairs"]:
        h["claim"] = (STOPPED_CLAIM if c["trade"].status == "ERROR"
                      else CLAIMED)
    from bot_program.models import AssetBotTrade
    unstamped = [claim_row(t) for t in AssetBotTrade.objects.filter(
                     config__user=user, paper=False,
                     status__in=("OPEN", "CLOSE_PENDING"))
                 if not str((t.metadata or {}).get("broker") or "").strip()
                 and _world_of_trade(t) == world]
    for h, _c in match_positions(claims["left"], unstamped)[0]:
        h["claim"] = NO_BROKER
    for r in rows:
        r["claimed"] = bool(r["claim"])


def outside_positions(user, acct=None, *, now=None, claims=None,
                      doubts=None) -> dict:
    """What eToro's holdings snapshot carries that no Sauron row accounts
    for, position by position (2026-10-31).

    {"known" (a snapshot exists), "at", "age_s", "age_t", "rows": [{"symbol",
    "side", "qty", "avg_cost", "leverage", "amount", "margin", "estimated",
    "net_profit", "position_id", "in_doubt_t"}], "n", "margin" (the rows'
    sum, None when one cannot be priced), "estimated_n"}.

    The claimants are Sauron's eToro rows of the account's world that the
    snapshot can list (_claimants): open when it was read, a close given
    up on, a row closed less than LIST_LAG_S before the read, and a row
    booked after the read by the position id it records only. `claims` is
    claim_holdings' answer when the caller has it already.

    "in_doubt_t" (2026-11-01): a position on a symbol with a fresh in-doubt
    note on any of the user's configs may be Sauron's own order whose
    answer did not come back — said in words (DOUBT), never claimed,
    adopted or counted apart — when it could be that order (doubt_at): a
    position eToro dates (its own open time) no earlier than LIST_LAG_S
    before the note, or with no such time, a list stamped so. `doubts` is
    in_doubt_times' answer when the caller has it already."""
    now = now or timezone.now()
    acct = acct if acct is not None else _account(user)
    out = {"known": False, "at": None, "age_s": None, "age_t": "",
           "rows": [], "n": 0, "margin": None, "estimated_n": 0}
    if acct is None:
        return out
    s_at = getattr(acct, "broker_positions_at", None)
    if claims is None:
        claims = _holdings_claims(user, acct)
    if claims is None:
        return out
    rows, total, priced, estimated = [], 0.0, True, 0
    if doubts is None and claims["left"]:
        doubts = in_doubt_times(user, now=now)
    for r in claims["left"]:
        margin, est = outside_margin(r)
        if margin is None:
            priced = False
        else:
            total += margin
        estimated += 1 if est else 0
        opened = _opened_at(r)
        noted = doubt_at((doubts or {}).get(_sym(r)),
                         opened if opened is not None else s_at)
        rows.append({"symbol": _sym(r), "side": side_key(r.get("side")),
                     "qty": _qty(r), "avg_cost": _f(r.get("avg_cost")),
                     "leverage": r.get("leverage"),
                     "amount": _f(r.get("amount")), "margin": margin,
                     "estimated": est, "net_profit": _f(r.get("net_profit")),
                     "position_id": _pid(r) or None,
                     "margin_t": money(margin),
                     "net_profit_t": money(r.get("net_profit"), signed=True),
                     "in_doubt_t": doubt_words(noted) if noted else ""})
    age = _age(s_at, now)
    out.update({"known": True, "at": s_at, "age_s": age,
                "age_t": _age_words(age), "rows": rows, "n": len(rows),
                "margin": round(total, 2) if priced else None,
                "margin_t": money(round(total, 2)) if priced else DASH,
                "estimated_n": estimated})
    return out
