"""SIZE BY PROOF (2026-10-07): real money follows the proving ground's
verdict on the rule, the class and the side.

The order of 2026-10-01 put 36 rules at live_full (reason manual_promote),
most of them with 0 graded signals: the promotion ladder was walked by
hand, and nothing on the entry path asked whether the rule had ever been
proven. The proving ground (backtester/proving) judges every live rule as
it trades today, per asset class and per side, every night; until now its
verdict was something to read, never something the money obeyed.

For a LIVE bot-lane entry (the AssetBot lane and the options lane), the
newest saved live-rules verdict for (rule, instrument class, side)
decides:

  FAILED       is refused (skips.PROVING_FAILED): no real money on a rule
               the proving ground measured as losing on this class and
               side, whatever its graded record says;
  PROVEN       keeps full size;
  anything     (PROMISING, INSUFFICIENT, no saved verdict, no side, a
  else         class the proving ground does not judge, a rule no family
               replays) enters at REDUCED — unless the rule's own graded
               record proves it on the floor's own measure
               (promotion_pipeline.proven_record), when it keeps full size
               (LIVE_PROVEN).

PROMISING is "worth watching on paper, never on money" in the judge's own
words (judge.py); the operator chose a reduced live size for it rather
than none. REDUCED is SIZE_FACTORS["live_small"], imported and never
typed: the quarter stage_policy gives live_small, and Aragorn's
PROBATION_SIZE. The proof caps the STAGE factor (stage_with_proof): an
unproven live_full rule is cut to the quarter, a live_small rule is not
cut twice, and PROVEN never raises anything. Aragorn, the posture, smart
money, the admin and allocator lanes, the correlation taper and the elite
scale still multiply on top, exactly as they do for a live_small rule.

The verdict is read per key: the newest rules- row (RULES_RUN_PREFIX) for
that (live_rule, asset_class, direction) at the live rules' own timeframe,
exit policy and filter — so a one-class `prove rules --class X --save`
does not unjudge the other classes, the compare_exits rows (whose "care"
rows carry the same live_rule strings) never count, and bollinger's short
reads its own row. A verdict that cannot be read is a reduced entry:
never full size, and never a refusal on a read that could not be made.

This is not base.py's eToro proof (ETORO_PROVEN, the venue's measured
behaviour for a class); it is the rule's.

GATE is read at call time: off in tests/__init__.py (the suite sizes
hundreds of live entries on rules no proving run ever judged), on in
tests/test_size_by_proof.py.

Never import backtester.proving.run or .families at module level here:
they pull numpy and pandas, and tests/__init__.py imports this module when
the test package loads.
"""
from __future__ import annotations

import logging

from signals.promotion_pipeline import SIZE_FACTORS

logger = logging.getLogger(__name__)

#: The switch, read at call time (tests/__init__.py turns it off).
GATE = True
#: The live rules' bars (signals/rules/technical_rules.py): the verdict
#: on the rule as it trades.
TIMEFRAME = "4h"
#: prove_live_rules' own exit policy and filter (run.py): the live rule at
#: its defaults, as it trades.
POLICY = "care"
FILTER = "none"

PROVEN, LIVE_PROVEN, UNPROVEN, FAILED = (
    "proven", "live_proven", "unproven", "failed")
#: The reduced live size: the quarter stage_policy gives live_small and
#: Aragorn's PROBATION_SIZE. Imported, never typed, so the three agree.
REDUCED = SIZE_FACTORS["live_small"]
MULTIPLIER = {PROVEN: 1.0, LIVE_PROVEN: 1.0, UNPROVEN: REDUCED, FAILED: 0.0}
#: What a trade row keeps of the proof (metadata["proof"]).
META_KEYS = ("tier", "multiplier", "cut", "words", "verdict", "run_id",
             "verdict_at", "asset_class", "direction", "trades_n",
             "expectancy", "holdout_expectancy", "lower_bound", "record")

