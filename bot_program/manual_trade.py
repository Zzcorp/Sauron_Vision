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
  * Execution is serialized per pool and deduped — per signal where there
    is one, and per (symbol, side) inside a short window where there is
    not — so a double-click cannot open two positions on either path.
  * The book's own limits bind here. This path used to enforce per-trade
    risk, the per-class notional cap and the pool's free capital and
    nothing else — no daily-loss stop, no exposure ceiling — so an
    operator who had set MAX DAILY LOSS 3% on /setup/ could go on
    clicking TAKE TRADE all the way down. `portfolio.risk_gate.preflight`
    now runs before the preview and again under the lock, and the
    single-position ceiling is judged on the size actually sent. The
    under-lock run is asked as of the instant before any funding close,
    so a close executed to fund a trade can never be the reason that
    trade is then refused.

Sizing is risk-derived by default and the default is the right answer:
qty such that a stop-out costs exactly the config's risk budget. The
operator may override it at the confirm step, in units or in cash, and
the override is re-derived and re-judged HERE — never taken on the
browser's word — against the same three rules the automatic path obeys:
the risk ceiling that keeps 1R comparable, the per-class notional cap
(4.0 for FX because the leverage lives at the broker), and the free
capital in that class's pool (FX commits margin, not levered notional).

The same posture now covers the rest of the ticket, because sizing was
never the only thing the confirm step was deciding on the operator's
behalf:

  levels    The stop and the target are adjustable. A moved stop moves the
            SIZE with it — risk sizing is what the stop is for — so the
            derived quantity faces the same three gates a typed one does,
            and both levels are re-judged against the fill: the band
            risk_levels sanctions, and the cost filter every bot entry
            already passes, because dragging a target in or a stop out can
            turn a paying setup into one that pays only the spread.

  funding   WHICH positions are liquidated to free capital is now the
            operator's choice rather than the proposal's. close_ids was
            always a list on the wire, but the popup filled it in
            automatically from close_proposal, so pressing the button
            liquidated whatever the server had picked. It is a selection
            now: the preview ships every open position in the pool with
            the proposal pre-picked, and the pool is re-read after the
            closes, under the lock, so a selection that frees too little
            is refused with the shortfall instead of opening a position
            the pool cannot carry.

  leverage  Deliberately NOT a control. Nothing in this platform's
            execution path multiplies a position: FX ties up broker margin
            (CAPITAL_USE_FRACTION) and every other class settles in full,
            and no per-trade number changes either. An input wired to
            nothing would be worse than no input, so the preview ships
            leverage as a FACT — what it is, whose it is, and how much
            notional this pool can carry — and size stays the only lever
            that exists.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

MANUAL_CONFIG_NAME = "manual"
MANUAL_RULE = "manual_take"

# How long an identical manual open is treated as the SAME intent.
#
# The signal path has always been deduped on metadata["signal_id"], so a
# double-click there could only ever produce one position. The signal-LESS
# path — the instrument view's BUY/SELL, which has no signal id to dedupe on
# — had no such guard, and it showed: one operator produced four XAUUSD BUY
# tickets inside eight seconds at identical qty and identical entry, ~42% of
# the book in one trade wearing four tickets, and every risk reading
# downstream then counted four independent bets.
#
# A WINDOW rather than a ban, because scaling into a position is a real
# thing an operator does deliberately. Sixty seconds is long enough to cover
# a double-click, an impatient re-click on a slow confirm, and a browser
# retry; it is far too short to be in anybody's way when the second entry is
# meant. The refusal names the position that already exists and says when
# the window ends, so the deliberate case is a wait, not a mystery.
MANUAL_REPEAT_WINDOW_SECONDS = 60

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


def _leverage(asset_class: str) -> float:
    """Dollars of exposure one dollar of pool capital carries in this class.

    A derived fact, not a setting: it is CAPITAL_USE_FRACTION read the
    other way up. 30x on FX because the broker margins it, 1x everywhere
    else because the position settles in full — and no code path anywhere
    in the platform multiplies a manual order by anything. That is why the
    confirm popup states the leverage instead of offering it: a control
    the execution path ignores would have the operator sizing against a
    number the order never sees, which is a worse failure than the missing
    control it was meant to fix.
    """
    frac = CAPITAL_USE_FRACTION.get(asset_class, 1.0)
    return (1.0 / frac) if frac > 0 else 1.0


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


def _concentration_guard(user, inst, side, cls, cfg, close_ids):
    """The concentration refusal, or None. Costs one preview and no orders.

    Subtracts the tickets the operator chose to liquidate, because those are
    exactly the exposure that will be gone by the time this trade opens, and
    refusing on a number that is about to change would block a trade whose
    whole purpose is to replace what is being closed.
    """
    from bot_program.models import AssetBotTrade
    from portfolio.risk_gate import capital_at_work, concentration_state
    from portfolio.services import value_per_unit

    probe = _preview(user, inst, side, signal=None)
    notional = probe.get("notional")
    if probe.get("error") or not notional:
        # Nothing to judge yet — the ordinary preview below will report
        # whatever is actually wrong, with a better message than this could.
        return None

    # This guard exists to refuse BEFORE an irreversible liquidation. With
    # nothing to liquidate there is nothing to protect, so it steps aside and
    # lets the ordinary path answer — which knows the operator's requested
    # size and whether the pool can fund it at all, and says so in terms of
    # the money that is actually missing. "You cannot afford this" is a more
    # useful sentence than "this would concentrate your book", and it is the
    # one that should arrive first when both are true.
    if not close_ids and not probe.get("sufficient", True):
        return None

    state = concentration_state(
        user, symbol=inst.symbol, side=side, asset_class=cls,
        notional=float(notional), capital_base=float(cfg.capital or 0),
        base_label="manual pool")
    if state["ok"]:
        return None

    # Credit back what is about to be closed, on this symbol and side only.
    freed = 0.0
    for trade in AssetBotTrade.objects.filter(
            id__in=list(close_ids or []), config=cfg, status="OPEN",
            symbol__iexact=inst.symbol):
        if (str(trade.side or "").upper() in ("BUY", "LONG")) !=                 (str(side or "").upper() in ("BUY", "LONG")):
            continue
        freed += capital_at_work(
            trade.asset_class,
            float(trade.entry_price or 0) * float(trade.qty or 0)
            * value_per_unit(trade))
    if freed and state["cap_money"] is not None             and (state["after"] - freed) <= state["cap_money"] + 1e-9:
        return None
    return state["reason"]



