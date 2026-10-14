"""THE PUBLIC LEAK WALK AS A MODULE (2026-10-14, core/leak_walk.py).

Until this module the walk the Book's and the Wall's tests run over every
byte of a public answer lived in tests/test_the_book.py, and the private
terms it looks for were stored there as bare sha256 digests of short
lowercase phrases. This repository is public, and a digest of a short
phrase with no secret is a confirm-my-guess oracle. Now the walk is a
module the views call at render time, and the private terms are read from
the server's environment (SAURON_PRIVATE_TERMS) at call time: nothing
derived from them is in this tree. One term is always armed, the canary,
which these tests plant in clear.

Pinned here: how the environment is read (absent, empty, several terms,
normalisation, a term of any length kept whole, blanks and duplicates,
memoisation by raw value); what the term walk finds (a one-word and a
four-word term in a comment, a style block and an entity-encoded span; a
five-word term; nothing inside a longer token; sorted; the canary); the
visitor's own words the render-time walk blanks (the Host header, with
and without its port); the whole walk's wording; and the once-per-process
INFO line.

Run with:  python manage.py test tests.test_leak_walk
"""
import logging
import os
from unittest import mock

from django.test import SimpleTestCase

from core import leak_walk as lw

ENV = lw.PRIVATE_TERMS_ENV


class _Fresh(SimpleTestCase):
    """Every test starts with an empty memo and an unsaid INFO line."""

    def setUp(self):
        lw._terms_of.cache_clear()
        lw._SAID = False
        self.addCleanup(lw._terms_of.cache_clear)
        self.addCleanup(setattr, lw, "_SAID", False)

    def env(self, value):
        patch = (mock.patch.dict(os.environ, {ENV: value}) if value is not None
                 else mock.patch.dict(os.environ, clear=False))
        patch.start()
        self.addCleanup(patch.stop)
        if value is None:
            os.environ.pop(ENV, None)


class ThePrivateTermsComeFromTheEnvironment(_Fresh):

    def test_absent_or_empty_is_the_canary_alone(self):
        self.env(None)
        self.assertEqual(lw.private_terms(), frozenset({lw.CANARY}))
        self.assertFalse(lw.configured())
        self.env("")
        self.assertEqual(lw.private_terms(), frozenset({lw.CANARY}))
        self.env("   |  | ")
        self.assertEqual(lw.private_terms(), frozenset({lw.CANARY}))
        self.assertFalse(lw.configured())

    def test_terms_are_split_on_the_pipe_and_normalised_like_a_page(self):
        self.env("Alpha|beta GAMMA|Jean-Pierre|  Tűr  ")
        self.assertEqual(lw.private_terms(), frozenset({
            lw.CANARY, "alpha", "beta gamma", "jean pierre", "tűr"}))
        self.assertTrue(lw.configured())
        # a comma or an apostrophe inside a term is not a separator
        self.env("Jean-Pierre, le vieux|l'autre")
        self.assertEqual(lw.private_terms(), frozenset({
            lw.CANARY, "jean pierre le vieux", "l autre"}))

    def test_a_term_of_any_length_is_kept_whole_and_found_whole(self):
        """(2026-10-14, review) The walk once dropped a term of more than
        four words with one warning while /health/ still said the list
        was configured: a five-word address the operator believed covered
        was published. The bound was the old n-gram walk's cost cap; the
        substring walk's cost does not depend on the term's length."""
        self.env("one two three four five|short")
        with self.assertNoLogs("core.leak_walk", logging.WARNING):
            terms = lw.private_terms()
        self.assertEqual(terms, frozenset({lw.CANARY, "one two three four five",
                                           "short"}))
        self.assertTrue(lw.configured())
        self.assertEqual(lw.private_terms_in("<p>and then One, two three "
                                             "four FIVE times</p>"),
                         ["one two three four five"])
        self.assertEqual(lw.private_terms_in("one two three four six"), [])
        self.assertFalse(hasattr(lw, "PRIVATE_TERM_MAX_WORDS"))

    def test_blanks_and_duplicates_are_ignored(self):
        self.env("a|a|A|  |b|")
        self.assertEqual(lw.private_terms(), frozenset({lw.CANARY, "a", "b"}))

    def test_the_raw_value_is_memoised_and_read_at_call_time(self):
        self.env("x")
        self.assertIs(lw.private_terms(), lw.private_terms())
        self.env("y")
        self.assertEqual(lw.private_terms(), frozenset({lw.CANARY, "y"}))
        self.assertEqual(lw.private_terms("given"), frozenset({lw.CANARY, "given"}))

    def test_the_canary_cannot_be_dropped(self):
        self.env(lw.CANARY)
        self.assertEqual(lw.private_terms(), frozenset({lw.CANARY}))


