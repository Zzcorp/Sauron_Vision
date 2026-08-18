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
        if df["low"].loc[recent_low_idx] < df["low"].loc[prior_low_idx] and \
           rsi.loc[recent_low_idx] > rsi.loc[prior_low_idx]:
            close = float(df["close"].iloc[-1])
            return {
                "symbol": symbol,
                "rule": self.name,
                "direction": "LONG",
                "score": 0.7,
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


def get_rules():
    """Return all technical rules — including evolved golden-cross forks,
    each running its own parameters under its own rule name."""
    return [
        RSIDivergenceRule(),
        MACDCrossoverRule(),
        *_golden_cross_family(),
        BollingerSqueezeRule(),
    ]
