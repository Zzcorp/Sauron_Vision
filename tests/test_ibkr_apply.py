"""One command between the stored login and a running Gateway.

The old flow — print the block in the container, paste it into .env by
hand — is how a password containing `$$` reached the Gateway one `$`
short (compose expands unquoted .env values at READ time) and was refused
behind a dialog IBC cannot read, silently, for three hours.

`deploy/ibkr-apply` replaces the paste. Its first draft went through an
adversarial review that found two blockers, and these tests pin the
review's confirmed findings so none of them can quietly return:

  * the render command's human trailer once rode stdout into .env and
    broke every later compose invocation on the box — the splice takes
    only the marker-delimited span, and the trailer now goes to stderr;
  * an unquoted credential line is REFUSED, because splicing it would
    reintroduce the exact $$-eating bug;
  * an empty render must never replace working credentials;
  * the rewrite is atomic, the temp file dies on signals too, the backup
    is locked down and gitignored, and no failure path prints a secret.

Run with:  python manage.py test tests.test_ibkr_apply
"""
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

REPO = Path(settings.BASE_DIR)


def script():
    return (REPO / "deploy" / "ibkr-apply").read_text(encoding="utf-8")


class TheScriptRefusesTheOldBugsTests(TestCase):

    def test_it_exists_and_is_a_posix_script(self):
        self.assertTrue(script().startswith("#!/usr/bin/env sh"))

    def test_only_the_marker_span_is_spliced(self):
        """The render trailer once rode into .env and killed every later
        compose command on the live box."""
        s = script()
        self.assertIn('l.startswith("# >>> sauron:")', s)
        self.assertIn('l.startswith("# <<< sauron:")', s)

    def test_unquoted_credentials_are_refused(self):
        s = script()
        self.assertIn("_USERNAME='.+'", s)
        self.assertIn("_PASSWORD='.+'", s)
        self.assertIn("UNQUOTED", s)

    def test_an_empty_render_cannot_replace_a_working_login(self):
        self.assertIn("will not splice an empty login", script())

    def test_the_rewrite_is_atomic(self):
        s = script()
        self.assertIn("os.replace", s)
        self.assertIn("O_EXCL", s)

    def test_secrets_hygiene(self):
        """umask before anything writes; temp file dies on signals, not
        just clean exit; the backup is locked down; and no failure path
        cats the rendered block anywhere."""
        s = script()
        self.assertIn("umask 077", s)
        self.assertIn("HUP INT TERM", s)
        self.assertIn('chmod 600 "$envfile.bak"', s)
        self.assertNotIn('cat "$tmp"', s)

    def test_the_operator_is_warned_before_the_session_drops(self):
        s = script()
        self.assertLess(s.index("drops its current session"),
                        s.index("--force-recreate"))

    def test_the_backup_family_is_gitignored(self):
        text = (REPO / ".gitignore").read_text(encoding="utf-8")
        for name in (".env.bak", ".env.tmp", ".env.lock"):
            self.assertIn(name, text, name)

    def test_the_runbook_teaches_the_one_command_flow(self):
        text = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("./deploy/ibkr-apply", text)
        self.assertIn("Second factor", text)
        self.assertIn("IB Key push", text)


class TheRenderKeepsItsChannelsSeparateTests(TestCase):
    """stdout is the block; humans read stderr. A captured stdout with a
    sentence in it is how .env got a sentence in it."""

    def _render(self):
        u = User.objects.create_user("rt_u", password="x")
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(user=u, label="ISA",
                                          host="ibgateway", port=4003,
                                          client_id=1)
        acct.set_credentials("U1234567")
        acct.set_login("trader777", "pw!!++$$end")
        acct.save()
        out, err = StringIO(), StringIO()
        call_command("render_ibkr_env", stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_stdout_holds_nothing_after_the_end_marker(self):
        out, _ = self._render()
        tail = out.split("# <<< sauron: IBKR gateway logins", 1)[1]
        self.assertEqual(tail.strip(), "")

    def test_the_trailer_went_to_stderr(self):
        out, err = self._render()
        self.assertNotIn("Nothing written", out)
        self.assertIn("Nothing written", err)


class TheFormSaysWhatAUsernameIsTests(TestCase):
    """IBKR's refusal for a malformed username ("Example user name:
    trader777") surfaces in a dialog IBC cannot read — so the form has to
    prevent the mistake instead."""

    def _page(self):
        return (REPO / "templates" / "dashboard" / "admin_dashboard.html"
                ).read_text(encoding="utf-8")

    def test_the_username_hint_exists(self):
        page = self._page()
        self.assertIn("IBKR website", page)
        self.assertIn("not</strong> your email", page)

    def test_it_mentions_the_paper_username_and_the_second_factor(self):
        page = self._page()
        self.assertIn("PAPER account has its own", page)
        self.assertIn("IB Key", page)