_LONG_WORDS = frozenset({"BUY", "LONG", "BULLISH"})
_SHORT_WORDS = frozenset({"SELL", "SHORT", "BEARISH"})


def side_of(direction) -> str:
    """"long" for BUY, LONG or BULLISH (any case), "short" for SELL, SHORT
    or BEARISH, "" for anything else (a HOLD has no side). The proving
    ground's own words for the two sides (families.LONG, families.SHORT);
    the live signals say LONG/SHORT and the bots BUY/SELL."""
    d = str(direction or "").strip().upper()
    if d in _LONG_WORDS:
        return "long"
    if d in _SHORT_WORDS:
        return "short"
    return ""


def _rules_rows(**filters):
    """The saved live-rules verdicts: prove_live_rules' rows only (the
    rules- prefix, generated False), at the live rules' timeframe, exit
    policy and filter."""
    from backtester.models_proving import ProvingVerdict
    from backtester.proving.run import RULES_RUN_PREFIX
    return ProvingVerdict.objects.filter(
        generated=False, run_id__startswith=RULES_RUN_PREFIX,
        timeframe=TIMEFRAME, policy=POLICY, filter=FILTER, **filters)


def newest_verdict(rule_name: str, asset_class: str, side: str):
    """The newest live-rules row FOR THIS KEY, or None.

    Per key, not per run: a one-class `prove rules --class X --save` is the
    newest run and holds no row for the other classes, which keep their
    own newest verdict. The prefix shuts out compare_exits' rows (their
    "care" rows carry the same live_rule). The exact live_rule match keeps
    a long-only rule off "<family> (short mirror)" and gives bollinger's
    short its own row. Never memory.rule_case: it returns the FIRST match,
    which is the long."""
    return (_rules_rows(live_rule=rule_name, asset_class=asset_class,
                        direction=side)
            .order_by("-created_at").first())


def proven_cases(rule_name: str, *, cache: dict | None = None) -> list:
    """Sorted ["<class> <side>"] of every (asset_class, direction) whose
    NEWEST live-rules row for `rule_name` reads proven — one query, the
    first row per key taken in Python (SQLite and Postgres agree on that,
    where DISTINCT ON is Postgres only). [] on a failed read, with a
    warning. Read once per tick through `cache`."""
    key = ("proof_cases", rule_name)
    if isinstance(cache, dict) and isinstance(cache.get(key), list):
        return list(cache[key])
    try:
        seen, out = set(), []
        for cls, side, verdict in (
                _rules_rows(live_rule=rule_name)
                .order_by("asset_class", "direction", "-created_at")
                .values_list("asset_class", "direction", "verdict")):
            if (cls, side) in seen:
                continue
            seen.add((cls, side))
            if verdict == PROVEN:
                out.append(f"{cls} {side}")
        out = sorted(out)
    except Exception as e:  # noqa: BLE001 — a label never breaks a page
        logger.warning("[proof] %s: the proving ground's proven cases "
                       "unread (%s)", rule_name, e)
        return []
    if isinstance(cache, dict):
        cache[key] = list(out)
    return out


def _r(x) -> str:
    return "unmeasured" if x is None else f"{float(x):+.2f}R"


def _blank(rule, cls, side) -> dict:
    return {"tier": UNPROVEN, "multiplier": MULTIPLIER[UNPROVEN],
            "words": "", "rule": rule, "asset_class": cls,
            "direction": side, "verdict": "", "run_id": "",
            "verdict_at": "", "trades_n": 0, "holdout_n": 0,
            "expectancy": None, "holdout_expectancy": None,
            "lower_bound": None, "why": "", "record": {}, "unread": ""}


