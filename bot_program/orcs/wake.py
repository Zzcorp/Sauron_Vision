"""WAKE DETECTION IN O1 (spec §1.3, §7.5, §5.2a): the tick DETECTS and
RECORDS; nothing is dispatched, no model is asked.

In the tick, after the care, the facts, the predicates, the arms and the
drums (bot_program/orcs/observe.py), `detect` reads what changed between
the Orc's memory before this tick (`orc._seen_before`) and after it, the
care's state on the row and the frames the tick already read, and finds:

  W1   the first detect after the birth                          urgent
  W2   a final venue bar of the decision timeframe (a Mercenary's 1h)
  W3   the mark within 0.1 x ATR(1h) of an invalidation level, once per
       level per 4 h                                              urgent
  W4   +1R, +2R, +3R first reached; -0.5R and -0.75R (urgent); the
       give-back to half the best after +1R
  W6   the care moved its stop; the venue refused the stop; the care
       closed the position (urgent)
  W8   a predicate met (urgent); the thesis check reads exit
  W9   a hand edit of the levels
  W10  a close in doubt, an entry in doubt, inert stop rules     urgent
  W11  the metronome: every 4 h while the market is open; a stock or ETF
       at its open + 60 min and its close - 90 min; 2 h before a weekend

and merges what the census left in `seen["wake_pending"]` (W5 the clock
around a print, W7 the book, W10 a close pending, W12 a drum). Each reason
counts once per key. An urgent reason records at once; the others wait
for MIN_WAKE_SPACING_MIN after the last recorded wake.

A recorded wake gets its complexity score, band and the day's class
(bot_program/orcs/complexity.py, weather.py), its dossier rendered and
stored (dossier.py), then: an OrcWake (`skipped`, "no model before O2";
or `quiet` under F6 with a code `reading` and Orc.latest_note), a journal
`wake` entry kept off the card's lines, and the card's `intellect`,
`integrity` and `next_wake_due`. Detection, spacing and the proxy for the
last answered facts hash live in Orc.seen, never in O2's columns
(last_wake_at, last_facts_hash).

`detect` never raises; a recorded wake is written in a savepoint, so a
failure leaves the tick and the Orc as they were, and a quiet tick costs
no query at all.

# O2: a recorded wake is dispatched (status `pending`, the router, the
# reserve, the budget) instead of `skipped`; W12 becomes a drum wake.
"""
import hashlib
import json
import logging
import math
from datetime import timedelta

from bot_program.orcs.constants import (BAND_HOLD_AFTER_URGENT_MIN,
                                        MIN_WAKE_SPACING_MIN, STATE_DEAD,
                                        STATUS_WORDS, W3_NEAR_ATR1H,
                                        W3_ONCE_H, W4_GIVEBACK_SHARE,
                                        W4_THRESHOLDS, W5_EARNINGS_H,
                                        W5_LATE_MIN, W5_OFFSETS_MIN,
                                        W7_OPEN_RISK_SHARE,
                                        W11_CLOSE_BEFORE_MIN,
                                        W11_METRONOME_H, W11_OPEN_AFTER_MIN,
                                        W11_WEEKEND_BEFORE_H,
                                        WAKE_KEYS_KEPT, WAKE_SKIPPED_REASON,
                                        WAKE_STATUS_QUIET,
                                        WAKE_STATUS_SKIPPED)

logger = logging.getLogger(__name__)

RUNG_O1 = "no model (O1: code only)"
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")
_RANKS = {"hold": "R0", "revise_plan": "R1", "tighten": "R2",
          "lock_waive": "R3", "trim": "R4", "exit": "R4", "add": "R5",
          "reenter": "R5", "be_swap": "R5", "widen_with_cut": "R6",
          "reverse": "R6"}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _iso(t):
    return t.isoformat() if hasattr(t, "isoformat") else t


def _parse(s):
    from django.utils.dateparse import parse_datetime
    try:
        return parse_datetime(str(s)) if s else None
    except (TypeError, ValueError):
        return None


