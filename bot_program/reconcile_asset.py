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


def _close_as_orphan(trade) -> None:
    """Mark an orphan trade CLOSED at last-known price."""
    # Best-effort exit price: use the broker's ticker, or fall back to
    # the trade's entry price (zero P&L) so we at least clear the row.
    from .engine.broker_router import client_for_symbol
    from market_data.models import LiveQuote

    exit_price = trade.entry_price
    if trade.asset_class == "options":
        # trade.symbol is the UNDERLYING — its ticker/LiveQuote is the wrong
        # scale for a premium-denominated trade. Mark at the option's own
        # premium, or entry (zero P&L) when unknown.
        try:
            from bot_program.asset_engine.options_bot import current_premium_for_trade
            exit_price = current_premium_for_trade(trade) or trade.entry_price
        except Exception:
            pass
    else:
        try:
            client = client_for_symbol(trade.config.user, trade.symbol, trade.config)
            tk = client.ticker(trade.symbol) or {}
            last = float(tk.get("lastPrice", 0) or 0)
            if last > 0:
                exit_price = Decimal(str(last))
        except Exception:
            try:
                from instruments.models import Instrument
                inst = Instrument.objects.filter(symbol=trade.symbol).first()
                if inst:
                    lq = LiveQuote.objects.filter(instrument=inst).first()
                    if lq and lq.last:
                        exit_price = lq.last
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

    trade.exit_price = exit_price
    trade.pnl = pnl
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.outcome = "manual_close"
    trade.reason = (trade.reason + " | reconciled-orphan").strip()
    trade.save(update_fields=["exit_price", "pnl", "status", "closed_at",
                                "outcome", "reason"])


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
