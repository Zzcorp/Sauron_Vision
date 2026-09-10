"""One read-only command for "the broker is unreachable".

"IBKR is unreachable" has had four different causes on this platform — a
Gateway up but not logged in, a login the server refused, an API session
lost while the Gateway stayed up, and a stale reading on the dashboard —
and each time the operator was handed a fresh ad-hoc command to tell them
apart. `deploy/ibkr-doctor` runs the runbook's checks and the two the
runbook could not, prints them in the order that decides, and names the
next step. It takes none of those steps itself.

Run with:  python manage.py test tests.test_ibkr_doctor
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _script() -> str:
    return (Path(settings.BASE_DIR) / "deploy" / "ibkr-doctor").read_text(
        encoding="utf-8")


def _commands(src: str):
    """Lines that RUN something: not comments, not echo text."""
    for raw in src.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("echo "):
            continue
        yield line


class TheDoctorTests(SimpleTestCase):

    def test_it_exists_and_is_a_posix_script(self):
        src = _script()
        self.assertTrue(src.startswith("#!/usr/bin/env sh\n"))
        self.assertIn("set -u", src)

    def test_it_changes_nothing(self):
        """Read-only is the contract: the operator decides the next step.
        Every mutating verb is allowed only inside comments and the echoed
        advice, never on a line that runs."""
        forbidden = re.compile(
            r"\b(restart|up -d|--force-recreate|down|kill|stop|rm)\b")
        for line in _commands(_script()):
            self.assertIsNone(forbidden.search(line),
                              f"a mutating command in a read-only script: "
                              f"{line}")

    def test_it_runs_the_runbooks_launcher_log_check(self):
        src = _script()
        self.assertIn("/home/ibgateway/Jts/launcher.log", src)
        self.assertIn("Authorization failed", src)

    def test_it_probes_both_relays_from_the_web_container(self):
        src = _script()
        self.assertIn("4003", src)
        self.assertIn("4004", src)
        # And says why an open relay proves nothing on its own.
        self.assertIn("step 1's health is the truth", src)

    def test_it_reads_sauron_too(self):
        self.assertIn("manage.py preflight_live", _script())

    def test_the_verdict_tells_the_three_states_apart(self):
        src = _script()
        self.assertIn('*"(unhealthy)"*', src)
        self.assertIn('*"(healthy)"*', src)
        self.assertIn("ibkr-apply", src)       # not running at all
        self.assertIn("326", src)              # the session, not the Gateway

    def test_the_runbook_points_at_it(self):
        runbook = (Path(settings.BASE_DIR) / "deploy" / "RUNBOOK.md"
                   ).read_text(encoding="utf-8")
        self.assertIn("./deploy/ibkr-doctor", runbook)
