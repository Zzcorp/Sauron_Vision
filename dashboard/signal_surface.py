"""The six questions every signal has to answer — /signals/ and `signals`.

The operator, reading the 2026-09-12 diagnosis: "since we are making the
setups and signals richer and more complex, the filtering and the information
shown for each signal has to improve". The diagnosis says WHY that is not a
cosmetic ask. A 0.85 signal from a RESEARCH-stage rule that no bot will ever
act on rendered EXACTLY like a 0.85 signal a bot is about to trade at full
size on a live venue, and nothing on the page told them apart. Twenty-six of
twenty-eight rules are at research, so on this platform that is almost every
card.

Six questions, and the first did not exist anywhere:

    (a) CAN ANYTHING ACT ON IT?   `stage_badge`
    (b) WHAT IS THIS RULE WORTH?  `rule_records`
    (c) WHY DID IT FIRE?          `why_block`
    (d) WHAT WOULD IT COST?       on the Signal row itself
    (e) DID ANYONE ACT?           `acted_index`
    (f) ITS OWN GRADE             on the Signal row itself

NO SECOND IMPLEMENTATION OF ANYTHING. (a) calls
`signals.rule_actuator.stage_policy` and `is_rule_active` — the same two
functions the ENTRY path calls, so the badge cannot drift from the gate. (b)
reads `bot_program.evidence.rule_rows`, the ledger's single entry point, and
its `MIN_EVIDENCE_N` floor; below the floor it renders 'unmeasured', never a
number. (e) joins on rule_name + symbol + time because THERE IS NO FOREIGN KEY
from a trade to a signal, and every caption says so.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The five badges, and what each one means for a viewer deciding whether to
# look twice at a card.
BADGE_TRADEABLE = "TRADEABLE"
BADGE_PAPER = "PAPER ONLY"
BADGE_UNREGISTERED = "PAPER ONLY"     # same venue, different reason — see below
BADGE_WATCHED = "WATCHED"
BADGE_PAUSED = "PAUSED"
BADGE_REDUCED = "REDUCED"

# Tone names the templates already understand (badge-<tone>).
_TONE = {
    BADGE_TRADEABLE: "bearish",   # red: real money can move on this
    BADGE_PAPER: "medium",
    BADGE_WATCHED: "low",
    BADGE_PAUSED: "high",
    BADGE_REDUCED: "high",
}


def stage_badge(rule_name: str) -> dict:
    """{label, tone, reason, stage, may_trade, registered} for one rule name.

    Derived from `stage_policy` and `is_rule_active` and NOTHING else. The
    four cases the page has to keep apart:

      TRADEABLE   a live venue stage — live_small or live_full. Real money.
      PAPER ONLY  the paper stage, OR NO RuleControl row at all. Those are the
                  same VENUE and a different fact, so the unregistered case
                  gets its own honest sentence: `stage_policy` fails SAFE, not
                  closed, and treats an unregistered rule as paper at FULL
                  nominal size — not as "blocked".
      WATCHED     research. may_trade is False, and the rule's votes are
                  DROPPED from every bot's consensus — which is why a fleet
                  running twenty-six research rules reads 'net evidence +0.00'.
      PAUSED /    the admin lane (RuleControl.status), which is orthogonal to
      REDUCED     the stage lane and wins the label when it is engaged: a
                  paused rule persists no new signals at all.
    """
    from signals.rule_actuator import is_rule_active, stage_policy

    policy = stage_policy(rule_name)
    stage = policy.get("stage") or ""
    ctrl = _control_row(rule_name)
    # REGISTERED is read from the same condition `stage_policy` itself
    # branches on (`ctrl is None or stage not in STAGE_ORDER`), against the
    # same table — NOT from a substring of its `reason` sentence. Matching on
    # prose would mean that rewording one docstring-adjacent string silently
    # relabels every unregistered rule as a registered paper one, and the
    # page would go on looking exactly as confident as before.
    registered = _is_registered(ctrl)

    if not is_rule_active(rule_name):
        # A PAUSE IS NOT A VENUE GATE, and this badge used to draw it as one:
        # it answered may_trade False for every paused rule, whatever its
        # stage. `is_rule_active` is read in exactly two places — the rule
        # engine's signal WRITE path (signals/tasks.py) and the fast-rule
        # runner — and nowhere else. `scan_all_setups` never consults it, so a
        # paused setup-backed rule keeps scanning and publishing; and the bot
        # ENTRY path consults `stage_policy` alone (asset_engine/base.py:2268,
        # options_bot.py:400), so a bot will act on a signal that ALREADY
        # exists from a paused rule exactly as it would from an unpaused one.
        # dashboard/views.py:866 spells the same asymmetry out for /strategies/.
        # So the pause is reported as the fact it is, and `may_trade` stays
        # the gate's own answer — a badge that claims more protection than the
        # gate delivers is worse than no badge (2026-09-12).
        may = bool(policy.get("may_trade"))
        if may:
            reason = ("PAUSED for new signals only — RuleControl.status is "
                      "paused, which stops the rule engine writing NEW "
                      "signals for this rule. It does not stop the "
                      "opportunity scanner, and it does not stop a bot "
                      f"acting on THIS signal: the entry path reads the "
                      f"stage, and this rule's stage is {stage!r} — "
                      f"{policy.get('reason')}")
        else:
            reason = ("paused — RuleControl.status is paused, so the rule "
                      "engine persists no new signal for this rule; and its "
                      f"stage ({stage!r}) permits no order either — "
                      f"{policy.get('reason')}")
        return {"label": BADGE_PAUSED,
                # A paused rule whose STAGE still opens a venue is not a safe
                # row, and must not be toned like one.
                "tone": _TONE[BADGE_TRADEABLE] if may else _TONE[BADGE_PAUSED],
                "stage": stage, "may_trade": may, "registered": registered,
                "reason": reason}

    ctrl_status = (getattr(ctrl, "status", "") or "") if ctrl else ""
    if ctrl_status == "reduced":
        return {"label": BADGE_REDUCED, "tone": _TONE[BADGE_REDUCED],
                "stage": stage, "may_trade": bool(policy.get("may_trade")),
                "registered": registered,
                "reason": (f"reduced — the admin lane is scaling this rule "
                           f"down; stage is {stage!r}: {policy.get('reason')}")}

    if not registered:
        return {"label": BADGE_UNREGISTERED, "tone": _TONE[BADGE_PAPER],
                "stage": "unregistered", "may_trade": True, "registered": False,
                "reason": ("unregistered - paper venue at full size. There is "
                           "NO RuleControl row for this rule, so stage_policy "
                           "fails safe rather than closed: it may trade, at "
                           "full nominal size, on the paper venue only.")}

    if stage == "research":
        return {"label": BADGE_WATCHED, "tone": _TONE[BADGE_WATCHED],
                "stage": stage, "may_trade": False, "registered": True,
                "reason": ("research stage — may_trade is False: no order is "
                           "ever placed, and this rule's votes are dropped "
                           "from every bot's consensus, which is why the "
                           "fleet reads 'net evidence +0.00'")}

    if stage == "paper" or policy.get("force_paper"):
        return {"label": BADGE_PAPER, "tone": _TONE[BADGE_PAPER],
                "stage": stage, "may_trade": bool(policy.get("may_trade")),
                "registered": True,
                "reason": f"paper venue, full nominal size — {policy.get('reason')}"}

    return {"label": BADGE_TRADEABLE, "tone": _TONE[BADGE_TRADEABLE],
            "stage": stage, "may_trade": True, "registered": True,
            "reason": (f"live venue — {policy.get('reason')}. A bot acting on "
                       f"this signal moves real money.")}


def _control_row(rule_name: str):
    """The rule's RuleControl row, or None — ONE query for both lanes.

    The badge needs two facts off this row: the ADMIN lane (`status`, which
    carries paused/reduced) and whether the rule is registered at all. They
    used to be two separate reads, one of them a substring match on prose.
    """
    from signals.models import RuleControl
    if not rule_name:
        return None
    return RuleControl.objects.filter(rule_name=rule_name).first()


def _is_registered(ctrl) -> bool:
    """`stage_policy`'s own first branch, read from the same table.

    That function treats a missing row AND a row whose `promotion_stage` is
    not in STAGE_ORDER identically — both are "no promotion record", paper
    venue, full size. So must this, or a junk stage value would render as a
    promoted rule.
    """
    from signals.promotion_pipeline import STAGE_ORDER
    return ctrl is not None and getattr(ctrl, "promotion_stage", None) in STAGE_ORDER


def badges_for(rule_names) -> dict:
    """{rule_name: badge} — one `stage_badge` call per DISTINCT rule.

    `stage_policy` takes a NAME and re-reads RuleControl, so calling it per
    card on a fifty-row page would be fifty queries for the ten rules that
    actually produced them. Calling the real function once per distinct name
    keeps the single implementation AND the query budget.
    """
    out = {}
    for name in {n or "" for n in rule_names}:
        try:
            out[name] = stage_badge(name)
        except Exception as e:  # noqa: BLE001 — a card renders regardless
            logger.warning("[signal surface] badge failed for %r: %s", name, e)
            out[name] = {"label": "—", "tone": "medium", "stage": "",
                         "may_trade": False, "registered": False,
                         "reason": f"stage unreadable: {e}"}
    return out


def rule_records(rule_names=None) -> dict:
    """{rule_name: {n, hit_rate, avg_r, measured, floor, window, text}}.

    Straight off `bot_program.evidence.rule_rows` — the ledger's own single
    entry point, never a second grader — and held to the platform's own
    sample floor (`evidence.MIN_EVIDENCE_N`). Below the floor this returns
    `measured False` and the page renders 'unmeasured', because a hit rate
    computed over three signals is not a small number, it is not a number.

    `window` is 'all time': `rule_rows` aggregates every graded Signal ever,
    with no date filter. Saying so is the point — a record with an unnamed
    window is a record nobody can compare to anything.
    """
    try:
        from bot_program.evidence import MIN_EVIDENCE_N, rule_rows
        rows = rule_rows()
    except Exception as e:  # noqa: BLE001
        logger.warning("[signal surface] evidence ledger unreadable: %s", e)
        return {}

    wanted = None if rule_names is None else {n or "" for n in rule_names}
    out = {}
    for row in rows:
        name = row.get("rule") or ""
        if wanted is not None and name not in wanted:
            continue
        n = int(row.get("sig_n") or 0)
        measured = n >= MIN_EVIDENCE_N
        rec = {
            "n": n, "floor": MIN_EVIDENCE_N, "measured": measured,
            "window": "all time",
            "hit_rate": (round(float(row["sig_hit"]) * 100, 1)
                         if measured and row.get("sig_hit") is not None else None),
            "avg_r": (round(float(row["sig_avg"]), 3)
                      if measured and row.get("sig_avg") is not None else None),
            "paper_n": int(row.get("paper_n") or 0),
            "live_n": int(row.get("live_n") or 0),
        }
        rec["text"] = (
            f"{rec['hit_rate']}% hit · {rec['avg_r']:+.2f}R avg over {n} graded "
            f"signals, all time" if measured else
            f"unmeasured — {n} graded signal{'' if n == 1 else 's'}, the "
            f"platform's floor is {MIN_EVIDENCE_N}")
        out[name] = rec
    return out


def why_block(signal, flag=None) -> dict:
    """{source, rows: [{label, value, matched}], caption} — why it fired.

    A scanner signal's reasons live on the linked OpportunityFlag's
    `conditions_evaluated`, one row per condition with its value and whether
    it matched. An engine rule has no flag and carries `sub_scores` instead.
    The block NAMES which of the two it came from, because a reader who does
    not know the source cannot know what the absence of a row means.
    """
    if flag is not None and flag.conditions_evaluated:
        rows = []
        for c in (flag.conditions_evaluated or []):
            if not isinstance(c, dict):
                continue
            details = c.get("details") or {}
            reason = details.get("reason") or details.get("error") or ""
            bits = []
            for k, v in details.items():
                if k in ("reason", "error"):
                    continue
                if isinstance(v, float):
                    v = round(v, 4)
                bits.append(f"{k}={v}")
            rows.append({
                "label": c.get("kind") or "?",
                "value": reason or ", ".join(bits[:4]) or "—",
                "matched": bool(c.get("matched")),
                "gate": bool(c.get("gate")),
                "score": c.get("score"),
            })
        return {"source": "scanner flag",
                "rows": rows,
                "caption": (f"From OpportunityFlag #{flag.pk}, written by the "
                            f"opportunity scanner at the moment it matched — "
                            f"these are the values it saw, not today's.")}

    subs = signal.sub_scores or {}
    rows = []
    for k, v in subs.items():
        if isinstance(v, float):
            v = round(v, 4)
        rows.append({"label": str(k), "value": v, "matched": None,
                     "gate": False, "score": None})
    return {"source": "engine sub-scores",
            "rows": rows,
            "caption": ("From Signal.sub_scores — this signal came from an "
                        "engine rule, which records component scores rather "
                        "than per-condition evaluations. No scanner flag is "
                        "linked to it." if rows else
                        "No scanner flag is linked to this signal and its "
                        "sub_scores are empty, so nothing recorded why it "
                        "fired.")}


def acted_index(signals) -> dict:
    """{signal_id: [trade dicts]} for a page of signals, in ONE query.

    THERE IS NO FOREIGN KEY from AssetBotTrade to Signal. The platform joins
    on rule_name + symbol + time — the same string join RuleControl, the
    graders and the track-record lanes already use — narrowed to trades opened
    at or after the signal, because a position opened BEFORE a signal fired
    cannot have been opened because of it. That join is EVIDENCE, not proof,
    and `ACTED_CAPTION` says so wherever it is rendered.
    """
    from django.db.models import Q

    from bot_program.models import AssetBotTrade

    signals = list(signals)
    if not signals:
        return {}
    pairs = Q()
    for s in signals:
        if not s.rule_name:
            continue
        pairs |= Q(rule_name=s.rule_name, symbol=s.instrument.symbol,
                   opened_at__gte=s.created_at)
    if not pairs:
        return {}
    try:
        trades = list(AssetBotTrade.objects.filter(pairs).order_by("-opened_at")[:400])
    except Exception as e:  # noqa: BLE001
        logger.warning("[signal surface] acted join failed: %s", e)
        return {}

    out: dict = {}
    for s in signals:
        if not s.rule_name:
            continue
        for t in trades:
            if (t.rule_name == s.rule_name
                    and t.symbol == s.instrument.symbol
                    and t.opened_at >= s.created_at):
                out.setdefault(s.pk, []).append({
                    "id": t.pk, "side": t.side, "qty": float(t.qty or 0),
                    "venue": "PAPER" if t.paper else "LIVE",
                    "status": t.status, "outcome": t.outcome or "",
                    "realized_r": t.realized_r,
                    "opened_at": t.opened_at,
                })
    return out


ACTED_CAPTION = (
    "Joined on rule name + symbol + time, NOT on a foreign key — no trade "
    "row points at a signal. A trade here fired the same rule on the same "
    "symbol after this signal; it is strong evidence, not certainty."
)

COST_NO_CONTEXT = (
    "no config context — the cost of this trade depends on which pool would "
    "take it, and this page is not looking at one"
)

COST_NO_LEVELS = (
    "no levels to weigh — this signal carries no suggested entry or no "
    "suggested target, so there is no planned move to set against the round "
    "trip. Nothing here is a cheap trade or an expensive one; it is an "
    "unpriced one."
)


def configs_for(user):
    """The viewing user's ENABLED bot configs — one query, or [].

    A config is the only thing that makes (d) answerable. The round trip is
    not a property of a signal: it is a property of the pool that would take
    it, which is where `cost_bps`, `min_edge_ratio` and `min_net_rr` live. A
    signal on its own has an entry, a stop and a target and NO idea what any
    of them cost, which is why this block refuses rather than inventing a
    number whenever this returns nothing.

    Disabled configs are excluded: a pool that is switched off would not take
    the trade, so its cost table is not the one that would be paid.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    try:
        from bot_program.models import AssetBotConfig
        return list(AssetBotConfig.objects
                    .filter(user=user, enabled=True)
                    .order_by("asset_class", "name"))
    except Exception as e:  # noqa: BLE001 — the block refuses, the page renders
        logger.warning("[signal surface] configs unreadable: %s", e)
        return []


