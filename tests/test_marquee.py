"""The price headband and the news ticker scroll again: continuously,
gently, still under the hand (2026-11-13).

The operator's decision, 2026-11-13: the two strips across the top of every
work page scroll on their own again, right to left, not too fast, and stop
on hover. It overrides S1a's §8 rule for these two strips; the rule's own
comment (static/css/sv-kit.css, §8 Motion) records it.

Why they did not scroll naturally on main 349b1ca: nothing moved them
(sv-kit.css §8, `animation: none` on both tracks), and what the hand did was
three drivers with three offsets: the wheel's (svWheelMarquee), a second
wheel listener on the ticker that moved it 12 px a notch on top of the first,
and the drag's; leaving a strip threw the hand's position away (back to 0),
and so did restoring a collapsed strip. Before S1a the keyframe marquee ran
at half the track's width over a fixed duration, so its speed was the
content's; a refetch or a painter update that changed the width moved the
strip; and after the hand it resumed from its own phase, not from where the
hand left it.

What they do now (static/js/sv-marquee.js): one position per strip, owned by
one driver on requestAnimationFrame, which the wheel, the drag and the arrow
crawl move too; a constant speed in px per second, the frame's own
data-sv-marquee-speed (prices 40, news 30); a seamless loop over the two
halves; the item at the left edge kept in place across a news refetch, a
region sweep, a painter update, an item added or removed; still while the
pointer is on the strip, while a card opened from it is on the page, while
focus is in it, while a finger is down and three seconds after, while the
hand drags it, while the tab is hidden or the strip collapsed, and under
reduced motion (where the wheel and the drag still move it); no frame asked
for while still; the transform rounded to device pixels.

The measured class lays the real shell out in a headless Chromium: the page
the test client renders, its scripts stripped but the three inline blocks
the strips run on (found by their own words, as tests.test_headband_hover_
lives finds them), the one painter and its quote block, the popup registry
and the driver; no network (a socket that never connects, /partials/ticker/
answering what the test queued). It moves a real pointer, wheel, keyboard
and finger through the DevTools and samples each track's transform and the
item at its left edge every frame. On main 349b1ca they fail: nothing moves.

The review of the first build (2026-11-13), each point measured here, red on
e4e8a2d: Shift+Tab into a strip left the focus off screen (the clip's scroll
was wrapped on the loop, trading the focused item for its twin); the loop's
copy took the keyboard and the screen reader a second time, and the last
stop sat under the collapse tab; one loop was a fraction of a pixel, so the
seam shifted every glyph once a loop; the steps' rhythm followed the frame
clock's jitter; a long task made the strip skip up to 10 px; a fresh
headline glowed out of view; a watchlist card (.dh-pop too) held the
headband; a short ticker showed its copy; a click on a collapse button that
moved a few pixels was taken for a drag.

Display only. No order, no broker, no model, no network; every row is
synthetic. Skipped without Chromium.

Run with:  python manage.py test tests.test_marquee
"""
import json
import pathlib
import re
import shutil
import tempfile
import time
import unittest
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, HOST, _Chrome

ROOT = pathlib.Path(settings.BASE_DIR)
BASE = "templates/base.html"
KIT = "static/css/sv-kit.css"
SAURON = "static/css/sauron.css"
DRIVER = "static/js/sv-marquee.js"
WALL = "templates/landing/the_wall.html"

#: px per second, the frame's own constant.
SPEED = {"dh": 40, "ticker": 30}
FRAME = {"dh": "dataHeadband", "ticker": "tickerBar"}
TRACK_ID = {"dh": "dhTrack", "ticker": "tickerTrack"}
#: a few seconds after a finger lifts
TOUCH_RESUME_S = 3.0
#: the most a late frame catches up (sv-marquee.js DT_MAX): after a longer
#: stall the strip goes on from where it froze
CATCH_UP_S = 0.05
#: Input.dispatchKeyEvent's modifier bit for Shift
SHIFT = 8


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


# ══════════════════════════════════════════════════════════════════════════
# The source: one constant each, the rule's record, nothing left to fight
# ══════════════════════════════════════════════════════════════════════════

class TheStripsSourceTests(SimpleTestCase):

    def test_one_constant_each_on_its_frame(self):
        """The speed is the frame's own attribute, in px per second: one
        number each, tuned where the strip is written."""
        base = read(BASE)
        self.assertRegex(base, r'<div class="ticker-bar" id="tickerBar"[^>]*\sdata-sv-marquee-speed="30"')
        self.assertRegex(base, r'<div class="data-headband" id="dataHeadband"[^>]*\sdata-sv-marquee-speed="40"')
        self.assertEqual(base.count('data-sv-marquee-speed="'), 2)

    def test_the_driver_is_loaded_once_deferred(self):
        base = read(BASE)
        self.assertEqual(len(re.findall(r"<script\b[^>]*js/sv-marquee\.js", base)), 1)
        self.assertIn("<script src=\"{% static 'js/sv-marquee.js' %}\" defer></script>", base)
        self.assertTrue((ROOT / DRIVER).is_file())

    def test_s1a_s_rule_records_the_operator_s_decision(self):
        """Where S1a's §8 stopped the marquees, the operator's decision of
        2026-11-13 is written, and the tracks carry no keyframe of their own:
        the driver moves them, on their own layer."""
        kit = read(KIT)
        sec = kit[kit.index("§8 Motion"):kit.index("§3.5 Whose money")]
        self.assertIn("2026-11-13", sec)
        self.assertIn("sv-marquee.js", sec)
        self.assertNotIn("The marquees stand still", sec)
        body = re.search(r"\.ticker-track, \.dh-track \{([^}]*)\}", strip_comments(sec))
        self.assertIsNotNone(body, "the tracks' rule left §8")
        decls = dict(d.split(":", 1) for d in (x.strip() for x in body.group(1).split(";")) if d)
        decls = {k.strip(): v.strip() for k, v in decls.items()}
        self.assertEqual(decls, {"animation": "none", "will-change": "transform"})

    def test_no_keyframe_marquee_is_left_to_fight_the_driver(self):
        css = strip_comments(read(SAURON))
        for gone in ("tickerScroll", "dhScroll"):
            self.assertNotIn(gone, css)
        self.assertNotRegex(css, r"\.ticker-bar:hover \.ticker-track")
        self.assertNotRegex(css, r"\.data-headband:hover \.dh-track")

    def test_one_wheel_listener_per_strip(self):
        """The ticker answered the wheel twice (svWheelMarquee, then a tStep
        listener 12 px a notch): one driver each now, svWheelMarquee."""
        base = read(BASE)
        self.assertNotIn("tStep(e.deltaY", base)
        self.assertNotIn("tStep(e.deltaX", base)
        self.assertIn("window.svWheelMarquee(ticker,", base)
        self.assertIn("window.svWheelMarquee(dhFrame, dhTrack)", base)

    def test_the_wall_s_ticker_shares_nothing_with_it(self):
        """The public Wall page has its own ticker, its own sheet and its own
        script: none of the changed code reaches it, so it is unchanged."""
        wall = read(WALL)
        for name in ("sv-marquee", "data-sv-marquee-speed", "sauron.css", "sv-kit.css",
                     "{% extends"):
            self.assertNotIn(name, wall)
        self.assertIn("animation: tickerScroll 30s linear infinite", wall)
        self.assertIn('id="wallTickerTrack"', wall)
        # the driver takes only the frames that declare a speed
        self.assertIn("[data-sv-marquee-speed]", read(DRIVER))

    def test_the_driver_is_display_only(self):
        src = strip_comments(read(DRIVER))
        for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "localStorage",
                     "sessionStorage", "eval(", "innerHTML", ".submit("):
            self.assertNotIn(word, src)


# ══════════════════════════════════════════════════════════════════════════
# Measured: the real shell in Chromium
# ══════════════════════════════════════════════════════════════════════════

URL = "/getting-started/"

#: The three inline blocks the strips run on, by their own words.
INLINE = ("window.svWheelMarquee = function (frame, track)",
          "UPGRADE-3: WebSocket live ticks.",
          "UPGRADE-9: headband popup escape + hover arrows")
#: The static scripts kept: the one painter, the popup registry, the driver.
STATIC = ("js/sv-venue.js", "js/sv-notif-card.js", "js/sv-marquee.js")

TITLES = (
    "Synthetic wire: a central bank holds its rate, markets steady",
    "Synthetic wire: oil stocks fall a third week",
    "Synthetic wire: cloud demand lifts a software maker",
    "Synthetic wire: a shipping index climbs",
    "Synthetic wire: bond yields ease after a soft print of prices",
    "Synthetic wire: copper firms on supply",
    "Synthetic wire: a retailer cuts its outlook for the season",
    "Synthetic wire: gold drifts",
    "Synthetic wire: a carmaker recalls a model",
    "Synthetic wire: wheat slips as rains return to the plains",
    "Synthetic wire: a chip maker guides higher",
    "Synthetic wire: the euro edges up against the dollar",
)
#: The short ticker's one headline: the shortest, which fits the desk v2
#: board's news lane (a third of the band) with its collapse tab.
SHORT_TITLE = "Synthetic wire: gold drifts"

#: Ahead of every script: a socket that never connects, a /partials/ticker/
#: that answers what the test queued, the driver's frame requests counted
#: by its file, and a tab whose visibility the test sets (headless
#: Chromium is always visible).
STUBS = r"""<script>
(function () {
  window.WebSocket = function (u) { this.url = u; this.readyState = 0; };
  window.WebSocket.prototype.send = function () {};
  window.WebSocket.prototype.close = function () {};
  window.__mqAnswers = [];
  window.fetch = function (url) {
    if (String(url).indexOf('/partials/ticker/') === 0 && window.__mqAnswers.length) {
      var body = window.__mqAnswers.shift();
      return Promise.resolve({ ok: true, status: 200, redirected: false,
        text: function () { return Promise.resolve(body); },
        json: function () { return Promise.reject(new Error('not json')); } });
    }
    return Promise.reject(new TypeError('offline'));
  };
  var raf = window.requestAnimationFrame.bind(window);
  window.__mqRaf = 0;
  window.requestAnimationFrame = function (cb) {
    if (String((new Error()).stack || '').indexOf('sv-marquee.js') >= 0) window.__mqRaf++;
    return raf(cb);
  };
  window.__mqHidden = false;
  Object.defineProperty(Document.prototype, 'hidden', { configurable: true,
    get: function () { return window.__mqHidden; } });
  Object.defineProperty(Document.prototype, 'visibilityState', { configurable: true,
    get: function () { return window.__mqHidden ? 'hidden' : 'visible'; } });
})();
</script>"""

