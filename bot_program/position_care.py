"""THE POSITION CARE (2026-10-02): what happens to a position after entry.

The operator: "the maintenance on those held assets still seems poor to my
taste, I dont want to lose". It was: every eToro row is protected by the
stop and target sent with the order, so the engine skipped it every tick;
break-even and trailing were off by default; the only exit of the
platform's own was a 14-30 day clock. A winner could ride to +2R and come
back to a full -1R stop, untouched.

Each tick, for every open row the bot manages (paper too, so the paper
evidence Aragorn promotes on is earned under the same exits), with
Aragorn switch ON:

  THE TRACK   the best and worst price since entry, in R (MFE / MAE),
              kept on metadata["care"].
  SOFT STOP   a stop the PLATFORM holds, tighten-only, beside the venue's
              own stop (which stays where it was sent, the disaster stop):
                break-even   MFE >= BREAKEVEN_AT_R: entry + BREAKEVEN_LOCK_R
                trail        MFE >= TRAIL_AT_R: lock MFE - TRAIL_GAP_R
                             (TRAIL_GAP_WIDE_R past TRAIL_WIDE_FROM_R)
                posture      a REAL-MONEY risk-on long (or a haven short) in
                             a stressed market: no worse than -0.75R; in a
                             crisis -0.5R (bot_program/posture.py)
                weekend      Friday from WEEKEND_FROM_UTC, a market that
                             shuts: a winner of WEEKEND_LOCK_AT_R or more
                             locks break-even
              The mark crossing it closes the position at market
              (reason SL, metadata["care_exit"] says which).
  WEEKEND CUT a real-money loser carrying WEEKEND_CUT_LEVERAGE or more,
              Friday evening in a market that shuts: closed rather than
              carried through a gap.
  NO PROGRESS open NO_PROGRESS_HOURS[class] or more, never reached +1R and
              under NO_PROGRESS_MAX_R now: closed (reason TIME, graded
              time_stop) — capital back from a thesis that did nothing.

The operator's MANUAL positions (the TAKE TRADE lane) get the profit
protections only — break-even, trail, the weekend lock — never a cut by a
rule (posture floor, weekend cut, no progress).

BEYOND THE CROWD (2026-10-02, with the smart_money switch ON as well): a
break-even or a trail that would sit in the hunt zone of a swing, the
latest pullback's extreme or a round number is placed beyond it
(bot_program/smart_money.stop_beyond_the_crowd), never closer to the
entry than its round-trip cost. The posture floors are risk limits and
the weekend lock guards a gap (no hunt): neither moves. Not on the
manual lane, nor on options (a premium has no crowd levels). The soft
stop stays tighten-only: a tick without the read keeps the tighter lock,
the safe side.

Every close is a AragornAction. Never raises: care that fails leaves the
row to the rest of manage_positions, exactly as before.
"""
import logging
from datetime import time as dtime
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

logger = logging.getLogger(__name__)

BREAKEVEN_AT_R = 1.0
BREAKEVEN_LOCK_R = 0.1
TRAIL_AT_R = 1.5
TRAIL_GAP_R = 1.0
TRAIL_WIDE_FROM_R = 3.0
TRAIL_GAP_WIDE_R = 0.75
STRESSED_FLOOR_R = -0.75
CRISIS_FLOOR_R = -0.5
#: Friday, New York time (DST follows): the window before each market
#: shuts for the weekend, by class
NY = ZoneInfo("America/New_York")
WEEKEND_WINDOW_NY = {"stock": (dtime(15, 0), dtime(16, 0)),
                     "etf": (dtime(15, 0), dtime(16, 0)),
                     "options": (dtime(15, 0), dtime(16, 0))}
WEEKEND_WINDOW_NY_DEFAULT = (dtime(15, 30), dtime(17, 0))
WEEKEND_LOCK_AT_R = 0.5
WEEKEND_CUT_LEVERAGE = 5
NO_PROGRESS_HOURS = {"forex": 96, "index": 96, "commodity": 120,
                     "stock": 120, "etf": 120, "crypto": 72}
