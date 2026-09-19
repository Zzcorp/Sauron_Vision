"""THE OCULUS — every cycle this platform runs, on one screen (2026-09-13).

Thirty dashboards existed before this one and each answered its own
question well. None answered the operator's: *is the machine turning, and
which of its wheels is actually engaged?* That question is not a
thirty-first subsystem, so this page owns no data. It reads what the
subsystems already record and does one thing they cannot do individually
— put them side by side without letting the comparison lie.

WHY A COUNT IS THE HARD PART HERE
---------------------------------

The recurring failure in this codebase is not a wrong number. It is a
right number that reads as its opposite:

* "26 rules registered" sounds like coverage. A rule at `research` stage
  cannot place an order AND its signals are dropped from decide()'s vote,
  so registering a rule DEMOTES it relative to never registering one.
* "N configs wear scalp" sounds like adoption. A wearing config may be
  disabled, or on an asset class whose bars nothing writes.
* "the desk chose 40 entries" sounds like allocation. In shadow — the
  default — every candidate executes at full size anyway and 'displaced'
  displaced nothing.
* "0.0R" sounds like breakeven. Below the evidence floor it means nobody
  has measured anything.

So every fact here carries its qualifier in the same breath, and three
values are kept strictly apart:

    a number   — measured
    None       — NOT measurable (no rows, table absent, counter fenced)
    the gate   — whether the component that writes it is even switched on

`core/wall_facts.py` collapses everything to 0 because it is the public
login gateway and must never raise. The Oculus is behind auth and has the
opposite duty: 0 and "unmeasured" are different answers and it prints
them differently. A 0 where None belongs is the exact fabrication
wall_facts exists to abolish, moved one page inward.

FENCING
-------

`oculus()` cannot raise. Every counter runs in its own fence, and a
counter that fails reports None and names itself in `degraded` rather
than taking the page — or worse, its nine healthy neighbours — down.
"""
import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Days of history in the evolution strips.
WINDOW_DAYS = 30

#: A fact whose builder failed, or whose table holds nothing to measure.
UNMEASURED = None

#: WHERE EACH CYCLE IS ANSWERED IN FULL (2026-09-13).
#:
#: A panel that reports a count and offers no way into it is a report, not
#: a command post: the operator reads "12 setups blind", nods, and still
#: has to remember which of thirty pages explains why. These are the
#: drill-downs — the existing pages, unchanged, reached from the cycle
#: that summarises them.
#:
#: SEVERAL DESTINATIONS PER CYCLE, ON PURPOSE. Picking one would be a
#: judgement this map has no business making: the ladder is answered by
#: three pages at three zooms, and allocation by three that size three
#: different things — the account's share per pool, one tick's entries,
#: and per-rule multipliers. One row named "allocator" once hid the
#: second (2026-09-12), and collapsing them here would repeat that.
#:
#: Names only, never paths: a hard-coded "/setups/" survives a route
#: rename and 404s in silence. tests/test_oculus.py reverses every one.
CYCLE_PAGES = {
    "forge": [("ops_dashboard", "Ops"),
              ("system_health", "System Health"),
              ("audit_dashboard", "Audit Log")],
    "book": [("portfolio_overview", "Portfolio"),
             ("positions_list", "Positions"),
             ("desk_dashboard", "Capital Desk")],
    "gates": [("ops_dashboard", "Ops"),
              ("system_health", "System Health")],
    "scan": [("setups_dashboard", "Setups"),
             ("opportunities_dashboard", "Opportunities")],
    "ladder": [("strategies_list", "Strategies"),
               ("promotions_dashboard", "Promotion Ladder"),
               ("rule_control_dashboard", "Rule Controls")],
    "signals": [("signals_list", "Signals"),
                ("performance_dashboard", "Signal Performance")],
    "evolution": [("evolution_dashboard", "Strategy Evolution"),
                  ("generated_dashboard", "Generated Strategies"),
                  ("discoveries_dashboard", "Discoveries")],
    "personas": [("personas_dashboard", "Personalities")],
    "allocation": [("shares_dashboard", "Share Allocator"),
                   ("desk_dashboard", "Capital Desk"),
                   ("allocator_dashboard", "Risk Allocator")],
    "horizon": [("horizon_dashboard", "Horizon"),
                ("calibration_dashboard", "Agent Calibration")],
    "backtests": [("backtest_list", "Backtesting"),
                  ("bot_backtest_list", "Bot Backtest"),
                  ("bot_performance_dashboard", "Bot Performance")],
    "trust": [("calibration_dashboard", "Agent Calibration"),
              ("brain_dashboard", "Sauron's Mind"),
              ("evidence_ledger", "Evidence Ledger")],
}


