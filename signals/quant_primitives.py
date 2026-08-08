"""Phase-34 quantitative primitives — math used by the advanced evaluators.

These are pure helper functions, not evaluators. They take number arrays
(closes, returns, OHLC bars) and return single scalars or small dicts that
the evaluators (in `evaluators_advanced.py`) consume.

What's here:
  - hurst_exponent(closes)           — regime classifier (0..1; 0.5=random)
  - garch_lite_forecast(closes)      — 1-step-ahead realised σ via EWMA
  - cvar(returns, alpha=0.05)        — Conditional VaR (avg loss in worst α%)
  - anchored_vwap(bars, anchor)      — price-volume mean from anchor onwards
  - bootstrap_quantile(samples, q)   — empirical quantile via bootstrap
  - rolling_zscore(values, window)   — z-score of last value vs window
  - linear_slope(values)             — least-squares slope per index step

All functions are tolerant of short inputs — return a sentinel (None or 0)
rather than raising, so evaluators can gracefully degrade.
"""
from __future__ import annotations

import math
import random
from typing import Iterable, Optional


def _safe_floats(values: Iterable) -> list[float]:
    out = []
    for v in values:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


# ── Regime classifier — Hurst exponent ────────────────────────────────────

def hurst_exponent(closes: Iterable, max_lag: int = 20) -> Optional[float]:
    """Estimate Hurst H via rescaled-range over multiple lags.

    Interpretation:
      H ≈ 0.5  → random walk (efficient market)
      H > 0.55 → trending / persistent
      H < 0.45 → mean-reverting / anti-persistent

    Mean-reverting strategies prefer H < 0.45.
    Trend-following strategies prefer H > 0.55.

    Returns None when input is too short to be meaningful.
    """
    series = _safe_floats(closes)
    n = len(series)
    if n < max_lag + 5:
        return None

    # Log returns are stationary enough for Hurst.
    rets = []
    for i in range(1, n):
        if series[i - 1] <= 0:
            return None
        rets.append(math.log(series[i] / series[i - 1]))
    if len(rets) < max_lag + 2:
        return None

    lags = range(2, min(max_lag, len(rets) // 2))
    try:
        log_rs, log_lag = [], []
        for lag in lags:
            chunks = [rets[i:i + lag] for i in range(0, len(rets) - lag + 1, lag)]
            rs_vals = []
            for ch in chunks:
                if len(ch) < 2:
                    continue
                m = sum(ch) / len(ch)
                z = [x - m for x in ch]
                cum = []
                acc = 0
                for x in z:
                    acc += x
                    cum.append(acc)
                R = max(cum) - min(cum)
                S = math.sqrt(sum((x - m) ** 2 for x in ch) / len(ch))
                if S > 0 and R > 0:
                    rs_vals.append(R / S)
            if not rs_vals:
                continue
            avg = sum(rs_vals) / len(rs_vals)
            if avg <= 0:
                continue
            log_rs.append(math.log(avg))
            log_lag.append(math.log(lag))

        if len(log_rs) < 4:
            return None
        # Linear regression slope = Hurst.
        n_points = len(log_lag)
        mean_x = sum(log_lag) / n_points
        mean_y = sum(log_rs) / n_points
        num = sum((log_lag[i] - mean_x) * (log_rs[i] - mean_y) for i in range(n_points))
        den = sum((x - mean_x) ** 2 for x in log_lag)
        if den == 0:
            return None
        h = num / den
        return max(0.0, min(1.0, h))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def hurst_regime_label(h: Optional[float]) -> str:
    """Map H value → human label. None → 'unknown'."""
    if h is None:
        return "unknown"
    if h > 0.55:
        return "trending"
    if h < 0.45:
        return "mean_reverting"
    return "random"


# ── Volatility forecast — EWMA-style 1-step-ahead σ ───────────────────────

def garch_lite_forecast(closes: Iterable, lambda_decay: float = 0.94) -> Optional[float]:
    """1-step-ahead realised volatility via RiskMetrics-style EWMA.

    σ²_t = λ × σ²_{t-1} + (1-λ) × r²_{t-1}

    Returns the 1-day-ahead σ as a fraction (0.015 = 1.5%/day).
    Industry-standard λ=0.94. None on insufficient data.
    """
    series = _safe_floats(closes)
    if len(series) < 30:
        return None
    rets = []
    for i in range(1, len(series)):
        if series[i - 1] <= 0:
            return None
        rets.append(math.log(series[i] / series[i - 1]))

    var = sum(r ** 2 for r in rets[:30]) / 30
    for r in rets[30:]:
        var = lambda_decay * var + (1 - lambda_decay) * r ** 2
    return math.sqrt(max(var, 0.0))


# ── Conditional Value-at-Risk (Expected Shortfall) ────────────────────────

def cvar(returns: Iterable, alpha: float = 0.05) -> Optional[float]:
    """Mean of worst α% returns. Negative number = expected tail loss.

    cvar 0.05 = "average loss on the worst 5% of days".
    More tail-aware than VaR which is just the threshold.
    Used for sizing: capital × CVaR caps the worst-case 1-day drawdown.
    """
    rets = _safe_floats(returns)
    if not rets or alpha <= 0 or alpha >= 1:
        return None
    rets.sort()
    cutoff = max(1, int(len(rets) * alpha))
    tail = rets[:cutoff]
    return sum(tail) / len(tail) if tail else None


# ── Anchored VWAP ─────────────────────────────────────────────────────────

def anchored_vwap(bars: Iterable[dict]) -> Optional[float]:
    """Volume-weighted average of typical price, summed from the anchor bar.

    `bars` is an iterable of {high, low, close, volume} dicts (oldest first).
    Caller is responsible for slicing from the anchor point (event date,
    earnings, prior session, etc.).

    Returns the AVWAP, or None if total volume is zero.
    """
    total_pv, total_v = 0.0, 0.0
    for b in bars:
        try:
            h = float(b["high"]); l = float(b["low"]); c = float(b["close"])
            v = float(b.get("volume", 0))
        except (KeyError, TypeError, ValueError):
            continue
        tp = (h + l + c) / 3
        total_pv += tp * v
        total_v += v
    return total_pv / total_v if total_v > 0 else None


# ── Bootstrap quantile (used by counterfactual sizing) ────────────────────

def bootstrap_quantile(samples: Iterable, q: float = 0.25,
                        n_resamples: int = 500,
                        rng_seed: Optional[int] = None) -> Optional[float]:
    """Empirical quantile via simple bootstrap. q=0.25 = lower-quartile.

    Used for counterfactual sizing: 'what's the conservative expectation
    if I sample with replacement from historical R-multiples?'
    """
    s = _safe_floats(samples)
    if len(s) < 5:
        return None
    rng = random.Random(rng_seed) if rng_seed is not None else random
    means = []
    for _ in range(n_resamples):
        resample = [rng.choice(s) for _ in range(len(s))]
        means.append(sum(resample) / len(resample))
    means.sort()
    idx = max(0, min(len(means) - 1, int(len(means) * q)))
    return means[idx]


# ── Rolling z-score ───────────────────────────────────────────────────────

def rolling_zscore(values: Iterable, window: int = 20) -> Optional[float]:
    """Z-score of the most recent value vs the prior `window` values.

    Used everywhere: 'is this candle's volume unusually high?',
    'is sentiment at an extreme?', 'is open interest spiking?'.
    """
    s = _safe_floats(values)
    if len(s) < window + 1:
        return None
    recent = s[-1]
    prior = s[-(window + 1):-1]
    mean = sum(prior) / len(prior)
    var = sum((x - mean) ** 2 for x in prior) / len(prior)
    sd = math.sqrt(var) if var > 0 else 0
    if sd == 0:
        return 0.0
    return (recent - mean) / sd


# ── Linear regression slope ───────────────────────────────────────────────

def linear_slope(values: Iterable) -> Optional[float]:
    """Least-squares slope of `values` vs index. Used for 'is X rising?'.

    Sign-aware: positive = rising, negative = falling.
    """
    s = _safe_floats(values)
    n = len(s)
    if n < 3:
        return None
    mean_x = (n - 1) / 2
    mean_y = sum(s) / n
    num = sum((i - mean_x) * (s[i] - mean_y) for i in range(n))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den > 0 else None
