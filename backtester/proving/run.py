"""The proving ground's runs: the universe, the pooling, the generator.

A verdict is pooled over an ASSET CLASS: one symbol's three years rarely
hold fifty trades of one rule, and a rule that works on EURUSD alone and
nowhere else in forex is an accident, not an edge. Every symbol of the
class with enough history (data.sufficiency) enters; the rest are named
and left out, never padded.

prove_live_rules  every live rule as it trades today, and its short
                  mirror: one candidate each, judged with no correction.
generate          every family x parameter set x direction x filter of a
                  class: chosen on the IN-SAMPLE span only (a bootstrap
                  lower bound, Sidak-corrected for the whole grid), then the
                  shortlist judged once on everything — the holdout seen
                  for the first time — with the same correction. Twenty
                  variants tried is twenty chances to fool oneself; the bar
                  rises with them.
"""
from __future__ import annotations

import uuid

import numpy as np

from backtester.proving import data as pdata
from backtester.proving import judge as pj
from backtester.proving.families import FAMILIES, FILTERS, apply_filter, \
    live_rule_cases
from backtester.proving.simulate import regimes, simulate

#: The classes the bots trade and the proving ground judges.
CLASSES = ("crypto", "forex", "stock", "etf", "index", "commodity")
#: How many in-sample leaders of a class go to the final judgement.
SHORTLIST = 5
#: Simulated trades kept per saved verdict (the newest), for the setup
#: memory; and how many runs' trades are kept before the oldest go.
TRADES_KEPT = 400
RUNS_KEPT = 3


def universe(asset_class=None, timeframe="4h", symbols=None) -> dict:
    """{class: [symbols]} — active instruments with bars at `timeframe`."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    with_bars = set(PriceData.objects.filter(timeframe=timeframe)
                    .values_list("instrument_id", flat=True).distinct())
    qs = Instrument.objects.filter(is_active=True, pk__in=with_bars)
    if asset_class:
        qs = qs.filter(asset_class=asset_class)
    else:
        qs = qs.filter(asset_class__in=CLASSES)
    if symbols:
        qs = qs.filter(symbol__in=[s.upper() for s in symbols])
    out = {}
    for sym, cls in qs.order_by("asset_class", "symbol") \
            .values_list("symbol", "asset_class"):
        out.setdefault(cls, []).append(sym)
    return out


def load_class(symbols, timeframe="4h", asset_class=None) -> dict:
    """{included: [(symbol, df, labels)], excluded: [(symbol, reason)],
    dropped: {symbol: bars}, broken: [(symbol, reason)], adjusted:
    {symbol: [words]}, held: {symbol: moves}, start, end} — the class's
    sufficient histories after THE BAR SANITY (data.sanitize), and the span
    they cover together. A broken series is left out of the run and named;
    the bad bars and spikes dropped from a judged series, the splits it was
    adjusted for and the held moves kept as a market are named per
    symbol."""
    included, excluded, dropped, broken = [], [], {}, []
    adjusted, held = {}, {}
    for sym in symbols:
        df, check = pdata.sanitize(
            pdata.load_history(sym, timeframe, raw=True), asset_class)
        if check["broken"]:
            excluded.append((sym, check["broken"]))
            broken.append((sym, check["broken"]))
            continue
        verdict = pdata.sufficiency(df, timeframe)
        if not verdict["ok"]:
            excluded.append((sym, verdict["reason"]))
            continue
        if check["dropped"]:
            dropped[sym] = check["dropped"]
        if check.get("adjusted"):
            adjusted[sym] = list(check["adjusted"])
        if check.get("held"):
            held[sym] = int(check["held"])
        included.append((sym, df, regimes(df)))
    start = min((df.index[0] for _s, df, _l in included), default=None)
    end = max((df.index[-1] for _s, df, _l in included), default=None)
    return {"included": included, "excluded": excluded,
            "dropped": dropped, "broken": broken,
            "adjusted": adjusted, "held": held,
            "start": start, "end": end}


def data_words(data_detail) -> str:
    """The line a verdict prints about what was not read as stored
    (2026-10-06): "3 bar(s) dropped on XYZ · SPY adjusted for a 10:1 split
    at ... · 41 win(s) excluded past +20R on XYZ (38), ABC (3) · QQQ left
    out: broken from ..." — or "" for a clean run."""
    d = data_detail or {}
    parts = []
    bars = d.get("bars_dropped") or {}
    if bars:
        parts.append(f"{sum(bars.values())} bar(s) dropped on "
                     f"{pj.named_counts(bars)}")
    for sym, said in sorted((d.get("adjusted") or {}).items()):
        parts.append(f"{sym} adjusted for " + ", ".join(said))
    held = d.get("held") or {}
    if held:
        parts.append(f"{sum(held.values())} held move(s) past the class's "
                     f"jump bar traded as a market on "
                     f"{pj.named_counts(held)}")
    skipped = d.get("trades_skipped") or {}
    if skipped:
        from backtester.proving.simulate import SKIP_STOP_FLOOR
        parts.append(f"{sum(skipped.values())} trade(s) skipped "
                     f"({SKIP_STOP_FLOOR}) on {pj.named_counts(skipped)}")
    excl = d.get("trades_excluded") or {}
    if excl:
        parts.append(f"{sum(excl.values())} win(s) excluded past "
                     f"+{pj.PROVING_MAX_TRADE_R:.0f}R on "
                     f"{pj.named_counts(excl)}")
    capped = d.get("trades_capped") or {}
    if capped:
        parts.append(f"{sum(capped.values())} loss(es) capped at "
                     f"-{pj.PROVING_MAX_TRADE_R:.0f}R on "
                     f"{pj.named_counts(capped)}")
    for sym, why in d.get("broken") or []:
        parts.append(f"{sym} left out: {why}")
    return " · ".join(parts)


