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

def _world(trade) -> str:
    """position_summary.world_of, fenced: an audit row is never lost to it."""
    try:
        from dashboard.position_summary import world_of
        return world_of(trade)
    except Exception:  # noqa: BLE001 — the row matters more than the word
        return ""


def _exit_model(trade) -> str:
    """"bar_replay" | "mark" for a paper exit, "broker" for a real one;
    "unmanaged" for a paper exit after an unmanaged stretch (ungraded)."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    if not trade.paper:
        return "broker"
    if meta.get("unmanaged_exit"):
        return "unmanaged"
    rec = meta.get("paper_exit")
    return str((rec or {}).get("model") or "mark") if isinstance(rec, dict) \
        else "mark"


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
            # The money world (2026-09-30): "demo" for a broker's demo fill,
            # which "mode" alone calls live. Read by the activity drawer.
            "world": _world(trade),
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
            # None when the exit is unmeasured (2026-10-15), never "None"
            "pnl": str(trade.pnl) if trade.pnl is not None else None,
            "outcome": trade.outcome or "",
            "realized_r": trade.realized_r,
            "duration_minutes": trade.duration_minutes,
            "rule_name": trade.rule_name or "",
            "mode": "paper" if trade.paper else "live",
            "world": _world(trade),
            # how the exit price was found (2026-10-15): a paper exit
            # replayed from the bars ("bar_replay") reads apart from one
            # booked at a tick's mark ("mark"); a real one is the broker's
            "exit_model": _exit_model(trade),
        }
        record_event("trade_close", data, user=user)
        from brain.observations import record_observation
        record_observation(kind="fill_closed", payload=data, source="audit")
    except Exception as e:
        logger.warning("audit record_trade_close failed: %s", e)


def record_funded_refusal(user, *, asset_class: str, symbol: str, side: str,
                          reason: str, closes: list) -> None:
    """THE FUNDING CLOSES OF A REFUSED TICKET (2026-10-31): a TAKE TRADE
    ticket refused AFTER its funding closes ran (manual_trade._execute
    runs every check it can before the first close; what is left can only
    be judged after them). The closes are irreversible and realised P&L:
    the row names each one — id, symbol, side, units, exit price, P&L —
    beside the refusal, so a review can see the money moved for a trade
    that never opened. Kind "funded_refusal" (a data kind, never
    KIND_CHOICES: a choices change is a migration)."""
    try:
        record_event("funded_refusal", {
            "asset_class": asset_class, "symbol": symbol, "side": side,
            "reason": str(reason or "")[:500], "closes": list(closes or []),
        }, user=user)
    except Exception as e:
        logger.warning("audit record_funded_refusal failed: %s", e)


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


def record_share_plan(plan, decision: str, user=None) -> None:
    """Hook from the share allocator's apply / reject / rollback.

    `decision` is 'applied' | 'rejected' | 'rolled_back'. The targets and
    the previous shares ride in the row so a re-sized pool can be traced
    to the plan and the admin that confirmed it — the PIN on the page is
    the consent, this is the receipt (2026-09-12). `user` may be an
    AnonymousUser or a shell caller; only a saved account is linked.
    """
    try:
        who = user if getattr(user, "is_authenticated", False) and \
            getattr(user, "pk", None) else None
        data = {
            "plan_id": plan.pk,
            "owner": getattr(plan.user, "username", str(plan.user_id)),
            "decision": decision,
            "state": plan.state,
            "targets": dict(plan.targets or {}),
            "previous_shares": dict(plan.previous_shares or {}),
            "reading_value": (str(plan.reading_value)
                              if plan.reading_value is not None else None),
            "reading_currency": plan.reading_currency or "",
            "governor": float(plan.governor or 1.0),
            "drawdown_pct": plan.drawdown_pct,
            "by": getattr(who, "username", "") or "",
        }
        record_event("share_plan", data, user=who)
    except Exception as e:
        logger.warning("audit record_share_plan failed: %s", e)


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


# ── Reach the phone, keep the record (2026-10-08) ────────────────────────
# The wiring audit of 2026-10-08 found two decisions that left no row a
# page could read: a ladder move onto or off real money (a PromotionEvent
# and an INFO log line, signals/promotion_pipeline._transition) with the
# nightly sweep's refusals in a log line alone, and a config's brake (an
# extras record that enable_config pops, bot_program/asset_engine/
# disarm.py). These kinds put them on the chain. Every one fits
# AuditLogEntry.kind, a 20-wide column Postgres enforces (pinned by
# tests/test_reach_the_phone.py).

#: A rule moved onto, off or between the live stages.
LADDER_MOVE = "ladder_move"
#: The nightly sweep's whole answer: promoted, demoted, held back.
LADDER_SWEEP = "ladder_sweep"
#: A config turned off (disarm.disable_config), whoever did it.
CONFIG_BRAKED = "config_braked"
#: A config turned back on (disarm.enable_config): whose stop it lifted.
CONFIG_REARMED = "config_rearmed"

AUDIT_KINDS_20261008 = (LADDER_MOVE, LADDER_SWEEP, CONFIG_BRAKED,
                        CONFIG_REARMED)

# ── The live-money switches (2026-10-23, core/switch_pin.py) ────────────
# A LIVE_MONEY_SWITCHES key turned on (with the trading PIN), turned off
# (free), or refused ON (no PIN, a wrong one, or a door that never takes
# one). Who, through which door, and when (created_at). Never the PIN,
# its length or its hash. Same 20-wide column as the kinds above.

#: A live-money switch turned ON, the PIN verified.
SWITCH_ARMED = "switch_armed"
#: A live-money switch turned OFF (stopping never asks for the PIN).
SWITCH_DISARMED = "switch_disarmed"
#: An ON refused: the row was left as it was.
SWITCH_REFUSED = "switch_refused"

AUDIT_KINDS_SWITCH = (SWITCH_ARMED, SWITCH_DISARMED, SWITCH_REFUSED)


def record_switch(kind: str, *, key: str, name: str = "", via: str,
                  who: str, before, after, reason: str = "",
                  user=None) -> None:
    """One flip (or refused flip) of a live-money switch on the chain.
    `via` is the door (ops, admin_dashboard, system_map, shell,
    django_admin, all_off); `who` the username, or "shell". Only a saved
    account is linked as `user`. Never raises: an audit failure neither
    blocks nor allows a switch."""
    try:
        linked = user if getattr(user, "is_authenticated", False) and \
            getattr(user, "pk", None) else None
        data = {
            "key": str(key or "")[:50],
            "name": str(name or "")[:100],
            "via": str(via or "")[:20],
            "who": str(who or "")[:80],
            "before": None if before is None else bool(before),
            "after": None if after is None else bool(after),
            "reason": str(reason or "")[:40],
        }
        record_event(kind, data, user=linked)
    except Exception as e:
        logger.warning("audit record_switch(%s) failed: %s", kind, e)


# ── The trading PIN at every door (2026-10-23, core/trading_pin.py) ─────
# Wrong answers one to five, the fifth, a right PIN given past five, an
# ended session, and the live arms of the legacy crypto bot. Constants
# only, never KIND_CHOICES (a choices change is a migration). Same
# 20-wide column. Never the PIN, its length or its hash.

#: A refused PIN: a counted guess, an ended session, "log in again", or
#: a live arm at a door that never takes one.
PIN_REFUSED = "pin_refused"
#: The session's fifth wrong answer (once per session).
PIN_SPENT = "pin_spent"
#: A right PIN given after five wrong answers (a stop, or the lock).
PIN_OK_SPENT = "pin_ok_spent"
#: The legacy crypto BotConfig armed LIVE, or a live one turned off.
LEGACY_BOT_ARMED = "legacy_bot_armed"
LEGACY_BOT_OFF = "legacy_bot_off"

AUDIT_KINDS_PIN = (PIN_REFUSED, PIN_SPENT, PIN_OK_SPENT, LEGACY_BOT_ARMED,
                   LEGACY_BOT_OFF)


def record_pin(kind: str, *, who: str, door: str, act: str,
               reason: str = "", attempts=None, ended: bool = False,
               user=None, **extra) -> None:
    """One PIN event on the chain: which door class, which act, why, the
    session's count and whether the session ended. Never raises."""
    try:
        linked = user if getattr(user, "is_authenticated", False) and \
            getattr(user, "pk", None) else None
        data = {
            "who": str(who or "")[:80],
            "door": str(door or "")[:10],
            "act": str(act or "")[:40],
            "reason": str(reason or "")[:40],
            "attempts": None if attempts is None else int(attempts),
            "ended": bool(ended),
        }
        for k, v in extra.items():
            data[str(k)[:20]] = v if isinstance(v, (bool, int)) \
                else str(v)[:40]
        record_event(kind, data, user=linked)
    except Exception as e:
        logger.warning("audit record_pin(%s) failed (%s)", kind,
                       type(e).__name__)