def unread_proof(rule_name, asset_class, direction, error) -> dict:
    """The proof of a verdict that could not be read: UNPROVEN at REDUCED,
    never full size and never a refusal (an unread verdict may be a FAILED
    one, and may as well be a PROVEN one). `error` is the exception, or
    its type name."""
    name = (error if isinstance(error, str)
            else type(error).__name__) or "Exception"
    out = _blank(str(rule_name or ""), str(asset_class or "").strip().lower(),
                 side_of(direction))
    out["unread"] = name
    out["words"] = (f"the proving ground's verdict could not be read "
                    f"({name}) — entered at {REDUCED:g}x, never full size "
                    f"and never a refusal on an unread verdict")
    return out


def proof_for(rule_name: str, asset_class: str, direction: str, *,
              cache: dict | None = None) -> dict:
    """The proof of one live entry: {tier, multiplier, words, rule,
    asset_class, direction (the side), verdict, run_id, verdict_at,
    trades_n, holdout_n, expectancy, holdout_expectancy, lower_bound, why,
    record, unread}.

    `asset_class` is the caller's: the Instrument's class in the bot lane,
    the underlying's Instrument class in the options lane, inst.asset_class
    on the ticket. Never map etf to stock: the proving ground pools etf on
    its own (run.CLASSES).

    The order of judgement: a row read that raises is UNPROVEN and the
    record is NOT read (an unread verdict may be a FAILED one); a FAILED
    row is FAILED whatever the record says; a PROVEN row is PROVEN;
    anything else asks the rule's own graded record
    (promotion_pipeline.proven_record) — LIVE_PROVEN when it proves the
    rule, UNPROVEN otherwise. Read once per (rule, class, side) per tick
    through `cache`; a copy is returned on a hit."""
    rule = str(rule_name or "")
    cls = str(asset_class or "").strip().lower()
    side = side_of(direction)
    key = ("proof", rule, cls, side)
    if isinstance(cache, dict) and isinstance(cache.get(key), dict):
        hit = dict(cache[key])
        hit["record"] = dict(hit.get("record") or {})
        return hit

    out = _blank(rule, cls, side)
    row = None
    reason = ""
    try:
        from backtester.proving import families
        from backtester.proving.run import CLASSES
        if not side:
            reason = f"no side for a {direction or 'blank'} decision"
        elif cls not in CLASSES:
            reason = f"the proving ground judges no {cls} class"
        else:
            row = newest_verdict(rule, cls, side)
            if row is None:
                replayed = {d for fam in families.FAMILIES.values()
                            for d, live in fam.live_rules.items()
                            if live == rule}
                if not replayed:
                    reason = (f"the proving ground replays no family for "
                              f"{rule}")
                elif side not in replayed:
                    reason = (f"the proving ground replays {rule} "
                              f"{'/'.join(sorted(replayed))} only")
                else:
                    reason = (f"no saved live-rules verdict on {cls} {side} "
                              f"— manage.py prove rules --save")
    except Exception as e:  # noqa: BLE001 — unread is reduced, never refused
        logger.warning("[proof] %s %s %s: the proving ground's verdict "
                       "unread (%s) — entered at %gx", rule, cls, side, e,
                       REDUCED)
        return unread_proof(rule, cls, direction, e)

    if row is not None:
        out.update({
            "verdict": str(row.verdict or ""), "run_id": str(row.run_id or ""),
            "verdict_at": (row.created_at.isoformat()
                           if row.created_at else ""),
            "trades_n": int(row.trades_n or 0),
            "holdout_n": int(row.holdout_n or 0),
            "expectancy": row.expectancy,
            "holdout_expectancy": row.holdout_expectancy,
            "lower_bound": row.lower_bound,
            "why": str(row.why or "")[:200]})
        reason = str(row.why or "")[:120]
    head = " ".join(p for p in (
        (out["verdict"].upper() if out["verdict"] else "NOT JUDGED"),
        cls, side) if p)
    date = (f"{row.created_at:%Y-%m-%d}"
            if row is not None and row.created_at else "")

    if out["verdict"] == FAILED:
        out["tier"] = FAILED
        out["words"] = (
            f"FAILED {cls} {side}: {_r(out['expectancy'])} a trade, holdout "
            f"{_r(out['holdout_expectancy'])} over {out['trades_n']} trades "
            f"(proving run of {date}) — {rule}: no real money on a failed "
            f"verdict")
    elif out["verdict"] == PROVEN:
        out["tier"] = PROVEN
        out["words"] = (
            f"PROVEN {cls} {side}: {_r(out['expectancy'])} a trade, holdout "
            f"{_r(out['holdout_expectancy'])}, lower bound "
            f"{_r(out['lower_bound'])} over {out['trades_n']} trades "
            f"(proving run of {date}) — full size")
    else:
        from signals.promotion_pipeline import (
            LOSER_MIN_N, LOSER_THIN_EDGE_R, loser_numbers, proven_record)
        rec = proven_record(rule, cache=cache)
        n = int(rec.get("n") or 0)
        out["record"] = {"n": n, "hit_rate": rec.get("hit_rate"),
                         "expectancy": rec.get("expectancy"),
                         "proven": bool(rec.get("proven"))}
        if rec.get("expectancy") is not None:
            h, e = loser_numbers(rec.get("hit_rate"), rec["expectancy"])
        else:
            h, e = "none", "none"
        if rec.get("proven"):
            out["tier"] = LIVE_PROVEN
            out["words"] = (
                f"{head} — but its own record proves it: {n} graded signals "
                f"all time (both sides, every class), hit {h}, expectancy "
                f"{e} — full size")
        else:
            out["tier"] = UNPROVEN
            out["words"] = (
                f"{head}: {reason} — its own record does not prove it ({n} "
                f"graded signals, expectancy {e}; proof needs {LOSER_MIN_N} "
                f"at {LOSER_THIN_EDGE_R:+.2f}R) — entered at {REDUCED:g}x")
    out["multiplier"] = MULTIPLIER[out["tier"]]
    if isinstance(cache, dict):
        cache[key] = dict(out, record=dict(out["record"]))
    return out


