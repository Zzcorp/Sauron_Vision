"""THE THESIS CHECK (2026-10-03): is the reason for this trade still alive?

The operator: "Sauron should not be so procedural ... can the price come
back and make the position a winner, or at least break even? If yes,
adjust. A resilient and smart trading system that truly behaves on market
conditions." The open-position review's triggers are arithmetic on the R
(brain/position_review.py): "-2.09R against entry, back to flat — the
thesis has paid nothing", and the model pass dressed that arithmetic as
"a failed breakout". A trader reads the structure first. The lows under
the stop were swept and the bar closed back above them: those stops are
gone, whoever took them is long, and the place for the stop is under
that sweep — not the exit button.

One question, answered from what the platform already reads:

  STRUCTURE  bot_program.smart_money on the 4h bars. A fresh sweep with
             or against the position (sweep_read); the bias, its
             confidence, the dealing-range zone, the opposing zone and the
             draw (ict_read); the latest break of structure AGAINST the
             position and whether it displaced (signals/smc/displacement,
             the same qualification daily_bias uses) or was reclaimed. A
             sweep that reversed and a break that displaced are the two
             faces of one kind of bar, and only one of them kills a
             thesis. The structure stop: HUNT_DEPTH_ATR beyond the swept
             extreme, or beyond the nearest held swing on the stop's side.
  ODDS       the proving ground's own trades for this rule on this class
             (ProvingTrade, with the worst excursion `mae` since
             2026-10-03): of the trades that were at least THIS deep, how
             many came back to win, how many reached the target, how long
             they took — in the current regime when there are enough,
             every regime otherwise, said. No family → no odds, never a
             number. A care-policy trade stops at -1R, so a position
             deeper than that has no analog and the structure decides.
  VERDICT    exit    the structure is broken: a displaced break against,
                     not reclaimed; a confident bias against with no
                     sweep in favour; or ODDS_MIN_N analogs this deep of
                     which under ODDS_EXIT came back
             adjust  alive, and a structure stop exists that TIGHTENS the
                     stop in place with MIN_ROOM_ATR of room to the mark
             hold    alive — the sweep reversed in favour, the entry was
                     reclaimed after a deep excursion, the bias is with,
                     the break was reclaimed, or the odds are ODDS_HOLD or
                     better
             watch   nothing structural either way: the R triggers stand
             unread  no usable mark, too few bars

A sweep in favour with the entry reclaimed outranks a bias against and
thin odds (the operator's case); it never outranks a displaced break
that was not reclaimed.

What each verdict does. `exit` is a trigger (thesis_dead) the review's
model pass answers and the operator decides on: nothing here closes
anything. `adjust` is written on the row (metadata["thesis"], bot book
only) and the position care — Aragorn, bot_program/position_care.plan —
takes the structure stop as one more tighten-only candidate beside its
own locks, never on the manual lane and never past THESIS_STOP_TTL_HOURS
without a fresh read. Reducing risk is the care's job already; adding
risk is never done from here. `hold` damps the adverse-excursion trigger
so the model budget goes to the dead theses first. Every verdict rides
the PositionReview row inside its facts, so `manage.py thesis record`
can say whether the holds paid and the exits saved anything.
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEFRAME = "4h"
#: Fewer bars than this and the structure is not read.
MIN_BARS = 30
#: A break against the position older than this is the regime, not news.
BREAK_FRESH_BARS = 6
#: Within this of the entry, after a deep excursion, the entry is reclaimed.
RECLAIM_BAND_R = 0.25
#: The excursion that makes the question worth asking: the review's
#: ADVERSE_EXCURSION_R (tests/test_thesis_check.py pins the equality).
DEEP_MAE_R = -0.75
#: A bias against the position at this confidence, with no sweep in its
#: favour, is a dead thesis.
BIAS_AGAINST_CONF = 0.6
#: A bias with the position at this confidence counts for it.
BIAS_WITH_CONF = 0.5
#: Analogs needed before the odds say anything.
ODDS_MIN_N = 10
#: Share of analogs this deep that came back to win: at or above, hold.
ODDS_HOLD = 0.5
#: Below this share, the odds alone kill the thesis.
ODDS_EXIT = 0.35
#: The newest analogs read.
ODDS_N = 200
#: A structure stop needs this much room to the mark, in ATRs.
MIN_ROOM_ATR = 0.25
#: A structure stop older than this is not applied by the care.
THESIS_STOP_TTL_HOURS = 24

EXIT, ADJUST, HOLD, WATCH, UNREAD = "exit", "adjust", "hold", "watch", "unread"
ALIVE = (HOLD, ADJUST)


def _buy(side) -> bool:
    return str(side or "").upper() in ("BUY", "LONG")


# ── 1. THE STRUCTURE ──────────────────────────────────────────────────────

def structure_read(symbol, side, mark, *, timeframe=TIMEFRAME, now=None,
                   bars=None) -> dict:
    """What the 4h structure says about a position on `side` at `mark`:
    {ok, atr, bias, confidence, zone, opposing, draw, draw_room_atr,
    sweep_with, sweep_against, sweep_why, break_against, structure_stop,
    structure_stop_why, bars}. `bars` = (df, swings) to read instead of
    loading. Too few bars reads nothing, said."""
    from bot_program import smart_money as sm
    out = {"ok": False, "why": "", "symbol": symbol, "timeframe": timeframe}
    df, swings = bars if bars is not None else sm._bars(symbol, timeframe)
    if df is None or len(df) < MIN_BARS or not swings:
        out["why"] = "too few bars for a structure read"
        return out
    from signals.smc.pivots import atr as _atr
    try:
        atr = float(_atr(df)[-1] or 0)
        mark = float(mark)
    except (TypeError, ValueError, IndexError):
        atr, mark = 0.0, 0.0
    if atr <= 0 or mark <= 0:
        out["why"] = "no ATR or no mark"
        return out
    buy = _buy(side)
    direction = "BUY" if buy else "SELL"
    sweep = sm.sweep_read(df, swings, direction, atr, entry=mark)
    ict = sm.ict_read(df, swings, direction, atr, mark, now=now)
    n = len(df)
    lows, highs = df["low"].values, df["high"].values

    # The latest break of structure against the position, qualified the
    # way daily_bias qualifies them (displacement behind the close).
    brk = None
    try:
        from signals.smc.displacement import qualify_breaks_with_displacement
        from signals.smc.structure import detect_market_structure_breaks
        breaks = qualify_breaks_with_displacement(
            df, detect_market_structure_breaks(df, swings))
        against = "BOS_DOWN" if buy else "BOS_UP"
        fresh = [b for b in breaks
                 if b["type"] == against and b["idx"] >= n - BREAK_FRESH_BARS]
        if fresh:
            b = fresh[-1]
            level = float(b["broken_swing_price"])
            reclaimed = (mark > level) if buy else (mark < level)
            brk = {"level": level, "close": float(b["trigger_price"]),
                   "bars_ago": int(n - 1 - b["idx"]),
                   "displaced": bool(b.get("displaced")) and not reclaimed,
                   "displacement_score": float(b.get("displacement_score")
                                               or 0.0),
                   "reclaimed": reclaimed}
    except Exception as e:  # noqa: BLE001 — a break unread is no break
        logger.debug("[thesis] %s: breaks unread: %s", symbol, e)

    # The structure stop: beyond the swept extreme, else beyond the nearest
    # held swing on the stop's side within the care's reach.
    stop, where = None, ""
    sw = sweep.get("with")
    if sw:
        i = n + int(sw["bar"])
        if 0 <= i < n:
            ext = float(lows[i]) if buy else float(highs[i])
            stop = (ext - sm.HUNT_DEPTH_ATR * atr if buy
                    else ext + sm.HUNT_DEPTH_ATR * atr)
            where = f"the sweep's {'low' if buy else 'high'} {ext:g}"
    if stop is None:
        reach = sm.LIVING_REACH_ATR * atr
        held = [s for s in swings
                if s["idx"] >= n - sm.LEVEL_LOOKBACK and sm._untaken(df, s, n)
                and ((buy and s["type"] == "L" and mark - reach < s["price"] < mark)
                     or (not buy and s["type"] == "H"
                         and mark < s["price"] < mark + reach))]
        if held:
            s = max(held, key=lambda s: s["price"]) if buy \
                else min(held, key=lambda s: s["price"])
            stop = (float(s["price"]) - sm.HUNT_DEPTH_ATR * atr if buy
                    else float(s["price"]) + sm.HUNT_DEPTH_ATR * atr)
            where = (f"the held swing {'low' if buy else 'high'} "
                     f"{float(s['price']):g}")
    out.update({
        "ok": True, "atr": atr, "mark": mark, "bars": n,
        "bias": ict.get("bias"), "confidence": ict.get("confidence"),
        "zone": ict.get("zone"), "opposing": ict.get("opposing"),
        "draw": ict.get("draw"), "draw_room_atr": ict.get("draw_room_atr"),
        "sweep_with": sw, "sweep_against": sweep.get("against"),
        "sweep_why": sweep.get("why", ""),
        "break_against": brk,
        "structure_stop": round(stop, 8) if stop is not None else None,
        "structure_stop_why": where,
    })
    return out


# ── 2. THE ODDS ───────────────────────────────────────────────────────────

def recovery_odds(rule_name, asset_class, mae_r, *, regime=None,
                  timeframe=TIMEFRAME, n=ODDS_N) -> dict:
    """Of the proving ground's trades for this rule on this class that
    were at least `mae_r` deep: {ok, n, thin, won_pct, target_pct, avg_r,
    avg_bars, fell_back, regime, depth_r, run_id, family, why}."""
    from backtester.proving.memory import MIN_IN_REGIME, rule_case
    out = {"ok": False, "n": 0, "thin": True, "won_pct": None,
           "target_pct": None, "avg_r": None, "avg_bars": None,
           "fell_back": False, "regime": regime, "depth_r": mae_r,
           "run_id": "", "family": "", "why": ""}
    case = rule_case(rule_name or "")
    if case is None:
        out["why"] = (f"no proving family for {rule_name or '—'}: "
                      f"no odds, never a number")
        return out
    fam, direction = case
    out["family"] = fam.key
    try:
        depth = float(mae_r)
    except (TypeError, ValueError):
        out["why"] = "no excursion to compare"
        return out
    from backtester.models_proving import ProvingTrade, ProvingVerdict
    verdict = (ProvingVerdict.objects
               .filter(family=fam.key, direction=direction,
                       asset_class=asset_class, timeframe=timeframe,
                       policy="care", generated=False, filter="none")
               .order_by("-created_at").first())
    if verdict is None:
        out["why"] = (f"no saved verdict for {fam.key} {direction} on "
                      f"{asset_class} — run `manage.py prove rules --save`")
        return out
    out["run_id"] = verdict.run_id
    qs = (ProvingTrade.objects.filter(verdict=verdict, mae__lte=depth)
          .order_by("-entry_ts"))
    rows = list(qs.filter(regime=regime)[:n]) if regime else []
    if regime and len(rows) < MIN_IN_REGIME:
        rows = list(qs[:n])
        out["fell_back"] = True
    elif not regime:
        rows = list(qs[:n])
    k = len(rows)
    out["n"] = k
    out["thin"] = k < ODDS_MIN_N
    if not k:
        out["why"] = (f"no analog of {rule_name} on {asset_class} was "
                      f"{depth:+.2f}R deep in the saved run")
        return out
    out["ok"] = True
    out["won_pct"] = sum(1 for r in rows if r.r > 0) / k
    out["target_pct"] = sum(1 for r in rows
                            if r.reason in ("target", "gap target")) / k
    out["avg_r"] = sum(r.r for r in rows) / k
    out["avg_bars"] = sum(r.bars for r in rows) / k
    return out


# ── 3. THE VERDICT ────────────────────────────────────────────────────────

def _adjust_for(st: dict, facts: dict, buy: bool):
    """The structure stop as an adjustment, or None: only when it TIGHTENS
    the stop in place and leaves MIN_ROOM_ATR to the mark."""
    s = st.get("structure_stop")
    if s is None:
        return None
    mark, stop_now = facts.get("mark"), facts.get("stop")
    atr = float(st.get("atr") or 0)
    if mark is None or atr <= 0:
        return None
    if buy:
        tighter = stop_now is None or s > float(stop_now)
        room = float(mark) - s
    else:
        tighter = stop_now is None or s < float(stop_now)
        room = s - float(mark)
    if not tighter or room < MIN_ROOM_ATR * atr:
        return None
    from bot_program.smart_money import HUNT_DEPTH_ATR
    out = {"stop": round(float(s), 8),
           "why": f"beyond {st.get('structure_stop_why') or 'the structure'} "
                  f"by {HUNT_DEPTH_ATR:g} ATR"}
    entry, risk = facts.get("entry"), facts.get("risk_per_unit")
    if entry and risk:
        d = 1.0 if buy else -1.0
        out["r"] = round(d * (s - float(entry)) / float(risk), 2)
    return out


def thesis_check(pos: dict, facts: dict, *, now=None, structure=None,
                 odds=None) -> dict:
    """{verdict, alive, why, words, structure, odds, adjust, as_of} for
    one measured position (position_review.measure's facts). `structure`
    and `odds` may be handed in (tests, a caller that already read them)."""
    now = now or timezone.now()
    out = {"verdict": UNREAD, "alive": None, "why": [], "words": "",
           "structure": None, "odds": None, "adjust": None,
           "as_of": now.isoformat()}
    mark = facts.get("mark")
    if facts.get("stale_quote") or mark is None:
        out["why"] = ["no usable mark"]
        out["words"] = "Thesis unread: no usable mark."
        return out
    side = facts.get("side") or pos.get("side") or ""
    buy = _buy(side)
    symbol = facts.get("symbol") or pos.get("symbol") or ""
    ur, mae = facts.get("unrealized_r"), facts.get("mae_r")
    deep = mae is not None and float(mae) <= DEEP_MAE_R

    st = structure
    if st is None:
        try:
            st = structure_read(symbol, side, mark, now=now)
        except Exception as e:  # noqa: BLE001 — a read that fails is unread
            logger.info("[thesis] %s: structure unread: %s", symbol, e)
            st = {"ok": False, "why": f"structure unread: {e}"[:200]}
    out["structure"] = st

    od = odds
    if od is None and deep and facts.get("rule_name"):
        try:
            from backtester.proving.memory import regime_now
            od = recovery_odds(facts.get("rule_name"),
                               facts.get("asset_class") or "", mae,
                               regime=regime_now(symbol))
        except Exception as e:  # noqa: BLE001
            logger.info("[thesis] %s: odds unread: %s", symbol, e)
            od = None
    out["odds"] = od

    if not st.get("ok"):
        out["why"] = [st.get("why") or "structure unread"]
        out["words"] = f"Thesis unread: {out['why'][0]}."
        return out

    dead_hard, dead, alive = [], [], []
    brk = st.get("break_against")
    if brk and brk.get("displaced"):
        dead_hard.append(
            f"structure broke against it: a displaced close through "
            f"{brk['level']:g} {brk['bars_ago']} bar(s) ago, not reclaimed")
    bias, conf = st.get("bias"), float(st.get("confidence") or 0.0)
    with_us = bias == ("long" if buy else "short")
    against_us = bias == ("short" if buy else "long")
    sw = st.get("sweep_with")
    if against_us and conf >= BIAS_AGAINST_CONF and not sw:
        dead.append(f"the bias is {bias} at {conf:.2f} confidence")
    if od and od.get("ok") and not od.get("thin") \
            and od["won_pct"] < ODDS_EXIT:
        dead.append(f"only {od['won_pct'] * 100:.0f}% of {od['n']} analogs "
                    f"{float(mae):+.2f}R deep came back to win")

    reclaimed = ur is not None and float(ur) >= -RECLAIM_BAND_R
    if sw:
        alive.append(
            f"the {'lows' if buy else 'highs'} were swept at {sw['level']:g} "
            f"and the bar closed back {'above' if buy else 'below'}: those "
            f"stops are gone, whoever took them is {'long' if buy else 'short'}")
    if deep and reclaimed:
        alive.append(f"back at the entry after {float(mae):+.2f}R against it")
    if with_us and conf >= BIAS_WITH_CONF:
        alive.append(f"the bias is {bias} at {conf:.2f}")
    if brk and not brk.get("displaced") and brk.get("reclaimed"):
        alive.append(f"the break of {brk['level']:g} was reclaimed")
    if od and od.get("ok") and not od.get("thin") \
            and od["won_pct"] >= ODDS_HOLD:
        alive.append(f"{od['won_pct'] * 100:.0f}% of {od['n']} analogs "
                     f"{float(mae):+.2f}R deep came back to win, "
                     f"{od['avg_r']:+.2f}R on average")

    if dead_hard:
        verdict, why = EXIT, dead_hard + dead
    elif dead and not (sw and reclaimed):
        verdict, why = EXIT, dead
    elif alive:
        verdict, why = HOLD, alive
        adj = _adjust_for(st, facts, buy)
        if adj:
            verdict = ADJUST
            out["adjust"] = adj
    else:
        verdict, why = WATCH, ["nothing structural either way"]
    out["verdict"] = verdict
    out["alive"] = (True if verdict in ALIVE else False if verdict == EXIT
                    else None)
    out["why"] = why

    label = {EXIT: "DEAD", HOLD: "ALIVE — hold", ADJUST: "ALIVE — adjust",
             WATCH: "unclear"}[verdict]
    words = f"Thesis {label}: " + "; ".join(why) + "."
    if out["adjust"]:
        words += (f" Stop to {out['adjust']['stop']:g} ({out['adjust']['why']}"
                  + (f", {out['adjust']['r']:+.2f}R)" if "r" in out["adjust"]
                     else ")") + ".")
    if od and deep:
        if od.get("ok") and od.get("thin"):
            words += (f" Only {od['n']} analog(s) this deep — a thin "
                      f"sample.")
        elif od.get("ok") and od.get("fell_back"):
            words += " (every tape counted: too few analogs in the current one)"
        elif not od.get("ok") and od.get("why"):
            words += f" Odds: {od['why']}."
    out["words"] = words
    return out


# ── 4. THE ROW AND THE CARE ──────────────────────────────────────────────

def write_on_row(position_id: int, thesis: dict) -> bool:
    """metadata["thesis"] = {verdict, stop, why, words, at} on the bot
    row, merged under a row lock like the care's own keys. The position
    care reads `stop` when the verdict is adjust and `at` is fresh."""
    from django.db import transaction

    from bot_program.models import AssetBotTrade
    adj = thesis.get("adjust") or {}
    value = {"verdict": thesis.get("verdict", UNREAD),
             "stop": adj.get("stop"), "why": adj.get("why", ""),
             "words": (thesis.get("words") or "")[:300],
             "at": thesis.get("as_of") or timezone.now().isoformat()}
    try:
        with transaction.atomic():
            row = (AssetBotTrade.objects.select_for_update()
                   .filter(pk=position_id).first())
            if row is None:
                return False
            meta = dict(row.metadata or {})
            if meta.get("thesis") == value:
                return False
            meta["thesis"] = value
            row.metadata = meta
            row.save(update_fields=["metadata"])
        return True
    except Exception as e:  # noqa: BLE001 — a note not written changes nothing
        logger.info("[thesis] #%s: not written on the row: %s", position_id, e)
        return False


def care_stop(meta: dict, now=None, *, ttl_hours=THESIS_STOP_TTL_HOURS):
    """(level, "structure") for the position care from a row's
    metadata["thesis"], or None: only an `adjust` verdict with a stop,
    read within `ttl_hours`. Pure, no I/O."""
    th = (meta or {}).get("thesis") or {}
    if th.get("verdict") != ADJUST or th.get("stop") is None:
        return None
    from django.utils.dateparse import parse_datetime
    at = parse_datetime(str(th.get("at") or "")) if th.get("at") else None
    if at is None:
        return None
    if at.tzinfo is None:
        # Read a naive time as UTC (settings.TIME_ZONE). django.utils
        # .timezone.utc left Django in 5.0: a naive `at` raised
        # AttributeError here, which escaped plan() into care()'s except
        # and skipped the row's whole care plan, not just this stop. No
        # writer stores a naive time today (write_on_row: aware ISO).
        at = at.replace(tzinfo=dt_timezone.utc)
    now = now or timezone.now()
    if now - at > timedelta(hours=ttl_hours):
        return None
    try:
        return float(th["stop"]), "structure"
    except (TypeError, ValueError):
        return None


# ── 5. THE RECORD ─────────────────────────────────────────────────────────

def track_record(*, days=30, now=None) -> dict:
    """How the thesis verdicts graded, from the PositionReview rows that
    carry one: {"alive"|"exit": {n, right, wrong, unresolved, pending,
    r_delta}}. An alive verdict (hold, adjust) was right when the position
    closed better than it stood at the call, past the review's noise
    band; exit was right when it closed worse. Graded here from the bot
    row's realized R, not from the model pass's own grading, because most
    thesis verdicts ride rows the model never saw. Still open: pending.
    No R either side, or inside the band: unresolved, out of the score."""
    from brain.position_review_agent import (GRADE_NOISE_BAND_R,
                                             _closed_bot_trade)
    from brain.position_review_models import PositionReview
    now = now or timezone.now()
    out = {}
    qs = (PositionReview.objects
          .filter(created_at__gte=now - timedelta(days=days))
          .exclude(stale_quote=True)
          .only("book", "position_id", "facts", "r_at_review", "r_at_close"))
    closed_cache: dict = {}
    for row in qs:
        th = (row.facts or {}).get("thesis") or {}
        v = th.get("verdict")
        if v not in (HOLD, ADJUST, EXIT):
            continue
        key = "alive" if v in ALIVE else "exit"
        slot = out.setdefault(key, {"n": 0, "right": 0, "wrong": 0,
                                    "unresolved": 0, "pending": 0,
                                    "r_delta": 0.0})
        slot["n"] += 1
        r_close = row.r_at_close
        if r_close is None and row.book == PositionReview.BOOK_BOT:
            if row.position_id not in closed_cache:
                closed_cache[row.position_id] = _closed_bot_trade(
                    row.position_id)
            closed = closed_cache[row.position_id]
            if closed is None:
                slot["pending"] += 1
                continue
            r_close = closed.get("realized_r")
        if r_close is None or row.r_at_review is None:
            slot["unresolved"] += 1
            continue
        delta = float(r_close) - float(row.r_at_review)
        if abs(delta) <= GRADE_NOISE_BAND_R:
            slot["unresolved"] += 1
            continue
        slot["r_delta"] = round(slot["r_delta"] + delta, 4)
        if (key == "alive") == (delta > 0):
            slot["right"] += 1
        else:
            slot["wrong"] += 1
    return out
