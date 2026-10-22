"""The Orc's thesis (spec §1.4): written once at birth, immutable after.

    {source: entry | reconstructed (| operator, from O1d's page),
     reason, rule, provenance, invalidation[], horizon_market_h,
     reconstructed_from?}

The provenance is an ALLOWLIST of what the entry already wrote: the
debate's verdicts and killer reason, the proof, the stage, the posture
(its level, kind, size and why) and its leverage note, Aragorn's state and
size, the attack tier, the elite flag, the leverage, the cost charged, the
desk's multiplier and lane; on a hand ticket the signal, the size source
and whether each entry check passed. Never the money: no risk_dollars,
capital_use or notional_fraction reaches a thesis.

The desk writes its keys only after execute_entry returns
(runner._stamp_desk_keys), and the idea is born inside execute_entry, so
`complete_provenance` adds those birth-time keys once, right after the
desk's stamp, while the Orc has nothing past its birth lines. Nothing else
ever writes a thesis after birth.

The invalidation predicates are machine-checkable, each marked "by":
"code" (O1b checks them as facts on every tick, bot_program/orcs/
predicates.py): a bot idea's time predicate (the persona's hold, else the
care's no-progress clock) and the displaced break of structure against it
on the decision timeframe (4h; 1d for a stock, an ETF or an Olog-hai once
60 fresh 1d venue bars exist); a hand idea's structure predicate only (the
care never cuts an operator's ticket on a clock); and, from the menu at
birth, a close beyond the nearest 4h structure level between the entry and
the stop.
"""

#: The bot entry's metadata keys a thesis may carry, as they are.
BOT_KEYS = ("debate_cut", "proof", "promotion_stage", "posture",
            "posture_leverage", "aragorn", "leverage",
            "cost_fraction_charged", "desk_size_mult", "desk_lane")
#: The desk's keys, written on the row after the birth (runner.py:536).
DESK_KEYS = ("desk_size_mult", "desk_lane")
#: A hand ticket's.
MANUAL_KEYS = ("signal_id", "size_source", "leverage")
#: The bars the structure predicate is read on until the menu (O1b) says.
STRUCTURE_TF = "4h"
#: A thesis whose time predicate has not moved +1R by then is dead.
TIME_MIN_MFE_R = 1.0
#: The horizon when no persona says one (spec §1.6).
DEFAULT_HORIZON_H = 72.0
REASON_MAX = 300


def _persona_hold(cfg):
    try:
        from bot_program.personas import persona_for
        p = persona_for(cfg)
        hold = (p.fields or {}).get("max_hold_hours") if p else None
        return float(hold) if hold else None
    except Exception:  # noqa: BLE001 — no persona read is no persona
        return None


def horizon(cfg) -> float:
    return _persona_hold(cfg) or DEFAULT_HORIZON_H


