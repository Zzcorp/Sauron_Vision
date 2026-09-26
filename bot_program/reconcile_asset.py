"""Phase-33 AssetBotTrade reconciliation.

Walks each user's open AssetBotTrade rows and verifies the broker still
agrees the position is open. Catches three drift classes:

  1. User manually closed a position via the broker UI (DB still OPEN).
  2. Broker-side stop-out / margin call / liquidation (DB still OPEN).
  3. Worker died mid-order — order may have filled broker-side but no DB row
     (this case is broker-state vs DB; we can only flag, not resolve here).

For (1) and (2), mark the trade CLOSED with `outcome="manual_close"`,
`exit_price=last_known_price`, `pnl=computed`, and grade it.

Skips paper trades (no real broker to query). Skips brokers that don't
expose a `get_positions()` or `account()` shape we can use.

Per-user; iterate all users with at least one OPEN AssetBotTrade.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

#: How long a row that just CLOSED keeps claiming its symbol for the sweep
#: (reconcile_unknown_positions). eToro lists a closed position for up to
#: ~60 s after the close (measured 2026-09-23); the sweep only REPORTS, so
#: claiming for twice that, at every venue, costs nothing and stops a page
#: saying "UNCLAIMED" about a position that is closing.
SWEEP_CLOSED_GRACE_S = 120


def keyed_venue_count(user) -> int:
    """How many of this user's broker rows exist AND carry credentials.

    The discriminator for an unattributable row. With one keyed venue a miss
    there means the position is gone; with two it could equally mean the
    position lives at the other one, and nothing on a pre-2026-09-19 row says
    which. Counted rather than assumed, and an unreadable row counts as not
    keyed — the same reading `broker_vision._keyed` takes.
    """
    from bot_program.broker_vision import BROKER_ROWS, _keyed
    n = 0
    for kind, attr, _name in BROKER_ROWS:
        acct = getattr(user, attr, None)
        if acct is not None and _keyed(kind, acct):
            n += 1
    return n


def unattributable(trade, client, *, keyed: int) -> str:
    """Why a MISS at `client` proves nothing about `trade`, or "".

    Two reasons, and they are the same sentence about two different gaps.

      * THE ROW NAMES A DIFFERENT VENUE. `execute_entry` stamps
        metadata["broker"] with the adapter that carried the entry, and every
        path that can book a close rebuilds the client from TODAY's
        primary-for flag instead. One moved checkbox and this asks the wrong
        venue about a live position.
      * THE ROW NAMES NOTHING AND MORE THAN ONE VENUE IS KEYED. The stamp
        only began today, so older rows carry nothing; with two keyed venues
        a miss cannot tell "gone" from "held at the other one".

    Empty string means the miss IS attributable and the caller may act on it:
    the venues agree, or only one venue exists to disagree with.
    """
    from bot_program.engine.capabilities import adapter_key
    carried = str((getattr(trade, "metadata", None) or {}).get("broker") or "")
    now_at = adapter_key(client)
    if carried and now_at and carried != now_at:
        return (f"it was carried by {carried} and the router now answers "
                f"{now_at}, so a miss at the wrong venue is not an absence")
    if not carried and keyed > 1:
        return (f"it records no carrier and {keyed} venues are keyed, so a "
                f"miss here cannot tell a closed position from one held at "
                f"another venue")
    # THE ROW NAMES A WORLD AND THE CLIENT ANSWERS FROM THE OTHER ONE.
    # execute_entry — and the TAKE TRADE lane, through AssetBot.venue_stamps
    # — stamp metadata["broker_env"] from the client that placed the order;
    # broker_router builds the eToro and Saxo clients from the account
    # row's Demo/SIM flag AT CALL TIME (broker_router._etoro_client_for).
    # Tick Demo on /brokers/ with live rows open and this function would
    # compare them against the demo book, whose honest "I hold nothing" is
    # not an absence. Three states: a row with no world, or a client that
    # does not say, refuses nothing — an unknown world is not a different
    # one. Reconcile and the drain inherit this through the one function.
    from .asset_engine.base import AssetBot
    filled_in = str((getattr(trade, "metadata", None) or {})
                    .get("broker_env") or "")
    answers_from = AssetBot.VENUE_WORLDS.get(
        str(getattr(client, "env", "") or "").lower(), "")
    if filled_in and answers_from and filled_in != answers_from:
        return (f"it was filled in the {filled_in} world and the router now "
                f"answers the {answers_from} world, so a miss here is not an "
                f"absence")
    return ""


def venue_lag_window(trade, client) -> str:
    """Why ONE read of this venue's position list cannot yet speak for
    `trade`, or "".

    The venue says how long its list lags, on the client, as
    PORTFOLIO_LAG_S (EtoroTrader: 60 — MEASURED 2026-09-23: a filled
    position absent ~2 s after the fill, a closed one still listed 3 s after
    the close, both settled by ~60 s). Only a NUMBER declares a window: a
    client with none, 0, or a MagicMock's attribute lags for nobody and the
    reader acts as before. Inside the window the row's own stamps say what
    just happened: opened_at (the bot lane creates the row right after the
    fill), entry_filled_at (a WORKING row that filled later), close_sent_at
    (a close sent and answered) and close_retry_last_at (a resend). A naive
    stamp is refused, not localised. Three states: the reason, or "" —
    never a guess about which way the list is wrong. Read by reconcile_user
    and by pending_closes.retry_trade_close.
    """
    from datetime import datetime as _dt
    lag = getattr(client, "PORTFOLIO_LAG_S", 0)
    if isinstance(lag, bool) or not isinstance(lag, (int, float)) or lag <= 0:
        return ""
    meta = (trade.metadata
            if isinstance(getattr(trade, "metadata", None), dict) else {})
    now = timezone.now()
    stamps = (("opened", getattr(trade, "opened_at", None)),
              ("filled", meta.get("entry_filled_at")),
              ("sent a close", meta.get("close_sent_at")),
              ("retried a close", meta.get("close_retry_last_at")))
    for what, raw in stamps:
        if not raw:
            continue
        try:
            at = raw if isinstance(raw, _dt) else _dt.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        if timezone.is_naive(at):
            continue
        age = (now - at).total_seconds()
        if 0 <= age < float(lag):
            return (f"{what} {int(age)} s ago, and {type(client).__name__}'s "
                    f"position list lags up to {int(lag)} s "
                    f"(measured 2026-09-23)")
    return ""


def _broker_open_symbols(client, *, asset_class: str, warm=()) -> dict:
    """Best-effort broker open-position state.

    Returns None if the broker doesn't expose enough state (we won't
    reconcile in that case rather than guess wrong), else a dict:

      symbols          — every symbol the broker reports open. Alpaca
                         reports options under their OCC symbol here.
      opt_underlyings  — underlyings of positions explicitly typed OPT
                         (IBKR provides sec_type per position).
      has_sec_types    — True when the client annotates security types,
                         i.e. opt_underlyings is a meaningful signal.
      unnamed          — how many open positions this client could not put
                         a platform symbol on. NOT in `symbols`, because
                         matching on `ETORO:1001` is matching on nothing —
                         and counted, because every caller reads a miss in
                         `symbols` as "the broker is flat" and closes the
                         row on it.

    `warm` is the symbols this reader is about to ask about. eToro names a
    position only from the reverse map the client itself filled and the
    router hands out a fresh client per call, so without the warm a reader
    that placed no order can never confirm a position IS open either — it
    would answer "unreadable" for ever, which is its own kind of blind.
    """
    # Alpaca exposes /v2/positions; OANDA via /v3/accounts/.../openPositions;
    # IBKR via positions(); Binance via positionRisk. The exact API varies —
    # we use a duck-typed `get_positions()` if present, else None.
    # WARM THE VENUE'S NAME FIRST, through the adapter's own method — the
    # same one an order uses. Failures are not fatal and are not silent
    # either: whatever the warm missed is counted as `unnamed` below.
    name_it = getattr(client, "instrument_id", None)
    if callable(name_it):
        for sym in (warm or ()):
            try:
                name_it(sym)
            except Exception as e:  # noqa: BLE001 — the count is the net
                logger.debug("reconcile: %s cannot name %s (%s)",
                             type(client).__name__, sym, e)

    fn = getattr(client, "get_positions", None)
    if not callable(fn):
        return None
    try:
        positions = fn() or []
    except Exception as e:
        logger.warning("reconcile: %s.get_positions() failed: %s",
                       type(client).__name__, e)
        return None
    symbols, opt_underlyings, has_sec_types = set(), set(), False
    unnamed = 0
    for p in positions:
        if isinstance(p, dict):
            sym, sec = p.get("symbol"), p.get("sec_type")
            unresolved = p.get("symbol_unresolved") is True
        else:
            sym, sec = getattr(p, "symbol", None), getattr(p, "sec_type", None)
            unresolved = getattr(p, "symbol_unresolved", None) is True
        # `is True` and not a truth test: a MagicMock answers any attribute
        # with a truthy object, and a reader that believed it would report
        # every position in every test as unnameable.
        if not sym or unresolved:
            unnamed += 1
            continue
        sym = str(sym).upper()
        symbols.add(sym)
        if sec is not None:
            has_sec_types = True
            if str(sec).upper() == "OPT":
                opt_underlyings.add(sym)
    return {"symbols": symbols, "opt_underlyings": opt_underlyings,
            "has_sec_types": has_sec_types, "unnamed": unnamed}


def _options_row_open_at_broker(trade, state: dict):
    """Whether the broker still reports this options trade — or None when the
    broker feed can't answer for options and we must not guess.

    trade.symbol is the UNDERLYING for options rows, and brokers disagree on
    how they report option positions: Alpaca lists the OCC symbol, IBKR lists
    the underlying with sec_type OPT. Matching trade.symbol against a stock
    feed would orphan-close a live option (and keep a closed one open).
    """
    occ = str((trade.metadata or {}).get("occ_symbol") or "").upper()
    if occ and occ in state["symbols"]:
        return True
    if trade.symbol.upper() in state["opt_underlyings"]:
        return True
    # Definitive "not open" needs a definitive way to have seen it: an OCC
    # symbol to look for, or a sec-typed feed. Otherwise: cannot reconcile.
    if not occ and not state["has_sec_types"]:
        return None
    return False


def reconcile_user(user) -> dict:
    """Reconcile one user's open AssetBotTrade rows against broker state.

    Returns counts: {checked, closed_as_orphan, broker_unavailable, errors}.
    """
    from .models import AssetBotTrade
    from .engine.broker_router import client_for_symbol
    from .engine.capabilities import adapter_key as _adapter_key

    qs = (AssetBotTrade.objects
          .filter(config__user=user, status__in=("OPEN", "CLOSE_PENDING"), paper=False)
          .select_related("config"))
    out = {"checked": 0, "closed_as_orphan": 0,
           "broker_unavailable": 0, "errors": 0}

    # Cache broker open-symbol sets per (asset_class, broker_name) — many
    # trades share the same broker, no need to query per row.
    cache: dict = {}

    # WHAT TO WARM BEFORE ASKING, per class, because the read below is
    # cached across rows and only the first row would otherwise warm
    # anything. The queryset is already evaluated by this second walk.
    by_class: dict = {}
    for _row in qs:
        if _row.symbol:
            by_class.setdefault(_row.asset_class, set()).add(_row.symbol)

    # Counted ONCE per walk, not per row: it cannot change mid-pass and the
    # credential read decrypts.
    _keyed_venues = keyed_venue_count(user)

    for trade in qs:
        # A WORKING entry is an ORDER, not a position: the broker correctly
        # reports no position for it, and closing it as an orphan would
        # cancel the protective legs of a parent that is still queued —
        # which then fills naked, into a row this function just closed. The
        # bot tick owns these rows (AssetBot._poll_working_entry).
        from .asset_engine.base import is_entry_working
        if is_entry_working(trade):
            out["entry_working"] = out.get("entry_working", 0) + 1
            continue
        out["checked"] += 1
        try:
            client = client_for_symbol(user, trade.symbol, trade.config)
            cache_key = (trade.asset_class, type(client).__name__)
            if cache_key not in cache:
                cache[cache_key] = _broker_open_symbols(
                    client, asset_class=trade.asset_class,
                    warm=by_class.get(trade.asset_class, ()))
            state = cache[cache_key]
            if state is None:
                # Broker doesn't expose state — can't reconcile this row.
                out["broker_unavailable"] += 1
                continue

            if trade.asset_class == "options":
                open_at_broker = _options_row_open_at_broker(trade, state)
                if open_at_broker is None:
                    out["broker_unavailable"] += 1
                    continue
            else:
                open_at_broker = trade.symbol.upper() in state["symbols"]

            # THE VENUE THAT CARRIED THIS ROW IS NOT ALWAYS THE VENUE
            # THE ROUTER ANSWERS TODAY. `execute_entry` stamps
            # metadata["broker"] with the adapter that actually carried the
            # entry, and until now the only reader of that field was the
            # /treasury/ display — while every path that can BOOK a close
            # rebuilds the client from today's primary-for flag. So moving
            # one checkbox makes this loop ask the wrong venue about a live
            # position, get an honest "I do not hold that", and orphan-close
            # a row whose leg is still open somewhere else.
            #
            # The `unnamed` valve below cannot catch it: the wrong venue can
            # name everything IT holds, so `unnamed` is 0 and the miss looks
            # like an absence.
            #
            # Three states. No recorded carrier (any row opened before
            # 2026-09-19) is cannot-tell and keeps today's behaviour; a
            # client the adapter map does not know answers "" and is also
            # cannot-tell. Only two KNOWN and DIFFERENT names refuse.
            _why = unattributable(trade, client, keyed=_keyed_venues)
            if not open_at_broker and _why:
                out["broker_unavailable"] += 1
                logger.error(
                    "reconcile: #%s (%s) NOT orphan-closed — %s",
                    trade.id, trade.symbol, _why)
                continue

            if not open_at_broker and state.get("unnamed"):
                # A MISS AGAINST A BOOK WE COULD NOT READ IS NOT AN ABSENCE.
                # The venue listed positions this client could not name, so
                # one of them may be this row. Orphan-closing here books a
                # live position CLOSED, labelled manual_close, at a mark
                # nobody filled at — and the label then means nothing on
                # this venue for ever after.
                out["broker_unavailable"] += 1
                logger.warning(
                    "reconcile: #%s (%s/%s) NOT orphan-closed — %s listed %d "
                    "position(s) it could not name, so a miss proves nothing",
                    trade.id, trade.asset_class, trade.symbol,
                    type(client).__name__, state["unnamed"])
                continue

            _lag_why = (venue_lag_window(trade, client)
                        if not open_at_broker else "")
            if _lag_why:
                # A MISS INSIDE THE VENUE'S OWN LAG WINDOW IS NOT AN ABSENCE.
                # eToro lists a filled position ~2 s late (measured
                # 2026-09-23); a */15 reconcile landing in that gap would
                # book a live, stop-protected position CLOSED with
                # exit_price_inferred and leave the venue holding it. Counted
                # unavailable, read again next pass. (The entry_working skip
                # above shielded every eToro row by accident under DEFECT 1;
                # this is the real shield.)
                out["broker_unavailable"] += 1
                logger.warning("reconcile: #%s (%s) NOT orphan-closed — %s",
                               trade.id, trade.symbol, _lag_why)
                continue

            if not open_at_broker:
                # DB says OPEN but broker says no position — orphan close.
                # Don't grade: we don't know if it was manual close, stop-out,
                # liquidation, etc. The `outcome="manual_close"` label is
                # honest about the uncertainty.
                _close_as_orphan(trade)
                out["closed_as_orphan"] += 1
                logger.warning("reconcile: closed orphan AssetBotTrade #%s "
                                "(%s/%s); broker no longer reports it.",
                                trade.id, trade.asset_class, trade.symbol)
        except Exception as e:
            logger.warning("reconcile: trade #%s failed: %s", trade.id, e)
            out["errors"] += 1
    return out


#: Set on a row that had to be closed with no price available. Its `pnl`
#: column reads 0.00 because the field is not nullable; this says that zero
#: is an absence of measurement, not a measurement of zero.
UNPRICED_EXIT_KEY = "exit_price_unavailable"


def _close_as_orphan(trade) -> None:
    """Mark an orphan trade CLOSED at last-known price."""
    # Best-effort exit price: use the broker's ticker, or fall back to
    # the trade's entry price (zero P&L) so we at least clear the row.
    from .engine.broker_router import client_for_symbol
    from .pending_closes import (EXIT_FILL_SOURCE_KEY,
                                 EXIT_SOURCE_BROKER, EXIT_SOURCE_MARK)
    from market_data.models import LiveQuote

    exit_price = trade.entry_price
    priced = False           # did anything but the entry price answer?
    measured = False         # ...and was it the BROKER'S OWN FILL?

    # The broker first, because it is the only source that knows what
    # actually happened. Stock and forex stops rest AT the broker, so for
    # most of those trades this is the exit — a leg the platform never
    # submitted and never saw print. Everything below this block is an
    # estimate, correctly flagged as one, and `realized_r` is computed
    # from whichever number lands here.
    try:
        from .engine.broker_router import client_for_symbol as _cfs
        _client = _cfs(trade.config.user, trade.symbol, trade.config)
        _fill = getattr(_client, "closing_fill", None)
        got = _fill(trade) if callable(_fill) else None
        if got and got.get("price"):
            exit_price = Decimal(str(got["price"]))
            priced = measured = True
            logger.info("reconcile: #%s %s exit read FROM THE BROKER at %s "
                        "(%s)", trade.id, trade.symbol, exit_price,
                        got.get("source", "?"))
    except Exception as e:  # noqa: BLE001 - an unreachable broker costs
        logger.debug("reconcile: broker fill unavailable for #%s: %s",
                     trade.id, e)          # this row an estimate, not a crash

    if measured:
        pass
    elif trade.asset_class == "options":
        # trade.symbol is the UNDERLYING — its ticker/LiveQuote is the wrong
        # scale for a premium-denominated trade. Mark at the option's own
        # premium, or entry (zero P&L) when unknown.
        try:
            from bot_program.asset_engine.options_bot import current_premium_for_trade
            premium = current_premium_for_trade(trade)
            if premium:
                exit_price, priced = premium, True
        except Exception:
            pass
    else:
        try:
            client = client_for_symbol(trade.config.user, trade.symbol, trade.config)
            tk = client.ticker(trade.symbol) or {}
            last = float(tk.get("lastPrice", 0) or 0)
            if last > 0:
                exit_price, priced = Decimal(str(last)), True
        except Exception:
            try:
                from instruments.models import Instrument
                inst = Instrument.objects.filter(symbol=trade.symbol).first()
                if inst:
                    lq = LiveQuote.objects.filter(instrument=inst).first()
                    if lq and lq.last:
                        exit_price, priced = lq.last, True
            except Exception:
                pass

    if trade.side == "BUY":
        pnl = (exit_price - trade.entry_price) * trade.qty
    else:
        pnl = (trade.entry_price - exit_price) * trade.qty
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import option_pnl_multiplier
            pnl *= option_pnl_multiplier(trade)
        except Exception:
            pass
    elif trade.asset_class == "forex":
        try:
            from bot_program.asset_engine.forex_bot import forex_usd_multiplier
            pnl *= forex_usd_multiplier(trade)
        except Exception:
            pass

    trade.exit_price = exit_price
    trade.pnl = pnl
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.reason = (trade.reason + " | reconciled-orphan").strip()

    # The exit price was INFERRED — a current ticker or a stored quote, not
    # the fill the broker actually got. Flag it, because the difference
    # matters to anyone reading the resulting R: this is the path every
    # bracket-protected stock and forex exit takes, so without the flag a
    # large share of the track record would silently be estimates.
    meta = dict(trade.metadata or {})
    # INFERRED only when it really was. A fill read from the broker is a
    # measurement, and flagging it as an estimate would understate the one
    # part of the track record that is not one.
    meta["exit_price_inferred"] = not measured
    if not priced:
        # Nothing anywhere could price this exit. The row still closes — an
        # orphan left open forever is its own failure — but its P&L is NULL
        # rather than a zero derived from the entry price, because a
        # stop-out that cost real money is not a scratch.
        #
        # The flag stays beside it. `pnl is None` is the fact; the flag is
        # what lets a reader distinguish "reconciliation could not price
        # this" from any other NULL a future writer might introduce, and
        # what the rows written before this migration still carry.
        meta[UNPRICED_EXIT_KEY] = True
        # trade.pnl, not the local: the assignment above has already run,
        # and setting a name nothing reads afterwards is how a fix looks
        # applied and is not.
        trade.pnl = None
        logger.error("reconcile: #%s %s closed with NO price available — "
                     "P&L recorded as UNMEASURED, not as flat",
                     trade.id, trade.symbol)
    # Provenance, written ONCE and from what actually happened.
    #
    # A CLOSE_PENDING row arrives here carrying `exit_fill_source: broker`
    # from the partial close that stranded it, and that stale value must not
    # survive a price this function had to assume — two contradictory flags
    # on one closed row let a reader treat an estimate as a measurement.
    # But it is `broker` again, honestly, when the block at the top of this
    # function actually read the fill: stamping `mark` unconditionally would
    # have thrown away the one number here that is not an estimate.
    meta[EXIT_FILL_SOURCE_KEY] = (EXIT_SOURCE_BROKER if measured
                                  else EXIT_SOURCE_MARK)
    trade.metadata = meta
    trade.save(update_fields=["exit_price", "pnl", "status", "closed_at",
                                "reason", "metadata"])

    # Grade it. The module docstring has always claimed this happened and it
    # never did: outcome was hardcoded to "manual_close" and realized_r was
    # left NULL. Since reconciliation is how EVERY broker-side exit is
    # finalised — which is all stock and forex trades, because their stops
    # rest at the broker — those two asset classes contributed exactly zero
    # graded trades to the learning loop no matter how long they ran.
    try:
        from bot_program.bot_grading import grade_bot_trade
        grade_bot_trade(trade)
    except Exception as e:
        logger.warning("reconcile: grading #%s failed: %s", trade.id, e)
        if not trade.outcome:
            trade.outcome = "manual_close"
            trade.save(update_fields=["outcome"])

    # THE VENUE CLOSED IT — a stop or a target struck, or a hand on the
    # broker's own app — and until 2026-09-26 this path, the one every
    # bracket-protected exit takes, told nobody: the bell and Telegram
    # heard first-attempt closes and retried closes only. Same notifier,
    # same preference, same quiet hours; after grading, so the words are
    # the graded outcome's.
    try:
        from bot_program.notifications import notify_bot_fill_close
        notify_bot_fill_close(
            trade.config.user, asset_class=trade.asset_class,
            symbol=trade.symbol, side=trade.side, qty=trade.qty,
            exit_price=trade.exit_price, pnl=trade.pnl,
            outcome=trade.outcome or "", trade_id=trade.id,
        )
    except Exception as e:  # noqa: BLE001 — a bell never blocks a close
        logger.warning("reconcile: close notification failed for #%s: %s",
                       trade.id, e)
    # A row reconciled as an orphan may still have its OTHER leg resting:
    # a stop that filled leaves the target behind (and vice versa) unless
    # the broker's OCA pair cancelled it. A resting exit against a flat
    # book opens a position rather than closing one.
    ids = (trade.metadata or {}).get("protective_order_ids") or []
    for oid in ids:
        # Its own client lookup: the one above lives inside a try that a
        # dead ticker call can leave unbound, and a leg left resting is
        # not a detail to skip on the way past.
        try:
            leg_client = client_for_symbol(trade.config.user, trade.symbol,
                                           trade.config)
            cancel = getattr(leg_client, "cancel_order", None)
            if callable(cancel):
                cancel(oid)
        except Exception as e:  # noqa: BLE001
            logger.warning("reconcile: leg %s for #%s may still rest at "
                           "the broker (%s)", oid, trade.id, e)

    # Every broker-side bracket exit (all stock and forex stops) is
    # finalised HERE — and none of them reached the dashboards live.
    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(trade.config.user, "fill_close", {
            "trade_id": trade.id, "asset_class": trade.asset_class,
            "symbol": trade.symbol, "side": trade.side,
            "outcome": trade.outcome or "",
            "pnl": str(trade.pnl) if trade.pnl is not None else "0",
        })
    except Exception as e:
        logger.warning("reconcile: eye push failed for #%s: %s",
                       trade.id, e)


def reconcile_unknown_positions(user) -> dict:
    """Positions the BROKER holds that no AssetBotTrade row claims.

    Reconciliation has only ever walked rows and asked the broker about
    each one. The other direction was never swept, so a position the broker
    holds that no row claims is invisible platform-wide: uncounted by every
    exposure and daily-loss gate, carrying no bot-side stop, and untouched
    by the kill switch — whose "flatten everything" iterates AssetBotTrade
    rows and never once asks the broker whether it is actually flat.

    The entry path manufactures exactly this state. If `market_order`
    reaches the broker but the response is lost — a read timeout on
    Alpaca's POST, a socket drop during _await_fill, a TWS disconnect after
    placeOrder — base.py logs and returns None, writing no row. The units
    are real and nothing here knows.

    REPORTS, never closes. The operator may have opened the position by
    hand at the broker, and an automated system that flattens what it does
    not recognise is worse than one that says so. This is the same posture
    the circuit breakers take.

    Returns {checked, unclaimed, broker_unavailable, errors, symbols}.
    """
    from .models import AssetBotConfig, AssetBotTrade
    from .engine.broker_router import client_for_symbol

    out = {"checked": 0, "unclaimed": 0, "broker_unavailable": 0,
           "errors": 0, "symbols": []}

    # Every symbol this user's rows currently claim, in one query. Options
    # are claimed under their OCC symbol, which is what the broker reports.
    claimed = set()
    from .asset_engine.base import is_entry_working
    for row in (AssetBotTrade.objects
                .filter(config__user=user,
                        status__in=("OPEN", "CLOSE_PENDING"), paper=False)
                .only("symbol", "metadata")):
        # A WORKING row claims a symbol it holds NOTHING of: its order is
        # still queued. Counting it here would mask the very position that
        # order creates when it fills — the sweep exists to find units no
        # row accounts for, and an unfilled order accounts for none.
        if row.symbol and not is_entry_working(row):
            claimed.add(str(row.symbol).upper())
    # A ROW CLOSED SECONDS AGO STILL CLAIMS ITS SYMBOL HERE (the lag; see
    # SWEEP_CLOSED_GRACE_S). Report-only, every venue.
    from datetime import timedelta as _td
    for row in (AssetBotTrade.objects
                .filter(config__user=user, status="CLOSED", paper=False,
                        closed_at__gte=timezone.now()
                        - _td(seconds=SWEEP_CLOSED_GRACE_S))
                .only("symbol")):
        if row.symbol:
            claimed.add(str(row.symbol).upper())

    configs = (AssetBotConfig.objects
               .filter(user=user, enabled=True)
               .exclude(mode="paper"))
    seen_clients = set()
    for cfg in configs:
        symbols = list(cfg.symbols or [])
        if not symbols:
            continue
        try:
            client = client_for_symbol(user, symbols[0], cfg)
        except Exception as e:  # noqa: BLE001 — one venue must not stop the rest
            logger.warning("unknown-position sweep: no client for %s: %s",
                           cfg.name, e)
            out["errors"] += 1
            continue

        venue = type(client).__name__
        # One read per venue, not per config: several configs routinely
        # route to the same broker.
        key = (cfg.asset_class, venue)
        if key in seen_clients:
            continue
        seen_clients.add(key)
        out["checked"] += 1

        state = _broker_open_symbols(client, asset_class=cfg.asset_class,
                                     warm=symbols)
        if state is None:
            # UNREADABLE is not EMPTY. Treating an unreachable broker as
            # "no positions" would report a clean sweep of a book nobody
            # could see, which is the reassuring answer.
            out["broker_unavailable"] += 1
            logger.warning("unknown-position sweep: %s state unreadable — "
                           "not reporting a clean sweep of a book nobody "
                           "could read", venue)
            continue

        if state.get("unnamed"):
            # UNNAMED IS NOT UNCLAIMED. A position this client could not name
            # cannot be compared to any row, and reporting it as
            # "ETORO:1001 is unclaimed" hands a human a name they cannot look
            # up — which is how the one true alarm stops being believed. The
            # named part of the book is still compared below: part measured,
            # part not, which is the honest shape.
            out["broker_unavailable"] += 1
            logger.error("unknown-position sweep: %s holds %d position(s) it "
                         "could not name — that part of the book is "
                         "unreadable, not clean", venue, state["unnamed"])

        held = {str(x).upper() for x in (state.get("symbols") or set())}
        unclaimed = sorted(held - claimed)
        if not unclaimed:
            continue

        out["unclaimed"] += len(unclaimed)
        out["symbols"].extend(unclaimed)
        logger.error("unknown-position sweep: %s holds %d position(s) no "
                     "row claims: %s", venue, len(unclaimed),
                     ", ".join(unclaimed[:8]))
        try:
            from bot_program.notifications import notify_unclaimed_position
            notify_unclaimed_position(user, symbols=unclaimed, venue=venue)
        except Exception as e:  # noqa: BLE001
            logger.warning("unknown-position sweep: alert failed: %s", e)
            out["errors"] += 1

    # THE ACCOUNT IS AN ENTRY POINT TOO, not just the config list. The
    # loop above only builds a client when an enabled non-paper config
    # with a NON-EMPTY symbol list routes to one — and TAKE TRADE's
    # "manual" configs carry empty symbol lists by construction. So a
    # funded ISA holding hand-bought stock, with no bot armed on it,
    # got ZERO sweeps and this function returned a confident
    # {unclaimed: 0} from a book nobody read — the signature failure,
    # in the sweep that exists to catch it. An interfaced IBKR account
    # is swept whether or not any config routes there.
    from .capital_truth import broker_backed, broker_kind
    # EVERY KEYED ROW, not only the book. Keyed is tested on the column the
    # way tasks._users_with_a_broker_row tests it — no decryption, and an
    # unkeyed row carries nothing to ask.
    _book = broker_backed(user)
    _rows = [r for r in (getattr(user, "saxo_account", None),
                         getattr(user, "etoro_account", None),
                         getattr(user, "ibkr_account", None))
             if r is not None and (getattr(r, "app_key_enc", "")
                                   or getattr(r, "api_key_enc", "")
                                   or getattr(r, "account_id_enc", ""))]
    # The book first: an error later in the walk must not cost it its pass.
    _rows.sort(key=lambda r: 0 if (_book is not None
                                   and type(r) is type(_book)
                                   and r.pk == _book.pk) else 1)

    for acct in _rows:
        _kind = None if acct is None else broker_kind(acct)
        _CLASS = {"saxo": "SaxoTrader", "etoro": "EtoroTrader",
                  "ibkr": "IBKRTrader"}
        venue_name = {"saxo": "Saxo", "etoro": "eToro",
                      "ibkr": "IBKR"}.get(_kind, "broker")
        # IBKR keeps its old skip: without the library there is nothing to
        # ask, and counting that as an error would change what every existing
        # caller and test sees.
        _skip = False
        if _kind == "ibkr":
            from .engine.ibkr_client import is_ibkr_available
            _skip = not is_ibkr_available()

        # A row that cannot be asked is skipped, not counted clean.
        if not _skip:
            # Not swept already by the config loop above, whichever adapter
            # this book speaks through.
            if _CLASS.get(_kind, "IBKRTrader") not in {v for (_cls, v)
                                                       in seen_clients}:
                    client = None
                    try:
                        if _kind == "saxo":
                            # Read from the ROW: no session slot, no clientId,
                            # no host or port. The IBKR branch below could only
                            # ever raise AttributeError on a Saxo book and
                            # count the broker unavailable — so this sweep was
                            # blind on the two newest venues.
                            from .engine.saxo_client import SaxoTrader
                            if not acct.session_alive():
                                raise RuntimeError(
                                    "no live Saxo session — sign in again at "
                                    "/brokers/")
                            client = SaxoTrader(acct)
                        elif _kind == "etoro":
                            from .engine.etoro_client import EtoroTrader
                            k, u = acct.get_credentials()
                            if not (k and u):
                                raise RuntimeError("no eToro keys on the book")
                            client = EtoroTrader(
                                k, u, env="demo" if acct.demo else "live")
                        else:
                            # The probe id, never the trade id — IBKR refuses a
                            # second connection on a held clientId (error 326),
                            # so a sweep on the trading id would fail against
                            # the trader or hold the id against it. The session
                            # comes from ibkr_sessions on this process's own
                            # slot; disconnecting below closes the socket and
                            # keeps the slot for the next pass.
                            from .engine.ibkr_sessions import acquire_trader
                            client = acquire_trader(
                                acct.host, acct.port, acct.client_id, "probe",
                                account_id=acct.get_account_id() or "",
                                paper=bool(acct.paper))
                            if client is None:
                                raise RuntimeError("no free IBKR clientId slot")
                        out["checked"] += 1
                        state = _broker_open_symbols(client,
                                                     asset_class="stock")
                    except Exception as e:  # noqa: BLE001
                        logger.warning("unknown-position sweep: account-entry "
                                       "%s read failed: %s", venue_name, e)
                        state = None
                        out["errors"] += 1
                    finally:
                        disconnect = getattr(client, "disconnect", None)
                        if callable(disconnect):
                            try:
                                disconnect()
                            except Exception:  # noqa: BLE001
                                pass
                    if state is None:
                        out["broker_unavailable"] += 1
                        logger.warning("unknown-position sweep: %s account "
                                       "%s unreadable — not reporting a clean "
                                       "sweep of a book nobody could read",
                                       venue_name, acct.label)
                    else:
                        held = {str(x).upper()
                                for x in (state.get("symbols") or set())}
                        unclaimed = sorted(held - claimed)
                        if unclaimed:
                            out["unclaimed"] += len(unclaimed)
                            out["symbols"].extend(unclaimed)
                            logger.error(
                                "unknown-position sweep: %s %s holds %d "
                                "position(s) no row claims: %s", venue_name,
                                acct.label, len(unclaimed),
                                ", ".join(unclaimed[:8]))
                            try:
                                from bot_program.notifications import (
                                    notify_unclaimed_position)
                                notify_unclaimed_position(
                                    user, symbols=unclaimed,
                                    venue=f"{venue_name} {acct.label}")
                            except Exception as e:  # noqa: BLE001
                                logger.warning("unknown-position sweep: alert "
                                               "failed: %s", e)
                                out["errors"] += 1

    return out


def reconcile_all_users() -> dict:
    """Walk every user with at least one open live AssetBotTrade."""
    from django.contrib.auth.models import User
    from .models import AssetBotTrade

    from .models import AssetBotConfig

    # Users with open ROWS, plus users with a live CONFIG. The second set
    # is the point of the unknown-position sweep: a user whose only broker
    # position is one no row claims has no open rows at all, so the
    # row-driven query would skip them entirely — which is precisely the
    # case that sweep exists to find.
    user_ids = set(
        AssetBotTrade.objects
        .filter(status__in=("OPEN", "CLOSE_PENDING"), paper=False)
        .values_list("config__user_id", flat=True))
    user_ids |= set(AssetBotConfig.objects
                    .filter(enabled=True).exclude(mode="paper")
                    .values_list("user_id", flat=True))
    # And users with an INTERFACED BROKER ACCOUNT, config or no config.
    # The two sets above both enter from Sauron's side of the ledger, so
    # an operator whose ISA holds hand-bought stock but who has armed no
    # bot was never selected at all — the same blind spot the account
    # entry inside reconcile_unknown_positions closes, one level up.
    # Every keyed broker, not only IBKR: a Saxo-only operator with no
    # armed config was not selected at all, which is the same blind spot
    # this union was added to close.
    from .tasks import _users_with_a_broker_row
    user_ids |= set(_users_with_a_broker_row().values_list("id", flat=True))
    user_ids = sorted(uid for uid in user_ids if uid)
    totals = {"users": 0, "checked": 0, "closed_as_orphan": 0,
               "broker_unavailable": 0, "errors": 0,
               "unclaimed": 0}
    for uid in user_ids:
        try:
            u = User.objects.get(id=uid)
        except User.DoesNotExist:
            continue
        try:
            r = reconcile_user(u)
            totals["users"] += 1
            for k in ("checked", "closed_as_orphan",
                       "broker_unavailable", "errors"):
                totals[k] += r.get(k, 0)
        except Exception as e:
            logger.warning("reconcile_all_users: user=%s failed: %s", uid, e)
            totals["errors"] += 1

        # The other direction. Separately guarded: a failure here must not
        # cost the row-driven reconciliation that already succeeded.
        try:
            u2 = reconcile_unknown_positions(u)
            totals["unclaimed"] += u2.get("unclaimed", 0)
            totals["broker_unavailable"] += u2.get("broker_unavailable", 0)
            totals["errors"] += u2.get("errors", 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("unknown-position sweep: user=%s failed: %s",
                           uid, e)
            totals["errors"] += 1
    return totals
