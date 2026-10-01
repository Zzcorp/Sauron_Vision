"""THE POSITION CARE (2026-10-02): what happens to a position after entry.

The operator: "the maintenance on those held assets still seems poor to my
taste, I dont want to lose". It was: every eToro row is protected by the
stop and target sent with the order, so the engine skipped it every tick;
break-even and trailing were off by default; the only exit of the
platform's own was a 14-30 day clock. A winner could ride to +2R and come
back to a full -1R stop, untouched.

Each tick, for every open row the bot manages (paper too, so the paper
evidence the steward promotes on is earned under the same exits), with
the steward switch ON:

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

Every close is a StewardAction. Never raises: care that fails leaves the
row to the rest of manage_positions, exactly as before.
"""
import logging
from datetime import time as dtime

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
WEEKEND_FROM_UTC = dtime(19, 30)
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
    if str(asset_class) in NEVER_SHUTS:
        return False
    return now.weekday() == 4 and now.time() >= WEEKEND_FROM_UTC


def plan(trade, price, *, now=None, posture_level="calm", kind="neutral",
         live=False, manual=False) -> dict:
    """The care decision for one row at one mark — pure, no I/O:
    {action: "hold"|"close", reason: "SL"|"TIME"|"", why, care: {...},
     changed: bool}."""
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
    if weekend and mfe >= WEEKEND_LOCK_AT_R:
        cands.append((lvl(BREAKEVEN_LOCK_R), "weekend lock"))

    soft = _f(care.get("soft_stop"))
    soft_why = care.get("soft_why", "")
    for level, why in cands:
        tighter = soft is None or (level > soft if d > 0 else level < soft)
        if tighter:
            soft, soft_why = level, why
    new_care = {"peak": round(new_peak, 8), "worst": round(new_worst, 8),
                "mfe_r": round(mfe, 3), "mae_r": round(mae, 3),
                "r_now": round(r_now, 3)}
    if soft is not None:
        new_care["soft_stop"] = round(soft, 8)
        new_care["soft_why"] = soft_why
    out["changed"] = any(care.get(k) != new_care.get(k)
                         for k in ("peak", "worst", "soft_stop", "soft_why"))
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
    hours = (now - trade.opened_at).total_seconds() / 3600.0 \
        if trade.opened_at else 0.0
    limit = NO_PROGRESS_HOURS.get(str(trade.asset_class),
                                  NO_PROGRESS_DEFAULT_HOURS)
    if hours >= limit and mfe < BREAKEVEN_AT_R and r_now < NO_PROGRESS_MAX_R:
        out.update(action="close", reason="TIME",
                   why=f"no progress: {hours:.0f}h open, best {mfe:+.2f}R, "
                       f"now {r_now:+.2f}R")
        out["care"]["exit"] = "no progress"
        return out
    return out


def care(bot, trade, price, client, *, now=None) -> bool:
    """Run the care on one row inside manage_positions. True when it closed
    the row (the caller counts it and moves on)."""
    from bot_program import steward
    if not steward.is_on():
        return False
    now = now or timezone.now()
    try:
        level, kind = "calm", "neutral"
        from bot_program import market_stress, posture
        if not trade.paper and posture.crisis_mode_on():
            level = market_stress.current(now)["level"]
            kind = posture.classify(trade.symbol, trade.asset_class, trade.side)
        manual = False
        try:
            from bot_program.share_allocator import _is_manual_lane
            manual = bool(_is_manual_lane(bot.cfg))
        except Exception:  # noqa: BLE001 — unknown reads as a bot's own
            manual = False
        decision = plan(trade, price, now=now, posture_level=level, kind=kind,
                        live=not trade.paper, manual=manual)
    except Exception as e:  # noqa: BLE001 — care that fails changes nothing
        logger.warning("[care] %s #%s not cared for: %s", trade.symbol,
                       trade.id, e)
        return False
    if decision["changed"] or decision["action"] == "close":
        meta = dict(trade.metadata or {})
        meta["care"] = decision["care"]
        if decision["action"] == "close":
            meta["care_exit"] = decision["care"].get("exit", "")
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
    if decision["action"] != "close":
        return False
    closed = bot._close_trade(trade, price, client, reason=decision["reason"])
    try:
        from bot_program.steward_models import StewardAction
        StewardAction.objects.create(
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
    return bool(closed)
