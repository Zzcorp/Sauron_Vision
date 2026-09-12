"""The share allocator's page (/shares/), as a command.

The page lists what the allocator proposed — a TARGET share of the
broker account per live follower pool, with every factor that went into
it — and takes a click per decision. This is that click without the
page: the same `propose_share_plan` the beat runs, the same
`apply_share_plan` (LIVE mode required, fresh reading required, three
applies a day, snapshot for rollback), the same `reject_share_plan` and
`rollback_share_plan`, the same audit row after each. Applying writes
each follower's `extras["account_share_pct"]` and re-splits the pools
through the sync's own arithmetic; it never writes a pool's capital by
hand and never talks to the broker.

The PIN gate is the page's; a shell on the server is already behind SSH,
and `--yes` is the deliberate act here. Say so when handing this to an
operator. Without `--yes`, apply and rollback only print what they would
write.

    python manage.py shares list                  # mode, pending, applied, last grade
    python manage.py shares list --user alice
    python manage.py shares propose --user alice  # a plan now, or the reason there is none
    python manage.py shares apply 12              # plan only
    python manage.py shares apply 12 --yes        # write it (LIVE mode only)
    python manage.py shares reject 12 13
    python manage.py shares rollback 12 --yes
    python manage.py shares grade                 # score every plan whose 24h closed
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("List, propose, apply, reject or roll back share plans "
            "(the /shares/ page's buttons).")

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "propose", "apply",
                                               "reject", "rollback", "grade"])
        parser.add_argument("ids", nargs="*", type=int)
        parser.add_argument("--user", default="",
                            help="Username: whose plans to list, or whose "
                                 "followers to propose for (propose needs it).")
        parser.add_argument("--yes", action="store_true",
                            help="apply / rollback: write. Without it the "
                                 "command only prints the plan.")
        parser.add_argument("--by", default="",
                            help="Username recorded as confirmed_by "
                                 "(default: none).")

    def handle(self, *args, **opts):
        act = opts["action"]
        if act == "list":
            return self._list(opts["user"])
        if act == "grade":
            return self._grade()
        if act == "propose":
            if not opts["user"]:
                raise CommandError("shares propose: give --user NAME "
                                   "(whose followers to size).")
            return self._propose(self._user(opts["user"]))
        ids = list(opts["ids"])
        if not ids:
            raise CommandError(f"shares {act}: give at least one id "
                               f"(see `shares list`).")
        by = self._user(opts["by"]) if opts["by"] else None
        for pk in ids:
            self._decide(act, pk, by, yes=opts["yes"])

    # ── helpers ──────────────────────────────────────────────────────────
    def _user(self, username):
        from django.contrib.auth import get_user_model
        row = get_user_model().objects.filter(username=username).first()
        if row is None:
            raise CommandError(f"no user {username!r}")
        return row

    def _mode(self):
        from bot_program.share_allocator import is_live_mode
        return ("LIVE (apply allowed)" if is_live_mode()
                else "SHADOW (apply disabled)")

    def _print_plan(self, plan, *, indent="  "):
        """One line per config: current → target, and the sentence of why.
        The same numbers the page shows — a plan the shell cannot explain
        is a plan the operator cannot paste back as proof."""
        reading = (f"{float(plan.reading_value):.2f} {plan.reading_currency}"
                   if plan.reading_value is not None else "no reading")
        stamp = {
            plan.STATE_APPLIED: plan.applied_at,
            plan.STATE_REJECTED: plan.rejected_at,
            plan.STATE_ROLLED_BACK: plan.rolled_back_at,
        }.get(plan.state) or plan.proposed_at
        self.stdout.write(
            f"{indent}#{plan.pk:<4} {plan.state.upper():<12} "
            f"{stamp:%m-%d %H:%M}  reading {reading}  "
            f"drawdown {float(plan.drawdown_pct or 0) * 100:.1f}%  "
            f"governor {float(plan.governor):.2f}")
        # The market state the plan was computed under, and why: a SHOCK
        # plan reads "down uncapped, up frozen" and the operator must see
        # that before the numbers, not infer it from them.
        mode = (getattr(plan, "mode", "") or "normal").upper()
        reasons = "; ".join(str(r) for r in (plan.mode_reasons or []))
        self.stdout.write(f"{indent}     mode {mode}"
                          + (f" — {reasons}" if reasons else ""))
        inputs = plan.inputs or {}
        current = plan.current_shares or {}
        for k, target in (plan.targets or {}).items():
            row = inputs.get(k, {})
            cur = current.get(k)
            cur_s = f"{float(cur):g}%" if cur is not None else "auto"
            tag = "  [held]" if row.get("held") else ""
            self.stdout.write(
                f"{indent}     [{k}] {row.get('name', '?'):<22} "
                f"{cur_s:>7} → {float(target):g}%{tag}")
            why = (row.get("why") or "").strip()
            if why:
                self.stdout.write(f"{indent}          {why}")
        if plan.grade_score is not None:
            self.stdout.write(f"{indent}     grade {plan.grade_score:+.4f} "
                              f"(configs graded: "
                              f"{(plan.grade_detail or {}).get('n_graded_configs', 0)})")
        if plan.notes:
            self.stdout.write(f"{indent}     notes: {plan.notes[:200]}")

    # ── list ─────────────────────────────────────────────────────────────
    def _list(self, username):
        from django.contrib.auth import get_user_model

        from bot_program.capital_truth import (account_equity, allocate_shares,
                                               followers_of, share_label)
        from bot_program.models import IBKRAccount
        from bot_program.share_allocator import (MAX_APPLIES_PER_DAY,
                                                 applies_used_today)
        from bot_program.share_models import SharePlan

        self.stdout.write(f"share allocator {self._mode()}")
        User = get_user_model()
        users = ([self._user(username)] if username else
                 list(User.objects.filter(
                     pk__in=IBKRAccount.objects.exclude(account_id_enc="")
                     .values_list("user_id", flat=True)).order_by("username")))
        for user in users:
            reading = account_equity(user)
            followers = followers_of(user)
            alloc = allocate_shares(followers)
            head = (f"{float(reading['value']):.2f} {reading['currency'] or ''} "
                    f"(age {int(reading['age_seconds']) // 60}m)"
                    if reading else "no reading")
            self.stdout.write(
                f"{user.username}: account {head}, {len(followers)} follower(s), "
                f"applies today {applies_used_today(user)}/{MAX_APPLIES_PER_DAY}")
            for f in followers:
                self.stdout.write(f"  [{f.pk}] {f.name:<22} "
                                  f"{share_label(f, alloc.get('plan')):<9} "
                                  f"pool {f.capital}")
            if not alloc["ok"]:
                self.stdout.write(self.style.ERROR(
                    f"  OVER-ALLOCATED: {alloc['reason']}"))

        plans = SharePlan.objects.all()
        if username:
            plans = plans.filter(user__username=username)
        pending = list(plans.filter(state=SharePlan.STATE_PROPOSED)
                       .order_by("-proposed_at"))
        self.stdout.write(f"\nPROPOSED ({len(pending)})")
        for p in pending:
            self._print_plan(p)
        applied = list(plans.filter(state=SharePlan.STATE_APPLIED)
                       .order_by("-applied_at")[:10])
        self.stdout.write(f"\nAPPLIED, rollback possible ({len(applied)})")
        for p in applied:
            self._print_plan(p)
        last = (plans.filter(graded_at__isnull=False)
                .order_by("-graded_at").first())
        self.stdout.write("\nLAST GRADED")
        if last is None:
            self.stdout.write("  none yet — a plan is graded 24h after it "
                              "is proposed, against the live closes in "
                              "that window")
        else:
            score = ("ungradeable (no live close in the window)"
                     if last.grade_score is None else f"{last.grade_score:+.4f}")
            self.stdout.write(f"  #{last.pk} {last.state} "
                              f"graded {last.graded_at:%m-%d %H:%M}: {score}")

    # ── propose ──────────────────────────────────────────────────────────
    def _propose(self, user):
        from bot_program.share_allocator import propose_share_plan_with_reason
        plan, reason = propose_share_plan_with_reason(user)
        if plan is None:
            self.stdout.write(self.style.WARNING(
                f"{user.username}: nothing proposed — {reason}"))
            return
        self.stdout.write(self.style.SUCCESS(
            f"{user.username}: proposed plan #{plan.pk} "
            f"({self._mode()} — nothing is re-sized until it is applied)"))
        self._print_plan(plan)

    # ── grade ────────────────────────────────────────────────────────────
    def _grade(self):
        from bot_program.share_allocator import grade_plans
        n = grade_plans()
        self.stdout.write(f"graded {n} plan(s) — positive means the plan "
                          f"leaned toward the pools that then paid")

    # ── apply / reject / rollback ────────────────────────────────────────
    def _decide(self, act, pk, by, *, yes):
        from bot_program.share_allocator import (ShareAllocatorError,
                                                 apply_share_plan,
                                                 reject_share_plan,
                                                 rollback_share_plan)
        from bot_program.share_models import SharePlan
        plan = SharePlan.objects.filter(pk=pk).first()
        if plan is None:
            self.stdout.write(self.style.ERROR(f"#{pk}: not found"))
            return
        if act in ("apply", "rollback") and not yes:
            self.stdout.write(f"share allocator {self._mode()}")
            self._print_plan(plan)
            if act == "rollback":
                for k, prev in (plan.previous_shares or {}).items():
                    name = (plan.inputs or {}).get(k, {}).get("name", "?")
                    back = f"{float(prev):g}%" if prev is not None else "auto (key removed)"
                    self.stdout.write(f"       [{k}] {name:<22} back to {back}")
            self.stdout.write("(plan only — add --yes to write)")
            return
        fn = {"apply": apply_share_plan, "reject": reject_share_plan,
              "rollback": rollback_share_plan}[act]
        try:
            plan = fn(pk, by)
        except ShareAllocatorError as e:
            self.stdout.write(self.style.ERROR(f"#{pk}: {e}"))
            return
        if act == "apply":
            n = len(plan.targets or {}) - int(plan.configs_skipped or 0)
            self.stdout.write(self.style.SUCCESS(
                f"#{pk}: APPLIED — {n} pool(s) re-sized from the account "
                f"reading; every follower's share is now explicit"))
            self._print_plan(plan)
        elif act == "rollback":
            self.stdout.write(self.style.SUCCESS(
                f"#{pk}: ROLLED BACK — previous shares restored exactly"))
        else:
            self.stdout.write(f"#{pk}: rejected")
