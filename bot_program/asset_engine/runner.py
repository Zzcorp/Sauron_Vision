"""AssetBot runners — invoked from Celery tasks or admin "Run Now" buttons.

Two entry points:
  - run_asset_bot_tick(config_id) → run one config's tick
  - run_all_asset_bots() → tick every enabled config; aggregate result

Both swallow per-bot exceptions (one bot's failure must not stop others).

THE FLEET PASS HAS TWO SHAPES (2026-09-12). With `pipeline_capital_desk`
off it is the loop it has always been: config after config, each one's
`tick()` running manage → gate → scan, and the third config proposing its
entry after the first two have already filled. With the component on it runs
two-phase — every config PROPOSES first (nothing is sent, the ticker is read
through the data session), the capital desk ranks the whole tick's
opportunities against one risk budget per venue, and only then does anything
execute. That is the only way a desk can see the opportunities side by side,
which is the whole of the operator's ask.

`run_asset_bot_tick(config_id)` is untouched by all of it: a single config's
tick is not a fleet, there is nothing to rank it against, and HQ's "Run Now"
must keep doing exactly what the button says.
"""
import logging
import uuid

from .base import make_bot

logger = logging.getLogger(__name__)


def run_asset_bot_tick(config_id: int) -> dict:
    """Run one tick for the given AssetBotConfig. Returns the bot's summary dict
    (or an error dict if the config is missing / disabled)."""
    from bot_program.models import AssetBotConfig

    cfg = AssetBotConfig.objects.filter(id=config_id).first()
    if cfg is None:
        return {"status": "error", "reason": "config_not_found", "config_id": config_id}
    if not cfg.enabled:
        return {"status": "skipped", "reason": "disabled", "config_id": config_id}

    try:
        bot = make_bot(cfg)
    except Exception as e:
        return {"status": "error", "reason": f"make_bot_failed: {e}",
                "config_id": config_id}

    try:
        return {"status": "ok", **bot.tick()}
    except Exception as e:
        logger.exception("[asset_bot] tick raised for cfg=%s", config_id)
        return {"status": "error", "reason": str(e), "config_id": config_id}


def _release_sessions():
    """Hand the exclusive IBKR trading session back BETWEEN configs. It
    is one clientId for the whole deployment — an order is visible
    only to the session that placed it — so holding it across a fleet
    of configs would keep the pending-close drain, a manual close and
    the kill switch waiting for minutes. Released per config, the
    longest anyone waits is one config's tick."""
    try:
        from bot_program.engine.ibkr_sessions import release_trade_sessions
        release_trade_sessions()
    except Exception as e:  # noqa: BLE001 — never break the loop
        logger.debug("[asset_bot] releasing the trade session: %s", e)


def run_all_asset_bots() -> dict:
    """Tick every enabled AssetBotConfig. Returns aggregate summary.

    Routed on `pipeline_capital_desk`: off is the legacy loop and costs one
    component read; on is the two-phase pass the desk needs. An unreadable
    component is OFF — the fleet's normal behaviour is never gated on a
    switch nobody could read.
    """
    try:
        from bot_program.capital_desk import is_desk_enabled
        desked = is_desk_enabled()
    except Exception as e:  # noqa: BLE001 — see the docstring
        logger.warning("[desk] component unreadable (%s) — legacy loop", e)
        desked = False
    if not desked:
        return _run_all_legacy()
    return _run_all_desked()


def _run_all_legacy() -> dict:
    """The loop as it was before the desk: one config at a time, whole."""
    from bot_program.models import AssetBotConfig

    summaries = []
    for cfg in AssetBotConfig.objects.filter(enabled=True):
        summaries.append(run_asset_bot_tick(cfg.id))
        _release_sessions()

    return {
        "status": "ok",
        "configs_ticked": len(summaries),
        "summaries": summaries,
    }


# ── The two-phase pass ───────────────────────────────────────────────────

def _last_skip_code(cfg, symbol: str) -> str:
    """The code `execute_entry` recorded on its way to returning None."""
    try:
        from bot_program.asset_engine import skips
        return str((skips.last_by_symbol(cfg).get(symbol) or {}).get("code", ""))
    except Exception:  # noqa: BLE001 — a diagnostic, never a failure
        return ""


