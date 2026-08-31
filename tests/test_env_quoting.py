"""The password reached the Gateway with a dollar sign missing.

`render_ibkr_env` wrote `IBKR_PASSWORD=<raw value>` into .env. Compose
interpolates .env values: `$$` is its escape for a single `$`, `${x}` is a
variable, and an unquoted value can end early at `#` or a space. The
operator's password held `$$`; the container received it one `$` short;
IBKR answered "Authorization failed: Invalid username or password" —
inside an HTML notice box the IBC automation cannot read, so the failure
surfaced as a Gateway sitting silently behind a dialog for three hours.

Compose takes a SINGLE-QUOTED .env value literally: no interpolation, no
escapes. That is the fix, with a double-quoted fallback for the one value
single quotes cannot hold — one that contains a single quote — escaping
the three characters compose treats specially inside double quotes.

Run with:  python manage.py test tests.test_env_quoting
"""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase


class TheQuoterTests(SimpleTestCase):

    def _q(self, v):
        from bot_program.management.commands.render_ibkr_env import _env_quote
        return _env_quote(v)

    def test_a_plain_value_is_single_quoted(self):
        self.assertEqual(self._q("trader777"), "'trader777'")

    def test_dollar_signs_survive_untouched_inside_single_quotes(self):
        """The operator's case. `$$` must reach the container as `$$`,
        not as compose's escaped single `$`."""
        self.assertEqual(self._q("pw!!++$$x"), "'pw!!++$$x'")

    def test_hash_and_space_survive(self):
        self.assertEqual(self._q("a #b c"), "'a #b c'")

    def test_a_single_quote_forces_the_double_quoted_form(self):
        out = self._q("it's$1")
        self.assertTrue(out.startswith('"') and out.endswith('"'))
        # `$` doubled, quote preserved, nothing else touched.
        self.assertEqual(out, '"it\'s$$1"')

    def test_double_quotes_and_backslashes_are_escaped_in_that_form(self):
        out = self._q('a"b\\c\'d')
        self.assertEqual(out, '"a\\"b\\\\c\'d"')

    def test_empty_is_an_empty_quoted_string_not_nothing(self):
        """`IBKR_PASSWORD=` and `IBKR_PASSWORD=''` differ to a reader; the
        rendered file must always show a value was written."""
        self.assertEqual(self._q(""), "''")


class TheRenderedBlockIsSafeForComposeTests(TestCase):

    def test_the_operators_password_renders_intact(self):
        from bot_program.models import IBKRAccount
        u = User.objects.create_user("q_u", password="x")
        acct = IBKRAccount.objects.create(user=u, label="ISA", host="ibgateway",
                                          port=4003, client_id=1)
        acct.set_credentials("U1234567")
        acct.set_login("trader777", "pw!!++$$end")
        acct.save()
        out = StringIO()
        call_command("render_ibkr_env", stdout=out)
        text = out.getvalue()
        self.assertIn("IBKR_USERNAME='trader777'", text)
        self.assertIn("IBKR_PASSWORD='pw!!++$$end'", text)
        self.assertIn("IBKR_TRADING_MODE=live", text)

    def test_what_compose_would_read_back_is_the_original(self):
        """Simulate compose's single-quote rule: the literal between the
        quotes, no interpolation. This is the round trip that failed."""
        from bot_program.management.commands.render_ibkr_env import _env_quote
        for pw in ("pw!!++$$end", "a #b", "${HOME}", "x$$y$z"):
            rendered = _env_quote(pw)
            self.assertTrue(rendered.startswith("'"))
            self.assertEqual(rendered[1:-1], pw)
