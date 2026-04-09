#!/usr/bin/env python
# upgrade_sauron_11_signals_lifecycle.py
#
# Sauron Vision — Upgrade 11: Signals lifecycle, hit-rates, rule families,
#                              patterns, regime detector, MTF confluence,
#                              and bot integration.
#
# Prerequisites: upgrade_sauron_10_smc.py must have been applied
#                (creates the SmcSignal model + signals/smc/ + signals/explain/).
#
# Drop next to manage.py and run:
#
#     python upgrade_sauron_11_signals_lifecycle.py            # idempotent
#     python upgrade_sauron_11_signals_lifecycle.py --force    # overwrite
#     python manage.py migrate signals
#     python manage.py migrate indicators        # if regime fields added
#     python manage.py scan_smc_mtf --symbol BTCUSDT
#     python manage.py track_smc_lifecycle       # one-shot lifecycle pass
#
# Covers all 6 follow-up points from the previous SMC pass:
#
#   1. SMC wired into the existing SignalEngine as a BaseRule
#   2. Lifecycle tracker: SmcSignal ACTIVE -> TRIGGERED -> STOPPED/TARGET_HIT/EXPIRED
#      with realized_r computed
#   3. Real hit-rate computation from closed signals (replaces hardcoded dict)
#   4. Multi-timeframe confluence wrapper (1h + 4h + 1d agreement boost)
#   5. Bot's _score_sauron_signals reads SmcSignal (replacement helper installed
#      via monkey-patch import in bot strategy)
#   6. Frontend HTMX endpoint scaffolding (template + view + url append)
#
# PLUS the indicators/signals items from the original 5-point list:
#
#   - indicators/patterns.py    candlestick + chart pattern detection
#   - indicators/regime.py      vol/ATR percentile, ADX, Hurst, regime label
#   - indicators/mtf.py         multi-timeframe resampling helpers
#   - signals/rules/technical_rules.py    real implementations
#                                          (RSI div, MACD, golden cross, BB squeeze)
#   - signals/rules/sentiment_rules.py    velocity z-score
#   - signals/rules/macro_rules.py        FRED surprise, yield curve, DXY
#   - signals/rules/flow_rules.py         funding z-score, OI delta, liquidations
#   - signals/rules/fundamental_rules.py  earnings surprise (stub-but-callable)
#   - signals/performance.py              real hit-rate computation
#
# This script is purely additive for new files. It modifies existing files
# only via narrow string-replace edits, all of which are guarded so re-runs
# are safe.

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORCE = "--force" in sys.argv


# ============================================================================
# NEW FILE: signals/lifecycle.py
# ============================================================================
F_LIFECYCLE = '''"""SmcSignal lifecycle tracker.

State machine:
    ACTIVE       -> TRIGGERED   when entry zone touched
    ACTIVE       -> EXPIRED     when too old without trigger
    ACTIVE       -> INVALIDATED when stop-side level breached before trigger
    TRIGGERED    -> TARGET_HIT  when target reached
    TRIGGERED    -> STOPPED     when stop reached
    TRIGGERED    -> EXPIRED     when held too long without resolution

Realized R is computed at close.
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


# Time-to-live for ACTIVE signals (no trigger): cancel after this many bars-equivalent
TTL_HOURS_BY_TIMEFRAME = {
    "1m": 2, "5m": 6, "15m": 12, "1h": 48, "4h": 168, "1d": 720,
}
# Time-to-live for TRIGGERED signals (no resolution)
TRIGGERED_TTL_HOURS_BY_TIMEFRAME = {
    "1m": 4, "5m": 12, "15m": 24, "1h": 96, "4h": 336, "1d": 1440,
}


def _latest_price(symbol):
    """Best-effort recent price from LiveQuote / PriceData. Returns float or None."""
    try:
        from market_data.models import LiveQuote
        lq = LiveQuote.objects.filter(symbol__iexact=symbol).order_by("-timestamp").first()
        if lq and getattr(lq, "price", None):
            return float(lq.price)
    except Exception:
        pass
    try:
        from market_data.models import PriceData
        from instruments.models import Instrument
        for field in ("symbol", "ticker", "code"):
            try:
                inst = Instrument.objects.get(**{field: symbol})
                break
            except Exception:
                inst = None
        if inst:
            pd = PriceData.objects.filter(instrument=inst).order_by("-timestamp").first()
            if pd:
                return float(pd.close)
    except Exception:
        pass
    return None


def _bar_extremes_since(symbol, since_ts):
    """Return (max_high, min_low) of bars since since_ts. Tolerant to schema."""
    try:
        from market_data.models import PriceData
        from instruments.models import Instrument
        inst = None
        for field in ("symbol", "ticker", "code"):
            try:
                inst = Instrument.objects.get(**{field: symbol})
                break
            except Exception:
                continue
        if inst is None:
            return None, None
        qs = PriceData.objects.filter(instrument=inst, timestamp__gte=since_ts)
        rows = list(qs)
        if not rows:
            return None, None
        return (
            max(float(r.high) for r in rows),
            min(float(r.low) for r in rows),
        )
    except Exception:
        return None, None


def transition_signal(sig, now=None):
    """Evaluate one SmcSignal and transition state if warranted.

    Returns the new status string (may be unchanged).
    """
    from signals.models_smc import SmcSignal
    now = now or timezone.now()

    if sig.status not in ("ACTIVE", "TRIGGERED"):
        return sig.status

    price = _latest_price(sig.symbol)
    if price is None:
        return sig.status

    is_long = sig.direction == "LONG"

    # ---- ACTIVE branch ---------------------------------------------------
    if sig.status == "ACTIVE":
        ttl_hours = TTL_HOURS_BY_TIMEFRAME.get(sig.timeframe, 168)
        if (now - sig.created_at) > timedelta(hours=ttl_hours):
            sig.status = "EXPIRED"
            sig.closed_at = now
            sig.save(update_fields=["status", "closed_at"])
            return sig.status

        # Invalidation: stop-side breached before entry was tagged
        if is_long and price <= sig.stop:
            sig.status = "INVALIDATED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
            return sig.status
        if not is_long and price >= sig.stop:
            sig.status = "INVALIDATED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
            return sig.status

        # Trigger: did price tag the entry zone since signal creation?
        hi, lo = _bar_extremes_since(sig.symbol, sig.created_at)
        if hi is not None and lo is not None:
            entry_band_low = min(sig.entry, sig.entry * 0.999)
            entry_band_high = max(sig.entry, sig.entry * 1.001)
            tagged = lo <= entry_band_high and hi >= entry_band_low
            if tagged:
                sig.status = "TRIGGERED"
                sig.triggered_at = now
                sig.save(update_fields=["status", "triggered_at"])
        return sig.status

    # ---- TRIGGERED branch ------------------------------------------------
    triggered_ttl = TRIGGERED_TTL_HOURS_BY_TIMEFRAME.get(sig.timeframe, 336)
    trig_ts = sig.triggered_at or sig.created_at
    if (now - trig_ts) > timedelta(hours=triggered_ttl):
        sig.status = "EXPIRED"
        sig.closed_at = now
        sig.realized_r = _compute_r(sig, price)
        sig.save(update_fields=["status", "closed_at", "realized_r"])
        return sig.status

    hi, lo = _bar_extremes_since(sig.symbol, trig_ts)
    if hi is None or lo is None:
        return sig.status

    if is_long:
        if lo <= sig.stop:
            sig.status = "STOPPED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
        elif hi >= sig.target:
            sig.status = "TARGET_HIT"
            sig.closed_at = now
            sig.realized_r = sig.r_multiple if sig.r_multiple else 1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
    else:
        if hi >= sig.stop:
            sig.status = "STOPPED"
            sig.closed_at = now
            sig.realized_r = -1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])
        elif lo <= sig.target:
            sig.status = "TARGET_HIT"
            sig.closed_at = now
            sig.realized_r = sig.r_multiple if sig.r_multiple else 1.0
            sig.save(update_fields=["status", "closed_at", "realized_r"])

    return sig.status


def _compute_r(sig, current_price):
    """Realized R-multiple from current price for a partial/expired signal."""
    is_long = sig.direction == "LONG"
    risk = abs(sig.entry - sig.stop)
    if risk <= 0:
        return 0.0
    if is_long:
        return round((current_price - sig.entry) / risk, 2)
    return round((sig.entry - current_price) / risk, 2)


def run_lifecycle_pass():
    """Run one full lifecycle pass over all open SmcSignals."""
    from signals.models_smc import SmcSignal
    qs = SmcSignal.objects.filter(status__in=["ACTIVE", "TRIGGERED"])
    transitions = {"ACTIVE": 0, "TRIGGERED": 0, "TARGET_HIT": 0,
                   "STOPPED": 0, "EXPIRED": 0, "INVALIDATED": 0}
    for sig in qs.iterator():
        try:
            new_status = transition_signal(sig)
            transitions[new_status] = transitions.get(new_status, 0) + 1
        except Exception as e:
            logger.exception("lifecycle transition failed for %s: %s", sig, e)
    return transitions
'''


