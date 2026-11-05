"""T8, NO AMOUNT OF MONEY SURVIVES INTO AN ORC'S WORDS (the O2 spec A.34,
N5, P22; §1.1.7 T8; 2026-11-05).

The platform's one money filter (dashboard/plain_words.py) is widened,
never a private regex, so every surface judges a line alike:
- every form of map_pitfalls P22 that passed before is now withheld:
  "P/L", up / down / made beside an amount, "unrealized", "floating",
  "the account is at", any ISO currency code beside a figure, "grand",
  "k" and "K", amounts spelled out;
- the forms withheld before stay withheld, the known false positive on
  the safe side (a grouped level with two decimals) included;
- the Orc's own R language keeps passing: up, down and made beside an R,
  ATR, pip or percent figure.

And a model's note carrying any of them, read through the gateway, reaches
none of the card, the Orc's page, Telegram or the next PS5: it is filtered
once, at write time (V11).

Run with:  python manage.py test tests.orcs.test_orc_o2a_money
"""
from django.urls import reverse

from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_call import MindFixture, answer

#: P22's forms that passed the filter before O2a: each now withheld.
NEWLY_WITHHELD = (
    "P/L -350", "up 1,200 today", "down 300 since entry",
    "made 450 on the trim", "unrealized -350", "floating -350",
    "the account is at 12,500", "NZD 500", "500 NZD", "500 SEK",
    "AED 2,000", "HKD 800", "ZAR 900", "MXN 1500", "2 grand",
    "1.2k on the table", "a 1.5k swing", "fifty thousand",
    "half a million")
#: P22's forms withheld before O2a: they stay withheld.
ALREADY_WITHHELD = (
    "$350", "350 USD", "EUR 1,200", "PnL -350", "lost 450", "worth 1,250",
    "gain of 640", "500 dollars", "350€",
    # the false positive on the safe side: a grouped level, two decimals
    "trim at P1h-H1 (2,650.50)")
#: The Orc's own R language (A.34's "must pass" column).
MUST_PASS = (
    "up 1.2R", "down 0.5R since entry", "made 0.8R on the trim",
    "0.4 ATR below the level", "down 12 pips", "up 0.6%",
    "Holding: up 1.2R, the 4h swing intact.", "tighten to S1h-L1",
    "+1.5R", "risk 0.5R")


class TheFilterTests(MindTestCase):

    def test_every_p22_form_is_withheld_and_the_r_language_passes(self):
        from dashboard.plain_words import WITHHELD, may_name_money, scrub
        for form in NEWLY_WITHHELD + ALREADY_WITHHELD:
            with self.subTest(form=form):
                self.assertTrue(may_name_money(form))
                self.assertEqual(scrub(f"Holding: {form}."), WITHHELD)
        for form in MUST_PASS:
            with self.subTest(form=form):
                self.assertFalse(may_name_money(form))
                self.assertEqual(scrub(form), form)

    def test_a_code_in_lower_case_is_a_word(self):
        """ISO codes are read in capitals only: "ALL 300" and "TRY 300"
        name money, "all", "top" and "try" stay words; the precious
        metals' codes name a commodity."""
        from dashboard.plain_words import may_name_money
        for text in ("ALL 300", "TRY 300", "300 TOP"):
            with self.subTest(text=text):
                self.assertTrue(may_name_money(text))
        for text in ("all 3 levels hold", "try the top 2 swings",
                     "XAU 2650 is the pool", "BTC 0.5"):
            with self.subTest(text=text):
                self.assertFalse(may_name_money(text))


class TheNoteReachesNoSurfaceTests(MindFixture):
    """V11 at write time: a note naming money is withheld before the card,
    the page, Telegram or the next dossier can hold it."""

    def setUp(self):
        super().setUp()
        self.base = self.rendered()
        self.client.force_login(self.user)

    def _surfaces(self) -> dict:
        import json

        from bot_program.orcs import dossier_position, surfaces
        from bot_program.orcs.models import Orc
        orc = Orc.objects.select_related("seat", "root_trade").get(
            pk=self.orc.pk)
        page = self.client.get(reverse("orc_detail", args=[self.row.pk]))
        self.assertEqual(page.status_code, 200)
        reply = surfaces.orc_card(orc)
        return {"card": json.dumps(orc.card),
                "latest_note": orc.latest_note,
                "page": page.content.decode(),
                "telegram": reply.text(),
                "ps5": " ".join(dossier_position.ps5_notes(orc, {}))}

    def test_every_form_in_a_note_reaches_no_surface(self):
        from bot_program.orcs.validator import NOTE_WITHHELD
        for form in NEWLY_WITHHELD + ALREADY_WITHHELD:
            with self.subTest(form=form):
                w = self.copy_of(self.base)
                self.think(w, fake_answer(answer(
                    note=f"Holding: {form} on this idea.")))
                seen = self._surfaces()
                self.assertEqual(seen["latest_note"], NOTE_WITHHELD)
                for name, text in seen.items():
                    self.assertNotIn(form, text, name)
                refusal = self.entries(kind="refusal", wake=w)
                self.assertEqual([e.body["rule"] for e in refusal],
                                 ["V11"])

    def test_the_r_language_reaches_every_surface(self):
        note = "Holding: up 1.2R, the 4h swing intact."
        self.think(self.copy_of(self.base), fake_answer(answer(note=note)))
        seen = self._surfaces()
        self.assertEqual(seen["latest_note"], note)
        self.assertIn(note, seen["ps5"])
        self.assertIn(note, seen["telegram"])
