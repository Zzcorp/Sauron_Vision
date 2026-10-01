"""ARAGORN (2026-10-02): what trades with real money, decided on what
real money and paper actually did.

The operator: "we are getting plundered ... remove the strategies not
working, promote new proven ones etc, make it pretty autonomous but still
maintainable by Gandalf or me". He chose the BALANCED thresholds and a
guardian that acts on its own from deployment (switch `aragorn`), and
named it Aragorn: the ranger who became king — he decides who rides to
war with real money and who stays behind on paper.

The unit is a PAIR: one rule on one asset class (AssetBotTrade.rule_name,
AssetBotTrade.asset_class — the config's class, the one the bots key
on). Every pair is in one of three states (aragorn_models.PairVerdict):

  live       trades real money at its normal size (a pair with no row)
  probation  trades real money at PROBATION_SIZE of its size
  bench      trades PAPER only — the evidence keeps coming

THE MOVES, every EVALUATE_HOURS (and on `manage.py aragorn run --yes`):
  live -> bench        over its last LIVE_WINDOW real-money closes (within
                       WINDOW_DAYS): n >= BENCH_MIN_N and expectancy <
                       BENCH_EXPECTANCY (R), or its last BENCH_STREAK
                       closes all lost; with fewer than BENCH_MIN_N real
                       closes, a paper record of PAPER_BENCH_MIN_N or more
                       closes under BENCH_EXPECTANCY (80% floor < 0)
  probation -> bench   since probation began: n >= PROBATION_FAIL_N and
                       expectancy < 0, or PROBATION_FAIL_STREAK losses in a
                       row
  probation -> live    since probation began: n >= GRADUATE_N real-money
                       closes, expectancy >= 0 and money >= 0
  bench -> probation   BENCH_DWELL_DAYS on the bench at least, then its
                       PAPER closes since it was benched pass `proven`
  paper rule -> live   a rule still at the paper STAGE with a pair whose
                       paper closes (WINDOW_DAYS) pass `proven`: the rule
                       moves to live_full (explicitly — a RuleControl row
                       created without a stage defaults to live_full, a
                       hazard this module never relies on), the proven
                       pair enters probation and every other class of the
                       rule is benched (the "*" row)
  research -> paper    a rule at the research stage the ladder's own
                       criterion (promotion_pipeline.is_eligible_for_
                       promotion) sends to paper: it starts paper trading

`proven` (PROMOTE_*): n >= 20, expectancy >= +0.15R, the 80% lower bound
of the mean R above 0, profit factor >= 1.3, and its last 10 closes not
negative.

A PINNED row is the operator's: Aragorn reads it, never writes it.
Open positions of a benched pair are not closed by the bench: the position
care (bot_program/position_care.py) manages them like any other.
Every move is a AragornAction row with its numbers.
"""
import logging
import math
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

SWITCH = "aragorn"
EVALUATE_HOURS = 4
WINDOW_DAYS = 60
LIVE_WINDOW = 30

BENCH_MIN_N = 8
BENCH_EXPECTANCY = -0.10
BENCH_STREAK = 4
#: a live pair with too few real-money closes to judge is benched on its
#: PAPER record when that record is long and clearly losing (the operator
#: moved every rule to live_full on 2026-10-01, evidence or not)
PAPER_BENCH_MIN_N = 20

PROBATION_SIZE = 0.25
PROBATION_FAIL_N = 5
PROBATION_FAIL_STREAK = 3
GRADUATE_N = 10

BENCH_DWELL_DAYS = 7
PROMOTE_MIN_N = 20
PROMOTE_EXPECTANCY = 0.15
PROMOTE_Z = 1.2816          # one-sided 80%
PROMOTE_PROFIT_FACTOR = 1.3
PROMOTE_LAST = 10
#: classes and rules Aragorn does not judge: options (the options bot
#: has its own entry path, which reads no verdict) and the operator's own
#: TAKE TRADE lane
SKIP_CLASSES = frozenset({"options"})
SKIP_RULES = frozenset({"manual_take", ""})
#: a research rule demoted (or entered) this recently is not sent back to
#: paper: no daily research <-> paper churn with the 04:30 ladder
RESEARCH_DWELL_DAYS = 14


def is_on() -> bool:
    from core.platform_control import is_component_enabled
    try:
        return bool(is_component_enabled(SWITCH))
    except Exception:  # noqa: BLE001
        return False


# ── the numbers ──────────────────────────────────────────────────────────

