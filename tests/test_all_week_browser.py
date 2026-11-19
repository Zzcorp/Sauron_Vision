"""eToro's ALL-WEEK INSTRUMENTS, MEASURED IN CHROMIUM (2026-11-19). Display
only; money direction none.

The operator, 2026-11-19: yes, the screens say "open 24/7 at eToro" at the
weekend for eToro's all-week instruments. The gold page of the bureau v2
note's invented book (tests/gold_weekend_fixture.py), served by the test
client and drawn by a headless Chromium (B0's driver, tests/old_design/
measure.py), the server and the page held at one instant:

  SATURDAY 21 November, 15:00 UTC. The header's market badge reads eToro's
  own "24/7", its dot filled (an open market), its title eToro's breaks,
  under its own session code; a minute later the badge poller has
  repainted it from its own row (/api/exchange-status/ "all_week") and it
  still reads 24/7, never CME's CLOSED (the build map's W2). Whose price
  and how old reads "open · eToro 24/7 · eToro ask · 4 min", whole, each
  part on one line, inside the 52 px row; the cell is not the shut
  market's muted cell. The badge's words keep 4.5:1 on their ground.

  FRIDAY 20 November, 22:10 UTC, inside eToro's Friday break. The badge
  reads "PAUSE", its dot ringed in the warning amber (no solid red, no
  fill), its title "pause · eToro reopens 22:30 UTC"; the words "pause ·
  eToro ask 22:00 · eToro reopens 22:30 UTC". At the reopening the
  browser's own grammar turns them open at eToro, by itself.

Skipped without Chromium (SV_CHROME names it). No order, no broker, no
model, no network: every request is answered here.

Run with:  python manage.py test tests.test_all_week_browser
"""
import json
import pathlib
import unittest
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from tests import gold_weekend_fixture as G
from tests.test_close_advice import CHROME

ROOT = pathlib.Path(settings.BASE_DIR)
LIB = ROOT / ("tests/vendor/lightweight-charts-4.1.0/"
              "lightweight-charts.standalone.production.js")
CDN = ("https://unpkg.com/lightweight-charts@4.1.0/dist/"
       "lightweight-charts.standalone.production.js")


def _ms(at):
    return int(at.timestamp() * 1000)


class _Desk:
    """B0's driver on the gold page, the page's clock held at `at`; the
    chart library from its pinned copy."""

    def __init__(self, client, at):
        from tests.old_design.measure import ORIGIN, _Driver, _Server
        self.origin, self.at = ORIGIN, at
        server = _Server(client)
        lib = LIB.read_bytes()

        def answer(request, rtype):
            url = request["url"]
            if url.startswith(ORIGIN + "/__lwc__/") or \
                    url.startswith(CDN.rsplit("/", 2)[0]):
                return 200, {"Content-Type":
                             "application/javascript; charset=utf-8",
                             "Access-Control-Allow-Origin": "*"}, lib
            got = server(request, rtype)
            if got and rtype == "Document" and got[0] == 200:
                body = got[2].replace(CDN.encode(), (
                    ORIGIN + "/__lwc__/lightweight-charts.js").encode())
                return got[0], got[1], body
            return got
        self.driver = _Driver(CHROME, answer)

    def open(self, width=1440, height=900):
        from tests.old_design.measure import ADVANCE, INIT, LOAD_MS, SETTLE
        prefs = {"sauron_signals_rail": "open", "sauron_sidebar": "full",
                 "sauron_rail_sig": "0", "sauron_rail_watch": "0",
                 "sv-chart:%s:%s" % (G.CHART_ID, G.SYMBOL):
                     json.dumps({"tf": "1h"})}
        init = INIT % {"t": _ms(self.at), "prefs": json.dumps(prefs),
                       "ws": json.dumps("open")}
        for attempt in range(4):
            tid, sid = self.driver.tab(width, height, init=init)
            try:
                self.driver.go(sid, self.origin + G.PAGE_URL, timeout=30)
                break
            except TimeoutError:
                self.driver.close_tab(tid)
                if attempt == 3:
                    raise
        self.driver.js(sid, ADVANCE % LOAD_MS)
        self.driver.quiet(sid, still=0.4, cap=15)
        for _ in range(150):
            if self.driver.js(sid, "(function(){var h=window.svCharts&&"
                                   "svCharts['%s'];return h&&h.bars?"
                                   "h.bars().length:0})()" % G.CHART_ID):
                break
            self.driver.js(sid, "window.__svClock.sleep(100)")
        self.driver.js(sid, ADVANCE % 1200)
        self.driver.quiet(sid, still=0.5, cap=15)
        self.driver.js(sid, SETTLE % 300)
        return tid, sid

    def read(self, sid, script):
        return json.loads(self.driver.js(sid, script))

    def close(self):
        self.driver.close()