NO_PROGRESS_DEFAULT_HOURS = 120
NO_PROGRESS_MAX_R = 0.3
NEVER_SHUTS = frozenset({"crypto"})


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def is_weekend_window(now, asset_class) -> bool:
    """Friday, the hour before this class's market shuts (New York time,
    so daylight saving follows)."""
    if str(asset_class) in NEVER_SHUTS:
        return False
    ny = now.astimezone(NY)
    start, end = WEEKEND_WINDOW_NY.get(str(asset_class),
                                       WEEKEND_WINDOW_NY_DEFAULT)
    return ny.weekday() == 4 and start <= ny.time() < end


def market_hours(start, now, asset_class) -> float:
    """Hours between start and now, less the Saturdays and Sundays (New
    York) of a market that shuts: a thesis is not "doing nothing" while
    its market is closed."""
    if start is None or now <= start:
        return 0.0
    total = (now - start).total_seconds() / 3600.0
    if str(asset_class) in NEVER_SHUTS:
        return total
    day = start.astimezone(NY).date()
    last = now.astimezone(NY).date()
    shut = 0
    while day <= last and shut < 400:
        if day.weekday() >= 5:
            shut += 1
        day += timedelta(days=1)
    return max(0.0, total - 24.0 * shut)


def plan(trade, price, *, now=None, posture_level="calm", kind="neutral",
         live=False, manual=False, crowd=None) -> dict:
    """The care decision for one row at one mark — pure, no I/O:
    {action: "hold"|"close", reason: "SL"|"TIME"|"", why, care: {...},
     changed: bool}. `crowd` = {"atr", "levels"} (smart_money.care_levels)
    places the profit locks beyond the crowd's levels."""
    now = now or timezone.now()
    meta = dict(trade.metadata or {})
    care = dict(meta.get("care") or {})
    entry = _f(trade.entry_price)
    init = _f(meta.get("initial_stop_loss")) or _f(trade.stop_loss)
    p = _f(price)
    out = {"action": "hold", "reason": "", "why": "", "care": care,
           "changed": False}
    if not entry or not init or not p or entry <= 0 or p <= 0:
        return out
    risk = abs(entry - init)
    if risk <= 0:
        return out
    d = 1.0 if str(trade.side).upper() == "BUY" else -1.0
    peak = _f(care.get("peak")) or entry
    worst = _f(care.get("worst")) or entry
    new_peak = max(peak, p) if d > 0 else min(peak, p)
    new_worst = min(worst, p) if d > 0 else max(worst, p)
    r_now = d * (p - entry) / risk
    mfe = d * (new_peak - entry) / risk
    mae = d * (new_worst - entry) / risk

    def lvl(r):
        return entry + d * r * risk

    cands = []
    if mfe >= BREAKEVEN_AT_R:
        cands.append((lvl(BREAKEVEN_LOCK_R), "breakeven"))
    if mfe >= TRAIL_AT_R:
        gap = TRAIL_GAP_WIDE_R if mfe >= TRAIL_WIDE_FROM_R else TRAIL_GAP_R
        cands.append((lvl(mfe - gap), "trail"))
    fights = kind in ("risk_on_long", "haven_short") and not manual
    if live and fights and posture_level == "stressed":
        cands.append((lvl(STRESSED_FLOOR_R), "stressed market"))
    if live and fights and posture_level == "crisis":
        cands.append((lvl(CRISIS_FLOOR_R), "crisis"))
    weekend = is_weekend_window(now, trade.asset_class)
    if weekend and r_now >= WEEKEND_LOCK_AT_R:
        # a winner NOW locks break-even; a past peak never closes a loser
        cands.append((lvl(BREAKEVEN_LOCK_R), "weekend lock"))

    if crowd and not manual and any(w in CROWD_MOVABLE for _l, w in cands):
        # the read is paid for only when a lock could move
        crowd = crowd() if callable(crowd) else crowd
        cost = _f(meta.get("cost_fraction_charged"))
        if cost is None:
            cost = float((crowd or {}).get("cost") or 0.0)
        if crowd:
            cands = [_beyond_the_crowd(level, why, d, p, entry, crowd,
                                       cost=cost)
                     for level, why in cands]

    soft = _f(care.get("soft_stop"))
    soft_why = care.get("soft_why", "")
    for level, why in cands:
        tighter = soft is None or (level > soft if d > 0 else level < soft)
        if tighter:
            soft, soft_why = level, why
    new_care = {"peak": round(new_peak, 8), "worst": round(new_worst, 8),
                "mfe_r": round(mfe, 3), "mae_r": round(mae, 3),
                "r_now": round(r_now, 3),
                # the first tick care saw this row: its MFE is only known
                # from here, and the no-progress clock starts here
                "since": care.get("since") or now.isoformat()}
    if soft is not None:
        new_care["soft_stop"] = round(soft, 8)
        new_care["soft_why"] = soft_why
    out["changed"] = any(care.get(k) != new_care.get(k)
                         for k in ("peak", "worst", "soft_stop", "soft_why",
                                   "since"))
    out["care"] = {**care, **new_care}

    if soft is not None and ((d > 0 and p <= soft) or (d < 0 and p >= soft)):
        out.update(action="close", reason="SL",
                   why=f"{soft_why} soft stop {soft:g} crossed at {p:g} "
                       f"({r_now:+.2f}R, best {mfe:+.2f}R)")
        out["care"]["exit"] = soft_why
        return out
    if manual:
        # THE OPERATOR'S OWN POSITION: profits are protected (break-even,
        # trail, the weekend lock above); nothing cuts it on a rule.
        return out
    lev = int(_f(meta.get("leverage")) or 1)
    if live and weekend and r_now < 0 and lev >= WEEKEND_CUT_LEVERAGE:
        out.update(action="close", reason="SL",
                   why=f"Friday evening, a {lev}x loser ({r_now:+.2f}R) is not "
                       f"carried through the weekend gap")
        out["care"]["exit"] = "weekend cut"
        return out
    from django.utils.dateparse import parse_datetime
    care_since = parse_datetime(new_care["since"]) if new_care.get("since") \
        else None
    start = max([t for t in (trade.opened_at, care_since) if t is not None],
                default=None)
    hours = market_hours(start, now, trade.asset_class)
    limit = NO_PROGRESS_HOURS.get(str(trade.asset_class),
                                  NO_PROGRESS_DEFAULT_HOURS)
    if hours >= limit and mfe < BREAKEVEN_AT_R and r_now < NO_PROGRESS_MAX_R:
        out.update(action="close", reason="TIME",
                   why=f"no progress: {hours:.0f} market hours watched, best "
                       f"{mfe:+.2f}R, now {r_now:+.2f}R")
        out["care"]["exit"] = "no progress"
        return out
    return out


