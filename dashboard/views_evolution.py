"""Strategy evolution dashboard — Phase 9.

The mutation loop, made legible. Everything this page needs was already
persisted at proposal time and rendered as bare numbers in a table, which
hid the one distinction that matters: a mutant that was MEASURED and lost
looks nothing like a mutant that was never measured at all. The second one
carries a flat -1.0R placeholder, and reading it as a result is the single
most expensive misreading available on this page.

No backtests run here — this view must stay cheap enough for every
registered user to keep open. Every number comes from a stored
`score_details` blob, the schema registry, or one grouped stats query.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

# A fork is the same detector as its parent, so it inherits the parent's
# schema and evaluator, and the registry panel resolves it to that parent
# before it looks either up — otherwise every fork lists as its own
# un-evolvable family and buries the honest count. `core.fork_names` is the
# one parser for the `{parent}_evolved_v{N}` scheme; this module used to carry
# a private copy of its regex under the name `_base_family`.
from core.fork_names import base_family


# How many mutations to render per family, newest first. A family that has
# been churning for months would otherwise render hundreds of cards and turn
# a diagnostic page into a scroll.
MAX_MUTATIONS_PER_FAMILY = 10
MAX_MUTATIONS_TOTAL = 80

# Rows in the decision ledger. The panel says which of the resolved total it
# is showing, so this cap never reads as the total itself.
LEDGER_ROWS = 30

# 90-day window for the live record beside each rule, matching the promotion
# ladder's own reporting window.
RECORD_WINDOW_DAYS = 90


def _live_records(rule_names):
    """{rule_name: {n, expectancy, hit_rate}} over the record window, in ONE
    grouped query.

    The explicit order_by is load-bearing: Signal.Meta.ordering is
    ("-created_at",) and rides straight into the GROUP BY, which would
    split each rule into one row per signal timestamp and report every rule
    as n=1. Selecting rule_name and ordering by it first is the fix.
    """
    from django.db.models import Avg, Count, Q
    from signals.models import Signal

    names = [n for n in rule_names if n]
    if not names:
        return {}
    cutoff = timezone.now() - timedelta(days=RECORD_WINDOW_DAYS)
    rows = (
        Signal.objects
        .filter(rule_name__in=names, is_active=False, expired_at__gte=cutoff)
        .exclude(outcome="").exclude(realized_r__isnull=True)
        .values("rule_name")
        .order_by("rule_name")
        .annotate(n=Count("id"),
                  expectancy=Avg("realized_r"),
                  hits=Count("id", filter=Q(outcome="hit_target")))
    )
    out = {}
    for r in rows:
        n = r["n"] or 0
        out[r["rule_name"]] = {
            "n": n,
            "expectancy": float(r["expectancy"]) if r["expectancy"] is not None else None,
            # A fraction here renders as "1%" for a healthy 55% rule; the
            # template prints a percent sign, so scale at the source.
            "hit_rate": (r["hits"] / n * 100.0) if n else None,
        }
    return out


def _fmt_num(value):
    """Compact display for a parameter value: 50 stays `50`, 0.05 stays
    `0.05`. Unknown is an em-dash — a dash means not measured, never 0."""
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{round(f, 6):g}"


def _pct(value, lo, hi):
    """Where `value` sits inside [lo, hi], as a 0-100 float, or None when the
    parameter has no declared bounds to sit inside."""
    if value is None or lo is None or hi is None:
        return None
    span = float(hi) - float(lo)
    if span <= 0:
        return None
    p = (float(value) - float(lo)) / span * 100.0
    return max(0.0, min(100.0, p))


def _param_moves(mutation, schema):
    """One row per parameter the mutation moved: where the parent sat in the
    declared range, where the mutant sits, and how far it travelled.

    A bare "fast: 30" says nothing about whether 30 is timid or extreme.
    Against the schema's [10, 90] it is immediately readable as near the
    floor, which is the judgement the operator is actually being asked for.
    """
    parent = mutation.parent_params or {}
    mutant = mutation.mutated_params or {}
    changed = list(mutation.parameters_changed or [])
    if not changed:
        # Older rows and hand-built fixtures may not carry the list; derive
        # it rather than render a card with an empty body.
        changed = [k for k in mutant if mutant.get(k) != parent.get(k)]

    moves = []
    for name in changed:
        spec = (schema or {}).get(name) or {}
        lo, hi = spec.get("min"), spec.get("max")
        was, now = parent.get(name), mutant.get(name)
        from_pct, to_pct = _pct(was, lo, hi), _pct(now, lo, hi)
        delta = None
        if was is not None and now is not None:
            try:
                delta = float(now) - float(was)
            except (TypeError, ValueError):
                delta = None
        moves.append({
            "name": name,
            "from_value": _fmt_num(was),
            "to_value": _fmt_num(now),
            "bounded": from_pct is not None and to_pct is not None,
            "lo": _fmt_num(lo),
            "hi": _fmt_num(hi),
            "from_css": None if from_pct is None else f"{from_pct:.2f}%",
            "to_css": None if to_pct is None else f"{to_pct:.2f}%",
            "span_left_css": None if from_pct is None else f"{min(from_pct, to_pct):.2f}%",
            "span_width_css": None if from_pct is None else f"{abs(to_pct - from_pct):.2f}%",
            "delta_str": "—" if delta is None else f"{round(delta, 6):+g}",
            "direction": "flat" if not delta else ("up" if delta > 0 else "down"),
        })
    return moves


# Half the leg-bar track, in percent. The bars diverge from a centre line so
# a negative expectancy reads as a bar pointing the other way, not as a
# shorter positive one.
_LEG_HALF = 46.0

_LEG_SLOTS = (
    ("train_parent", "TRAIN", "parent"),
    ("train_mutant", "TRAIN", "mutant"),
    ("test_parent", "TEST", "parent"),
    ("test_mutant", "TEST", "mutant"),
)


def _evidence_legs(details, min_trades):
    """The four walk-forward legs — train/test x parent/mutant — as bars on a
    shared scale.

    All four share one scale so the eye compares them directly; scaling each
    to itself would draw a +0.02R leg the same size as a +2.0R one.
    """
    values = []
    for key, _window, _side in _LEG_SLOTS:
        d = details.get(key)
        if isinstance(d, dict) and d.get("expectancy") is not None:
            values.append(abs(float(d["expectancy"])))
    scale = max(values) if values else 0.0
    scale = max(scale, 0.5)

    legs = []
    for i, (key, window, side) in enumerate(_LEG_SLOTS):
        raw = details.get(key)
        d = raw if isinstance(raw, dict) else {}
        exp = d.get("expectancy")
        n = d.get("n")
        measured = exp is not None
        width = (abs(float(exp)) / scale * _LEG_HALF) if measured else 0.0
        positive = measured and float(exp) >= 0
        legs.append({
            "key": key,
            "order": i,
            "window": window,
            "side": side,
            # `present` and `measured` are different facts. A leg that ran and
            # found zero trades is the loudest evidence a card can carry, and
            # keying the panel off `measured` alone hid it behind "not
            # recorded" — the opposite of what happened.
            "present": isinstance(raw, dict),
            "measured": measured,
            "value": "—" if not measured else f"{round(float(exp), 2):+.2f}R",
            "n": n,
            # Below the floor this leg contributed nothing but a penalty —
            # the card has to say which leg starved, or "thin data" is a
            # verdict with no evidence behind it.
            "starved": n is not None and n < min_trades,
            "n_display": "—" if n is None else str(n),
            # An unmeasured leg gets no sign at all. Defaulting it to "neg"
            # painted a loss-coloured (if zero-width) bar for a leg that
            # never produced a number to be negative about.
            "sign": ("pos" if positive else "neg") if measured else "none",
            "left_css": f"{50.0 if positive else 50.0 - width:.2f}%",
            "width_css": f"{width:.2f}%",
        })
    return legs


def _score_basis(mutation, details):
    """The baseline the score was actually measured against, or None when the
    row states none.

    A walk-forward score is `mean(train_parent, test_parent) + min(Δtrain,
    Δtest)` — its origin is the parent's two BACKTEST legs. `parent_expectancy`
    is an average of live closed Signals over a different window, universe,
    data source and fill convention, so drawing the arrow from it printed a
    gap between two numbers no single measurement ever produced. The heuristic
    path really is built on that live average, so only that path keeps it.

    A parent leg the scorer never measured is substituted with 0 inside
    `score_mutant_walkforward`; reporting that 0 here as the parent's result
    would invent the very measurement the penalty exists to flag.
    """
    if mutation.score_method == "walk_forward":
        vals = [d["expectancy"] for d in (details.get("train_parent"),
                                          details.get("test_parent"))
                if isinstance(d, dict) and d.get("expectancy") is not None]
        return (sum(vals) / 2.0) if len(vals) == 2 else None
    if (mutation.score_method or "heuristic") == "heuristic":
        return mutation.parent_expectancy
    return None


def _unbacktested_verdict(mutation, has_evaluator):
    """No walk-forward evidence — and three different reasons for that, which
    send the operator after three different things.

    Asserting "no evaluator is registered" on every one of them pointed at a
    missing registration when the actual cause was a scorer exception already
    sitting in the worker log, and called a `manual_backtest` row a backtest
    that never happened.
    """
    method = mutation.score_method or "heuristic"
    if method != "heuristic":
        return {
            "key": "unbacktested", "label": "UNVERIFIED", "tone": "muted",
            "measured": False, "glyph": "○", "flag": "unverified",
            "headline": f"Scored by '{method}', not by the walk-forward scorer.",
            "why": ("This page can only draw walk-forward evidence, and this "
                    "row carries none. Whatever produced the number is not "
                    "recorded here, so nothing on this card vouches for it."),
        }

    # `score_mutant_heuristic` returns a flat 0.0 when the parent has no closed
    # trades, so "expectancy plus drift" would describe arithmetic that never
    # ran on a rule that has never finished a trade.
    drift = ("the parent's live expectancy plus random drift — a stand-in, "
             "not evidence")
    if mutation.parent_expectancy is None:
        drift = ("a flat 0.0R: the parent has no closed trades to average, so "
                 "the heuristic had nothing to drift around")

    if has_evaluator:
        return {
            "key": "unbacktested", "label": "NO BACKTEST", "tone": "muted",
            "measured": False, "glyph": "○", "flag": "placeholder",
            "headline": "The walk-forward scorer failed; the heuristic stood in.",
            "why": (f"An evaluator IS registered for this rule, so the replay "
                    f"was attempted and raised — the proposer logged the "
                    f"exception and fell back. Look in the worker log, not the "
                    f"registry. The score is {drift}."),
        }
    return {
        "key": "unbacktested", "label": "NO BACKTEST", "tone": "muted",
        "measured": False, "glyph": "○", "flag": "placeholder",
        "headline": "Scored by the heuristic placeholder.",
        "why": (f"No evaluator is registered for this rule, so nothing was "
                f"replayed on bars. The score is {drift}."),
    }


def _verdict(mutation, details, min_trades, penalty, basis, has_evaluator):
    """Why this mutation scored what it scored.

    Five outcomes, and only three of them are measurements. NOT MEASURED and
    NO BACKTEST both carry a number that looks like a result and is not one;
    they get their own tone so the eye never files them next to a real loss.
    """
    train_d, test_d = details.get("train_delta"), details.get("test_delta")
    # `sufficient_data` is authoritative when present; older rows predate the
    # key, and for those a missing delta is what insufficiency looked like.
    sufficient = details.get("sufficient_data")
    if sufficient is None:
        sufficient = train_d is not None
    # A row claiming sufficiency with no deltas to show is malformed; treat it
    # as unmeasured rather than comparing None and raising on a live page.
    sufficient = bool(sufficient) and train_d is not None and test_d is not None

    if mutation.score_method != "walk_forward":
        return _unbacktested_verdict(mutation, has_evaluator)

    if not sufficient:
        # With no parent legs the scorer's baseline collapses to zero and the
        # score IS the bare penalty; describing it as "the parent's mean plus"
        # would credit a mean that was never computed.
        tail = (f"The score is that baseline plus a flat {penalty:+.2f}R "
                f"placeholder"
                if basis is not None else
                f"The parent's own legs are unmeasured too, so there is no "
                f"baseline under it: the score is close to the bare "
                f"{penalty:+.2f}R placeholder")
        return {
            "key": "thin", "label": "NOT MEASURED", "tone": "warn",
            "measured": False, "glyph": "⚠", "flag": "placeholder",
            "headline": f"Fewer than {min_trades} trades on at least one leg.",
            "why": (f"No delta could be computed, so none was. {tail} — a "
                    f"penalty for being untested, NOT a measured loss. Read it "
                    f"as 'unknown', never as 'worse'."),
        }

    if train_d > 0 and test_d > 0:
        return {
            "key": "robust", "label": "ROBUST", "tone": "good",
            "measured": True, "glyph": "▲",
            "headline": "Improved on both halves.",
            "why": ("Train and test both beat the parent, so the min() that "
                    "sets the score still lands above it. This is the only "
                    "shape that survives the scorer honestly."),
        }
    if train_d > 0:
        return {
            "key": "overfit", "label": "OVERFIT", "tone": "bad",
            "measured": True, "glyph": "◆",
            "headline": "Gained in-sample, lost out-of-sample.",
            "why": ("The mutant beat the parent on train and lost on test. "
                    "The score takes min(train, test), so the out-of-sample "
                    "loss is what counts — that is the whole point of the split."),
        }
    return {
        "key": "worse", "label": "WORSE THAN PARENT", "tone": "bad",
        "measured": True, "glyph": "▼",
        "headline": "Measured, and it lost.",
        "why": ("The mutant did not beat the parent on the training half, so "
                "the min() is negative before the test half is even consulted. "
                "This is a real result on real trades, not a data penalty."),
    }


_STATE_TONE = {
    "proposed": "open",
    "applied": "good",
    "rejected": "bad",
    "expired": "muted",
}


def _mutation_card(mutation, schema, min_trades, penalty, ttl_days, now,
                   has_evaluator=False):
    details = mutation.score_details or {}
    legs = _evidence_legs(details, min_trades)
    basis = _score_basis(mutation, details)
    verdict = _verdict(mutation, details, min_trades, penalty, basis,
                       has_evaluator)

    score = mutation.proposed_score
    parent_exp = mutation.parent_expectancy
    # Resolved here rather than compared in the template: `{% if a > b %}` with
    # either side None silently reads as False, so a rule with no parent
    # expectancy yet would render its score in loss-red without ever losing.
    # Gated on `measured` as well, because a placeholder score is neither up
    # nor down — colouring it either way is the exact confusion this page
    # exists to prevent.
    score_tone = ""
    if verdict["measured"] and score is not None and basis is not None:
        score_tone = "up" if score > basis else "down"

    # The live record is a real number and a real answer to a different
    # question. It rides beside the arrow, never as the arrow's origin, on
    # every card whose score was not built from it.
    if mutation.score_method == "walk_forward":
        basis_label, live_expectancy = "backtest parent", parent_exp
    elif (mutation.score_method or "heuristic") == "heuristic":
        basis_label, live_expectancy = "live parent", None
    else:
        basis_label, live_expectancy = "unstated basis", parent_exp

    # Expiry only exists while the question is still open; a decided mutation
    # showing a countdown would be inventing urgency that has passed.
    expires_at = days_left = expiry_pct = None
    if mutation.state == "proposed" and mutation.proposed_at:
        expires_at = mutation.proposed_at + timedelta(days=ttl_days)
        remaining = expires_at - now
        days_left = max(0, remaining.days)
        elapsed = (now - mutation.proposed_at).total_seconds()
        expiry_pct = max(0.0, min(100.0, elapsed / (ttl_days * 86400.0) * 100.0))

    return {
        "id": mutation.id,
        "state": mutation.state,
        "state_label": mutation.get_state_display(),
        "state_tone": _STATE_TONE.get(mutation.state, "muted"),
        "forked_rule": mutation.forked_rule,
        "decided_by": getattr(mutation.decided_by, "username", "") or "",
        "proposed_at": mutation.proposed_at,
        "applied_at": mutation.applied_at,
        "moves": _param_moves(mutation, schema),
        "legs": legs,
        "has_leg_detail": any(leg["present"] for leg in legs),
        "train_delta": "—" if details.get("train_delta") is None
                       else f"{round(details['train_delta'], 2):+.2f}R",
        "test_delta": "—" if details.get("test_delta") is None
                      else f"{round(details['test_delta'], 2):+.2f}R",
        "worst_delta": "—" if details.get("worst_delta") is None
                       else f"{round(details['worst_delta'], 2):+.2f}R",
        "verdict": verdict,
        "score": score,
        "parent_expectancy": parent_exp,
        "basis": basis,
        "basis_label": basis_label,
        "live_expectancy": live_expectancy,
        "score_tone": score_tone,
        "score_method": mutation.score_method,
        "expires_at": expires_at,
        "days_left": days_left,
        "expiry_pct_css": None if expiry_pct is None else f"{expiry_pct:.1f}%",
        "expiry_urgent": days_left is not None and days_left <= 3,
        "rationale": mutation.rationale,
    }


def _registry_rows(schema_registry):
    """Every rule family the engine actually runs, and whether evolution can
    touch it.

    "1 registered schema" is a question this page should answer without
    being asked. Listing only the registry answers half of it; listing the
    families that have NO schema, with the reason, answers the rest.
    """
    names = set()
    try:
        from signals.engine import SignalEngine
        names = {base_family(r.name) for r in SignalEngine().rules if r.name}
    except Exception:  # noqa: BLE001
        # Rule construction touches the DB; the panel degrades to what the
        # registry and the control table already know rather than 500ing.
        pass
    try:
        from signals.models import RuleControl
        names.update(base_family(n) for n in RuleControl.objects
                     .order_by("rule_name")
                     .values_list("rule_name", flat=True))
    except Exception:  # noqa: BLE001
        pass
    names.update(schema_registry.keys())
    names.discard("")

    rows = []
    for name in sorted(names):
        schema = schema_registry.get(name)
        params = []
        for pname, spec in (schema or {}).items():
            params.append({
                "name": pname,
                "type": spec.get("type", "—"),
                "lo": _fmt_num(spec.get("min")),
                "hi": _fmt_num(spec.get("max")),
                "default": _fmt_num(spec.get("default")),
                "step": _fmt_num(spec.get("step")) if spec.get("step") else "—",
            })
        rows.append({
            "rule_name": name,
            "evolvable": schema is not None,
            "n_params": len(params),
            "params": params,
            "reason": ("mutations are drawn from these bounds"
                       if schema is not None else
                       "no parameter schema — the proposer skips it at the "
                       "has_schema gate, by design"),
        })
    # Evolvable families first: the panel's job is to show what the loop can
    # reach, with the dormant majority as the honest context underneath.
    rows.sort(key=lambda r: (not r["evolvable"], r["rule_name"]))
    return rows


@login_required
def evolution_dashboard(request):
    from signals.models import RuleControl, RuleMutation
    from signals.evolution import (PARENT_LOOKBACK_DAYS, PROPOSAL_TTL_DAYS,
                                   SCHEMA_REGISTRY, _ensure_rules_registered)
    from signals.evolution_backtest import (INSUFFICIENT_DATA_PENALTY,
                                            MIN_TRADES_PER_SPLIT, has_evaluator)

    # Registration is a lazy per-process side effect; a fresh web worker
    # has never run a proposal task, so without this the panel renders
    # "no schemas registered" while celery is actively proposing.
    _ensure_rules_registered()

    now = timezone.now()
    # Every open question is fetched, uncapped; only the resolved history is
    # windowed. A pending mutation scrolled off the page by old history is a
    # decision the operator never gets to make.
    pending = list(RuleMutation.objects.select_related("decided_by")
                   .filter(state=RuleMutation.STATE_PROPOSED)
                   .order_by("-proposed_at"))
    resolved = list(RuleMutation.objects.select_related("decided_by")
                    .exclude(state=RuleMutation.STATE_PROPOSED)
                    .order_by("-proposed_at")[:MAX_MUTATIONS_TOTAL])
    mutations = pending + resolved

    # Headline counts come from the whole table, not the fetched window — the
    # explicit order_by keeps RuleMutation's Meta.ordering ("-proposed_at")
    # out of the GROUP BY, which would otherwise return one row per timestamp
    # and count every state as 1.
    from django.db.models import Count
    state_counts = dict(
        RuleMutation.objects.values("state").order_by("state")
        .annotate(n=Count("id")).values_list("state", "n"))

    # Per-family totals from the whole table, for the same reason as the
    # headline counts: `len(muts)` is the size of an 80-row fetch window, and
    # a family with 300 mutations rendered "mutations 80 · 70 older not shown"
    # as though it had counted them. Same GROUP BY caveat — the explicit
    # order_by keeps Meta.ordering ("-proposed_at") out of it.
    fam_totals = dict(
        RuleMutation.objects.values("parent_rule").order_by("parent_rule")
        .annotate(n=Count("id")).values_list("parent_rule", "n"))

    # Forks are fetched unwindowed. Built from the same 80-row window, an
    # applied mutation older than that window dropped its fork off the page
    # while the forked rule was still trading — and while the strip's FORKS
    # count, sourced from the whole table, still counted it.
    fork_muts = list(RuleMutation.objects
                     .filter(state=RuleMutation.STATE_APPLIED)
                     .exclude(forked_rule="")
                     .order_by("parent_rule", "-proposed_at"))

    # ── Lineage: parent rule → its mutations → which of them forked ──────
    controls = {c.rule_name: c for c in RuleControl.objects.all()}
    record_names = set()
    by_parent = {}
    for mut in mutations:
        by_parent.setdefault(mut.parent_rule, []).append(mut)
        record_names.add(mut.parent_rule)
        if mut.forked_rule:
            record_names.add(mut.forked_rule)
    forks_by_parent = {}
    for mut in fork_muts:
        forks_by_parent.setdefault(mut.parent_rule, []).append(mut)
        record_names.add(mut.parent_rule)
        record_names.add(mut.forked_rule)
    records = _live_records(record_names)

    def _node(name):
        ctrl = controls.get(name)
        rec = records.get(name) or {}
        return {
            "name": name,
            "stage": getattr(ctrl, "promotion_stage", "") or "",
            "status": getattr(ctrl, "status", "") or "",
            "params": getattr(ctrl, "parameters", None) or {},
            "known": ctrl is not None,
            "n_90d": rec.get("n") or 0,
            "expectancy_90d": rec.get("expectancy"),
            "hit_rate_90d": rec.get("hit_rate"),
        }

    families = []
    # A family whose every row aged out of the window still has a fork
    # trading; rendering it card-less with an honest "older, not shown" line
    # beats omitting the parent from the lineage altogether.
    for parent_name in set(by_parent) | set(forks_by_parent):
        muts = by_parent.get(parent_name, [])
        schema = SCHEMA_REGISTRY.get(base_family(parent_name))
        has_eval = has_evaluator(base_family(parent_name))
        # Pending first and never trimmed; the per-family cap only ever eats
        # into settled history.
        fam_open = [m for m in muts if m.state == RuleMutation.STATE_PROPOSED]
        fam_done = [m for m in muts if m.state != RuleMutation.STATE_PROPOSED]
        room = max(0, MAX_MUTATIONS_PER_FAMILY - len(fam_open))
        shown = fam_open + fam_done[:room]
        cards = [_mutation_card(m, schema, MIN_TRADES_PER_SPLIT,
                                INSUFFICIENT_DATA_PENALTY, PROPOSAL_TTL_DAYS,
                                now, has_evaluator=has_eval)
                 for m in shown]
        forks = [{"node": _node(m.forked_rule), "mutation_id": m.id,
                  "applied_at": m.applied_at}
                 for m in forks_by_parent.get(parent_name, [])]
        n_total = fam_totals.get(parent_name, len(muts))
        families.append({
            "parent": _node(parent_name),
            "evolvable": schema is not None,
            "schema_params": sorted((schema or {}).keys()),
            "mutations": cards,
            "forks": forks,
            "n_total": n_total,
            "n_hidden": max(0, n_total - len(shown)),
            "n_pending": len(fam_open),
        })
    # The families with an unanswered question come first — that is the only
    # thing on this page the operator can act on.
    families.sort(key=lambda f: (-f["n_pending"], f["parent"]["name"]))

    open_cards = [c for f in families for c in f["mutations"]
                  if c["state"] == RuleMutation.STATE_PROPOSED]
    n_measured = sum(1 for c in open_cards if c["verdict"]["measured"])
    soonest = [c["days_left"] for c in open_cards if c["days_left"] is not None]

    registry = _registry_rows(SCHEMA_REGISTRY)
    n_evolvable = sum(1 for r in registry if r["evolvable"])

    # The chronological audit trail, across families — who decided what, when.
    # The lineage answers "what happened to this rule"; this answers "what did
    # we do last week", which is a different question and was a real panel.
    #
    # `applied_at` is stamped only by apply_evolution(); reject_evolution() and
    # expire_stale_mutations() record the outcome and not the moment. Falling
    # back to proposed_at dated every rejection and expiry to the day the
    # question was ASKED — understating an expiry by at least the full 14-day
    # TTL, in a column headed "decided", with no other timestamp on the row
    # for an operator to catch it against. Both times are shown, and a
    # decision nobody stamped stays an em-dash.
    ledger = [{
        "id": m.id,
        "parent_rule": m.parent_rule,
        "forked_rule": m.forked_rule,
        "state": m.state,
        "state_label": m.get_state_display(),
        "state_tone": _STATE_TONE.get(m.state, "muted"),
        "proposed_at": m.proposed_at,
        "decided_at": m.applied_at,
        "decided_by": getattr(m.decided_by, "username", "") or "",
    } for m in resolved[:LEDGER_ROWS]]
    n_resolved = sum(n for state, n in state_counts.items()
                     if state != RuleMutation.STATE_PROPOSED)

    # Families whose every row aged out of the fetch window AND that have no
    # fork to anchor them. Without this line the lineage silently omits them
    # and reads as the complete history.
    n_families_hidden = len(set(fam_totals) - {f["parent"]["name"]
                                              for f in families})

    context = {
        "page_id": "evolution",
        "families": families,
        "n_families_hidden": n_families_hidden,
        "registry": registry,
        "ledger": ledger,
        "n_resolved": n_resolved,
        "n_evolvable": n_evolvable,
        "n_families": len(registry),
        "n_dormant": len(registry) - n_evolvable,
        "n_proposed": state_counts.get(RuleMutation.STATE_PROPOSED, 0),
        "n_measured": n_measured,
        "n_unmeasured": len(open_cards) - n_measured,
        "n_applied": state_counts.get(RuleMutation.STATE_APPLIED, 0),
        "n_mutations": sum(state_counts.values()),
        "next_expiry_days": min(soonest) if soonest else None,
        "min_trades": MIN_TRADES_PER_SPLIT,
        "penalty": INSUFFICIENT_DATA_PENALTY,
        "ttl_days": PROPOSAL_TTL_DAYS,
        "record_days": RECORD_WINDOW_DAYS,
        "parent_window_days": PARENT_LOOKBACK_DAYS,
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/evolution.html", context)
