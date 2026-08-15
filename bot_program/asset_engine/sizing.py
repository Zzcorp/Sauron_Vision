"""Risk-denominated position sizing.

The old rule was `qty = capital * position_size_pct / price` — fixed
NOTIONAL. It never read the stop, and structurally it could not: qty was
final twenty-one lines before `stop_and_target()` was called.

That is not a matter of taste. With $10,000 at 2% and AAPL at $200 you buy
one share either way, but a 0.3% ATR stop risks $0.60 and a 3% stop risks
$6.00. `risk_levels` sanctions stop fractions from 0.2% to 25%, so the
achievable risk band is 125x wide, decided by nothing but what ATR happened
to be that morning.

The consequence reaches further than the risk itself. `bot_grading` computes

    realized_r = pnl / (|entry - initial_stop| * qty)

so one trade's "1R" is $0.60 and another's is $6.00, and both are written to
the same column as if they were the same unit. The mean of `realized_r` is
therefore not an expectancy and never becomes one however many trades are
collected — it averages inches and pounds. Every downstream consumer reads
that number: `kelly_from_history`, the meta-allocator's expectancy lane,
`weighted_consensus`, and every promotion threshold.

So sizing by risk is not an alternative to Kelly or to expectancy weighting.
It is the precondition for them: it is what makes 1R mean one thing.

    qty = f * equity / |entry - stop|

`f` defaults to 0.25% of equity. That number comes from the payoff geometry
the config already fixes (a 1.5 ATR stop against a 3.0 ATR target, so
sigma ~ 1.45R per trade), not from any estimate of edge — which is
unavailable and will be for months. It answers: how small must f be so that
a system with ZERO edge does not destroy the account during the several
hundred trades it takes to find out? At 0.25% the 95th-percentile drawdown
over the first 200 trades is roughly 11%. At 1.00% it is 43% — past the
point at which anyone keeps the system switched on.

It also makes the existing safety defaults cohere for the first time:
`max_daily_loss_pct = 2.0` becomes exactly 8R, and the 10% drawdown breaker
exactly 40R. Under notional sizing the number of losses needed to trip the
daily limit was somewhere between 3 and 3,300.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Fraction of equity risked per trade, and the ceiling nothing may exceed.
DEFAULT_RISK_FRACTION = 0.0025   # 0.25%
MAX_RISK_FRACTION = 0.010        # 1.0% — a hard cap, not a target

# Risk sizing fixes the denominator and unbounds the numerator:
# notional = equity * f / stop_fraction. At f=0.25% and the 0.2% stop floor
# that is 125% of equity in a single position, which notional sizing could
# never produce. This is the standard way a "risk-based sizing" rewrite ends
# up losing more money than the naive rule it replaced.
#
# The obvious guard — clamp qty to a notional ceiling — is wrong, because it
# makes realised risk min(f, cap * stop_fraction), which is stop-dependent
# again and biased: it binds precisely on the low-volatility instruments. It
# would reintroduce the incomparable-denominator problem, systematically
# rather than randomly.
#
# So we widen the STOP to a floor instead. Risk stays exactly f, notional
# stays legal, and 1R keeps meaning one thing on every trade.
MAX_NOTIONAL_FRACTION = {
    "stock": 0.20,
    "etf": 0.20,
    "index": 0.20,
    "commodity": 0.20,
    "crypto": 0.20,
    "options": 0.20,
    # 20% notional on an FX major is an economically meaningless constraint —
    # the leverage is at the broker, and a 0.06% stop floor never binds.
    "forex": 4.0,
}
DEFAULT_MAX_NOTIONAL_FRACTION = 0.20


def _extras(cfg) -> dict:
    return getattr(cfg, "extras", None) or {}


def _extras_float(cfg, key: str, default: float) -> float:
    """extras is hand-edited JSON; a typo must not raise into the entry path."""
    raw = _extras(cfg).get(key, default)
    try:
        return float(raw if raw is not None else default)
    except (TypeError, ValueError):
        logger.warning("[sizing] cfg %s: extras[%r]=%r is not numeric — "
                       "using %s", getattr(cfg, "id", "?"), key, raw, default)
        return float(default)


def risk_fraction(cfg) -> float:
    """The fraction of equity to put at risk on one trade.

    Override per config with extras['risk_per_trade_pct'] (in percent, so
    0.25 means 0.25%). Always clamped to MAX_RISK_FRACTION — no config value
    and no multiplier may exceed it.
    """
    pct = _extras(cfg).get("risk_per_trade_pct")
    if pct is None:
        f = DEFAULT_RISK_FRACTION
    else:
        f = _extras_float(cfg, "risk_per_trade_pct", DEFAULT_RISK_FRACTION * 100.0) / 100.0
    if f <= 0:
        return 0.0
    return min(f, MAX_RISK_FRACTION)


def max_notional_fraction(cfg, asset_class: str) -> float:
    override = _extras(cfg).get("max_notional_fraction")
    if override is not None:
        val = _extras_float(cfg, "max_notional_fraction",
                            DEFAULT_MAX_NOTIONAL_FRACTION)
        if val > 0:
            return val
    return MAX_NOTIONAL_FRACTION.get(asset_class, DEFAULT_MAX_NOTIONAL_FRACTION)


def min_stop_fraction(cfg, asset_class: str, f: float) -> float:
    """The stop distance below which sizing would breach the notional cap."""
    cap = max_notional_fraction(cfg, asset_class)
    if cap <= 0:
        return 0.0
    return f / cap


def apply_stop_floor(cfg, asset_class: str, entry: float, stop: float,
                     direction: str, f: float) -> tuple:
    """Resolve a stop so tight that sizing to `f` would breach the notional cap.

    Returns (stop, widened, skip). Two honest resolutions, and the choice is
    a real trade-off rather than an implementation detail:

      widen (default)  Keep the risk budget exact and place a wider stop.
                       Trades keep flowing and every 1R stays comparable, but
                       the trade taken is not quite the trade the rule
                       designed — a 0.3% ATR stop becomes 1.25%, which is a
                       different holding period and a different hit rate.

      skip             Refuse the setup. Risk stays exact AND the strategy
                       stays faithful, at the cost of never taking the
                       tightest-stop setups — which, on a low-volatility
                       instrument, may be most of them.

    Set extras['on_stop_floor'] = 'skip' to prefer fidelity over volume.
    Either way `stop_widened` / the skip reason is recorded, so the frequency
    is measurable rather than a silent property of the book.
    """
    if entry <= 0 or f <= 0:
        return stop, False, False
    floor = min_stop_fraction(cfg, asset_class, f)
    if floor <= 0:
        return stop, False, False
    actual = abs(entry - stop) / entry
    if actual >= floor:
        return stop, False, False

    policy = str(_extras(cfg).get("on_stop_floor", "widen")).lower()
    detail = ("%s stop %.3f%% is inside the %.3f%% floor implied by a %.2f%% "
              "risk budget and a %.0f%% notional cap"
              % (asset_class, actual * 100, floor * 100, f * 100,
                 max_notional_fraction(cfg, asset_class) * 100))
    if policy == "skip":
        logger.info("[sizing] %s — skipping (on_stop_floor=skip)", detail)
        return stop, False, True
    logger.info("[sizing] %s — widening the stop", detail)
    widened = (entry * (1 - floor) if str(direction).upper() == "BUY"
               else entry * (1 + floor))
    return widened, True, False


def qty_for_risk(equity: float, f: float, entry: float, stop: float,
                 *, value_per_unit: float = 1.0) -> float:
    """Units such that a stop-out costs exactly `f` of equity.

    `value_per_unit` scales the loss per price-point per unit — 100 for an
    options contract whose entry/stop are quoted in premium per share.
    Returns 0.0 on any degenerate input rather than raising, because the
    caller treats 0 as "do not trade".
    """
    risk_budget = float(equity) * float(f)
    per_unit = abs(float(entry) - float(stop)) * float(value_per_unit)
    if risk_budget <= 0 or per_unit <= 0:
        return 0.0
    return risk_budget / per_unit


def size_position(cfg, *, asset_class: str, entry: float, stop: float,
                  direction: str, value_per_unit: float = 1.0) -> dict:
    """The whole calculation, in one place.

    Returns {qty, stop, stop_widened, risk_fraction, risk_dollars,
             skipped_by_stop_floor, notional_fraction}. `stop` is the one to
            actually place: it may have been widened, and the caller must use
            the returned value for both the broker order and
            `initial_stop_loss`, or realized_r is denominated against a stop
            that was never live. qty is 0 when the setup was skipped.
    """
    f = risk_fraction(cfg)
    equity = float(getattr(cfg, "capital", 0) or 0)
    stop_used, widened, skip = apply_stop_floor(cfg, asset_class, entry, stop,
                                                direction, f)
    qty = 0.0 if skip else qty_for_risk(equity, f, entry, stop_used,
                                        value_per_unit=value_per_unit)
    notional = qty * float(entry) * float(value_per_unit)
    return {
        "qty": qty,
        "stop": stop_used,
        "stop_widened": widened,
        "skipped_by_stop_floor": skip,
        "risk_fraction": f,
        "risk_dollars": round(equity * f, 6),
        "notional_fraction": round(notional / equity, 6) if equity > 0 else 0.0,
        # Recorded into entry_meta so every close path and the grader can
        # convert quote-currency P&L with the SAME entry-time number —
        # symmetry is what keeps realized_r price-based.
        "value_per_unit": float(value_per_unit),
    }