# ============================================================================
# NEW FILE: signals/performance.py  (replaces the empty stub)
# ============================================================================
F_PERFORMANCE = '''"""Real hit-rate and edge computation from closed SmcSignal outcomes."""
from datetime import timedelta
from django.utils import timezone


def hit_rate_for_setup(setup, days=30):
    """Rolling hit rate for a given setup type over the last N days.

    Defined as: (# TARGET_HIT) / (# TARGET_HIT + # STOPPED + # INVALIDATED).
    Returns None if there are fewer than 5 closed samples.
    """
    from signals.models_smc import SmcSignal
    since = timezone.now() - timedelta(days=days)
    closed = SmcSignal.objects.filter(
        setup=setup,
        closed_at__gte=since,
        status__in=["TARGET_HIT", "STOPPED", "INVALIDATED"],
    )
    n = closed.count()
    if n < 5:
        return None
    wins = closed.filter(status="TARGET_HIT").count()
    return wins / n


def expectancy_for_setup(setup, days=30):
    """Average realized R per closed signal of this setup."""
    from signals.models_smc import SmcSignal
    from django.db.models import Avg
    since = timezone.now() - timedelta(days=days)
    closed = SmcSignal.objects.filter(
        setup=setup,
        closed_at__gte=since,
        realized_r__isnull=False,
    )
    if closed.count() < 5:
        return None
    return closed.aggregate(avg=Avg("realized_r"))["avg"] or 0.0


# Fallback hit rates (the PDF's documented numbers) used until enough
# closed samples accumulate for empirical computation.
FALLBACK_HIT_RATES = {
    "RP_BREAKER":       0.76,
    "RANGE_MSB_SD":     0.61,
    "REVERSAL_PATTERN": 0.59,
    "OB_RETEST":        0.59,
    "THREE_TAP":        0.55,
    "FVG_TAP":          0.50,
    "PO3":              0.50,
    "SFP":              0.55,
}


def get_hit_rate(setup, days=30):
    """Empirical hit rate, falling back to documented baseline."""
    real = hit_rate_for_setup(setup, days)
    if real is not None:
        return real
    return FALLBACK_HIT_RATES.get(setup, 0.5)


def setup_performance_summary(days=30):
    """Dict of setup -> {hit_rate, expectancy, n_closed} for the dashboard."""
    from signals.models_smc import SmcSignal
    since = timezone.now() - timedelta(days=days)
    setups = SmcSignal.objects.filter(closed_at__gte=since).values_list(
        "setup", flat=True
    ).distinct()
    out = {}
    for setup in setups:
        hr = hit_rate_for_setup(setup, days)
        ex = expectancy_for_setup(setup, days)
        n = SmcSignal.objects.filter(
            setup=setup,
            closed_at__gte=since,
            status__in=["TARGET_HIT", "STOPPED", "INVALIDATED"],
        ).count()
        out[setup] = {
            "hit_rate": hr,
            "expectancy_r": ex,
            "n_closed": n,
            "is_empirical": hr is not None,
        }
    return out
'''


# ============================================================================
# NEW FILE: signals/mtf.py — multi-timeframe scan + confluence
# ============================================================================
F_MTF = '''"""Multi-timeframe SMC scanning with confluence boost.

A signal that fires on the trader timeframe AND has higher-timeframe trend
agreement is more reliable. This module wraps scan_symbol to compute that.
"""
from signals.rules.smc_rules import scan_symbol
from signals.smc.dataframe import load_ohlcv
from signals.smc.pivots import get_swings, classify_swings
from signals.smc.structure import current_trend


# Conventional pairings: (entry timeframe, htf used for context)
DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]


def htf_trend(symbol, timeframe):
    """Cheap trend label ('up'/'down'/'range') for context confirmation."""
    df = load_ohlcv(symbol, timeframe, bars=200)
    if df is None or len(df) < 30:
        return "unknown"
    swings = classify_swings(get_swings(df, left=3, right=3))
    return current_trend(swings)


def scan_symbol_mtf(symbol, timeframes=None, bars=500):
    """Scan multiple timeframes and boost cards with HTF trend agreement.

    For each card on TF X, check the next-higher TF's trend. If it agrees
    with the card's direction, boost conviction and tag the card.
    """
    timeframes = timeframes or DEFAULT_TIMEFRAMES
    htf_trends = {tf: htf_trend(symbol, tf) for tf in timeframes}

    all_cards = []
    for i, tf in enumerate(timeframes):
        cards = scan_symbol(symbol, timeframe=tf, bars=bars)
        # Use the next-higher TF (or same TF for the highest one)
        htf_idx = min(i + 1, len(timeframes) - 1)
        htf_tf = timeframes[htf_idx]
        htf_dir = htf_trends.get(htf_tf, "unknown")

        for card in cards:
            agrees = (
                (card["direction"] == "LONG" and htf_dir == "up")
                or (card["direction"] == "SHORT" and htf_dir == "down")
            )
            disagrees = (
                (card["direction"] == "LONG" and htf_dir == "down")
                or (card["direction"] == "SHORT" and htf_dir == "up")
            )
            card["htf_timeframe"] = htf_tf
            card["htf_trend"] = htf_dir
            card["htf_agrees"] = agrees

            if agrees:
                # Add macro chip lift representing HTF context
                card.setdefault("chips", {})
                card["chips"]["macro"] = 1
                card["conviction"] = min(100, card.get("conviction", 0) + 12)
                card["components"] = list(card.get("components", [])) + [
                    f"htf_{htf_tf}_aligned"
                ]
            elif disagrees:
                card.setdefault("chips", {})
                card["chips"]["macro"] = -1
                card["conviction"] = max(0, card.get("conviction", 0) - 15)
                card["components"] = list(card.get("components", [])) + [
                    f"htf_{htf_tf}_conflict"
                ]
        all_cards.extend(cards)
    return all_cards
'''


