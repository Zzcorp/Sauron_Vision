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

THE STRUCTURE STOP (2026-10-03, the thesis check, brain/thesis_check.py):
the open-position review reads the structure every half hour and, when
the thesis is alive and a stop beyond the swept extreme or the held swing
would TIGHTEN the stop in place, writes it on the row
(metadata["thesis"], verdict "adjust"). The care takes it as one more
tighten-only candidate ("structure"), fresh within THESIS_STOP_TTL_HOURS,
never on the manual lane. It is already beyond the crowd, so the crowd
read does not move it. The operator: "can the price come back... if yes
adjust" — the adjustment is the stop under the sweep, never a wider one.

THE SCALE-OUT (2026-10-04, the operator's list: "half at +1R, the rest to
break-even and trailed"): a PAPER bot row whose mark reaches +SCALE_OUT_AT_R
banks SCALE_OUT_FRACTION of its size at the modelled fill, once; the rest
rides the break-even and the trail above. The banked half is written on
the row (metadata["scale_out"]: qty, price, pnl, R, the original size),
the row's qty shrinks, and the final close adds the banked money back
(AssetBot._realised_pnl) while grading divides by the ORIGINAL size
(bot_grading), so the ledger keeps ONE trade with its blended R. Under the
aragorn_scale_out switch, beside Aragorn's own. Never on a LIVE row: eToro
closes a position whole (UnitsToDeduct is accepted and never executes,
measured 2026-09-23), so a real-money half cannot be sold — those rows keep
break-even and trail. Never on the manual lane, never on options, never
on a stock or ETF row too small to split into whole shares.

THE MIRROR (2026-10-04, the operator asked for more resilience on open
positions): the soft stop lived on the platform only. With Celery down or
the VPS gone, the venue knew the disaster stop sent at entry and nothing
else — a winner at +2R could ride back to its -1R stop. Now a REAL row
whose stop rests at the venue (metadata["protected"], a protective_trade_id)
gets every TIGHTER soft stop copied onto the venue's own stop, through the
engine's one mover (AssetBot._move_broker_stop -> client.modify_protective:
eToro PATCH stopLossRate, accepted 2026-09-23), tighten-only
(trailing.is_improvement), at the instrument's printed precision
(core.price_format.price_decimals). The level the venue took is written on
the row (care["venue_stop"], the row's stop_loss, a stop_moves entry) and
journaled (AragornAction "care_mirror"); a refusal is written too
(care["venue_stop_refusal"], the venue's own words) and asked again when
the soft stop moves or after MIRROR_RETRY_MINUTES, never every tick. A
venue stop already tighter than the lock (the operator's own hand) is left
alone and remembered. The manual lane's rows are mirrored as well: the
profit locks are the only locks they get, and the care already closes at
them. Never with a close, never a paper row, never without the venue's
handle. The risk denominator (metadata["initial_stop_loss"]) is stamped
from the sent stop before the first move on a row that lacks it, so R
keeps its meaning after the venue stop has moved.

THE EVENT WINDOW (2026-10-05, the operator asked for more resilience on
open positions): a high-impact calendar event is the weekend's gap in
miniature — the print after a central bank or a payrolls number can sit
far from the last one, through every stop. The care already locked a
winner and cut a levered real loser before the weekend shut; it now does
the same from EVENT_BEFORE_MINUTES before to EVENT_AFTER_MINUTES after a
high-impact macro event (market_data.EconomicEvent, the macro sources of
bot_program.news_risk) on the row's currency — either leg of a pair; the
home currency (USD) for every other class — and within EARNINGS_BEFORE_HOURS
of a held stock's or ETF's own earnings. A winner of EVENT_LOCK_AT_R locks
break-even ("event lock", a gap, not a hunt: the crowd read never moves
it); a REAL loser carrying EVENT_CUT_LEVERAGE or more is closed ("event
cut") rather than carried through the print. The manual lane gets the lock
only, never the cut, as on the weekend. Options are never read (a premium
has its own clock). The calendar is read once per tick (the bot's per-tick
cache) and the event the row sits in is written on its care
(care["event"]: title, at). A calendar that cannot be read means no
window: the care runs as before.

Every close, scale-out and mirror is a AragornAction. Never raises: care
that fails leaves the row to the rest of manage_positions, exactly as
before.
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
#: THE SCALE-OUT: at +SCALE_OUT_AT_R on the mark, SCALE_OUT_FRACTION of a
#: paper bot row is banked, once. Stock and ETF rows split in whole shares.
SCALE_OUT_AT_R = 1.0
SCALE_OUT_FRACTION = 0.5
WHOLE_UNIT_CLASSES = frozenset({"stock", "etf"})
SCALE_OUT_SWITCH = "aragorn_scale_out"
#: THE MIRROR: a venue that refused the soft stop is asked again when the
#: lock moves, else no sooner than this.
MIRROR_RETRY_MINUTES = 30
#: THE EVENT WINDOW: a high-impact calendar event on the row's currency is
#: the weekend's gap in miniature, from EVENT_BEFORE_MINUTES before it to
#: EVENT_AFTER_MINUTES after; a held stock's own earnings count from
#: EARNINGS_BEFORE_HOURS out. The lock and the cut are the weekend's.
EVENT_BEFORE_MINUTES = 60
EVENT_AFTER_MINUTES = 15
EARNINGS_BEFORE_HOURS = 24
EVENT_LOCK_AT_R = WEEKEND_LOCK_AT_R
EVENT_CUT_LEVERAGE = WEEKEND_CUT_LEVERAGE
EVENT_IMPACT = "high"
#: Every class but forex is exposed to this currency's events.
EVENT_HOME_CURRENCY = "USD"
#: The macro calendar's writers (news_risk.MACRO_SOURCES); earnings rows
#: are read from any source by their title.
EVENT_SOURCES = ("forexfactory", "fmp_macro")
#: The per-tick cache key (the bot's _tick_broker_cache).
EVENT_CACHE_KEY = "care_events"


def scale_out_on() -> bool:
    """The aragorn_scale_out switch, read like every component (a missing
    row reads OFF; `manage.py component on aragorn_scale_out`)."""
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled(SCALE_OUT_SWITCH))
    except Exception:  # noqa: BLE001 — an unreadable switch scales nothing
        return False


def scale_out_qty(trade, fraction: float = SCALE_OUT_FRACTION):
    """The size to bank, as a Decimal, or 0 when the row cannot be split:
    a stock or ETF row banks whole shares and keeps at least one; any
    other class banks the exact fraction."""
    from decimal import Decimal
    try:
        qty = Decimal(str(trade.qty))
    except Exception:  # noqa: BLE001
        return Decimal(0)
    if qty <= 0 or not 0 < float(fraction) < 1:
        return Decimal(0)
    if str(trade.asset_class) in WHOLE_UNIT_CLASSES:
        part = int(qty * Decimal(str(fraction)))
        if part < 1 or qty - part < 1:
            return Decimal(0)
        return Decimal(part)
    return (qty * Decimal(str(fraction))).quantize(Decimal("0.00000001"))


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


def upcoming_events(now=None, cache=None, *,
                    horizon_minutes=EVENT_BEFORE_MINUTES) -> list:
    """The calendar rows the event window can reach, as [{at, title,
    currency, earnings}] — read once per tick when `cache` (the bot's
    per-tick dict) is given. High-impact macro rows (EVENT_SOURCES) from
    EVENT_AFTER_MINUTES ago to `horizon_minutes` ahead (EVENT_BEFORE_MINUTES
    by default; the entry timing asks EVENT_ATTACK_HOURS deep and caches
    under its own key); earnings rows (any source, "earnings" in the
    title) out to EARNINGS_BEFORE_HOURS. A calendar that cannot be read
    is an empty list."""
    now = now or timezone.now()
    horizon = int(horizon_minutes or EVENT_BEFORE_MINUTES)
    key = (EVENT_CACHE_KEY if horizon == EVENT_BEFORE_MINUTES
           else f"{EVENT_CACHE_KEY}:{horizon}")
    if isinstance(cache, dict) and key in cache:
        return cache[key]
    rows = []
    try:
        from django.db.models import Q

        from market_data.models import EconomicEvent
        since = now - timedelta(minutes=EVENT_AFTER_MINUTES)
        until = now + timedelta(hours=EARNINGS_BEFORE_HOURS)
        qs = (EconomicEvent.objects
              .filter(datetime__gte=since, datetime__lte=until)
              .filter(Q(source__in=EVENT_SOURCES, impact__iexact=EVENT_IMPACT)
                      | Q(title__icontains="earnings"))
              .order_by("datetime")
              .values("datetime", "title", "currency_affected"))
        for r in qs:
            title = str(r["title"] or "")
            earnings = "earnings" in title.lower()
            if not earnings and (r["datetime"] - now) > timedelta(
                    minutes=horizon):
                continue
            rows.append({"at": r["datetime"], "title": title,
                         "currency": str(r["currency_affected"] or "").upper(),
                         "earnings": earnings})
    except Exception as e:  # noqa: BLE001 — an unread calendar is no window
        logger.info("[care] calendar unread: %s", e)
        rows = []
    if isinstance(cache, dict):
        cache[key] = rows
    return rows


def event_for(trade, now=None, events=None, *,
              before_minutes=EVENT_BEFORE_MINUTES):
    """The event whose window `trade` sits in now, or None: {title, at,
    minutes (to the event; negative once past), earnings, why}. Forex:
    either leg's currency. A stock or ETF: its own earnings (the symbol as
    the row's ticker or a word of its title) within EARNINGS_BEFORE_HOURS,
    else the home currency's events. Everything else: the home currency's.
    Options: never. The nearest event wins. A macro row counts out to
    `before_minutes` ahead (EVENT_BEFORE_MINUTES: the care's window; the
    entry timing asks EVENT_ATTACK_HOURS deep for its attack cap)."""
    import re
    now = now or timezone.now()
    before_minutes = float(before_minutes or EVENT_BEFORE_MINUTES)
    cls = str(getattr(trade, "asset_class", "") or "").lower()
    if cls == "options":
        return None
    sym = str(getattr(trade, "symbol", "") or "").upper()
    legs = (sym[:3], sym[3:6]) if len(sym) == 6 else (sym,)
    if events is None:
        events = upcoming_events(now)
    best = None
    for ev in events or []:
        at = ev.get("at")
        if at is None:
            continue
        minutes = (at - now).total_seconds() / 60.0
        if minutes < -EVENT_AFTER_MINUTES:
            continue
        if ev.get("earnings"):
            if cls not in ("stock", "etf") or not sym:
                continue
            if minutes > EARNINGS_BEFORE_HOURS * 60:
                continue
            title = str(ev.get("title") or "").upper()
            mine = (ev.get("currency") == sym
                    or re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])",
                                 title) is not None)
            if not mine:
                continue
        else:
            if minutes > before_minutes:
                continue
            ccy = str(ev.get("currency") or "").upper()
            if not ccy:
                continue
            if cls == "forex":
                if ccy not in legs:
                    continue
            elif ccy != EVENT_HOME_CURRENCY:
                continue
        if best is None or abs(minutes) < abs(best["minutes"]):
            best = {"title": str(ev.get("title") or "event"),
                    "at": at.isoformat(), "minutes": round(minutes, 1),
                    "earnings": bool(ev.get("earnings"))}
    if best is None:
        return None
    m = best["minutes"]
    when = (f"in {m:.0f} min" if m >= 0 else f"{-m:.0f} min ago")
    if best["earnings"] and m > 120:
        when = f"in {m / 60:.0f} h"
    best["why"] = f"{best['title']} {when}"
    return best