def _closes(rule, cls, *, paper, since=None, limit=None, now=None):
    """Graded closes of one pair on one venue, newest first."""
    from bot_program.asset_models import AssetBotTrade
    now = now or timezone.now()
    qs = AssetBotTrade.objects.filter(
        rule_name=rule, asset_class=cls, paper=paper, status="CLOSED",
        realized_r__isnull=False,
        closed_at__gte=max(since or now - timedelta(days=WINDOW_DAYS),
                           now - timedelta(days=WINDOW_DAYS)))
    rows = list(qs.order_by("-closed_at").values_list("realized_r", "pnl"))
    return rows[:limit] if limit else rows


def stats(rows) -> dict:
    """{n, wins, expectancy, sd, lower, profit_factor, money, streak,
    last_expectancy} over rows [(realized_r, pnl)], newest first. streak
    is the run of losses at the newest end."""
    rs = [float(r) for r, _p in rows]
    n = len(rs)
    out = {"n": n, "wins": sum(1 for r in rs if r > 0), "expectancy": None,
           "sd": None, "lower": None, "profit_factor": None,
           "money": round(sum(float(p) for _r, p in rows if p is not None), 2),
           "streak": 0, "last_expectancy": None}
    for r in rs:
        if r < 0:
            out["streak"] += 1
        else:
            break
    if n == 0:
        return out
    m = sum(rs) / n
    out["expectancy"] = round(m, 4)
    if n >= 2:
        sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
        out["sd"] = round(sd, 4)
        out["lower"] = round(m - PROMOTE_Z * sd / math.sqrt(n), 4)
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    out["profit_factor"] = (round(gains / losses, 3) if losses > 0
                            else (None if gains == 0 else 99.0))
    last = rs[:PROMOTE_LAST]
    out["last_expectancy"] = round(sum(last) / len(last), 4)
    return out


def bench_reason(s) -> str:
    """Why a live pair goes to the bench, or ""."""
    if s["n"] >= BENCH_MIN_N and s["expectancy"] is not None \
            and s["expectancy"] < BENCH_EXPECTANCY:
        return (f"expectancy {s['expectancy']:+.2f}R over its last {s['n']} "
                f"real-money closes (bench under {BENCH_EXPECTANCY:+.2f}R from "
                f"{BENCH_MIN_N})")
    if s["streak"] >= BENCH_STREAK:
        return f"its last {s['streak']} real-money closes all lost"
    return ""


def paper_bench_reason(s) -> str:
    """Why a live pair with too little real-money evidence goes to the
    bench on its paper record, or ""."""
    if s["n"] >= PAPER_BENCH_MIN_N and s["expectancy"] is not None \
            and s["expectancy"] < BENCH_EXPECTANCY \
            and s["lower"] is not None and s["lower"] < 0:
        return (f"too few real-money closes to judge, and its paper record "
                f"loses: expectancy {s['expectancy']:+.2f}R over {s['n']} "
                f"paper closes")
    return ""


def probation_fail_reason(s) -> str:
    if s["n"] >= PROBATION_FAIL_N and (s["expectancy"] or 0) < 0:
        return (f"on probation: expectancy {s['expectancy']:+.2f}R over "
                f"{s['n']} real-money closes")
    if s["streak"] >= PROBATION_FAIL_STREAK:
        return f"on probation: {s['streak']} losses in a row"
    return ""


def graduate_reason(s) -> str:
    if s["n"] >= GRADUATE_N and (s["expectancy"] or 0) >= 0 \
            and s["money"] >= 0:
        return (f"probation passed: {s['n']} real-money closes, expectancy "
                f"{s['expectancy']:+.2f}R, money not negative")
    return ""


def proven_reason(s) -> str:
    """Why a pair's PAPER record earns real money, or ""."""
    if s["n"] < PROMOTE_MIN_N:
        return ""
    ok = (s["expectancy"] is not None
          and s["expectancy"] >= PROMOTE_EXPECTANCY
          and s["lower"] is not None and s["lower"] > 0
          and (s["profit_factor"] or 0) >= PROMOTE_PROFIT_FACTOR
          and (s["last_expectancy"] or 0) >= 0)
    if not ok:
        return ""
    return (f"paper proven: {s['n']} closes, expectancy "
            f"{s['expectancy']:+.2f}R (80% floor {s['lower']:+.2f}R), "
            f"profit factor {s['profit_factor']:g}, last {PROMOTE_LAST} "
            f"{s['last_expectancy']:+.2f}R")