def _risk_appetite(cfg) -> dict:
    """What fraction of the pool one stop-out costs, and how that reads.

    `flagged` past AGGRESSIVE_RISK_FRACTION, with the losing-streak
    arithmetic attached — the number that matters is not the per-trade
    percentage, which always sounds small, but what a normal bad run does
    to the book.
    """
    from bot_program.asset_engine.sizing import (AGGRESSIVE_RISK_FRACTION,
                                                 MAX_RISK_FRACTION,
                                                 max_notional_fraction,
                                                 min_stop_fraction,
                                                 risk_fraction)
    f = risk_fraction(cfg)
    ten = 1.0 - (1.0 - f) ** 10
    cls = getattr(cfg, "asset_class", "") or ""
    # The two knobs are COUPLED and the coupling is not obvious: sizing
    # solves notional = equity * f / stop_fraction, so holding notional
    # under the cap forces a stop no tighter than f / cap. Raise the risk
    # budget alone and the platform does not risk more — it WIDENS the
    # stop, silently turning the setup the signal proposed into a
    # different trade. Said out loud here, with the number.
    cap = max_notional_fraction(cfg, cls)
    floor = min_stop_fraction(cfg, cls, f)
    return {
        "fraction": round(f, 6),
        "pct": round(f * 100, 3),
        "cap_pct": round(MAX_RISK_FRACTION * 100, 1),
        "at_cap": f >= MAX_RISK_FRACTION - 1e-9,
        "flagged": f > AGGRESSIVE_RISK_FRACTION,
        "ten_loss_drawdown_pct": round(ten * 100, 1),
        "notional_cap_pct": round(cap * 100, 1),
        "min_stop_pct": round(floor * 100, 2),
        "reason": (f"{f * 100:.2f}% of the pool per trade — ten losses in a "
                   f"row, an ordinary run, would cost "
                   f"{ten * 100:.0f}% of it"),
        # Only when the coupling is about to change the operator's trade.
        # Shown when the coupling would actually change the operator's
        # trade — that is, when the forced floor is wider than the band this
        # asset class is judged by. The old test was a flat `floor > 0.03`,
        # three percent, which on forex is the entire CEILING: a 0.5% forced
        # floor on EURUSD silently widens a 20-pip stop to 54 pips and said
        # nothing, because 0.5% is under 3%. The comparison has to be
        # against the class, not against a number borrowed from equities.
        "stop_floor_note": (
            f"a {f * 100:.2f}% risk budget against a "
            f"{cap * 100:.0f}% notional cap forces any stop wider than "
            f"{floor * 100:.3f}% — tighter stops get WIDENED to it. Raise "
            f"extras['max_notional_fraction'] to keep your own stops."
            if floor > _floor_note_threshold(cls) else ""),
    }

def _floor_note_threshold(asset_class: str) -> float:
    """Above this forced floor, the operator has to be told.

    Twice the class's own sane-stop minimum: at that point the coupling is
    no longer a rounding detail, it is placing a stop the operator did not
    choose and would notice.
    """
    try:
        from bot_program.asset_engine.risk_levels import stop_band
        return stop_band(asset_class)[0] * 2.0
    except Exception:  # noqa: BLE001
        return 0.03


def _manual_rule_advisory() -> dict:
    """What the brain currently thinks of hand-taken entries.

    `brain_rule_advisory` is consulted on the BOT path and was never asked
    here, so the platform could conclude that `manual_take` is the only
    negative-expectancy rule on the board, raise `pause_recommended`, and
    the discretionary path would go on firing without ever mentioning it.

    Never raises and never blocks: a control-plane hiccup must not stop a
    trade, and an advisory is advice.
    """
    try:
        from brain.context import brain_rule_advisory
        status, why = brain_rule_advisory(MANUAL_RULE)
    except Exception as e:  # noqa: BLE001 — advice is not a precondition
        logger.debug("[take-trade] rule advisory unavailable: %s", e)
        return {"status": "unknown", "reason": "", "flagged": False}
    return {"status": status, "reason": why,
            "flagged": status == "pause_recommended"}


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


def _correlation_note(user, inst) -> dict:
    """What the book's correlation limit says about this candidate.

    A note on the ticket, not a gate. `scale` is what an AUTOMATED entry in
    this instrument would be sized to right now, so the operator can see the
    machine's own reading of "you already own most of this bet" before
    deciding to take it at full size anyway. `measured` False means nothing
    could be correlated — an empty book, or not enough daily history — and a
    1.0 scale then means unmeasured, never cleared.

    Never fatal: a correlation read is a diagnostic and a missing one must not
    cost the operator a trade. It degrades to unmeasured with the reason in
    place of the number.
    """
    try:
        from portfolio.risk_gate import correlation_state
        state = correlation_state(user, inst)
    except Exception as e:  # noqa: BLE001 — a note, not a gate
        logger.warning("[take-trade] correlation read failed for %s: %s",
                       getattr(inst, "symbol", "?"), e)
        return {"scale": 1.0, "max_corr": None, "peer": None,
                "threshold": None, "measured": False,
                "reason": f"correlation could not be measured ({e})"}
    return state


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