def _stamp_desk_keys(trade_id, *, plan, decision, cand):
    """Write the desk's own fields onto the row that was just created.

    A SEPARATE save(update_fields=["metadata"]) right after the row exists,
    rather than a parameter threaded through execute_entry: the entry path
    owns that dict and every key in it is evidence about the TRADE. These
    eight are evidence about the DECISION, and the row must be complete and
    correct whether or not the desk is in the picture.
    """
    from bot_program.models import AssetBotTrade

    try:
        trade = AssetBotTrade.objects.filter(id=trade_id).first()
        if trade is None:
            return
        meta = dict(trade.metadata or {})
        meta.update({
            "desk_plan_id": plan.pk,
            "desk_decision_id": getattr(decision, "pk", None),
            "desk_mode": plan.mode,
            "desk_size_mult": float(getattr(decision, "size_mult", 1.0)),
            "desk_qty_default": float(cand.qty_default),
            "desk_risk_dollars_default": float(cand.risk_dollars_default),
            "desk_e_r": getattr(decision, "e_r", None),
            "desk_lane": getattr(decision, "lane", ""),
        })
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
    except Exception as e:  # noqa: BLE001 — the row matters, the stamp does not
        logger.warning("[desk] could not stamp desk keys on trade %s: %s",
                       trade_id, e)


def _propose_phase(cfg, *, signal_stats, candidates, not_desked, summaries):
    """PHASE 1 for one config: manage, gate, then propose (or, for a lane
    that is not desked, trade whole exactly as today)."""
    from bot_program.asset_engine.safety import write_heartbeat
    from bot_program.models import AssetBotTrade

    try:
        bot = make_bot(cfg)
    except Exception as e:  # noqa: BLE001 — one config's failure is its own
        logger.warning("[asset_bot] make_bot failed for cfg=%s: %s", cfg.id, e)
        summaries.append({"status": "error", "config_id": cfg.id,
                          "reason": f"make_bot_failed: {e}"})
        return None

    opened, proposed = [], 0
    gate_reason = ""
    try:
        write_heartbeat(cfg, status="RUNNING")
        managed = bot.manage_positions()
        ok, gate_reason = bot.can_open_new()
        if ok and not getattr(bot, "DESKED", True):
            # The options lane overrides scan_symbol wholesale and in a
            # different order. It trades HERE, whole, as it always has, and
            # the desk files what it opened as 'not_desked' — never
            # displaced, never resized. Its fills are already exposure by
            # the time the budget is computed, which is correct: the desk
            # must budget around a lane it does not control.
            for symbol in (cfg.symbols or []):
                try:
                    res = bot.scan_symbol(symbol)
                    if res:
                        opened.append(res)
                        trade = AssetBotTrade.objects.filter(
                            id=res.get("trade_id")).first()
                        venue = ("paper" if (trade is None or trade.paper)
                                 else "live")
                        not_desked[venue].append({
                            "config_id": cfg.id, "symbol": res.get("symbol", ""),
                            "direction": res.get("side", ""),
                            "rule_name": getattr(trade, "rule_name", ""),
                            "qty": res.get("qty"), "price": res.get("entry"),
                            "stop": getattr(trade, "stop_loss", None),
                            "target": getattr(trade, "take_profit", None),
                            "trade_id": res.get("trade_id"),
                        })
                    ok, gate_reason = bot.can_open_new()
                    if not ok:
                        break
                except Exception as e:  # noqa: BLE001 — one symbol, one pass
                    logger.warning("[%s_bot] scan_symbol(%s) failed: %s",
                                   bot.asset_class, symbol, e)
        elif ok:
            # Nothing fills in this phase, so there is no per-symbol
            # can_open_new re-check here: the gate can only move on a fill,
            # and the first fill of this pass is still two phases away. The
            # re-check lives in the executing phase, where fills happen.
            for symbol in (cfg.symbols or []):
                try:
                    cand = bot.propose_entry(symbol, pricing="data",
                                             signal_stats=signal_stats)
                    if cand is not None:
                        candidates.append(cand)
                        proposed += 1
                except Exception as e:  # noqa: BLE001 — one symbol, one pass
                    logger.warning("[%s_bot] propose_entry(%s) failed: %s",
                                   bot.asset_class, symbol, e)
        write_heartbeat(cfg, status="OK", note=gate_reason)
        summaries.append({"status": "ok", "asset_class": bot.asset_class,
                          "config_id": cfg.id, "managed": managed,
                          "opened": opened, "proposed": proposed,
                          "gate_reason": gate_reason})
    except Exception as e:  # noqa: BLE001 — one config's failure is its own
        logger.exception("[asset_bot] propose phase raised for cfg=%s", cfg.id)
        summaries.append({"status": "error", "config_id": cfg.id,
                          "reason": str(e)})
    return bot


