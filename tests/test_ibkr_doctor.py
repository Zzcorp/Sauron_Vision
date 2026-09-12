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

    def test_healthy_is_not_logged_in(self):
        """2026-09-11: the container said (healthy), every API request
        timed out, the reading was 19h old, launcher.log said
        'Authorization failed' — and the verdict said 'logged in' and
        sent the operator to restart the workers. The healthy branch
        must read step 3 and step 5 before it trusts the healthcheck."""
        src = _script()
        start = src.index('*"(healthy)"*')
        healthy = src[start:src.index('    "")', start)]
        self.assertIn('[ -n "$session" ] || [ -n "$stale" ]', healthy)
        self.assertIn("NOT the login", healthy)
        self.assertIn("Restarting the workers changes nothing", healthy)
        self.assertIn("approve the IB Key notification", healthy)
        self.assertIn('restart $svc', healthy)
        # And the facts it reads come from the steps above it.
        self.assertIn('case "$pre" in *"no equity reading has landed"*', src)
        self.assertIn('case "$after" in', src)
        self.assertIn('*"Authorization failed"*', src)
        self.assertIn('*"Existing session detected"*', src)
        # The dialog IBC leaves for a human: the fix is a recreate with the
        # compose's EXISTING_SESSION_DETECTED_ACTION, never a restart.
        self.assertIn("EXISTING_SESSION_DETECTED_ACTION=primary", src)
        self.assertIn("up -d $svc", src)

    def test_a_completed_login_resets_the_clock(self):
        """2026-09-11 18:46: a clean login one minute old, container
        healthy, reading 25h old because the sync had not run since —
        and the verdict said 'session lost' because the successful
        'Second Factor Authentication' dialog matched its pattern. Only
        what step 2 shows AFTER the last 'Login has completed' can be a
        problem; a fresh login with a stale reading means 'run the sync'."""
        src = _script()
        self.assertIn('after="${ibc##*Login has completed}"', src)
        self.assertIn('case "$after" in', src)
        self.assertIn('*"Second Factor Authentication initiated"*', src)
        self.assertNotIn('*"Second Factor"*', src)
        self.assertNotIn('*"second factor"*|', src)
        # The server's refusal is evidence only while no login completed.
        self.assertIn('if [ -z "$login_done" ]; then', src)
        start = src.index('*"(healthy)"*')
        healthy = src[start:src.index('    "")', start)]
        self.assertIn('[ -n "$login_done" ] && [ -z "$session" ]', healthy)
        self.assertIn("the broker sync has not run since", healthy)
        self.assertIn("sync_broker_account", healthy)
        self.assertIn("Nothing to do here", healthy)

    def test_the_api_churn_is_hidden_not_the_ibc_lines(self):
        """Sauron's reconnects leave 'remove Client N' forty times over
        and bury IBC's one line; the doctor hides the churn, counts it,
        and says what it means."""
        src = _script()
        self.assertIn('grep -v "remove Client"', src)
        self.assertIn('grep -c "remove Client"', src)
        self.assertIn("lines hidden", src)

    def test_the_runbook_points_at_it(self):
        runbook = (Path(settings.BASE_DIR) / "deploy" / "RUNBOOK.md"
                   ).read_text(encoding="utf-8")
        self.assertIn("./deploy/ibkr-doctor", runbook)


def _session_lost_substrings():
    """The literals the script's own `case "$after"` tests, read OUT of the
    script rather than restated here — a test that keeps its own copy of
    the patterns passes while the script says something else."""
    src = _script()
    start = src.index('case "$after" in')
    line = src[start:src.index("esac", start)]
    line = line[line.index("\n") + 1:]          # drop the `case` line itself
    return re.findall(r'\*"([^"]+)"\*', line)


def _looks_lost(tail: str) -> bool:
    subs = _session_lost_substrings()
    assert subs, "no patterns extracted — the case block was re-spelled"
    return any(s in tail for s in subs)