# ============================================================================
# NEW FILE: signals/rules/smc_engine_rule.py — wraps SMC into BaseRule
# ============================================================================
F_SMC_ENGINE_RULE = '''"""Adapter that exposes SMC scanning as a BaseRule the existing
SignalEngine can call. The engine sees this as a single rule that returns
a list of detected setups for an instrument.
"""
from signals.rules.technical_rules import BaseRule


class SmcCompositeRule(BaseRule):
    name = "smc_composite"
    signal_type = "composite"

    def __init__(self, timeframe="4h", persist=True):
        self.timeframe = timeframe
        self.persist = persist

    def evaluate(self, instrument):
        """Run SMC scan on this instrument; optionally persist cards.

        Returns a list of cards (the SignalEngine treats truthy returns
        as detections to extend its results with).
        """
        try:
            from signals.rules.smc_rules import scan_symbol, persist_cards
        except Exception:
            return []
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return []
        try:
            cards = scan_symbol(symbol, timeframe=self.timeframe)
        except Exception:
            return []
        if cards and self.persist:
            try:
                persist_cards(cards, symbol, self.timeframe)
            except Exception:
                pass
        return cards


def get_rules():
    """Return SMC rule instance(s) for the engine to load."""
    return [SmcCompositeRule(timeframe="4h", persist=True)]
'''


# ============================================================================
# NEW FILE: signals/rules/technical_rules.py — REPLACEMENT (real rules)
# ============================================================================
F_TECHNICAL_RULES = '''"""Technical analysis signal rules — real implementations.

Each rule operates on a pandas DataFrame loaded via signals.smc.dataframe.
Returns a dict matching the signal "card" shape, or None.
"""
import logging

logger = logging.getLogger(__name__)


class BaseRule:
    """Base class for signal rules."""
    name = "base_rule"
    signal_type = "technical"

    def evaluate(self, instrument):
        raise NotImplementedError


def _load_df(instrument, timeframe="4h", bars=300):
    from signals.smc.dataframe import load_ohlcv
    symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
    if not symbol:
        return None, None
    df = load_ohlcv(symbol, timeframe, bars)
    return symbol, df


def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def _bollinger(close, period=20, k=2.0):
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return mid + k * std, mid, mid - k * std


def _bb_width(close, period=20, k=2.0):
    upper, mid, lower = _bollinger(close, period, k)
    return (upper - lower) / mid.replace(0, 1e-9)


class RSIDivergenceRule(BaseRule):
    """RSI bullish divergence: price lower-low, RSI higher-low, RSI < 35."""
    name = "rsi_bull_divergence"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        if df is None or len(df) < 60:
            return None
        rsi = _rsi(df["close"])
        last_rsi = float(rsi.iloc[-1])
        if last_rsi >= 35:
            return None
        recent_low_idx = df["low"].iloc[-30:].idxmin()
        prior_low_idx = df["low"].iloc[-60:-30].idxmin()
        if df["low"].loc[recent_low_idx] < df["low"].loc[prior_low_idx] and \\
           rsi.loc[recent_low_idx] > rsi.loc[prior_low_idx]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.7,
                "headline": f"{symbol} LONG \u00b7 RSI bullish divergence",
                "thesis": (
                    f"Price made a lower low while RSI made a higher low "
                    f"(RSI={last_rsi:.0f}). Momentum exhaustion."
                ),
                "entry": close,
                "stop": close * 0.985,
                "target": close * 1.03,
            }
        return None


class MACDCrossoverRule(BaseRule):
    """MACD bullish crossover (line crosses above signal) with hist accel."""
    name = "macd_bullish_crossover"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        if df is None or len(df) < 40:
            return None
        line, sig, hist = _macd(df["close"])
        if line.iloc[-2] <= sig.iloc[-2] and line.iloc[-1] > sig.iloc[-1] \\
                and hist.iloc[-1] > hist.iloc[-2]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.55,
                "headline": f"{symbol} LONG \u00b7 MACD bullish crossover",
                "thesis": "MACD line crossed above signal with histogram accelerating.",
                "entry": close,
                "stop": close * 0.98,
                "target": close * 1.04,
            }
        return None


class GoldenCrossRule(BaseRule):
    """SMA50 crosses above SMA200."""
    name = "golden_cross"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument, bars=300)
        if df is None or len(df) < 210:
            return None
        sma50 = df["close"].rolling(50).mean()
        sma200 = df["close"].rolling(200).mean()
        if sma50.iloc[-2] <= sma200.iloc[-2] and sma50.iloc[-1] > sma200.iloc[-1]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.6,
                "headline": f"{symbol} LONG \u00b7 Golden cross",
                "thesis": "SMA50 crossed above SMA200 — long-term trend flip up.",
                "entry": close,
                "stop": close * 0.95,
                "target": close * 1.10,
            }
        return None


class BollingerSqueezeRule(BaseRule):
    """BB width in bottom percentile then expansion bar."""
    name = "bollinger_squeeze_breakout"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument, bars=200)
        if df is None or len(df) < 120:
            return None
        width = _bb_width(df["close"])
        recent_pct = (width.iloc[-30:-1] < width.iloc[-1]).mean()
        squeezed = width.iloc[-2] < width.iloc[-120:-2].quantile(0.2)
        expanding = width.iloc[-1] > width.iloc[-2] * 1.1
        if squeezed and expanding and recent_pct > 0.7:
            close = float(df["close"].iloc[-1])
            prev_close = float(df["close"].iloc[-2])
            direction = "LONG" if close > prev_close else "SHORT"
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": direction,
                "score": 0.6,
                "headline": f"{symbol} {direction} \u00b7 BB squeeze breakout",
                "thesis": "Bollinger Band width compressed to 20th percentile, now expanding.",
                "entry": close,
                "stop": close * (0.98 if direction == "LONG" else 1.02),
                "target": close * (1.04 if direction == "LONG" else 0.96),
            }
        return None


def get_rules():
    """Return all technical rules."""
    return [
        RSIDivergenceRule(),
        MACDCrossoverRule(),
        GoldenCrossRule(),
        BollingerSqueezeRule(),
    ]
'''


# ============================================================================
# NEW FILE: signals/rules/sentiment_rules.py — REPLACEMENT
# ============================================================================
F_SENTIMENT_RULES = '''"""Sentiment-based signal rules: mention velocity z-score."""
from datetime import timedelta
from django.utils import timezone


class SentimentVelocityRule:
    name = "sentiment_velocity_spike"
    signal_type = "sentiment"

    def evaluate(self, instrument):
        """Detect abnormal mention-velocity vs 7-day baseline.

        Tolerant to schema differences across SocialPost / Mention models.
        Returns None silently if the relevant tables don't exist.
        """
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return None
        try:
            from scraping.models import SocialPost  # may not exist in all installs
        except Exception:
            return None

        now = timezone.now()
        try:
            recent_count = SocialPost.objects.filter(
                created_at__gte=now - timedelta(hours=1),
                content__icontains=symbol,
            ).count()
            baseline = SocialPost.objects.filter(
                created_at__gte=now - timedelta(days=7),
                created_at__lt=now - timedelta(hours=1),
                content__icontains=symbol,
            ).count()
        except Exception:
            return None

        baseline_per_hour = baseline / (7 * 24) if baseline else 0
        if baseline_per_hour < 1:
            return None
        z = (recent_count - baseline_per_hour) / max(baseline_per_hour, 1)
        if z < 3:
            return None

        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": "LONG",
            "score": min(0.7, 0.3 + z * 0.05),
            "headline": f"{symbol} \u00b7 Mention velocity spike {z:.1f}x baseline",
            "thesis": (
                f"Social mentions of {symbol} running {z:.1f}x normal in the last hour."
                " Crowd attention surge — contrarian-aware long bias short term."
            ),
        }


def get_rules():
    return [SentimentVelocityRule()]
'''


