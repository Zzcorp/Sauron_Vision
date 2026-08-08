"""Phase-12 real-time event-driven signal engine.

Architecture
-----------

  streamer / API / cron
         │ publishes event with (event_type, payload)
         ▼
  dispatch_event(event_type, payload)
         │ for each FastRule registered for this event_type:
         │   - check actuator (paused rules skipped)
         │   - check cooldown (rate-limit per (rule, instrument))
         │   - call rule.evaluate(...) — must be FAST (≤ 100ms target)
         │   - if SignalSpec returned → create Signal row
         │ persist FastEvent audit row with timing + fired rules
         ▼
  Signal flows through every Phase-1-11 lane automatically.

Honest latency expectation: 100ms-1s per dispatch in this codebase. True
sub-millisecond would require dropping Django+Celery, moving to a pure
asyncio/Redis-only path with pre-loaded rule state. The architecture here
is a pragmatic middle ground: real-time enough for crypto + breaking news,
not for HFT.

Public API
----------

    register_fast_rule(rule_instance) — decorator-friendly
    has_rule(rule_name) -> bool
    dispatch_event(event_type, payload, *, source="api") -> dict
    set_cooldown(rule_name, instrument_symbol, seconds=60)

Plus two example rules: BreakoutOnTickRule, NewsShockRule.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Default cooldown: a rule won't fire twice on the same (rule, instrument)
# pair within this many seconds. Prevents tick-storm spam.
DEFAULT_COOLDOWN_SECONDS = 60

# A FastRule that takes longer than this is logged as a perf warning.
SLOW_RULE_MS_THRESHOLD = 200


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SignalSpec:
    """A FastRule's output — gets converted to a Signal row by the dispatcher."""
    instrument: Any  # Instrument
    direction: str   # "bullish" | "bearish" | "neutral"
    score: float
    title: str = ""
    description: str = ""
    urgency: str = "high"
    price: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    sub_scores: dict = field(default_factory=dict)


# ── FastRule base ───────────────────────────────────────────────────────────

class FastRule(ABC):
    """Subclass + register via `register_fast_rule(MyRule())`.

    Subclasses MUST set:
      - rule_name: str (unique, used as Signal.rule_name)
      - event_types: list[str] (which events this rule reacts to)

    Optional override:
      - cooldown_seconds: per-(rule, instrument) min interval. Default 60s.
    """

    rule_name: str = ""
    event_types: list[str] = []
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    signal_type: str = "composite"

    @abstractmethod
    def evaluate(self, event_type: str, payload: dict) -> Optional[SignalSpec]:
        """Return a SignalSpec on match, or None.

        Keep this fast — avoid heavy DB queries when possible.
        """


# ── Registry ────────────────────────────────────────────────────────────────

FAST_RULE_REGISTRY: dict[str, FastRule] = {}

# In-memory cooldown tracker: {(rule_name, symbol): last_fire_ts}
_COOLDOWNS: dict[tuple, float] = {}


def register_fast_rule(rule: FastRule) -> None:
    if not isinstance(rule, FastRule):
        raise TypeError("rule must be a FastRule instance")
    if not rule.rule_name:
        raise ValueError("FastRule.rule_name must be non-empty")
    if not rule.event_types:
        raise ValueError("FastRule.event_types must be non-empty")
    FAST_RULE_REGISTRY[rule.rule_name] = rule


def has_rule(rule_name: str) -> bool:
    return rule_name in FAST_RULE_REGISTRY


def reset_cooldowns():
    """Clear all in-memory cooldowns (test helper, also useful after a deploy)."""
    _COOLDOWNS.clear()


def _on_cooldown(rule_name: str, symbol: str, cooldown_seconds: int) -> bool:
    key = (rule_name, symbol)
    last = _COOLDOWNS.get(key)
    now = time.monotonic()
    if last is not None and (now - last) < cooldown_seconds:
        return True
    _COOLDOWNS[key] = now
    return False


# ── Dispatcher ──────────────────────────────────────────────────────────────

