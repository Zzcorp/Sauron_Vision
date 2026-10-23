"""THE DAY'S WEATHER (spec §7.5.3): calm, eventful or stormy per (user,
class), computed at the trading-day roll (17:00 New York) over the day
ahead, re-run UPWARD only when the posture's level or the Mind's regime
changed since it was computed, never lowered within the trading day.

In O1 the weather routes nothing and caps nothing: it is journaled on
every detected wake, shown on the card and the Horde's class band (O1d),
and its caps are written for display only (`caps_for`; the dollar caps
arrive with the router, O2).

    calm       day score < 30
    eventful   30 to < 55
    stormy     >= 55; or a stressed, crisis or recovery posture (only while
               measured: with crisis_mode OFF the posture is never read,
               so it never makes a day stormy); or three high-impact
               prints today on the class's currencies

The day score renormalises the six market terms over their own weights
(bot_program/orcs/complexity.day_score).
"""
import logging
from datetime import timedelta

from bot_program.orcs import complexity
from bot_program.orcs.constants import ROUTING_VERSION

logger = logging.getLogger(__name__)

#: §7.5.7, display only in O1: the model wakes a day by money and weather,
#: and the frontier quota (§7.5.3).
WAKES_PER_DAY = {"real": {"calm": 12, "eventful": 14, "stormy": 16},
                 "paper": 12}
FRONTIER_PER_DAY = {"calm": 1, "eventful": 2, "stormy": 4}
_RANK = {"calm": 0, "eventful": 1, "stormy": 2}


def caps_for(day_class, real) -> dict:
    wakes = (WAKES_PER_DAY["real"].get(day_class, 12) if real
             else WAKES_PER_DAY["paper"])
    return {"wakes_per_day": int(wakes),
            "frontier_quota": int(FRONTIER_PER_DAY.get(day_class, 1)),
            "probes": day_class != "stormy", "display_only": True}


def _class_currencies(user, asset_class) -> list:
    """The currencies whose prints reach the class: either leg of every
    held pair for forex, USD otherwise."""
    if asset_class != "forex":
        return ["USD"]
    try:
        from bot_program.orcs.constants import STATE_DEAD
        from bot_program.orcs.models import Orc
        out = set()
        for sym in (Orc.objects.filter(user=user, asset_class="forex")
                    .exclude(state=STATE_DEAD)
                    .values_list("symbol", flat=True)):
            s = str(sym).upper()
            if len(s) == 6:
                out.update((s[:3], s[3:]))
        return sorted(out) or ["USD"]
    except Exception:  # noqa: BLE001
        return ["USD"]


def market_inputs(user, asset_class, now) -> dict:
    """The six market terms' raw inputs for the class over the day ahead,
    with the posture and the Mind's regime they were read on. Never
    raises: an unread input is its component's dash."""
    from bot_program.orcs import sources
    from bot_program.orcs.sessions import day_bounds, trading_day
    td = trading_day(now)
    start, end = day_bounds(td)
    out = {}
    try:
        p = sources.posture(now)
    except Exception:  # noqa: BLE001
        p = sources.dash("posture unread")
    fresh = not p.get("dash")
    level = (p["value"] or {}).get("level") if fresh else "unmeasured"
    term = sources.vix_term(now)
    out["stress"] = {"fresh": fresh,
                     "score": (sources._f((p["value"] or {}).get("score"))
                               if fresh else None),
                     "vix_term": (sources._f(term["value"])
                                  if not term.get("dash") else None)}
    out["posture_level"], out["posture_fresh"] = level, fresh
    try:
        from bot_program.persona_mix import latest_report
        rep = latest_report(now)
        then = latest_report(start)
        out["regime_label"] = str(rep.get("regime") or "unknown")
        out["regime"] = {
            "posture_changed_h": (sources.posture_changed_h(now, start)
                                  if fresh else None),
            "brain_changed": (rep.get("report_id") is not None
                              and then.get("report_id") is not None
                              and rep.get("regime") != then.get("regime")),
            "brain_conf": (float(rep.get("confidence") or 0)
                           if rep.get("report_id") is not None else None)}
    except Exception:  # noqa: BLE001
        out["regime_label"], out["regime"] = "unknown", {}
    cal = sources.calendar(start, end, _class_currencies(user, asset_class))
    if cal.get("dash"):
        out["prints"] = {"unread": True}
        out["prints_today"] = 0
    else:
        rows = cal["value"]
        soon = [r for r in rows if now <= r["at"] <= now + timedelta(hours=3)]
        major = any(m in r["title"].upper() for r in soon
                    for m in complexity.MAJOR_PRINTS)
        out["prints"] = {"in_24h": len(rows), "within_3h": len(soon),
                         "in_window": False, "major": major}
        out["prints_today"] = len(rows)
    blind, since = sources.analyst_blind(now)
    if blind:
        out["news"] = {"blind": True, "since": since}
    else:
        ratio = sources.news_ratio(asset_class, now)
        out["news"] = {"blind": False,
                       "ratio": None if ratio.get("dash") else ratio["value"]}
    out["atr_ratio"] = None
    shut = False
    try:
        from bot_program.orcs.sessions import shuts_within
        shut = bool(shuts_within(asset_class, "", now,
                                 hours=(end - now).total_seconds() / 3600.0))
    except Exception:  # noqa: BLE001
        shut = False
    out["gap"] = {"shut_within_6h": shut, "gap_r": None}
    return out