def plan(trade, price, *, now=None, posture_level="calm", kind="neutral",
         live=False, manual=False, crowd=None, scale=False,
         event=None) -> dict:
    """The care decision for one row at one mark — pure, no I/O:
    {action: "hold"|"close", reason: "SL"|"TIME"|"", why, care: {...},
     changed: bool[, scale_out: {fraction, r_now}]}. `crowd` = {"atr",
    "levels"} (smart_money.care_levels) places the profit locks beyond the
    crowd's levels. `scale` (2026-10-04): the row may bank a fraction at
    +SCALE_OUT_AT_R — a paper bot row with the switch on; `scale_out` is
    set on a HOLD whose mark stands at or past it and that has not banked
    yet (care["scaled_out"]). Never with a close, never on the manual lane.
    `event` (2026-10-05, event_for): the calendar event whose window the
    row sits in — the weekend's lock and cut apply."""
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
    if event and r_now >= EVENT_LOCK_AT_R:
        # THE EVENT WINDOW: the weekend's lock before a print that gaps
        cands.append((lvl(BREAKEVEN_LOCK_R), "event lock"))
    if not manual:
        # the thesis check's structure stop, written on the row by the
        # open-position review (brain/thesis_check.care_stop): tighten-only
        # like every candidate here, and already beyond the crowd
        from brain.thesis_check import care_stop
        structure = care_stop(meta, now)
        if structure:
            cands.append(structure)

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
    if event:
        new_care["event"] = {"title": event.get("title"), "at": event.get("at")}
    else:
        care.pop("event", None)
    out["changed"] = any(care.get(k) != new_care.get(k)
                         for k in ("peak", "worst", "soft_stop", "soft_why",
                                   "since", "event"))
    out["care"] = {**care, **new_care}

    if soft is not None and ((d > 0 and p <= soft) or (d < 0 and p >= soft)):
        out.update(action="close", reason="SL",
                   why=f"{soft_why} soft stop {soft:g} crossed at {p:g} "
                       f"({r_now:+.2f}R, best {mfe:+.2f}R)")
        out["care"]["exit"] = soft_why
        return out
    if scale and not manual and not care.get("scaled_out") \
            and str(trade.asset_class) != "options" \
            and r_now >= SCALE_OUT_AT_R:
        # THE SCALE-OUT: the mark stands at +1R NOW (not the peak — a
        # half banked at a price the market left would be a fiction);
        # the caller books the fraction and marks care["scaled_out"].
        out["scale_out"] = {"fraction": SCALE_OUT_FRACTION,
                            "r_now": round(r_now, 3),
                            "why": f"scale-out: {r_now:+.2f}R reached, "
                                   f"{SCALE_OUT_FRACTION:.0%} banked, the "
                                   f"rest to break-even and the trail"}
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
    if live and event and r_now < 0 and lev >= EVENT_CUT_LEVERAGE:
        out.update(action="close", reason="SL",
                   why=f"{event.get('why') or 'a high-impact event'}: a {lev}x "
                       f"loser ({r_now:+.2f}R) is not carried through the "
                       f"print")
        out["care"]["exit"] = "event cut"
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
    held = any(str(p.get("position_id") or "") == pid for p in positions)
    if not held:
        # THE FIRST TICK WHOSE LIST DID NOT SHOW IT (2026-10-07): the upper
        # bound of the window reconciliation writes. Booking stays
        # reconcile's.
        from bot_program import venue_exit
        venue_exit.note_missing(trade, client)
    return held


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
        # The scale-out is asked of a PAPER bot row only (the docstring:
        # eToro closes whole; the manual lane is the operator's).
        scale = bool(trade.paper) and not manual and scale_out_on()
        # THE EVENT WINDOW: the calendar once per tick, the row's event
        event = None
        try:
            event = event_for(trade, now, upcoming_events(
                now, cache=getattr(bot, "_tick_broker_cache", None)))
        except Exception as e:  # noqa: BLE001 — no calendar, no window
            logger.info("[care] %s #%s: calendar unread (%s)", trade.symbol,
                        trade.id, e)
        decision = plan(trade, price, now=now, posture_level=level, kind=kind,
                        live=not trade.paper, manual=manual, crowd=crowd,
                        scale=scale, event=event)
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
        if not trade.paper:
            # THE MIRROR: the lock goes to the venue so it outlives us
            _mirror_to_venue(bot, trade, price, client, decision)
        if decision.get("scale_out"):
            _scale_out(bot, trade, price, decision)
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


