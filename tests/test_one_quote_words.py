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


#: The engine, loaded in a sandbox with no document: the grammar alone.
NODE_WORDS = r"""
const fs = require('fs'), vm = require('vm');
const M = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sandbox = { setTimeout: function () { return 0; }, setInterval: function () { return 0; },
                  console: console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(M.engine, sandbox, { filename: 'sv-venue.js' });
const V = sandbox.SVVenue;
const out = { words: [], slots: [] };
M.table.cases.forEach(function (c) { out.words.push(V.words(c.payload, c.now, c.side || '')); });
M.table.slots.forEach(function (c) { out.slots.push(V.slotWords(c.payload, c.now)); });
process.stdout.write(JSON.stringify(out));
"""


def _node(program, manifest):
    tmp = Path(tempfile.mkdtemp(prefix="sv-oq-words-"))
    try:
        (tmp / "run.js").write_text(program, encoding="utf-8")
        (tmp / "m.json").write_text(json.dumps(manifest), encoding="utf-8")
        out = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "m.json")],
                             capture_output=True, text=True, encoding="utf-8",
                             timeout=120)
        if out.returncode != 0:
            raise AssertionError("node failed: %s" % out.stderr[-2000:])
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed")
class TheBrowserSpeaksTheTableTests(SimpleTestCase):
    """The same table, through SVVenue.words in static/js/sv-venue.js."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.table = _table()
        cls.r = _node(NODE_WORDS, {"engine": ENGINE.read_text(encoding="utf-8"),
                                   "table": cls.table})

    def test_every_case(self):
        for c, got in zip(self.table["cases"], self.r["words"]):
            with self.subTest(c["name"]):
                self.assertEqual(got, c["words"])

    def test_every_slot(self):
        for c, got in zip(self.table["slots"], self.r["slots"]):
            with self.subTest(c["name"]):
                self.assertEqual(got, c["slot"])
