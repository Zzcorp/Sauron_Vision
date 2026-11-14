"""The Wall walked for leaks (2026-10-08).

The Wall is the most public page of a public repository, read by anyone
who finds the address, and the answer a visitor receives is more than its
visible words: the stylesheet, the scripts and every HTML comment travel
with it. The Book has been walked this way since its second edition
(tests/test_the_book.py); these tests walk the Wall and the text files
every visitor downloads with it the same way, with the walk the views
themselves call at render time (core/leak_walk.py), whose private terms
come from the server's environment, so no term that must stay private is
typed here either.

Four walks:

  1. no private term, anywhere in the answer or in the static files;
  2. no command, host or key: the words an operator types at a shell or
     reads off a console, in the answer and in the static files. The
     login form needs "password" and "token", so the Book's whole list is
     not the Wall's;
  3. no e-mail address, no IP address, no identifier-length digit run;
  4. no commit hash of the road.

And one guard of the render-time walk itself (2026-10-31): the `next` a
visitor puts in the address is echoed into the login form, and is never
read as the page's.

And one guard of the third walk's scrub (2026-11-14): the login forms'
CSRF token is a random draw, not an identifier, and is cut out by its own
attribute; the same digits anywhere beside it are still found.

Run with:  python manage.py test tests.test_wall_public_safety
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.middleware.csrf import CSRF_SECRET_LENGTH, CSRF_TOKEN_LENGTH
from django.test import Client, TestCase

from core import book_content as book
from core import wall_facts as wf
from core.leak_walk import WHOLE_PATTERNS, private_terms_in, whole
from tests.test_the_book import KNOWN_COMMITS

WALL = "/wall/"
#: Downloaded by every visitor beside the page: walked with it. Every text
#: file the two pages link, the page icon among them (an SVG's comments
#: travel with it, and the Book links the same icon).
STATIC = (Path(settings.BASE_DIR) / "static" / "js" / "sv-day-scheme.js",
          Path(settings.BASE_DIR) / "static" / "css" / "sv-day-scheme.css",
          Path(settings.BASE_DIR) / "static" / "logo" / "sauron_eye.svg")

#: What an operator types or reads, never a visitor. "password" and
#: "token" are left out on purpose: the login form carries both.
COMMAND_HOST_OR_KEY = [
    "/stop", "/status", "/health/", "manage.py", "sudo", "systemctl",
    "git pull", "--yes", "localhost", "127.0.0.1", "hostname", "vps", "ssh ",
    "api key", "api_key", "user key", "user_key", "chat id", "chat_id",
    "secret", "account number", "account id", "position id", "positionid",
    "orderid",
]

#: The CSRF token of the Wall's three login forms, as whole() reads it:
#: Django's {% csrf_token %} prints <input type="hidden"
#: name="csrfmiddlewaretoken" value="...">, the value 64 letters and
#: digits drawn afresh on every render. The value alone, found by that
#: attribute.
CSRF_TOKEN_VALUE = re.compile(
    r'(?<=name="csrfmiddlewaretoken" value=")[0-9a-z]{%d}(?=")'
    % CSRF_TOKEN_LENGTH)
#: The third walk's own digit-run pattern, looked up by what it finds.
DIGIT_RUN = dict((what, pattern) for pattern, what in WHOLE_PATTERNS)[
    "an identifier-length digit run"]
#: The run CI read in a token (PR #112's CI, 2026-11-14: "the Wall shows
#: an identifier-length digit run: '65685'"), and a CSRF draw that holds
#: it: 32 characters of Django's alphabet, what
#: django.middleware.csrf._get_new_csrf_string returns for a secret and
#: for a mask, so every token the page prints holds the run too.
CSRF_RUN = "65685"
CSRF_DRAW = ("wall" + CSRF_RUN).ljust(CSRF_SECRET_LENGTH, "x")


def _scrubbed(whole, facts):
    """The whole answer with what is a draw, an escape or a count taken
    out, so the digit-run pattern reads identifiers and nothing else.

    The login forms' CSRF token is a draw (2026-11-14): 64 random letters
    and digits, new on every render, hold a run of five digits in about
    one render in 180, and CI read one as an identifier twice in a day.
    Its value comes out first, found by its own attribute, and nothing
    beside it does: the same digits in the page's text, in the token's
    tag or in the same form are still found
    (test_an_identifier_beside_the_token_is_still_found).

    json_script writes an en dash as \\u2013, and the ring's "13:15–20:15"
    then holds the six-digit run 201320; the escapes come out next. A
    wall count of five figures or more (the tests green) is a count, not an
    identifier, and only those come out: removing every value, the small
    ones included, erased those digits page-wide and blinded the IP and
    digit-run checks (measured: a planted 10.0.0.1 was found before and
    missed after)."""
    text = CSRF_TOKEN_VALUE.sub("", whole)
    text = re.sub(r"\\u[0-9a-f]{4}", " ", text)
    for value in facts.values():
        if isinstance(value, int) and value >= 10000:
            text = re.sub(r"(?<![\d,.])%d(?![\d,])" % value, " ", text)
    return text


class TheWallCarriesNothingPrivate(TestCase):

    def setUp(self):
        cache.delete(wf.CACHE_KEY)
        self.body = self.client.get(WALL).content.decode("utf-8")
        self.whole = whole(self.body)

    def test_the_wall_carries_no_private_term(self):
        self.assertEqual(private_terms_in(self.whole), [])
        for path in STATIC:
            with self.subTest(file=path.name):
                self.assertEqual(
                    private_terms_in(whole(path.read_text(encoding="utf-8"))), [])

    def test_the_wall_names_no_command_host_or_key(self):
        found = [word for word in COMMAND_HOST_OR_KEY if word in self.whole]
        self.assertEqual(found, [], "the Wall says %r" % found)
        # The ring's labels are drawn by the script, so the page body never
        # carries them: the static files are walked the same way. Until
        # 2026-10-08 the ring named the alarm chat's brake by its command,
        # in capitals, which the quoted lowercase check in
        # tests.test_wall_day never saw.
        for path in STATIC:
            with self.subTest(file=path.name):
                text = whole(path.read_text(encoding="utf-8"))
                found = [word for word in COMMAND_HOST_OR_KEY if word in text]
                self.assertEqual(found, [], "%s says %r" % (path.name, found))

    def assertShowsNoEmailIpOrIdentifier(self, text, facts):
        """The third walk, on a whole answer: once scrubbed, no e-mail
        address, no IP address, no identifier-length digit run."""
        scrubbed = _scrubbed(text, facts)
        for pattern, what in WHOLE_PATTERNS:
            hit = pattern.search(scrubbed)
            self.assertIsNone(hit, "the Wall shows %s: %r" % (what, hit and hit.group(0)))

    def test_the_wall_shows_no_email_ip_or_identifier(self):
        facts = wf.wall_facts()
        self.assertShowsNoEmailIpOrIdentifier(self.whole, facts)
        # The scrub blinds nothing: a planted address is still found.
        planted = _scrubbed(self.whole + " 10.0.0.1 ", facts)
        self.assertTrue(any(p.search(planted) for p, _ in WHOLE_PATTERNS))

    def test_a_digit_run_in_the_csrf_token_is_not_an_identifier(self):
        """CI's run, pinned (2026-11-14). Django's CSRF draw is made to
        hold "65685", so every token the page prints holds it, where the
        digit-run pattern reads it: before the cut this failed on every
        run, as it had failed by chance about one render in 180."""
        with mock.patch("django.middleware.csrf._get_new_csrf_string",
                        return_value=CSRF_DRAW):
            text = whole(Client().get(WALL).content.decode("utf-8"))
        values = re.findall(r'name="csrfmiddlewaretoken" value="([^"]*)"', text)
        self.assertTrue(values)
        for value in values:
            self.assertIn(CSRF_RUN, [hit.group(0) for hit in DIGIT_RUN.finditer(value)])
        self.assertShowsNoEmailIpOrIdentifier(text, wf.wall_facts())

    def test_an_identifier_beside_the_token_is_still_found(self):
        """The cut is the token's value and nothing wider: the same five
        digits as an account number in the page's text, in the token's own
        tag, or in the same form beside it, fail the walk."""
        facts = wf.wall_facts()
        tag = re.search(r'<input type="hidden" name="csrfmiddlewaretoken" '
                        r'value="[^"]*"', self.body).group(0)
        plants = (
            ("the page's text", "</body>", "<p>Account %s</p></body>" % CSRF_RUN),
            ("the token's tag", tag, '%s data-account="%s"' % (tag, CSRF_RUN)),
            ("the same form", tag + ">",
             '%s><input type="hidden" name="account" value="%s">' % (tag, CSRF_RUN)),
        )
        for where, old, new in plants:
            with self.subTest(planted_in=where):
                self.assertIn(old, self.body)
                with self.assertRaisesRegex(
                        AssertionError,
                        "the Wall shows an identifier-length digit run: '%s'" % CSRF_RUN,
                        msg="the walk missed %s planted in %s" % (CSRF_RUN, where)):
                    self.assertShowsNoEmailIpOrIdentifier(
                        whole(self.body.replace(old, new, 1)), facts)

    def test_the_wall_shows_no_commit_hash(self):
        hashes = {commit for *_rest, commit in book.MILESTONES} | set(KNOWN_COMMITS)
        self.assertGreater(len(hashes), 100)
        shown = [commit for commit in sorted(hashes)
                 if re.search(r"(?<![0-9a-f])%s(?![0-9a-f])" % commit, self.whole)]
        self.assertEqual(shown, [], "the Wall shows the commit(s) %r" % shown)


class TheVisitorsNextIsNotThePages(TestCase):
    """(Review, 2026-10-31) The Wall echoes a Telegram link's `next` into
    its login form, id-only (alerts.links.DEEP_LINK_PATHS), and those
    digits are whatever the visitor typed. Read as the page's, a digit-run
    private term guessed there came back as the placeholder, and a miss as
    the whole Wall: a confirm-my-guess oracle against the server's list,
    and a staff incident anyone could raise. The walk reads the page with
    the echo blanked; the page served still carries it."""

    PLANTED = "424242"

    def setUp(self):
        import os
        from unittest import mock

        from core import leak_walk
        cache.clear()
        leak_walk._terms_of.cache_clear()
        self.addCleanup(leak_walk._terms_of.cache_clear)
        patch = mock.patch.dict(os.environ, {leak_walk.PRIVATE_TERMS_ENV: self.PLANTED})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_guess_in_next_gets_the_whole_wall(self):
        from unittest import mock

        from core import leak_walk
        for path in ("/signals/%s/ticket/" % self.PLANTED,
                     "/positions/%s/close-dialog/" % self.PLANTED):
            with self.subTest(next=path), \
                    mock.patch.object(leak_walk, "withheld",
                                      side_effect=AssertionError("withheld")):
                response = self.client.get(WALL, {"next": path})
                self.assertEqual(response.status_code, 200)
                body = response.content.decode("utf-8")
                self.assertIn('id="council"', body)
                self.assertIn('name="next" value="%s"' % path, body)

    def test_the_same_term_on_the_page_itself_is_still_held(self):
        from unittest import mock

        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from core import leak_walk, views_wall
        real = views_wall.render_to_string

        def leaking(*args, **kwargs):
            return real(*args, **kwargs).replace("</body>", "<p>%s</p></body>" % self.PLANTED)

        request = RequestFactory().get(WALL, {"next": "/signals/%s/ticket/" % self.PLANTED})
        request.user = AnonymousUser()
        with mock.patch.object(views_wall, "render_to_string", side_effect=leaking), \
                mock.patch.object(leak_walk, "withheld", return_value="HELD") as held:
            self.assertEqual(views_wall.the_wall(request), "HELD")
        held.assert_called_once_with("wall", [self.PLANTED])