def _pool(family, direction, params, flt, data, asset_class, timeframe,
          base_cache=None, policy="care"):
    """(trades, open positions, {symbol: trades skipped under the stop
    floor}) pooled over the class's included symbols."""
    trades, open_n, skipped = [], 0, {}
    for sym, df, labels in data["included"]:
        key = (family.key, direction, tuple(sorted(params.items())), sym)
        base = None if base_cache is None else base_cache.get(key)
        if base is None:
            base = family.fn(df, direction,
                             **dict(family.defaults, **params))
            if base_cache is not None:
                base_cache[key] = base
        fires = apply_filter(df, base, direction, flt, timeframe)
        res = simulate(df, fires, direction, asset_class=asset_class,
                       timeframe=timeframe, labels=labels, symbol=sym,
                       policy=policy)
        trades.extend(res["trades"])
        open_n += 1 if res["open"] else 0
        if res.get("skipped"):
            skipped[sym] = skipped.get(sym, 0) + int(res["skipped"])
    return trades, open_n, skipped


def _verdict_row(run_id, family, direction, params, flt, asset_class,
                 timeframe, data, judged, *, generated, live_rule="",
                 policy="care", skipped=None):
    return {
        "run_id": run_id, "family": family.key, "live_rule": live_rule,
        "params": dict(family.defaults, **params), "direction": direction,
        "filter": flt, "policy": policy,
        "asset_class": asset_class, "timeframe": timeframe,
        "generated": generated, "n_candidates": judged["n_candidates"],
        "symbols_n": len(data["included"]),
        "trades_n": judged["all"]["n"], "holdout_n": judged["holdout"]["n"],
        "expectancy": judged["all"]["expectancy"],
        "holdout_expectancy": judged["holdout"]["expectancy"],
        "lower_bound": judged["lower_bound"],
        "stressed_expectancy": judged["stressed"]["expectancy"],
        "win_rate": judged["all"]["win_rate"],
        "payoff": judged["all"]["payoff"],
        "max_dd_r": judged["all"]["max_dd_r"],
        "positive_folds": judged["positive_folds"],
        "verdict": judged["verdict"], "why": judged["why"],
        "detail": {
            "regimes": judged["regimes"], "exits": judged["exits"],
            "folds": judged["folds"], "in_sample": judged["in_sample"],
            "holdout": judged["holdout"],
            "start": data["start"].isoformat() if data["start"] else None,
            "end": data["end"].isoformat() if data["end"] else None,
            "split": judged["split"].isoformat() if data["start"] else None,
            "excluded": [list(x) for x in data["excluded"][:50]],
            # what was not read, and why (2026-10-06; data_words)
            "data": {
                "bars_dropped": dict(data.get("dropped") or {}),
                "broken": [list(x) for x in data.get("broken") or []],
                "adjusted": {s: list(w) for s, w
                             in (data.get("adjusted") or {}).items()},
                "held": dict(data.get("held") or {}),
                "trades_skipped": dict(skipped or {}),
                "trades_excluded": dict(
                    (judged.get("excluded") or {}).get("wins_by_symbol")
                    or {}),
                "trades_capped": dict(
                    (judged.get("excluded") or {}).get("capped_by_symbol")
                    or {}),
            },
        },
        # Transient: the newest simulated trades, kept by _save for the
        # setup memory and never part of the verdict row itself.
        "_trades": sorted(judged.get("trades") or [],
                          key=lambda t: t["entry_ts"])[-TRADES_KEPT:],
    }