def _scale_out(bot, trade, price, decision) -> bool:
    """Bank the fraction `plan` asked for on a paper row, journal it. The
    row stays with the rest of the tick either way (the soft stop and the
    SL/TP check below it read the reduced size). Never raises."""
    ask = decision.get("scale_out") or {}
    try:
        banked = bot._scale_out_paper(trade, price, float(ask.get("fraction")
                                                           or SCALE_OUT_FRACTION),
                                      why=str(ask.get("why") or "scale-out"))
    except Exception as e:  # noqa: BLE001 — a scale-out that fails banks nothing
        logger.warning("[care] %s #%s: scale-out not booked: %s", trade.symbol,
                       trade.id, e)
        return False
    if not banked:
        return False
    so = (trade.metadata or {}).get("scale_out") or {}
    try:
        from bot_program.aragorn_models import AragornAction
        AragornAction.objects.create(
            kind="scale_out", rule_name=trade.rule_name or "",
            asset_class=trade.asset_class, symbol=trade.symbol,
            trade_id=trade.id, detail=str(ask.get("why") or "scale-out"),
            stats={"banked_qty": so.get("qty"), "banked_r": so.get("r"),
                   "remaining_qty": str(trade.qty),
                   "mfe_r": decision["care"].get("mfe_r"),
                   "r_now": decision["care"].get("r_now")})
    except Exception as e:  # noqa: BLE001
        logger.info("[care] scale-out journal not written: %s", e)
    logger.info("[care] %s #%s scaled out: %s banked at %s, %s left",
                trade.symbol, trade.id, so.get("qty"), so.get("price"),
                trade.qty)
    return True


