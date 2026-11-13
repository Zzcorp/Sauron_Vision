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
#: a few seconds after a finger lifts
TOUCH_RESUME_S = 3.0


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
  function snap(name) {
    var p = parts(name), c = p.c.getBoundingClientRect(), r = p.t.getBoundingClientRect();
    var its = items(p.t), seen = {}, edge = null;
    for (var i = 0; i < its.length; i++) {
      var k = keyOf(its[i]);
      seen[k] = (seen[k] || 0) + 1;
      var b = its[i].getBoundingClientRect();
      if (b.right > c.left + 0.5) {
        edge = { key: k, copy: seen[k] - 1, left: b.left - c.left, right: b.right - c.left };
        break;
      }
    }
    return { t: performance.now(), x: tx(p.t), P: period(p.t), n: its.length,
             gapL: r.left - c.left, gapR: c.right - r.right, edge: edge,
             scroll: p.c.scrollLeft, w: writes[name], m: marks.length,
             collapsed: p.f.classList.contains('collapsed') };
  }
  var rec = null;
  function start(names) {
    marks = [];
    var me = { names: names, out: {} };
    names.forEach(function (n) { me.out[n] = []; });
    rec = me;
    (function loop() {
      if (rec !== me) return;
      me.names.forEach(function (n) { me.out[n].push(snap(n)); });
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
  /* An item wholly inside the clip, clear of the collapse tab. */
  function inside(name) {
    var p = parts(name), c = p.c.getBoundingClientRect(), its = items(p.t);
    for (var i = 0; i < its.length; i++) {
      var b = its[i].getBoundingClientRect();
      if (b.left > c.left + 40 && b.right < c.right - 120) {
        return { i: i, key: keyOf(its[i]), x: Math.round((b.left + b.right) / 2),
                 y: Math.round((b.top + b.bottom) / 2) };
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
  function away() { return [Math.round(innerWidth * 0.45), Math.round(innerHeight * 0.7)]; }
  /* Where item k starts, from the first item, in px of the track. */
  function at(name, k) {
    var its = items(parts(name).t);
    return its[k].getBoundingClientRect().left - its[0].getBoundingClientRect().left;
  }
  function x(name) { return tx(parts(name).t); }
  function activeIn(name) {
    var p = parts(name), a = document.activeElement;
    if (!a || !p.t.contains(a)) return null;
    var c = p.c.getBoundingClientRect(), b = a.getBoundingClientRect();
    return { key: keyOf(a), inClip: b.left >= c.left - 0.5 && b.right <= c.right + 0.5 };
  }
  function text(sel) {
    return Array.prototype.map.call(document.querySelectorAll(sel), function (e) { return e.textContent.trim(); });
  }
  return { start: start, stop: stop, mark: mark, point: point, inside: inside, card: card,
           away: away, at: at, x: x, items: function (n) { return items(parts(n).t).length; },
           period: function (n) { return period(parts(n).t); }, focusInside: focusInside,
           activeIn: activeIn, text: text, writes: writes,
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

    def key(self, key, code, vk):
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code,
                                                 "windowsVirtualKeyCode": vk,
                                                 "nativeVirtualKeyCode": vk})

    def touch(self, kind, xy=None):
        pts = [{"x": xy[0], "y": xy[1]}] if xy else []
        self.call("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

    def sample(self, names):
        self.js("__mq.start(%s)" % json.dumps(list(names)))

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
        tab.sample([name])
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
    tab.mark()                                   # 1: on the item
    tab.move((at["x"], at["y"]))
    tab.wait(0.9)
    opened = tab.js("__mq.card('%s')" % sel)
    tab.mark()                                   # 2: on the card
    if opened:
        tab.move((opened["x"], opened["y"]))
    tab.wait(0.9)
    still_open = tab.js("__mq.card('%s')" % sel)
    tab.mark()                                   # 3: away
    tab.move(tab.js("__mq.away()"))
    tab.wait(1.4)
    closed = tab.js("__mq.card('%s')" % sel) is None
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
    tab.wait(0.2)
    pinned = tab.js("__mq.card('.dh-pop')")
    tab.mark()                                   # 1: hand away, card pinned
    tab.move(tab.js("__mq.away()"))
    tab.wait(1.0)
    held = tab.js("__mq.card('.dh-pop')")
    tab.mark()                                   # 2: Escape
    tab.key("Escape", "Escape", 27)
    tab.wait(1.0)
    closed = tab.js("__mq.card('.dh-pop')") is None
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
    """px per second, right to left positive."""
    st = _steps(samples)
    total = sum(s["dt"] for s in st)
    return sum(-s["dx"] for s in st) / total if total else 0.0


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
            _guard(got, "ambience", lambda: _ambience(tab))
            _guard(got, "dpr2", lambda: _dpr2(tab))
            _guard(got, "cost", lambda: _cost(tab))
            for name in ("dh", "ticker"):
                _guard(got, "hover/" + name, lambda: _hover(tab, name))
                _guard(got, "wheel/" + name, lambda: _wheel(tab, name))
                _guard(got, "seam/" + name, lambda: _seam(tab, name))
                _guard(got, "focus/" + name, lambda: _focus(tab, name))
            _guard(got, "tabkey", lambda: _tab_key(tab))
            _guard(got, "card/dh", lambda: _card(tab, "dh", ".dh-pop"))
            _guard(got, "card/ticker", lambda: _card(tab, "ticker", ".ticker-popup"))
            _guard(got, "pinned", lambda: _pinned(tab))
            _guard(got, "refetch", lambda: _refetch(tab, [first, second], [str(a.id) for a in fresh]))
            _guard(got, "changes", lambda: _changes(tab, sweep, tick))
            _guard(got, "hidden", lambda: _hidden(tab))
            _guard(got, "collapse", lambda: _collapse(tab))
            _guard(got, "reduced", lambda: _reduced(_Tab(chrome, uri, reduced=True)))
            _guard(got, "touch", lambda: _touch(_Tab(chrome, uri, touch=True)))
            for name in ("dh", "ticker"):
                _guard(got, "drag/" + name, lambda: _drag(_Tab(chrome, uri), name))
        finally:
            chrome.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def scenario(self, name):
        got = self.got.get(name)
        self.assertIsNotNone(got, name)
        if isinstance(got, dict) and "error" in got:
            self.fail("%s: %s" % (name, got["error"]))
        return got

    def assertSpeed(self, samples, name, tol=0.15, label=""):
        self.assertGreater(len(samples), 10, label or name)
        v = _speed(samples)
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
        self.assertSpeed(_phase(rows["samples"], 3, skip=0.2), "dh", tol=0.25, label="36 instruments")

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
                after = _phase(samples, 3, skip=0.0)
                # the card closes on its own grace after the hand leaves it
                moving = [s for s in after if s["t"] - after[0]["t"] > 450]
                self.assertResumesFrom(on_card, moving, name, "card closed")

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
        self.assertSpeed(samples[-40:], "ticker", tol=0.25, label="after the refetches")

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
                self.assertSpeed(_phase(samples, m, skip=0.15), "dh", tol=0.3, label="phase %d" % m)

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