def _debate(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    ex = raw.get("executioner") if isinstance(raw.get("executioner"),
                                              dict) else {}
    ch = raw.get("champion") if isinstance(raw.get("champion"), dict) else {}
    out = {"ran": bool(raw.get("ran")), "binding": bool(raw.get("binding")),
           "champion_wins": bool(raw.get("champion_wins")),
           "executioner": str(ex.get("verdict") or ""),
           "champion": str(ch.get("verdict") or "")}
    killer = " ".join(str(ex.get("killer") or "").split())
    if killer:
        out["killer"] = killer[:200]
    return out


#: Never in a thesis, at any depth.
MONEY_KEYS = frozenset({"risk_dollars", "capital_use", "notional_fraction",
                        "risk_fraction", "conviction", "qty", "pnl",
                        "margin", "notional"})


def _clean(value):
    """A provenance value as plain JSON, money keys dropped at any depth."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()
                if str(k) not in MONEY_KEYS}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def provenance(meta, *, manual: bool) -> dict:
    meta = meta if isinstance(meta, dict) else {}
    out = {}
    if manual:
        for key in MANUAL_KEYS:
            if meta.get(key) is not None:
                out[key] = _clean(meta[key])
        for key, value in sorted(meta.items()):
            if key.endswith("_at_entry") and isinstance(value, dict):
                out[key] = bool(value.get("ok", True))
        return out
    debate = _debate(meta.get("debate"))
    if debate:
        out["debate"] = debate
    for key in BOT_KEYS:
        if meta.get(key) is not None:
            out[key] = _clean(meta[key])
    attack = meta.get("attack")
    if isinstance(attack, dict):
        out["attack"] = {k: _clean(attack[k]) for k in ("tier", "leverage")
                         if attack.get(k) is not None}
    if meta.get("elite") or meta.get("elite_past_daily_stop"):
        out["elite"] = True
    return out


def invalidation(trade, cfg, *, manual: bool, menu=None,
                 army_type="") -> list:
    """The machine-checkable predicates, written by code (O1b,
    bot_program/orcs/predicates.code_invalidation): a bot idea's time
    predicate (the persona's hold, else the care's no-progress clock), the
    displaced break against it on the decision timeframe, and, with the
    menu at birth, a close beyond the nearest 4h structure level between the
    entry and the stop."""
    from bot_program.orcs import predicates
    from bot_program.orcs.facts import initial_stop
    hold = None
    if not manual:
        hold = _persona_hold(cfg)
        if hold is None:
            from bot_program.position_care import (NO_PROGRESS_DEFAULT_HOURS,
                                                   NO_PROGRESS_HOURS)
            hold = float(NO_PROGRESS_HOURS.get(str(trade.asset_class),
                                               NO_PROGRESS_DEFAULT_HOURS))
    return predicates.code_invalidation(
        side=trade.side, manual=manual, hold_h=hold, menu=menu,
        entry=trade.entry_price, init_stop=initial_stop(trade),
        tf=predicates.decision_tf(trade.asset_class, army_type, menu))


#: The last stop moves an adopted thesis carries, and its memory's words.
STOP_MOVES_KEPT = 5
MEMORY_WORDS_MAX = 200


def _memory_rule(trade, meta) -> str:
    """The rule behind the row: the signal's for a hand ticket taken on
    one (metadata["signal_id"]), else the row's own unless it is the
    manual rule; "" when no rule backs it."""
    sid = meta.get("signal_id")
    if sid:
        try:
            from signals.models import Signal
            rule = (Signal.objects.filter(pk=int(sid))
                    .values_list("rule_name", flat=True).first())
            if rule:
                return str(rule)
        except Exception:  # noqa: BLE001 — an unread signal backs nothing
            pass
    from bot_program.manual_trade import MANUAL_RULE
    rule = str(trade.rule_name or "")
    return "" if rule == MANUAL_RULE else rule


def setup_memory(trade, meta=None) -> dict:
    """The proving ground's memory of the row's rule on its symbol and
    class (backtester.proving.memory.memory_for, the one the TAKE TRADE
    preview shows): {ok, words}. An unread memory reads ok False; R and
    rates only, never money."""
    meta = meta if isinstance(meta, dict) else (
        trade.metadata if isinstance(trade.metadata, dict) else {})
    try:
        rule = _memory_rule(trade, meta)
        if not rule:
            return {"ok": False, "words": ""}
        from backtester.proving.memory import memory_for
        mem = memory_for(rule, trade.symbol, str(trade.asset_class or ""))
        return {"ok": bool(mem.get("ok")),
                "words": " ".join(str(mem.get("words") or "").split())
                [:MEMORY_WORDS_MAX]}
    except Exception:  # noqa: BLE001 — an unread memory is no memory
        return {"ok": False, "words": ""}


def _moves(moves) -> list:
    """The last stop moves as prices and words: {to, why, when}."""
    if not isinstance(moves, list):
        return []
    out = []
    for m in moves[-STOP_MOVES_KEPT:]:
        if isinstance(m, dict):
            out.append({"to": _clean(m.get("to")),
                        "why": str(m.get("why") or "")[:60],
                        "when": str(m.get("when") or "")[:32]})
    return out


def reconstructed_from(trade) -> dict:
    """What an adopted row's thesis is rebuilt from (§1.2): the care's
    history, the stop moves (how many, and the last few as prices and
    words), the setup memory the ticket showed, the thesis check and the
    latest review verdict."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    th = meta.get("thesis") if isinstance(meta.get("thesis"), dict) else {}
    moves = meta.get("stop_moves")
    out = {"care": {k: care.get(k) for k in ("soft_why", "mfe_r", "mae_r",
                                             "since") if care.get(k) is not None},
           "stop_moves_n": len(moves) if isinstance(moves, list) else 0,
           "stop_moves": _moves(moves),
           "setup_memory": setup_memory(trade, meta),
           "thesis_verdict": str(th.get("verdict") or ""),
           "last_review_verdict": ""}
    try:
        from brain.position_review_models import PositionReview

        from bot_program.orcs.constants import REVIEW_FACT_VERDICTS
        out["last_review_verdict"] = str(
            PositionReview.objects.filter(book="bot", position_id=trade.pk,
                                          verdict__in=REVIEW_FACT_VERDICTS)
            .order_by("-id").values_list("verdict", flat=True).first() or "")
    except Exception:  # noqa: BLE001 — an unread review is no review
        pass
    return out


def build(trade, cfg, *, source: str, manual: bool, menu=None,
          army_type="") -> dict:
    out = {"source": source,
           "reason": " ".join(str(trade.reason or "").split())[:REASON_MAX],
           "rule": str(trade.rule_name or ""),
           "provenance": provenance(trade.metadata, manual=manual),
           "invalidation": invalidation(trade, cfg, manual=manual, menu=menu,
                                        army_type=army_type),
           "horizon_market_h": horizon(cfg)}
    if source == "reconstructed":
        out["reconstructed_from"] = reconstructed_from(trade)
    return out


def complete_provenance(trade, keys=DESK_KEYS) -> bool:
    """Merge the birth-time `keys` the row gained after the idea was born
    (the desk's, stamped after execute_entry returns) into its thesis's
    provenance, ONCE: under the Orc's row lock, only for an entry thesis,
    only while the Orc is still `born` with no fact past its birth lines,
    and never over a key already there. Writes the Orc table only; True
    when it wrote. The caller fences it."""
    from django.db import transaction

    from bot_program.orcs.constants import STATE_BORN
    from bot_program.orcs.models import Orc
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    stamp = meta.get("orc")
    if not isinstance(stamp, dict) or not stamp.get("idea"):
        return False
    with transaction.atomic():
        orc = (Orc.objects.select_for_update()
               .filter(pk=stamp["idea"], root_trade_id=trade.pk).first())
        if orc is None or orc.state != STATE_BORN:
            return False
        seen = dict(orc.seen or {})
        if seen.get("provenance_completed"):
            return False
        if int(seen.get("fact_seq") or 0) != int(seen.get("birth_seq") or 0):
            return False
        thesis = dict(orc.thesis or {})
        if thesis.get("source") != "entry":
            return False
        prov = dict(thesis.get("provenance") or {})
        added = {k: _clean(meta[k]) for k in keys
                 if k not in prov and meta.get(k) is not None}
        seen["provenance_completed"] = True
        orc.seen = seen
        if not added:
            orc.save(update_fields=["seen"])
            return False
        prov.update(added)
        thesis["provenance"] = prov
        orc.thesis = thesis
        orc.save(update_fields=["thesis", "seen"])
    return True
