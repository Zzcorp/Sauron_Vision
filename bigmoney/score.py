"""Forward measures, the record, and the one automatic weight rule
(spec §2.8).

Every read cell with a claim becomes a BigMoneyCell, graded later on its
proxy's own daily closes: the return over h business days (calendar days
for crypto), and for a tail claim the worst close against the crowd on the
way. Statistics are computed when asked, per (footprint, market, live or
replayed); live and replayed are never pooled.

THE ONE AUTOMATIC WEIGHT RULE, one-sided: a lean footprint whose record
says "works against its claim so far" has its weight set to zero. Never
flipped (the reverse is a new hypothesis for the proving ground), never
raised above its prior: more weight is a code change the operator makes.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from bigmoney import words as W
from bigmoney.cells import ACTIVE_AT, LEAN_AT, LEAN_FOOTPRINTS
from bigmoney.rows import GLOBAL, INSTRUMENTS, ROW_ORDER, ROWS

logger = logging.getLogger(__name__)

SCORE_MIN_N = 40
TAIL_MIN_N = 20
T_PAYS = 2.0
LATE_DAYS = 5
CALIBRATION_AGENT = "big_money"
CALIBRATION_HORIZON_H = 120
CALIBRATION_CONFIDENCE = 0.55
TAIL_FLAG_AT = 0.6          # |s| at or above: COT index >= 80 or <= 20


def _is_crypto(symbol, store=None) -> bool:
    from bigmoney.rows import CRYPTO_SYMBOLS
    if symbol in CRYPTO_SYMBOLS:
        return True
    if store is not None:
        return store.asset_class(symbol) == "crypto"
    return False


# ── storing a read ───────────────────────────────────────────────────────

def _claims(cells: dict, market: str):
    """[(footprint, market, proxy, cell)] for every read cell with a claim."""
    out = []
    for name, c in (cells or {}).items():
        if name.startswith("_") or not isinstance(c, dict):
            continue
        if c.get("state") != "read" or not c.get("claim"):
            continue
        proxies = c.get("proxies") or [c.get("proxy")]
        for proxy in proxies:
            if not proxy:
                continue
            m = proxy if len(proxies) > 1 else market
            out.append((name, m, proxy, c))
    return out


def claim_close(store, proxy, as_of: date, run) -> tuple:
    """(day, close) of c_t, the close a claim is graded from: the proxy's
    close ON the as-of day (the day before for a crypto proxy read in the
    evening, whose as-of bar closes at 00:00 UTC after the read), or
    (None, None). Never an older close: a claim graded from a tape that
    died twelve days before would record twelve days of move as the
    claim's own (measure() then says "no close on {as_of}: unscored")."""
    want = as_of
    if _is_crypto(proxy, store) and run == "evening":
        want = as_of - timedelta(days=1)
    day, close = store.close_on_or_before(proxy, want)
    if day != want:
        return None, None
    return day, close