def _judge_pool(trades, data, n_candidates):
    if not data["included"]:
        return pj.judge([], start=_EPOCH, end=_EPOCH,
                        n_candidates=n_candidates, data_ok=False,
                        data_reason="no symbol of this class has enough "
                                    "history")
    return pj.judge(trades, start=data["start"], end=data["end"],
                    n_candidates=n_candidates)


def _epoch():
    import pandas as pd
    return pd.Timestamp("1970-01-01", tz="UTC")


_EPOCH = _epoch()


def prove_live_rules(*, asset_class=None, timeframe="4h", symbols=None,
                     save=False, run_id=None) -> list:
    """Every live rule and its short mirror, per class: [row dict]."""
    run_id = run_id or f"rules-{uuid.uuid4().hex[:10]}"
    rows = []
    for cls, syms in universe(asset_class, timeframe, symbols).items():
        data = load_class(syms, timeframe, cls)
        cache = {}
        for fam, direction in live_rule_cases():
            trades, _open, skipped = _pool(fam, direction, {}, "none", data,
                                           cls, timeframe, cache)
            judged = _judge_pool(trades, data, 1)
            live = fam.live_rules.get(direction, "")
            rows.append(_verdict_row(
                run_id, fam, direction, {}, "none", cls, timeframe, data,
                judged, generated=False,
                live_rule=live or f"{fam.key} (short mirror)",
                skipped=skipped))
    if save:
        _save(rows)
    return rows


def generate(*, asset_class=None, timeframe="4h", symbols=None,
             families=None, save=False, run_id=None,
             shortlist=SHORTLIST) -> list:
    """The generator, per class: [row dict] of the judged shortlist."""
    run_id = run_id or f"gen-{uuid.uuid4().hex[:10]}"
    fams = [FAMILIES[k] for k in (families or FAMILIES)]
    rows = []
    for cls, syms in universe(asset_class, timeframe, symbols).items():
        data = load_class(syms, timeframe, cls)
        if not data["included"]:
            continue
        cands = [(f, d, p, flt) for f in fams for d in f.directions
                 for p in f.grid for flt in FILTERS]
        k = len(cands)
        level = pj.sidak(pj.ALPHA, k)
        split = data["start"] + (data["end"] - data["start"]) * \
            (1.0 - pj.HOLDOUT_FRAC)
        cache, scored = {}, []
        for fam, direction, params, flt in cands:
            trades, _open, skipped = _pool(fam, direction, params, flt,
                                           data, cls, timeframe, cache)
            # chosen on the trades the judge will read: past the last
            # guard, a win is not a market's and must not pick a leader,
            # and a loss is read capped
            sane, _absurd = pj.sane_trades(trades)
            ins = [t["r"] for t in sane if t["entry_ts"] < split]
            lower = pj.bootstrap_lower(ins, level) \
                if len(ins) >= pj.MIN_TRADES * (1 - pj.HOLDOUT_FRAC) else None
            scored.append((lower if lower is not None else -np.inf,
                           fam, direction, params, flt, trades, skipped))
        scored.sort(key=lambda x: x[0], reverse=True)
        for lower, fam, direction, params, flt, trades, skipped \
                in scored[:shortlist]:
            judged = _judge_pool(trades, data, k)
            if lower == -np.inf or lower <= 0:
                judged["verdict"] = (pj.INSUFFICIENT
                                     if judged["verdict"] == pj.INSUFFICIENT
                                     else pj.FAILED)
                judged["why"] = ("no in-sample lower bound above zero at "
                                 f"{level:.4f} over {k} candidates — "
                                 + judged["why"])
            rows.append(_verdict_row(run_id, fam, direction, params, flt,
                                     cls, timeframe, data, judged,
                                     generated=True, skipped=skipped))
    if save:
        _save(rows)
    return rows


