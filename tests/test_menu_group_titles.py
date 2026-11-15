"""The menu's group titles keep a clear gap from their fold chevron (the
desk v2 polish, D6, 2026-11-15).

Every scene of the desk v2 deploy note with the menu open showed "THE BOOK
· THE MONEY" running into its fold chevron. The menu is 232 px; a group
title's button leaves its name 199 px beside the 14 px chevron, and the
title, in Orbitron 600 at 11 px tracked .18em, takes 193 px. The name was
let shrink (min-width: 0) without its words wrapping, and the button's gap
was 4 px (a second gap: 4px in static/css/sv-frame.css overrode the
board's 8 px), so the words ran 8.5 px over the chevron.

Measured on the scene (tests/desk_scenes.py: the pictures' invented book,
/command/ at 1440 x 900 with the menu open, the page served with every
script) in a face at least as wide as Orbitron (the frame tests'
stand-in, tests/test_shell_frame_measured.ORBITRON_STANDIN: no face is
fetched in a test; a title that keeps its gap in this one keeps it in
Orbitron): every group title's words stand whole, at least the board's
8 px clear of their chevron, open and folded with its unseen dot.

Display only: the menu's links, words and order are unchanged; nothing
here posts, trades, or calls a broker or a model.
"""
import json
import unittest

from django.test import Client, TestCase

from tests import desk_scenes as S
from tests.old_design.measure import ACT_MS
from tests.test_close_advice import CHROME
from tests.test_shell_frame_measured import ORBITRON_STANDIN

#: The board's gap between a group title and its chevron (Desk2.dc.html,
#: .sec { gap: 8px }).
GAP = 8

#: Each group title of the open menu: its words' extent (every line), its
#: box, its chevron's box, whether anything overflows the name's box, and
#: the section's fold state.
TITLES = r"""(function () {
  var out = [];
  document.querySelectorAll('#mainSidebar .nav-section[data-nav-sec]').forEach(function (sec) {
    var b = sec.querySelector('.nav-fold'), name = b.querySelector('.nav-fold-name'), ico = b.querySelector('.sv-ico-fold');
    var g = document.createRange(); g.selectNodeContents(name);
    var rects = Array.prototype.filter.call(g.getClientRects(), function (q) { return q.width > 0; });
    var nb = name.getBoundingClientRect(), ib = ico.getBoundingClientRect(), bb = b.getBoundingClientRect();
    var cs = getComputedStyle(b);
    out.push({sec: sec.getAttribute('data-nav-sec'), words: name.textContent.trim(),
              folded: sec.classList.contains('is-folded'), unseen: sec.classList.contains('has-unseen'),
              textL: Math.min.apply(null, rects.map(function (q) { return q.left; })),
              textR: Math.max.apply(null, rects.map(function (q) { return q.right; })),
              lines: rects.length, name: {l: nb.left, r: nb.right, t: nb.top, b: nb.bottom}, sw: name.scrollWidth, cw: name.clientWidth,
              ico: {l: ib.left, r: ib.right, t: ib.top, b: ib.bottom}, btn: {l: bb.left, r: bb.right, t: bb.top, b: bb.bottom},
              padL: parseFloat(cs.paddingLeft), family: getComputedStyle(name).fontFamily});
  });
  return JSON.stringify({side: document.querySelector('#mainSidebar').getBoundingClientRect().width, titles: out});
})()"""

#: THE BOOK · THE MONEY folded by its own button, as the operator folds it.
FOLD_THE_BOOK = r"""(function () {
  var b = document.querySelector('#mainSidebar .nav-section[data-nav-sec="the-book"] .nav-fold');
  b.click();
  return b.getAttribute('aria-expanded');
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheGroupTitlesKeepTheirGapTests(TestCase):
    """Scene 01: /command/ at 1440 x 900, the menu open, its titles drawn in
    a face at least as wide as Orbitron; then THE BOOK · THE MONEY folded,
    its unseen dot beside its words."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        S.hold_the_clock(cls)
        book = S.scene_book()
        client = Client()
        client.force_login(book["user"])
        desk = S.SceneBrowser(client)
        try:
            tid, sid = desk.open("/command/", 1440, 900)
            cls.standin = desk.js(sid, ORBITRON_STANDIN)
            desk.js(sid, "document.fonts.ready.then(function () { return 1; })")
            cls.open = json.loads(desk.js(sid, TITLES))
            nid = desk.driver.nodes(sid, '#mainSidebar .nav-section[data-nav-sec="the-book"] .nav-fold-name')
            got = desk.driver.call("CSS.getPlatformFontsForNode", {"nodeId": nid[0]}, session=sid) if nid else {}
            cls.faces = [f["familyName"] for f in got.get("fonts", [])]
            cls.fold = desk.js(sid, FOLD_THE_BOOK)
            # as the pictures settled after an act: the chevron's quarter
            # turn (a transition) ended, its box square again
            desk.settle(sid, ACT_MS)
            cls.folded = json.loads(desk.js(sid, TITLES))
            desk.close_tab(tid)
        finally:
            desk.close()

    def _book(self, got):
        return [t for t in got["titles"] if t["sec"] == "the-book"][0]

    def test_the_scene_was_reached_in_the_wide_face(self):
        self.assertAlmostEqual(self.open["side"], 232, delta=0.5)
        self.assertEqual(len(self.open["titles"]), 8)
        self.assertEqual(self._book(self.open)["words"], "The book · the money")
        self.assertFalse(self._book(self.open)["folded"])
        self.assertGreater(self.standin, 0, "the stand-in face loaded")
        self.assertIn("DejaVu Sans", self.faces, "THE BOOK · THE MONEY drawn in the wide face")

    def _held(self, t):
        """Its words whole inside its button, nothing over its name's box,
        and GAP px clear of its chevron."""
        self.assertGreaterEqual(t["textL"], t["btn"]["l"] + t["padL"] - 0.5, t)
        self.assertLessEqual(t["sw"], t["cw"], t)
        self.assertGreaterEqual(t["ico"]["l"] - t["textR"], GAP - 0.5, t)
        self.assertGreaterEqual(t["ico"]["l"] - t["name"]["r"], GAP - 0.5, t)

    def test_every_open_title_keeps_its_gap(self):
        for t in self.open["titles"]:
            with self.subTest(title=t["words"]):
                self._held(t)

    def test_a_folded_title_keeps_its_gap_with_its_unseen_dot(self):
        """Folded, a group holding an unseen row says so with a dot after
        its words (static/js/sv-frame.js, has-unseen): the dot is part of
        the name and keeps the same gap."""
        self.assertEqual(self.fold, "false")
        t, was = self._book(self.folded), self._book(self.open)
        self.assertTrue(t["folded"])
        self.assertTrue(t["unseen"], "the book holds an unseen row in the scene")
        # the chevron at rest after its quarter turn, no wider than open
        self.assertLessEqual(t["ico"]["r"] - t["ico"]["l"], was["ico"]["r"] - was["ico"]["l"] + 0.5, t["ico"])
        self._held(t)
