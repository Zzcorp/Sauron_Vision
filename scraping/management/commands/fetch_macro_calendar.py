"""Fetch the macro calendar by hand, and say plainly what happened.

The scheduled task runs it every 30 minutes inside the Economic Calendar
component. This exists for the first run and for diagnosis: an operator who
sees UNCHECKED on a forex position needs one command that tells them
whether the key is missing, the plan refuses the endpoint, or the fortnight
is genuinely quiet — three states that all used to look like an empty
table.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fetch upcoming macro events (FMP) into EconomicEvent."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14,
                            help="How far ahead to look (default 14).")

    def handle(self, *args, **opts):
        from scraping.scrapers.macro_calendar import fetch_macro_calendar_fmp

        out = fetch_macro_calendar_fmp(days_ahead=opts["days"])
        if out.get("skipped"):
            self.stderr.write(self.style.WARNING(
                "SKIPPED (%s) — every forex position stays UNCHECKED "
                "until FMP_API_KEY is set." % out["skipped"]))
            return
        if out.get("error"):
            self.stderr.write(self.style.ERROR(
                "FAILED: %s" % out["error"]))
            return
        self.stdout.write(self.style.SUCCESS(
            "parsed %s, stored %s high/low-impact events"
            % (out["parsed"], out["stored"])))
        if not out["stored"]:
            self.stdout.write(
                "Nothing stored. That is a genuinely quiet fortnight for "
                "the eight traded currencies — not a failure.")