def store_board(board: dict, store=None, run=None) -> int:
    """Write the read's rows (update_or_create on as_of, row, replayed) and
    one BigMoneyCell per claim. Returns the number of read rows stored.
    `run` relabels the stored rows (the command stores a read made with the
    morning's or the evening's rules as "manual"); the read's own run still
    decides which crypto close a claim is graded from."""
    from bigmoney.inputs import Store
    from bigmoney.models import BigMoneyCell, BigMoneyRead
    as_of = date.fromisoformat(board["as_of"])
    replayed = bool(board.get("replayed"))
    run = run or board.get("run") or "morning"
    store = store or Store(upto=as_of if replayed else None)
    stored = 0
    payload = []
    for key in ROW_ORDER:
        r = board["rows"].get(key)
        if r is None:
            continue
        payload.append((key, {"lean": r["lean"], "lean_label": r["lean_label"],
                              "lean_from": r["lean_from"],
                              "coverage": r["coverage"], "current": r["current"],
                              "risk": r["risk"], "cells": r["cells"],
                              "unread": r["unread"]}, r["cells"]))
    g = board.get("global") or {}
    payload.append((GLOBAL, {"lean": None, "lean_label": "", "lean_from": [],
                             "coverage": None, "current": g.get("current", []),
                             "risk": g.get("risk", []),
                             "cells": g.get("cells", {}),
                             "unread": g.get("unread", [])}, None))
    inst = board.get("instruments") or {}
    payload.append((INSTRUMENTS, {"lean": None, "lean_label": "",
                                  "lean_from": [], "coverage": None,
                                  "current": [], "risk": [],
                                  "cells": inst.get("cells", {}),
                                  "unread": inst.get("unread", [])}, None))
    with transaction.atomic():
        for key, fields, _cells in payload:
            read, _ = BigMoneyRead.objects.update_or_create(
                as_of=as_of, row=key, replayed=replayed,
                defaults=dict(fields, run=run, computed_at=timezone.now()))
            stored += 1
            if key == GLOBAL:
                claims = _claims(fields["cells"], GLOBAL)
            elif key == INSTRUMENTS:
                claims = []
                for sym, cells in (fields["cells"] or {}).items():
                    claims.extend(_claims(cells, sym))
            else:
                claims = _claims(fields["cells"], key)
            keep = set()
            for footprint, market, proxy, c in claims:
                # The read's own run (never the relabel) decides which
                # crypto close the claim is graded from.
                close_day, close = claim_close(store, proxy, as_of,
                                               board.get("run"))
                cell, created = BigMoneyCell.objects.get_or_create(
                    read=read, footprint=footprint, market=market,
                    defaults={"proxy": proxy, "score": c.get("score"),
                              "claim": c["claim"],
                              "horizon_days": int(c.get("horizon_days") or 1),
                              "proxy_close": close,
                              "proxy_close_date": close_day})
                keep.add(cell.pk)
                if not created and cell.scored_at is None:
                    cell.proxy, cell.score = proxy, c.get("score")
                    cell.claim = c["claim"]
                    cell.horizon_days = int(c.get("horizon_days") or 1)
                    cell.proxy_close = close
                    cell.proxy_close_date = close_day
                    cell.save(update_fields=["proxy", "score", "claim",
                                             "horizon_days", "proxy_close",
                                             "proxy_close_date"])
            BigMoneyCell.objects.filter(read=read, scored_at__isnull=True) \
                .exclude(pk__in=keep).delete()
    return stored


# ── grading ──────────────────────────────────────────────────────────────

def target_date(as_of: date, h: int, cal, crypto: bool) -> date:
    if crypto:
        return as_of + timedelta(days=int(h))
    return cal.add_business_days(as_of, int(h))


def measure(cell, as_of: date, cal, store) -> dict | None:
    """{fwd_return, fwd_adverse} or {"note"} once due; None while waiting."""
    crypto = _is_crypto(cell.proxy, store)
    target = target_date(as_of, cell.horizon_days, cal, crypto)
    late = target_date(target, LATE_DAYS, cal, crypto)
    if not cell.proxy_close or cell.proxy_close <= 0:
        # No close on the as-of day. The next run's read of the same day
        # may still store it (the morning after the evening), so the cell
        # waits until its target day has passed, then is kept unscored.
        if timezone.now().date() <= target:
            return None
        return {"note": W.UNSCORED.format(date=as_of.isoformat())}
    days, closes, _ = store.series(cell.proxy)
    path = [(d, c) for d, c in zip(days, closes) if as_of < d <= late]
    at_target = next(((d, c) for d, c in path if d >= target), None)
    if at_target is None:
        if timezone.now().date() > late:
            return {"note": W.UNSCORED.format(date=target.isoformat())}
        return None
    c_t = cell.proxy_close
    out = {"fwd_return": math.log(at_target[1] / c_t), "fwd_adverse": None}
    if cell.claim == "tail":
        S = 1 if (cell.score or 0) >= 0 else -1
        seg = [c for d, c in path if d <= at_target[0]]
        out["fwd_adverse"] = min(S * (c / c_t - 1.0) for c in [c_t] + seg)
    return out


