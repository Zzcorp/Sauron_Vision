"""Candlestick and chart pattern detection.

Hand-rolled (no TA-Lib dependency required). Returns lists of detection
dicts: {pattern, idx, ts, direction, confidence}.
"""
import logging

logger = logging.getLogger(__name__)


def _body(row):
    return abs(row["close"] - row["open"])


def _range(row):
    return row["high"] - row["low"]


def _upper_wick(row):
    return row["high"] - max(row["open"], row["close"])


def _lower_wick(row):
    return min(row["open"], row["close"]) - row["low"]


def detect_candlestick_patterns(df):
    """Detect common candlestick patterns in OHLCV DataFrame.

    Returns a list of detection dicts.
    """
    patterns = []
    if df is None or len(df) < 3:
        return patterns

    for i in range(2, len(df)):
        cur = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2]
        rng = _range(cur)
        if rng <= 0:
            continue
        body = _body(cur)
        body_pct = body / rng

        # ---- Doji: body < 10% of range ---------------------------------
        if body_pct < 0.1:
            patterns.append({
                "pattern": "doji", "idx": i, "ts": df.index[i],
                "direction": "neutral", "confidence": 0.5,
            })

        # ---- Hammer: small body, lower wick >= 2x body, upper wick small
        lw = _lower_wick(cur)
        uw = _upper_wick(cur)
        if body > 0 and lw >= 2 * body and uw <= body * 0.5 and body_pct < 0.4:
            patterns.append({
                "pattern": "hammer", "idx": i, "ts": df.index[i],
                "direction": "bullish", "confidence": 0.6,
            })

        # ---- Shooting star: inverted hammer at top
        if body > 0 and uw >= 2 * body and lw <= body * 0.5 and body_pct < 0.4:
            patterns.append({
                "pattern": "shooting_star", "idx": i, "ts": df.index[i],
                "direction": "bearish", "confidence": 0.6,
            })

        # ---- Bullish engulfing
        prev_body = _body(prev)
        if prev["close"] < prev["open"] and cur["close"] > cur["open"] \
                and cur["open"] <= prev["close"] and cur["close"] >= prev["open"] \
                and body > prev_body:
            patterns.append({
                "pattern": "bullish_engulfing", "idx": i, "ts": df.index[i],
                "direction": "bullish", "confidence": 0.7,
            })

        # ---- Bearish engulfing
        if prev["close"] > prev["open"] and cur["close"] < cur["open"] \
                and cur["open"] >= prev["close"] and cur["close"] <= prev["open"] \
                and body > prev_body:
            patterns.append({
                "pattern": "bearish_engulfing", "idx": i, "ts": df.index[i],
                "direction": "bearish", "confidence": 0.7,
            })

        # ---- Morning star: down, small, up
        if i >= 2:
            p2_down = prev2["close"] < prev2["open"]
            p_small = _body(prev) < _body(prev2) * 0.5
            cur_up = cur["close"] > cur["open"] and cur["close"] > (prev2["open"] + prev2["close"]) / 2
            if p2_down and p_small and cur_up:
                patterns.append({
                    "pattern": "morning_star", "idx": i, "ts": df.index[i],
                    "direction": "bullish", "confidence": 0.75,
                })

        # ---- Evening star
        if i >= 2:
            p2_up = prev2["close"] > prev2["open"]
            p_small = _body(prev) < _body(prev2) * 0.5
            cur_dn = cur["close"] < cur["open"] and cur["close"] < (prev2["open"] + prev2["close"]) / 2
            if p2_up and p_small and cur_dn:
                patterns.append({
                    "pattern": "evening_star", "idx": i, "ts": df.index[i],
                    "direction": "bearish", "confidence": 0.75,
                })

    return patterns


def detect_chart_patterns(df):
    """Detect basic chart patterns: double top, double bottom.

    Uses fractal pivots; full H&S / triangle detection is left to a more
    advanced module. Returns detection dicts.
    """
    patterns = []
    if df is None or len(df) < 30:
        return patterns

    try:
        from signals.smc.pivots import get_swings
    except Exception:
        return patterns

    swings = get_swings(df, left=3, right=3)
    highs = [s for s in swings if s["type"] == "H"]
    lows = [s for s in swings if s["type"] == "L"]

    # Double top: two consecutive highs within 1% of each other
    for i in range(1, len(highs)):
        a, b = highs[i - 1], highs[i]
        if a["price"] == 0:
            continue
        if abs(b["price"] - a["price"]) / a["price"] < 0.01 and b["idx"] - a["idx"] >= 5:
            patterns.append({
                "pattern": "double_top", "idx": b["idx"], "ts": b["ts"],
                "direction": "bearish", "confidence": 0.65,
                "level": (a["price"] + b["price"]) / 2,
            })

    # Double bottom
    for i in range(1, len(lows)):
        a, b = lows[i - 1], lows[i]
        if a["price"] == 0:
            continue
        if abs(b["price"] - a["price"]) / a["price"] < 0.01 and b["idx"] - a["idx"] >= 5:
            patterns.append({
                "pattern": "double_bottom", "idx": b["idx"], "ts": b["ts"],
                "direction": "bullish", "confidence": 0.65,
                "level": (a["price"] + b["price"]) / 2,
            })

    return patterns
