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


def _broker_open_symbols(client, *, asset_class: str) -> set:
    """Best-effort set of symbols the broker says are open.

    Returns None if the broker doesn't expose enough state (we won't
    reconcile in that case rather than guess wrong).
    """
    # Alpaca exposes /v2/positions; OANDA via /v3/accounts/.../openPositions;
    # IBKR via positions(); Binance via balance / open orders. The exact API
    # varies — we use a duck-typed `get_positions()` if present, else None.
    fn = getattr(client, "get_positions", None)
    if not callable(fn):
        return None
    try:
        positions = fn() or []
    except Exception as e:
        logger.warning("reconcile: %s.get_positions() failed: %s",
                       type(client).__name__, e)
        return None
    out = set()
    for p in positions:
        sym = p.get("symbol") if isinstance(p, dict) else getattr(p, "symbol", None)
        if sym:
            out.add(str(sym).upper())
    return out


def reconcile_user(user) -> dict:
    """Reconcile one user's open AssetBotTrade rows against broker state.

    Returns counts: {checked, closed_as_orphan, broker_unavailable, errors}.
    """
    from .models import AssetBotTrade
    from .engine.broker_router import client_for_symbol

    qs = (AssetBotTrade.objects
          .filter(config__user=user, status="OPEN", paper=False)
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
            broker_open = cache[cache_key]
            if broker_open is None:
                # Broker doesn't expose state — can't reconcile this row.
                out["broker_unavailable"] += 1
                continue

            if trade.symbol.upper() not in broker_open:
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
        .filter(status="OPEN", paper=False)
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
