"""Why a setup never fires — the /setups/ page as a command.

Sixteen of the twenty-six research-stage rules on this platform have never
produced one gradable signal in their life (2026-09-12), and until this
command existed nothing anywhere said whether their conditions were too
strict, their data was missing, or they missed the threshold by 0.02. These
five verbs are that answer:

    list      every setup: armed or not, stage, signals in 7d, graded ever
    diagnose  every active setup's verdict, worst first, one sentence each
    show      one setup's conditions, per-condition counts, composite spread
    arm       arm the setups the generator wrote and nobody clicked
    grading   how many signals died closed and ungraded — invisible evidence

ARMING A RESEARCH-STAGE SETUP IS SAFE. A setup's `is_active` flag decides
whether the SCANNER looks at it; `RuleControl.promotion_stage` decides whether
any bot may act on what it finds, and at 'research' `stage_policy` returns
may_trade False — no order is ever placed. So arming a research-stage setup
buys evidence and risks nothing. `arm` says so on every row, and REFUSES to
stay quiet about a setup whose stage is anything else: that one may reach a
venue, and the operator has to read the word before typing --yes.

Where a GeneratedSetupProposal exists for the setup, `arm` goes through
`brain.strategy_generator.approve_proposal` — the /generated/ page's own call,
with its `approval_blocker` re-validation and its audit row — rather than a
second path that would flip the flag without either.

    python manage.py setups list
    python manage.py setups diagnose
    python manage.py setups diagnose --near-miss 0.15 --limit 40
    python manage.py setups show starter_forex_breakout
    python manage.py setups arm advanced_smc_long              # plan only
    python manage.py setups arm advanced_smc_long --yes        # writes
    python manage.py setups grading --days 30
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Diagnose why an opportunity setup never fires; arm the ones "
            "nobody clicked.")

    def add_arguments(self, parser):
        parser.add_argument("action",
                            choices=["list", "diagnose", "show", "arm", "grading"])
        parser.add_argument("names", nargs="*",
                            help="show: one setup name. arm: one or more.")
        parser.add_argument("--near-miss", type=float, default=0.10,
                            help="diagnose/show: how far below the threshold still counts as near.")
        parser.add_argument("--limit", type=int, default=None,
                            help="diagnose: cap the instruments scanned per setup.")
        parser.add_argument("--days", type=int, default=30,
                            help="grading: the window, in days.")
        parser.add_argument("--yes", action="store_true",
                            help="arm: write. Without it the command only prints the plan.")
        parser.add_argument("--by", default="cli",
                            help="arm: who decided (stored as reviewed_by).")

    def handle(self, *args, **opts):
        action = opts["action"]
        if action == "list":
            return self._list()
        if action == "diagnose":
            return self._diagnose(opts["near_miss"], opts["limit"])
        if action == "show":
            if not opts["names"]:
                raise CommandError("setups show: give a setup name (see `setups list`).")
            return self._show(opts["names"][0], opts["near_miss"])
        if action == "grading":
            return self._grading(opts["days"])
        if not opts["names"]:
            raise CommandError("setups arm: give at least one setup name "
                               "(see `setups list`).")
        return self._arm(opts["names"], yes=opts["yes"], by=opts["by"])

    # ── list ───────────────────────────────────────────────────────────
    def _list(self):
        from datetime import timedelta

        from django.db.models import Count, Max, Q
        from django.utils import timezone

        from signals.models import (OpportunityFlag, OpportunitySetup,
                                    RuleControl, Signal)

        now = timezone.now()
        week = now - timedelta(days=7)
        setups = list(OpportunitySetup.objects.all().order_by("name"))
        if not setups:
            self.stdout.write("No OpportunitySetup rows at all. The starter "
                              "pack is `python manage.py seed_strategies`.")
            return
        # One grouped query per fact, keyed by rule_name — every join between
        # Signal / RuleControl / OpportunitySetup is a STRING, so there is no
        # select_related to lean on and a per-row helper would be a query a row.
        sig = {r["rule_name"]: r for r in (
            Signal.objects.values("rule_name").annotate(
                n_7d=Count("id", filter=Q(created_at__gte=week)),
                n_graded=Count("id", filter=Q(is_active=False)
                               & ~Q(outcome="") & Q(realized_r__isnull=False))))}
        flags = {r["setup__name"]: r["last"] for r in (
            OpportunityFlag.objects.values("setup__name")
            .annotate(last=Max("scanned_at")))}
        ctrls = {c.rule_name: c for c in RuleControl.objects.all()}

        self.stdout.write(f"{len(setups)} setup(s) · "
                          f"{sum(1 for s in setups if s.is_active)} armed")
        self.stdout.write(f"{'setup':44} {'armed':6} {'stage':11} "
                          f"{'7d':>4} {'graded':>7}  last flag")
        for s in setups:
            row = sig.get(s.name) or {}
            ctrl = ctrls.get(s.name)
            stage = getattr(ctrl, "promotion_stage", "") or "no control row"
            last = flags.get(s.name)
            last_txt = last.strftime("%Y-%m-%d") if last else "never"
            self.stdout.write(
                f"{s.name[:44]:44} {'yes' if s.is_active else 'NO':6} "
                f"{stage[:11]:11} {row.get('n_7d', 0):>4} "
                f"{row.get('n_graded', 0):>7}  {last_txt}")
        self.stdout.write("\n`setups diagnose` says why the ones with no flag "
                          "have none; `setups arm <name> --yes` arms an "
                          "unarmed one.")

    # ── diagnose ───────────────────────────────────────────────────────
    def _diagnose(self, near_miss, limit):
        from signals.setup_diagnostics import VERDICT_LABEL, diagnose_setups

        rep = diagnose_setups(near_miss=near_miss, limit_instruments=limit)
        if not rep["setups"]:
            self.stdout.write("No ACTIVE setup to diagnose. `setups list` "
                              "shows the unarmed ones; `setups arm <name> "
                              "--yes` arms one.")
            return
        self.stdout.write(
            f"{rep['n_setups']} active setup(s) × {rep['n_instruments']} active "
            f"instrument(s) in {rep['seconds']}s · near-miss band "
            f"{rep['near_miss']:.2f} · read {rep['as_of']:%Y-%m-%d %H:%M} UTC")
        # --limit caps the population PER SETUP, and the line above counts the
        # whole universe. Without this the header claims 179 instruments while
        # every verdict under it was taken over 40 — and a verdict saying a
        # condition "never" matches is a claim about the rows actually walked.
        n_capped = sum(1 for r in rep["setups"] if r["truncated"])
        if n_capped:
            self.stdout.write(self.style.WARNING(
                f"CAPPED at --limit {limit}: {n_capped} of {len(rep['setups'])} "
                f"setup(s) below were read over the first {limit} instrument(s) "
                f"of their asset classes, not all of them. Drop --limit for a "
                f"verdict about the whole universe."))
        counts = " · ".join(f"{v}={rep['by_verdict'].get(v, 0)}"
                            for v in ("fires", "near", "strict", "blind", "empty"))
        self.stdout.write(counts + "\n")
        last = None
        for r in rep["setups"]:
            if r["verdict"] != last:
                last = r["verdict"]
                self.stdout.write(f"\n── {VERDICT_LABEL[last]}")
            p90 = "—" if r["composite_p90"] is None else f"{r['composite_p90']:.2f}"
            self.stdout.write(
                f"  {r['name'][:44]:44} p90 {p90} / thr "
                f"{r['min_match_score']:.2f} · {r['n_matched']} matched of "
                f"{r['n_evaluated']}")
            self.stdout.write(f"      {r['verdict_detail']}")
        self.stdout.write("\n`setups show <name>` opens one of these row by row.")

    # ── show ───────────────────────────────────────────────────────────
    def _show(self, name, near_miss):
        from signals.models import OpportunitySetup
        from signals.setup_diagnostics import VERDICT_LABEL, diagnose_setups

        setup = OpportunitySetup.objects.filter(name=name).first()
        if setup is None:
            near = list(OpportunitySetup.objects
                        .filter(name__icontains=name[:12])
                        .values_list("name", flat=True)[:5])
            hint = f" Did you mean: {', '.join(near)}?" if near else ""
            raise CommandError(f"no setup named {name!r}.{hint}")
        rep = diagnose_setups(setups=[setup], near_miss=near_miss)
        r = rep["setups"][0]
        self.stdout.write(f"{r['name']}  ({r['direction']})  "
                          f"{'ARMED' if setup.is_active else 'NOT ARMED'}")
        self.stdout.write(f"  asset classes : "
                          f"{', '.join(r['asset_classes']) or 'every class'}")
        self.stdout.write(f"  threshold     : {r['min_match_score']:.2f}")
        self.stdout.write(f"  population    : {r['n_evaluated']} instrument(s)"
                          + (" (TRUNCATED)" if r["truncated"] else ""))
        self.stdout.write(f"  verdict       : {VERDICT_LABEL[r['verdict']]}")
        self.stdout.write(f"  {r['verdict_detail']}")
        self.stdout.write("")
        self.stdout.write(f"{'condition':26} {'match':>6} {'no-match':>9} "
                          f"{'CANNOT EVAL':>12}  why it could not")
        for c in r["conditions"]:
            gate = " [gate]" if c["gate"] else ""
            self.stdout.write(
                f"{(c['kind'] + gate)[:26]:26} {c['n_matched']:>6} "
                f"{c['n_no_match']:>9} {c['n_unevaluable']:>12}  "
                f"{c['sample_reason'][:60]}")
            if c["n_not_reached"]:
                self.stdout.write(f"{'':26} {c['n_not_reached']} pair(s) never "
                                  f"reached this condition — a gate above it shut")
        self.stdout.write("")
        p50 = "—" if r["composite_p50"] is None else f"{r['composite_p50']:.3f}"
        p90 = "—" if r["composite_p90"] is None else f"{r['composite_p90']:.3f}"
        mx = "—" if r["composite_max"] is None else f"{r['composite_max']:.3f}"
        self.stdout.write(f"composite  p50 {p50}  p90 {p90}  max {mx} "
                          f"({r['best_instrument'] or 'no instrument'})  "
                          f"threshold {r['min_match_score']:.2f}")
        self.stdout.write(f"near misses {r['n_near_miss']} · gate-skipped "
                          f"{r['n_gate_skipped']} · no price {r['n_no_price']} "
                          f"· below quorum {r['n_quorum_failed']}")
        self.stdout.write(f"measured in {rep['seconds']}s, writing nothing.")

    # ── arm ────────────────────────────────────────────────────────────
    def _arm(self, names, *, yes, by):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import approval_blocker, approve_proposal
        from signals.models import OpportunitySetup, RuleControl

        ctrls = {c.rule_name: c for c in RuleControl.objects.all()}
        n_done = 0
        for name in names:
            setup = OpportunitySetup.objects.filter(name=name).first()
            if setup is None:
                self.stdout.write(self.style.ERROR(
                    f"{name}: no such setup (see `setups list`)"))
                continue
            if setup.is_active:
                self.stdout.write(f"{name}: already armed — nothing to do")
                continue

            ctrl = ctrls.get(name)
            stage = getattr(ctrl, "promotion_stage", "") or ""
            if stage == "research":
                self.stdout.write(
                    f"{name}: stage 'research' — the scanner will grade it and "
                    f"the stage gate keeps every bot off it. Safe.")
            elif ctrl is None:
                # stage_policy's own answer for a rule with no control row.
                self.stdout.write(self.style.WARNING(
                    f"{name}: NO RuleControl row — stage_policy treats such a "
                    f"rule as PAPER: it may trade, at full size, on the paper "
                    f"venue. Not research. Read that before --yes."))
            else:
                self.stdout.write(self.style.WARNING(
                    f"{name}: stage {stage!r} — NOT research. A signal from "
                    f"this setup may reach a venue. Read that before --yes."))

            proposal = (GeneratedSetupProposal.objects
                        .filter(setup=setup,
                                status=GeneratedSetupProposal.STATUS_PENDING)
                        .order_by("-created_at").first())
            if proposal is not None:
                blocker = approval_blocker(proposal)
                if blocker:
                    self.stdout.write(self.style.ERROR(
                        f"{name}: cannot arm — {blocker}"))
                    continue
                self.stdout.write(f"{name}: would arm via approve_proposal "
                                  f"(proposal #{proposal.pk}) — re-validated "
                                  f"and audited by the generator's own path")
                if not yes:
                    continue
                if approve_proposal(proposal, reviewed_by=by,
                                    notes="armed from `setups arm`"):
                    n_done += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"{name}: armed (proposal #{proposal.pk} approved)"))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"{name}: approve_proposal refused — "
                        f"{approval_blocker(proposal) or 'no reason given'}"))
                continue

            # No proposal row: the generator never wrote one, or it was already
            # decided. Flip the flag directly and audit it here, because the
            # generator's audit row hangs off a proposal that does not exist.
            self.stdout.write(f"{name}: no pending proposal — would flip "
                              f"is_active directly, with its own audit event")
            if not yes:
                continue
            setup.is_active = True
            setup.save(update_fields=["is_active", "updated_at"])
            try:
                from bot_program.audit import record_event
                record_event("setup_armed", {
                    "setup": setup.name, "setup_id": setup.pk,
                    "path": "direct", "stage": stage or "none",
                    "by": by,
                })
            except Exception as e:  # noqa: BLE001 — an audit hiccup must not
                # make the operator think the arm failed; it did not.
                self.stdout.write(self.style.WARNING(
                    f"{name}: armed, but the audit row failed: {e}"))
            n_done += 1
            self.stdout.write(self.style.SUCCESS(f"{name}: armed (direct)"))

        if not yes:
            self.stdout.write("\n(plan only — add --yes to write)")
        else:
            self.stdout.write(f"\n{n_done} setup(s) armed. "
                              f"`setups diagnose` says what they will do.")

    # ── grading ────────────────────────────────────────────────────────
    def _grading(self, days):
        from signals.setup_diagnostics import diagnose_grading

        rep = diagnose_grading(days=days)
        t = rep["totals"]
        self.stdout.write(f"Signals CREATED in the last {rep['days']} days, and "
                          f"what they became:")
        self.stdout.write(f"  created {t['n_created']} · closed {t['n_closed']} "
                          f"· graded {t['n_graded']} · closed ungraded "
                          f"{t['n_closed_ungraded']} · closed with no outcome "
                          f"{t['n_expired_no_outcome']}")
        if t["leak_pct"] is None:
            self.stdout.write("  leak rate: unmeasured — nothing closed in the "
                              "window, so there is no share to take.")
        else:
            self.stdout.write(f"  leak rate: {t['leak_pct']}% of closed signals "
                              f"carry no realized_r — INVISIBLE to the "
                              f"promotion ladder and to every evidence lane.")
        if not rep["rules"]:
            self.stdout.write(f"No signal was created in {rep['days']} days. "
                              f"`setups diagnose` says why.")
            return
        self.stdout.write(f"\n{'rule':40} {'made':>5} {'closed':>7} "
                          f"{'graded':>7} {'ungraded':>9} {'no outcome':>11}")
        for r in rep["rules"]:
            self.stdout.write(
                f"{r['rule_name'][:40]:40} {r['n_created']:>5} "
                f"{r['n_closed']:>7} {r['n_graded']:>7} "
                f"{r['n_closed_ungraded']:>9} {r['n_expired_no_outcome']:>11}")
        if rep["worst"]:
            self.stdout.write("\nWorst leaks: " + ", ".join(
                f"{r['rule_name']} ({r['n_lost']})" for r in rep["worst"]))