def stage_with_proof(stage: dict, p: dict) -> dict:
    """The stage with the proof folded in: the proof caps the STAGE factor
    at its multiplier — an unproven live_full rule is cut to REDUCED, a
    live_small rule (already REDUCED) is not cut twice, and PROVEN never
    raises anything. Aragorn, the posture and the smart-money scale are
    already in live_size_factor and stay multiplied. stage["proof"] is the
    proof with its `cut`."""
    base = float(SIZE_FACTORS.get(stage.get("stage"), 1.0) or 1.0)
    cut = min(1.0, float(p["multiplier"]) / base)
    out = dict(stage)
    if cut < 1:
        out["live_size_factor"] = (
            float(stage.get("live_size_factor", 1.0)) * cut)
    out["proof"] = dict(p, cut=round(cut, 6))
    return out


def meta_of(p: dict) -> dict:
    """What a trade row keeps of the proof (metadata["proof"])."""
    out = {k: p.get(k) for k in META_KEYS}
    out["words"] = str(out.get("words") or "")[:300]
    rec = p.get("record") or {}
    out["record"] = ({"n": rec.get("n"), "expectancy": rec.get("expectancy"),
                      "hit_rate": rec.get("hit_rate")} if rec else {})
    return out


def cut_note(stage: dict) -> str:
    """"unproven 0.25x: " when the proof cut this entry's stage factor, else
    "". The one spelling of the note: it leads every refusal the cut can
    cause (SIZED_TO_ZERO, VENUE_MIN_SIZE, the venue-fee COST_FILTER,
    LEVERAGE_REFUSED) in the bot lane, and the options lane's."""
    p = (stage or {}).get("proof") or {}
    try:
        cut = float(p.get("cut", 1))
    except (TypeError, ValueError):
        return ""
    return f"unproven {cut:g}x: " if cut < 1 else ""