def compare_exits(*, asset_class=None, timeframe="4h", symbols=None,
                  families=None, policies=None, save=False,
                  run_id=None) -> list:
    """Every exit policy on the SAME signals, per class (2026-10-03): the
    live rules and their mirrors by default, or the given families at
    their defaults, both directions. The trailing stop and the target are
    chosen on history, not by taste; the correction counts the policies
    compared."""
    from backtester.proving.simulate import EXIT_POLICIES
    run_id = run_id or f"exits-{uuid.uuid4().hex[:10]}"
    keys = list(policies or EXIT_POLICIES)
    unknown = [k for k in keys if k not in EXIT_POLICIES]
    if unknown:
        raise ValueError(f"unknown exit policies {unknown}")
    if families:
        cases = [(FAMILIES[f], d) for f in families
                 for d in FAMILIES[f].directions]
    else:
        cases = live_rule_cases()
    rows = []
    for cls, syms in universe(asset_class, timeframe, symbols).items():
        data = load_class(syms, timeframe, cls)
        cache = {}
        for fam, direction in cases:
            if fam.live_rules:
                live = fam.live_rules.get(direction) \
                    or f"{fam.key} (short mirror)"
            else:
                live = fam.key
            for key in keys:
                trades, _open, skipped = _pool(fam, direction, {}, "none",
                                               data, cls, timeframe, cache,
                                               policy=key)
                judged = _judge_pool(trades, data, len(keys))
                rows.append(_verdict_row(
                    run_id, fam, direction, {}, "none", cls, timeframe, data,
                    judged, generated=False, live_rule=live, policy=key,
                    skipped=skipped))
    if save:
        _save(rows)
    return rows


def _save(rows):
    """Verdict rows, each with its newest trades (ProvingTrade); the
    trades of runs older than the RUNS_KEPT newest go."""
    from backtester.models_proving import ProvingTrade, ProvingVerdict
    for r in rows:
        trades = r.pop("_trades", None) or []
        verdict = ProvingVerdict.objects.create(**r)
        ProvingTrade.objects.bulk_create([
            ProvingTrade(verdict=verdict, symbol=str(t.get("symbol") or ""),
                         entry_ts=t["entry_ts"], exit_ts=t["exit_ts"],
                         r=float(t["r"]), mfe=float(t.get("mfe") or 0.0),
                         mae=float(t.get("mae") or 0.0),
                         regime=str(t.get("regime") or ""),
                         reason=str(t.get("reason") or ""),
                         bars=int(t.get("bars") or 0))
            for t in trades], batch_size=500)
    from django.db.models import Max
    runs = list(ProvingVerdict.objects.values("run_id")
                .annotate(newest=Max("created_at")).order_by("-newest")
                .values_list("run_id", flat=True)[:RUNS_KEPT])
    ProvingTrade.objects.exclude(verdict__run_id__in=runs).delete()


def data_report(*, asset_class=None, timeframe="4h", symbols=None) -> dict:
    """{class: {"ok": [(sym, bars, days)], "short": [(sym, reason)],
    "dropped": {sym: bars}, "broken": [(sym, reason)], "adjusted":
    {sym: [words]}, "held": {sym: moves}}} — how much history the proving
    ground actually has to judge on, read after THE BAR SANITY exactly as a
    run reads it."""
    out = {}
    for cls, syms in universe(asset_class, timeframe, symbols).items():
        ok, short, dropped, broken = [], [], {}, []
        adjusted, held = {}, {}
        for sym in syms:
            df, check = pdata.sanitize(
                pdata.load_history(sym, timeframe, raw=True), cls)
            if check["broken"]:
                broken.append((sym, check["broken"]))
                continue
            if check["dropped"]:
                dropped[sym] = check["dropped"]
            if check.get("adjusted"):
                adjusted[sym] = list(check["adjusted"])
            if check.get("held"):
                held[sym] = int(check["held"])
            v = pdata.sufficiency(df, timeframe)
            if v["ok"]:
                ok.append((sym, v["bars"], v["span_days"]))
            else:
                short.append((sym, v["reason"]))
        out[cls] = {"ok": ok, "short": short, "dropped": dropped,
                    "broken": broken, "adjusted": adjusted, "held": held}
    return out