class TheTermWalk(_Fresh):

    BODY = ("<!DOCTYPE html><html><head><title>A page</title>"
            "<style>/* the Alpha word */ body { color: red }</style>"
            "<script>// one two three four\n</script></head>"
            "<body><p>Hello &amp; welcome, Jean&#45;Pierre.</p>"
            "<!-- canary private phrase --></body></html>")

    def test_a_term_is_found_in_a_comment_a_style_block_and_an_encoded_span(self):
        self.env("alpha|one two three four|jean pierre")
        self.assertEqual(lw.private_terms_in(lw.whole(self.BODY)),
                         ["alpha", "canary private phrase", "jean pierre",
                          "one two three four"])

    def test_nothing_is_found_inside_a_longer_token(self):
        self.env("alpha|two")
        self.assertEqual(lw.private_terms_in("alphabet twofold"), [])
        self.assertEqual(lw.private_terms_in("the alpha and two"), ["alpha", "two"])

    def test_the_output_is_sorted_and_the_terms_may_be_given(self):
        self.env(None)
        found = lw.private_terms_in("zulu then Alpha then mike",
                                    terms=["mike", "Alpha", "zulu", "", "  "])
        self.assertEqual(found, ["alpha", "mike", "zulu"])
        self.assertEqual(lw.private_terms_in("anything", terms=[]), [])

    def test_the_canary_is_found_with_no_list_configured(self):
        self.env(None)
        self.assertEqual(lw.private_terms_in("a Canary Private Phrase here"),
                         [lw.CANARY])
        self.assertEqual(lw.private_terms_in("a canary, a private phrase"), [])

    def test_whole_and_visible_read_as_the_book_tests_do(self):
        text = lw.whole('<p data-count="12345">12,345</p><i style="color:#030806">x</i>'
                        " text-wrap: balance &lt;b&gt;")
        self.assertNotIn("12345", text)
        self.assertNotIn("030806", text)
        self.assertNotIn("balance", text)
        self.assertIn("<b>", text)
        self.assertEqual(lw.visible(self.BODY), "Hello & welcome, Jean-Pierre.")


class TheVisitorsWords(_Fresh):
    """(2026-10-14, review) What the visitor typed that the page echoes is
    blanked before the render-time walk: the Host header, which every
    absolute address on the page carries, with and without its port."""

    def _request(self, host):
        from django.test import RequestFactory
        return RequestFactory().get("/wall/", HTTP_HOST=host)

    def test_the_host_with_and_without_its_port_lowercased(self):
        with self.settings(ALLOWED_HOSTS=[".example.test"]):
            self.assertEqual(lw.visitors_words(self._request("Planted.Example.test:8443")),
                             ["planted.example.test:8443", "planted.example.test"])
            self.assertEqual(lw.visitors_words(self._request("planted.example.test")),
                             ["planted.example.test"])
        self.assertEqual(lw.visitors_words(None), [])

    def test_a_host_that_cannot_be_read_blanks_nothing(self):
        from django.core.exceptions import DisallowedHost
        request = mock.MagicMock()
        request.get_host.side_effect = DisallowedHost("x")
        self.assertEqual(lw.visitors_words(request), [])
        request.get_host.side_effect = None
        request.get_host.return_value = ""
        self.assertEqual(lw.visitors_words(request), [])

    def test_the_render_time_walk_blanks_the_host_and_nothing_else(self):
        self.env("planted withhold phrase")
        body = ('<html><head><meta property="og:image" content='
                '"https://planted-withhold-phrase.example.test/static/x.png">'
                '</head><body><p>quiet</p></body></html>')
        with self.settings(ALLOWED_HOSTS=[".example.test"]):
            request = self._request("planted-withhold-phrase.example.test")
            # the host is the visitor's: the page publishes
            self.assertIsNone(lw.withhold_if_private("wall", body, request))
            # the same words elsewhere on the page are still a leak
            leaking = body.replace("<p>quiet</p>",
                                   "<p>a planted withhold phrase here</p>")
            with mock.patch("bot_program.notifications.notify_staff"), \
                    mock.patch.object(lw, "withheld",
                                      return_value="HELD") as held:
                self.assertEqual(lw.withhold_if_private("wall", leaking, request),
                                 "HELD")
            held.assert_called_once_with("wall", ["planted withhold phrase"])
        # without a request the host is read as the page's (the old walk)
        with mock.patch.object(lw, "withheld", return_value="HELD"):
            self.assertEqual(lw.withhold_if_private("wall", body), "HELD")


