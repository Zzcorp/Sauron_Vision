"""Phase-28 audit-log helpers.

Module-level public surface:
  record_event(kind, data, *, user=None) → AuditLogEntry | None
  verify_chain(*, start_id=None, limit=None) → dict
  hash_payload(prev_hash, kind, data) → str

`record_event` is the single entry point used by every hook. It computes the
hash chain and inserts the row inside a `select_for_update` lock so concurrent
writers see a consistent prev_hash even under race conditions.
"""
from __future__ import annotations

import hashlib
import json
import logging

from django.db import transaction

from .audit_models import AuditLogEntry, GENESIS_HASH

logger = logging.getLogger(__name__)


def hash_payload(prev_hash: str, kind: str, data: dict) -> str:
    """sha256(prev_hash || kind || canonical_json(data)). Deterministic."""
    h = hashlib.sha256()
    h.update((prev_hash or "").encode())
    h.update("|".encode())
    h.update((kind or "").encode())
    h.update("|".encode())
    h.update(json.dumps(data or {}, sort_keys=True, default=str).encode())
    return h.hexdigest()


def record_event(kind: str, data: dict, *, user=None):
    """Append one row to the audit chain. Returns the row, or None on failure
    (errors are swallowed and logged so audit failures never break trading).

    Concurrency: `transaction.atomic()` + `select_for_update` on the latest
    row guarantees prev_hash is read consistently across writers.
    """
    try:
        with transaction.atomic():
            # Lock the latest row to prevent racing writers from chaining off
            # the same prev_hash. On engines without row locks (SQLite tests)
            # this is a no-op but tests are single-threaded so no issue.
            last = (AuditLogEntry.objects
                    .select_for_update(skip_locked=False)
                    .order_by("-id").first())
            prev_hash = last.payload_hash if last else GENESIS_HASH
            payload_hash = hash_payload(prev_hash, kind, data)
            entry = AuditLogEntry(
                user=user, kind=kind, data=data or {},
                prev_hash=prev_hash, payload_hash=payload_hash,
            )
            entry.save()
            return entry
    except Exception as e:
        logger.warning("audit record_event(%s) failed: %s", kind, e)
        return None


def verify_chain(*, start_id: int = None, limit: int = None) -> dict:
    """Walk the chain from `start_id` (or beginning) and recompute hashes.

    Returns:
      {
        "ok": bool,                # True if no breaks detected
        "verified": int,           # how many rows scanned
        "breaks": [
          {"id": ..., "type": "prev_hash_mismatch", ...},
          {"id": ..., "type": "payload_tampered"},
        ]
      }
    """
    qs = AuditLogEntry.objects.order_by("id")
    if start_id is not None:
        qs = qs.filter(id__gte=start_id)
        prev_row = (AuditLogEntry.objects.filter(id__lt=start_id)
                    .order_by("-id").first())
        expected_prev = prev_row.payload_hash if prev_row else GENESIS_HASH
    else:
        expected_prev = GENESIS_HASH
    if limit is not None:
        qs = qs[:limit]

    breaks = []
    n = 0
    for entry in qs.iterator():
        n += 1
        if entry.prev_hash != expected_prev:
            breaks.append({
                "id": entry.id, "type": "prev_hash_mismatch",
                "expected": expected_prev, "actual": entry.prev_hash,
            })
        recomputed = hash_payload(entry.prev_hash, entry.kind, entry.data or {})
        if recomputed != entry.payload_hash:
            breaks.append({
                "id": entry.id, "type": "payload_tampered",
                "expected": recomputed, "actual": entry.payload_hash,
            })
        expected_prev = entry.payload_hash

    return {"ok": len(breaks) == 0, "verified": n, "breaks": breaks}


# ── Convenience helpers used by hook points ───────────────────────────────

def record_trade_open(user, *, trade) -> None:
    """Hook from `AssetBot.scan_symbol` after a trade is created."""
    try:
        data = {
            "trade_id": trade.id,
            "asset_class": trade.asset_class,
            "symbol": trade.symbol,
            "side": trade.side,
            "qty": str(trade.qty),
            "entry_price": str(trade.entry_price),
            "stop_loss": str(trade.stop_loss) if trade.stop_loss is not None else None,
            "take_profit": str(trade.take_profit) if trade.take_profit is not None else None,
            "rule_name": trade.rule_name or "",
            "mode": "paper" if trade.paper else "live",
            "broker_order_id": trade.broker_order_id or "",
        }
        record_event("trade_open", data, user=user)
        from brain.observations import record_observation
        record_observation(kind="audit_event", payload={"audit_kind": "trade_open", **data},
                            source="audit")
    except Exception as e:
        logger.warning("audit record_trade_open failed: %s", e)


