"""The Wall walked for leaks (2026-10-08).

The Wall is the most public page of a public repository, read by anyone
who finds the address, and the answer a visitor receives is more than its
visible words: the stylesheet, the scripts and every HTML comment travel
with it. The Book has been walked this way since its second edition
(tests/test_the_book.py); these tests walk the Wall and the two static
files every visitor downloads with it the same way, with the Book's own
helpers, so no term that must stay private is typed here either.

Four walks:

  1. no private term, anywhere in the answer or in the static files;
  2. no command, host or key: the words an operator types at a shell or
     reads off a console. The login form needs "password" and "token", so
     the Book's whole list is not the Wall's;
  3. no e-mail address, no IP address, no identifier-length digit run;
  4. no commit hash of the road.

Run with:  python manage.py test tests.test_wall_public_safety
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from core import book_content as book
from core import wall_facts as wf
from tests.test_the_book import (KNOWN_COMMITS, WHOLE_PATTERNS, _private_terms_in,
                                 _whole)

WALL = "/wall/"
#: Downloaded by every visitor beside the page: walked with it.
STATIC = (Path(settings.BASE_DIR) / "static" / "js" / "sv-day-scheme.js",
          Path(settings.BASE_DIR) / "static" / "css" / "sv-day-scheme.css")

#: What an operator types or reads, never a visitor. "password" and
#: "token" are left out on purpose: the login form carries both.
COMMAND_HOST_OR_KEY = [
    "/stop", "/status", "/health/", "manage.py", "sudo", "systemctl",
    "git pull", "--yes", "localhost", "127.0.0.1", "hostname", "vps", "ssh ",
    "api key", "api_key", "user key", "user_key", "chat id", "chat_id",
    "secret", "account number", "account id", "position id", "positionid",
    "orderid",
]


def _scrubbed(whole, facts):
    """The whole answer with what is a count or an escape taken out, so the
    digit-run pattern reads identifiers and nothing else.

    json_script writes an en dash as \\u2013, and the ring's "13:15–20:15"
    then holds the six-digit run 201320; the escapes come out first. A
    wall count of five figures or more (the tests green) is a count, not an
    identifier, and only those come out: removing every value, the small
    ones included, erased those digits page-wide and blinded the IP and
    digit-run checks (measured: a planted 10.0.0.1 was found before and
    missed after)."""
    text = re.sub(r"\\u[0-9a-f]{4}", " ", whole)
    for value in facts.values():
        if isinstance(value, int) and value >= 10000:
            text = re.sub(r"(?<![\d,.])%d(?![\d,])" % value, " ", text)
    return text


class TheWallCarriesNothingPrivate(TestCase):

    def setUp(self):
        cache.delete(wf.CACHE_KEY)
        self.body = self.client.get(WALL).content.decode("utf-8")
        self.whole = _whole(self.body)

    def test_the_wall_carries_no_private_term(self):
        self.assertEqual(_private_terms_in(self.whole), [])
        for path in STATIC:
            with self.subTest(file=path.name):
                self.assertEqual(
                    _private_terms_in(_whole(path.read_text(encoding="utf-8"))), [])

    def test_the_wall_names_no_command_host_or_key(self):
        found = [word for word in COMMAND_HOST_OR_KEY if word in self.whole]
        self.assertEqual(found, [], "the Wall says %r" % found)

    def test_the_wall_shows_no_email_ip_or_identifier(self):
        facts = wf.wall_facts()
        scrubbed = _scrubbed(self.whole, facts)
        for pattern, what in WHOLE_PATTERNS:
            hit = pattern.search(scrubbed)
            self.assertIsNone(hit, "the Wall shows %s: %r" % (what, hit and hit.group(0)))
        # The scrub blinds nothing: a planted address is still found.
        planted = _scrubbed(self.whole + " 10.0.0.1 ", facts)
        self.assertTrue(any(p.search(planted) for p, _ in WHOLE_PATTERNS))

    def test_the_wall_shows_no_commit_hash(self):
        hashes = {commit for *_rest, commit in book.MILESTONES} | set(KNOWN_COMMITS)
        self.assertGreater(len(hashes), 100)
        shown = [commit for commit in sorted(hashes)
                 if re.search(r"(?<![0-9a-f])%s(?![0-9a-f])" % commit, self.whole)]
        self.assertEqual(shown, [], "the Wall shows the commit(s) %r" % shown)