#: The class's day reads no volatility of its own: `vol` is one row's ATR
#: against its median, read on each wake (bot_program/orcs/wake.py).
VOL_PER_ROW = "— (read per position on each wake, not per class)"


def _market(inputs) -> dict:
    comps = complexity.components(inputs)
    market = {k: comps[k] for k in complexity.MARKET_KEYS}
    if inputs.get("atr_ratio") is None:
        market["vol"] = {**market["vol"], "dash": VOL_PER_ROW}
    return market


def _compute(inputs) -> tuple:
    market = _market(inputs)
    sc = complexity.day_score(market)
    cls = complexity.day_class(sc, posture_level=inputs.get("posture_level"),
                               posture_fresh=inputs.get("posture_fresh"),
                               prints_today=inputs.get("prints_today"))
    return market, sc, cls


def _stamp(inputs) -> dict:
    return {"posture_level": inputs.get("posture_level"),
            "regime_label": inputs.get("regime_label")}


def current(user, asset_class, now=None, *, inputs=None, real=True):
    """The (user, class) weather for `now`'s trading day: created at the
    first read of the day; raised (never lowered) when the posture's level
    or the Mind's regime changed since its inputs were read."""
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from bot_program.orcs.models import OrcDayBaseline
    from bot_program.orcs.sessions import trading_day
    now = now or timezone.now()
    td = trading_day(now)
    row = OrcDayBaseline.objects.filter(user=user, asset_class=asset_class,
                                        trading_day=td).first()
    if row is not None and inputs is None:
        cheap = _cheap_stamp(now)
        if cheap == (row.components or {}).get("inputs"):
            return row
    inputs = inputs if inputs is not None else market_inputs(
        user, asset_class, now)
    stamp = _stamp(inputs)
    if row is not None and stamp == (row.components or {}).get("inputs"):
        return row
    market, sc, cls = _compute(inputs)
    entry = {"at": now.isoformat(), "score": sc, "day_class": cls,
             "inputs": stamp}
    if row is None:
        try:
            with transaction.atomic():
                return OrcDayBaseline.objects.create(
                    user=user, asset_class=asset_class, trading_day=td,
                    day_class=cls, score=sc,
                    components={"market": market, "inputs": stamp},
                    caps=caps_for(cls, real),
                    frontier_quota=caps_for(cls, real)["frontier_quota"],
                    routing_version=ROUTING_VERSION,
                    history=[{**entry, "why": "computed at the day's first "
                                              "read"}])
        except IntegrityError:
            row = OrcDayBaseline.objects.get(user=user,
                                             asset_class=asset_class,
                                             trading_day=td)
    comps = dict(row.components or {})
    comps["inputs"] = stamp
    raised = (sc > float(row.score or 0)
              or _RANK.get(cls, 0) > _RANK.get(row.day_class, 0))
    if raised:
        new_cls = cls if _RANK.get(cls, 0) >= _RANK.get(row.day_class, 0) \
            else row.day_class
        row.score = max(sc, float(row.score or 0))
        row.day_class = new_cls
        comps["market"] = market
        row.caps = caps_for(new_cls, real)
        row.frontier_quota = row.caps["frontier_quota"]
        row.history = list(row.history or []) + [
            {**entry, "day_class": new_cls, "why": "re-run upward: the "
                                                   "posture or the regime "
                                                   "changed"}]
    row.components = comps
    row.save()
    return row


def _cheap_stamp(now) -> dict:
    """The posture's level and the Mind's regime now: two reads, so an
    unchanged day costs no recomputation."""
    from bot_program.orcs import sources
    p = sources.posture(now)
    level = (p["value"] or {}).get("level") if not p.get("dash") \
        else "unmeasured"
    try:
        from bot_program.persona_mix import latest_report
        regime = str(latest_report(now).get("regime") or "unknown")
    except Exception:  # noqa: BLE001
        regime = "unknown"
    return {"posture_level": level, "regime_label": regime}


def hourly(user, asset_class, now) -> dict:
    """The class's hourly market terms (§7.5.1), stored under
    components["hour"] of the day's row, and the upward re-run."""
    inputs = market_inputs(user, asset_class, now)
    row = current(user, asset_class, now, inputs=inputs)
    hour = _market(inputs)
    hour["at"] = now.isoformat()
    data = dict(row.components or {})
    data["hour"] = hour
    row.components = data
    row.save(update_fields=["components", "computed_at"])
    return hour