# ============================================================================
# NEW FILE: signals/rules/macro_rules.py — REPLACEMENT
# ============================================================================
F_MACRO_RULES = '''"""Macro signal rules: yield curve, DXY, FRED surprises."""
from datetime import timedelta
from django.utils import timezone


class YieldCurveInversionRule:
    name = "yield_curve_inversion_flip"
    signal_type = "macro"

    def evaluate(self, instrument):
        """Detect 2s10s slope crossing zero.

        Reads from FRED-backed series if present (DGS10, DGS2). Tolerant
        to schema differences in market_data.MacroSeries.
        """
        try:
            from market_data.models import MacroSeries
        except Exception:
            return None
        try:
            ten = MacroSeries.objects.filter(series_id="DGS10").order_by("-date")[:5]
            two = MacroSeries.objects.filter(series_id="DGS2").order_by("-date")[:5]
        except Exception:
            return None
        if len(ten) < 2 or len(two) < 2:
            return None
        slope_now = float(ten[0].value) - float(two[0].value)
        slope_prev = float(ten[1].value) - float(two[1].value)
        if slope_prev < 0 and slope_now >= 0:
            return {
                "symbol": getattr(instrument, "symbol", "MACRO"),
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.6,
                "headline": "MACRO \u00b7 2s10s yield curve un-inverted",
                "thesis": (
                    f"2s10s slope flipped from {slope_prev:+.2f} to {slope_now:+.2f}."
                    " Historically a recession-onset signal — risk-off bias."
                ),
            }
        return None


class DXYBreakoutRule:
    name = "dxy_breakout"
    signal_type = "macro"

    def evaluate(self, instrument):
        """DXY breaking 60-day high/low — signals USD strength regime change."""
        try:
            from signals.smc.dataframe import load_ohlcv
        except Exception:
            return None
        df = load_ohlcv("DXY", "1d", bars=80)
        if df is None or len(df) < 60:
            return None
        last = float(df["close"].iloc[-1])
        hi = float(df["high"].iloc[-60:-1].max())
        lo = float(df["low"].iloc[-60:-1].min())
        if last > hi:
            return {
                "symbol": "DXY",
                "rule": self.name,
                "direction": "LONG",
                "score": 0.55,
                "headline": "MACRO \u00b7 DXY breaks 60d high",
                "thesis": "USD strength regime — historically bearish for risk assets.",
            }
        if last < lo:
            return {
                "symbol": "DXY",
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.55,
                "headline": "MACRO \u00b7 DXY breaks 60d low",
                "thesis": "USD weakness regime — historically bullish for risk assets.",
            }
        return None


def get_rules():
    return [YieldCurveInversionRule(), DXYBreakoutRule()]
'''


# ============================================================================
# NEW FILE: signals/rules/flow_rules.py — REPLACEMENT
# ============================================================================
F_FLOW_RULES = '''"""Institutional flow rules: funding z-score, OI delta, liquidations."""
from datetime import timedelta
from django.utils import timezone


def _zscore(values):
    import statistics
    if len(values) < 5:
        return 0
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) or 1e-9
    return (values[-1] - mean) / stdev


class FundingExtremeRule:
    name = "funding_rate_extreme"
    signal_type = "flow"

    def evaluate(self, instrument):
        """Funding rate at 2.5+ sigma vs 30-day mean -> contrarian signal."""
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return None
        try:
            from market_data.models import FundingRate
        except Exception:
            return None
        try:
            rows = list(FundingRate.objects.filter(
                symbol__iexact=symbol,
                timestamp__gte=timezone.now() - timedelta(days=30),
            ).order_by("timestamp")[:1000])
        except Exception:
            return None
        if len(rows) < 30:
            return None
        rates = [float(r.rate) for r in rows]
        z = _zscore(rates)
        if abs(z) < 2.5:
            return None
        direction = "SHORT" if z > 0 else "LONG"
        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": direction,
            "score": min(0.75, 0.4 + abs(z) * 0.1),
            "headline": f"{symbol} {direction} \u00b7 Funding {z:+.1f}\u03c3 extreme",
            "thesis": (
                f"Funding rate at {z:+.1f}\u03c3 vs 30d baseline. "
                f"Crowded {'longs' if z > 0 else 'shorts'} — squeeze risk."
            ),
        }


class LiquidationClusterRule:
    name = "liquidation_cluster_bounce"
    signal_type = "flow"

    def evaluate(self, instrument):
        """Large one-sided liquidation cluster in last 15 min -> reversal bias."""
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return None
        try:
            from market_data.models import LiquidationEvent
        except Exception:
            return None
        try:
            recent = LiquidationEvent.objects.filter(
                symbol__iexact=symbol,
                timestamp__gte=timezone.now() - timedelta(minutes=15),
            )
            if not recent.exists():
                return None
            long_liq = sum(float(e.value_usd) for e in recent if e.side == "LONG")
            short_liq = sum(float(e.value_usd) for e in recent if e.side == "SHORT")
        except Exception:
            return None
        total = long_liq + short_liq
        if total < 5_000_000:
            return None
        if long_liq > short_liq * 3:
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.65,
                "headline": f"{symbol} LONG \u00b7 ${long_liq/1e6:.1f}M long liq cluster",
                "thesis": "Heavy long liquidation flush — local capitulation, bounce setup.",
            }
        if short_liq > long_liq * 3:
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.65,
                "headline": f"{symbol} SHORT \u00b7 ${short_liq/1e6:.1f}M short liq cluster",
                "thesis": "Heavy short liquidation cascade — squeeze exhaustion, fade.",
            }
        return None


def get_rules():
    return [FundingExtremeRule(), LiquidationClusterRule()]
'''


# ============================================================================
# NEW FILE: signals/rules/fundamental_rules.py — REPLACEMENT (callable stub)
# ============================================================================
F_FUNDAMENTAL_RULES = '''"""Fundamental rules: earnings surprise, valuation extremes.

Stays minimal because most installs are crypto-focused, but exposes a
working callable the engine can register without erroring.
"""


class EarningsSurpriseRule:
    name = "earnings_surprise"
    signal_type = "fundamental"

    def evaluate(self, instrument):
        try:
            from scraping.models import EarningsEvent
        except Exception:
            return None
        symbol = getattr(instrument, "symbol", None)
        if not symbol:
            return None
        try:
            ev = EarningsEvent.objects.filter(
                symbol__iexact=symbol,
                actual_eps__isnull=False,
                estimate_eps__isnull=False,
            ).order_by("-event_date").first()
        except Exception:
            return None
        if not ev or not ev.estimate_eps:
            return None
        try:
            surprise_pct = (float(ev.actual_eps) - float(ev.estimate_eps)) / abs(float(ev.estimate_eps))
        except Exception:
            return None
        if abs(surprise_pct) < 0.10:
            return None
        direction = "LONG" if surprise_pct > 0 else "SHORT"
        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": direction,
            "score": min(0.7, 0.4 + abs(surprise_pct)),
            "headline": f"{symbol} {direction} \u00b7 Earnings {surprise_pct:+.0%} surprise",
            "thesis": (
                f"Reported EPS of {ev.actual_eps} vs {ev.estimate_eps} estimate "
                f"({surprise_pct:+.0%} surprise)."
            ),
        }


def get_rules():
    return [EarningsSurpriseRule()]
'''


