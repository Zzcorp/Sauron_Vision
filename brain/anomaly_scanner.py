"""Phase 51 — Proactive anomaly scanner.

Pure-Python deterministic detection (no LLM). Runs every 30min on the
beat schedule and emits `anomaly_detected` BrainObservations. The brain
synthesizer + nightly consolidation already consume that kind:
  - Brain reads recent anomalies in its 30min snapshot
  - Consolidation promotes anomalies that recur ≥3x/24h to KnowledgeNodes
    (kind="anomaly")

Each detector emits a STABLE `key` per occurrence type so dedupe works
sensibly. We ALSO de-dup at scan time: if the same (kind, key) already
fired within the last `dedupe_minutes`, skip it. That prevents a single
real anomaly from spamming the queue every 30 minutes for hours.

Detectors shipped in this phase:
  1. brain_regime_flip          — latest BrainReport.regime != prior
  2. rvol_spike                 — instruments with RVOL > threshold
  3. narrative_price_divergence — bullish news + flat/down price (or
                                  bearish news + flat/up price) for held names

More detectors can be added by appending to DETECTORS list — each is a
callable returning a list of `Anomaly` dicts.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────────────

DEDUPE_MINUTES = 90  # don't re-emit the same (kind, key) within this window
MAX_HELD_FOR_NARRATIVE_SCAN = 20  # cost cap on news lookups
RVOL_PERIOD = 20
RVOL_THRESHOLD = 3.0  # 3x average — high bar so we don't spam
NARRATIVE_LOOKBACK_DAYS = 2
NARRATIVE_MIN_ARTICLES = 3
NARRATIVE_MIN_SENTIMENT = 0.3
NARRATIVE_MAX_PRICE_MOVE_PCT = 0.5


# ── Dedupe helper ─────────────────────────────────────────────────────────

def _recent_anomaly_keys(within_minutes: int = DEDUPE_MINUTES) -> set[str]:
    """Set of `f"{payload.detector}:{payload.key}"` from anomaly observations
    in the last N minutes — used to skip duplicates."""
    out: set[str] = set()
    try:
        from .models import BrainObservation
    except Exception:
        return out
    cutoff = timezone.now() - timedelta(minutes=max(1, within_minutes))
    qs = BrainObservation.objects.filter(
        kind="anomaly_detected", created_at__gte=cutoff,
    ).values_list("payload", flat=True)
    for p in qs:
        if not isinstance(p, dict):
            continue
        det = p.get("detector") or ""
        key = p.get("key") or ""
        if det and key:
            out.add(f"{det}:{key}")
    return out


def _emit_anomalies(anomalies: Iterable[dict]) -> int:
    """Persist a batch of anomaly dicts as BrainObservation rows.
    Skips duplicates based on `_recent_anomaly_keys()`. Returns count emitted.
    """
    try:
        from .observations import record_observation
    except Exception:
        return 0

    seen = _recent_anomaly_keys()
    n = 0
    for a in anomalies:
        det = (a or {}).get("detector") or ""
        key = (a or {}).get("key") or ""
        if not det or not key:
            continue
        if f"{det}:{key}" in seen:
            continue
        # Strip non-JSON-serializable Instrument object from the payload
        # before persisting; it's used as a separate FK arg.
        instrument_obj = a.pop("_instrument_obj", None)
        record_observation(
            kind="anomaly_detected", payload=a,
            source="anomaly_scanner", instrument=instrument_obj,
        )
        n += 1
    return n


# ── Detector 1: Brain regime flip ────────────────────────────────────────

def detect_brain_regime_flip() -> list[dict]:
    """If the latest BrainReport's regime differs from the prior, emit one
    anomaly. Idempotent via dedupe (same key based on the new regime label
    + the date — won't re-emit until the next flip)."""
    try:
        from .models import BrainReport
    except Exception:
        return []
    recent = list(BrainReport.objects.filter(error="")
                   .order_by("-created_at")[:2])
    if len(recent) < 2:
        return []
    latest, prior = recent[0], recent[1]
    if latest.regime_label == prior.regime_label:
        return []
    return [{
        "detector": "brain_regime_flip",
        "key": f"{prior.regime_label}_to_{latest.regime_label}_{latest.created_at:%Y%m%d}",
        "from_regime": prior.regime_label,
        "to_regime": latest.regime_label,
        "from_confidence": prior.regime_confidence,
        "to_confidence": latest.regime_confidence,
        "report_id": latest.id,
        "text": (f"Brain regime flipped from {prior.regime_label} "
                  f"({prior.regime_confidence:.2f}) → {latest.regime_label} "
                  f"({latest.regime_confidence:.2f})"),
    }]


# ── Detector 2: RVOL spike ───────────────────────────────────────────────

def detect_rvol_spikes(*, threshold: float = RVOL_THRESHOLD,
                          period: int = RVOL_PERIOD) -> list[dict]:
    """Walk active instruments; for each, compute current bar volume vs
    period-day average. Flag those with ratio ≥ threshold.

    Bounded: walks at most 50 instruments per scan to keep cost predictable.
    """
    out: list[dict] = []
    try:
        from instruments.models import Instrument
        from signals.evaluators_advanced import _eval_relative_volume
    except Exception:
        return out

    candidates = list(Instrument.objects.filter(is_active=True)[:50])
    now = timezone.now()
    for inst in candidates:
        try:
            res = _eval_relative_volume(
                {"period": period, "threshold": threshold,
                 "timeframe": "1d"},
                inst, now,
            )
        except Exception:
            continue
        if not res.get("matched"):
            continue
        details = res.get("details") or {}
        ratio = float(details.get("ratio", 0))
        out.append({
            "detector": "rvol_spike",
            "key": f"{inst.symbol}_{now:%Y%m%d}",
            "symbol": inst.symbol,
            "ratio": round(ratio, 4),
            "threshold": threshold,
            "_instrument_obj": inst,  # consumed by _emit_anomalies, then dropped
            "text": (f"RVOL {ratio:.1f}x on {inst.symbol} "
                      f"(threshold {threshold:.1f}x)"),
        })
    return out


# ── Detector 3: Narrative-vs-price divergence on held names ─────────────

def detect_narrative_price_divergence() -> list[dict]:
    """For each currently-held symbol: if news sentiment is strongly bullish
    but price is flat/down (or strongly bearish but price flat/up), emit an
    anomaly. Uses our existing news_price_divergence evaluator.

    Bounded: at most MAX_HELD_FOR_NARRATIVE_SCAN held names."""
    out: list[dict] = []
    try:
        from instruments.models import Instrument
        from signals.evaluators_advanced import _eval_news_price_divergence
        from .earnings_reviewer import _held_symbols
    except Exception:
        return out

    held = list(_held_symbols())[:MAX_HELD_FOR_NARRATIVE_SCAN]
    if not held:
        return out

    now = timezone.now()
    for sym in held:
        inst = Instrument.objects.filter(symbol__iexact=sym).first()
        if inst is None:
            continue
        # Try both directions; either is anomalous.
        for direction in ("bullish_news_bearish_price",
                           "bearish_news_bullish_price"):
            try:
                res = _eval_news_price_divergence(
                    {"sentiment_dir": direction,
                      "lookback_days": NARRATIVE_LOOKBACK_DAYS,
                      "min_articles": NARRATIVE_MIN_ARTICLES,
                      "min_sentiment": NARRATIVE_MIN_SENTIMENT,
                      "max_price_move_pct": NARRATIVE_MAX_PRICE_MOVE_PCT},
                    inst, now,
                )
            except Exception:
                continue
            if not res.get("matched"):
                continue
            details = res.get("details") or {}
            out.append({
                "detector": "narrative_price_divergence",
                "key": f"{sym}_{direction}_{now:%Y%m%d}",
                "symbol": sym,
                "direction": direction,
                "avg_sentiment": details.get("avg_sentiment"),
                "price_move_pct": details.get("price_move_pct"),
                "n_articles": details.get("n_articles"),
                "_instrument_obj": inst,
                "text": (
                    f"{sym}: {direction.replace('_', ' ')} — sentiment "
                    f"{details.get('avg_sentiment')}, price move "
                    f"{details.get('price_move_pct')}%"
                ),
            })
            break  # one direction match per symbol is enough
    return out


# ── Top-level scanner ────────────────────────────────────────────────────

DETECTORS = [
    detect_brain_regime_flip,
    detect_rvol_spikes,
    detect_narrative_price_divergence,
]


def _load_phase52_detectors() -> None:
    """Late-import correlation-audit detectors (Phase 52 + Phase 53). Kept
    separate so that module reloads in tests don't accumulate duplicates."""
    try:
        from .correlation_audit import (
            detect_position_overlap,
            detect_evaluator_signature_overlap,
            detect_realized_return_correlation,
        )
    except Exception as e:  # pragma: no cover
        logger.warning("[anomaly-scanner] correlation detectors unavailable: %s", e)
        return
    for fn in (detect_position_overlap,
                detect_evaluator_signature_overlap,
                detect_realized_return_correlation):
        if fn not in DETECTORS:
            DETECTORS.append(fn)


_load_phase52_detectors()


def scan_anomalies_now() -> dict:
    """Run all detectors, dedupe, persist as BrainObservations.

    Always returns a summary dict; never raises (per-detector exceptions
    are logged + skipped)."""
    all_anomalies: list[dict] = []
    by_detector: dict[str, int] = {}
    for fn in DETECTORS:
        try:
            anoms = fn() or []
        except Exception as e:  # pragma: no cover
            logger.warning("[anomaly-scanner] detector %s failed: %s",
                            fn.__name__, e)
            continue
        all_anomalies.extend(anoms)
        by_detector[fn.__name__] = len(anoms)

    n_emitted = _emit_anomalies(all_anomalies)
    n_deduped = len(all_anomalies) - n_emitted

    return {
        "ok": True,
        "n_detected": len(all_anomalies),
        "n_emitted": n_emitted,
        "n_deduped": n_deduped,
        "by_detector": by_detector,
    }
