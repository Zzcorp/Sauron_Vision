"""The Morgul guards, run once by hand (bot_program/morgul.py).

Every guard reads the book once and the findings are printed: the facts,
what the brake would stop, and what was not judged and why. READ ONLY
by default: nothing is sent, nothing is stopped, not even the guards'
memory is written. --send runs the beat's own cycle instead: the
three-hour dedupe, the brake while its switch (morgul_brake) AND the
guards' (morgul_guards) are ON, the messages to the staff Telegram group
and the memory -- one run at a time, as the beat's.

    python manage.py morgul
    python manage.py morgul --send
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Run every Morgul guard once and print the findings. Sends "
            "nothing and stops nothing unless --send.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--send", action="store_true",
            help="run the beat's cycle: dedupe, the brake if its switch "
                 "and the guards' are on, the Telegram messages, the memory")

    def handle(self, *args, **opts):
        from bot_program import morgul
        send = bool(opts.get("send"))
        report = morgul.cycle(send=send)
        if report.result.get("idle"):
            self.stdout.write(f"Nothing done: {report.result['idle']} "
                              f"(one run at a time; try again in a few "
                              f"minutes).")
            return
        for line in morgul.render_report(report):
            self.stdout.write(line)
        if not send:
            self.stdout.write("Read only: nothing was sent and nothing was "
                              "stopped (--send runs the beat's cycle).")
            return
        result = report.result
        stopped = ", ".join(result.get("stopped") or []) or "nothing"
        self.stdout.write(f"Sent: {result.get('sent', 0)} message(s) · "
                          f"due: {result.get('due', 0)} · back to normal: "
                          f"{result.get('cleared', 0)} · stopped: {stopped}")
        if result.get("skipped"):
            self.stdout.write(f"Not sent: {result['skipped']}.")
