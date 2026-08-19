"""Manual trade execution — the TAKE TRADE button's engine.

A signal proposes; the operator disposes. This module turns one Signal —
or a bare instrument + direction from the watchlist popup — into one
sized, tracked position on demand, using the same sizing, levels, cost
model and bookkeeping the bots use — so a manual trade is graded,
reconciled, kill-switchable and audited exactly like a bot's.

Manual trades live on a per-user, per-class "manual" AssetBotConfig that
is enabled with an EMPTY symbols list: the 5-minute tick manages its open
positions (stops, targets, trailing) every pass, but the entry scan has
nothing to scan, so the config can never open a trade on its own.

Wave 1 executes on the PAPER venue only — the rehearsal stage for the
IBKR wiring. That also keeps the close-to-fund chain synchronous: paper
closes finalize immediately, so "close these, then open" completes
inside one request. The live version routes the same calls through the
broker router and needs the pending-close state machine plus the PIN.

Safety posture (each learned from adversarial review of the first cut):
  * A disabled manual config is a DELIBERATE state — the kill switch or
    the operator put it there — so this module refuses instead of
    silently re-arming it.
  * A pre-existing user config that happens to be named "manual" is
    refused, never adopted and rewritten.
  * Capital accounting is per asset class (each class has its own pool)
    and margin-aware (an FX position ties up its broker margin, not its
    levered notional).
  * Execution is serialized per pool and deduped per signal, so a
    double-click cannot open two positions.

Sizing is risk-derived by default and the default is the right answer:
qty such that a stop-out costs exactly the config's risk budget. The
operator may override it at the confirm step, in units or in cash, and
the override is re-derived and re-judged HERE — never taken on the
browser's word — against the same three rules the automatic path obeys:
the risk ceiling that keeps 1R comparable, the per-class notional cap
(4.0 for FX because the leverage lives at the broker), and the free
capital in that class's pool (FX commits margin, not levered notional).
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal

logger = logging.getLogger(__name__)

MANUAL_CONFIG_NAME = "manual"
MANUAL_RULE = "manual_take"

# Instrument.asset_class -> AssetBotConfig.asset_class. Indices are absent
# on purpose: no execution class exists for them (the tradeable proxy would
# be a CFD, which has no bot either), and pretending otherwise here would
# manufacture positions nothing can manage.
EXECUTABLE_CLASS = {
    "stock": "stock", "etf": "stock",
    "forex": "forex", "commodity": "commodity", "crypto": "crypto",
}

# Cash a position ties up, per dollar of notional. Forex is margined at the
# broker — sizing.py's 4.0 notional cap exists BECAUSE the leverage lives
# there — so charging an FX trade its full notional against the pool made
# any stop tighter than 0.25% "insufficient capital" on an empty book.
# 30:1 is the standard retail FX margin. Everything else settles in full.
CAPITAL_USE_FRACTION = {"forex": 1.0 / 30.0}


def _capital_use(asset_class: str, notional: float) -> float:
    return notional * CAPITAL_USE_FRACTION.get(asset_class, 1.0)


def manual_config_for(user, asset_class):
    """The per-user manual config for this class — created on first use.

    Deliberately does NOT mutate an existing row: enabled/symbols/mode
    drift is a refusal condition (see _config_error), not something to
    silently paper over — re-arming a config the kill switch disabled
    would reverse the one decision that must never be reversed quietly.
    """
    from bot_program.models import AssetBotConfig

    cfg, _created = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name=MANUAL_CONFIG_NAME,
        defaults={"mode": "paper", "symbols": [], "enabled": True},
    )
    return cfg


def _config_error(cfg):
    """Why this config must not take a trade right now, or None."""
    if cfg.symbols:
        # get_or_create adopted a pre-existing config the USER named
        # "manual" — destroying its symbol universe (as the first cut did)
        # is not an option, and neither is trading through it.
        return ("A bot config named 'manual' with its own symbols already "
                "exists for this class — rename that bot; TAKE TRADE "
                "reserves the name for its managed-but-never-trades config")
    if getattr(cfg, "mode", "paper") != "paper":
        return ("The manual config for this class is set to live mode — "
                "TAKE TRADE executes on the paper venue only in this wave")
    if not cfg.enabled:
        return ("The manual config for this class is disabled — the kill "
                "switch or an operator turned it off. Re-enable it in the "
                "bot fleet to take manual trades again")
    return None


def _tick_manages() -> bool:
    """Whether the 5-minute tick that enforces stops/targets is actually
    running. The popup must not promise management the platform switches
    have turned off."""
    try:
        from core.platform_control import is_component_enabled
        return (is_component_enabled("platform_master")
                and is_component_enabled("pipeline_asset_bots"))
    except Exception:  # noqa: BLE001 — a control-plane hiccup is not a blocker
        return False


def _mark_for(user, cfg, symbol):
    """Current mark through the same client the trade will execute on."""
    from bot_program.engine.broker_router import client_for_symbol

    client = client_for_symbol(user, symbol, cfg)
    try:
        tk = client.ticker(symbol) or {}
        price = float(tk.get("lastPrice", 0) or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("[take-trade] ticker(%s) failed: %s", symbol, e)
        return None, client
    return (price if price > 0 else None), client


def _trade_notional_usd(trade) -> float:
    """Entry notional in account currency, using the entry-time rate."""
    meta = trade.metadata or {}
    vpu = float(meta.get("value_per_unit", 1.0) or 1.0)
    return float(trade.entry_price) * float(trade.qty) * vpu


def _trade_capital_use(trade) -> float:
    return _capital_use(trade.asset_class, _trade_notional_usd(trade))


def _open_manual_trades(cfg):
    """Open manual trades ON THIS CONFIG only. Each class has its own
    capital pool; summing other classes' positions against it double-counts
    every dollar and proposes closing healthy positions in pools that were
    never short."""
    from bot_program.models import AssetBotTrade
    return list(AssetBotTrade.objects.filter(
        config=cfg, status="OPEN").order_by("opened_at"))


def _symbol_exposure(user, symbol):
    """Live positions this user already holds in this symbol, ANY config.

    _open_manual_trades deliberately looks at one config, because that is
    what the capital pool is. Market exposure is not: a rule's entry lands
    on the bot's own AssetBotConfig row, so the manual path could not see
    it and the confirm popup said nothing. That blind spot IS the double
    booking the operator reported — EURGBP entered once by a rule and once
    by hand, with nothing on the screen admitting the first one existed.

    Reported, never enforced: adding to a position the engine opened is a
    legitimate decision. Taking it without being told is not.
    """
    from bot_program.models import AssetBotTrade

    return [{"trade_id": t.id, "side": t.side, "qty": float(t.qty),
             "rule": t.rule_name or "", "venue": "PAPER" if t.paper else "LIVE",
             "manual": bool((t.metadata or {}).get("manual")),
             "entry": float(t.entry_price)}
            for t in AssetBotTrade.objects.filter(
                config__user=user, symbol=symbol,
                status__in=("OPEN", "CLOSE_PENDING")).order_by("opened_at")]


def _qty_step(bot, price: float) -> float:
    """The smallest size increment this venue actually keeps.

    Probed through the bot's own _round_qty rather than hardcoded, because
    the granularity is per class AND per mode: crypto keeps 8 decimals,
    paper stock 4, LIVE stock whole shares, forex 100-unit boundaries. A
    hardcoded step would offer the operator a size the venue silently
    rounds to zero.
    """
    for step in (1e-8, 1e-6, 1e-4, 1e-2, 0.1, 1.0, 10.0, 100.0, 1000.0):
        try:
            if bot._round_qty(step, price) == step:
                return step
        except Exception:  # noqa: BLE001 — a class that refuses tiny sizes
            continue
    return 1.0


def _floor_to_step(qty: float, step: float) -> float:
    """Round DOWN to the step. A ceiling that rounds up is not a ceiling."""
    if step <= 0:
        return max(qty, 0.0)
    return math.floor(max(qty, 0.0) / step + 1e-9) * step


def validate_qty_override(cfg, *, asset_class, raw, entry, stop,
                          value_per_unit, available, round_qty):
    """The operator's size, re-derived and re-judged server-side.

    Returns (qty, None) or (None, reason). Never trust the number in the
    request: the browser computed its preview from a payload it can edit,
    and the rules being checked are the ones that keep the book solvent
    and 1R comparable. Same three gates the automatic path obeys —

      risk      MAX_RISK_FRACTION is documented in sizing.py as "a hard
                cap, not a target". The default budget is 0.25%; an
                override may reach the 1.0% ceiling and not a cent past
                it, or realized_r stops being one unit across the book.
      notional  max_notional_fraction — 20% for most classes, 4.0 for FX
                because that cap presumes the broker's leverage.
      pool      the free capital in THIS class's pool, margin-aware, so
                an FX override is charged its margin and a stock override
                its full settlement.

    — and an impossible number is refused WITH the arithmetic, never
    silently clamped to something the operator did not ask for.
    """
    from bot_program.asset_engine.sizing import (MAX_RISK_FRACTION,
                                                 max_notional_fraction)

    # bool is an int in Python: JSON `true` would otherwise size to 1 unit.
    if isinstance(raw, bool):
        return None, "The size must be a number"
    try:
        qty = float(raw)
    except (TypeError, ValueError):
        return None, "The size must be a number"
    if not math.isfinite(qty) or qty <= 0:
        return None, "The size must be a positive number"

    qty = float(round_qty(qty, entry))
    if qty <= 0:
        return None, ("That size rounds to zero at this venue's minimum "
                      "increment — nothing would have been sent")

    capital = float(getattr(cfg, "capital", 0) or 0)
    per_unit_risk = abs(float(entry) - float(stop)) * float(value_per_unit)
    notional = qty * float(entry) * float(value_per_unit)
    capital_use = _capital_use(asset_class, notional)

    risk = qty * per_unit_risk
    risk_cap = capital * MAX_RISK_FRACTION
    # The 1e-9 slack is for float noise on an exactly-at-the-cap size, not
    # tolerance: a size one cent over still fails.
    if per_unit_risk > 0 and risk > risk_cap + 1e-9:
        return None, (
            f"{qty:g} units risks ${risk:,.2f} to the stop — past the "
            f"${risk_cap:,.2f} ceiling ({MAX_RISK_FRACTION * 100:.1f}% of "
            f"the ${capital:,.2f} {asset_class} pool). Size down, or raise "
            f"the pool's capital.")

    notional_cap = capital * max_notional_fraction(cfg, asset_class)
    if notional > notional_cap + 1e-9:
        return None, (
            f"{qty:g} units is ${notional:,.2f} of notional — past the "
            f"${notional_cap:,.2f} this class allows against a "
            f"${capital:,.2f} pool.")

    if capital_use > float(available) + 1e-9:
        return None, (
            f"{qty:g} units ties up ${capital_use:,.2f} of capital but only "
            f"${float(available):,.2f} is free in the {asset_class} pool.")
    return qty, None


def _funding_proposal(open_trades, deficit):
    """The least disturbance that frees the deficit, or None if even
    closing everything falls short.

    Preference order: the SMALLEST single position that covers the whole
    deficit; otherwise accumulate ascending and prune members whose
    removal keeps the freed sum sufficient — plain ascending accumulation
    liquidated every small position on the book before touching the one
    that actually covered the gap.
    """
    asc = sorted(open_trades, key=_trade_capital_use)
    if sum(_trade_capital_use(t) for t in asc) < deficit:
        return None
    covering = [t for t in asc if _trade_capital_use(t) >= deficit]
    if covering:
        chosen = [covering[0]]
    else:
        chosen, freed = [], 0.0
        for t in asc:
            chosen.append(t)
            freed += _trade_capital_use(t)
            if freed >= deficit:
                break
        for t in sorted(chosen, key=_trade_capital_use):
            if len(chosen) > 1 and freed - _trade_capital_use(t) >= deficit:
                chosen.remove(t)
                freed -= _trade_capital_use(t)
    return [{"trade_id": t.id, "symbol": t.symbol, "side": t.side,
             "qty": float(t.qty), "freed": round(_trade_capital_use(t), 2)}
            for t in chosen]


def _preview(user, inst, side, signal=None) -> dict:
    """Everything the confirm popup needs, or {"error": ...}.

    The funding proposal ("close these to free enough") considers ONLY
    open manual trades in this class — closing a bot's position from a
    popup would fight the bot that manages it, and closing another
    class's position would raid a pool this trade does not draw from.
    """
    from bot_program.asset_engine.base import make_bot
    from bot_program.asset_engine.risk_levels import stop_and_target
    from bot_program.asset_engine.sizing import size_position

    cls = EXECUTABLE_CLASS.get(inst.asset_class)
    if cls is None:
        return {"error": f"{inst.asset_class} instruments have no execution "
                         f"path — nothing could manage the position"}

    cfg = manual_config_for(user, cls)
    err = _config_error(cfg)
    if err:
        return {"error": err}
    bot = make_bot(cfg)

    price, _client = _mark_for(user, cfg, inst.symbol)
    if price is None:
        return {"error": f"No usable price mark for {inst.symbol} — the "
                         f"quote feeds have nothing fresh"}

    # The signal's own levels when it has them; the engine's ATR levels
    # otherwise, so an unlevelled signal degrades instead of blocking.
    stop = target = None
    if signal is not None:
        stop = float(signal.suggested_stop or 0) or None
        target = float(signal.suggested_target or 0) or None
    if stop is None or target is None:
        eng_stop, eng_target, _meta = stop_and_target(
            cfg, inst.symbol, price, side)
        stop = stop or eng_stop
        target = target or eng_target

    # Levels must bracket the CURRENT mark. A signal whose stop or target
    # the price has already crossed is stale — taking it would open a
    # position that the very next tick closes at a guaranteed loss.
    wrong_side = ((side == "BUY" and not (stop < price < target)) or
                  (side == "SELL" and not (target < price < stop)))
    if wrong_side:
        return {"error": f"The levels sit on the wrong side of the current "
                         f"price (mark {price:g}, stop {stop:g}, target "
                         f"{target:g}) — this move has likely already "
                         f"played out"}

    vpu = float(bot._value_per_unit(inst.symbol))
    sizing = size_position(cfg, asset_class=cls, entry=price, stop=stop,
                           direction=side, value_per_unit=vpu)
    qty = bot._round_qty(sizing["qty"], price)
    if qty <= 0:
        return {"error": "Sized to zero — the risk budget does not cover "
                         "one tradeable unit at this stop distance"}

    capital = float(cfg.capital)
    notional = round(sizing["notional_fraction"] * capital, 2)
    capital_use = round(_capital_use(cls, notional), 2)
    open_trades = _open_manual_trades(cfg)
    committed = round(sum(_trade_capital_use(t) for t in open_trades), 2)
    available = round(capital - committed, 2)
    deficit = round(capital_use - available, 2)

    proposal = []
    if deficit > 0:
        if not open_trades:
            return {"error": f"This trade ties up ${capital_use:,.2f} of "
                             f"capital but only ${available:,.2f} is free — "
                             f"and there are no open manual {cls} positions "
                             f"to close"}
        proposal = _funding_proposal(open_trades, deficit)
        if proposal is None:
            freeable = round(sum(_trade_capital_use(t)
                                 for t in open_trades), 2)
            return {"error": f"Closing every open manual {cls} position "
                             f"would free ${freeable:,.2f} against the "
                             f"${deficit:,.2f} short"}

    # ── What an override is allowed to be ───────────────────────────────
    # Per-unit costs so the confirm step can show the consequence of a size
    # LIVE, without a round trip per keystroke, and in the same arithmetic
    # validate_qty_override will re-run on execute. The browser is given
    # the rules; it is never given the verdict.
    from bot_program.asset_engine.sizing import (MAX_RISK_FRACTION,
                                                 max_notional_fraction)
    stop_used = float(sizing["stop"])
    risk_per_unit = abs(price - stop_used) * vpu
    notional_per_unit = price * vpu
    capital_use_per_unit = _capital_use(cls, notional_per_unit)
    step = _qty_step(bot, price)
    # The pool line moves with the funding closes: what an override may use
    # is what is free AFTER whatever the operator agrees to close.
    freed = sum(c["freed"] for c in proposal) if proposal else 0.0
    pool_free = round(available + freed, 2)

    caps = []
    if risk_per_unit > 0:
        caps.append(capital * MAX_RISK_FRACTION / risk_per_unit)
    if notional_per_unit > 0:
        caps.append(capital * max_notional_fraction(cfg, cls)
                    / notional_per_unit)
    if capital_use_per_unit > 0:
        caps.append(pool_free / capital_use_per_unit)
    max_qty = _floor_to_step(min(caps), step) if caps else 0.0

    return {
        "symbol": inst.symbol, "side": side, "qty": qty,
        "entry": round(price, 8),
        "stop": round(stop_used, 8),
        "target": round(float(target), 8),
        "stop_widened": bool(sizing["stop_widened"]),
        "risk_dollars": sizing["risk_dollars"],
        "notional": notional,
        "capital_use": capital_use,
        "capital": capital, "committed": committed, "available": available,
        "sufficient": capital_use <= available,
        "close_proposal": proposal,
        "managed": _tick_manages(),
        "venue": "paper",
        # Sizing bounds — the override control's whole vocabulary.
        "asset_class": cls,
        "value_per_unit": vpu,
        "qty_step": step,
        "risk_per_unit": risk_per_unit,
        "notional_per_unit": notional_per_unit,
        "capital_use_per_unit": capital_use_per_unit,
        "pool_free": pool_free,
        "max_qty": max_qty,
        "max_risk_dollars": round(capital * MAX_RISK_FRACTION, 2),
        "max_notional": round(capital * max_notional_fraction(cfg, cls), 2),
        # Live exposure in this symbol, from ANY of this user's configs —
        # the fact whose absence let one symbol be booked twice.
        "existing_exposure": _symbol_exposure(user, inst.symbol),
    }


def preview_take_trade(user, signal) -> dict:
    """Preview for a signal's TAKE TRADE button."""
    if signal.direction not in ("bullish", "bearish"):
        # A neutral signal has no trade direction; "not bullish, so SELL"
        # was how the first cut turned FLAT verdicts into full-risk shorts.
        return {"error": f"'{signal.direction}' signals carry no trade "
                         f"direction — only bullish and bearish signals "
                         f"are executable"}
    side = "BUY" if signal.direction == "bullish" else "SELL"
    return _preview(user, signal.instrument, side, signal=signal)


