"""WAKE DETECTION IN O1 (spec §1.3, §7.5, §5.2a): the tick DETECTS and
RECORDS; nothing is dispatched, no model is asked.

In the tick, after the care, the facts, the predicates, the arms and the
drums (bot_program/orcs/observe.py), `detect` reads what changed between
the Orc's memory before this tick (`orc._seen_before`) and after it, the
care's state on the row and the frames the tick already read, and finds:

  W1   the first detect after the birth                          urgent
  W2   a final venue bar of the decision timeframe (a Mercenary's 1h)
  W3   the closing-side mark within 0.1 x ATR(1h) of an invalidation
       level, again only W3_ONCE_H after that level's last W3   urgent
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
around a print, W7 the book, W10 a close pending). Each reason counts once
per key: the one-shot reasons read from a STATE rather than a transition
(W4's thresholds and give-back, W6's close, W10) are remembered in
`seen["wake_once"]`, never trimmed, so they never fire twice however long
the position lives; the time-keyed ones (W2, W3, W5, W6's stop steps, W7,
W11) in the last WAKE_KEYS_KEPT of `seen["wake_keys"]`. An urgent reason
records at once; the others wait for MIN_WAKE_SPACING_MIN after the last
recorded wake. The tick and the census load the Orc in separate processes:
the wake memory is merged under the Orc's lock (journal.merge_seen,
add_keys, add_reasons, consume_reasons), never written from a copy in
hand.

RECORDING IS SPLIT (2026-10-23). The tick writes the OrcWake with its
reasons and the tick's cheap facts (its moment, its price, the care's
state, the predicates) and the memory that decided it: a handful of
queries, never the dossier. The slow queue (tasks.orc_render_wakes,
`render_queued`) then renders each recorded wake AS OF its moment: its
complexity score, band and the day's class (complexity.py, weather.py),
its dossier stored block by block (dossier.py), then the OrcWake's score
and hashes, its status (`skipped`, "no model before O2"; or `quiet` under
F6 with a code `reading` and Orc.latest_note), a journal `wake` entry kept
off the card's lines, and the card's `intellect` and `integrity`.
Detection, spacing and the proxy for the last answered facts hash live in
Orc.seen, never in O2's columns (last_wake_at, last_facts_hash).

`detect` never raises; a recorded wake is written in a savepoint, so a
failure leaves the tick and the Orc as they were, and a quiet tick costs
no query at all. A render that fails marks its wake `failed` and never
stops the next.

# O2: a recorded wake is dispatched (status `pending`, the router, the
# reserve, the budget) instead of `skipped`; drum deliveries add W12.
"""
import hashlib
import json
import logging
import math
import re
from datetime import timedelta

