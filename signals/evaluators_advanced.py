"""Phase 34-37 advanced evaluators — tradecraft, behavioral, quantitative.

Four families of evaluators that move Sauron beyond simple indicator-thresholds
into the territory professional discretionary traders actually operate in:

  Phase 34 — Quantitative regime detection (Hurst, GARCH, CVaR)
  Phase 35 — Microstructure / Smart-Money tradecraft (liquidity sweeps, FVG,
             order blocks, session breaks, RVOL, anchored VWAP breaks)
  Phase 36 — Behavioral / psychology (news-price divergence, crowd extremes,
             anchoring zones, capitulation, parabolic exhaustion, fakeouts,
             narrative consensus, smart-money divergence)
  Phase 37 — Structure, calendar and carry (market structure breaks / CHoCH,
             event ORDERING, seasonality, perpetual funding carry)

Why Phase 37 exists, and why it lives HERE
------------------------------------------

This module is the only evaluator lane that can open a position. The richer
`signals/smc` package writes SmcSignal cards that `rule_adapter.is_smc_card`
deliberately drops before the Signal table, so anything missing from this file
is missing from trading, whatever the SMC lane can see.

Three things were missing. Structure — not one of the seventeen Phase 34-36
kinds detected a break of structure, so `advanced_smc_long`, the setup
`rule_adapter` names as the substitute for SMC cards, was an unordered bag:
a sweep AND a gap AND volume, in any order, on any leg. ICT is a SEQUENCE
model and the lane could not express sequence at all. Calendar — PriceData
timestamps were never read as evidence. Carry — FundingRate was traded only as
a contrarian z-score, never as the payment stream it is.

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

import calendar
import logging
import math
import statistics
from datetime import datetime, timedelta, timezone as _dt_timezone
from typing import Optional

from django.utils import timezone

from .opportunity_scanner import (
    cot_net_speculative, cot_sign, latest_fresh_cot_report, register_kind,
    _recent_closes,
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


def _bars_since(instrument, cutoff: datetime, now: datetime,
                timeframe: str = "1d") -> list[dict]:
    """Every bar in [cutoff, now], oldest first — sized in CALENDAR TIME.

    `_recent_bars` is sized in BARS and widens its own cutoff by a factor of
    two to be sure of finding them. Seasonality asks a calendar question
    ("three years of Tuesdays"), so it has to name the window it means: asking
    `_recent_bars` for 1095 "bars" of a five-day-a-week instrument would quietly
    reach back four and a half years and report the sample size of one span
    while having measured another.
    """
    from market_data.models import PriceData
    qs = (PriceData.objects
          .filter(instrument=instrument, timeframe=timeframe,
                  timestamp__gte=cutoff, timestamp__lte=now)
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
    return bars


def _bullish_body(b: dict) -> bool:
    return b["close"] >= b["open"]


def _body_size(b: dict) -> float:
    return abs(b["close"] - b["open"])


def _range(b: dict) -> float:
    return max(b["high"] - b["low"], 1e-12)


def _as_utc(ts: datetime) -> datetime:
    """`ts` in UTC. A naive timestamp is READ as UTC rather than localised.

    Django stores aware UTC, so naive only reaches here from a direct caller
    that built its own datetime; guessing the server's zone for it would move
    a bar across a day boundary and put it in the wrong weekday bucket.
    """
    if timezone.is_naive(ts):
        return ts.replace(tzinfo=_dt_timezone.utc)
    return ts.astimezone(_dt_timezone.utc)


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


# An order block only means anything if the move that left it actually took out
# the level price had been failing at — that is what makes the block the ORIGIN
# of a break rather than one red candle in a hundred. The reference cannot be
# the whole `lookback` window (a months-old extreme vetoes every block in a
# downtrend) nor a single bar (which is not a level), so it is the extreme of
# the bars IMMEDIATELY before the candidate. Ten, because a fractal swing point
# needs SWING_FRACTAL_STRENGTH bars either side to confirm, so ten is the
# smallest window guaranteed to contain at least one confirmable swing.
ORDER_BLOCK_ANCHOR_BARS = 10


def _eval_order_block(params: dict, instrument, now: datetime) -> dict:
    """Order block: the LAST bear/bull candle that occurred BEFORE a strong
    impulsive move in the OPPOSITE direction, where that move BROKE STRUCTURE.
    Smart-money concept: that final counter-trend candle is where institutions
    absorbed liquidity and reversed.

    Bullish order block: last red candle before a rally of `min_impulse_pct`
    over the next `impulse_window` bars, whose closes cleared the high that had
    been capping price (see ORDER_BLOCK_ANCHOR_BARS). Without the structural
    half, "a red candle followed by 1.5% up" describes most red candles in any
    uptrend, and the level it hands back is arbitrary.

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
    unanchored = 0
    # NEWEST first, and BREAK on the first hit. The old loop ran oldest to
    # newest and never broke, so which block survived was decided by assignment
    # order rather than by a rule — a fact legible only to someone who traces
    # the overwrite, and one that a later refactor reversing the walk would
    # silently invert. It has to be the most recent: an order block is a level
    # price is expected to RETURN to, and a block price has already returned to
    # twice has been consumed. "Price is near the block" said of a block thirty
    # bars back is a statement about a level nobody is defending any more.
    #
    # The upper bound is `len - impulse_window - 1`, not `- 2`: a block whose
    # impulse completes on the CURRENT bar is inside the window the caller asked
    # for. It will normally fail the proximity test below (price is still at the
    # top of its own impulse), so this is a boundary made deliberate rather than
    # a bug fixed.
    for i in range(len(bars) - impulse_window - 1, -1, -1):
        cand = bars[i]
        if cand["close"] <= 0:
            continue
        future = bars[i + 1: i + 1 + impulse_window]
        if len(future) < impulse_window:
            continue
        anchor_window = bars[max(0, i - ORDER_BLOCK_ANCHOR_BARS):i]
        if not anchor_window:
            continue
        if direction == "bullish":
            # Red candle followed by impulse UP.
            if _bullish_body(cand) or cand["close"] == cand["open"]:
                continue
            high_after = max(b["high"] for b in future)
            move_pct = (high_after - cand["close"]) / cand["close"] * 100.0
            if move_pct < min_impulse_pct:
                continue
            # The structural anchor. A CLOSE beyond the level, not a wick: this
            # is `smc.structure.detect_market_structure_breaks`' own definition
            # of BOS_UP, with the anchor window's running extreme standing in
            # for its fractal pivot so a short window still has a reference.
            structure_level = max(b["high"] for b in anchor_window)
            if max(b["close"] for b in future) <= structure_level:
                unanchored += 1
                continue
        else:  # bearish
            if (not _bullish_body(cand)) or cand["close"] == cand["open"]:
                continue
            low_after = min(b["low"] for b in future)
            move_pct = (cand["close"] - low_after) / cand["close"] * 100.0
            if move_pct < min_impulse_pct:
                continue
            structure_level = min(b["low"] for b in anchor_window)
            if min(b["close"] for b in future) >= structure_level:
                unanchored += 1
                continue
        found = (cand, move_pct, structure_level, len(bars) - 1 - i)
        break

    if not found:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "no structurally-anchored order block",
                            # Named, because "none found" and "three found, none
                            # of which broke anything" are different markets and
                            # the operator tuning min_impulse_pct needs to know
                            # which one they are looking at.
                            "unanchored_candidates": unanchored,
                            "anchor_bars": ORDER_BLOCK_ANCHOR_BARS,
                            "direction": direction}}

    block, move_pct, structure_level, age_bars = found
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
                        "structure_level": structure_level,
                        "age_bars": age_bars,
                        "unanchored_candidates": unanchored,
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
      period          — bars in the average (default 20)
      threshold       — multiplier (default 2.0 → "2x average")
      timeframe       — bar timeframe (default "1d")
      baseline_offset — end the average this many bars BEFORE the current one
                        (default 0: it runs right up to it)

    `baseline_offset` is for the legs that fire in the days AFTER a known
    event rather than on the event bar. Left at zero the average is taken over
    the bars immediately behind the current one, so several days into a
    post-event window it has already swallowed the event's own volume spike
    and the fat days trailing it. That lifts the divisor, and a threshold at 1.3x
    then asks for something closer to 1.8x of the quiet tape the author meant
    — a gate that tightens the further into the window the scan lands, which
    is backwards for any setup whose thesis is the tail of the move. Offset
    the window clear of the event stretch and the number means what it says on
    every day of it.
    """
    period = int((params or {}).get("period", 20))
    timeframe = (params or {}).get("timeframe", "1d")
    try:
        threshold = float((params or {}).get("threshold", 2.0))
        baseline_offset = max(0, int((params or {}).get("baseline_offset", 0)))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "bad threshold or baseline_offset"}}

    needed = period + baseline_offset + 1
    bars = _recent_bars(instrument, needed + 1, now, timeframe=timeframe)
    if len(bars) < needed:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"need {needed} bars"}}

    last_vol = bars[-1]["volume"]
    prior = [b["volume"] for b in bars[-needed:-(baseline_offset + 1)]
             if b["volume"] > 0]
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
                        "period": period, "baseline_offset": baseline_offset}}


register_kind("relative_volume", _eval_relative_volume,
                params=("period", "timeframe", "threshold", "baseline_offset"))


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

    # Bounded by `now` AND by age — see `latest_fresh_cot_report`. This test is
    # the one that pays most for a stale read: the slope half is live, so
    # frozen positioning drifts out from under a moving price and the
    # divergence it "finds" is nothing but the scraper's own downtime.
    report, reason = latest_fresh_cot_report(instrument, now)
    if report is None:
        return {"matched": False, "score": 0.0, "details": {"reason": reason}}

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


# ══════════════════════════════════════════════════════════════════════════
# Phase 37a — Market structure, and ORDER between events
# ══════════════════════════════════════════════════════════════════════════
#
# Everything below reads the market through `signals/smc`, the same detectors
# that produce the SmcSignal cards, rather than through a second implementation.
# Two lanes disagreeing about whether a BOS printed would be worse than one lane
# not seeing BOS at all: the operator would be reading two vocabularies that
# look identical and are not.

# Fractal half-width for swing detection. `smc.pivots.get_swings` defaults to 3
# and every SmcSignal on this platform was detected with 3, so the armed lane
# uses the same number — a "swing high" has to mean one thing across the two
# lanes or the cards and the trades are describing different markets.
SWING_FRACTAL_STRENGTH = 3

# How far past a broken swing a close must travel before the break counts as
# decisive, measured in MEDIAN BAR RANGES of the same window. One full bar's
# range is the smallest displacement that cannot be produced by a single candle
# poking through and closing marginally beyond. Deliberately scale-free: a
# fixed 0.3% is a decisive break on EURUSD and invisible on a perp, so any
# percentage constant here would be right for one asset class and wrong for the
# other three this lane trades.
DECISIVE_BREAK_RANGES = 1.0

# Half the score is how FRESH the event is, half is how cleanly it PRINTED. The
# even split is deliberate and is not a tuned number: a stale-but-perfect break
# and a fresh-but-marginal one are each half a signal, and nothing measured on
# this platform justifies preferring one over the other yet.
EVENT_RECENCY_WEIGHT = 0.5

# The swing window handed to `detect_sweeps`. It matches the `lookback` the
# seeded `liquidity_sweep` legs pass, so both lanes ask about the same stop
# pools. Note `detect_sweeps` STARTS its scan at bar `lookback`, so a larger
# number here does not widen the search — it blinds the detector to everything
# but the tail of the window.
SWEEP_SWING_LOOKBACK = 20

# Minimum rejection wick as a fraction of the bar's range for the sequence
# lane's sweep. Same 0.3 the seeded `liquidity_sweep` legs use, so the two ask
# for the same SIZE of rejection. They still MEASURE it differently —
# `detect_sweeps` measures the wick from the candle body, `_eval_liquidity_sweep`
# measures penetration beyond the swing — so they can disagree at the margin,
# which is exactly why a setup may carry both without double-counting one test.
SWEEP_WICK_RATIO = 0.3

# The event vocabulary both structure evaluators speak.
_SEQUENCE_EVENTS = ("sweep", "structure_break", "choch", "fair_value_gap")


def _smc_frame(instrument, lookback: int, now: datetime, timeframe: str):
    """(df, swings, reason) for the smc detectors, bounded by `now`.

    `reason` is None on success and a string naming what is missing otherwise —
    never a silently empty frame, because an evaluator that cannot see the
    market must say so rather than reporting "no structure break", which is a
    measurement it did not make.

    Built from `_recent_bars` rather than from `smc.dataframe.load_ohlcv`: the
    loader takes the last N rows with no upper time bound, so a replay would be
    handed bars from after the instant it is replaying.
    """
    bars = _recent_bars(instrument, lookback, now, timeframe=timeframe)
    # A fractal swing needs `strength` bars either side, and a break needs at
    # least one bar after the swing to close beyond it.
    need = SWING_FRACTAL_STRENGTH * 2 + 2
    if len(bars) < need:
        return None, None, f"need {need} bars for a swing, got {len(bars)}"
    try:
        import pandas as pd
        from .smc.pivots import get_swings
    except Exception as exc:            # pragma: no cover - install-shaped
        logger.warning("[advanced] smc structure lane unavailable: %s", exc)
        return None, None, f"smc detectors unavailable: {exc}"
    df = pd.DataFrame(bars).set_index("timestamp")
    swings = get_swings(df, left=SWING_FRACTAL_STRENGTH,
                        right=SWING_FRACTAL_STRENGTH)
    return df, swings, None


def _event_indices(df, swings, event_name: str, bullish: bool) -> list:
    """Bar indices at which `event_name` printed in the wanted direction.

    Oldest first, DEDUPLICATED. The smc detectors emit one record per
    (bar, reference swing) pair, so one bar sweeping a cluster of equal lows
    comes back three times; an ordering question only ever cares which BAR the
    event landed on, and leaving the duplicates in would make the `n_triggers`
    an operator reads a count of reference points dressed up as a count of
    events.

    Every detector called here comes from `signals/smc`, so the ordering the
    armed lane trades is built out of events the richer lane already agrees
    happened.
    """
    from .smc.liquidity import detect_sweeps
    from .smc.structure import detect_market_structure_breaks
    from .smc.zones import detect_fvgs

    if event_name == "sweep":
        # A swept LOW is the BULLISH event: the stops resting under the low were
        # taken and price closed back above it. Getting this pairing backwards
        # is the classic way an SMC rule ends up trading the trap instead of the
        # reversal.
        want = "SWEEP_LOW" if bullish else "SWEEP_HIGH"
        return sorted({s["idx"] for s in detect_sweeps(
            df, swings, lookback=SWEEP_SWING_LOOKBACK,
            wick_ratio=SWEEP_WICK_RATIO) if s["type"] == want})
    if event_name in ("structure_break", "choch"):
        want = "BOS_UP" if bullish else "BOS_DOWN"
        breaks = detect_market_structure_breaks(df, swings)
        return sorted({b["idx"] for b in breaks
                       if b["type"] == want
                       and (b.get("choch") if event_name == "choch" else True)})
    if event_name == "fair_value_gap":
        want = "FVG_BULL" if bullish else "FVG_BEAR"
        return sorted({f["idx"] for f in detect_fvgs(df) if f["type"] == want})
    return []


def _eval_market_structure_break(params: dict, instrument, now: datetime) -> dict:
    """Break of Structure / Change of Character — the concept this lane had no
    detector for at all.

    A BOS is a close beyond a confirmed swing point: the market did not merely
    reach a level, it accepted price past it. A CHoCH is the first BOS that
    contradicts the previous one — the moment a trend's own definition breaks,
    and the only event in this vocabulary that says "the direction changed"
    rather than "the direction continued".

    Wraps `smc.structure.detect_market_structure_breaks` verbatim. The seventeen
    Phase 34-36 kinds could tell you a stop-hunt happened and an imbalance
    existed; none of them could tell you the market had actually turned, so
    `advanced_smc_long` was buying reclaims inside intact downtrends.

    Params:
      direction   — "bullish" (BOS_UP) | "bearish" (BOS_DOWN)
      event       — "bos" (any break the wanted way) | "choch" (only the ones
                    that flipped the prior break's direction)
      lookback    — bars loaded for swing + break detection (default 90)
      max_age     — bars ago the break may have printed (default 5)
      timeframe   — bar timeframe (default "1d")
    """
    direction = (params or {}).get("direction", "bullish")
    event = (params or {}).get("event", "bos")
    lookback = int((params or {}).get("lookback", 90))
    max_age = int((params or {}).get("max_age", 5))
    timeframe = (params or {}).get("timeframe", "1d")

    if direction not in ("bullish", "bearish"):
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown direction {direction!r}"}}
    if event not in ("bos", "choch"):
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown event {event!r}"}}

    df, swings, reason = _smc_frame(instrument, lookback, now, timeframe)
    if reason:
        return {"matched": False, "score": 0.0, "details": {"reason": reason}}

    from .smc.structure import detect_market_structure_breaks
    breaks = detect_market_structure_breaks(df, swings)
    wanted = "BOS_UP" if direction == "bullish" else "BOS_DOWN"
    last_idx = len(df) - 1
    # The two filters are applied separately so the no-match can say WHICH one
    # rejected the window. Folded into one comprehension they cannot be told
    # apart, and the message then claimed there was no break at all in a window
    # that held several — sending anyone debugging a silent `choch` leg to look
    # for a break that is sitting right there in the data.
    of_type = [b for b in breaks
               if b["type"] == wanted and last_idx - b["idx"] <= max_age]
    fresh = [b for b in of_type if b.get("choch")] if event == "choch" else of_type
    if not fresh:
        if of_type:
            no_match = (f"{len(of_type)} {wanted} in the last {max_age} bars, "
                        f"none of them a change of character")
        else:
            no_match = f"no {wanted} in the last {max_age} bars"
        return {"matched": False, "score": 0.0,
                "details": {"reason": no_match, "event": event,
                            # "the direction never broke" and "the direction
                            # broke, continuing the trend it was already in"
                            # are different markets and the operator reads the
                            # difference off this count.
                            "n_fresh_of_type": len(of_type),
                            "n_breaks": len(breaks),
                            "n_swings": len(swings), "direction": direction}}

    # The most recent break, and — among the several `breaks` routinely holds
    # for one bar, because a single close can take out a stack of swings — the
    # one whose broken level is CLOSEST to the trigger. Those entries are one
    # event seen from different reference points; measuring displacement against
    # the furthest of them would credit the bar with distance it never had to
    # travel past a level, so the nearest is the honest reading and the smallest
    # score. Chosen explicitly rather than by taking whatever list order left
    # last, which is the accident `order_block` was carrying.
    newest_idx = max(int(b["idx"]) for b in fresh)
    brk = min((b for b in fresh if int(b["idx"]) == newest_idx),
              key=lambda b: abs(float(b["trigger_price"])
                                - float(b["broken_swing_price"])))
    broken = float(brk["broken_swing_price"])
    trigger = float(brk["trigger_price"])
    median_range = float((df["high"] - df["low"]).median())
    if not median_range > 0:
        # A window with no range at all cannot tell decisive from marginal, and
        # a break measured against zero would score 1.0 on a dead instrument.
        return {"matched": False, "score": 0.0,
                "details": {"reason": "window has no bar range to measure against",
                            "direction": direction, "event": event}}

    age = last_idx - int(brk["idx"])
    # A break printed on the current bar keeps the whole recency term; one at
    # the far edge of the window keeps 1/(max_age+1) of it rather than zero,
    # because it is still inside the window the setup asked for.
    recency = (max_age + 1 - age) / (max_age + 1) if max_age >= 0 else 1.0
    strength = min(1.0, abs(trigger - broken)
                   / (median_range * DECISIVE_BREAK_RANGES))
    score = EVENT_RECENCY_WEIGHT * recency + (1 - EVENT_RECENCY_WEIGHT) * strength
    return {"matched": True, "score": round(score, 4),
            "details": {"type": brk["type"], "choch": bool(brk.get("choch")),
                        "event": event, "direction": direction,
                        "broken_swing_price": round(broken, 8),
                        "trigger_price": round(trigger, 8),
                        "displacement_ranges": round(
                            abs(trigger - broken) / median_range, 4),
                        "median_bar_range": round(median_range, 8),
                        "age_bars": age, "n_breaks": len(breaks),
                        "n_swings": len(swings)}}


register_kind("market_structure_break", _eval_market_structure_break,
                params=("direction", "event", "lookback", "max_age", "timeframe"),
                choices={"direction": ("bullish", "bearish"),
                         "event": ("bos", "choch")})


def _eval_event_sequence(params: dict, instrument, now: datetime) -> dict:
    """Did `first` print BEFORE `then`? — the gap the whole lane was missing.

    Every other kind in this file answers "is X true now". A setup composed of
    three of them is a BAG: `advanced_smc_long` fired on "a sweep happened AND a
    gap exists somewhere in the last five days AND volume is 1.5x", in any
    order, on any leg. ICT is a sequence model. Sweep-then-break is a reversal;
    break-then-sweep is the same two events describing a trend that just got
    tested and held — the opposite trade. A bag scores both identically.

    Two events, not N, on purpose: two is enough to state an ordering, and the
    canonical three-step read (sweep → CHoCH → FVG) composes as two legs on the
    same setup without this evaluator having to grow a parser.

    Params:
      first        — the trigger: "sweep" | "structure_break" | "choch"
                     | "fair_value_gap"
      then         — the confirmation, same vocabulary
      direction    — "bullish" | "bearish" (applied to BOTH events; a bullish
                     sequence is a swept low then an upside break)
      lookback     — bars loaded (default 90)
      max_gap_bars — how many bars may separate them (default 8)
      max_age      — how many bars ago the CONFIRMATION may have printed
                     (default 5)
      timeframe    — bar timeframe (default "1d")
    """
    first = (params or {}).get("first", "sweep")
    then = (params or {}).get("then", "structure_break")
    direction = (params or {}).get("direction", "bullish")
    lookback = int((params or {}).get("lookback", 90))
    max_gap_bars = int((params or {}).get("max_gap_bars", 8))
    max_age = int((params or {}).get("max_age", 5))
    timeframe = (params or {}).get("timeframe", "1d")

    if direction not in ("bullish", "bearish"):
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown direction {direction!r}"}}
    # Named rather than silently returning no events: an unrecognised event
    # would otherwise make this leg permanently unmatched and indistinguishable
    # from a quiet market — the exact failure PARAM_CHOICES exists to stop, and
    # the registry can only check the values it was given, not a typo in a row
    # written by the strategy generator before the check ran.
    unknown = [e for e in (first, then) if e not in _SEQUENCE_EVENTS]
    if unknown:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown event(s) {unknown}",
                            "accepted": list(_SEQUENCE_EVENTS)}}
    if max_gap_bars < 1:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "max_gap_bars must be at least 1 — the "
                                      "two events cannot share a bar and still "
                                      "be ordered"}}

    df, swings, reason = _smc_frame(instrument, lookback, now, timeframe)
    if reason:
        return {"matched": False, "score": 0.0, "details": {"reason": reason}}

    bullish = direction == "bullish"
    last_idx = len(df) - 1
    confirmations = [i for i in _event_indices(df, swings, then, bullish)
                     if last_idx - i <= max_age]
    if not confirmations:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"no {then} in the last {max_age} bars",
                            "first": first, "then": then,
                            "direction": direction}}

    # Newest confirmation first, but keep looking past it. Taking `max()` alone
    # would throw away a complete sequence whenever a LATER unaccompanied
    # confirmation existed — a second break continuing the same move is common,
    # and it would have silently voided the sweep→break that preceded it.
    all_triggers = _event_indices(df, swings, first, bullish)
    confirm_idx = trigger_idx = None
    for candidate in sorted(confirmations, reverse=True):
        # The closest trigger before this confirmation: if the sweep repeated,
        # the one the break actually followed is the last of them.
        preceding = [i for i in all_triggers
                     if i < candidate and candidate - i <= max_gap_bars]
        if preceding:
            confirm_idx, trigger_idx = candidate, max(preceding)
            break
    if confirm_idx is None:
        # The interesting no-match, and worth spelling out in `details`: the
        # confirmation IS there. A bag-of-legs setup would have scored this bar.
        return {"matched": False, "score": 0.0,
                "details": {"reason": (f"{then} printed at bar "
                                       f"{max(confirmations)} with no {first} "
                                       f"in the {max_gap_bars} bars before it"),
                            "confirmation_idx": max(confirmations),
                            "n_confirmations": len(confirmations),
                            "n_triggers_in_window": len(all_triggers),
                            "first": first, "then": then,
                            "direction": direction}}
    triggers = [i for i in all_triggers
                if i < confirm_idx and confirm_idx - i <= max_gap_bars]

    gap = confirm_idx - trigger_idx
    age = last_idx - confirm_idx
    recency = (max_age + 1 - age) / (max_age + 1) if max_age >= 0 else 1.0
    # gap == 1 is back-to-back and scores full; gap == max_gap_bars is the edge
    # of what the setup asked for and scores zero on this term, not on the whole
    # leg — the ordering still held, it just held loosely.
    tightness = 1.0 - (gap - 1) / max(max_gap_bars - 1, 1)
    score = EVENT_RECENCY_WEIGHT * recency + (1 - EVENT_RECENCY_WEIGHT) * tightness
    return {"matched": True, "score": round(max(0.0, min(1.0, score)), 4),
            "details": {"first": first, "then": then, "direction": direction,
                        "trigger_idx": trigger_idx,
                        "confirmation_idx": confirm_idx,
                        "gap_bars": gap, "age_bars": age,
                        "n_triggers": len(triggers),
                        "n_confirmations": len(confirmations)}}


register_kind("event_sequence", _eval_event_sequence,
                params=("first", "then", "direction", "lookback",
                        "max_gap_bars", "max_age", "timeframe"),
                choices={"first": _SEQUENCE_EVENTS, "then": _SEQUENCE_EVENTS,
                         "direction": ("bullish", "bearish")})


# ══════════════════════════════════════════════════════════════════════════
# Phase 37b — Seasonality: the evidence already sitting in the timestamps
# ══════════════════════════════════════════════════════════════════════════

# Turn-of-month window, in calendar days either side of the month boundary.
# Lakonishok & Smidt's original definition is the last TRADING day of a month
# through the third of the next; three calendar days either side is the closest
# a calendar-day rule gets to it, and a calendar-day rule is what this lane can
# actually apply — crypto trades weekends and has no trading-day calendar at
# all, and PriceData carries no exchange calendar for the ones that do.
TURN_OF_MONTH_WINDOW_DAYS = 3

# Buckets that are a mode's REMAINDER rather than one of its seasons, keyed by
# mode. Every bucket of `day_of_week`, `month_of_year` and `time_of_day` names a
# season — a Tuesday is a thing that recurs. `turn_of_month` is the odd one out:
# it splits the calendar in two and only one half is the claim, so "rest" is
# every ordinary mid-month day and its mean is the instrument's own drift with
# the calendar effect removed. Scored, it is reliably positive on anything in a
# multi-year uptrend, which is how `advanced_seasonal_turn_long` came to fire on
# the 15th of the month — a seasonality setup that ignored the season. Asked
# from inside such a bucket the evaluator reports where `now` landed and
# declines to measure, the same refusal it makes below for too few observations.
SEASONAL_BASELINE_BUCKETS = {"turn_of_month": ("rest",)}

# |t| at which a seasonal bucket scores 1.0. Two is the two-sided 95% critical
# value for a large sample — the conventional line between "this bucket's mean
# differs from zero" and "this is what noise looks like". A bucket at t=1 scores
# 0.5, which is the right shape: half a signal, not half an edge.
SEASONAL_T_FULL_SCORE = 2.0


def _seasonal_bucket(ts: datetime, mode: str):
    """The calendar bucket `ts` falls in, in UTC, or None for an unknown mode.

    UTC and said so in `details`, rather than a guessed exchange clock: the
    instruments this lane scans settle in four time zones and PriceData names
    none of them, so localising would put a New York afternoon bar on the wrong
    weekday for half the year and call the result seasonality.
    """
    t = _as_utc(ts)
    if mode == "day_of_week":
        return t.strftime("%A")
    if mode == "month_of_year":
        return t.strftime("%B")
    if mode == "time_of_day":
        return f"{t.hour:02d}:00Z"
    if mode == "turn_of_month":
        days_in_month = calendar.monthrange(t.year, t.month)[1]
        at_turn = (t.day <= TURN_OF_MONTH_WINDOW_DAYS
                   or t.day > days_in_month - TURN_OF_MONTH_WINDOW_DAYS)
        return "turn" if at_turn else "rest"
    return None


def _eval_seasonal_bias(params: dict, instrument, now: datetime) -> dict:
    """Calendar effect measured on THIS instrument's own history.

    Day-of-week, turn-of-month, month-of-year, time-of-day. No new data source,
    no schema: PriceData timestamps were always evidence and nothing in this
    lane had ever read them as such.

    The honest part is the refusal, and there are two of them. A published
    seasonal effect is a claim about a universe; what matters to a trade is
    whether THIS symbol shows it, and with how many observations. Below
    `min_observations` this returns matched=False with the count and
    `mean_return_pct=None` — not measured, not zero. Above it the score is a
    t-statistic, so a bucket whose mean is large only because its dispersion is
    enormous scores low rather than high.

    The second refusal is about WHEN the question is asked. A mode whose
    vocabulary includes a remainder bucket — see SEASONAL_BASELINE_BUCKETS — is
    only making a claim inside its own window, so asked from outside it this
    reports where `now` landed and measures nothing. Without that, the
    turn-of-month leg measured the mean of every ordinary mid-month day, which
    is the instrument's drift, and a setup built on the calendar took trades on
    the 15th.

    What `n_observations` is NOT: it counts BARS in the bucket, not seasons. A
    `month_of_year` bucket over three years of daily bars holds ~60 daily
    returns and THREE Februaries, and sixty overlapping days inside three
    Februaries are nothing like sixty independent observations of a February
    effect. `day_of_week` and `turn_of_month` do not have this problem — each
    of their observations is a different week or a different month — which is
    why the seeded pack uses those two and why a setup reaching for
    `month_of_year` has to raise `min_observations` on purpose.

    Params:
      mode              — "day_of_week" | "turn_of_month" | "month_of_year"
                          | "time_of_day"
      direction         — "bullish" (bucket's mean return positive) | "bearish"
      lookback_days     — calendar days of history to measure over (default 1095,
                          three years)
      min_observations  — below this the bucket is reported, never scored
                          (default 20)
      min_edge_pct      — minimum |mean| per bar, in percent (default 0.05)
      timeframe         — bar timeframe (default "1d"; "time_of_day" needs an
                          intraday one or every bar lands in one bucket)
    """
    mode = (params or {}).get("mode", "day_of_week")
    direction = (params or {}).get("direction", "bullish")
    lookback_days = int((params or {}).get("lookback_days", 1095))
    timeframe = (params or {}).get("timeframe", "1d")
    try:
        min_observations = int((params or {}).get("min_observations", 20))
        min_edge_pct = float((params or {}).get("min_edge_pct", 0.05))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "bad numeric param"}}

    if direction not in ("bullish", "bearish"):
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown direction {direction!r}"}}
    bucket_now = _seasonal_bucket(now, mode)
    if bucket_now is None:
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown mode {mode!r}",
                            "accepted": ["day_of_week", "turn_of_month",
                                         "month_of_year", "time_of_day"]}}
    if bucket_now in SEASONAL_BASELINE_BUCKETS.get(mode, ()):
        # The season is not on. Nothing here is measured, so every measurement
        # is None rather than 0.0 — a zero would read on the flag as "we looked
        # at the calendar effect and there is none", when what happened is that
        # `now` is not in the window the effect is claimed for.
        return {"matched": False, "score": 0.0,
                "details": {"mode": mode, "bucket": bucket_now,
                            "direction": direction, "measured": False,
                            "n_observations": None, "mean_return_pct": None,
                            "t_stat": None, "lookback_days": lookback_days,
                            "timeframe": timeframe, "tz": "UTC",
                            "reason": (f"{_as_utc(now).date()} is not in the "
                                       f"{mode} window — {bucket_now!r} is the "
                                       f"remainder of the calendar, not a "
                                       f"season, and its mean is drift")}}

    bars = _bars_since(instrument, now - timedelta(days=lookback_days), now,
                       timeframe=timeframe)
    # A return belongs to the bar it CLOSED on, so the bucket is that bar's own
    # calendar position. Attributing it to the previous bar would answer a
    # different question — "what happens the day after a Tuesday" — and would
    # shift the whole result by one bucket without changing its shape, which is
    # the kind of error a plausible-looking number hides indefinitely.
    sample = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1]["close"]
        if prev_close <= 0:
            continue
        if _seasonal_bucket(bars[i]["timestamp"], mode) != bucket_now:
            continue
        sample.append((bars[i]["close"] / prev_close - 1.0) * 100.0)

    n = len(sample)
    base = {"mode": mode, "bucket": bucket_now, "direction": direction,
            "n_observations": n, "min_observations": min_observations,
            "lookback_days": lookback_days, "timeframe": timeframe,
            "tz": "UTC"}
    if n < min_observations:
        # None, not 0.0. There is no measurement here to report and a confident
        # zero would read on the flag as "we looked and there is no edge".
        return {"matched": False, "score": 0.0,
                "details": {**base, "measured": False,
                            "mean_return_pct": None, "t_stat": None,
                            "reason": (f"{n} observations of {bucket_now}, "
                                       f"need {min_observations} before this "
                                       f"is an average rather than an anecdote")}}

    mean_pct = statistics.fmean(sample)
    sd = statistics.stdev(sample) if n >= 2 else 0.0
    # sd == 0 means every observation was identical, which real prices do not
    # do; it is a synthetic series or a stale feed. The t-statistic is undefined
    # there (not infinite in any useful sense), so it is reported as None and
    # the score falls back to the raw edge against its own threshold.
    t_stat = (mean_pct / (sd / math.sqrt(n))) if sd > 0 else None
    positive = sum(1 for r in sample if r > 0)
    share_positive = positive / n

    want_up = direction == "bullish"
    matched = (mean_pct >= min_edge_pct) if want_up else (mean_pct <= -min_edge_pct)
    if t_stat is not None:
        score = min(1.0, abs(t_stat) / SEASONAL_T_FULL_SCORE)
    else:
        score = min(1.0, abs(mean_pct) / max(min_edge_pct * 2, 1e-9))
    return {"matched": matched, "score": round(score if matched else 0.0, 4),
            "details": {**base, "measured": True,
                        "mean_return_pct": round(mean_pct, 6),
                        "stdev_pct": round(sd, 6),
                        "t_stat": round(t_stat, 4) if t_stat is not None else None,
                        "share_positive": round(share_positive, 4),
                        "min_edge_pct": min_edge_pct}}


register_kind("seasonal_bias", _eval_seasonal_bias,
                params=("mode", "direction", "lookback_days",
                        "min_observations", "min_edge_pct", "timeframe"),
                choices={"mode": ("day_of_week", "turn_of_month",
                                  "month_of_year", "time_of_day"),
                         "direction": ("bullish", "bearish")})


# ══════════════════════════════════════════════════════════════════════════
# Phase 37c — Perpetual funding CARRY (the other way to read FundingRate)
# ══════════════════════════════════════════════════════════════════════════

# Binance settles perpetual funding every eight hours.
FUNDING_INTERVALS_PER_DAY = 3

# Binance's base funding rate: the level funding reverts to when neither side is
# paying up for leverage. It annualises to 0.0001 × 3 × 365 = 10.95%, which is
# why `min_annualized_pct` must sit ABOVE that — a threshold at or below the
# base rate fires on a market with no positioning skew at all and calls it carry.
FUNDING_BASE_RATE = 0.0001

# Floor on raw snapshot count, matching the 30 rows `FundingExtremeRule` demands
# before it will compute a z-score. The two readings of this table agree about
# when the table has anything to say; disagreeing would let one lane trade a
# symbol the other considers uncovered.
MIN_FUNDING_SNAPSHOTS = 30


def _eval_funding_carry(params: dict, instrument, now: datetime) -> dict:
    """Persistently positive funding pays the SHORT. Persistently negative pays
    the long. The carry is the trade.

    How this differs from `funding_rate_extreme`, and how it can CONTRADICT it
    ---------------------------------------------------------------------------

    `signals.rules.flow_rules.FundingExtremeRule` reads the same table and takes
    the opposite kind of measurement:

      - it reads the DEVIATION — a z-score of the latest rate against its own
        30-day mean — and fires contrarian, on the thesis that a crowded book
        gets squeezed within hours or days;
      - this reads the LEVEL and its PERSISTENCE, on the thesis that whoever
        holds the paying side collects, over weeks.

    Because one is a deviation and the other a level, they routinely disagree,
    and the disagreement is not a bug in either:

      - Funding sits at +0.08% for a month, then eases to +0.02%. The z-score is
        deeply NEGATIVE, so `funding_rate_extreme` publishes LONG ("crowded
        shorts"). Funding is still positive and still persistent, so this
        publishes SHORT. Two live signals, one table, opposite directions.
      - Funding spikes for a day to +0.15%. Now they AGREE on SHORT — and that
        is the dangerous case, not the reassuring one. `AssetBot.decide()` votes
        by headcount, so one dataset read twice arrives as two independent
        confirmations, at the exact moment the book is most crowded and the
        squeeze `funding_rate_extreme` exists to catch is most likely.

    Neither of those is a reason to suppress one lane. It is a reason for both
    to say what they measured, which is why `details` carries `measures` and the
    base-rate multiple: a reviewer looking at a bullish and a bearish card on
    one perp can see in one line that they are the same table read two ways.

    Params:
      direction           — "collect_short" (funding persistently POSITIVE, the
                            short is paid) | "collect_long" (persistently
                            negative)
      lookback_days       — window over which carry is averaged (default 14)
      min_annualized_pct  — minimum annualised carry (default 15.0; see
                            FUNDING_BASE_RATE for why not lower)
      min_persistence     — fraction of snapshots on the paying side (default 0.8)
      min_days_covered    — distinct UTC days that must carry data (default 10)
    """
    direction = (params or {}).get("direction", "collect_short")
    lookback_days = int((params or {}).get("lookback_days", 14))
    try:
        min_annualized_pct = float((params or {}).get("min_annualized_pct", 15.0))
        min_persistence = float((params or {}).get("min_persistence", 0.8))
        min_days_covered = int((params or {}).get("min_days_covered", 10))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "bad numeric param"}}

    if direction not in ("collect_short", "collect_long"):
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown direction {direction!r}"}}

    try:
        from market_data.models import FundingRate
    except Exception:
        return {"matched": False, "score": 0.0,
                "details": {"reason": "FundingRate unavailable"}}
    from django.db.models import Avg, Count, Q
    from django.db.models.functions import TruncDate

    # FundingRate has no FK to Instrument — it is keyed by the exchange's own
    # perp symbol, so a symbol this install stores as "BTCUSD" simply finds
    # nothing under Binance's "BTCUSDT". The symbol is echoed into `details`
    # rather than guessed at, because a silent zero-row read on a mis-mapped
    # symbol looks exactly like a market with no funding skew.
    symbol = getattr(instrument, "symbol", "") or ""
    # Counted and averaged IN THE DATABASE, never materialised. `save_funding`
    # writes one row per @markPrice tick — around 2,880 a day per symbol, not
    # the three settlements a day the rate itself changes on — and
    # `cleanup_funding` keeps 60 days of them, so a fortnight's window is tens
    # of thousands of rows and this evaluator runs once per crypto symbol per
    # scan. A LIMIT would be the wrong repair: the tail of the window is a few
    # hours of ticks, so capping the read would collapse `days_covered` and make
    # the leg refuse every densely-streamed symbol. Aggregating asks the same
    # questions of the whole window and carries back four numbers rather than
    # forty thousand rows.
    window = (FundingRate.objects
              .filter(symbol__iexact=symbol,
                      timestamp__gte=now - timedelta(days=lookback_days),
                      timestamp__lte=now)
              # Meta.ordering is ["-timestamp"]; left on, it joins the DISTINCT
              # clause of the day count below and turns it into a count of ticks.
              .order_by())
    want_positive = direction == "collect_short"
    paying_side = (Q(funding_rate__gt=0) if want_positive
                   else Q(funding_rate__lt=0))
    agg = window.aggregate(n=Count("id"), mean_rate=Avg("funding_rate"),
                           paying=Count("id", filter=paying_side))
    n = int(agg["n"] or 0)
    base = {"symbol": symbol, "direction": direction, "n_snapshots": n,
            "lookback_days": lookback_days, "measures": "level_and_persistence"}
    if n < MIN_FUNDING_SNAPSHOTS:
        return {"matched": False, "score": 0.0,
                "details": {**base, "measured": False,
                            "annualized_pct": None, "persistence": None,
                            "reason": (f"{n} funding snapshots for {symbol!r}, "
                                       f"need {MIN_FUNDING_SNAPSHOTS}")}}

    # UTC explicitly, because TruncDate otherwise buckets in the server's local
    # zone and would move a Binance settlement across a day boundary — the same
    # reason `_as_utc` exists for the seasonality lane.
    days_covered = (window
                    .annotate(funding_day=TruncDate("timestamp",
                                                    tzinfo=_dt_timezone.utc))
                    .values("funding_day").distinct().count())
    if days_covered < min_days_covered:
        # Funding is paid three times a day, so a fortnight's carry claim needs
        # most of that fortnight actually observed. Without this, one afternoon
        # of snapshots during a streamer outage becomes a two-week average.
        return {"matched": False, "score": 0.0,
                "details": {**base, "measured": False,
                            "annualized_pct": None, "persistence": None,
                            "days_covered": days_covered,
                            "min_days_covered": min_days_covered,
                            "reason": (f"only {days_covered} of the last "
                                       f"{lookback_days} days carry funding data")}}

    mean_rate = float(agg["mean_rate"] or 0.0)
    annualized_pct = mean_rate * FUNDING_INTERVALS_PER_DAY * 365 * 100.0
    persistence = int(agg["paying"] or 0) / n

    sign_ok = (mean_rate > 0) if want_positive else (mean_rate < 0)
    matched = (sign_ok and abs(annualized_pct) >= min_annualized_pct
               and persistence >= min_persistence)
    # Persistence multiplies rather than adds: carry that pays four days in five
    # is worth four fifths of carry that always pays, and a huge mean assembled
    # out of a few spikes should not outrank a steady one.
    size = min(1.0, abs(annualized_pct) / max(min_annualized_pct * 2, 1e-9))
    return {"matched": matched, "score": round(size * persistence if matched else 0.0, 4),
            "details": {**base, "measured": True,
                        "days_covered": days_covered,
                        "mean_rate_per_interval": round(mean_rate, 10),
                        "annualized_pct": round(annualized_pct, 4),
                        "base_rate_multiple": round(mean_rate / FUNDING_BASE_RATE, 3),
                        "persistence": round(persistence, 4),
                        "min_annualized_pct": min_annualized_pct,
                        "min_persistence": min_persistence,
                        "min_days_covered": min_days_covered}}


register_kind("funding_carry", _eval_funding_carry,
                params=("direction", "lookback_days", "min_annualized_pct",
                        "min_persistence", "min_days_covered"),
                choices={"direction": ("collect_short", "collect_long")})


# ══════════════════════════════════════════════════════════════════════════
# Phase 38 — Post-earnings-announcement drift, as a HELD position
# ══════════════════════════════════════════════════════════════════════════
#
# The event family this lane already had — `earnings_surprise`, `news_volume`,
# `calendar_event` — reads an event as a SAME-DAY reaction: something printed
# inside the lookback, so fire now. Post-earnings-announcement drift is the
# opposite claim. The documented anomaly is not the gap on the print; it is
# that prices keep moving in the direction of the surprise for weeks after it,
# because the market under-reacts and institutions accumulate slowly. So the
# entry is deliberately LATE — the announcement bar is conceded, not chased —
# and the position is HELD. The holding period is part of the thesis rather
# than a detail, which is why the setup that carries this leg argues for its
# own `suggested_horizon_days` instead of inheriting a default.
#
# What this lane can see, and the three things it cannot
# ------------------------------------------------------
# The EPS pair lives in `market_data.EconomicEvent`, written by
# `scraping.scrapers.earnings_calendar._persist_earnings` as one row per issuer
# per print date: title "{SYMBOL} Earnings", `forecast` the consensus estimate,
# `actual` the reported number, both as strings. That is the entire schema, and
# it leaves three quantities the PEAD literature is built on unavailable. Each
# is reported as None with the reason attached, because a card that shows a
# surprise and says nothing about the rest invites the reader to assume they
# were checked:
#
#   surprise_percentile         The literature sorts on SUE — the surprise
#                               standardised against its own history — and
#                               trades the extreme deciles. Ranking needs a
#                               per-issuer history of surprises, and
#                               `check_economic_calendar` fetches [today,
#                               today+14] with nothing backfilling behind it,
#                               so whatever history exists is shaped by scraper
#                               uptime rather than by the issuer. A raw percent
#                               threshold is the substitute this data supports;
#                               calling it a percentile would be a different
#                               and stronger claim.
#   pre_announcement_drift_pct  Only the single final `forecast` survives — no
#                               revision path, no whisper number — so the drift
#                               INTO the print, the other half of the
#                               literature, is not measurable here at all.
#   announcement_reaction_pct   `_event_datetime` approximates the print time
#                               from FMP's session code (bmo → 13:30Z, amc →
#                               21:00Z) and PriceData carries daily bars, so
#                               the bar containing the print cannot be split
#                               into reaction and drift. `move_since_print_pct`
#                               is the CUMULATIVE move, under a name that says
#                               so.
#
# On replay. Everything read here is bounded by `now`, so this evaluator needs
# no `as_of` flag. One honest caveat: the calendar row is UPDATED IN PLACE when
# a later fetch carries the reported EPS, so a replay reads the row's final
# contents. The only window where that differs from what was knowable is
# between the release and the fetch that captured it — bounded by the
# half-hourly cadence of `check_economic_calendar`, and PEAD_MIN_AGE_HOURS puts
# every entry a full day past it.

# Minimum |actual − estimate| ÷ |estimate|, in percent, before this lane will
# call a print a surprise. 10% is the bar `signals.rules.fundamental_rules
# .EarningsSurpriseRule` applies to the same two numbers, and matching it is
# deliberate: that rule imports `scraping.models.EarningsEvent`, a model this
# install does not have, so it catches the ImportError and returns None on
# every symbol — it is inert today. Picking a different bar would mean the two
# lanes disagreed about what counts as a surprise on the day someone repairs
# its data source, which is exactly when nobody would be looking here.
PEAD_MIN_SURPRISE_PCT = 10.0

# How stale a print must be before this lane will enter. Twenty-four hours is
# one full session past either FMP session code, and therefore the smallest
# delay that puts the entry AFTER the announcement bar rather than inside it —
# and the announcement bar is the reaction, which is the trade this evaluator
# exists not to take.
PEAD_MIN_AGE_HOURS = 24.0

# The far edge of the entry window. Not a claim about where the drift ends —
# the literature follows it for a quarter — but about where a NEW position
# stops being early: five days keeps the entry near the print while leaving
# room for the daily scan to miss a pass or two.
PEAD_MAX_AGE_DAYS = 5.0

# |surprise| at which the size term scores 1.0, as a multiple of the threshold
# the setup asked for: twice the bar is full marks. Same shape `funding_carry`
# uses, so two legs in one pack do not mean different things by a full score.
PEAD_FULL_SCORE_MULTIPLE = 2.0

# Half the score is how big the surprise was, half is how much of the entry
# window is left. The even split is deliberate and untuned — the same admission
# EVENT_RECENCY_WEIGHT makes — because nothing measured on this platform yet
# justifies preferring a huge stale surprise over a modest fresh one.
PEAD_SURPRISE_WEIGHT = 0.5

# How far before a print to look for the close that preceded it. Ten days
# covers a long weekend plus a market holiday on a five-day instrument; below
# that, a Thanksgiving-week print would find no pre-print bar and the move
# would be reported as unmeasured on a symbol with perfectly good data.
PEAD_PRE_PRINT_LOOKBACK_DAYS = 10


def _eps_value(raw) -> Optional[float]:
    """The EPS in an EconomicEvent string column, or None if it is not a number.

    None is the entire point. `actual` is blank until a fetch covers the print
    day AFTER the release, and `float(raw or 0)` would turn every not-yet-
    reported print into a company that earned exactly zero — a total miss
    against any positive estimate, pointing short, on no evidence whatsoever.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _earnings_prints(instrument, now: datetime) -> list[dict]:
    """This instrument's earnings rows that had already printed by `now`.

    Newest first, each {"at", "actual", "estimate"} with both EPS numbers
    parsed and None where the column is blank or junk.

    `datetime__lte=now` is not tidiness, it is the whole safety of this lane.
    The table's PURPOSE is to hold FUTURE prints — `check_economic_calendar`
    fetches [today, today+14] every half hour — so an unbounded "latest
    earnings row" query returns next quarter's SCHEDULED print, and on a scan
    replaying history it would hand back prints that had not happened on the
    day being replayed with the reported EPS already filled in.
    """
    symbol = (getattr(instrument, "symbol", "") or "").strip()
    if not symbol:
        return []
    from django.db.models import Q
    from market_data.models import EconomicEvent

    # `_persist_earnings` writes exactly one shape — title "{SYMBOL} Earnings",
    # currency_affected the symbol — so both branches below reach every row it
    # writes. `stock_bot._has_upcoming_earnings` asks this table two ways too,
    # and its currency branch is the same one written below; where the two part
    # is the title. It accepts the symbol as a SUBSTRING of the title, which is
    # right for a BLACKOUT and wrong here: on a one- or two-letter ticker that
    # matches earnings rows belonging to other issuers entirely, and a false
    # match makes the blackout decline a trade while it would make this one
    # take a trade. So the title branch here pins the whole title instead.
    rows = (EconomicEvent.objects
            .filter(Q(title__iexact=f"{symbol} Earnings")
                    | Q(currency_affected__iexact=symbol,
                        title__icontains="earnings"),
                    datetime__lte=now)
            .order_by("-datetime")
            .values("datetime", "actual", "forecast"))
    return [{"at": r["datetime"], "actual": _eps_value(r["actual"]),
             "estimate": _eps_value(r["forecast"])} for r in rows]


def _move_since_print(instrument, printed_at: datetime, now: datetime) -> dict:
    """Close-to-close move from before the print to the latest bar at `now`.

    The split is on the print's UTC calendar DAY, not on its timestamp, and the
    difference matters: a daily bar is stamped at the START of its session, so
    a before-open print at 13:30Z sits INSIDE a bar timestamped 00:00Z that
    day. Splitting on the timestamp would push the reaction session onto the
    pre-print side and report a drift measured from after the move it is
    supposed to contain. Splitting on the day costs the opposite, smaller
    error: for an after-close print the pre-print session's own move is
    included, which is noise from before the news rather than a reading taken
    after it.

    Returns every endpoint it used, so a reader can see exactly what was
    compared instead of trusting a single percentage.
    """
    day_start = _as_utc(printed_at).replace(hour=0, minute=0, second=0,
                                            microsecond=0)
    bars = _bars_since(instrument,
                       day_start - timedelta(days=PEAD_PRE_PRINT_LOOKBACK_DAYS),
                       now)
    before = [b for b in bars if _as_utc(b["timestamp"]) < day_start]
    after = [b for b in bars if _as_utc(b["timestamp"]) >= day_start]
    if not before or not after or before[-1]["close"] <= 0:
        return {"move_since_print_pct": None, "pre_print_close": None,
                "last_close": None, "n_bars_since_print": len(after),
                "move_unmeasured_because": (
                    "no bar on both sides of the print day within "
                    f"{PEAD_PRE_PRINT_LOOKBACK_DAYS} days of it")}
    pre_close, last_close = before[-1]["close"], after[-1]["close"]
    return {"move_since_print_pct": round((last_close / pre_close - 1.0) * 100.0, 4),
            "pre_print_close": pre_close, "last_close": last_close,
            "pre_print_bar_at": before[-1]["timestamp"].isoformat(),
            "last_bar_at": after[-1]["timestamp"].isoformat(),
            "n_bars_since_print": len(after)}


def _eval_pead(params: dict, instrument, now: datetime) -> dict:
    """Post-earnings-announcement drift: enter after the print, hold the drift.

    Fires when a print that has ALREADY happened beat (or missed) its estimate
    by enough, in the direction the setup trades, and is old enough to be past
    its own reaction bar but young enough that a new position is still early.

    The score blends two terms, PEAD_SURPRISE_WEIGHT apart: how far past the
    threshold the surprise was, and how much of the entry window is left. A
    print at the far edge of the window still matches — the ordering held, the
    edge is simply older — but it scores half of what the same print scored on
    day one, which is the shape the drift itself has.

    Params:
      direction        — "bullish" (positive surprise) | "bearish" (negative)
      min_surprise_pct — |actual − estimate| ÷ |estimate|, percent
                         (default PEAD_MIN_SURPRISE_PCT)
      min_age_hours    — earliest entry after the print (default 24)
      max_age_days     — latest entry after the print (default 5)
      min_move_pct     — require the move SINCE the print to agree with the
                         surprise by at least this much, in percent. 0.0
                         (the default) asks nothing of price.
    """
    direction = (params or {}).get("direction", "bullish")
    try:
        min_surprise_pct = float((params or {}).get("min_surprise_pct",
                                                    PEAD_MIN_SURPRISE_PCT))
        min_age_hours = float((params or {}).get("min_age_hours",
                                                  PEAD_MIN_AGE_HOURS))
        max_age_days = float((params or {}).get("max_age_days",
                                                PEAD_MAX_AGE_DAYS))
        min_move_pct = float((params or {}).get("min_move_pct", 0.0))
    except (TypeError, ValueError):
        return {"matched": False, "score": 0.0,
                "details": {"reason": "bad numeric param"}}

    if direction not in ("bullish", "bearish"):
        return {"matched": False, "score": 0.0,
                "details": {"reason": f"unknown direction {direction!r}"}}

    max_age_hours = max_age_days * 24.0
    if max_age_hours <= min_age_hours:
        # An empty entry window is a leg that can never fire, and from the
        # outside it looks exactly like an issuer that never surprises.
        return {"matched": False, "score": 0.0,
                "details": {"reason": (f"empty entry window: max_age_days="
                                       f"{max_age_days} does not reach past "
                                       f"min_age_hours={min_age_hours}")}}

    symbol = (getattr(instrument, "symbol", "") or "").strip()
    # Attached to every return below. Naming what was NOT measured beside what
    # was is the difference between a card that reports a surprise and a card
    # that implies the surprise was ranked against anything.
    unmeasured = {
        "surprise_percentile": None,
        "pre_announcement_drift_pct": None,
        "announcement_reaction_pct": None,
        "unmeasured_because": (
            "EconomicEvent stores one estimate and one actual per print and "
            "nothing else: no revision path (so no pre-announcement drift), no "
            "retained per-issuer surprise history (so no SUE percentile — the "
            "calendar fetch only ever looks forward), and a print time "
            "approximated to the session against daily bars (so the "
            "announcement bar cannot be separated from the drift)"),
    }
    base = {"symbol": symbol, "direction": direction,
            "min_surprise_pct": min_surprise_pct,
            "min_age_hours": min_age_hours, "max_age_days": max_age_days,
            "min_move_pct": min_move_pct, **unmeasured}

    prints = _earnings_prints(instrument, now)
    # `estimate` is tested for truth rather than for None on purpose: a zero
    # consensus makes the percent surprise a division by zero, and "infinitely
    # above a zero estimate" is not a magnitude any threshold can rank.
    reported = [p for p in prints
                if p["actual"] is not None and p["estimate"]]
    if not reported:
        return {"matched": False, "score": 0.0,
                "details": {**base, "measured": False, "surprise_pct": None,
                            "n_rows": len(prints), "n_prior_prints_with_eps": 0,
                            "move_since_print_pct": None,
                            "reason": (
                                f"no reported EPS pair for {symbol!r} on or "
                                f"before this scan ({len(prints)} calendar "
                                f"row(s) matched; `actual` is written only by "
                                f"a fetch that covered the print day after the "
                                f"release and nothing backfills it)")}}

    latest = reported[0]
    # A row NEWER than the one being traded, still carrying no EPS, is the
    # interesting near-miss: the print that matters has happened and its
    # numbers have not been captured yet, which is a data gap rather than a
    # quiet market. Counted so the card can tell the two apart.
    newer_unreported = sum(1 for p in prints if p["at"] > latest["at"])
    age_hours = (now - latest["at"]).total_seconds() / 3600.0
    surprise_pct = ((latest["actual"] - latest["estimate"])
                    / abs(latest["estimate"]) * 100.0)
    base = {**base, "measured": True,
            "printed_at": latest["at"].isoformat(),
            "actual_eps": latest["actual"], "estimate_eps": latest["estimate"],
            "surprise_pct": round(surprise_pct, 4),
            "age_hours": round(age_hours, 2),
            "n_prior_prints_with_eps": len(reported) - 1,
            "n_newer_prints_without_eps": newer_unreported}

    if age_hours < min_age_hours or age_hours > max_age_hours:
        # Price is deliberately not read here. The window decides on the
        # calendar alone, so a query per instrument per scan would buy a number
        # nothing in this branch can use — and None says "not measured", which
        # is exactly what happened.
        window = ("inside its own reaction — the announcement bar is the trade "
                  "this leg concedes" if age_hours < min_age_hours
                  else "past the entry window — a new position here is late")
        return {"matched": False, "score": 0.0,
                "details": {**base, "move_since_print_pct": None,
                            "reason": f"print is {age_hours:.1f}h old, {window}"}}

    want_up = direction == "bullish"
    sign_ok = (surprise_pct > 0) if want_up else (surprise_pct < 0)
    if not sign_ok or abs(surprise_pct) < min_surprise_pct:
        return {"matched": False, "score": 0.0,
                "details": {**base, "move_since_print_pct": None,
                            "reason": (f"surprise {surprise_pct:+.2f}% does not "
                                       f"clear {min_surprise_pct:.2f}% in the "
                                       f"{direction} direction")}}

    move = _move_since_print(instrument, latest["at"], now)
    move_pct = move["move_since_print_pct"]
    if min_move_pct > 0:
        # An unmeasured move cannot satisfy a requirement about the move. This
        # is the one branch where treating None as 0.0 would be a trade rather
        # than a missing number.
        agrees = move_pct is not None and (
            move_pct >= min_move_pct if want_up else move_pct <= -min_move_pct)
        if not agrees:
            return {"matched": False, "score": 0.0,
                    "details": {**base, **move,
                                "reason": ("the market has not moved with the "
                                           "surprise since the print"
                                           if move_pct is not None
                                           else "move since the print is not measured")}}

    size = min(1.0, abs(surprise_pct)
               / max(min_surprise_pct * PEAD_FULL_SCORE_MULTIPLE, 1e-9))
    freshness = max(0.0, min(1.0, (max_age_hours - age_hours)
                             / max(max_age_hours - min_age_hours, 1e-9)))
    score = (PEAD_SURPRISE_WEIGHT * size
             + (1.0 - PEAD_SURPRISE_WEIGHT) * freshness)
    return {"matched": True, "score": round(max(0.0, min(1.0, score)), 4),
            "details": {**base, **move,
                        "size_term": round(size, 4),
                        "freshness_term": round(freshness, 4)}}


register_kind("pead", _eval_pead,
                params=("direction", "min_surprise_pct", "min_age_hours",
                        "max_age_days", "min_move_pct"),
                choices={"direction": ("bullish", "bearish")})


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
    # Phase 37
    "market_structure_break", "event_sequence", "seasonal_bias",
    "funding_carry",
    # Phase 38 — the event family's first HELD position
    "pead",
]