def record_trade_close(user, *, trade) -> None:
    """Hook from `AssetBot._close_trade` after grading."""
    try:
        data = {
            "trade_id": trade.id,
            "asset_class": trade.asset_class,
            "symbol": trade.symbol,
            "side": trade.side,
            "qty": str(trade.qty),
            "entry_price": str(trade.entry_price),
            "exit_price": str(trade.exit_price) if trade.exit_price is not None else None,
            "pnl": str(trade.pnl),
            "outcome": trade.outcome or "",
            "realized_r": trade.realized_r,
            "duration_minutes": trade.duration_minutes,
            "rule_name": trade.rule_name or "",
            "mode": "paper" if trade.paper else "live",
        }
        record_event("trade_close", data, user=user)
        from brain.observations import record_observation
        record_observation(kind="fill_closed", payload=data, source="audit")
    except Exception as e:
        logger.warning("audit record_trade_close failed: %s", e)


def record_gate_reject(user, *, asset_class: str, symbol: str, side: str,
                        right: str, reason: str,
                        exposure_before: dict, exposure_after: dict,
                        caps: dict) -> None:
    """Hook from `gate_new_entry` after a reject decision."""
    try:
        data = {
            "asset_class": asset_class, "symbol": symbol, "side": side,
            "right": right, "reason": reason,
            "exposure_before": exposure_before,
            "exposure_after": exposure_after,
            "caps": caps,
        }
        record_event("gate_reject", data, user=user)
        from brain.observations import record_observation
        record_observation(kind="gate_reject", payload=data, source="orchestrator")
    except Exception as e:
        logger.warning("audit record_gate_reject failed: %s", e)


# ── Phase-54 brain-stack audit helpers ──────────────────────────────────
#
# AI-driven decisions that should land in the hash-chained audit log for
# forensics + compliance replay. All wrappers swallow exceptions so audit
# failures NEVER break the calling code path.

def record_proposal_decision(*, proposal, decision: str, reviewed_by: str,
                              notes: str = "") -> None:
    """Hook from generator approve/reject. `decision` ∈ {"approved", "rejected"}."""
    try:
        data = {
            "proposal_id": proposal.id,
            "proposed_name": proposal.proposed_name,
            "decision": decision,
            "reviewed_by": reviewed_by,
            "notes": (notes or "")[:500],
            "direction": proposal.direction,
            "asset_classes": list(proposal.asset_classes or []),
            "min_match_score": float(proposal.min_match_score or 0),
            "horizon_days": int(proposal.suggested_horizon_days or 0),
            "confidence": float(proposal.confidence or 0),
        }
        record_event(f"proposal_{decision}", data)
    except Exception as e:
        logger.warning("audit record_proposal_decision failed: %s", e)


def record_rule_demoted(*, rule_name: str, criterion: str,
                          metrics: dict, notes: str = "") -> None:
    """Hook from auto-demoter. Captures WHY a rule was killed."""
    try:
        data = {
            "rule_name": rule_name,
            "criterion": criterion,
            "metrics": dict(metrics or {}),
            "notes": (notes or "")[:500],
        }
        record_event("rule_demoted", data)
    except Exception as e:
        logger.warning("audit record_rule_demoted failed: %s", e)


def record_rule_restored(*, rule_name: str, restored_by: str = "") -> None:
    """Hook from admin restore — manual override of an auto-demotion."""
    try:
        data = {"rule_name": rule_name, "restored_by": restored_by[:80]}
        record_event("rule_restored", data)
    except Exception as e:
        logger.warning("audit record_rule_restored failed: %s", e)


def record_brain_soft_block(*, user, asset_class: str, symbol: str,
                              rule_name: str, advisory_source: str,
                              status: str = "pause_recommended") -> None:
    """Hook from scan_symbol when brain advisory soft-blocks an entry.
    Different from `gate_reject` — this is an AI-driven block, not a
    deterministic theme/currency cap rejection."""
    try:
        data = {
            "asset_class": asset_class, "symbol": symbol,
            "rule_name": rule_name,
            "advisory_status": status,
            "advisory_source": advisory_source,
        }
        record_event("brain_soft_block", data, user=user)
    except Exception as e:
        logger.warning("audit record_brain_soft_block failed: %s", e)


def record_hypothesis_resolved(*, hypothesis, outcome: str,
                                  resolution_notes: str = "") -> None:
    """Hook from hypothesis market resolver — chains the calibration
    history so trust scores can be reconstructed forensically."""
    try:
        data = {
            "hypothesis_id": hypothesis.id,
            "source_agent": hypothesis.source_agent,
            "claim_text": (hypothesis.claim_text or "")[:300],
            "confidence": float(hypothesis.confidence or 0),
            "outcome": outcome,
            "resolution_notes": (resolution_notes or "")[:300],
            "resolution_criteria": hypothesis.resolution_criteria or {},
        }
        record_event("hypothesis_resolved", data)
    except Exception as e:
        logger.warning("audit record_hypothesis_resolved failed: %s", e)
