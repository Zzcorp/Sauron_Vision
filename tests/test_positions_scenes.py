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
  * D5, 1280 x 800 (scene 10): OPEN POSITIONS scrolled sideways, and
    PRICED BY's ages sat under the pinned CLOSE column. Its columns need
    1,044 px with PRICED BY at its fixed 160 (the figure columns as wide
    as their widest figure); the desk has 961. At 1280 the table fits: the
    source may shorten, from its start, the age never.

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


#: OPEN POSITIONS as the 1280 screen shows it: the table against its
#: wrapper, every cell's words against the cell (B7's own measure: PRICED
#: BY may shorten its source, never its end), and each row's PRICED BY: its
#: words, the age (what follows their last " · ") and whether the age is
#: whole in the span's visible box and is what the screen shows there (not
#: the pinned CLOSE column over it).
OPEN_ROWS = r"""(function () {
  function rect(r) { return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }
  var wrap = document.querySelector('.pd-pos .table-wrapper');
  var wb = wrap.getBoundingClientRect();
  var out = {vw: innerWidth, fit: [wrap.scrollWidth, wrap.clientWidth],
             view: {l: wb.left + wrap.clientLeft, r: wb.left + wrap.clientLeft + wrap.clientWidth}, cut: [], rows: []};
  function texts(el) {
    var rects = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), t;
    while ((t = w.nextNode())) {
      if (!t.nodeValue.trim()) continue;
      var p = t.parentElement;
      if (!p || p.closest('.pd-sr, [hidden]') || !p.checkVisibility()) continue;
      var g = document.createRange(); g.selectNodeContents(t);
      Array.prototype.forEach.call(g.getClientRects(), function (q) { if (q.width > 0) rects.push(q); });
    }
    return rects;
  }
  Array.prototype.forEach.call(document.querySelectorAll('.pd-pos .pd-table > thead > tr > th, .pd-pos .pd-table > tbody > tr[data-sv-position-row] > td'), function (td) {
    var rects = texts(td); if (!rects.length) return;
    var cs = getComputedStyle(td), b = td.getBoundingClientRect();
    var left = b.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft) - 0.5;
    var right = b.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight) + 0.5;
    var lo = Math.min.apply(null, rects.map(function (q) { return q.left; }));
    var hi = Math.max.apply(null, rects.map(function (q) { return q.right; }));
    var cut = td.classList.contains('pd-srcc') ? hi > right : (lo < left || hi > right);
    if (cut) out.cut.push([td.getAttribute('data-label') || td.tagName, td.textContent.replace(/\s+/g, ' ').trim().slice(0, 30)]);
  });
  Array.prototype.forEach.call(document.querySelectorAll('.pd-pos .pd-table > tbody > tr[data-sv-position-row]'), function (tr) {
    var sp = tr.querySelector('td.pd-srcc .pd-src');
    var row = {sym: tr.getAttribute('data-pos-symbol')};
    if (!sp) { out.rows.push(row); return; }
    var tn = sp.firstChild; while (tn && tn.nodeType !== 3) tn = tn.nextSibling;
    var words = tn.nodeValue, at = words.lastIndexOf('·');
    var start = at < 0 ? 0 : at + 1;
    while (start < words.length && /\s/.test(words.charAt(start))) start++;
    var g = document.createRange(); g.setStart(tn, start); g.setEnd(tn, words.replace(/\s+$/, '').length);
    var age = rect(g.getBoundingClientRect());
    var cs = getComputedStyle(sp), sb = sp.getBoundingClientRect();
    var box = {l: sb.left + parseFloat(cs.paddingLeft), r: sb.right - parseFloat(cs.paddingRight)};
    var hit = document.elementFromPoint((age.l + age.r) / 2, (age.t + age.b) / 2);
    row.words = words.trim(); row.age = words.slice(start).trim(); row.ageBox = age; row.box = box;
    row.seen = !!(hit && (hit === sp || sp.contains(hit)));
    row.over = hit ? String(hit.className || hit.tagName).slice(0, 40) : null;
    out.rows.push(row);
  });
  return JSON.stringify(out);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheOpenBookAt1280Tests(TestCase):
    """D5: /positions/ at 1280 x 800 (scene 10): OPEN POSITIONS fits its
    card; every figure whole; PRICED BY's age whole and on screen."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        S.hold_the_clock(cls)
        book = S.scene_book()
        client = Client()
        client.force_login(book["user"])
        desk = S.SceneBrowser(client)
        try:
            tid, sid = desk.open("/positions/", 1280, 800)
            cls.got = json.loads(desk.js(sid, OPEN_ROWS))
            desk.close_tab(tid)
        finally:
            desk.close()

    def test_the_scene_was_reached(self):
        self.assertEqual(self.got["vw"], 1280)
        self.assertEqual(sorted(r["sym"] for r in self.got["rows"]),
                         ["AUDUSD", "BTCUSD", "EURUSD", "GBPUSD", "XAUUSD"])
        self.assertTrue(all(r.get("words") for r in self.got["rows"]), self.got["rows"])

    def test_the_table_fits_its_card(self):
        scroll, client = self.got["fit"]
        self.assertLessEqual(scroll, client)

    def test_no_figure_and_no_word_is_cut_but_a_source_s_start(self):
        self.assertEqual(self.got["cut"], [])

    def test_every_age_is_whole_and_on_screen(self):
        """The words' end, after their last " · " (13 s, live), inside the
        span's visible box and the table's, and what the screen shows at
        its centre: never under the pinned CLOSE."""
        view = self.got["view"]
        for row in self.got["rows"]:
            with self.subTest(row=row["sym"], words=row["words"]):
                self.assertRegex(row["age"], r"^(\d+ (s|min|h|d)|live)$")
                self.assertGreaterEqual(row["ageBox"]["l"], row["box"]["l"] - 0.5, row)
                self.assertLessEqual(row["ageBox"]["r"], row["box"]["r"] + 0.5, row)
                self.assertGreaterEqual(row["ageBox"]["l"], view["l"] - 0.5, row)
                self.assertLessEqual(row["ageBox"]["r"], view["r"] + 0.5, row)
                self.assertTrue(row["seen"], "the age of %s is under %s" % (row["sym"], row["over"]))