class TheReauthenticationItMissedTests(SimpleTestCase):
    """2026-09-13: six hours of a dead broker reported as healthy.

    The IBC log, AFTER a 'Login has completed' at 11:53:39, read:

        16:00:27 detected frame entitled: Connecting to server...; Opened
        16:00:33 detected frame entitled: Attempt 3: Authenticating
                 (trying for another 1772548 seconds)...
        16:00:33 detected dialog entitled: IBKR Gateway; event=Opened

    — a dialog that never carried an `event=Closed`, unlike every other
    dialog in the file. The API accepted Sauron's sockets and answered
    nothing (116 `remove Client` lines), the equity reading went 2.3h
    stale, and preflight blocked arming. The doctor said "nothing went
    wrong after it".

    It said that because `$session` stayed empty: the pattern asked for
    "detected dialog entitled: Gateway" and the title was "IBKR Gateway",
    and no pattern knew what a re-authentication looks like. The branch
    that would have given the right answer — "this is the Gateway's
    SESSION, restarting the workers changes nothing, phone first" — was
    already written and simply never reached.
    """

    REAL_TAIL = (
        "\nibgateway-1  | 2026-09-12 16:00:27:128 IBC: detected frame "
        "entitled: Connecting to server...; event=Activated"
        "\nibgateway-1  | 2026-09-12 16:00:33:796 IBC: detected frame "
        "entitled: Attempt 3: Authenticating (trying for another 1772548 "
        "seconds)...; event=Lost focus"
        "\nibgateway-1  | 2026-09-12 16:00:33:803 IBC: detected dialog "
        "entitled: IBKR Gateway; event=Opened"
        "\nibgateway-1  | 2026-09-12 16:00:33:913 IBC: detected dialog "
        "entitled: IBKR Gateway; event=Activated\n"
    )

    def test_the_outage_that_was_called_healthy_now_reads_as_lost(self):
        self.assertTrue(
            _looks_lost(self.REAL_TAIL),
            "the 2026-09-13 outage still reads as a healthy session")

    def test_each_of_the_three_shapes_is_caught_on_its_own(self):
        """Three independent tells. Any one of them alone must be enough —
        an outage that shows only the dialog, or only the retry frame,
        is the same outage."""
        for name, line in (
            ("the IBKR Gateway dialog",
             "IBC: detected dialog entitled: IBKR Gateway; event=Opened"),
            ("a re-authentication attempt",
             "IBC: detected frame entitled: Attempt 3: Authenticating "
             "(trying for another 1772548 seconds)...; event=Opened"),
            ("a reconnect to the server",
             "IBC: detected frame entitled: Connecting to server...; "
             "event=Opened"),
        ):
            with self.subTest(shape=name):
                self.assertTrue(_looks_lost(line), f"{name} reads as fine")

    def test_the_plain_gateway_dialog_is_still_caught(self):
        """The older shape the pattern was written for. Broadening the
        match must not drop it."""
        self.assertTrue(_looks_lost(
            "IBC: detected dialog entitled: Gateway; event=Opened"))

    def test_a_quiet_tail_after_a_completed_login_is_not_an_alarm(self):
        """The other half of the contract, and the reason this is not just
        'match more things'. $after holds only what follows the LAST
        'Login has completed', so a login that began and finished moved
        the marker and left nothing here. A tail with no authentication in
        it must stay silent, or the doctor cries wolf on every healthy box
        and the operator stops reading it."""
        quiet = (
            "\nibgateway-1  | 2026-09-12 11:53:40:001 IBC: detected dialog "
            "entitled: U28134395 Trader Workstation Configuration; "
            "event=Closed"
            "\nibgateway-1  | 2026-09-12 12:10:02:114 IBC: Configuration "
            "tasks completed\n"
        )
        self.assertFalse(_looks_lost(quiet),
                         "a healthy post-login tail now reports a lost "
                         "session — every box would show red")

    def test_the_verdict_reached_by_this_is_the_session_branch(self):
        """Catching it is only half: it must land on the branch that says
        phone-then-recreate, not the one that says restart the workers."""
        src = _script()
        start = src.index('*"(healthy)"*')
        healthy = src[start:src.index('    "")', start)]
        self.assertIn('elif [ -n "$session" ] || [ -n "$stale" ]', healthy)
        branch = healthy[healthy.index('elif [ -n "$session" ]'):]
        self.assertIn("This is the Gateway's SESSION", branch)
        self.assertIn("Restarting the workers changes nothing", branch)
        self.assertIn("approve the IB Key notification", branch)