def score_due(*, cal=None, store=None, replayed=None) -> int:
    """Grade every unscored cell whose horizon has passed. Returns the count."""
    from bigmoney.calendar import BusinessCalendar
    from bigmoney.inputs import Store
    from bigmoney.models import BigMoneyCell
    cal = cal or BusinessCalendar.from_db()
    store = store or Store()
    qs = BigMoneyCell.objects.filter(scored_at__isnull=True).select_related("read")
    if replayed is not None:
        qs = qs.filter(read__replayed=replayed)
    n = 0
    for cell in qs.iterator():
        try:
            got = measure(cell, cell.read.as_of, cal, store)
        except Exception as e:  # noqa: BLE001
            logger.warning("[big money] cell %s unscored: %s", cell.pk, e)
            continue
        if got is None:
            continue
        if "note" in got:
            cell.score_note = got["note"][:120]
        else:
            cell.fwd_return = got["fwd_return"]
            cell.fwd_adverse = got["fwd_adverse"]
        cell.scored_at = timezone.now()
        cell.save(update_fields=["fwd_return", "fwd_adverse", "scored_at",
                                 "score_note"])
        n += 1
    return n


# ── statistics ───────────────────────────────────────────────────────────

def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


def drift_of(proxy, h, first: date, last: date, store) -> float | None:
    """The proxy's own mean h-bar forward log return over every stored day
    of the scored span: what any reading would have earned, so a bull
    market does not flatter "leans up"."""
    days, closes, _ = store.series(proxy)
    rets = []
    for i, d in enumerate(days):
        if d < first or d > last or i + h >= len(closes):
            continue
        rets.append(math.log(closes[i + h] / closes[i]))
    return sum(rets) / len(rets) if rets else None


def _h(r, h) -> int:
    """A row's own horizon (opex stores one per read day: the business
    days to the expiry Friday), else the record's."""
    return int(r.get("h") or h or 1)


def non_overlapping(rows, h, cal):
    """Every h-th observation: a row is kept when its as-of day is at least
    its predecessor's horizon (in business days) after the last kept one."""
    kept, next_ok = [], None
    for r in sorted(rows, key=lambda r: r["as_of"]):
        if next_ok is None or r["as_of"] >= next_ok:
            kept.append(r)
            next_ok = cal.add_business_days(r["as_of"], _h(r, h))
    return kept


def stats_for(rows, *, h, proxy, cal, store) -> dict:
    """The record of one (footprint, market, live or replayed). Each row is
    benchmarked against the proxy's drift over its OWN horizon, so a
    footprint whose horizon varies by read day (opex: 5 business days on
    Monday, 1 on Thursday) is never measured against one horizon's drift."""
    scored = [r for r in rows if r["fwd_return"] is not None]
    # A row left unscored ("no close on ...") is kept and counted apart:
    # it never enters the statistics.
    out = {"n": len(scored), "unscored": len(rows) - len(scored),
           "n_active": 0, "hit": None, "mean_bp": None, "edge_bp": None,
           "spearman": None, "n_eff": 0, "t": None, "drift": None}
    if not scored:
        return out
    active = [r for r in scored if abs(r["score"] or 0) >= ACTIVE_AT]
    out["n_active"] = len(active)
    first, last = min(r["as_of"] for r in scored), max(r["as_of"] for r in scored)
    drifts = {}

    def drift_for(hr):
        if hr not in drifts:
            d = drift_of(proxy, hr, first, last, store)
            if d is None:
                same = [r["fwd_return"] for r in scored if _h(r, h) == hr]
                same = same or [r["fwd_return"] for r in scored]
                d = sum(same) / len(same)
            drifts[hr] = d
        return drifts[hr]

    out["drift"] = drift_for(int(h or 1))
    out["spearman"] = spearman([r["score"] or 0 for r in scored],
                               [r["fwd_return"] for r in scored])
    if not active:
        return out
    signed = [(1 if r["score"] > 0 else -1) * r["fwd_return"] for r in active]
    excess = [(1 if r["score"] > 0 else -1)
              * (r["fwd_return"] - drift_for(_h(r, h))) for r in active]
    out["hit"] = sum(1 for x in signed if x > 0) / len(signed)
    out["mean_bp"] = 1e4 * sum(signed) / len(signed)
    out["edge_bp"] = 1e4 * sum(excess) / len(excess)
    sub = non_overlapping(active, h, cal)
    xs = [(1 if r["score"] > 0 else -1) * (r["fwd_return"] - drift_for(_h(r, h)))
          for r in sub]
    out["n_eff"] = len(xs)
    if len(xs) >= 2:
        m = sum(xs) / len(xs)
        v = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
        out["t"] = m / math.sqrt(v / len(xs)) if v > 0 else None
    return out


