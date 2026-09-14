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
        _fact("capital du pool", _f("capital"),
              qualifier="le dénominateur que le dimensionnement divise"),
        _fact("positions ouvertes", _f("n_open")),
        _fact("risque au stop engagé", _f("book_risk"),
              qualifier="somme de qty × |entrée − stop d'ouverture|, "
                        "les clôtures en attente comprises"),
        _fact("budget restant", _f("budget"), tone="caution",
              qualifier="brut moins le risque déjà au livre"),
    ]
    if b.get("unmeasured_open"):
        facts.append(_fact(
            "positions au risque NON mesuré", _f("unmeasured_open"),
            tone="caution",
            qualifier="ouvertes sans stop initial lisible : elles pèsent sur "
                      "le livre et ne pèsent sur aucun budget"))
    if venue == "live":
        # The governor exists on the live venue only — a drawdown brake on a
        # simulation would throttle a book that cannot lose anything.
        facts.append(_fact(
            "gouverneur de drawdown (×100)",
            lambda: round(float(b.get("governor") or 0) * 100),
            tone="caution",
            qualifier="100 veut dire DEUX choses : aucun drawdown, ou aucune "
                      "lecture d'équité. Le plancher est 40."))
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
        "title": "Le livre",
        "question": "Combien d'argent réel est engagé, et combien n'est qu'une simulation ?",
        "gate": _gate("platform_master", "broker_account_sync"),
        "facts": [],
        "venues": venues,
        "gaps": gaps,
        "caveat": (
            "Le seul panneau de cette page qui ne parle que de VOUS : tous "
            "les autres cycles comptent la plateforme entière. Live et papier "
            "ne sont jamais additionnés — un pool simulé gonfle le total et "
            "aucune entrée réelle ne peut y puiser. L'écart d'espérance vaut "
            "None quand une des deux venues n'a rien clôturé : un écart "
            "contre une venue non mesurée n'est pas un petit écart, c'est "
            "l'absence de mesure."),
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
        "title": "Les interrupteurs",
        "question": "Qu'est-ce qui a le droit de tourner ?",
        "gate": _gate("platform_master"),
        "facts": [
            _fact("composants allumés", _on),
            _fact("composants éteints", _off, tone="inert",
                  qualifier="éteint ne veut pas dire cassé — c'est souvent le bon défaut"),
            _fact("allumés mais jamais exécutés", _never_ran, tone="caution",
                  qualifier="allumé et jamais lancé : le planificateur ne l'atteint pas"),
            _fact("dernier passage en erreur", _errored, tone="caution"),
        ],
        "caveat": (
            "Le maître-interrupteur coupe tout en amont. Un composant sans "
            "ligne en base se lit « éteint » : c'est ce que fait la barrière, "
            "et c'est ainsi que trois tâches n'ont jamais tourné jusqu'au "
            "2026-09-13."),
        "series": [],
    }


def _cycle_scan():
    from signals.models_opportunity import OpportunityFlag, OpportunitySetup

    now = timezone.now()
    week = now - timedelta(days=7)

    return {
        "key": "scan",
        "title": "Le scan",
        "question": "Que la plateforme regarde-t-elle, et que trouve-t-elle ?",
        "gate": _gate("pipeline_opportunity_scanner"),
        "facts": [
            _fact("setups armés", lambda: OpportunitySetup.objects.filter(
                is_active=True).count(),
                qualifier="armé = is_active seul ; le scan ne consulte aucune échelle"),
            _fact("setups désarmés", lambda: OpportunitySetup.objects.filter(
                is_active=False).count(), tone="inert",
                qualifier="jamais évalués, et sans verdict de diagnostic"),
            _fact("détections sur 7 jours", lambda: OpportunityFlag.objects.filter(
                scanned_at__gte=week).count(),
                qualifier="une ligne par passage tant que la correspondance dure, "
                          "pas une par opportunité"),
            _fact("détections encore non résolues", lambda: OpportunityFlag.objects.filter(
                outcome="").count(), tone="caution",
                qualifier="si le résolveur est éteint, elles ne le seront jamais"),
            _fact("détections notées « sans prix »", lambda: OpportunityFlag.objects.filter(
                outcome="expired").count(), tone="caution",
                qualifier="expired = aucune donnée de prix à l'échéance, pas « fenêtre passée »"),
        ],
        "caveat": (
            "Le scan tourne une fois par jour à 09:00 UTC sur environ 179 "
            "instruments. Le nombre de détections suit la persistance d'une "
            "correspondance, pas le nombre d'occasions distinctes."),
        "series": _series(OpportunityFlag, "scanned_at"),
    }