def _execute_one(bot, cand, *, mult, plan, decision, opened, halted):
    """Run one candidate through execute_entry and record what happened.

    The last two gates before real units move, both re-read from the
    database: `_still_armed` (the kill switch may have landed between the
    proposal and now) and `can_open_new` (an earlier fill on this same tick
    may have taken the config's last slot, or tipped its 24h loss). A
    candidate refused here is `chosen_then_refused`, which is a different
    fact from `displaced`: the desk wanted it and the book would not take it.
    """
    cfg = bot.cfg
    if halted.get(cfg.pk):
        _mark_refused(decision, halted[cfg.pk])
        return None
    try:
        armed = bot._still_armed()
    except Exception:  # noqa: BLE001 — unreadable fails open, as it does in the bot
        armed = True
    if not armed:
        _mark_refused(decision, "config was disarmed mid-tick")
        halted[cfg.pk] = "config was disarmed mid-tick"
        return None
    try:
        ok, why = bot.can_open_new()
    except Exception as e:  # noqa: BLE001 — see above
        ok, why = True, f"gate unreadable: {e}"
    if not ok:
        _mark_refused(decision, why)
        halted[cfg.pk] = why
        return None

    # ONE SYMBOL, ONE PASS — exactly the tolerance the legacy loop had.
    # `tick()` wrapped every `scan_symbol` in this try, so a bot that threw
    # on one entry cost that entry and nothing else. Unwrapped here, the
    # same exception would escape the per-user loop, the fleet pass and the
    # Celery task: one bad symbol would stop every remaining config of every
    # remaining user, in SHADOW as well as live (2026-09-12).
    try:
        res = bot.execute_entry(cand, size_mult=mult)
    except Exception as e:  # noqa: BLE001 — see above
        logger.warning("[%s_bot] execute_entry(%s) failed: %s",
                       bot.asset_class, cand.symbol, e)
        res = None
    if not res:
        _mark_refused(decision,
                      _last_skip_code(cfg, cand.symbol) or "refused at execution")
    elif decision is not None:
        decision.trade_id = res.get("trade_id")
        decision.qty_final = res.get("qty")
        try:
            decision.save(update_fields=["trade_id", "qty_final"])
        except Exception as e:  # noqa: BLE001 — the trade is what matters
            logger.warning("[desk] could not link decision %s: %s",
                           decision.pk, e)
        if plan is not None:
            _stamp_desk_keys(res.get("trade_id"), plan=plan,
                             decision=decision, cand=cand)
    if res:
        opened.append(res)
    # A fill can close the config's gate for the rest of this pass, exactly
    # as the legacy loop's per-symbol re-check did.
    try:
        ok, why = bot.can_open_new()
        if not ok:
            halted[cfg.pk] = why
    except Exception:  # noqa: BLE001
        pass
    return res


def _mark_refused(decision, reason: str):
    from bot_program.models import DeskDecision

    if decision is None:
        return
    # ONLY A DECISION THE DESK ACTUALLY CHOSE CAN BE "CHOSEN, THEN REFUSED".
    # In SHADOW every candidate executes — the displaced and the duplicates
    # included, because shadow must leave the fleet unchanged — so this is
    # reached for rows the desk REFUSED. Overwriting their outcome would
    # erase the displacement `resolve_counterfactuals` keys off (the row
    # would never be walked, and never enter the default set the desk is
    # graded against), and it would leave the plan's own n_displaced
    # disagreeing with its rows on the ladder (2026-09-12).
    if decision.outcome not in (DeskDecision.OUTCOME_CHOSEN,
                                DeskDecision.OUTCOME_RESIZED):
        return
    try:
        decision.outcome = DeskDecision.OUTCOME_REFUSED_AFTER
        decision.reason = str(reason)[:120]
        decision.save(update_fields=["outcome", "reason"])
    except Exception as e:  # noqa: BLE001 — a label, never a failure
        logger.warning("[desk] could not mark decision %s refused: %s",
                       getattr(decision, "pk", "?"), e)


def _log_displacement(cand, plan, decision):
    """One graded call per displaced entry: the desk claims the direction it
    refused to take, so the ledger can ask later whether the displacements
    were the right ones. `log_direction_prediction` keeps ONE live call per
    (agent, symbol) and returns None silently when there already is one —
    tolerated on purpose, that is the dedup doing its job."""
    try:
        from ai_agents.calibration import log_direction_prediction
        agent = f"desk:{cand.cfg_id}"[:50]
        log_direction_prediction(
            agent, cand.symbol, cand.direction,
            horizon_hours=float(cand.horizon_hours),
            confidence=float(cand.decision.score or 0.5),
            reference_price=float(cand.price),
            notes=(f"desk:displaced;plan={plan.pk};"
                   f"rule={cand.rule_name}")[:200],
        )
    except Exception as e:  # noqa: BLE001 — a prediction never costs a tick
        logger.debug("[desk] displacement prediction failed for %s: %s",
                     cand.symbol, e)