#: The probe: each track's transform and the item at its clip's left edge,
#: every frame; where to point; the style writes each track took.
PROBE = r"""
window.__mq = (function () {
  var IDS = { dh: 'dataHeadband', ticker: 'tickerBar' };
  function parts(name) {
    var f = document.getElementById(IDS[name]);
    var t = f.querySelector('.dh-track, .ticker-track');
    return { f: f, t: t, c: t.parentElement };
  }
  function tx(t) {
    var v = getComputedStyle(t).transform;
    if (!v || v === 'none') return 0;
    var m = /^matrix\(([^)]+)\)$/.exec(v);
    if (m) return parseFloat(m[1].split(',')[4]);
    m = /^matrix3d\(([^)]+)\)$/.exec(v);
    return m ? parseFloat(m[1].split(',')[12]) : NaN;
  }
  function items(t) {
    return Array.prototype.filter.call(t.children, function (n) { return n.matches('.dh-item, .ticker-item'); });
  }
  function keyOf(n) {
    return n.getAttribute('data-news-id') || n.getAttribute('data-symbol') || (n.textContent || '').trim().slice(0, 40);
  }
  function period(t) {
    var its = items(t), n = its.length;
    if (n < 2 || n % 2) return 0;
    return its[n / 2].getBoundingClientRect().left - its[0].getBoundingClientRect().left;
  }
  var writes = { dh: 0, ticker: 0 };
  ['dh', 'ticker'].forEach(function (n) {
    new MutationObserver(function (rs) { writes[n] += rs.length; })
      .observe(parts(n).t, { attributes: true, attributeFilter: ['style'] });
  });
  var marks = [];
  /* With `vis`, every item in view too: its key and its left in the clip. */
  function snap(name, vis) {
    var p = parts(name), c = p.c.getBoundingClientRect(), r = p.t.getBoundingClientRect();
    var its = items(p.t), seen = {}, edge = null, shown = vis ? [] : null;
    for (var i = 0; i < its.length; i++) {
      var k = keyOf(its[i]);
      seen[k] = (seen[k] || 0) + 1;
      var b = its[i].getBoundingClientRect();
      if (!edge && b.right > c.left + 0.5) {
        edge = { key: k, copy: seen[k] - 1, left: b.left - c.left, right: b.right - c.left };
        if (!vis) break;
      }
      if (vis && b.left >= c.right) break;
      if (vis && b.right > c.left) shown.push([k, b.left - c.left]);
    }
    var out = { t: performance.now(), x: tx(p.t), P: period(p.t), n: its.length,
                gapL: r.left - c.left, gapR: c.right - r.right, edge: edge,
                scroll: p.c.scrollLeft, w: writes[name], m: marks.length,
                collapsed: p.f.classList.contains('collapsed') };
    if (vis) out.vis = shown;
    return out;
  }
  var rec = null;
  function start(names, vis) {
    marks = [];
    var me = { names: names, out: {}, vis: !!vis };
    names.forEach(function (n) { me.out[n] = []; });
    rec = me;
    (function loop() {
      if (rec !== me) return;
      me.names.forEach(function (n) { me.out[n].push(snap(n, me.vis)); });
      requestAnimationFrame(loop);
    })();
    return names.length;
  }
  function mark() { marks.push(performance.now()); return marks.length; }
  function stop() { var r = rec; rec = null; return JSON.stringify(r ? r.out : {}); }
  /* A point on the strip, left of its middle (the collapse tab is right). */
  function point(name) {
    var p = parts(name), c = p.c.getBoundingClientRect(), f = p.f.getBoundingClientRect();
    return [Math.round(c.left + c.width * 0.35), Math.round(f.top + f.height / 2)];
  }
  /* An item wholly inside the clip, clear of the collapse tab.
     Updated deliberately (the desk v2 board, approved 2026-11-13: "amazing
     work, bravo, I need it fast!!"): the news is a lane of a third of the
     band, so "clear of the tab" is the tab measured (seeRight), not the old
     120 px, and where no item stands wholly inside at that frame the
     strip's own position puts the first one that fits 8 px in, as the
     hand's wheel would, before anything is measured.
     The room is the one find() asks for (#115's CI, 2026-11-14): 8 px
     clear of the clip's left and 8 px clear of the tab, and a pixel for the
     strip's whole-pixel rounding. With the CI's faces the first headline
     that "fitted" was 366.0 px in a room of 366.4, put at 9 px in it ran
     a pixel into the tab's 8 px, and the helper gave up; now the item
     stands in the middle of that room, and the next is tried if one still
     falls short. */
  function inside(name) {
    var p = parts(name), c = p.c.getBoundingClientRect(), its = items(p.t);
    function find() {
      var right = seeRight(p, c);
      for (var i = 0; i < its.length; i++) {
        var b = its[i].getBoundingClientRect();
        if (b.left > c.left + 8 && b.right < right - 8) {
          return { i: i, key: keyOf(its[i]), x: Math.round((b.left + b.right) / 2),
                   y: Math.round((b.top + b.bottom) / 2) };
        }
      }
      return null;
    }
    var at = find();
    if (at || !window.SVMarquee) return at;
    var room = seeRight(p, c) - c.left - 18;
    for (var i = 0; i < its.length; i++) {
      var b = its[i].getBoundingClientRect();
      if (b.width < room && b.right > c.left) {
        SVMarquee.to(p.t, SVMarquee.offset(p.t) + (c.left + 9 + (room - b.width) / 2 - b.left));
        at = find();
        if (at) return at;
      }
    }
    return null;
  }
  function focusInside(name) {
    var p = parts(name), at = inside(name);
    if (!at) return null;
    items(p.t)[at.i].focus();
    return at.key;
  }
  /* The card a strip opened, on <body>, displayed. */
  function card(sel) {
    var el = document.querySelector('body > ' + sel);
    if (!el || getComputedStyle(el).display === 'none') return null;
    var r = el.getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + Math.min(r.height / 2, 40)),
             pinned: el.classList.contains('sv-pinned') };
  }
  /* A card's coming and going take the popup engine's own timers (the
     hover beat, the crossing's grace): wait for them, up to ms. */
  function waitCard(sel, ms) {
    return new Promise(function (resolve) {
      var t0 = performance.now();
      (function poll() {
        var c = card(sel);
        if (c) return resolve(c);
        if (performance.now() - t0 > ms) return resolve(null);
        setTimeout(poll, 15);
      })();
    });
  }
  /* Armed before the hand moves: the card leaving <body> is seen in the
     microtask the engine hides it in, and with markIt the next mark is set
     right there, before any frame: what comes before it is the grace. */
  function armGone(sel, ms, markIt) {
    window.__mqGone = new Promise(function (resolve) {
      var done = false, mo = null;
      function end(ok) {
        if (done) return;
        done = true;
        if (mo) mo.disconnect();
        if (markIt) mark();
        resolve(ok);
      }
      if (!card(sel)) return end(true);
      mo = new MutationObserver(function () { if (!card(sel)) end(true); });
      mo.observe(document.body, { childList: true });
      setTimeout(function () { end(!card(sel)); }, ms);
    });
    return 0;
  }
  function away() { return [Math.round(innerWidth * 0.45), Math.round(innerHeight * 0.7)]; }
  /* Where item k starts, from the first item, in px of the track. */
  function at(name, k) {
    var its = items(parts(name).t);
    return its[k].getBoundingClientRect().left - its[0].getBoundingClientRect().left;
  }
  function x(name) { return tx(parts(name).t); }
  /* The clip's right edge the eye has: the collapse tab sits over it. */
  function seeRight(p, c) {
    var tab = p.f.querySelector('.hb-collapse-btn'), right = c.right;
    if (tab && tab.offsetWidth) right = Math.min(right, tab.getBoundingClientRect().left);
    return right;
  }
  /* The focused item of a strip: which one (its index, its key, which copy
     of the loop), whether it is inside the clip, and whether it is clear of
     the collapse tab too. */
  function activeIn(name) {
    var p = parts(name), a = document.activeElement;
    if (!a || !p.t.contains(a)) return null;
    while (a.parentElement !== p.t) a = a.parentElement;
    var c = p.c.getBoundingClientRect(), b = a.getBoundingClientRect(), right = seeRight(p, c);
    var its = items(p.t), k = keyOf(a), copy = 0, index = its.indexOf(a);
    for (var i = 0; i < index; i++) if (keyOf(its[i]) === k) copy++;
    return { key: k, index: index, copy: copy,
             inClip: b.left >= c.left - 0.5 && b.right <= c.right + 0.5,
             clear: b.left >= c.left - 0.5 && b.right <= right + 0.5,
             left: Math.round(b.left - c.left), right: Math.round(b.right - c.left), x: tx(p.t) };
  }
  /* The items the keyboard stops on, by index. */
  function stops(name) {
    return items(parts(name).t).map(function (e, i) {
      return e.tabIndex >= 0 && getComputedStyle(e).visibility !== 'hidden' ? i : -1;
    }).filter(function (i) { return i >= 0; });
  }
  /* Each copy of a news item: where it is, whether the eye can see it,
     whether its fresh-headline glow runs and for how long. */
  function glow(id) {
    var p = parts('ticker'), c = p.c.getBoundingClientRect(), right = seeRight(p, c);
    var els = p.t.querySelectorAll('.ticker-item[data-news-id="' + id + '"]');
    return Array.prototype.map.call(els, function (el, i) {
      var b = el.getBoundingClientRect();
      var runs = (el.getAnimations ? el.getAnimations() : []).filter(function (a) {
        return /tNewGlow/.test(a.animationName || '') && a.playState === 'running';
      });
      return { copy: i, left: Math.round(b.left - c.left), right: Math.round(b.right - c.left),
               any: b.right > c.left + 1 && b.left < right - 1,
               whole: b.left >= c.left - 0.5 && b.right <= right + 0.5,
               glowing: runs.length > 0, since: runs.length ? Math.round(runs[0].currentTime) : null,
               bg: getComputedStyle(el).backgroundColor };
    });
  }
  /* Each item of a strip: its key, which copy, whether it is painted. */
  function shown(name) {
    var its = items(parts(name).t), seen = {};
    return its.map(function (e) {
      var k = keyOf(e);
      seen[k] = (seen[k] || 0) + 1;
      return [k, seen[k] - 1, getComputedStyle(e).visibility !== 'hidden'];
    });
  }
  function text(sel) {
    return Array.prototype.map.call(document.querySelectorAll(sel), function (e) { return e.textContent.trim(); });
  }
  return { start: start, stop: stop, mark: mark, point: point, inside: inside, card: card,
           waitCard: waitCard, armGone: armGone,
           away: away, at: at, x: x, items: function (n) { return items(parts(n).t).length; },
           period: function (n) { return period(parts(n).t); }, focusInside: focusInside,
           activeIn: activeIn, stops: stops, glow: glow, shown: shown, text: text, writes: writes,
           order: function (n) { var its = items(parts(n).t); return its.slice(0, its.length / 2).map(keyOf); } };
})();
0
"""


