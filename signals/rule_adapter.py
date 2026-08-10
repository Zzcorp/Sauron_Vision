"""Translate what the rule layer emits into what the Signal table stores.

These two halves were written against different dictionary shapes and never
matched. Rules return:

    {"symbol": "BTCUSD", "rule": "rsi_bull_divergence", "direction": "LONG",
     "score": 0.7, "headline": "...", "thesis": "...",
     "entry": 100.0, "stop": 98.5, "target": 103.0}

and `signals/tasks._create_signals_and_notify` reads `result["instrument"]`
and `result["rule_name"]`, finds neither, logs

    "Signal result missing instrument or rule_name — skipping"

and drops the row. Every setup the engine has ever found went that way. It
is the reason 81,000 lines of platform never produced a single trade, and it
survived because the caller discards the created-count and flashes "ok".

`normalise()` is the missing translation. It is deliberately a separate,
directly testable function rather than a few lines inside the persister,
because the absence of a test across this exact seam is what let the gap
live so long.

Both shapes are accepted, so anything already emitting the storage shape
(the opportunity scanner, the SMC bridge) keeps working untouched.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DIRECTION_MAP = {
    "LONG": "bullish", "BUY": "bullish", "BULL": "bullish", "BULLISH": "bullish",
    "SHORT": "bearish", "SELL": "bearish", "BEAR": "bearish", "BEARISH": "bearish",
    "FLAT": "neutral", "NEUTRAL": "neutral", "HOLD": "neutral",
}

VALID_SIGNAL_TYPES = {"technical", "fundamental", "sentiment", "macro",
                      "flow", "ai_generated", "composite"}
VALID_URGENCY = {"critical", "high", "medium", "low"}


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _decimal_or_none(value):
    from decimal import Decimal, InvalidOperation
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _urgency_for(score: float) -> str:
    """Rules do not set urgency; derive it from conviction so the dashboard
    can sort by something meaningful instead of everything being 'medium'."""
    if score >= 0.85:
        return "critical"
    if score >= 0.70:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def normalise(result: dict, *, default_signal_type: str = "technical") -> dict | None:
    """Rule output -> Signal kwargs, or None if it cannot be stored.

    Returns a dict with `instrument` resolved to an Instrument row. None
    means the row genuinely cannot be written, and the caller should say so
    loudly — it is not the silent skip that hid this bug.
    """
    if not isinstance(result, dict):
        logger.warning("[rule_adapter] expected a dict, got %s: %r",
                       type(result).__name__, result)
        return None

    rule_name = _first(result, "rule_name", "rule")
    if not rule_name:
        logger.warning("[rule_adapter] no rule name in %r", result)
        return None

    instrument = result.get("instrument")
    if instrument is None:
        symbol = _first(result, "symbol", "ticker")
        if not symbol:
            logger.warning("[rule_adapter] %s: no instrument and no symbol",
                           rule_name)
            return None
        from instruments.models import Instrument
        instrument = Instrument.objects.filter(symbol=str(symbol).upper()).first()
        if instrument is None:
            logger.warning("[rule_adapter] %s: no Instrument row for %r — the "
                           "rule fired on a symbol the platform does not know",
                           rule_name, symbol)
            return None

    raw_dir = str(_first(result, "direction") or "").upper()
    direction = DIRECTION_MAP.get(raw_dir, raw_dir.lower())
    if direction not in ("bullish", "bearish", "neutral"):
        logger.warning("[rule_adapter] %s: unusable direction %r",
                       rule_name, raw_dir)
        return None

    try:
        score = float(result.get("score", 0) or 0)
    except (TypeError, ValueError):
        logger.warning("[rule_adapter] %s: non-numeric score %r",
                       rule_name, result.get("score"))
        return None

    entry = _decimal_or_none(_first(result, "suggested_entry", "entry"))
    stop = _decimal_or_none(_first(result, "suggested_stop", "stop"))
    target = _decimal_or_none(_first(result, "suggested_target", "target"))

    # price_at_signal is NOT NULL. Flow and fundamental rules emit no price
    # at all, so a naive adapter converts a skipped warning into an uncaught
    # IntegrityError that kills the whole scan on the first such hit.
    price = _decimal_or_none(_first(result, "price_at_signal", "price", "entry"))
    if price is None:
        price = _last_close(instrument)
    if price is None:
        logger.warning("[rule_adapter] %s on %s: no price and no recent bar — "
                       "cannot store a signal without price_at_signal",
                       rule_name, instrument.symbol)
        return None

    rr = result.get("risk_reward_ratio")
    if rr is None and entry and stop and target:
        risk = abs(float(entry) - float(stop))
        if risk > 0:
            rr = round(abs(float(target) - float(entry)) / risk, 4)

    signal_type = str(result.get("signal_type") or default_signal_type).lower()
    if signal_type not in VALID_SIGNAL_TYPES:
        signal_type = default_signal_type

    urgency = str(result.get("urgency") or "").lower()
    if urgency not in VALID_URGENCY:
        urgency = _urgency_for(score)

    title = _first(result, "title", "headline") or f"{instrument.symbol} {direction}"
    description = _first(result, "description", "thesis") or ""

    return {
        "instrument": instrument,
        "signal_type": signal_type,
        "direction": direction,
        "urgency": urgency,
        "title": str(title)[:255],
        "description": str(description),
        "rule_name": str(rule_name),
        "score": score,
        "sub_scores": dict(result.get("sub_scores") or {}),
        "price_at_signal": price,
        "suggested_entry": entry,
        "suggested_stop": stop,
        "suggested_target": target,
        "risk_reward_ratio": rr,
    }


def _last_close(instrument):
    from market_data.models import PriceData
    row = (PriceData.objects.filter(instrument=instrument)
           .order_by("-timestamp").values_list("close", flat=True).first())
    return row


def is_smc_card(d: dict) -> bool:
    """An SMC setup card, which does NOT belong in the Signal table.

    `SmcCompositeRule.evaluate` already calls `persist_cards()`, writing each
    card to SmcSignal with its own lifecycle pass. Storing them again as
    Signal rows would double-count them, and worse: `decide()` votes by
    headcount, so five cards from one detector would read as five
    independent confirmations of what is really a single opinion. The
    opportunity scanner separately emits `advanced_smc_long/short` Signals
    when an SMC setup deserves a vote.

    Cards are identifiable by carrying `setup` with no rule name.
    """
    return bool(d.get("setup")) and not (d.get("rule") or d.get("rule_name"))


def flatten(results) -> list:
    """Rule outputs, one storable dict per signal.

    `SmcCompositeRule.evaluate` returns a LIST of setups while every other
    rule returns a single dict. `SignalEngine.scan_instrument` appends the
    result whole, so `.get()` on the list raises AttributeError and takes
    down the entire scan the first time any SMC setup is detected.
    """
    out = []
    for r in results or []:
        if r is None:
            continue
        items = r if isinstance(r, (list, tuple)) else [r]
        for x in items:
            if not isinstance(x, dict):
                logger.warning("[rule_adapter] ignoring %s in rule output",
                               type(x).__name__)
                continue
            if is_smc_card(x):
                # Already persisted as an SmcSignal — not a defect, and not
                # a warning, or the warning channel stops meaning anything.
                logger.debug("[rule_adapter] SMC card %s already persisted "
                             "separately — not duplicating into Signal",
                             x.get("setup"))
                continue
            out.append(x)
    return out
