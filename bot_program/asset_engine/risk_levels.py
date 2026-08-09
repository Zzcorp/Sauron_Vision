"""Volatility-normalised stops/targets and a cost-aware entry filter.

Two strategy-level defects this replaces:

1. FIXED-PERCENT STOPS. Every bot used `stop_loss_pct` / `take_profit_pct`
   straight from config, so the same 2% stop was ~0.3 ATR on a quiet
   instrument and ~3 ATR on a violent one. That randomises risk/reward
   across the universe and across regimes, and it makes `realized_r`
   incomparable between symbols — which the whole learning loop depends on.
   Levels are now ATR multiples, so "1R" means the same thing everywhere.

2. NO COST MODEL. Spread + commission + slippage were never subtracted
   before deciding a trade was worth taking, so on wider-spread instruments
   some trades were negative-expectancy by construction.

Both are opt-out via `AssetBotConfig.extras` so an existing config can keep
the old behaviour while it is being re-tuned.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ATR multiples. 1.5 ATR stop / 3.0 ATR target = 2:1 planned reward:risk.
DEFAULT_ATR_STOP_MULT = 1.5
DEFAULT_ATR_TARGET_MULT = 3.0
DEFAULT_ATR_PERIOD = 14
# Guard rails: an ATR-derived stop outside this band of the entry price is
# almost always a data problem (a spike bar, a bad feed), not a real regime.
MIN_STOP_FRACTION = 0.002   # 0.2%
MAX_STOP_FRACTION = 0.25    # 25%

# Round-trip cost assumptions per asset class, as a fraction of notional.
# Deliberately conservative: it is cheaper to skip a marginal trade than to
# discover the cost after paying it.
DEFAULT_COST_BPS = {
    "stock": 5.0,       # commission + typical spread on liquid US equities
    "forex": 2.0,       # spread-only on majors
    "crypto": 10.0,     # taker fee both sides + spread
    "commodity": 8.0,
    "options": 60.0,    # wide spreads dominate; per-contract fees on top
}
DEFAULT_MIN_EDGE_RATIO = 2.0  # planned move must beat cost by this multiple


def _extras(cfg) -> dict:
    return getattr(cfg, "extras", None) or {}


def atr_for(symbol: str, timeframe: str = "4h", period: int = DEFAULT_ATR_PERIOD):
    """Latest ATR for a symbol, or None when there aren't enough bars.

    Reads the stored TechnicalIndicator row first (cheap, already computed
    by the indicator task) and falls back to computing from bars.
    """
    try:
        from indicators.models import TechnicalIndicator
        row = (TechnicalIndicator.objects
               .filter(instrument__symbol=symbol, timeframe=timeframe,
                       atr_14__isnull=False)
               .order_by("-timestamp").first())
        if row and row.atr_14:
            return float(row.atr_14)
    except Exception:
        pass
    try:
        from indicators.calculator import calculate_atr
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, timeframe, bars=period * 4)
        if df is None or len(df) < period + 1:
            return None
        atr = calculate_atr(df["high"].astype(float), df["low"].astype(float),
                            df["close"].astype(float), period=period)
        value = float(atr.iloc[-1])
        return value if value == value and value > 0 else None
    except Exception as e:
        logger.debug("[risk_levels] ATR unavailable for %s: %s", symbol, e)
        return None


def stop_and_target(cfg, symbol: str, price: float, direction: str) -> tuple:
    """Return (stop, target, meta) for an entry.

    Volatility-normalised when an ATR is available; otherwise the config's
    percentages, so a missing indicator degrades to the old behaviour
    rather than blocking the trade.
    """
    extras = _extras(cfg)
    use_atr = extras.get("use_atr_levels", True)
    stop_mult = float(extras.get("atr_stop_mult", DEFAULT_ATR_STOP_MULT))
    target_mult = float(extras.get("atr_target_mult", DEFAULT_ATR_TARGET_MULT))

    atr = atr_for(symbol, extras.get("atr_timeframe", "4h")) if use_atr else None
    meta = {"levels_source": "pct"}

    if atr and price > 0:
        stop_distance = atr * stop_mult
        fraction = stop_distance / price
        if MIN_STOP_FRACTION <= fraction <= MAX_STOP_FRACTION:
            target_distance = atr * target_mult
            meta = {"levels_source": "atr", "atr": round(atr, 8),
                    "atr_stop_mult": stop_mult, "atr_target_mult": target_mult,
                    "stop_fraction": round(fraction, 6)}
            if direction == "BUY":
                return price - stop_distance, price + target_distance, meta
            return price + stop_distance, price - target_distance, meta
        logger.info("[risk_levels] %s ATR stop %.4f%% outside sane band — "
                    "falling back to configured percentages",
                    symbol, fraction * 100)
        meta["levels_fallback_reason"] = "atr_out_of_band"

    sl_pct = cfg.stop_loss_pct / 100.0
    tp_pct = cfg.take_profit_pct / 100.0
    if direction == "BUY":
        return price * (1 - sl_pct), price * (1 + tp_pct), meta
    return price * (1 + sl_pct), price * (1 - tp_pct), meta


def round_trip_cost_fraction(cfg, symbol: str) -> float:
    """Estimated round-trip cost as a fraction of notional."""
    extras = _extras(cfg)
    override = extras.get("cost_bps")
    if override is not None:
        try:
            return float(override) / 10_000.0
        except (TypeError, ValueError):
            pass
    bps = DEFAULT_COST_BPS.get(getattr(cfg, "asset_class", ""), 5.0)
    return float(bps) / 10_000.0


def passes_cost_filter(cfg, symbol: str, price: float, target: float) -> tuple:
    """(ok, reason) — is the planned move worth more than the round trip?

    Without this, a fixed take-profit percentage smaller than the spread
    plus fees is a guaranteed loser no matter how good the signal is.
    """
    extras = _extras(cfg)
    if not extras.get("use_cost_filter", True):
        return True, "cost filter disabled"
    if price <= 0:
        return False, "no price"

    min_ratio = float(extras.get("min_edge_ratio", DEFAULT_MIN_EDGE_RATIO))
    cost = round_trip_cost_fraction(cfg, symbol)
    move = abs(target - price) / price
    if cost <= 0:
        return True, "no cost model"
    ratio = move / cost
    if ratio < min_ratio:
        return (False,
                f"planned move {move * 100:.2f}% is only {ratio:.1f}x the "
                f"{cost * 100:.2f}% round-trip cost (need {min_ratio:.1f}x)")
    return True, f"edge {ratio:.1f}x cost"