def verdict(st: dict) -> str:
    if st.get("n_eff", 0) < SCORE_MIN_N:
        return W.VERDICT_FEW.format(n=st.get("n_eff", 0), m=SCORE_MIN_N)
    t, edge = st.get("t"), st.get("edge_bp")
    if t is not None and t >= T_PAYS and (edge or 0) > 0:
        return W.VERDICT_PAYS
    if t is not None and t <= -T_PAYS:
        return W.VERDICT_AGAINST
    return W.VERDICT_NONE


def tail_stats(rows) -> dict:
    scored = [r for r in rows if r["fwd_adverse"] is not None]
    flagged = [r for r in scored if abs(r["score"] or 0) >= TAIL_FLAG_AT]
    out = {"n": len(scored), "n_flagged": len(flagged), "ratio": None}
    if flagged and scored:
        usual = sum(r["fwd_adverse"] for r in scored) / len(scored)
        mine = sum(r["fwd_adverse"] for r in flagged) / len(flagged)
        if usual < 0:
            out["ratio"] = mine / usual
    return out


def tail_verdict(st: dict) -> str:
    if st["n_flagged"] < TAIL_MIN_N or st["ratio"] is None:
        return W.VERDICT_FEW.format(n=st["n_flagged"], m=TAIL_MIN_N)
    return W.VERDICT_TAIL.format(x=st["ratio"], n=st["n_flagged"])


def cost_line(st: dict, proxy: str, store=None) -> str:
    """The measured signed move against the platform's own round trip."""
    if st.get("mean_bp") is None:
        return ""
    from bot_program.asset_engine.risk_levels import DEFAULT_COST_BPS
    klass = ""
    try:
        if store is not None:
            klass = store.asset_class(proxy)
        else:
            from instruments.models import Instrument
            inst = Instrument.objects.filter(symbol=proxy).first()
            klass = (inst.asset_class if inst else "") or ""
    except Exception:  # noqa: BLE001
        klass = ""
    c = float(DEFAULT_COST_BPS.get(klass, 8.0))
    text = W.COST_LINE.format(m=st["mean_bp"], klass=klass or "this class", c=c)
    if abs(st["mean_bp"]) < 2 * c:
        text += W.COST_SHORT
    return text


def _rows_of(footprint=None, market=None, replayed=False):
    from bigmoney.models import BigMoneyCell
    qs = BigMoneyCell.objects.filter(read__replayed=replayed,
                                     scored_at__isnull=False)
    if footprint:
        qs = qs.filter(footprint=footprint)
    if market:
        qs = qs.filter(market=market)
    out = {}
    # Plain values, not two model instances per cell: a 3-year replay is
    # about a hundred thousand scored cells.
    for c in qs.order_by("read__as_of").values(
            "footprint", "market", "proxy", "claim", "horizon_days", "score",
            "fwd_return", "fwd_adverse", "read__as_of"):
        out.setdefault((c["footprint"], c["market"]), []).append({
            "as_of": c["read__as_of"], "score": c["score"],
            "proxy": c["proxy"], "claim": c["claim"],
            "h": c["horizon_days"], "fwd_return": c["fwd_return"],
            "fwd_adverse": c["fwd_adverse"]})
    return out


RECORD_CACHE_S = 3600
RECORD_CACHE_PREFIX = "bigmoney:record"


def _record_key(replayed) -> str | None:
    """The cache key of one record: it changes whenever a cell is graded
    (score_due stamps scored_at) or a scored cell is added or removed, so
    the cache is invalidated by the grading itself. None when the table
    cannot be read."""
    try:
        from django.db.models import Count, Max

        from bigmoney.models import BigMoneyCell
        agg = BigMoneyCell.objects.filter(
            read__replayed=bool(replayed), scored_at__isnull=False).aggregate(
            m=Max("scored_at"), n=Count("id"), k=Max("id"))
        stamp = agg["m"].isoformat() if agg["m"] else "none"
        return (f"{RECORD_CACHE_PREFIX}:{int(bool(replayed))}:{stamp}:"
                f"{agg['n']}:{agg['k']}")
    except Exception:  # noqa: BLE001
        return None