def _keep(m):
    """The scripts the strips run on, left where the page has them."""
    s = m.group(0)
    head = s[:s.index(">") + 1]
    if "data-sv-quotes" in head:
        return s
    if "src=" in head:
        return s if any(name in head for name in STATIC) else ""
    return s if any(words in s for words in INLINE) else ""


def _file(markup):
    page = re.sub(r"<script\b.*?</script>", _keep, markup, flags=re.S)
    page = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", page)
    page = page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
    return re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + STUBS, page, count=1)


def _get(client, url):
    resp = client.get(url, HTTP_HOST=HOST)
    if resp.status_code != 200:
        raise AssertionError("%s answered %s" % (url, resp.status_code))
    return resp.content.decode("utf-8")


class _DeskChrome(_Chrome):
    """Headless Chromium reports no pointer that hovers, and sv-overlay.css
    hides every hover card under (hover: none), as on a phone: this one
    reports what a desk computer does, a fine pointer that hovers."""

    ARGS = _Chrome.ARGS + ("--blink-settings=primaryHoverType=2,availableHoverTypes=2,"
                           "primaryPointerType=4,availablePointerTypes=4",)


class _Tab:
    """One Chromium tab on the page, a hand and a clock."""

    def __init__(self, chrome, uri, *, reduced=False, touch=False, width=1440, height=900):
        self.c = chrome
        self.sid = chrome.page(width, height, False)
        if reduced:
            self.media(True)
        if touch:
            self.c.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1},
                        session=self.sid)
        self.c.open(self.sid, uri)
        self.js(PROBE)
        time.sleep(0.8)          # the first measures, the first frames

    def media(self, reduced):
        self.c.call("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}]},
            session=self.sid)

    def js(self, expression):
        return self.c.eval(self.sid, expression)

    def call(self, method, params):
        return self.c.call(method, params, session=self.sid)

    def move(self, xy, buttons=0):
        p = {"type": "mouseMoved", "x": xy[0], "y": xy[1]}
        if buttons:
            p.update(button="left", buttons=buttons)
        self.call("Input.dispatchMouseEvent", p)

    def press(self, xy):
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": xy[0], "y": xy[1],
                                               "button": "left", "buttons": 1, "clickCount": 1})

    def release(self, xy):
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": xy[0], "y": xy[1],
                                               "button": "left", "buttons": 0, "clickCount": 1})

    def wheel(self, xy, dx, dy):
        self.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": xy[0], "y": xy[1],
                                               "deltaX": dx, "deltaY": dy})

    def key(self, key, code, vk, modifiers=0):
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code,
                                                 "windowsVirtualKeyCode": vk,
                                                 "nativeVirtualKeyCode": vk,
                                                 "modifiers": modifiers})

    def touch(self, kind, xy=None):
        pts = [{"x": xy[0], "y": xy[1]}] if xy else []
        self.call("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

    def sample(self, names, vis=False):
        self.js("__mq.start(%s, %s)" % (json.dumps(list(names)), "true" if vis else "false"))

    def mark(self):
        return self.js("__mq.mark()")

    def stop(self):
        return json.loads(self.js("__mq.stop()"))

    def beat(self, on):
        self.js("window.SV_HOVER_BEAT_MS = %s; 0" % ("450" if on else "1e9"))

    @staticmethod
    def wait(seconds):
        time.sleep(seconds)


def _guard(got, name, fn):
    """Each scenario on its own: one that throws records why and the rest
    still run."""
    try:
        got[name] = fn()
    except Exception as exc:          # recorded, and the test that reads it fails
        got[name] = {"error": "%s: %s" % (type(exc).__name__, exc)}


# ── the scenarios ────────────────────────────────────────────────────────

def _run(tab):
    """Both strips, two seconds, as they come."""
    tab.sample(["dh", "ticker"])
    tab.wait(2.0)
    return tab.stop()


def _ambience(tab):
    out = {}
    for mode in ("magic", "calm", "off"):
        for light in (False, True):
            tab.js("document.body.setAttribute('data-sv-ambience', '%s');"
                   " document.body.classList.toggle('light-mode', %s); 0" % (mode, "true" if light else "false"))
            tab.wait(0.15)
            tab.sample(["dh", "ticker"])
            tab.wait(0.8)
            out["%s/%s" % (mode, "light" if light else "dark")] = tab.stop()
    tab.js("document.body.setAttribute('data-sv-ambience', 'magic'); document.body.classList.remove('light-mode'); 0")
    return out


def _dpr2(tab):
    tab.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900,
                                                   "deviceScaleFactor": 2, "mobile": False})
    try:
        tab.wait(0.4)
        tab.sample(["dh", "ticker"])
        tab.wait(0.9)
        return tab.stop()
    finally:
        tab.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900,
                                                       "deviceScaleFactor": 1, "mobile": False})
        tab.wait(0.3)


def _cost(tab):
    """A second of motion, nothing sampled: what the frames cost."""
    tab.call("Performance.enable", {})

    def metrics():
        got = tab.call("Performance.getMetrics", {})["metrics"]
        return {m["name"]: m["value"] for m in got}
    x0 = {n: tab.js("__mq.x('%s')" % n) for n in ("dh", "ticker")}
    m0 = metrics()
    tab.wait(1.0)
    m1 = metrics()
    x1 = {n: tab.js("__mq.x('%s')" % n) for n in ("dh", "ticker")}
    return {"layouts": m1["LayoutCount"] - m0["LayoutCount"],
            "styles": m1["RecalcStyleCount"] - m0["RecalcStyleCount"],
            "moved": {n: x0[n] - x1[n] for n in x0}}


def _hover(tab, name):
    tab.beat(False)
    try:
        tab.sample([name])
        tab.wait(0.5)
        tab.mark()
        tab.move(tab.js("__mq.point('%s')" % name))
        tab.wait(1.0)
        tab.mark()
        tab.move(tab.js("__mq.away()"))
        tab.wait(1.0)
        return tab.stop()[name]
    finally:
        tab.beat(True)


def _wheel(tab, name):
    tab.beat(False)
    try:
        tab.sample([name])
        tab.move(tab.js("__mq.point('%s')" % name))
        tab.wait(0.4)
        tab.mark()
        tab.wheel(tab.js("__mq.point('%s')" % name), 0, 120)
        tab.wait(0.4)
        tab.mark()
        tab.wheel(tab.js("__mq.point('%s')" % name), -80, 0)      # a trackpad's sideways swipe
        tab.wait(0.4)
        tab.mark()
        tab.move(tab.js("__mq.away()"))
        tab.wait(1.0)
        return tab.stop()[name]
    finally:
        tab.beat(True)


def _seam(tab, name):
    """The strip put 25 px before the end of its loop by the wheel, then let
    go: it crosses the seam."""
    tab.beat(False)
    try:
        xy = tab.js("__mq.point('%s')" % name)
        tab.move(xy)
        tab.wait(0.3)
        period = tab.js("__mq.period('%s')" % name)
        pos = -tab.js("__mq.x('%s')" % name)
        tab.wheel(xy, 0, (period - 25) - pos)
        tab.wait(0.2)
        before = -tab.js("__mq.x('%s')" % name)
        tab.sample([name], vis=True)
        tab.mark()
        tab.move(tab.js("__mq.away()"))
        tab.wait(1.8)
        return {"period": period, "placed": before, "order": tab.js("__mq.order('%s')" % name),
                "samples": tab.stop()[name]}
    finally:
        tab.beat(True)


def _focus(tab, name):
    tab.sample([name])
    tab.wait(0.5)
    tab.mark()
    key = tab.js("__mq.focusInside('%s')" % name)
    tab.wait(1.0)
    tab.mark()
    tab.js("document.activeElement && document.activeElement.blur(); 0")
    tab.wait(1.0)
    return {"key": key, "samples": tab.stop()[name]}


def _tab_key(tab):
    """The keyboard: Tab from the headband's collapse button reaches its
    first item, which the strip shows, and the strip holds."""
    tab.sample(["dh"])
    tab.wait(0.4)
    tab.js("document.querySelector('#dataHeadband .hb-collapse-btn').focus(); 0")
    tab.mark()
    tab.key("Tab", "Tab", 9)
    tab.wait(0.15)
    active = tab.js("__mq.activeIn('dh')")
    tab.wait(1.0)
    tab.mark()
    tab.js("document.activeElement && document.activeElement.blur(); 0")
    tab.wait(1.0)
    return {"active": active, "samples": tab.stop()["dh"]}


def _card(tab, name, sel):
    """Hover an item until its card opens, move onto the card, then away."""
    tab.beat(True)
    tab.sample([name])
    tab.wait(0.4)
    at = tab.js("__mq.inside('%s')" % name)
    tab.mark()                                   # 1: on the item, until its card opens
    tab.move((at["x"], at["y"]))
    opened = tab.js("__mq.waitCard('%s', 3000)" % sel)
    tab.wait(0.3)
    tab.mark()                                   # 2: on the card
    if opened:
        tab.move((opened["x"], opened["y"]))
    tab.wait(0.9)
    still_open = tab.js("__mq.card('%s')" % sel)
    tab.mark()                                   # 3: away, the card on its grace
    tab.js("__mq.armGone('%s', 3000, true)" % sel)   # 4: marked as the card closes
    tab.move(tab.js("__mq.away()"))
    closed = tab.js("window.__mqGone")
    tab.wait(1.0)
    return {"opened": opened, "stillOpen": still_open, "closed": closed,
            "samples": tab.stop()[name]}


def _pinned(tab):
    """A click pins the headband's card: it holds the strip with the hand
    away, until Escape closes it."""
    tab.beat(True)
    tab.sample(["dh"])
    tab.wait(0.4)
    at = tab.js("__mq.inside('dh')")
    tab.move((at["x"], at["y"]))
    tab.press((at["x"], at["y"]))
    tab.release((at["x"], at["y"]))
    pinned = tab.js("__mq.waitCard('.dh-pop', 3000)")
    tab.mark()                                   # 1: hand away, card pinned
    tab.move(tab.js("__mq.away()"))
    tab.wait(1.0)
    held = tab.js("__mq.card('.dh-pop')")
    tab.mark()                                   # 2: Escape
    tab.js("__mq.armGone('.dh-pop', 3000, false)")
    tab.key("Escape", "Escape", 27)
    closed = tab.js("window.__mqGone")
    tab.wait(1.0)
    return {"pinned": pinned, "held": held, "closed": closed, "samples": tab.stop()["dh"]}