def preview_asset_trade(user, inst, side) -> dict:
    """Preview for a signal-less LONG/SHORT from an instrument popup —
    levels come from the engine's ATR machinery."""
    if side not in ("BUY", "SELL"):
        return {"error": f"Unknown side {side!r}"}
    return _preview(user, inst, side)


def _execute(user, inst, side, close_ids=None, signal=None,
             qty_override=None) -> dict:
    """Close the funding positions (if any), then open the trade. Paper is
    synchronous, so the whole chain settles before this returns.

    `qty_override` is the operator's size from the confirm step. None means
    "use the risk budget", which is the path that existed before it and is
    reproduced here untouched, down to the metadata it writes.

    The structure is transactional hygiene, learned the hard way:
      * Funding closes run OUTSIDE the open-side transaction. _close_trade
        sends Telegram/Eye messages the moment it closes — wrapping it in
        a transaction that later rolls back would announce closes that
        never happened, and would hold the DB write lock across external
        HTTP. Each close commits on its own, exactly like a bot-tick close.
      * The open runs inside ONE transaction with the config row locked
        (serialized on Postgres; SQLite falls back to its single-writer
        lock), so two clicks racing each other cannot both read
        "sufficient" before either row exists. The per-signal dedupe
        closes the same door sequentially.
      * The open's external side effects (notification, Eye push) fire
        AFTER the commit — never announce a row that can still roll back.
        The audit entry and tax lot are DB rows and stay inside: they must
        live and die with the trade row.
    """
    from django.db import transaction
    from bot_program.asset_engine.base import make_bot
    from bot_program.asset_engine.risk_levels import paper_fill_price
    from bot_program.models import AssetBotConfig, AssetBotTrade

    cls = EXECUTABLE_CLASS.get(inst.asset_class)
    if cls is None:
        return {"error": f"{inst.asset_class} instruments have no execution "
                         f"path — nothing could manage the position"}

    cfg = manual_config_for(user, cls)

    def _dup():
        if signal is None:
            return None
        return AssetBotTrade.objects.filter(
            config=cfg, status="OPEN",
            metadata__signal_id=signal.id).first()

    # Cheap guards BEFORE anything is liquidated; all re-checked under the
    # lock below.
    err = _config_error(cfg)
    if err:
        return {"error": err}
    dup = _dup()
    if dup is not None:
        return {"error": f"This signal is already taken — position "
                         f"#{dup.id} ({dup.side} {dup.symbol}) is open"}

    closed = []
    if close_ids:
        # Nothing may be closed for a trade that was never going to preview
        # clean — full preview first, closes second.
        preview = _preview(user, inst, side, signal=signal)
        if preview.get("error"):
            return preview
        for trade in AssetBotTrade.objects.filter(
                id__in=list(close_ids), config=cfg, status="OPEN"):
            t_bot = make_bot(trade.config)
            price, client = _mark_for(user, trade.config, trade.symbol)
            if price is None:
                return {"error": f"Cannot close {trade.symbol} — no "
                                 f"price mark; nothing was opened",
                        "closed": closed}
            if t_bot._close_trade(trade, Decimal(str(price)), client,
                                  reason="FUNDING · take-trade"):
                closed.append(trade.symbol)
            else:
                return {"error": f"Closing {trade.symbol} failed — "
                                 f"nothing was opened", "closed": closed}

    with transaction.atomic():
        cfg = AssetBotConfig.objects.select_for_update().get(pk=cfg.pk)
        err = _config_error(cfg)
        if err:
            return {"error": err, "closed": closed}
        dup = _dup()
        if dup is not None:
            return {"error": f"This signal is already taken — position "
                             f"#{dup.id} ({dup.side} {dup.symbol}) is open",
                    "closed": closed}

        # Fresh preview under the lock — it sees the post-close book, and
        # no competing execute can insert between this read and the create.
        preview = _preview(user, inst, side, signal=signal)
        if preview.get("error"):
            # The closes already happened — the caller must see them even
            # though the open did not follow.
            preview.setdefault("closed", closed)
            return preview

        # Only the AUTOMATIC size is gated on the preview's own sufficiency
        # flag, which is computed for that size. An override is judged
        # against the pool on its own terms below — a smaller one legitimately
        # fits where the risk-derived size did not, and refusing it here
        # would tell the operator to close positions to make room for a
        # trade that already fits.
        if qty_override is None and not preview["sufficient"]:
            return {"error": "Insufficient capital — the funding closes did "
                             "not cover the required amount",
                    "closed": closed}

        bot = make_bot(cfg)
        stop = preview["stop"]
        # Fill FIRST, size from the fill — the bot entry path's ordering.
        # Sizing off the free raw mark and then filling adversely overshoots
        # the risk budget by half the round-trip cost every time.
        fill = paper_fill_price(cfg, inst.symbol, preview["entry"], side)
        # No `or 1.0` fallback here: ForexBot returns 0.0 as its deliberate
        # no-fresh-rate sentinel ("size to zero rather than to a wrong
        # number"), and flattening it to 1.0 would size at the wrong rate
        # AND write value_per_unit=1.0 into metadata, mis-converting every
        # later P&L, grading and capital calculation. vpu 0 → dist 0 → the
        # refusal below, exactly matching the preview path's behaviour.
        vpu = float(bot._value_per_unit(inst.symbol))
        dist = abs(fill - stop) * vpu
        overridden = qty_override is not None
        if not overridden:
            qty = bot._round_qty(preview["risk_dollars"] / dist, fill) \
                if dist > 0 else 0
            if qty <= 0:
                return {"error": "Sized to zero at the adjusted fill price",
                        "closed": closed}
        elif dist <= 0:
            # Same sentinel as above: no usable rate, so no size is legal —
            # including one the operator typed.
            return {"error": "Sized to zero at the adjusted fill price",
                    "closed": closed}
        else:
            # Re-derived against the ACTUAL fill and the post-close pool,
            # not against whatever the preview the browser saw contained.
            qty, why = validate_qty_override(
                cfg, asset_class=cls, raw=qty_override, entry=fill, stop=stop,
                value_per_unit=vpu, available=preview["available"],
                round_qty=bot._round_qty)
            if why:
                return {"error": why, "closed": closed}
            logger.info("[take-trade] %s sized %s %s by hand: %s units "
                        "(automatic size was %s)", user.username, side,
                        inst.symbol, qty,
                        bot._round_qty(preview["risk_dollars"] / dist, fill))

        # An operator-sized trade carries the R it actually carries — qty x
        # the stop distance — not the config's risk budget. Writing the
        # budget would denominate this trade's realized_r against money that
        # was never at risk, which is the one thing sizing.py exists to
        # prevent. The automatic branch keeps the preview's own numbers
        # verbatim, so an un-overridden trade is byte-for-byte what it was
        # before this option existed.
        if overridden:
            notional = qty * fill * vpu
            capital = float(preview["capital"])
            risk_dollars = round(qty * dist, 6)
            notional_fraction = round(notional / capital, 6) if capital else 0.0
            capital_use = round(_capital_use(cls, notional), 2)
        else:
            risk_dollars = preview["risk_dollars"]
            notional_fraction = (preview["notional"] / preview["capital"]
                                 if preview["capital"] else 0.0)
            capital_use = preview["capital_use"]

        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class=cfg.asset_class, symbol=inst.symbol,
            side=side, qty=Decimal(str(qty)),
            entry_price=Decimal(str(round(fill, 8))),
            stop_loss=Decimal(str(stop)),
            take_profit=Decimal(str(preview["target"])),
            status="OPEN", paper=True, rule_name=MANUAL_RULE,
            composite_score=float(getattr(signal, "score", 0) or 0),
            reason=(f"TAKE TRADE · signal #{signal.id} · "
                    f"{signal.rule_name or ''}" if signal is not None
                    else f"TAKE TRADE · manual {side} from instrument view"),
            metadata={
                "manual": True,
                "signal_id": signal.id if signal is not None else None,
                "initial_stop_loss": stop,
                "value_per_unit": vpu,
                "risk_dollars": risk_dollars,
                "notional_fraction": notional_fraction,
                "capital_use": capital_use,
                "paper_fill": True, "market_price": preview["entry"],
                "funding_closes": closed,
                # Which size this was, so the ledger can tell an operator's
                # judgement apart from the engine's arithmetic later.
                "size_source": "operator" if overridden else "risk_budget",
            },
        )

        # DB-side bookkeeping lives inside the transaction — the audit
        # entry and the tax lot must exist exactly when the trade row does.
        # Without them the audit log gets closes with no opens and the
        # tax-lot ledger consumes OTHER trades' lots when this one closes.
        try:
            from bot_program.audit import record_trade_open
            record_trade_open(user, trade=trade)
        except Exception as e:  # noqa: BLE001
            logger.warning("[take-trade] audit record_trade_open failed: %s", e)
        try:
            from bot_program.tax_lots import open_lot
            open_lot(trade)
        except Exception as e:  # noqa: BLE001
            logger.warning("[take-trade] tax_lots.open_lot failed: %s", e)

        # Star the instrument: the star is what keeps quotes and bars
        # flowing for off-fleet symbols. Without it a stock/ETF manual
        # position on an unstarred symbol loses its mark within hours and
        # becomes permanently unmanageable — unclosable even by the
        # funding path.
        try:
            if not inst.is_watchlist:
                inst.is_watchlist = True
                inst.save(update_fields=["is_watchlist"])
        except Exception as e:  # noqa: BLE001
            logger.warning("[take-trade] watchlist star failed: %s", e)

    # External side effects AFTER the commit — the row is durable now.
    try:
        from bot_program.notifications import notify_bot_fill_open
        notify_bot_fill_open(
            user, asset_class=cfg.asset_class, symbol=inst.symbol,
            side=side, qty=trade.qty, entry_price=trade.entry_price,
            rule_name=trade.rule_name, trade_id=trade.id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[take-trade] open notification failed: %s", e)
    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(user, "fill_open", {
            "trade_id": trade.id, "asset_class": cfg.asset_class,
            "symbol": inst.symbol, "side": side,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[take-trade] WS push (open) failed: %s", e)

    logger.info("[take-trade] %s opened %s %s x%s%s (closed first: %s)",
                user.username, side, inst.symbol, qty,
                f" from signal {signal.id}" if signal is not None else "",
                closed or "none")
    return {"ok": True, "trade_id": trade.id, "symbol": inst.symbol,
            "side": side, "qty": float(qty),
            "entry": float(trade.entry_price),
            "risk_dollars": risk_dollars,
            "sized_by": "operator" if overridden else "risk_budget",
            "managed": preview.get("managed", False),
            "closed": closed}


def execute_take_trade(user, signal, close_ids=None, qty=None) -> dict:
    """Execute a signal's TAKE TRADE. `qty` None keeps the risk-derived size."""
    if signal.direction not in ("bullish", "bearish"):
        return {"error": f"'{signal.direction}' signals carry no trade "
                         f"direction — only bullish and bearish signals "
                         f"are executable"}
    side = "BUY" if signal.direction == "bullish" else "SELL"
    return _execute(user, signal.instrument, side, close_ids=close_ids,
                    signal=signal, qty_override=qty)


def execute_asset_trade(user, inst, side, close_ids=None, qty=None) -> dict:
    """Execute a signal-less LONG/SHORT from an instrument popup."""
    if side not in ("BUY", "SELL"):
        return {"error": f"Unknown side {side!r}"}
    return _execute(user, inst, side, close_ids=close_ids, qty_override=qty)