# ── the verdicts ─────────────────────────────────────────────────────────

def verdict_for(rule, cls):
    """The PairVerdict that governs (rule, cls): its own row, else the
    rule's "*" row, else None (live)."""
    from bot_program.aragorn_models import PairVerdict
    if not rule:
        return None
    rows = {v.asset_class: v for v in PairVerdict.objects.filter(
        rule_name=rule, asset_class__in=[cls, PairVerdict.ANY_CLASS])}
    return rows.get(cls) or rows.get(PairVerdict.ANY_CLASS)


def pair_policy(rule, cls) -> dict:
    """{state, force_paper, size, reason} for one entry; no rule, or no
    verdict, reads live at full size. THE VERDICTS BIND WHATEVER THE
    SWITCH SAYS: switching Aragorn OFF stops its moves and its
    position care, it does not hand every benched loser (and every class
    of a rule it promoted for one) back to full-size real money. An
    operator frees a pair with `manage.py aragorn live RULE CLASS`."""
    out = {"state": "live", "force_paper": False, "size": 1.0, "reason": ""}
    if not rule:
        return out
    try:
        v = verdict_for(rule, cls)
    except Exception as e:  # noqa: BLE001 — an unread verdict changes nothing
        logger.warning("[aragorn] verdict unread for %s/%s: %s", rule, cls, e)
        return out
    if v is None or v.state == "live":
        return out
    if v.state == "bench":
        return {"state": "bench", "force_paper": True, "size": 1.0,
                "reason": f"aragorn: {rule} on {cls} is on the bench "
                          f"({v.reason[:120]}) — paper only"}
    return {"state": "probation", "force_paper": False,
            "size": PROBATION_SIZE,
            "reason": f"aragorn: {rule} on {cls} on probation at "
                      f"{PROBATION_SIZE:g}x"}


def _set(rule, cls, state, reason, s, *, by="aragorn", now=None):
    from bot_program.aragorn_models import PairVerdict, AragornAction
    now = now or timezone.now()
    PairVerdict.objects.update_or_create(
        rule_name=rule, asset_class=cls,
        defaults={"state": state, "since": now, "reason": reason,
                  "stats": s, "changed_by": by})
    AragornAction.objects.create(
        at=now, kind=state, rule_name=rule, asset_class=cls,
        detail=reason, stats=s, by=by)


# ── the pass ─────────────────────────────────────────────────────────────

