"""A PUBLIC PAGE THAT CARRIES A PRIVATE TERM IS NOT SENT (2026-10-14).

core/leak_walk.py is called by the two public views at render time
(core/views_book.py, core/views_wall.py). The private terms come from the
server's environment (SAURON_PRIVATE_TERMS); a phrase planted here stands
for them. When the rendered answer carries one:

  * the visitor receives a neutral placeholder (landing/withheld.html):
    status 200 (probe_routes counts a non-200 as a missing route), never
    cached, no chapter of the Book, no word of the term, no reason;
  * the log carries the page and the COUNT, never the term;
  * staff is told once a day per page (notify_staff behind a cache gate);
  * the health digest and /health/ read the event off a cache key: a
    public GET writes no database row.

A staff reader's Book is NOT walked (the staff-only chapter is private by
design and never cached); a plain signed-in user's is. With no list
configured both pages publish and the canary alone is armed; the walk
raising publishes the page with one warning.

The visitor's own words are not the page's (2026-10-14, review): a query
string is neither printed (the Wall's og:url is the canonical path) nor
walked, and a Host the visitor typed, which a leading-dot ALLOWED_HOSTS
entry admits for any subdomain, is blanked from the walked text. Without
that an anonymous GET was a confirm-my-guess oracle against the server's
live list, and each hit forged the incident staff is told about. The
ERROR line is written once an hour per page; a GET storm logs at DEBUG.

Run with:  python manage.py test tests.test_public_pages_withheld
"""
import copy
import os
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from core import book_content as book
from core import leak_walk as lw
from tests.test_the_book import FIXTURE, _StaffChapterOnDisk, _clear

BOOK = "/book/"
WALL = "/wall/"
PHRASE = "Planted Withhold Phrase"
NOTIFY = "bot_program.notifications.notify_staff"


class _Pages(TestCase):

    def setUp(self):
        _clear()
        for page in ("book", "wall"):
            for key in (lw.WITHHELD_KEY, lw.TOLD_KEY, lw.LOGGED_KEY):
                cache.delete(key % page)
        lw._terms_of.cache_clear()
        lw._SAID = False
        self.addCleanup(lw._terms_of.cache_clear)
        self.addCleanup(setattr, lw, "_SAID", False)

    def env(self, value):
        patch = mock.patch.dict(os.environ, {lw.PRIVATE_TERMS_ENV: value})
        patch.start()
        self.addCleanup(patch.stop)

    def plant_in_book(self, phrase=PHRASE):
        hero = dict(book.HERO, subtitle="%s · %s" % (book.HERO["subtitle"], phrase))
        patch = mock.patch.object(book, "HERO", hero)
        patch.start()
        self.addCleanup(patch.stop)

    def plant_in_wall(self, phrase=PHRASE):
        step = [{"date": "2026-10-08", "day": "8 October 2026",
                 "title": phrase, "anchor": "m-planted"}]
        patch = mock.patch("core.views_wall.latest_steps", return_value=step)
        patch.start()
        self.addCleanup(patch.stop)

    def assert_withheld(self, response, phrase=PHRASE):
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertTemplateUsed(response, "landing/withheld.html")
        self.assertIn("This page is not published right now", body)
        self.assertNotIn(phrase, body)
        self.assertNotIn(phrase.lower(), body.lower())
        self.assertNotIn('id="closing"', body)
        self.assertNotIn('id="staff-chapter"', body)
        self.assertNotIn("private term", body)
        self.assertIn("no-store", response["Cache-Control"])
        return body


