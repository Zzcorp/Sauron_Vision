"""Why a setup never fires — the instrument that ends the silence (2026-09-12).

On 2026-09-12 the live deployment carried 20 active OpportunitySetups, and
sixteen of the twenty-six research-stage rules beside them had produced ZERO
gradable signals in their whole life. Nothing anywhere said why. A setup that
never matches looked exactly like a setup that matches rarely, which looked
exactly like a setup whose data source has been dead since the day it was
seeded. The promotion ladder wants thirty graded signals per rule; at the
observed rate no designed rule reaches that, so no designed rule is ever
promoted, so no designed rule ever trades. That is the silence this module
exists to end.

THE DISTINCTION THAT IS THE WHOLE POINT
---------------------------------------

For every condition, "evaluated and did not match" and "could not evaluate"
are different facts with opposite remedies:

    evaluated and refused   the setup is STRICT — loosen the threshold, widen
                            the window, or accept that it is a rare pattern
    could not evaluate      the setup is BLIND — there are no 1d bars for
                            crypto, no MacroIndicator row for that series_id,
                            no news rows at all. Loosening the threshold of a
                            blind condition changes nothing, ever.

The scanner's evaluators already say which is which, in three different
shapes, and this module keys on the real shapes rather than on a guess:

  1. a top-level `measured: False` on the result — the explicit contract
     `scan_setup` reads to drop a leg from both sides of the weighted average
     (see `_rank_refusal` in opportunity_scanner);
  2. `details["error"]` — the evaluator raised and `scan_setup` caught it;
  3. `details["reason"]` drawn from the data-refusal vocabulary the evaluators
     actually write: "insufficient price data", "need 50 closes", "no bars",
     "only 12 of 60", "MacroIndicator unavailable", "no indicator for CPIAUCSL".

An AUTHORING refusal ("unknown kind", "unknown pattern 'rsi_oversold'", "bad
numeric param") is counted as unevaluable too, because a condition that can
never evaluate is dead whatever killed it — but `sample_reason` carries the
evaluator's own words, so the operator sees which of the two they are looking
at without reading this file.

PURE AND READ-ONLY
------------------

`diagnose_setups` writes nothing. It runs the SCANNER'S OWN `scan_setup` with
`emit=False`, which is a full suppression: `_emit_match` — the only writer in
the module — is reached solely on the `emit` branch, and the `emit=False`
return happens before it. Re-implementing the composite arithmetic here was
the obvious alternative and it is the wrong one: a diagnostic that computes
its own score answers a question about itself, not about the scanner.

Public API
----------

    diagnose_setups(*, setups=None, instruments=None, now=None,
                    near_miss=0.10, limit_instruments=None) -> dict
    diagnose_grading(*, days=30) -> dict
    VERDICTS
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# The five answers, worst-actionable first. The page and the command both sort
# by this order, so "worst first" means the same thing on both surfaces.
VERDICTS = ("blind", "empty", "strict", "near", "fires")

VERDICT_LABEL = {
    "fires": "fires — it has matched somewhere in the population",
    "near": "near — its best composite is within the near-miss band of its threshold",
    "strict": "strict — every condition evaluates, none combine past the threshold",
    "blind": "blind — a condition cannot evaluate on most of the population",
    "empty": "empty — no active instrument is in its asset classes at all",
}

# Substrings of an evaluator's own `details["reason"]` that mean IT NEVER GOT
# TO LOOK. Collected by reading every `"reason":` literal in
# opportunity_scanner.py and evaluators_advanced.py, not invented: a phrase
# added to this list that no evaluator writes silently classifies nothing, and
# a refusal shape missed here is read as a no-match, which is the exact error
# this module was built to stop making.
_DATA_REFUSAL = (
    "insufficient", "need ", "need>", "need ≥", "no bars", "no prior bars",
    "no price bars", "no price data", "no_price_data", "no body history",
    "no volume history", "no level window", "no anchor", "no history",
    "only ", "unavailable", "missing ", "undefined", "no indicator",
    "no observation", "not enough", "zero variance", "empty entry window",
    "no news", "no macro", "window too short", "window too small",
    "no bar range", "not measured", "has not moved",
)

# The other half: the condition is not blind on the data, it is broken on the
# page it was authored on. Kept in the SAME counter — a condition that can
# never evaluate is dead either way — but named apart in `sample_reason` so an
# operator can tell a missing feed from a typo without opening this file.
_AUTHORING_REFUSAL = (
    "unknown kind", "unknown pattern", "unknown mode", "unknown direction",
    "unknown event", "bad ", "invalid ", "self-reference", "must be at least",
)


def _classify(res: dict) -> tuple:
    """('matched' | 'no_match' | 'unevaluable', reason-or-empty).

    `res` is one entry of `scan_setup`'s `conditions` list, which is the
    evaluator's own dict plus {kind, weight, gate}.
    """
    details = res.get("details") or {}
    if res.get("measured") is False:
        return "unevaluable", str(details.get("reason") or "the evaluator did not measure")
    # The SAME statement, written one level down. `_eval_seasonality`,
    # `_eval_funding_carry` (twice) and `_eval_earnings_surprise` all say
    # `measured: False` inside `details` rather than at the top level, where
    # `scan_setup` reads it — so the scanner scores those refusals as measured
    # zeros (that is the scanner's own bug, and it is not this module's to
    # fix). But the evaluator HAS made a machine-readable statement that it
    # never measured, and reading it here costs nothing and removes four
    # evaluators from the substring heuristic below. Without this,
    # "no reported EPS pair for 'AAPL' on or before this scan" matches no
    # token in `_DATA_REFUSAL` and an earnings leg with no EPS row anywhere is
    # reported as a condition that looked and refused — the exact confusion
    # between BLIND and STRICT this module exists to end (2026-09-12).
    if details.get("measured") is False:
        return "unevaluable", str(details.get("reason") or "the evaluator did not measure")
    if details.get("error"):
        return "unevaluable", f"evaluator raised: {details['error']}"
    reason = str(details.get("reason") or "").strip()
    if reason:
        low = reason.lower()
        if any(tok in low for tok in _DATA_REFUSAL):
            return "unevaluable", reason
        if any(tok in low for tok in _AUTHORING_REFUSAL):
            return "unevaluable", reason
    return ("matched" if res.get("matched") else "no_match"), reason


def _percentile(values: list, pct: float) -> Optional[float]:
    """Nearest-rank percentile over an already-sorted-able list, or None.

    Deliberately not numpy and not statistics.quantiles: the population can be
    a single instrument, and `quantiles` raises below n=2 — a diagnostic that
    raises on a one-instrument setup is useless on exactly the setups that are
    most likely to be broken.
    """
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(pct * (len(ordered) - 1)))))
    return round(float(ordered[k]), 4)


def _population(setup, instruments) -> list:
    """The active instruments this setup's asset_classes admit.

    Empty `asset_classes` means ALL — that is the scanner's own reading:
    `scan_setup` gates on `if setup.asset_classes:` before testing membership,
    so an empty list never excludes anything.
    """
    classes = list(setup.asset_classes or [])
    if not classes:
        return list(instruments)
    return [i for i in instruments if i.asset_class in classes]


def _condition_rows(setup) -> list:
    out = []
    for cond in (setup.conditions or []):
        if not isinstance(cond, dict):
            cond = {}
        out.append({
            "kind": cond.get("kind") or "?",
            "params": cond.get("params") or {},
            "gate": bool(cond.get("gate")),
            "weight": float(cond.get("weight", 1.0) or 0.0),
            "n_matched": 0, "n_no_match": 0, "n_unevaluable": 0,
            # A gate that shuts ends the pair, so every condition after it is
            # never reached. Counting silence as a no-match would accuse a
            # perfectly good condition of refusing.
            "n_not_reached": 0,
            "sample_reason": "",
        })
    return out


def _verdict_detail(row) -> str:
    """One plain sentence naming the binding cause, with its number in it.

    Every number in it is a number about THE POPULATION ACTUALLY WALKED. When
    `limit_instruments` capped that population the sentence says so, in the
    sentence itself rather than in a column beside it, because this string is
    rendered on the page, in `setups diagnose`, in `setups show` and in the
    never-fired card, and "relative_volume never does" over 60 of 179
    instruments is a claim about 60 instruments (2026-09-12).
    """
    body = _verdict_body(row)
    if row.get("truncated"):
        return (f"{body} — read over the first {row['n_evaluated']} instrument(s) "
                f"of this setup's asset classes, not all of them: "
                f"`python manage.py setups diagnose` walks the whole universe")
    return body


def _verdict_body(row) -> str:
    thr = row["min_match_score"]
    n = row["n_evaluated"]
    conds = row["conditions"]
    worst = None
    if conds:
        # The condition that most often stopped this setup: the one that
        # matched least, ties broken towards the one that could not evaluate.
        worst = sorted(conds, key=lambda c: (c["n_matched"], -c["n_unevaluable"]))[0]

    if row["verdict"] == "empty":
        classes = ", ".join(row["asset_classes"]) or "every class"
        return (f"no active instrument is in {classes}: the population is "
                f"empty, so the setup was never scanned at all")

    if row["verdict"] == "blind":
        if row["n_no_price"] and not row["n_matched"]:
            return (f"cleared its {thr:.2f} threshold on {row['n_no_price']} of "
                    f"{n} instruments and none of them had a price to build "
                    f"levels from, so no flag could be written")
        blind = [c for c in conds if c["n_unevaluable"] * 2 > max(n, 1)]
        blind.sort(key=lambda c: -c["n_unevaluable"])
        if blind:
            c = blind[0]
            return (f"{c['kind']} could not evaluate on {c['n_unevaluable']} of "
                    f"{n} instruments: {c['sample_reason'] or 'no reason given'}")
        if row["n_quorum_failed"]:
            # No ONE leg died everywhere, but on every instrument enough of
            # them died that the scanner refused the composite. Naming the
            # quorum is the point: the threshold is not what is stopping this
            # setup, and lowering it would change nothing.
            return (f"less than half this setup's authored weight could be "
                    f"measured on {row['n_quorum_failed']} of {n} instruments, "
                    f"so the scanner refused the composite on every one of "
                    f"them — the {thr:.2f} threshold was never the binding "
                    f"constraint")
        return (f"a condition could not evaluate on most of the {n} "
                f"instruments scanned")

    if row["verdict"] == "fires":
        return (f"matched on {row['n_matched']} of {n} instruments; best "
                f"composite {row['composite_max']:.2f} on "
                f"{row['best_instrument'] or '—'} against a {thr:.2f} threshold")

    firing = sum(1 for c in conds if c["n_matched"] > 0)
    best = row["composite_max"]
    best_txt = f"{best:.2f}" if best is not None else "—"
    tail = ""
    if worst is not None and worst["n_matched"] == 0:
        tail = (f": {firing} of {len(conds)} conditions fire somewhere, "
                f"{worst['kind']} never does")
    if row["n_quorum_failed"]:
        # These pairs have NO composite in the distribution above — the
        # scanner refused them for want of measured weight — so a sentence
        # that said "every condition evaluates" without them would be wrong
        # about the instruments it is silently not describing.
        tail += (f"; a further {row['n_quorum_failed']} instrument(s) measured "
                 f"less than half this setup's authored weight and were "
                 f"refused before any threshold was applied")
    if row["verdict"] == "near":
        return (f"best composite {best_txt} against a {thr:.2f} threshold on "
                f"{n} instruments, {row['n_near_miss']} of them inside the "
                f"near-miss band{tail}")
    # "every condition evaluates" is only true when nothing was refused for
    # want of measured weight; with a quorum failure in the population it is
    # the one claim this sentence must not make.
    opener = ("the best composite is" if row["n_quorum_failed"]
              else "every condition evaluates and the best composite is")
    return (f"{opener} {best_txt} against a {thr:.2f} threshold on "
            f"{n} instruments{tail}")


def diagnose_setups(*, setups=None, instruments=None, now=None,
                    near_miss: float = 0.10,
                    limit_instruments: Optional[int] = None) -> dict:
    """Why each active setup does or does not fire. WRITES NOTHING.

    Returns {as_of, n_setups, n_instruments, seconds, near_miss, by_verdict,
    setups: [...]}. `seconds` is the wall clock of this pass over the real
    population — the number the cadence decision in the RUNBOOK rests on, so
    it is measured here rather than estimated anywhere else.

    `limit_instruments` truncates the population per setup. It exists for a
    fast page render, and a truncated pass says so on every row it returns
    (`truncated: True`) because a verdict taken over 40 of 179 instruments is
    a verdict about 40 instruments.
    """
    from django.utils import timezone

    from instruments.models import Instrument
    from signals.models import OpportunitySetup
    from signals.opportunity_scanner import CrossSectionalField, scan_setup

    started = time.perf_counter()
    now = now or timezone.now()
    if setups is None:
        setups = list(OpportunitySetup.objects.filter(is_active=True))
    else:
        setups = list(setups)
    if instruments is None:
        instruments = list(Instrument.objects.filter(is_active=True))
    else:
        instruments = list(instruments)

    # ONE field for the whole diagnostic, exactly as `scan_all_setups` builds
    # one for the whole pass: a rank taken against a different universe than
    # the scanner's would answer about a different market.
    field = CrossSectionalField(instruments, now=now)

    rows = []
    for setup in setups:
        pop = _population(setup, instruments)
        truncated = False
        if limit_instruments is not None and len(pop) > limit_instruments:
            pop = pop[:limit_instruments]
            truncated = True

        conds = _condition_rows(setup)
        composites: list = []
        best_score, best_symbol = None, None
        n_matched = n_gate = n_no_price = n_quorum = 0
        for inst in pop:
            try:
                res = scan_setup(setup, inst, now=now, as_of=False, emit=False,
                                 field=field)
            except Exception as e:  # noqa: BLE001 — one bad pair must not
                # void the whole reading; the pair is counted as unevaluable
                # against every condition it never reached.
                logger.warning("[setup_diagnostics] %s x %s raised: %s",
                               setup.name, inst.symbol, e)
                for c in conds:
                    c["n_not_reached"] += 1
                continue

            evaluated = res.get("conditions") or []
            for idx, c in enumerate(conds):
                if idx >= len(evaluated):
                    c["n_not_reached"] += 1
                    continue
                verdict, reason = _classify(evaluated[idx])
                c[f"n_{verdict}"] += 1
                if verdict == "unevaluable" and not c["sample_reason"] and reason:
                    c["sample_reason"] = reason[:200]

            reason = res.get("reason")
            if reason == "gate_failed":
                n_gate += 1
                continue
            if reason == "asset_class_filter":
                # Cannot happen — `_population` already applied the same gate —
                # but counted rather than assumed away.
                continue
            # A QUORUM-FAILED pair carries a `score`, and it is NOT a number
            # the scanner ever compares to the threshold: `scan_setup` drops
            # every unmeasured leg from both sides of the weighted average and
            # then refuses the whole pair because less than half the authored
            # weight answered, so what rides out on `score` is the surviving
            # legs renormalised to themselves. Counting it here put a
            # confident 1.00 in `composite_max` for a setup that can never
            # fire, drew the page's p90 bar clean past its own threshold
            # notch, and — where such a score lands inside the band — reported
            # verdict 'near', which tells an operator to lower a threshold
            # that is not what is stopping them. The quorum is counted
            # instead, and named in the sentence (2026-09-12).
            if reason == "not_enough_measured":
                n_quorum += 1
                continue
            score = res.get("score")
            if score is not None:
                composites.append(float(score))
                if best_score is None or float(score) > best_score:
                    best_score, best_symbol = float(score), inst.symbol
            if reason == "no_price_data":
                n_no_price += 1
            elif res.get("matched"):
                n_matched += 1

        thr = float(setup.min_match_score or 0.0)
        floor = thr - float(near_miss)
        n_near = sum(1 for s in composites if floor <= s < thr)
        row = {
            "name": setup.name,
            "pk": setup.pk,
            "direction": setup.direction,
            "min_match_score": thr,
            "asset_classes": list(setup.asset_classes or []),
            "n_evaluated": len(pop),
            "n_matched": n_matched,
            "n_near_miss": n_near,
            "n_gate_skipped": n_gate,
            "n_no_price": n_no_price,
            "n_quorum_failed": n_quorum,
            "composite_p50": _percentile(composites, 0.50),
            "composite_p90": _percentile(composites, 0.90),
            "composite_max": round(best_score, 4) if best_score is not None else None,
            "best_instrument": best_symbol,
            "conditions": conds,
            "truncated": truncated,
        }

        # Verdict priority: an empty population precedes everything (nothing
        # was measured, so no other answer is available); a setup that FIRES is
        # not broken whatever else is true of it; 'near' precedes 'blind'
        # because a setup landing inside the band has a threshold an operator
        # can act on today, and its blind leg is named in the sentence anyway.
        blind_conds = [c for c in conds if c["n_unevaluable"] * 2 > max(len(pop), 1)]
        if not pop:
            row["verdict"] = "empty"
        elif n_matched > 0:
            row["verdict"] = "fires"
        elif n_near > 0:
            row["verdict"] = "near"
        # A setup that reached NO comparable composite because the quorum
        # refused every pair is blind by the only definition that matters: it
        # never measured enough of itself to have an opinion. `blind_conds`
        # usually catches it — one dead leg on the whole population — but not
        # when a DIFFERENT leg dies on each instrument, and that setup is
        # exactly as unfireable.
        elif (blind_conds or (n_no_price and not n_matched)
              or (n_quorum and not composites)):
            row["verdict"] = "blind"
        else:
            row["verdict"] = "strict"
        row["verdict_detail"] = _verdict_detail(row)
        rows.append(row)

    by_verdict = {v: 0 for v in VERDICTS}
    for r in rows:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    rows.sort(key=lambda r: (VERDICTS.index(r["verdict"])
                             if r["verdict"] in VERDICTS else 99,
                             -r["n_evaluated"], r["name"]))
    return {
        "as_of": now,
        "n_setups": len(setups),
        "n_instruments": len(instruments),
        "near_miss": float(near_miss),
        "seconds": round(time.perf_counter() - started, 3),
        "by_verdict": by_verdict,
        "setups": rows,
    }


# ── The grading audit ──────────────────────────────────────────────────────
#
# A signal that closes with no outcome, or with an outcome and no realized_r,
# is INVISIBLE to the promotion ladder (`promotion_pipeline._stats_since`
# excludes both) and to every evidence lane (`bot_program.evidence.rule_rows`
# excludes both). It was produced, it cost a scan, and it taught nothing. On a
# platform whose ladder needs thirty graded signals per rule, a leak here is
# indistinguishable from a scanner that never fired — and it is a different
# repair.

def diagnose_grading(*, days: int = 30) -> dict:
    """Per rule: what the window's signals became. READ-ONLY.

    The cohort is signals CREATED in the window, and the counters say what
    happened to them — not "signals closed in the window", which would credit
    a rule for grading a signal it fired two months ago and hide the ones it
    fired yesterday and never graded.

    Counters, from the same columns `_stats_since` and `evidence.rule_rows`
    filter on:
        n_created            rows created in the window
        n_closed             is_active False
        n_graded             outcome set AND realized_r not null  ← the only
                             ones the ladder and the ledger can see
        n_closed_ungraded    closed, outcome set, realized_r NULL
        n_expired_no_outcome closed, outcome blank
    """
    from datetime import timedelta

    from django.db.models import Count, Q
    from django.utils import timezone

    from signals.models import Signal

    now = timezone.now()
    cutoff = now - timedelta(days=int(days))
    closed = Q(is_active=False)
    graded = closed & ~Q(outcome="") & Q(realized_r__isnull=False)
    ungraded = closed & ~Q(outcome="") & Q(realized_r__isnull=True)
    no_outcome = closed & Q(outcome="")

    agg = (Signal.objects.filter(created_at__gte=cutoff)
           .values("rule_name")
           .annotate(n_created=Count("id"),
                     n_closed=Count("id", filter=closed),
                     n_graded=Count("id", filter=graded),
                     n_closed_ungraded=Count("id", filter=ungraded),
                     n_expired_no_outcome=Count("id", filter=no_outcome))
           .order_by())

    rules = []
    totals = {"n_created": 0, "n_closed": 0, "n_graded": 0,
              "n_closed_ungraded": 0, "n_expired_no_outcome": 0}
    for r in agg:
        row = {"rule_name": r["rule_name"] or "—"}
        for k in totals:
            row[k] = int(r[k] or 0)
            totals[k] += row[k]
        row["n_lost"] = row["n_closed_ungraded"] + row["n_expired_no_outcome"]
        row["leak_pct"] = (round(row["n_lost"] / row["n_closed"] * 100, 1)
                           if row["n_closed"] else None)
        rules.append(row)

    totals["n_lost"] = (totals["n_closed_ungraded"]
                        + totals["n_expired_no_outcome"])
    # None, not 0.0, when nothing closed: a leak rate with no closed signal
    # behind it is unmeasured, and a 0% there reads as "the grader is fine".
    totals["leak_pct"] = (round(totals["n_lost"] / totals["n_closed"] * 100, 1)
                          if totals["n_closed"] else None)
    rules.sort(key=lambda r: (-r["n_lost"], -r["n_created"], r["rule_name"]))
    return {
        "as_of": now,
        "days": int(days),
        "rules": rules,
        "totals": totals,
        "worst": [r for r in rules if r["n_lost"] > 0][:10],
    }
