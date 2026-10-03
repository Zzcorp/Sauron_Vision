"""THE POSITIONING MAP (2026-10-03): who is already placed, where their
stops are, where the market is pulled — and what that means for one side.

The operator: "calculate the chances other bot teams take those trades or
the contrary one... understand how other actors are already placed and
how they will behave depending on their targets and stops... identify the
liquidity pools... give them a visual". Said honestly first: nobody can
see another desk's orders, and no number here is a probability that
"other bots take this trade". What CAN be read, and is:

  THE CROWD   one score, -1 (crowd net short) to +1 (crowd net long), from
              the components the platform already stores, each weighted
              and each said when it cannot be read:
                cot_speculators  the large speculators' 3-year COT index
                                 (smart_money.cot_read), the crowd itself
                cot_commercials  the hedgers' index, the other side of the
                                 crowd's trade, half weight
                funding          the perpetual's funding rate (crypto):
                                 longs pay when positive
                volume           the flow of the last VOLUME_WINDOW bars:
                                 the share of volume on up-closes, half
                                 weight (flow, not positioning)
                sentiment        the newest social snapshot
                                 (scraping.SentimentSnapshot), half weight
              and its label: crowded long/short, leaning long/short,
              balanced, unread.
  THE STOPS   the pools above and below the mark (smart_money.living_levels:
              equal highs/lows of POOL_MIN_TOUCHES swings or more, else the
              held swings). The longs keep their stops under the pools
              below; the shorts over the pools above.
  THE PATH    two legs. The HUNT: the crowd's stops are the first place the
              market goes — under the pools below with a crowd long, over
              the pools above with a crowd short, the nearer pool when it
              is balanced. The DRAW: after the hunt, the pool on the bias's
              side (smart_money.ict_read); the opposite pool without a bias.
  THE ODDS    the proving ground's verdict on the path's claim — that a
              pool sweep reverses — from the `pool_sweep` family
              (backtester/proving/families.py) on this class, in this
              direction: PROVEN, PROMISING, FAILED, INSUFFICIENT, or
              unjudged until `manage.py prove generate` has run.
  YOUR SIDE   for a ticket: with the crowd (your stop sits where the hunt
              goes — keep it beyond the pool, which the anti-hunt stop
              already does, or wait for the sweep) or against it (the hunt
              works for you, the draw is against you); and the share of the
              measurable crowd on your side, (score + 1) / 2 for a buy.

Information, never a gate: the ticket shows it, the chart captions it, the
position review reads it, the sizing does not change here (the COT scale
on real-money entries is smart_money's, unchanged). Nothing raises.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEFRAME = "4h"
MIN_BARS = 30
#: |score| at or above: crowded; at or above LEAN: leaning; under: balanced.
CROWDED = 0.5
LEAN = 0.2
#: Funding per 8h at which the score saturates: 0.05% is a heavy market.
FUNDING_HEAVY = 0.0005
#: A funding print older than this says nothing about now.
FUNDING_MAX_AGE_H = 12
#: A social snapshot older than this says nothing about now.
SENTIMENT_MAX_AGE_D = 3
WEIGHTS = {"cot_speculators": 1.0, "cot_commercials": 0.5, "funding": 1.0,
           "volume": 0.5, "sentiment": 0.5}


def _buy(side) -> bool:
    return str(side or "BUY").upper() in ("BUY", "LONG")


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, float(x)))


def _label(score) -> str:
    if score is None:
        return "unread"
    if score >= CROWDED:
        return "crowded long"
    if score <= -CROWDED:
        return "crowded short"
    if score >= LEAN:
        return "leaning long"
    if score <= -LEAN:
        return "leaning short"
    return "balanced"


# ── 1. THE CROWD ──────────────────────────────────────────────────────────

def _funding(symbol, now):
    """The newest funding print for a crypto symbol (Binance perpetual
    symbols end in USDT), or None."""
    from market_data.models_live import FundingRate
    names = [symbol]
    if symbol.endswith("USD") and not symbol.endswith("USDT"):
        names.append(symbol + "T")
    row = (FundingRate.objects
           .filter(symbol__in=names,
                   timestamp__gte=now - timedelta(hours=FUNDING_MAX_AGE_H))
           .order_by("-timestamp").first())
    return row


def crowd_read(symbol, asset_class="", df=None, *, now=None) -> dict:
    """{score, label, components: {name: {score, weight, words, ...}}} —
    every component read, the unreadable ones said with their reason."""
    from bot_program import smart_money as sm
    now = now or timezone.now()
    comps = {}

    cot = sm.cot_read(symbol, "BUY", now=now)
    if cot.get("spec_index") is not None:
        s = (float(cot["spec_index"]) - 50.0) / 50.0
        comps["cot_speculators"] = {
            "score": round(s, 2), "index": cot["spec_index"],
            "words": (f"speculators' COT index {cot['spec_index']:g}"
                      + (f" (report {cot['report_date']})"
                         if cot.get("report_date") else ""))}
        if cot.get("comm_index") is not None:
            c = -(float(cot["comm_index"]) - 50.0) / 50.0
            comps["cot_commercials"] = {
                "score": round(c, 2), "index": cot["comm_index"],
                "words": f"commercials' COT index {cot['comm_index']:g}"}
    else:
        comps["cot_speculators"] = {"score": None,
                                    "words": cot.get("why") or "no COT"}

    if str(asset_class).lower() == "crypto":
        try:
            row = _funding(symbol, now)
        except Exception as e:  # noqa: BLE001 — an unread print is said
            row = None
            logger.debug("[positioning] %s funding unread: %s", symbol, e)
        if row is not None:
            rate = float(row.funding_rate or 0)
            comps["funding"] = {
                "score": round(_clip(rate / FUNDING_HEAVY), 2), "rate": rate,
                "words": (f"funding {rate * 100:+.3f}% per 8h: "
                          f"{'longs pay' if rate > 0 else 'shorts pay' if rate < 0 else 'flat'}")}
        else:
            comps["funding"] = {"score": None,
                                "words": f"no funding print inside "
                                         f"{FUNDING_MAX_AGE_H}h"}

    if df is not None:
        vol = sm.volume_read(df, "BUY")
        p = vol.get("pressure")
        if p is not None and p > 0:
            up_share = 1.0 / (1.0 + float(p))
            comps["volume"] = {
                "score": round(_clip((up_share - 0.5) * 4.0), 2),
                "pressure": round(float(p), 2),
                "words": (f"{up_share * 100:.0f}% of the recent volume on "
                          f"up-closes")}
        else:
            comps["volume"] = {"score": None,
                               "words": (vol.get("why")
                                         or "no up or down closes to read "
                                            "the flow")}

    try:
        from instruments.models import Instrument
        from scraping.models import SentimentSnapshot
        inst = Instrument.objects.filter(symbol=symbol).first()
        snap = None
        if inst is not None:
            snap = (SentimentSnapshot.objects
                    .filter(instrument=inst,
                            timestamp__gte=now - timedelta(
                                days=SENTIMENT_MAX_AGE_D))
                    .order_by("-timestamp").first())
        if snap is not None:
            comps["sentiment"] = {
                "score": round(_clip(float(snap.composite_score or 0)), 2),
                "source": snap.source,
                "words": f"social sentiment {float(snap.composite_score):+.2f} "
                         f"({snap.source})"}
    except Exception as e:  # noqa: BLE001
        logger.debug("[positioning] %s sentiment unread: %s", symbol, e)

    num = den = 0.0
    for name, c in comps.items():
        if c.get("score") is None:
            continue
        w = WEIGHTS.get(name, 0.5)
        c["weight"] = w
        num += w * c["score"]
        den += w
    score = round(num / den, 2) if den else None
    return {"score": score, "label": _label(score), "components": comps}


# ── 2. THE STOPS AND THE PATH ─────────────────────────────────────────────

def _touches(level: dict) -> int:
    m = re.search(r"\((\d+) touches\)", str(level.get("kind") or ""))
    return int(m.group(1)) if m else 1


def _nearest(levels, side, mark):
    """The nearest pool on `side` of the mark; a held swing or the latest
    extreme when there is no pool; never a round number."""
    cands = [l for l in levels if l["side"] == side
             and l["kind"] != "round number"]
    if not cands:
        return None
    pools = [l for l in cands if l.get("pool")]
    pick = pools or cands
    best = (max(pick, key=lambda l: l["price"]) if side == "below"
            else min(pick, key=lambda l: l["price"]))
    return {"price": best["price"], "kind": best["kind"], "side": side,
            "pool": bool(best.get("pool")), "touches": _touches(best),
            "atr_away": best.get("atr_away")}


def _pool_sweep_odds(asset_class, direction, timeframe=TIMEFRAME) -> dict:
    """The proving ground's newest verdict on `pool_sweep` for this class
    and direction, or unjudged."""
    try:
        from backtester.models_proving import ProvingVerdict
        v = (ProvingVerdict.objects
             .filter(family="pool_sweep", direction=direction,
                     asset_class=asset_class, timeframe=timeframe,
                     policy="care", filter="none")
             .order_by("-created_at").first())
    except Exception as e:  # noqa: BLE001
        return {"verdict": "unjudged", "why": f"unread: {e}"[:120]}
    if v is None:
        return {"verdict": "unjudged",
                "why": (f"no pool_sweep verdict on {asset_class or '—'} yet "
                        f"— manage.py prove generate --families pool_sweep")}
    return {"verdict": v.verdict, "expectancy": v.expectancy,
            "win_rate": v.win_rate, "n": v.trades_n, "why": v.why,
            "run_id": v.run_id}


def _leg_words(leg) -> str:
    """"equal lows 1.09 (2 touches), 1.2 ATR" — the kind without its own
    touch count, said once."""
    if not leg:
        return "no pool"
    kind = re.sub(r"\s*\(\d+ touches\)", "", str(leg.get("kind") or "")).strip()
    return (f"{kind} {leg['price']:g}"
            + (f" ({leg['touches']} touches)" if leg.get("pool") else "")
            + (f", {leg['atr_away']:g} ATR" if leg.get("atr_away") is not None
               else ""))


def positioning_map(symbol, *, asset_class="", direction=None,
                    timeframe=TIMEFRAME, mark=None, now=None,
                    levels=None) -> dict:
    """The whole map for one symbol: {ok, symbol, mark, atr, crowd, stops:
    {below, above}, bias, path: [hunt, draw], odds, words, side: {...}}.
    `direction` adds what the map means for a BUY or a SELL. `levels` is
    a living_levels read the caller already holds (the chart reads them
    once for the lines and the caption both); None reads them here."""
    from bot_program import smart_money as sm
    now = now or timezone.now()
    out = {"ok": False, "symbol": symbol, "asset_class": asset_class,
           "why": "", "words": ""}
    df, swings = sm._bars(symbol, timeframe)
    if df is None or len(df) < MIN_BARS:
        out["why"] = "too few bars for a positioning read"
        out["words"] = f"Positioning unread: {out['why']}."
        return out
    from signals.smc.pivots import atr as _atr
    atr = float(_atr(df)[-1] or 0)
    try:
        px = float(mark) if mark else float(df["close"].values[-1])
    except (TypeError, ValueError):
        px = float(df["close"].values[-1])
    if atr <= 0 or px <= 0:
        out["why"] = "no ATR or no mark"
        out["words"] = f"Positioning unread: {out['why']}."
        return out

    crowd = crowd_read(symbol, asset_class, df, now=now)
    if levels is None:
        lv = sm.living_levels(symbol, px, timeframe=timeframe) or {"levels": []}
        levels = lv["levels"]
    below = _nearest(levels, "below", px)
    above = _nearest(levels, "above", px)
    ict = {}
    try:
        ict = sm.ict_read(df, swings, "BUY", atr, px, now=now) if swings else {}
    except Exception as e:  # noqa: BLE001
        logger.debug("[positioning] %s bias unread: %s", symbol, e)
    bias, conf = ict.get("bias"), ict.get("confidence")

    score = crowd["score"]
    if score is not None and score >= LEAN:
        hunt_side, hunt_why = "below", "the longs' stops"
    elif score is not None and score <= -LEAN:
        hunt_side, hunt_why = "above", "the shorts' stops"
    else:
        near = [l for l in (below, above) if l and l.get("atr_away") is not None]
        if near:
            hunt_side = min(near, key=lambda l: l["atr_away"])["side"]
        else:
            hunt_side = "below" if below else ("above" if above else None)
        hunt_why = "the nearer pool, the crowd being balanced"
    hunt = below if hunt_side == "below" else above if hunt_side == "above" \
        else None
    if bias == "long":
        draw_side = "above"
    elif bias == "short":
        draw_side = "below"
    else:
        draw_side = "above" if hunt_side == "below" else "below"
    draw = above if draw_side == "above" else below
    path = [{"leg": "hunt", "why": hunt_why, **(hunt or {"side": hunt_side})},
            {"leg": "draw",
             "why": (f"the bias is {bias} at {conf:.2f}" if bias and conf
                     is not None else "the other side, no bias"),
             **(draw or {"side": draw_side})}]
    odds = _pool_sweep_odds(asset_class,
                            "long" if hunt_side == "below" else "short",
                            timeframe)

    words = f"Crowd {crowd['label']}"
    said = [c["words"] for c in crowd["components"].values()
            if c.get("score") is not None]
    if said:
        words += " (" + "; ".join(said[:3]) + ")"
    words += "."
    if hunt:
        words += (f" Its stops sit {'under' if hunt_side == 'below' else 'over'}"
                  f" the {_leg_words(hunt)}: a hunt runs there first.")
    else:
        words += " No pool within reach on the hunt's side."
    if draw:
        words += (f" After it, the draw is the {_leg_words(draw)}"
                  + (f" — the bias is {bias} at {conf:.2f}."
                     if bias and conf is not None else "."))
    if odds.get("verdict") not in (None, "unjudged"):
        words += (f" Pool sweeps on {asset_class}: {odds['verdict'].upper()}"
                  + (f" ({odds['expectancy']:+.2f}R a trade, "
                     f"{odds['win_rate'] * 100:.0f}% won)"
                     if odds.get("expectancy") is not None
                     and odds.get("win_rate") is not None else "") + ".")
    else:
        words += " Pool sweeps on this class: not yet judged."

    out.update({"ok": True, "mark": px, "atr": atr, "crowd": crowd,
                "stops": {"below": below, "above": above},
                "bias": bias, "bias_confidence": conf,
                "path": path, "odds": odds, "words": words,
                "levels_n": len(levels)})
    if direction:
        out["side"] = side_read(out, direction)
    return out


# ── 3. YOUR SIDE ──────────────────────────────────────────────────────────

def side_read(pmap: dict, direction) -> dict:
    """What the map means for a BUY or a SELL: {with_crowd, against_crowd,
    share_on_your_side, hunt_hits_you, words}."""
    buy = _buy(direction)
    score = (pmap.get("crowd") or {}).get("score")
    out = {"direction": "BUY" if buy else "SELL", "with_crowd": None,
           "against_crowd": None, "share_on_your_side": None,
           "hunt_hits_you": None, "words": ""}
    hunt = pmap.get("path", [{}])[0] if pmap.get("path") else {}
    hunt_side = hunt.get("side")
    out["hunt_hits_you"] = (hunt_side == "below") if buy else \
        (hunt_side == "above") if hunt_side else None
    if score is None:
        out["words"] = ("The crowd cannot be read on this symbol; the pools "
                        "still say where the stops are.")
        if hunt.get("price"):
            out["words"] += (f" {'Yours would sit' if out['hunt_hits_you'] else 'The hunt runs'}"
                             f" {'under' if hunt_side == 'below' else 'over'} "
                             f"{hunt['price']:g}.")
        return out
    out["share_on_your_side"] = round((score + 1) / 2 if buy
                                      else (1 - score) / 2, 2)
    out["with_crowd"] = bool((score >= LEAN and buy) or (score <= -LEAN
                                                         and not buy))
    out["against_crowd"] = bool((score <= -LEAN and buy) or (score >= LEAN
                                                             and not buy))
    pct = f"{out['share_on_your_side'] * 100:.0f}%"
    if out["with_crowd"]:
        out["words"] = (f"You join the crowd ({pct} of the measurable "
                        f"positioning is on your side): your stop sits where "
                        f"the hunt goes" + (f", {'under' if buy else 'over'} "
                                           f"{hunt['price']:g}" if hunt.get("price")
                                           else "")
                        + " — keep it beyond the pool (the anti-hunt stop does)"
                          " or wait for the sweep.")
    elif out["against_crowd"]:
        out["words"] = (f"You fade the crowd ({pct} on your side): the hunt "
                        + (f"of {hunt['price']:g} " if hunt.get("price") else "")
                        + "works for you; the draw after it is against you — "
                          "the stop beyond it, the target before it.")
    else:
        out["words"] = (f"The crowd is balanced ({pct} on your side): the "
                        f"pools decide, not the positioning.")
    return out


def compact(pmap: dict) -> dict:
    """The map as a ticket, a chart or a review carries it."""
    if not pmap or not pmap.get("ok"):
        return {"ok": False, "words": (pmap or {}).get("words", ""),
                "why": (pmap or {}).get("why", "")}
    crowd = pmap["crowd"]
    return {"ok": True, "label": crowd["label"], "score": crowd["score"],
            "components": {k: {"score": v.get("score"), "words": v.get("words")}
                           for k, v in crowd["components"].items()},
            "stops": pmap["stops"], "bias": pmap["bias"],
            "bias_confidence": pmap["bias_confidence"], "path": pmap["path"],
            "odds": pmap["odds"], "words": pmap["words"],
            "side": pmap.get("side")}