def hold_server(cls, at):
    """Every clock the server reads held at `at` for the class (B0's hold
    at another instant)."""
    from django.core.cache import cache

    from tests.old_design.measure import _ClockSwap
    patches = [_ClockSwap(at.timestamp, over=True),
               mock.patch("django.utils.timezone.now", return_value=at),
               mock.patch("market_data.one_quote.now", return_value=at),
               mock.patch("signals.market_hold.GATE", True),
               mock.patch("bot_program.entry_timing.GATE", True)]
    try:
        import market_data.all_week_display  # noqa: F401
        patches.append(mock.patch("market_data.all_week_display.GATE", True))
    except ImportError:
        pass        # the branch's base: Sauron's own words, to be measured
    for p in patches:
        p.start()
        cls.addClassCleanup(p.stop)
    cache.clear()


def desk_user(name, at):
    from tests.old_design.measure import tour_done
    user = get_user_model().objects.create_user(
        name, password="x", is_staff=True, is_superuser=True)
    tour_done(user)
    G.seed(user, at)
    client = Client()
    client.force_login(user)
    return client


#: The header as the page draws it: the badge (its words, classes, title,
#: session code, its dot's fill and ring, its words' colour and ground),
#: whose price and how old (its text, each part's lines, the row and the
#: words' boxes), and the cell's state.
HEADER = r"""(function () {
  function box(e) { if (!e) return null; var r = e.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
  function rgb(s) { var m = String(s).match(/[\d.]+/g); return m ? m.slice(0, 4).map(Number) : null; }
  function lum(c) { return [0, 1, 2].map(function (i) { var v = c[i] / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); })
    .reduce(function (a, v, i) { return a + v * [0.2126, 0.7152, 0.0722][i]; }, 0); }
  function ground(e) { while (e) { var c = rgb(getComputedStyle(e).backgroundColor);
    if (c && (c.length < 4 || c[3] > 0.5)) return c; e = e.parentElement; } return [255, 255, 255]; }
  var ih = document.querySelector('.sv-ih');
  var m = ih ? ih.querySelector('.dtl-mkt') : null;
  var t = m ? m.querySelector('.mk-text') : null, dot = m ? m.querySelector('.mk-dot') : null;
  var src = ih ? ih.querySelector('.dtl-src') : null;
  var R = { ih: box(ih), feed: box(ih ? ih.querySelector('.sv-ih-feed') : null), badge: null, words: '',
            parts: [], ink: null, state: src ? src.getAttribute('data-q-state') : null,
            mutedColor: null, color: src ? getComputedStyle(src).color : null };
  if (m) {
    var fg = rgb(getComputedStyle(t).color), bg = ground(m);
    var hi = Math.max(lum(fg), lum(bg)), lo = Math.min(lum(fg), lum(bg));
    var ds = getComputedStyle(dot);
    R.badge = { text: t.textContent.trim(), cls: m.className, title: m.getAttribute('title'),
                session: m.getAttribute('data-market-session'), dotFill: ds.backgroundColor,
                dotRing: ds.borderTopColor, contrast: (hi + 0.05) / (lo + 0.05) };
  }
  if (!src) return JSON.stringify(R);
  R.words = src.textContent;
  var all = document.createRange(); all.selectNodeContents(src);
  var rs = Array.prototype.slice.call(all.getClientRects()).filter(function (r) { return r.width > 0 && r.height > 0; });
  if (rs.length) R.ink = { x: Math.min.apply(null, rs.map(function (r) { return r.left; })),
                           r: Math.max.apply(null, rs.map(function (r) { return r.right; })),
                           y: Math.min.apply(null, rs.map(function (r) { return r.top; })),
                           b: Math.max.apply(null, rs.map(function (r) { return r.bottom; })) };
  Array.prototype.forEach.call(src.querySelectorAll('.sv-q-seg'), function (seg) {
    var rg = document.createRange(); rg.selectNodeContents(seg);
    var tops = {}; Array.prototype.forEach.call(rg.getClientRects(), function (r) {
      if (r.width > 0) tops[Math.round(r.top)] = 1; });
    R.parts.push({ t: seg.textContent, lines: Object.keys(tops).length });
  });
  return JSON.stringify(R);
})()"""

#: The token colours the badge is drawn in, as the page resolves them.
TOKENS = r"""(function () {
  function c(v) { var e = document.createElement('span'); e.style.color = 'var(' + v + ')';
    document.body.appendChild(e); var out = getComputedStyle(e).color; e.remove(); return out; }
  return JSON.stringify({ ink2: c('--sv-ink-2'), warn: c('--sv-warn'), down: c('--sv-down') });
})()"""