#: the profit locks smart money may move; the posture floors (risk limits)
#: and the weekend lock (a gap, not a hunt) never move
CROWD_MOVABLE = frozenset({"breakeven", "trail"})


def _beyond_the_crowd(level, why, d, price, entry, crowd, *, cost=0.0):
    """(level, why) with a profit lock moved out of the crowd's hunt zone
    (smart_money.lock_beyond_the_crowd: never closer to the entry than its
    round-trip `cost`). The posture floors and the weekend lock pass."""
    if why not in CROWD_MOVABLE:
        return level, why
    from bot_program.smart_money import lock_beyond_the_crowd
    moved_to, moved = lock_beyond_the_crowd(
        "BUY" if d > 0 else "SELL", price, entry, level, crowd, cost=cost)
    return (moved_to, f"{why} (beyond the crowd)") if moved else (level, why)


def _save_care(trade, care_value, care_exit=None):
    """Merge ONLY care's keys into the row's metadata, read fresh under a
    row lock: other writers (adjust_levels, a manual close's in-doubt
    marker) are never clobbered by this tick's stale copy."""
    from django.db import transaction

    from bot_program.asset_models import AssetBotTrade
    with transaction.atomic():
        row = AssetBotTrade.objects.select_for_update().get(pk=trade.pk)
        meta = dict(row.metadata or {})
        meta["care"] = care_value
        if care_exit is not None:
            meta["care_exit"] = care_exit
        row.metadata = meta
        row.save(update_fields=["metadata"])
    trade.metadata = meta


def _venue_still_holds(bot, trade, client) -> bool:
    """A protected real-money row may be closed by care only when its venue
    closes by position id (eToro: the close takes the stop and target with
    it) AND this tick's position list still shows its position — a stop or
    target eToro already filled is reconciliation's to book, at its real
    price, never care's to close again."""
    from bot_program.engine.venue_close import venue_needs_position_id
    if not venue_needs_position_id(client):
        return False
    pid = str((trade.metadata or {}).get("protective_trade_id") or "")
    if not pid:
        return False
    positions = bot._broker_snapshot(client, "positions")
    if positions is None:
        return False
    return any(str(p.get("position_id") or "") == pid for p in positions)