def record(*, replayed=False, cal=None, store=None, footprint=None,
           market=None) -> list:
    """[{footprint, market, proxy, claim, h, stats, verdict, cost}] of one
    record, live or replayed. The whole record (no footprint, market or
    store given) is cached for an hour under a key that moves with every
    grading, so the page and each run's weights pay for it once."""
    whole = footprint is None and market is None and store is None
    key = _record_key(replayed) if whole else None
    if key:
        try:
            from django.core.cache import cache
            got = cache.get(key)
            if got is not None:
                return got
        except Exception:  # noqa: BLE001
            pass
    out = _record(replayed=replayed, cal=cal, store=store,
                  footprint=footprint, market=market)
    if key:
        try:
            from django.core.cache import cache
            cache.set(key, out, RECORD_CACHE_S)
        except Exception:  # noqa: BLE001
            pass
    return out


def _record(*, replayed, cal, store, footprint, market) -> list:
    from bigmoney.calendar import BusinessCalendar
    from bigmoney.inputs import Store
    cal = cal or BusinessCalendar.from_db()
    store = store or Store()
    out = []
    for (fp, mk), rows in sorted(_rows_of(footprint, market, replayed).items()):
        proxy, claim = rows[-1]["proxy"], rows[-1]["claim"]
        h = int(rows[-1]["h"] or 1)
        if claim == "tail":
            st = tail_stats(rows)
            out.append({"footprint": fp, "market": mk, "proxy": proxy,
                        "claim": claim, "h": h, "stats": st,
                        "verdict": tail_verdict(st), "cost": ""})
            continue
        st = stats_for(rows, h=h, proxy=proxy, cal=cal, store=store)
        out.append({"footprint": fp, "market": mk, "proxy": proxy,
                    "claim": claim, "h": h, "stats": st,
                    "verdict": verdict(st), "cost": cost_line(st, proxy, store)})
    return out


def effective_weights(*, cal=None, store=None) -> dict:
    """{(footprint, market): (weight, zeroed)} for the lean footprints whose
    record says "works against its claim so far": the live record, or the
    replayed one while the live has fewer than 40 non-overlapping readings.
    Only zeros are returned: a weight never rises above its prior."""
    out = {}
    live = {(r["footprint"], r["market"]): r for r in record(
        replayed=False, cal=cal, store=store) if r["footprint"] in LEAN_FOOTPRINTS}
    replay = {(r["footprint"], r["market"]): r for r in record(
        replayed=True, cal=cal, store=store) if r["footprint"] in LEAN_FOOTPRINTS}
    for key in set(live) | set(replay):
        r = live.get(key)
        if r is None or r["stats"].get("n_eff", 0) < SCORE_MIN_N:
            r = replay.get(key) or r
        if r is not None and r["verdict"] == W.VERDICT_AGAINST:
            out[key] = (0.0, True)
    return out


# ── calibration ──────────────────────────────────────────────────────────

def calibrate(board: dict) -> int:
    """One direction call per lean at or past LEAN_AT, on the morning live
    run only, graded by the existing 03:30 resolver. No money path reads
    this agent's trust (risk_gate reads pretrade_sanity; the brain reads
    sauron_mind)."""
    if board.get("replayed") or board.get("run") != "morning":
        return 0
    from ai_agents.calibration import log_direction_prediction
    n = 0
    targets = []
    for key in ROW_ORDER:
        r = (board.get("rows") or {}).get(key) or {}
        targets.append((ROWS[key]["graded_on"], r.get("lean"),
                        r.get("lean_from") or []))
    for sym, cells in ((board.get("instruments") or {}).get("cells") or {}).items():
        lean = (cells or {}).get("_lean") or {}
        targets.append((sym, lean.get("lean"), lean.get("from") or []))
    for proxy, lean, lean_from in targets:
        if lean is None or abs(lean) < LEAN_AT:
            continue
        try:
            got = log_direction_prediction(
                CALIBRATION_AGENT, proxy, "up" if lean > 0 else "down",
                horizon_hours=CALIBRATION_HORIZON_H,
                confidence=CALIBRATION_CONFIDENCE,
                notes="lean from: " + ", ".join(lean_from))
            n += got is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("[big money] calibration call on %s failed: %s",
                           proxy, e)
    return n
