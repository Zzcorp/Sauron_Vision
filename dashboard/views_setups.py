"""Why a setup never fires — /setups/.

The question this page answers was unanswerable on any screen until
2026-09-12: twenty setups armed, sixteen research rules that had never in
their life produced one gradable signal, and nothing anywhere saying whether
a silent setup was too strict, blind on its data, or missing its threshold by
two hundredths. Every number here comes from `signals.setup_diagnostics`,
which runs the SCANNER'S OWN `scan_setup` with `emit=False` — so the page
cannot disagree with the scanner about what the scanner does.

THE DIAGNOSTIC IS EXPENSIVE. It is a full pass over every active setup ×
every instrument admitted by its asset classes — hundreds of pairs, each
several evaluator queries. Running it on a page load would make /setups/ the
slowest page on the platform and would put a multi-second database walk
behind every refresh. So it runs behind a `django.core.cache` entry keyed by
nothing user-specific (the population is platform-wide, and every viewer's
answer is the same answer), and the page SAYS when the reading was taken.
A cache MISS pays for one pass — capped at `PAGE_INSTRUMENT_LIMIT`
instruments per setup so the bill is bounded — and every later viewer inside
the window is served that same reading, with its age printed beside it. If
the pass itself raises, the page still renders and names the command that
takes the reading from a shell.

Staff gating follows /ops/ and /health/: the per-setup zones are for any
login, the platform-wide grading leak and the arming form are staff's.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)

# 900 s is the floor the chantier specified and the right one: the scanner
# writes flags once a day, so a reading fifteen minutes old is describing
# exactly the same population as a reading taken now — and the fifteen
# minutes buy an operator who is refreshing the page while arming setups a
# page that answers instantly.
SETUP_DIAGNOSTIC_CACHE_SECONDS = 900
SETUP_DIAGNOSTIC_CACHE_KEY = "setups:diagnostic:v1"
GRADING_CACHE_KEY = "setups:grading:v1"

STAFF_ONLY = "staff only — platform-wide, as on /health/"

# How many instruments the PAGE's pass may walk per setup. The command has no
# cap. A page that takes thirty seconds is a page nobody opens, and a verdict
# over a capped population is honest as long as it says so — every row carries
# `truncated` and the template prints it.
PAGE_INSTRUMENT_LIMIT = 60


def _diagnostic(force=False) -> dict:
    """The cached reading, computing one only on a miss.

    Every viewer gets the same answer — the population is platform-wide and
    the key carries nothing user-specific — so the first opener of a cold
    page pays for the pass and the next fifteen minutes of openers do not.
    The template prints `as_of` beside every number, because a cached reading
    presented as live is the exact dishonesty this whole page exists against.
    """
    cached = cache.get(SETUP_DIAGNOSTIC_CACHE_KEY)
    if cached is not None and not force:
        return cached
    from signals.setup_diagnostics import diagnose_setups
    rep = diagnose_setups(limit_instruments=PAGE_INSTRUMENT_LIMIT)
    cache.set(SETUP_DIAGNOSTIC_CACHE_KEY, rep, SETUP_DIAGNOSTIC_CACHE_SECONDS)
    return rep


@login_required
def setups_dashboard(request):
    from datetime import timedelta

    from django.db.models import Count, Max, Q

    from signals.models import (OpportunityFlag, OpportunitySetup, RuleControl,
                                Signal)

    now = timezone.now()
    week = now - timedelta(days=7)
    is_staff = bool(request.user.is_staff or request.user.is_superuser)

    # ── the setups themselves ────────────────────────────────────────
    setups, n_active, n_inactive = [], 0, 0
    try:
        setups = list(OpportunitySetup.objects.all().order_by("name"))
        n_active = sum(1 for s in setups if s.is_active)
        n_inactive = len(setups) - n_active
    except Exception as e:  # noqa: BLE001 — the page renders regardless
        logger.warning("[setups page] setups unreadable: %s", e)

    # One grouped query per fact. Every join here is a STRING (`rule_name`),
    # so there is no select_related and a per-card helper would be a query a
    # card — the same budget rule the strategies page keeps.
    sig_rows, flag_rows, ctrls = {}, {}, {}
    try:
        sig_rows = {r["rule_name"]: r for r in (
            Signal.objects.values("rule_name").annotate(
                n_7d=Count("id", filter=Q(created_at__gte=week)),
                n_graded=Count("id", filter=Q(is_active=False)
                               & ~Q(outcome="") & Q(realized_r__isnull=False))))}
        flag_rows = {r["setup__name"]: r for r in (
            OpportunityFlag.objects.values("setup__name")
            .annotate(n_7d=Count("id", filter=Q(scanned_at__gte=week)),
                      last=Max("scanned_at")))}
        ctrls = {c.rule_name: c for c in RuleControl.objects.all()}
    except Exception as e:  # noqa: BLE001
        logger.warning("[setups page] counters unreadable: %s", e)

    # ── the diagnostic: cached, never computed on a page load ────────
    diag, diag_error = None, ""
    try:
        diag = _diagnostic()
    except Exception as e:  # noqa: BLE001
        logger.warning("[setups page] diagnostic unreadable: %s", e)
        diag_error = f"{type(e).__name__}: {e}"[:160]
    by_name = {r["name"]: r for r in ((diag or {}).get("setups") or [])}

    rows = []
    for s in setups:
        d = by_name.get(s.name)
        ctrl = ctrls.get(s.name)
        sig = sig_rows.get(s.name) or {}
        flg = flag_rows.get(s.name) or {}
        thr = float(s.min_match_score or 0.0)
        p90 = (d or {}).get("composite_p90")
        rows.append({
            "setup": s,
            "name": s.name,
            "armed": s.is_active,
            "stage": getattr(ctrl, "promotion_stage", "") or "",
            "has_control": ctrl is not None,
            "threshold": thr,
            "threshold_pct": round(min(1.0, max(0.0, thr)) * 100, 1),
            "p90": p90,
            # The bar is the composite p90 against the threshold, both as a
            # percentage of the same 0..1 axis, so "how far short" is a
            # LENGTH on the page and not an arithmetic exercise for the reader.
            "p90_pct": (round(min(1.0, max(0.0, float(p90))) * 100, 1)
                        if p90 is not None else None),
            "verdict": (d or {}).get("verdict") or "",
            "verdict_detail": (d or {}).get("verdict_detail") or "",
            "n_evaluated": (d or {}).get("n_evaluated"),
            "n_matched": (d or {}).get("n_matched"),
            "n_near_miss": (d or {}).get("n_near_miss"),
            "truncated": bool((d or {}).get("truncated")),
            "conditions": (d or {}).get("conditions") or [],
            "signals_7d": sig.get("n_7d", 0),
            "graded_ever": sig.get("n_graded", 0),
            "flags_7d": flg.get("n_7d", 0),
            "last_flag": flg.get("last"),
        })

    from signals.setup_diagnostics import VERDICTS
    order = {v: i for i, v in enumerate(VERDICTS)}
    rows.sort(key=lambda r: (order.get(r["verdict"], 99), -(r["signals_7d"] or 0),
                             r["name"]))

    # ── the never-fired card: silent setups and what binds them ──────
    never = []
    for r in rows:
        if r["armed"] and not r["signals_7d"] and not r["flags_7d"]:
            binding = ""
            for c in r["conditions"]:
                if c["n_unevaluable"] and not c["n_matched"]:
                    binding = (f"{c['kind']} — could not evaluate on "
                               f"{c['n_unevaluable']} instrument(s): "
                               f"{c['sample_reason'] or 'no reason given'}")
                    break
            if not binding:
                for c in r["conditions"]:
                    # `n_no_match` must be non-zero to say "evaluated and
                    # matched none": a condition behind a gate that shut is
                    # never reached, and "evaluated on 0 instrument(s) and
                    # matched none of them" accuses a leg that never ran.
                    if not c["n_matched"] and c["n_no_match"]:
                        binding = (f"{c['kind']} — evaluated on "
                                   f"{c['n_no_match']} instrument(s) and "
                                   f"matched none of them")
                        break
            if not binding:
                for c in r["conditions"]:
                    if c["n_not_reached"] and not c["n_matched"]:
                        binding = (f"{c['kind']} — never reached on "
                                   f"{c['n_not_reached']} instrument(s): a "
                                   f"gate above it shut the setup out first")
                        break
            r = dict(r)
            r["binding"] = binding
            never.append(r)

    # ── the grading leak (platform-wide → staff) ─────────────────────
    grading, grading_error = None, ""
    if not is_staff:
        grading_error = STAFF_ONLY
    else:
        try:
            grading = cache.get(GRADING_CACHE_KEY)
            if grading is None:
                from signals.setup_diagnostics import diagnose_grading
                grading = diagnose_grading(days=30)
                cache.set(GRADING_CACHE_KEY, grading,
                          SETUP_DIAGNOSTIC_CACHE_SECONDS)
        except Exception as e:  # noqa: BLE001
            logger.warning("[setups page] grading unreadable: %s", e)
            grading_error = f"{type(e).__name__}: {e}"[:160]

    # ── KPI strip ────────────────────────────────────────────────────
    n_flags_7d = sum(r["flags_7d"] or 0 for r in rows)
    n_signals_7d = sum(r["signals_7d"] or 0 for r in rows)
    n_graded = sum(r["graded_ever"] or 0 for r in rows)
    n_research = sum(1 for c in ctrls.values()
                     if getattr(c, "promotion_stage", "") == "research")
    n_promoted = sum(1 for c in ctrls.values()
                     if getattr(c, "promotion_stage", "") in
                     ("paper", "live_small", "live_full"))

    context = {
        "page_id": "setups",
        "is_staff": is_staff,
        "is_superuser": bool(request.user.is_superuser),
        "rows": rows,
        "never": never,
        "diag": diag,
        "diag_error": diag_error,
        "grading": grading,
        "grading_error": grading_error,
        "n_active": n_active,
        "n_inactive": n_inactive,
        "n_flags_7d": n_flags_7d,
        "n_signals_7d": n_signals_7d,
        "n_graded": n_graded,
        "n_research": n_research,
        "n_promoted": n_promoted,
        "scan_cadence": _scan_cadence(),
        "inactive_rows": [r for r in rows if not r["armed"]],
        "cache_seconds": SETUP_DIAGNOSTIC_CACHE_SECONDS,
        # ANY row, not the first one. The table is sorted by verdict, and an
        # unarmed setup — which carries no diagnostic row and so is never
        # `truncated` — can hold position zero, which silently hid the cap
        # from the whole page while every verdict under it was taken over 60
        # of 179 instruments (2026-09-12).
        "any_truncated": any(r["truncated"] for r in rows),
        "page_instrument_limit": PAGE_INSTRUMENT_LIMIT,
    }
    return render(request, "dashboard/setups.html", context)


def _scan_cadence() -> str:
    """The beat entry's own words, read from the schedule rather than typed
    here — a cadence sentence that is a second copy of the schedule is a
    sentence that goes stale the first time the schedule changes."""
    try:
        from config.celery import app
        entry = (app.conf.beat_schedule or {}).get("scan-opportunities")
        if entry is None:
            return "no beat entry — the scanner is not scheduled"
        return str(entry.get("schedule"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[setups page] cadence unreadable: %s", e)
        return "—"


@login_required
def setups_arm(request):
    """Arm one inactive setup — the superuser's form on /setups/.

    Goes through the generator's own `approve_proposal` where a pending
    proposal exists, so the re-validation and the audit row are the
    /generated/ page's and not a second path.
    """
    from django.contrib import messages
    from django.http import HttpResponseForbidden, HttpResponseNotAllowed
    from django.shortcuts import redirect

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not request.user.is_superuser:
        return HttpResponseForbidden("superuser only — arming makes the "
                                     "scanner grade a setup")

    from brain.generator_models import GeneratedSetupProposal
    from brain.strategy_generator import approval_blocker, approve_proposal
    from signals.models import OpportunitySetup, RuleControl

    name = (request.POST.get("name") or "").strip()
    setup = OpportunitySetup.objects.filter(name=name).first()
    if setup is None:
        messages.error(request, f"no setup named {name!r}")
        return redirect("setups_dashboard")
    if setup.is_active:
        messages.info(request, f"{name} is already armed")
        return redirect("setups_dashboard")

    # WHAT ARMING THIS ONE MEANS, read from the rule's own control row rather
    # than assumed. `is_active` decides whether the SCANNER looks at a setup;
    # `RuleControl.promotion_stage` decides whether any bot may act on what it
    # finds. At 'research' that gate is shut and arming risks nothing — but
    # this message used to promise that sentence to EVERY arm, including a
    # setup sitting at live_full and one with no control row at all, which
    # `stage_policy` treats as paper at full nominal size. A reassurance that
    # is only sometimes true is worse than none (2026-09-12).
    ctrl = RuleControl.objects.filter(rule_name=setup.name).first()
    stage = getattr(ctrl, "promotion_stage", "") or ""
    if stage == "research":
        consequence = ("the scanner will grade it and the stage gate keeps "
                       "every bot off it — this is safe")
    elif ctrl is None:
        consequence = ("THERE IS NO RuleControl ROW for this rule, so "
                       "stage_policy treats it as PAPER: it may trade, at "
                       "full nominal size, on the paper venue")
    else:
        consequence = (f"its stage is {stage!r}, NOT research — a signal from "
                       f"this setup may reach a venue")

    proposal = (GeneratedSetupProposal.objects
                .filter(setup=setup, status=GeneratedSetupProposal.STATUS_PENDING)
                .order_by("-created_at").first())
    if proposal is not None:
        blocker = approval_blocker(proposal)
        if blocker:
            messages.error(request, f"{name}: cannot arm — {blocker}")
        elif approve_proposal(proposal,
                              reviewed_by=request.user.get_username(),
                              notes="armed from /setups/"):
            messages.success(request, f"{name} armed via proposal "
                                      f"#{proposal.pk} — {consequence}.")
        else:
            messages.error(request, f"{name}: approve_proposal refused")
        return redirect("setups_dashboard")

    setup.is_active = True
    setup.save(update_fields=["is_active", "updated_at"])
    try:
        from bot_program.audit import record_event
        record_event("setup_armed", {"setup": setup.name, "setup_id": setup.pk,
                                     "path": "direct", "stage": stage or "none"},
                     user=request.user)
    except Exception as e:  # noqa: BLE001
        logger.warning("[setups page] audit failed for %s: %s", name, e)
    messages.success(request, f"{name} armed (no proposal row — flipped "
                              f"is_active directly, audited) — {consequence}.")
    return redirect("setups_dashboard")