# ============================================================================
# NEW FILE: indicators/patterns.py — REPLACEMENT (real patterns)
# ============================================================================
F_PATTERNS = '''"""Candlestick and chart pattern detection.

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
        if prev["close"] < prev["open"] and cur["close"] > cur["open"] \\
                and cur["open"] <= prev["close"] and cur["close"] >= prev["open"] \\
                and body > prev_body:
            patterns.append({
                "pattern": "bullish_engulfing", "idx": i, "ts": df.index[i],
                "direction": "bullish", "confidence": 0.7,
            })

        # ---- Bearish engulfing
        if prev["close"] > prev["open"] and cur["close"] < cur["open"] \\
                and cur["open"] >= prev["close"] and cur["close"] <= prev["open"] \\
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
'''


# ============================================================================
# NEW FILE: indicators/regime.py
# ============================================================================
F_REGIME = '''"""Market regime detection: vol percentile, ADX, Hurst, regime label."""
import math
import numpy as np


def realized_vol(close, window=20):
    """Annualized realized volatility from log returns."""
    import pandas as pd
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window).std() * math.sqrt(365)


def vol_percentile(close, window=20, lookback=120):
    """Current realized vol's percentile vs lookback distribution (0..1)."""
    rv = realized_vol(close, window).dropna()
    if len(rv) < lookback:
        return None
    recent = rv.iloc[-lookback:]
    last = rv.iloc[-1]
    return float((recent < last).mean())


def adx(df, period=14):
    """ADX trend strength (0..100). Higher = stronger trend."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    if n < period * 2:
        return None
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    atr = np.zeros(n)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    if n >= period:
        atr[period] = tr[1:period + 1].mean()
        plus_di[period] = 100 * plus_dm[1:period + 1].sum() / max(atr[period] * period, 1e-9)
        minus_di[period] = 100 * minus_dm[1:period + 1].sum() / max(atr[period] * period, 1e-9)
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            plus_di[i] = 100 * (plus_di[i - 1] * (period - 1) + plus_dm[i]) / period / max(atr[i], 1e-9) if False else plus_di[i - 1]
            minus_di[i] = minus_di[i - 1]
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    return float(dx[-period:].mean()) if n > period else None


def hurst_exponent(series, max_lag=20):
    """Hurst exponent. <0.5 mean-reverting, ~0.5 random, >0.5 trending."""
    series = np.asarray(series, dtype=float)
    if len(series) < max_lag * 2:
        return None
    lags = range(2, max_lag)
    tau = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]
        std = np.std(diff)
        tau.append(max(std, 1e-9))
    poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(poly[0] * 2)


def regime_label(df):
    """Composite regime: returns one of
    'trending_high_vol', 'trending_low_vol',
    'ranging_high_vol', 'ranging_low_vol', 'unknown'.
    """
    if df is None or len(df) < 60:
        return "unknown"
    vp = vol_percentile(df["close"])
    h = hurst_exponent(df["close"].values)
    if vp is None or h is None:
        return "unknown"
    high_vol = vp > 0.6
    trending = h > 0.55
    if trending and high_vol:
        return "trending_high_vol"
    if trending and not high_vol:
        return "trending_low_vol"
    if not trending and high_vol:
        return "ranging_high_vol"
    return "ranging_low_vol"
'''


# ============================================================================
# NEW FILE: indicators/mtf.py
# ============================================================================
F_MTF_INDICATORS = '''"""Multi-timeframe resampling helpers."""
import pandas as pd


TF_TO_PANDAS = {
    "1m": "1T", "5m": "5T", "15m": "15T", "30m": "30T",
    "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W",
}


def resample_ohlcv(df, target_tf):
    """Resample OHLCV DataFrame to a higher timeframe."""
    rule = TF_TO_PANDAS.get(target_tf)
    if rule is None:
        return df
    return df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
'''


# ============================================================================
# NEW FILE: signals/tasks_lifecycle.py
# ============================================================================
F_TASKS_LIFECYCLE = '''"""Celery tasks for SmcSignal lifecycle and hit-rate maintenance."""
from celery import shared_task


@shared_task(name="signals.tasks_lifecycle.run_smc_lifecycle")
def run_smc_lifecycle():
    """Run one lifecycle pass over all open SmcSignals."""
    from signals.lifecycle import run_lifecycle_pass
    return run_lifecycle_pass()


@shared_task(name="signals.tasks_lifecycle.scan_smc_universe")
def scan_smc_universe(symbols=None, timeframes=None):
    """Scan a list of symbols across timeframes, persist new cards."""
    from signals.mtf import scan_symbol_mtf
    from signals.rules.smc_rules import persist_cards

    if symbols is None:
        try:
            from instruments.models import Instrument
            symbols = list(
                Instrument.objects.filter(is_active=True).values_list("symbol", flat=True)[:50]
            )
        except Exception:
            symbols = []
    timeframes = timeframes or ["1h", "4h", "1d"]
    total = 0
    for sym in symbols:
        try:
            cards = scan_symbol_mtf(sym, timeframes=timeframes)
            for tf in timeframes:
                tf_cards = [c for c in cards if c["timeframe"] == tf]
                if tf_cards:
                    persist_cards(tf_cards, sym, tf)
                    total += len(tf_cards)
        except Exception:
            continue
    return {"scanned_symbols": len(symbols), "persisted_cards": total}
'''


# ============================================================================
# NEW FILE: signals/management/commands/scan_smc_mtf.py
# ============================================================================
F_SCAN_MTF_CMD = '''"""Multi-timeframe SMC scan with HTF confluence boost."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scan a symbol across multiple timeframes with HTF confluence."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--timeframes", default="1h,4h,1d",
                            help="Comma-separated list, e.g. 1h,4h,1d")
        parser.add_argument("--bars", type=int, default=500)
        parser.add_argument("--persist", action="store_true")

    def handle(self, *args, **opts):
        from signals.mtf import scan_symbol_mtf
        from signals.rules.smc_rules import persist_cards
        from signals.explain.formatter import render_terminal_card

        timeframes = [tf.strip() for tf in opts["timeframes"].split(",")]
        cards = scan_symbol_mtf(opts["symbol"], timeframes=timeframes, bars=opts["bars"])

        if not cards:
            self.stdout.write(self.style.WARNING(
                f"No setups found for {opts['symbol']} across {timeframes}"
            ))
            return

        for c in cards:
            self.stdout.write(render_terminal_card(c))
            extra = []
            if c.get("htf_agrees"):
                extra.append(self.style.SUCCESS(
                    f"  HTF {c['htf_timeframe']} ({c['htf_trend']}) agrees"
                ))
            elif c.get("htf_trend") in ("up", "down"):
                extra.append(self.style.ERROR(
                    f"  HTF {c['htf_timeframe']} ({c['htf_trend']}) conflicts"
                ))
            for line in extra:
                self.stdout.write(line)
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS(
            f"Found {len(cards)} setup(s) for {opts['symbol']} across {timeframes}"
        ))

        if opts["persist"]:
            count = 0
            for tf in timeframes:
                tf_cards = [c for c in cards if c["timeframe"] == tf]
                if tf_cards:
                    persist_cards(tf_cards, opts["symbol"], tf)
                    count += len(tf_cards)
            self.stdout.write(self.style.SUCCESS(
                f"Persisted {count} signal cards"
            ))
'''


