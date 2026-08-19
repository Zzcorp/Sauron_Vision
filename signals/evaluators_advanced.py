"""Phase 34-36 advanced evaluators — tradecraft, behavioral, quantitative.

Three families of evaluators that move Sauron beyond simple indicator-thresholds
into the territory professional discretionary traders actually operate in:

  Phase 34 — Quantitative regime detection (Hurst, GARCH, CVaR)
  Phase 35 — Microstructure / Smart-Money tradecraft (liquidity sweeps, FVG,
             order blocks, session breaks, RVOL, anchored VWAP breaks)
  Phase 36 — Behavioral / psychology (news-price divergence, crowd extremes,
             anchoring zones, capitulation, parabolic exhaustion, fakeouts,
             narrative consensus, smart-money divergence)

Why this matters
----------------

A pure technical or pure fundamental rule is exactly the kind of signal that
the market has already priced in. The edges that remain are at the seams:

  - "Bullish data, price drops" → smart money sold the news; chase = trap.
  - "Everyone is euphoric on Reddit" → crowd at extreme; revert.
  - "Price ran the obvious stops then snapped back" → liquidity grab, not breakout.
  - "Price is anchored at a round 100" → magnetic zone, expect reaction.

Each evaluator below explicitly models one of those non-obvious patterns. They
compose with each other (and with the Phase-10 evaluators) inside an
OpportunitySetup — so a "trade only when X liquidity-swept Y resistance with
news-price divergence and crowd at extreme" rule is just JSON.

Contract (same as opportunity_scanner)
--------------------------------------

  fn(params: dict, instrument, now: datetime) -> {
      "matched": bool,
      "score":   float in [0, 1],
      "details": {...evaluation diagnostics...},
  }

All evaluators return matched=False rather than raising on insufficient data —
a setup with insufficient inputs is a setup that doesn't fire, not a crash.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

from .opportunity_scanner import (
    cot_net_speculative, cot_sign, register_kind, _recent_closes,
)
from .quant_primitives import (
    hurst_exponent,
    hurst_regime_label,
    garch_lite_forecast,
    cvar,
    anchored_vwap,
    rolling_zscore,
    linear_slope,
)

logger = logging.getLogger(__name__)


# ── Shared helpers ────────────────────────────────────────────────────────

def _recent_bars(instrument, lookback: int, now: datetime,
                 timeframe: str = "1d") -> list[dict]:
    """Return the last `lookback` OHLCV bars (oldest first) up to `now`.

    Used by tradecraft evaluators that need wicks/bodies, not just closes.
    """
    from market_data.models import PriceData
    cutoff = now - timedelta(days=lookback * 2)
    qs = (PriceData.objects
          .filter(instrument=instrument, timeframe=timeframe,
                  timestamp__lte=now, timestamp__gte=cutoff)
          .order_by("timestamp")
          .values("timestamp", "open", "high", "low", "close", "volume"))
    bars = []
    for row in qs:
        try:
            bars.append({
                "timestamp": row["timestamp"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"] or 0),
            })
        except (TypeError, ValueError):
            continue
    return bars[-lookback:] if len(bars) >= lookback else bars


def _bullish_body(b: dict) -> bool:
    return b["close"] >= b["open"]


def _body_size(b: dict) -> float:
    return abs(b["close"] - b["open"])


def _range(b: dict) -> float:
    return max(b["high"] - b["low"], 1e-12)


# ══════════════════════════════════════════════════════════════════════════
# Phase 34 — Quantitative regime evaluators
# ══════════════════════════════════════════════════════════════════════════

def _eval_hurst_regime(params: dict, instrument, now: datetime) -> dict:
    """Hurst exponent reveals whether the series is trending, mean-reverting,
    or random. Use this as a regime gate: only fire trend-following rules in a
    trending regime, only fire mean-reversion rules in a mean-reverting one.

    Why it works: most strategies have a regime they thrive in and a regime
    that murders them. Hurst is the cleanest single number for that split.

    Params:
      regime         — "trending" | "mean_reverting" | "random"
      lookback       — bars used (default 120)
      max_lag        — Hurst max lag (default 20)
    """
    regime = (params or {}).get("regime", "trending")
    lookback = int((params or {}).get("lookback", 120))
    max_lag = int((params or {}).get("max_lag", 20))

    closes = _recent_closes(instrument, lookback, now)
    if len(closes) < max_lag + 5:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient closes"}}

    h = hurst_exponent(closes, max_lag=max_lag)
    if h is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "hurst undefined"}}

    label = hurst_regime_label(h)
    matched = label == regime
    # Score = how decisively the regime is held (further from 0.5 = stronger).
    distance = abs(h - 0.5)
    score = min(1.0, distance / 0.25) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"hurst": round(h, 4), "regime": label,
                        "expected": regime, "lookback": lookback}}


register_kind("hurst_regime", _eval_hurst_regime,
                params=("regime", "lookback", "max_lag"),
                choices={"regime": ("trending", "mean_reverting", "random")})


def _eval_garch_vol_forecast(params: dict, instrument, now: datetime) -> dict:
    """1-step-ahead realized-vol forecast (RiskMetrics EWMA, λ=0.94).

    Use as a vol-regime filter: e.g. "only fire breakout rules when
    forecast vol > 1.2%/day", or "only fire mean-reversion when vol is
    compressed below 0.8%/day".

    Params:
      direction      — "above" | "below"
      threshold_pct  — daily vol threshold expressed as percent (e.g. 1.5 = 1.5%/day)
      lookback       — closes used (default 120)
      lambda_decay   — EWMA decay (default 0.94)
    """
    direction = (params or {}).get("direction", "above")
    try:
        threshold_pct = float((params or {}).get("threshold_pct", 1.5))
        lambda_decay = float((params or {}).get("lambda_decay", 0.94))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}
    lookback = int((params or {}).get("lookback", 120))

    closes = _recent_closes(instrument, lookback, now)
    sigma = garch_lite_forecast(closes, lambda_decay=lambda_decay)
    if sigma is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient data"}}
    sigma_pct = sigma * 100.0

    if direction == "above":
        matched = sigma_pct >= threshold_pct
        score = min(1.0, max(0.0, (sigma_pct - threshold_pct) / max(threshold_pct, 1e-6))) if matched else 0.0
    else:
        matched = sigma_pct <= threshold_pct
        score = min(1.0, max(0.0, (threshold_pct - sigma_pct) / max(threshold_pct, 1e-6))) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"forecast_vol_pct": round(sigma_pct, 4),
                        "direction": direction, "threshold_pct": threshold_pct,
                        "lambda": lambda_decay}}


register_kind("garch_vol_forecast", _eval_garch_vol_forecast,
                params=("direction", "threshold_pct", "lambda_decay", "lookback"),
                choices={"direction": ("above", "below")})


def _eval_cvar_tail_risk(params: dict, instrument, now: datetime) -> dict:
    """Conditional VaR — average loss in the worst α% of historical days.

    A *worse-than-threshold* CVaR (e.g. cvar < -3%) signals the asset has
    fat-tailed downside; you'd typically *down-size* such trades or skip them
    entirely. Setting `direction="worse_than"` matches when the tail is fatter
    than expected.

    Params:
      alpha          — tail fraction (default 0.05 = 5%)
      direction      — "worse_than" | "better_than"
      threshold_pct  — CVaR threshold as percent (e.g. -3.0 means -3% expected
                       tail loss).
      lookback       — daily closes used (default 120)
    """
    direction = (params or {}).get("direction", "worse_than")
    try:
        alpha = float((params or {}).get("alpha", 0.05))
        threshold_pct = float((params or {}).get("threshold_pct", -3.0))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}
    lookback = int((params or {}).get("lookback", 120))

    closes = _recent_closes(instrument, lookback, now)
    if len(closes) < 20:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient closes"}}
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            rets.append((closes[i] / closes[i - 1] - 1.0) * 100.0)  # pct

    cv = cvar(rets, alpha=alpha)
    if cv is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "cvar undefined"}}

    # cv is a pct already (since rets are pct). Threshold also pct.
    if direction == "worse_than":
        matched = cv <= threshold_pct
        score = min(1.0, max(0.0, (threshold_pct - cv) / max(abs(threshold_pct), 1e-6))) if matched else 0.0
    else:
        matched = cv >= threshold_pct
        score = min(1.0, max(0.0, (cv - threshold_pct) / max(abs(threshold_pct), 1e-6))) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"cvar_pct": round(cv, 4), "alpha": alpha,
                        "direction": direction, "threshold_pct": threshold_pct,
                        "n_returns": len(rets)}}


register_kind("cvar_tail_risk", _eval_cvar_tail_risk,
                params=("direction", "alpha", "threshold_pct", "lookback"),
                choices={"direction": ("worse_than", "better_than")})


# ══════════════════════════════════════════════════════════════════════════
# Phase 35 — Microstructure / Smart-Money tradecraft
# ══════════════════════════════════════════════════════════════════════════

def _eval_liquidity_sweep(params: dict, instrument, now: datetime) -> dict:
    """Liquidity sweep: price wicks beyond a recent swing high/low and CLOSES
    BACK INSIDE the prior range — the textbook 'stop hunt'.

    Why it works: stops cluster just beyond obvious swing points. Big players
    push price through to harvest that liquidity, then the move reverses. A
    breakout that closes back inside is not a breakout — it's a trap that
    just printed itself. We flag it as the *opposite* direction signal.

    Params:
      direction   — "bullish_sweep" (sweeps a swing low → reversal up)
                    | "bearish_sweep" (sweeps a swing high → reversal down)
      lookback    — bars to scan for the swing level (default 20)
      wick_pct    — minimum wick beyond the swing as % of the bar's range (default 0.3 = 30%)
    """
    direction = (params or {}).get("direction", "bullish_sweep")
    lookback = int((params or {}).get("lookback", 20))
    try:
        wick_pct = float((params or {}).get("wick_pct", 0.3))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad wick_pct"}}

    bars = _recent_bars(instrument, lookback + 2, now)
    if len(bars) < lookback + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {lookback + 1} bars, got {len(bars)}"}}

    last = bars[-1]
    prior = bars[-(lookback + 1):-1]
    swing_high = max(b["high"] for b in prior)
    swing_low = min(b["low"] for b in prior)
    rng = _range(last)

    if direction == "bullish_sweep":
        # Wick took out swing low, but close is back inside (above swing_low).
        wick_below = max(0.0, swing_low - last["low"])
        matched = (last["low"] < swing_low and last["close"] > swing_low
                   and wick_below / rng >= wick_pct)
        score = min(1.0, wick_below / rng / max(wick_pct, 1e-6)) if matched else 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"swing_low": swing_low, "wick_below": round(wick_below, 8),
                            "close": last["close"], "range": round(rng, 8),
                            "wick_ratio": round(wick_below / rng, 4),
                            "direction": direction}}
    else:  # bearish_sweep
        wick_above = max(0.0, last["high"] - swing_high)
        matched = (last["high"] > swing_high and last["close"] < swing_high
                   and wick_above / rng >= wick_pct)
        score = min(1.0, wick_above / rng / max(wick_pct, 1e-6)) if matched else 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"swing_high": swing_high, "wick_above": round(wick_above, 8),
                            "close": last["close"], "range": round(rng, 8),
                            "wick_ratio": round(wick_above / rng, 4),
                            "direction": direction}}


register_kind("liquidity_sweep", _eval_liquidity_sweep,
                params=("direction", "lookback", "wick_pct"),
                choices={"direction": ("bullish_sweep", "bearish_sweep")})


def _eval_fair_value_gap(params: dict, instrument, now: datetime) -> dict:
    """Fair Value Gap (FVG / imbalance): a 3-bar pattern where the wick of
    bar[-3] doesn't overlap the wick of bar[-1] — leaving a price 'vacuum'
    that often fills on retest.

    Bullish FVG: bar[-3].high < bar[-1].low → an unfilled gap below the
    middle bar; price tends to retrace down into [bar[-3].high .. bar[-1].low]
    before continuing up.

    Why it works: it's literally a hole in the order book printed by an
    impulsive move. Algo desks fill it because that's where rest-orders sit.

    Params:
      direction   — "bullish" | "bearish"
      max_age     — bars old the FVG can be (default 5; we look at the most recent)
    """
    direction = (params or {}).get("direction", "bullish")
    max_age = int((params or {}).get("max_age", 5))

    bars = _recent_bars(instrument, max_age + 4, now)
    if len(bars) < 4:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "need ≥4 bars"}}

    # Scan from the most recent triple backwards.
    for offset in range(0, min(max_age, len(bars) - 2)):
        i = len(bars) - 1 - offset
        if i < 2:
            break
        b0 = bars[i - 2]; b1 = bars[i - 1]; b2 = bars[i]
        if direction == "bullish" and b0["high"] < b2["low"]:
            gap = b2["low"] - b0["high"]
            mid_range = _range(b1)
            score = min(1.0, gap / max(mid_range, 1e-9))
            return {"matched": True, "score": round(score, 4),
                    "details": {"gap_low": b0["high"], "gap_high": b2["low"],
                                "gap_size": round(gap, 8), "age_bars": offset,
                                "direction": direction}}
        if direction == "bearish" and b0["low"] > b2["high"]:
            gap = b0["low"] - b2["high"]
            mid_range = _range(b1)
            score = min(1.0, gap / max(mid_range, 1e-9))
            return {"matched": True, "score": round(score, 4),
                    "details": {"gap_high": b0["low"], "gap_low": b2["high"],
                                "gap_size": round(gap, 8), "age_bars": offset,
                                "direction": direction}}

    return {"matched": False, "score": 0.0,
            "details": {"reason": f"no {direction} FVG in last {max_age} bars"}}


register_kind("fair_value_gap", _eval_fair_value_gap, params=("direction", "max_age"),
                choices={"direction": ("bullish", "bearish")})


def _eval_order_block(params: dict, instrument, now: datetime) -> dict:
    """Order block: the LAST bear/bull candle that occurred BEFORE a strong
    impulsive move in the OPPOSITE direction. Smart-money concept: that final
    counter-trend candle is where institutions absorbed liquidity and reversed.

    Bullish order block: last red candle before a rally of `min_impulse_pct`
    over the next `impulse_window` bars.

    Use it as a magnetic level — price often returns to the order block
    before continuing.

    Params:
      direction         — "bullish" | "bearish"
      lookback          — bars to scan (default 30)
      impulse_window    — bars after the candle to count the impulse (default 3)
      min_impulse_pct   — minimum % move (default 1.5)
      proximity_pct     — last close must be within this % of the block (default 1.0)
    """
    direction = (params or {}).get("direction", "bullish")
    lookback = int((params or {}).get("lookback", 30))
    impulse_window = int((params or {}).get("impulse_window", 3))
    try:
        min_impulse_pct = float((params or {}).get("min_impulse_pct", 1.5))
        proximity_pct = float((params or {}).get("proximity_pct", 1.0))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}

    bars = _recent_bars(instrument, lookback + impulse_window + 2, now)
    if len(bars) < impulse_window + 5:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient bars"}}

    last_close = bars[-1]["close"]
    found = None
    # Walk from oldest (with room for impulse window after it) to newest.
    for i in range(0, len(bars) - impulse_window - 1):
        cand = bars[i]
        future = bars[i + 1: i + 1 + impulse_window]
        if direction == "bullish":
            # Red candle followed by impulse UP.
            if _bullish_body(cand) or cand["close"] == cand["open"]:
                continue
            high_after = max(b["high"] for b in future)
            move_pct = (high_after - cand["close"]) / cand["close"] * 100.0
            if move_pct >= min_impulse_pct:
                found = (cand, move_pct)
        else:  # bearish
            if (not _bullish_body(cand)) or cand["close"] == cand["open"]:
                continue
            low_after = min(b["low"] for b in future)
            move_pct = (cand["close"] - low_after) / cand["close"] * 100.0
            if move_pct >= min_impulse_pct:
                found = (cand, move_pct)

    if not found:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no order block found"}}

    block, move_pct = found
    # Block zone: the candle's body; we test "price near the block" as proximity.
    block_top = max(block["open"], block["close"])
    block_bot = min(block["open"], block["close"])
    block_mid = (block_top + block_bot) / 2.0
    distance_pct = abs(last_close - block_mid) / block_mid * 100.0
    matched = distance_pct <= proximity_pct
    # Score: closer to block AND stronger impulse → higher score.
    proximity_score = max(0.0, 1.0 - distance_pct / max(proximity_pct, 1e-6))
    impulse_score = min(1.0, move_pct / max(min_impulse_pct * 2, 1e-6))
    score = (proximity_score + impulse_score) / 2 if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"block_top": block_top, "block_bottom": block_bot,
                        "block_mid": block_mid, "last_close": last_close,
                        "distance_pct": round(distance_pct, 4),
                        "impulse_pct": round(move_pct, 4),
                        "direction": direction}}


register_kind("order_block", _eval_order_block,
                params=("direction", "lookback", "impulse_window", "min_impulse_pct",
                        "proximity_pct"),
                choices={"direction": ("bullish", "bearish")})


def _eval_session_break(params: dict, instrument, now: datetime) -> dict:
    """Asian-range break during London/NY open — classic FX/crypto edge.

    Computes the high/low range of the prior `range_hours` (Asia session by
    default) and matches when current price has broken outside it.

    Params:
      range_hours   — span of the prior session (default 8)
      timeframe     — bar timeframe (default "1h")
      direction     — "above" (broken high) | "below" (broken low)
    """
    range_hours = int((params or {}).get("range_hours", 8))
    timeframe = (params or {}).get("timeframe", "1h")
    direction = (params or {}).get("direction", "above")

    from market_data.models import PriceData
    cutoff_high = now
    cutoff_low = now - timedelta(hours=range_hours * 2)
    qs = (PriceData.objects
          .filter(instrument=instrument, timeframe=timeframe,
                  timestamp__gte=cutoff_low, timestamp__lte=cutoff_high)
          .order_by("timestamp")
          .values_list("timestamp", "high", "low", "close"))
    rows = list(qs)
    if len(rows) < range_hours + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {range_hours + 1} bars, got {len(rows)}"}}

    # The most recent bar is our 'breakout' bar; the prior `range_hours` form the range.
    range_bars = rows[-(range_hours + 1):-1]
    last = rows[-1]
    range_high = max(float(b[1]) for b in range_bars)
    range_low = min(float(b[2]) for b in range_bars)
    last_close = float(last[3])
    rng = max(range_high - range_low, 1e-12)

    if direction == "above":
        matched = last_close > range_high
        excess = last_close - range_high
        score = min(1.0, excess / rng) if matched else 0.0
    else:
        matched = last_close < range_low
        excess = range_low - last_close
        score = min(1.0, excess / rng) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"range_high": range_high, "range_low": range_low,
                        "last_close": last_close, "direction": direction,
                        "range_hours": range_hours, "timeframe": timeframe}}


register_kind("session_break", _eval_session_break,
                params=("range_hours", "timeframe", "direction"),
                choices={"direction": ("above", "below")})


def _eval_relative_volume(params: dict, instrument, now: datetime) -> dict:
    """Current bar's volume ÷ N-bar average ≥ threshold. The cleanest
    'something is happening' filter — pros watch it more than price.

    Params:
      period     — bars in the average (default 20)
      threshold  — multiplier (default 2.0 → "2x average")
      timeframe  — bar timeframe (default "1d")
    """
    period = int((params or {}).get("period", 20))
    timeframe = (params or {}).get("timeframe", "1d")
    try:
        threshold = float((params or {}).get("threshold", 2.0))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad threshold"}}

    bars = _recent_bars(instrument, period + 2, now, timeframe=timeframe)
    if len(bars) < period + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {period + 1} bars"}}

    last_vol = bars[-1]["volume"]
    prior = [b["volume"] for b in bars[-(period + 1):-1] if b["volume"] > 0]
    if len(prior) < max(5, period // 2):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "not enough non-zero volume bars"}}
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return {"matched": False, "score": 0.0, "details": {"reason": "avg volume zero"}}
    ratio = last_vol / avg
    matched = ratio >= threshold
    score = min(1.0, (ratio - threshold) / max(threshold, 1e-6) + 0.5) if matched else 0.0
    return {"matched": matched, "score": round(min(score, 1.0), 4),
            "details": {"last_volume": last_vol, "avg_volume": round(avg, 2),
                        "ratio": round(ratio, 4), "threshold": threshold,
                        "period": period}}


register_kind("relative_volume", _eval_relative_volume,
                params=("period", "timeframe", "threshold"))


def _eval_anchored_vwap_break(params: dict, instrument, now: datetime) -> dict:
    """Price crosses Anchored VWAP from a chosen anchor point.

    AVWAP is the volume-weighted mean since the anchor — the *true* break-even
    of everyone who positioned since that event. Crossing it flips the
    average participant from in-loss to in-profit (or vice versa), which
    triggers behavior at scale.

    Params:
      anchor_days_ago  — anchor offset in days (default 30)
      direction        — "above" (price closes above AVWAP) | "below"
      timeframe        — default "1d"
    """
    anchor_days_ago = int((params or {}).get("anchor_days_ago", 30))
    direction = (params or {}).get("direction", "above")
    timeframe = (params or {}).get("timeframe", "1d")

    bars = _recent_bars(instrument, anchor_days_ago + 5, now, timeframe=timeframe)
    if len(bars) < 10:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient bars"}}

    cutoff = now - timedelta(days=anchor_days_ago)
    anchored = [b for b in bars if b["timestamp"] >= cutoff]
    if len(anchored) < 5:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "anchor window too short"}}

    avwap = anchored_vwap(anchored)
    if avwap is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "avwap undefined (zero volume)"}}

    last_close = bars[-1]["close"]
    if direction == "above":
        matched = last_close > avwap
        score = min(1.0, (last_close - avwap) / max(avwap, 1e-6) * 10) if matched else 0.0
    else:
        matched = last_close < avwap
        score = min(1.0, (avwap - last_close) / max(avwap, 1e-6) * 10) if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"avwap": round(avwap, 6), "last_close": last_close,
                        "anchor_days_ago": anchor_days_ago,
                        "direction": direction, "n_bars": len(anchored)}}


register_kind("anchored_vwap_break", _eval_anchored_vwap_break,
                params=("anchor_days_ago", "direction", "timeframe"),
                choices={"direction": ("above", "below")})


# ══════════════════════════════════════════════════════════════════════════
# Phase 36 — Behavioral / psychology evaluators
# ══════════════════════════════════════════════════════════════════════════

def _eval_news_price_divergence(params: dict, instrument, now: datetime) -> dict:
    """News sentiment says one thing; price moved the OTHER way.

    The single most important pattern in the news/data world. When clearly
    bullish news drops and price doesn't go up (or drops), it means whoever
    needed to sell into the news already sold — supply > demand at this level
    despite the catalyst. The signal is the *opposite* of what the news says.

    Soros called it 'reflexivity' — the market's reaction to the news is more
    information than the news itself.

    Params:
      lookback_days   — window for news + price move (default 2)
      keywords        — news keywords (default = symbol)
      sentiment_dir   — "bullish_news_bearish_price" |
                        "bearish_news_bullish_price"
      min_articles    — minimum sentiment-tagged articles (default 3)
      min_sentiment   — abs sentiment threshold (default 0.3)
      max_price_move_pct — price move in opposite direction must be ≤ this (default 0.5)
    """
    lookback_days = int((params or {}).get("lookback_days", 2))
    keywords = (params or {}).get("keywords") or [instrument.symbol]
    sentiment_dir = (params or {}).get("sentiment_dir", "bullish_news_bearish_price")
    try:
        min_articles = int((params or {}).get("min_articles", 3))
        min_sentiment = float((params or {}).get("min_sentiment", 0.3))
        max_price_move_pct = float((params or {}).get("max_price_move_pct", 0.5))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}

    try:
        from scraping.models import NewsArticle
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "NewsArticle unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    from django.db.models import Q, Avg as _Avg
    q = Q()
    for kw in keywords:
        q |= (Q(title__icontains=kw) | Q(content_summary__icontains=kw)
              | Q(ai_summary__icontains=kw))
    qs = NewsArticle.objects.filter(q, published_at__gte=cutoff,
                                     published_at__lte=now,
                                     ai_sentiment_score__isnull=False)
    n = qs.count()
    if n < min_articles:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"only {n} sentiment articles"}}
    avg_sent = float(qs.aggregate(a=_Avg("ai_sentiment_score"))["a"] or 0.0)

    bars = _recent_bars(instrument, lookback_days + 3, now)
    if len(bars) < 2:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no price bars"}}
    first = bars[0]["close"]
    last = bars[-1]["close"]
    move_pct = (last - first) / max(first, 1e-9) * 100.0

    if sentiment_dir == "bullish_news_bearish_price":
        # News strongly bullish, price flat or down by max_price_move_pct
        sentiment_ok = avg_sent >= min_sentiment
        price_ok = move_pct <= max_price_move_pct
        matched = sentiment_ok and price_ok
        # Score: strength of divergence
        sent_strength = min(1.0, max(0.0, avg_sent / max(min_sentiment, 1e-6)))
        price_strength = min(1.0, max(0.0, (max_price_move_pct - move_pct) / max(abs(max_price_move_pct) + 1.0, 1e-6)))
        score = (sent_strength + price_strength) / 2 if matched else 0.0
    else:  # bearish_news_bullish_price
        sentiment_ok = avg_sent <= -min_sentiment
        price_ok = move_pct >= -max_price_move_pct
        matched = sentiment_ok and price_ok
        sent_strength = min(1.0, max(0.0, -avg_sent / max(min_sentiment, 1e-6)))
        price_strength = min(1.0, max(0.0, (move_pct + max_price_move_pct) / max(abs(max_price_move_pct) + 1.0, 1e-6)))
        score = (sent_strength + price_strength) / 2 if matched else 0.0

    return {"matched": matched, "score": round(score, 4),
            "details": {"avg_sentiment": round(avg_sent, 4),
                        "n_articles": n, "price_move_pct": round(move_pct, 4),
                        "sentiment_dir": sentiment_dir,
                        "lookback_days": lookback_days}}


register_kind("news_price_divergence", _eval_news_price_divergence,
                params=("lookback_days", "keywords", "sentiment_dir", "min_articles",
                        "min_sentiment", "max_price_move_pct"),
                choices={"sentiment_dir": ("bullish_news_bearish_price",
                                           "bearish_news_bullish_price")})


def _eval_crowd_extreme(params: dict, instrument, now: datetime) -> dict:
    """Social/retail sentiment at a statistical extreme → contrarian signal.

    Built on Phase-10 SentimentSnapshot. A z-score of recent composite_score
    vs its own history above/below the threshold means the crowd is at an
    extreme — the moment when the marginal buyer/seller is exhausted.

    "When all are bullish, who is left to buy?"

    Params:
      direction       — "euphoric" (extreme positive → contrarian short) |
                        "panic" (extreme negative → contrarian long)
      window          — z-score window in snapshot count (default 30)
      z_threshold     — abs z (default 1.5)
      source          — optional snapshot source filter
      lookback_days   — pool data from last N days (default 60)
    """
    direction = (params or {}).get("direction", "euphoric")
    window = int((params or {}).get("window", 30))
    try:
        z_threshold = float((params or {}).get("z_threshold", 1.5))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad z_threshold"}}
    source = (params or {}).get("source")
    lookback_days = int((params or {}).get("lookback_days", 60))

    try:
        from scraping.models import SentimentSnapshot
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "SentimentSnapshot unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    qs = SentimentSnapshot.objects.filter(
        instrument=instrument, timestamp__gte=cutoff, timestamp__lte=now,
    ).order_by("timestamp")
    if source:
        qs = qs.filter(source=source)
    scores = list(qs.values_list("composite_score", flat=True))
    if len(scores) < window + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {window + 1} snapshots, got {len(scores)}"}}

    z = rolling_zscore([float(s) for s in scores], window=window)
    if z is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "z-score undefined"}}

    if direction == "euphoric":
        matched = z >= z_threshold
    else:  # panic
        matched = z <= -z_threshold

    score = min(1.0, abs(z) / max(z_threshold * 2, 1e-6)) if matched else 0.0
    return {"matched": matched, "score": round(score, 4),
            "details": {"z_score": round(z, 4), "direction": direction,
                        "z_threshold": z_threshold, "window": window,
                        "n_snapshots": len(scores), "source": source or "any"}}


register_kind("crowd_extreme", _eval_crowd_extreme,
                params=("direction", "window", "z_threshold", "source", "lookback_days"),
                choices={"direction": ("euphoric", "panic")})


def _eval_anchoring_zone(params: dict, instrument, now: datetime) -> dict:
    """Price approaching a psychological anchor: round number ($100, $1000) or
    a memorable prior swing high/low. Markets react at these levels because
    humans (and stop-orders) cluster there.

    Anchoring bias (Tversky/Kahneman) — even pros use round numbers as
    reference points subconsciously.

    Params:
      mode          — "round_number" | "prior_swing_high" | "prior_swing_low"
      proximity_pct — how close last price must be (default 0.5%)
      lookback      — for swing detection (default 60 bars)
    """
    mode = (params or {}).get("mode", "round_number")
    try:
        proximity_pct = float((params or {}).get("proximity_pct", 0.5))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad proximity_pct"}}
    lookback = int((params or {}).get("lookback", 60))

    bars = _recent_bars(instrument, lookback + 2, now)
    if not bars:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no bars"}}
    last = bars[-1]["close"]

    if mode == "round_number":
        # Find the nearest power-of-10 anchor. For BTC at 67k, anchor is 70k.
        if last <= 0:
            return {"matched": False, "score": 0.0, "details": {"reason": "price <= 0"}}
        magnitude = 10 ** math.floor(math.log10(last))
        # Nearest round multiple of (magnitude / 2) — lets us hit "65,000" type levels
        step = magnitude
        nearest = round(last / step) * step
        if nearest == 0:
            return {"matched": False, "score": 0.0, "details": {"reason": "no anchor"}}
        dist_pct = abs(last - nearest) / nearest * 100.0
        matched = dist_pct <= proximity_pct
        score = max(0.0, 1.0 - dist_pct / max(proximity_pct, 1e-6)) if matched else 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"last": last, "anchor": nearest,
                            "distance_pct": round(dist_pct, 4),
                            "mode": mode}}

    # Swing detection
    if mode in ("prior_swing_high", "prior_swing_low"):
        prior = bars[:-1]
        if not prior:
            return {"matched": False, "score": 0.0, "details": {"reason": "no prior bars"}}
        if mode == "prior_swing_high":
            anchor = max(b["high"] for b in prior)
        else:
            anchor = min(b["low"] for b in prior)
        dist_pct = abs(last - anchor) / anchor * 100.0 if anchor != 0 else 1e9
        matched = dist_pct <= proximity_pct
        score = max(0.0, 1.0 - dist_pct / max(proximity_pct, 1e-6)) if matched else 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"last": last, "anchor": anchor,
                            "distance_pct": round(dist_pct, 4),
                            "mode": mode}}

    return {"matched": False, "score": 0.0, "details": {"reason": f"unknown mode {mode}"}}


register_kind("anchoring_zone", _eval_anchoring_zone,
                params=("mode", "proximity_pct", "lookback"),
                choices={"mode": ("round_number", "prior_swing_high",
                                  "prior_swing_low")})


def _eval_capitulation_detector(params: dict, instrument, now: datetime) -> dict:
    """Capitulation: outsized red candle on outsized volume after a multi-bar
    decline. The 'I give up' moment when weak hands flush.

    The day after capitulation is statistically the strongest mean-reversion
    bounce in the dataset — sellers exhausted, value buyers step in.

    Params:
      decline_bars     — minimum prior down-trend length (default 5)
      decline_min_pct  — minimum cumulative decline (default 5%)
      body_z           — current candle body must exceed this z-score vs window (default 2.0)
      vol_multiplier   — volume vs N-bar avg ≥ this (default 1.8)
      window           — z-score / avg window (default 20)
    """
    decline_bars = int((params or {}).get("decline_bars", 5))
    try:
        decline_min_pct = float((params or {}).get("decline_min_pct", 5.0))
        body_z = float((params or {}).get("body_z", 2.0))
        vol_multiplier = float((params or {}).get("vol_multiplier", 1.8))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}
    window = int((params or {}).get("window", 20))

    bars = _recent_bars(instrument, max(window, decline_bars) + 5, now)
    if len(bars) < window + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {window + 1} bars"}}

    last = bars[-1]
    # Must be red.
    if _bullish_body(last):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "last bar not red"}}

    # Prior decline.
    decline_window = bars[-(decline_bars + 1):-1]
    if len(decline_window) < decline_bars:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "decline window too small"}}
    decline_pct = (decline_window[0]["close"] - decline_window[-1]["close"]) / max(decline_window[0]["close"], 1e-9) * 100.0
    if decline_pct < decline_min_pct:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"decline only {decline_pct:.2f}%",
                            "min": decline_min_pct}}

    # Body z-score vs prior `window` bodies.
    prior_bodies = [_body_size(b) for b in bars[-(window + 1):-1]]
    body_now = _body_size(last)
    if len(prior_bodies) < 2:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no body history"}}
    mean_b = statistics.fmean(prior_bodies)
    sd_b = statistics.pstdev(prior_bodies) if len(prior_bodies) >= 2 else 0.0
    z = (body_now - mean_b) / sd_b if sd_b > 0 else 0.0
    if z < body_z:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"body z={z:.2f} below {body_z}"}}

    # Volume.
    prior_vols = [b["volume"] for b in bars[-(window + 1):-1] if b["volume"] > 0]
    if len(prior_vols) < max(5, window // 2):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no volume history"}}
    avg_vol = sum(prior_vols) / len(prior_vols)
    vol_ratio = last["volume"] / avg_vol if avg_vol > 0 else 0.0
    if vol_ratio < vol_multiplier:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"volume ratio {vol_ratio:.2f} < {vol_multiplier}"}}

    # Composite score: strong on all three.
    score = min(1.0, (z / max(body_z * 2, 1e-6) +
                      vol_ratio / max(vol_multiplier * 2, 1e-6) +
                      decline_pct / max(decline_min_pct * 2, 1e-6)) / 3.0)
    return {"matched": True, "score": round(score, 4),
            "details": {"body_z": round(z, 4), "vol_ratio": round(vol_ratio, 4),
                        "decline_pct": round(decline_pct, 4),
                        "decline_bars": decline_bars}}


register_kind("capitulation_detector", _eval_capitulation_detector,
                params=("decline_bars", "decline_min_pct", "body_z", "vol_multiplier",
                        "window"))


def _eval_parabolic_exhaustion(params: dict, instrument, now: datetime) -> dict:
    """Three or more consecutive ACCELERATING up-candles (or down-candles) →
    high probability mean-reversion setup.

    Each candle must close above the prior candle's close AND have a larger
    body than the previous one. The 'exponential' shape is what separates
    healthy trend from euphoric blow-off.

    Why: parabolic moves require ever-increasing marginal demand to sustain;
    almost mathematically impossible to maintain for long.

    Params:
      direction        — "exhaustion_up" | "exhaustion_down"
      min_consecutive  — required consecutive accelerating bars (default 3)
    """
    direction = (params or {}).get("direction", "exhaustion_up")
    min_consec = int((params or {}).get("min_consecutive", 3))

    bars = _recent_bars(instrument, min_consec + 3, now)
    if len(bars) < min_consec + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient bars"}}

    tail = bars[-min_consec:]
    sizes = [_body_size(b) for b in tail]
    if direction == "exhaustion_up":
        same_dir = all(_bullish_body(b) for b in tail)
        ascending_close = all(tail[i]["close"] > tail[i - 1]["close"]
                               for i in range(1, len(tail)))
    else:
        same_dir = all(not _bullish_body(b) for b in tail)
        ascending_close = all(tail[i]["close"] < tail[i - 1]["close"]
                               for i in range(1, len(tail)))
    accelerating = all(sizes[i] > sizes[i - 1] for i in range(1, len(sizes)))

    matched = same_dir and ascending_close and accelerating
    if not matched:
        return {"matched": False, "score": 0.0,
                "details": {"same_direction": same_dir,
                            "monotonic_close": ascending_close,
                            "accelerating": accelerating,
                            "n": len(tail)}}

    # Score: ratio of last body to first — bigger blow-off = higher score.
    score = min(1.0, sizes[-1] / max(sizes[0], 1e-9) / 3.0)
    return {"matched": True, "score": round(score, 4),
            "details": {"bodies": [round(s, 8) for s in sizes],
                        "direction": direction, "n": len(tail)}}


register_kind("parabolic_exhaustion", _eval_parabolic_exhaustion,
                params=("direction", "min_consecutive"),
                choices={"direction": ("exhaustion_up", "exhaustion_down")})


def _eval_fakeout_pattern(params: dict, instrument, now: datetime) -> dict:
    """Failed breakout: price broke a level then closed back inside within
    `recovery_bars`. Practical version of liquidity_sweep that works on
    multi-bar timeframes — the previous bar broke, this bar reverted.

    Stops just got harvested.

    Params:
      direction      — "bull_trap" (broke above, closed below) | "bear_trap"
      lookback       — bars defining the level (default 20)
      recovery_bars  — how many bars after the break before we still call it (default 2)
    """
    direction = (params or {}).get("direction", "bull_trap")
    lookback = int((params or {}).get("lookback", 20))
    recovery_bars = int((params or {}).get("recovery_bars", 2))

    bars = _recent_bars(instrument, lookback + recovery_bars + 2, now)
    if len(bars) < lookback + recovery_bars + 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient bars"}}

    # Level from bars BEFORE the recovery window started.
    level_window = bars[:-(recovery_bars + 1)]
    recovery_window = bars[-(recovery_bars + 1):]
    if not level_window:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no level window"}}

    level_high = max(b["high"] for b in level_window)
    level_low = min(b["low"] for b in level_window)
    last = bars[-1]

    if direction == "bull_trap":
        # Some bar in recovery window broke above, but last close is back below.
        broke = any(b["high"] > level_high for b in recovery_window)
        reverted = last["close"] < level_high
        matched = broke and reverted
        # Score: how far below the level we closed.
        if matched:
            depth = (level_high - last["close"]) / max(level_high, 1e-9) * 100.0
            score = min(1.0, depth)
        else:
            score = 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"level_high": level_high, "last_close": last["close"],
                            "broke_above": broke, "reverted_below": reverted,
                            "direction": direction}}
    else:  # bear_trap
        broke = any(b["low"] < level_low for b in recovery_window)
        reverted = last["close"] > level_low
        matched = broke and reverted
        if matched:
            depth = (last["close"] - level_low) / max(level_low, 1e-9) * 100.0
            score = min(1.0, depth)
        else:
            score = 0.0
        return {"matched": matched, "score": round(score, 4),
                "details": {"level_low": level_low, "last_close": last["close"],
                            "broke_below": broke, "reverted_above": reverted,
                            "direction": direction}}


register_kind("fakeout_pattern", _eval_fakeout_pattern,
                params=("direction", "lookback", "recovery_bars"),
                choices={"direction": ("bull_trap", "bear_trap")})


def _eval_narrative_consensus(params: dict, instrument, now: datetime) -> dict:
    """Many news articles + small price reaction = narrative is *baked in*.

    When everyone has written about a story but price barely moved, it means
    every market participant who was going to act on the story already has.
    The thesis is exhausted. Continuation is unlikely; reversal is more
    probable than the news headline would suggest.

    'Buy the rumor, sell the news' codified.

    Params:
      lookback_days       — window (default 5)
      keywords            — default = symbol
      min_articles        — articles required to call it 'consensus' (default 8)
      max_price_move_pct  — abs price move ≤ this for it to be 'baked in' (default 1.5%)
    """
    lookback_days = int((params or {}).get("lookback_days", 5))
    keywords = (params or {}).get("keywords") or [instrument.symbol]
    try:
        min_articles = int((params or {}).get("min_articles", 8))
        max_price_move_pct = float((params or {}).get("max_price_move_pct", 1.5))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}

    try:
        from scraping.models import NewsArticle
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "NewsArticle unavailable"}}

    cutoff = now - timedelta(days=lookback_days)
    from django.db.models import Q
    q = Q()
    for kw in keywords:
        q |= (Q(title__icontains=kw) | Q(content_summary__icontains=kw)
              | Q(ai_summary__icontains=kw))
    n = NewsArticle.objects.filter(q, published_at__gte=cutoff,
                                    published_at__lte=now).count()
    if n < min_articles:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"only {n} articles", "min": min_articles}}

    bars = _recent_bars(instrument, lookback_days + 3, now)
    if len(bars) < 2:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no bars"}}
    move_pct = abs(bars[-1]["close"] - bars[0]["close"]) / max(bars[0]["close"], 1e-9) * 100.0
    if move_pct > max_price_move_pct:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"price moved {move_pct:.2f}% > {max_price_move_pct}",
                            "n_articles": n}}

    # Score: more articles + smaller move → higher 'baked in' score.
    article_score = min(1.0, n / max(min_articles * 2, 1e-6))
    move_score = max(0.0, 1.0 - move_pct / max(max_price_move_pct, 1e-6))
    score = (article_score + move_score) / 2
    return {"matched": True, "score": round(score, 4),
            "details": {"n_articles": n, "price_move_pct": round(move_pct, 4),
                        "lookback_days": lookback_days}}


register_kind("narrative_consensus", _eval_narrative_consensus,
                params=("lookback_days", "keywords", "min_articles",
                        "max_price_move_pct"))


def _eval_smart_money_divergence(params: dict, instrument, now: datetime) -> dict:
    """COT non-commercial (smart-money speculators) positioning OPPOSITE the
    recent price trend. When commercials and large specs disagree with retail
    momentum, the historical edge sits with the smart money.

    Combines COT with a price-slope check: if price is rising but the
    non-commercials are net short and getting shorter, that's a divergence.

    Two things about this test point in a DIRECTION, and a setup that fixes one
    `direction` on its own row has to say which it wants:

      1. The COT column is denominated in the CFTC contract's unit, which for an
         FX future is the FOREIGN currency — see `cot_sign`. Read raw, the
         divergence test was inverted on USDJPY / USDCHF / USDCAD / USDMXN.
      2. A divergence is bullish or bearish depending on which way it points.
         "Price up, smart money short" is a SHORT thesis; "price down, smart
         money long" is a LONG one. `scan_setup` writes `setup.direction`
         verbatim into the Signal and the flag, so a setup pinned to "bullish"
         that accepts both branches publishes half its flags upside-down. The
         `direction` param is how a setup asks for the branch it means.

    Params:
      slope_lookback    — bars for price slope (default 20)
      slope_threshold   — minimum |slope|/price (default 0.0005, ~0.05%/bar)
      min_ratio         — non-commercial extreme ratio (default 0.3)
      direction         — "bullish" (price falling, specs long)
                          | "bearish" (price rising, specs short)
                          | "any" (either — the default, and what an
                            unqualified caller has always meant)
    """
    slope_lookback = int((params or {}).get("slope_lookback", 20))
    direction = (params or {}).get("direction", "any")
    try:
        slope_threshold = float((params or {}).get("slope_threshold", 0.0005))
        min_ratio = float((params or {}).get("min_ratio", 0.3))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0, "details": {"reason": "bad numeric param"}}

    try:
        from scraping.models import COTReport
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "COTReport unavailable"}}

    # Bounded by `now` for the same reason as cot_report: the price slope below
    # is already as-of, so an unbounded COT read would diverge the two halves of
    # the divergence test onto different dates.
    report = (COTReport.objects.filter(instrument=instrument,
                                       report_date__lte=now.date())
              .order_by("-report_date").first())
    if report is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no COT report"}}

    closes = _recent_closes(instrument, slope_lookback + 2, now)
    if len(closes) < slope_lookback:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "insufficient closes for slope"}}
    slope = linear_slope(closes[-slope_lookback:])
    if slope is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "slope undefined"}}
    avg_price = statistics.fmean(closes[-slope_lookback:])
    norm_slope = slope / max(avg_price, 1e-9)

    # In the SYMBOL's frame, not the contract's — see `cot_sign`.
    net = cot_net_speculative(report, instrument)
    total = abs(int(report.non_commercial_long or 0)) + abs(int(report.non_commercial_short or 0))
    ratio = (abs(net) / total) if total > 0 else 0.0

    # Divergence: price slope direction != COT speculative direction, with extremes.
    price_rising = norm_slope > slope_threshold
    price_falling = norm_slope < -slope_threshold
    spec_long = net > 0
    spec_short = net < 0

    if ratio < min_ratio:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"COT ratio {ratio:.2f} < {min_ratio}",
                            "net_speculative": net}}

    long_thesis = price_falling and spec_long     # price down, smart money long
    short_thesis = price_rising and spec_short    # price up, smart money short
    if direction == "bullish":
        matched = long_thesis
    elif direction == "bearish":
        matched = short_thesis
    else:  # "any"
        matched = long_thesis or short_thesis
    if not matched:
        return {"matched": False, "score": 0.0,
                "details": {"price_rising": price_rising, "price_falling": price_falling,
                            "spec_long": spec_long, "spec_short": spec_short,
                            "wanted": direction, "ratio": round(ratio, 4)}}

    score = min(1.0, ratio / max(min_ratio * 2, 1e-6))
    return {"matched": True, "score": round(score, 4),
            "details": {"norm_slope": round(norm_slope, 6),
                        "net_speculative": net, "ratio": round(ratio, 4),
                        "contract_frame_flipped": cot_sign(instrument) < 0,
                        "wanted": direction,
                        "direction": "price_up_smart_short" if short_thesis else "price_down_smart_long",
                        "report_date": str(report.report_date)}}


register_kind("smart_money_divergence", _eval_smart_money_divergence,
                params=("slope_lookback", "slope_threshold", "min_ratio",
                        "direction"),
                choices={"direction": ("bullish", "bearish", "any")})


# ── Module-load summary ─────────────────────────────────────────────────────

ADVANCED_EVALUATORS = [
    # Phase 34
    "hurst_regime", "garch_vol_forecast", "cvar_tail_risk",
    # Phase 35
    "liquidity_sweep", "fair_value_gap", "order_block",
    "session_break", "relative_volume", "anchored_vwap_break",
    # Phase 36
    "news_price_divergence", "crowd_extreme", "anchoring_zone",
    "capitulation_detector", "parabolic_exhaustion", "fakeout_pattern",
    "narrative_consensus", "smart_money_divergence",
]