# ── The demo short proofs (2026-10-31, bot_program/short_proofs.py) ─────
# A superuser revoked a short the platform proved on eToro's demo account
# (the bots' gate reads it no more), or cleared the runner's in-doubt stop
# (it goes on), with the trading PIN on /short-proofs/. Constants only,
# never KIND_CHOICES; the same 20-wide column. Never an order id, a
# position id or an amount.

#: A recorded demo short proof revoked.
SHORT_PROOF_REVOKED = "short_proof_revoked"
#: The demo proofs' in-doubt stop cleared.
SHORT_PROOF_CLEARED = "short_proof_cleared"

AUDIT_KINDS_SHORT_PROOF = (SHORT_PROOF_REVOKED, SHORT_PROOF_CLEARED)


def record_short_proof(kind: str, *, row, who: str, reason: str = "",
                       user=None, rows=None) -> None:
    """One revoke or clear on the chain: the row's number, its class,
    instrument, multiplier, world and step, whether it was the overnight
    hold, who, and why; and `rows`, the numbers of every row the act
    marked (a revoke marks every standing proof of the class at that
    multiplier, 2026-10-31). Never raises."""
    try:
        linked = user if getattr(user, "is_authenticated", False) and \
            getattr(user, "pk", None) else None
        data = {
            "row": int(row.pk),
            "rows": [int(r.pk) for r in (rows or [row])][:50],
            "asset_class": str(row.asset_class or "")[:12],
            "symbol": str(row.symbol or "")[:40],
            "leverage": int(row.leverage or 1),
            "world": str(row.world or "")[:8],
            "state": str(row.proof_state or "")[:16],
            "overnight": bool(row.overnight),
            "who": str(who or "")[:80],
            "reason": str(reason or "")[:120],
        }
        record_event(kind, data, user=linked)
    except Exception as e:
        logger.warning("audit record_short_proof(%s) failed (%s)", kind,
                       type(e).__name__)


