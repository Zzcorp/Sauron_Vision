"""The instrument page on the bureau v2 note's own pictures (2026-11-15).

The operator's deploy note for the desk v2 promised a small follow-up for
the display defects its before/after pictures show. Two are this page's,
on scenes 04 and 05 (/instruments/AUDUSD/ at 1440 x 900, the signal rail
open, his REAL long of 10,000 on the chart; 05 with the rail's AUDUSD card
pinned), read here on the pictures' own invented book
(tests/audusd_scene_fixture.py) at the pictures' own instant:

  D1  THE HEADER'S FEED LINE. Whose price this is and how old ("eToro bid
      · 10 s") wrapped at any space: "eToro bid · 10" over "s", the unit
      alone on its line. A word, or a number with its unit, never splits:
      the line may take two lines, and only at its separators.

Measured in a headless Chromium on the page the test client serves, every
request answered here (B0's driver, tests/old_design/measure.py), the
server and the page held at the pictures' instant, the chart library from
its pinned copy (tests/vendor), the machine's faces drawing (Inter and
JetBrains Mono, as on CI). Skipped without Chromium. Display only: no
order, no broker, no model, no network.

Run with:  python manage.py test tests.test_instrument_desk_v2_scenes
"""
import json
import pathlib
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from tests import audusd_scene_fixture as S
from tests.test_close_advice import CHROME

ROOT = pathlib.Path(settings.BASE_DIR)
LIB = ROOT / "tests/vendor/lightweight-charts-4.1.0/lightweight-charts.standalone.production.js"
CDN = "https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"
ID = S.CHART_ID
T_MS = int(S.T.timestamp() * 1000)

#: The pictures' desk first (1440 x 900, the rail open), then the others
#: the page's own live tests read (tests/test_instrument_desk_v2.py,
#: LIVE_SIZES).
PICTURES = (1440, 900, "open")
SIZES = (PICTURES, (1280, 800, "open"), (1366, 768, "open"), (1600, 900, "open"),
         (1280, 800, "closed"), (1440, 900, "closed"), (1920, 1080, "open"))


class _Scene:
    """B0's driver with the chart library from its pinned copy, the page's
    clock held at the pictures' instant; one tab per state."""

    def __init__(self, client):
        from tests.old_design.measure import ORIGIN, _Driver, _Server
        self.origin = ORIGIN
        server = _Server(client)
        lib = LIB.read_bytes()

        def answer(request, rtype):
            url = request["url"]
            # the library from its pinned copy, on the page's own origin
            # (the same bytes, so its SRI hash holds)
            if url.startswith(ORIGIN + "/__lwc__/") or url.startswith(CDN.rsplit("/", 2)[0]):
                return 200, {"Content-Type": "application/javascript; charset=utf-8",
                             "Access-Control-Allow-Origin": "*"}, lib
            got = server(request, rtype)
            if got and rtype == "Document" and got[0] == 200:
                body = got[2].replace(CDN.encode(), (ORIGIN + "/__lwc__/lightweight-charts.js").encode())
                return got[0], got[1], body
            return got
        self.driver = _Driver(CHROME, answer)

    def open(self, width, height, rail="open"):
        """A tab on the instrument page as the pictures read it: B0's held
        clock at T (INIT), the rail as asked, the menu open, the chart on
        its one-hour candles; read once its fetches have landed and the
        chart has drawn."""
        from tests.old_design.measure import ADVANCE, INIT, LOAD_MS, SETTLE
        prefs = {"sauron_signals_rail": rail, "sauron_sidebar": "full", "sauron_rail_sig": "0",
                 "sauron_rail_watch": "0", "sv-chart:%s:%s" % (ID, S.SYMBOL): json.dumps({"tf": "1h"})}
        init = INIT % {"t": T_MS, "prefs": json.dumps(prefs), "ws": json.dumps("open")}
        for attempt in range(4):
            tid, sid = self.driver.tab(width, height, init=init)
            try:
                self.driver.go(sid, self.origin + S.PAGE_URL, timeout=30)
                break
            except TimeoutError:
                # a loaded machine can stall a tab's first parse: a fresh
                # tab, at most 4 (as the page's own live tests do)
                self.driver.close_tab(tid)
                if attempt == 3:
                    raise
        self.driver.js(sid, ADVANCE % LOAD_MS)
        self.driver.quiet(sid, still=0.4, cap=15)
        for _ in range(150):
            if self.driver.js(sid, "(function(){var h=window.svCharts&&svCharts['%s'];"
                                   "return h&&h.bars?h.bars().length:0})()" % ID):
                break
            self.driver.js(sid, "window.__svClock.sleep(100)")
        self.driver.js(sid, ADVANCE % 1200)
        self.driver.quiet(sid, still=0.5, cap=15)
        self.driver.js(sid, SETTLE % 300)
        return tid, sid

    def js(self, sid, expression):
        return self.driver.js(sid, expression)

    def read(self, sid, script):
        return json.loads(self.driver.js(sid, script))

    def close(self):
        self.driver.close()