def _cycle_ladder():
    from signals.models_control import PromotionEvent, RuleControl

    def _stage(stage):
        return lambda: RuleControl.objects.filter(promotion_stage=stage).count()

    return {
        "key": "ladder",
        "title": "L'échelle de promotion",
        "question": "Qu'est-ce qui a le droit d'agir sur ce qui est trouvé ?",
        "gate": _gate("pipeline_actuator", "pipeline_promotion"),
        "facts": [
            _fact("règles en recherche", _stage("research"), tone="inert",
                  qualifier="ne peut pas passer d'ordre ET ses signaux sont retirés "
                            "du vote : enregistrer une règle la rétrograde"),
            _fact("règles en papier", _stage("paper"), tone="inert"),
            _fact("règles en live réduit", _stage("live_small"), tone="caution"),
            _fact("règles en live plein", _stage("live_full"), tone="caution"),
            _fact("règles en pause", lambda: RuleControl.objects.filter(
                status="paused").count(), tone="inert"),
            _fact("transitions sur 30 jours", lambda: PromotionEvent.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=30)).count(),
                qualifier="la seule série honnête du mouvement de l'échelle"),
        ],
        "caveat": (
            "Une règle SANS ligne d'échelle n'est pas non gouvernée : elle est "
            "traitée comme du papier à taille pleine. Le compte des lignes "
            "mesure donc ce qui est bridé, pas ce qui est couvert."),
        "series": _series(PromotionEvent, "created_at"),
    }