def judge_qty(cfg, *, asset_class, qty, entry, stop, value_per_unit,
              available):
    """Why this size may not be sent, or None.

    The three gates that keep the book solvent and 1R comparable —

      risk      MAX_RISK_FRACTION is documented in sizing.py as "a hard
                cap, not a target". The default budget is 0.25%; an
                override may reach the 1.0% ceiling and not a cent past
                it, or realized_r stops being one unit across the book.
      notional  max_notional_fraction — 20% for most classes, 4.0 for FX
                because that cap presumes the broker's leverage.
      pool      the free capital in THIS class's pool, margin-aware, so
                an FX override is charged its margin and a stock override
                its full settlement.

    — refusing WITH the arithmetic, never silently clamping to something
    the operator did not ask for.

    Lifted out of validate_qty_override so the LEVEL override can reach
    them too. A tightened stop buys more units per dollar of risk, so an
    operator who moves the stop and leaves the size on automatic gets a
    bigger position than the one the preview was judged for — the caps
    have to bite on the size that is actually sent, not on the one that
    was typed.
    """
    from bot_program.asset_engine.sizing import (MAX_RISK_FRACTION,
                                                 max_notional_fraction)

    capital = float(getattr(cfg, "capital", 0) or 0)
    per_unit_risk = abs(float(entry) - float(stop)) * float(value_per_unit)
    notional = qty * float(entry) * float(value_per_unit)
    capital_use = _capital_use(asset_class, notional)

    risk = qty * per_unit_risk
    risk_cap = capital * MAX_RISK_FRACTION
    # The 1e-9 slack is for float noise on an exactly-at-the-cap size, not
    # tolerance: a size one cent over still fails.
    if per_unit_risk > 0 and risk > risk_cap + 1e-9:
        return (
            f"{qty:g} units risks ${risk:,.2f} to the stop — past the "
            f"${risk_cap:,.2f} ceiling ({MAX_RISK_FRACTION * 100:.1f}% of "
            f"the ${capital:,.2f} {asset_class} pool). Size down, or raise "
            f"the pool's capital.")

    notional_cap = capital * max_notional_fraction(cfg, asset_class)
    if notional > notional_cap + 1e-9:
        return (
            f"{qty:g} units is ${notional:,.2f} of notional — past the "
            f"${notional_cap:,.2f} this class allows against a "
            f"${capital:,.2f} pool.")

    if capital_use > float(available) + 1e-9:
        return (
            f"{qty:g} units ties up ${capital_use:,.2f} of capital but only "
            f"${float(available):,.2f} is free in the {asset_class} pool.")
    return None


def validate_qty_override(cfg, *, asset_class, raw, entry, stop,
                          value_per_unit, available, round_qty):
    """The operator's size, re-derived and re-judged server-side.

    Returns (qty, None) or (None, reason). Never trust the number in the
    request: the browser computed its preview from a payload it can edit,
    so this settles the SHAPE (a positive, finite, venue-representable
    number) and hands the money question to judge_qty, which the automatic
    path's re-derived sizes go through too.
    """
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

    why = judge_qty(cfg, asset_class=asset_class, qty=qty, entry=entry,
                    stop=stop, value_per_unit=value_per_unit,
                    available=available)
    return (None, why) if why else (qty, None)


def validate_stop_override(cfg, *, asset_class, raw, entry, side):
    """The operator's stop, re-judged server-side. (stop, None) | (None, why).

    Two gates, both the platform's own rather than invented here:

      side   The stop has to sit on the losing side of the fill. A BUY
             stopped ABOVE its entry is not a tight stop, it is a position
             the very next tick closes at a guaranteed loss — the same
             refusal _preview already makes for a stale signal's levels.
      band   The window risk_levels sanctions for an ATR stop ON THIS
             ASSET CLASS. Outside it a level is a fat finger or a bad
             feed, not a regime: 0.05% on a stock is inside the spread,
             and 60% is not a stop at all. Per class because the equity
             band refused ordinary forex stops — a 20-pip stop on EURUSD
             is 0.18%, under the 0.2% floor, and it is the most normal
             stop in that market.

    Notably NOT applied: sizing.apply_stop_floor, which widens a stop that
    is too tight for the notional cap. Widening is right when the machine
    picked the level and only the risk budget matters; silently moving a
    stop the OPERATOR typed would place a level they did not choose. The
    consequence lands on the size instead, where judge_qty refuses it with
    the arithmetic and the operator can decide which of the two to give.
    """
    from bot_program.asset_engine.risk_levels import stop_band

    lo, hi = stop_band(asset_class)

    if isinstance(raw, bool):
        return None, "The stop must be a number"
    try:
        stop = float(raw)
    except (TypeError, ValueError):
        return None, "The stop must be a number"
    if not math.isfinite(stop) or stop <= 0:
        return None, "The stop must be a positive number"

    entry = float(entry)
    if entry <= 0:
        return None, "No usable entry price to place a stop against"
    if side == "BUY" and stop >= entry:
        return None, (f"A BUY stop must sit BELOW the entry — {stop:g} is at "
                      f"or above {entry:g}, so the position would open "
                      f"already stopped out")
    if side == "SELL" and stop <= entry:
        return None, (f"A SELL stop must sit ABOVE the entry — {stop:g} is at "
                      f"or below {entry:g}, so the position would open "
                      f"already stopped out")

    fraction = abs(entry - stop) / entry
    if fraction < lo:
        return None, (
            f"A {fraction * 100:.3f}% stop is inside the "
            f"{lo * 100:.3f}% floor this platform trades on "
            f"{asset_class or 'this class'} — that distance is spread and "
            f"noise, not a level.")
    if fraction > hi:
        return None, (
            f"A {fraction * 100:.1f}% stop is past the "
            f"{hi * 100:.1f}% ceiling this platform trades on "
            f"{asset_class or 'this class'} — at that distance the level is "
            f"not doing any work.")
    return stop, None


def validate_target_override(*, raw, entry, side):
    """The operator's target, re-judged server-side. (target, None) | (None, why).

    Side only: a target on the losing side of the entry is a take-profit
    that books a loss the moment the tick reaches it. How FAR is a
    judgement — an operator scalping half the ATR is making a real choice —
    so the distance is left to the cost filter in validate_levels, which is
    the gate that knows what the round trip costs.
    """
    if isinstance(raw, bool):
        return None, "The target must be a number"
    try:
        target = float(raw)
    except (TypeError, ValueError):
        return None, "The target must be a number"
    if not math.isfinite(target) or target <= 0:
        return None, "The target must be a positive number"

    entry = float(entry)
    if entry <= 0:
        return None, "No usable entry price to place a target against"
    if side == "BUY" and target <= entry:
        return None, (f"A BUY target must sit ABOVE the entry — {target:g} is "
                      f"at or below {entry:g}, so hitting it would book a "
                      f"loss")
    if side == "SELL" and target >= entry:
        return None, (f"A SELL target must sit BELOW the entry — {target:g} "
                      f"is at or above {entry:g}, so hitting it would book a "
                      f"loss")
    return target, None