def _config_for_signal(signal, configs):
    """(cfg, trades_this_symbol) — the pool that would actually take it.

    Preference: a config of the signal's own asset class that LISTS the
    symbol, then any config of that class. The second case is still a real
    answer — `round_trip_cost_fraction` reads the class's cost table and the
    config's own `extras`, not its symbol list — but the two are not the same
    claim, so the caller is told which it got and says so on the page.
    """
    if not configs:
        return None, False
    klass = (getattr(signal.instrument, "asset_class", "") or "")
    same = [c for c in configs if c.asset_class == klass]
    if not same:
        return None, False
    symbol = (signal.instrument.symbol or "").upper()
    for cfg in same:
        if symbol in {str(s).upper() for s in (cfg.symbols or [])}:
            return cfg, True
    return same[0], False


def cost_block(signal, configs=None):
    """(d) WHAT WOULD IT COST — `passes_cost_filter`, or an honest refusal.

    The verdict is the answer of `bot_program.asset_engine.risk_levels
    .passes_cost_filter`, THE gate every bot entry already goes through
    (asset_engine/base.py, options_bot.py and manual_trade.validate_levels
    all call it). Never a second cost arithmetic: a page that computed its
    own round trip would tell the operator a signal clears its costs while
    the entry path silently refused it for not clearing them, and the page
    would be the one that was wrong.

    Three outcomes, and the two refusals are not the same refusal:

      answerable   a config of this asset class exists → (ok, reason) from
                   the gate, with the round trip it charged.
      no context   no enabled config of this class → COST_NO_CONTEXT. The
                   spec's own instruction: say 'no config context' rather
                   than inventing one.
      no levels    the signal has no entry or no target → COST_NO_LEVELS.
                   This is a property of the SIGNAL, not of the reader, so
                   it must not be reported as a missing config.
    """
    entry = signal.suggested_entry
    target = signal.suggested_target
    stop = signal.suggested_stop
    base = {
        "entry": entry, "stop": stop, "target": target,
        "rr": signal.risk_reward_ratio,
        "answerable": False, "ok": None, "verdict": "", "reason": "",
        "config": "", "trades_symbol": False, "cost_pct": None,
    }
    cfg, trades_symbol = _config_for_signal(signal, configs or [])
    if cfg is None:
        base["reason"] = COST_NO_CONTEXT
        return base
    if entry is None or target is None or float(entry or 0) <= 0:
        base["reason"] = COST_NO_LEVELS
        return base

    try:
        from bot_program.asset_engine.risk_levels import (
            passes_cost_filter, round_trip_cost_fraction)
        ok, reason = passes_cost_filter(
            cfg, signal.instrument.symbol, float(entry), float(target),
            stop=(float(stop) if stop is not None else None))
        cost_pct = round(float(round_trip_cost_fraction(
            cfg, signal.instrument.symbol)) * 100, 3)
    except Exception as e:  # noqa: BLE001
        logger.warning("[signal surface] cost gate failed for signal %s: %s",
                       signal.pk, e)
        base["reason"] = (f"the cost gate could not be read for this signal: "
                          f"{e}")
        return base

    base.update({
        "answerable": True, "ok": bool(ok), "cost_pct": cost_pct,
        "config": f"{cfg.name} ({cfg.asset_class}, {cfg.mode})",
        "trades_symbol": trades_symbol,
        "verdict": ("clears its costs" if ok else "does NOT clear its costs"),
        "reason": reason,
    })
    return base


