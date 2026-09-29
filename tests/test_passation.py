"""The handover letter opens when the operator has left, and not before.

The operator, 2026-09-28, the night before leaving for three weeks at
least: a letter of passation to Gandalf, his father, "something pretty
fancy that will only show after 4PM tomorrow afternoon French time, when
I'll have left and my dad will have taken my PC and duty".

What these tests pin (core/passation.py, dashboard/views_passation.py):

  * The clock is 2026-09-29 16:00 Paris, written in UTC (14:00) so no
    server timezone can move it.
  * Before the hour: /passation/ sends the reader to the dashboard and no
    page carries the card. Not a teaser, not a countdown — nothing. (Not
    a 404 either: probe_routes counts a 404 as a page wired to nothing.)
  * From the hour: the page serves the letter, and the card leading to it
    stands on every logged-in page for the length of the watch (21 days),
    then the page stays and the card goes.
  * The letter is for a logged-in reader only, and carries no figure of
    money: it is a letter, not a statement.

Run with:  python manage.py test tests.test_passation
"""
import re
from datetime import datetime, timedelta, timezone as dt_tz
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core import passation

BEFORE = datetime(2026, 9, 29, 13, 59, tzinfo=dt_tz.utc)
AT = datetime(2026, 9, 29, 14, 0, tzinfo=dt_tz.utc)
LATER = AT + timedelta(days=3)
AFTER_THE_WATCH = AT + timedelta(days=21, minutes=1)

MONEY = re.compile(
    r"(?:[€$£]\s?\d|\d[\d\s.,]*\s?(?:€|\$|£|USD|EUR|GBP)\b|\bP&amp;L\b|\bP&L\b"
    r"|\b(?:equity|balance|marge|margin)\b\s*[:=]?\s*\d)", re.I)


def _at(when):
    return mock.patch("core.passation._now", return_value=when)


class TheClockTests(TestCase):

    def test_it_opens_at_four_in_the_afternoon_in_paris(self):
        self.assertEqual(passation.OPENS_AT, AT)
        paris = passation.OPENS_AT.astimezone(ZoneInfo("Europe/Paris"))
        self.assertEqual((paris.hour, paris.minute, paris.day, paris.month),
                         (16, 0, 29, 9))

    def test_the_card_stands_for_the_watch_and_the_page_for_ever(self):
        self.assertFalse(passation.is_open(BEFORE))
        self.assertTrue(passation.is_open(AT))
        self.assertTrue(passation.is_open(AFTER_THE_WATCH))
        self.assertFalse(passation.card_due(BEFORE))
        self.assertTrue(passation.card_due(AT))
        self.assertTrue(passation.card_due(LATER))
        self.assertFalse(passation.card_due(AFTER_THE_WATCH))


class TheLetterTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("gandalf_u", password="x")
        self.client.force_login(self.user)

    def test_nothing_before_the_hour(self):
        with _at(BEFORE):
            r = self.client.get(reverse("passation"))
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r["Location"], reverse("dashboard"))
            body = self.client.get("/calendar/").content.decode()
        self.assertNotIn("sv-passation-card", body)
        self.assertNotIn("Gandalf", body)

    def test_the_letter_from_the_hour(self):
        with _at(AT):
            r = self.client.get(reverse("passation"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        for words in ("À GANDALF", "Papa, si tu lis ces lignes", "trois",
                      "Tiens la maison, Gandalf", "TON FILS",
                      "LA GARDE, EN PRATIQUE", "/status", "/stopall",
                      "LE SECOND BOT", "@BotFather"):
            self.assertIn(words, body, words)

    def test_the_card_leads_to_it_on_every_page_during_the_watch(self):
        # Any page that extends base.html: the calendar is the plainest.
        with _at(LATER):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn('id="svPassationCard"', body)
        self.assertIn(f'href="{reverse("passation")}"', body)
        self.assertIn("Gandalf", body)

    def test_after_the_watch_the_card_goes_and_the_page_stays(self):
        with _at(AFTER_THE_WATCH):
            self.assertEqual(self.client.get(reverse("passation")).status_code, 200)
            body = self.client.get("/calendar/").content.decode()
        self.assertNotIn('id="svPassationCard"', body)

    def test_the_letter_carries_no_figure_of_money(self):
        with _at(AT):
            body = self.client.get(reverse("passation")).content.decode()
        start = body.index('<article class="pass-letter"')
        article = body[start:body.index("</article>", start)]
        # The words, not the markup: a stylesheet's "margin:0" is not money.
        text = re.sub(r"<[^>]+>", " ", article)
        self.assertIsNone(MONEY.search(text), MONEY.search(text))

    def test_the_card_is_dismissable_but_the_letter_is_not_lost(self):
        with _at(AT):
            body = self.client.get("/calendar/").content.decode()
        self.assertIn('id="svPassationDismiss"', body)
        self.assertIn("localStorage", body)


class TheLetterIsForTheHouseOnlyTests(TestCase):

    def test_anonymous_is_sent_to_the_login_page(self):
        with _at(AT):
            r = self.client.get(reverse("passation"))
        # The login gateway of this platform is the Wall's overlay.
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"next={reverse('passation')}", r["Location"])