def _held_at_t(cls):
    """Every clock the server reads held at the pictures' instant (B0's
    hold), released when the class is done."""
    from django.core.cache import cache

    from tests.old_design.measure import freeze_patches
    for p in freeze_patches():
        p.start()
        cls.addClassCleanup(p.stop)
    cache.clear()


def _scene_user(name):
    from tests.old_design.measure import tour_done
    user = get_user_model().objects.create_user(name, password="x", is_staff=True, is_superuser=True)
    tour_done(user)
    S.seed_scene(user)
    client = Client()
    client.force_login(user)
    return client


# ══════════════════════════════════════════════════════════════════════════
# D1: the header's feed line
# ══════════════════════════════════════════════════════════════════════════

#: Whose price and how old, as the header shows it: the row and the feed's
#: boxes, the words, and for each part between two separators (" · ") the
#: lines its letters sit on, read off the glyphs themselves.
WORDS = r"""(function () {
  function box(e) { if (!e) return null; var r = e.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
  var ih = document.querySelector('.sv-ih');
  var src = ih ? ih.querySelector('.dtl-src') : null;
  var R = { ih: box(ih), feed: box(ih ? ih.querySelector('.sv-ih-feed') : null), src: box(src),
            mkt: box(ih ? ih.querySelector('.dtl-mkt') : null), sides: box(ih ? ih.querySelector('.sv-ih-act') : null),
            text: '', parts: [], lines: [], ink: null };
  if (!src) return JSON.stringify(R);
  /* the words' own glyphs, wherever they are drawn */
  var all = document.createRange(); all.selectNodeContents(src);
  var rs = Array.prototype.slice.call(all.getClientRects()).filter(function (r) { return r.width > 0 && r.height > 0; });
  if (rs.length) R.ink = { x: Math.min.apply(null, rs.map(function (r) { return r.left; })),
                           r: Math.max.apply(null, rs.map(function (r) { return r.right; })),
                           y: Math.min.apply(null, rs.map(function (r) { return r.top; })),
                           b: Math.max.apply(null, rs.map(function (r) { return r.bottom; })) };
  var chars = [], walk = document.createTreeWalker(src, NodeFilter.SHOW_TEXT), n;
  while ((n = walk.nextNode())) for (var i = 0; i < n.data.length; i++) chars.push([n, i]);
  R.text = chars.map(function (c) { return c[0].data.charAt(c[1]); }).join('');
  function top(k) {
    var c = chars[k], rg = document.createRange();
    rg.setStart(c[0], c[1]); rg.setEnd(c[0], c[1] + 1);
    var rs = rg.getClientRects();
    return rs.length ? Math.round(rs[0].top) : null;
  }
  var tops = {};
  for (var k = 0; k < chars.length; k++) {
    if (/\s/.test(R.text.charAt(k))) continue;
    var t = top(k); if (t !== null) tops[t] = (tops[t] || '') + R.text.charAt(k);
  }
  R.lines = Object.keys(tops).sort(function (a, b) { return a - b; }).map(function (t) { return tops[t]; });
  var at = 0;
  R.text.split(' \u00b7 ').forEach(function (part) {
    var on = {};
    for (var k = at; k < at + part.length; k++) {
      if (/\s/.test(R.text.charAt(k))) continue;
      var t = top(k); if (t !== null) on[t] = (on[t] || '') + R.text.charAt(k);
    }
    R.parts.push({ t: part, on: Object.keys(on).sort(function (a, b) { return a - b; }).map(function (t) { return on[t]; }) });
    at += part.length + 3;
  });
  return JSON.stringify(R);
})()"""

