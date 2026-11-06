"""THE EVIDENCE FACTS (the O2 spec A.46; O2a, 2026-11-05): the code facts
the validator's V6 and V10 need, which no O1 code writes (map_wakes trap
13). Written by the render while the minds are on, BEFORE the dossier is
rendered, so PS5 lists them; each a T0 fact with an F-id and a body["fk"]
that fence.fact_kind reads first. Event keys are code ids, never titles.
With the minds off nothing here runs, and the journal stays O1's.

  level_reached  a final 1h venue bar since max(birth, the last check)
                 traded through a pool, swing, sweep, recent extreme or
                 round number of the wake's menu (never BE, CARE or EFF);
                 once per (kind, tf, price): seen["reached"] keeps those
                 keys, never the ids, so a later level under the same id is
                 a new fact
  bar            the final decision bar, on a wake that carries W2
  gap            the gap model of each event the wake's context lists (a
                 print within PRINT_WITHIN_H, a shut within the type's
                 add_pre_shut_h), once per event
  expectation    an earlier decision's expectation, once the decision
                 frame's next bar is final: graded on the stored price,
                 never on a later menu
"""
import logging

from bot_program.orcs.constants import REACHED_KINDS

logger = logging.getLogger(__name__)

#: How many level keys and graded expectations the memory keeps.
KEPT = 400
#: The 1h bars one check reads at most (a first check after a long gap).
MAX_BARS = 48


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _parse(at):
    from django.utils.dateparse import parse_datetime
    try:
        return parse_datetime(str(at)) if at else None
    except (TypeError, ValueError):
        return None


def _hhmm(at) -> str:
    return at.strftime("%H:%M") if hasattr(at, "strftime") else "—"


def _final_rows(frame, now, since=None, limit=MAX_BARS) -> list:
    """[(end, open, high, low, close)] of the frame's FINAL bars, oldest
    first, those ending after `since` only."""
    from bot_program.orcs import bars
    df = bars.final_df(frame, now) if frame is not None else None
    if df is None or not len(df):
        return []
    span = bars.span_of(frame.tf)
    out = []
    for i in range(len(df)):
        end = bars._utc(df.index[i]) + span
        if since is not None and end <= since:
            continue
        out.append((end, float(df["open"].values[i]),
                    float(df["high"].values[i]), float(df["low"].values[i]),
                    float(df["close"].values[i])))
    return out[-int(limit):]


def level_key(level) -> str:
    """A level by its stored reference (kind, tf, price), never its id."""
    return f"{level.get('kind')}|{level.get('tf') or ''}|{level.get('price')}"


def _level_reached(orc, trade, ctx, vctx, now) -> list:
    from bot_program.orcs import bars, journal
    from bot_program.orcs.facts import px
    f1h = bars.frame(trade.symbol, "1h", asset_class=trade.asset_class,
                     now=now, cache=ctx.get("cache"))
    if f1h is None or not f1h.venue:
        return []
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    since = _parse(seen.get("reached_at")) or getattr(orc, "born_at", None)
    rows = _final_rows(f1h, now, since)
    if not rows:
        return []
    done = set(seen.get("reached") or [])
    levels = [lv for lv in vctx.get("menu") or []
              if isinstance(lv, dict) and lv.get("kind") in REACHED_KINDS
              and _f(lv.get("price")) is not None]
    out = []
    for end, _o, high, low, _c in rows:
        for lv in levels:
            price = _f(lv["price"])
            key = level_key(lv)
            if key in done or not (low <= price <= high):
                continue
            done.add(key)
            body = {"fk": "level_reached", "level_id": lv["id"],
                    "kind": lv["kind"], "tf": lv.get("tf") or "",
                    "price": price, "bar_end": end.isoformat(),
                    "symbol": trade.symbol}
            e = journal.append(
                orc, "fact", f"Price reached {lv['id']} ({px(trade, price)})"
                f" on the 1h bar to {_hhmm(end)} UTC.", body=body, fact=True,
                at=now, remember={"reached": journal.add_keys(KEPT, [key])})
            out.append(e.fact_id)
    journal.remember(orc, reached_at=rows[-1][0].isoformat())
    return out


def _bar(orc, trade, ctx, vctx, now) -> list:
    from bot_program.orcs import journal
    from bot_program.orcs.facts import px
    frame = ctx.get("frame")
    rows = _final_rows(frame, now)
    if not rows:
        return []
    end, o, h, lo, c = rows[-1]
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    if seen.get("bar_fact") == end.isoformat():
        return []
    tf = frame.tf
    atr = _f((vctx.get("atr") or {}).get(tf)) or _f(getattr(frame, "atr",
                                                            None))
    moved = (f", {abs(c - o) / atr:.1f} ATR from its open" if atr
             else ", its ATR unmeasured")
    e = journal.append(
        orc, "fact", f"The {tf} bar to {_hhmm(end)} UTC closed at "
        f"{px(trade, c)}{moved}.",
        body={"fk": "bar", "tf": tf, "end": end.isoformat(), "open": o,
              "high": h, "low": lo, "close": c, "symbol": trade.symbol},
        fact=True, at=now, remember={"bar_fact": end.isoformat()})
    return [e.fact_id]