COST_SYMBOL_CAVEAT = (
    "this pool does not list this symbol, so the verdict is its cost model "
    "applied to a trade it would not itself take"
)


# ── The filters ────────────────────────────────────────────────────────────
#
# Today (2026-09-12) /signals/ has exactly ONE filter: ?active=1. Eleven more
# land here, and EVERY ONE of them is a real queryset filter. That is not a
# performance preference: a Python pass over an unbounded queryset would have
# to load every Signal ever written into memory to answer "score above 0.7",
# and the page's own "N of M" header would then be counting a list the
# database never narrowed.
#
# An unknown VALUE is ignored rather than raising. A filter value arrives in a
# URL an operator typed, a bookmark that outlived a vocabulary change, or a
# link someone pasted; a 500 there teaches nothing and loses the page.

STATES = ("active", "closed", "graded", "ungraded")
ACTED = ("yes", "no")
STAGES = ("research", "paper", "live_small", "live_full", "unregistered")


def _stage_filter(qs, stages):
    """Stage, as a queryset filter over the string join.

    A signal has no stage column: the stage lives on RuleControl, joined by
    `rule_name`. Two queries — the names at each requested stage, then one
    `rule_name__in` — rather than a Python pass, so pagination and the count
    stay the database's job.
    """
    from django.db.models import Q

    from signals.models import RuleControl

    known = set(RuleControl.objects.values_list("rule_name", flat=True))
    wanted = [s for s in stages if s in STAGES]
    if not wanted:
        return qs
    names = set(RuleControl.objects
                .filter(promotion_stage__in=[s for s in wanted
                                             if s != "unregistered"])
                .values_list("rule_name", flat=True))
    q = Q(rule_name__in=names) if names else Q(pk__in=[])
    if "unregistered" in wanted:
        # `stage_policy`'s own fifth case: a rule with NO RuleControl row.
        q |= ~Q(rule_name__in=known)
    return qs.filter(q)


