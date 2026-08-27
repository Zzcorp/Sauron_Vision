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

# ...but "a fraction of the entry price" means very different things on
# different instruments, and one band for all of them was calibrated for
# equities. A 1.5xATR stop on EURUSD is about 0.30% of price in an ordinary
# session and about 0.15% in a quiet one — so the quiet half of the week fell
# THROUGH the 0.2% floor and the pair silently took the percentage fallback
# instead: `stop_loss_pct` defaults to 1.5%, which on EURUSD is 163 pips.
# Five times the stop the setup was built around, on a trade the operator was
# told was volatility-normalised, with only an INFO line to say so. The low-
# volatility crosses (EURGBP, EURCHF) sat under the floor most of the time,
# and the same floor refused an operator's own 20-pip stop outright.
#
# Per class, therefore. Every class except forex keeps today's exact numbers,
# because nothing was wrong with them and this is a correction, not a re-tune.
# Forex: 0.03% is about three pips on a major — under that a stop is inside
# the spread — and 3% is about 325 pips, past which it is not a stop on a
# major currency, it is a position held to conviction.
STOP_FRACTION_BANDS = {
    "forex": (0.0003, 0.03),
}


def stop_band(asset_class: str) -> tuple:
    """(min, max) sane stop fraction for this asset class."""
    return STOP_FRACTION_BANDS.get(asset_class or "",
                                   (MIN_STOP_FRACTION, MAX_STOP_FRACTION))

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
# Reward:risk the setup must still clear once the round trip is paid out
# of the winner and added to the loser. A 2:1 planned system that drops
# below this is being run for the broker's benefit, not the book's.
DEFAULT_MIN_NET_RR = 1.5


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
    lo, hi = stop_band(getattr(cfg, "asset_class", ""))

    if atr and price > 0:
        stop_distance = atr * stop_mult
        fraction = stop_distance / price
        if lo <= fraction <= hi:
            target_distance = atr * target_mult
            meta = {"levels_source": "atr", "atr": round(atr, 8),
                    "atr_stop_mult": stop_mult, "atr_target_mult": target_mult,
                    "stop_fraction": round(fraction, 6)}
            if direction == "BUY":
                return price - stop_distance, price + target_distance, meta
            return price + stop_distance, price - target_distance, meta
        # WARNING, not INFO. The fallback is not a smaller version of the
        # ATR stop — it is a different trade, sized off a percentage nobody
        # chose for this instrument, and the only trace it used to leave was
        # a line nobody reads at INFO.
        logger.warning("[risk_levels] %s: a %.4f%% ATR stop is outside the "
                       "%.3f%%-%.1f%% band for %s — falling back to the "
                       "configured %.2f%% percentage, which is a DIFFERENT "
                       "stop, not a clamped one",
                       symbol, fraction * 100, lo * 100, hi * 100,
                       getattr(cfg, "asset_class", "?") or "?",
                       float(getattr(cfg, "stop_loss_pct", 0) or 0))
        meta["levels_fallback_reason"] = "atr_out_of_band"
        meta["atr_stop_fraction"] = round(fraction, 6)
        meta["stop_band"] = [lo, hi]

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


def paper_fill_price(cfg, symbol: str, price: float, side: str,
                     *, cost_fraction: float | None = None) -> float:
    """The price a paper order would REALISTICALLY fill at.

    The AssetBot paper path never touches PaperTrader: the order block sits
    inside `if not paper:`, so a paper entry was recorded at the raw ticker
    and a paper exit at the raw mark. Both sides free. That inflates paper
    expectancy by exactly the quantity `passes_cost_filter` exists to defend
    against — and paper expectancy is the evidence the promotion ladder uses
    to decide whether a rule may touch real money. A system that measures
    itself with costs removed will promote rules that lose money net.

    Half the round trip is charged per side, adversely: a buyer pays up, a
    seller sells down.

    This is a model, not a measurement — DEFAULT_COST_BPS is an assumption.
    That is why the fraction applied is recorded on the trade, so it can be
    retuned against real fills later instead of being baked irreversibly
    into the ledger.
    """
    if price <= 0:
        return price
    cost = (float(cost_fraction) if cost_fraction is not None
            else round_trip_cost_fraction(cfg, symbol))
    if cost <= 0:
        return price
    half = cost / 2.0
    return price * (1 + half) if str(side).upper() == "BUY" else price * (1 - half)


def passes_cost_filter(cfg, symbol: str, price: float, target: float,
                       *, stop: float | None = None,
                       cost_fraction: float | None = None) -> tuple:
    """(ok, reason) — is the planned move worth more than the round trip?

    Two checks, because the gross one alone cannot bite on the ATR path.
    An ATR target is 2x the ATR stop and the stop is floored at
    MIN_STOP_FRACTION, so the planned move is always >= 0.4% of notional —
    comfortably above `min_edge_ratio x cost` for every asset class in
    DEFAULT_COST_BPS. The filter would pass everything and read as if it
    were protecting the book.

    What actually decides whether a setup survives its costs is the reward
    and the risk *net of* them: the winner pays the round trip out of its
    target and the loser pays it on top of its stop. So when `stop` is
    known we also require

        (reward - cost) / (risk + cost) >= min_net_rr

    which rejects exactly the trades the gross check misses — tight stops
    on instruments whose spread is a large fraction of 1R.

    `cost_fraction` overrides the asset-class table with a measured cost
    (e.g. an option's own bid/ask spread), as a fraction of notional.
    """
    extras = _extras(cfg)
    if not extras.get("use_cost_filter", True):
        return True, "cost filter disabled"
    if price <= 0:
        return False, "no price"

    min_ratio = float(extras.get("min_edge_ratio", DEFAULT_MIN_EDGE_RATIO))
    cost = (float(cost_fraction) if cost_fraction is not None
            else round_trip_cost_fraction(cfg, symbol))
    move = abs(target - price) / price
    if cost <= 0:
        return True, "no cost model"
    ratio = move / cost
    if ratio < min_ratio:
        return (False,
                f"planned move {move * 100:.2f}% is only {ratio:.1f}x the "
                f"{cost * 100:.2f}% round-trip cost (need {min_ratio:.1f}x)")

    if stop is not None:
        risk = abs(price - float(stop)) / price
        if risk > 0:
            min_net_rr = float(extras.get("min_net_rr", DEFAULT_MIN_NET_RR))
            net_rr = (move - cost) / (risk + cost)
            if net_rr < min_net_rr:
                return (False,
                        f"reward:risk falls to {net_rr:.2f} after the "
                        f"{cost * 100:.2f}% round trip "
                        f"(gross {move / risk:.2f}, need {min_net_rr:.2f})")
            return True, (f"edge {ratio:.1f}x cost, net R:R {net_rr:.2f}")

    return True, f"edge {ratio:.1f}x cost"