def dispatch_event(event_type: str, payload: dict, *,
                    source: str = "api") -> dict:
    """Run every registered FastRule for `event_type`. Persists Signals on
    matches and a FastEvent audit row with timing + fired rules.

    Returns: {"event_id", "rules_evaluated", "rules_fired", "signal_ids", "elapsed_ms"}.
    """
    from signals.models import FastEvent, Signal
    from signals.rule_actuator import is_rule_active

    t0 = time.perf_counter()
    payload = dict(payload or {})
    symbol = str(payload.get("symbol", "")).strip()

    candidates = [r for r in FAST_RULE_REGISTRY.values() if event_type in r.event_types]
    fired_names: list[str] = []
    signal_ids: list[int] = []
    error_msg = ""

    for rule in candidates:
        # Phase-5 actuator gate — paused fast rules are silently skipped.
        try:
            if not is_rule_active(rule.rule_name):
                continue
        except Exception:
            pass

        # Per-(rule, symbol) cooldown.
        if symbol and _on_cooldown(rule.rule_name, symbol, rule.cooldown_seconds):
            continue

        try:
            rule_t0 = time.perf_counter()
            spec = rule.evaluate(event_type, payload)
            rule_ms = (time.perf_counter() - rule_t0) * 1000
            if rule_ms > SLOW_RULE_MS_THRESHOLD:
                logger.warning("[fast_rules] %s slow: %.1fms", rule.rule_name, rule_ms)
        except Exception as e:
            logger.warning("[fast_rules] %s raised: %s", rule.rule_name, e)
            error_msg = (error_msg + f"\n{rule.rule_name}: {e}").strip()
            continue

        if spec is None:
            continue

        # Persist a Signal so it flows through Phase 1-11.
        try:
            sig = Signal.objects.create(
                instrument=spec.instrument,
                signal_type=rule.signal_type,
                direction=spec.direction,
                urgency=spec.urgency,
                title=spec.title or f"{rule.rule_name} fired on {spec.instrument.symbol}",
                description=spec.description or "",
                rule_name=rule.rule_name,
                score=float(spec.score),
                sub_scores={**(spec.sub_scores or {}), "fast_rule": True, "source": source},
                price_at_signal=Decimal(str(spec.price)) if spec.price is not None else Decimal("0"),
                suggested_entry=Decimal(str(spec.price)) if spec.price is not None else None,
                suggested_stop=Decimal(str(spec.stop)) if spec.stop is not None else None,
                suggested_target=Decimal(str(spec.target)) if spec.target is not None else None,
            )
            signal_ids.append(sig.id)
            fired_names.append(rule.rule_name)
        except Exception as e:
            logger.warning("[fast_rules] Signal.create failed for %s: %s", rule.rule_name, e)
            error_msg = (error_msg + f"\n{rule.rule_name} create-fail: {e}").strip()

    elapsed_ms = (time.perf_counter() - t0) * 1000
    fe = FastEvent.objects.create(
        event_type=event_type, symbol=symbol[:40], payload=payload,
        rules_evaluated=len(candidates), rules_fired=len(fired_names),
        fired_rule_names=fired_names, signal_ids=signal_ids,
        dispatch_ms=round(elapsed_ms, 2), error=error_msg[:1000],
    )
    return {
        "event_id": fe.id,
        "rules_evaluated": len(candidates),
        "rules_fired": len(fired_names),
        "signal_ids": signal_ids,
        "elapsed_ms": round(elapsed_ms, 2),
    }


# ── Example FastRules ──────────────────────────────────────────────────────

