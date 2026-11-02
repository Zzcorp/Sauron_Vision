"""The platform's own short proofs on eToro's DEMO account (2026-10-31,
bot_program/short_proofs.py).

    python manage.py short_proofs_demo --dry-run                 # the plan: nothing sent
    python manage.py short_proofs_demo                           # one step now, as the beat runs it
    python manage.py short_proofs_demo --class etf --leverage 2  # that step now
    python manage.py short_proofs_demo --class index --overnight # hold one across the close

ONE step, the one the beat would take (bot_program.tasks.run_short_proofs_
demo, every 15 minutes): close a demo position the runner holds (closes
first), or prove the next class whose short no code pins — eToro's demo
row, a SELL of the venue minimum, the fill read, the close, the close
read — at 1x, then 2x and 5x where eToro lists them, then once per class
an overnight hold that measures the overnight fee. Only on eToro's DEMO
segment: the client is built from the keys, never from the eToro row's
demo flag, refuses any URL off the demo segment before it is sent, and
follows no redirect.

--dry-run prints every step and its state (done, due, waiting for its
market, held, blocked, in its back-off) and sends nothing, whatever the
switch says. A step named by hand (--class, --leverage, --overnight) is
not spaced out from the last one; a multiplier or the overnight hold named
by hand runs whatever its record says, never while a demo position is held
(whatever its class: one class at a time) or its market is shut. The dry
run names, too, each real close pending that the runner does not wait on,
and why (2026-11-02: a close eToro already holds, which the retry task
only reads, and one the retry task holds back behind it, for which it
sends nothing while that close stands). Refused while the component
short_proofs_demo is OFF and while a step is in doubt (cleared on
/short-proofs/ with the trading PIN). --user names whose eToro keys
(default: the first row that has both).

Deliberately NOT runnable from the ops page: it presents the operator's
eToro keys to an external service and places orders on the demo account.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("One step of the platform's own short proofs on eToro's demo "
            "account (--dry-run: the plan, nothing sent).")

    def add_arguments(self, parser):
        from bot_program.short_proofs import CLASS_ORDER, LEVERAGES
        parser.add_argument("--dry-run", action="store_true",
                            help="print the plan; send nothing")
        parser.add_argument("--class", dest="asset_class",
                            choices=CLASS_ORDER, default=None,
                            help="the class to prove")
        parser.add_argument("--leverage", type=int, choices=LEVERAGES,
                            default=None, help="the multiplier to prove")
        parser.add_argument("--overnight", action="store_true",
                            help="hold one short across the close")
        parser.add_argument("--user", default="",
                            help="whose eToro keys (default: the first "
                                 "row that has both)")

    def handle(self, *args, **opts):
        from bot_program import short_proofs as sp
        w = self.stdout.write
        user = None
        if opts["user"]:
            user = get_user_model().objects.filter(
                username=opts["user"]).first()
            if user is None:
                raise CommandError(f"No user {opts['user']!r}.")
        kw = dict(asset_class=opts["asset_class"],
                  leverage=opts["leverage"], overnight=opts["overnight"],
                  user=user)
        if opts["dry_run"]:
            out = sp.run_once(dry_run=True, **kw)
            w("A dry run: nothing is sent to eToro.")
            w(f"Switch {sp.SWITCH_KEY}: "
              f"{'ON' if out['switch'] else 'OFF'}; eToro keys on file: "
              f"{'yes' if out['keyed'] else 'no'}.")
            if out["stopped"]:
                w(f"STOPPED: {out['stopped']}.")
            if out["refusing"]:
                w(f"Waiting on the live lane: {out['refusing']}.")
            if out["not_waited_on"]:
                words = out["not_waited_on"]
                w(f"{words[0].upper()}{words[1:]}.")
            for step in out["plan"]:
                w("  " + sp.step_words(step))
            if not out["plan"]:
                w("  no class is left to prove: every short is pinned in "
                  "the code")
            return
        if not sp.switch_on():
            raise CommandError(
                f"The switch {sp.SWITCH_KEY} is OFF: nothing was sent. "
                f"Turn it on with `python manage.py component on "
                f"{sp.SWITCH_KEY}`.")
        out = sp.run_once(**kw)
        if out.get("status") == "error":
            raise CommandError(out.get("error") or "the step failed")
        if out.get("status") == "skipped":
            w(f"Nothing sent: {out.get('reason')}.")
            return
        w(f"{out.get('did')} ({out.get('requests', 0)} requests to "
          f"eToro's demo account).")
