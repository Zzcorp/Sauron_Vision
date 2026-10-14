"""deploy/IBKR_RETIREMENT.md and deploy/ETORO_DEPARTURE.md stay runnable as written (2026-09-23).

Both documents hand the operator commands. A stale username answers "no user";
a bare `python manage.py` on the VPS answers "command not found" outside the
container; an invented flag answers "unrecognized arguments". These pins fail
before the operator does.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(settings.BASE_DIR)
PREFIX = "./deploy/dc exec worker-fast python manage.py"
# A `stop` or `rm` through the wrapper with nothing after it but the end of
# the command: without a service name compose takes the WHOLE stack down.
BARE_STOP = re.compile(
    r"\./deploy/dc(?:\s+--profile\s+\S+)*\s+(?:stop|rm)(?:\s+-f)?\s*"
    r"(?:$|&&|\|\||;|`|\)|\"|#)")


def _assert_no_login_name(case, text):
    """Every --user and username= in a deploy document is <you>, so is
    the login that prefixes `follow`'s printed line (`<name>: account
    ...`, bot_program/management/commands/follow.py), and the text
    carries none of the private terms the server lists."""
    from core.leak_walk import private_terms_in
    for m in re.finditer(r"--user[ =]([^\s`'\",.;)]+)", text):
        case.assertIn(m.group(1), ("<you>", "help"), m.group(0))
    for m in re.finditer(r"username=['\"]([^'\"]+)['\"]", text):
        case.assertEqual(m.group(1), "<you>", m.group(0))
    for m in re.finditer(r"`(\S+): account ", text):
        case.assertEqual(m.group(1), "<you>", m.group(0))
    case.assertEqual(private_terms_in(text), [])


class RetirementDocTests(SimpleTestCase):

    def test_no_login_name_and_every_command_carries_the_dc_prefix(self):
        """The two deploy documents name no login: every --user and every
        username= is the placeholder <you> (the operator's own name stands
        behind it on the box), and no private term of the server's list
        (core/leak_walk.py; the canary alone where none is configured)."""
        t = (REPO / "deploy" / "IBKR_RETIREMENT.md").read_text(encoding="utf-8")
        _assert_no_login_name(self, t)
        # the proof that quotes follow's printed line keeps the placeholder
        # where the command prints the login
        self.assertIn("`<you>: account <value> USD, N follower(s)`", t)
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

    def test_stage_6_stops_the_gateway_slots_and_nothing_else(self):
        """Stage 6 gave `docker compose -f deploy/docker-compose.yml
        --profile ibkr … stop` / `rm -f` with no service name — every
        service of the project, postgres to caddy, while eToro live rows
        were still being managed — and no --env-file, the trap deploy/dc
        exists to close. Every compose command goes through the wrapper
        and every stop/rm names its slot, as ETORO_DEPARTURE §2c does."""
        t = (REPO / "deploy" / "IBKR_RETIREMENT.md").read_text(encoding="utf-8")
        self.assertNotIn("docker compose", t)
        for ln in t.splitlines():
            self.assertIsNone(BARE_STOP.search(ln), ln)
        self.assertIn("./deploy/dc --profile ibkr stop ibgateway", t)
        self.assertIn("./deploy/dc --profile ibkr rm -f ibgateway", t)
        self.assertIn("./deploy/dc --profile ibkr2 stop ibgateway-2", t)

    def test_the_proof_that_the_socket_is_gone_is_taken_where_sauron_connects(self):
        """A host `ss -ltnp` for 4001-4004 returns nothing whether or not a
        Gateway is logged in behind them: the compose never publishes a
        Gateway port to the box (tests/test_ibkr_gateway_service). The
        proof is the compose-network connect the runbook already uses."""
        t = (REPO / "deploy" / "IBKR_RETIREMENT.md").read_text(encoding="utf-8")
        self.assertIn("create_connection(('ibgateway', 4003)", t)
        self.assertNotRegex(t, r"ss -ltnp[^\n]*must return nothing")


class DepartureDocTests(SimpleTestCase):

    def test_exists_names_the_rows_and_prefixes_every_command(self):
        path = REPO / "deploy" / "ETORO_DEPARTURE.md"
        self.assertTrue(path.exists())
        t = path.read_text(encoding="utf-8")
        for needle in ("#93", "#94", "#95", "config 10", 'metadata["broker"]',
                       "keyed_venue_count", "exit_price_inferred", "IBKRTrader",
                       "--user <you>"):
            self.assertIn(needle, t)
        _assert_no_login_name(self, t)
        self.assertNotIn("x-api-key", t)
        for ln in t.splitlines():
            if "python manage.py" in ln:
                self.assertIn(PREFIX, ln, ln)

    def test_the_dated_env_backup_is_gitignored_and_the_doc_says_so(self):
        """§2c copies .env — SECRET_KEY, FERNET_KEY, the database password
        and the Gateway login it is about to delete — to a dated
        `.env.bak.<date>` in the checkout. .gitignore covered `.env.bak`
        by exact name only, so the dated copy was an ordinary untracked
        file that a `git add -A` from the box would have staged."""
        t = (REPO / "deploy" / "ETORO_DEPARTURE.md").read_text(encoding="utf-8")
        self.assertIn(".env.bak.$(date +%F)", t)
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env.bak.*", ignore)
        self.assertIn("`.env.bak.*`", t)


class FollowDenominatorDocTests(SimpleTestCase):

    def test_the_commands_it_names_exist_as_spelled(self):
        """`follow` lists when given no id and `shares` takes a positional
        `list`; neither has a --list flag, and argparse answers
        'unrecognized arguments' to the spelling the note used."""
        t = (REPO / "deploy" / "FOLLOW_DENOMINATOR.md").read_text(encoding="utf-8")
        self.assertNotIn("--list", t)
        self.assertIn("`shares list`", t)
        self.assertIn("`follow`", t)