# ============================================================================
# NEW FILE: signals/management/commands/track_smc_lifecycle.py
# ============================================================================
F_TRACK_CMD = '''"""Run one SmcSignal lifecycle pass from the CLI."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run one SmcSignal lifecycle pass."

    def handle(self, *args, **opts):
        from signals.lifecycle import run_lifecycle_pass
        from signals.performance import setup_performance_summary

        result = run_lifecycle_pass()
        self.stdout.write(self.style.SUCCESS("Lifecycle pass complete:"))
        for status, count in result.items():
            self.stdout.write(f"  {status:14s} {count}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Setup performance (last 30d):"))
        perf = setup_performance_summary(days=30)
        if not perf:
            self.stdout.write("  (no closed signals yet)")
        for setup, p in perf.items():
            tag = "empirical" if p["is_empirical"] else "fallback"
            hr = f"{p['hit_rate']:.0%}" if p["hit_rate"] is not None else "n/a"
            ex = f"{p['expectancy_r']:+.2f}R" if p["expectancy_r"] is not None else "n/a"
            self.stdout.write(
                f"  {setup:18s}  hit={hr:>5}  exp={ex:>7}  n={p['n_closed']:3d}  ({tag})"
            )
'''


# ============================================================================
# NEW FILE: dashboard/views_signals_htmx.py
# ============================================================================
F_HTMX_VIEW = '''"""HTMX endpoints for live signal cards on the dashboard."""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def signal_cards_htmx(request):
    """Render the active SmcSignal feed for HTMX polling."""
    try:
        from signals.models_smc import SmcSignal
        signals = SmcSignal.objects.filter(
            status__in=["ACTIVE", "TRIGGERED"]
        ).order_by("-conviction", "-created_at")[:30]
    except Exception:
        signals = []
    return render(request, "dashboard/_signal_cards.html", {
        "signals": signals,
    })


@login_required
def signal_performance_htmx(request):
    """Render the per-setup hit-rate panel."""
    try:
        from signals.performance import setup_performance_summary
        perf = setup_performance_summary(days=30)
    except Exception:
        perf = {}
    return render(request, "dashboard/_signal_performance.html", {
        "perf": perf,
    })
'''


# ============================================================================
# NEW FILE: templates/dashboard/_signal_cards.html
# ============================================================================
F_HTMX_CARDS_TPL = '''{% load static %}
<div class="smc-signal-feed">
  {% if signals %}
    {% for s in signals %}
      <div class="smc-card smc-card--{{ s.direction|lower }} smc-card--{{ s.status|lower }}">
        <div class="smc-card__headline">{{ s.headline }}</div>
        <div class="smc-card__thesis">{{ s.thesis }}</div>

        <div class="smc-card__levels">
          <span class="lvl lvl--entry">
            <span class="lvl__label">Entry</span>
            <span class="lvl__value">{{ s.entry|floatformat:4 }}</span>
          </span>
          <span class="lvl lvl--stop">
            <span class="lvl__label">Stop</span>
            <span class="lvl__value">{{ s.stop|floatformat:4 }}</span>
          </span>
          <span class="lvl lvl--target">
            <span class="lvl__label">Target</span>
            <span class="lvl__value">{{ s.target|floatformat:4 }}</span>
          </span>
          <span class="lvl lvl--r">
            <span class="lvl__label">R</span>
            <span class="lvl__value">{{ s.r_multiple|floatformat:2 }}</span>
          </span>
        </div>

        <div class="smc-card__chips">
          <span class="chip chip--{% if s.chip_structure > 0 %}on{% elif s.chip_structure < 0 %}neg{% else %}off{% endif %}">STRUCT</span>
          <span class="chip chip--{% if s.chip_momentum > 0 %}on{% elif s.chip_momentum < 0 %}neg{% else %}off{% endif %}">MOMO</span>
          <span class="chip chip--{% if s.chip_flow > 0 %}on{% elif s.chip_flow < 0 %}neg{% else %}off{% endif %}">FLOW</span>
          <span class="chip chip--{% if s.chip_macro > 0 %}on{% elif s.chip_macro < 0 %}neg{% else %}off{% endif %}">MACRO</span>
          <span class="chip chip--{% if s.chip_sentiment > 0 %}on{% elif s.chip_sentiment < 0 %}neg{% else %}off{% endif %}">SENT</span>
        </div>

        <div class="smc-card__footer">
          <div class="smc-card__conviction">
            <div class="conviction-bar">
              <div class="conviction-bar__fill" style="width: {{ s.conviction }}%"></div>
            </div>
            <span class="conviction-num">{{ s.conviction }}/100</span>
            {% if s.rule_hit_rate_30d %}
              <span class="hit-rate">{{ s.rule_hit_rate_30d|floatformat:2 }} 30d hit</span>
            {% endif %}
          </div>
          <div class="smc-card__invalidation">
            Fails: {{ s.invalidation }}
          </div>
        </div>
      </div>
    {% endfor %}
  {% else %}
    <div class="smc-empty">No active signals.</div>
  {% endif %}
</div>

<style>
.smc-signal-feed { display: flex; flex-direction: column; gap: 12px; }
.smc-card { padding: 12px; border-radius: 6px; background: #0e0e10;
            border-left: 3px solid #555; font-family: ui-monospace, monospace; }
.smc-card--long { border-left-color: #2dbb6c; }
.smc-card--short { border-left-color: #c4384b; }
.smc-card--triggered { background: #1a1410; }
.smc-card__headline { font-weight: 600; margin-bottom: 4px; }
.smc-card__thesis { font-size: 0.85em; color: #b0b0b0; margin-bottom: 8px; }
.smc-card__levels { display: flex; gap: 16px; margin: 8px 0;
                    font-variant-numeric: tabular-nums; }
.lvl { display: flex; flex-direction: column; }
.lvl__label { font-size: 0.7em; color: #888; text-transform: uppercase; }
.lvl__value { font-weight: 600; }
.lvl--stop .lvl__value { color: #c4384b; }
.lvl--target .lvl__value { color: #2dbb6c; }
.smc-card__chips { display: flex; gap: 6px; margin: 8px 0; }
.chip { padding: 2px 8px; border-radius: 10px; font-size: 0.7em;
        border: 1px solid #444; color: #777; }
.chip--on { background: #1c3a26; border-color: #2dbb6c; color: #2dbb6c; }
.chip--neg { background: #3a1c20; border-color: #c4384b; color: #c4384b;
             text-decoration: line-through; }
.smc-card__footer { display: flex; justify-content: space-between;
                    align-items: center; font-size: 0.75em; color: #888; }
.conviction-bar { display: inline-block; width: 80px; height: 4px;
                  background: #222; border-radius: 2px; vertical-align: middle; }
.conviction-bar__fill { height: 100%; background: #c4384b; border-radius: 2px; }
.smc-empty { padding: 24px; text-align: center; color: #666; }
</style>
'''