def apply_filters(qs, params):
    """(qs, chips, active) — every filter as a real queryset narrowing.

    `chips` is one dict per engaged filter, each carrying the querystring that
    REMOVES it, so a filter is never something the operator has to guess their
    way out of by editing a URL.
    """
    from datetime import timedelta

    from django.db.models import Exists, OuterRef, Q
    from django.utils import timezone

    active: dict = {}

    def _one(key):
        v = (params.get(key) or "").strip()
        return v

    q = _one("q")
    if q:
        qs = qs.filter(instrument__symbol__icontains=q)
        active["q"] = q

    rule = _one("rule")
    if rule:
        qs = qs.filter(rule_name=rule)
        active["rule"] = rule

    stages = [s for s in params.getlist("stage") if s in STAGES]
    if stages:
        qs = _stage_filter(qs, stages)
        active["stage"] = stages

    # The four CLOSED vocabularies. A value outside one is IGNORED, not
    # applied: `?direction=sideways` applied would empty the page and blame
    # the platform, when the honest answer is that "sideways" is not a
    # direction this system has. `q` and `rule` are open-ended, so an
    # unmatched value there is a legitimate zero and stays applied.
    from core.constants import AssetClass, Direction, Urgency

    from signals.models import Signal as _Signal

    asset_class = _one("asset_class")
    if asset_class in {c for c, _ in AssetClass.CHOICES}:
        qs = qs.filter(instrument__asset_class=asset_class)
        active["asset_class"] = asset_class

    direction = _one("direction")
    if direction in {c for c, _ in Direction.CHOICES}:
        qs = qs.filter(direction=direction)
        active["direction"] = direction

    signal_type = _one("signal_type")
    if signal_type in {c for c, _ in _Signal.SIGNAL_TYPES}:
        qs = qs.filter(signal_type=signal_type)
        active["signal_type"] = signal_type

    urgency = _one("urgency")
    if urgency in {c for c, _ in Urgency.CHOICES}:
        qs = qs.filter(urgency=urgency)
        active["urgency"] = urgency

    score_min = _one("score_min")
    if score_min:
        try:
            qs = qs.filter(score__gte=float(score_min))
            active["score_min"] = score_min
        except (TypeError, ValueError):
            pass  # a typed URL, not a crash

    age_hours = _one("age_hours")
    if age_hours:
        try:
            hours = float(age_hours)
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(hours=hours))
            active["age_hours"] = age_hours
        except (TypeError, ValueError):
            pass

    state = _one("state")
    if state in STATES:
        if state == "active":
            qs = qs.filter(is_active=True)
        elif state == "closed":
            qs = qs.filter(is_active=False)
        elif state == "graded":
            qs = qs.filter(is_active=False, realized_r__isnull=False).exclude(outcome="")
        else:  # ungraded: closed, and invisible to the ladder and the ledger
            qs = qs.filter(is_active=False).filter(
                Q(outcome="") | Q(realized_r__isnull=True))
        active["state"] = state

    acted = _one("acted")
    if acted in ACTED:
        from bot_program.models import AssetBotTrade
        # A correlated EXISTS, so "was this acted on" is answered by the
        # database over the whole table instead of by loading it.
        sub = AssetBotTrade.objects.filter(
            symbol=OuterRef("instrument__symbol"),
            rule_name=OuterRef("rule_name"),
            opened_at__gte=OuterRef("created_at"))
        qs = qs.annotate(_acted=Exists(sub)).filter(_acted=(acted == "yes"))
        active["acted"] = acted

    # `?active=1` is the filter this page has always had. It is kept working
    # to the letter: a bookmark from before today must not silently widen.
    if (params.get("active") or "") == "1":
        qs = qs.filter(is_active=True)
        active["active"] = "1"

    chips = []
    for key, value in active.items():
        rest = params.copy()
        rest.pop(key, None)
        rest.pop("page", None)
        values = value if isinstance(value, list) else [value]
        chips.append({
            "key": key,
            "label": key.replace("_", " "),
            "value": ", ".join(str(v) for v in values),
            "remove": rest.urlencode(),
        })
    return qs, chips, active