def care(bot, trade, price, client, *, now=None) -> str:
    """Run the care on one row inside manage_positions. "" when it left the
    row to the rest of the tick; "closed" or "attempted" when it sent a
    close — the caller then moves on either way (a close in flight must
    never meet the SL/TP check below it the same tick)."""
    from bot_program import aragorn
    if not aragorn.is_on():
        return ""
    now = now or timezone.now()
    try:
        level, kind = "calm", "neutral"
        from bot_program import market_stress, posture
        if not trade.paper and posture.crisis_mode_on():
            level = market_stress.current(now)["level"]
            icls = bot._instrument_class(trade.symbol) or trade.asset_class
            kind = posture.classify(trade.symbol, icls, trade.side)
        manual = False
        try:
            from bot_program.share_allocator import _is_manual_lane
            manual = bool(_is_manual_lane(bot.cfg))
        except Exception:  # noqa: BLE001 — unknown reads as a bot's own
            manual = False
        crowd = None
        if not manual and trade.asset_class != "options" \
                and getattr(bot, "asset_class", "") != "options":
            from bot_program import smart_money
            if smart_money.is_on():
                def crowd():
                    try:
                        levels = smart_money.care_levels(trade.symbol,
                                                         trade.side, price)
                        if levels is not None:
                            # the round trip a row opened before
                            # cost_fraction_charged existed was charged
                            from bot_program.asset_engine.risk_levels import (
                                round_trip_cost_fraction,
                            )
                            levels = dict(levels, cost=float(
                                round_trip_cost_fraction(bot.cfg,
                                                         trade.symbol)))
                        return levels
                    except Exception as e:  # noqa: BLE001 — plain care runs
                        logger.info("[care] %s #%s: crowd levels unread (%s)",
                                    trade.symbol, trade.id, e)
                        return None
        decision = plan(trade, price, now=now, posture_level=level, kind=kind,
                        live=not trade.paper, manual=manual, crowd=crowd)
    except Exception as e:  # noqa: BLE001 — care that fails changes nothing
        logger.warning("[care] %s #%s not cared for: %s", trade.symbol,
                       trade.id, e)
        return ""
    if decision["action"] == "close" and not trade.paper \
            and (trade.metadata or {}).get("protected"):
        try:
            held = _venue_still_holds(bot, trade, client)
        except Exception as e:  # noqa: BLE001
            logger.info("[care] %s #%s: holding unread (%s)", trade.symbol,
                        trade.id, e)
            held = False
        if not held:
            logger.info("[care] %s #%s: %s — not sent: the venue does not "
                        "show the position (or closes by order), "
                        "reconciliation books it", trade.symbol, trade.id,
                        decision["why"])
            decision["action"] = "hold"
    try:
        if decision["changed"] or decision["action"] == "close":
            _save_care(trade, decision["care"],
                       decision["care"].get("exit", "")
                       if decision["action"] == "close" else None)
    except Exception as e:  # noqa: BLE001
        logger.warning("[care] %s #%s: care not saved: %s", trade.symbol,
                       trade.id, e)
    if decision["action"] != "close":
        return ""
    closed = bot._close_trade(trade, price, client, reason=decision["reason"])
    try:
        from bot_program.aragorn_models import AragornAction
        AragornAction.objects.create(
            kind="care_close" if closed else "care_close_pending",
            rule_name=trade.rule_name or "", asset_class=trade.asset_class,
            symbol=trade.symbol, trade_id=trade.id,
            detail=("" if trade.paper else "REAL MONEY: ") + decision["why"],
            stats={k: decision["care"].get(k) for k in
                   ("mfe_r", "mae_r", "r_now", "soft_stop", "exit")})
    except Exception as e:  # noqa: BLE001
        logger.info("[care] journal not written: %s", e)
    logger.info("[care] %s #%s %s: %s", trade.symbol, trade.id,
                "closed" if closed else "close pending", decision["why"])
    return "closed" if closed else "attempted"