def facts_hash(snapshot) -> str:
    """The facts a quiet wake compares (§1.3): the R in quarter-R buckets,
    the menu's level set, the PO3 phase, the calendar distance (by the
    hour), the thesis check's verdict, the predicates' states."""
    s = snapshot or {}
    r = _f(s.get("r_now"))
    cal = _f(s.get("calendar_min"))
    canon = {"r": None if r is None else int(math.floor(r / 0.25 + 1e-9)),
             "menu": sorted(str(x) for x in s.get("menu") or ()),
             "po3": str(s.get("po3") or ""),
             "calendar_h": None if cal is None else int(cal // 60),
             "thesis": str(s.get("thesis") or ""),
             "predicates": {str(k): str(v) for k, v in sorted(
                 (s.get("predicates") or {}).items())}}
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()) \
        .hexdigest()


def _reason(code, key, t, urgent) -> dict:
    return {"code": code, "key": str(key)[:120], "t": str(t),
            "urgent": bool(urgent)}


# ── the reasons ──────────────────────────────────────────────────────────

def _w2(orc, trade, now, cache, seen, add):
    from bot_program.orcs import bars, dossier
    tf = dossier.decision_tf(orc)
    f = bars.frame(trade.symbol, tf, asset_class=trade.asset_class, now=now,
                   cache=cache)
    if f is None or not f.venue or not f.fresh:
        return None
    end = bars.final_end(f, now)
    if end is None:
        return None
    if seen.get("w1") and seen.get("w2_bar") != end.isoformat():
        add("W2", f"W2:{tf}:{end.isoformat()}", f"{tf} bar closed", False)
    return end.isoformat()


