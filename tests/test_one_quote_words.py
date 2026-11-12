"""ONE GRAMMAR FOR THE WORDS BESIDE A PRICE (2026-11-12).

The operator read one held price as "7m ago" on the headband card, "8 min
old" on the hero, "8 min ago" on the quote card after its poll, "7
minutes ago" on the same card as rendered, and with no age at all on the
rails and the hover. One grammar now (market_data.one_quote.words):

    eToro bid · 25 s                     an eToro reading, its side, its age
    OANDA stream · live                  an outside stream within its bound
    Yahoo GBPUSD=X · 4 min               any other outside quote
    Yahoo EURUSD=X previous close · Thu 12 Nov
    closed · eToro bid Fri 13 Nov 21:58 · opens Sun 22:00 UTC
    awaiting eToro / no price

and the ages are the Horde's (bot_program.venue_mark.age_words). The
browser recounts the age every second with its mirror (SVVenue.words in
static/js/sv-venue.js); ONE case table (tests/one_quote_words.json,
hand-written from the build spec) is asserted against both, so the server
and the browser can never word one price two ways.

Run with:  python manage.py test tests.test_one_quote_words
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TABLE = Path(settings.BASE_DIR) / "tests" / "one_quote_words.json"
ENGINE = Path(settings.BASE_DIR) / "static" / "js" / "sv-venue.js"
NODE = shutil.which("node")


def _table():
    return json.loads(TABLE.read_text(encoding="utf-8"))


class TheServerSpeaksTheTableTests(SimpleTestCase):

    def test_every_case(self):
        from market_data.one_quote import words
        cases = _table()["cases"]
        self.assertGreaterEqual(len(cases), 30)
        for c in cases:
            with self.subTest(c["name"]):
                self.assertEqual(
                    words(c["payload"], c["now"], side=c.get("side")),
                    c["words"])

    def test_every_slot(self):
        from market_data.one_quote import slot_words
        for c in _table()["slots"]:
            with self.subTest(c["name"]):
                self.assertEqual(slot_words(c["payload"], c["now"]), c["slot"])

    def test_the_table_covers_every_state_and_the_age_boundaries(self):
        cases = _table()["cases"]
        states = {c["payload"]["state"] for c in cases}
        self.assertEqual(states, {"delayed", "shut", "none"} | (
            states & {"live"}))
        words = [c["words"] for c in cases]
        for w in ("89 s", "2 min", "89 min", "2 h", "47 h", "2 days",
                  "· live", "previous close", "closed ·", "awaiting eToro",
                  "no price"):
            self.assertTrue(any(w in x for x in words), w)