def _gaps(orc, trade, vctx, now) -> list:
    from bot_program.orcs import journal
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    done = set(seen.get("gap_facts") or [])
    out = []
    for code in sorted(vctx.get("events") or {}):
        if code in done:
            continue
        g = (vctx.get("gaps") or {}).get(code) or {}
        n = int(g.get("n") or 0)
        p90 = _f(g.get("p90_r"))
        measured = bool(g.get("measured"))
        p90_t = f"p90 {p90:.2f}R" if p90 is not None else "no p90"
        e = journal.append(
            orc, "fact", f"The gap model for {code}: {n} samples, {p90_t} "
            f"({'measured' if measured else 'unmeasured'}).",
            body={"fk": "gap", "event": code,
                  "kind": str(g.get("kind") or ""), "n": n, "p90_r": p90,
                  "measured": measured, "symbol": trade.symbol},
            fact=True, at=now,
            remember={"gap_facts": journal.add_keys(KEPT, [code])})
        out.append(e.fact_id)
    return out


EXPECTATION_WORDS = {"closes_above": "a close above {id} ({price})",
                     "closes_below": "a close below {id} ({price})"}


def expectation_words(exp, target) -> str:
    """An expectation in words, its price drawn by code."""
    from bot_program.orcs.facts import px
    exp = exp if isinstance(exp, dict) else {}
    level = exp.get("level") if isinstance(exp.get("level"), dict) else {}
    tpl = EXPECTATION_WORDS.get(str(exp.get("kind") or ""))
    if not tpl:
        return "no expectation"
    return tpl.format(id=level.get("level_id") or "—",
                      price=px(target, level.get("price")))


def _expectations(orc, trade, ctx, vctx, now) -> list:
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcJournal
    frame = ctx.get("frame")
    rows = _final_rows(frame, now)
    if not rows:
        return []
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    done = set(str(x) for x in seen.get("expectations_graded") or [])
    out = []
    for d in (OrcJournal.objects.filter(orc_id=orc.pk, kind="decision")
              .order_by("at", "id")):
        body = d.body if isinstance(d.body, dict) else {}
        exp = body.get("expectation")
        if not isinstance(exp, dict) or exp.get("kind") in (None, "", "none"):
            continue
        if str(d.pk) in done:
            continue
        bar = next((r for r in rows if r[0] > d.at), None)
        if bar is None:
            continue
        end, _o, _h, _lo, close = bar
        price = _f((exp.get("level") or {}).get("price"))
        if price is None:
            continue
        hit = close > price if exp["kind"] == "closes_above" else \
            close < price
        words = expectation_words(exp, trade)
        e = journal.append(
            orc, "fact", f"The expectation set at {_hhmm(d.at)} UTC "
            f"({words}) was {'met' if hit else 'missed'}.",
            body={"fk": "expectation", "decision": d.pk,
                  "kind": exp["kind"], "level": exp.get("level"),
                  "result": "hit" if hit else "missed",
                  "bar_end": end.isoformat(), "close": close,
                  "symbol": trade.symbol},
            fact=True, at=now,
            remember={"expectations_graded": journal.add_keys(
                KEPT, [str(d.pk)])})
        out.append(e.fact_id)
    return out


def write(orc, trade, ctx, vctx, *, reasons, now) -> list:
    """Every evidence fact this wake's render owes, before its dossier is
    rendered; the fact ids written. Never raises: a fact that cannot be
    written is logged, and the render goes on."""
    out = []
    steps = [("level_reached", lambda: _level_reached(orc, trade, ctx, vctx,
                                                      now)),
             ("gap", lambda: _gaps(orc, trade, vctx, now)),
             ("expectation", lambda: _expectations(orc, trade, ctx, vctx,
                                                   now))]
    if any(isinstance(r, dict) and r.get("code") == "W2"
           for r in reasons or ()):
        steps.insert(1, ("bar", lambda: _bar(orc, trade, ctx, vctx, now)))
    for name, step in steps:
        try:
            out += step()
        except Exception as e:  # noqa: BLE001 — one fact never stops one
            logger.warning("[orcs] Orc %s: %s evidence not written: %s",
                           orc.pk, name, e)
    return out
