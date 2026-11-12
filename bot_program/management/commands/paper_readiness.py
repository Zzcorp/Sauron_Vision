"""WILL 90 DAYS OF PAPER PRODUCE A GRADED TRACK RECORD? (2026-09-15)

`preflight_live` answers "is it safe to arm real money". This is its mirror,
and it exists because the operator asked to spend two to three months on a
full paper campaign and then arrive with evidence — which is exactly what a
real firm would ask for, and exactly what this platform can silently fail to
produce.

    python manage.py paper_readiness
    python manage.py paper_readiness --window-days 90

The measurement lives in `bot_program/campaign_readiness.py`, shared with
`watch_evidence_chain`, which runs the same check on a schedule and speaks
when the chain goes cold. This module is only the rendering: a command and a
watchdog that disagreed about whether the chain was cold would be the worst
possible pair.

It writes nothing and it makes no broker call. It also never reports a
component as ON because a default says so: the answer comes from the row, and
a missing row is printed as its own state, because "off" and "never seeded"
lead an operator to two different actions.

A LIVE OPERATION IS NAMED AS ONE (2026-11-12). With a bot armed for real
money the two paper checks (a live-action switch ON, no paper bot) are the
operator's decision, and this printed them under "BLOCKERS — 90 days would
produce nothing gradeable". For a live operation it now prints three groups:

    CHAIN FAULTS — evidence is not being produced
    LIVE BY DECISION — not a paper campaign, and no fault
    WORTH READING

and heads section 3 "LIVE-ACTION SWITCHES". For a paper campaign, or none,
the output is what it was, the heading "3. MONEY MUST NOT MOVE" and the one
BLOCKERS list included.
"""
from django.core.management.base import BaseCommand

from bot_program.campaign_readiness import (  # noqa: F401 — re-exported for
    EVIDENCE_CHAIN, MUST_BE_OFF, UNGATED, component_state, fleet_words,
    readiness)

#: Section 3 for a live operation: readiness() still names it "MONEY MUST
#: NOT MOVE", which is true of a paper campaign only.
LIVE_SWITCHES_HEADING = ("LIVE-ACTION SWITCHES — a paper campaign wants all "
                         "five off")


class Command(BaseCommand):
    help = ("Is the evidence chain complete? Read-only readiness check for a "
            "paper-trading campaign.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-days", type=int, default=30,
            help="Window for counting graded rows (default 30).")

    def handle(self, *args, **opts):
        report = readiness(opts.get("window_days") or 30)
        lines = []

        def w(text=""):
            lines.append(text)

        w("=" * 70)
        w("PAPER READINESS — WILL 90 DAYS PRODUCE A GRADED TRACK RECORD")
        w("=" * 70)

        live = report["campaign"] == "live"

        for i, (title, rows) in enumerate(report["sections"], 1):
            if live and title == "MONEY MUST NOT MOVE":
                title = LIVE_SWITCHES_HEADING
            w(f"\n{i}. {title}")
            for left, middle, right in rows:
                w(f"   {left:<30} {middle:<12} {right}".rstrip())
            if title == "THE EVIDENCE CHAIN":
                w("\n   Ungated by design — no switch to look for:")
                for task, every, what in UNGATED:
                    w(f"   {task.split('.')[-1]:<30} every {every}s  {what}")

        w("\n" + "=" * 70)
        if live:
            # The verdict names the kind: nothing below is a paper
            # campaign's blocker list.
            w(f"A LIVE OPERATION, NOT A PAPER CAMPAIGN — "
              f"{fleet_words(report['fleet'])}.")
            if report["blockers"]:
                w("\nCHAIN FAULTS — evidence is not being produced:")
                for i, m in enumerate(report["blockers"], 1):
                    w(f"  {i}. {m}")
            else:
                w("\nNO CHAIN FAULTS — the chain is complete end to end.")
            if report["campaign_gaps"]:
                w("\nLIVE BY DECISION — not a paper campaign, and no fault:")
                for i, m in enumerate(report["campaign_gaps"], 1):
                    w(f"  {i}. {m}")
        elif report["blockers"]:
            w("BLOCKERS — 90 days would produce nothing gradeable:")
            for i, m in enumerate(report["blockers"], 1):
                w(f"  {i}. {m}")
        else:
            w("NO BLOCKERS — the chain is complete end to end.")
        if report["notes"]:
            w("\nWORTH READING:")
            for i, m in enumerate(report["notes"], 1):
                w(f"  {i}. {m}")
        w("=" * 70)
        w("This command writes nothing and makes no broker call. It says")
        w("whether the chain CAN produce evidence, never whether the")
        w("evidence is good.")

        self.stdout.write("\n".join(lines) + "\n")
