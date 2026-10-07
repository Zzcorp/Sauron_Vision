"""THE VENUE'S OWN WORD BEFORE A MISS IS BOOKED, AND THE PRICE OF A CLOSE
NOBODY SAW (2026-10-07, PR50).

NVDA #131: care moved the eToro stop to break-even (238.03); eToro filled it
in its extended session. At 11:07:59 the tick saw 237.9 cross it and no
position in the list; the 11:15 reconcile booked 238.16, "priced from the
last mark". AMZN #140 (braked): stop 254.18 filled before 11:45, booked at
the 11:45 rate 254.48 (-0.91R against -1.00R). PG #138 (short): booked at the
01:15 rate, 0.75R short of its stop. XAGUSD #134: the 12:30 rate was already
beyond the stop.

THE GUARD. A miss in eToro's /portfolio is booked CLOSED only after eToro's
own order read (position_state by the row's OPEN order id) says "closed".
"open": nothing booked, staff told once per episode. No answer: nothing
booked, the ask counted (MISS_KEY); booked as before only once
UNPROVEN_WAIT_S and UNPROVEN_MIN_ASKS have both passed in one unbroken run
of asks, and the row says so. No order id, a non-eToro client, a MagicMock:
exactly as before.

THE PRICE. When the venue said closed, no close of ours was sent, answered,
filled or left in doubt, and the row's stop (or target) rests at the venue,
the exit is booked AT that level when the price since eToro last showed the
position open reached it (the tick's crossing stamp, care's last mark, the
platform's 1h bars), or the mark stands beyond it, or (an estimate, said
so) the mark is within NEAREST_STOP_MAX_R of the stop or
NEAREST_TARGET_MAX_R of the target. Otherwise the mark, as before.

THE WINDOW. Facts only: when eToro last showed it open (a listing read, an
"open" answer) and when a list read first did not (the tick's, the first
unanswered miss, the booking). Written only when the venue said closed.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from datetime import timezone as dt_timezone   # django.utils.timezone.utc
                                               # does not exist on Django 5
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

LISTED_AT_KEY = "venue_listed_at"          # the book read that listed its id
SAID_OPEN_AT_KEY = "venue_said_open_at"    # last "open" answer on a miss
MISSING_AT_KEY = "venue_missing_at"        # first tick list without it
MISS_KEY = "venue_miss"                    # {"since", "asks", "last_at"}
UNPROVEN_KEY = "venue_unproven_close"      # words, on a row booked unproven
OPEN_ALERTED_KEY = "venue_listing_missed_alerted_at"
CROSSED_KEY = "venue_level_crossed"        # {"level","price","mark","at"}
PRICED_AT_KEY = "exit_priced_at"           # the basis estimate() returned
CLOSED_BETWEEN_KEY = "venue_closed_between"  # [lo_iso, hi_iso]

UNPROVEN_WAIT_S = 3300
UNPROVEN_MIN_ASKS = 4
MISS_RESTART_AFTER_S = 2100
NEAREST_STOP_MAX_R = 1.0
NEAREST_TARGET_MAX_R = 0.5
BARS_TIMEFRAME = "1h"
BARS_START_SLACK_S = 300
NO_STOP_SENTINEL = 0.0001      # = morgul.NO_STOP_SENTINEL


def _f(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _when(raw):
    if not raw:
        return None
    try:
        at = parse_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    return None if at is None or timezone.is_naive(at) else at


def _meta(trade) -> dict:
    m = getattr(trade, "metadata", None)
    return m if isinstance(m, dict) else {}


def _same(a, b) -> bool:
    a, b = _f(a), _f(b)
    return a is not None and b is not None and round(a, 8) == round(b, 8)


def _is_etoro_row(trade) -> bool:
    """A real eToro row that carries its OPEN order id: the only kind the
    venue's word can be asked about (can_ask), so the only kind a crossing
    stamp can ever serve as evidence for. A row without the id gets no new
    metadata (2026-10-07)."""
    return (not getattr(trade, "paper", True)
            and str(_meta(trade).get("broker") or "") == "etoro"
            and bool(str(getattr(trade, "broker_order_id", "") or "").strip()))


def merge_meta(trade, updates=None, *, pop=()) -> dict:
    """The _save_care / venue_mark.stamp idiom: fresh read under a row lock,
    merge, save, and put the merged dict back on the in-memory row."""
    from django.db import transaction
    from bot_program.asset_models import AssetBotTrade
    with transaction.atomic():
        row = AssetBotTrade.objects.select_for_update().get(pk=trade.pk)
        meta = dict(row.metadata or {})
        for key in pop:
            meta.pop(key, None)
        meta.update(updates or {})
        row.metadata = meta
        row.save(update_fields=["metadata"])
    trade.metadata = meta
    return meta


# ── A. the guard ────────────────────────────────────────────────────────

def can_ask(trade, client) -> bool:
    """eToro by adapter_key (class name; a MagicMock answers ""), a
    position_state, a real row, and the OPEN order id."""
    from bot_program.engine.capabilities import adapter_key
    if getattr(trade, "paper", True) or adapter_key(client) != "etoro":
        return False
    if not callable(getattr(client, "position_state", None)):
        return False
    return bool(str(getattr(trade, "broker_order_id", "") or "").strip())


def note_listed(trade, client, *, at=None) -> bool:
    """The reconcile read listed this row's own position id at `at`: when
    eToro last showed it open; any miss run and its alert end. Never raises."""
    try:
        if not can_ask(trade, client):
            return False
        merge_meta(trade, {LISTED_AT_KEY: (at or timezone.now()).isoformat()},
                   pop=(MISS_KEY, MISSING_AT_KEY, OPEN_ALERTED_KEY))
        return True
    except Exception as e:  # noqa: BLE001
        logger.info("[venue exit] #%s listing not stamped: %s",
                    getattr(trade, "id", "?"), e)
        return False


def said_open(trade, client, *, where: str, now=None) -> None:
    """The list missed a position eToro's order read calls OPEN: nothing
    booked, the miss run ends, staff told once per episode (no money
    figure). Never raises."""
    now = now or timezone.now()
    try:
        meta = merge_meta(trade, {SAID_OPEN_AT_KEY: now.isoformat()},
                          pop=(MISS_KEY,))
    except Exception as e:  # noqa: BLE001
        logger.warning("[venue exit] #%s: open answer not stamped: %s",
                       trade.id, e)
        meta = _meta(trade)
    logger.error("%s: #%s (%s) NOT booked — eToro's position list does not "
                 "show it and its own order read (order %s) says the "
                 "position is OPEN", where, trade.id, trade.symbol,
                 trade.broker_order_id)
    if meta.get(OPEN_ALERTED_KEY):
        return
    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title=f"⚠ {trade.symbol} #{trade.id}: eToro's list missed a "
                  f"live position",
            body=(f"eToro's position list does not show trade #{trade.id} "
                  f"({trade.symbol}), but eToro's own order read says the "
                  f"position is still OPEN. Nothing was booked: the row "
                  f"stays open and the platform asks again at every pass. "
                  f"Check the position in the eToro app."),
            url="/positions/")
        merge_meta(trade, {OPEN_ALERTED_KEY: now.isoformat()})
    except Exception as e:  # noqa: BLE001
        logger.warning("[venue exit] #%s: the alert could not be sent: %s",
                       trade.id, e)


def last_seen_open(trade):
    """The latest VENUE READING that showed the position open: a listing of
    its id, or an "open" answer. A stop move is NOT one (a 202 is accepted,
    not applied; a PATCH on a closed id is unmeasured)."""
    meta = _meta(trade)
    times = [t for t in (_when(meta.get(LISTED_AT_KEY)),
                         _when(meta.get(SAID_OPEN_AT_KEY))) if t is not None]
    return max(times) if times else None


def after_no_answer(trade, *, now=None) -> tuple:
    """Count one unanswered ask under the row lock. A run restarts when its
    last ask is older than MISS_RESTART_AFTER_S or the venue showed the
    position open since it began. ("wait", why) | ("unproven", note)."""
    from django.db import transaction
    from bot_program.asset_models import AssetBotTrade
    now = now or timezone.now()
    with transaction.atomic():
        row = AssetBotTrade.objects.select_for_update().get(pk=trade.pk)
        meta = dict(row.metadata or {})
        miss = meta.get(MISS_KEY) if isinstance(meta.get(MISS_KEY), dict) else {}
        since, last = _when(miss.get("since")), _when(miss.get("last_at"))
        seen = last_seen_open(row)
        try:
            asks = int(miss.get("asks") or 0)
        except (TypeError, ValueError):
            asks = 0
        if (since is None or last is None
                or (now - last).total_seconds() > MISS_RESTART_AFTER_S
                or (seen is not None and seen >= since)):
            since, asks = now, 0
        asks += 1
        meta[MISS_KEY] = {"since": since.isoformat(), "asks": asks,
                          "last_at": now.isoformat()}
        row.metadata = meta
        row.save(update_fields=["metadata"])
    trade.metadata = meta
    waited = (now - since).total_seconds()
    if asks >= UNPROVEN_MIN_ASKS and waited >= UNPROVEN_WAIT_S:
        return "unproven", (
            f"eToro's order read did not answer {asks} asks over "
            f"{int(waited // 60)} minutes; booked from its position list, "
            f"because a position left open here after it is gone is its own "
            f"failure")
    return "wait", (f"eToro's order read did not answer (ask {asks} since "
                    f"{since.astimezone(dt_timezone.utc):%H:%M} UTC); nothing "
                    f"booked, asked again next pass")


def word_on_miss(trade, client, *, now=None) -> tuple:
    """For reconcile: ("", "") cannot ask (today's rule); ("closed", "");
    ("open", ""); ("wait", why); ("unproven", note)."""
    if not can_ask(trade, client):
        return "", ""
    from bot_program.pending_closes import venue_position_state
    said = venue_position_state(trade, client)
    if said == "closed":
        return "closed", ""
    if said == "open":
        said_open(trade, client, where="reconcile", now=now)
        return "open", ""
    return after_no_answer(trade, now=now)


def note_missing(trade, client, *, now=None) -> bool:
    """Care wanted to close and the tick's list did not show the position,
    outside the venue's lag: the first such moment bounds the window from
    above. Never raises."""
    try:
        if not can_ask(trade, client):
            return False
        from bot_program.reconcile_asset import venue_lag_window
        if venue_lag_window(trade, client) or _meta(trade).get(MISSING_AT_KEY):
            return False
        merge_meta(trade, {MISSING_AT_KEY: (now or timezone.now()).isoformat()})
        return True
    except Exception as e:  # noqa: BLE001
        logger.info("[venue exit] #%s miss not stamped: %s",
                    getattr(trade, "id", "?"), e)
        return False


# ── B. the price ────────────────────────────────────────────────────────

def venue_levels(trade) -> dict:
    """{"stop": S, "target": T} resting AT THE VENUE; {} when protected is
    False (never sent, stripped base.py:3298-3301, vanished 2252-2255)."""
    meta = _meta(trade)
    if not meta.get("protected"):
        return {}
    stop = _f(trade.stop_loss)
    rew = meta.get("stop_rewritten_by_venue")
    if isinstance(rew, dict) and not (meta.get("stop_moves")
                                      or meta.get("level_edits")
                                      or meta.get("stop_reanchored_to_fill")):
        held = _f(rew.get("held"))
        if held is not None:
            stop = held if held > NO_STOP_SENTINEL else None
    if meta.get("venue_stop_unread"):
        stop = None
    out = {}
    if stop and stop > 0:
        out["stop"] = stop
    target = _f(trade.take_profit)
    if target and target > 0:
        out["target"] = target
    return out


def crossed(side, price, levels):
    p = _f(price)
    if p is None or p <= 0:
        return None
    buy = str(side).upper() == "BUY"
    s, t = levels.get("stop"), levels.get("target")
    if s is not None and (p <= s if buy else p >= s):
        return "stop"
    if t is not None and (p >= t if buy else p <= t):
        return "target"
    return None


def _level_changed_at(trade):
    """When the levels last changed: stop_moves[-1]["when"] (new, G3 §5.6),
    level_edits[-1]["at"] (adjust_levels.py:251-265)."""
    meta = _meta(trade)
    times = []
    for key, at in (("stop_moves", "when"), ("level_edits", "at")):
        rows = meta.get(key) or []
        if rows and isinstance(rows[-1], dict):
            times.append(_when(rows[-1].get(at)))
    times = [t for t in times if t is not None]
    return max(times) if times else None


def note_crossing(trade, price, *, now=None) -> bool:
    """A live eToro row's accepted mark stands beyond a level the venue
    holds: the FIRST such mark since eToro last showed it open is kept.
    Never raises.

    KEPT BY estimate()'S OWN RULE (2026-10-07, review). An old stamp stays
    while estimate() would still take it as evidence, WHICHEVER level a
    later tick crosses: the row stays OPEN here until a reconcile reads
    "closed", and a tick that crosses the other level after eToro filled
    the first booked a stop-out as a target hit (or the reverse). A stamp
    estimate() would refuse (older than the last listing or than the last
    level change, or of a level since moved) is written again: the tick
    stamps BEFORE that tick's care and stop moves, so a target crossing
    followed by a trailed stop move was dead evidence, and was kept."""
    try:
        if not _is_etoro_row(trade):
            return False
        lv = venue_levels(trade)
        hit = crossed(trade.side, price, lv)
        if hit is None:
            return False
        now = now or timezone.now()
        old = _meta(trade).get(CROSSED_KEY)
        old = old if isinstance(old, dict) else {}
        old_at, kept = _when(old.get("at")), old.get("level")
        floor = [t for t in (last_seen_open(trade), _level_changed_at(trade))
                 if t is not None]
        ev_lo = max(floor) if floor else None
        if (old_at is not None and kept in lv
                and _same(old.get("price"), lv[kept])
                and (ev_lo is None or old_at >= ev_lo)):
            return False
        merge_meta(trade, {CROSSED_KEY: {"level": hit, "price": lv[hit],
                                         "mark": _f(price),
                                         "at": now.isoformat()}})
        return True
    except Exception as e:  # noqa: BLE001
        logger.info("[venue exit] #%s crossing not stamped: %s",
                    getattr(trade, "id", "?"), e)
        return False


def _bars_reached(trade, levels, *, since, until):
    """1h PriceData bars (stamped at their OPEN, on the hour) that opened no
    earlier than since - BARS_START_SLACK_S. Only proves a level was
    reached. Both in one bar: the stop."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = Instrument.objects.filter(symbol=trade.symbol).first()
    if inst is None:
        return None
    buy = str(trade.side).upper() == "BUY"
    s, t = levels.get("stop"), levels.get("target")
    rows = (PriceData.objects
            .filter(instrument=inst, timeframe=BARS_TIMEFRAME,
                    timestamp__gte=since - timedelta(seconds=BARS_START_SLACK_S),
                    timestamp__lte=until)
            .order_by("timestamp").values_list("high", "low"))
    for high, low in rows:
        hi, lo = _f(high), _f(low)
        if hi is None or lo is None:
            continue
        if s is not None and (lo <= s if buy else hi >= s):
            return "stop", (lo if buy else hi)
        if t is not None and (hi >= t if buy else lo <= t):
            return "target", (hi if buy else lo)
    return None


def _risk_per_unit(trade):
    init = _f(_meta(trade).get("initial_stop_loss")) or _f(trade.stop_loss)
    entry = _f(trade.entry_price)
    if not init or not entry:
        return None
    return abs(entry - init) or None


def _ours_may_be_the_fill(meta) -> bool:
    from bot_program.pending_closes import (CLOSE_FILLS_KEY,
                                            CLOSE_IN_DOUBT_KEY,
                                            CLOSE_SENT_AT_KEY)
    return bool(meta.get(CLOSE_SENT_AT_KEY) or meta.get(CLOSE_FILLS_KEY)
                or meta.get(CLOSE_IN_DOUBT_KEY))


def estimate(trade, *, mark=None, now=None):
    """The level a venue-closed row is booked at, or None (keep the mark).
    Called ONLY when the venue said "closed". {level, price, evidence,
    seen, source, since}; evidence: crossed | last_mark | bars |
    mark_beyond | nearest."""
    from bot_program.pending_closes import (EXIT_SOURCE_VENUE_STOP,
                                            EXIT_SOURCE_VENUE_TARGET)
    if getattr(trade, "paper", True) or trade.asset_class == "options":
        return None
    meta = _meta(trade)
    if _ours_may_be_the_fill(meta):
        return None
    lv = venue_levels(trade)
    if not lv:
        return None
    now = now or timezone.now()
    lo = last_seen_open(trade)

    def basis(name, evidence, seen):
        return {"level": name, "price": lv[name], "evidence": evidence,
                "seen": _f(seen),
                "source": (EXIT_SOURCE_VENUE_STOP if name == "stop"
                           else EXIT_SOURCE_VENUE_TARGET),
                "since": lo.isoformat() if lo else None}

    if lo is not None:
        ev_lo = max([lo] + [t for t in (_level_changed_at(trade),) if t])
        c = meta.get(CROSSED_KEY) if isinstance(meta.get(CROSSED_KEY), dict) else {}
        c_at = _when(c.get("at"))
        if (c_at is not None and c_at >= ev_lo and c.get("level") in lv
                and _same(c.get("price"), lv[c["level"]])):
            return basis(c["level"], "crossed", c.get("mark"))
        care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
        lm, lm_at = _f(care.get("last_mark")), _when(care.get("last_mark_at"))
        if lm and lm_at is not None and lm_at >= ev_lo:
            hit = crossed(trade.side, lm, lv)
            if hit:
                return basis(hit, "last_mark", lm)
        got = _bars_reached(trade, lv, since=ev_lo, until=now)
        if got:
            return basis(got[0], "bars", got[1])
    m = _f(mark)
    if m and m > 0:
        hit = crossed(trade.side, m, lv)
        if hit:
            return basis(hit, "mark_beyond", m)
        risk = _risk_per_unit(trade)
        if risk:
            caps = {"stop": NEAREST_STOP_MAX_R, "target": NEAREST_TARGET_MAX_R}
            near = [(abs(m - level), name != "stop", name)
                    for name, level in lv.items()
                    if abs(m - level) <= caps[name] * risk]
            if near:
                return basis(min(near)[2], "nearest", m)
    return None


# ── the window ──────────────────────────────────────────────────────────

def closed_between(trade, *, now=None):
    """(lo, hi): the last venue reading that showed it open, and the first
    list read that did not (or `now`); None with no reading."""
    lo = last_seen_open(trade)
    if lo is None:
        return None
    meta = _meta(trade)
    miss = meta.get(MISS_KEY) if isinstance(meta.get(MISS_KEY), dict) else {}
    his = [now or timezone.now()]
    for raw in (meta.get(MISSING_AT_KEY), miss.get("since")):
        t = _when(raw)
        if t is not None and t >= lo:
            his.append(t)
    return lo, min(his)


def between_words(lo, hi) -> str:
    """Facts, not an inferred close time (the list keeps a closed position
    up to ~60 s): lo floored, hi ceiled to the minute; dates when the UTC
    days differ."""
    utc = dt_timezone.utc
    a = lo.astimezone(utc).replace(second=0, microsecond=0)
    b = hi.astimezone(utc)
    if b.second or b.microsecond:
        b = b.replace(second=0, microsecond=0) + timedelta(minutes=1)
    fmt = "%H:%M" if a.date() == b.date() else "%Y-%m-%d %H:%M"
    return (f"eToro last showed it open at {a.strftime(fmt)} UTC and no "
            f"longer at {b.strftime(fmt)} UTC")
