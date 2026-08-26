"""Stop management for open positions — break-even and trailing.

Every rule here obeys the same two invariants, and they are the whole
reason this module is small:

  1. A stop only ever TIGHTENS. Loosening one converts a defined loss
     into an open-ended one, which is the single worst thing an
     automated exit can do.
  2. R is measured against the stop the trade was OPENED with —
     `metadata["initial_stop_loss"]`, frozen at entry — never against
     the current one. Measuring against a stop these rules just moved
     makes risk and reward the same quantity, so every managed winner
     scores ~1R and the track record stops meaning anything.
     `bot_grading` freezes it for exactly this reason.

A third rule earns its place from a live trade: a stop is never placed
on the wrong side of the current price. A break-even stop that lands
past the mark closes the position at market on the next tick and books
it as a stop-out, which reads in the history as a loss the thesis never
took.
"""
from decimal import Decimal


def _dec(v):
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001 — a bad knob means "rule off"
        return None


def initial_risk_per_unit(trade):
    """|entry - the stop this trade OPENED with|, or None.

    None when the trade carries no frozen stop: without it there is no
    denominator, and guessing one from the current stop is how every
    managed exit ends up scoring 1R.

    A None here silently disables both rules for the life of the trade,
    so the caller that has a logger says so — an operator who configured
    break-even and watches nothing happen is owed the reason.
    """
    entry = _dec(getattr(trade, "entry_price", None))
    frozen = (getattr(trade, "metadata", None) or {}).get("initial_stop_loss")
    stop = _dec(frozen)
    if entry is None or stop is None:
        return None
    risk = abs(entry - stop)
    return risk if risk > 0 else None


def unrealised_r(trade, price):
    """How far the trade has run, in units of its ORIGINAL risk.

    Positive is profit for both sides. None when it cannot be measured,
    and every caller must treat that as "do not act" rather than "zero".
    """
    entry = _dec(getattr(trade, "entry_price", None))
    px = _dec(price)
    risk = initial_risk_per_unit(trade)
    if entry is None or px is None or risk is None:
        return None
    move = (px - entry) if getattr(trade, "side", "") == "BUY" else (entry - px)
    return move / risk


def _tighter(trade, candidate, current):
    """True when `candidate` is a tighter stop than `current`."""
    if current is None:
        return True
    return candidate > current if trade.side == "BUY" else candidate < current


def _on_the_right_side(trade, candidate, price):
    """A stop must sit BELOW the mark on a long, ABOVE it on a short.

    Placing one past the mark closes the position at market on the next
    tick and books it as a stop-out — a loss the thesis never took.
    """
    return candidate < price if trade.side == "BUY" else candidate > price


def _commit(trade, candidate, price, note):
    """Persist a stop move, or return False if it fails either guard.

    `metadata` is a JSON column that several tasks write. Rewriting it
    wholesale from an instance loaded at the start of a tick puts back
    the pre-tick value of every key this function did not set — which
    on this row includes `protected` and `protective_order_ids`, the two
    flags that decide whether anything manages the position at all. Re-
    read immediately before merging so the blob written is the current
    one. Best effort: a trade object that cannot be refreshed (the pure
    unit tests pass a stub) just proceeds with what it holds.
    """
    try:
        trade.refresh_from_db(fields=["stop_loss", "metadata"])
    except Exception:  # noqa: BLE001 - a stub or an unsaved row
        pass
    current = _dec(getattr(trade, "stop_loss", None))
    if not _tighter(trade, candidate, current):
        return False
    if not _on_the_right_side(trade, candidate, price):
        return False
    trade.stop_loss = candidate
    meta = dict(getattr(trade, "metadata", None) or {})
    moves = list(meta.get("stop_moves") or [])
    # Bounded: this is a per-tick path and the row is read by the UI.
    moves.append({"to": str(candidate), "at": str(price), "why": note})
    meta["stop_moves"] = moves[-20:]
    trade.metadata = meta
    trade.save(update_fields=["stop_loss", "metadata"])
    return True


def apply_breakeven(trade, current_price, at_r, buffer_r=0.0):
    """Move the stop to entry once the trade has run `at_r` in profit.

    The buffer is in R and defaults to nothing. A stop exactly AT entry
    is not break-even in practice: the spread crossed on the way in and
    the commission on both legs still have to come out of it, so a
    position stopped "at break-even" books a small loss. A buffer of
    even 0.05R puts the exit on the right side of its own costs.

    Fires once — the trailing rule owns the stop from there, and
    re-running this would drag a trailed stop BACK toward entry.
    """
    if at_r is None or at_r <= 0:
        return False
    r_now = unrealised_r(trade, current_price)
    if r_now is None or r_now < Decimal(str(at_r)):
        return False
    meta = getattr(trade, "metadata", None) or {}
    if meta.get("breakeven_armed"):
        return False

    entry = _dec(trade.entry_price)
    risk = initial_risk_per_unit(trade)
    price = _dec(current_price)
    if entry is None or risk is None or price is None:
        return False

    offset = risk * Decimal(str(buffer_r or 0))
    candidate = entry + offset if trade.side == "BUY" else entry - offset

    if not _commit(trade, candidate, price, "breakeven"):
        return False
    # Stamped only on success, so a refused move is retried next tick
    # rather than silently disarming the rule for the life of the trade.
    meta = dict(trade.metadata or {})
    meta["breakeven_armed"] = True
    trade.metadata = meta
    trade.save(update_fields=["metadata"])
    return True


def update_trailing_stop(trade, current_price, trail_pct, start_r=0.0):
    """Ratchet the stop toward price. Returns True if it moved.

    `start_r` delays the ratchet until the trade has actually run:
    trailing from the first tick in profit converts a position that has
    barely moved into a scratch on the first pullback, which is the
    complaint that usually follows switching trailing on.
    """
    if trail_pct is None or trail_pct <= 0:
        return False
    price = _dec(current_price)
    if price is None or price <= 0:
        return False

    # In profit FIRST, always. A trailing stop is a way of keeping part
    # of a move; on a trade that is DOWN it is just a tighter stop
    # arriving early, and with a small trail_pct the candidate really
    # can land above a losing long's stop (entry 100, stop 98, mark 99,
    # trail 0.5% -> 98.505 is "tighter" and would be accepted). The
    # engine used to hold this gate and the rewrite dropped it.
    entry = _dec(getattr(trade, "entry_price", None))
    if entry is None:
        return False
    in_profit = price > entry if trade.side == "BUY" else price < entry
    if not in_profit:
        return False

    # start_r is the SECOND gate, not a replacement: it delays the
    # ratchet until the move is worth locking in.
    if start_r and start_r > 0:
        r_now = unrealised_r(trade, price)
        if r_now is None or r_now < Decimal(str(start_r)):
            return False

    trail = Decimal(str(trail_pct)) / Decimal("100")
    candidate = (price * (Decimal("1") - trail) if trade.side == "BUY"
                 else price * (Decimal("1") + trail))
    return _commit(trade, candidate, price, "trail")
