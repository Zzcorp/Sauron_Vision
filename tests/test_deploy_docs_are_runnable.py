"""deploy/IBKR_RETIREMENT.md and deploy/ETORO_DEPARTURE.md stay runnable as written (2026-09-23).

Both documents hand the operator commands. A stale username answers "no user";
a bare `python manage.py` on the VPS answers "command not found" outside the
container; an invented flag answers "unrecognized arguments". These pins fail
before the operator does.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(settings.BASE_DIR)
PREFIX = "./deploy/dc exec worker-fast python manage.py"


class RetirementDocTests(SimpleTestCase):

    def test_no_stale_username_and_every_command_carries_the_dc_prefix(self):
        t = (REPO / "deploy" / "IBKR_RETIREMENT.md").read_text(encoding="utf-8")
        self.assertNotIn("--user mathe", t)
        self.assertNotIn("username='mathe'", t)
        # the one bare spelling is the literal hint dashboard/views_system_health
        # prints, quoted verbatim, and it must stay bare
        hint = 'the hint "Run `python manage.py check_feeds`"'
        self.assertIn(hint, t)
        self.assertEqual(t.count("python manage.py"), t.count(PREFIX) + 1)
        self.assertIn("0035_alter_saxoaccount_is_primary_for_stocks", t)
        self.assertNotIn("migrations/0035_*.py", t)
        self.assertNotIn("shares --list", t)
        self.assertLess(t.find("## Stage 2 "), t.find("## Stage 2b"))
        self.assertLess(t.find("## Stage 2b"), t.find("## Stage 3"))


class DepartureDocTests(SimpleTestCase):

    def test_exists_names_the_rows_and_prefixes_every_command(self):
        path = REPO / "deploy" / "ETORO_DEPARTURE.md"
        self.assertTrue(path.exists())
        t = path.read_text(encoding="utf-8")
        for needle in ("#93", "#94", "#95", "config 10", 'metadata["broker"]',
                       "keyed_venue_count", "exit_price_inferred", "IBKRTrader",
                       "--user Sauron"):
            self.assertIn(needle, t)
        self.assertNotIn("mathe", t)
        self.assertNotIn("x-api-key", t)
        for ln in t.splitlines():
            if "python manage.py" in ln:
                self.assertIn(PREFIX, ln, ln)