def _cycle_signals():
    from signals.models import Signal

    def _outcome(value):
        return lambda: Signal.objects.filter(outcome=value).count()

    return {
        "key": "signals",
        "title": "Les signaux",
        "question": "Combien d'opinions, et combien ont reçu une réponse ?",
        "gate": _gate("pipeline_signals"),
        "facts": [
            _fact("signaux vivants", lambda: Signal.objects.filter(
                is_active=True).count()),
            _fact("notés : objectif atteint", _outcome("hit_target")),
            _fact("notés : stop touché", _outcome("stopped_out")),
            _fact("notés : expirés", _outcome("expired")),
            _fact("notés : clôture manuelle", _outcome("manual_close")),
            _fact("jamais notés", _outcome(""), tone="caution",
                  qualifier="une opinion sans réponse n'est pas une preuve"),
        ],
        "caveat": (
            "Un setup qui correspond trente passages de suite produit UN "
            "signal réutilisé, pas trente. Les détections et les signaux ne "
            "se comparent pas terme à terme."),
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
        "title": "L'évolution",
        "question": "La plateforme invente-t-elle, et qu'advient-il de ses idées ?",
        "gate": _gate("pipeline_evolution", "generator_auto_research"),
        "facts": [
            _fact("propositions en attente", _status("pending"), tone="caution"),
            _fact("propositions approuvées", _status("approved")),
            _fact("propositions refusées", _status("rejected"),
                  qualifier="une ligne de refus est écrite exprès : une idée "
                            "payée puis refusée doit rester visible"),
            _fact("propositions expirées", _status("expired"), tone="inert"),
            _fact("mutations réellement backtestées", lambda: RuleMutation.objects.filter(
                score_method="walk_forward").count(),
                qualifier="seul walk_forward signifie qu'un backtest a tourné"),
            _fact("mutations jamais backtestées", lambda: RuleMutation.objects.exclude(
                score_method="walk_forward").count(), tone="caution",
                qualifier="score_method « heuristic » : un avis, pas une mesure"),
        ],
        "caveat": (
            "Compter les mutations comme des preuves de backtest est le "
            "sur-engagement que cette page refuse : la colonne dit "
            "laquelle a vraiment été simulée."),
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

    facts = [_fact("personnalités définies", lambda: len(personas.PERSONAS),
                   qualifier="une constante de code, pas une requête")]
    for key in ("scalp", "swing", "position"):
        facts.append(_fact(f"configs portant « {key} »", _count_for(key)))
        facts.append(_fact(f"… dont réellement activées", _count_for(key, True),
                           tone="caution",
                           qualifier="porter une personnalité sans être activé "
                                     "ne fait rien tourner"))
    facts.append(_fact("configs éligibles sans personnalité", _eligible_without,
                       qualifier="dénominateur honnête : les options ne peuvent "
                                 "jamais en porter"))

    return {
        "key": "personas",
        "title": "Les personnalités",
        "question": "Quel genre de trader chaque poche est-elle ?",
        "gate": _gate("pipeline_asset_bots"),
        "facts": facts,
        "caveat": (
            "Aucune transaction ne porte de personnalité : l'attribution se "
            "fait par la personnalité ACTUELLE de la config, donc changer de "
            "personnalité réattribue le passé. Une personnalité mal orthographiée "
            "se lit partout « n'en porte aucune », sans la moindre alerte."),
        "series": [],
    }


def _cycle_allocation():
    from bot_program.desk_models import DeskPlan
    from bot_program.share_models import SharePlan

    return {
        "key": "allocation",
        "title": "L'allocation",
        "question": "Le capital bouge-t-il, ou est-ce une répétition ?",
        "gate": _gate("pipeline_share_allocator", "share_allocator_mode_live",
                      "pipeline_capital_desk", "capital_desk_mode_live"),
        "facts": [
            _fact("plans de part proposés", lambda: SharePlan.objects.filter(
                state="proposed").count(), tone="inert"),
            _fact("plans de part réellement appliqués", lambda: SharePlan.objects.filter(
                applied_at__isnull=False).count(),
                qualifier="mesuré sur applied_at, pas sur l'état : un plan annulé "
                          "a bel et bien bougé une part"),
            _fact("plans de part expirés", lambda: SharePlan.objects.filter(
                state="expired").count(), tone="inert",
                qualifier="surtout des remplacements, pas de la négligence"),
            _fact("passes du bureau en ombre", lambda: DeskPlan.objects.filter(
                mode="shadow").count(), tone="inert",
                qualifier="en ombre, un candidat « déplacé » n'a rien déplacé : "
                          "tout s'exécute à taille pleine"),
            _fact("passes du bureau en live", lambda: DeskPlan.objects.filter(
                mode="live").count(), tone="caution"),
        ],
        "caveat": (
            "Rien ici ne déplace d'argent sans humain tant que les deux "
            "interrupteurs live ne sont pas allumés. Papier et live ne sont "
            "jamais additionnés, nulle part."),
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
        "title": "L'horizon",
        "question": "La vue à cinq-dix ans existe-t-elle, et l'allocateur s'en sert-il ?",
        "gate": _gate("agent_horizon", "pipeline_calibration"),
        "facts": [
            _fact("vues abouties", _status("ok")),
            _fact("vues refusées", _status("rejected"), tone="inert"),
            _fact("vues en erreur", _status("error"), tone="caution"),
            _fact("vues restées « en cours »", _status("running"), tone="caution",
                  qualifier="aucun ramasseur : un worker tué laisse la ligne ainsi "
                            "pour toujours"),
            _fact("âge en jours de la vue utilisée", _age_days,
                  qualifier="au-delà de 45 jours l'allocateur l'ignore et retombe à 1.00"),
        ],
        "caveat": (
            "Les appels de l'horizon portent à 6 et 12 mois et la première vue "
            "date du 2026-09-12 : zéro noté est honnête jusqu'en mars 2027. "
            "Le rendre en « 0 % de justesse » transformerait « pas encore dû » "
            "en « faux »."),
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
        "title": "Les backtests",
        "question": "Qu'est-ce qui a été simulé avant d'être cru ?",
        "gate": [],
        "facts": [
            _fact("runs moteur v1", lambda: BacktestRun.objects.count()),
            _fact("… aboutis", lambda: BacktestRun.objects.filter(
                status="completed").count(),
                qualifier="le littéral est « completed »"),
            _fact("… aboutis sans la moindre transaction", lambda: BacktestRun.objects.filter(
                status="completed", total_trades=0).count(), tone="caution",
                qualifier="un résultat, pas un échec"),
            _fact("… portant un taux de réussite MESURÉ", lambda: BacktestRun.objects.filter(
                win_rate__isnull=False).count(),
                qualifier="les NULL sont inconnus, jamais 0 %"),
            _fact("runs de bots", lambda: BotBacktestRun.objects.count()),
            _fact("… aboutis", lambda: BotBacktestRun.objects.filter(
                status="complete").count(),
                qualifier="ici le littéral est « complete », sans -d : "
                          "un filtre partagé renverrait 0 pour toujours"),
            _fact("… calculés avant le correctif du 14/09",
                  _bot_runs_before_the_fix, tone="caution",
                  qualifier="un signal sans barre y valait −50 R et le "
                            "plafond de durée n'existait pas : ces chiffres "
                            "ne se comparent pas aux suivants"),
            _fact("signaux qu'un run n'a pas pu simuler",
                  _signals_no_run_could_price, tone="caution",
                  qualifier="aucune barre après le signal — écartés et "
                            "comptés, jamais moyennés"),
        ],
        "caveat": (
            "Deux tables, deux vocabulaires de statut à une lettre près, et "
            "deux unités pour le taux de réussite (pourcentage d'un côté, "
            "fraction de l'autre). Elles ne sont jamais additionnées ici. "
            "Aucun backtest ne conditionne une promotion : la barrière "
            "automatique tourne en mémoire et n'écrit aucune ligne. "
            "Le 14/09 le simulateur de bots a changé sur quatre points : un "
            "signal sans barre n'est plus une perte de −50 R mais un signal "
            "écarté et compté, un gap à travers le stop se remplit à "
            "l'ouverture et non au stop, « expiré » ne recouvre plus « le "
            "flux de barres s'arrête ici », et le plafond de durée du bot "
            "est enfin respecté. Les runs d'avant ne mesuraient pas le même "
            "bot."),
        "series": [],
    }


def _cycle_trust():
    from ai_agents.models import AgentPrediction

    base = AgentPrediction.objects.filter(prediction_type="direction")

    return {
        "key": "trust",
        "title": "La confiance",
        "question": "Ce que la plateforme affirme s'est-il vérifié ?",
        "gate": _gate("pipeline_calibration"),
        "facts": [
            _fact("appels de direction notés justes",
                  lambda: base.filter(was_correct=True).count()),
            _fact("appels de direction notés faux",
                  lambda: base.filter(was_correct=False).count()),
            _fact("appels en attente de note",
                  lambda: base.filter(was_correct__isnull=True,
                                      evaluated_at__isnull=True).count(),
                  tone="caution",
                  qualifier="si le noteur est éteint, « en attente » veut dire "
                            "« personne ne note », pas « le marché n'a pas répondu »"),
            _fact("appels que le marché n'a pas pu trancher",
                  lambda: base.filter(was_correct__isnull=True,
                                      evaluated_at__isnull=False).count(),
                  tone="inert",
                  qualifier="résolus et définitivement non mesurables"),
            _fact("agents portant au moins un appel",
                  lambda: base.values("agent").distinct().count()),
        ],
        "caveat": (
            "Une confiance de 1,00 veut dire deux choses opposées : bien "
            "calibré, ou moins de dix appels notés. Un taux de justesse sans "
            "sa taille d'échantillon n'est pas un fait. Le plat compte comme "
            "faux, donc la ligne de base n'est pas 50 %."),
        "series": _series(AgentPrediction, "created_at",
                          extra={"prediction_type": "direction"}),
    }


def _cycle_forge():
    """LA FORGE — the state of the code that is running, not of the market.

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
        "title": "La forge",
        "question": "De quel code cette plateforme tourne-t-elle, et est-ce celui qui a été écrit ?",
        "gate": [],
        "facts": [
            _text_fact("commit de cette image", lambda: st["sha"],
                       qualifier="posé au build par deploy/dc ; un tiret veut "
                                 "dire que l'image n'a pas été estampillée, "
                                 "jamais un sha inventé"),
            _fact("âge du build, en heures", lambda: st["age_hours"],
                  tone="caution",
                  qualifier="l'âge est le fait qui compte : un sha ne dit rien "
                            "à un humain, « construit il y a 31 h » sur une "
                            "branche qui a bougé ce matin dit tout"),
            _fact("migrations en attente", _pending_migrations, tone="caution",
                  qualifier="non appliquées sur CETTE base : un déploiement "
                            "sans elles sert des pages contre un schéma absent"),
            _fact("tests publiés sur le mur", _tests_published,
                  qualifier="le chiffre que la page publique affiche ; "
                            "tests/test_wall_facts échoue quand il dérive"),
            _fact("tâches gardées sans interrupteur", _unregistered_guards,
                  tone="caution",
                  qualifier="une clé guarded_task sans ligne se lit « éteint » "
                            "et la tâche ne tourne jamais — trois l'étaient "
                            "depuis toujours, découvertes le 2026-09-13"),
        ],
        "caveat": (
            "Cette lane REND COMPTE, elle n'agit pas encore, et c'est l'état "
            "honnête de la forge aujourd'hui. Elle sait de quel commit l'image "
            "a été construite ; elle ne peut pas savoir si ce commit est "
            "toujours le dernier — l'image n'a ni git ni réseau garanti. "
            "C'était déjà tout ce qui manquait le 13 septembre."),
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
                "caveat": "Ce cycle n'a pas pu être lu. Le chiffre absent "
                          "n'est pas un zéro.",
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
