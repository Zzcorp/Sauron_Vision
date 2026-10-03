"""The next steps Sauron read in its own reports (ai_agents/next_steps.py),
from the shell: what is waiting, and the operator's yes or no.

    python manage.py next_steps list
    python manage.py next_steps approve 12
    python manage.py next_steps reject 12
    python manage.py next_steps read weekly_review   # read the latest report again, now

Approving a pause or a size cut creates a RuleAction PROPOSAL for HQ (the
actuator applies it under its own switch and caps); approving a watch
stars the instrument; a note is acknowledged. `read` re-runs the reader on
the latest stored report of that kind and costs one fast-tier call.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List, approve or reject the next steps Sauron read in its reports."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "approve", "reject",
                                               "read"])
        parser.add_argument("target", nargs="?", default="")

    def handle(self, *args, **opts):
        from ai_agents import next_steps as ns
        from ai_agents.models import ReportNextStep
        w = self.stdout.write
        action, target = opts["action"], opts["target"]
        if action == "list":
            rows = ns.for_page(limit=50)
            if not rows:
                w("No next step is waiting.")
                return
            w(f"{len(rows)} next step(s) waiting:")
            for r in rows:
                w(f"  #{r['id']:<5} {r['kind_words']:<14} {r['ref']:<18} "
                  f"from {r['report_words']} · {r['age_words']} · "
                  f"{r['confidence_pct']}%")
                w(f"         {r['why']}")
                w(f"         approving {r['consequence']}")
            return
        if action in ("approve", "reject"):
            try:
                step = ReportNextStep.objects.get(pk=int(target))
            except (TypeError, ValueError, ReportNextStep.DoesNotExist):
                raise CommandError(f"next_steps {action}: give the id of a "
                                   f"waiting step (see `next_steps list`)")
            before = step.status
            step = (ns.approve if action == "approve" else ns.reject)(step)
            if before != ReportNextStep.PENDING:
                w(f"#{step.pk} was already {before}: unchanged")
                return
            tail = ""
            if step.rule_action_id:
                tail = (f" — RuleAction #{step.rule_action_id} proposed; an "
                        f"admin applies it at HQ")
            elif step.kind == "watch" and action == "approve":
                tail = f" — {step.ref} is on the watchlist"
            w(f"#{step.pk} {step.kind} {step.ref}: {before} → {step.status}{tail}")
            return
        if target not in ns.REPORTS:
            raise CommandError(f"next_steps read: one of "
                               f"{', '.join(ns.REPORTS)}")
        text = _latest_report_text(target)
        if not text:
            raise CommandError(f"no stored {target} to read")
        made = ns.extract(target, text, source_ref="manual read")
        w(f"{len(made)} step(s) proposed from {ns.REPORTS[target]}"
          + (" (is agent_next_steps ON?)" if not made else ""))


def _latest_report_text(kind) -> str:
    """The newest stored text of one report kind, as its task stored it."""
    from ai_agents.models import AgentTask
    agent, key = {"daily_briefing": ("daily_briefing", "briefing"),
                  "weekly_review": ("weekly_reviewer", "review"),
                  "monday_plan": ("monday_plan", "plan")}.get(kind, (None, None))
    if agent is None:
        from alerts.scheduled_digests import digest_lines, generate_eod_digest
        return "\n".join(digest_lines(generate_eod_digest(user=None)))
    row = (AgentTask.objects.filter(agent=agent, success=True)
           .order_by("-created_at").first())
    return str((row.structured_output or {}).get(key) or "") if row else ""