def _pages_for(key):
    """Resolve a cycle's drill-downs, dropping any that no longer exist.

    A dead url name in a template raises at RENDER — on this page and on
    nothing else, but completely. A cycle losing a link is a smaller
    failure than the page losing itself, so this resolves rather than
    trusts, and a route that has been renamed simply stops being offered.
    """
    from django.urls import NoReverseMatch, reverse

    out = []
    for name, label in CYCLE_PAGES.get(key, ()):
        try:
            out.append({"name": name, "label": label, "href": reverse(name)})
        except NoReverseMatch:
            logger.warning("oculus: cycle %s links to %r, which reverses to "
                           "nothing — link dropped", key, name)
    return out


# ── one fact, one fence ─────────────────────────────────────────────────

def _fact(label, builder, *, note="", qualifier="", tone="plain"):
    """Run one counter inside its own fence.

    `tone` is for the template only and never changes a number:
      plain    — a count
      caution  — a count the operator should read twice (see `qualifier`)
      inert    — a count of things that cannot act (research, shadow, off)
    """
    try:
        value = builder()
        if value is not None:
            value = int(value)
    except Exception as exc:  # noqa: BLE001 — a dead table must not take the page
        logger.debug("oculus: %s unavailable (%s)", label, exc)
        value = UNMEASURED
    return {"label": label, "value": value, "note": note,
            "qualifier": qualifier, "tone": tone}


