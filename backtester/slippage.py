"""Realistic fill price model for backtests."""


def realistic_fill_price(signal_price: float, side: str, qty: float,
                         spread_bps: float = 5.0,
                         impact_bps: float = 5.0,
                         avg_volume: float = 1_000_000.0) -> float:
    """Apply spread + size-dependent impact to a signal-time price.

    BUY pays half-spread + impact above mid; SELL receives half-spread - impact
    below mid. Impact scales with qty/avg_volume ratio.
    """
    half_spread = spread_bps / 2 / 10_000
    impact = impact_bps / 10_000 * min(1.0, qty / max(avg_volume, 1.0))
    if side == "BUY":
        return signal_price * (1 + half_spread + impact)
    return signal_price * (1 - half_spread - impact)


def funding_payment(notional: float, funding_rate: float, hours_held: float) -> float:
    """Funding payment for a perpetual position over a holding period.

    funding_rate: per-8-hour rate (Binance convention)
    Positive funding = longs pay shorts.
    """
    intervals = hours_held / 8.0
    return notional * funding_rate * intervals