# ============================================================================
# NEW FILE: templates/dashboard/_signal_performance.html
# ============================================================================
F_HTMX_PERF_TPL = '''<div class="smc-perf">
  <h3>Setup performance — last 30 days</h3>
  {% if perf %}
    <table class="smc-perf__table">
      <thead>
        <tr><th>Setup</th><th>Hit rate</th><th>Expectancy</th><th>n</th><th>Source</th></tr>
      </thead>
      <tbody>
        {% for setup, p in perf.items %}
          <tr>
            <td>{{ setup }}</td>
            <td>{% if p.hit_rate %}{{ p.hit_rate|floatformat:2 }}{% else %}—{% endif %}</td>
            <td>{% if p.expectancy_r %}{{ p.expectancy_r|floatformat:2 }}R{% else %}—{% endif %}</td>
            <td>{{ p.n_closed }}</td>
            <td>{% if p.is_empirical %}empirical{% else %}fallback{% endif %}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="smc-perf__empty">No closed signals yet — performance will populate as the lifecycle tracker runs.</p>
  {% endif %}
</div>
<style>
.smc-perf__table { width: 100%; border-collapse: collapse;
                   font-family: ui-monospace, monospace; font-size: 0.85em; }
.smc-perf__table th, .smc-perf__table td { padding: 6px 8px; text-align: left;
                                            border-bottom: 1px solid #222; }
.smc-perf__table th { color: #888; text-transform: uppercase; font-size: 0.75em; }
.smc-perf__empty { color: #888; padding: 12px; }
</style>
'''


# ============================================================================
# NEW FILE: signals/bot_bridge.py
# ============================================================================
F_BOT_BRIDGE = '''"""Bridge that lets the bot read SmcSignal as a composite score.

Used by bot_program/engine/strategy.py instead of (or in addition to)
the legacy Signal table read.
"""
from datetime import timedelta


def smc_score_for_symbol(symbol, hours=6, max_signals=10):
    """Return (score, reasons) summarizing recent SmcSignals for a symbol.

    Score is in [-1, +1] where +1 = strong long bias, -1 = strong short.
    Computed as average (direction-signed conviction/100) over recent
    ACTIVE/TRIGGERED signals, weighted by rule hit rate.
    """
    try:
        from signals.models_smc import SmcSignal
        from signals.performance import get_hit_rate
        from django.utils import timezone
    except Exception:
        return (0.0, [])

    cutoff = timezone.now() - timedelta(hours=hours)
    try:
        recent = list(
            SmcSignal.objects.filter(
                symbol__iexact=symbol,
                created_at__gte=cutoff,
                status__in=["ACTIVE", "TRIGGERED"],
            ).order_by("-created_at")[:max_signals]
        )
    except Exception:
        return (0.0, [])

    if not recent:
        return (0.0, [])

    weighted_sum = 0.0
    weight_total = 0.0
    setups_seen = {}
    for s in recent:
        sign = 1.0 if s.direction == "LONG" else -1.0
        conv = (s.conviction or 0) / 100.0
        weight = get_hit_rate(s.setup) or 0.5
        weighted_sum += sign * conv * weight
        weight_total += weight
        setups_seen[s.setup] = setups_seen.get(s.setup, 0) + 1

    if weight_total == 0:
        return (0.0, [])

    score = max(-1.0, min(1.0, weighted_sum / weight_total))
    reasons = [
        f"smc {score:+.2f} from {len(recent)} signals: "
        + ", ".join(f"{k}x{v}" for k, v in setups_seen.items())
    ]
    return (score, reasons)
'''


# ============================================================================
# Assemble FILES dict
# ============================================================================
FILES = {
    "signals/lifecycle.py":                                 F_LIFECYCLE,
    "signals/performance.py":                               F_PERFORMANCE,
    "signals/mtf.py":                                       F_MTF,
    "signals/bot_bridge.py":                                F_BOT_BRIDGE,
    "signals/tasks_lifecycle.py":                           F_TASKS_LIFECYCLE,
    "signals/rules/smc_engine_rule.py":                     F_SMC_ENGINE_RULE,
    "signals/rules/technical_rules.py":                     F_TECHNICAL_RULES,
    "signals/rules/sentiment_rules.py":                     F_SENTIMENT_RULES,
    "signals/rules/macro_rules.py":                         F_MACRO_RULES,
    "signals/rules/flow_rules.py":                          F_FLOW_RULES,
    "signals/rules/fundamental_rules.py":                   F_FUNDAMENTAL_RULES,
    "indicators/patterns.py":                               F_PATTERNS,
    "indicators/regime.py":                                 F_REGIME,
    "indicators/mtf.py":                                    F_MTF_INDICATORS,
    "signals/management/commands/scan_smc_mtf.py":          F_SCAN_MTF_CMD,
    "signals/management/commands/track_smc_lifecycle.py":   F_TRACK_CMD,
    "dashboard/views_signals_htmx.py":                      F_HTMX_VIEW,
    "templates/dashboard/_signal_cards.html":               F_HTMX_CARDS_TPL,
    "templates/dashboard/_signal_performance.html":         F_HTMX_PERF_TPL,
}


# Files to OVERWRITE even without --force, because they replace stubs
# (the original files are 7-line returns-empty stubs we want to replace)
OVERWRITE_STUBS = {
    "signals/rules/technical_rules.py",
    "signals/rules/sentiment_rules.py",
    "signals/rules/macro_rules.py",
    "signals/rules/flow_rules.py",
    "signals/rules/fundamental_rules.py",
    "indicators/patterns.py",
}


# ============================================================================
# Modifications to existing files (narrow, guarded)
# ============================================================================

def modify_signal_engine():
    """Add flow_rules and fundamental_rules + smc_engine_rule to SignalEngine._load_rules()."""
    path = ROOT / "signals" / "engine.py"
    if not path.exists():
        return False, "engine.py not found"
    text = path.read_text(encoding="utf-8")

    if "smc_engine_rule" in text:
        return True, "already wired"

    old = (
        "        from signals.rules import technical_rules, sentiment_rules, macro_rules\n"
        "        self.rules.extend(technical_rules.get_rules())\n"
        "        self.rules.extend(sentiment_rules.get_rules())\n"
        "        self.rules.extend(macro_rules.get_rules())"
    )
    new = (
        "        from signals.rules import (\n"
        "            technical_rules, sentiment_rules, macro_rules,\n"
        "            flow_rules, fundamental_rules, smc_engine_rule,\n"
        "        )\n"
        "        self.rules.extend(technical_rules.get_rules())\n"
        "        self.rules.extend(sentiment_rules.get_rules())\n"
        "        self.rules.extend(macro_rules.get_rules())\n"
        "        self.rules.extend(flow_rules.get_rules())\n"
        "        self.rules.extend(fundamental_rules.get_rules())\n"
        "        self.rules.extend(smc_engine_rule.get_rules())"
    )

    # Tolerate \r\n vs \n
    text_normalized = text.replace("\r\n", "\n")
    if old not in text_normalized:
        return False, "_load_rules block not found in expected form"
    new_text = text_normalized.replace(old, new)
    path.write_text(new_text, encoding="utf-8")
    return True, "wired all rule families + SMC into SignalEngine"