class TheBookIsWithheld(_Pages):

    def test_a_planted_term_withholds_the_book_and_tells_once(self):
        self.env(PHRASE)
        self.plant_in_book()
        with mock.patch(NOTIFY) as told, \
                self.assertLogs("core.leak_walk", "ERROR") as logs:
            first = self.client.get(BOOK)
            second = self.client.get(BOOK)
        self.assert_withheld(first)
        self.assert_withheld(second)
        self.assertIn("Cookie", first["Vary"])
        # told once over two GETs, never the term
        self.assertEqual(told.call_count, 1)
        kwargs = told.call_args.kwargs
        self.assertIn("The Book was withheld", kwargs["title"])
        self.assertEqual(kwargs["url"], "/health/")
        self.assertEqual(kwargs["cooldown_hours"], 24)
        for text in (kwargs["title"], kwargs["body"]):
            self.assertNotIn(PHRASE.lower(), text.lower())
        # the log: the page and the count, never the term
        said = " ".join(logs.output)
        self.assertIn("The Book was withheld: 1 private term(s) in the rendered page", said)
        self.assertNotIn(PHRASE.lower(), said.lower())
        # the cache key the digest reads
        row = cache.get(lw.WITHHELD_KEY % "book")
        self.assertEqual(row["n"], 1)
        self.assertTrue(hasattr(row["at"], "isoformat"))

    def test_the_digest_and_the_health_page_read_the_event_without_the_term(self):
        from core.component_digest import collect_faults
        from dashboard.views_system_health import check_public_leak_walk
        self.env(PHRASE)
        self.plant_in_book()
        with mock.patch(NOTIFY):
            self.client.get(BOOK)
        faults = collect_faults()
        rows = [r for r in faults["errors"] if r["key"] == "public_leak_walk"]
        self.assertEqual(len(rows), 1)
        self.assertIn("The Book was withheld at", rows[0]["message"])
        self.assertEqual(rows[0]["errors"], 1)
        for value in rows[0].values():
            self.assertNotIn(PHRASE.lower(), str(value).lower())
        check = check_public_leak_walk()
        self.assertEqual(check["state"], "fail")
        self.assertIn("The Book at", check["detail"])
        self.assertNotIn(PHRASE.lower(), (check["detail"] + check["hint"]).lower())

    def test_a_plain_signed_in_user_is_withheld_too(self):
        self.env(PHRASE)
        self.plant_in_book()
        self.client.force_login(User.objects.create_user("withheld_plain", password="x"))
        with mock.patch(NOTIFY):
            self.assert_withheld(self.client.get(BOOK))

    def test_the_canary_withholds_the_book_with_no_list_configured(self):
        self.env("")
        self.plant_in_book(lw.CANARY)
        with mock.patch(NOTIFY):
            self.assert_withheld(self.client.get(BOOK), lw.CANARY)

    def test_without_a_term_on_the_page_the_book_publishes(self):
        self.env(PHRASE)
        with mock.patch(NOTIFY) as told:
            response = self.client.get(BOOK)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn('id="closing"', body)
        self.assertNotIn("This page is not published right now", body)
        told.assert_not_called()
        self.assertIsNone(cache.get(lw.WITHHELD_KEY % "book"))


class TheStaffBookIsNotWalked(_StaffChapterOnDisk, _Pages):

    def test_staff_still_reads_the_chapter_that_carries_the_term(self):
        self.env(PHRASE)
        data = copy.deepcopy(FIXTURE)
        data["chapter"]["paragraphs"].append("Un paragraphe avec %s dedans." % PHRASE)
        self.put_chapter(data=data)
        self.client.force_login(User.objects.create_user("withheld_staff", password="x", is_staff=True))
        with mock.patch(NOTIFY) as told, mock.patch.object(
                lw, "private_terms_in", wraps=lw.private_terms_in) as walk:
            response = self.client.get(BOOK)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn('id="staff-chapter"', body)
        self.assertIn(PHRASE, body)
        self.assertIn("no-store", response["Cache-Control"])
        told.assert_not_called()
        walk.assert_not_called()
        self.assertIsNone(cache.get(lw.WITHHELD_KEY % "book"))


