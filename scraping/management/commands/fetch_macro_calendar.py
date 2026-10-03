"""Fetch the macro calendar by hand, and say plainly what happened.

The scheduled task runs it every 30 minutes inside the Economic Calendar
component. This exists for the first run and for diagnosis: an operator who
sees UNCHECKED on a forex position needs one command that tells them
which source answered (Forex Factory first, FMP only when it failed), why
neither did, or that the fortnight is genuinely quiet — states that all
used to look like an empty table.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Fetch upcoming macro events into EconomicEvent — Forex Factory, "
            "FMP as the fallback.")

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14,
                            help="How far ahead FMP looks when it is the "
                                 "fallback (default 14).")

    def handle(self, *args, **opts):
        from scraping.scrapers.macro_calendar import fetch_macro_calendar

        out = fetch_macro_calendar(days_ahead=opts["days"])
        if out.get("skipped"):
            self.stderr.write(self.style.WARNING(
                "SKIPPED (%s) — every forex position stays UNCHECKED "
                "until a macro source answers." % out["skipped"]))
            return
        if out.get("error"):
            # Scrubbed explicitly: this goes to stderr, which never passes
            # through a logging handler, and the string is built from
            # `raise_for_status()` messages that carry the full URL —
            # including the apikey that authenticated the call.
            from core.secret_scrub import scrub
            self.stderr.write(self.style.ERROR(
                "FAILED: %s" % scrub(out["error"])))
            return
        source = out.get("source") or "the macro source"
        weeks = out.get("weeks")
        self.stdout.write(self.style.SUCCESS(
            "parsed %s, stored %s high/low-impact events (%s%s)"
            % (out["parsed"], out["stored"], source,
               ", " + " + ".join(weeks) if weeks else "")))
        if out.get("fallback_after"):
            self.stdout.write(self.style.WARNING(
                "Forex Factory failed (%s); FMP answered instead."
                % out["fallback_after"]))
        if out.get("failures"):
            self.stdout.write(self.style.WARNING(
                "One week did not answer: %s" % "; ".join(out["failures"])))
        if not out["stored"]:
            self.stdout.write(
                "Nothing stored. That is a genuinely quiet fortnight for "
                "the eight traded currencies — not a failure.")