def _whole_in_the_row(test, got):
    for part in got["parts"]:
        test.assertEqual(part["lines"], 1, "a part split over lines: %r"
                         % (got["parts"],))
    ih, ink = got["ih"], got["ink"]
    test.assertIsNotNone(ink, "the words drawn")
    test.assertGreaterEqual(ink["y"], ih["y"] - 0.5, (ink, ih))
    test.assertLessEqual(ink["b"], ih["b"] + 0.5, (ink, ih))


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class SaturdayAfternoonTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        hold_server(cls, G.SAT)
        desk = _Desk(desk_user("aw_sat_desk", G.SAT), G.SAT)
        try:
            tid, sid = desk.open()
            cls.first = desk.read(sid, HEADER)
            cls.tokens = desk.read(sid, TOKENS)
            from tests.old_design.measure import ADVANCE
            desk.driver.js(sid, ADVANCE % 61000)       # the badge poller
            desk.driver.quiet(sid, still=0.5, cap=15)
            cls.polled = desk.read(sid, HEADER)
            desk.driver.close_tab(tid)
            tid, sid = desk.open(1280, 800)
            cls.narrow = desk.read(sid, HEADER)
            desk.driver.close_tab(tid)
        finally:
            desk.close()

    def test_the_badge_reads_etoros_24_7(self):
        b = self.first["badge"]
        self.assertEqual(b["text"], "24/7")
        self.assertEqual(b["session"], "ETORO247_18")
        self.assertIn("mk-open", b["cls"])
        self.assertNotIn("mk-closed", b["cls"])
        self.assertEqual(b["title"], "open · eToro 24/7 (breaks 22:00-23:00 "
                                     "UTC daily, Fri 22:00-22:30)")
        self.assertEqual(b["dotFill"], self.tokens["ink2"], "a filled dot")

    def test_the_poller_keeps_it_a_minute_later(self):
        b = self.polled["badge"]
        self.assertEqual((b["text"], b["session"]), ("24/7", "ETORO247_18"))
        self.assertIn("mk-open", b["cls"])
        self.assertNotIn("CLOSED", json.dumps(self.polled["badge"]))

    def test_whose_price_and_how_old_reads_open_at_etoro(self):
        got = self.first
        self.assertEqual(got["words"], "open · eToro 24/7 · eToro ask · 4 min")
        self.assertEqual(got["state"], "delayed", "not the shut cell")
        _whole_in_the_row(self, got)
        self.assertRegex(self.polled["words"],
                         r"^open · eToro 24/7 · eToro ask · 5 min$")
        _whole_in_the_row(self, self.narrow)

    def test_the_words_keep_their_contrast(self):
        self.assertGreaterEqual(self.first["badge"]["contrast"], 4.5)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FridayBreakTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        hold_server(cls, G.PAUSE)
        desk = _Desk(desk_user("aw_pause_desk", G.PAUSE), G.PAUSE)
        try:
            tid, sid = desk.open()
            cls.got = desk.read(sid, HEADER)
            cls.tokens = desk.read(sid, TOKENS)
            reopened = _ms(G.PAUSE) + 21 * 60 * 1000
            cls.after = desk.driver.js(
                sid, "SVVenue.words(SVVenue.get('XAUUSD'), %d, '')" % reopened)
            cls.state_after = desk.driver.js(
                sid, "SVVenue.stateAt(SVVenue.get('XAUUSD'), %d)" % reopened)
            desk.driver.close_tab(tid)
        finally:
            desk.close()

    def test_the_badge_reads_pause_ringed_in_amber(self):
        b = self.got["badge"]
        self.assertEqual(b["text"], "PAUSE")
        self.assertIn("mk-pause", b["cls"])
        self.assertNotIn("mk-open", b["cls"])
        self.assertEqual(b["title"], "pause · eToro reopens 22:30 UTC")
        self.assertEqual(b["dotRing"], self.tokens["warn"])
        self.assertNotEqual(b["dotFill"], self.tokens["down"], "no red fill")
        self.assertIn(b["dotFill"], ("rgba(0, 0, 0, 0)", "transparent"),
                      "a ring, not a fill")
        self.assertGreaterEqual(b["contrast"], 4.5)

    def test_the_words_say_the_pause_and_reopen_by_themselves(self):
        self.assertEqual(self.got["words"],
                         "pause · eToro ask 22:00 · eToro reopens 22:30 UTC")
        self.assertEqual(self.got["state"], "shut")
        _whole_in_the_row(self, self.got)
        self.assertEqual(self.state_after, "delayed")
        self.assertEqual(self.after,
                         "open · eToro 24/7 · eToro ask · 25 min")