from bot_program.orcs.constants import (BAND_HOLD_AFTER_URGENT_MIN,
                                        MIN_WAKE_SPACING_MIN, STATE_DEAD,
                                        STATUS_WORDS, VENUE_LIVE,
                                        VENUE_PAPER, W3_NEAR_ATR1H,
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
#: The reasons read from a STATE (not a transition): remembered for life in
#: seen["wake_once"], so they fire once however long the position lives.
ONCE_CODES = ("W4", "W10")
ONCE_KEYS = ("W6:closed",)
#: OrcWake.components["render"]: the tick queued it; the slow queue
#: rendered it; or its render failed (it is not retried).
RENDER_QUEUED, RENDER_DONE, RENDER_FAILED = "queued", "done", "failed"
#: The recorded wakes one render pass takes, oldest first.
RENDER_BATCH = 40
#: §7.5.1's "the symbol's regime flipped within 6 bars": the decision
#: frame's last 6 final bars against the one before them.
REGIME_FLIP_BARS = 6
#: The fewest final bars the regime labels are read on (ADX's warm-up).
REGIME_MIN_BARS = 40
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


def _reason(code, key, t, urgent, **extra) -> dict:
    out = {"code": code, "key": str(key)[:120], "t": str(t),
           "urgent": bool(urgent)}
    out.update(extra)
    return out


def _one_shot(reason) -> bool:
    return (reason.get("code") in ONCE_CODES
            or reason.get("key") in ONCE_KEYS)


def _done_keys(seen) -> set:
    """Every reason key a recorded wake carried: the one-shot memory and
    the rolling one."""
    seen = seen if isinstance(seen, dict) else {}
    return set(seen.get("wake_keys") or []) | set(seen.get("wake_once")
                                                  or [])


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


def _closing_mark(bot, trade, price, now):
    """§1.3 W3's mark: the CLOSING side, from what the tick holds (no
    query): a real row's fresh venue stamp on its closing side
    (venue_mark.closing_side); else the tick's own ticker, its bid for a
    long and its ask for a short; else the tick's price."""
    side = str(getattr(trade, "side", "") or "").upper()
    try:
        from bot_program import venue_mark
        vm = venue_mark.fresh(trade, now=now)
        if vm is not None:
            return _f(venue_mark.closing_side(trade, vm))
    except Exception:  # noqa: BLE001 — an unread stamp is the ticker's
        pass
    ticks = getattr(bot, "_last_ticks", None) if bot is not None else None
    tick = ticks.get(trade.symbol) if isinstance(ticks, dict) else None
    if isinstance(tick, dict):
        side_px = _f(tick.get("bid" if side == "BUY" else "ask"))
        if side_px:
            return side_px
    return _f(price)


def _w3(orc, trade, bot, price, now, cache, seen, add):
    """The closing-side mark near an invalidation level: urgent, and again
    for that level only W3_ONCE_H after its last recorded W3 (never a
    fixed clock bucket: 11:59 and 12:00 are one W3)."""
    from bot_program.orcs import bars
    from bot_program.orcs.facts import px
    levels = [p for p in (orc.thesis or {}).get("invalidation") or []
              if isinstance(p, dict) and p.get("kind") == "close_beyond"
              and _f(p.get("level")) is not None]
    if not levels:
        return
    m = _closing_mark(bot, trade, price, now)
    if m is None:
        return
    f = bars.frame(trade.symbol, "1h", asset_class=trade.asset_class,
                   now=now, cache=cache)
    atr = f.atr if f is not None else None
    if not atr:
        return
    last_at = seen.get("w3_at") if isinstance(seen.get("w3_at"), dict) \
        else {}
    for p in levels:
        lid = str(p.get("level_id") or "the level")
        last = _parse(last_at.get(lid))
        if last is not None and now - last < timedelta(hours=W3_ONCE_H):
            continue
        if abs(m - _f(p["level"])) <= W3_NEAR_ATR1H * atr:
            add("W3", f"W3:{lid}:{now:%Y%m%d%H%M}",
                f"the mark near {lid} ({px(trade, p['level'])})", True,
                level=lid)


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
    keys = _done_keys(seen)
    pending = dict(seen.get("wake_pending") or {})
    reasons = [r for r in pending.get("reasons") or []
               if isinstance(r, dict) and r.get("key") not in keys]
    have = {r["key"] for r in reasons}
    fresh = []

    def add(code, key, t, urgent, **extra):
        key = str(key)[:120]
        if key in keys or key in have:
            return
        have.add(key)
        fresh.append(_reason(code, key, t, urgent, **extra))

    if not seen.get("w1"):
        add("W1", "W1", "birth", True)
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    w2_bar = _w2(orc, trade, now, cache, seen, add)
    _w3(orc, trade, bot, price, now, cache, seen, add)
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
            _pend(orc, fresh, now)
        return None
    # the record runs in a savepoint: a failure inside it leaves no half
    # wake; a quiet tick opens none (no query at all)
    from django.db import transaction
    with transaction.atomic():
        return record(orc, trade, reasons, now=now, bot=bot, price=price,
                      cache=cache, w2_bar=w2_bar)


def _pend(orc, new, now) -> bool:
    """Add reasons to the Orc's pending wake under its lock: once per key,
    none a recorded wake already carried (the LOCKED memory's keys, so a
    tick that recorded meanwhile is seen)."""
    from bot_program.orcs import journal

    def fn(seen):
        done = _done_keys(seen)
        pend = seen.get("wake_pending") if isinstance(
            seen.get("wake_pending"), dict) else {}
        have = {r.get("key") for r in pend.get("reasons") or []
                if isinstance(r, dict)}
        add = [r for r in new if r["key"] not in done
               and r["key"] not in have]
        if not add:
            return False
        seen["wake_pending"] = journal.add_reasons(
            add, since=now.isoformat())(pend)
        return True
    return bool(journal.merge_seen(orc, fn))


# ── recording ────────────────────────────────────────────────────────────

def _world(trade) -> str:
    """The row's money world (birth.world): "live", "demo" or "paper". The
    weather, the stakes and the floors read `real` as world "live"; the
    book reads the world itself (sources.book). An unreadable world falls
    back to the row's paper flag: paper=True is paper, anything else
    live."""
    try:
        from bot_program.orcs.birth import world
        return world(trade)
    except Exception:  # noqa: BLE001
        return VENUE_PAPER if getattr(trade, "paper", True) else VENUE_LIVE


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
    # §7.5.1 regime: this row's own flip (the class's terms come from the
    # day's weather; _components keeps the higher of the two)
    inputs["regime"] = {"symbol_flip": bool(_symbol_flip(ctx.get("frame"),
                                                         now))}
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
    # SIGNED: the closing-side mark's distance to the stop on the side it
    # protects, so a mark already through the stop (a gap, a venue stop not
    # filled yet) reads <= 0 and scores 100, never "far away"
    d = 1.0 if str(trade.side).upper() == "BUY" else -1.0
    inputs["stop_atr"] = (d * (m - eff) / atr if eff is not None and
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
    book = sources.book(orc.user, world=ctx.get("world") or _world(trade),
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


def _symbol_flip(frame, now):
    """Did this row's own regime label (backtester/proving/simulate.regimes:
    trend or range, "+hi_vol") change within the last REGIME_FLIP_BARS
    final bars of its decision frame? None when it cannot be read."""
    try:
        from backtester.proving.simulate import regimes

        from bot_program.orcs import bars
        df = bars.final_df(frame, now) if frame is not None else None
        if df is None or len(df) < REGIME_MIN_BARS:
            return None
        labels = regimes(df)[-(REGIME_FLIP_BARS + 1):]
        return len(set(labels)) > 1
    except Exception:  # noqa: BLE001 — unread is no flip, never a raise
        return None


def _components(inputs):
    """The wake's vector: the class's news and stress terms from the day's
    weather; the regime term the HIGHER of the class's and this row's own
    (its symbol's flip, §7.5.1)."""
    from bot_program.orcs import complexity
    comps = complexity.components(inputs)
    for key in ("regime", "news", "stress"):
        given = inputs.get(f"_market_{key}")
        if not (isinstance(given, dict) and "s" in given):
            continue
        if key == "regime" and float(comps[key].get("s") or 0) > float(
                given.get("s") or 0):
            continue
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
            "predicates": (dict(ctx["tick_predicates"])
                           if isinstance(ctx.get("tick_predicates"), dict)
                           else {k: (v or {}).get("state") for k, v in (
                               (orc.seen or {}).get("predicates")
                               or {}).items()})}


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
    """Record one detected wake IN THE TICK: the OrcWake with its reasons
    and the tick's cheap facts (its moment, its price, the care's state,
    the predicates' states), queued for its render; the memory that
    decided it, merged under the Orc's lock; the next metronome. A handful
    of queries, never the dossier (render_queued, on the slow queue).
    Returns the OrcWake."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcWake
    codes = {r.get("code") for r in reasons}
    urgent = any(r.get("urgent") for r in reasons)
    seen = orc.seen or {}
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    preds = {str(k): (v or {}).get("state")
             for k, v in (seen.get("predicates") or {}).items()
             if isinstance(v, dict)}
    wake = OrcWake.objects.create(
        orc=orc, reasons=reasons,
        dedupe_key=f"orc{orc.pk}:{now:%Y%m%d%H%M%S}:{reasons[0]['key']}"
        [:120],
        priority=1.0 if urgent else 0.0, kind=_kind_of(reasons),
        status=WAKE_STATUS_SKIPPED, skipped_reason=WAKE_SKIPPED_REASON,
        components={"render": RENDER_QUEUED, "as_of": now.isoformat(),
                    "price": (str(price) if _f(price) is not None
                              else None),
                    "care": dict(care), "predicates": preds,
                    # PS8's "since the last wake": the one BEFORE this
                    "prev_recorded": seen.get("last_recorded")})
    w11_at = now.isoformat() if ("W11" in codes or not seen.get("w1")) \
        else seen.get("w11_at") or now.isoformat()
    due = (_parse(w11_at) or now) + timedelta(hours=W11_METRONOME_H)
    remember = {
        "w1": True,
        "wake_keys": journal.add_keys(WAKE_KEYS_KEPT, [
            r["key"] for r in reasons if not _one_shot(r)]),
        "wake_once": journal.add_keys(None, [
            r["key"] for r in reasons if _one_shot(r)]),
        "wake_pending": journal.consume_reasons([r["key"] for r in reasons]),
        "last_recorded": now.isoformat(), "w11_at": w11_at}
    if urgent:
        remember["band_hold_until"] = (now + timedelta(
            minutes=BAND_HOLD_AFTER_URGENT_MIN)).isoformat()
    if w2_bar:
        remember["w2_bar"] = w2_bar
    w3 = {str(r["level"]): now.isoformat() for r in reasons
          if r.get("code") == "W3" and r.get("level")}
    if w3:
        remember["w3_at"] = lambda cur, w3=w3: {
            **(cur if isinstance(cur, dict) else {}), **w3}
    journal.remember(orc, fields={"next_wake_due": due},
                     card_extra={"next_wake_due": due.isoformat()},
                     **remember)
    return wake


def render_wake(wake):
    """Score, weather and dossier of one recorded wake, AS OF its moment
    (components["as_of"]), with the care's state and the price the tick
    saw. Writes the OrcWake's score, band, day class, components, block
    hashes and status, the journal's `wake` entry (off the card's lines),
    the card's intellect and integrity, and a quiet wake's reading.
    Raises on a failure (render_queued fences it). Returns the wake."""
    from bot_program.orcs import complexity, dossier, journal, weather
    orc = wake.orc
    trade = orc.root_trade
    tick = dict(wake.components or {})
    now = _parse(tick.get("as_of")) or wake.created_at
    price = tick.get("price")
    if isinstance(tick.get("care"), dict):
        meta = dict(trade.metadata) if isinstance(trade.metadata,
                                                  dict) else {}
        meta["care"] = tick["care"]
        trade.metadata = meta        # in memory only: the care the tick saw
    reasons = [r for r in wake.reasons or [] if isinstance(r, dict)]
    world = _world(trade)
    real = world == VENUE_LIVE
    orc._orc_results = None
    ctx = dossier.context_for(orc, trade, price=price, now=now, cache={},
                              reasons=reasons, bot=None)
    ctx["real"] = real
    ctx["world"] = world
    if isinstance(tick.get("predicates"), dict):
        ctx["tick_predicates"] = tick["predicates"]
    ctx["prev_recorded"] = tick.get("prev_recorded")
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
    kind = wake.kind or _kind_of(reasons)
    codes = {r.get("code") for r in reasons}
    floor = complexity.floors(kind=kind, real=real, binding_on_table=False,
                              day_class=day.day_class, birth="W1" in codes)
    seen = orc.seen or {}
    band = complexity.band(sc, prev_band=seen.get("band"),
                           hold_until=_parse(seen.get("band_hold_until")),
                           now=now, floor=floor)
    f5_on, f5_items = complexity.f5(ctx.get("integrity"))
    snapshot = _snapshot(orc, trade, ctx)
    fh = facts_hash(snapshot)
    quiet = complexity.f6(reasons, fh, seen.get("answered_hash"))
    status = WAKE_STATUS_QUIET if quiet else WAKE_STATUS_SKIPPED
    words = reasons_words(reasons)
    wake.score, wake.band, wake.day_class = sc, band, day.day_class
    wake.status = status
    wake.skipped_reason = "" if quiet else WAKE_SKIPPED_REASON
    wake.components = {**comps, "stakes": st, "floor": floor,
                       "f5": f5_items, "f6": quiet,
                       "tokens": rendered.get("tokens"),
                       "trimmed": rendered.get("trimmed"),
                       "render": RENDER_DONE, "as_of": tick.get("as_of"),
                       "price": price}
    wake.block_hashes = rendered["hashes"]
    wake.finished_at = now
    wake.save(update_fields=["score", "band", "day_class", "status",
                             "skipped_reason", "components", "block_hashes",
                             "finished_at"])
    remember = {"band": band}
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
                      "t": integrity_words(ctx.get("integrity"))}}
    headline = (f"Wake detected: {words}. Complexity {sc:.0f} ({band}); "
                f"the day is {day.day_class}. Recorded only: no model is "
                f"asked yet.")
    journal.append(orc, "wake", headline, body={
        "wake": wake.pk, "reasons": [r.get("t") for r in reasons],
        "score": sc, "band": band, "day_class": day.day_class,
        "status": status, "f5": f5_items, "trimmed": rendered.get("trimmed"),
        "withheld": rendered.get("withheld"), "tokens":
        rendered.get("tokens")}, snapshot=snapshot, facts_hash=fh, wake=wake,
        block_hashes=rendered["hashes"], card=False, card_extra=card_extra,
        remember=remember, at=now)
    if quiet:
        line = _reading(trade, ctx, ctx.get("tf") or "4h")
        journal.append(orc, "reading", line, wake=wake, at=now,
                       fields={"latest_note": line[:140],
                               "latest_note_at": now})
    return wake


def render_queued(*, limit=RENDER_BATCH) -> tuple:
    """(rendered, failed): the recorded wakes still waiting for their
    dossier, oldest first, each in its own savepoint. One that fails is
    marked `failed` with its error's kind (never retried, never stopping
    the next). Never raises."""
    from django.db import transaction

    from bot_program.orcs.models import OrcWake
    try:
        ids = list(OrcWake.objects
                   .filter(components__render=RENDER_QUEUED)
                   .order_by("id").values_list("id", flat=True)[:int(limit)])
    except Exception as e:  # noqa: BLE001
        logger.warning("[orcs] the queued wakes could not be listed: %s", e)
        return 0, 0
    done = failed = 0
    for wid in ids:
        try:
            with transaction.atomic():
                w = (OrcWake.objects
                     .select_related("orc", "orc__root_trade", "orc__user")
                     .get(pk=wid))
                if (w.components or {}).get("render") != RENDER_QUEUED:
                    continue
                render_wake(w)
            done += 1
        except Exception as e:  # noqa: BLE001 — one wake never stops one
            failed += 1
            logger.warning("[orcs] wake %s not rendered: %s", wid, e)
            try:
                w = OrcWake.objects.filter(pk=wid).first()
                if w is not None:
                    w.components = {**(w.components or {}),
                                    "render": RENDER_FAILED,
                                    "render_error": type(e).__name__}
                    w.save(update_fields=["components"])
            except Exception:  # noqa: BLE001
                pass
    return done, failed


# ── the census's reasons (merged by the next tick) ───────────────────────

def _living():
    from bot_program.orcs.models import Orc
    return list(Orc.objects.exclude(state=STATE_DEAD)
                .filter(root_trade__status__in=OPEN_STATUSES)
                .select_related("root_trade", "user"))


def _queue(orc, new, now) -> bool:
    """Add census reasons to the Orc's pending wake, once per key, merged
    under its lock (_pend). The copy in hand only spares the lock when it
    already holds every key (a key it holds was recorded or queued)."""
    seen = orc.seen or {}
    keys = _done_keys(seen)
    pend = seen.get("wake_pending") if isinstance(seen.get("wake_pending"),
                                                  dict) else {}
    have = {r.get("key") for r in pend.get("reasons") or []
            if isinstance(r, dict)}
    if not [r for r in new if r["key"] not in keys and r["key"] not in have]:
        return False
    return _pend(orc, new, now)


def _earnings_of(sym, ev) -> bool:
    """Is this earnings row the symbol's own? The care's rule
    (position_care.event_for): the writer's ticker in currency_affected
    (scraping/scrapers/earnings_calendar.py), or the ticker as a WORD of
    the title, never a substring ("MS" is not "MSFT Earnings")."""
    sym = str(sym or "").upper()
    if not sym:
        return False
    if str(ev.get("currency_affected") or "").upper() == sym:
        return True
    title = str(ev.get("title") or "").upper()
    return re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])",
                     title) is not None


def census_clock(now) -> int:
    """W5: T-180, T-60 and T+15 around a high-impact print on the row's
    currencies; a stock's or ETF's own earnings at T-24h. Urgent. The
    reason's words are code only (the currency, the calendar row's id and
    the minutes): a calendar title is third-party text and travels only
    fenced (sources.calendar), never in a reason, a headline or the
    tail."""
    from market_data.models import EconomicEvent

    from bot_program.orcs import journal
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
                        not _earnings_of(sym, ev):
                    continue
                if 0 < mins <= W5_EARNINGS_H * 60:
                    new.append(_reason("W5", f"W5:{ev['id']}:-1440",
                                       f"{sym} earnings (C{ev['id']}) in "
                                       f"{mins / 60:.0f} h", True))
                continue
            ccy = str(ev["currency_affected"] or "").upper()
            if ev["source"] not in EVENT_SOURCES or \
                    str(ev["impact"]).lower() != EVENT_IMPACT or \
                    ccy not in ccys:
                continue
            what = f"a high-impact {ccy} print (C{ev['id']})"
            for off in W5_OFFSETS_MIN:
                if off < 0 and 0 < mins <= -off:
                    new.append(_reason("W5", f"W5:{ev['id']}:{off}",
                                       f"{what} in {mins:.0f} min", True))
                elif off > 0 and -W5_LATE_MIN <= mins <= -off:
                    new.append(_reason("W5", f"W5:{ev['id']}:+{off}",
                                       f"{what} printed {-mins:.0f} min ago",
                                       True))
        # one reason per event: the nearest offset speaks, the farther ones
        # are spent with it (once each: add_keys never appends a key twice)
        by_event = {}
        for r in new:
            ev_key = r["key"].rsplit(":", 1)[0]
            by_event.setdefault(ev_key, []).append(r)
        chosen, spent = [], []
        for rs in by_event.values():
            chosen.append(rs[-1])
            spent.extend(r["key"] for r in rs[:-1])
        done = _done_keys(orc.seen)
        spent = [k for k in spent if k not in done]
        if spent:
            journal.remember(orc, wake_keys=journal.add_keys(
                WAKE_KEYS_KEPT, spent))
        if chosen and _queue(orc, chosen, now):
            n += 1
    return n


def census_book(now) -> int:
    """W7: the daily-loss mode changed, open risk crossed 80% of its
    limit, the measured posture's level changed. Each term is compared
    only when it is READABLE now and was readable before: the first
    reading is recorded silently, and an unreadable book or a stale
    posture keeps the last reading (it is no change, and the next readable
    one is compared with what was last read)."""
    from bot_program.orcs import journal, sources
    orcs = _living()
    if not orcs:
        return 0
    cache = {}
    p = sources.posture(now)
    level = (p["value"] or {}).get("level") if not p.get("dash") else None
    n = 0
    for orc in orcs:
        # the Orc's own money world: a demo Orc has no book of its own
        # (a dash: no W7), a real one counts world-live rows only
        b = sources.book(orc.user, world=_world(orc.root_trade),
                         cache=cache)
        if b.get("dash"):
            cur = {"mode": None, "hot": None}
            share = None
        else:
            share = b["value"].get("open_risk_share")
            cur = {"mode": b["value"].get("daily_loss_mode"),
                   "hot": (None if share is None
                           else share >= W7_OPEN_RISK_SHARE)}
        cur["posture"] = level
        was = (orc.seen or {}).get("book_state")
        was = was if isinstance(was, dict) else None
        state = {k: (cur[k] if cur[k] is not None else (was or {}).get(k))
                 for k in ("mode", "hot", "posture")}
        if was is None:
            if any(v is not None for v in state.values()):
                journal.remember(orc, book_state=state)
            continue
        new = []
        stamp = f"{now:%Y%m%d%H%M}"
        if cur["mode"] is not None and was.get("mode") is not None and \
                cur["mode"] != was.get("mode"):
            new.append(_reason("W7", f"W7:mode:{cur['mode']}:{stamp}",
                               f"daily-loss mode {cur['mode']}", False))
        if cur["hot"] is True and was.get("hot") is False:
            new.append(_reason("W7", f"W7:risk:{stamp}",
                               f"open risk at {share:.0%} of its limit",
                               False))
        if cur["posture"] is not None and was.get("posture") is not None \
                and cur["posture"] != was.get("posture"):
            new.append(_reason("W7", f"W7:posture:{level}:{stamp}",
                               f"posture {level}", False))
        if state != was:
            journal.remember(orc, book_state=state)
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