def _refetch(tab, answers, fresh_ids):
    """Fresh news announced twice: the ticker's items are swapped under the
    driver (a headline at the front, then five more)."""
    tab.js("window.__mqAnswers = %s; 0" % json.dumps(answers))
    tab.sample(["ticker"])
    tab.wait(0.6)
    tab.mark()
    tab.js("document.dispatchEvent(new CustomEvent('sv:pin-unlocked')); 0")
    tab.wait(2.0)
    tab.mark()
    tab.js("document.dispatchEvent(new CustomEvent('sv:pin-unlocked')); 0")
    tab.wait(2.0)
    present = tab.js("(function(){ var t = document.getElementById('tickerTrack');"
                     " return %s.map(function (id) { return t.querySelectorAll("
                     "'.ticker-item[data-news-id=\"' + id + '\"]').length; }); })()" % json.dumps(fresh_ids))
    return {"present": present, "samples": tab.stop()["ticker"]}


def _changes(tab, sweep, tick):
    """The headband's left edge put past USDJPY by the wheel, then: a region
    sweep (SPX500 a figure wider), a painter tick (USDJPY a figure wider),
    two items removed, two put back. Each change is left of the edge."""
    tab.beat(False)
    try:
        xy = tab.js("__mq.point('dh')")
        tab.move(xy)
        tab.wait(0.3)
        target = tab.js("__mq.at('dh', 25)") + 10
        tab.wheel(xy, 0, target + tab.js("__mq.x('dh')"))
        tab.wait(0.2)
        tab.move(tab.js("__mq.away()"))
        before = {"spx": tab.js("__mq.text('#dhTrack .dh-item[data-symbol=\"SPX500\"] .dh-val')"),
                  "jpy": tab.js("__mq.text('#dhTrack .dh-item[data-symbol=\"USDJPY\"] .dh-val')"),
                  "P": tab.js("__mq.period('dh')")}
        tab.sample(["dh"])
        tab.wait(0.6)
        tab.mark()                                     # 1: the region sweep
        tab.js("window.__mqSweep = %s; window.svDhIngest(new DOMParser().parseFromString("
               "window.__mqSweep, 'text/html')); 0" % json.dumps(sweep))
        tab.wait(1.0)
        tab.mark()                                     # 2: the painter's tick
        tab.js("window.SVVenue.tick(%s); 0" % json.dumps(tick))
        tab.wait(1.0)
        after = {"spx": tab.js("__mq.text('#dhTrack .dh-item[data-symbol=\"SPX500\"] .dh-val')"),
                 "jpy": tab.js("__mq.text('#dhTrack .dh-item[data-symbol=\"USDJPY\"] .dh-val')"),
                 "P": tab.js("__mq.period('dh')")}
        tab.mark()                                     # 3: two items out
        tab.js("(function(){ var t = document.getElementById('dhTrack');"
               " var its = Array.prototype.filter.call(t.children, function (n) { return n.matches('.dh-item'); });"
               " var h = its.length / 2;"
               " window.__mqOut = [[its[1], its[2], its[3]], [its[h + 1], its[h + 2], its[h + 3]]];"
               " its[h + 1].remove(); its[h + 2].remove(); its[1].remove(); its[2].remove(); })(); 0")
        tab.wait(1.0)
        removed = tab.js("__mq.items('dh')")
        tab.mark()                                     # 4: put back
        tab.js("(function(){ window.__mqOut.forEach(function (o) { o[2].before(o[0], o[1]); }); })(); 0")
        tab.wait(1.0)
        return {"before": before, "after": after, "removed": removed,
                "restored": tab.js("__mq.items('dh')"), "samples": tab.stop()["dh"]}
    finally:
        tab.beat(True)


def _hidden(tab):
    tab.sample(["dh", "ticker"])
    tab.wait(0.5)
    tab.mark()
    tab.js("window.__mqHidden = true; document.dispatchEvent(new Event('visibilitychange')); 0")
    tab.wait(0.15)
    r0 = tab.js("window.__mqRaf")
    tab.wait(1.2)
    r1 = tab.js("window.__mqRaf")
    tab.mark()
    tab.js("window.__mqHidden = false; document.dispatchEvent(new Event('visibilitychange')); 0")
    tab.wait(1.0)
    return {"frames": r1 - r0, "samples": tab.stop()}


def _collapse(tab):
    tab.sample(["dh", "ticker"])
    tab.wait(0.5)
    tab.mark()
    tab.js("document.querySelector('#dataHeadband .hb-collapse-btn').click(); 0")
    tab.wait(0.15)
    w0 = tab.js("__mq.writes.dh")
    tab.wait(1.2)
    w1 = tab.js("__mq.writes.dh")
    tab.mark()
    tab.js("document.querySelector('.hb-restore-tab.data').click(); 0")
    tab.wait(1.2)
    return {"writes": w1 - w0, "samples": tab.stop()}


def _reduced(tab):
    tab.sample(["dh", "ticker"])
    r0 = tab.js("window.__mqRaf")
    tab.wait(1.2)
    r1 = tab.js("window.__mqRaf")
    tab.mark()                                     # 1: the wheel, under reduced motion
    xy = tab.js("__mq.point('dh')")
    tab.beat(False)
    tab.move(xy)
    tab.wait(0.2)
    tab.wheel(xy, 0, 120)
    tab.wait(0.4)
    tab.mark()                                     # 2: the hand leaves
    tab.move(tab.js("__mq.away()"))
    tab.wait(1.0)
    tab.mark()                                     # 3: motion allowed again
    tab.media(False)
    tab.wait(1.2)
    tab.mark()                                     # 4: reduced again
    tab.media(True)
    tab.wait(1.0)
    tab.beat(True)
    return {"framesAtRest": r1 - r0, "samples": tab.stop()}


def _touch(tab):
    tab.sample(["dh"])
    tab.wait(0.6)
    xy = tab.js("__mq.point('dh')")
    tab.mark()                                     # 1: a finger down
    tab.touch("touchStart", xy)
    tab.wait(0.8)
    tab.touch("touchMove", (xy[0] - 20, xy[1]))
    tab.touch("touchMove", (xy[0] - 40, xy[1]))
    tab.wait(0.2)
    tab.mark()                                     # 2: lifted
    tab.touch("touchEnd")
    tab.wait(TOUCH_RESUME_S + 1.6)
    return tab.stop()["dh"]


def _drag(tab, name):
    """Press, drag 150 px left, let go; a wheel notch; then away."""
    tab.beat(False)
    try:
        href = tab.js("location.href")
        xy = tab.js("__mq.point('%s')" % name)
        # Updated deliberately (the desk v2 board, approved 2026-11-13:
        # "amazing work, bravo, I need it fast!!"): the news is a lane of a
        # third of the band, so the hand starts far enough right that 150 px
        # later it is still on the strip, as it was on the full-width one.
        left = tab.js("Math.round(document.getElementById('%s').getBoundingClientRect().left)" % FRAME[name])
        xy = [max(xy[0], left + 150 + 24), xy[1]]
        tab.sample([name])
        tab.move(xy)
        tab.wait(0.4)
        tab.mark()                                     # 1: pressed and dragged
        tab.press(xy)
        for k in range(1, 6):
            tab.move((xy[0] - 30 * k, xy[1]), buttons=1)
            tab.wait(0.03)
        tab.release((xy[0] - 150, xy[1]))
        tab.mark()                                     # 2: let go, the pointer on it
        tab.wait(0.4)
        tab.mark()                                     # 3: a wheel notch after the drag
        tab.wheel((xy[0] - 150, xy[1]), 0, 100)
        tab.wait(0.4)
        tab.mark()                                     # 4: away
        tab.move(tab.js("__mq.away()"))
        tab.wait(1.0)
        samples = tab.stop()[name]
        return {"samples": samples, "pinned": tab.js("!!document.querySelector('.sv-pinned')"),
                "stayed": tab.js("location.href") == href}
    finally:
        try:
            tab.beat(True)
        except Exception:
            pass


# ── the review's scenarios (2026-11-13) ──────────────────────────────────

def _rhythm(tab):
    """Six seconds of both strips, put four times on a whole pixel first, as
    a strip starts at page load (at 0): the rhythm of their steps."""
    tab.sample(["dh", "ticker"])
    for k in range(4):
        # the mark and the move in one task: the move is the phase's first step
        tab.js("__mq.mark(); SVMarquee.to(document.getElementById('dhTrack'), -%d);"
               " SVMarquee.to(document.getElementById('tickerTrack'), -%d); 0" % (1000 + 200 * k, 1000 + 200 * k))
        tab.wait(1.5)
    return tab.stop()


def _stall(tab):
    """A long task on the page's main thread (300 ms): the strips freeze
    with it, then go on from where they froze."""
    tab.sample(["dh", "ticker"])
    tab.wait(0.6)
    tab.mark()
    tab.js("(function(){ var t = performance.now(); while (performance.now() - t < 300) {} })(); 0")
    tab.wait(0.6)
    return tab.stop()


def _shift_tab(tab, name):
    """Shift+Tab from a button right after the strip: three keyboard stops
    backwards into it."""
    tab.sample([name])
    tab.wait(0.3)
    tab.js("(function(){ var b = document.createElement('button'); b.id = 'mqAfter'; b.type = 'button';"
           " b.textContent = 'after'; b.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:99999';"
           " document.getElementById('%s').after(b); b.focus(); })(); 0" % FRAME[name])
    tab.wait(0.1)
    stops = []
    for _ in range(3):
        tab.mark()
        tab.key("Tab", "Tab", 9, modifiers=SHIFT)
        tab.wait(0.35)
        stops.append(tab.js("__mq.activeIn('%s')" % name))
    keys = tab.js("__mq.stops('%s')" % name)
    tab.mark()                                   # 4: blurred
    tab.js("document.activeElement && document.activeElement.blur();"
           " document.getElementById('mqAfter').remove(); 0")
    tab.wait(0.5)
    return {"stops": stops, "keys": keys, "items": tab.js("__mq.items('%s')" % name),
            "samples": tab.stop()[name]}


def _tab_end(tab, name):
    """Tab to the strip's last keyboard stop, from the one before it."""
    tab.sample([name])
    tab.wait(0.3)
    keys = tab.js("__mq.stops('%s')" % name)
    tab.js("(function(){ var its = Array.prototype.filter.call(document.getElementById('%s').children,"
           " function (n) { return n.matches('.dh-item, .ticker-item'); }); its[%d].focus(); })(); 0"
           % (TRACK_ID[name], keys[-2]))
    tab.wait(0.3)
    tab.mark()
    tab.key("Tab", "Tab", 9)
    tab.wait(0.35)
    last = tab.js("__mq.activeIn('%s')" % name)
    tab.js("document.activeElement && document.activeElement.blur(); 0")
    tab.wait(0.5)
    return {"keys": keys, "last": last, "samples": tab.stop()[name]}


