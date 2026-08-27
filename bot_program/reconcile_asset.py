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


def _broker_open_symbols(client, *, asset_class: str) -> dict:
    """Best-effort broker open-position state.

    Returns None if the broker doesn't expose enough state (we won't
    reconcile in that case rather than guess wrong), else a dict:

      symbols          — every symbol the broker reports open. Alpaca
                         reports options under their OCC symbol here.
      opt_underlyings  — underlyings of positions explicitly typed OPT
                         (IBKR provides sec_type per position).
      has_sec_types    — True when the client annotates security types,
                         i.e. opt_underlyings is a meaningful signal.
    """
    # Alpaca exposes /v2/positions; OANDA via /v3/accounts/.../openPositions;
    # IBKR via positions(); Binance via positionRisk. The exact API varies —
    # we use a duck-typed `get_positions()` if present, else None.
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
    for p in positions:
        if isinstance(p, dict):
            sym, sec = p.get("symbol"), p.get("sec_type")
        else:
            sym, sec = getattr(p, "symbol", None), getattr(p, "sec_type", None)
        if not sym:
            continue
        sym = str(sym).upper()
        symbols.add(sym)
        if sec is not None:
            has_sec_types = True
            if str(sec).upper() == "OPT":
                opt_underlyings.add(sym)
    return {"symbols": symbols, "opt_underlyings": opt_underlyings,
            "has_sec_types": has_sec_types}


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

    qs = (AssetBotTrade.objects
          .filter(config__user=user, status__in=("OPEN", "CLOSE_PENDING"), paper=False)
          .select_related("config"))
    out = {"checked": 0, "closed_as_orphan": 0,
           "broker_unavailable": 0, "errors": 0}

    # Cache broker open-symbol sets per (asset_class, broker_name) — many
    # trades share the same broker, no need to query per row.
    cache: dict = {}

    for trade in qs:
        out["checked"] += 1
        try:
            client = client_for_symbol(user, trade.symbol, trade.config)
            cache_key = (trade.asset_class, type(client).__name__)
            if cache_key not in cache:
                cache[cache_key] = _broker_open_symbols(
                    client, asset_class=trade.asset_class)
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
    from .pending_closes import EXIT_FILL_SOURCE_KEY, EXIT_SOURCE_MARK
    from market_data.models import LiveQuote

    exit_price = trade.entry_price
    priced = False           # did anything but the entry price answer?
    if trade.asset_class == "options":
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
    meta["exit_price_inferred"] = True
    if not priced:
        # Nothing anywhere could price this exit, so the number booked above
        # is the ENTRY price and the P&L is a fabricated zero. The row still
        # closes — an orphan left open forever is its own failure — but it
        # is marked, and `realized_since` excludes a marked row from the
        # daily-loss sum instead of counting a real loss as a scratch.
        meta[UNPRICED_EXIT_KEY] = True
        logger.error("reconcile: #%s %s closed with NO price available — "
                     "booked at entry and flagged UNMEASURED, not flat",
                     trade.id, trade.symbol)
    # A CLOSE_PENDING row arrives here carrying `exit_fill_source: broker`
    # from the partial close that stranded it. The price booked just above is
    # NOT that fill — it is a ticker read taken now, for the whole quantity —
    # so leaving the old value would put two contradictory provenance flags on
    # one closed row and let a reader treat an estimate as a measurement.
    # `mark` is what the exit vocabulary calls a price we had to assume.
    meta[EXIT_FILL_SOURCE_KEY] = EXIT_SOURCE_MARK
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


def reconcile_all_users() -> dict:
    """Walk every user with at least one open live AssetBotTrade."""
    from django.contrib.auth.models import User
    from .models import AssetBotTrade

    user_ids = sorted(set(
        AssetBotTrade.objects
        .filter(status__in=("OPEN", "CLOSE_PENDING"), paper=False)
        .values_list("config__user_id", flat=True)
    ))
    totals = {"users": 0, "checked": 0, "closed_as_orphan": 0,
               "broker_unavailable": 0, "errors": 0}
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
    return totals