def record_legacy_bot(cfg, *, on: bool, via: str, who: str,
                      user=None) -> None:
    """A legacy crypto BotConfig turned on in LIVE mode, or a live one
    turned off: whose, by whom, through which door. Never raises."""
    try:
        linked = user if getattr(user, "is_authenticated", False) and \
            getattr(user, "pk", None) else None
        owner = getattr(getattr(cfg, "user", None), "username", "") or ""
        data = {"config_id": getattr(cfg, "pk", None),
                "owner": str(owner)[:80], "mode": str(cfg.mode)[:8],
                "via": str(via or "")[:20], "who": str(who or "")[:80]}
        record_event(LEGACY_BOT_ARMED if on else LEGACY_BOT_OFF, data,
                     user=linked)
    except Exception as e:
        logger.warning("audit record_legacy_bot failed (%s)",
                       type(e).__name__)


def record_ladder_move(event, *, by: str = "", size_note: str = "") -> None:
    """One PromotionEvent that touched a live stage, on the chain. Called
    inside _transition's transaction: a move rolled back takes its row
    with it. `size_note` is what the move set besides the stage (Aragorn's
    pair verdicts). Never raises."""
    try:
        who = getattr(event, "triggered_by", None)
        data = {
            "event_id": event.pk,
            "rule_name": event.rule_name,
            "from_stage": event.from_stage or "",
            "to_stage": event.to_stage,
            "reason": event.reason,
            "notes": (event.notes or "")[:500],
            "expectancy": event.expectancy_at_transition,
            "n": event.n_at_transition,
            "by": (by or getattr(who, "username", "") or "")[:80],
        }
        if size_note:
            data["size_note"] = str(size_note)[:300]
        record_event(LADDER_MOVE, data, user=who)
    except Exception as e:
        logger.warning("audit record_ladder_move failed: %s", e)