def _watch(tab):
    """The rail's watchlist card (.dh-pop.wl-pop: the headband's look, not
    its card): hovered open, then pinned with the hand away.

    Updated deliberately (the desk v2 board, approved 2026-11-13: "amazing
    work, bravo, I need it fast!!"): the rail is a column that is either
    open, pushing the page, or not on the screen at all, so the hand opens
    it first (its Signals button in the dock does the same) and shuts it
    after."""
    tab.beat(True)
    tab.js("var r = document.getElementById('signalsRail'); if (r) r.classList.add('open'); 0")
    tab.wait(0.6)
    at = tab.js("""(function(){
      var body = document.getElementById('railWatchBody');
      if (!body) return null;
      var it = body.querySelector('.wl-item');
      if (!it) {
        body.insertAdjacentHTML('afterbegin', '<a href="#mq-watch" class="wl-item" data-symbol="MQWATCH">'
          + '<div class="wl-row1"><span class="wl-sym">MQWATCH</span></div>'
          + '<div class="dh-pop wl-pop"><div class="dh-pop-head"><div><div class="dh-pop-title">MQWATCH</div>'
          + '</div></div><div class="dh-pop-row"><span class="k">Synthetic</span><span class="v">1</span></div></div></a>');
        it = body.querySelector('.wl-item');
      }
      var b = it.getBoundingClientRect();
      if (!b.width || !b.height) return null;
      return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + Math.min(b.height / 2, 9)) };
    })()""")
    if not at:
        return {"error": "no watchlist item to hover"}
    tab.sample(["dh"])
    tab.wait(0.4)
    tab.mark()                                   # 1: on the watchlist item, its card opening
    tab.move((at["x"], at["y"]))
    opened = tab.js("__mq.waitCard('.wl-pop', 3000)")
    tab.wait(1.0)
    tab.mark()                                   # 2: pinned by a click, the hand away
    tab.press((at["x"], at["y"]))
    tab.release((at["x"], at["y"]))
    tab.move(tab.js("__mq.away()"))
    tab.wait(0.3)
    pinned = tab.js("__mq.card('.wl-pop')")
    tab.wait(0.9)
    holds = tab.js("SVMarquee.state(document.getElementById('dhTrack')).holds")
    tab.mark()                                   # 3: Escape
    tab.js("__mq.armGone('.wl-pop', 3000, false)")
    tab.key("Escape", "Escape", 27)
    closed = tab.js("window.__mqGone")
    tab.wait(0.5)
    samples = tab.stop()["dh"]
    tab.js("var r = document.getElementById('signalsRail'); if (r) r.classList.remove('open'); 0")
    tab.wait(0.3)
    return {"opened": opened, "pinned": pinned, "holds": holds, "closed": closed,
            "samples": samples}