class TheWallIsWithheld(_Pages):

    def test_a_planted_term_withholds_the_wall_and_tells_once(self):
        self.env(PHRASE)
        self.plant_in_wall()
        with mock.patch(NOTIFY) as told, \
                self.assertLogs("core.leak_walk", "ERROR") as logs:
            first = self.client.get(WALL)
            second = self.client.get(WALL)
        for response in (first, second):
            body = self.assert_withheld(response)
            self.assertNotIn("csrfmiddlewaretoken", body)
        self.assertEqual(told.call_count, 1)
        self.assertIn("The Wall was withheld", told.call_args.kwargs["title"])
        said = " ".join(logs.output)
        self.assertIn("The Wall was withheld: 1 private term(s)", said)
        self.assertNotIn(PHRASE.lower(), said.lower())
        self.assertEqual(cache.get(lw.WITHHELD_KEY % "wall")["n"], 1)

    def test_the_withheld_wall_points_at_the_book_and_the_book_at_the_wall(self):
        self.env(PHRASE)
        self.plant_in_wall()
        self.plant_in_book()
        with mock.patch(NOTIFY):
            wall = self.client.get(WALL).content.decode("utf-8")
            book_page = self.client.get(BOOK).content.decode("utf-8")
        self.assertIn('href="/book/"', wall)
        self.assertIn('href="/wall/"', book_page)

    def test_without_a_term_on_the_page_the_wall_publishes(self):
        self.env(PHRASE)
        with mock.patch(NOTIFY) as told:
            response = self.client.get(WALL)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("This page is not published right now",
                         response.content.decode("utf-8"))
        told.assert_not_called()

    def test_the_telling_is_fenced(self):
        """notify_staff raising costs a warning; the placeholder still goes out."""
        self.env(PHRASE)
        self.plant_in_wall()
        with mock.patch(NOTIFY, side_effect=RuntimeError("down")), \
                self.assertLogs("core.leak_walk", "WARNING") as logs:
            self.assert_withheld(self.client.get(WALL))
        self.assertTrue(any("could not be told" in line for line in logs.output))

    def test_the_error_line_is_written_once_an_hour_and_the_storm_at_debug(self):
        """(2026-10-14, review) The front door has no rate limit: a loop
        fetching a withheld Wall ten times a second wrote an ERROR line
        each time. One ERROR per page per hour; the count still reaches
        the cache key /health/ and the digest read."""
        self.env(PHRASE)
        self.plant_in_wall()
        with mock.patch(NOTIFY), \
                self.assertLogs("core.leak_walk", "DEBUG") as logs:
            for _ in range(3):
                self.assert_withheld(self.client.get(WALL))
        lines = [line for line in logs.output if "The Wall was withheld" in line]
        self.assertEqual(len(lines), 3)
        self.assertEqual([line.split(":")[0] for line in lines],
                         ["ERROR", "DEBUG", "DEBUG"])
        self.assertFalse(any(PHRASE.lower() in line.lower() for line in lines))
        self.assertEqual(cache.get(lw.WITHHELD_KEY % "wall")["n"], 1)
        self.assertEqual(cache.get(lw.LOGGED_KEY % "wall"), 1)
        # the other page keeps its own hour
        self.plant_in_book()
        with mock.patch(NOTIFY), \
                self.assertLogs("core.leak_walk", "ERROR") as logs:
            self.assert_withheld(self.client.get(BOOK))
        self.assertEqual(len(logs.output), 1)
        self.assertIn("The Book was withheld", logs.output[0])