def record_ladder_sweep(result: dict) -> None:
    """The nightly sweep's answer (auto_evaluate_all_rules): the rules it
    promoted, demoted and HELD BACK with the evidence gate's sentence,
    which until now lived in a log line and the returned dict. Never
    raises."""
    try:
        data = {
            "promoted": list(result.get("promoted") or []),
            "demoted": list(result.get("demoted") or []),
            "blocked": [{"rule_name": str(b.get("rule_name") or ""),
                         "target": str(b.get("target") or ""),
                         "reason": str(b.get("reason") or "")[:300]}
                        for b in (result.get("blocked") or [])
                        if isinstance(b, dict)],
        }
        record_event(LADDER_SWEEP, data)
    except Exception as e:
        logger.warning("audit record_ladder_sweep failed: %s", e)


def _config_facts(cfg) -> dict:
    return {"config_id": getattr(cfg, "pk", None),
            "config": str(getattr(cfg, "name", "") or "")[:120],
            "asset_class": str(getattr(cfg, "asset_class", "") or ""),
            "mode": str(getattr(cfg, "mode", "") or "")}


def record_config_braked(cfg, record: dict, *, superseded: bool = False,
                         adopted: bool = False) -> None:
    """A config turned off (disarm.disable_config, disarm.adopt_unrecorded):
    the record it carries — by (the code), at, why, who — on the chain,
    where re-arming cannot pop it. `brake` says whether the runner keeps
    managing what it holds (disarm.BRAKES); `superseded` that the kill
    switch replaced a brake's record on a config already off; `adopted`
    that the config was ALREADY off with no record and `bot brake` only
    recorded it (its exits had stopped with it and run again from this
    row, not from a stop made now). Never raises."""
    try:
        from bot_program.asset_engine import disarm
        by = str((record or {}).get("by") or "")
        data = dict(_config_facts(cfg), **{
            "by": by,
            "by_words": disarm.BY_WORDS.get(by, by),
            "brake": by in disarm.BRAKES,
            "at": str((record or {}).get("at") or ""),
            "why": str((record or {}).get("why") or "")[:200],
            "who": str((record or {}).get("who") or "")[:80],
            "superseded": bool(superseded),
        })
        if adopted:
            data["adopted"] = True
        record_event(CONFIG_BRAKED, data, user=getattr(cfg, "user", None))
    except Exception as e:
        logger.warning("audit record_config_braked failed: %s", e)