def _fresh(tab, answer, fresh_id):
    """A fresh headline lands at the front while the strip keeps the item at
    its left edge where it was: out of view. Then the hand brings it in."""
    tab.js("window.__mqAnswers = %s; 0" % json.dumps([answer]))
    tab.js("document.dispatchEvent(new CustomEvent('sv:pin-unlocked')); 0")
    landed = False
    for _ in range(40):
        tab.wait(0.1)
        if tab.js("__mq.glow('%s').length" % fresh_id) == 2:
            landed = True
            break
    tab.wait(1.6)
    unseen = tab.js("__mq.glow('%s')" % fresh_id)
    xy = tab.js("__mq.point('ticker')")
    tab.beat(False)
    try:
        tab.move(xy)
        tab.wait(0.2)
        # the nearer copy, brought 60 px inside the clip's left edge, or
        # less where the lane is narrow: updated deliberately (the desk v2
        # board, approved 2026-11-13: "amazing work, bravo, I need it
        # fast!!"), the news lane is a third of the band, and the copy must
        # come wholly into view, clear of the collapse tab
        room = tab.js("(function(){ var f = document.getElementById('tickerBar'), c = f.getBoundingClientRect(),"
                      " b = f.querySelector('.hb-collapse-btn');"
                      " return (b && b.offsetWidth ? b.getBoundingClientRect().left : c.right) - c.left; })()")
        copies = tab.js("__mq.glow('%s')" % fresh_id)
        inset = max(4, min(60, int((room - (copies[0]["right"] - copies[0]["left"])) // 2)))
        near = min(copies, key=lambda c: abs(c["left"] - inset))
        tab.wheel(xy, 0, near["left"] - inset)
        tab.wait(0.4)
        seen = tab.js("__mq.glow('%s')" % fresh_id)
        tab.move(tab.js("__mq.away()"))
    finally:
        tab.beat(True)
    return {"landed": landed, "unseen": unseen, "seen": seen}


def _short(tab, short):
    """A ticker with too few headlines to fill its strip (one, in the desk
    v2 board's news lane): it has nothing to reveal. Then the wheel over it, and over the headband, which
    loops, with the page scrolled."""
    tab.js("window.__mqAnswers = %s; document.body.style.minHeight = '3200px';"
           " window.scrollTo(0, 400); 0" % json.dumps([short]))
    tab.js("document.dispatchEvent(new CustomEvent('sv:pin-unlocked')); 0")
    for _ in range(40):
        tab.wait(0.1)
        if tab.js("__mq.items('ticker')") == 2:
            break
    tab.wait(0.6)
    out = {"state": tab.js("SVMarquee.state(document.getElementById('tickerTrack'))"),
           "shown": tab.js("__mq.shown('ticker')"), "x": tab.js("__mq.x('ticker')")}
    tab.beat(False)
    try:
        xy = tab.js("__mq.point('ticker')")
        tab.move(xy)
        tab.wait(0.3)
        out["y0"], out["x0"] = tab.js("scrollY"), tab.js("__mq.x('ticker')")
        tab.wheel(xy, 0, 120)
        tab.wait(0.6)
        out["y1"], out["x1"] = tab.js("scrollY"), tab.js("__mq.x('ticker')")
        xy = tab.js("__mq.point('dh')")
        tab.move(xy)
        tab.wait(0.3)
        out["d0"] = tab.js("__mq.x('dh')")
        tab.wheel(xy, 0, 120)
        tab.wait(0.6)
        out["y2"], out["d1"] = tab.js("scrollY"), tab.js("__mq.x('dh')")
        tab.move(tab.js("__mq.away()"))
    finally:
        tab.beat(True)
    return out


def _shaky(tab):
    """A click on each strip's collapse button whose hand moves 6 px between
    press and release, as a hand does; then the strip put back."""
    out = {}
    for name, kind in (("dh", "data"), ("ticker", "ticker")):
        r = tab.js("(function(){ var b = document.querySelector('#%s .hb-collapse-btn').getBoundingClientRect();"
                   " return [Math.round(b.left + b.width / 2), Math.round(b.top + b.height / 2)]; })()"
                   % FRAME[name])
        tab.move((r[0] - 3, r[1]))
        tab.wait(0.1)
        tab.press((r[0] - 3, r[1]))
        tab.move((r[0] + 3, r[1]), buttons=1)
        tab.release((r[0] + 3, r[1]))
        tab.wait(0.3)
        out[name] = tab.js("document.getElementById('%s').classList.contains('collapsed')" % FRAME[name])
        tab.move(tab.js("__mq.away()"))
        tab.js("(function(){ var t = document.querySelector('.hb-restore-tab.%s');"
               " if (document.getElementById('%s').classList.contains('collapsed') && t) t.click(); })(); 0"
               % (kind, FRAME[name]))
        tab.wait(0.7)
    return out


# ── reading the samples ──────────────────────────────────────────────────

def _steps(samples):
    """Each step between two frames: its time (s) and its move (px), a step
    across the loop's seam unwrapped by the period."""
    out = []
    for a, b in zip(samples, samples[1:]):
        dx = b["x"] - a["x"]
        period = b["P"] or a["P"]
        wrapped = False
        if period and dx > period / 2:
            dx -= period
            wrapped = True
        elif period and dx < -period / 2:
            dx += period
            wrapped = True
        out.append({"dt": (b["t"] - a["t"]) / 1000.0, "dx": dx, "wrapped": wrapped,
                    "x": b["x"], "m": b["m"]})
    return out


def _speed(samples):
    """px per second, right to left positive. A step longer than the
    driver's catch-up (CATCH_UP_S: the machine stalled the page, and the
    strip goes on from where it froze) is left out: that is the machine's
    time, not the strip's speed."""
    st = [s for s in _steps(samples) if s["dt"] <= CATCH_UP_S]
    total = sum(s["dt"] for s in st)
    return sum(-s["dx"] for s in st) / total if total else 0.0


def _edge_speed(samples):
    """px per second the eye sees: the item at the clip's left edge, frame
    to frame, while it stays the same item. Where the items change under
    the strip (a refetch, a sweep, the painter, rows in or out), the
    transform jumps by design to keep that item where it was; this is the
    speed of what is shown."""
    moved = total = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = (b["t"] - a["t"]) / 1000.0
        if dt > CATCH_UP_S or not a["edge"] or not b["edge"] or a["edge"]["key"] != b["edge"]["key"]:
            continue
        moved += a["edge"]["left"] - b["edge"]["left"]
        total += dt
    return moved / total if total else 0.0


def _span(samples):
    xs = [s["x"] for s in samples]
    return max(xs) - min(xs) if xs else 0.0


def _phase(samples, m, skip=0.12):
    """The samples after mark m and before the next, the first `skip`
    seconds left out (the event's own frame)."""
    got = [s for s in samples if s["m"] == m]
    if not got:
        return []
    t0 = got[0]["t"] + skip * 1000
    return [s for s in got if s["t"] >= t0]


def _allow(speed, dt, lag=0.0):
    """The most a step between two samples may move: the speed for its
    time and for one frame more (the sampler's frame callback and the
    driver's take turns, so a sample can show the frame before), half again
    for a late frame, and a device pixel and a half for the rounding. A
    jump (a width change of one figure, a headline put in front) is more."""
    return speed * (dt + min(lag, 0.1)) * 1.5 + 1.5


def _jumps(samples, speed):
    bad, lag = [], 0.0
    for s in _steps(samples):
        if -s["dx"] > _allow(speed, s["dt"], lag) or s["dx"] > 1.0:
            bad.append({"dx": round(s["dx"], 2), "dt": round(s["dt"], 3), "x": s["x"], "m": s["m"]})
        lag = s["dt"]
    return bad


def _edge_jumps(samples, speed):
    """The item at the clip's left edge, frame to frame: it moves left at
    most as fast as the strip, never right, and gives way to another only
    once it has left the edge."""
    bad, lag = [], 0.0
    for a, b in zip(samples, samples[1:]):
        ea, eb = a["edge"], b["edge"]
        dt = (b["t"] - a["t"]) / 1000.0
        if not ea or not eb:
            bad.append({"missing": True, "m": b["m"]})
            continue
        allow = _allow(speed, dt, lag)
        lag = dt
        if ea["key"] == eb["key"]:
            d = eb["left"] - ea["left"]
            if d > 1.0 or -d > allow:
                bad.append({"key": ea["key"], "moved": round(d, 2), "dt": round(dt, 3), "m": b["m"]})
        elif ea["right"] > allow:
            bad.append({"from": ea["key"], "to": eb["key"], "right": round(ea["right"], 2), "m": b["m"]})
    return bad


def _crisp(samples, dpr):
    return [s["x"] for s in samples if abs(s["x"] * dpr - round(s["x"] * dpr)) > 1e-3]


def _rhythm_faults(samples, speed, dpr=1):
    """Windows of two to four frames, between late or early frames, whose
    device-pixel steps stray a whole pixel from the speed: a strip that
    stands two frames and then steps two, or steps once too often, the
    uneven rhythm the eye reads as a hitch. One constant distance a frame,
    rounded to device pixels, never strays that far: its steps repeat one
    pattern (news at 30 px/s and 60 Hz: 0,1,0,1; prices at 40: 1,1,0)."""
    steps = _steps(samples)
    if len(steps) < 60:
        return ["too few frames: %d" % len(steps)]
    frame = sorted(s["dt"] for s in steps)[len(steps) // 2]
    per = speed * frame * dpr
    runs, cur, m = [], [], None
    for s in steps:
        if s["m"] != m or not 0.8 * frame <= s["dt"] <= 1.25 * frame:
            runs.append(cur)
            cur, m = [], s["m"]
            continue
        cur.append(-s["dx"] * dpr)
    runs.append(cur)
    faults = []
    for run in runs:
        for k in (2, 3, 4):
            for i in range(len(run) - k + 1):
                moved = sum(run[i:i + k])
                if abs(moved - k * per) >= 0.95:
                    faults.append({"frames": k, "moved": round(moved, 2), "due": round(k * per, 2),
                                   "steps": run[max(0, i - 2):i + k + 2]})
    return faults


def _shift_by_key(a, b):
    """How far each item in view in both samples moved, matched by key: at
    the seam the loop's copy gives way to the first half, the same item for
    the eye."""
    out = {}
    for key, la in a:
        for other, lb in b:
            if key == other and (key not in out or abs(lb - la) < abs(out[key])):
                out[key] = lb - la
    return out


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheStripsMeasuredTests(TestCase):
    """The two strips of the real shell, measured frame by frame."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from django.core.cache import cache
        from django.utils import timezone

        from scraping.models import NewsArticle
        from tests.one_quote_fixture import quote
        cache.clear()
        now = timezone.now()
        user = get_user_model().objects.create_user("mq_operator", password="x", is_staff=True)
        for i, title in enumerate(TITLES):
            NewsArticle.objects.create(title=title, source="Synthetic wire",
                                       url="https://example.test/mq/%d" % i,
                                       published_at=now - timedelta(minutes=40 + i))
        quote("USDJPY", "99.998", "oanda_stream", 20, bid="99.996", ask="100.000", at=now)
        quote("SPX500", "9999.50", "yfinance", 60, at=now)
        client = Client()
        client.force_login(user)
        page = _get(client, URL)
        # Two refetches of the ticker: one fresh headline at the front, then
        # five more (13 and 18 headlines; the page has 12).
        fresh = [NewsArticle.objects.create(
            title="Synthetic wire: fresh headline one, at the front", source="Synthetic wire",
            url="https://example.test/mq/fresh-1", published_at=now)]
        first = _get(client, "/partials/ticker/")
        for i in range(5):
            fresh.append(NewsArticle.objects.create(
                title="Synthetic wire: later headline %d" % (i + 2), source="Synthetic wire",
                url="https://example.test/mq/fresh-%d" % (i + 2),
                published_at=now + timedelta(seconds=i + 1)))
        second = _get(client, "/partials/ticker/")
        # The region sweep's answer: the shell rendered again, SPX500 a
        # figure wider and newer.
        quote("SPX500", "10012.25", "yfinance", 0, at=timezone.now() + timedelta(seconds=5))
        cache.clear()
        sweep = _get(client, URL)
        tick = {"type": "quote_stream", "data": {
            "symbol": "USD_JPY", "last": 100.012, "bid": 100.010, "ask": 100.014,
            "source": "oanda_stream", "ts": (timezone.now() + timedelta(seconds=60)).isoformat()}}
        # A ticker too short to loop: one headline left. Updated deliberately
        # (the desk v2 board, approved 2026-11-13: "amazing work, bravo, I
        # need it fast!!"): the news is a lane of a third of the band, where
        # two of these headlines no longer fit; the shortest one does.
        NewsArticle.objects.exclude(title=SHORT_TITLE).delete()
        cache.clear()
        short = _get(client, "/partials/ticker/")

        tmp = tempfile.mkdtemp(prefix="sv-marquee-")
        path = pathlib.Path(tmp) / "page.html"
        path.write_text(_file(page), encoding="utf-8")
        uri = path.as_uri()
        chrome = _DeskChrome(CHROME)
        got = cls.got = {}
        try:
            tab = _Tab(chrome, uri)
            got["driver"] = tab.js("!!window.SVMarquee")
            got["items"] = {n: tab.js("__mq.items('%s')" % n) for n in ("dh", "ticker")}
            _guard(got, "run", lambda: _run(tab))
            _guard(got, "rhythm", lambda: _rhythm(tab))
            _guard(got, "ambience", lambda: _ambience(tab))
            _guard(got, "dpr2", lambda: _dpr2(tab))
            _guard(got, "cost", lambda: _cost(tab))
            _guard(got, "stall", lambda: _stall(tab))
            for name in ("dh", "ticker"):
                _guard(got, "hover/" + name, lambda: _hover(tab, name))
                _guard(got, "wheel/" + name, lambda: _wheel(tab, name))
                _guard(got, "seam/" + name, lambda: _seam(tab, name))
                _guard(got, "focus/" + name, lambda: _focus(tab, name))
            _guard(got, "tabkey", lambda: _tab_key(tab))
            for name in ("dh", "ticker"):
                _guard(got, "shifttab/" + name, lambda: _shift_tab(tab, name))
                _guard(got, "tabend/" + name, lambda: _tab_end(tab, name))
            _guard(got, "card/dh", lambda: _card(tab, "dh", ".dh-pop"))
            _guard(got, "card/ticker", lambda: _card(tab, "ticker", ".ticker-popup"))
            _guard(got, "pinned", lambda: _pinned(tab))
            _guard(got, "watch", lambda: _watch(tab))
            _guard(got, "refetch", lambda: _refetch(tab, [first, second], [str(a.id) for a in fresh]))
            _guard(got, "changes", lambda: _changes(tab, sweep, tick))
            _guard(got, "hidden", lambda: _hidden(tab))
            _guard(got, "collapse", lambda: _collapse(tab))
            _guard(got, "reduced", lambda: _reduced(_Tab(chrome, uri, reduced=True)))
            _guard(got, "touch", lambda: _touch(_Tab(chrome, uri, touch=True)))
            for name in ("dh", "ticker"):
                _guard(got, "drag/" + name, lambda: _drag(_Tab(chrome, uri), name))
            _guard(got, "fresh", lambda: _fresh(_Tab(chrome, uri), first, str(fresh[0].id)))
            _guard(got, "short", lambda: _short(_Tab(chrome, uri), short))
            _guard(got, "shaky", lambda: _shaky(_Tab(chrome, uri)))
        finally:
            chrome.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def scenario(self, name):
        got = self.got.get(name)
        self.assertIsNotNone(got, name)
        if isinstance(got, dict) and "error" in got:
            self.fail("%s: %s" % (name, got["error"]))
        return got

    def assertSpeed(self, samples, name, tol=0.15, label="", edge=False):
        self.assertGreater(len(samples), 10, label or name)
        v = _edge_speed(samples) if edge else _speed(samples)
        self.assertAlmostEqual(v, SPEED[name], delta=SPEED[name] * tol,
                               msg="%s %s: %.1f px/s" % (label, name, v))

    def assertStill(self, samples, label):
        self.assertGreater(len(samples), 5, label)
        self.assertLessEqual(_span(samples), 0.5, "%s moved: %s" % (label, sorted({s["x"] for s in samples})[:6]))

    def assertResumesFrom(self, held, resumed, name, label):
        """The first frames after a hold start from the held place, and the
        strip then runs at its speed."""
        self.assertTrue(held and resumed, label)
        last = held[-1]
        first = resumed[0]
        dt = (first["t"] - last["t"]) / 1000.0
        self.assertLessEqual(abs(first["x"] - last["x"]), _allow(SPEED[name], dt),
                             "%s: a jump from %.1f to %.1f in %.3f s" % (label, last["x"], first["x"], dt))
        self.assertEqual(_jumps(resumed, SPEED[name]), [], label)
        self.assertSpeed(resumed, name, tol=0.25, label=label)

    # ── the motion ───────────────────────────────────────────────────────

    def test_both_strips_run_right_to_left_at_their_own_constant_speed(self):
        self.assertTrue(self.got["driver"], "no driver on the page")
        run = self.scenario("run")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                self.assertSpeed(run[name], name)

    def test_the_motion_is_continuous(self):
        run = self.scenario("run")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                self.assertGreater(_span(run[name]), SPEED[name])
                self.assertEqual(_jumps(run[name], SPEED[name]), [])
                self.assertEqual(_edge_jumps(run[name], SPEED[name]), [])

    def test_the_loop_is_seamless(self):
        """Put 25 px before the end of its loop and let go: the strip crosses
        the seam once, its picture continuous (the item at the edge moves on
        at the speed and the next comes in order) and never a gap at either
        end."""
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("seam/" + name)
                samples = got["samples"]
                self.assertGreater(got["period"], 0)
                self.assertAlmostEqual(got["placed"], got["period"] - 25, delta=1.5)
                wraps = [s for s in _steps(samples) if s["wrapped"]]
                self.assertEqual(len(wraps), 1, "crossed the seam %d times" % len(wraps))
                self.assertEqual(_jumps(samples, SPEED[name]), [])
                self.assertEqual(_edge_jumps(samples, SPEED[name]), [])
                order, keys = got["order"], []
                for s in samples:
                    if not keys or keys[-1] != s["edge"]["key"]:
                        keys.append(s["edge"]["key"])
                for a, b in zip(keys, keys[1:]):
                    self.assertEqual(order.index(b), (order.index(a) + 1) % len(order), keys)
                for s in samples:
                    self.assertLessEqual(s["gapL"], 0.5)
                    self.assertLessEqual(s["gapR"], 0.5)
                # The review (2026-11-13): one loop was a fraction of a pixel
                # (6638.39 px), so across the seam the copy and the first half
                # sat at another sub-pixel phase and every glyph shifted by
                # that fraction, backwards on the news strip. Across the seam
                # every item in view moves as on any frame: by the same whole
                # device pixels, never right.
                seam = [(a, b) for a, b, st in zip(samples, samples[1:], _steps(samples)) if st["wrapped"]]
                self.assertEqual(len(seam), 1)
                a, b = seam[0]
                moved = _shift_by_key(a["vis"], b["vis"])
                self.assertGreaterEqual(len(moved), 2, (a["vis"], b["vis"]))
                for key, d in moved.items():
                    self.assertAlmostEqual(d, round(d), delta=1e-3,
                                           msg="%s moved %.4f px across the seam" % (key, d))
                    self.assertLessEqual(d, 0.0, "%s moved right across the seam" % key)
                self.assertEqual(len({round(d, 3) for d in moved.values()}), 1, moved)

    def test_the_speed_does_not_depend_on_how_many_items_the_strip_holds(self):
        """The ticker at 12, 13 and 18 headlines, the headband at 38 and 36
        instruments: the same px per second."""
        self.assertEqual(self.got["items"], {"dh": 76, "ticker": 24})
        samples = self.scenario("refetch")["samples"]
        by_n = {}
        for s in samples:
            by_n.setdefault(s["n"], []).append(s)
        self.assertEqual(sorted(by_n), [24, 26, 36])
        for n, group in sorted(by_n.items()):
            with self.subTest(ticker_items=n):
                self.assertSpeed(group[8:], "ticker", tol=0.2, label="%d items" % n)
        rows = self.scenario("changes")
        self.assertEqual(rows["removed"], 72)
        self.assertSpeed(_phase(rows["samples"], 3, skip=0.2), "dh", tol=0.25, label="36 instruments",
                         edge=True)

    def test_the_figures_stay_crisp_on_device_pixels(self):
        run, two = self.scenario("run"), self.scenario("dpr2")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name, dpr=1):
                self.assertGreater(_span(run[name]), 10)
                self.assertEqual(_crisp(run[name], 1), [])
            with self.subTest(strip=name, dpr=2):
                self.assertGreater(_span(two[name]), 10)
                self.assertEqual(_crisp(two[name], 2), [])

    def test_transform_only_no_layout_per_frame(self):
        """A second of both strips running costs no layout per frame (the
        page's own clock may lay out once or twice)."""
        cost = self.scenario("cost")
        for name in ("dh", "ticker"):
            self.assertGreater(cost["moved"][name], SPEED[name] * 0.6, cost)
        self.assertLessEqual(cost["layouts"], 3, cost)

    def test_it_runs_in_every_ambience_and_both_themes(self):
        amb = self.scenario("ambience")
        self.assertEqual(len(amb), 6)
        for key, got in sorted(amb.items()):
            for name in ("dh", "ticker"):
                with self.subTest(ambience=key, strip=name):
                    self.assertSpeed(got[name], name, tol=0.25, label=key)

    # ── still under the hand ─────────────────────────────────────────────

    def test_hover_holds_it_and_leaving_resumes_from_the_same_spot(self):
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                samples = self.scenario("hover/" + name)
                self.assertSpeed(_phase(samples, 0), name, tol=0.25, label="before")
                held = _phase(samples, 1, skip=0.1)
                self.assertStill(held, "hovered")
                self.assertEqual(held[-1]["w"] - held[0]["w"], 0, "style written while held")
                self.assertResumesFrom(held, _phase(samples, 2, skip=0.0), name, "left")

    def test_a_card_opened_from_it_holds_it_until_it_closes(self):
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("card/" + name)
                self.assertTrue(got["opened"], "no card opened")
                self.assertTrue(got["stillOpen"], "the card closed under the hand")
                self.assertTrue(got["closed"], "the card stayed")
                samples = got["samples"]
                self.assertStill(_phase(samples, 1, skip=0.1), "on the item")
                on_card = _phase(samples, 2, skip=0.1)
                self.assertStill(on_card, "on its card")
                # the hand gone, the card still open on its grace: still
                grace = _phase(samples, 3, skip=0.0)
                self.assertLessEqual(_span(on_card + grace), 0.5, "moved under an open card")
                self.assertResumesFrom(on_card + grace, _phase(samples, 4, skip=0.0), name, "card closed")

    def test_a_pinned_card_holds_it_with_the_hand_away(self):
        got = self.scenario("pinned")
        self.assertTrue(got["pinned"] and got["pinned"]["pinned"], got["pinned"])
        self.assertTrue(got["held"], "the pinned card closed when the hand left")
        self.assertTrue(got["closed"], "Escape left the card open")
        held = _phase(got["samples"], 1, skip=0.1)
        self.assertStill(held, "pinned, hand away")
        self.assertResumesFrom(held, _phase(got["samples"], 2, skip=0.1), "dh", "Escape")

    def test_focus_inside_holds_it(self):
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("focus/" + name)
                self.assertTrue(got["key"])
                held = _phase(got["samples"], 1, skip=0.1)
                self.assertStill(held, "focused")
                self.assertResumesFrom(held, _phase(got["samples"], 2, skip=0.0), name, "blurred")

    def test_the_keyboard_reaches_an_item_the_strip_shows_and_holds(self):
        got = self.scenario("tabkey")
        self.assertTrue(got["active"], "Tab did not reach the headband's first item")
        self.assertTrue(got["active"]["inClip"], got["active"])
        held = _phase(got["samples"], 1, skip=0.2)
        self.assertStill(held, "keyboard focus")
        self.assertResumesFrom(held, _phase(got["samples"], 2, skip=0.0), "dh", "blurred")

    def test_a_finger_down_holds_it_and_it_resumes_seconds_after(self):
        samples = self.scenario("touch")
        self.assertSpeed(_phase(samples, 0), "dh", tol=0.25, label="before the finger")
        self.assertStill(_phase(samples, 1, skip=0.1), "finger down")
        lifted = _phase(samples, 2, skip=0.0)
        t0 = lifted[0]["t"]
        soon = [s for s in lifted if s["t"] - t0 < (TOUCH_RESUME_S - 0.8) * 1000]
        self.assertStill(soon, "just lifted")
        later = [s for s in lifted if s["t"] - t0 > (TOUCH_RESUME_S + 0.4) * 1000]
        self.assertResumesFrom(soon, later, "dh", "seconds after the finger")

    # ── the hand moves the one position ──────────────────────────────────

    def test_the_wheel_moves_it_and_the_scroll_goes_on_from_there(self):
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                samples = self.scenario("wheel/" + name)
                rest, down, side = (_phase(samples, m, skip=0.1) for m in (0, 1, 2))
                self.assertStill(rest, "pointer on it")
                self.assertStill(down, "after a notch")
                self.assertStill(side, "after a swipe")
                self.assertAlmostEqual(down[0]["x"] - rest[-1]["x"], -120, delta=1.01)
                self.assertAlmostEqual(side[0]["x"] - down[-1]["x"], 80, delta=1.01)
                self.assertResumesFrom(side, _phase(samples, 3, skip=0.0), name, "after the wheel")

    def test_the_drag_moves_it_and_the_scroll_goes_on_from_there(self):
        """A drag of 150 px moves the strip 150 px; a wheel notch after it
        starts from where the drag left it (one position); leaving, the
        scroll goes on from there. The drag opens no card and follows no
        link."""
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("drag/" + name)
                samples = got["samples"]
                self.assertTrue(got["stayed"], "the drag followed the item's link")
                self.assertFalse(got["pinned"], "the drag pinned a card")
                rest = _phase(samples, 0, skip=0.1)
                dragged = _phase(samples, 2, skip=0.1)
                notch = _phase(samples, 3, skip=0.1)
                self.assertStill(rest, "pointer on it")
                self.assertStill(dragged, "let go, pointer on it")
                self.assertAlmostEqual(dragged[0]["x"] - rest[-1]["x"], -150, delta=2)
                self.assertAlmostEqual(notch[0]["x"] - dragged[-1]["x"], -100, delta=1.01)
                self.assertResumesFrom(notch, _phase(samples, 4, skip=0.0), name, "after the drag")

    # ── never a jump on a refresh ────────────────────────────────────────

    def test_no_jump_across_a_news_refetch(self):
        got = self.scenario("refetch")
        self.assertEqual(got["present"], [2] * 6, "the refetches did not land")
        samples = got["samples"]
        self.assertEqual(_edge_jumps(samples, SPEED["ticker"]), [])
        self.assertSpeed(samples[-40:], "ticker", tol=0.25, label="after the refetches", edge=True)

    def test_no_jump_across_a_sweep_a_painter_update_or_items_added_or_removed(self):
        got = self.scenario("changes")
        b, a = got["before"], got["after"]
        self.assertNotEqual(a["spx"], b["spx"], "the sweep painted nothing")
        self.assertNotEqual(a["jpy"], b["jpy"], "the painter painted nothing")
        self.assertGreater(a["P"], b["P"] + 4, "no width changed: nothing tested")
        self.assertEqual((got["removed"], got["restored"]), (72, 76))
        samples = got["samples"]
        self.assertEqual(_edge_jumps(samples, SPEED["dh"]), [])
        for m in range(5):
            with self.subTest(phase=m):
                self.assertSpeed(_phase(samples, m, skip=0.15), "dh", tol=0.3, label="phase %d" % m,
                                 edge=True)

    # ── still when nobody can see it, or nobody wants it ─────────────────

    def test_reduced_motion_stands_still_and_the_hand_still_moves_it(self):
        got = self.scenario("reduced")
        self.assertEqual(got["framesAtRest"], 0, "frames asked for under reduced motion")
        dh, ticker = got["samples"]["dh"], got["samples"]["ticker"]
        self.assertStill(_phase(dh, 0), "reduced")
        self.assertStill(_phase(ticker, 0), "reduced")
        wheeled = _phase(dh, 1, skip=0.3)
        self.assertAlmostEqual(wheeled[0]["x"] - _phase(dh, 0)[-1]["x"], -120, delta=1.01)
        left = _phase(dh, 2, skip=0.1)
        self.assertStill(left, "reduced, hand away")
        self.assertAlmostEqual(left[0]["x"], wheeled[-1]["x"], delta=0.5)
        self.assertResumesFrom(left, _phase(dh, 3, skip=0.1), "dh", "motion allowed again")
        self.assertStill(_phase(dh, 4, skip=0.2), "reduced again")

    def test_a_hidden_tab_holds_it_asks_no_frame_and_resumes_in_place(self):
        got = self.scenario("hidden")
        self.assertEqual(got["frames"], 0, "frames asked for in a hidden tab")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                samples = got["samples"][name]
                self.assertSpeed(_phase(samples, 0), name, tol=0.25, label="visible")
                held = _phase(samples, 1, skip=0.1)
                self.assertStill(held, "hidden")
                self.assertResumesFrom(held, _phase(samples, 2, skip=0.0), name, "visible again")

    def test_a_collapsed_strip_does_not_run_and_comes_back_in_place(self):
        got = self.scenario("collapse")
        self.assertEqual(got["writes"], 0, "the collapsed strip was written")
        dh, ticker = got["samples"]["dh"], got["samples"]["ticker"]
        held = _phase(dh, 1, skip=0.1)
        self.assertTrue(all(s["collapsed"] for s in held))
        self.assertStill(held, "collapsed")
        self.assertSpeed(_phase(ticker, 1, skip=0.1), "ticker", tol=0.25, label="the other strip")
        self.assertResumesFrom(held, _phase(dh, 2, skip=0.0), "dh", "restored")

    # ── the review of the first build (2026-11-13) ───────────────────────

    def test_one_loop_is_a_whole_number_of_device_pixels(self):
        """The copy of the items starts a whole number of device pixels
        after the first half (the driver pads the gap between the halves by
        the fraction), so the picture at a position and one loop further is
        the same one, glyph for glyph: at 1x and at 2x."""
        for dpr, got in ((1, self.scenario("run")), (2, self.scenario("dpr2"))):
            for name in ("dh", "ticker"):
                with self.subTest(strip=name, dpr=dpr):
                    loops = sorted({s["P"] for s in got[name] if s["P"]})
                    self.assertTrue(loops)
                    for p in loops:
                        self.assertAlmostEqual(p * dpr, round(p * dpr), delta=1e-3,
                                               msg="one loop of %r px at %dx" % (p, dpr))

    def test_its_steps_keep_one_even_rhythm(self):
        """Each frame moves a strip the same distance (its speed over the
        display's frame interval, whole frames): the device-pixel steps keep
        one pattern instead of following the jitter of the frame clock
        (news at 30 px/s is half a pixel a frame at 60 Hz: on e4e8a2d it
        stood two frames and stepped two about twice a second)."""
        got = self.scenario("rhythm")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                self.assertEqual(_rhythm_faults(got[name], SPEED[name]), [])
                for m in range(1, 5):
                    self.assertSpeed(_phase(got[name], m, skip=0.05), name, label="phase %d" % m)

    def test_a_long_task_freezes_it_and_it_goes_on_without_a_skip(self):
        """A 300 ms task on the main thread freezes a strip moved by script;
        after it the strip catches up one frame at most (CATCH_UP_S), it
        does not leap the 12 px the task took (e4e8a2d: up to 10 px)."""
        got = self.scenario("stall")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                samples = got[name]
                st = _steps(samples)
                at = max(range(len(st)), key=lambda i: st[i]["dt"])
                self.assertGreaterEqual(st[at]["dt"], 0.25, "no stall seen")
                # The frame that ends the stall can carry a stale clock, and
                # the catch-up lands a frame or two after it: the stall's
                # step and every step in the 60 ms after it.
                after, spent = [st[at]], 0.0
                for s in st[at + 1:]:
                    if spent + s["dt"] > 0.06:
                        break
                    after.append(s)
                    spent += s["dt"]
                moved = -sum(s["dx"] for s in after)
                most = SPEED[name] * (CATCH_UP_S + 1 / 60.0 + spent) + 1.01
                self.assertLessEqual(moved, most, [(round(s["dt"], 3), s["dx"]) for s in after])
                self.assertGreaterEqual(moved, 0.0, after)
                self.assertSpeed(samples[at + 6:], name, tol=0.25, label="after the stall")

    def test_shift_tab_into_a_strip_shows_each_stop_clear_of_its_tab(self):
        """Shift+Tab from the element after a strip enters it from its end:
        each stop is shown inside the clip and clear of the collapse tab,
        the strip moving no more than an item between two keys. On e4e8a2d
        the focus went to the loop's copy, off screen, and each key threw
        the strip thousands of pixels: the clip's scroll was wrapped."""
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("shifttab/" + name)
                stops = got["stops"]
                for i, stop in enumerate(stops):
                    self.assertTrue(stop, "Shift+Tab %d did not land in the strip" % (i + 1))
                    self.assertTrue(stop["clear"], "stop %d not shown: %r" % (i + 1, stop))
                    self.assertEqual(stop["copy"], 0, "the keyboard reached the loop's copy: %r" % stop)
                self.assertEqual([s["index"] for s in stops],
                                 [got["keys"][-1], got["keys"][-2], got["keys"][-3]])
                for a, b in zip(stops, stops[1:]):
                    self.assertLessEqual(abs(b["x"] - a["x"]), 600, stops)
                held = _phase(got["samples"], 3, skip=0.15)
                self.assertStill(held, "focus on the third stop")

    def test_the_keyboard_stops_once_on_each_item(self):
        """The loop's copy is there for the eye: out of the tab order (and
        hidden from screen readers, below), so the keyboard stops on each
        item once, never on a twin a loop away."""
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("shifttab/" + name)
                self.assertEqual(got["keys"], list(range(got["items"] // 2)))

    def test_tab_to_a_strip_s_last_stop_shows_it_clear_of_its_tab(self):
        """The last stop is shown whole, not under the collapse tab (e4e8a2d:
        38 px of it sat under the tab, the copy's end against the clip's)."""
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                got = self.scenario("tabend/" + name)
                last = got["last"]
                self.assertTrue(last, "Tab left the strip")
                self.assertEqual(last["index"], got["keys"][-1], last)
                self.assertTrue(last["clear"], last)

    def test_a_watchlist_card_does_not_hold_the_headband(self):
        """The rail's watchlist cards wear the headband's card class (.dh-pop
        .wl-pop): open on hover, or pinned with the hand away, they are not
        a card opened from the headband, which runs on (e4e8a2d: held)."""
        got = self.scenario("watch")
        self.assertTrue(got["opened"], "no watchlist card opened")
        self.assertTrue(got["pinned"] and got["pinned"]["pinned"], got["pinned"])
        self.assertNotIn("popup", got["holds"])
        self.assertTrue(got["closed"], "Escape left the watchlist card open")
        samples = got["samples"]
        self.assertSpeed(_phase(samples, 1, skip=0.6), "dh", tol=0.25, label="watchlist card open")
        self.assertSpeed(_phase(samples, 2, skip=0.4), "dh", tol=0.25, label="watchlist card pinned")

    def test_a_fresh_headline_glows_when_the_eye_first_sees_it(self):
        """A refetch keeps the item at the left edge where it was, so the
        fresh headline at the front lands out of view: its 6 s glow waits
        until a copy of it comes into view, and starts there (e4e8a2d: it
        played out of view and was over when the headline rode in)."""
        got = self.scenario("fresh")
        self.assertTrue(got["landed"], "the refetch did not land")
        self.assertEqual(len(got["unseen"]), 2)
        for c in got["unseen"]:
            self.assertFalse(c["any"], "the fresh headline landed in view: %r" % c)
            self.assertFalse(c["glowing"], "it glowed out of view: %r" % c)
        # the hand's wheel may wrap the loop: whichever copy came into view
        seen = [c for c in got["seen"] if c["whole"]]
        self.assertEqual(len(seen), 1, got["seen"])
        first = seen[0]
        self.assertTrue(first["glowing"], "in view, no glow: %r" % first)
        self.assertLess(first["since"], 1500, first)
        self.assertNotIn(first["bg"], ("rgba(0, 0, 0, 0)", "transparent"), first)
        other = [c for c in got["seen"] if not c["whole"]][0]
        self.assertFalse(other["glowing"], "the copy out of view glowed too: %r" % other)

    def test_a_short_ticker_shows_each_headline_once_and_the_page_has_the_wheel(self):
        """A headline that fits in the strip: nothing to reveal, so it stands
        at its start and shows each headline once (e4e8a2d showed the loop's
        copy beside them). Updated deliberately (the desk v2 board, approved
        2026-11-13: "amazing work, bravo, I need it fast!!"): the news is a
        lane of a third of the band, so the short ticker holds one headline,
        not two; the copy is still there and still hidden. With nothing to reveal it is an end, and the wheel
        goes to the page. A strip that loops has no end (2026-11-13, the
        operator's decision that they scroll continuously): over the
        headband the wheel moves the strip, as the hand asks."""
        got = self.scenario("short")
        self.assertFalse(got["state"]["loop"])
        self.assertEqual(got["x"], 0)
        shown = got["shown"]
        self.assertEqual(len(shown), 2)
        self.assertEqual(sorted(k for k, copy, painted in shown if painted),
                         sorted({k for k, copy, painted in shown}), shown)
        self.assertGreater(got["y1"], got["y0"], "the wheel did not reach the page")
        self.assertEqual(got["x1"], got["x0"])
        self.assertEqual(got["y2"], got["y1"], "the wheel over the looping headband moved the page")
        self.assertAlmostEqual(got["d1"] - got["d0"], -120, delta=1.01)

    def test_a_collapse_click_that_moves_a_few_pixels_still_collapses(self):
        """The drag takes no press on a collapse button: a click whose hand
        moved 6 px collapses the strip, as on 349b1ca (e4e8a2d swallowed it
        as a drag)."""
        got = self.scenario("shaky")
        for name in ("dh", "ticker"):
            with self.subTest(strip=name):
                self.assertTrue(got[name], "the collapse button did not collapse the strip")


class TheLoopsCopyIsForTheEyeTests(TestCase):
    """The second copy of each strip's items is what makes the loop seamless:
    it is there for the eye. Out of the tab order and hidden from screen
    readers (2026-11-13, the review), so the keyboard and the reader take
    each item once; the hand still hovers and clicks it."""

    def setUp(self):
        user = get_user_model().objects.create_user("mq_copy", password="x", is_staff=True)
        self.client.force_login(user)

    @staticmethod
    def anchors_of(html, cls):
        # Not "tags": Django reads `tags` on every test when a run filters
        # by tag (the CI's --exclude-tag), and a method by that name stops
        # the whole run before its first test (tests/test_ci_tags.py).
        return re.findall(r'<a\b[^>]*\bclass="%s"[^>]*>' % cls, html)

    def assertCopy(self, tags):
        self.assertGreaterEqual(len(tags), 2)
        self.assertEqual(len(tags) % 2, 0)
        half = len(tags) // 2
        for tag in tags[:half]:
            self.assertNotIn("aria-hidden", tag)
            self.assertNotIn("tabindex", tag)
        for tag in tags[half:]:
            self.assertIn('aria-hidden="true"', tag)
            self.assertIn('tabindex="-1"', tag)

    def test_the_ticker_s_copy(self):
        from django.utils import timezone

        from scraping.models import NewsArticle
        for i in range(2):
            NewsArticle.objects.create(title="Synthetic wire: copy %d" % i, source="Synthetic wire",
                                       url="https://example.test/mq-copy/%d" % i,
                                       published_at=timezone.now() - timedelta(minutes=i + 1))
        html = _get(self.client, "/partials/ticker/")
        tags = self.anchors_of(html, "ticker-item")
        self.assertEqual(len(tags), 4)
        self.assertCopy(tags)

    def test_the_headband_s_copy(self):
        page = _get(self.client, URL)
        track = page[page.index('id="dhTrack"'):]
        track = track[:track.index('<!-- Restore tabs')]
        self.assertCopy(self.anchors_of(track, "dh-item"))