def _run_all_desked() -> dict:
    """PHASE 1 propose → PHASE 2 rank → PHASE 3 execute, per user."""
    from collections import OrderedDict

    from bot_program import capital_desk
    from bot_program.models import AssetBotConfig, DeskPlan
    from bot_program.asset_engine.aggregation import signal_stats_for_tick
    from bot_program.asset_engine import skips

    try:
        # Six months of per-rule signal history, computed ONCE for the whole
        # fleet pass rather than once per symbol per config.
        signal_stats = signal_stats_for_tick()
    except Exception as e:  # noqa: BLE001 — an empty aggregate weighs neutral
        logger.warning("[desk] signal stats unreadable: %s", e)
        signal_stats = {}

    by_user = OrderedDict()
    for cfg in AssetBotConfig.objects.filter(enabled=True):
        by_user.setdefault(cfg.user_id, []).append(cfg)

    summaries, plan_rows = [], []
    for _user_id, configs in by_user.items():
        user = configs[0].user
        tick_id = uuid.uuid4()
        candidates = []
        not_desked = {"paper": [], "live": []}
        bots = {}

        # ── PHASE 1 ──────────────────────────────────────────────────────
        for cfg in configs:
            bot = _propose_phase(cfg, signal_stats=signal_stats,
                                 candidates=candidates,
                                 not_desked=not_desked, summaries=summaries)
            if bot is not None:
                bots[cfg.id] = bot
            _release_sessions()

        venues = {c.venue for c in candidates}
        venues |= {v for v, rows in not_desked.items() if rows}
        if not venues:
            continue

        # ── PHASE 2 ──────────────────────────────────────────────────────
        plans, desk_error = [], ""
        try:
            for venue in ("live", "paper"):
                if venue not in venues:
                    continue
                plans.append(capital_desk.plan_for(
                    user, venue, candidates, tick_id=tick_id,
                    signal_stats=signal_stats,
                    not_desked=not_desked[venue]))
        except Exception as e:  # noqa: BLE001 — FAIL OPEN, see below
            # A ranking agent that goes down must not stop the bots. The
            # failure is recorded on a plan of its own and the fleet then
            # runs exactly as it does with the component off: every
            # candidate, at its own size, in config order.
            desk_error = str(e)
            logger.exception("[desk] plan failed — fleet ran undesked")
            plans = []
            for venue in sorted(venues):
                row = capital_desk.fail_open_plan(user, venue, error=e,
                                                  tick_id=tick_id)
                if row is not None:
                    plan_rows.append(row)
            logger.error("[desk] plan failed — fleet ran undesked: %s", e)

        for entry in plans:
            plan_rows.append(entry["plan"])

        mode = (plans[0]["mode"] if plans else DeskPlan.MODE_SHADOW)
        if desk_error:
            mode = DeskPlan.MODE_SHADOW

        # ── PHASE 3 ──────────────────────────────────────────────────────
        halted, opened = {}, []
        if mode == DeskPlan.MODE_LIVE:
            for entry in plans:
                plan = entry["plan"]
                for decision, cand in entry["decisions"]:
                    bot = bots.get(cand.cfg_id)
                    if bot is None:
                        continue
                    if decision.outcome in ("chosen", "resized"):
                        _execute_one(bot, cand, mult=decision.size_mult,
                                     plan=plan, decision=decision,
                                     opened=opened, halted=halted)
                        _release_sessions()
                    elif decision.outcome in ("displaced", "duplicate"):
                        skips.record(bot.cfg, cand.symbol,
                                     skips.DESK_DISPLACED,
                                     f"plan #{plan.pk}: {decision.reason}")
                        _log_displacement(cand, plan, decision)
                for cand, prev_id, prev_reason in entry["remembered"]:
                    bot = bots.get(cand.cfg_id)
                    if bot is None:
                        continue
                    skips.record(bot.cfg, cand.symbol, skips.DESK_DISPLACED,
                                 f"plan #{prev_id} (remembered): {prev_reason}")
        else:
            # SHADOW — and the fail-open path. EVERY candidate executes, at
            # its own size, in the order the configs were walked, so the
            # fleet does precisely what it would have done with no desk at
            # all. The plan beside it is the counterfactual being graded.
            index = {}
            for entry in plans:
                for decision, cand in entry["decisions"]:
                    index[id(cand)] = (entry["plan"], decision)
            for cand in candidates:
                bot = bots.get(cand.cfg_id)
                if bot is None:
                    continue
                plan, decision = index.get(id(cand), (None, None))
                _execute_one(bot, cand, mult=1.0, plan=plan,
                             decision=decision, opened=opened, halted=halted)
                _release_sessions()

        summaries.append({"status": "ok", "desk": True, "user_id": _user_id,
                          "tick_id": str(tick_id), "mode": mode,
                          "candidates": len(candidates),
                          "executed": len(opened),
                          "plans": [p["plan"].pk for p in plans],
                          "error": desk_error})

    return {
        "status": "ok",
        "desk": True,
        "configs_ticked": sum(1 for s in summaries if "config_id" in s),
        "plans": [p.pk for p in plan_rows],
        "summaries": summaries,
    }