def evaluate(*, apply=False, now=None) -> list:
    """Every move Aragorn would make now, as dicts {kind, rule,
    asset_class, reason, stats}; applied (verdicts written, stages moved,
    the journal kept) when `apply`. Never raises on one pair."""
    from bot_program.asset_models import AssetBotTrade
    from bot_program.aragorn_models import PairVerdict
    now = now or timezone.now()
    moves = []
    since = now - timedelta(days=WINDOW_DAYS)

    def _move(kind, rule, cls, reason, s):
        moves.append({"kind": kind, "rule": rule, "asset_class": cls,
                      "reason": reason, "stats": s})

    # 1 — pairs trading real money: bench or graduate
    live_pairs = set(AssetBotTrade.objects.filter(
        paper=False, status="CLOSED", closed_at__gte=since)
        .exclude(rule_name__in=SKIP_RULES).exclude(asset_class__in=SKIP_CLASSES)
        .values_list("rule_name", "asset_class"))
    for rule, cls in sorted(live_pairs):
        try:
            v = verdict_for(rule, cls)
            if v is not None and v.pinned:
                continue
            state = v.state if v is not None else "live"
            if state == "live":
                # a pair with its OWN live row (graduated, or freed by the
                # operator) is judged on what it did since: the closes that
                # benched it before are history, not evidence
                own = (v.since if v is not None
                       and v.asset_class == cls else None)
                s = stats(_closes(rule, cls, paper=False, since=own,
                                  limit=LIVE_WINDOW, now=now))
                why = bench_reason(s)
                if why:
                    _move("bench", rule, cls, why, s)
            elif state == "probation":
                s = stats(_closes(rule, cls, paper=False, since=v.since,
                                  now=now))
                why = probation_fail_reason(s)
                if why:
                    _move("bench", rule, cls, why, s)
                else:
                    why = graduate_reason(s)
                    if why:
                        _move("live", rule, cls, why, s)
        except Exception as e:  # noqa: BLE001
            logger.warning("[aragorn] %s/%s not judged: %s", rule, cls, e)

    # 1b — pairs allowed real money with too few real closes to judge:
    # their paper record speaks (a rule at a live stage, no verdict or a
    # live one, fewer than BENCH_MIN_N real-money closes)
    try:
        from signals.models_control import RuleControl
        live_rules = set(RuleControl.objects.filter(
            promotion_stage__in=("live_small", "live_full"))
            .values_list("rule_name", flat=True))
    except Exception as e:  # noqa: BLE001
        live_rules = set()
        logger.warning("[aragorn] live rules unread: %s", e)
    judged = {(m["rule"], m["asset_class"]) for m in moves}
    for rule, cls in sorted(set(AssetBotTrade.objects.filter(
            paper=True, status="CLOSED", closed_at__gte=since,
            rule_name__in=live_rules).exclude(asset_class__in=SKIP_CLASSES)
            .values_list("rule_name", "asset_class"))):
        if (rule, cls) in judged:
            continue
        try:
            v = verdict_for(rule, cls)
            if v is not None and (v.pinned or v.state != "live"):
                continue
            own = v.since if v is not None and v.asset_class == cls else None
            n_live = len(_closes(rule, cls, paper=False, since=own,
                                 limit=LIVE_WINDOW, now=now))
            if n_live >= BENCH_MIN_N:
                continue
            s = stats(_closes(rule, cls, paper=True, now=now))
            why = paper_bench_reason(s)
            if why:
                s["live_n"] = n_live
                _move("bench", rule, cls, why, s)
        except Exception as e:  # noqa: BLE001
            logger.warning("[aragorn] %s/%s paper record not judged: %s",
                           rule, cls, e)

    # 2 — benched pairs: back to real money on fresh paper proof. A "*"
    # bench row covers every class of its rule without a row of its own:
    # each such class is judged too, on its paper closes since the "*" row
    benched = []
    for v in PairVerdict.objects.filter(state="bench", pinned=False):
        if v.asset_class != PairVerdict.ANY_CLASS:
            benched.append((v.rule_name, v.asset_class, v.since))
            continue
        own = set(PairVerdict.objects.filter(rule_name=v.rule_name)
                  .values_list("asset_class", flat=True))
        for cls in sorted(set(AssetBotTrade.objects.filter(
                rule_name=v.rule_name, paper=True, status="CLOSED",
                closed_at__gte=v.since).exclude(asset_class__in=SKIP_CLASSES)
                .values_list("asset_class", flat=True)) - own):
            benched.append((v.rule_name, cls, v.since))
    for rule, cls, bench_since in benched:
        try:
            if now - bench_since < timedelta(days=BENCH_DWELL_DAYS):
                continue
            s = stats(_closes(rule, cls, paper=True, since=bench_since,
                              now=now))
            why = proven_reason(s)
            if why:
                _move("probation", rule, cls, why, s)
        except Exception as e:  # noqa: BLE001
            logger.warning("[aragorn] bench %s/%s not judged: %s", rule, cls, e)

    # 3 — rules still at the paper STAGE: a proven pair takes it live
    try:
        from signals.models_control import RuleControl
        paper_rules = set(RuleControl.objects.filter(
            promotion_stage="paper").exclude(status="paused")
            .values_list("rule_name", flat=True))
    except Exception as e:  # noqa: BLE001
        paper_rules = set()
        logger.warning("[aragorn] paper rules unread: %s", e)
    paper_pairs = set(AssetBotTrade.objects.filter(
        paper=True, status="CLOSED", closed_at__gte=since,
        rule_name__in=paper_rules).exclude(asset_class__in=SKIP_CLASSES)
        .values_list("rule_name", "asset_class"))
    promoted_rules = set()
    for rule, cls in sorted(paper_pairs):
        if rule in promoted_rules:
            continue
        try:
            v = verdict_for(rule, cls)
            if v is not None and v.pinned:
                continue
            s = stats(_closes(rule, cls, paper=True, now=now))
            why = proven_reason(s)
            if why:
                _move("rule_live", rule, cls, why, s)
                promoted_rules.add(rule)
        except Exception as e:  # noqa: BLE001
            logger.warning("[aragorn] paper %s/%s not judged: %s", rule, cls, e)

    # 4 — research rules the ladder's own criterion sends to paper
    try:
        from signals.models_control import RuleControl
        from signals.promotion_pipeline import is_eligible_for_promotion
        for rule, entered in RuleControl.objects.filter(
                promotion_stage="research").exclude(status="paused") \
                .values_list("rule_name", "stage_entered_at"):
            if entered and now - entered < timedelta(days=RESEARCH_DWELL_DAYS):
                continue
            if is_eligible_for_promotion(rule) == "paper":
                _move("rule_paper", rule, "", "the ladder's research -> "
                      "paper criterion holds (signal record)", {})
    except Exception as e:  # noqa: BLE001
        logger.warning("[aragorn] research rules not judged: %s", e)

    if apply:
        for m in moves:
            try:
                _apply(m, now=now)
            except Exception as e:  # noqa: BLE001
                logger.error("[aragorn] move %s failed: %s", m, e)
                m["error"] = str(e)
    return moves