def _text_fact(label, builder, *, note="", qualifier="", tone="plain"):
    """A fact whose answer is a word, not a count.

    `_fact` coerces to int because nearly everything on this page is a
    count and an accidental string would sort and compare wrongly. A
    commit sha is the exception: it is an identifier, and rounding it to
    an integer is not a category error anyone would catch later. Same
    fence, same None-is-not-zero rule — an unstamped build renders an em
    dash rather than the word "unknown", which reads like data.
    """
    try:
        value = builder()
        value = None if value in (None, "") else str(value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("oculus: %s unavailable (%s)", label, exc)
        value = None
    return {"label": label, "value": value, "note": note,
            "qualifier": qualifier, "tone": tone, "text": True}


def _series(model, field, *, days=WINDOW_DAYS, extra=None):
    """A per-day count over `days`, bucketed on `field`.

    Always `created_at`-shaped, never a settlement stamp: `completed_at`,
    `resolved_at` and `evaluated_at` are NULL on exactly the rows a
    stalled cycle would show, so bucketing on them hides the stall.
    """
    try:
        cutoff = timezone.now() - timedelta(days=days)
        qs = model.objects.filter(**{f"{field}__gte": cutoff})
        if extra:
            qs = qs.filter(**extra)
        rows = (qs.annotate(d=TruncDate(field)).values("d")
                  .annotate(n=Count("id")).order_by("d"))
        by_day = {r["d"]: r["n"] for r in rows if r["d"]}
        today = timezone.now().date()
        out = []
        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            out.append({"d": day.isoformat(), "n": int(by_day.get(day, 0))})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("oculus: series %s.%s unavailable (%s)",
                     getattr(model, "__name__", "?"), field, exc)
        return []


def _gate(*keys):
    """The switch state behind a cycle.

    A count written by a task nobody has switched on is not a measurement
    of the market, it is a measurement of the switch — so the switch is
    rendered beside the count, never inferred from it. A key with no row
    reads False, which is what `is_component_enabled` returns and what
    the gate actually does (see tests/test_component_registry.py).
    """
    out = []
    try:
        from core.platform_control import PlatformComponent
        rows = {r.key: r for r in
                PlatformComponent.objects.filter(key__in=keys)}
        for key in keys:
            row = rows.get(key)
            out.append({
                "key": key,
                "on": bool(row and row.is_enabled),
                "known": row is not None,
                "last_run": row.last_run_at if row else None,
                "last_status": (row.last_status if row else "") or "",
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("oculus: gate %s unavailable (%s)", keys, exc)
        return [{"key": k, "on": False, "known": False,
                 "last_run": None, "last_status": ""} for k in keys]
    return out


# ── the cycles ──────────────────────────────────────────────────────────

def _venue_facts(user, venue):
    """One venue's book, from the primitives the desk already sizes with.

    `budget_for` answers the whole column in one call — capital, risk at
    stop, budget left, the governor and how many open rows could not be
    measured — so this cannot drift from what the sizing engine believes.
    """
    from bot_program.capital_desk import budget_for

    b = budget_for(user, venue)

    def _f(key):
        return lambda: b.get(key)

    facts = [
        _fact('pool capital', _f("capital"),
              qualifier='the denominator sizing divides'),
        _fact("open positions", _f("n_open")),
        _fact('risk to stop committed', _f("book_risk"),
              qualifier='sum of qty × |entry − opening stop|, pending '
                        'closes included'),
        _fact("budget left", _f("budget"), tone="caution",
              qualifier='gross minus the risk already booked'),
    ]
    if b.get("unmeasured_open"):
        facts.append(_fact(
            'positions whose risk is NOT measured', _f("unmeasured_open"),
            tone="caution",
            qualifier='open with no readable initial stop: they weigh on '
                      'the book and on no budget'))
    if venue == "live":
        # The governor exists on the live venue only — a drawdown brake on a
        # simulation would throttle a book that cannot lose anything.
        facts.append(_fact(
            "drawdown governor (×100)",
            lambda: round(float(b.get("governor") or 0) * 100),
            tone="caution",
            qualifier='100 means TWO things: no drawdown, or no equity '
                      'reading at all. The floor is 40.'))
    return facts


def _cycle_book(user):
    """THE BOOK — live beside paper, and never the two added.

    The only per-VIEWER panel on this page; every other cycle is
    platform-wide. Capital belongs to a user, so pooling it across the
    platform would be meaningless, and saying so in the caveat matters
    more than the numbers: a reader who takes this for a fleet total
    misreads every figure in it.
    """
    venues = []
    for venue in ("live", "paper"):
        try:
            facts = _venue_facts(user, venue)
        except Exception as exc:  # noqa: BLE001 — one venue must not cost both
            logger.debug("oculus: book/%s unavailable (%s)", venue, exc)
            facts = []
        venues.append({"venue": venue, "facts": facts})

    # What the simulator promised, against what execution returned.
    gaps = []
    try:
        from bot_program.bot_grading import paper_live_expectancy_gap
        for row in paper_live_expectancy_gap(user=user, days=180, min_n=1):
            gaps.append({
                "rule": row.get("rule_name") or "—",
                "asset_class": row.get("asset_class") or "—",
                "n_paper": row.get("n_paper"),
                "n_live": row.get("n_live"),
                "paper": row.get("paper_expectancy"),
                "live": row.get("live_expectancy"),
                "gap": row.get("gap"),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("oculus: expectancy gap unavailable (%s)", exc)

    return {
        "key": "book",
        "title": 'The book',
        "question": 'How much real money is committed, and how much is only '
                    'a simulation?',
        "gate": _gate("platform_master", "broker_account_sync"),
        "facts": [],
        "venues": venues,
        "gaps": gaps,
        "caveat": (
            'The only panel on this page that speaks about YOU alone: every '
            'other cycle counts the whole platform. Live and paper are '
            'never summed — a simulated pool inflates the total and no real '
            'entry can draw on it. The expectancy gap is None when one of '
            'the two venues closed nothing: a gap measured against an '
            'unmeasured venue is not a small gap, it is the absence of '
            'measurement.'),
        "series": [],
    }


def _cycle_gates():
    from core.platform_control import PlatformComponent

    def _on():
        return PlatformComponent.objects.filter(is_enabled=True).count()

    def _off():
        return PlatformComponent.objects.filter(is_enabled=False).count()

    def _never_ran():
        return PlatformComponent.objects.filter(
            is_enabled=True, last_run_at__isnull=True).count()

    def _errored():
        return PlatformComponent.objects.filter(last_status="error").count()

    return {
        "key": "gates",
        "title": 'The switches',
        "question": 'What is allowed to run?',
        "gate": _gate("platform_master"),
        "facts": [
            _fact('components on', _on),
            _fact('components off', _off, tone="inert",
                  qualifier='off does not mean broken — it is often the '
                            'right default'),
            _fact('on but never run', _never_ran, tone="caution",
                  qualifier='on and never launched: the scheduler does not '
                            'reach it'),
            _fact('last pass in error', _errored, tone="caution"),
        ],
        "caveat": (
            'The master switch cuts everything upstream. A component with '
            'no row in the database reads OFF — that is what the gate does, '
            'and it is how three tasks had never run at all until '
            '2026-09-13.'),
        "series": [],
    }


def _cycle_scan():
    from signals.models_opportunity import OpportunityFlag, OpportunitySetup

    now = timezone.now()
    week = now - timedelta(days=7)

    return {
        "key": "scan",
        "title": 'The scan',
        "question": 'What is the platform watching, and what does it find?',
        "gate": _gate("pipeline_opportunity_scanner"),
        "facts": [
            _fact('setups armed', lambda: OpportunitySetup.objects.filter(
                is_active=True).count(),
                qualifier='armed = is_active alone; the scan consults no '
                          'ladder'),
            _fact('setups disarmed', lambda: OpportunitySetup.objects.filter(
                is_active=False).count(), tone="inert",
                qualifier='never evaluated, and with no diagnostic verdict'),
            _fact('detections over 7 days', lambda: OpportunityFlag.objects.filter(
                scanned_at__gte=week).count(),
                qualifier='one row per pass while the match lasts, not one '
                          'per opportunity'),
            _fact('detections still unresolved', lambda: OpportunityFlag.objects.filter(
                outcome="").count(), tone="caution",
                qualifier='if the resolver is off, they never will be'),
            _fact('detections graded "no price"', lambda: OpportunityFlag.objects.filter(
                outcome="expired").count(), tone="caution",
                qualifier='expired = no price data at the deadline, not '
                          '"window passed"'),
        ],
        "caveat": (
            'The scan runs once a day at 09:00 UTC over about 179 '
            'instruments. The detection count follows how long a match '
            'persists, not the number of distinct opportunities.'),
        "series": _series(OpportunityFlag, "scanned_at"),
    }


def _cycle_ladder():
    from signals.models_control import PromotionEvent, RuleControl

    def _stage(stage):
        return lambda: RuleControl.objects.filter(promotion_stage=stage).count()

    return {
        "key": "ladder",
        "title": 'The promotion ladder',
        "question": 'What is allowed to act on what it finds?',
        "gate": _gate("pipeline_actuator", "pipeline_promotion"),
        "facts": [
            _fact('rules at research', _stage("research"), tone="inert",
                  qualifier='cannot place an order AND its signals are '
                            'dropped from the vote: registering a rule '
                            'demotes it'),
            _fact('rules at paper', _stage("paper"), tone="inert"),
            _fact('rules at live reduced', _stage("live_small"), tone="caution"),
            _fact('rules at live full', _stage("live_full"), tone="caution"),
            _fact('rules paused', lambda: RuleControl.objects.filter(
                status="paused").count(), tone="inert"),
            _fact("transitions over 30 days", lambda: PromotionEvent.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=30)).count(),
                qualifier="the only honest series of the ladder's movement"),
        ],
        "caveat": (
            'A rule with NO ladder row is not ungoverned: it is treated as '
            'full-size paper. So the row count measures what is throttled, '
            'not what is covered.'),
        "series": _series(PromotionEvent, "created_at"),
    }


def _cycle_signals():
    from signals.models import Signal

    def _outcome(value):
        return lambda: Signal.objects.filter(outcome=value).count()

    return {
        "key": "signals",
        "title": 'The signals',
        "question": 'How many opinions, and how many got an answer?',
        "gate": _gate("pipeline_signals"),
        "facts": [
            _fact("live signals", lambda: Signal.objects.filter(
                is_active=True).count()),
            _fact('graded: target hit', _outcome("hit_target")),
            _fact('graded: stopped out', _outcome("stopped_out")),
            _fact('graded: expired', _outcome("expired")),
            _fact('graded: closed by hand', _outcome("manual_close")),
            _fact('never graded', _outcome(""), tone="caution",
                  qualifier='an opinion with no answer is not evidence'),
        ],
        "caveat": (
            'A setup that matches thirty passes in a row produces ONE '
            'reused signal, not thirty. Detections and signals do not '
            'compare term for term.'),
        "series": _series(Signal, "created_at"),
    }


def _cycle_evolution():
    from brain.generator_models import GeneratedSetupProposal
    from signals.models_control import RuleMutation

    def _status(value):
        return lambda: GeneratedSetupProposal.objects.filter(
            status=value).count()

    return {
        "key": "evolution",
        "title": 'Evolution',
        "question": 'Does the platform invent, and what becomes of its ideas?',
        "gate": _gate("pipeline_evolution", "generator_auto_research"),
        "facts": [
            _fact('proposals pending', _status("pending"), tone="caution"),
            _fact('proposals approved', _status("approved")),
            _fact('proposals refused', _status("rejected"),
                  qualifier='a refusal row is written on purpose: an idea '
                            'paid for and then refused must stay visible'),
            _fact('proposals expired', _status("expired"), tone="inert"),
            _fact('mutations actually backtested', lambda: RuleMutation.objects.filter(
                score_method="walk_forward").count(),
                qualifier='only walk_forward means a backtest ran'),
            _fact('mutations never backtested', lambda: RuleMutation.objects.exclude(
                score_method="walk_forward").count(), tone="caution",
                qualifier='score_method "heuristic": an opinion, not a '
                          'measurement'),
        ],
        "caveat": (
            'Counting mutations as evidence of a backtest is the over-claim '
            'this page refuses: the column says which one was actually '
            'simulated.'),
        "series": _series(GeneratedSetupProposal, "created_at"),
    }


def _cycle_personas():
    from bot_program import personas
    from bot_program.models import AssetBotConfig

    def _wearing_map():
        """The Python bucket persona_mix._wearing uses — never a JSON query."""
        from types import SimpleNamespace
        out = {}
        for pk, extras, enabled in AssetBotConfig.objects.values_list(
                "pk", "extras", "enabled"):
            key = personas.persona_of(SimpleNamespace(extras=extras or {}))
            if key:
                out.setdefault(key, []).append((pk, enabled))
        return out

    def _count_for(key, only_enabled=False):
        def _inner():
            worn = _wearing_map().get(key, [])
            if only_enabled:
                return sum(1 for _pk, en in worn if en)
            return len(worn)
        return _inner

    def _eligible_without():
        worn = sum(len(v) for v in _wearing_map().values())
        total = AssetBotConfig.objects.filter(
            asset_class__in=personas.PERSONA_ASSET_CLASSES).count()
        return max(0, total - worn)

    facts = [_fact('personalities defined', lambda: len(personas.PERSONAS),
                   qualifier='a code constant, not a query')]
    for key in ("scalp", "swing", "position"):
        facts.append(_fact(f'configs carrying "{key}"', _count_for(key)))
        facts.append(_fact("… of which actually enabled", _count_for(key, True),
                           tone="caution",
                           qualifier='carrying a personality without being '
                                     'enabled runs nothing'))
    facts.append(_fact('eligible configs with no personality', _eligible_without,
                       qualifier='honest denominator: options can never '
                                 'carry one'))

    return {
        "key": "personas",
        "title": 'Personalities',
        "question": 'What kind of trader is each pool?',
        "gate": _gate("pipeline_asset_bots"),
        "facts": facts,
        "caveat": (
            'No trade carries a personality: attribution goes by the '
            "config's CURRENT personality, so changing personality "
            'reattributes the past. A misspelled personality reads '
            'everywhere as "carries none", without a single alert.'),
        "series": [],
    }


def _cycle_allocation():
    from bot_program.desk_models import DeskPlan
    from bot_program.share_models import SharePlan

    return {
        "key": "allocation",
        "title": 'Allocation',
        "question": 'Is capital moving, or is this a rehearsal?',
        "gate": _gate("pipeline_share_allocator", "share_allocator_mode_live",
                      "pipeline_capital_desk", "capital_desk_mode_live"),
        "facts": [
            _fact('share plans proposed', lambda: SharePlan.objects.filter(
                state="proposed").count(), tone="inert"),
            _fact('share plans actually applied', lambda: SharePlan.objects.filter(
                applied_at__isnull=False).count(),
                qualifier='measured on applied_at, not on state: a '
                          'cancelled plan did move a share'),
            _fact('share plans expired', lambda: SharePlan.objects.filter(
                state="expired").count(), tone="inert",
                qualifier='mostly replacements, not neglect'),
            _fact('desk passes in shadow', lambda: DeskPlan.objects.filter(
                mode="shadow").count(), tone="inert",
                qualifier='in shadow, a "moved" candidate moved nothing: '
                          'everything runs at full size'),
            _fact('desk passes live', lambda: DeskPlan.objects.filter(
                mode="live").count(), tone="caution"),
        ],
        "caveat": (
            'Nothing here moves money without a human until both live '
            'switches are on. Paper and live are never summed, anywhere.'),
        "series": _series(DeskPlan, "created_at"),
    }


def _cycle_horizon():
    from brain.horizon_models import HorizonView

    def _status(value):
        return lambda: HorizonView.objects.filter(status=value).count()

    def _age_days():
        row = (HorizonView.objects.filter(status="ok")
               .order_by("-created_at").first())
        if row is None:
            return None
        return (timezone.now() - row.created_at).days

    return {
        "key": "horizon",
        "title": 'The horizon',
        "question": 'Does the five-to-ten-year view exist, and does the '
                    'allocator use it?',
        "gate": _gate("agent_horizon", "pipeline_calibration"),
        "facts": [
            _fact("views completed", _status("ok")),
            _fact('views refused', _status("rejected"), tone="inert"),
            _fact('views in error', _status("error"), tone="caution"),
            _fact('views left "in progress"', _status("running"), tone="caution",
                  qualifier='no reaper: a killed worker leaves the row that '
                            'way forever'),
            _fact('age in days of the view in use', _age_days,
                  qualifier='past 45 days the allocator ignores it and '
                            'falls back to 1.00'),
        ],
        "caveat": (
            "The horizon's calls come due at 6 and 12 months and the first "
            'view dates from 2026-09-12: zero graded is honest until March '
            '2027. Rendering that as "0% accuracy" would turn "not due yet" '
            'into "wrong".'),
        "series": [],
    }


def _bot_runs_before_the_fix():
    """Completed bot runs whose stats carry no `unmeasured` key.

    Until 2026-09-14 a signal with no bar after it was priced at 0.0 and
    booked as a −50 R expiry, and the config's time-stop ceiling was ignored
    entirely. Both are fixed, and every run stored since carries the
    `unmeasured` key. Its absence is therefore a reliable marker of a number
    computed by the old engine — which must not be read beside the new ones
    as though they measured the same thing.
    """
    from bot_program.backtest_models import BotBacktestRun
    stale = 0
    for stats in BotBacktestRun.objects.filter(
            status="complete").values_list("stats", flat=True):
        if not isinstance(stats, dict) or "unmeasured" not in stats:
            stale += 1
    return stale


def _signals_no_run_could_price():
    """Signals that qualified and had no bar after them, across all runs."""
    from bot_program.backtest_models import BotBacktestRun
    total = 0
    for stats in BotBacktestRun.objects.filter(
            status="complete").values_list("stats", flat=True):
        if isinstance(stats, dict):
            block = stats.get("unmeasured") or {}
            try:
                total += int(block.get("signals_without_bars") or 0)
            except (TypeError, ValueError):
                continue
    return total


def _cycle_backtests():
    from backtester.models import BacktestRun
    from bot_program.backtest_models import BotBacktestRun

    return {
        "key": "backtests",
        "title": 'The backtests',
        "question": 'What was simulated before it was believed?',
        "gate": [],
        "facts": [
            _fact("engine v1 runs", lambda: BacktestRun.objects.count()),
            _fact("… completed", lambda: BacktestRun.objects.filter(
                status="completed").count(),
                qualifier='the literal is "completed"'),
            _fact('… completed with no trade at all', lambda: BacktestRun.objects.filter(
                status="completed", total_trades=0).count(), tone="caution",
                qualifier='a result, not a failure'),
            _fact('… carrying a MEASURED win rate', lambda: BacktestRun.objects.filter(
                win_rate__isnull=False).count(),
                qualifier='NULLs are unknown, never 0%'),
            _fact('bot runs', lambda: BotBacktestRun.objects.count()),
            _fact("… complete", lambda: BotBacktestRun.objects.filter(
                status="complete").count(),
                qualifier='here the literal is "complete", with no -d: a '
                          'shared filter would return 0 forever'),
            _fact('… computed before the 09-14 fix',
                  _bot_runs_before_the_fix, tone="caution",
                  qualifier='a signal with no bar was worth −50 R there and '
                            'the time cap did not exist: these numbers do '
                            'not compare with the later ones'),
            _fact('signals a run could not simulate',
                  _signals_no_run_could_price, tone="caution",
                  qualifier='no bar after the signal — set aside and '
                            'counted, never averaged'),
        ],
        "caveat": (
            'Two tables, two status vocabularies one letter apart, and two '
            'units for the win rate (a percentage on one side, a fraction '
            'on the other). They are never summed here. No backtest gates a '
            'promotion: the automatic ladder runs in memory and writes no '
            'row. On 09-14 the bot simulator changed in four ways: a signal '
            'with no bar is no longer a −50 R loss but a signal set aside '
            'and counted, a gap through the stop fills at the open rather '
            'than at the stop, "expired" no longer covers "the bar feed '
            'stops here", and the bot\'s own time cap is finally honoured. '
            'Earlier runs were not measuring the same bot.'),
        "series": [],
    }


def _cycle_trust():
    from ai_agents.models import AgentPrediction

    base = AgentPrediction.objects.filter(prediction_type="direction")

    return {
        "key": "trust",
        "title": 'Confidence',
        "question": 'Did what the platform asserted turn out to be true?',
        "gate": _gate("pipeline_calibration"),
        "facts": [
            _fact('direction calls graded right',
                  lambda: base.filter(was_correct=True).count()),
            _fact('direction calls graded wrong',
                  lambda: base.filter(was_correct=False).count()),
            _fact('calls awaiting a grade',
                  lambda: base.filter(was_correct__isnull=True,
                                      evaluated_at__isnull=True).count(),
                  tone="caution",
                  qualifier='if the grader is off, "pending" means "nobody '
                            'is grading", not "the market did not answer"'),
            _fact('calls the market could not settle',
                  lambda: base.filter(was_correct__isnull=True,
                                      evaluated_at__isnull=False).count(),
                  tone="inert",
                  qualifier='resolved and permanently unmeasurable'),
            _fact('agents carrying at least one call',
                  lambda: base.values("agent").distinct().count()),
        ],
        "caveat": (
            'A confidence of 1.00 means two opposite things: well '
            'calibrated, or fewer than ten graded calls. An accuracy rate '
            'without its sample size is not a fact. Flat counts as wrong, '
            'so the baseline is not 50%.'),
        "series": _series(AgentPrediction, "created_at",
                          extra={"prediction_type": "direction"}),
    }


def _cycle_forge():
    """THE FORGE — the state of the code that is running, not of the market.

    Every other cycle answers a question about trading. This one answers
    the question the platform could not answer about ITSELF, and the one
    that cost a whole day on 2026-09-13: WHICH COMMIT AM I, and is what I
    am running the thing that was written?

    The blindness was total. `.dockerignore` excludes `.git`, so the
    container had no sha; nothing was stamped at build time; the box
    served the previous commit for a day while two pages answered 404,
    and the only way to discover it was probing the public site route by
    route from outside. A stamp and a timestamp would have made it a
    five-second glance.

    It reports and does not act — and that is the honest state of the
    forge today. The lane where an agent proposes a patch and a human
    approves it from this page is the next brick; a table of proposals
    that do not exist yet would be a panel of em dashes pretending to be
    a feature.
    """
    from core.build_stamp import stamp

    st = stamp()

    def _pending_migrations():
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return len(executor.migration_plan(targets))

    def _tests_published():
        from core.wall_facts import TESTS_GREEN
        return TESTS_GREEN

    def _unregistered_guards():
        """Guarded task keys with no component row — the defect that hid
        three never-running tasks until 2026-09-13."""
        import re
        from pathlib import Path

        from django.conf import settings
        from core.platform_control import DEFAULT_COMPONENTS
        declared = {c["key"] for c in DEFAULT_COMPONENTS}
        skip = {".git", ".venv", "venv", "__pycache__", "staticfiles",
                "static", "node_modules", ".pytest_cache", "test_backups",
                "migrations"}
        pattern = re.compile(r"""guarded_task\(\s*["']([A-Za-z0-9_]+)["']""")
        root = Path(settings.BASE_DIR)
        used = set()
        for path in root.rglob("*.py"):
            if any(p in skip for p in path.relative_to(root).parts):
                continue
            used.update(pattern.findall(
                path.read_text(encoding="utf-8", errors="replace")))
        return len(used - declared)

    return {
        "key": "forge",
        "title": 'The forge',
        "question": 'Which code is this platform running, and is it the '
                    'code that was written?',
        "gate": [],
        "facts": [
            _text_fact('commit of this image', lambda: st["sha"],
                       qualifier='stamped at build time by deploy/dc; a '
                                 'dash means the image was not stamped, '
                                 'never an invented sha'),
            _fact('build age, in hours', lambda: st["age_hours"],
                  tone="caution",
                  qualifier='the age is the fact that matters: a sha tells '
                            'a human nothing, "built 31 h ago" on a branch '
                            'that moved this morning tells everything'),
            _fact('migrations pending', _pending_migrations, tone="caution",
                  qualifier='not applied on THIS database: a deploy without '
                            'them serves pages against a schema that is not '
                            'there'),
            _fact('tests published on the wall', _tests_published,
                  qualifier='the number the public page shows; '
                            'tests/test_wall_facts fails when it drifts'),
            _fact('guarded tasks with no switch', _unregistered_guards,
                  tone="caution",
                  qualifier='a guarded_task key with no row reads OFF and '
                            'the task never runs — three were, from the '
                            'beginning, found on 2026-09-13'),
        ],
        "caveat": (
            'This lane REPORTS; it does not act yet, and that is the honest '
            'state of the forge today. It knows which commit the image was '
            'built from; it cannot know whether that commit is still the '
            'latest — the image has neither git nor guaranteed network. '
            'That was already all that was missing on 13 September.'),
        "series": [],
    }


BUILDERS = (
    _cycle_forge,
    _cycle_gates,
    _cycle_scan,
    _cycle_ladder,
    _cycle_signals,
    _cycle_evolution,
    _cycle_personas,
    _cycle_allocation,
    _cycle_horizon,
    _cycle_backtests,
    _cycle_trust,
)


def oculus(user=None) -> dict:
    """Every cycle, fenced one by one. Never raises.

    A cycle whose builder dies is REPORTED AS DEAD rather than dropped:
    a missing panel reads as "there is no such cycle", which is a lie of
    omission the operator cannot see. A broken one says so.

    `user` adds THE BOOK — the one per-viewer panel. Without it the page
    is entirely platform-wide, which is what an anonymous or system
    caller should get: a book pooled across users would be a number
    nobody could act on.
    """
    cycles, degraded = [], []
    builders = list(BUILDERS)
    if user is not None and getattr(user, "is_authenticated", False):
        builders.insert(0, lambda: _cycle_book(user))
    for builder in builders:
        name = getattr(builder, "__name__", "_cycle_book")
        if name == "<lambda>":
            name = "_cycle_book"
        try:
            cycle = builder()
        except Exception as exc:  # noqa: BLE001
            logger.warning("oculus: cycle %s failed (%s)", name, exc)
            degraded.append(name)
            cycles.append({
                "key": name.replace("_cycle_", ""),
                "title": name.replace("_cycle_", "").title(),
                "question": "",
                "gate": [],
                "facts": [],
                "caveat": 'This cycle could not be read. The missing number '
                          'is not a zero.',
                "series": [],
                "dead": True,
            })
            continue
        cycle.setdefault("dead", False)
        # The spark's own scale. Each strip is scaled to ITSELF, never to
        # the busiest cycle on the page: one shared axis would flatten
        # every slow cycle into a line of nothing and read as "dead" when
        # the honest reading is "slower than the scanner, by design".
        series = cycle.get("series") or []
        cycle["max_n"] = max((p["n"] for p in series), default=0)
        # The way OUT of the panel. Resolved here rather than in the
        # template so a renamed route costs one link, not the page.
        cycle["pages"] = _pages_for(cycle.get("key", ""))
        for fact in cycle.get("facts", []):
            if fact.get("value") is UNMEASURED:
                degraded.append(f"{cycle['key']}.{fact['label']}")
        cycles.append(cycle)
    return {
        "generated_at": timezone.now(),
        "window_days": WINDOW_DAYS,
        "cycles": cycles,
        "degraded": degraded,
    }