def record_config_rearmed(cfg, lifted: dict, *, who: str = "",
                          why: str = "") -> None:
    """A config turned back on (disarm.enable_config): who re-armed it and
    whose stop that lifted (the record enable_config cleared, {} when the
    stop kept none). Never raises."""
    try:
        from bot_program.asset_engine import disarm
        lifted = dict(lifted or {})
        by = str(lifted.get("by") or "")
        data = dict(_config_facts(cfg), **{
            "who": str(who or "")[:80],
            "why": str(why or "")[:200],
            "lifted_by": by,
            "lifted_by_words": (disarm.BY_WORDS.get(by, by) if by
                                else "no record of who"),
            "lifted_at": str(lifted.get("at") or ""),
            "lifted_why": str(lifted.get("why") or "")[:200],
            "lifted_who": str(lifted.get("who") or "")[:80],
        })
        record_event(CONFIG_REARMED, data, user=getattr(cfg, "user", None))
    except Exception as e:
        logger.warning("audit record_config_rearmed failed: %s", e)


#: A manual lane's own knobs set from its card on /admin-dashboard/
#: (2026-10-31, manual_trade.set_lane_knobs, behind the trading PIN).
#: 14 characters in the 20-wide column; a constant, never KIND_CHOICES.
LANE_KNOBS_SET = "lane_knobs_set"


def record_lane_knobs(cfg, *, before: dict, after: dict, who: str = "",
                      user=None) -> None:
    """The lane's knobs as they were and as they are now (each None when
    the key is absent: the default stands), with who set them and the
    lane's mode at the time. Never raises: the save stands either way."""
    try:
        linked = user if getattr(user, "is_authenticated", False) and \
            getattr(user, "pk", None) else getattr(cfg, "user", None)
        data = dict(_config_facts(cfg), **{
            "who": str(who or "")[:80],
            "before": {str(k)[:40]: v for k, v in (before or {}).items()},
            "after": {str(k)[:40]: v for k, v in (after or {}).items()},
        })
        record_event(LANE_KNOBS_SET, data, user=linked)
    except Exception as e:  # noqa: BLE001
        logger.warning("audit record_lane_knobs failed: %s", e)


def record_desk_plan(plan, extra: dict = None) -> None:
    """Hook from the capital desk — one row per plan, taken or refused.

    The desk is the only agent on this platform that can cost an
    opportunity without anything appearing in the trade table: a displaced
    entry leaves a DeskDecision and a skip counter and no fill. This row is
    the receipt for that, so the chain carries the budget, the book, what
    was chosen and what was refused on every tick the desk ran.

    'desk_plan' is 14 characters — AuditLogEntry.kind is a 20-wide column
    Postgres enforces, and a kind that overflows raises inside the trading
    path rather than at seed time (2026-09-12).

    NEVER RAISES. A desk that cannot write its audit line still has a plan
    worth executing, and the caller is on the entry path.
    """
    try:
        data = {
            "plan_id": plan.pk,
            "tick_id": str(plan.tick_id),
            "owner": getattr(plan.user, "username", str(plan.user_id)),
            "venue": plan.venue,
            "mode": plan.mode,
            "budget": float(plan.budget or 0),
            "book_risk": float(plan.book_risk or 0),
            # Both, and labelled: the budget was spent in marginal risk,
            # while the raw sum is what the account carries if every stop
            # is hit. One number alone described less than the plan holds
            # (2026-09-12).
            "new_risk_chosen": float(plan.new_risk_chosen or 0),
            "new_risk_marginal": (None if plan.new_risk_marginal is None
                                  else float(plan.new_risk_marginal)),
            "n_candidates": plan.n_candidates,
            "n_chosen": plan.n_chosen,
            "n_resized": plan.n_resized,
            "n_displaced": plan.n_displaced,
            "n_duplicate": plan.n_duplicate,
            "n_not_desked": plan.n_not_desked,
            "matrix_pairs_measured": plan.matrix_pairs_measured,
            "matrix_pairs_total": plan.matrix_pairs_total,
            "error": (plan.error or "")[:300],
        }
        data.update(extra or {})
        record_event("desk_plan", data, user=plan.user)
    except Exception as e:
        logger.warning("audit record_desk_plan failed: %s", e)
