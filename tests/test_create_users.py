"""THE SEEDED USERS COME FROM THE ENVIRONMENT (2026-10-14).

core/management/commands/create_users.py once carried the platform's
roster in source — six usernames, the superuser's among them — in a
public repository. Now the roster is SAURON_PLATFORM_USERS
("name[:role],..."; role staff or superuser, which implies staff) and
each password SAURON_PW_<USERNAME>, as before. Unset or empty, the
command does nothing and names the variable; a listed user without a
password is skipped; the module's source holds no quoted username.

Run with:  python manage.py test tests.test_create_users
"""
import inspect
import os
import re
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.management.commands import create_users as cmd


class TheRosterIsRead(SimpleTestCase):

    def test_unset_or_empty_is_nobody(self):
        with mock.patch.dict(os.environ, {cmd.ROSTER_ENV: ""}):
            self.assertEqual(cmd.roster(), [])
        with mock.patch.dict(os.environ):
            os.environ.pop(cmd.ROSTER_ENV, None)
            self.assertEqual(cmd.roster(), [])
        self.assertEqual(cmd.roster(" , ,"), [])

    def test_the_three_role_forms(self):
        self.assertEqual(cmd.roster("alice, bob:staff ,carol:SUPERUSER"),
                         [("alice", False, False), ("bob", False, True),
                          ("carol", True, True)])

    def test_a_name_listed_twice_is_taken_once_and_an_unknown_role_raises(self):
        self.assertEqual(cmd.roster("alice:staff,alice"), [("alice", False, True)])
        with self.assertRaises(ValueError) as caught:
            cmd.roster("alice:root")
        self.assertIn("unknown role 'root'", str(caught.exception))

    def test_the_password_key_is_the_username_uppercased(self):
        self.assertEqual(cmd._env_key("Jean-Pierre"), "SAURON_PW_JEAN_PIERRE")
        self.assertEqual(cmd._env_key("alice"), "SAURON_PW_ALICE")

    def test_the_source_holds_no_quoted_username(self):
        """The old roster: a list of ("name", bool, bool) tuples. No
        string literal that looks like a login may sit in the module."""
        src = inspect.getsource(cmd)
        src = re.sub(r'"""[\s\S]*?"""', "", src, count=1)  # the docstring
        self.assertNotIn("PLATFORM_USERS = [", src)
        self.assertEqual(re.findall(r'\("[A-Za-z_]+",\s*(?:True|False),\s*(?:True|False)\)', src), [])


class TheCommandRuns(TestCase):

    def _run(self, env):
        out = StringIO()
        with mock.patch.dict(os.environ, env, clear=False):
            for key in list(os.environ):
                if key.startswith("SAURON_PW_") and key not in env:
                    os.environ.pop(key)
            if cmd.ROSTER_ENV not in env:
                os.environ.pop(cmd.ROSTER_ENV, None)
            call_command("create_users", stdout=out)
        return out.getvalue()

    def test_no_roster_creates_nobody_and_names_the_variable(self):
        before = User.objects.count()
        said = self._run({})
        self.assertEqual(User.objects.count(), before)
        self.assertIn(cmd.ROSTER_ENV, said)
        self.assertIn("Nothing to do", said)

    def test_a_roster_with_passwords_creates_the_users_with_their_roles(self):
        from alerts.models import UserNotificationPrefs
        from portfolio.trader_profile import TraderProfile
        said = self._run({cmd.ROSTER_ENV: "alice,bob:staff,carol:superuser",
                          "SAURON_PW_ALICE": "a-pass", "SAURON_PW_BOB": "b-pass",
                          "SAURON_PW_CAROL": "c-pass"})
        alice, bob, carol = (User.objects.get(username=n) for n in ("alice", "bob", "carol"))
        self.assertEqual((alice.is_superuser, alice.is_staff), (False, False))
        self.assertEqual((bob.is_superuser, bob.is_staff), (False, True))
        self.assertEqual((carol.is_superuser, carol.is_staff), (True, True))
        self.assertTrue(carol.check_password("c-pass"))
        for user in (alice, bob, carol):
            self.assertTrue(TraderProfile.objects.filter(user=user).exists())
            self.assertTrue(UserNotificationPrefs.objects.filter(user=user).exists())
        self.assertIn("Created: carol (superuser)", said)
        self.assertIn("Created: bob (staff)", said)
        self.assertIn("3 created, 0 updated, 0 skipped", said)
        for secret in ("a-pass", "b-pass", "c-pass"):
            self.assertNotIn(secret, said)

    def test_a_listed_user_without_a_password_is_skipped(self):
        said = self._run({cmd.ROSTER_ENV: "alice,dave:staff",
                          "SAURON_PW_ALICE": "a-pass"})
        self.assertTrue(User.objects.filter(username="alice").exists())
        self.assertFalse(User.objects.filter(username="dave").exists())
        self.assertIn("Skipped: dave — set SAURON_PW_DAVE", said)
        self.assertIn("1 created, 0 updated, 1 skipped", said)

    def test_a_second_run_updates_and_an_unknown_role_is_a_command_error(self):
        self._run({cmd.ROSTER_ENV: "alice", "SAURON_PW_ALICE": "one"})
        said = self._run({cmd.ROSTER_ENV: "alice:staff", "SAURON_PW_ALICE": "two"})
        alice = User.objects.get(username="alice")
        self.assertTrue(alice.is_staff)
        self.assertTrue(alice.check_password("two"))
        self.assertIn("Updated: alice (staff)", said)
        with self.assertRaises(CommandError) as caught:
            self._run({cmd.ROSTER_ENV: "alice:root", "SAURON_PW_ALICE": "two"})
        self.assertIn("unknown role 'root'", str(caught.exception))
        self.assertNotIn("two", str(caught.exception))
