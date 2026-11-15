"""/positions/ in the desk v2 deploy note's scenes (the desk v2 polish,
2026-11-15).

The note's pictures of /positions/ (scratchpad bureau_v2: shoot.py's
scenes, phonecheck/phone.py's phone) showed display defects on the desk
B7 drew. Each class below reads its own scene: the pictures' invented book,
the held instant, the page served with every script (tests/desk_scenes.py),
at the scene's size.

  * D4, the phone (390 x 844): THE BOOK AT ETORO kept its three figures
    side by side and they ran into each other ("$19,950.00" into "1.50%"):
    the book's own three columns (static/css/sv-positions.css,
    .pd-kgrp--book .pd-kcells, two classes) outranked the phone's one
    column (.pd-kcells, one class).

Display only: the figures are the page's own; nothing here posts, trades,
or calls a broker or a model.
"""
import json
import unittest

from django.test import Client, TestCase

from tests import desk_scenes as S
from tests.test_close_advice import CHROME

#: THE BOOK AT ETORO as the phone shows it: each cell's box, its figure's
#: text and its lines', and whether a line is cut short.
BOOK = r"""(function () {
  function rect(r) { return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }
  function text(el) { var g = document.createRange(); g.selectNodeContents(el); return rect(g.getBoundingClientRect()); }
  var card = document.querySelector('.pd-kgrp--book');
  if (!card) return JSON.stringify(null);
  var cells = Array.prototype.map.call(card.querySelectorAll('.pd-kcells > .pd-kc'), function (kc) {
    var cs = getComputedStyle(kc), b = kc.getBoundingClientRect(), v = kc.querySelector('.pd-kv');
    return {box: rect(b),
            content: {l: b.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft),
                      r: b.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight)},
            figure: v.textContent.replace(/\s+/g, ' ').trim(), text: text(v),
            lines: Array.prototype.map.call(kc.querySelectorAll('.pd-ks'), function (s) {
              return {t: s.textContent.replace(/\s+/g, ' ').trim(), sw: s.scrollWidth, cw: s.clientWidth}; })};
  });
  return JSON.stringify({vw: innerWidth, card: rect(card.getBoundingClientRect()), cells: cells,
                         sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth});
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheBookOnThePhoneTests(TestCase):
    """D4: /positions/ at 390 x 844 (the phone check's first screen):
    THE BOOK AT ETORO's three figures, each whole in its own cell, one
    under the other as the by-world card's, none over another."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        S.hold_the_clock(cls)
        book = S.scene_book()
        client = Client()
        client.force_login(book["user"])
        desk = S.SceneBrowser(client)
        try:
            tid, sid = desk.open("/positions/", 390, 844)
            cls.got = json.loads(desk.js(sid, BOOK))
            desk.close_tab(tid)
        finally:
            desk.close()

    def test_the_scene_was_reached(self):
        got = self.got
        self.assertIsNotNone(got, "THE BOOK AT ETORO on the page")
        self.assertEqual(got["vw"], 390)
        self.assertEqual([c["figure"] for c in got["cells"]], ["$19,950.00", "1.50%", "10.0%"])

    def test_each_figure_is_whole_inside_its_own_cell(self):
        for c in self.got["cells"]:
            with self.subTest(figure=c["figure"]):
                self.assertGreaterEqual(c["text"]["l"], c["content"]["l"] - 0.5, c)
                self.assertLessEqual(c["text"]["r"], c["content"]["r"] + 0.5, c)

    def test_no_figure_runs_into_another(self):
        cells = self.got["cells"]
        for i, a in enumerate(cells):
            for b in cells[i + 1:]:
                apart = (a["text"]["r"] <= b["text"]["l"] or b["text"]["r"] <= a["text"]["l"]
                         or a["text"]["b"] <= b["text"]["t"] or b["text"]["b"] <= a["text"]["t"])
                with self.subTest(pair=(a["figure"], b["figure"])):
                    self.assertTrue(apart, (a["text"], b["text"]))

    def test_the_three_cells_stand_one_under_the_other(self):
        """The phone's one column, as the by-world card's: the same left
        edge, each cell under the one before it, the card's whole width."""
        cells, card = self.got["cells"], self.got["card"]
        for prev, cell in zip(cells, cells[1:]):
            self.assertAlmostEqual(cell["box"]["l"], prev["box"]["l"], delta=0.5)
            self.assertGreaterEqual(cell["box"]["t"], prev["box"]["b"] - 0.5)
        for c in cells:
            self.assertGreaterEqual(c["box"]["r"] - c["box"]["l"], card["r"] - card["l"] - 2.5, c["box"])

    def test_their_lines_are_whole_and_the_page_never_scrolls_sideways(self):
        for c in self.got["cells"]:
            for line in c["lines"]:
                with self.subTest(line=line["t"]):
                    self.assertLessEqual(line["sw"], line["cw"], line)
        self.assertLessEqual(self.got["sideways"], 0)
