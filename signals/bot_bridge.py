"""Bridge that lets the bot read SmcSignal as a composite score.

Used by bot_program/engine/strategy.py instead of (or in addition to)
the legacy Signal table read.

The thing to know before editing this file: `strategy.py` blends this score
only `if smc_score != 0`, so anything that makes this function return 0.0 turns
the entire SMC lane off without a word. That is not hypothetical. The weighting
import named `signals.performance.get_hit_rate`, no such function existed, a
blanket `except Exception` at the top caught the ImportError, and this returned
(0.0, []) on every call from the day it was written — the composite score never
once reached a trading decision. Which imports may be caught and which may not
is therefore load-bearing, and the two blocks below are deliberately separate.
"""
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


# Weight carried by a setup whose hit rate has not been measured. A coin flip,
# because that is what an absent record says: nothing. The setup's own
# conviction then carries the signal by itself. Zero would be a verdict rather
# than a gap — it deletes the setup from the average entirely, and on a fresh
# install, where nothing has closed for any setup yet, it deletes all of them
# and hands this lane back the same permanent 0.0 it just came out of.
UNMEASURED_SETUP_WEIGHT = 0.5


def smc_score_for_symbol(symbol, hours=6, max_signals=10):
    """Return (score, reasons) summarizing recent SmcSignals for a symbol.

    Score is in [-1, +1] where +1 = strong long bias, -1 = strong short.
    Computed as average (direction-signed conviction/100) over recent
    ACTIVE/TRIGGERED signals, weighted by the setup's measured hit rate.
    """
    try:
        from django.utils import timezone
        from signals.models_smc import SmcSignal
    except Exception as e:
        # A legitimate degrade: this can be imported into a process where the
        # signals app is not installed. Nothing was measured, so the lane says
        # nothing — and says out loud that it said nothing.
        logger.warning("smc bridge: SmcSignal unavailable, scoring nothing: %s", e)
        return (0.0, [])

    # Deliberately NOT in the block above and never to be folded into it. An
    # unavailable model is a deployment state; a missing `get_hit_rate` is a
    # broken repo, and the difference is the whole reason this lane spent its
    # life returning zero. Loud, then raised: a lane that cannot weight its own
    # evidence is not degrading, it is broken.
    try:
        from signals.performance import get_hit_rate
    except ImportError:
        logger.exception(
            "smc bridge: signals.performance.get_hit_rate is missing — the SMC "
            "composite score cannot be weighted and this lane is broken")
        raise

    cutoff = timezone.now() - timedelta(hours=hours)
    try:
        recent = list(
            SmcSignal.objects.filter(
                symbol__iexact=symbol,
                created_at__gte=cutoff,
                status__in=["ACTIVE", "TRIGGERED"],
            ).order_by("-created_at")[:max_signals]
        )
    except Exception as e:
        logger.warning("smc bridge: could not read recent %s signals: %s",
                       symbol, e)
        return (0.0, [])

    if not recent:
        return (0.0, [])

    weighted_sum = 0.0
    weight_total = 0.0
    setups_seen = {}
    measured = {}
    for s in recent:
        sign = 1.0 if s.direction == "LONG" else -1.0
        conv = (s.conviction or 0) / 100.0
        if s.setup not in measured:
            # One aggregate per distinct setup rather than one per signal:
            # `get_hit_rate` re-reads the whole 30-day record on every call and
            # this window routinely holds several cards of the same setup.
            measured[s.setup] = get_hit_rate(s.setup)
        rate = measured[s.setup]
        # `is None` and not `or`: a setup MEASURED at 0.0 has a record, and a
        # bad one, so it is weighted at what it earned. Only the absence of a
        # measurement falls back to neutral.
        weight = UNMEASURED_SETUP_WEIGHT if rate is None else rate
        weighted_sum += sign * conv * weight
        weight_total += weight
        setups_seen[s.setup] = setups_seen.get(s.setup, 0) + 1

    if weight_total == 0:
        # Reachable only when every setup in the window is measured at a 0%
        # hit rate — a real finding, and one worth saying rather than
        # returning the same bare zero as "no cards here".
        return (0.0, ["smc +0.00: every recent setup here has a measured 0% "
                      "hit rate"])

    score = max(-1.0, min(1.0, weighted_sum / weight_total))
    reasons = [
        f"smc {score:+.2f} from {len(recent)} signals: "
        + ", ".join(f"{k}x{v}" for k, v in setups_seen.items())
    ]
    return (score, reasons)
