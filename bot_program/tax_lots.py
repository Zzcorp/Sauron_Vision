"""Phase-27 tax-lot bookkeeping service.

Three public functions:
  open_lot(trade)        — called when a long position opens; creates a TaxLot
  close_lots_for(trade)  — called when a long position closes; consumes lots in
                            user's chosen FIFO/LIFO/HIFO order
  lot_method_for(user)   — read TraderProfile.tax_lot_method (default FIFO)

All hooks are no-ops for SELL-side opens (short trades — different tax rules,
out of scope for v1) and for trades missing data (safe degrade).
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def lot_method_for(user) -> str:
    """Return the user's preferred lot-consumption order. Default FIFO."""
    try:
        m = getattr(user.trader_profile, "tax_lot_method", "FIFO")
        return m if m in ("FIFO", "LIFO", "HIFO") else "FIFO"
    except Exception:
        return "FIFO"


def _multiplier(trade) -> int:
    """Options/futures contract multiplier; default 1."""
    if trade.asset_class == "options":
        try:
            m = (trade.metadata or {}).get("multiplier", 100)
            return int(m) if m else 100
        except Exception:
            return 100
    return 1


def open_lot(trade):
    """Open one TaxLot per BUY-side trade. Returns the lot or None."""
    if not trade or trade.side != "BUY":
        return None
    if trade.qty is None or trade.entry_price is None:
        return None
    if trade.config is None or trade.opened_at is None:
        return None
    try:
        from .tax_lot_models import TaxLot
        return TaxLot.objects.create(
            user=trade.config.user,
            asset_class=trade.asset_class or "",
            symbol=trade.symbol or "",
            qty_initial=trade.qty,
            qty_remaining=trade.qty,
            cost_basis_per_unit=trade.entry_price,
            multiplier=_multiplier(trade),
            opened_at=trade.opened_at,
            source_trade=trade,
            method_at_open=lot_method_for(trade.config.user),
            paper=bool(trade.paper),
        )
    except Exception as e:
        logger.warning("tax_lots.open_lot failed: %s", e)
        return None


def close_lots_for(trade):
    """Consume open lots when a long position closes.

    Walks the user's open lots for (symbol, asset_class, paper-mode) in their
    preferred order and creates one `TaxLotConsumption` per slice. Updates
    `qty_remaining` on each lot, sets `closed_at` when fully consumed.

    Returns the list of consumptions created (possibly empty).
    """
    if not trade or trade.side != "BUY":
        return []
    if trade.exit_price is None or trade.qty is None or trade.closed_at is None:
        return []
    if trade.config is None:
        return []

    try:
        from .tax_lot_models import TaxLot, TaxLotConsumption

        method = lot_method_for(trade.config.user)
        qs = TaxLot.objects.filter(
            user=trade.config.user, symbol=trade.symbol,
            asset_class=trade.asset_class, paper=bool(trade.paper),
            qty_remaining__gt=Decimal("0"),
        )
        if method == "LIFO":
            qs = qs.order_by("-opened_at")
        elif method == "HIFO":
            qs = qs.order_by("-cost_basis_per_unit", "opened_at")
        else:  # FIFO default
            qs = qs.order_by("opened_at")

        qty_to_consume = Decimal(str(trade.qty))
        sale_price = Decimal(str(trade.exit_price))
        consumptions = []
        for lot in list(qs):
            if qty_to_consume <= 0:
                break
            take = min(qty_to_consume, Decimal(str(lot.qty_remaining)))
            if take <= 0:
                continue
            mult = Decimal(str(lot.multiplier or 1))
            gain_per_unit = (sale_price - Decimal(str(lot.cost_basis_per_unit))) * mult
            realized_gain = gain_per_unit * take
            holding_days = max(0, (trade.closed_at - lot.opened_at).days)
            cons = TaxLotConsumption.objects.create(
                lot=lot, consuming_trade=trade,
                qty_consumed=take, sale_price_per_unit=sale_price,
                sold_at=trade.closed_at,
                realized_gain=realized_gain.quantize(Decimal("0.0001")),
                holding_period_days=holding_days,
                long_term=(holding_days >= 365),
            )
            consumptions.append(cons)

            lot.qty_remaining = Decimal(str(lot.qty_remaining)) - take
            update_fields = ["qty_remaining"]
            if lot.qty_remaining <= 0:
                lot.qty_remaining = Decimal("0")
                lot.closed_at = trade.closed_at
                update_fields.append("closed_at")
            lot.save(update_fields=update_fields)
            qty_to_consume -= take
        return consumptions
    except Exception as e:
        logger.warning("tax_lots.close_lots_for failed: %s", e)
        return []