def validate_levels(cfg, symbol, *, entry, stop, target):
    """Why the operator's levels may not be traded, or None.

    passes_cost_filter — the gate every bot entry goes through — asked of
    a hand-placed pair. It catches the two ways a moved level quietly
    stops being worth taking: a target dragged in until the planned move
    no longer clears the round trip, and a stop pushed out until 1R is
    wider than the reward net of costs. Both leave a ticket that pays the
    spread and nothing else.

    Applied ONLY when a level was actually moved. The untouched defaults
    come from machinery that already respects this band, and re-judging
    them here could refuse a trade the button takes today — which would
    change the default, the one thing this control must not do.
    """
    from bot_program.asset_engine.risk_levels import passes_cost_filter

    ok, why = passes_cost_filter(cfg, symbol, float(entry), float(target),
                                 stop=float(stop))
    if ok:
        return None
    return f"Those levels do not clear their own costs — {why}"


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


def _preview(user, inst, side, signal=None, *, gate_now=None) -> dict:
    """Everything the confirm popup needs, or {"error": ...}.

    The funding proposal ("close these to free enough") considers ONLY
    open manual trades in this class — closing a bot's position from a
    popup would fight the bot that manages it, and closing another
    class's position would raid a pool this trade does not draw from.

    `gate_now` is the instant the book-level limits are judged AS OF, and
    the live clock when nothing passes one. `_execute` passes the moment
    before its funding closes ran, for the reason set out there.
    """
    from bot_program.asset_engine.base import make_bot
    from bot_program.asset_engine.risk_levels import (
        DEFAULT_MIN_EDGE_RATIO, DEFAULT_MIN_NET_RR, paper_fill_price,
        round_trip_cost_fraction, stop_and_target, stop_band)
    from bot_program.asset_engine.sizing import size_position

    cls = EXECUTABLE_CLASS.get(inst.asset_class)
    if cls is None:
        return {"error": f"{inst.asset_class} instruments have no execution "
                         f"path — nothing could manage the position"}

    cfg = manual_config_for(user, cls)
    err = _config_error(cfg)
    if err:
        return {"error": err}

    # The book's own limits from /setup/ — MAX DAILY LOSS and MAX TOTAL
    # EXPOSURE — before anything is priced or sized. The manual path enforced
    # per-trade risk, the per-class notional cap and the pool's free capital
    # and nothing else, so an operator who had set a 3% daily-loss limit could
    # keep clicking TAKE TRADE all the way down. Checked here so the popup
    # says why, and again under the lock in `_execute` so the answer cannot go
    # stale between the two.
    from portfolio.risk_gate import (limits_book, preflight,
                                     single_position_state)
    risk_book = limits_book()
    book = preflight(user, portfolio=risk_book, now=gate_now)
    # NOT a refusal on this path. The two book-level limits — daily loss and
    # total exposure — are statements of RISK APPETITE, and on a hand-taken
    # trade there is a human on the other end who is entitled to change
    # their mind about their own appetite with the facts in front of them.
    # The bots keep them as hard refusals, because nobody is there to make
    # that call on a beat.
    #
    # It is reported, not hidden: it rides the preview into the confirm
    # dialog as a warning the operator has to read past, and it is recorded
    # on the trade so a later review can see the limit was live and
    # overridden. What stays a refusal on this path is everything that is
    # not appetite — no usable price, levels on the wrong side, not enough
    # free capital in the pool to fund the position at all.
    book_advisory = {
        "ok": bool(book["ok"]),
        "reason": "" if book["ok"] else book["reason"],
        "failed_open": bool(book.get("failed_open")),
        "checks": book.get("checks", {}),
    }

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
    levels_note = ""
    if stop is None or target is None:
        eng_stop, eng_target, _meta = stop_and_target(
            cfg, inst.symbol, price, side)
        stop = stop or eng_stop
        target = target or eng_target
        # A percentage stop and an ATR stop look identical on the ticket —
        # two numbers — and they are not the same promise. One is this
        # instrument's own volatility; the other is a default that was never
        # asked whether it suits this instrument. The operator is about to
        # risk money on the difference, so the ticket says which it is.
        if _meta.get("levels_source") == "pct":
            why = _meta.get("levels_fallback_reason")
            levels_note = (
                f"These levels are the configured "
                f"{float(getattr(cfg, 'stop_loss_pct', 0) or 0):.2f}% / "
                f"{float(getattr(cfg, 'take_profit_pct', 0) or 0):.2f}% "
                f"percentages, not this instrument's own volatility"
                + (f" — its ATR stop fell outside the sane band for {cls}"
                   if why == "atr_out_of_band" else " — no ATR was available")
                + ". Check the stop before sending.")

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

    # MAX SINGLE POSITION from /setup/ — a percentage of the BOOK, where the
    # pool caps are percentages of this CLASS's pool. Two different ceilings
    # and the trade has to clear both.
    #
    # Deliberately NOT an error here, even when the proposed size is over it.
    # The preview IS the popup: erroring closes the one screen on which the
    # operator could size down to something that fits, so a book ceiling would
    # have made a takeable trade untakeable. It becomes a bound on the size
    # control instead (see `caps` below) and a hard refusal in `_execute`,
    # which is where the size actually being sent is known.
    # `capital` here is the manual config's pool, the same number the
    # sizing above divided by — not the portfolio book, which nothing on
    # this path consults.
    single = single_position_state(risk_book, asset_class=cls,
                                   notional=notional,
                                   capital_base=float(capital or 0),
                                   base_label="manual pool")
    # The concentration ceiling, reported here and enforced in `_execute`.
    # The preview must never raise the operator's own screen out from under
    # them — it bounds the size control and explains itself instead.
    from portfolio.risk_gate import concentration_state
    concentration = concentration_state(
        user, symbol=inst.symbol, side=side, asset_class=cls,
        notional=notional, capital_base=float(capital or 0),
        base_label="manual pool")

    # A DUPLICATE EXPRESSION is refused even on this path, where the money
    # limits only warn — because it is not appetite. Appetite is how much
    # of their own book an operator puts behind a decision; this is a
    # SECOND AUTHOR already holding the same bet under a rule the popup
    # does not show them managing. The operator who wants this entry
    # anyway has a real move available — close the other leg — and the
    # refusal names it. Tickets from this manual config itself are exempt:
    # adding to your own expression is sizing, and the ceilings above
    # already govern it.
    from portfolio.risk_gate import duplicate_state, theme_state
    dup = duplicate_state(user, symbol=inst.symbol, side=side,
                          config_id=cfg.id)
    if not dup["ok"]:
        return {"error": dup["reason"]}
    # The currency-theme crowd, as information on this path: stacking a
    # fourth deliberate EUR leg is a call a present human is entitled to
    # make, and the bots take it as a hard cap because nobody is there to
    # make it. Rides the popup next to book_advisory; recorded at entry.
    theme = theme_state(user, symbol=inst.symbol, side=side,
                        asset_class=cls)

    open_trades = _open_manual_trades(cfg)
    # Committed counts CLOSE_PENDING too — a close that has not filled is
    # still capital at the broker, exactly as every gate and the capital
    # card measure it; this sum used to read OPEN only, so the pool looked
    # richer than it was for as long as a close was stuck retrying. The
    # CLOSABLE list below stays OPEN-only: a pending close cannot be
    # closed again to free capital.
    from bot_program.models import AssetBotTrade as _ABT
    committed = round(sum(
        _trade_capital_use(t) for t in _ABT.objects.filter(
            config=cfg, status__in=("OPEN", "CLOSE_PENDING"))), 2)
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
    # The book's own single-position ceiling, converted into units, so the
    # size control stops where `_execute` will refuse rather than one refusal
    # later. Absent when the book has no usable value to take a percentage of.
    if capital_use_per_unit > 0 and single["cap_money"] is not None:
        caps.append(single["cap_money"] / capital_use_per_unit)
    max_qty = _floor_to_step(min(caps), step) if caps else 0.0

    # ── What the funding choice is allowed to be ────────────────────────
    # EVERY open position in this pool, with the proposal's picks flagged —
    # not just the picks. The popup used to receive only close_proposal and
    # send all of it back, so "close first" was a fact the operator was
    # shown rather than a decision they made. Keeping a position, or
    # closing a different one that frees as much, are both legitimate
    # answers, and neither was expressible.
    proposed_ids = {c["trade_id"] for c in proposal}
    closable = [{"trade_id": t.id, "symbol": t.symbol, "side": t.side,
                 "qty": float(t.qty), "entry": float(t.entry_price),
                 "freed": round(_trade_capital_use(t), 2),
                 "rule": t.rule_name or "",
                 "proposed": t.id in proposed_ids}
                for t in open_trades]

    # ── What the LEVEL controls are allowed to be ───────────────────────
    # The same shape as the sizing bounds above and for the same reason:
    # the browser gets the rules so it can show the consequence of a level
    # per keystroke, and the server keeps the verdict. cost_fraction and
    # min_net_rr are what passes_cost_filter will judge the moved levels
    # against, and `fill` is the price it will judge them AT — the preview
    # showed the free mark, but the position opens at the adverse fill and
    # a reward:risk quoted off the mark is a reward:risk nobody gets.
    extras = getattr(cfg, "extras", None) or {}

    def _extra_num(key, default):
        try:
            return float(extras.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    band_lo, band_hi = stop_band(cls)
    levels = {
        "fill": round(paper_fill_price(cfg, inst.symbol, price, side), 8),
        # The band THIS class is judged by. Publishing the equity numbers to
        # a forex ticket told the operator their perfectly ordinary 20-pip
        # stop was below the floor, which it no longer is.
        "min_stop_fraction": band_lo,
        "max_stop_fraction": band_hi,
        # The band, spelled for a human. The browser printed its own
        # `(minF * 100).toFixed(1)`, which renders the forex floor of
        # 0.0003 as "0.0%" — a refusal quoting a limit of zero.
        "min_stop_pct_text": f"{band_lo * 100:.3f}",
        "max_stop_pct_text": f"{band_hi * 100:.1f}",
        "asset_class": cls,
        # Empty unless these levels are percentages wearing an ATR's clothes.
        "levels_note": levels_note,
        "cost_fraction": round_trip_cost_fraction(cfg, inst.symbol),
        "cost_filter": bool(extras.get("use_cost_filter", True)),
        "min_edge_ratio": _extra_num("min_edge_ratio", DEFAULT_MIN_EDGE_RATIO),
        "min_net_rr": _extra_num("min_net_rr", DEFAULT_MIN_NET_RR),
    }

    # ── What the leverage control is NOT ────────────────────────────────
    # Stated, never offered. See _leverage: no execution path multiplies a
    # manual order, so the honest control here is the truth about where the
    # leverage lives plus the notional this pool can carry.
    lev = _leverage(cls)
    max_notional = round(capital * max_notional_fraction(cfg, cls), 2)
    leverage = {
        "effective": round(lev, 4),
        "adjustable": False,
        "margin_fraction": CAPITAL_USE_FRACTION.get(cls, 1.0),
        "max_notional": max_notional,
        "note": (
            f"{lev:.0f}:1 — the leverage is the broker's, not this "
            f"platform's: {cls} ties up margin and nothing here multiplies "
            f"it per trade. Size is the lever; this pool carries up to "
            f"${max_notional:,.0f} of notional."
            if lev > 1.0 else
            f"No leverage on {cls} — a position settles in full, so its "
            f"cash cost IS its notional. Size is the only lever; this pool "
            f"carries up to ${max_notional:,.0f} of notional."),
    }

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
        "deficit": max(deficit, 0.0),
        "close_proposal": proposal,
        # The proposal is a recommendation now; this is the menu it was
        # chosen from, so the operator can decline one, keep one, or close
        # something else entirely.
        "closable": closable,
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
        "max_notional": max_notional,
        # The book's ceilings, so the popup can name the one that is binding
        # instead of the operator meeting it for the first time as a refusal.
        "book_single_position": single,
        "book_limits": book["checks"],
        # Level bounds and the leverage truth — the rest of the pre-trade
        # control panel's vocabulary.
        "levels": levels,
        "leverage": leverage,
        # Live exposure in this symbol, from ANY of this user's configs —
        # the fact whose absence let one symbol be booked twice.
        "existing_exposure": _symbol_exposure(user, inst.symbol),
        # What this ticket would make of the whole bet, and the ceiling it
        # is measured against. Enforced in `_execute`; shown here so the
        # refusal is never a surprise at the moment of pressing the button.
        "concentration": concentration,
        # The currency-theme crowd this ticket joins. A warning here and a
        # record at entry, never a manual refusal — see the note above.
        "theme": theme,
        # The brain's standing verdict on discretionary entries. Reported,
        # not enforced: pausing a RULE is the platform's call because nobody
        # is watching it, but a hand-taken trade has a human on the other
        # end and taking the decision away from them is the one thing this
        # path exists not to do. What they must not be is uninformed.
        "rule_advisory": _manual_rule_advisory(),
        # How hard this pool is set to swing, and whether that is unusual.
        # The ceiling is 5% because a small book needs room for a win to
        # clear its own costs; a number typed into extras months ago must
        # not go on sizing at 5% without saying so.
        "risk_appetite": _risk_appetite(cfg),
        # The book's own limits, as information rather than as a veto. The
        # dialog renders this as a warning the operator reads past; the
        # execute path records it on the trade.
        "book_advisory": book_advisory,
        # How much of this bet the book already holds under other names.
        # Reported, never applied — the same posture as existing_exposure
        # above and for the same reason: adding correlated exposure on
        # purpose is a legitimate decision, and the bots take the taper
        # because nobody is there to make it. Quietly shrinking a size the
        # operator is looking at would be the browser and the server
        # disagreeing about what was ordered.
        "correlation": _correlation_note(user, inst),
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
             qty_override=None, stop_override=None,
             target_override=None) -> dict:
    """Close the funding positions (if any), then open the trade. Paper is
    synchronous, so the whole chain settles before this returns.

    The three overrides are the operator's answers from the confirm step,
    and None means "the platform's answer" for each independently. All
    three None is the path that existed before any of them and is
    reproduced here untouched, down to the metadata it writes.

    `close_ids` is the operator's SELECTION of funding closes, not an
    acknowledgement of the proposal. Whatever is not in it stays open, and
    the sufficiency check below runs against the pool that selection
    actually leaves — so declining a close costs the trade, never the
    position.

    The structure is transactional hygiene, learned the hard way:
      * Funding closes run OUTSIDE the open-side transaction. _close_trade
        sends Telegram/Eye messages the moment it closes — wrapping it in
        a transaction that later rolls back would announce closes that
        never happened, and would hold the DB write lock across external
        HTTP. Each close commits on its own, exactly like a bot-tick close.
      * Because those closes are irreversible AND realise P&L, the book's
        daily-loss gate is asked as of the instant before they ran. A gate
        that measured them would be able to refuse the trade they were
        executed to fund — see the note at the capture below.
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
        """The open position this request would duplicate, or None.

        Two different questions, because the two entry paths have two
        different notions of "the same trade":
          * From a signal — the same SIGNAL, for as long as the position is
            open. One idea, one position, no expiry.
          * Without one — the same symbol and side inside
            MANUAL_REPEAT_WINDOW_SECONDS. There is no id to key on, so
            recency is the only evidence available that a second identical
            request is a second click rather than a second decision.
        """
        if signal is not None:
            return AssetBotTrade.objects.filter(
                config=cfg, status="OPEN",
                metadata__signal_id=signal.id).first()
        from django.utils import timezone as _tz
        since = _tz.now() - timedelta(seconds=MANUAL_REPEAT_WINDOW_SECONDS)
        return (AssetBotTrade.objects
                .filter(config=cfg, status="OPEN", symbol=inst.symbol,
                        side=side, opened_at__gte=since)
                .order_by("-opened_at").first())

    def _dup_error(dup):
        if signal is not None:
            return (f"This signal is already taken — position "
                    f"#{dup.id} ({dup.side} {dup.symbol}) is open")
        from django.utils import timezone as _tz
        age = max(0, int((_tz.now() - dup.opened_at).total_seconds()))
        wait = max(1, MANUAL_REPEAT_WINDOW_SECONDS - age)
        return (f"You opened {dup.side} {dup.symbol} {age}s ago "
                f"(position #{dup.id}, {dup.qty} units). A second identical "
                f"order this quickly is treated as a double-click. To add to "
                f"the position deliberately, try again in {wait}s.")

    # Cheap guards BEFORE anything is liquidated; all re-checked under the
    # lock below.
    err = _config_error(cfg)
    if err:
        return {"error": err}
    dup = _dup()
    if dup is not None:
        return {"error": _dup_error(dup)}

    # CONCENTRATION — before anything is liquidated, and measured on the book
    # as it will stand AFTER the closes the operator picked.
    #
    # The per-ticket ceiling judges this ticket; this judges the BET. Five
    # clips each comfortably inside the per-ticket limit summed to 42% of the
    # book on one instrument, because nothing added them up — the operator was
    # refused nothing, a clip at a time, until one name carried nearly half
    # the book and a single adverse print hit it five times at once.
    #
    # It runs HERE rather than under the lock for the same reason the
    # daily-loss gate takes a frozen clock: the funding closes are
    # irreversible, and a gate that refuses after them costs the operator the
    # position AND the trade for one click. The closes are deterministic —
    # the operator named them — so their exposure can be subtracted now
    # instead of discovered later.
    # REPORTED, not refused — the same posture the book-level limits now
    # take on this path. A symbol-and-side ceiling is a statement about how
    # much of one idea the operator wants to own, and owning more of an idea
    # on purpose is a decision a human is allowed to make. The bots keep it
    # as a hard refusal, because a beat has nobody to make it.
    #
    # It is still computed BEFORE any liquidation, which was the point of
    # putting it here: the operator sees the number while the book is still
    # the book they were looking at, not after a funding close has moved it.
    _conc_guard = _concentration_guard(user, inst, side, cls, cfg, close_ids)

    closed = []
    # The instant the book-level limits are judged as of. None while this
    # request has done nothing irreversible, and the live clock is then the
    # right reading; set at the capture below, where that stops being true.
    gate_now = None
    if close_ids:
        # Nothing may be closed for a trade that was never going to preview
        # clean — full preview first, closes second.
        preview = _preview(user, inst, side, signal=signal)
        if preview.get("error"):
            return preview

        # Frozen BEFORE the first liquidation, and handed to the gate that
        # runs after them.
        #
        # The funding closes REALISE P&L, and realised P&L over the trailing
        # 24h is the exact quantity MAX DAILY LOSS measures. So a losing
        # funding close could push the book past the floor, and the preflight
        # under the lock — the same gate that let this request through a
        # moment ago — would then refuse the trade those closes were executed
        # to fund. One click, and the operator loses the position AND does not
        # get the trade.
        #
        # The closes cannot simply move to after the gate: they are what frees
        # the capital the gate is asked about, and they have to commit outside
        # the open's transaction (see the docstring). So the gate measures the
        # day as it stood the instant before this operation touched anything,
        # which is the only reading under which these closes cannot refuse the
        # trade they are paying for. Nothing is hidden: the next click reads
        # the new reality, closes included.
        from django.utils import timezone as _tz
        gate_now = _tz.now()

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
            return {"error": _dup_error(dup), "closed": closed}

        # Fresh preview under the lock — it sees the post-close book, and
        # no competing execute can insert between this read and the create.
        # The one thing it deliberately does NOT see is this request's own
        # funding closes in the daily-loss window: `gate_now` is the instant
        # before they ran.
        preview = _preview(user, inst, side, signal=signal, gate_now=gate_now)
        if preview.get("error"):
            # The closes already happened — the caller must see them even
            # though the open did not follow.
            preview.setdefault("closed", closed)
            return preview

        # Only the wholly AUTOMATIC ticket is gated on the preview's own
        # sufficiency flag, which is computed for the preview's own size at
        # the preview's own stop. Anything the operator moved is judged
        # against the pool on its own terms below — a smaller size, or a
        # wider stop, legitimately fits where the risk-derived default did
        # not, and refusing here would tell the operator to close positions
        # to make room for a trade that already fits.
        #
        # The message carries the shortfall now because the closes are a
        # SELECTION: "the funding closes did not cover it" reads as a
        # platform failure when what actually happened is that the operator
        # kept a position open, which is a decision they are entitled to
        # make and entitled to see the price of.
        if (qty_override is None and stop_override is None
                and not preview["sufficient"]):
            short = round(preview["capital_use"] - preview["available"], 2)
            return {"error": (f"This trade ties up "
                              f"${preview['capital_use']:,.2f} but only "
                              f"${preview['available']:,.2f} is free in the "
                              f"{cls} pool — ${short:,.2f} short. Close more "
                              f"of the book, or size down."),
                    "closed": closed}

        bot = make_bot(cfg)
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

        # ── The operator's levels, re-derived against the real fill ──────
        # Against the FILL, not the mark the browser was shown: the fill is
        # where the position opens, so it is the price the stop's side, the
        # stop's distance and the reward:risk have to be true of. A stop
        # that clears the mark by a tick and not the fill is a stop that was
        # never really below the entry.
        stop = preview["stop"]
        target = float(preview["target"])
        level_overrides = []
        if stop_override is not None:
            stop, why = validate_stop_override(
                cfg, asset_class=cls, raw=stop_override, entry=fill, side=side)
            if why:
                return {"error": why, "closed": closed}
            level_overrides.append("stop")
        if target_override is not None:
            target, why = validate_target_override(
                raw=target_override, entry=fill, side=side)
            if why:
                return {"error": why, "closed": closed}
            level_overrides.append("target")
        if level_overrides:
            why = validate_levels(cfg, inst.symbol, entry=fill, stop=stop,
                                  target=target)
            if why:
                return {"error": why, "closed": closed}

        dist = abs(fill - stop) * vpu
        overridden = qty_override is not None
        if not overridden:
            qty = bot._round_qty(preview["risk_dollars"] / dist, fill) \
                if dist > 0 else 0
            if qty <= 0:
                return {"error": "Sized to zero at the adjusted fill price",
                        "closed": closed}
            if stop_override is not None:
                # A hand-placed stop re-denominates the risk budget, so the
                # size it derives is not the size the preview was judged
                # for — a stop half as wide buys twice the position. The
                # caps have to bite on what is actually sent.
                why = judge_qty(cfg, asset_class=cls, qty=qty, entry=fill,
                                stop=stop, value_per_unit=vpu,
                                available=preview["available"])
                if why:
                    return {"error": why, "closed": closed}
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
        # prevent. A hand-placed STOP resizes the position for the same
        # reason, so the money figures are re-derived there too; the
        # preview's own numbers are for its own stop and its own size.
        # With nothing overridden every one of them is the preview's
        # verbatim, so an untouched trade is byte-for-byte what it was
        # before any of this existed.
        resized = overridden or stop_override is not None
        if resized:
            notional = qty * fill * vpu
            capital = float(preview["capital"])
            risk_dollars = round(qty * dist, 6)
            notional_fraction = round(notional / capital, 6) if capital else 0.0
            capital_use = round(_capital_use(cls, notional), 2)
        else:
            notional = float(preview["notional"])
            risk_dollars = preview["risk_dollars"]
            notional_fraction = (preview["notional"] / preview["capital"]
                                 if preview["capital"] else 0.0)
            capital_use = preview["capital_use"]

        # MAX SINGLE POSITION from /setup/, on the notional actually being
        # sent — after any override and at the real fill, because a ceiling
        # that judges the number the browser was shown is a ceiling on a trade
        # nobody placed. The preview only bounded the control; this is the
        # refusal, and it carries the arithmetic so the operator can see
        # whether to size down or to raise the book's limit.
        from portfolio.risk_gate import limits_book, single_position_state
        single = single_position_state(limits_book(), asset_class=cls,
                                       notional=notional,
                                       capital_base=float(cfg.capital or 0),
                                       base_label="manual pool")
        if not single["ok"]:
            return {"error": single["reason"], "closed": closed}

        # The duplicate refusal, re-asked at the moment of the order — a
        # bot may have opened this exact bet between the preview and the
        # click, and a stale answer here is how one idea gets booked
        # twice. Funding closes need no credit: they liquidate this
        # config's own tickets, and this config's tickets were never
        # duplication.
        from portfolio.risk_gate import duplicate_state, theme_state
        dup = duplicate_state(user, symbol=inst.symbol, side=side,
                              config_id=cfg.id)
        if not dup["ok"]:
            return {"error": dup["reason"], "closed": closed}
        theme_now = theme_state(user, symbol=inst.symbol, side=side,
                                asset_class=cls)


        meta = {
            "manual": True,
            "signal_id": signal.id if signal is not None else None,
            # The stop the position OPENS with, whoever chose it — R is
            # denominated by this number for the life of the trade, so it
            # has to be the level actually placed and not the level the
            # engine would have placed.
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
            # Whether the brain was recommending against discretionary
            # entries when this one was taken. Grading later has to be able
            # to ask whether the advisory was worth following, and it cannot
            # ask a question nobody recorded the answer to.
            "advisory_at_entry": _manual_rule_advisory(),
            # And whether a BOOK limit was breached at the moment this was
            # taken. It no longer refuses a hand-taken entry, so the only
            # record that the operator traded through their own daily-loss
            # or exposure ceiling is the one written here. A limit that is
            # overridden without a trace is indistinguishable afterwards
            # from a limit that was never reached.
            "book_limit_at_entry": (preview.get("book_advisory")
                                    or {"ok": True, "reason": ""}),
            # And whether this ticket took the symbol past its
            # concentration ceiling. Same reason: an override nobody
            # recorded cannot be reviewed afterwards.
            "concentration_at_entry": {"ok": _conc_guard is None,
                                       "reason": _conc_guard or ""},
            # And the currency-theme crowd at the moment of entry — the
            # cap the bots take as a refusal and a present human may
            # override. Same rule as its siblings: an override nobody
            # recorded cannot be reviewed afterwards.
            "theme_at_entry": {"ok": bool(theme_now["ok"]),
                               "reason": theme_now["reason"]},
        }
        if level_overrides:
            # Only when something moved: an untouched ticket keeps the exact
            # metadata shape it had before the levels became adjustable, so
            # nothing downstream has to learn a new key to read an ordinary
            # trade. Grading later wants to know whether a level was the
            # engine's or a person's — that is a different question from
            # who chose the size.
            meta["level_source"] = "operator"
            meta["operator_overrides"] = level_overrides
            meta["engine_stop"] = preview["stop"]
            meta["engine_target"] = float(preview["target"])

        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class=cfg.asset_class, symbol=inst.symbol,
            side=side, qty=Decimal(str(qty)),
            entry_price=Decimal(str(round(fill, 8))),
            stop_loss=Decimal(str(stop)),
            take_profit=Decimal(str(round(target, 8))),
            status="OPEN", paper=True, rule_name=MANUAL_RULE,
            composite_score=float(getattr(signal, "score", 0) or 0),
            reason=(f"TAKE TRADE · signal #{signal.id} · "
                    f"{signal.rule_name or ''}" if signal is not None
                    else f"TAKE TRADE · manual {side} from instrument view"),
            metadata=meta,
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
        # The operator's own fill, announced as the operator's own. The bot
        # helper types its row "Bot Event" and hides it behind the bot-alert
        # preference, so a deliberate TAKE TRADE arrived in the bell as
        # automation — and went silent entirely for anyone who had muted the
        # fleet's chatter, which is the one fill they cannot afford to miss.
        from bot_program.notifications import notify_manual_fill_open
        notify_manual_fill_open(
            user, asset_class=cfg.asset_class, symbol=inst.symbol,
            side=side, qty=trade.qty, entry_price=trade.entry_price,
            trade_id=trade.id)
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

    logger.info("[take-trade] %s opened %s %s x%s%s (closed first: %s%s)",
                user.username, side, inst.symbol, qty,
                f" from signal {signal.id}" if signal is not None else "",
                closed or "none",
                f"; operator levels: {', '.join(level_overrides)}"
                if level_overrides else "")
    return {"ok": True, "trade_id": trade.id, "symbol": inst.symbol,
            "side": side, "qty": float(qty),
            "entry": float(trade.entry_price),
            "stop": float(trade.stop_loss),
            "target": float(trade.take_profit),
            "risk_dollars": risk_dollars,
            "sized_by": "operator" if overridden else "risk_budget",
            # What the operator moved, so the confirmation can name it back
            # to them rather than claiming the platform's own defaults.
            "overrides": (["qty"] if overridden else []) + level_overrides,
            "managed": preview.get("managed", False),
            "closed": closed}


def execute_take_trade(user, signal, close_ids=None, qty=None, stop=None,
                       target=None) -> dict:
    """Execute a signal's TAKE TRADE.

    Every keyword None is "the platform's answer": the risk-derived size,
    the signal's own stop and target. Each is independent — a hand-placed
    stop with an automatic size is the ordinary case, not an exotic one.
    """
    if signal.direction not in ("bullish", "bearish"):
        return {"error": f"'{signal.direction}' signals carry no trade "
                         f"direction — only bullish and bearish signals "
                         f"are executable"}
    side = "BUY" if signal.direction == "bullish" else "SELL"
    return _execute(user, signal.instrument, side, close_ids=close_ids,
                    signal=signal, qty_override=qty, stop_override=stop,
                    target_override=target)


def execute_asset_trade(user, inst, side, close_ids=None, qty=None, stop=None,
                        target=None) -> dict:
    """Execute a signal-less LONG/SHORT from an instrument popup."""
    if side not in ("BUY", "SELL"):
        return {"error": f"Unknown side {side!r}"}
    return _execute(user, inst, side, close_ids=close_ids, qty_override=qty,
                    stop_override=stop, target_override=target)
