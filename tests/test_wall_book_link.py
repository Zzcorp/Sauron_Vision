"""The Book of Sauron is one tap from the top of the Wall.

The operator, 2026-09-28: "add also a link to sauron book at the top of the
wall so that the viewer can view directly". Until then the only way from the
Wall to /book/ was the READ THE BOOK OF SAURON line at the very bottom,
four screens down for a reader who arrived for the story.

What these tests pin (templates/landing/the_wall.html, the nav):

  * The nav carries a link to the Book, before the Access Terminal button,
    and it resolves to the real page.
  * The phone tier hides every nav anchor but the Access button — and now
    the Book: the rule that hides them names the exception.
  * The bottom line is still there: two doors, not a moved one.

Run with:  python manage.py test tests.test_wall_book_link
"""
import re

from django.test import TestCase
from django.urls import reverse


class TheBookFromTheTopOfTheWallTests(TestCase):

    def setUp(self):
        self.body = self.client.get(reverse("the_wall")).content.decode()
        m = re.search(r'<nav class="wall-nav" id="wallNav">(.*?)</nav>',
                      self.body, re.S)
        self.assertIsNotNone(m, "the Wall's nav is gone")
        self.nav = m.group(1)

    def test_the_nav_links_to_the_book_before_the_access_button(self):
        book = reverse("the_book")
        self.assertIn(f'href="{book}" class="nav-book"', self.nav)
        self.assertLess(self.nav.index('class="nav-book"'),
                        self.nav.index('class="btn-access"'),
                        "the Book comes before Access Terminal")

    def test_the_link_names_the_book_and_the_page_answers(self):
        self.assertRegex(self.nav, r'class="nav-book">\s*The Book\s*</a>')
        self.assertEqual(self.client.get(reverse("the_book")).status_code, 200)

    def test_the_phone_tier_keeps_the_book_beside_the_access_button(self):
        """`.nav-links a:not(.btn-access) { display: none; }` hid every
        anchor on a phone; the exception must now name the Book too, or
        the link exists only on a laptop."""
        self.assertIn(".nav-links a:not(.btn-access):not(.nav-book) { display: none; }",
                      self.body)

    def test_the_bottom_door_still_stands(self):
        self.assertIn("READ THE BOOK OF SAURON", self.body)
