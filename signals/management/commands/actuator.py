"""The rule actuator's Apply / Reject / Rollback buttons, as a command.

The admin page lists the actuator's proposals — "pause rule", "reduce
size" — one per decay investigation, and takes a click per decision.
This is that click without the page: the same `apply_action` (live mode
required, daily caps, snapshot for rollback), the same `reject_action`,
the same `rollback_action`. Nothing here touches capital or a broker:
a pause sets a rule's weight to zero for 30 days, a reduction halves it,
and both can be rolled back.

The page has no "reject the duplicates" button, and the investigation
re-proposes the same enforcement every day it still holds — six "pause
macd_bullish_crossover" rows for one finding. `--stale` rejects every
proposal that a newer one on the same rule and action supersedes.

    python manage.py actuator list
    python manage.py actuator apply 11 9
    python manage.py actuator reject 2 4 6
    python manage.py actuator reject --stale
    python manage.py actuator rollback 11
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List, apply, reject or roll back rule-actuator proposals (the page's buttons)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "apply", "reject", "rollback"])
        parser.add_argument("ids", nargs="*", type=int)
        parser.add_argument("--stale", action="store_true",
                            help="reject: every proposal a newer one on the same "
                                 "rule and action supersedes.")
        parser.add_argument("--by", default="",
                            help="Username recorded as confirmed_by (default: none).")

    def handle(self, *args, **opts):
        from signals.models import RuleAction
        act = opts["action"]
        if act == "list":
            return self._list()
        ids = list(opts["ids"])
        if act == "reject" and opts["stale"]:
            ids += self._stale_ids()
            if not ids:
                self.stdout.write("no stale proposals")
                return
        if not ids:
            raise CommandError(f"actuator {act}: give at least one id "
                               f"(see `actuator list`).")
        user = self._user(opts["by"])
        for pk in ids:
            self._decide(act, pk, user)

    # ── helpers ──────────────────────────────────────────────────────────
    def _user(self, username):
        if not username:
            return None
        from django.contrib.auth import get_user_model
        row = get_user_model().objects.filter(username=username).first()
        if row is None:
            raise CommandError(f"no user {username!r}")
        return row

    def _stale_ids(self):
        """Proposed rows that decide nothing any more: a newer row on the
        same rule and action exists in ANY state (applied on the page,
        rejected, or a fresher proposal), or the enforcement is already
        in effect on the rule (pausing a paused rule, reducing a reduced
        or paused one). 2026-09-11: the first cut only looked at other
        PROPOSED rows, so a pause the page had already applied did not
        make the older proposal stale, and applying it paused the rule
        twice."""
        from signals.models import RuleAction
        from signals.rule_actuator import _control_for, _enforcement_in_effect
        newest_any = {}
        for r in RuleAction.objects.exclude(
                action__in=("monitor", "investigate_data", "retune_params")
        ).order_by("-proposed_at", "-id"):
            newest_any.setdefault((r.rule_name, r.action), r.id)
        stale = []
        for r in (RuleAction.objects.filter(state=RuleAction.STATE_PROPOSED)
                  .order_by("-proposed_at", "-id")):
            key = (r.rule_name, r.action)
            if newest_any.get(key) != r.id:
                stale.append(r.id)
            elif _enforcement_in_effect(_control_for(r.rule_name), r.action):
                stale.append(r.id)
        return stale

    def _list(self):
        from signals.models import RuleAction
        from signals.rule_actuator import (MAX_PAUSES_PER_DAY,
                                           MAX_REDUCTIONS_PER_DAY,
                                           _daily_count, is_live_mode)
        mode = "LIVE (apply allowed)" if is_live_mode() else "SHADOW (apply disabled)"
        self.stdout.write(
            f"actuator {mode}; today {_daily_count('pause_rule')}/{MAX_PAUSES_PER_DAY} "
            f"pauses, {_daily_count('reduce_size')}/{MAX_REDUCTIONS_PER_DAY} reductions")
        stale = set(self._stale_ids())
        pending = list(RuleAction.objects.filter(state=RuleAction.STATE_PROPOSED)
                       .order_by("rule_name", "action", "-proposed_at"))
        self.stdout.write(f"PROPOSED ({len(pending)})")
        from signals.rule_actuator import _control_for, _enforcement_in_effect
        for r in pending:
            tag = ""
            if r.id in stale:
                effect = _enforcement_in_effect(_control_for(r.rule_name), r.action)
                tag = (f"  [stale — rule already {effect}]" if effect
                       else "  [stale — a newer row on this rule and action exists]")
            why = (r.rationale or "").replace("\n", " ").strip()
            self.stdout.write(f"  #{r.id:<4} {r.action:<12} {r.rule_name:<32} "
                              f"{r.proposed_at:%m-%d %H:%M}{tag}")
            if why:
                self.stdout.write(f"        {why[:150]}")
        applied = list(RuleAction.objects.filter(state=RuleAction.STATE_APPLIED)
                       .order_by("-applied_at")[:10])
        self.stdout.write(f"\nAPPLIED, rollback possible ({len(applied)})")
        for r in applied:
            self.stdout.write(f"  #{r.id:<4} {r.action:<12} {r.rule_name:<32} "
                              f"applied {r.applied_at:%m-%d %H:%M}")

    def _decide(self, act, pk, user):
        from signals.models import RuleAction
        from signals.rule_actuator import (ActuatorError, apply_action,
                                           reject_action, rollback_action)
        row = RuleAction.objects.filter(pk=pk).first()
        if row is None:
            self.stdout.write(self.style.ERROR(f"#{pk}: not found"))
            return
        fn = {"apply": apply_action, "reject": reject_action,
              "rollback": rollback_action}[act]
        try:
            row = fn(pk, user)
        except ActuatorError as e:
            self.stdout.write(self.style.ERROR(f"#{pk} {row.action} {row.rule_name}: {e}"))
            return
        verb = {"apply": "APPLIED", "reject": "rejected",
                "rollback": "ROLLED BACK"}[act]
        line = f"#{pk} {row.action} {row.rule_name}: {verb}"
        if act == "apply":
            line += (" — weight 0 for 30 days" if row.action == RuleAction.ACTION_PAUSE
                     else " — weight ×0.5")
        self.stdout.write(self.style.SUCCESS(line) if act != "reject" else line)