class TheWholeWalk(_Fresh):

    def test_each_finding_is_said_in_the_old_words(self):
        self.env("alpha")
        body = ("<html><head><style>/* password */</style></head><body>"
                "<p>alpha ops@example.org 10.0.0.1 1234567890 deadbee1 "
                "positions bot off 12 @</p></body></html>")
        found = lw.leaks(body, commits=["deadbee1"])
        self.assertIn("says 'password'", found)
        self.assertIn("carries the private term 'alpha'", found)
        self.assertIn("shows an e-mail address: 'ops@example.org'", found)
        self.assertIn("shows an IP address: '10.0.0.1'", found)
        self.assertIn("shows an identifier-length digit run: '1234567890'", found)
        self.assertIn("shows the commit deadbee1", found)
        self.assertIn("shows a position: 'positions'", found)
        self.assertIn("shows a command: 'bot off 1'", found)
        self.assertIn("shows an @", found)

    def test_a_clean_page_leaks_nothing(self):
        self.env("alpha")
        body = ("<html><head><style>body { color: red }</style></head><body>"
                "<p>A quiet page about the weather.</p></body></html>")
        self.assertEqual(lw.leaks(body, commits=["deadbee1"]), [])
        self.assertEqual(lw.leaks(body, forbidden=["weather"]), ["says 'weather'"])


class TheInfoLineIsSaidOnce(_Fresh):

    def test_no_list_is_said_once_per_process(self):
        self.env(None)
        with self.assertLogs("core.leak_walk", "INFO") as logs:
            lw.say_canary_only_once()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("runs with the canary only", logs.output[0])
        self.assertIn(ENV, logs.output[0])
        with self.assertNoLogs("core.leak_walk", "INFO"):
            lw.say_canary_only_once()

    def test_a_configured_list_says_nothing(self):
        self.env("alpha")
        with self.assertNoLogs("core.leak_walk", logging.INFO):
            lw.say_canary_only_once()
        self.assertTrue(lw._SAID)


class TheVariableIsDocumented(SimpleTestCase):

    def test_both_env_examples_and_the_runbook_name_it(self):
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for name in (".env.example", ".env.production.example"):
            raw = (base / name).read_text(encoding="utf-8")
            self.assertIn("%s=\n" % ENV, raw, name)
            self.assertIn("core/leak_walk.py", raw, name)
            self.assertIn("--force-recreate web", raw, name)
        runbook = (base / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("## The private terms", runbook)
        self.assertIn("%s=a name|a town|another phrase" % ENV, runbook)


class TheSourcesCarryNoDigest(SimpleTestCase):

    def test_no_sha256_digest_and_no_private_term_list_is_typed_in_the_tree(self):
        """The old list: 38 bare sha256 digests in tests/test_the_book.py.
        Neither that file nor the module may hold one again."""
        import re
        from pathlib import Path

        from django.conf import settings

        from core import views_book
        # The one digest the Book's test may carry is the integrity pin of
        # the staff-only chapter, a file outside git (not a short phrase).
        allowed = {views_book.STAFF_CHAPTER_SHA256}
        for path in (Path(settings.BASE_DIR) / "core" / "leak_walk.py",
                     Path(settings.BASE_DIR) / "tests" / "test_the_book.py",
                     Path(settings.BASE_DIR) / "tests" / "test_wall_public_safety.py",
                     Path(__file__)):
            src = path.read_text(encoding="utf-8")
            digests = set(re.findall(r"\b[0-9a-f]{64}\b", src))
            self.assertEqual(digests - allowed, set(), path.name)
            self.assertNotIn("PRIVATE_TERM_" + "DIGESTS", src, path.name)