class TheVisitorsOwnWordsAreNotWalked(_Pages):
    """(2026-10-14, review) GET /wall/?<guess> put the guess on the page
    (og:url printed request.build_absolute_uri, path AND query string)
    and the walk read it; with a leading-dot ALLOWED_HOSTS entry, Host:
    <guess>.example.test did the same on both pages through every absolute
    address. The verdict was readable off the placeholder: a yes/no oracle
    against the operator's live list, unauthenticated and unlimited, each
    hit also telling staff of a leak that never happened."""

    QUERY = "?planted+withhold+phrase&x=planted&y=withhold&z=phrase"
    HOST = "planted-withhold-phrase.example.test"

    def assert_published(self, response):
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn("This page is not published right now", body)
        self.assertTemplateNotUsed(response, "landing/withheld.html")
        return body

    def test_a_query_string_is_neither_printed_nor_walked(self):
        self.env(PHRASE)
        with mock.patch(NOTIFY) as told:
            wall = self.client.get(WALL + self.QUERY)
            book_page = self.client.get(BOOK + self.QUERY)
        body = self.assert_published(wall)
        self.assert_published(book_page)
        self.assertNotIn("planted", body.lower())
        self.assertNotIn("withhold", body.lower())
        self.assertIn('<meta property="og:url" content="http://testserver/wall/">',
                      body)
        self.assertNotIn("build_absolute_uri", body)
        told.assert_not_called()
        self.assertIsNone(cache.get(lw.WITHHELD_KEY % "wall"))
        self.assertIsNone(cache.get(lw.WITHHELD_KEY % "book"))

    def test_the_wall_template_never_prints_the_request_address(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "landing"
               / "the_wall.html").read_text(encoding="utf-8")
        self.assertNotIn("{{ request.build_absolute_uri }}", src)
        self.assertNotIn("request.get_full_path", src)
        self.assertIn('content="{{ canonical_url }}"', src)

    def test_a_host_the_visitor_typed_is_not_walked_on_either_page(self):
        self.env(PHRASE)
        with self.settings(ALLOWED_HOSTS=[".example.test"]), \
                mock.patch(NOTIFY) as told:
            wall = self.client.get(WALL, HTTP_HOST=self.HOST)
            book_page = self.client.get(BOOK, HTTP_HOST=self.HOST)
        for response in (wall, book_page):
            body = self.assert_published(response)
            # the host IS on the page (the card image's absolute address):
            # it is the visitor's, not the page's
            self.assertIn(self.HOST, body)
        told.assert_not_called()
        self.assertIsNone(cache.get(lw.WITHHELD_KEY % "wall"))
        self.assertIsNone(cache.get(lw.WITHHELD_KEY % "book"))

    def test_a_term_on_the_page_is_still_found_under_a_typed_host(self):
        """The control: blanking the host does not blind the walk."""
        self.env(PHRASE)
        self.plant_in_wall()
        self.plant_in_book()
        with self.settings(ALLOWED_HOSTS=[".example.test"]), \
                mock.patch(NOTIFY) as told:
            self.assert_withheld(self.client.get(WALL, HTTP_HOST="other.example.test"))
            self.assert_withheld(self.client.get(BOOK, HTTP_HOST=self.HOST))
        self.assertEqual(told.call_count, 2)

    def test_the_views_hand_the_request_to_the_walk(self):
        self.env(PHRASE)
        with mock.patch.object(lw, "withhold_if_private",
                               wraps=lw.withhold_if_private) as walk, \
                mock.patch(NOTIFY):
            self.client.get(WALL)
            self.client.get(BOOK)
        self.assertEqual([c.args[0] for c in walk.call_args_list], ["wall", "book"])
        for call in walk.call_args_list:
            self.assertEqual(call.args[2].path, "/%s/" % call.args[0])


class NoListConfigured(_Pages):

    def test_both_pages_publish_and_the_info_line_is_said_once(self):
        self.env("")
        with mock.patch(NOTIFY) as told, \
                self.assertLogs("core.leak_walk", "INFO") as logs:
            self.assertEqual(self.client.get(WALL).status_code, 200)
            self.assertEqual(self.client.get(BOOK).status_code, 200)
        info = [line for line in logs.output if "canary only" in line]
        self.assertEqual(len(info), 1)
        told.assert_not_called()
        self.assertFalse(lw.configured())

    def test_a_walk_that_raises_publishes_the_page_with_one_warning(self):
        self.env(PHRASE)
        self.plant_in_book()
        with mock.patch.object(lw, "private_terms_in", side_effect=RuntimeError("boom")), \
                mock.patch(NOTIFY) as told, \
                self.assertLogs("core.leak_walk", "WARNING") as logs:
            response = self.client.get(BOOK)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="closing"', response.content.decode("utf-8"))
        self.assertTrue(any("could not run (RuntimeError)" in line for line in logs.output))
        self.assertFalse(any("boom" in line for line in logs.output))
        told.assert_not_called()

    def test_the_probe_still_walks_both_pages(self):
        from core.management.commands.probe_routes import free_routes
        routes = free_routes()
        self.assertIn(("the_book", "book/", True), routes)
        self.assertIn(("the_wall", "wall/", True), routes)


class TheHealthPageSaysWhichListItRunsWith(_Pages):

    def test_ok_with_and_without_a_list(self):
        from dashboard.views_system_health import check_public_leak_walk
        self.env("")
        check = check_public_leak_walk()
        self.assertEqual(check["state"], "ok")
        self.assertIn("canary only", check["detail"])
        self.assertIn(lw.PRIVATE_TERMS_ENV, check["detail"])
        self.env(PHRASE)
        check = check_public_leak_walk()
        self.assertEqual(check["state"], "ok")
        self.assertIn("a private-term list is configured", check["detail"])
        self.assertNotIn(PHRASE.lower(), check["detail"].lower())