#: The market shuts, as the page hears it: the one painter takes the
#: quote's shut state (its own words, "closed · eToro bid 19:13 · opens Sun
#: 22:00 UTC") and sv-market-status.js's chip turns CLOSED.
SHUT = r"""(function () {
  var p = window.SVVenue && SVVenue.get('%s');
  if (!p) return '';
  var q = JSON.parse(JSON.stringify(p));
  q.state = 'shut';
  q.shut = { since: q.at, opens: 'opens Sun 22:00 UTC' };
  SVVenue.ingest(q, (q._t || SVVenue.now()) + 1000);
  SVVenue.flush();
  var m = document.querySelector('.sv-ih .dtl-mkt');
  if (m) { m.classList.remove('mk-open'); m.classList.add('mk-closed');
    var t = m.querySelector('.mk-text'); if (t) t.textContent = 'CLOSED'; }
  return document.querySelector('.sv-ih .dtl-src').textContent;
})()""" % S.SYMBOL


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheFeedLineBreaksOnlyAtItsSeparatorsTests(TestCase):
    """D1. The header at 1440 x 900 with the rail open and his REAL long
    (scenes 04 and 05): "● eToro bid · 10" over "s" over "● OPEN", the
    unit alone on its line. Whose price and how old is never cut nor
    split: the feed line takes two lines where the row is tight, broken
    after a separator, never inside a word or between a number and its
    unit; it stays inside the 52 px row; and so at every desk the page's
    own tests read, open market and shut."""

    @classmethod
    def setUpTestData(cls):
        _held_at_t(cls)
        desk = _Scene(_scene_user("scene_words"))
        cls.open, cls.shut, cls.said = {}, {}, {}
        try:
            for w, h, rail in SIZES:
                tid, sid = desk.open(w, h, rail)
                cls.open[(w, rail)] = desk.read(sid, WORDS)
                cls.said[(w, rail)] = desk.js(sid, SHUT)
                cls.shut[(w, rail)] = desk.read(sid, WORDS)
                desk.driver.close_tab(tid)
        finally:
            desk.close()

    def _each(self, got):
        return [(w, rail, got[(w, rail)]) for w, _h, rail in SIZES]

    def _whole(self, got, words):
        self.assertRegex(got["text"], words, "the one painter's words")
        for part in got["parts"]:
            self.assertEqual(len(part["on"]), 1, "%r split over lines %r (the line: %r)"
                             % (part["t"], part["on"], got["lines"]))
        self.assertLessEqual(len(got["lines"]), 2, "two lines at most: %r" % got["lines"])

    def _inside(self, got):
        """The words inside their group, the group inside the 52 px row,
        and clear of the two sides beside it."""
        ih, feed, ink, sides = got["ih"], got["feed"], got["ink"], got["sides"]
        self.assertGreaterEqual(feed["y"], ih["y"] - 0.5, "the feed inside the 52 px row: %r in %r" % (feed, ih))
        self.assertLessEqual(feed["b"], ih["b"] + 0.5, "the feed inside the 52 px row: %r in %r" % (feed, ih))
        self.assertIsNotNone(ink, "the words drawn")
        self.assertGreaterEqual(ink["x"], feed["x"] - 0.5, "the words inside their group: %r in %r" % (ink, feed))
        self.assertLessEqual(ink["r"], feed["r"] + 0.5, "the words inside their group: %r in %r" % (ink, feed))
        self.assertGreaterEqual(ink["y"], ih["y"] - 0.5, "the words inside the row: %r in %r" % (ink, ih))
        self.assertLessEqual(ink["b"], ih["b"] + 0.5, "the words inside the row: %r in %r" % (ink, ih))
        self.assertLessEqual(ink["r"], sides["x"] - 4, "the words clear of the two sides: %r, %r" % (ink, sides))

    def test_the_pictures_feed_line_never_leaves_a_unit_alone(self):
        """Scene 04 (and 05, the same header): "eToro bid · 10 s" whole on
        one line, or "eToro bid ·" over "10 s"; never "s" alone."""
        got = self.open[PICTURES[0], PICTURES[2]]
        self._whole(got, r"^eToro bid · \d+ s$")
        self._inside(got)

    def test_the_feed_line_breaks_only_at_its_separators_at_every_desk(self):
        for w, rail, got in self._each(self.open):
            with self.subTest(width=w, rail=rail):
                self._whole(got, r"^eToro bid · \d+ s$")
                self._inside(got)

    def test_a_shut_market_s_words_break_only_at_their_separators(self):
        """The longest words the line says: "closed · eToro bid 19:13 ·
        opens Sun 22:00 UTC", painted by the one painter."""
        for w, rail, got in self._each(self.shut):
            with self.subTest(width=w, rail=rail):
                self.assertIn("opens Sun 22:00 UTC", self.said[(w, rail)])
                self._whole(got, r"^closed · eToro bid \d\d:\d\d · opens Sun 22:00 UTC$")
                self._inside(got)