class BreakoutOnTickRule(FastRule):
    """Fires on price_tick when last > prior N-bar high by >= threshold_pct.

    Payload schema: {symbol: str, last: float, ts: optional}.
    """
    rule_name = "fast_breakout_on_tick"
    event_types = ["price_tick"]
    cooldown_seconds = 300  # 5 minutes — breakouts shouldn't re-fire too fast

    def __init__(self, lookback_bars: int = 20, threshold_pct: float = 0.5,
                 timeframe: str = "5m"):
        self.lookback = lookback_bars
        self.threshold = threshold_pct / 100.0
        self.timeframe = timeframe

    def evaluate(self, event_type, payload):
        symbol = payload.get("symbol")
        last = payload.get("last")
        if not symbol or last is None:
            return None
        try:
            last = float(last)
        except (TypeError, ValueError):
            return None
        if last <= 0:
            return None

        from instruments.models import Instrument
        from market_data.models import PriceData
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            return None

        recent = list(
            PriceData.objects
            .filter(instrument=inst, timeframe=self.timeframe)
            .order_by("-timestamp")[:self.lookback]
            .values_list("high", flat=True)
        )
        if len(recent) < self.lookback:
            return None

        prior_high = max(float(h) for h in recent)
        if last > prior_high * (1 + self.threshold):
            stop = prior_high * 0.999
            target = last + (last - prior_high) * 2
            return SignalSpec(
                instrument=inst, direction="bullish",
                score=0.85, urgency="high",
                title=f"{symbol} breakout above {prior_high:.6f}",
                description=(f"price_tick: last {last:.6f} > prior {self.lookback}-bar "
                             f"{self.timeframe} high {prior_high:.6f} + {self.threshold:.2%}"),
                price=last, stop=stop, target=target,
                sub_scores={"breakout_pct": (last / prior_high - 1) * 100},
            )

        # Bearish mirror: breakdown below prior low.
        recent_lows = list(
            PriceData.objects
            .filter(instrument=inst, timeframe=self.timeframe)
            .order_by("-timestamp")[:self.lookback]
            .values_list("low", flat=True)
        )
        if len(recent_lows) >= self.lookback:
            prior_low = min(float(l) for l in recent_lows)
            if last < prior_low * (1 - self.threshold):
                stop = prior_low * 1.001
                target = last - (prior_low - last) * 2
                return SignalSpec(
                    instrument=inst, direction="bearish",
                    score=0.85, urgency="high",
                    title=f"{symbol} breakdown below {prior_low:.6f}",
                    description=(f"price_tick: last {last:.6f} < prior {self.lookback}-bar "
                                 f"{self.timeframe} low {prior_low:.6f} - {self.threshold:.2%}"),
                    price=last, stop=stop, target=target,
                    sub_scores={"breakdown_pct": (1 - last / prior_low) * 100},
                )
        return None


class NewsShockRule(FastRule):
    """Fires on a news event with extreme sentiment for an instrument.

    Payload schema: {symbol: str, sentiment: float in [-1, 1],
                     headline: str, source: str, last_price: optional float}.
    """
    rule_name = "fast_news_shock"
    event_types = ["news"]
    cooldown_seconds = 600  # 10 minutes — avoid spam from cross-source duplicates

    def __init__(self, sentiment_threshold: float = 0.7, stop_pct: float = 1.5,
                 target_rr: float = 2.0):
        self.threshold = sentiment_threshold
        self.stop_pct = stop_pct / 100.0
        self.target_rr = target_rr

    def evaluate(self, event_type, payload):
        symbol = payload.get("symbol")
        sentiment = payload.get("sentiment")
        if not symbol or sentiment is None:
            return None
        try:
            sentiment = float(sentiment)
        except (TypeError, ValueError):
            return None
        if abs(sentiment) < self.threshold:
            return None

        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            return None

        last = payload.get("last_price")
        if last is None:
            try:
                lq = inst.live_quote
                last = float(lq.last) if lq.last else None
            except Exception:
                last = None
        if last is None or last <= 0:
            return None

        direction = "bullish" if sentiment > 0 else "bearish"
        if direction == "bullish":
            stop = last * (1 - self.stop_pct)
            target = last + (last - stop) * self.target_rr
        else:
            stop = last * (1 + self.stop_pct)
            target = last - (stop - last) * self.target_rr

        return SignalSpec(
            instrument=inst, direction=direction,
            score=min(1.0, abs(sentiment)), urgency="critical",
            title=f"{symbol} news shock: sentiment {sentiment:+.2f}",
            description=(f"news: {payload.get('source', '?')} - "
                         f"\"{(payload.get('headline') or '')[:200]}\""),
            price=last, stop=stop, target=target,
            sub_scores={"sentiment": sentiment, "source": payload.get("source", "")},
        )


# Register the example rules at import time so they're available to the
# dispatcher without explicit setup. Tests can `reset_fast_rules()` to clear.
def reset_fast_rules():
    FAST_RULE_REGISTRY.clear()
    reset_cooldowns()


def register_default_rules():
    """Register the bundled example rules. Idempotent."""
    if "fast_breakout_on_tick" not in FAST_RULE_REGISTRY:
        register_fast_rule(BreakoutOnTickRule())
    if "fast_news_shock" not in FAST_RULE_REGISTRY:
        register_fast_rule(NewsShockRule())


register_default_rules()