def _w3(orc, trade, price, now, cache, add):
    from bot_program.orcs import bars
    from bot_program.orcs.facts import px
    levels = [p for p in (orc.thesis or {}).get("invalidation") or []
              if isinstance(p, dict) and p.get("kind") == "close_beyond"
              and _f(p.get("level")) is not None]
    if not levels or _f(price) is None:
        return
    f = bars.frame(trade.symbol, "1h", asset_class=trade.asset_class,
                   now=now, cache=cache)
    atr = f.atr if f is not None else None
    if not atr:
        return
    bucket = int(now.timestamp() // (W3_ONCE_H * 3600))
    for p in levels:
        if abs(_f(price) - _f(p["level"])) <= W3_NEAR_ATR1H * atr:
            lid = p.get("level_id") or "the level"
            add("W3", f"W3:{lid}:{bucket}",
                f"the mark near {lid} ({px(trade, p['level'])})", True)


def _w4(care, add):
    mfe, now_r = _f(care.get("mfe_r")), _f(care.get("r_now"))
    worst = min(x for x in (now_r, _f(care.get("mae_r")), 0.0)
                if x is not None)
    for thr in W4_THRESHOLDS:
        if thr > 0 and mfe is not None and mfe >= thr:
            add("W4", f"W4:{thr:+g}", f"{thr:+g}R reached", False)
        elif thr < 0 and worst <= thr:
            add("W4", f"W4:{thr:+g}", f"{thr:+g}R reached", True)
    if mfe is not None and now_r is not None and mfe >= 1.0 and \
            now_r <= W4_GIVEBACK_SHARE * mfe:
        add("W4", "W4:giveback", "give-back to half the best", False)


def _w6_w8_w9(before, seen, cared, add):
    if seen.get("care_stop") is not None and \
            before.get("care_stop") != seen.get("care_stop"):
        add("W6", f"W6:stop:{seen.get('care_stop')}",
            "the care moved its stop", False)
    if before.get("venue_refused") is None and \
            seen.get("venue_refused") is not None:
        add("W6", f"W6:refused:{seen.get('venue_refused')}",
            "the venue refused the stop", False)
    if cared in ("closed", "attempted"):
        add("W6", "W6:closed", "the care closed the position", True)
    pb = before.get("predicates") or {}
    for key, st in sorted((seen.get("predicates") or {}).items()):
        if (st or {}).get("state") == "met" and \
                (pb.get(key) or {}).get("state") != "met":
            add("W8", f"W8:{key}",
                f"invalidation met ({key.split(':')[0]})", True)
    tb = (before.get("thesis") or [None])[0]
    ta = (seen.get("thesis") or [None])[0]
    if ta == "exit" and tb != "exit":
        add("W8", f"W8:thesis:{seen.get('thesis')}",
            "the thesis check reads exit", False)
    if seen.get("hand_at") and seen.get("hand_at") != before.get("hand_at"):
        add("W9", f"W9:{seen.get('hand_at')}", "a hand edit of the levels",
            False)


def _w10(bot, trade, add):
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    try:
        from bot_program.pending_closes import CLOSE_IN_DOUBT_KEY
    except Exception:  # noqa: BLE001
        CLOSE_IN_DOUBT_KEY = "close_in_doubt"
    doubt = meta.get(CLOSE_IN_DOUBT_KEY)
    if doubt:
        at = doubt.get("at") if isinstance(doubt, dict) else doubt
        add("W10", f"W10:doubt:{at}", "a close in doubt", True)
    inert = meta.get("stop_rules_inert")
    if inert:
        add("W10", f"W10:inert:{inert}", "the stop rules are inert", True)
    cfg = getattr(bot, "cfg", None)
    book = ((getattr(cfg, "extras", None) or {}).get("entry_in_doubt")
            if cfg is not None else None) or {}
    note = book.get(str(trade.symbol).upper()) if isinstance(book, dict) \
        else None
    if isinstance(note, dict) and note.get("at"):
        add("W10", f"W10:entry:{note.get('at')}",
            "an entry in doubt on this symbol", True)


def _w11(orc, trade, now, seen, add):
    from bot_program.orcs.sessions import NEVER_SHUTS, next_shut
    cls = str(trade.asset_class or "")
    shut = None
    if cls not in NEVER_SHUTS:
        try:
            shut = next_shut(cls, trade.symbol, now)
        except Exception:  # noqa: BLE001
            shut = None
        if shut and shut.get("now_shut"):
            return
    last = _parse(seen.get("w11_at"))
    if last is not None and now - last >= timedelta(hours=W11_METRONOME_H):
        add("W11", f"W11:{now:%Y%m%d%H}", "metronome", False)
    if shut and shut.get("modelled") and shut.get("at") is not None:
        to_shut = (shut["at"] - now).total_seconds() / 60.0
        day = f"{now:%Y%m%d}"
        if shut.get("kind") == "weekend" and \
                0 < to_shut <= W11_WEEKEND_BEFORE_H * 60:
            add("W11", f"W11:weekend:{day}",
                "metronome: two hours before the weekend", False)
        if cls in ("stock", "etf") and 0 < to_shut <= W11_CLOSE_BEFORE_MIN:
            add("W11", f"W11:close:{day}",
                "metronome: 90 min before the close", False)
    if cls in ("stock", "etf"):
        try:
            from core.exchange_status import market_clock
            opened = market_clock(cls, "", trade.symbol,
                                  now_utc=now).get("opened")
        except Exception:  # noqa: BLE001
            opened = None
        if opened is not None and now - opened >= timedelta(
                minutes=W11_OPEN_AFTER_MIN):
            add("W11", f"W11:open:{now:%Y%m%d}",
                "metronome: 60 min after the open", False)


def reasons_words(reasons) -> str:
    return ", ".join(str(r.get("t") or r.get("code")) for r in reasons or ())


# ── the tick's entry ─────────────────────────────────────────────────────

def detect(bot, trade, price, cared, orc):
    """Detect, and record when due. The OrcWake, or None. Never raises."""
    try:
        if orc is None or trade is None or orc.state == STATE_DEAD:
            return None
        return _detect(bot, trade, price, cared, orc)
    except Exception as e:  # noqa: BLE001 — the Orcs never stop the tick
        logger.warning("[orcs] Orc %s: wake detection failed: %s",
                       getattr(orc, "pk", "?"), e)
        return None


def _detect(bot, trade, price, cared, orc):
    from bot_program.orcs.observe import _now_of
    now = _now_of(trade)
    cache = getattr(bot, "_tick_broker_cache", None)
    seen = dict(orc.seen or {})
    before = getattr(orc, "_seen_before", None)
    before = dict(before) if isinstance(before, dict) else dict(seen)
    keys = set(seen.get("wake_keys") or [])
    pending = dict(seen.get("wake_pending") or {})
    reasons = [r for r in pending.get("reasons") or []
               if isinstance(r, dict) and r.get("key") not in keys]
    have = {r["key"] for r in reasons}
    fresh = []

    def add(code, key, t, urgent):
        if key in keys or key in have:
            return
        have.add(key)
        fresh.append(_reason(code, key, t, urgent))

    if not seen.get("w1"):
        add("W1", "W1", "birth", True)
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    w2_bar = _w2(orc, trade, now, cache, seen, add)
    _w3(orc, trade, price, now, cache, add)
    _w4(care, add)
    _w6_w8_w9(before, seen, cared, add)
    _w10(bot, trade, add)
    if seen.get("w1"):
        _w11(orc, trade, now, seen, add)
    reasons += fresh
    if not reasons:
        return None
    urgent = any(r.get("urgent") for r in reasons)
    last = _parse(seen.get("last_recorded"))
    spaced = last is None or now - last >= timedelta(
        minutes=MIN_WAKE_SPACING_MIN)
    if not urgent and not spaced:
        if fresh:
            from bot_program.orcs import journal
            journal.remember(orc, wake_pending={
                "reasons": reasons,
                "since": pending.get("since") or now.isoformat()})
        return None
    # the record runs in a savepoint: a failure inside it leaves no half
    # wake; a quiet tick opens none (no query at all)
    from django.db import transaction
    with transaction.atomic():
        return record(orc, trade, reasons, now=now, bot=bot, price=price,
                      cache=cache, w2_bar=w2_bar)


# ── recording ────────────────────────────────────────────────────────────

def _world_real(trade) -> bool:
    try:
        from bot_program.orcs.birth import world
        from bot_program.orcs.constants import VENUE_LIVE
        return world(trade) == VENUE_LIVE
    except Exception:  # noqa: BLE001
        return not bool(getattr(trade, "paper", True))


def _atr_ratio(frame):
    try:
        from signals.smc.pivots import atr
        series = [float(x) for x in atr(frame.df) if x == x and x > 0]
        closes = [float(c) for c in frame.df["close"].values[-len(series):]]
        pct = [a / c for a, c in zip(series, closes) if c > 0]
        if len(pct) < 20:
            return None
        window = sorted(pct[-250:])
        median = window[len(window) // 2]
        return pct[-1] / median if median > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _position_inputs(orc, trade, ctx, reasons, now, market) -> dict:
    """The complexity inputs of this wake: the class's market terms from
    the day's weather (regime, news, stress), this row's own vol, prints
    and gap, and the position and decision terms."""
    from bot_program.orcs import gaps, sources
    from bot_program.orcs.facts import r_at
    from bot_program.orcs.sessions import shuts_within
    care = ctx.get("care") or {}
    inputs = {}
    f1h = None
    try:
        from bot_program.orcs import bars
        f1h = bars.frame(trade.symbol, "1h", asset_class=trade.asset_class,
                         now=now, cache=ctx.get("cache"))
    except Exception:  # noqa: BLE001
        f1h = None
    inputs["atr_ratio"] = _atr_ratio(f1h) if f1h is not None else None
    cal = ctx.get("calendar") or {}
    if cal.get("dash"):
        inputs["prints"] = {"unread": True}
        inputs["gap"] = {"unread": True}
    else:
        from bot_program.orcs.situation import currencies
        from bot_program.orcs.complexity import MAJOR_PRINTS
        ccys = currencies(trade)
        mine = [e for e in cal["value"] if e["ccy"] in ccys
                and e["at"] >= now - timedelta(minutes=15)]
        day = [e for e in mine if e["at"] <= now + timedelta(hours=24)]
        soon = [e for e in mine if e["at"] <= now + timedelta(hours=3)]
        inputs["prints"] = {
            "in_24h": len(day), "within_3h": len(soon),
            "in_window": bool(care.get("event")),
            "major": any(m in e["title"].upper() for e in soon
                         for m in MAJOR_PRINTS)}
        shut, gap_r = False, None
        try:
            shut = bool(shuts_within(trade.asset_class, trade.symbol, now,
                                     hours=6))
            if shut and ctx.get("rpu"):
                g = gaps.next_shut_gap(trade.symbol, trade.asset_class,
                                       now=now)
                gap_r = gaps.in_r(g, ctx["rpu"]) if gaps.measured(g) \
                    else None
        except Exception:  # noqa: BLE001
            pass
        inputs["gap"] = {"shut_within_6h": shut, "gap_r": gap_r}
    eff, m, atr = ctx.get("effective"), ctx.get("m"), ctx.get("atr1h")
    inputs["stop_atr"] = (abs(m - eff) / atr if eff is not None and
                          m is not None and atr else None)
    r_now = _f(care.get("r_now"))
    if r_now is None and m is not None:
        r_now = r_at(trade, m)
    mfe = _f(care.get("mfe_r"))
    points = 0
    if r_now is not None:
        points += sum(1 for lv in (1.0, 1.5, -0.75)
                      if abs(r_now - lv) <= 0.2)
        if mfe is not None and mfe >= 1.0 and r_now <= 0.5 * mfe:
            points += 1
    for p in (orc.thesis or {}).get("invalidation") or []:
        lv = _f((p or {}).get("level")) if isinstance(p, dict) else None
        if lv is not None and m is not None and atr and \
                abs(m - lv) <= 0.5 * atr:
            points += 1
    inputs["decision_points"] = points
    book = sources.book(orc.user, real=bool(ctx.get("real")),
                        cache=ctx.get("cache"))
    limit = _f(book.get("_limit")) if not book.get("dash") else None
    r_money = _f(orc.r_money)
    wc = r_at(trade, eff) if eff is not None else -1.0
    risk_r = max(0.0, -(wc if wc is not None else -1.0))
    inputs["size_share"] = (r_money * risk_r / limit
                            if limit and r_money else None)
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    deb = meta.get("debate") if isinstance(meta.get("debate"), dict) else {}
    ex = (deb.get("executioner") or {}).get("verdict") if deb else None
    ch = (deb.get("champion") or {}).get("verdict") if deb else None
    disp = None
    if ex or ch:
        e = {"veto": -1.0, "cut": -0.5, "pass": 0.0}.get(str(ex), 0.0)
        c = {"back": 1.0, "neutral": 0.0}.get(str(ch), 0.0)
        disp = abs(e - c) / 2.0
    flags = ["a drum heard on this wake"] if any(
        r.get("code") == "W12" for r in reasons) else []
    inputs["disagreement"] = {"dispersion": disp, "flags": flags}
    ranks = [_RANKS.get(getattr(c, "action", ""), "R0")
             for c in ctx.get("all_candidates") or []]
    if any(getattr(c, "id", "") == "P-HOLD" for c in
           ctx.get("all_candidates") or []):
        ranks.append("R3")
    inputs["reversibility"] = {"r": max(ranks or ["R0"]), "shadow": True}
    for key in ("regime", "news", "stress"):
        inputs[f"_market_{key}"] = (market or {}).get(key)
    return inputs


def _components(inputs):
    from bot_program.orcs import complexity
    comps = complexity.components(inputs)
    for key in ("regime", "news", "stress"):
        given = inputs.get(f"_market_{key}")
        if isinstance(given, dict) and "s" in given:
            comps[key] = given
    return comps


def _snapshot(orc, trade, ctx) -> dict:
    from bot_program.orcs.facts import r_at
    care = ctx.get("care") or {}
    r_now = _f(care.get("r_now"))
    if r_now is None and ctx.get("m") is not None:
        r_now = r_at(trade, ctx["m"])
    nxt = ctx.get("next_event")
    th = ctx.get("thesis_check") or {}
    po3 = ctx.get("po3")
    return {"r_now": r_now,
            "menu": [r.get("id") for r in ctx.get("rows") or []],
            "po3": po3 if isinstance(po3, str) else (
                (po3 or {}).get("phase") if isinstance(po3, dict) else ""),
            "calendar_min": ((nxt["at"] - ctx["now"]).total_seconds() / 60.0
                             if nxt else None),
            "thesis": th.get("verdict") if isinstance(th, dict) else "",
            "predicates": {k: (v or {}).get("state") for k, v in (
                (orc.seen or {}).get("predicates") or {}).items()}}


def _reading(trade, ctx, tf) -> str:
    from bot_program.orcs.facts import px, r_at
    care = ctx.get("care") or {}
    r_now = _f(care.get("r_now"))
    if r_now is None and ctx.get("m") is not None:
        r_now = r_at(trade, ctx["m"])
    r = f"{r_now:+.1f}R" if r_now is not None else "its R unmeasured"
    soft = _f(care.get("soft_stop"))
    care_t = (f"care {care.get('soft_why') or 'lock'} at {px(trade, soft)}"
              if soft is not None else "no care stop yet")
    return f"Nothing new: {r}, {care_t}, {tf} structure unchanged."


def _kind_of(reasons) -> str:
    codes = {r.get("code") for r in reasons}
    if "W1" in codes:
        return "birth"
    if codes <= {"W2", "W11"}:
        return "routine"
    return "material"


def record(orc, trade, reasons, *, now, bot=None, price=None, cache=None,
           w2_bar=None):
    """Score, render and store one detected wake. Returns the OrcWake."""
    from bot_program.orcs import complexity, dossier, journal, weather
    from bot_program.orcs.models import OrcWake
    real = _world_real(trade)
    ctx = dossier.context_for(orc, trade, price=price, now=now, cache=cache,
                              reasons=reasons, bot=bot)
    ctx["real"] = real
    day = weather.current(orc.user, orc.asset_class, now, real=real)
    hour = (day.components or {}).get("hour") or {}
    hour_at = _parse(hour.get("at")) if isinstance(hour, dict) else None
    market = hour if hour_at is not None and now - hour_at <= timedelta(
        minutes=90) else (day.components or {}).get("market") or {}
    rendered = dossier.render(orc, trade, ctx, as_of=now)
    inputs = _position_inputs(orc, trade, ctx, reasons, now, market)
    comps = _components(inputs)
    st = complexity.stakes(real=real, hand=bool(orc.manual))
    sc = complexity.score(comps, st)
    kind = _kind_of(reasons)
    codes = {r.get("code") for r in reasons}
    floor = complexity.floors(kind=kind, real=real, binding_on_table=False,
                              day_class=day.day_class, birth="W1" in codes)
    seen = orc.seen or {}
    urgent = any(r.get("urgent") for r in reasons)
    band = complexity.band(sc, prev_band=seen.get("band"),
                           hold_until=_parse(seen.get("band_hold_until")),
                           now=now, floor=floor)
    f5_on, f5_items = complexity.f5(ctx.get("integrity"))
    snapshot = _snapshot(orc, trade, ctx)
    fh = facts_hash(snapshot)
    quiet = complexity.f6(reasons, fh, seen.get("answered_hash"))
    status = WAKE_STATUS_QUIET if quiet else WAKE_STATUS_SKIPPED
    words = reasons_words(reasons)
    wake = OrcWake.objects.create(
        orc=orc, reasons=reasons,
        dedupe_key=f"orc{orc.pk}:{now:%Y%m%d%H%M%S}:{reasons[0]['key']}"
        [:120],
        priority=1.0 if urgent else 0.0, kind=kind, status=status,
        skipped_reason=("" if quiet else WAKE_SKIPPED_REASON),
        score=sc, band=band, day_class=day.day_class,
        components={**comps, "stakes": st, "floor": floor,
                    "f5": f5_items, "f6": quiet,
                    "tokens": rendered.get("tokens"),
                    "trimmed": rendered.get("trimmed")},
        block_hashes=rendered["hashes"], finished_at=now)
    keys = list(seen.get("wake_keys") or []) + [r["key"] for r in reasons]
    w11_at = now.isoformat() if ("W11" in codes or not seen.get("w1")) \
        else seen.get("w11_at") or now.isoformat()
    due = (_parse(w11_at) or now) + timedelta(hours=W11_METRONOME_H)
    remember = {"w1": True, "wake_keys": keys[-WAKE_KEYS_KEPT:],
                "wake_pending": None, "last_recorded": now.isoformat(),
                "band": band, "w11_at": w11_at,
                "band_hold_until": ((now + timedelta(
                    minutes=BAND_HOLD_AFTER_URGENT_MIN)).isoformat()
                    if urgent else seen.get("band_hold_until"))}
    if w2_bar:
        remember["w2_bar"] = w2_bar
    if not quiet:
        remember["answered_hash"] = fh
    from bot_program.orcs.integrity import words as integrity_words
    card_extra = {
        "intellect": {"score_v": round(sc), "score_t":
                      f"score {sc:.0f} · {band}", "band": band,
                      "day_class": day.day_class, "rung_t": RUNG_O1,
                      "status_t": STATUS_WORDS.get(status, status),
                      "escalated": False, "late": False,
                      "at": now.isoformat()},
        "integrity": {"flag": (ctx.get("integrity") or {}).get("flag", "ok"),
                      "t": integrity_words(ctx.get("integrity"))},
        "next_wake_due": due.isoformat()}
    headline = (f"Wake detected: {words}. Complexity {sc:.0f} ({band}); "
                f"the day is {day.day_class}. Recorded only: no model is "
                f"asked yet.")
    journal.append(orc, "wake", headline, body={
        "wake": wake.pk, "reasons": [r["t"] for r in reasons], "score": sc,
        "band": band, "day_class": day.day_class, "status": status,
        "f5": f5_items, "trimmed": rendered.get("trimmed"),
        "withheld": rendered.get("withheld"), "tokens":
        rendered.get("tokens")}, snapshot=snapshot, facts_hash=fh, wake=wake,
        block_hashes=rendered["hashes"], card=False, card_extra=card_extra,
        remember=remember, fields={"next_wake_due": due}, at=now)
    if quiet:
        line = _reading(trade, ctx, ctx.get("tf") or "4h")
        journal.append(orc, "reading", line, wake=wake, at=now,
                       fields={"latest_note": line[:140],
                               "latest_note_at": now})
    return wake


# ── the census's reasons (merged by the next tick) ───────────────────────

def _living():
    from bot_program.orcs.models import Orc
    return list(Orc.objects.exclude(state=STATE_DEAD)
                .filter(root_trade__status__in=OPEN_STATUSES)
                .select_related("root_trade", "user"))


def _queue(orc, new, now) -> bool:
    """Add census reasons to the Orc's pending wake, once per key."""
    from bot_program.orcs import journal
    seen = orc.seen or {}
    keys = set(seen.get("wake_keys") or [])
    pend = dict(seen.get("wake_pending") or {})
    have = {r.get("key") for r in pend.get("reasons") or []}
    add = [r for r in new if r["key"] not in keys and r["key"] not in have]
    if not add:
        return False
    pend["reasons"] = list(pend.get("reasons") or []) + add
    pend.setdefault("since", now.isoformat())
    journal.remember(orc, wake_pending=pend)
    return True


def census_clock(now) -> int:
    """W5: T-180, T-60 and T+15 around a high-impact print on the row's
    currencies; a stock's or ETF's own earnings at T-24h. Urgent."""
    from market_data.models import EconomicEvent

    from bot_program.orcs.fence import sanitize
    from bot_program.orcs.situation import currencies
    from bot_program.position_care import EVENT_IMPACT, EVENT_SOURCES
    orcs = _living()
    if not orcs:
        return 0
    events = list(EconomicEvent.objects.filter(
        datetime__gte=now - timedelta(minutes=W5_LATE_MIN),
        datetime__lte=now + timedelta(hours=W5_EARNINGS_H))
        .values("id", "datetime", "title", "currency_affected", "impact",
                "source"))
    n = 0
    for orc in orcs:
        row = orc.root_trade
        ccys = currencies(row)
        sym = str(row.symbol or "").upper()
        new = []
        for ev in events:
            title = str(ev["title"] or "")
            mins = (ev["datetime"] - now).total_seconds() / 60.0
            earnings = "earnings" in title.lower()
            if earnings:
                if str(row.asset_class) not in ("stock", "etf") or \
                        sym not in title.upper():
                    continue
                if 0 < mins <= W5_EARNINGS_H * 60:
                    new.append(_reason("W5", f"W5:{ev['id']}:-1440",
                                       f"{sanitize(title, 80)} in "
                                       f"{mins / 60:.0f} h", True))
                continue
            if ev["source"] not in EVENT_SOURCES or \
                    str(ev["impact"]).lower() != EVENT_IMPACT or \
                    str(ev["currency_affected"]).upper() not in ccys:
                continue
            t = sanitize(title, 80)
            for off in W5_OFFSETS_MIN:
                if off < 0 and 0 < mins <= -off:
                    new.append(_reason("W5", f"W5:{ev['id']}:{off}",
                                       f"{t} in {mins:.0f} min", True))
                elif off > 0 and -W5_LATE_MIN <= mins <= -off:
                    new.append(_reason("W5", f"W5:{ev['id']}:+{off}",
                                       f"{t} printed {-mins:.0f} min ago",
                                       True))
        # one reason per event: the nearest offset speaks, the farther ones
        # are spent with it
        by_event = {}
        for r in new:
            ev_key = r["key"].rsplit(":", 1)[0]
            by_event.setdefault(ev_key, []).append(r)
        chosen = []
        for rs in by_event.values():
            chosen.append(rs[-1] if len(rs) > 1 else rs[0])
            spent = [r["key"] for r in rs[:-1]] if len(rs) > 1 else []
            if spent:
                from bot_program.orcs import journal
                keys = list((orc.seen or {}).get("wake_keys") or [])
                journal.remember(orc, wake_keys=(keys + spent)
                                 [-WAKE_KEYS_KEPT:])
        if chosen and _queue(orc, chosen, now):
            n += 1
    return n


def census_book(now) -> int:
    """W7: the daily-loss mode changed, open risk crossed 80% of its
    limit, the measured posture's level changed. Recorded silently the
    first time; a reason on each change."""
    from bot_program.orcs import journal, sources
    orcs = _living()
    if not orcs:
        return 0
    cache = {}
    p = sources.posture(now)
    level = (p["value"] or {}).get("level") if not p.get("dash") else None
    n = 0
    for orc in orcs:
        real = _world_real(orc.root_trade)
        b = sources.book(orc.user, real=real, cache=cache)
        if b.get("dash"):
            state = {"mode": None, "hot": None, "posture": level}
        else:
            share = b["value"].get("open_risk_share")
            state = {"mode": b["value"].get("daily_loss_mode"),
                     "hot": (share is not None and share >=
                             W7_OPEN_RISK_SHARE),
                     "posture": level, "share": share}
        was = (orc.seen or {}).get("book_state")
        compare = {k: state.get(k) for k in ("mode", "hot", "posture")}
        if was is None:
            journal.remember(orc, book_state=compare)
            continue
        if compare == was:
            continue
        new = []
        stamp = f"{now:%Y%m%d%H%M}"
        if state["mode"] and state["mode"] != was.get("mode"):
            new.append(_reason("W7", f"W7:mode:{state['mode']}:{stamp}",
                               f"daily-loss mode {state['mode']}", False))
        if state.get("hot") and not was.get("hot"):
            new.append(_reason("W7", f"W7:risk:{stamp}",
                               f"open risk at {state['share']:.0%} of its "
                               f"limit", False))
        if level and level != was.get("posture"):
            new.append(_reason("W7", f"W7:posture:{level}:{stamp}",
                               f"posture {level}", False))
        journal.remember(orc, book_state=compare)
        if new and _queue(orc, new, now):
            n += 1
    return n


def census_pending(now) -> int:
    """W10: a close pending at the venue on any leg. Urgent, once."""
    from bot_program.orcs.models import OrcLeg
    legs = list(OrcLeg.objects.filter(trade__status="CLOSE_PENDING")
                .exclude(orc__state=STATE_DEAD)
                .select_related("orc"))
    n = 0
    for leg in legs:
        if _queue(leg.orc, [_reason("W10", f"W10:pending:{leg.trade_id}",
                                    "a close pending at the venue", True)],
                  now):
            n += 1
    return n