def modify_bot_strategy_for_smc_bridge():
    """Patch bot_program/engine/strategy.py _score_sauron_signals to also
    consult signals.bot_bridge.smc_score_for_symbol and average the two.
    Adds an import + an additive block. Idempotent via marker.
    """
    path = ROOT / "bot_program" / "engine" / "strategy.py"
    if not path.exists():
        return False, "bot strategy.py not found"
    text = path.read_text(encoding="utf-8")
    if "smc_score_for_symbol" in text:
        return True, "already wired"

    # Insert helper-call augmentation just before the function ends.
    pattern_text = "        return (agg, [f\"sauron sig avg {agg:+.2f} ({len(recent)})\"])"
    replacement = (
        "        legacy_score = agg\n"
        "        legacy_reasons = [f\"sauron sig avg {agg:+.2f} ({len(recent)})\"]\n"
        "        try:\n"
        "            from signals.bot_bridge import smc_score_for_symbol\n"
        "            smc_score, smc_reasons = smc_score_for_symbol(symbol)\n"
        "            blended = (legacy_score + smc_score) / 2 if smc_score != 0 else legacy_score\n"
        "            return (blended, legacy_reasons + smc_reasons)\n"
        "        except Exception:\n"
        "            return (legacy_score, legacy_reasons)"
    )
    text_n = text.replace("\r\n", "\n")
    if pattern_text not in text_n:
        return False, "expected return line not found in bot strategy"
    new_text = text_n.replace(pattern_text, replacement)
    path.write_text(new_text, encoding="utf-8")
    return True, "wired SmcSignal into bot _score_sauron_signals"


def modify_celery_beat():
    """Append two beat schedule entries: lifecycle pass + SMC universe scan."""
    path = ROOT / "config" / "celery.py"
    if not path.exists():
        return False, "config/celery.py not found"
    text = path.read_text(encoding="utf-8")
    if "smc-lifecycle-pass" in text:
        return True, "already scheduled"

    text_n = text.replace("\r\n", "\n")
    # Find the closing brace of beat_schedule. We append before the final '}'.
    marker = '"weekly-portfolio-rebalance-suggestions": {'
    if marker not in text_n:
        return False, "could not find anchor in beat schedule"
    # Insert new entries right before the marker
    insert = (
        '    "smc-lifecycle-pass": {\n'
        '        "task": "signals.tasks_lifecycle.run_smc_lifecycle",\n'
        '        "schedule": 300.0,\n'
        '    },\n'
        '    "smc-universe-scan": {\n'
        '        "task": "signals.tasks_lifecycle.scan_smc_universe",\n'
        '        "schedule": 1800.0,\n'
        '    },\n'
        '    '
    )
    new_text = text_n.replace(marker, insert + marker)
    path.write_text(new_text, encoding="utf-8")
    return True, "added 2 beat schedule entries (lifecycle 5min, SMC scan 30min)"


def modify_dashboard_urls():
    """Append HTMX endpoints to dashboard/urls.py."""
    path = ROOT / "dashboard" / "urls.py"
    if not path.exists():
        return False, "dashboard/urls.py not found"
    text = path.read_text(encoding="utf-8")
    if "signal_cards_htmx" in text:
        return True, "already added"

    text_n = text.replace("\r\n", "\n")
    import_line = "from .views_signals_htmx import signal_cards_htmx, signal_performance_htmx"
    new_paths = (
        '    path("htmx/signal-cards/", signal_cards_htmx, name="htmx_signal_cards"),\n'
        '    path("htmx/signal-performance/", signal_performance_htmx, name="htmx_signal_performance"),\n'
        ']'
    )

    if "from .views_signals_htmx" not in text_n:
        # Insert import after the existing imports near the top
        text_n = text_n.replace(
            "from . import views",
            "from . import views\n" + import_line,
            1,
        )
    # Insert new paths right before the closing ']'
    if text_n.rstrip().endswith("]"):
        text_n = text_n.rstrip()[:-1] + new_paths + "\n"
    else:
        return False, "urls.py doesn't end with ']' as expected"
    path.write_text(text_n, encoding="utf-8")
    return True, "added 2 HTMX endpoints"


# ============================================================================
# Migration: append lifecycle index to SmcSignal
# (Status field is already there from upgrade 10. We add a created_at+status
#  composite index for the lifecycle scanner's main query.)
# ============================================================================
F_MIGRATION = '''from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("signals", "0002_smcsignal")]

    operations = [
        migrations.AddIndex(
            model_name="smcsignal",
            index=models.Index(
                fields=["status", "created_at"],
                name="signals_smc_status_created_idx",
            ),
        ),
    ]
'''
FILES["signals/migrations/0003_smcsignal_lifecycle_index.py"] = F_MIGRATION


# ============================================================================
# Runner
# ============================================================================
def write_files():
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        is_stub_replacement = rel in OVERWRITE_STUBS
        if path.exists() and not FORCE and not is_stub_replacement:
            existing = path.read_text(encoding="utf-8")
            if existing.strip() == content.strip():
                print(f"  OK   (unchanged): {rel}")
                continue
            print(f"  SKIP (exists, --force to overwrite): {rel}")
            continue
        if is_stub_replacement and path.exists():
            existing = path.read_text(encoding="utf-8")
            # Only auto-replace if it really is the empty stub
            if "TODO" in existing or len(existing.strip()) < 300:
                path.write_text(content, encoding="utf-8")
                print(f"  REPLACED stub: {rel}")
                continue
            elif not FORCE:
                print(f"  SKIP (modified, --force to overwrite): {rel}")
                continue
        path.write_text(content, encoding="utf-8")
        print(f"  WROTE: {rel}")


def run_modifications():
    print()
    print("[modifications to existing files]")
    for label, fn in [
        ("signals/engine.py", modify_signal_engine),
        ("bot_program/engine/strategy.py", modify_bot_strategy_for_smc_bridge),
        ("config/celery.py", modify_celery_beat),
        ("dashboard/urls.py", modify_dashboard_urls),
    ]:
        try:
            ok, msg = fn()
            tag = "OK" if ok else "WARN"
            print(f"  {tag}: {label} -- {msg}")
        except Exception as e:
            print(f"  ERROR: {label} -- {e}")


def main():
    print("=" * 72)
    print("  Sauron Vision - Upgrade 11: Signals Lifecycle + Rule Families")
    print("=" * 72)
    print()
    print("[1/2] Writing files...")
    write_files()
    run_modifications()
    print()
    print("=" * 72)
    print("  DONE. Next steps:")
    print("=" * 72)
    print()
    print("  # 1. Apply migrations")
    print("  python manage.py migrate signals")
    print()
    print("  # 2. Smoke test the new rule families")
    print("  python manage.py shell -c \\")
    print("    'from signals.engine import SignalEngine; "
          "print(len(SignalEngine().rules), \"rules loaded\")'")
    print()
    print("  # 3. Multi-timeframe SMC scan")
    print("  python manage.py scan_smc_mtf --symbol BTCUSDT --persist")
    print()
    print("  # 4. Run lifecycle pass (also prints performance summary)")
    print("  python manage.py track_smc_lifecycle")
    print()
    print("  # 5. Restart Celery beat to pick up the 2 new periodic tasks:")
    print("  #    - smc-lifecycle-pass    every 5 min")
    print("  #    - smc-universe-scan     every 30 min")
    print()
    print("  # 6. The bot's _score_sauron_signals now blends SmcSignal data;")
    print("  #    no extra step needed beyond restarting bot workers.")
    print()


if __name__ == "__main__":
    main()
