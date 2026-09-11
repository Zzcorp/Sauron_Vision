"""Read, arm or reject the strategy generator's proposals from the shell.

The brain page (/generated/) shows the pending proposals and takes a
click per decision. This is the same decision, without the page: the
same `approve_proposal` the page calls, the same blocker check before
it, the same audit row after it. Nothing here touches capital — an
approved proposal is a setup in RESEARCH stage: the scanner grades its
signals, the stage gate keeps every bot from trading it.

    python manage.py proposals list
    python manage.py proposals approve 10 11
    python manage.py proposals reject 12 --notes "duplicates rule X"
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List, approve (arm in research) or reject generator proposals."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "approve", "reject"])
        parser.add_argument("ids", nargs="*", type=int)
        parser.add_argument("--by", default="cli",
                            help="Who decides (stored as reviewed_by).")
        parser.add_argument("--notes", default="")
        parser.add_argument("--history", type=int, default=10,
                            help="list: how many decided rows to show.")

    def handle(self, *args, **opts):
        action = opts["action"]
        if action == "list":
            return self._list(opts["history"])
        if not opts["ids"]:
            raise CommandError(f"proposals {action}: give at least one id "
                               f"(see `proposals list`).")
        self._decide(action, opts["ids"], by=opts["by"], notes=opts["notes"])

    def _list(self, n_history):
        from brain.generator_models import GeneratedSetupProposal as P
        pending = list(P.objects.filter(status=P.STATUS_PENDING)
                       .order_by("-created_at"))
        self.stdout.write(f"PENDING ({len(pending)})")
        for p in pending:
            kinds = [c.get("kind") for c in (p.conditions or [])
                     if isinstance(c, dict)]
            self.stdout.write(
                f"  #{p.pk}  {p.proposed_name}  {p.direction}  "
                f"{','.join(p.asset_classes or [])}  conf {p.confidence:.2f}  "
                f"horizon {p.suggested_horizon_days}d  model {p.model_used}")
            self.stdout.write(f"       conditions: {', '.join(k for k in kinds if k)}")
            head = (p.rationale_md or "").replace("\n", " ").strip()
            if head:
                self.stdout.write(f"       {head[:220]}")
        history = list(P.objects.exclude(status=P.STATUS_PENDING)
                       .order_by("-created_at")[:n_history])
        self.stdout.write(f"\nDECIDED (last {len(history)})")
        for p in history:
            why = (p.review_notes or "").replace("\n", " ").strip()
            self.stdout.write(
                f"  #{p.pk}  {p.proposed_name}  {p.status.upper()}  "
                f"by {p.reviewed_by or '-'}  {why[:120]}")

    def _decide(self, action, ids, *, by, notes):
        from brain.generator_models import GeneratedSetupProposal as P
        from brain.strategy_generator import (approval_blocker,
                                              approve_proposal,
                                              reject_proposal)
        for pk in ids:
            row = P.objects.filter(pk=pk).first()
            if row is None:
                self.stdout.write(self.style.ERROR(f"#{pk}: not found"))
                continue
            if row.status != P.STATUS_PENDING:
                self.stdout.write(f"#{pk} {row.proposed_name}: already "
                                  f"{row.status}, untouched")
                continue
            if action == "approve":
                blocker = approval_blocker(row)
                if approve_proposal(row, reviewed_by=by, notes=notes):
                    self.stdout.write(self.style.SUCCESS(
                        f"#{pk} {row.proposed_name}: ARMED in research — "
                        f"the scanner grades it, no bot trades it"))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"#{pk} {row.proposed_name}: NOT armed — {blocker}"))
            else:
                reject_proposal(row, reviewed_by=by, notes=notes)
                self.stdout.write(f"#{pk} {row.proposed_name}: rejected")