def _mirror_to_venue(bot, trade, price, client, decision) -> bool:
    """Copy a REAL row's soft stop onto the venue's stop (the docstring: THE
    MIRROR). True when the venue took it this tick. Never raises; a mirror
    that fails leaves the platform's soft stop exactly where it was."""
    try:
        care = dict(decision.get("care") or {})
        soft = _f(care.get("soft_stop"))
        if trade.paper or soft is None or soft <= 0:
            return False
        meta = trade.metadata or {}
        if not meta.get("protected"):
            return False
        if not callable(getattr(client, "modify_protective", None)):
            return False
        d = 1.0 if str(trade.side).upper() == "BUY" else -1.0
        venue = _f(care.get("venue_stop"))
        if venue is not None and d * (venue - soft) >= -1e-12:
            return False                    # the venue holds it, or tighter
        now = timezone.now()
        asked_for = _f(care.get("venue_asked_for"))
        asked_at = care.get("venue_asked_at")
        if asked_for is not None and abs(asked_for - soft) < 1e-12 and asked_at:
            from django.utils.dateparse import parse_datetime
            last = parse_datetime(str(asked_at))
            if last is not None and (now - last) < timedelta(
                    minutes=MIRROR_RETRY_MINUTES):
                return False                # the same ask, too soon
        from decimal import Decimal

        from core.price_format import price_decimals
        from bot_program.engine.trailing import is_improvement
        places = price_decimals(soft, trade.asset_class, trade.symbol)
        candidate = Decimal(str(round(soft, places)))
        care["venue_asked_at"] = now.isoformat()
        care["venue_asked_for"] = soft
        if not is_improvement(trade, candidate, price):
            held = _f(trade.stop_loss)
            if held is not None and d * (held - soft) >= -1e-12:
                # the venue's stop is already tighter (the operator's own
                # hand, or the config knobs): remembered, nothing sent
                care["venue_stop"] = held
                care.pop("venue_stop_refusal", None)
            else:
                care["venue_stop_refusal"] = ("not sent: the level is not "
                                              "on the right side of the mark")
            _save_care(trade, care)
            return False
        if meta.get("initial_stop_loss") is None and trade.stop_loss is not None:
            # the risk denominator is the SENT stop; stamp it before the
            # row's stop_loss moves (the mover persists the metadata)
            trade.metadata = {**meta,
                              "initial_stop_loss": float(trade.stop_loss)}
        why = f"care {care.get('soft_why') or 'lock'}"
        note = ""
        try:
            ok = bool(bot._move_broker_stop(trade, price, client, candidate,
                                            why))
        except Exception as e:  # noqa: BLE001 — the venue's refusal is a fact
            ok, note = False, str(e)
        if ok:
            taken = _f(trade.stop_loss)
            care["venue_stop"] = taken if taken is not None else float(candidate)
            care.pop("venue_stop_refusal", None)
        else:
            care["venue_stop_refusal"] = str(
                (trade.metadata or {}).get("stop_move_last_error")
                or note or "refused")[:160]
        _save_care(trade, care)
        if not ok:
            logger.info("[care] %s #%s: the venue did not take the %s at %s "
                        "(%s) — the platform's soft stop stands",
                        trade.symbol, trade.id, why, candidate,
                        care["venue_stop_refusal"])
            return False
        try:
            from bot_program.aragorn_models import AragornAction
            AragornAction.objects.create(
                kind="care_mirror", rule_name=trade.rule_name or "",
                asset_class=trade.asset_class, symbol=trade.symbol,
                trade_id=trade.id,
                detail=(f"REAL MONEY: the venue stop follows the "
                        f"{care.get('soft_why') or 'lock'} to "
                        f"{care['venue_stop']:g} — the lock outlives the "
                        f"platform"),
                stats={"soft_stop": soft, "venue_stop": care["venue_stop"],
                       "mfe_r": care.get("mfe_r"), "r_now": care.get("r_now")})
        except Exception as e:  # noqa: BLE001
            logger.info("[care] mirror journal not written: %s", e)
        logger.info("[care] %s #%s: the venue stop follows the %s to %s",
                    trade.symbol, trade.id, why, care["venue_stop"])
        return True
    except Exception as e:  # noqa: BLE001 — a mirror that fails moves nothing
        logger.warning("[care] %s #%s: soft stop not mirrored: %s",
                       trade.symbol, getattr(trade, "id", "?"), e)
        return False