def _apply(m, *, now):
    from bot_program.aragorn_models import PairVerdict, AragornAction
    kind, rule, cls = m["kind"], m["rule"], m["asset_class"]
    if kind in ("bench", "probation", "live"):
        _set(rule, cls, kind, m["reason"], m["stats"], now=now)
        return
    from signals.promotion_pipeline import _transition
    with transaction.atomic():
        if kind == "rule_live":
            _transition(rule, "live_full", user=None, reason="auto_promote",
                        notes=f"aragorn: {cls} {m['reason']}"[:500])
            if not PairVerdict.objects.filter(
                    rule_name=rule, asset_class=PairVerdict.ANY_CLASS).exists():
                _set(rule, PairVerdict.ANY_CLASS, "bench",
                     f"the rule went live for {cls} alone; its other classes "
                     f"stay on paper until each proves itself", {}, now=now)
            _set(rule, cls, "probation", m["reason"], m["stats"], now=now)
        elif kind == "rule_paper":
            _transition(rule, "paper", user=None, reason="auto_promote",
                        notes=f"aragorn: {m['reason']}"[:500])
            AragornAction.objects.create(at=now, kind="rule_paper",
                                         rule_name=rule, detail=m["reason"])


def set_by_operator(rule, cls, state, *, by, pin=None, reason=""):
    """An operator's verdict: written, journaled, pinned when asked."""
    from bot_program.aragorn_models import PairVerdict, AragornAction
    if state not in ("live", "probation", "bench"):
        raise ValueError("state must be live, probation or bench")
    now = timezone.now()
    defaults = {"state": state, "since": now, "changed_by": by,
                "reason": reason or f"set by {by}"}
    if pin is not None:
        defaults["pinned"] = bool(pin)
    PairVerdict.objects.update_or_create(rule_name=rule, asset_class=cls,
                                         defaults=defaults)
    AragornAction.objects.create(
        at=now, kind=f"operator_{state}", rule_name=rule, asset_class=cls,
        detail=(reason or f"set by {by}") + (" (pinned)" if pin else ""),
        by=by)


def report_lines(now=None, *, limit=40) -> list:
    """Aragorn's state in plain lines (command, daily report)."""
    from bot_program import market_stress
    from bot_program.aragorn_models import PairVerdict, AragornAction
    now = now or timezone.now()
    cur = market_stress.current(now)
    lines = [f"Aragorn: {'ON' if is_on() else 'OFF'} · posture "
             f"{cur['level'].upper()} (score "
             f"{cur['score'] if cur['score'] is not None else '—'}): "
             f"{cur['why']}"]
    rows = list(PairVerdict.objects.all())
    if rows:
        lines.append("Pairs:")
        for v in rows[:limit]:
            s = v.stats or {}
            exp = s.get("expectancy")
            lines.append(
                f"  {v.state:<9} {v.rule_name}/{v.asset_class}"
                f"{' [pinned]' if v.pinned else ''} since {v.since:%m-%d %H:%M}"
                f" · n {s.get('n', '—')} exp "
                f"{(f'{exp:+.2f}R' if isinstance(exp, (int, float)) else '—')}"
                f" · {v.reason[:90]}")
    acts = list(AragornAction.objects.filter(
        at__gte=now - timedelta(days=1))[:15])
    if acts:
        lines.append("Last 24h:")
        for a in acts:
            lines.append(f"  {a.at:%m-%d %H:%M} {a.kind} "
                         f"{a.rule_name}{'/' + a.asset_class if a.asset_class else ''}"
                         f"{' ' + a.symbol if a.symbol else ''}: {a.detail[:100]}")
    return lines
