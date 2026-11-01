"""Technical analysis signal rules — real implementations.

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


def _sane(df, instrument):
    """THE BAR SANITY on a rule's own frame (backtester/proving/data.
    sanitize, 2026-10-31): the frame the proving ground judges, so the rule
    never fires on a bar the judge refuses to read. An unadjusted forward
    split reads as a crash, and a crash is exactly what a short rule fires
    on. None when the series is broken or the sanity dropped the newest
    bar (the bar the rule would fire on is not a market)."""
    if df is None or len(df) == 0:
        return df
    from backtester.proving.data import sanitize
    clean, check = sanitize(df, getattr(instrument, "asset_class", None))
    if check.get("broken") or clean is None or len(clean) == 0:
        return None
    if clean.index[-1] != df.index[-1]:
        return None
    return clean


def closed_frame(df, timeframe="4h", now=None):
    """`df` without its last row when that bar is still open: its open plus
    the bar's length is after `now`. PriceData stamps a bar's OPEN
    (market_data/bot_bars.py; eToro's newest candle may be stored while
    forming, and the public feed resamples a partial bin), and a family
    fires on the close of bar t."""
    if df is None or len(df) == 0:
        return df
    import pandas as pd
    from django.utils import timezone

    from backtester.proving.data import BAR_HOURS
    now = pd.Timestamp(now or timezone.now())
    if now.tz is None:
        now = now.tz_localize("UTC")
    last = pd.Timestamp(df.index[-1])
    if last.tz is None:
        last = last.tz_localize("UTC")
    if last + pd.Timedelta(hours=BAR_HOURS.get(timeframe, 4.0)) > now:
        return df.iloc[:-1]
    return df


def _closed_sane(df, instrument, timeframe="4h"):
    """The frame a short mirror reads: its closed bars (closed_frame) after
    the bar sanity (_sane) — the frame its proving-ground family judges,
    which fires on the close of bar t."""
    return _sane(closed_frame(df, timeframe), instrument)


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


#: RSI divergence conviction (2026-10-04). The rule scored every firing a
#: constant 0.7, which rule_adapter reads as HIGH urgency — the weekly
#: review found it hitting 17% and calling each one high. The score now
#: reads the setup: RSI_SCORE_FLOOR at the 35 threshold (medium), rising
#: to RSI_SCORE_CEILING (high) as the RSI reaches RSI_DEEP; the rule's
#: own record (signals/rule_scope) caps the word again when it has earned
#: that.
RSI_THRESHOLD = 35.0
RSI_DEEP = 20.0
RSI_SCORE_FLOOR = 0.55
RSI_SCORE_CEILING = 0.70


def rsi_divergence_score(last_rsi: float) -> float:
    """RSI_SCORE_FLOOR at RSI_THRESHOLD, RSI_SCORE_CEILING at or below
    RSI_DEEP, linear between — a deeper oversold reading is a stronger
    exhaustion claim; a divergence at 34 is a shallow one."""
    span = RSI_THRESHOLD - RSI_DEEP
    depth = (RSI_THRESHOLD - float(last_rsi)) / span if span > 0 else 1.0
    depth = min(1.0, max(0.0, depth))
    return round(RSI_SCORE_FLOOR + (RSI_SCORE_CEILING - RSI_SCORE_FLOOR) * depth, 3)


class RSIDivergenceRule(BaseRule):
    """RSI bullish divergence: price lower-low, RSI higher-low, RSI < 35."""
    name = "rsi_bull_divergence"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        if df is None or len(df) < 60:
            return None
        rsi = _rsi(df["close"])
        last_rsi = float(rsi.iloc[-1])
        if last_rsi >= RSI_THRESHOLD:
            return None
        recent_low_idx = df["low"].iloc[-30:].idxmin()
        prior_low_idx = df["low"].iloc[-60:-30].idxmin()
        if df["low"].loc[recent_low_idx] < df["low"].loc[prior_low_idx] and \
           rsi.loc[recent_low_idx] > rsi.loc[prior_low_idx]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": rsi_divergence_score(last_rsi),
                "sub_scores": {"rsi": round(last_rsi, 1)},
                "headline": f"{symbol} LONG · RSI bullish divergence",
                "thesis": (
                    f"Price made a lower low while RSI made a higher low "
                    f"(RSI={last_rsi:.0f}). Momentum exhaustion."
                ),
                "entry": close,
                "stop": close * 0.985,
                "target": close * 1.03,
            }
        return None


class RSIBearDivergenceRule(BaseRule):
    """RSI bearish divergence: price higher-high, RSI lower-high, RSI > 65
    (100 - RSI_THRESHOLD) — the short mirror of rsi_bull_divergence
    (2026-10-31), its own name so every layer judges the short apart, born
    at research (signals/rule_birth). The proving ground replays it as
    rsi_divergence short, which fires on the close of bar t: it reads its
    CLOSED bars (closed_frame — the newest stored bar may still be
    forming) through the bar sanity, and fires on the last of them."""
    name = "rsi_bear_divergence"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        df = _closed_sane(df, instrument)
        if df is None or len(df) < 60:
            return None
        rsi = _rsi(df["close"])
        last_rsi = float(rsi.iloc[-1])
        if last_rsi <= 100.0 - RSI_THRESHOLD:
            return None
        recent_high_idx = df["high"].iloc[-30:].idxmax()
        prior_high_idx = df["high"].iloc[-60:-30].idxmax()
        if df["high"].loc[recent_high_idx] > df["high"].loc[prior_high_idx] and \
           rsi.loc[recent_high_idx] < rsi.loc[prior_high_idx]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "SHORT",
                # the mirror of the long's scale: 0.55 at RSI 65, 0.70 at 80+
                "score": rsi_divergence_score(100.0 - last_rsi),
                "sub_scores": {"rsi": round(last_rsi, 1)},
                "headline": f"{symbol} SHORT · RSI bearish divergence",
                "thesis": (
                    f"Price made a higher high while RSI made a lower high "
                    f"(RSI={last_rsi:.0f}). Momentum exhaustion."
                ),
                "entry": close,
                "stop": close * 1.015,
                "target": close * 0.97,
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
        if line.iloc[-2] <= sig.iloc[-2] and line.iloc[-1] > sig.iloc[-1] \
                and hist.iloc[-1] > hist.iloc[-2]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.55,
                "headline": f"{symbol} LONG · MACD bullish crossover",
                "thesis": "MACD line crossed above signal with histogram accelerating.",
                "entry": close,
                "stop": close * 0.98,
                "target": close * 1.04,
            }
        return None


class MACDBearishCrossoverRule(BaseRule):
    """MACD bearish crossover (line crosses under signal) with the
    histogram falling — the short mirror of macd_bullish_crossover
    (2026-10-31), born at research. Its twin's constant 0.55: like its
    twin it never votes at entry_score_min 0.60 (choice left to the
    operator), and it still builds a graded record by side. Its CLOSED
    bars through the bar sanity (_closed_sane): macd_cross short, which
    judges it, fires on the close of bar t, never on an intrabar cross."""
    name = "macd_bearish_crossover"

    def evaluate(self, instrument):
        symbol, df = _load_df(instrument)
        df = _closed_sane(df, instrument)
        if df is None or len(df) < 40:
            return None
        line, sig, hist = _macd(df["close"])
        if line.iloc[-2] >= sig.iloc[-2] and line.iloc[-1] < sig.iloc[-1] \
                and hist.iloc[-1] < hist.iloc[-2]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.55,
                "headline": f"{symbol} SHORT · MACD bearish crossover",
                "thesis": "MACD line crossed under signal with histogram falling.",
                "entry": close,
                "stop": close * 1.02,
                "target": close * 0.96,
            }
        return None


class GoldenCrossRule(BaseRule):
    """Fast SMA crosses above slow SMA — the first PARAMETER-AWARE rule.

    Every constant is a parameter so Phase-9 evolution has something real
    to mutate: window lengths and stop/target distances come from the
    instance, defaulting to the classic 50/200 with 5%/10% brackets. An
    evolved fork runs as its OWN instance carrying its RuleControl's
    parameters and its forked name — without that, apply_evolution created
    RuleControl rows that no engine ever executed, and no fork could climb
    the promotion ladder.
    """
    name = "golden_cross"
    DEFAULTS = {"fast": 50, "slow": 200, "stop_pct": 0.05, "target_pct": 0.10}

    def __init__(self, name=None, params=None):
        if name:
            self.name = name
        self.params = {**self.DEFAULTS, **(params or {})}

    def evaluate(self, instrument):
        p = self.params
        try:
            fast, slow = int(p["fast"]), int(p["slow"])
            stop_pct, target_pct = float(p["stop_pct"]), float(p["target_pct"])
        except (KeyError, TypeError, ValueError):
            fast, slow, stop_pct, target_pct = 50, 200, 0.05, 0.10
        if fast >= slow or stop_pct <= 0 or target_pct <= 0:
            # A degenerate mutant must go silent, not trade nonsense.
            return None
        symbol, df = _load_df(instrument, bars=slow + 100)
        if df is None or len(df) < slow + 10:
            return None
        sma_fast = df["close"].rolling(fast).mean()
        sma_slow = df["close"].rolling(slow).mean()
        if sma_fast.iloc[-2] <= sma_slow.iloc[-2] and sma_fast.iloc[-1] > sma_slow.iloc[-1]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.6,
                "headline": f"{symbol} LONG · Golden cross",
                "thesis": (f"SMA{fast} crossed above SMA{slow} — "
                           f"long-term trend flip up."),
                "entry": close,
                "stop": close * (1 - stop_pct),
                "target": close * (1 + target_pct),
            }
        return None


class DeathCrossRule(BaseRule):
    """Fast SMA crosses under slow SMA — the parameter-aware short mirror
    of GoldenCrossRule (2026-10-31), born at research with its forks
    (death_cross_evolved_vN). The same parameters and the same brackets,
    mirrored: stop above by stop_pct, target below by target_pct. Its
    CLOSED bars go through the bar sanity (_closed_sane): an unadjusted
    forward split is a death cross on raw bars, and ma_cross short, which
    judges it, fires on the close of bar t."""
    name = "death_cross"
    DEFAULTS = {"fast": 50, "slow": 200, "stop_pct": 0.05, "target_pct": 0.10}

    def __init__(self, name=None, params=None):
        if name:
            self.name = name
        self.params = {**self.DEFAULTS, **(params or {})}

    def evaluate(self, instrument):
        p = self.params
        try:
            fast, slow = int(p["fast"]), int(p["slow"])
            stop_pct, target_pct = float(p["stop_pct"]), float(p["target_pct"])
        except (KeyError, TypeError, ValueError):
            fast, slow, stop_pct, target_pct = 50, 200, 0.05, 0.10
        if fast >= slow or stop_pct <= 0 or target_pct <= 0:
            # A degenerate mutant must go silent, not trade nonsense.
            return None
        symbol, df = _load_df(instrument, bars=slow + 100)
        df = _closed_sane(df, instrument)
        if df is None or len(df) < slow + 10:
            return None
        sma_fast = df["close"].rolling(fast).mean()
        sma_slow = df["close"].rolling(slow).mean()
        if sma_fast.iloc[-2] >= sma_slow.iloc[-2] and sma_fast.iloc[-1] < sma_slow.iloc[-1]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.6,
                "headline": f"{symbol} SHORT · Death cross",
                "thesis": (f"SMA{fast} crossed under SMA{slow} — "
                           f"long-term trend flip down."),
                "entry": close,
                "stop": close * (1 + stop_pct),
                "target": close * (1 - target_pct),
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
                "headline": f"{symbol} {direction} · BB squeeze breakout",
                "thesis": "Bollinger Band width compressed to 20th percentile, now expanding.",
                "entry": close,
                "stop": close * (0.98 if direction == "LONG" else 1.02),
                "target": close * (1.04 if direction == "LONG" else 0.96),
            }
        return None


def _golden_cross_family():
    """The base rule (honouring any tuned parameters on its RuleControl)
    plus one instance per applied evolution fork. The engine rebuilds its
    rule list per scan, so a freshly applied fork trades on the very next
    pass. Fenced: rules must load even where the DB is unavailable."""
    base_params = {}
    forks = []
    try:
        from signals.models import RuleControl
        base = RuleControl.objects.filter(rule_name="golden_cross").first()
        if base and base.parameters:
            base_params = dict(base.parameters)
        # Effective activity, not raw status: a REDUCED fork still trades
        # (at the multiplier the actuator applies downstream), and a pause
        # that has expired auto-reactivates. Filtering on status=='active'
        # made both vanish from the engine permanently — demoted-not-dead
        # forks could never demote further, recover, or be evaluated again.
        forks = [
            GoldenCrossRule(name=rc.rule_name, params=rc.parameters or {})
            for rc in RuleControl.objects.filter(
                rule_name__startswith="golden_cross_evolved_v")
            if rc.is_effectively_active()
        ]
    except Exception as e:  # noqa: BLE001
        logger.debug("golden cross family load failed: %s", e)
    return [GoldenCrossRule(params=base_params)] + forks


def _death_cross_family():
    """The death cross as _golden_cross_family loads the golden: the base
    rule with its row's parameters, plus one instance per effectively
    active `death_cross_evolved_v*` row. Fenced the same way."""
    base_params = {}
    forks = []
    try:
        from signals.models import RuleControl
        base = RuleControl.objects.filter(rule_name="death_cross").first()
        if base and base.parameters:
            base_params = dict(base.parameters)
        forks = [
            DeathCrossRule(name=rc.rule_name, params=rc.parameters or {})
            for rc in RuleControl.objects.filter(
                rule_name__startswith="death_cross_evolved_v")
            if rc.is_effectively_active()
        ]
    except Exception as e:  # noqa: BLE001
        logger.debug("death cross family load failed: %s", e)
    return [DeathCrossRule(params=base_params)] + forks


def get_rules():
    """Return all technical rules — including evolved golden-cross and
    death-cross forks, each running its own parameters under its own rule
    name — and the three short mirrors (2026-10-31), born at research."""
    return [
        RSIDivergenceRule(),
        RSIBearDivergenceRule(),
        MACDCrossoverRule(),
        MACDBearishCrossoverRule(),
        *_golden_cross_family(),
        *_death_cross_family(),
        BollingerSqueezeRule(),
    ]
