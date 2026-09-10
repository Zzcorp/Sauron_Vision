"""Agent calibration — Phase 6.

Closes the loop: every agent prediction is logged with a resolution deadline
and a link to the source object (Signal, RuleAction, etc.). A nightly resolver
fetches ground truth and stamps the prediction. The risk gate consults
`trust_adjustment_for(agent)` before honouring an AI scale, so an agent that's
been wrong a lot has its influence dampened.

Public API:
  log_trade_prediction(agent, signal, predicted_outcome, confidence)
        Log a prediction tied to a Signal — resolves when the signal closes.

  log_decay_prediction(agent, rule_action, predicted_continues, confidence)
        Log a prediction tied to a RuleAction — resolves 30 days later.

  resolve_pending_predictions()
        Nightly: walk every unresolved prediction past its deadline, look up
        ground truth, stamp it. Returns count resolved.

  trust_adjustment_for(agent_name) -> float
        0.5 .. 1.3 multiplier for risk-gate consumption. <1 = damped trust.

  CalibrationTracker.* (legacy API preserved)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Default lookback when computing trust scores.
DEFAULT_LOOKBACK_DAYS = 90

# A rule expectancy delta (recent_after - recent_before) below this means the
# decay-investigation prediction was correct (the rule did continue to decay).
DECAY_CONFIRMATION_THRESHOLD = -0.5  # R-units

# Minimum sample size before trust_adjustment_for moves away from 1.0.
MIN_SAMPLE_FOR_TRUST = 10


# ── Helpers ─────────────────────────────────────────────────────────────────

def _AgentPrediction():
    from ai_agents.models import AgentPrediction
    return AgentPrediction


# ── Logging entry points ────────────────────────────────────────────────────

def log_prediction(agent, prediction_type, predicted_value,
                   instrument_symbol="", confidence=0.5,
                   expected_resolution_at=None,
                   linked_signal=None, linked_rule_action=None):
    """Generic logger — preferred to use the typed helpers below."""
    return _AgentPrediction().objects.create(
        agent=agent,
        prediction_type=prediction_type,
        predicted_value=str(predicted_value),
        instrument_symbol=instrument_symbol,
        confidence=float(confidence),
        expected_resolution_at=expected_resolution_at,
        linked_signal=linked_signal,
        linked_rule_action=linked_rule_action,
    )


def log_trade_prediction(agent: str, signal, *, predicted_outcome="hit_target",
                         confidence: float = 0.5):
    """Predict a Signal's eventual outcome.

    `predicted_outcome` should be one of "hit_target" or "stopped_out".
    Resolves when `Signal.is_active = False`. Confidence = the agent's
    self-reported probability that the trade will hit target.
    """
    return log_prediction(
        agent=agent,
        prediction_type="trade_outcome",
        predicted_value=predicted_outcome,
        instrument_symbol=signal.instrument.symbol if signal.instrument else "",
        confidence=confidence,
        # Trade signals expire by SIGNAL_TTL_DAYS=7 if nothing happens.
        expected_resolution_at=timezone.now() + timedelta(days=8),
        linked_signal=signal,
    )


def log_decay_prediction(agent: str, rule_action, *,
                         predicted_continues: bool = True, confidence: float = 0.6):
    """Predict whether a rule's decay will continue.

    Resolves 30 days after creation by comparing rule expectancy then vs now.
    If the agent recommended pause/reduce, it's predicting decay continues.
    """
    return log_prediction(
        agent=agent,
        prediction_type="decay_continues",
        predicted_value="continues" if predicted_continues else "recovers",
        instrument_symbol="",
        confidence=confidence,
        expected_resolution_at=timezone.now() + timedelta(days=30),
        linked_rule_action=rule_action,
    )


# ── Auto-resolver ───────────────────────────────────────────────────────────

def _resolve_trade_prediction(pred) -> bool:
    """Return True if successfully resolved (and stamped)."""
    sig = pred.linked_signal
    if sig is None or sig.is_active:
        return False
    actual_outcome = sig.outcome or ""
    realized_r = sig.realized_r if sig.realized_r is not None else 0.0

    # was_correct = predicted == actual (binary), reduced from outcome string.
    was_correct = (pred.predicted_value == actual_outcome)
    pred.actual_value = actual_outcome
    pred.was_correct = bool(was_correct)
    pred.score = float(realized_r)
    pred.evaluated_at = timezone.now()
    pred.evaluation_notes = f"signal #{sig.id} closed as {actual_outcome} at R={realized_r}"
    pred.save()
    return True


def _resolve_decay_prediction(pred) -> bool:
    """Resolve a decay prediction by comparing rule expectancy then vs now."""
    from signals.performance import calculate_signal_stats

    action = pred.linked_rule_action
    if action is None:
        return False

    rule_name = action.rule_name
    # Window: 30 days starting from prediction time.
    # Compute current expectancy over the resolution window for this rule.
    from signals.models import Signal
    cutoff_recent = pred.created_at
    qs = Signal.objects.filter(
        rule_name=rule_name, is_active=False,
        expired_at__gte=cutoff_recent,
    ).exclude(outcome="")
    n_recent = qs.count()
    if n_recent < 3:
        # Not enough resolved trades to judge; give it more time.
        # Push expected_resolution_at out by 14d so we'll retry later.
        pred.expected_resolution_at = timezone.now() + timedelta(days=14)
        pred.save(update_fields=["expected_resolution_at"])
        return False

    from django.db.models import Avg
    expectancy = qs.aggregate(avg=Avg("realized_r"))["avg"] or 0.0

    # If predicted "continues" and recent expectancy is below threshold → correct.
    predicted_continues = (pred.predicted_value == "continues")
    actually_continues = expectancy < DECAY_CONFIRMATION_THRESHOLD
    was_correct = (predicted_continues == actually_continues)

    pred.actual_value = f"expectancy_{expectancy:.2f}R"
    pred.was_correct = bool(was_correct)
    pred.score = float(expectancy)  # negative = bad rule, positive = good
    pred.evaluated_at = timezone.now()
    pred.evaluation_notes = (
        f"30d expectancy on rule={rule_name} is {expectancy:+.2f}R (n={n_recent}). "
        f"Predicted continues={predicted_continues}, actually continues={actually_continues}."
    )
    pred.save()
    return True


def resolve_pending_predictions(now=None) -> dict:
    """Resolve every prediction whose deadline has passed and ground truth is available.

    Idempotent: skips already-resolved (was_correct__isnull=False).
    """
    AgentPrediction = _AgentPrediction()
    now = now or timezone.now()
    # evaluated_at__isnull: a call the market never answered (no bar in
    # the grace window) is stamped evaluated with was_correct left NULL —
    # ungraded, not wrong — and must not be walked again every night.
    pending = AgentPrediction.objects.filter(
        was_correct__isnull=True,
        evaluated_at__isnull=True,
        expected_resolution_at__lte=now,
    )
    resolved = 0
    failed = 0
    by_type = {}
    for pred in pending:
        try:
            if pred.prediction_type == "trade_outcome":
                ok = _resolve_trade_prediction(pred)
            elif pred.prediction_type == "decay_continues":
                ok = _resolve_decay_prediction(pred)
            elif pred.prediction_type == "direction":
                ok = _resolve_direction_prediction(pred, now=now)
            else:
                ok = False  # unknown type — leave for human inspection
            if ok:
                resolved += 1
                by_type[pred.prediction_type] = by_type.get(pred.prediction_type, 0) + 1
            else:
                failed += 1
        except Exception as e:
            logger.warning("calibration: failed to resolve pred #%s: %s", pred.id, e)
            failed += 1

    return {"resolved": resolved, "failed": failed, "by_type": by_type}


# ── Trust-score consumer ────────────────────────────────────────────────────

def brier_score(agent: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> Optional[float]:
    """Mean Brier score (lower = better) for resolved predictions in window.

    For each prediction: bs = (confidence - actual_outcome)^2, where
    actual_outcome is 1 if was_correct else 0. Returns None if no data.
    """
    AgentPrediction = _AgentPrediction()
    cutoff = timezone.now() - timedelta(days=lookback_days)
    qs = AgentPrediction.objects.filter(
        agent=agent, was_correct__isnull=False, evaluated_at__gte=cutoff,
    )
    n = qs.count()
    if n == 0:
        return None
    total = 0.0
    for p in qs:
        actual = 1.0 if p.was_correct else 0.0
        total += (float(p.confidence) - actual) ** 2
    return round(total / n, 4)


def trust_adjustment_for(agent: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> float:
    """Multiplier in [0.5, 1.3] reflecting the agent's historical reliability.

    Default 1.0 when sample size is too small. Brier-score-based:
      - bs ≤ 0.10 → 1.30 (well-calibrated, confident, correct often)
      - bs ≤ 0.20 → 1.15
      - bs ≤ 0.25 → 1.00 (around random; no boost, no damp)
      - bs ≤ 0.35 → 0.80
      - bs >  0.35 → 0.50 (markedly poor — heavily damped)
    """
    AgentPrediction = _AgentPrediction()
    qs = AgentPrediction.objects.filter(
        agent=agent, was_correct__isnull=False,
        evaluated_at__gte=timezone.now() - timedelta(days=lookback_days),
    )
    if qs.count() < MIN_SAMPLE_FOR_TRUST:
        return 1.0

    bs = brier_score(agent, lookback_days)
    if bs is None:
        return 1.0
    if bs <= 0.10:
        return 1.30
    if bs <= 0.20:
        return 1.15
    if bs <= 0.25:
        return 1.00
    if bs <= 0.35:
        return 0.80
    return 0.50


# ── Legacy API (kept for backwards compat with views.agent_calibration_api) ─

class CalibrationTracker:
    """Track and report agent calibration metrics."""

    def get_agent_accuracy(self, agent_name, lookback_days=DEFAULT_LOOKBACK_DAYS):
        AgentPrediction = _AgentPrediction()
        cutoff = timezone.now() - timedelta(days=lookback_days)
        predictions = AgentPrediction.objects.filter(
            agent=agent_name, created_at__gte=cutoff, was_correct__isnull=False,
        )
        total = predictions.count()
        if total == 0:
            return {"agent": agent_name, "total": 0, "note": "no evaluated predictions"}

        correct = predictions.filter(was_correct=True).count()
        accuracy = correct / total

        by_type = {}
        for pt in predictions.values_list("prediction_type", flat=True).distinct():
            tp = predictions.filter(prediction_type=pt)
            t_total = tp.count()
            t_correct = tp.filter(was_correct=True).count()
            by_type[pt] = {
                "total": t_total, "correct": t_correct,
                "accuracy": round(t_correct / t_total, 4) if t_total else 0,
            }

        # Reliability buckets — predicted-confidence vs actual-accuracy.
        calibration = {}
        for bucket in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            bp = predictions.filter(confidence__gte=bucket - 0.05,
                                    confidence__lt=bucket + 0.05)
            bn = bp.count()
            if bn:
                calibration[str(bucket)] = {
                    "predicted_confidence": bucket,
                    "actual_accuracy": round(bp.filter(was_correct=True).count() / bn, 4),
                    "n": bn,
                }

        return {
            "agent": agent_name,
            "total_predictions": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "brier_score": brier_score(agent_name, lookback_days),
            "trust_adjustment": trust_adjustment_for(agent_name, lookback_days),
            "by_type": by_type,
            "calibration": calibration,
            "lookback_days": lookback_days,
        }

    def get_all_agents_accuracy(self):
        AgentPrediction = _AgentPrediction()
        agents = AgentPrediction.objects.values_list("agent", flat=True).distinct()
        return {a: self.get_agent_accuracy(a) for a in agents}

    def suggest_confidence_adjustment(self, agent_name):
        adj = trust_adjustment_for(agent_name)
        return {"adjustment": adj,
                "reason": f"Brier-derived trust adjustment ({adj:.2f}×)"}


# Legacy single-shot helper.
def evaluate_prediction(prediction_id, actual_value, was_correct):
    AgentPrediction = _AgentPrediction()
    pred = AgentPrediction.objects.get(id=prediction_id)
    pred.actual_value = str(actual_value)
    pred.was_correct = was_correct
    pred.evaluated_at = timezone.now()
    pred.save()
    return pred


# ── Direction calls: a claim anyone can grade against a bar ───────────────
#
# Five prediction kinds existed and none was a price direction, though the
# model's own comment listed it first. Every agent that talked about a
# symbol — the strategy advisor's long/short legs, the anomaly scan, the
# three prose briefings — talked into a void: prose, or a table nothing
# read, and a trust score with nothing to score. A direction call is the
# smallest falsifiable claim on this platform: a symbol, up or down, a
# horizon, and the price it was measured from. It resolves against the
# first bar at or after the deadline, with no model in the loop.
DIRECTION_FLAT_BAND = 0.001            # |move| under 0.1% is flat: a miss
DIRECTION_GRACE_HOURS = 48.0           # how long past the deadline to wait for a bar
DIRECTION_MIN_HORIZON_H = 1.0
DIRECTION_MAX_HORIZON_H = 24.0 * 60    # sixty days
DEFAULT_HORIZON_HOURS = 24.0
HORIZON_HOURS_FOR = {"scalp": 4.0, "intraday": 24.0, "swing": 120.0,
                     "position": 480.0}
MARK_MAX_AGE_S = 6 * 3600
_UP = {"up", "long", "buy", "bullish", "higher", "rise", "rising"}
_DOWN = {"down", "short", "sell", "bearish", "lower", "fall", "falling"}

# Appended to every prose agent's system prompt. A briefing that states a
# view and does not put it here has stated nothing the platform can grade.
CALLS_INSTRUCTION = (
    " Finish with a fenced ```json block of exactly this shape: "
    '{"calls": [{"symbol": "AAPL", "direction": "up", "horizon_hours": 24, '
    '"confidence": 0.6, "why": "one line"}]} — one entry for EVERY '
    "directional view stated above, using the platform's own symbols, and "
    "an empty list if you stated none. Each call is graded against the "
    "price at its horizon, and your trust score is built from those grades."
)


def normalise_direction(value) -> Optional[str]:
    v = str(value or "").strip().lower()
    if v in _UP:
        return "up"
    if v in _DOWN:
        return "down"
    return None


def clamp_horizon(hours, default: float = DEFAULT_HORIZON_HOURS) -> float:
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return default
    if h != h:                      # NaN
        return default
    return max(DIRECTION_MIN_HORIZON_H, min(DIRECTION_MAX_HORIZON_H, h))


def mark_for_symbol(symbol: str) -> Optional[float]:
    """The last price the platform knows for `symbol`, or None.

    A fresh LiveQuote first, then the newest bar of the timeframes the
    rule layer reads. Both are the platform's own numbers: a call is
    measured from what Sauron saw, not from what the agent imagined.
    """
    from instruments.models import Instrument
    from market_data.models import LiveQuote, PriceData

    inst = Instrument.objects.filter(symbol=symbol).first()
    if inst is None:
        return None
    now = timezone.now()
    quote = LiveQuote.objects.filter(instrument=inst).first()
    if quote is not None and quote.updated_at is not None and \
            (now - quote.updated_at).total_seconds() <= MARK_MAX_AGE_S:
        try:
            px = float(quote.last or 0)
            if px > 0:
                return px
        except (TypeError, ValueError):
            pass
    bar = (PriceData.objects
           .filter(instrument=inst, timeframe__in=("1h", "4h", "1d"),
                   timestamp__gte=now - timedelta(seconds=MARK_MAX_AGE_S * 8))
           .order_by("-timestamp").first())
    if bar is None:
        return None
    try:
        px = float(bar.close or 0)
    except (TypeError, ValueError):
        return None
    return px if px > 0 else None


def log_direction_prediction(agent: str, symbol, direction, *,
                             horizon_hours=DEFAULT_HORIZON_HOURS,
                             confidence=0.5, reference_price=None,
                             notes: str = ""):
    """Register "symbol goes up/down within horizon_hours", or None.

    None, with the reason logged, when the claim cannot be graded: an
    unknown direction, a symbol the catalogue does not hold, no price to
    measure from, or the same agent already has a live call on the
    symbol. One live call per agent per symbol: an hourly scan that
    re-detects a condition must not stack ten identical claims.
    """
    from instruments.models import Instrument

    AgentPrediction = _AgentPrediction()
    sym = str(symbol or "").strip().upper()
    d = normalise_direction(direction)
    if not sym or d is None:
        return None
    if not Instrument.objects.filter(symbol=sym).exists():
        logger.info("calibration: %s called %s on unknown symbol %s — not "
                    "registered", agent, d, sym)
        return None
    now = timezone.now()
    if AgentPrediction.objects.filter(
            agent=agent, prediction_type="direction", instrument_symbol=sym,
            was_correct__isnull=True, evaluated_at__isnull=True,
            expected_resolution_at__gt=now).exists():
        return None
    ref = reference_price if reference_price else mark_for_symbol(sym)
    try:
        ref = float(ref) if ref is not None else None
    except (TypeError, ValueError):
        ref = None
    if not ref or ref <= 0:
        logger.info("calibration: %s called %s on %s with no price to "
                    "measure from — not registered", agent, d, sym)
        return None
    h = clamp_horizon(horizon_hours)
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = 0.5
    conf = min(1.0, max(0.0, conf))
    return AgentPrediction.objects.create(
        agent=agent, prediction_type="direction", predicted_value=d,
        instrument_symbol=sym, confidence=conf,
        expected_resolution_at=now + timedelta(hours=h),
        reference_price=Decimal(str(round(ref, 6))), horizon_hours=h,
        evaluation_notes=str(notes or "")[:500])


def _resolve_direction_prediction(pred, now=None) -> bool:
    """Grade a call against the first bar at or after its deadline."""
    from market_data.models import PriceData

    now = now or timezone.now()
    deadline = pred.expected_resolution_at
    prefix = (pred.evaluation_notes + " | ") if pred.evaluation_notes else ""
    bar = (PriceData.objects
           .filter(instrument__symbol=pred.instrument_symbol,
                   timeframe__in=("1h", "4h", "1d"),
                   timestamp__gte=deadline)
           .order_by("timestamp").first())
    if bar is None:
        if (now - deadline).total_seconds() < DIRECTION_GRACE_HOURS * 3600:
            return False                    # the bar may still arrive
        pred.actual_value = "ungradeable_no_bar"
        pred.evaluated_at = now
        pred.evaluation_notes = (prefix + f"no bar within "
                                 f"{DIRECTION_GRACE_HOURS:.0f}h after the "
                                 f"deadline — not graded")
        pred.save(update_fields=["actual_value", "evaluated_at",
                                 "evaluation_notes"])
        return True
    try:
        ref = float(pred.reference_price or 0)
    except (TypeError, ValueError):
        ref = 0.0
    if ref <= 0:
        pred.actual_value = "ungradeable_no_reference"
        pred.evaluated_at = now
        pred.evaluation_notes = prefix + "no reference price — not graded"
        pred.save(update_fields=["actual_value", "evaluated_at",
                                 "evaluation_notes"])
        return True
    close = float(bar.close)
    move = (close - ref) / ref
    if move > DIRECTION_FLAT_BAND:
        actual = "up"
    elif move < -DIRECTION_FLAT_BAND:
        actual = "down"
    else:
        actual = "flat"
    pred.actual_value = actual
    pred.was_correct = (actual == pred.predicted_value)
    pred.score = round(move if pred.predicted_value == "up" else -move, 6)
    pred.evaluated_at = now
    pred.evaluation_notes = (
        prefix + f"{pred.instrument_symbol} {ref:.6g} -> {close:.6g} "
        f"({move:+.2%}) by {bar.timestamp:%Y-%m-%d %H:%M} ({bar.timeframe})")
    pred.save()
    return True


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_calls(text: str) -> list:
    """The `calls` list from the LAST fenced JSON block in a briefing."""
    calls: list = []
    for block in _FENCE.findall(str(text or "")):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("calls"), list):
            calls = [c for c in data["calls"] if isinstance(c, dict)]
    return calls


def register_calls(agent: str, calls, *,
                   default_horizon: float = DEFAULT_HORIZON_HOURS) -> int:
    """Register every well-formed call; returns how many were taken."""
    n = 0
    for c in calls or []:
        if not isinstance(c, dict):
            continue
        pred = log_direction_prediction(
            agent, c.get("symbol"), c.get("direction"),
            horizon_hours=clamp_horizon(c.get("horizon_hours"),
                                        default_horizon),
            confidence=c.get("confidence", 0.5),
            notes=str(c.get("why") or c.get("reason") or "")[:300])
        if pred is not None:
            n += 1
    return n


def register_proposal_calls(agent: str, proposal) -> int:
    """Every long/short leg of a strategy proposal becomes a call.

    The advisor's `time_horizon` is a word — scalp, intraday, swing,
    position — mapped to hours here; `hedge` legs claim no direction and
    are not registered.
    """
    if not isinstance(proposal, dict):
        return 0
    horizon = HORIZON_HOURS_FOR.get(
        str(proposal.get("time_horizon", "")).strip().lower(),
        DEFAULT_HORIZON_HOURS)
    thesis = str(proposal.get("thesis") or "")[:300]
    n = 0
    for leg in proposal.get("instruments") or []:
        if not isinstance(leg, dict):
            continue
        pred = log_direction_prediction(
            agent, leg.get("symbol"), leg.get("action"),
            horizon_hours=horizon, confidence=proposal.get("confidence", 0.5),
            notes=thesis)
        if pred is not None:
            n += 1
    return n
